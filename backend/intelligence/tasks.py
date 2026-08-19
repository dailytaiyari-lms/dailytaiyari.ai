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
# Learner state + item stats (default queue — cheap, statistical)
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(name='intelligence.update_learner_state', max_retries=0)
def update_learner_state_for_attempt(kind, attempt_id):
    """Recompute the concept states an attempt touched. Idempotent."""
    from .services import state

    try:
        return state.update_for_attempt(kind, attempt_id)
    except Exception:  # noqa: BLE001 — the nightly refresh catches up
        logger.exception('intelligence.update_learner_state failed for %s %s', kind, attempt_id)
        return 0


@shared_task(name='intelligence.refresh_learner_state', time_limit=1800)
def refresh_learner_state():
    """Nightly: re-decay stale states and catch up on any missed enqueues.

    Two sweeps:
    - states not recomputed in 24h get fresh retention/mastery decay;
    - attempts finalized in the last 48h whose enqueue may have been lost
      (broker blip) are re-processed — a no-op when nothing was missed.
    """
    from datetime import timedelta

    from django.utils import timezone

    from .models import LearnerConceptState
    from .services import state

    refreshed = 0
    cutoff = timezone.now() - timedelta(hours=24)
    stale = (
        LearnerConceptState.objects.filter(computed_at__lt=cutoff, effective_evidence__gt=0)
        .select_related('student__user', 'concept')[:5000]
    )
    for row in stale:
        state.recompute_state(row.student, row.concept)
        refreshed += 1

    caught_up = 0
    recent = timezone.now() - timedelta(hours=48)
    from .models import LearningEvent

    pairs = (
        LearningEvent.objects.filter(created_at__gte=recent)
        .values_list('attempt_kind', 'attempt_id').distinct()
    )
    for kind, attempt_id in pairs:
        if kind in ('quiz', 'mock') and attempt_id:
            caught_up += state.update_for_attempt(kind, attempt_id)

    logger.info('intelligence.refresh_learner_state: %d refreshed, %d catch-up concepts',
                refreshed, caught_up)
    return refreshed


@shared_task(name='intelligence.recompute_item_stats', time_limit=1800)
def recompute_item_stats():
    """Nightly: rebuild empirical item statistics from the event log."""
    from .services import itemstats

    count = itemstats.recompute_all()
    logger.info('intelligence.recompute_item_stats: %d item(s)', count)
    return count


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
