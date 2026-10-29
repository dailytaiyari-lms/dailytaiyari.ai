"""Skill and thinking-level profiles (spec 2B §6.3).

LearnerFacetState is recomputed from the student's graded LearningEvents,
like LearnerConceptState and with the same decay, prior, diagnosis weighting
and confidence rules (it calls ``state.compute_state_fields``):

- an answered item counts towards each of its ItemSkillTags, at 1.0 for a
  core skill and 0.5 for a supporting one;
- and towards its ItemTagging.thinking_level, at 1.0.

A contribution belongs to the subject of the item's syllabus node
(``ItemTagging.primary_node``), else the event's subject snapshot.
Recompute is per student and idempotent, and runs only for tenants with
``my_progress`` on.
"""
from collections import defaultdict

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from intelligence import progress_config as C
from intelligence.models import ItemSkillTag, ItemTagging, LearnerFacetState, LearningEvent
from intelligence.services import state
from intelligence.versions import FACET_MODEL_VERSION

KINDS = (LearnerFacetState.KIND_SKILL, LearnerFacetState.KIND_THINKING)
UNIQUE_FIELDS = ['student', 'subject', 'kind', 'key']
FIELDS = ('mastery', 'evidence_count', 'effective_evidence', 'confidence', 'computed_at')


def facets_enabled(tenant):
    """True when the tenant has My Progress on. Never raises."""
    try:
        return bool(tenant and tenant.get_features().get('my_progress'))
    except Exception:  # noqa: BLE001 — a broken features blob counts as off
        return False


def _item_key(event):
    return ('q', event.question_id) if event.question_id else ('m', event.mock_item_id)


def _latest_events(student):
    """Latest graded event per source answer, oldest first."""
    latest = {}
    for event in (
        LearningEvent.objects.filter(student=student)
        .filter(Q(question__isnull=False) | Q(mock_item__isnull=False))
        .order_by('occurred_at', 'created_at')
    ):
        latest[event.dedup_key.rsplit(':', 1)[0]] = event
    return list(latest.values())


def _item_tags(keys):
    """({item: tagging values}, {item: [(skill key, role)]}) for these items."""
    question_ids = [item_id for arm, item_id in keys if arm == 'q']
    mock_item_ids = [item_id for arm, item_id in keys if arm == 'm']
    condition = state._items_condition(question_ids, mock_item_ids)
    taggings = {}
    for row in ItemTagging.objects.filter(condition).values(
            'question_id', 'mock_item_id', 'thinking_level', 'primary_node__subject_id'):
        key = ('q', row['question_id']) if row['question_id'] else ('m', row['mock_item_id'])
        taggings[key] = row
    skills = defaultdict(list)
    for question_id, mock_item_id, skill_key, role in ItemSkillTag.objects.filter(condition).values_list(
            'question_id', 'mock_item_id', 'skill__key', 'role'):
        skills[('q', question_id) if question_id else ('m', mock_item_id)].append((skill_key, role))
    return taggings, skills


def facet_observations(student):
    """{(subject_id, kind, key): [observation]} from the student's latest answers."""
    events = _latest_events(student)
    if not events:
        return {}
    taggings, skills = _item_tags({_item_key(event) for event in events})
    diagnosis = state._diagnosis_weights(student, events)

    groups = defaultdict(list)
    for event in events:
        key = _item_key(event)
        tagging = taggings.get(key)
        item_skills = skills.get(key, [])
        if tagging is None and not item_skills:
            continue
        subject_id = (tagging or {}).get('primary_node__subject_id') or event.subject_id
        if subject_id is None:
            continue
        source = (state.PRACTICE_WEIGHT
                  if event.source_type == LearningEvent.SOURCE_PRACTICE_ANSWER else 1.0)
        base = source * diagnosis.get(state._diagnosis_key(event), 1.0)
        contributions = [
            (LearnerFacetState.KIND_SKILL, skill_key, C.SKILL_ROLE_WEIGHTS.get(role, 0.5))
            for skill_key, role in item_skills
        ]
        if tagging and tagging['thinking_level']:
            contributions.append(
                (LearnerFacetState.KIND_THINKING, tagging['thinking_level'], C.THINKING_LEVEL_WEIGHT))
        for kind, facet_key, weight in contributions:
            groups[(subject_id, kind, facet_key)].append(state._Observation(
                occurred_at=event.occurred_at,
                score=max(0.0, min(1.0, event.score_fraction)),
                link_weight=base * weight,
                is_multi=False,
                item_ref=str(key[1]),
            ))
    return groups


