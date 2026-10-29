"""Mastery roll-ups for My Progress (spec 2B §6.1–6.2).

Mastery lives at the leaves (one LearnerConceptState per subtopic Concept).
Every figure above a leaf is computed on read and never stored:

- a parent's mastery is the mean of its children that have evidence,
  weighted by ``evidence × weightage``, or by evidence alone when no sibling
  carries a weightage;
- coverage is leaves with evidence over all leaves beneath a node;
- a node under ``MIN_EVIDENCE`` effective evidence shows no mastery, though
  its raw figures still feed its parent;
- the 4-week trend comes from LearningEvents, because state rows hold only
  the current value.

A course subject without a syllabus tree falls back to subject → course
Topic → Concept (``Concept.topics``), with no sub-subject level.

Everything above the "Database" line is pure.
"""
from collections import defaultdict
from datetime import timedelta

from django.utils import timezone

from intelligence import progress_config as C
from intelligence.services.state import CONFIDENCE_HIGH, CONFIDENCE_MEDIUM

LEAF_LEVELS = ('subtopic', 'concept')
LIVE_STATUSES = ('active', 'proposed')
WEEK = timedelta(days=7)


def classify(mastery, evidence):
    if mastery is None or evidence < C.MIN_EVIDENCE:
        return 'not_enough_data'
    if mastery < C.WEAK_BELOW:
        return 'weak'
    if mastery >= C.STRONG_AT:
        return 'strong'
    return 'in_progress'


def confidence_for(evidence):
    if evidence < CONFIDENCE_MEDIUM:
        return 'low'
    if evidence < CONFIDENCE_HIGH:
        return 'medium'
    return 'high'


def _round(value):
    return round(value, 4) if value is not None else None


def rollup_node(node, states, trends=None):
    """Roll ``node`` and its subtree up from leaf states; returns the payload."""
    payload, _raw, _evidence = _roll(node, states, trends or {})
    return payload


def _roll(node, states, trends):
    children = node.get('children') or []
    if node['level'] in LEAF_LEVELS:
        concept_id = node.get('concept_id')
        mastery, evidence = states.get(concept_id, (None, 0.0)) if concept_id else (None, 0.0)
        raw = mastery if evidence > 0 else None
        covered, total = (1 if evidence > 0 else 0), 1
        concept_ids = [str(concept_id)] if concept_id else []
        child_payloads = []
    else:
        rolled = [_roll(child, states, trends) for child in children]
        weighted = any((child.get('weightage') or 0) > 0 for child in children)
        numerator = denominator = evidence = 0.0
        covered = total = 0
        concept_ids = []
        for child, (child_payload, child_raw, child_evidence) in zip(children, rolled):
            evidence += child_evidence
            covered += child_payload['covered']
            total += child_payload['total']
            concept_ids.extend(child_payload['concept_ids'])
            if child_raw is None or child_evidence <= 0:
                continue
            factor = (child.get('weightage') or 0) if weighted else 1.0
            numerator += child_evidence * factor * child_raw
            denominator += child_evidence * factor
        raw = numerator / denominator if denominator > 0 else None
        child_payloads = [payload for payload, _, _ in rolled]

    status = classify(raw, evidence)
    payload = {
        'id': str(node['id']),
        'name': node['name'],
        'level': node['level'],
        'mastery': _round(raw) if status != 'not_enough_data' else None,
        'status': status,
        'coverage': _round(covered / total) if total else None,
        'covered': covered,
        'total': total,
        'evidence': round(evidence, 4),
        'confidence': confidence_for(evidence),
        'trend_4w': trends.get(str(node['id']), [None] * C.TREND_WEEKS),
        'concept_ids': list(dict.fromkeys(concept_ids)),
        'children': child_payloads,
    }
    return payload, raw, evidence


def iter_nodes(payload):
    yield payload
    for child in payload['children']:
        yield from iter_nodes(child)


