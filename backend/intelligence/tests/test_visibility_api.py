"""Diagnosis-visibility endpoints: switches, scope and payloads."""
from datetime import timedelta

from django.utils import timezone

from intelligence.diagnosis_config import THRESHOLDS
from intelligence.models import ResponseDiagnosis
from intelligence.versions import CLASSIFIER_VERSION
from intelligence.tests.visibility_fixtures import VisibilityTestCase

INSIGHTS = '/api/v1/tenant-admin/intelligence'


class AssessmentBehaviourTests(VisibilityTestCase):
    def url(self, quiz=None):
        return f'{INSIGHTS}/assessments/quiz/{(quiz or self.quiz).id}/behaviour/'

    def setUp(self):
        self.q1 = self.make_question(1)
        self.q2 = self.make_question(2)
        # 8 attempts on q1: 3 guesses (37.5 %) → many_guesses; q2 all correct.
        for n in range(8):
            attempt = self.quiz_attempt(self.student, minutes_ago=100 + n)
            label = 'guess' if n < 3 else 'correct'
            self.diagnose(attempt, self.q1, label,
                          metrics={'active_s': 10 + n, 'usual_s': 70.0},
                          self_report='guessed' if n == 0 else '')
            self.diagnose(attempt, self.q2, 'correct', metrics={'active_s': 30, 'usual_s': 70.0})

    def test_payload(self):
        response = self.client_for(self.faculty).get(self.url())
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual(data['answers'], 16)
        self.assertEqual(data['flagged'], 1)
        first = data['items'][0]
        self.assertEqual(first['item_key'], f'bank:{self.q1.id}')
        self.assertEqual(first['distribution']['counts']['guess'], 3)
        self.assertEqual(first['median_active_s'], 13.5)
        self.assertEqual(first['usual_s'], 70.0)
        self.assertEqual(first['self_reports'], 1)
        self.assertEqual([f['code'] for f in first['flags']], ['many_guesses'])
        self.assertEqual(data['items'][1]['flags'], [])

    def test_in_progress_attempts_are_ignored(self):
        attempt = self.quiz_attempt(self.student, status='in_progress')
        self.diagnose(attempt, self.q2, 'guess')
        self.assertEqual(self.client_for(self.admin).get(self.url()).json()['answers'], 16)

    def test_switch_off_is_403(self):
        self.tenant.features = {'response_diagnosis': True}
        self.tenant.save()
        self.assertEqual(self.client_for(self.admin).get(self.url()).status_code, 403)

    def test_requirement_off_is_403(self):
        self.tenant.features = {'diagnosis_teacher_view': True}
        self.tenant.save()
        self.assertEqual(self.client_for(self.admin).get(self.url()).status_code, 403)

    def test_scope(self):
        self.assertEqual(self.client_for(self.other_faculty).get(self.url()).status_code, 403)
        self.assertEqual(self.client_for(self.student_user).get(self.url()).status_code, 403)
        self.assertEqual(self.client_for(self.admin).get(self.url()).status_code, 200)

    def test_unknown_assessment_is_404(self):
        response = self.client_for(self.admin).get(
            f'{INSIGHTS}/assessments/quiz/{self.student.id}/behaviour/')
        self.assertEqual(response.status_code, 404)


class StudentAnswersTests(VisibilityTestCase):
    def url(self, student=None, page=None):
        base = f'{INSIGHTS}/students/{(student or self.student).id}/answers/'
        return f'{base}?page={page}' if page else base

    def setUp(self):
        self.question = self.make_question(1)
        # 22 attempts taken (and diagnosed) oldest first; the newest 3 are
        # second guesses. Attempts are listed in the order they were first
        # diagnosed, newest first.
        self.attempts = []
        first_diagnosed = timezone.now() - timedelta(hours=1)
        for n in range(22):
            attempt = self.quiz_attempt(self.student, minutes_ago=200 - n)
            label = 'second_guess' if n >= 19 else 'correct'
            diagnosis = self.diagnose(
                attempt, self.question, label,
                metrics={'active_s': 12.0, 'usual_s': 45.0},
                evidence=[{'code': 'right_to_wrong', 'detail': ''}] if n >= 19 else [],
            )
            # created_at is auto_now_add and rows made in a burst tie on a
            # coarse clock: give each attempt its own, increasing, time.
            ResponseDiagnosis.objects.filter(id=diagnosis.id).update(
                created_at=first_diagnosed + timedelta(seconds=n),
            )
            self.attempts.append(attempt)

    def test_first_page_has_20_attempts_and_patterns(self):
        response = self.client_for(self.faculty).get(self.url())
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual((data['page'], data['pages'], data['total_attempts']), (1, 2, 22))
        self.assertEqual(len(data['attempts']), 20)
        self.assertEqual(data['attempts'][0]['attempt_id'], str(self.attempts[-1].id))
        answer = data['attempts'][0]['answers'][0]
        self.assertEqual(answer['label'], 'second_guess')
        self.assertEqual(answer['label_display'], 'Changed a right answer')
        self.assertEqual(answer['evidence'], ['Changed a correct answer to a wrong one.'])
        self.assertEqual(answer['topic'], 'Kinematics')
        self.assertEqual([p['code'] for p in data['patterns']], ['changes_right_to_wrong'])

    def test_second_page_has_no_patterns(self):
        data = self.client_for(self.admin).get(self.url(page=2)).json()
        self.assertEqual(len(data['attempts']), 2)
        self.assertEqual(data['patterns'], [])

    def test_bad_page_falls_back_to_1(self):
        self.assertEqual(self.client_for(self.admin).get(self.url(page='x')).json()['page'], 1)

    def test_scope(self):
        self.assertEqual(self.client_for(self.faculty).get(self.url(self.outsider)).status_code, 403)
        self.assertEqual(self.client_for(self.other_faculty).get(self.url()).status_code, 403)
        self.assertEqual(self.client_for(self.student_user).get(self.url()).status_code, 403)

    def test_switch_off_is_403(self):
        self.tenant.features = {'response_diagnosis': True}
        self.tenant.save()
        self.assertEqual(self.client_for(self.admin).get(self.url()).status_code, 403)


