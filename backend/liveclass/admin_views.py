"""Admin/instructor authoring for live classes, plus Zoom attendance reporting.

Beyond plain CRUD this viewset owns the Zoom meeting lifecycle (create/update/
delete on save) and exposes the attendance register:

  * ``GET   .../classes/<id>/attendance/``        — the roster with durations
  * ``POST  .../classes/<id>/attendance/sync/``   — pull Zoom's report now
  * ``PATCH .../classes/<id>/attendance/<row>/``  — admin override of a row
  * ``GET   .../classes/<id>/attendance/export/`` — CSV download
  * ``GET   .../classes/<id>/host-link/``         — the host start URL
"""
import csv

from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone
from django.utils.text import slugify
from rest_framework.decorators import action
from rest_framework.response import Response

from exams.admin_views import TenantAdminModelViewSet

from .models import LiveClass, LiveClassAttendance
from .admin_serializers import AdminLiveClassSerializer, AdminLiveClassAttendanceSerializer
from .services import (
    attendance_summary, attendance_threshold, delete_zoom_meeting,
    ensure_absent_rows, get_zoom_client, sync_attendance_from_zoom,
    sync_zoom_meeting,
)


def _search_q(search):
    """Search across a student's name/email and the raw Zoom display name."""
    return (
        Q(display_name__icontains=search)
        | Q(email__icontains=search)
        | Q(student__user__email__icontains=search)
        | Q(student__user__first_name__icontains=search)
        | Q(student__user__last_name__icontains=search)
    )


def _fmt(value):
    if not value:
        return ''
    return timezone.localtime(value).strftime('%Y-%m-%d %H:%M')


