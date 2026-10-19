"""Response diagnosis rules — why a mark was won or lost (pure functions).

No database and no LLM: ``classify`` turns gathered facts into exactly one
label with a confidence and machine-readable evidence; ``reconcile`` folds
in the student's own "what happened?" answer. Facts are gathered by
``services.diagnose``. Rule order and thresholds are the spec (§4).
"""
import math
from dataclasses import dataclass, field

from intelligence.diagnosis_config import (
    DEFAULT_USUAL_S, MCQ_TYPES, SELF_REPORT_LABEL, THRESHOLDS as T, TIMELESS_TYPES,
)


@dataclass
class ItemFacts:
    item_type: str
    difficulty: str = 'medium'
    usual_s: float | None = None        # ItemStats median, only when trustworthy
    answered: bool = False
    score_fraction: float = 0.0
    numeric_value: float | None = None
    numeric_correct: float | None = None
    numeric_tolerance: float = 0.0
    misconception_pick: bool = False
    prior_mastery: float | None = None
    prior_confidence: str | None = None
    pending_grade: bool = False


@dataclass
class TimingFacts:
    active_s: float = 0.0
    visits: int = 0
    first_answer_s: float | None = None
    final_answer_at_s: float | None = None
    first_enter_at_s: float | None = None
    hidden_s: float = 0.0
    answer_correctness: list = field(default_factory=list)  # graded digests, in order


@dataclass
class WindowFacts:
    duration_s: float | None = None     # None / 0 → untimed
    elapsed_s: float | None = None      # window-relative submit time
    timed_out: bool = False


@dataclass
class Diagnosis:
    label: str
    confidence: str
    flags: list
    evidence: list
    metrics: dict


def usual_seconds(facts):
    """(seconds this item usually takes, where that number came from)."""
    if facts.usual_s:
        return float(facts.usual_s), 'stats'
    if facts.item_type in TIMELESS_TYPES:
        return None, 'none'
    table = DEFAULT_USUAL_S.get(facts.item_type, DEFAULT_USUAL_S['mcq'])
    return table.get(facts.difficulty or 'medium', table['medium']), 'default'


def _round_sig(value, digits):
    return round(value, digits - 1 - int(math.floor(math.log10(abs(value)))))


def slip_match(value, correct, tolerance):
    """Does a wrong numerical answer equal the right one under a common slip?"""
    if value is None or correct is None or value == 0 or correct == 0:
        return False
    candidates = [-correct]
    for power in (1, 2, 3):
        candidates += [correct * 10 ** power, correct / 10 ** power]
    for factor in (60, 100, 1000, 3600):
        candidates += [correct * factor, correct / factor]
    for digits in (1, 2, 3):
        rounded = _round_sig(correct, digits)
        if rounded != correct:
            candidates.append(rounded)
    return any(
        abs(value - candidate) <= max(abs(tolerance), abs(candidate) * 1e-9)
        for candidate in candidates
    )


def _r(value):
    return round(value, 1) if value is not None else None


def _mastery_known(facts):
    return facts.prior_mastery is not None and facts.prior_confidence in ('medium', 'high')


def _near_threshold(rel, usual):
    cuts = (
        max(T['too_fast_floor_s'] / usual, T['too_fast_ratio']),
        T['too_long_ratio'],
        T['rushed_ratio'],
    )
    return any(abs(rel - cut) <= T['near_threshold_band'] * cut for cut in cuts)


def _label(facts, timing, window, flags, rel, zone):
    """(label, confidence, decided_by_time) — first matching rule wins."""
    has = set(flags).__contains__
    fast_confidence = 'high' if facts.usual_s else 'medium'

    if facts.pending_grade:
        return 'unclear', 'low', False

    if not facts.answered:
        if timing is None:
            return 'unclear', 'low', False
        if timing.visits == 0 or timing.active_s < T['not_seen_active_s']:
            return 'not_seen', 'high', False
        if window.duration_s:
            ended_late = window.timed_out or (
                window.elapsed_s is not None and window.duration_s - window.elapsed_s <= zone
            )
            late_entry = (
                timing.first_enter_at_s is not None
                and timing.first_enter_at_s >= window.duration_s * (1 - T['late_entry_ratio'])
            )
            short = rel is not None and rel < T['unanswered_short_ratio']
            if ended_late and (late_entry or short):
                return 'time_pressure', 'medium', True
        return 'skipped', 'medium', False

    if facts.score_fraction >= 0.5:
        if facts.item_type in MCQ_TYPES and has('too_fast'):
            return 'correct_lucky', fast_confidence, True
        if has('too_long'):
            return 'correct_slow', 'medium', True
        return 'correct', 'high', False

    if has('too_fast'):
        return 'guess', fast_confidence, True
    if has('right_to_wrong'):
        return 'second_guess', 'high', False
    if has('rushed'):
        return 'time_pressure', 'medium', True
    if has('slip_match'):
        return 'careless_slip', 'high', False

    known = _mastery_known(facts)
    strong = known and facts.prior_mastery >= T['slip_mastery'] and not has('misconception_pick')
    if strong and has('too_long'):
        return 'unclear', 'low', False   # strong on paper, yet struggled: conflict
    if strong and (rel is None or T['slip_speed_min'] <= rel <= T['slip_speed_max']):
        return 'careless_slip', 'medium', False
    if (known and facts.prior_mastery < T['gap_mastery']) or has('misconception_pick'):
        return 'concept_gap', 'medium', False
    if has('too_long'):
        return 'concept_gap', 'medium', True
    return 'unclear', 'low', False


