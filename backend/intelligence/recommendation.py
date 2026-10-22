"""The practice recommendation engine — deficits in, practice sets out.

Pure Python over LearnerConceptState + the tagged question pool. No LLM:
matching is tag algebra, explanations are templates rendered from real
numbers. Every diagnosis sits behind an evidence floor so a student is never
confronted with a confident story built on two data points.
"""
import logging
from datetime import timedelta

from django.db.models import F
from django.utils import timezone

from intelligence.models import (
    CoursePracticeConfig, LearnerConceptState, LearningEvent, PracticeSet, PracticeSetItem,
)

logger = logging.getLogger(__name__)

SET_SIZE = 8
MIN_SET_SIZE = 4
WARMUP_COUNT = 2
STRETCH_COUNT = 1
POOL_HEADROOM = 1.5          # pool must hold 1.5× the set size, else it's "thin"
SEEN_COOLDOWN_DAYS = 21      # don't re-serve an item the student saw recently
SET_TTL_DAYS = 14
MAX_DEFICITS = 3

# Evidence floors per deficit kind.
MIN_OBSERVATIONS = 4

BAND_BELOW = {'easy': 'easy', 'medium': 'easy', 'hard': 'medium'}
BAND_ABOVE = {'easy': 'medium', 'medium': 'hard', 'hard': 'hard'}

REASON_TEMPLATES = {
    'low_mastery': (
        "You've answered {n} questions on {concept} and got {pct}% right. "
        "This set rebuilds it from easier ground up."
    ),
    'retention': (
        "You had {concept} solid, but it's been {days} days without practice. "
        "A quick refresh before it fades."
    ),
    'misconception': (
        "In recent questions on {concept} you repeatedly picked the same kind of "
        "wrong answer. These questions are chosen to surface and correct that."
    ),
    'transfer_gap': (
        "You're strong on {concept} in isolation — this set mixes it with related "
        "ideas the way the exam does."
    ),
    'starter': (
        "Not enough data yet — this starter set covers {course}'s key concepts "
        "so your suggestions get smarter."
    ),
}


def _render_reason(kind, slots):
    template = REASON_TEMPLATES.get(kind, '')
    try:
        text = template.format(**slots)
    except (KeyError, IndexError):
        text = template
    return {'template_key': kind, 'slots': slots, 'text': text}


# ─────────────────────────────────────────────────────────────────────────────
# Deficit extraction
# ─────────────────────────────────────────────────────────────────────────────

def extract_deficits(student, course):
    """Ranked list of deficits for one student in one course.

    Each: {kind, signature, concept, severity, slots} — at most MAX_DEFICITS,
    highest severity first, every one clearing its evidence floor.
    """
    states = (
        LearnerConceptState.objects.filter(
            student=student,
            concept__subject__course=course,
            concept__status='active',
            evidence_count__gte=MIN_OBSERVATIONS,
        )
        .select_related('concept')
    )

    deficits = []
    for state in states:
        concept = state.concept
        if state.mastery < 0.5:
            deficits.append({
                'kind': 'low_mastery',
                'signature': f'mastery:c={concept.id}',
                'concept': concept,
                'severity': (0.5 - state.mastery) * state.effective_evidence,
                'slots': {
                    'concept': concept.name,
                    'n': state.evidence_count,
                    'pct': round(state.mastery * 100),
                },
            })
            continue  # rebuilding mastery outranks polishing it

        if 'repeat_misconception' in (state.flags or []):
            worst = max((state.misconception_counts or {}).values(), default=0)
            deficits.append({
                'kind': 'misconception',
                'signature': f'miscon:c={concept.id}',
                'concept': concept,
                'severity': float(worst) * 1.5,
                'slots': {'concept': concept.name},
            })

        if 'fading_retention' in (state.flags or []):
            days = 0
            if state.last_seen_at:
                days = max(1, (timezone.now() - state.last_seen_at).days)
            deficits.append({
                'kind': 'retention',
                'signature': f'retention:c={concept.id}',
                'concept': concept,
                'severity': (0.7 - state.retention) * state.mastery * 4,
                'slots': {'concept': concept.name, 'days': days},
            })

        if 'weak_transfer' in (state.flags or []):
            deficits.append({
                'kind': 'transfer_gap',
                'signature': f'transfer:c={concept.id}',
                'concept': concept,
                'severity': (state.transfer_gap or 0) * 3,
                'slots': {'concept': concept.name},
            })

    deficits.sort(key=lambda d: d['severity'], reverse=True)
    return deficits[:MAX_DEFICITS]


