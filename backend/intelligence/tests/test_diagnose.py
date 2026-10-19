"""Response diagnosis: schema, fact assembly, persistence and state weights."""
from datetime import timedelta

from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.utils import timezone

from intelligence.models import (
    AttemptTimeline, ConceptLink, ItemStats, LearnerConceptState, PracticeSet,
    PracticeSetItem, ResponseDiagnosis, ResponseSelfReport,
)
from intelligence import recommendation
from intelligence.services import diagnose, itemstats
from intelligence.services import practice as practice_service
from intelligence.services.events import record_attempt_events
from intelligence.services.state import recompute_state
from intelligence.tests.diagnosis_fixtures import DiagnosisTestCase
from intelligence.tests.test_practice import PracticeTestCase
from quiz.models import Answer, Question, QuestionOption, Quiz, QuizAttempt, QuizQuestion
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

    def test_answered_item_with_no_answer_event_has_no_timing(self):
        item = self.make_item()
        attempt = self.make_attempt(minutes_ago=30)
        self.answer(attempt, item, selected=[1])
        key = f'item:{item.id}'
        self.make_timeline(attempt, [[0, 'e', key], [3000, 'l', key]])
        self.finish(attempt, after_minutes=20)
        diagnose.diagnose_attempt('mock', str(attempt.id))
        row = ResponseDiagnosis.objects.get(attempt_id=attempt.id, mock_item=item)
        self.assertNotEqual(row.label, 'guess')
        self.assertFalse(row.has_timeline)

    def test_answered_item_whose_last_change_is_a_clear_has_no_timing(self):
        item = self.make_item()
        attempt = self.make_attempt(minutes_ago=30)
        self.answer(attempt, item, selected=[1])
        k = f'item:{item.id}'
        self.make_timeline(attempt, [
            [0, 'e', k], [5000, 'a', k, {'sel': [1]}], [9000, 'c', k], [12000, 'l', k],
        ])
        self.finish(attempt, after_minutes=20)
        diagnose.diagnose_attempt('mock', str(attempt.id))
        row = ResponseDiagnosis.objects.get(attempt_id=attempt.id, mock_item=item)
        self.assertFalse(row.has_timeline)
        self.assertNotIn(row.label, ('guess', 'rushed', 'overthought', 'careless_slip'))

    def test_row_writes_are_atomic(self):
        from unittest import mock

        from intelligence.services import diagnosis as rules

        first, second = self.make_item(), self.make_item()
        attempt = self.make_attempt(minutes_ago=30)
        self.answer(attempt, first, selected=[1])
        self.answer(attempt, second, selected=[1])
        self.finish(attempt, after_minutes=20)
        real = rules.classify
        calls = {'n': 0}

        def flaky(*args, **kwargs):
            calls['n'] += 1
            if calls['n'] > 1:
                raise RuntimeError('boom')
            return real(*args, **kwargs)

        with mock.patch('intelligence.services.diagnosis.classify', side_effect=flaky):
            with self.assertRaises(RuntimeError):
                diagnose.diagnose_attempt('mock', str(attempt.id))
        self.assertEqual(ResponseDiagnosis.objects.filter(attempt_id=attempt.id).count(), 0)

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


