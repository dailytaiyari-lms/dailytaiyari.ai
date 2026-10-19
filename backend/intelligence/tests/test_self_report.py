"""Self-report ground truth + the admin calibration report."""
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from intelligence.models import ResponseDiagnosis, ResponseSelfReport
from intelligence.tests.diagnosis_fixtures import DiagnosisTestCase
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

    def test_validation(self):
        self.assertEqual(self.post('nope').status_code, 400)
        self.assertEqual(self.post(item_id=str(self.make_attempt().id)).status_code, 400)
        self.assertEqual(self.post(user=self.other_user).status_code, 404)

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

    def test_students_cannot_read_it(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(self.user).access_token}')
        response = client.get(CALIBRATION, HTTP_X_TENANT_ID=str(self.tenant.id))
        self.assertEqual(response.status_code, 403)
