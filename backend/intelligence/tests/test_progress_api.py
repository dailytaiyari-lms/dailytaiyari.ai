"""My Progress: switch, endpoints, scope and opt-out."""
import uuid

from django.test import TestCase

from core.models import Tenant
from intelligence import api
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
