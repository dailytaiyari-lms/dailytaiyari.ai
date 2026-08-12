"""Celery tasks for live classes.

Zoom's participant report is not ready the instant a meeting ends, so the
webhook's immediate sync can come back empty. These tasks retry the pull a few
minutes later. They are optional: the admin attendance view also lazily syncs
when it is opened, and there is a "Sync now" button, so attendance is correct
even with no worker running.
"""
import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(name='liveclass.sync_attendance', bind=True, max_retries=3)
def sync_attendance_task(self, live_class_id):
    from .models import LiveClass
    from .services import sync_attendance_from_zoom

    live_class = LiveClass.objects.filter(id=live_class_id).select_related('tenant').first()
    if live_class is None:
        return None
    ok, message = sync_attendance_from_zoom(live_class, force=True)
    if not ok:
        logger.info('Attendance sync for %s not ready yet: %s', live_class_id, message)
        # Zoom typically publishes the report within a few minutes of the end.
        raise self.retry(countdown=300, exc=RuntimeError(message))
    return message


@shared_task(name='liveclass.sync_recent_attendance')
def sync_recent_attendance_task(hours=24):
    """Reconcile every Zoom class that ended recently and was never synced.

    Safe to run on a schedule (or from cron via the ``sync_live_attendance``
    management command) as a backstop for missed webhooks.
    """
    from .models import LiveClass
    from .services import sync_attendance_from_zoom

    since = timezone.now() - timezone.timedelta(hours=hours)
    classes = LiveClass.objects.filter(
        provider=LiveClass.PROVIDER_ZOOM, scheduled_start__gte=since,
    ).exclude(zoom_meeting_id='').select_related('tenant')

    synced = 0
    for live_class in classes:
        if live_class.live_status != 'ended':
            continue
        # Skip classes already reconciled after they finished.
        if live_class.attendance_synced_at and live_class.zoom_ended_at \
                and live_class.attendance_synced_at > live_class.zoom_ended_at:
            continue
        ok, _ = sync_attendance_from_zoom(live_class, force=True)
        synced += 1 if ok else 0
    return synced
