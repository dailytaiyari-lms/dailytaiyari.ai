"""Response diagnosis: schema, fact assembly, persistence and state weights."""
from django.db import IntegrityError, transaction

from intelligence.models import (
    AttemptTimeline, ItemStats, ResponseDiagnosis, ResponseSelfReport,
)
from intelligence.services import diagnose, itemstats
from intelligence.services.events import record_attempt_events
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


class DiagnoseAttemptTests(DiagnosisTestCase):
    def build(self):
        """A finished 60-minute rich mock, 20 minutes in, four items:
        a 3-second wrong MCQ, an untouched MCQ, a ×10 numerical slip and an
        MCQ looked at for 40s and left blank."""
        self.guessed = self.make_item()
        self.untouched = self.make_item()
        self.slip = self.make_item(item_type='numerical', numerical=9.81)
        self.skipped = self.make_item()
        attempt = self.make_attempt(minutes_ago=30)
        self.answer(attempt, self.guessed, selected=[1])
        self.answer(attempt, self.slip, numerical=98.1)
        g, s, k = f'item:{self.guessed.id}', f'item:{self.slip.id}', f'item:{self.skipped.id}'
        self.make_timeline(attempt, [
            [0, 'e', g], [3000, 'a', g, {'sel': [1]}], [3000, 'l', g],
            [3000, 'e', s], [50000, 'a', s, {'num': '98.1'}], [60000, 'l', s],
            [60000, 'e', k], [100000, 'l', k],
        ])
        self.finish(attempt, after_minutes=20)
        record_attempt_events(attempt)
        return attempt

    def labels(self, attempt):
        return {
            row.mock_item_id: row
            for row in ResponseDiagnosis.objects.filter(attempt_id=attempt.id)
        }

    def test_every_item_gets_one_row_with_the_right_label(self):
        attempt = self.build()
        written = diagnose.diagnose_attempt('mock', str(attempt.id))
        self.assertEqual(written, 4)
        rows = self.labels(attempt)
        self.assertEqual(rows[self.guessed.id].label, 'guess')
        self.assertEqual(rows[self.untouched.id].label, 'not_seen')
        self.assertEqual(rows[self.slip.id].label, 'careless_slip')
        self.assertEqual(rows[self.skipped.id].label, 'skipped')
        row = rows[self.guessed.id]
        self.assertTrue(row.has_timeline)
        self.assertTrue(row.answered)
        self.assertEqual(row.final_label, 'guess')
        self.assertEqual(row.classifier_version, CLASSIFIER_VERSION)
        self.assertEqual(row.tenant, self.tenant)

    def test_is_idempotent_and_finalizes_the_timeline(self):
        attempt = self.build()
        diagnose.diagnose_attempt('mock', str(attempt.id))
        diagnose.diagnose_attempt('mock', str(attempt.id))
        self.assertEqual(ResponseDiagnosis.objects.filter(attempt_id=attempt.id).count(), 4)
        self.assertIsNotNone(AttemptTimeline.objects.get(attempt_id=attempt.id).finalized_at)

    def test_unfinished_attempt_is_not_diagnosed(self):
        attempt = self.make_attempt()
        self.assertEqual(diagnose.diagnose_attempt('mock', str(attempt.id)), 0)

    def test_no_timeline_degrades_without_inventing_time(self):
        item = self.make_item(item_type='numerical', numerical=9.81)
        attempt = self.make_attempt()
        self.answer(attempt, item, numerical=-9.81)
        self.finish(attempt)
        diagnose.diagnose_attempt('mock', str(attempt.id))
        row = ResponseDiagnosis.objects.get(attempt_id=attempt.id, mock_item=item)
        self.assertEqual(row.label, 'careless_slip')     # sign flip needs no timeline
        self.assertFalse(row.has_timeline)

    def test_self_report_is_kept_across_recompute(self):
        attempt = self.build()
        ResponseSelfReport.objects.create(
            tenant=self.tenant, student=self.student, attempt_kind='mock',
            attempt_id=attempt.id, mock_item=self.guessed, choice='guessed',
        )
        diagnose.diagnose_attempt('mock', str(attempt.id))
        row = ResponseDiagnosis.objects.get(attempt_id=attempt.id, mock_item=self.guessed)
        self.assertEqual(row.self_report, 'guessed')

    def test_right_to_wrong_from_the_answer_path(self):
        item = self.make_item()
        attempt = self.make_attempt(minutes_ago=30)
        self.answer(attempt, item, selected=[2])
        key = f'item:{item.id}'
        self.make_timeline(attempt, [
            [0, 'e', key], [30000, 'a', key, {'sel': [0]}],
            [60000, 'a', key, {'sel': [2]}], [70000, 'l', key],
        ])
        self.finish(attempt)
        diagnose.diagnose_attempt('mock', str(attempt.id))
        row = ResponseDiagnosis.objects.get(attempt_id=attempt.id, mock_item=item)
        self.assertEqual(row.label, 'second_guess')

    def test_item_stats_learn_the_median_active_time(self):
        attempt = self.build()
        diagnose.diagnose_attempt('mock', str(attempt.id))
        stats = itemstats.recompute_for_item(self.slip)
        self.assertEqual(stats.active_time_n, 1)
        self.assertAlmostEqual(stats.median_active_seconds, 57.0)
        # the 3-second guess is excluded from the usual-time sample
        stats = itemstats.recompute_for_item(self.guessed)
        self.assertEqual(stats.active_time_n, 0)
        self.assertIsNone(ItemStats.objects.get(mock_item=self.guessed).median_active_seconds)
