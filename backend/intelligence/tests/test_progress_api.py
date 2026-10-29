"""My Progress: switch, endpoints, scope and opt-out."""
import uuid
from unittest.mock import patch

from django.test import TestCase

from core.models import Tenant
from intelligence import api
from intelligence.models import ItemSkillTag, ItemTagging, LearnerFacetState, TagDefinition
from intelligence.tests.progress_fixtures import ProgressTestCase


class SwitchTests(TestCase):
    def test_my_progress_is_opt_in_and_a_learning_feature(self):
        self.assertIn('my_progress', Tenant.FEATURE_CHOICES)
        self.assertIn('my_progress', Tenant.OPT_IN_FEATURES)
        self.assertIn('my_progress', api.LEARNING_FEATURES)
        tenant = Tenant.objects.create(name='Progress Switch Academy')
        self.assertFalse(tenant.get_features()['my_progress'])
        self.assertFalse(api.intelligence_enabled(tenant))
        tenant.features = {'my_progress': True}
        self.assertTrue(api.intelligence_enabled(tenant))


MY = '/api/v1/intelligence/my/progress/'
INSIGHTS = '/api/v1/tenant-admin/intelligence'


class MyProgressTests(ProgressTestCase):
    def test_student_gets_their_course(self):
        self.hand_states()
        response = self.client_for(self.student_user).get(MY)
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual(data['course']['id'], str(self.course.id))
        self.assertEqual(data['subjects'][0]['mastery'], 0.6625)
        self.assertEqual([t['name'] for t in data['weak']], ['Dynamics'])
        self.assertEqual(data['recent_answers'], [])

    def test_recent_answers_need_the_student_view(self):
        attempt = self.quiz_attempt(self.student)
        self.diagnose(attempt, self.make_question(1), 'guess')
        data = self.client_for(self.student_user).get(MY).json()
        self.assertEqual(data['recent_answers'][0]['summary'], '1 quick guess')
        self.assertNotIn('label', data['recent_answers'][0])
        self.tenant.features = {**self.tenant.features, 'diagnosis_student_view': False}
        self.tenant.save()
        self.assertIsNone(self.client_for(self.student_user).get(MY).json()['recent_answers'])

    def test_course_scope(self):
        client = self.client_for(self.student_user)
        self.assertEqual(client.get(MY, {'course': str(self.other_course.id)}).status_code, 403)
        self.assertEqual(client.get(MY, {'course': str(uuid.uuid4())}).status_code, 404)
        self.assertEqual(client.get(MY, {'course': 'nope'}).status_code, 404)

    def test_student_without_courses_gets_an_empty_page(self):
        from users.models import User

        loner = User.objects.create_user(email='loner@example.com', password='pw-loner-1',
                                         tenant=self.tenant, role='student')
        data = self.client_for(loner).get(MY).json()
        self.assertEqual((data['course'], data['subjects']), (None, []))

    def test_staff_have_no_progress_page(self):
        self.assertEqual(self.client_for(self.admin).get(MY).status_code, 403)


class StudentProgressTests(ProgressTestCase):
    def url(self, student):
        return f'{INSIGHTS}/students/{student.id}/progress/'

    def test_faculty_see_their_students(self):
        response = self.client_for(self.faculty).get(self.url(self.student))
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual(data['student']['id'], str(self.student.id))
        self.assertEqual(data['courses'], [{'id': str(self.course.id), 'name': 'Physics'}])
        self.assertEqual(data['recent_answers'], [])      # teacher view is on

    def test_scope(self):
        self.assertEqual(self.client_for(self.faculty).get(self.url(self.outsider)).status_code, 403)
        self.assertEqual(self.client_for(self.other_faculty).get(self.url(self.student)).status_code,
                         403)
        self.assertEqual(
            self.client_for(self.faculty).get(
                self.url(self.student), {'course': str(self.other_course.id)}).status_code,
            403)
        admin = self.client_for(self.admin).get(self.url(self.outsider))
        self.assertEqual(admin.status_code, 200)
        self.assertEqual(admin.json()['course']['id'], str(self.other_course.id))
        self.assertEqual(self.client_for(self.admin).get(
            f'{INSIGHTS}/students/{uuid.uuid4()}/progress/').status_code, 404)

    def test_students_cannot_call_it(self):
        self.assertEqual(self.client_for(self.student_user).get(self.url(self.student)).status_code,
                         403)


class HeatmapApiTests(ProgressTestCase):
    def url(self, course):
        return f'{INSIGHTS}/courses/{course.id}/heatmap/'

    def test_scope_and_payload(self):
        self.hand_states()
        response = self.client_for(self.faculty).get(self.url(self.course))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['students'], 1)
        self.assertEqual(self.client_for(self.faculty).get(self.url(self.other_course)).status_code,
                         403)
        self.assertEqual(self.client_for(self.admin).get(self.url(self.other_course)).status_code,
                         200)


class PracticeSerializerTests(ProgressTestCase):
    def test_practice_sets_carry_concept_ids(self):
        from intelligence.models import PracticeSet
        from intelligence.serializers import PracticeSetSerializer

        practice_set = PracticeSet.objects.create(
            tenant=self.tenant, student=self.student, course=self.course,
            deficit_kind='low_mastery', deficit_signature='sig',
        )
        practice_set.target_concepts.add(self.concepts['velocity'])
        self.assertEqual(PracticeSetSerializer(practice_set).data['concept_ids'],
                         [str(self.concepts['velocity'].id)])


