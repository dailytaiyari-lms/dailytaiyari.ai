"""Response diagnosis: schema, fact assembly, persistence and state weights."""
from django.db import IntegrityError, transaction

from intelligence.models import AttemptTimeline, ResponseDiagnosis, ResponseSelfReport
from intelligence.tests.diagnosis_fixtures import DiagnosisTestCase
from intelligence.versions import CLASSIFIER_VERSION, STATE_MODEL_VERSION


class DiagnosisSchemaTests(DiagnosisTestCase):
    def test_versions(self):
        self.assertEqual(CLASSIFIER_VERSION, '1')
        self.assertEqual(STATE_MODEL_VERSION, '2')

    def test_feature_is_opt_in(self):
        from core.models import Tenant
        self.assertIn('response_diagnosis', Tenant.FEATURE_CHOICES)
        self.assertIn('response_diagnosis', Tenant.OPT_IN_FEATURES)
        plain = Tenant.objects.create(name='Plain', is_active=True)
        self.assertFalse(plain.get_features()['response_diagnosis'])

    def test_one_timeline_per_attempt(self):
        attempt = self.make_attempt()
        self.make_timeline(attempt, [])
        with self.assertRaises(IntegrityError), transaction.atomic():
            AttemptTimeline.objects.create(
                tenant=self.tenant, student=self.student, attempt_kind='mock',
                attempt_id=attempt.id,
            )

    def test_diagnosis_requires_exactly_one_item(self):
        attempt = self.make_attempt()
        with self.assertRaises(IntegrityError), transaction.atomic():
            ResponseDiagnosis.objects.create(
                tenant=self.tenant, student=self.student, attempt_kind='mock',
                attempt_id=attempt.id, label='unclear', final_label='unclear',
            )

    def test_one_self_report_per_attempt_item(self):
        attempt = self.make_attempt()
        item = self.make_item()
        ResponseSelfReport.objects.create(
            tenant=self.tenant, student=self.student, attempt_kind='mock',
            attempt_id=attempt.id, mock_item=item, choice='guessed',
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            ResponseSelfReport.objects.create(
                tenant=self.tenant, student=self.student, attempt_kind='mock',
                attempt_id=attempt.id, mock_item=item, choice='slipped',
            )
