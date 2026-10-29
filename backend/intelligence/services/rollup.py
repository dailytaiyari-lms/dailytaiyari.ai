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
from datetime import timedelta

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