class OptOutTests(ProgressTestCase):
    """With every learning-layer switch off: no Part C endpoint is reachable,
    no facet rows appear, and the nightly sweep does no facet work."""

    features = {}

    def test_every_endpoint_is_403(self):
        urls = [
            (self.student_user, MY),
            (self.admin, f'{INSIGHTS}/students/{self.student.id}/progress/'),
            (self.admin, f'{INSIGHTS}/courses/{self.course.id}/heatmap/'),
        ]
        for user, url in urls:
            self.assertEqual(self.client_for(user).get(url).status_code, 403, url)

    def test_no_facets_without_my_progress(self):
        from intelligence.services import facets
        from intelligence.tasks import refresh_learner_state

        skill = TagDefinition.objects.create(kind='skill', key='k', label='K', definition='-')
        question = self.make_question(1)
        ItemTagging.objects.create(tenant=self.tenant, question=question,
                                   primary_node=self.velocity, thinking_level='apply')
        ItemSkillTag.objects.create(tenant=self.tenant, question=question, skill=skill, role='core')
        attempt = self.quiz_attempt(self.student)
        self.event(question, score=1.0, attempt=attempt)

        self.assertEqual(facets.update_for_attempt('quiz', str(attempt.id)), 0)
        with patch('intelligence.services.facets.recompute_facets') as recompute:
            refresh_learner_state()
        recompute.assert_not_called()
        self.assertFalse(LearnerFacetState.objects.exists())

    def test_practice_alone_does_not_turn_on_facets(self):
        from intelligence.services import facets

        self.tenant.features = {'practice': True}
        self.tenant.save()
        self.assertFalse(facets.facets_enabled(self.tenant))
        self.assertEqual(
            self.client_for(self.student_user).get(MY).status_code, 403)


class TeacherProgressScopeTests(ProgressTestCase):
    def url(self):
        return f'{INSIGHTS}/students/{self.student.id}/progress/'

    def test_faculty_cannot_open_a_course_they_do_not_teach(self):
        # The student is approved in BOTH courses, so the faculty member may
        # see the student, but only through the course they teach.
        from users.models import CourseEnrollment

        CourseEnrollment.objects.create(
            tenant=self.tenant, student=self.student, course=self.other_course,
            status='approved', is_active=True,
        )
        client = self.client_for(self.faculty)
        own = client.get(self.url(), {'course': str(self.course.id)})
        self.assertEqual(own.status_code, 200, own.content)
        self.assertEqual(own.json()['course']['id'], str(self.course.id))
        self.assertEqual(
            client.get(self.url(), {'course': str(self.other_course.id)}).status_code, 403)
        self.assertEqual(
            [c['id'] for c in client.get(self.url()).json()['courses']], [str(self.course.id)])

    def test_recent_answers_need_the_teacher_view(self):
        self.tenant.features = {**self.tenant.features, 'diagnosis_teacher_view': False}
        self.tenant.save()
        response = self.client_for(self.faculty).get(self.url())
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIsNone(response.json()['recent_answers'])


class UnreleasedMockTests(ProgressTestCase):
    """A mock whose results are not released must not leak its diagnoses."""

    def make_attempt(self, visibility, released=False):
        from quiz.models import MockTest, MockTestAttempt

        mock = MockTest.objects.create(
            tenant=self.tenant, course=self.course, title='Weekly mock', duration_minutes=60,
            total_marks=4, result_visibility=visibility, results_released=released)
        attempt = MockTestAttempt.objects.create(
            student=self.student, mock_test=mock, status='completed')
        for number in range(3):
            self.diagnose(attempt, self.make_question(number), 'guess', kind='mock')
        return attempt

    def student_rows(self):
        return self.client_for(self.student_user).get(MY).json()['recent_answers']

    def teacher_rows(self):
        url = f'{INSIGHTS}/students/{self.student.id}/progress/'
        return self.client_for(self.faculty).get(url).json()['recent_answers']

    def test_on_release_mock_is_withheld_from_the_student_only(self):
        self.make_attempt('on_release')
        row = self.student_rows()[0]
        self.assertEqual((row['results_pending'], row['summary'], row['noted']), (True, '', 0))
        teacher = self.teacher_rows()[0]
        self.assertEqual((teacher['results_pending'], teacher['noted']), (False, 3))
        self.assertEqual(teacher['summary'], '3 quick guesses')

    def test_released_and_immediate_mocks_show_their_summary(self):
        self.make_attempt('on_release', released=True)
        self.make_attempt('immediate')
        rows = self.student_rows()
        self.assertEqual([row['results_pending'] for row in rows], [False, False])
        self.assertEqual({row['summary'] for row in rows}, {'3 quick guesses'})

    def test_quizzes_are_never_pending(self):
        attempt = self.quiz_attempt(self.student)
        self.diagnose(attempt, self.make_question(1), 'guess')
        self.assertFalse(self.student_rows()[0]['results_pending'])
