"""LearnerConceptState recomputation — the inference layer.

Pure recompute over the event log: given the same events, the same state
comes out, whatever ran before. No LLM anywhere in this path.

Pedagogical grounding, deliberately simple and inspectable:
- mastery      recency-decayed weighted mean with a Laplace prior, so one
               lucky answer can't read as mastery and old evidence fades;
- retention    a spacing model — memory stability grows when recall succeeds
               after a *gap* (spacing effect) and halves on failure; predicted
               recall decays exponentially against that stability;
- transfer     single-concept vs multi-concept performance split, which is
               what detects "applies concepts individually, can't combine
               them";
- misconceptions  repeated picks of the same wrong option.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from django.utils import timezone

from intelligence.models import ConceptLink, LearnerConceptState, LearningEvent
from intelligence.versions import STATE_MODEL_VERSION

HALF_LIFE_DAYS = 30.0        # mastery evidence half-life
PRIOR_ALPHA = 3.0            # Laplace prior strength (pseudo-observations)
PRIOR_MEAN = 0.5
STABILITY_GROWTH = 0.6       # spacing-effect gain per successful spaced recall
STABILITY_GROWTH_CAP = 2.0   # max Δ/S credited per recall
TRANSFER_WINDOW_DAYS = 90
TRANSFER_MIN_N = 5
TRANSFER_GAP_FLAG = 0.25
RETENTION_FLAG = 0.7
CONFIDENCE_MEDIUM = 3.0
CONFIDENCE_HIGH = 10.0


@dataclass
class _Observation:
    """One deduplicated graded response, as the algorithm sees it."""
    occurred_at: datetime
    score: float             # score_fraction in [0, 1]
    link_weight: float
    is_multi: bool
    item_ref: str            # stable id of the item, for misconception keys
    selected: list = field(default_factory=list)  # wrong-pick option indices


def _item_maps(concept):
    """(question ids, mock item ids, weight per item, multi-ness per item)."""
    weights = {}
    question_ids, mock_item_ids = [], []
    for link in ConceptLink.objects.filter(concept=concept):
        if link.question_id:
            question_ids.append(link.question_id)
            weights[('q', link.question_id)] = link.weight
        else:
            mock_item_ids.append(link.mock_item_id)
            weights[('m', link.mock_item_id)] = link.weight
    return question_ids, mock_item_ids, weights


def _multi_map(question_ids, mock_item_ids):
    """Item → True when it links ≥2 concepts (a genuine cross-concept item)."""
    multi = {}
    for arm, ids in (('question', question_ids), ('mock_item', mock_item_ids)):
        counts = defaultdict(int)
        for value in ConceptLink.objects.filter(**{f'{arm}__in': ids}).values_list(
                f'{arm}_id', flat=True):
            counts[value] += 1
        key = 'q' if arm == 'question' else 'm'
        for item_id, count in counts.items():
            multi[(key, item_id)] = count >= 2
    return multi


def _cognitive_multi(event):
    item = event.mock_item or event.question
    return bool(item and item.cognitive_type == 'multi_concept')


def _selected_indices(event):
    """Wrong-pick option indices from the response digest, if MCQ-like."""
    digest = event.response_digest or {}
    picks = []
    if isinstance(digest.get('selected'), list):
        picks = [i for i in digest['selected'] if isinstance(i, int)]
    else:
        raw = digest.get('selected_option')
        if isinstance(raw, str) and raw.strip().isdigit():
            picks = [int(raw.strip())]
    return picks


def observations_for(student, concept):
    """Latest-per-answer observations of this student on this concept."""
    question_ids, mock_item_ids, weights = _item_maps(concept)
    if not question_ids and not mock_item_ids:
        return []
    multi_by_links = _multi_map(question_ids, mock_item_ids)

    events = (
        LearningEvent.objects.filter(student=student)
        .filter(_items_condition(question_ids, mock_item_ids))
        .select_related('question', 'mock_item')
        .order_by('occurred_at', 'created_at')
    )

    # Latest event per source answer: the dedup_key minus its grade marker is a
    # stable per-answer handle even if the answer row was deleted.
    latest = {}
    for event in events:
        latest[event.dedup_key.rsplit(':', 1)[0]] = event

    observations = []
    for event in sorted(latest.values(), key=lambda e: (e.occurred_at, e.created_at)):
        if event.question_id:
            item_key = ('q', event.question_id)
        elif event.mock_item_id:
            item_key = ('m', event.mock_item_id)
        else:
            continue  # item deleted — no link weight to attribute
        observations.append(_Observation(
            occurred_at=event.occurred_at,
            score=max(0.0, min(1.0, event.score_fraction)),
            link_weight=weights.get(item_key, 1.0),
            is_multi=multi_by_links.get(item_key, False) or _cognitive_multi(event),
            item_ref=str(item_key[1]),
            selected=_selected_indices(event) if event.score_fraction < 0.5 else [],
        ))
    return observations


def _items_condition(question_ids, mock_item_ids):
    from django.db.models import Q

    condition = Q(pk__in=[])
    if question_ids:
        condition |= Q(question_id__in=question_ids)
    if mock_item_ids:
        condition |= Q(mock_item_id__in=mock_item_ids)
    return condition


def compute_state_fields(observations, now=None):
    """Pure function: observations → the LearnerConceptState field dict."""
    now = now or timezone.now()
    if not observations:
        return None

    # ── mastery: recency-decayed weighted mean with a prior ────────────────
    weight_sum = 0.0
    weighted_score = 0.0
    for obs in observations:
        age_days = max(0.0, (now - obs.occurred_at).total_seconds() / 86400.0)
        weight = (0.5 ** (age_days / HALF_LIFE_DAYS)) * obs.link_weight
        weight_sum += weight
        weighted_score += weight * obs.score
    mastery = (weighted_score + PRIOR_ALPHA * PRIOR_MEAN) / (weight_sum + PRIOR_ALPHA)

    # ── retention: stability walk over the exposure sequence ───────────────
    stability = 1.0
    previous_at = None
    streak = 0
    for obs in observations:
        if previous_at is not None:
            gap_days = max(0.0, (obs.occurred_at - previous_at).total_seconds() / 86400.0)
            if obs.score >= 0.5:
                stability *= 1.0 + STABILITY_GROWTH * min(gap_days / stability, STABILITY_GROWTH_CAP)
            else:
                stability = max(1.0, 0.5 * stability)
        previous_at = obs.occurred_at
        streak = streak + 1 if obs.score >= 0.5 else 0
    days_since_seen = max(0.0, (now - observations[-1].occurred_at).total_seconds() / 86400.0)
    retention = 2.0 ** (-days_since_seen / stability)

    # ── transfer split (recent window) ──────────────────────────────────────
    buckets = {False: [0, 0.0, 0.0], True: [0, 0.0, 0.0]}  # n, w_sum, wx_sum
    for obs in observations:
        age_days = (now - obs.occurred_at).total_seconds() / 86400.0
        if age_days > TRANSFER_WINDOW_DAYS:
            continue
        weight = 0.5 ** (max(0.0, age_days) / HALF_LIFE_DAYS)
        bucket = buckets[obs.is_multi]
        bucket[0] += 1
        bucket[1] += weight
        bucket[2] += weight * obs.score
    single_n, single_w, single_wx = buckets[False]
    multi_n, multi_w, multi_wx = buckets[True]
    transfer_gap = None
    if single_n >= TRANSFER_MIN_N and multi_n >= TRANSFER_MIN_N and single_w and multi_w:
        transfer_gap = (single_wx / single_w) - (multi_wx / multi_w)

    # ── misconceptions: repeated wrong picks of the same option ────────────
    misconceptions = defaultdict(int)
    for obs in observations:
        for index in obs.selected:
            misconceptions[f'{obs.item_ref}:{index}'] += 1

    flags = []
    if mastery >= 0.7 and transfer_gap is not None and transfer_gap >= TRANSFER_GAP_FLAG:
        flags.append('weak_transfer')
    if mastery >= 0.6 and retention < RETENTION_FLAG:
        flags.append('fading_retention')
    if any(count >= 2 for count in misconceptions.values()):
        flags.append('repeat_misconception')

    if weight_sum < CONFIDENCE_MEDIUM:
        confidence = 'low'
    elif weight_sum < CONFIDENCE_HIGH:
        confidence = 'medium'
    else:
        confidence = 'high'

    return {
        'mastery': round(mastery, 4),
        'evidence_count': len(observations),
        'effective_evidence': round(weight_sum, 4),
        'confidence': confidence,
        'first_seen_at': observations[0].occurred_at,
        'last_seen_at': observations[-1].occurred_at,
        'stability_days': round(stability, 3),
        'retention': round(retention, 4),
        'correct_streak': streak,
        'single_attempts': single_n,
        'single_correct_w': round(single_wx, 4),
        'multi_attempts': multi_n,
        'multi_correct_w': round(multi_wx, 4),
        'transfer_gap': round(transfer_gap, 4) if transfer_gap is not None else None,
        'misconception_counts': dict(misconceptions),
        'flags': flags,
        'model_version': STATE_MODEL_VERSION,
        'computed_at': now,
    }


def recompute_state(student, concept, now=None):
    """Recompute (and persist) one (student, concept) state row."""
    fields = compute_state_fields(observations_for(student, concept), now=now)
    if fields is None:
        LearnerConceptState.objects.filter(student=student, concept=concept).delete()
        return None
    state, _created = LearnerConceptState.objects.update_or_create(
        student=student, concept=concept,
        defaults={'tenant': student.user.tenant, **fields},
    )
    return state


def concepts_touched_by_attempt(attempt):
    """Distinct concepts linked to any item answered in this attempt."""
    from quiz.models import QuizAttempt

    question_ids = list(attempt.answers.values_list('question_id', flat=True))
    mock_item_ids = []
    if not isinstance(attempt, QuizAttempt):
        mock_item_ids = list(attempt.item_answers.values_list('item_id', flat=True))
    if not question_ids and not mock_item_ids:
        return set()
    links = (
        ConceptLink.objects.filter(_items_condition(question_ids, mock_item_ids))
        .select_related('concept')
    )
    return {link.concept for link in links}


def update_for_attempt(kind, attempt_id):
    """Recompute every concept this attempt touched. Idempotent."""
    from quiz.models import MockTestAttempt, QuizAttempt

    model = QuizAttempt if kind == 'quiz' else MockTestAttempt
    attempt = model.objects.filter(id=attempt_id).select_related('student__user').first()
    if attempt is None:
        return 0
    concepts = concepts_touched_by_attempt(attempt)
    for concept in concepts:
        recompute_state(attempt.student, concept)
    return len(concepts)
