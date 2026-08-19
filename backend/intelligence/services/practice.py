"""Practice session mechanics: answer grading, submission, evidence, XP.

Practice is formative — each answer is graded immediately and explained.
Completed sets feed the same event log as exams (at a lower evidence weight,
handled in the state service), so the diagnosis the set came from updates
as soon as it's done.
"""
import logging
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db.models import F
from django.utils import timezone

from intelligence.models import GeneratedItem, LearningEvent, PracticeSet
from intelligence.versions import EVENT_SCHEMA_VERSION

logger = logging.getLogger(__name__)

PRACTICE_SET_XP = 10


class PracticeError(Exception):
    """User-facing practice flow error."""


def _correct_indices(question):
    return [i for i, option in enumerate(question.options.order_by('order'))
            if option.is_correct]


def grade_practice_answer(item, *, selected_options=None, numerical_answer=None):
    """Grade one PracticeSetItem in place (does not save). Returns is_correct."""
    question = item.question
    item.answered_at = timezone.now()

    if question.question_type in ('mcq', 'mcq_multi'):
        selected = sorted(int(i) for i in (selected_options or []))
        item.selected_options = selected
        item.is_correct = bool(selected) and selected == sorted(_correct_indices(question))
    elif question.question_type == 'numerical':
        try:
            value = Decimal(str(numerical_answer))
        except (InvalidOperation, TypeError, ValueError):
            value = None
        item.numerical_answer = value
        item.is_correct = bool(
            value is not None and question.numerical_answer is not None
            and abs(value - question.numerical_answer) <= question.numerical_tolerance
        )
    else:
        raise PracticeError('This question type is not supported in practice.')
    return item.is_correct


def answer_item(practice_set, item_id, *, selected_options=None, numerical_answer=None,
                time_taken_seconds=0):
    """Grade and store one answer; returns the review payload for the UI."""
    if practice_set.status not in ('suggested', 'in_progress'):
        raise PracticeError('This practice set is no longer active.')
    if practice_set.status == 'suggested':
        start_set(practice_set)

    item = practice_set.items.select_related('question').filter(id=item_id).first()
    if item is None:
        raise PracticeError('Question not found in this set.')
    if item.answered_at is not None:
        raise PracticeError('This question was already answered.')

    grade_practice_answer(
        item, selected_options=selected_options, numerical_answer=numerical_answer,
    )
    item.time_taken_seconds = max(0, int(time_taken_seconds or 0))
    item.save()

    question = item.question
    return {
        'item_id': str(item.id),
        'is_correct': item.is_correct,
        'correct_options': _correct_indices(question),
        'correct_numerical': (
            str(question.numerical_answer) if question.numerical_answer is not None else None
        ),
        'explanation': question.explanation or '',
    }


def start_set(practice_set):
    if practice_set.status == 'suggested':
        practice_set.status = 'in_progress'
        practice_set.started_at = timezone.now()
        practice_set.save(update_fields=['status', 'started_at', 'updated_at'])
    return practice_set


def _emit_events(practice_set):
    student = practice_set.student
    tenant = student.user.tenant
    events = []
    for item in practice_set.items.select_related(
            'question__topic', 'question__subject').filter(answered_at__isnull=False):
        question = item.question
        digest = {}
        if item.selected_options:
            digest['selected'] = item.selected_options
        if item.numerical_answer is not None:
            digest['numerical'] = str(item.numerical_answer)
        events.append(LearningEvent(
            student=student,
            tenant=tenant,
            source_type=LearningEvent.SOURCE_PRACTICE_ANSWER,
            event_kind='graded',
            question=question,
            topic=question.topic,
            subject=question.subject,
            attempt_kind='practice',
            attempt_id=practice_set.id,
            occurred_at=item.answered_at,
            is_correct=bool(item.is_correct),
            score_fraction=1.0 if item.is_correct else 0.0,
            marks_obtained=1 if item.is_correct else 0,
            max_marks=1,
            time_taken_seconds=item.time_taken_seconds,
            response_digest=digest,
            dedup_key=f'{LearningEvent.SOURCE_PRACTICE_ANSWER}:{item.id}:0',
            schema_version=EVENT_SCHEMA_VERSION,
        ))
    if events:
        LearningEvent.objects.bulk_create(events, ignore_conflicts=True)
    return len(events)


def _award_set_xp(practice_set):
    """Flat XP per completed set, capped per day — practice serves warm-ups
    below ability on purpose, so accuracy-scaled XP would be farmable."""
    from gamification.services import GamificationService

    from intelligence.recommendation import practice_config_for

    if practice_set.course is None:
        return 0
    config = practice_config_for(practice_set.course)
    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    rewarded_today = PracticeSet.objects.filter(
        student=practice_set.student, completed_at__gte=today_start, xp_awarded__gt=0,
    ).exclude(id=practice_set.id).count()
    if rewarded_today >= config.daily_xp_set_cap:
        return 0
    GamificationService.award_xp(
        practice_set.student, PRACTICE_SET_XP, 'practice_complete',
        'Completed a practice set', str(practice_set.id),
    )
    return PRACTICE_SET_XP


def submit_set(practice_set):
    """Finalize a set: score, events, learner-state refresh, XP, next steps."""
    if practice_set.status == 'completed':
        raise PracticeError('This practice set was already submitted.')
    if practice_set.status not in ('suggested', 'in_progress'):
        raise PracticeError('This practice set is no longer active.')

    answered = practice_set.items.filter(answered_at__isnull=False)
    if not answered.exists():
        raise PracticeError('Answer at least one question before submitting.')

    before = _mastery_snapshot(practice_set)

    practice_set.score_total = answered.count()
    practice_set.score_correct = answered.filter(is_correct=True).count()
    practice_set.status = 'completed'
    practice_set.completed_at = timezone.now()
    practice_set.xp_awarded = _award_set_xp(practice_set)
    practice_set.save()

    GeneratedItem.objects.filter(
        question_id__in=answered.values_list('question_id', flat=True),
    ).update(times_answered=F('times_answered') + 1)

    _emit_events(practice_set)

    # Refresh every concept this set actually touched, synchronously — the
    # student is looking at the "what changed" screen right now. Derived from
    # the answered questions' links (not just target_concepts) so starter
    # sets, which target no concept, still seed learner state.
    from intelligence.models import ConceptLink
    from intelligence.services import state as state_service

    touched = {
        link.concept
        for link in ConceptLink.objects.filter(
            question_id__in=answered.values_list('question_id', flat=True),
        ).select_related('concept')
    } | set(practice_set.target_concepts.all())
    for concept in touched:
        state_service.recompute_state(practice_set.student, concept)

    after = _mastery_snapshot(practice_set)

    # New evidence may retire or reshuffle the remaining suggestions.
    try:
        from intelligence.tasks import recompute_recommendations
        recompute_recommendations.delay(
            str(practice_set.student_id), str(practice_set.course_id) if practice_set.course_id else None,
        )
    except Exception:
        logger.exception('practice: failed to enqueue recommendation refresh')

    return {
        'score_correct': practice_set.score_correct,
        'score_total': practice_set.score_total,
        'xp_awarded': practice_set.xp_awarded,
        'mastery_before': before,
        'mastery_after': after,
    }


def _mastery_snapshot(practice_set):
    from intelligence.models import LearnerConceptState

    return {
        str(row.concept_id): round(row.mastery, 3)
        for row in LearnerConceptState.objects.filter(
            student=practice_set.student,
            concept__in=practice_set.target_concepts.all(),
        )
    }
