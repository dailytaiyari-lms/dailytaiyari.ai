"""Feature-gated hooks the quiz app calls after grading events.

Cheap guards first, then a task enqueue — and everything fail-safe, because
these run inside student-facing request paths. When a feature is disabled the
hook is a no-op; the foundation (events, states) keeps accruing regardless,
so flipping a feature on works instantly.
"""
import logging

logger = logging.getLogger(__name__)


def _feature_enabled(tenant, key):
    try:
        return bool(tenant and tenant.get_features().get(key))
    except Exception:
        logger.exception('intelligence: feature check failed for %s', key)
        return False


def on_attempt_graded(attempt, course=None):
    """After an attempt is finalized: refresh practice recommendations."""
    student = attempt.student
    tenant = student.user.tenant
    if not _feature_enabled(tenant, 'practice'):
        return
    try:
        from intelligence.tasks import recompute_recommendations
        recompute_recommendations.delay(
            str(student.id), str(course.id) if course else None,
        )
    except Exception:
        logger.exception('intelligence: failed to enqueue recommendations for %s', student.pk)


def maybe_enqueue_ai_grading(attempt):
    """After a rich mock finalization: grade subjective answers with AI.

    Only when the tenant opted into ai_grading and something actually pends.
    """
    tenant = attempt.student.user.tenant
    if not _feature_enabled(tenant, 'ai_grading'):
        return
    try:
        if not attempt.item_answers.filter(needs_manual_grading=True).exists():
            return
        from intelligence.tasks import grade_subjective_answers
        grade_subjective_answers.delay(str(attempt.id))
    except Exception:
        logger.exception('intelligence: failed to enqueue AI grading for %s', attempt.pk)