def classify(facts, timing, window):
    """Facts → Diagnosis. ``timing`` is None when there is no usable timeline."""
    flags, evidence = [], []
    usual, source = usual_seconds(facts)
    metrics = {'usual_s': usual, 'usual_source': source}
    zone = None
    if window.duration_s:
        zone = max(T['last_minute_floor_s'], T['last_minute_ratio'] * window.duration_s)
    rel = None

    def flag(code, detail=''):
        flags.append(code)
        evidence.append({'code': code, 'detail': detail})

    if timing is None:
        evidence.append({'code': 'no_timeline', 'detail': 'no interaction timeline for this item'})
    else:
        metrics.update({
            'active_s': _r(timing.active_s), 'visits': timing.visits,
            'hidden_s': _r(timing.hidden_s), 'first_answer_s': _r(timing.first_answer_s),
            'final_answer_at_s': _r(timing.final_answer_at_s),
        })
        if usual:
            rel = timing.active_s / usual
            metrics['rel_speed'] = round(rel, 3)
            fast_cut = max(T['too_fast_floor_s'], T['too_fast_ratio'] * usual)
            if facts.answered and timing.active_s < fast_cut:
                flag('too_fast', f'{timing.active_s:.0f}s on screen; usually {usual:.0f}s')
            if timing.active_s > T['too_long_ratio'] * usual:
                flag('too_long', f'{timing.active_s:.0f}s on screen; usually {usual:.0f}s')
        if zone is not None and timing.final_answer_at_s is not None:
            time_left = window.duration_s - timing.final_answer_at_s
            metrics['time_left_s'] = _r(time_left)
            if time_left <= zone:
                flag('last_minute', f'answered with {max(0.0, time_left):.0f}s left')
                if rel is not None and rel < T['rushed_ratio']:
                    flag('rushed', f'{rel:.0%} of the usual time')
        graded = timing.answer_correctness
        if facts.answered and len(graded) >= 2:
            earlier = graded[:-1]
            final_correct = facts.score_fraction >= 0.5
            if not final_correct and any(earlier):
                flag('right_to_wrong', 'changed a correct answer to a wrong one')
            if final_correct and not all(earlier):
                flag('wrong_to_right', 'corrected an earlier wrong answer')
        if timing.hidden_s > 0:
            flag('tab_hidden', f'{timing.hidden_s:.0f}s with the tab hidden')
        if window.elapsed_s and timing.final_answer_at_s is not None:
            third = min(3, 1 + int(3 * timing.final_answer_at_s / window.elapsed_s))
            metrics['third'] = max(1, third)
            if third >= 3:
                flag('late_third', 'answered in the last third of the attempt')

    wrong = facts.answered and facts.score_fraction < 0.5 and not facts.pending_grade
    if wrong and slip_match(facts.numeric_value, facts.numeric_correct, facts.numeric_tolerance):
        flag('slip_match', f'{facts.numeric_value:g} vs {facts.numeric_correct:g}')
    if wrong and facts.misconception_pick:
        flag('misconception_pick', 'picked the same wrong option before')
    if facts.prior_mastery is not None:
        metrics['prior_mastery'] = round(facts.prior_mastery, 4)
        evidence.append({'code': 'prior_mastery',
                         'detail': f'{facts.prior_mastery:.2f} ({facts.prior_confidence})'})

    label, confidence, by_time = _label(facts, timing, window, flags, rel, zone)
    if by_time and confidence != 'low' and source == 'default' and rel is not None \
            and _near_threshold(rel, usual):
        confidence = 'low'
    return Diagnosis(label, confidence, flags, evidence, metrics)


def reconcile(label, confidence, flags, self_report, timed_out):
    """The label to act on, once the student's self-report is known.

    A confident classifier label stands. An unclear/low one adopts the
    report, unless behaviour makes the report implausible.
    """
    if not self_report or self_report not in SELF_REPORT_LABEL:
        return label
    if label != 'unclear' and confidence != 'low':
        return label
    if self_report == 'slipped' and 'too_fast' in flags:
        return label
    if self_report == 'ran_out_of_time' and not ('last_minute' in flags or timed_out):
        return label
    return SELF_REPORT_LABEL[self_report]