# ─────────────────────────────────────────────────────────────────────────────
# Candidate pool
# ─────────────────────────────────────────────────────────────────────────────

def _recently_seen_question_ids(student):
    cutoff = timezone.now() - timedelta(days=SEEN_COOLDOWN_DAYS)
    seen = set(
        LearningEvent.objects.filter(
            student=student, occurred_at__gte=cutoff, question__isnull=False,
        ).values_list('question_id', flat=True)
    )
    seen |= set(
        PracticeSetItem.objects.filter(
            practice_set__student=student,
        ).exclude(practice_set__status='expired')
        .values_list('question_id', flat=True)
    )
    return seen


def candidate_questions(course, seen_ids, *, concept=None, cognitive_types=None):
    """Auto-gradable, healthy, unseen questions — the one place pool-health
    policy lives. ``concept=None`` is the cold-start pool: any tagged question
    in the course."""
    from quiz.models import Question

    queryset = Question.objects.filter(
        status='published',
        courses=course,
        question_type__in=['mcq', 'mcq_multi', 'numerical'],
    )
    if concept is not None:
        queryset = queryset.filter(
            concept_links__concept=concept, concept_links__weight__gte=0.5,
        )
    else:
        queryset = queryset.filter(concept_links__isnull=False)
    queryset = (
        queryset
        # Empirically bad items never reach a student: negative discrimination
        # or an extreme p-value at credible volume.
        .exclude(item_stats__discrimination__lt=0)
        .exclude(item_stats__attempts_count__gte=20, item_stats__p_value__gt=0.98)
        .exclude(generated_item__retired_at__isnull=False)
        .distinct()
    )
    if seen_ids:
        queryset = queryset.exclude(id__in=seen_ids)
    if cognitive_types:
        queryset = queryset.filter(cognitive_type__in=cognitive_types)
    return list(queryset[:SET_SIZE * 6])


def _target_band(state):
    if state is None or state.mastery < 0.35:
        return 'easy'
    if state.mastery < 0.7:
        return 'medium'
    return 'hard'


def _pick_ladder(candidates, target_band):
    """(question, role) pairs: warm-ups a band below, core at target, one stretch."""
    by_band = {'easy': [], 'medium': [], 'hard': []}
    for question in candidates:
        by_band.setdefault(question.difficulty or 'medium', by_band['medium']).append(question)

    picked = []
    used = set()

    def take(band, count, role):
        taken = 0
        for question in by_band.get(band, []):
            if question.id in used or taken >= count:
                continue
            used.add(question.id)
            picked.append((question, role))
            taken += 1
        return taken

    below, above = BAND_BELOW[target_band], BAND_ABOVE[target_band]
    if below != target_band:
        take(below, WARMUP_COUNT, 'ladder_easy')
    core_needed = SET_SIZE - len(picked) - (STRETCH_COUNT if above != target_band else 0)
    take(target_band, core_needed, 'core')
    if above != target_band:
        take(above, STRETCH_COUNT, 'ladder_stretch')
    # Backfill from any band if the ladder came up short.
    if len(picked) < SET_SIZE:
        for question in candidates:
            if question.id not in used:
                used.add(question.id)
                picked.append((question, 'core'))
            if len(picked) >= SET_SIZE:
                break
    return picked


# ─────────────────────────────────────────────────────────────────────────────
# Assembly
# ─────────────────────────────────────────────────────────────────────────────

def practice_config_for(course):
    config, _created = CoursePracticeConfig.objects.get_or_create(
        course=course, defaults={'tenant': course.tenant},
    )
    return config


def _build_set(student, course, deficit, questions):
    practice_set = PracticeSet.objects.create(
        tenant=student.user.tenant,
        student=student,
        course=course,
        deficit_kind=deficit['kind'],
        deficit_signature=deficit['signature'],
        reason=_render_reason(deficit['kind'], deficit['slots']),
        item_count=len(questions),
        expires_at=timezone.now() + timedelta(days=SET_TTL_DAYS),
    )
    if deficit.get('concept'):
        practice_set.target_concepts.add(deficit['concept'])
    PracticeSetItem.objects.bulk_create([
        PracticeSetItem(
            tenant=practice_set.tenant, practice_set=practice_set,
            question=question, role=role, order=order,
        )
        for order, (question, role) in enumerate(questions)
    ])
    # Reuse accounting for generated items.
    from intelligence.models import GeneratedItem
    GeneratedItem.objects.filter(
        question_id__in=[q.id for q, _ in questions],
    ).update(times_served=F('times_served') + 1)
    return practice_set


