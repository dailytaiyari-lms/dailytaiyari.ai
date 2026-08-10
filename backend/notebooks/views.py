"""Student-facing notebook endpoints: list, open, autosave a draft, submit."""
import logging

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from users.models import CourseEnrollment

from . import services
from .models import (
    Notebook, NotebookCompletion, NotebookDraft, NotebookSubmission,
)
from .nbformat_utils import NotebookFormatError, merge_student_notebook, normalize_notebook
from .serializers import (
    NotebookDetailSerializer, NotebookListSerializer, MySubmissionSummarySerializer,
    SubmissionResultSerializer,
)

logger = logging.getLogger(__name__)

UUID_RE = r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'


class NotebookViewSet(viewsets.ReadOnlyModelViewSet):
    """Published notebooks for the student's approved-enrolled courses."""
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        return NotebookDetailSerializer if self.action == 'retrieve' else NotebookListSerializer

    def get_throttles(self):
        if self.action == 'submit':
            self.throttle_scope = 'notebook_submit'
            return [ScopedRateThrottle()]
        # Autosave fires on a debounce and polling runs while a submission
        # grades; both are cheap owner-scoped writes/reads that must not eat the
        # shared 'user' bucket.
        if self.action in ('draft', 'submission_status'):
            return []
        return super().get_throttles()

    def _student(self):
        return getattr(self.request.user, 'profile', None)

    def _enrolled_course_ids(self):
        student = self._student()
        if not student:
            return []
        return list(CourseEnrollment.objects.filter(
            student=student, status='approved', is_active=True,
        ).values_list('course_id', flat=True))

    def get_queryset(self):
        qs = Notebook.objects.select_related('topic', 'subject').prefetch_related(
            'tests', 'datasets',
        ).filter(status='published', course_id__in=self._enrolled_course_ids())
        topic_id = self.request.query_params.get('topic')
        if topic_id:
            qs = qs.filter(topic_id=topic_id)
        course_id = self.request.query_params.get('course')
        if course_id:
            qs = qs.filter(course_id=course_id)
        return qs.order_by('order', '-created_at')

    def _attach_state(self, notebooks, *, with_draft=False):
        """Attach each student's attempts, best submission and completion."""
        student = self._student()
        for nb in notebooks:
            nb._my_best = None
            nb._my_completion = None
            nb._my_submissions = []
            nb._attempts_used = 0
            nb._my_draft = None
        if not student or not notebooks:
            return

        subs = NotebookSubmission.objects.filter(
            student=student, notebook__in=notebooks,
        ).order_by('notebook_id', '-attempt_number')
        by_notebook = {}
        for s in subs:
            by_notebook.setdefault(s.notebook_id, []).append(s)

        completions = {
            c.notebook_id: c
            for c in NotebookCompletion.objects.filter(student=student, notebook__in=notebooks)
        }

        drafts = {}
        if with_draft:
            drafts = {
                d.notebook_id: d
                for d in NotebookDraft.objects.filter(student=student, notebook__in=notebooks)
            }

        for nb in notebooks:
            mine = by_notebook.get(nb.id, [])
            nb._my_submissions = mine
            # Errored attempts (engine failures) don't count against the limit.
            nb._attempts_used = sum(
                1 for s in mine if s.status != NotebookSubmission.STATUS_ERROR
            )
            graded = [s for s in mine if s.status == NotebookSubmission.STATUS_GRADED]
            if graded:
                nb._my_best = max(graded, key=lambda s: (s.passed_points, s.submitted_at))
            elif mine:
                nb._my_best = mine[0]
            nb._my_completion = completions.get(nb.id)
            nb._my_draft = drafts.get(nb.id)

    def list(self, request, *args, **kwargs):
        notebooks = list(self.get_queryset())
        self._attach_state(notebooks)
        return Response(self.get_serializer(notebooks, many=True).data)

    def retrieve(self, request, *args, **kwargs):
        notebook = self.get_object()
        self._attach_state([notebook], with_draft=True)
        return Response(self.get_serializer(notebook).data)

    @action(detail=True, methods=['get', 'put', 'delete'])
    def draft(self, request, pk=None):
        """Read, autosave or reset the student's working copy.

        DELETE resets the working copy back to the notebook's template, which
        is what the "Reset notebook" button does.
        """
        notebook = self.get_object()
        student = self._student()
        if not student:
            return Response({'error': 'Student profile required.'}, status=400)

        if request.method == 'GET':
            draft = NotebookDraft.objects.filter(notebook=notebook, student=student).first()
            return Response({
                'notebook_json': draft.notebook_json if draft else notebook.template_json,
                'saved_at': draft.updated_at if draft else None,
                'time_spent_seconds': draft.time_spent_seconds if draft else 0,
            })

        if request.method == 'DELETE':
            NotebookDraft.objects.filter(notebook=notebook, student=student).delete()
            return Response({
                'notebook_json': notebook.template_json, 'saved_at': None,
                'time_spent_seconds': 0,
            })

        try:
            document = normalize_notebook(request.data.get('notebook_json'))
        except NotebookFormatError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        try:
            time_spent = max(int(request.data.get('time_spent_seconds') or 0), 0)
        except (TypeError, ValueError):
            time_spent = 0

        draft, _ = NotebookDraft.objects.update_or_create(
            notebook=notebook, student=student,
            defaults={'notebook_json': document, 'tenant': notebook.tenant},
        )
        # Time is cumulative and reported as a delta by the client.
        if time_spent:
            NotebookDraft.objects.filter(pk=draft.pk).update(
                time_spent_seconds=draft.time_spent_seconds + time_spent,
            )
        return Response({'saved_at': draft.updated_at})

    @action(detail=True, methods=['post'])
    def submit(self, request, pk=None):
        """Submit the notebook for grading.

        The submitted document is merged against the template so locked setup
        cells can't be tampered with, then queued for authoritative grading in
        the sandboxed server-side runner. The browser's provisional score is
        stored for display but never becomes the grade.
        """
        notebook = self.get_object()
        student = self._student()
        if not student:
            return Response({'error': 'Student profile required.'}, status=400)

        if notebook.status != 'published':
            return Response({'error': 'This notebook is not available.'},
                            status=status.HTTP_403_FORBIDDEN)
        if notebook.is_past_due:
            return Response({'error': 'The due date for this notebook has passed.'},
                            status=status.HTTP_403_FORBIDDEN)

        try:
            document = normalize_notebook(request.data.get('notebook_json'))
        except NotebookFormatError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        merged = merge_student_notebook(notebook.template_json, document)

        # Claim the next attempt atomically so double-clicks and concurrent tabs
        # can't consume two attempts or race past the limit. Attempts that
        # failed with an engine error don't count against the student's limit
        # (that's our fault, not theirs) but still occupy an attempt_number.
        try:
            with transaction.atomic():
                existing = list(NotebookSubmission.objects.select_for_update().filter(
                    notebook=notebook, student=student,
                ).values_list('attempt_number', 'status'))
                used = sum(
                    1 for _, st in existing if st != NotebookSubmission.STATUS_ERROR
                )
                remaining = notebook.attempts_remaining(used)
                if remaining is not None and remaining <= 0:
                    return Response(
                        {'error': 'You have used all your attempts for this notebook.'},
                        status=status.HTTP_403_FORBIDDEN,
                    )
                next_number = max((n for n, _ in existing), default=0) + 1
                submission = NotebookSubmission.objects.create(
                    tenant=notebook.tenant,
                    notebook=notebook, student=student,
                    attempt_number=next_number,
                    notebook_json=merged,
                    status=NotebookSubmission.STATUS_QUEUED,
                    is_late=notebook.is_past_due,
                )
        except IntegrityError:
            return Response(
                {'error': 'That submission was already recorded. Reload to see your result.'},
                status=status.HTTP_409_CONFLICT,
            )

        from . import grading
        grading.apply_provisional(submission, request.data.get('provisional_results'))

        if not services.is_enabled():
            # Server-side grading disabled: the browser's provisional score is
            # all we have, so promote it to the recorded result. Still runs
            # through finalize_* semantics for completion/XP.
            return self._grade_from_provisional(submission)

        if getattr(settings, 'NOTEBOOKS_JUDGE_ASYNC', True):
            try:
                from .tasks import grade_notebook_submission
                grade_notebook_submission.delay(str(submission.id))
            except Exception as exc:  # broker down -> never block the student
                logger.warning('Async enqueue failed (%s); grading synchronously.', exc)
                return self._grade_sync(submission)
            return Response(
                SubmissionResultSerializer(submission).data,
                status=status.HTTP_202_ACCEPTED,
            )

        return self._grade_sync(submission)

    def _grade_sync(self, submission):
        from . import grading
        try:
            xp_awarded = grading.finalize_submission(submission)
        except services.EngineError as exc:
            # The attempt is kept (status='error') so the student sees what
            # happened; error attempts don't consume the limit (see below).
            data = SubmissionResultSerializer(submission).data
            data['error'] = str(exc)
            return Response(data, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        data = SubmissionResultSerializer(submission).data
        data['xp_awarded'] = xp_awarded
        return Response(data, status=status.HTTP_201_CREATED)

    def _grade_from_provisional(self, submission):
        """Record the browser's score as the result (server grading disabled)."""
        from django.utils import timezone
        from . import grading

        results = submission.provisional_results or []
        submission.status = NotebookSubmission.STATUS_GRADED
        submission.results = results
        submission.passed_count = sum(1 for r in results if r.get('passed'))
        submission.total_count = len(results)
        submission.passed_points = submission.provisional_passed_points
        submission.total_points = submission.provisional_total_points
        submission.marks = grading._marks_for(
            submission.notebook, submission.passed_points, submission.total_points,
        )
        submission.graded_at = timezone.now()
        submission.save()
        xp_awarded = grading.refresh_completion(submission)
        data = SubmissionResultSerializer(submission).data
        data['xp_awarded'] = xp_awarded
        return Response(data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'], url_path=rf'submissions/(?P<sub_id>{UUID_RE})')
    def submission_status(self, request, pk=None, sub_id=None):
        """Poll a single submission's status/result (owner-scoped)."""
        student = self._student()
        if not student:
            return Response({'error': 'Student profile required.'}, status=400)
        try:
            submission = NotebookSubmission.objects.select_related('notebook').filter(
                id=sub_id, notebook_id=pk, student=student,
            ).first()
        except (ValidationError, ValueError):
            submission = None
        if not submission:
            return Response({'error': 'Submission not found.'},
                            status=status.HTTP_404_NOT_FOUND)
        return Response(SubmissionResultSerializer(submission).data)

    @action(detail=True, methods=['get'], url_path='my-submissions')
    def my_submissions(self, request, pk=None):
        """The student's submission history for this notebook (newest first)."""
        notebook = self.get_object()
        student = self._student()
        if not student:
            return Response([])
        subs = NotebookSubmission.objects.filter(
            notebook=notebook, student=student,
        ).order_by('-attempt_number')
        return Response(MySubmissionSummarySerializer(subs, many=True).data)

    @action(detail=True, methods=['get'],
            url_path=rf'submissions/(?P<sub_id>{UUID_RE})/notebook')
    def submission_notebook(self, request, pk=None, sub_id=None):
        """The exact notebook document the student submitted (owner-scoped)."""
        student = self._student()
        if not student:
            return Response({'error': 'Student profile required.'}, status=400)
        submission = NotebookSubmission.objects.filter(
            id=sub_id, notebook_id=pk, student=student,
        ).first()
        if not submission:
            return Response({'error': 'Submission not found.'},
                            status=status.HTTP_404_NOT_FOUND)
        return Response({
            'notebook_json': submission.notebook_json,
            'attempt_number': submission.attempt_number,
            'submitted_at': submission.submitted_at,
        })
