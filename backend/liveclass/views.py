"""Student-facing live-class endpoints: list published classes for a topic and
issue a personal join link.

Students go through ``POST /classes/<id>/join/`` rather than opening the raw
link, so a registered Zoom meeting can hand them their *personal* join URL
(which is what makes attendance map exactly to a student) and so the click is
recorded even for Google Meet.
"""
from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response

from users.models import CourseEnrollment

from .models import LiveClass
from .serializers import LiveClassSerializer
from .services import join_url_for_student, record_portal_join


class LiveClassViewSet(viewsets.ReadOnlyModelViewSet):
    """Published live classes for the student's approved-enrolled courses."""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = LiveClassSerializer

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
        qs = LiveClass.objects.select_related('topic', 'subject').filter(
            status='published', course_id__in=self._enrolled_course_ids(),
        )
        topic_id = self.request.query_params.get('topic')
        if topic_id:
            qs = qs.filter(topic_id=topic_id)
        return qs.order_by('order', 'scheduled_start', '-created_at')

    @action(detail=True, methods=['post'])
    def join(self, request, pk=None):
        """Return the link this student should open, and log the join."""
        live_class = self.get_object()
        student = self._student()
        if student is None:
            return Response({'detail': 'No student profile for this account.'}, status=403)

        url = join_url_for_student(live_class, student)
        if not url:
            return Response(
                {'detail': 'No join link has been set up for this class yet.'},
                status=400,
            )
        record_portal_join(live_class, student)
        return Response({'join_url': url, 'provider': live_class.provider})
