"""Pure My Progress rules, against hand-computed fixtures."""
from datetime import datetime, timedelta, timezone as dt_timezone

from django.test import SimpleTestCase

from intelligence.services import rollup

A, B, C, D = 'concept-a', 'concept-b', 'concept-c', 'concept-d'


def leaf(id, concept, weightage=0.0):
    return {'id': id, 'name': id.title(), 'level': 'subtopic', 'weightage': weightage,
            'concept_id': concept, 'children': []}


def branch(id, level, children, weightage=0.0):
    return {'id': id, 'name': id.title(), 'level': level, 'weightage': weightage,
            'children': children}


# subject → Mechanics (sub-subject) → Kinematics (0.6) / Dynamics (0.4) → subtopics
TREE = branch('physics', 'subject', [
    branch('mechanics', 'sub_subject', [
        branch('kinematics', 'topic', [
            leaf('velocity', A), leaf('projectile', B), leaf('relative', C),
        ], weightage=0.6),
        branch('dynamics', 'topic', [leaf('friction', D)], weightage=0.4),
    ]),
])
STATES = {A: (0.9, 6.0), B: (0.3, 2.0), D: (0.4, 4.0)}


def find(payload, node_id):
    return next(node for node in rollup.iter_nodes(payload) if node['id'] == node_id)


class ClassifyTests(SimpleTestCase):
    def test_bands(self):
        self.assertEqual(rollup.classify(0.49, 3), 'weak')
        self.assertEqual(rollup.classify(0.5, 3), 'in_progress')
        self.assertEqual(rollup.classify(0.79, 3), 'in_progress')
        self.assertEqual(rollup.classify(0.8, 3), 'strong')
        self.assertEqual(rollup.classify(0.9, 2.99), 'not_enough_data')
        self.assertEqual(rollup.classify(None, 10), 'not_enough_data')

    def test_confidence_uses_state_cut_offs(self):
        self.assertEqual(rollup.confidence_for(2.9), 'low')
        self.assertEqual(rollup.confidence_for(3.0), 'medium')
        self.assertEqual(rollup.confidence_for(10.0), 'high')


class RollupTests(SimpleTestCase):
    def setUp(self):
        self.payload = rollup.rollup_node(TREE, STATES)

    def test_leaves(self):
        velocity = find(self.payload, 'velocity')
        self.assertEqual((velocity['mastery'], velocity['status']), (0.9, 'strong'))
        self.assertEqual((velocity['covered'], velocity['total']), (1, 1))
        self.assertEqual(velocity['concept_ids'], [A])
        projectile = find(self.payload, 'projectile')   # evidence 2 < 3
        self.assertIsNone(projectile['mastery'])
        self.assertEqual(projectile['status'], 'not_enough_data')
        relative = find(self.payload, 'relative')       # no state at all
        self.assertEqual((relative['covered'], relative['evidence']), (0, 0.0))

    def test_unweighted_topic_uses_evidence_and_keeps_thin_leaves(self):
        # siblings all weightage 0 → weights 6 and 2: (6×0.9 + 2×0.3) / 8 = 0.75
        kinematics = find(self.payload, 'kinematics')
        self.assertEqual(kinematics['mastery'], 0.75)
        self.assertEqual(kinematics['status'], 'in_progress')
        self.assertEqual(kinematics['evidence'], 8.0)
        self.assertEqual((kinematics['covered'], kinematics['total']), (2, 3))
        self.assertEqual(kinematics['coverage'], 0.6667)
        self.assertEqual(kinematics['concept_ids'], [A, B, C])

    def test_weighted_parent(self):
        # 8×0.6 = 4.8 and 4×0.4 = 1.6: (4.8×0.75 + 1.6×0.4) / 6.4 = 0.6625
        mechanics = find(self.payload, 'mechanics')
        self.assertEqual(mechanics['mastery'], 0.6625)
        self.assertEqual(mechanics['evidence'], 12.0)
        self.assertEqual(mechanics['coverage'], 0.75)
        self.assertEqual(mechanics['confidence'], 'high')
        self.assertEqual(self.payload['mastery'], 0.6625)
        self.assertEqual(find(self.payload, 'dynamics')['status'], 'weak')

    def test_zero_weightage_child_in_weighted_group_adds_no_mastery(self):
        tree = branch('topic', 'topic', [
            leaf('weighted', A, weightage=1.0), leaf('unweighted', D, weightage=0.0)])
        payload = rollup.rollup_node(tree, {A: (0.9, 6.0), D: (0.1, 6.0)})
        self.assertEqual(payload['mastery'], 0.9)
        self.assertEqual(payload['evidence'], 12.0)

    def test_node_without_leaves_has_no_coverage(self):
        payload = rollup.rollup_node(branch('empty', 'topic', []), {})
        self.assertIsNone(payload['coverage'])
        self.assertEqual(payload['status'], 'not_enough_data')

    def test_trend_defaults_to_nulls(self):
        self.assertEqual(self.payload['trend_4w'], [None, None, None, None])
        payload = rollup.rollup_node(TREE, STATES, {'kinematics': [0.5, None, None, 1.0]})
        self.assertEqual(find(payload, 'kinematics')['trend_4w'], [0.5, None, None, 1.0])


class TopicListTests(SimpleTestCase):
    def test_weak_and_strong(self):
        tree = branch('physics', 'subject', [
            branch(name, 'topic', [leaf(f'{name}-leaf', concept)])
            for name, concept in (('alpha', A), ('beta', B), ('gamma', C), ('delta', D))
        ])
        states = {A: (0.2, 5.0), B: (0.4, 5.0), C: (0.95, 5.0), D: (0.85, 1.0)}
        weak, strong = rollup.topic_lists([rollup.rollup_node(tree, states)])
        self.assertEqual([t['name'] for t in weak], ['Alpha', 'Beta'])
        self.assertEqual([t['name'] for t in strong], ['Gamma'])     # delta: too little evidence
        self.assertEqual(weak[0]['subject'], 'Physics')
        self.assertEqual(weak[0]['concept_ids'], [A])


NOW = datetime(2026, 10, 28, 12, 0, tzinfo=dt_timezone.utc)


class TrendTests(SimpleTestCase):
    def test_weekly_weighted_mean_oldest_first(self):
        points = [
            (NOW - timedelta(days=1), 1.0, 1.0),
            (NOW - timedelta(days=2), 0.0, 0.2),    # a guess: weight 0.2
            (NOW - timedelta(days=10), 1.0, 1.0),   # week 1 has one answer → null
            (NOW - timedelta(days=22), 1.0, 1.0),
            (NOW - timedelta(days=23), 1.0, 0.5),
            (NOW - timedelta(days=40), 0.0, 1.0),   # outside the window
        ]
        # week 0: (1×1 + 0×0.2) / 1.2 = 0.8333
        self.assertEqual(rollup.weekly_trend(points, NOW), [1.0, None, None, 0.8333])

    def test_event_sets_union_children(self):
        sets = rollup.node_event_sets(TREE, {A: [0, 1], B: [1, 2], D: [3]})
        self.assertEqual(sets['velocity'], {0, 1})
        self.assertEqual(sets['kinematics'], {0, 1, 2})
        self.assertEqual(sets['physics'], {0, 1, 2, 3})
        self.assertEqual(sets['relative'], set())