def compute_facet_fields(observations, now=None):
    fields = state.compute_state_fields(observations, now=now)
    if fields is None:
        return None
    return {**{name: fields[name] for name in FIELDS}, 'model_version': FACET_MODEL_VERSION}


def recompute_facets(student, now=None):
    """Recompute every facet row of one student; returns rows written.

    Compute and write run in one transaction, and the write is an upsert on
    the unique key, so two recomputes for the same student (two attempts
    finishing together) cannot collide on ``uniq_learner_facet_state``.
    """
    now = now or timezone.now()
    tenant = student.user.tenant
    with transaction.atomic():
        rows = []
        for (subject_id, kind, key), observations in facet_observations(student).items():
            fields = compute_facet_fields(observations, now=now)
            if fields is None:
                continue
            rows.append(LearnerFacetState(
                tenant=tenant, student=student, subject_id=subject_id, kind=kind, key=key,
                **fields,
            ))
        if rows:
            # Fixed order: concurrent upserts lock rows in the same sequence.
            rows.sort(key=lambda r: (str(r.subject_id), r.kind, r.key))
            # bulk_create stamps updated_at (auto_now); listing it in update_fields makes the upsert copy it.
            LearnerFacetState.objects.bulk_create(
                rows, update_conflicts=True, unique_fields=UNIQUE_FIELDS,
                update_fields=[*FIELDS, 'model_version', 'updated_at'],
            )
        kept = {(row.subject_id, row.kind, row.key) for row in rows}
        LearnerFacetState.objects.filter(id__in=[
            row_id for row_id, subject_id, kind, key in
            LearnerFacetState.objects.filter(student=student)
            .values_list('id', 'subject_id', 'kind', 'key')
            if (subject_id, kind, key) not in kept
        ]).delete()
    return len(rows)


def update_for_attempt(kind, attempt_id):
    """Recompute the attempt's student's facets when My Progress is on."""
    from quiz.models import MockTestAttempt, QuizAttempt

    model = QuizAttempt if kind == 'quiz' else MockTestAttempt
    attempt = model.objects.filter(id=attempt_id).select_related('student__user__tenant').first()
    if attempt is None or not facets_enabled(attempt.student.user.tenant):
        return 0
    return recompute_facets(attempt.student)


def profile_for(student, course):
    """Skill and thinking-level rows per course subject (spec 2B §6.3)."""
    from intelligence.models import TagDefinition
    from intelligence.services.rollup import classify

    subjects = list(course.subjects.order_by('order', 'name'))
    tagged = set(
        ItemTagging.objects.filter(primary_node__subject__in=subjects)
        .values_list('primary_node__subject_id', flat=True).distinct()
    )
    definitions = {
        (kind, key): (label, order)
        for kind, key, label, order in TagDefinition.objects.filter(kind__in=KINDS)
        .values_list('kind', 'key', 'label', 'order')
    }
    rows = defaultdict(list)
    for row in LearnerFacetState.objects.filter(student=student, subject__in=subjects):
        rows[(row.subject_id, row.kind)].append(row)

    def facet(row):
        status = classify(row.mastery, row.effective_evidence)
        label = definitions.get((row.kind, row.key), (row.key.replace('_', ' ').capitalize(), 0))[0]
        return {
            'key': row.key, 'label': label,
            'mastery': round(row.mastery, 4) if status != 'not_enough_data' else None,
            'evidence': round(row.effective_evidence, 4),
            'confidence': row.confidence, 'status': status,
        }

    def definition_order(row):
        return (definitions.get((row.kind, row.key), ('', 999))[1], row.key)

    profiles = []
    for subject in subjects:
        base = {'subject_id': str(subject.id), 'subject': subject.name}
        if subject.id not in tagged:
            profiles.append({**base, 'status': 'needs_tagging', 'skills': [], 'thinking_levels': []})
            continue
        skills = sorted(rows[(subject.id, LearnerFacetState.KIND_SKILL)],
                        key=lambda row: (-row.effective_evidence, row.key))
        levels = sorted(rows[(subject.id, LearnerFacetState.KIND_THINKING)], key=definition_order)
        profiles.append({
            **base, 'status': 'ok',
            'skills': [facet(row) for row in skills],
            'thinking_levels': [facet(row) for row in levels],
        })
    return profiles
