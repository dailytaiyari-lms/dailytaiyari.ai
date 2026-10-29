"""My Progress roll-up from real rows (spec 2B §6.1)."""
from datetime import timedelta

from exams.models import Topic
from intelligence.models import Concept, LearningEvent
from intelligence.services import rollup
from intelligence.tests.progress_fixtures import ProgressTestCase


def find(payload, node_id):
    return next(node for node in rollup.iter_nodes(payload) if node['id'] == str(node_id))


class TreeRollupTests(ProgressTestCase):
    def test_matches_the_hand_computed_tree(self):
        self.hand_states()
        physics, optics = rollup.rollup_for(self.student, self.course)
        self.assertTrue(physics['has_tree'])
        self.assertEqual(physics['level'], 'subject')
        self.assertEqual(physics['mastery'], 0.6625)
        self.assertEqual(physics['coverage'], 0.75)
        self.assertEqual(find(physics, self.kinematics.id)['mastery'], 0.75)
        self.assertEqual(find(physics, self.dynamics.id)['status'], 'weak')
        self.assertIsNone(find(physics, self.projectile.id)['mastery'])
        self.assertFalse(optics['has_tree'])

    def test_other_students_states_do_not_leak(self):
        self.hand_states(student=self.outsider)
        physics = rollup.rollup_for(self.student, self.course)[0]
        self.assertEqual(physics['evidence'], 0.0)

    def test_proposed_counts_archived_and_out_of_syllabus_do_not(self):
        self.hand_states()
        proposed = self.node('waves', 'Waves', 'subtopic', self.kinematics, status='proposed')
        archived = self.node('old', 'Old', 'subtopic', self.kinematics, status='archived')
        outside = self.node('extra', 'Extra', 'subtopic', self.kinematics, in_syllabus=False)
        hidden_topic = self.node('hidden', 'Hidden', 'topic', self.mechanics, status='archived')
        under_hidden = self.node('under', 'Under', 'subtopic', hidden_topic)
        for node in (proposed, archived, outside, under_hidden):
            self.set_state(node.concept, 0.1, 5.0)
        physics = rollup.rollup_for(self.student, self.course)[0]
        kinematics = find(physics, self.kinematics.id)
        self.assertEqual(kinematics['total'], 4)
        ids = {node['id'] for node in rollup.iter_nodes(physics)}
        self.assertIn(str(proposed.id), ids)
        self.assertFalse(ids & {str(archived.id), str(outside.id), str(under_hidden.id)})


class FallbackTests(ProgressTestCase):
    def test_subject_topic_concept_without_a_tree(self):
        lenses = Topic.objects.create(tenant=self.tenant, subject=self.optics, name='Lenses',
                                      code='lenses')
        mirrors = Topic.objects.create(tenant=self.tenant, subject=self.optics, name='Mirrors',
                                       code='mirrors', order=1)
        focal = self.concept('focal', subject=self.optics)
        image = self.concept('image', subject=self.optics)
        loose = self.concept('loose', subject=self.optics)
        focal.topics.add(lenses)
        image.topics.add(lenses, mirrors)
        Concept.objects.create(tenant=self.tenant, subject=self.optics, name='Gone',
                               slug='progress-gone', status='merged')
        self.set_state(focal, 0.9, 6.0)
        self.set_state(image, 0.3, 2.0)

        optics = rollup.rollup_for(self.student, self.course)[1]
        self.assertFalse(optics['has_tree'])
        self.assertEqual([t['name'] for t in optics['children']],
                         ['Lenses', 'Mirrors', 'Other concepts'])
        lenses_row, mirrors_row, other = optics['children']
        self.assertEqual(lenses_row['mastery'], 0.75)          # (6×0.9 + 2×0.3) / 8
        self.assertEqual(mirrors_row['status'], 'not_enough_data')
        self.assertEqual(mirrors_row['coverage'], 1.0)
        self.assertEqual([c['name'] for c in other['children']], [loose.name])
        self.assertTrue(all(c['level'] == 'concept' for c in lenses_row['children']))


class TrendTests(ProgressTestCase):
    def setUp(self):
        self.question = self.make_question(1)
        self.link(self.question, self.concepts['velocity'])

    def test_trend_weighs_diagnoses(self):
        attempt = self.quiz_attempt(self.student)
        self.event(self.question, score=1.0, days_ago=1)
        self.event(self.question, score=0.0, days_ago=2, attempt=attempt)
        self.diagnose(attempt, self.question, 'guess')            # weight 0.2
        self.event(self.question, score=1.0, days_ago=10)         # alone in week 1

        physics = rollup.rollup_for(self.student, self.course)[0]
        # week 0: (1×1 + 0×0.2) / 1.2 = 0.8333
        self.assertEqual(find(physics, self.velocity.id)['trend_4w'], [None, None, None, 0.8333])
        self.assertEqual(find(physics, self.kinematics.id)['trend_4w'], [None, None, None, 0.8333])
        self.assertEqual(find(physics, self.dynamics.id)['trend_4w'], [None] * 4)

    def test_a_regrade_replaces_the_original_answer(self):
        right = self.event(self.question, score=1.0, days_ago=1)
        self.event(self.question, score=1.0, days_ago=2)
        # A real regrade occurs at its graded_at, after the original answer
        # (events.record_regrade_event). A distinct occurred_at also keeps the
        # "latest wins" order independent of created_at clock resolution.
        LearningEvent.objects.create(
            tenant=self.tenant, student=self.student, source_type='quiz_answer',
            question=self.question, subject=self.question.subject,
            occurred_at=right.occurred_at + timedelta(hours=1), is_correct=False,
            score_fraction=0.0,
            event_kind='regraded',
            dedup_key=right.dedup_key.rsplit(':', 1)[0] + ':1700000000',
        )
        physics = rollup.rollup_for(self.student, self.course)[0]
        # week 0: the regrade (0.0) and the day-2 answer (1.0) → 0.5
        self.assertEqual(find(physics, self.velocity.id)['trend_4w'], [None, None, None, 0.5])

    def test_without_trend(self):
        physics = rollup.rollup_for(self.student, self.course, with_trend=False)[0]
        self.assertEqual(physics['trend_4w'], [None] * 4)