def weekly_trend(points, now):
    """``[(occurred_at, score, weight)]`` → weekly weighted mean scores,
    oldest first. A week with fewer than ``TREND_MIN_EVENTS`` answers is None."""
    weeks = [[0, 0.0, 0.0] for _ in range(C.TREND_WEEKS)]   # n, Σw, Σw·score
    for occurred_at, score, weight in points:
        index = (now - occurred_at) // WEEK
        if not 0 <= index < C.TREND_WEEKS:
            continue
        bucket = weeks[index]
        bucket[0] += 1
        bucket[1] += weight
        bucket[2] += weight * score
    values = [
        round(weighted / weights, 4) if count >= C.TREND_MIN_EVENTS and weights > 0 else None
        for count, weights, weighted in weeks
    ]
    return list(reversed(values))


def node_event_sets(node, events_by_concept):
    """{node id: set of event indexes} over each node's leaf concepts."""
    found = {}
    _collect(node, events_by_concept, found)
    return found


def _collect(node, events_by_concept, found):
    if node['level'] in LEAF_LEVELS:
        indexes = set(events_by_concept.get(node.get('concept_id'), ()))
    else:
        indexes = set()
        for child in node.get('children') or []:
            indexes |= _collect(child, events_by_concept, found)
    found[str(node['id'])] = indexes
    return indexes


def topic_lists(subjects):
    """(weak, strong): the weakest and strongest topics across subjects."""
    topics = [
        {
            'id': node['id'], 'name': node['name'], 'subject': subject['name'],
            'mastery': node['mastery'], 'evidence': node['evidence'],
            'coverage': node['coverage'], 'status': node['status'],
            'concept_ids': node['concept_ids'],
        }
        for subject in subjects
        for node in iter_nodes(subject)
        if node['level'] == 'topic'
    ]
    weak = sorted((t for t in topics if t['status'] == 'weak'),
                  key=lambda t: (t['mastery'], t['name']))
    strong = sorted((t for t in topics if t['status'] == 'strong'),
                    key=lambda t: (-t['mastery'], t['name']))
    return weak[:C.TOP_TOPICS], strong[:C.TOP_TOPICS]


# ── Database ─────────────────────────────────────────────────────────────────


def _tree_children(subject):
    """The subject's live, in-syllabus nodes as nested node dicts."""
    from intelligence.models import SyllabusNode

    nodes = (
        SyllabusNode.objects.filter(subject=subject, status__in=LIVE_STATUSES, in_syllabus=True)
        .order_by('order', 'name')
    )
    by_parent = defaultdict(list)
    for node in nodes:
        by_parent[node.parent_id].append(node)

    def build(node):
        return {
            'id': node.id, 'name': node.name, 'level': node.level,
            'weightage': node.weightage, 'concept_id': node.concept_id,
            'children': [build(child) for child in by_parent.get(node.id, [])],
        }

    # Walking down from the roots drops anything under an excluded parent.
    return [build(node) for node in by_parent.get(None, [])]


def _has_subtopic(node):
    return node['level'] == 'subtopic' or any(_has_subtopic(c) for c in node['children'])


def _fallback_children(subject):
    """subject → course Topic → Concept, from ``Concept.topics``."""
    from intelligence.models import Concept

    concepts = (
        Concept.objects.filter(subject=subject, status='active')
        .prefetch_related('topics').order_by('name')
    )
    groups, loose = {}, []
    for concept in concepts:
        topics = [topic for topic in concept.topics.all() if topic.subject_id == subject.id]
        if not topics:
            loose.append(concept)
        for topic in topics:
            groups.setdefault(topic.id, (topic, []))[1].append(concept)

    def leaf(concept):
        return {'id': concept.id, 'name': concept.name, 'level': 'concept',
                'weightage': 0.0, 'concept_id': concept.id, 'children': []}

    children = [
        {'id': topic.id, 'name': topic.name, 'level': 'topic', 'weightage': 0.0,
         'children': [leaf(concept) for concept in members]}
        for topic, members in sorted(groups.values(), key=lambda pair: (pair[0].order, pair[0].name))
    ]
    if loose:
        children.append({
            'id': f'other:{subject.id}', 'name': 'Other concepts', 'level': 'topic',
            'weightage': 0.0, 'children': [leaf(concept) for concept in loose],
        })
    return children


