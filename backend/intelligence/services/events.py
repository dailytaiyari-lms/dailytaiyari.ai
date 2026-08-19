"""LearningEvent emission — the observation layer.

Events are appended with ``bulk_create(ignore_conflicts=True)`` against a
unique ``dedup_key``, so every function here is idempotent: calling it twice
for the same attempt is a no-op. A manual regrade appends a *superseding* row
rather than mutating; consumers take the latest event per source answer.
"""
import logging

from django.utils import timezone

from intelligence.models import LearningEvent
from intelligence.versions import EVENT_SCHEMA_VERSION

logger = logging.getLogger(__name__)


def _clamp01(value):
    return max(0.0, min(1.0, value))


def _bank_event_fields(answer):
    """Common fields for a bank-question Answer row (quiz or mock)."""
    question = answer.question
    max_marks = question.marks
    return {
        'question': question,
        'mock_item': None,
        'topic': question.topic,
        'subject': question.subject,
        'is_correct': answer.is_correct,
        # Bank grading is binary; negative marking must not push mastery
        # evidence below zero.
        'score_fraction': 1.0 if answer.is_correct else 0.0,
        'marks_obtained': answer.marks_obtained,
        'max_marks': max_marks,
        'time_taken_seconds': answer.time_taken_seconds,
        'response_digest': {
            'selected_option': answer.selected_option,
            'answer_text': answer.answer_text[:200] if answer.answer_text else '',
            'numerical': str(answer.numerical_answer) if answer.numerical_answer is not None else None,
        },
    }


def _item_event_fields(item_answer):
    """Common fields for an inline MockTestAnswer row."""
    item = item_answer.item
    max_marks = item_answer.max_marks or item.marks
    if item_answer.needs_manual_grading:
        # Ungraded subjective answer: no mastery signal yet; the regrade
        # event will supersede this row.
        score = 0.0
    elif max_marks and float(max_marks) > 0:
        # Partial credit (coding, graded subjective).
        score = _clamp01(float(item_answer.marks_obtained) / float(max_marks))
    else:
        score = 1.0 if item_answer.is_correct else 0.0
    digest = {'selected': item_answer.selected_options or []}
    if item_answer.numerical_answer is not None:
        digest['numerical'] = str(item_answer.numerical_answer)
    if item_answer.needs_manual_grading:
        digest['needs_manual'] = True
    return {
        'question': None,
        'mock_item': item,
        'topic': item.topic,
        'subject': item.subject,
        'is_correct': item_answer.is_correct,
        'score_fraction': score,
        'marks_obtained': item_answer.marks_obtained,
        'max_marks': max_marks,
        'time_taken_seconds': item_answer.time_taken_seconds,
        'response_digest': digest,
    }


def _event(student, tenant, source_type, occurred_at, attempt_kind, attempt_id,
           dedup_key, event_kind='graded', **fields):
    return LearningEvent(
        student=student,
        tenant=tenant,
        source_type=source_type,
        event_kind=event_kind,
        occurred_at=occurred_at,
        attempt_kind=attempt_kind,
        attempt_id=attempt_id,
        dedup_key=dedup_key,
        schema_version=EVENT_SCHEMA_VERSION,
        **fields,
    )


def events_for_quiz_attempt(attempt):
    """Build (unsaved) events for a completed QuizAttempt."""
    student = attempt.student
    tenant = student.user.tenant
    occurred_at = attempt.completed_at or timezone.now()
    return [
        _event(
            student, tenant, LearningEvent.SOURCE_QUIZ_ANSWER, occurred_at,
            'quiz', attempt.id,
            f'{LearningEvent.SOURCE_QUIZ_ANSWER}:{answer.id}:0',
            answer=answer,
            **_bank_event_fields(answer),
        )
        for answer in attempt.answers.select_related('question__topic', 'question__subject')
    ]


def events_for_mock_attempt(attempt):
    """Build (unsaved) events for a completed/timed-out MockTestAttempt."""
    student = attempt.student
    tenant = student.user.tenant
    occurred_at = attempt.completed_at or timezone.now()
    events = [
        _event(
            student, tenant, LearningEvent.SOURCE_MOCK_BANK_ANSWER, occurred_at,
            'mock', attempt.id,
            f'{LearningEvent.SOURCE_MOCK_BANK_ANSWER}:{answer.id}:0',
            answer=answer,
            **_bank_event_fields(answer),
        )
        for answer in attempt.answers.select_related('question__topic', 'question__subject')
    ]
    events += [
        _event(
            student, tenant, LearningEvent.SOURCE_MOCK_ITEM_ANSWER, occurred_at,
            'mock', attempt.id,
            f'{LearningEvent.SOURCE_MOCK_ITEM_ANSWER}:{item_answer.id}:0',
            item_answer=item_answer,
            **_item_event_fields(item_answer),
        )
        for item_answer in attempt.item_answers.select_related('item__topic', 'item__subject')
    ]
    return events


def record_attempt_events(attempt):
    """Persist events for a finalized attempt (idempotent). Returns count built."""
    from quiz.models import QuizAttempt

    if isinstance(attempt, QuizAttempt):
        events = events_for_quiz_attempt(attempt)
    else:
        events = events_for_mock_attempt(attempt)
    if events:
        LearningEvent.objects.bulk_create(events, ignore_conflicts=True)
    return len(events)


def record_regrade_event(item_answer):
    """Append a superseding event after a manual (re)grade of an inline answer.

    Keyed by ``graded_at`` so grading the same answer twice produces two
    distinct superseding rows, the latest of which wins.
    """
    if not item_answer.graded_at:
        return None
    attempt = item_answer.attempt
    student = attempt.student
    marker = int(item_answer.graded_at.timestamp())
    fields = _item_event_fields(item_answer)
    # A graded answer no longer pends; recompute score from awarded marks.
    fields['response_digest'].pop('needs_manual', None)
    event = _event(
        student, student.user.tenant, LearningEvent.SOURCE_MOCK_ITEM_ANSWER,
        item_answer.graded_at, 'mock', attempt.id,
        f'{LearningEvent.SOURCE_MOCK_ITEM_ANSWER}:{item_answer.id}:{marker}',
        event_kind='regraded',
        item_answer=item_answer,
        **fields,
    )
    LearningEvent.objects.bulk_create([event], ignore_conflicts=True)
    return event
