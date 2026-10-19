"""Celery tasks for notifications.

Emails and announcement fan-out run off the web request thread when
``NOTIFICATIONS_ASYNC`` is enabled (prod has redis + a celery worker). The
service layer falls back to running these inline when the broker is unavailable,
so nothing here is required for correctness in development.
"""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name='notifications.send_branded_email', max_retries=2, bind=True)
def send_branded_email_task(self, tenant_id, to, subject, heading, body_html,
                            cta_text=None, cta_url=None, preheader=None):
    from core.models import Tenant
    from . import emails

    tenant = Tenant.objects.filter(id=tenant_id).first() if tenant_id else None
    ok = emails.send_branded_email(
        tenant, to, subject, heading, body_html, cta_text, cta_url, preheader,
    )
    if not ok:
        logger.warning('send_branded_email_task: delivery reported failure to %s', to)
    return ok


@shared_task(name='notifications.deliver_announcement', bind=True)
def deliver_announcement_task(self, announcement_id):
    from .models import Announcement
    from . import services

    announcement = Announcement.objects.filter(id=announcement_id).first()
    if not announcement:
        logger.warning('deliver_announcement_task: %s not found', announcement_id)
        return None
    services.deliver_announcement(announcement)
    return str(announcement_id)


@shared_task(name='notifications.send_birthday_greetings', bind=True)
def send_birthday_greetings_task(self):
    """Daily birthday sweep across every active tenant.

    Registered for deployments that add a beat scheduler; the management command
    and the request-time trigger cover everyone else.
    """
    from . import birthdays

    summaries = birthdays.run_sweep()
    total = sum(len(s.get('greeted') or []) for s in summaries)
    logger.info('send_birthday_greetings_task: greeted %s user(s)', total)
    return total


@shared_task(name='notifications.run_tenant_birthday_sweep', bind=True)
def run_tenant_birthday_sweep_task(self, tenant_id, run_date=None):
    """One tenant's birthday sweep, enqueued by the request-time trigger."""
    from datetime import date

    from core.models import Tenant
    from . import birthdays

    tenant = Tenant.objects.filter(id=tenant_id).first()
    if not tenant:
        logger.warning('run_tenant_birthday_sweep_task: tenant %s not found', tenant_id)
        return 0
    today = date.fromisoformat(run_date) if run_date else None
    summary = birthdays.run_for_tenant(tenant, today)
    return len(summary.get('greeted') or [])
