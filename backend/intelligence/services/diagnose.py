"""Gather classifier facts for every item of a finished attempt and persist
ResponseDiagnosis rows. The judgment itself lives in ``services.diagnosis``
(pure); this module only collects facts — grading, timeline, prior mastery,
item statistics — and writes results. Idempotent: a rerun overwrites.
"""
from dataclasses import dataclass

from django.utils import timezone

from intelligence.diagnosis_config import THRESHOLDS
from intelligence.models import (
    AttemptTimeline, ConceptLink, ItemStats, LearningEvent, ResponseDiagnosis,
    ResponseSelfReport,
)
from intelligence.services import diagnosis as rules
from intelligence.services.timeline import (
    KeyTimeline, valid_sessions, reduce_sessions, window_start_s,
)
from intelligence.versions import CLASSIFIER_VERSION

@dataclass
class _Ref:
    """One item in the attempt plus the student's final answer facts."""
    arm: str                  # 'q' → quiz.Question, 'm' → quiz.MockTestItem
    item: object
    answered: bool
    score_fraction: float
    is_correct: object        # bool | None
    selected: list
    numeric: object           # float | None
    pending: bool = False
    practice: bool = False    # graded by QuestionOption.is_correct, like practice does

    @property
    def key(self):
        return f"{'bank' if self.arm == 'q' else 'item'}:{self.item.id}"

    @property
    def item_type(self):
        return self.item.question_type if self.arm == 'q' else self.item.item_type


@dataclass
class _Loaded:
    student: object
    refs: list
    anchor: object            # datetime the timeline offsets are relative to
    cutoff: object            # prior-mastery cutoff (attempt start)
    ended_at: object
    duration_s: float
    timed_out: bool
    finished: bool


def _f(value):
    return float(value) if value is not None else None


def _bank_ref(question, answer):
    if answer is None:
        return _Ref('q', question, False, 0.0, None, [], None)
    raw = (answer.selected_option or '').strip()
    answered = bool(raw or (answer.answer_text or '').strip()
                    or answer.numerical_answer is not None)
    return _Ref(
        'q', question, answered, 1.0 if answer.is_correct else 0.0,
        answer.is_correct if answered else None,
        [int(raw)] if raw.isdigit() else [], _f(answer.numerical_answer),
    )


def _item_ref(item, answer):
    from intelligence.services.events import item_score_fraction

    if answer is None:
        return _Ref('m', item, False, 0.0, None, [], None)
    answered = bool(answer.selected_options or answer.numerical_answer is not None
                    or (answer.answer_text or '').strip() or (answer.code or '').strip())
    pending = answered and bool(answer.needs_manual_grading)
    return _Ref(
        'm', item, answered, item_score_fraction(answer),
        None if (pending or not answered) else answer.is_correct,
        [i for i in (answer.selected_options or []) if isinstance(i, int)],
        _f(answer.numerical_answer), pending,
    )


def _load(kind, attempt_id):
    from quiz.models import MockTestAttempt, MockTestItem, MockTestQuestion, QuizAttempt

    from intelligence.models import PracticeSet

    if kind == 'quiz':
        attempt = QuizAttempt.objects.filter(id=attempt_id).select_related(
            'quiz', 'student__user').first()
        if attempt is None:
            return None
        answers = {a.question_id: a for a in attempt.answers.all()}
        refs = [_bank_ref(q, answers.get(q.id))
                for q in attempt.quiz.questions.prefetch_related('options')]
        return _Loaded(attempt.student, refs, attempt.started_at, attempt.started_at,
                       attempt.completed_at, float((attempt.quiz.duration_minutes or 0) * 60),
                       attempt.status == 'timed_out', attempt.status != 'in_progress')

    if kind == 'mock':
        attempt = MockTestAttempt.objects.filter(id=attempt_id).select_related(
            'mock_test', 'student__user').first()
        if attempt is None:
            return None
        answers = {a.question_id: a for a in attempt.answers.all()}
        item_answers = {a.item_id: a for a in attempt.item_answers.all()}
        refs = [
            _bank_ref(mtq.question, answers.get(mtq.question_id))
            for mtq in MockTestQuestion.objects.filter(mock_test=attempt.mock_test)
            .select_related('question').prefetch_related('question__options')
        ]
        refs += [_item_ref(item, item_answers.get(item.id))
                 for item in MockTestItem.objects.filter(mock_test=attempt.mock_test)]
        return _Loaded(attempt.student, refs, attempt.started_at, attempt.started_at,
                       attempt.completed_at,
                       float((attempt.mock_test.duration_minutes or 0) * 60),
                       attempt.status == 'timed_out', attempt.status != 'in_progress')

    if kind == 'practice':
        practice_set = PracticeSet.objects.filter(id=attempt_id).select_related(
            'student__user').first()
        if practice_set is None:
            return None
        refs = []
        for set_item in practice_set.items.select_related('question').prefetch_related(
                'question__options'):
            answered = set_item.answered_at is not None
            refs.append(_Ref(
                'q', set_item.question, answered, 1.0 if set_item.is_correct else 0.0,
                set_item.is_correct if answered else None,
                [i for i in (set_item.selected_options or []) if isinstance(i, int)],
                _f(set_item.numerical_answer), practice=True,
            ))
        return _Loaded(practice_set.student, refs, practice_set.created_at,
                       practice_set.started_at or practice_set.created_at,
                       practice_set.completed_at, 0.0, False,
                       practice_set.status == 'completed')
    return None