class DiagnoseFixRoundTests(DiagnosisTestCase):
    def make_bank_question(self, n):
        question = Question.objects.create(
            tenant=self.tenant, topic=self.topic, subject=self.subject,
            question_text=f'Bank question {n}?', question_type='mcq',
            difficulty='medium', status='published', correct_answer='0', marks=1,
        )
        for i in range(3):
            QuestionOption.objects.create(
                tenant=self.tenant, question=question, option_text=f'Option {i}',
                is_correct=(i == 0), order=i,
            )
        ConceptLink.objects.create(
            tenant=self.tenant, concept=self.concept, question=question,
            is_primary=True, weight=1.0, source='generator',
        )
        return question

    def test_blank_subjective_row_is_skipped_not_pending(self):
        item = self.make_item(item_type='subjective')
        attempt = self.make_attempt(minutes_ago=30)
        self.answer(attempt, item, text='', needs_manual=True)
        key = f'item:{item.id}'
        self.make_timeline(attempt, [[0, 'e', key], [40000, 'l', key]])
        self.finish(attempt)
        diagnose.diagnose_attempt('mock', str(attempt.id))
        row = ResponseDiagnosis.objects.get(attempt_id=attempt.id, mock_item=item)
        self.assertFalse(row.answered)
        self.assertEqual(row.label, 'skipped')

    def test_corrupt_only_session_is_treated_as_no_timeline(self):
        item = self.make_item()
        attempt = self.make_attempt()
        AttemptTimeline.objects.create(
            tenant=self.tenant, student=self.student, attempt_kind='mock',
            attempt_id=attempt.id, clock='server', sessions={'s1': 'not-a-dict'},
        )
        self.finish(attempt)
        diagnose.diagnose_attempt('mock', str(attempt.id))
        row = ResponseDiagnosis.objects.get(attempt_id=attempt.id, mock_item=item)
        self.assertEqual(row.label, 'unclear')
        self.assertFalse(row.has_timeline)

    def test_quiz_loader_rows_and_server_clock_answer_time(self):
        quiz = Quiz.objects.create(
            tenant=self.tenant, course=self.course, title='Q', quiz_type='topic',
            duration_minutes=15,
        )
        q1, q2 = self.make_bank_question(1), self.make_bank_question(2)
        QuizQuestion.objects.create(quiz=quiz, question=q1)
        QuizQuestion.objects.create(quiz=quiz, question=q2)
        attempt = QuizAttempt.objects.create(student=self.student, quiz=quiz)
        QuizAttempt.objects.filter(id=attempt.id).update(
            started_at=timezone.now() - timedelta(minutes=30))
        attempt.refresh_from_db()
        Answer.objects.create(quiz_attempt=attempt, question=q1, selected_option='1',
                              is_correct=False)
        k = f'bank:{q1.id}'
        self.make_timeline(attempt, [
            [0, 'e', k], [20000, 'a', k, {'sel': [1]}], [25000, 'l', k],
        ], clock='server', offset_ms=60000, kind='quiz')
        attempt.status = 'completed'
        attempt.completed_at = attempt.started_at + timedelta(minutes=10)
        attempt.save()
        self.assertEqual(diagnose.diagnose_attempt('quiz', str(attempt.id)), 2)
        rows = {r.question_id: r for r in ResponseDiagnosis.objects.filter(attempt_id=attempt.id)}
        self.assertTrue(rows[q1.id].answered)
        self.assertEqual(rows[q2.id].label, 'not_seen')
        # server clock: the window starts at the anchor, so the 60s offset shifts it
        self.assertAlmostEqual(rows[q1.id].metrics['final_answer_at_s'], 80.0, delta=1.0)

    def test_practice_loader_rows_are_untimed(self):
        q1, q2 = self.make_bank_question(1), self.make_bank_question(2)
        practice_set = PracticeSet.objects.create(
            tenant=self.tenant, student=self.student, course=self.course,
            status='completed', deficit_kind='starter', deficit_signature='starter:t',
            started_at=timezone.now() - timedelta(minutes=10),
            completed_at=timezone.now(),
        )
        PracticeSetItem.objects.create(
            tenant=self.tenant, practice_set=practice_set, question=q1, order=0,
            selected_options=[1], is_correct=False, answered_at=timezone.now())
        PracticeSetItem.objects.create(
            tenant=self.tenant, practice_set=practice_set, question=q2, order=1)
        self.assertEqual(diagnose.diagnose_attempt('practice', str(practice_set.id)), 2)
        rows = ResponseDiagnosis.objects.filter(attempt_id=practice_set.id)
        self.assertEqual({r.attempt_kind for r in rows}, {'practice'})
        for row in rows:
            self.assertNotIn('last_minute', row.flags)

    def test_practice_digest_graded_by_option_flags(self):
        q = self.make_bank_question(1)
        q.correct_answer = '2'       # stale; practice grades by is_correct options
        q.save()
        q = Question.objects.prefetch_related('options').get(id=q.id)
        ref = diagnose._Ref('q', q, True, 0.0, False, [0], None, practice=True)
        self.assertTrue(diagnose._digest_correct(ref, {'sel': [0]}))
        ref.practice = False
        self.assertFalse(diagnose._digest_correct(ref, {'sel': [0]}))

    def test_prior_mastery_uses_only_evidence_before_the_attempt(self):
        first = self.make_item()
        old = self.make_attempt(minutes_ago=300)
        self.answer(old, first, selected=[1])
        self.finish(old, after_minutes=20)
        record_attempt_events(old)
        item = self.make_item()
        new = self.make_attempt(minutes_ago=30)
        self.answer(new, item, selected=[2])
        self.finish(new)
        record_attempt_events(new)
        diagnose.diagnose_attempt('mock', str(new.id))
        row = ResponseDiagnosis.objects.get(attempt_id=new.id, mock_item=item)
        self.assertIn('prior_mastery', row.metrics)

    def test_own_events_are_not_prior_mastery(self):
        item = self.make_item()
        attempt = self.make_attempt(minutes_ago=30)
        self.answer(attempt, item, selected=[2])
        self.finish(attempt)
        record_attempt_events(attempt)
        diagnose.diagnose_attempt('mock', str(attempt.id))
        row = ResponseDiagnosis.objects.get(attempt_id=attempt.id, mock_item=item)
        self.assertNotIn('prior_mastery', row.metrics)