class AdminLiveClassViewSet(TenantAdminModelViewSet):
    queryset = LiveClass.objects.select_related('course', 'subject', 'topic').all()
    serializer_class = AdminLiveClassSerializer
    search_fields = ['title']
    ordering_fields = ['order', 'created_at', 'title', 'scheduled_start']
    ordering = ['order', '-created_at']
    filterset_fields = ['course', 'subject', 'topic', 'status', 'provider']
    tenant_lookup = 'tenant'
    course_lookup = 'course'

    # ------------------------------------------------------------ lifecycle
    def perform_create(self, serializer):
        super().perform_create(serializer)
        self._sync_zoom(serializer)

    def perform_update(self, serializer):
        serializer.save()
        self._sync_zoom(serializer)

    def perform_destroy(self, instance):
        # Remove the meeting from Zoom before dropping our record, otherwise it
        # lingers on the academy's calendar forever.
        delete_zoom_meeting(instance)
        instance.delete()

    def _sync_zoom(self, serializer):
        """Create/update the Zoom meeting, attaching any error to the response.

        A Zoom failure never fails the save: the class is stored, flagged, and
        the admin can retry with the "Reconnect Zoom meeting" action.
        """
        obj = serializer.instance
        if obj.provider != LiveClass.PROVIDER_ZOOM:
            return
        ok, error = sync_zoom_meeting(obj)
        if not ok:
            obj._zoom_error = error
            # Without a Zoom meeting the class is only usable if the admin
            # pasted a link themselves; make that explicit in the payload.
            if not obj.meeting_url:
                obj._zoom_error = (
                    f'{error} No join link is set yet, so students cannot join. '
                    'Connect Zoom and retry, or paste a Zoom link manually.'
                )

    # --------------------------------------------------------------- actions
    @action(detail=True, methods=['post'], url_path='zoom-sync')
    def zoom_sync(self, request, pk=None):
        """Retry creating/updating the Zoom meeting for this class."""
        live_class = self.get_object()
        if live_class.provider != LiveClass.PROVIDER_ZOOM:
            return Response({'detail': 'This is not a Zoom class.'}, status=400)
        ok, error = sync_zoom_meeting(live_class)
        if not ok:
            return Response({'detail': error}, status=400)
        live_class.refresh_from_db()
        return Response(self.get_serializer(live_class).data)

    @action(detail=True, methods=['get'], url_path='host-link')
    def host_link(self, request, pk=None):
        """The host start URL. Kept off the list payload — it starts the meeting."""
        live_class = self.get_object()
        if not live_class.zoom_start_url:
            return Response(
                {'detail': 'No Zoom host link is available for this class.'},
                status=404,
            )
        return Response({'start_url': live_class.zoom_start_url})

    @action(detail=True, methods=['get'])
    def attendance(self, request, pk=None):
        """The attendance register for this class.

        Once a class has ended we materialise absent rows so the table is the
        full roster instead of only the people who turned up.
        """
        live_class = self.get_object()
        if live_class.live_status == 'ended':
            ensure_absent_rows(live_class)
            # Zoom only publishes its report a few minutes after a meeting
            # ends, so the webhook's immediate pull often comes back empty.
            # Lazily reconcile the first time an admin opens the register, which
            # keeps attendance correct even with no Celery worker running.
            stale = live_class.attendance_synced_at is None or (
                live_class.zoom_ended_at
                and live_class.attendance_synced_at < live_class.zoom_ended_at
            )
            if live_class.zoom_linked and stale:
                sync_attendance_from_zoom(live_class)
                live_class.refresh_from_db()

        rows = LiveClassAttendance.objects.filter(
            live_class=live_class
        ).select_related('student__user')

        status_filter = request.query_params.get('status')
        if status_filter in dict(LiveClassAttendance.STATUS_CHOICES):
            rows = rows.filter(status=status_filter)
        search = (request.query_params.get('search') or '').strip()
        if search:
            rows = rows.filter(_search_q(search))

        rows = rows.order_by('status', '-duration_minutes', 'display_name')
        return Response({
            'live_class': {
                'id': str(live_class.id),
                'title': live_class.title,
                'provider': live_class.provider,
                'scheduled_start': live_class.scheduled_start,
                'duration_minutes': live_class.duration_minutes,
                'live_status': live_class.live_status,
                'zoom_linked': live_class.zoom_linked,
                'supports_attendance': live_class.supports_attendance,
                'threshold_percent': attendance_threshold(live_class.tenant),
            },
            'summary': attendance_summary(live_class),
            'results': AdminLiveClassAttendanceSerializer(rows, many=True).data,
        })

    @action(detail=True, methods=['post'], url_path='attendance/sync')
    def attendance_sync(self, request, pk=None):
        """Pull the authoritative participant report from Zoom now."""
        live_class = self.get_object()
        if get_zoom_client(live_class.tenant) is None:
            return Response(
                {'detail': 'Zoom is not connected for this academy. '
                           'Add credentials in Settings → Integrations.'},
                status=400,
            )
        ok, message = sync_attendance_from_zoom(live_class, force=True)
        if not ok:
            return Response({'detail': message}, status=400)
        live_class.refresh_from_db()
        return Response({
            'detail': message,
            'summary': attendance_summary(live_class),
        })

    @action(detail=True, methods=['patch'], url_path=r'attendance/(?P<row_id>[^/.]+)')
    def attendance_update(self, request, pk=None, row_id=None):
        """Let an admin override a row (mark present/absent, add a note).

        Overridden rows are pinned: later Zoom syncs leave their status alone.
        """
        live_class = self.get_object()
        row = LiveClassAttendance.objects.filter(
            live_class=live_class, pk=row_id
        ).select_related('student__user').first()
        if row is None:
            return Response({'detail': 'Attendance row not found.'}, status=404)

        new_status = request.data.get('status')
        if new_status is not None:
            if new_status not in dict(LiveClassAttendance.STATUS_CHOICES):
                return Response({'status': ['Invalid attendance status.']}, status=400)
            row.status = new_status
            row.is_manual_override = True
            row.source = LiveClassAttendance.SOURCE_MANUAL
        if 'notes' in request.data:
            row.notes = (request.data.get('notes') or '')[:500]
        if request.data.get('clear_override'):
            row.is_manual_override = False
            row.recompute_status(attendance_threshold(live_class.tenant))
        row.save()
        return Response(AdminLiveClassAttendanceSerializer(row).data)

    @action(detail=True, methods=['get'], url_path='attendance/export')
    def attendance_export(self, request, pk=None):
        """Download the register as CSV."""
        live_class = self.get_object()
        if live_class.live_status == 'ended':
            ensure_absent_rows(live_class)

        rows = LiveClassAttendance.objects.filter(
            live_class=live_class
        ).select_related('student__user').order_by(
            'status', '-duration_minutes', 'display_name'
        )

        started = live_class.scheduled_start
        when = timezone.localtime(started).strftime('%Y-%m-%d') if started else 'unscheduled'
        filename = f'attendance-{slugify(live_class.title) or "live-class"}-{when}.csv'

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        writer = csv.writer(response)
        writer.writerow([
            'Name', 'Email', 'Type', 'Status', 'Minutes attended',
            '% of class', 'Times joined', 'First joined', 'Last left',
            'Source', 'Manually adjusted', 'Notes',
        ])
        for row in rows:
            user = getattr(row.student, 'user', None) if row.student_id else None
            writer.writerow([
                (getattr(user, 'full_name', '') or row.display_name or '').strip(),
                getattr(user, 'email', '') or row.email,
                'Student' if row.student_id else 'Guest',
                row.get_status_display(),
                row.duration_minutes,
                row.attendance_percent,
                row.join_count,
                _fmt(row.first_joined_at),
                _fmt(row.last_left_at),
                row.get_source_display(),
                'Yes' if row.is_manual_override else 'No',
                row.notes,
            ])
        return response