def _correct_indices(ref):
    item = ref.item
    if ref.arm == 'm':
        return {i for i, option in enumerate(item.options or [])
                if isinstance(option, dict) and option.get('is_correct')}
    if not ref.practice and item.question_type in ('mcq', 'true_false'):
        raw = (item.correct_answer or '').strip()
        return {int(raw)} if raw.isdigit() else set()
    return {i for i, option in enumerate(item.options.all()) if option.is_correct}


def _digest_correct(ref, digest):
    """Grade one intermediate answer digest; None when it can't be graded."""
    if not isinstance(digest, dict):
        return None
    if isinstance(digest.get('sel'), list):
        correct = _correct_indices(ref)
        picks = {i for i in digest['sel'] if isinstance(i, int)}
        return bool(correct) and picks == correct
    if 'num' in digest:
        target = _f(getattr(ref.item, 'numerical_answer', None))
        try:
            value = float(digest['num'])
        except (TypeError, ValueError):
            return None
        if target is None:
            return None
        return abs(value - target) <= float(ref.item.numerical_tolerance or 0)
    return None


def _primary_concept(ref):
    arm = 'question' if ref.arm == 'q' else 'mock_item'
    link = (ConceptLink.objects.filter(**{arm: ref.item}).select_related('concept')
            .order_by('-is_primary', '-weight').first())
    return link.concept if link else None


def _prior_mastery(student, concept, cutoff, cache):
    """(mastery, confidence) from evidence strictly before the attempt."""
    if concept is None:
        return None, None
    if concept.id not in cache:
        from intelligence.services.state import compute_state_fields, observations_for

        prior = [o for o in observations_for(student, concept) if o.occurred_at < cutoff]
        fields = compute_state_fields(prior, now=cutoff)
        cache[concept.id] = (fields['mastery'], fields['confidence']) if fields else (None, None)
    return cache[concept.id]


def _misconception_pick(student, ref, cutoff):
    """Picked this same wrong option on this same item before this attempt."""
    if ref.score_fraction >= THRESHOLDS['correct_score'] or not ref.selected:
        return False
    arm = 'question_id' if ref.arm == 'q' else 'mock_item_id'
    earlier = LearningEvent.objects.filter(
        student=student, occurred_at__lt=cutoff, score_fraction__lt=THRESHOLDS['correct_score'],
        **{arm: ref.item.id},
    ).values_list('response_digest', flat=True)
    from intelligence.services.state import selected_from_digest

    picks = set(ref.selected)
    return any(set(selected_from_digest(digest)) & picks for digest in earlier)


def _usual_from_stats(ref):
    arm = 'question' if ref.arm == 'q' else 'mock_item'
    row = ItemStats.objects.filter(**{arm: ref.item}).values_list(
        'median_active_seconds', 'active_time_n').first()
    if row and row[0] and row[1] >= THRESHOLDS['stats_min_n']:
        return row[0]
    return None


def _timing_for(ref, line, has_sessions, truncated):
    """TimingFacts for one item, or None when its timeline can't be trusted."""
    if not has_sessions:
        return None
    line = line or KeyTimeline()
    if line.visits == 0 and (ref.answered or truncated):
        # Answered but never seen on screen = lost events, not a 0s guess.
        return None
    answered_digests = [d for _at, d in line.answers if d is not None]
    if ref.answered and (not answered_digests or line.answers[-1][1] is None):
        # The tail of the session never arrived (or the answer was cleared):
        # an early visit says nothing about how long the final answer took.
        return None
    graded = [_digest_correct(ref, digest) for _at, digest in line.answers if digest is not None]
    return rules.TimingFacts(
        active_s=line.active_s, visits=line.visits,
        first_answer_s=line.first_answer_active_s,
        final_answer_at_s=line.final_answer_at_s,
        first_enter_at_s=line.first_enter_at_s, hidden_s=line.hidden_s,
        answer_correctness=[c for c in graded if c is not None],
    )


