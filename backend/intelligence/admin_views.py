"""Tenant-admin / instructor endpoints (/api/v1/tenant-admin/intelligence/)."""
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from exams.models import Course

from .models import CoursePracticeConfig
from .recommendation import practice_config_for


class IsTenantAdminOrInstructor(permissions.BasePermission):
    """Teacher-visible surfaces: tenant admins and faculty both see them."""

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user and user.is_authenticated
            and getattr(user, 'role', '') in ('admin', 'instructor')
        )


def _course_or_404(request, course_id):
    return Course.objects.filter(id=course_id, tenant=request.tenant).first()


class TaggingRunView(APIView):
    """On-demand tagging pass for this tenant (queued on the AI worker)."""

    permission_classes = [permissions.IsAuthenticated, IsTenantAdminOrInstructor]

    def post(self, request):
        from .tasks import tag_items_for_tenant

        tenant = getattr(request, 'tenant', None)
        if tenant is None:
            return Response({'error': 'Tenant required.'}, status=status.HTTP_400_BAD_REQUEST)
        tag_items_for_tenant.delay(str(tenant.id))
        return Response({'queued': True})


class CoursePracticeConfigView(APIView):
    """Per-course practice toggle + knobs (the teacher's off switch)."""

    permission_classes = [permissions.IsAuthenticated, IsTenantAdminOrInstructor]

    def get(self, request, course_id):
        course = _course_or_404(request, course_id)
        if course is None:
            return Response({'error': 'Course not found.'}, status=status.HTTP_404_NOT_FOUND)
        config = practice_config_for(course)
        return Response(self._payload(config))

    def patch(self, request, course_id):
        course = _course_or_404(request, course_id)
        if course is None:
            return Response({'error': 'Course not found.'}, status=status.HTTP_404_NOT_FOUND)
        config = practice_config_for(course)
        for field in ('practice_enabled', 'generation_enabled'):
            if field in request.data:
                setattr(config, field, bool(request.data[field]))
        for field in ('max_active_sets', 'daily_xp_set_cap'):
            if field in request.data:
                try:
                    setattr(config, field, max(0, int(request.data[field])))
                except (TypeError, ValueError):
                    pass
        config.save()
        return Response(self._payload(config))

    @staticmethod
    def _payload(config: CoursePracticeConfig):
        return {
            'course': str(config.course_id),
            'practice_enabled': config.practice_enabled,
            'generation_enabled': config.generation_enabled,
            'max_active_sets': config.max_active_sets,
            'daily_xp_set_cap': config.daily_xp_set_cap,
        }