class DiagnosisWeightTests(DiagnosisTestCase):
    def wrong_attempt(self):
        item = self.make_item()
        attempt = self.make_attempt()
        self.answer(attempt, item, selected=[1])
        self.finish(attempt)
        record_attempt_events(attempt)
        return attempt, item

    def test_guess_weighs_less_than_an_honest_miss(self):
        attempt, item = self.wrong_attempt()
        recompute_state(self.student, self.concept)
        honest = LearnerConceptState.objects.get(student=self.student, concept=self.concept)
        # (0*1 + 3*0.5) / (1 + 3)
        self.assertAlmostEqual(honest.mastery, 0.375, places=3)

        ResponseDiagnosis.objects.create(
            tenant=self.tenant, student=self.student, attempt_kind='mock',
            attempt_id=attempt.id, mock_item=item, answered=True, is_correct=False,
            label='guess', final_label='guess', confidence='high',
        )
        recompute_state(self.student, self.concept)
        guessed = LearnerConceptState.objects.get(student=self.student, concept=self.concept)
        # (0*0.2 + 3*0.5) / (0.2 + 3)
        self.assertAlmostEqual(guessed.mastery, 0.4688, places=3)
        self.assertEqual(guessed.model_version, '2')

    def test_api_hook_diagnoses_then_updates_state(self):
        from intelligence import api

        attempt, item = self.wrong_attempt()
        api.record_attempt_events(attempt)   # Celery is eager in tests
        self.assertTrue(ResponseDiagnosis.objects.filter(attempt_id=attempt.id).exists())
        self.assertTrue(LearnerConceptState.objects.filter(
            student=self.student, concept=self.concept).exists())

    def test_recompute_command(self):
        attempt, _item = self.wrong_attempt()
        call_command('recompute_diagnoses', verbosity=0)
        self.assertEqual(ResponseDiagnosis.objects.filter(attempt_id=attempt.id).count(), 1)


class SweepAndRecomputeResilienceTests(DiagnosisTestCase):
    def wrong_attempt(self, student=None):
        item = self.make_item()
        attempt = self.make_attempt(student=student)
        self.answer(attempt, item, selected=[1])
        self.finish(attempt)
        record_attempt_events(attempt)
        return attempt, item

    def test_nightly_sweep_survives_one_bad_attempt(self):
        from unittest import mock

        from intelligence import tasks
        from intelligence.services import state as state_module

        bad, _ = self.wrong_attempt()
        good, _ = self.wrong_attempt(student=self.other_user.profile)
        real = state_module.update_for_attempt

        def flaky(kind, attempt_id):
            if str(attempt_id) == str(bad.id):
                raise RuntimeError('boom')
            return real(kind, attempt_id)

        with mock.patch('intelligence.services.state.update_for_attempt', side_effect=flaky):
            tasks.refresh_learner_state()

        self.assertTrue(LearnerConceptState.objects.filter(
            student=self.other_user.profile, concept=self.concept).exists())
        for attempt in (bad, good):
            self.assertTrue(ResponseDiagnosis.objects.filter(attempt_id=attempt.id).exists())

    def test_recompute_survives_one_bad_attempt(self):
        from io import StringIO
        from unittest import mock

        bad, _ = self.wrong_attempt()
        good, _ = self.wrong_attempt(student=self.other_user.profile)
        real = diagnose.diagnose_attempt

        def flaky(kind, attempt_id):
            if str(attempt_id) == str(bad.id):
                raise RuntimeError('boom')
            return real(kind, attempt_id)

        out, err = StringIO(), StringIO()
        with mock.patch('intelligence.services.diagnose.diagnose_attempt', side_effect=flaky):
            call_command('recompute_diagnoses', stdout=out, stderr=err)
        self.assertEqual(ResponseDiagnosis.objects.filter(attempt_id=good.id).exists(), True)
        self.assertFalse(ResponseDiagnosis.objects.filter(attempt_id=bad.id).exists())
        self.assertIn(str(bad.id), err.getvalue())
        self.assertIn('1 failure(s)', out.getvalue())
        self.assertIn('Diagnosed 1 attempt(s)', out.getvalue())

    def test_recompute_guess_weight_reaches_mastery(self):
        item = self.make_item()
        attempt = self.make_attempt(minutes_ago=30)
        self.answer(attempt, item, selected=[1])
        key = f'item:{item.id}'
        self.make_timeline(attempt, [
            [0, 'e', key], [3000, 'a', key, {'sel': [1]}], [3000, 'l', key],
        ])
        self.finish(attempt, after_minutes=20)
        record_attempt_events(attempt)
        call_command('recompute_diagnoses', verbosity=0)
        row = ResponseDiagnosis.objects.get(attempt_id=attempt.id, mock_item=item)
        self.assertEqual(row.final_label, 'guess')
        state = LearnerConceptState.objects.get(student=self.student, concept=self.concept)
        self.assertAlmostEqual(state.mastery, 0.4688, places=3)

    def test_since_filters_out_older_attempts(self):
        from intelligence.models import LearningEvent

        attempt, _ = self.wrong_attempt()
        LearningEvent.objects.filter(attempt_id=attempt.id).update(
            occurred_at=timezone.now() - timedelta(days=30))
        since = (timezone.now() - timedelta(days=2)).strftime('%Y-%m-%d')
        call_command('recompute_diagnoses', since=since, verbosity=0)
        self.assertFalse(ResponseDiagnosis.objects.filter(attempt_id=attempt.id).exists())
        call_command('recompute_diagnoses', verbosity=0)
        self.assertTrue(ResponseDiagnosis.objects.filter(attempt_id=attempt.id).exists())


