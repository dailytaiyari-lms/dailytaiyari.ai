"""Student-facing practice + mastery endpoints (/api/v1/intelligence/)."""
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
