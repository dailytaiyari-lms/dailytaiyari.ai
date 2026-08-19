"""Empirical per-item statistics, recomputed nightly from the event log.

Everything inferential is threshold-gated: discrimination needs n ≥ 30,
difficulty divergence n ≥ 20 — at low volumes the fields stay null/false
rather than radiating noise.
"""
import math
from collections import defaultdict

from django.utils import timezone

from intelligence.models import ItemStats, LearningEvent
from intelligence.versions import ITEM_STATS_VERSION

DISCRIMINATION_MIN_N = 30
DIVERGENCE_MIN_N = 20

# Observed difficulty bands on p-value (share answering correctly).
EASY_P = 0.75
HARD_P = 0.40

_BAND_ORDER = {'easy': 0, 'medium': 1, 'hard': 2}


def _observed_band(p_value):
    if p_value > EASY_P:
        return 'easy'
    if p_value < HARD_P:
        return 'hard'
    return 'medium'


def _latest_per_answer(events):
    latest = {}
    for event in events:
        latest[event.dedup_key.rsplit(':', 1)[0]] = event
    return sorted(latest.values(), key=lambda e: (e.occurred_at, e.created_at))


def _selected_indices(event):
    digest = event.response_digest or {}
    if isinstance(digest.get('selected'), list):
        return [i for i in digest['selected'] if isinstance(i, int)]
    raw = digest.get('selected_option')
    if isinstance(raw, str) and raw.strip().isdigit():
        return [int(raw.strip())]
    return []


def _point_biserial(pairs):
    """Correlation between item correctness (0/1) and attempt percentage."""
    n = len(pairs)
    if n < 2:
        return None
    correct = [c for c, _ in pairs]
    scores = [s for _, s in pairs]
    p = sum(correct) / n
    if p in (0.0, 1.0):
        return None
    mean_all = sum(scores) / n
    std_all = math.sqrt(sum((s - mean_all) ** 2 for s in scores) / n)
    if std_all == 0:
        return None
    mean_correct = sum(s for c, s in pairs if c) / sum(correct)
    return round((mean_correct - mean_all) / std_all * math.sqrt(p / (1 - p)), 4)


def _attempt_percentages(events):
    """{(kind, id): percentage} for every attempt referenced by the events."""
    from quiz.models import MockTestAttempt, QuizAttempt

    wanted = defaultdict(set)
    for event in events:
        if event.attempt_id:
            wanted[event.attempt_kind].add(event.attempt_id)
    percentages = {}
    for kind, model in (('quiz', QuizAttempt), ('mock', MockTestAttempt)):
        for pk, pct in model.objects.filter(id__in=wanted.get(kind, ())).values_list(
                'id', 'percentage'):
            percentages[(kind, pk)] = float(pct)
    return percentages


def recompute_for_item(item, *, now=None):
    """Recompute the ItemStats row for one Question or MockTestItem."""
    from quiz.models import MockTestItem

    arm = 'mock_item' if isinstance(item, MockTestItem) else 'question'
    events = _latest_per_answer(
        LearningEvent.objects.filter(**{f'{arm}_id': item.id}).order_by('occurred_at')
    )
    if not events:
        return None

    attempts_count = len(events)
    correct_count = sum(1 for e in events if e.score_fraction >= 0.5)
    p_value = correct_count / attempts_count
    times = [e.time_taken_seconds for e in events if e.time_taken_seconds]
    option_distribution = defaultdict(int)
    for event in events:
        for index in _selected_indices(event):
            option_distribution[str(index)] += 1

    discrimination = None
    if attempts_count >= DISCRIMINATION_MIN_N:
        percentages = _attempt_percentages(events)
        pairs = [
            (1 if e.score_fraction >= 0.5 else 0, percentages[(e.attempt_kind, e.attempt_id)])
            for e in events
            if (e.attempt_kind, e.attempt_id) in percentages
        ]
        if len(pairs) >= DISCRIMINATION_MIN_N:
            discrimination = _point_biserial(pairs)

    predicted = getattr(item, 'difficulty', '') or ''
    observed = _observed_band(p_value)
    divergence = bool(
        predicted in _BAND_ORDER
        and attempts_count >= DIVERGENCE_MIN_N
        and abs(_BAND_ORDER[predicted] - _BAND_ORDER[observed]) >= 1
    )

    stats, _created = ItemStats.objects.update_or_create(
        **{arm: item},
        defaults={
            'tenant': item.tenant,
            'attempts_count': attempts_count,
            'correct_count': correct_count,
            'p_value': round(p_value, 4),
            'avg_time_seconds': round(sum(times) / len(times), 2) if times else None,
            'option_distribution': dict(option_distribution),
            'discrimination': discrimination,
            'predicted_difficulty': predicted,
            'observed_difficulty': observed,
            'difficulty_divergence': divergence,
            'stats_version': ITEM_STATS_VERSION,
            'computed_at': now or timezone.now(),
        },
    )
    return stats


def recompute_all(*, tenant=None, since=None):
    """Recompute stats for every item that has events (optionally scoped)."""
    from quiz.models import MockTestItem, Question

    events = LearningEvent.objects.all()
    if tenant is not None:
        events = events.filter(tenant=tenant)
    if since is not None:
        events = events.filter(occurred_at__gte=since)

    question_ids = set(
        events.filter(question__isnull=False).values_list('question_id', flat=True).distinct()
    )
    mock_item_ids = set(
        events.filter(mock_item__isnull=False).values_list('mock_item_id', flat=True).distinct()
    )

    now = timezone.now()
    count = 0
    for question in Question.objects.filter(id__in=question_ids).iterator(chunk_size=200):
        if recompute_for_item(question, now=now):
            count += 1
    for item in MockTestItem.objects.filter(id__in=mock_item_ids).iterator(chunk_size=200):
        if recompute_for_item(item, now=now):
            count += 1
    return count
