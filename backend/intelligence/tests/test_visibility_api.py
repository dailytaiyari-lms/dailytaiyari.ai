"""Diagnosis-visibility endpoints: switches, scope and payloads."""
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
        for n in range(22):
            attempt = self.quiz_attempt(self.student, minutes_ago=200 - n)
            label = 'second_guess' if n >= 19 else 'correct'
            self.diagnose(
                attempt, self.question, label,
                metrics={'active_s': 12.0, 'usual_s': 45.0},
                evidence=[{'code': 'right_to_wrong', 'detail': ''}] if n >= 19 else [],
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
