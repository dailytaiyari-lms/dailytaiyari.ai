"""Admin/instructor authoring + submission review for notebooks."""
import json
import logging

from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from exams.admin_views import TenantAdminModelViewSet
from users.models import CourseEnrollment

from . import services
from .admin_serializers import (
    AdminNotebookDatasetSerializer, AdminNotebookListSerializer,
    AdminNotebookSerializer, AdminSubmissionListSerializer,
    AdminSubmissionSerializer, NotebookMetaSerializer,
)
from .models import Notebook, NotebookDataset, NotebookSubmission
from .nbformat_utils import NotebookFormatError, normalize_notebook, strip_outputs

logger = logging.getLogger(__name__)

# Cap on an uploaded .ipynb so a huge outputs-laden notebook can't blow up the DB row.
MAX_IPYNB_BYTES = 20 * 1024 * 1024


class NotebookMetaView(APIView):
    """Static authoring metadata (available packages, cell roles, modes)."""
    from rest_framework import permissions
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(NotebookMetaSerializer.payload())


class AdminNotebookViewSet(TenantAdminModelViewSet):
    queryset = Notebook.objects.select_related('course', 'subject', 'topic').prefetch_related(
        'tests', 'datasets',
    ).all()
    serializer_class = AdminNotebookSerializer
    search_fields = ['title']
    ordering_fields = ['order', 'created_at', 'title']
    ordering = ['order', '-created_at']
    filterset_fields = ['course', 'subject', 'topic', 'status', 'difficulty']
    tenant_lookup = 'tenant'
    course_lookup = 'course'
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_serializer_class(self):
        if self.action == 'list':
            return AdminNotebookListSerializer
        return AdminNotebookSerializer

    @action(detail=False, methods=['post'], url_path='import-ipynb',
            parser_classes=[MultiPartParser, FormParser])
    def import_ipynb(self, request):
        """Parse an uploaded .ipynb into a normalized template document.

        Does not create a Notebook — it returns the parsed document so the
        admin can review cell roles before saving. Outputs are stripped so
        students start from a clean notebook.
        """
        upload = request.FILES.get('file')
        if not upload:
            return Response({'error': 'Attach a .ipynb file.'}, status=400)
        if upload.size > MAX_IPYNB_BYTES:
            return Response(
                {'error': 'That notebook is too large. Clear its outputs and try again.'},
                status=400,
            )
        try:
            raw = upload.read().decode('utf-8')
        except UnicodeDecodeError:
            return Response({'error': 'That file is not a UTF-8 notebook.'}, status=400)
        try:
            document = strip_outputs(json.loads(raw))
        except (ValueError, NotebookFormatError) as exc:
            return Response({'error': f'Could not read that notebook: {exc}'}, status=400)
        return Response({
            'template_json': document,
            'cell_count': len(document.get('cells') or []),
        })

    @action(detail=True, methods=['post'], url_path='duplicate')
    def duplicate(self, request, pk=None):
        """Copy a notebook (template, tests and dataset rows) as a new draft."""
        source = self.get_object()
        tests = list(source.tests.all())
        datasets = list(source.datasets.all())

        source.pk = None
        source.id = None
        source._state.adding = True
        source.title = f'{source.title} (copy)'
        source.status = 'draft'
        source.save()

        for test in tests:
            test.pk = None
            test.id = None
            test._state.adding = True
            test.notebook = source
            test.save()
        for dataset in datasets:
            dataset.pk = None
            dataset.id = None
            dataset._state.adding = True
            dataset.notebook = source
            dataset.save()

        return Response(AdminNotebookSerializer(source, context={'request': request}).data,
                        status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='test-run')
    def test_run(self, request, pk=None):
        """Dry-run the notebook's tests against a reference solution.

        Lets an author confirm the autograder actually passes on a correct
        solution before publishing. Body: {"notebook_json": {...}} — defaults to
        the template when omitted.
        """
        notebook = self.get_object()
        if not services.is_enabled():
            return Response(
                {'error': 'Server-side notebook grading is not enabled on this deployment.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        try:
            document = normalize_notebook(
                request.data.get('notebook_json') or notebook.template_json,
            )
        except NotebookFormatError as exc:
            return Response({'error': str(exc)}, status=400)
        try:
            outcome = services.grade_notebook(notebook, document)
        except services.EngineError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response(outcome)

    @action(detail=True, methods=['get'])
    def submissions(self, request, pk=None):
        """Per-student latest + best submission, pending students, and counts."""
        notebook = self.get_object()
        all_subs = notebook.submissions.select_related('student__user').order_by(
            'student_id', '-attempt_number',
        )

        latest_by_student = {}
        best_by_student = {}
        attempts_by_student = {}
        for s in all_subs:
            attempts_by_student[s.student_id] = attempts_by_student.get(s.student_id, 0) + 1
            if s.student_id not in latest_by_student:
                latest_by_student[s.student_id] = s
            if s.status == NotebookSubmission.STATUS_GRADED:
                current = best_by_student.get(s.student_id)
                if current is None or s.passed_points > current.passed_points:
                    best_by_student[s.student_id] = s

        submitted_ids = set(latest_by_student.keys())

        enrollments = CourseEnrollment.objects.filter(
            course=notebook.course, status='approved', is_active=True,
        ).select_related('student__user')

        pending = []
        for e in enrollments:
            if e.student_id in submitted_ids:
                continue
            u = getattr(e.student, 'user', None)
            pending.append({
                'student': str(e.student_id),
                'student_name': ((getattr(u, 'full_name', '') or (u.email if u else '')).strip()
                                 if u else ''),
                'student_email': u.email if u else '',
            })

        rows = []
        for student_id, latest in latest_by_student.items():
            best = best_by_student.get(student_id, latest)
            row = AdminSubmissionListSerializer(best, context={'request': request}).data
            row['attempts_used'] = attempts_by_student.get(student_id, 0)
            row['latest_submission'] = str(latest.id)
            row['latest_status'] = latest.status
            rows.append(row)
        rows.sort(key=lambda r: (-(r.get('passed_points') or 0), r.get('student_name') or ''))

        total = enrollments.count()
        graded_rows = [r for r in rows if r.get('status') == NotebookSubmission.STATUS_GRADED]
        avg_percent = (
            round(sum(r.get('score_percent') or 0 for r in graded_rows) / len(graded_rows))
            if graded_rows else 0
        )
        return Response({
            'notebook': {
                'id': str(notebook.id),
                'title': notebook.title,
                'description': notebook.description,
                'difficulty': notebook.difficulty,
                'max_marks': notebook.max_marks,
                'status': notebook.status,
                'total_points': sum(t.points for t in notebook.tests.all()),
                'is_timed': notebook.is_timed,
                'due_at': notebook.due_at,
                'topic_name': notebook.topic.name if notebook.topic else '',
            },
            'counts': {
                'total_students': total,
                'submitted': len(submitted_ids),
                'pending': max(total - len(submitted_ids), 0),
                'completed': sum(
                    1 for r in rows
                    if (r.get('total_points') or 0) and
                    (r.get('passed_points') or 0) >= 0.6 * (r.get('total_points') or 0)
                ),
                'average_percent': avg_percent,
            },
            'submissions': rows,
            'pending_students': pending,
        })

    @action(detail=True, methods=['get'], url_path='stats')
    def stats(self, request, pk=None):
        """Per-test pass rates, so authors can spot a broken or too-hard test."""
        notebook = self.get_object()
        graded = notebook.submissions.filter(status=NotebookSubmission.STATUS_GRADED)
        totals = {}
        for submission in graded:
            for result in submission.results or []:
                key = str(result.get('id'))
                bucket = totals.setdefault(key, {'passed': 0, 'attempted': 0})
                bucket['attempted'] += 1
                if result.get('passed'):
                    bucket['passed'] += 1
        rows = []
        for test in notebook.tests.all().order_by('order', 'created_at'):
            bucket = totals.get(str(test.id), {'passed': 0, 'attempted': 0})
            attempted = bucket['attempted']
            rows.append({
                'id': str(test.id),
                'name': test.name,
                'points': test.points,
                'is_hidden': test.is_hidden,
                'attempted': attempted,
                'passed': bucket['passed'],
                'pass_rate': round(100 * bucket['passed'] / attempted) if attempted else 0,
            })
        return Response({'tests': rows, 'graded_submissions': graded.count()})


class AdminNotebookDatasetViewSet(TenantAdminModelViewSet):
    """Upload/manage the data files mounted into a notebook."""
    queryset = NotebookDataset.objects.select_related('notebook').all()
    serializer_class = AdminNotebookDatasetSerializer
    tenant_lookup = 'notebook__tenant'
    course_lookup = 'notebook__course'
    search_fields = ['filename']
    ordering_fields = ['order', 'created_at']
    ordering = ['order', 'created_at']
    filterset_fields = ['notebook']
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def perform_create(self, serializer):
        # Tenant comes from the parent notebook, not the request body.
        notebook = serializer.validated_data.get('notebook')
        serializer.save(tenant=getattr(notebook, 'tenant', None))


class AdminNotebookSubmissionViewSet(TenantAdminModelViewSet):
    """Review a single submission and override its marks."""
    queryset = NotebookSubmission.objects.select_related(
        'student__user', 'notebook', 'graded_by',
    ).all()
    serializer_class = AdminSubmissionSerializer
    http_method_names = ['get', 'patch', 'post', 'head', 'options']
    tenant_lookup = 'notebook__tenant'
    course_lookup = 'notebook__course'
    search_fields = []
    ordering_fields = ['submitted_at', 'passed_points']
    ordering = ['-submitted_at']
    filterset_fields = ['notebook', 'student', 'status']

    def get_serializer_class(self):
        if self.action == 'list':
            return AdminSubmissionListSerializer
        return AdminSubmissionSerializer

    def perform_update(self, serializer):
        serializer.save(graded_by=self.request.user)

    @action(detail=True, methods=['post'], url_path='regrade')
    def regrade(self, request, pk=None):
        """Re-run the autograder on this submission (e.g. after fixing a test)."""
        submission = self.get_object()
        if not services.is_enabled():
            return Response(
                {'error': 'Server-side notebook grading is not enabled on this deployment.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        NotebookSubmission.objects.filter(pk=submission.pk).update(
            status=NotebookSubmission.STATUS_QUEUED,
        )
        submission.refresh_from_db()
        try:
            from .tasks import grade_notebook_submission
            grade_notebook_submission.delay(str(submission.id))
            return Response({'status': 'queued'}, status=status.HTTP_202_ACCEPTED)
        except Exception as exc:  # broker down -> grade inline
            logger.warning('Regrade enqueue failed (%s); grading synchronously.', exc)
        from . import grading
        try:
            # The task claims 'queued' -> 'running'; do the same inline.
            NotebookSubmission.objects.filter(
                pk=submission.pk, status=NotebookSubmission.STATUS_QUEUED,
            ).update(status=NotebookSubmission.STATUS_RUNNING)
            submission.refresh_from_db()
            grading.finalize_submission(submission)
        except services.EngineError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response(AdminSubmissionSerializer(submission, context={'request': request}).data)

    @action(detail=True, methods=['post'], url_path='grade')
    def grade(self, request, pk=None):
        """Manually override marks and leave feedback."""
        submission = self.get_object()
        marks = request.data.get('override_marks', request.data.get('marks'))
        feedback = request.data.get('feedback')

        if marks in ('', None):
            submission.override_marks = None
        else:
            try:
                value = float(marks)
            except (TypeError, ValueError):
                return Response({'error': 'Marks must be a number.'}, status=400)
            max_marks = submission.notebook.max_marks
            if value < 0 or (max_marks and value > max_marks):
                return Response(
                    {'error': f'Marks must be between 0 and {max_marks or "the maximum"}.'},
                    status=400,
                )
            submission.override_marks = value

        if feedback is not None:
            submission.feedback = feedback
        submission.graded_by = request.user
        submission.graded_at = timezone.now()
        submission.save(update_fields=[
            'override_marks', 'feedback', 'graded_by', 'graded_at', 'updated_at',
        ])
        return Response(AdminSubmissionSerializer(submission, context={'request': request}).data)