def diagnose_attempt(kind, attempt_id):
    """(Re)diagnose every item of a finished attempt. Returns rows written."""
    loaded = _load(kind, attempt_id)
    if loaded is None or not loaded.finished:
        return 0
    tenant = loaded.student.user.tenant

    timeline = AttemptTimeline.objects.filter(attempt_kind=kind, attempt_id=attempt_id).first()
    now = timezone.now()
    if timeline is not None and timeline.finalized_at is None:
        # Claim the timeline first, so a sync can't land after we read it.
        AttemptTimeline.objects.filter(pk=timeline.pk, finalized_at__isnull=True).update(
            finalized_at=now)
        timeline.refresh_from_db()
    sessions = (timeline.sessions or {}) if timeline else {}
    if sessions and not valid_sessions(sessions):
        sessions = {}     # every stored session is corrupt: no usable timeline
    clock = timeline.clock if timeline else None
    keys = {ref.key for ref in loaded.refs}
    lines = reduce_sessions(sessions, clock=clock, known_keys=keys) if sessions else {}
    truncated = any(isinstance(s, dict) and s.get('truncated') for s in sessions.values())
    offset_s = window_start_s(sessions, clock) if sessions else 0.0

    elapsed_s = None
    if loaded.ended_at:
        elapsed_s = (loaded.ended_at - loaded.anchor).total_seconds() - offset_s
    window = rules.WindowFacts(
        duration_s=loaded.duration_s if (loaded.duration_s and clock != 'none') else None,
        elapsed_s=elapsed_s, timed_out=loaded.timed_out,
    )

    reports = {
        (r.question_id, r.mock_item_id): r.choice
        for r in ResponseSelfReport.objects.filter(attempt_kind=kind, attempt_id=attempt_id)
    }
    mastery_cache = {}
    written = 0
    for ref in loaded.refs:
        mastery, confidence = _prior_mastery(
            loaded.student, _primary_concept(ref), loaded.cutoff, mastery_cache)
        facts = rules.ItemFacts(
            item_type=ref.item_type,
            difficulty=getattr(ref.item, 'difficulty', '') or 'medium',
            usual_s=_usual_from_stats(ref),
            answered=ref.answered, score_fraction=ref.score_fraction,
            numeric_value=ref.numeric,
            numeric_correct=_f(getattr(ref.item, 'numerical_answer', None)),
            numeric_tolerance=float(getattr(ref.item, 'numerical_tolerance', 0) or 0),
            misconception_pick=_misconception_pick(loaded.student, ref, loaded.cutoff),
            prior_mastery=mastery, prior_confidence=confidence,
            pending_grade=ref.pending,
        )
        timing = _timing_for(ref, lines.get(ref.key), bool(sessions), truncated)
        result = rules.classify(facts, timing, window)
        timed_out = loaded.timed_out or bool(result.metrics.get('ended_late'))

        question_id = ref.item.id if ref.arm == 'q' else None
        mock_item_id = ref.item.id if ref.arm == 'm' else None
        self_report = reports.get((question_id, mock_item_id), '')
        lookup = {'attempt_kind': kind, 'attempt_id': attempt_id}
        lookup['question_id' if ref.arm == 'q' else 'mock_item_id'] = ref.item.id
        ResponseDiagnosis.objects.update_or_create(**lookup, defaults={
            'tenant': tenant,
            'student': loaded.student,
            'answered': ref.answered,
            'is_correct': ref.is_correct,
            'score_fraction': ref.score_fraction,
            'metrics': {**result.metrics, 'timed_out': timed_out},
            'flags': result.flags,
            'label': result.label,
            'confidence': result.confidence,
            'evidence': result.evidence,
            'self_report': self_report,
            'final_label': rules.reconcile(result.label, result.confidence, result.flags,
                                           self_report, timed_out),
            'has_timeline': timing is not None,
            'classifier_version': CLASSIFIER_VERSION,
            'computed_at': now,
        })
        written += 1

    return written
