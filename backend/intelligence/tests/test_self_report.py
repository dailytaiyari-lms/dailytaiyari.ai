"""Self-report ground truth + the admin calibration report."""
from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from intelligence.models import ResponseDiagnosis, ResponseSelfReport
from intelligence.tests.diagnosis_fixtures import DiagnosisTestCase
from core.models import Tenant
from quiz.models import (
    MockTest, MockTestAttempt, MockTestItem, Question, QuestionOption, Quiz,
    QuizAttempt, QuizQuestion,
)
from users.models import User

URL = '/api/v1/intelligence/self-report/'
CALIBRATION = '/api/v1/tenant-admin/intelligence/diagnosis/calibration/'


class SelfReportTests(DiagnosisTestCase):
    def setUp(self):
        self.item = self.make_item()
        self.attempt = self.finish(self.make_attempt())
        self.diag = ResponseDiagnosis.objects.create(
            tenant=self.tenant, student=self.student, attempt_kind='mock',
            attempt_id=self.attempt.id, mock_item=self.item, answered=True,
            is_correct=False, label='unclear', final_label='unclear', confidence='low',
            flags=[], metrics={'timed_out': False},
        )

    def client_for(self, user):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(user).access_token}')
        return client

    def post(self, choice='slipped', user=None, **overrides):
        body = {'attempt_kind': 'mock', 'attempt_id': str(self.attempt.id),
                'item_kind': 'item', 'item_id': str(self.item.id), 'choice': choice}
        body.update(overrides)
        return self.client_for(user or self.user).post(
            URL, body, format='json', HTTP_X_TENANT_ID=str(self.tenant.id))

    def test_report_is_saved_and_reconciled(self):
        response = self.post('slipped')
        self.assertEqual(response.status_code, 200, response.content)
        self.diag.refresh_from_db()
        self.assertEqual(self.diag.self_report, 'slipped')
        self.assertEqual(self.diag.final_label, 'careless_slip')
        # changing your mind replaces the report
        self.post('didnt_know')
        self.assertEqual(ResponseSelfReport.objects.get().choice, 'didnt_know')

    def test_get_returns_reports_and_not_seen(self):
        self.post('guessed')
        unseen = self.make_item()
        ResponseDiagnosis.objects.create(
            tenant=self.tenant, student=self.student, attempt_kind='mock',
            attempt_id=self.attempt.id, mock_item=unseen, label='not_seen',
            final_label='not_seen', confidence='high',
        )
        response = self.client_for(self.user).get(
            URL, {'attempt_kind': 'mock', 'attempt_id': str(self.attempt.id)},
            HTTP_X_TENANT_ID=str(self.tenant.id))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['reports'], {f'item:{self.item.id}': 'guessed'})
        self.assertEqual(response.data['not_seen'], [f'item:{unseen.id}'])

    def test_correct_answers_take_no_report(self):
        self.diag.is_correct = True
        self.diag.save()
        self.assertEqual(self.post().status_code, 400)

    def test_unknown_choice_is_400(self):
        self.assertEqual(self.post('nope').status_code, 400)

    def test_item_not_in_attempt_is_400(self):
        self.assertEqual(self.post(item_id=str(self.make_attempt().id)).status_code, 400)

    def test_other_students_attempt_is_404(self):
        self.assertEqual(self.post(user=self.other_user).status_code, 404)

    def test_non_string_choice_is_400(self):
        self.assertEqual(self.post(choice=[]).status_code, 400)
        self.assertEqual(self.post(choice={'a': 1}).status_code, 400)

    def test_non_string_attempt_kind_is_not_500(self):
        self.assertIn(self.post(attempt_kind=['mock']).status_code, (400, 404))

    def test_non_string_attempt_id_and_item_id_are_not_500(self):
        self.assertIn(self.post(attempt_id=['x']).status_code, (400, 404))
        self.assertEqual(self.post(item_id=['x']).status_code, 400)
        self.assertEqual(self.post(item_kind=['item']).status_code, 400)

    def test_json_list_body_is_400(self):
        response = self.client_for(self.user).post(
            URL, [1, 2], format='json', HTTP_X_TENANT_ID=str(self.tenant.id))
        self.assertEqual(response.status_code, 400)

    def test_get_bad_uuid_is_404(self):
        response = self.client_for(self.user).get(
            URL, {'attempt_kind': 'mock', 'attempt_id': 'not-a-uuid'},
            HTTP_X_TENANT_ID=str(self.tenant.id))
        self.assertEqual(response.status_code, 404)

    def test_unknown_item_kind_is_400(self):
        self.assertEqual(self.post(item_kind='other').status_code, 400)

    def test_unknown_attempt_kind_is_404(self):
        self.assertEqual(self.post(attempt_kind='exam').status_code, 404)

    def test_pending_diagnosis_still_stores_report(self):
        ResponseDiagnosis.objects.all().delete()
        response = self.post('guessed')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(ResponseSelfReport.objects.get().choice, 'guessed')

    def test_ran_out_of_time_needs_evidence(self):
        self.assertEqual(self.post('ran_out_of_time').status_code, 200)
        self.diag.refresh_from_db()
        self.assertEqual(self.diag.final_label, 'unclear')
        self.diag.flags = ['last_minute']
        self.diag.save()
        self.assertEqual(self.post('ran_out_of_time').status_code, 200)
        self.diag.refresh_from_db()
        self.assertEqual(self.diag.final_label, 'time_pressure')

    def _quiz_attempt(self):
        quiz = Quiz.objects.create(
            tenant=self.tenant, course=self.course, title='Q', quiz_type='topic',
            duration_minutes=15)
        question = self._bank_question(1)
        QuizQuestion.objects.create(quiz=quiz, question=question)
        attempt = QuizAttempt.objects.create(
            student=self.student, quiz=quiz, status='completed',
            completed_at=timezone.now())
        return attempt, question

    def _bank_question(self, n):
        question = Question.objects.create(
            tenant=self.tenant, topic=self.topic, subject=self.subject,
            question_text=f'Bank question {n}?', question_type='mcq',
            difficulty='medium', status='published', correct_answer='0', marks=1)
        for i in range(3):
            QuestionOption.objects.create(
                tenant=self.tenant, question=question, option_text=f'Option {i}',
                is_correct=(i == 0), order=i)
        return question

    def test_quiz_attempt_with_bank_question(self):
        attempt, question = self._quiz_attempt()
        response = self.post(
            'guessed', attempt_kind='quiz', attempt_id=str(attempt.id),
            item_kind='bank', item_id=str(question.id))
        self.assertEqual(response.status_code, 200, response.content)
        got = self.client_for(self.user).get(
            URL, {'attempt_kind': 'quiz', 'attempt_id': str(attempt.id)},
            HTTP_X_TENANT_ID=str(self.tenant.id))
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.data['reports'], {f'bank:{question.id}': 'guessed'})

    def test_bank_question_outside_quiz_is_400(self):
        attempt, _ = self._quiz_attempt()
        stray = self._bank_question(2)
        response = self.post(
            attempt_kind='quiz', attempt_id=str(attempt.id),
            item_kind='bank', item_id=str(stray.id))
        self.assertEqual(response.status_code, 400)

    def test_in_progress_attempt_is_404(self):
        live = self.make_attempt()
        self.assertEqual(self.post(attempt_id=str(live.id)).status_code, 404)

    def test_feature_gate(self):
        self.tenant.features = {}
        self.tenant.save()
        self.assertEqual(self.post().status_code, 403)


