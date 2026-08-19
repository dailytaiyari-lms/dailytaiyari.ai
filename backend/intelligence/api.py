"""The only surface other apps call into the intelligence layer.

Every function here is fail-safe: an intelligence failure (Redis blip, bad
data, bug) must never fail a student's submit or an admin's grading action.
Missed work is caught up by the nightly sweep, which recomputes from the
append-only event log.
"""
import logging

logger = logging.getLogger(__name__)


def record_attempt_events(attempt):
    """Record LearningEvents for a finalized quiz/mock attempt and queue the
    learner-state update. Idempotent; safe to call more than once."""
    try:
        from intelligence.services import events
        events.record_attempt_events(attempt)
    except Exception:
        logger.exception('intelligence: failed to record events for attempt %s', attempt.pk)
        return
    _enqueue_state_update(attempt)


def record_regrade_event(item_answer):
    """Record a superseding event after a manual regrade of an inline answer."""
    try:
        from intelligence.services import events
        events.record_regrade_event(item_answer)
    except Exception:
        logger.exception('intelligence: failed to record regrade for answer %s', item_answer.pk)
        return
    _enqueue_state_update(item_answer.attempt)


def mark_item_stale_if_changed(item):
    """After a manual edit, flag a tagged item for re-tagging when its
    semantic content changed. Fail-safe; returns True when flipped."""
    try:
        from intelligence.services.itemtags import mark_stale_if_changed
        return mark_stale_if_changed(item)
    except Exception:
        logger.exception('intelligence: stale check failed for item %s', item.pk)
        return False


def _enqueue_state_update(attempt):
    try:
        from quiz.models import QuizAttempt

        from intelligence.tasks import update_learner_state_for_attempt
        kind = 'quiz' if isinstance(attempt, QuizAttempt) else 'mock'
        update_learner_state_for_attempt.delay(kind, str(attempt.pk))
    except Exception:
        # Broker down or task missing — the nightly sweep recomputes students
        # whose events are newer than their computed state.
        logger.exception('intelligence: failed to enqueue state update for attempt %s', attempt.pk)
