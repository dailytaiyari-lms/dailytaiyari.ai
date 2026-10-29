"""My Progress roll-up from real rows (spec 2B §6.1)."""
from datetime import timedelta

from exams.models import Topic
from intelligence.models import Concept, LearningEvent
from intelligence.services import progress, rollup
from intelligence.tests.progress_fixtures import ProgressTestCase
from quiz.models import MockTest, MockTestAttempt, MockTestItem


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


class RecentAnswersTests(ProgressTestCase):
    def test_counts_noted_answers_per_attempt(self):
        attempt = self.quiz_attempt(self.student, minutes_ago=30)
        questions = [self.make_question(n) for n in range(5)]
        self.diagnose(attempt, questions[0], 'guess')
        self.diagnose(attempt, questions[1], 'guess', confidence='medium')
        self.diagnose(attempt, questions[2], 'time_pressure', answered=False)
        self.diagnose(attempt, questions[3], 'careless_slip', confidence='low')   # not counted
        self.diagnose(attempt, questions[4], 'correct')                            # not counted
        older = self.quiz_attempt(self.student, minutes_ago=600)

        rows = progress.recent_answers(self.student, self.course)
        self.assertEqual([row['attempt_id'] for row in rows], [str(attempt.id), str(older.id)])
        self.assertEqual(rows[0]['summary'], '2 quick guesses, 1 ran out of time')
        self.assertEqual((rows[0]['noted'], rows[0]['review'], rows[0]['title']),
                         (3, 'quiz', 'Kinematics quiz'))
        self.assertEqual((rows[1]['noted'], rows[1]['summary']), (0, ''))

    def test_rich_mocks_and_course_filter(self):
        rich = MockTest.objects.create(tenant=self.tenant, course=self.course, title='Rich',
                                       duration_minutes=60, total_marks=4)
        MockTestItem.objects.create(tenant=self.tenant, mock_test=rich, item_type='mcq',
                                    question_text='Q?', marks=4,
                                    options=[{'text': 'A', 'is_correct': True}])
        MockTestAttempt.objects.create(student=self.student, mock_test=rich, status='completed')
        other = MockTest.objects.create(tenant=self.tenant, course=self.other_course,
                                        title='Elsewhere', duration_minutes=60, total_marks=4)
        MockTestAttempt.objects.create(student=self.student, mock_test=other, status='completed')
        MockTestAttempt.objects.create(student=self.student, mock_test=rich, status='in_progress')
        rows = progress.recent_answers(self.student, self.course)
        self.assertEqual([(row['title'], row['review']) for row in rows], [('Rich', 'rich_mock')])


class PayloadTests(ProgressTestCase):
    def test_payload_shape(self):
        self.hand_states()
        data = progress.progress_payload(self.student, self.course, [self.course], recent=False)
        self.assertEqual(data['course'], {'id': str(self.course.id), 'name': 'Physics'})
        self.assertEqual(data['courses'], [{'id': str(self.course.id), 'name': 'Physics'}])
        self.assertEqual([t['name'] for t in data['weak']], ['Dynamics'])
        self.assertEqual(data['strong'], [])
        self.assertIsNone(data['recent_answers'])
        self.assertEqual([p['status'] for p in data['profiles']], ['needs_tagging', 'needs_tagging'])
        self.assertEqual(data['thresholds'], {'weak_below': 0.5, 'strong_at': 0.8, 'min_evidence': 3})


class HeatmapTests(ProgressTestCase):
    def test_bands_and_coverage(self):
        from users.models import CourseEnrollment, User

        self.hand_states()                      # student: kinematics 0.75, dynamics 0.4
        second = User.objects.create_user(email='prog-2@example.com', password='pw-prog-2',
                                          tenant=self.tenant, role='student').profile
        CourseEnrollment.objects.create(tenant=self.tenant, student=second, course=self.course,
                                        status='approved', is_active=True)
        self.set_state(self.concepts['velocity'], 0.95, 5.0, student=second)
        self.hand_states(student=self.outsider)   # not in this course

        data = progress.heatmap(self.course)
        self.assertEqual(data['students'], 2)
        rows = {row['name']: row for row in data['topics']}
        self.assertEqual(rows['Kinematics']['counts'],
                         {'weak': 0, 'in_progress': 1, 'strong': 1, 'not_enough_data': 0})
        self.assertEqual(rows['Dynamics']['counts']['weak'], 1)
        self.assertEqual(rows['Dynamics']['counts']['not_enough_data'], 1)
        # kinematics coverage: student 2/3, second 1/3 → mean 0.5
        self.assertEqual(rows['Kinematics']['coverage'], 0.5)
        self.assertEqual(rows['Dynamics']['students']['weak'],
                         [{'id': str(self.student.id), 'name': self.student_user.email}])
        self.assertEqual(list(rows), ['Dynamics', 'Kinematics'])   # tree order: order, then name