class PracticeDiagnosisHookTests(PracticeTestCase):
    def answered_set(self, selected):
        for n in range(12):
            self.make_question(n, difficulty='easy')
        self.make_low_mastery_state()
        practice_set = recommendation.refresh_recommendations(self.student, self.course)[0]
        item = practice_set.items.select_related('question').order_by('order').first()
        practice_service.answer_item(practice_set, str(item.id), selected_options=selected)
        return practice_set, item

    def test_diagnosis_runs_on_submit(self):
        practice_set, item = self.answered_set([1])
        practice_service.submit_set(practice_set)
        rows = ResponseDiagnosis.objects.filter(
            attempt_kind='practice', attempt_id=practice_set.id)
        self.assertTrue(rows.exists())
        self.assertTrue(rows.filter(question=item.question).exists())

    def test_diagnosis_failure_never_fails_the_submit(self):
        from unittest import mock

        practice_set, _ = self.answered_set([0])
        with mock.patch('intelligence.services.diagnose.diagnose_attempt',
                        side_effect=RuntimeError('boom')):
            practice_service.submit_set(practice_set)
        practice_set.refresh_from_db()
        self.assertEqual(practice_set.status, 'completed')

    def test_practice_guess_label_scales_the_practice_weight(self):
        practice_set, item = self.answered_set([1])
        practice_service.submit_set(practice_set)
        ResponseDiagnosis.objects.filter(
            attempt_kind='practice', attempt_id=practice_set.id, question=item.question,
        ).update(label='guess', final_label='guess')
        recompute_state(self.student, self.concept)
        state = LearnerConceptState.objects.get(student=self.student, concept=self.concept)
        # weight 0.6 (practice) x 0.2 (guess) = 0.12; wrong answer scores 0.
        self.assertAlmostEqual(state.mastery, (0 + 1.5) / (0.12 + 3), places=3)


class RecomputeCommandOrderTests(DiagnosisTestCase):
    def test_bad_since_is_a_command_error(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command('recompute_diagnoses', since='not-a-date')

    def test_attempts_run_oldest_first(self):
        from unittest import mock

        newer_item, older_item = self.make_item(), self.make_item()
        newer = self.make_attempt(minutes_ago=10)
        self.answer(newer, newer_item, selected=[1])
        self.finish(newer, after_minutes=5)
        older = self.make_attempt(minutes_ago=300, student=self.other_user.profile)
        self.answer(older, older_item, selected=[1])
        self.finish(older, after_minutes=5)
        record_attempt_events(newer)    # created first, but its events are newer
        record_attempt_events(older)
        calls = []
        with mock.patch('intelligence.services.diagnose.diagnose_attempt',
                        side_effect=lambda kind, attempt_id: calls.append(str(attempt_id)) or 0):
            call_command('recompute_diagnoses', verbosity=0)
        self.assertEqual(calls, [str(older.id), str(newer.id)])
