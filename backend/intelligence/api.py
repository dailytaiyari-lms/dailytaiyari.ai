"""The only surface other apps call into the intelligence layer.

Every function here is fail-safe: an intelligence failure (Redis blip, bad
data, bug) must never fail a student's submit or an admin's grading action.
Missed work is caught up by the nightly sweep, which recomputes from the
append-only event log.

The whole layer is opt-in per tenant: unless a tenant enables at least one of
``LEARNING_FEATURES``, every hook here is a no-op, so that tenant's submit and
grading paths behave exactly as they did before the layer existed.
"""
import logging

logger = logging.getLogger(__name__)

# Any one of these switches the learning layer on for a tenant.
LEARNING_FEATURES = ('practice', 'ai_grading', 'response_diagnosis')

# Publish retry cap for enqueues made inside student/admin request paths.
# The global CELERY_BROKER_TRANSPORT_OPTIONS stay exactly as on main (every
# other app's enqueues use them), so the cap is applied per call instead: with
# a dead broker, one fast retry and then give up — well under a second, and
# only ever for opted-in tenants. The nightly sweep catches up anything lost.
ENQUEUE_RETRY_POLICY = {
    'max_retries': 1, 'interval_start': 0, 'interval_step': 0.2, 'interval_max': 0.5,
}


def enqueue(task, *args):
    """Publish ``task(*args)`` with the request-path retry cap. Raises on a
    broker failure; callers wrap it in their own fail-safe try/except."""
    task.apply_async(args=list(args), retry=True, retry_policy=ENQUEUE_RETRY_POLICY)


def intelligence_enabled(tenant):
    """True when ``tenant`` has at least one learning-layer feature enabled.

    A missing tenant, or any error reading its features, counts as disabled.
    Never raises.
    """
    try:
        if tenant is None:
            return False
        from .hooks import _feature_enabled
        return any(_feature_enabled(tenant, key) for key in LEARNING_FEATURES)
    except Exception:
        logger.exception('intelligence: enabled check failed')
        return False


def enabled_tenant_ids():
    """Ids of every tenant with the learning layer on (empty set on error)."""
    try:
        from core.models import Tenant
        tenants = Tenant.objects.only('id', 'features', 'feature_locks')
        return {tenant.id for tenant in tenants if intelligence_enabled(tenant)}
    except Exception:
        logger.exception('intelligence: could not list enabled tenants')
        return set()


def _attempt_tenant(attempt):
    try:
        return attempt.student.user.tenant
    except Exception:
        return None


def _item_tenant(item):
    try:
        if item.tenant_id:
            return item.tenant
        mock_test = getattr(item, 'mock_test', None)
        return mock_test.tenant if mock_test is not None else None
    except Exception:
        return None


def record_attempt_events(attempt):
    """Record LearningEvents for a finalized quiz/mock attempt and queue the
    learner-state update. Idempotent; safe to call more than once. A no-op for
    tenants without the learning layer."""
    if not intelligence_enabled(_attempt_tenant(attempt)):
        return
    try:
        from intelligence.services import events
        events.record_attempt_events(attempt)
    except Exception:
        logger.exception('intelligence: failed to record events for attempt %s', attempt.pk)
        return
    _enqueue_state_update(attempt)


def record_regrade_event(item_answer):
    """Record a superseding event after a manual regrade of an inline answer.
    A no-op for tenants without the learning layer."""
    try:
        attempt = item_answer.attempt
    except Exception:
        logger.exception('intelligence: regrade answer %s has no attempt', item_answer.pk)
        return
    if not intelligence_enabled(_attempt_tenant(attempt)):
        return
    try:
        from intelligence.services import events
        events.record_regrade_event(item_answer)
    except Exception:
        logger.exception('intelligence: failed to record regrade for answer %s', item_answer.pk)
        return
    _enqueue_state_update(attempt)


def mark_item_stale_if_changed(item):
    """After a manual edit, flag a tagged item for re-tagging when its
    semantic content changed. Fail-safe; returns True when flipped. A no-op
    (False) for tenants without the learning layer."""
    if not intelligence_enabled(_item_tenant(item)):
        return False
    try:
        from intelligence.services.itemtags import mark_stale_if_changed
        return mark_stale_if_changed(item)
    except Exception:
        logger.exception('intelligence: stale check failed for item %s', item.pk)
        return False


def _enqueue_state_update(attempt):
    if not intelligence_enabled(_attempt_tenant(attempt)):
        return
    try:
        from quiz.models import QuizAttempt

        from intelligence.tasks import diagnose_and_update_state
        kind = 'quiz' if isinstance(attempt, QuizAttempt) else 'mock'
        enqueue(diagnose_and_update_state, kind, str(attempt.pk))
    except Exception:
        # Broker down or task missing — the nightly sweep recomputes students
        # whose events are newer than their computed state.
        logger.exception('intelligence: failed to enqueue state update for attempt %s', attempt.pk)
