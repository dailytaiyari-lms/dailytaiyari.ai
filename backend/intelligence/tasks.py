"""Celery tasks for the learner-intelligence layer.

Two kinds of work, on two queues:
- LLM work (tagging) runs on ``aigen`` beside the course/mock builders, with
  its own generous time limits;
- statistical work (learner state, item stats) is cheap and runs on the
  default queue. All of it is recompute-from-events, so redelivery or a
  double-enqueue is harmless.
"""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# LLM tagging (queue: aigen)
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(
    name='intelligence.tag_items', bind=True, max_retries=0,
    queue='aigen', soft_time_limit=1500, time_limit=1560,
)
def tag_items_for_tenant(self, tenant_id, limit=200):
    """One budget-gated tagging pass for one tenant."""
    from core.models import Tenant

    from .services import tagging

    tenant = Tenant.objects.filter(id=tenant_id).first()
    if tenant is None:
        logger.warning('intelligence.tag_items: tenant %s not found', tenant_id)
        return 0
    try:
        return tagging.run_tagging_for_tenant(tenant, limit=limit)
    except Exception as exc:  # noqa: BLE001 — a failed sweep just waits for the next one
        logger.warning('intelligence.tag_items: tenant %s failed: %s', tenant_id, exc)
        return 0


@shared_task(name='intelligence.tagging_sweep', queue='aigen', time_limit=300)
def tagging_sweep():
    """Weekly: enqueue a tagging pass for every tenant with untagged items."""
    from core.models import Tenant
    from quiz.models import MockTestItem, Question

    tenant_ids = set(
        Question.objects.filter(tagging_status__in=['', 'stale'], tenant__isnull=False)
        .values_list('tenant_id', flat=True).distinct()
    ) | set(
        MockTestItem.objects.filter(tagging_status__in=['', 'stale'], tenant__isnull=False)
        .values_list('tenant_id', flat=True).distinct()
    )
    active = set(Tenant.objects.filter(id__in=tenant_ids, is_active=True)
                 .values_list('id', flat=True))
    for tenant_id in active:
        tag_items_for_tenant.delay(str(tenant_id))
    logger.info('intelligence.tagging_sweep: %d tenant(s) queued', len(active))
    return len(active)