class CourseBehaviourTests(VisibilityTestCase):
    def url(self, course=None):
        return f'{INSIGHTS}/courses/{(course or self.course).id}/behaviour/'

    def setUp(self):
        question = self.make_question(1)
        # 16 answers this week for student: 4 slips (25 %), 12 correct.
        for n in range(16):
            attempt = self.quiz_attempt(self.student, minutes_ago=60 + n)
            self.diagnose(attempt, question, 'careless_slip' if n < 4 else 'correct')
        # 2 answers 20 days ago: one guess.
        for n, label in enumerate(['guess', 'correct']):
            attempt = self.quiz_attempt(self.student, minutes_ago=20 * 24 * 60 + n)
            self.diagnose(attempt, question, label)
        # Outside the 28-day window: ignored.
        old = self.quiz_attempt(self.student, minutes_ago=40 * 24 * 60)
        self.diagnose(old, question, 'guess')

    def test_payload(self):
        response = self.client_for(self.faculty).get(self.url())
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual(data['rates']['answers'], 18)
        self.assertEqual(data['rates']['careless_slip'], round(4 / 18, 3))
        self.assertEqual(data['rates']['guess'], round(1 / 18, 3))
        self.assertEqual(len(data['trend']), 4)
        self.assertEqual(data['trend'][-1]['answers'], 16)
        self.assertEqual(data['trend'][-1]['careless_slip'], 0.25)
        self.assertEqual(data['trend'][1]['answers'], 2)
        self.assertIsNone(data['trend'][0]['guess'])
        self.assertEqual(len(data['students_to_check']), 1)
        self.assertEqual(data['students_to_check'][0]['student_id'], str(self.student.id))
        self.assertEqual(data['recent_assessments'][0]['id'], str(self.quiz.id))

    def test_scope_and_switch(self):
        self.assertEqual(self.client_for(self.faculty).get(self.url(self.other_course)).status_code, 403)
        self.tenant.features = {'response_diagnosis': True}
        self.tenant.save()
        self.assertEqual(self.client_for(self.admin).get(self.url()).status_code, 403)


class CalibrationTests(VisibilityTestCase):
    URL = f'{INSIGHTS}/diagnosis/calibration/'

    def test_admin_only(self):
        self.assertEqual(self.client_for(self.faculty).get(self.URL).status_code, 403)
        response = self.client_for(self.admin).get(self.URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['classifier_version'], CLASSIFIER_VERSION)
        self.assertEqual(response.json()['thresholds'], THRESHOLDS)


class MyAttemptDiagnosisTests(VisibilityTestCase):
    def setUp(self):
        self.q1 = self.make_question(1)
        self.q2 = self.make_question(2)
        self.q3 = self.make_question(3)
        self.attempt = self.quiz_attempt(self.student)
        self.diagnose(self.attempt, self.q1, 'guess', metrics={'active_s': 3.6})
        self.diagnose(self.attempt, self.q2, 'careless_slip', confidence='low')
        self.diagnose(self.attempt, self.q3, 'correct')

    def url(self, attempt=None, kind='quiz'):
        return f'/api/v1/intelligence/my/attempts/{kind}/{(attempt or self.attempt).id}/diagnosis/'

    def test_notes_are_medium_or_high_only(self):
        response = self.client_for(self.student_user).get(self.url())
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json(), {
            'notes': {f'bank:{self.q1.id}': 'Looks like a quick guess — you spent 4s here.'},
        })

    def test_payload_never_carries_a_label(self):
        body = self.client_for(self.student_user).get(self.url()).content.decode()
        self.assertNotIn('guess"', body)
        self.assertNotIn('careless_slip', body)

    def test_other_students_attempt_is_404(self):
        self.assertEqual(self.client_for(self.outsider_user).get(self.url()).status_code, 404)

    def test_in_progress_attempt_is_404(self):
        attempt = self.quiz_attempt(self.student, status='in_progress')
        self.assertEqual(self.client_for(self.student_user).get(self.url(attempt)).status_code, 404)

    def test_unknown_kind_is_404(self):
        self.assertEqual(
            self.client_for(self.student_user).get(self.url(kind='exam')).status_code, 404)

    def test_switch_off_is_403(self):
        self.tenant.features = {'response_diagnosis': True}
        self.tenant.save()
        self.assertEqual(self.client_for(self.student_user).get(self.url()).status_code, 403)