def course_structure(course):
    """Each course subject as a node tree: its syllabus tree when it has a
    live subtopic, else the Topic → Concept fallback."""
    structures = []
    for subject in course.subjects.order_by('order', 'name'):
        children = _tree_children(subject)
        has_tree = any(_has_subtopic(child) for child in children)
        if not has_tree:
            children = _fallback_children(subject)
        structures.append({
            'subject': subject,
            'has_tree': has_tree,
            'node': {'id': subject.id, 'name': subject.name, 'level': 'subject',
                     'weightage': 0.0, 'children': children},
        })
    return structures


def leaf_concept_ids(node):
    if node['level'] in LEAF_LEVELS:
        return {node['concept_id']} if node.get('concept_id') else set()
    ids = set()
    for child in node.get('children') or []:
        ids |= leaf_concept_ids(child)
    return ids


def _trend_events(student, concept_ids, now):
    """(points, {concept_id: [point index]}) for the student's latest answers
    on these concepts inside the trend window."""
    from intelligence.models import ConceptLink, LearningEvent
    from intelligence.services.state import (
        PRACTICE_WEIGHT, _diagnosis_key, _diagnosis_weights, _items_condition,
    )

    concepts_by_item = defaultdict(set)
    for concept_id, question_id, mock_item_id in ConceptLink.objects.filter(
            concept_id__in=concept_ids).values_list('concept_id', 'question_id', 'mock_item_id'):
        key = ('q', question_id) if question_id else ('m', mock_item_id)
        concepts_by_item[key].add(concept_id)
    if not concepts_by_item:
        return [], {}

    question_ids = [item_id for arm, item_id in concepts_by_item if arm == 'q']
    mock_item_ids = [item_id for arm, item_id in concepts_by_item if arm == 'm']
    newest = list(
        LearningEvent.objects.filter(
            student=student, occurred_at__gte=now - WEEK * C.TREND_WEEKS, occurred_at__lte=now,
        ).filter(_items_condition(question_ids, mock_item_ids))
        .order_by('-occurred_at', '-created_at')[:C.TREND_MAX_EVENTS]
    )
    latest = {}
    for event in reversed(newest):   # oldest first, so a regrade wins
        latest[event.dedup_key.rsplit(':', 1)[0]] = event

    diagnosis = _diagnosis_weights(student, latest.values())
    points, by_concept = [], defaultdict(list)
    for event in latest.values():
        key = ('q', event.question_id) if event.question_id else ('m', event.mock_item_id)
        source = PRACTICE_WEIGHT if event.source_type == LearningEvent.SOURCE_PRACTICE_ANSWER else 1.0
        points.append((
            event.occurred_at,
            max(0.0, min(1.0, event.score_fraction)),
            source * diagnosis.get(_diagnosis_key(event), 1.0),
        ))
        for concept_id in concepts_by_item.get(key, ()):
            by_concept[concept_id].append(len(points) - 1)
    return points, by_concept


def rollup_for(student, course, *, now=None, with_trend=True):
    """The student's roll-up for one course: one payload per subject."""
    from intelligence.models import LearnerConceptState

    now = now or timezone.now()
    structures = course_structure(course)
    concept_ids = set()
    for structure in structures:
        concept_ids |= leaf_concept_ids(structure['node'])
    states = {
        concept_id: (mastery, evidence)
        for concept_id, mastery, evidence in LearnerConceptState.objects.filter(
            student=student, concept_id__in=concept_ids,
        ).values_list('concept_id', 'mastery', 'effective_evidence')
    }

    trends = {}
    if with_trend and concept_ids:
        points, by_concept = _trend_events(student, concept_ids, now)
        for structure in structures:
            for node_id, indexes in node_event_sets(structure['node'], by_concept).items():
                trends[node_id] = weekly_trend([points[i] for i in indexes], now)

    subjects = []
    for structure in structures:
        payload = rollup_node(structure['node'], states, trends)
        payload['has_tree'] = structure['has_tree']
        subjects.append(payload)
    return subjects
