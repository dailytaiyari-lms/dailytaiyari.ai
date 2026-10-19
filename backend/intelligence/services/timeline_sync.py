"""Timeline sync: attach one browser session's raw events to its attempt.

Attempt resolution mirrors the submit endpoints: rich mocks and practice
sets send their id; quizzes and legacy mocks/PYPs send their parent (quiz or
mock test) id and the student's in-progress attempt is used.
"""
import math
import uuid
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from intelligence.models import AttemptTimeline
from intelligence.services.timeline import TimelineError, clean_events

SYNC_GRACE = timedelta(seconds=120)  # a late flush right after submit still lands
KINDS = ('quiz', 'mock', 'practice')


class TimelineFinalized(TimelineError):
    """Diagnosis already consumed this attempt's timeline."""


def _uuid_or_none(value):
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError:
        raise TimelineError('bad id')


def _open(obj, now):
    """In progress, or finished within the grace window."""
    return obj.completed_at is None or now - obj.completed_at <= SYNC_GRACE


def resolve_attempt(kind, student, *, attempt_id=None, parent_id=None, now=None):
    """Return ``(attempt uuid, anchor datetime, clock)`` or raise TimelineError."""
    from quiz.models import MockTestAttempt, QuizAttempt

    from intelligence.models import PracticeSet

    now = now or timezone.now()
    if kind not in KINDS:
        raise TimelineError('unknown attempt kind')
    attempt_id = _uuid_or_none(attempt_id)
    parent_id = _uuid_or_none(parent_id)

    if kind == 'practice':
        practice_set = (
            PracticeSet.objects.filter(id=attempt_id, student=student).first()
            if attempt_id else None
        )
        if practice_set is None:
            raise TimelineError('practice set not found')
        if practice_set.status not in ('suggested', 'in_progress') and not (
                practice_set.status == 'completed' and _open(practice_set, now)):
            raise TimelineError('practice set is closed')
        return practice_set.id, practice_set.created_at, 'none'

    model = QuizAttempt if kind == 'quiz' else MockTestAttempt
    if attempt_id:
        attempt = model.objects.filter(id=attempt_id, student=student).first()
    elif parent_id:
        parent_field = 'quiz_id' if kind == 'quiz' else 'mock_test_id'
        attempt = (
            model.objects.filter(student=student, status='in_progress',
                                 **{parent_field: parent_id})
            .order_by('-started_at').first()
        )
    else:
        attempt = None
    if attempt is None:
        raise TimelineError('attempt not found')
    if attempt.status != 'in_progress' and not (
            attempt.completed_at and _open(attempt, now)):
        raise TimelineError('attempt is closed')
    # Since #209 the quiz timer is anchored to the attempt's started_at and
    # survives reloads, so quizzes are server-clocked however they resolve.
    # Only the legacy mock/PYP screen (synced by parent_id) restarts its timer
    # per page load; that is the 'client' clock (newest session replaces older).
    clock = 'server' if (kind == 'quiz' or attempt_id) else 'client'
    return attempt.id, attempt.started_at, clock


def _elapsed_or_error(elapsed_ms):
    if isinstance(elapsed_ms, bool) or not isinstance(elapsed_ms, (int, float)):
        raise TimelineError('bad elapsed_ms')
    try:
        elapsed = float(elapsed_ms)
    except OverflowError:
        raise TimelineError('bad elapsed_ms')
    if not math.isfinite(elapsed) or elapsed < 0:
        raise TimelineError('bad elapsed_ms')
    return elapsed


def save_session(*, kind, student, session_id, elapsed_ms, events, truncated,
                 attempt_id=None, parent_id=None, now=None):
    """Validate and store one session snapshot. Returns the AttemptTimeline."""
    now = now or timezone.now()
    if not isinstance(session_id, str) or not 1 <= len(session_id) <= 64:
        raise TimelineError('bad session id')
    elapsed = _elapsed_or_error(elapsed_ms)
    cleaned = clean_events(events)
    resolved_id, anchor, clock = resolve_attempt(
        kind, student, attempt_id=attempt_id, parent_id=parent_id, now=now,
    )
    offset_ms = max(0.0, (now - anchor).total_seconds() * 1000.0 - elapsed)
    stored_events = [
        [t, code, key] + ([value] if value is not None else [])
        for t, code, key, value in cleaned
    ]

    with transaction.atomic():
        row, _created = AttemptTimeline.objects.select_for_update().get_or_create(
            attempt_kind=kind, attempt_id=resolved_id,
            defaults={'student': student, 'tenant': student.user.tenant, 'clock': clock},
        )
        if row.student_id != student.id:
            raise TimelineError('attempt not found')
        if row.finalized_at is not None:
            raise TimelineFinalized('attempt already diagnosed')
        sessions = dict(row.sessions or {})
        if clock == 'client' and session_id not in sessions:
            # The client timer restarted with the page; older sessions are void.
            sessions = {}
        sessions[session_id] = {
            'offset_ms': round(offset_ms, 1),
            'events': stored_events,
            'received_at': now.isoformat(),
            'truncated': bool(truncated),
        }
        row.sessions = sessions
        row.clock = clock
        row.save(update_fields=['sessions', 'clock', 'updated_at'])
    return row