class CalibrationTests(DiagnosisTestCase):
    def test_confusion_and_agreement(self):
        admin = User.objects.create_user(
            email='diag-admin@example.com', password='pw-admin-1',
            tenant=self.tenant, role='admin',
        )
        attempt = self.finish(self.make_attempt())
        for label, report, timeline in (('guess', 'guessed', True), ('guess', 'slipped', True),
                                        ('concept_gap', '', False)):
            ResponseDiagnosis.objects.create(
                tenant=self.tenant, student=self.student, attempt_kind='mock',
                attempt_id=attempt.id, mock_item=self.make_item(), label=label,
                final_label=label, self_report=report, has_timeline=timeline,
                metrics={'usual_source': 'default'},
                computed_at=attempt.completed_at,
            )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(admin).access_token}')
        response = client.get(CALIBRATION, {'days': 30}, HTTP_X_TENANT_ID=str(self.tenant.id))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data['total'], 3)
        self.assertEqual(response.data['with_timeline'], 2)
        self.assertEqual(response.data['labels'], {'guess': 2, 'concept_gap': 1})
        self.assertEqual(response.data['confusion'], {'guess': {'guessed': 1, 'slipped': 1}})
        self.assertEqual(response.data['agreement'], {'guess': 0.5})

    def _admin_client(self):
        admin = User.objects.create_user(
            email='diag-admin2@example.com', password='pw-admin-1',
            tenant=self.tenant, role='admin')
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(admin).access_token}')
        return client

    def _diag(self, **kwargs):
        attempt = self.finish(self.make_attempt())
        return ResponseDiagnosis.objects.create(
            tenant=self.tenant, student=self.student, attempt_kind='mock',
            attempt_id=attempt.id, mock_item=self.make_item(), label='guess',
            final_label='guess', computed_at=timezone.now(), **kwargs)

    def test_other_tenant_rows_not_counted(self):
        self._diag()
        tenant2 = Tenant.objects.create(
            name='Other Academy', is_active=True, features={'response_diagnosis': True})
        user2 = User.objects.create_user(
            email='t2-student@example.com', password='pw-t2-1',
            tenant=tenant2, role='student')
        mock2 = MockTest.objects.create(
            tenant=tenant2, course=self.course, title='P2', duration_minutes=60,
            total_marks=4)
        item2 = MockTestItem.objects.create(
            tenant=tenant2, mock_test=mock2, item_type='mcq', question_text='Q?',
            marks=4, options=[])
        attempt2 = MockTestAttempt.objects.create(
            tenant=tenant2, student=user2.profile, mock_test=mock2, status='completed')
        ResponseDiagnosis.objects.create(
            tenant=tenant2, student=user2.profile, attempt_kind='mock',
            attempt_id=attempt2.id, mock_item=item2, label='guess', final_label='guess',
            computed_at=timezone.now())
        response = self._admin_client().get(
            CALIBRATION, HTTP_X_TENANT_ID=str(self.tenant.id))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['total'], 1)

    def test_bad_days_falls_back_to_30(self):
        response = self._admin_client().get(
            CALIBRATION, {'days': 'abc'}, HTTP_X_TENANT_ID=str(self.tenant.id))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['days'], 30)

    def test_days_window(self):
        diag = self._diag()
        ResponseDiagnosis.objects.filter(id=diag.id).update(
            computed_at=timezone.now() - timedelta(days=60))
        client = self._admin_client()
        h = {'HTTP_X_TENANT_ID': str(self.tenant.id)}
        self.assertEqual(client.get(CALIBRATION, {'days': 30}, **h).data['total'], 0)
        self.assertEqual(client.get(CALIBRATION, {'days': 90}, **h).data['total'], 1)

    def test_students_cannot_read_it(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(self.user).access_token}')
        response = client.get(CALIBRATION, HTTP_X_TENANT_ID=str(self.tenant.id))
        self.assertEqual(response.status_code, 403)


class RichReviewRefTests(DiagnosisTestCase):
    def test_review_entries_carry_ref_ids(self):
        from quiz.mock_grading import build_review

        item = self.make_item()
        attempt = self.finish(self.make_attempt())
        self.answer(attempt, item, selected=[1])
        entries = build_review(attempt)
        self.assertEqual(entries[0]['kind'], 'item')
        self.assertEqual(entries[0]['ref_id'], str(item.id))