def _cognitive_types_for(deficit):
    if deficit['kind'] == 'transfer_gap':
        return ['multi_concept']
    return None


def refresh_recommendations(student, course):
    """Recompute this student's suggested sets for one course.

    Supersedes stale 'suggested' sets whose deficit no longer ranks; never
    touches in_progress sets. Returns the list of live suggested sets.
    """
    config = practice_config_for(course)
    if not config.practice_enabled:
        return []

    now = timezone.now()
    PracticeSet.objects.filter(
        student=student, course=course, status='suggested', expires_at__lt=now,
    ).update(status='expired')

    deficits = extract_deficits(student, course)
    if not deficits and _is_cold_start(student, course):
        deficits = [_starter_deficit(course)]
    wanted_signatures = {d['signature'] for d in deficits}

    active = PracticeSet.objects.filter(
        student=student, course=course, status__in=['suggested', 'in_progress'],
    )
    # Drop suggestions that no longer rank (a new attempt supersedes them).
    active.filter(status='suggested').exclude(
        deficit_signature__in=wanted_signatures,
    ).update(status='expired')

    existing_signatures = set(active.values_list('deficit_signature', flat=True))
    slots_left = max(0, config.max_active_sets - active.count())

    seen_ids = _recently_seen_question_ids(student)
    built = []
    for deficit in deficits:
        if slots_left <= 0:
            break
        if deficit['signature'] in existing_signatures:
            continue

        if deficit['kind'] == 'starter':
            state = None
            candidates = candidate_questions(course, seen_ids)
        else:
            state = LearnerConceptState.objects.filter(
                student=student, concept=deficit['concept'],
            ).first()
            candidates = candidate_questions(
                course, seen_ids, concept=deficit['concept'],
                cognitive_types=_cognitive_types_for(deficit),
            )
            if deficit['kind'] == 'transfer_gap' and len(candidates) < MIN_SET_SIZE:
                # Not enough genuinely multi-concept items — fall back to any.
                candidates = candidate_questions(
                    course, seen_ids, concept=deficit['concept'],
                )

        if len(candidates) < SET_SIZE * POOL_HEADROOM:
            # Thin pool: ask for novel questions (also for starter pools — a
            # freshly launched course must be able to bootstrap itself).
            _maybe_request_generation(course, deficit, config, have=len(candidates))
        if len(candidates) < MIN_SET_SIZE:
            continue  # hold the deficit until generation lands

        ladder = _pick_ladder(candidates, _target_band(state))
        if len(ladder) < MIN_SET_SIZE:
            continue
        built.append(_build_set(student, course, deficit, ladder))
        slots_left -= 1

    return built


def _starter_deficit(course):
    """The synthetic non-diagnosis used when no diagnosis is possible yet.

    Kept next to nothing: same dict contract as extract_deficits entries.
    """
    return {
        'kind': 'starter',
        'signature': f'starter:course={course.id}',
        'concept': None,
        'severity': 0.0,
        'slots': {'course': course.name},
    }


def _is_cold_start(student, course):
    """True when no diagnosis is possible AND no recent starter set exists.

    Mirrors extract_deficits' evidence filter (including concept status), and
    refuses to deal starter set after starter set: one per SET_TTL_DAYS,
    whatever became of the previous one.
    """
    has_evidence = LearnerConceptState.objects.filter(
        student=student, concept__subject__course=course,
        concept__status='active', evidence_count__gte=MIN_OBSERVATIONS,
    ).exists()
    if has_evidence:
        return False
    recent_starter = PracticeSet.objects.filter(
        student=student, course=course, deficit_kind='starter',
        created_at__gte=timezone.now() - timedelta(days=SET_TTL_DAYS),
    ).exclude(status='expired').exists()
    return not recent_starter


def _maybe_request_generation(course, deficit, config, *, have):
    """Queue novel-question generation for a thin pool (step 10 wiring)."""
    if not config.generation_enabled:
        return
    try:
        from intelligence.services import practice_generation
        practice_generation.request_generation(course, deficit, have=have)
    except ImportError:
        logger.info('recommendation: generation service not available yet')
    except Exception:
        logger.exception('recommendation: failed to request generation for %s',
                         deficit['signature'])
