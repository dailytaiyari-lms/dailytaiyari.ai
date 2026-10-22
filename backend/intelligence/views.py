"""Student-facing practice + mastery endpoints (/api/v1/intelligence/)."""
import json

from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from .models import LearnerConceptState, PracticeSet
from .serializers import (
    MasteryRowSerializer, PracticeSetDetailSerializer, PracticeSetSerializer,
)
from .services import practice as practice_service
from .services.practice import PracticeError


class PracticeFeaturePermission(permissions.BasePermission):
    """The tenant must have opted into Smart Practice."""

    message = 'Smart Practice is not enabled for this academy.'

    def has_permission(self, request, view):
        tenant = getattr(request, 'tenant', None)
        return bool(tenant and tenant.get_features().get('practice'))


class RefreshThrottle(UserRateThrottle):
    rate = '6/hour'


def _student_or_none(request):
    return getattr(request.user, 'profile', None)


class PracticeSetViewSet(viewsets.ReadOnlyModelViewSet):
    """A student's own practice sets, with the session actions inline."""

    permission_classes = [permissions.IsAuthenticated, PracticeFeaturePermission]
    serializer_class = PracticeSetSerializer

    def get_queryset(self):
        student = _student_or_none(self.request)
        tenant = getattr(self.request, 'tenant', None)
        if student is None or tenant is None:
            return PracticeSet.objects.none()
        queryset = (
            PracticeSet.objects.filter(tenant=tenant, student=student)
            .select_related('course')
            .prefetch_related('target_concepts', 'items__question__options')
        )
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status__in=status_filter.split(','))
        else:
            queryset = queryset.exclude(status='expired')
        return queryset

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return PracticeSetDetailSerializer
        return PracticeSetSerializer

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        practice_set = self.get_object()
        try:
            if practice_set.status not in ('suggested', 'in_progress'):
                raise PracticeError('This practice set is no longer active.')
            practice_service.start_set(practice_set)
        except PracticeError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(PracticeSetDetailSerializer(practice_set).data)

    @action(detail=True, methods=['post'])
    def answer(self, request, pk=None):
        practice_set = self.get_object()
        try:
            result = practice_service.answer_item(
                practice_set,
                request.data.get('item_id'),
                selected_options=request.data.get('selected_options'),
                numerical_answer=request.data.get('numerical_answer'),
                time_taken_seconds=request.data.get('time_taken_seconds', 0),
            )
        except PracticeError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result)

    @action(detail=True, methods=['post'])
    def submit(self, request, pk=None):
        practice_set = self.get_object()
        try:
            summary = practice_service.submit_set(practice_set)
        except PracticeError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(summary)

    @action(detail=True, methods=['post'])
    def dismiss(self, request, pk=None):
        practice_set = self.get_object()
        if practice_set.status != 'suggested':
            return Response(
                {'error': 'Only a suggested set can be dismissed.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        practice_set.status = 'dismissed'
        practice_set.save(update_fields=['status', 'updated_at'])
        return Response({'status': 'dismissed'})


class PracticeRefreshView(APIView):
    """On-demand recompute of the student's suggestions (throttled)."""

    permission_classes = [permissions.IsAuthenticated, PracticeFeaturePermission]
    throttle_classes = [RefreshThrottle]

    def post(self, request):
        student = _student_or_none(request)
        if student is None:
            return Response({'error': 'No student profile.'}, status=status.HTTP_400_BAD_REQUEST)

        from exams.models import Course
        from users.models import CourseEnrollment

        from . import recommendation

        course_ids = CourseEnrollment.objects.filter(
            student=student, status='approved',
        ).values_list('course_id', flat=True)
        built = 0
        for course in Course.objects.filter(id__in=course_ids, status='active'):
            built += len(recommendation.refresh_recommendations(student, course))
        return Response({'new_sets': built})


class MasteryView(APIView):
    """The student's concept-mastery map (optionally per course)."""

    permission_classes = [permissions.IsAuthenticated, PracticeFeaturePermission]

    def get(self, request):
        student = _student_or_none(request)
        if student is None:
            return Response([])
        queryset = (
            LearnerConceptState.objects.filter(student=student)
            .select_related('concept__subject')
            .order_by('concept__subject__name', '-mastery')
        )
        course_id = request.query_params.get('course')
        if course_id:
            queryset = queryset.filter(concept__subject__course_id=course_id)
        return Response(MasteryRowSerializer(queryset[:300], many=True).data)


class TimelineThrottle(UserRateThrottle):
    scope = 'timeline'  # own cache history, not shared with the default 'user' scope
    rate = '20/min'


MAX_TIMELINE_BODY = 256 * 1024


class TimelineSyncView(APIView):
    """Browser → raw per-question timeline for an attempt.

    Only for tenants with the learning layer on (any of practice, ai_grading,
    response_diagnosis). Otherwise it answers 204 and writes nothing: a 403
    would make the client mark its session dead and log noise, and the client
    gate means it is rarely called anyway.
    """

    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [TimelineThrottle]

    def post(self, request):
        from .api import intelligence_enabled
        from .services.timeline import TimelineError
        from .services.timeline_sync import TimelineFinalized, save_session

        if not intelligence_enabled(getattr(request, 'tenant', None)):
            return Response(status=status.HTTP_204_NO_CONTENT)
        try:
            length = int(request.META.get('CONTENT_LENGTH') or 0)
        except ValueError:
            length = 0
        if length > MAX_TIMELINE_BODY:
            return Response({'error': 'Timeline too large.'},
                            status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        student = _student_or_none(request)
        if student is None:
            return Response({'error': 'Students only.'}, status=status.HTTP_403_FORBIDDEN)
        data = request.data
        if not isinstance(data, dict):
            return Response({'error': 'Body must be a JSON object.'},
                            status=status.HTTP_400_BAD_REQUEST)
        # Content-Length can be absent (chunked); re-check the parsed payload.
        try:
            events_size = len(json.dumps(data.get('events'), separators=(',', ':')))
        except (TypeError, ValueError):
            events_size = 0
        if events_size > MAX_TIMELINE_BODY:
            return Response({'error': 'Timeline too large.'},
                            status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        try:
            save_session(
                kind=data.get('attempt_kind'), student=student,
                attempt_id=data.get('attempt_id'), parent_id=data.get('parent_id'),
                session_id=data.get('session_id'), elapsed_ms=data.get('elapsed_ms'),
                events=data.get('events'), truncated=bool(data.get('truncated')),
            )
        except TimelineFinalized:
            return Response({'error': 'This attempt was already diagnosed.'},
                            status=status.HTTP_409_CONFLICT)
        except TimelineError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'ok': True})


class DiagnosisFeaturePermission(permissions.BasePermission):
    """The tenant must have opted into Answer Diagnosis."""

    message = 'Answer Diagnosis is not enabled for this academy.'

    def has_permission(self, request, view):
        tenant = getattr(request, 'tenant', None)
        return bool(tenant and tenant.get_features().get('response_diagnosis'))


def _item_key(question_id, mock_item_id):
    return f'bank:{question_id}' if question_id else f'item:{mock_item_id}'


def _owned_finished_attempt(kind, attempt_id, student):
    import uuid

    from quiz.models import MockTestAttempt, QuizAttempt

    if not isinstance(kind, str) or not isinstance(attempt_id, str):
        return None
    model = {'quiz': QuizAttempt, 'mock': MockTestAttempt}.get(kind)
    if model is None or student is None:
        return None
    try:
        uuid.UUID(attempt_id)
    except ValueError:
        return None
    return model.objects.filter(id=attempt_id, student=student).exclude(
        status='in_progress').first()


def _attempt_item(kind, attempt, item_kind, item_id):
    """The Question / MockTestItem ``item_id`` names, only if it is in the attempt."""
    import uuid

    from quiz.models import MockTestItem, MockTestQuestion

    if not isinstance(item_id, str) or not isinstance(item_kind, str):
        return None
    try:
        uuid.UUID(item_id)
    except ValueError:
        return None
    if item_kind == 'bank':
        if kind == 'quiz':
            return attempt.quiz.questions.filter(id=item_id).first()
        link = MockTestQuestion.objects.filter(
            mock_test=attempt.mock_test, question_id=item_id).select_related('question').first()
        return link.question if link else None
    if item_kind == 'item' and kind == 'mock':
        return MockTestItem.objects.filter(mock_test=attempt.mock_test, id=item_id).first()
    return None


class SelfReportView(APIView):
    """The student's own "what happened?" on wrong/unanswered review items."""

    permission_classes = [permissions.IsAuthenticated, DiagnosisFeaturePermission]

    def get(self, request):
        from .models import ResponseDiagnosis, ResponseSelfReport

        kind = request.query_params.get('attempt_kind')
        attempt = _owned_finished_attempt(
            kind, request.query_params.get('attempt_id'), _student_or_none(request))
        if attempt is None:
            return Response({'error': 'Attempt not found.'}, status=status.HTTP_404_NOT_FOUND)
        reports = {
            _item_key(q, m): choice
            for q, m, choice in ResponseSelfReport.objects.filter(
                attempt_kind=kind, attempt_id=attempt.id,
            ).values_list('question_id', 'mock_item_id', 'choice')
        }
        not_seen = [
            _item_key(q, m)
            for q, m in ResponseDiagnosis.objects.filter(
                attempt_kind=kind, attempt_id=attempt.id, final_label='not_seen',
            ).values_list('question_id', 'mock_item_id')
        ]
        return Response({'reports': reports, 'not_seen': not_seen})

    def post(self, request):
        from .models import ResponseDiagnosis, ResponseSelfReport
        from .services.diagnosis import reconcile

        data = request.data
        if not isinstance(data, dict):
            return Response({'error': 'Body must be a JSON object.'},
                            status=status.HTTP_400_BAD_REQUEST)
        kind = data.get('attempt_kind')
        choice = data.get('choice')
        if not isinstance(choice, str) or choice not in dict(ResponseSelfReport.CHOICE_CHOICES):
            return Response({'error': 'Unknown choice.'}, status=status.HTTP_400_BAD_REQUEST)
        student = _student_or_none(request)
        attempt = _owned_finished_attempt(kind, data.get('attempt_id'), student)
        if attempt is None:
            return Response({'error': 'Attempt not found.'}, status=status.HTTP_404_NOT_FOUND)
        item = _attempt_item(kind, attempt, data.get('item_kind'), data.get('item_id'))
        if item is None:
            return Response({'error': 'Question not in this attempt.'},
                            status=status.HTTP_400_BAD_REQUEST)

        arm = {'question': item} if data.get('item_kind') == 'bank' else {'mock_item': item}
        diag = ResponseDiagnosis.objects.filter(
            attempt_kind=kind, attempt_id=attempt.id, **arm).first()
        if diag is not None and diag.is_correct:
            return Response({'error': 'Only wrong or unanswered questions take a self-report.'},
                            status=status.HTTP_400_BAD_REQUEST)

        ResponseSelfReport.objects.update_or_create(
            attempt_kind=kind, attempt_id=attempt.id, **arm,
            defaults={'student': student, 'tenant': student.user.tenant, 'choice': choice},
        )
        if diag is not None:
            # Cheap: reconcile only — the stored label, confidence and flags stand.
            diag.self_report = choice
            diag.final_label = reconcile(diag.label, diag.confidence, diag.flags, choice,
                                         bool((diag.metrics or {}).get('timed_out')))
            diag.save(update_fields=['self_report', 'final_label', 'updated_at'])
        return Response({'saved': True, 'choice': choice})
