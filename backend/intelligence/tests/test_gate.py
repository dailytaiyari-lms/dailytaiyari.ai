"""The learning layer is opt-in per tenant.

A tenant with none of ``practice``, ``ai_grading`` or ``response_diagnosis``
enabled must behave exactly as before the layer existed: no LearningEvents,
no Celery enqueues, no timeline rows, no tagging sweep, no nightly writes.
"""
from io import StringIO
from unittest import mock

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.models import Tenant
from exams.models import Course, Subject, Topic
from intelligence import api, tasks
from intelligence.models import (
    AttemptTimeline, ItemStats, LearnerConceptState, LearningEvent, ResponseDiagnosis,
)
from intelligence.services import events as event_service
from quiz.models import (
    Answer, MockTest, MockTestAnswer, MockTestAttempt, MockTestItem,
    Question, QuestionOption, Quiz, QuizAttempt, QuizQuestion,
)
from users.models import CourseEnrollment, User


class GateFixture(TestCase):
    """One tenant whose features each test sets; a student enrolled in one
    active course with a published quiz and a published open rich mock."""

    features = {}

    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create(
            name='Gate Academy', is_active=True, features=dict(cls.features),
        )
        cls.user = User.objects.create_user(
            email='gate-student@example.com', password='pw-gate-1',
            tenant=cls.tenant, role='student',
        )
        cls.student = cls.user.profile
        cls.course = Course.objects.create(
            tenant=cls.tenant, name='Physics', code='gate-physics',
            course_type='competitive', status='active',
        )
        CourseEnrollment.objects.create(
            tenant=cls.tenant, student=cls.student, course=cls.course,
            status='approved', is_active=True,
        )
        cls.subject = Subject.objects.create(
            tenant=cls.tenant, course=cls.course, name='Mechanics', code='gate-mech',
        )
        cls.topic = Topic.objects.create(
            tenant=cls.tenant, subject=cls.subject, name='Motion', code='gate-motion',
        )

    def setUp(self):
        cache.clear()  # submit / timeline throttles must not leak between tests

    def api_client(self):
        client = APIClient()
        client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(self.user).access_token}',
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )
        return client

    def make_question(self):
        question = Question.objects.create(
            tenant=self.tenant, topic=self.topic, subject=self.subject,
            question_text='What is v for a body at rest?', question_type='mcq',
            correct_answer='0', status='published',
        )
        QuestionOption.objects.create(
            tenant=self.tenant, question=question, option_text='0', is_correct=True, order=0,
        )
        QuestionOption.objects.create(
            tenant=self.tenant, question=question, option_text='1', is_correct=False, order=1,
        )
        return question

    def make_quiz(self):
        quiz = Quiz.objects.create(
            tenant=self.tenant, course=self.course, subject=self.subject, topic=self.topic,
            title='Kinematics quiz', quiz_type='topic', status='published',
            duration_minutes=10,
        )
        question = self.make_question()
        QuizQuestion.objects.create(tenant=self.tenant, quiz=quiz, question=question, order=0)
        return quiz, question

    def make_rich_mock(self):
        mock_test = MockTest.objects.create(
            tenant=self.tenant, title='Open paper', duration_minutes=60,
            total_marks=4, status='published',
        )
        item = MockTestItem.objects.create(
            tenant=self.tenant, mock_test=mock_test, item_type='mcq',
            question_text='Pick A', marks=4, topic=self.topic, subject=self.subject,
            options=[{'text': 'A', 'is_correct': True}, {'text': 'B', 'is_correct': False}],
        )
        return mock_test, item

    def submit_quiz(self):
        quiz, question = self.make_quiz()
        client = self.api_client()
        response = client.post(
            f'/api/v1/quiz/quizzes/{quiz.id}/submit/',
            {'answers': [{'question_id': str(question.id), 'selected_option': '0',
                          'time_taken_seconds': 7}],
             'time_taken_seconds': 30},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.content)
        return QuizAttempt.objects.get(quiz=quiz, student=self.student)

    def submit_rich(self):
        mock_test, item = self.make_rich_mock()
        client = self.api_client()
        started = client.post(f'/api/v1/quiz/mock-tests/{mock_test.id}/start_rich/', format='json')
        self.assertIn(started.status_code, (200, 201), started.content)
        response = client.post(
            f'/api/v1/quiz/mock-tests/{mock_test.id}/submit_rich/',
            {'bank_answers': [],
             'item_answers': [{'item_id': str(item.id), 'selected_options': [0]}]},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.content)
        return MockTestAttempt.objects.get(mock_test=mock_test, student=self.student)


class IntelligenceEnabledHelperTests(TestCase):
    def test_missing_tenant_is_disabled(self):
        self.assertFalse(api.intelligence_enabled(None))

    def test_no_learning_feature_is_disabled(self):
        self.assertFalse(api.intelligence_enabled(Tenant(name='Plain', features={})))

    def test_any_one_learning_feature_enables(self):
        for key in ('practice', 'ai_grading', 'response_diagnosis'):
            with self.subTest(key=key):
                self.assertTrue(api.intelligence_enabled(Tenant(name=key, features={key: True})))

    def test_a_locked_off_feature_stays_disabled(self):
        tenant = Tenant(name='Locked', features={'practice': True},
                        feature_locks={'practice': False})
        self.assertFalse(api.intelligence_enabled(tenant))

    def test_never_raises(self):
        broken = mock.Mock()
        broken.get_features.side_effect = RuntimeError('boom')
        self.assertFalse(api.intelligence_enabled(broken))


class DisabledTenantSubmitTests(GateFixture):
    features = {}

    def test_quiz_submit_records_nothing_and_enqueues_nothing(self):
        with mock.patch.object(tasks.diagnose_and_update_state, 'apply_async') as delay:
            self.submit_quiz()
        delay.assert_not_called()
        self.assertFalse(LearningEvent.objects.exists())

    def test_quiz_submit_keeps_the_client_time_per_answer(self):
        attempt = self.submit_quiz()
        self.assertEqual(Answer.objects.get(quiz_attempt=attempt).time_taken_seconds, 7)

    def test_rich_submit_records_nothing_and_enqueues_nothing(self):
        with mock.patch.object(tasks.diagnose_and_update_state, 'apply_async') as delay:
            self.submit_rich()
        delay.assert_not_called()
        self.assertFalse(LearningEvent.objects.exists())

    def test_regrade_and_stale_check_are_no_ops(self):
        mock_test, item = self.make_rich_mock()
        attempt = MockTestAttempt.objects.create(
            tenant=self.tenant, student=self.student, mock_test=mock_test,
            status='completed', completed_at=timezone.now(),
        )
        answer = MockTestAnswer.objects.create(
            tenant=self.tenant, attempt=attempt, item=item, selected_options=[0],
            is_correct=True, marks_obtained=4, max_marks=4,
        )
        with mock.patch.object(tasks.diagnose_and_update_state, 'apply_async') as delay:
            api.record_regrade_event(answer)
        delay.assert_not_called()
        self.assertFalse(LearningEvent.objects.exists())

        MockTestItem.objects.filter(id=item.id).update(content_hash='old', tagging_status='tagged')
        item.refresh_from_db()
        self.assertFalse(api.mark_item_stale_if_changed(item))
        item.refresh_from_db()
        self.assertEqual(item.tagging_status, 'tagged')

    def test_timeline_sync_returns_204_and_writes_nothing(self):
        attempt = MockTestAttempt.objects.create(
            tenant=self.tenant, student=self.student,
            mock_test=self.make_rich_mock()[0], status='in_progress',
        )
        response = self.api_client().post(
            '/api/v1/intelligence/timeline/',
            {'attempt_kind': 'mock', 'attempt_id': str(attempt.id), 'session_id': 's1',
             'elapsed_ms': 1000, 'truncated': False,
             'events': [[0, 'e', 'item:a'], [900, 'l', 'item:a']]},
            format='json',
        )
        self.assertEqual(response.status_code, 204, response.content)
        self.assertEqual(response.content, b'')
        self.assertFalse(AttemptTimeline.objects.exists())


class EnabledTenantSubmitTests(GateFixture):
    features = {'response_diagnosis': True}

    def test_quiz_submit_records_events_and_enqueues(self):
        with mock.patch.object(tasks.diagnose_and_update_state, 'apply_async') as delay:
            attempt = self.submit_quiz()
        delay.assert_called_once_with(args=['quiz', str(attempt.id)], retry=True, retry_policy=POLICY)
        self.assertTrue(LearningEvent.objects.filter(attempt_id=attempt.id).exists())

    def test_rich_submit_records_events_and_enqueues(self):
        with mock.patch.object(tasks.diagnose_and_update_state, 'apply_async') as delay:
            attempt = self.submit_rich()
        delay.assert_called_once_with(args=['mock', str(attempt.id)], retry=True, retry_policy=POLICY)
        self.assertTrue(LearningEvent.objects.filter(attempt_id=attempt.id).exists())

    def test_timeline_sync_is_accepted(self):
        attempt = MockTestAttempt.objects.create(
            tenant=self.tenant, student=self.student,
            mock_test=self.make_rich_mock()[0], status='in_progress',
        )
        response = self.api_client().post(
            '/api/v1/intelligence/timeline/',
            {'attempt_kind': 'mock', 'attempt_id': str(attempt.id), 'session_id': 's1',
             'elapsed_ms': 1000, 'truncated': False,
             'events': [[0, 'e', 'item:a'], [900, 'l', 'item:a']]},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(AttemptTimeline.objects.filter(attempt_id=attempt.id).exists())


class TaggingGateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.plain = Tenant.objects.create(name='Plain Academy', is_active=True)
        cls.opted = Tenant.objects.create(
            name='Opted Academy', is_active=True, features={'practice': True},
        )
        for tenant in (cls.plain, cls.opted):
            course = Course.objects.create(
                tenant=tenant, name='C', code=f'c-{tenant.name[:5].lower()}',
                course_type='competitive',
            )
            subject = Subject.objects.create(tenant=tenant, course=course, name='S', code='s')
            topic = Topic.objects.create(tenant=tenant, subject=subject, name='T', code='t')
            Question.objects.create(
                tenant=tenant, topic=topic, subject=subject, question_text='Untagged?',
                question_type='mcq', correct_answer='0', status='published',
            )

    def test_sweep_skips_tenants_without_a_learning_feature(self):
        with mock.patch.object(tasks.tag_items_for_tenant, 'delay') as delay:
            tasks.tagging_sweep()
        queued = {call.args[0] for call in delay.call_args_list}
        self.assertEqual(queued, {str(self.opted.id)})

    def test_tag_task_is_a_no_op_for_a_disabled_tenant(self):
        with mock.patch('intelligence.services.tagging_sweep.run_sweep') as run:
            self.assertEqual(tasks.tag_items_for_tenant.run(str(self.plain.id)), 0)
        run.assert_not_called()

    def test_tag_task_runs_for_an_enabled_tenant(self):
        with mock.patch('intelligence.services.tagging_sweep.run_sweep',
                        return_value={'v2': 1, 'v1': 2}) as run:
            self.assertEqual(tasks.tag_items_for_tenant.run(str(self.opted.id)), 3)
        run.assert_called_once()

    def test_cli_still_runs_for_an_explicit_disabled_tenant_with_a_note(self):
        out = StringIO()
        with mock.patch('intelligence.services.tagging_sweep.run_sweep',
                        return_value={'v2': 0, 'v1': 1}) as run:
            call_command('tag_items', tenant=str(self.plain.id), stdout=out, stderr=StringIO())
        run.assert_called_once()
        self.assertIn('no learning-layer feature enabled', out.getvalue())


class NightlyGateTests(GateFixture):
    """Backfilled events of a tenant that has not opted in stay inert."""

    features = {}

    def _backfilled_attempt(self):
        quiz, question = self.make_quiz()
        attempt = QuizAttempt.objects.create(
            tenant=self.tenant, student=self.student, quiz=quiz, status='completed',
            completed_at=timezone.now(),
        )
        Answer.objects.create(
            tenant=self.tenant, quiz_attempt=attempt, question=question,
            selected_option='1', is_correct=False, marks_obtained=0, time_taken_seconds=20,
        )
        # Operator backfill writes events directly, bypassing the api gate.
        event_service.record_attempt_events(attempt)
        self.assertTrue(LearningEvent.objects.exists())
        return attempt

    def test_refresh_learner_state_ignores_disabled_tenants(self):
        self._backfilled_attempt()
        tasks.refresh_learner_state()
        self.assertFalse(ResponseDiagnosis.objects.exists())
        self.assertFalse(LearnerConceptState.objects.exists())

    def test_recompute_item_stats_ignores_disabled_tenants(self):
        self._backfilled_attempt()
        self.assertEqual(tasks.recompute_item_stats(), 0)
        self.assertFalse(ItemStats.objects.exists())

    def test_recompute_item_stats_covers_enabled_tenants(self):
        self._backfilled_attempt()
        Tenant.objects.filter(id=self.tenant.id).update(features={'response_diagnosis': True})
        self.assertGreaterEqual(tasks.recompute_item_stats(), 1)
        self.assertTrue(ItemStats.objects.exists())


POLICY = {'max_retries': 1, 'interval_start': 0, 'interval_step': 0.2, 'interval_max': 0.5}


class EnqueueRetryPolicyTests(GateFixture):
    """Request-path enqueues cap their own publish retries, so a dead broker
    costs an opted-in tenant well under a second (the global setting is
    main's)."""

    features = {'response_diagnosis': True, 'practice': True, 'ai_grading': True}

    def assert_capped(self, apply_async, args):
        apply_async.assert_called_once_with(args=args, retry=True, retry_policy=POLICY)

    def test_policy_constant(self):
        self.assertEqual(api.ENQUEUE_RETRY_POLICY, POLICY)

    def test_state_update_enqueue_is_capped(self):
        quiz, _question = self.make_quiz()
        attempt = QuizAttempt.objects.create(
            tenant=self.tenant, student=self.student, quiz=quiz, status='completed',
            completed_at=timezone.now(),
        )
        with mock.patch.object(tasks.diagnose_and_update_state, 'apply_async') as apply_async:
            api.record_attempt_events(attempt)
        self.assert_capped(apply_async, ['quiz', str(attempt.id)])

    def test_recommendation_enqueue_is_capped(self):
        from intelligence import hooks

        quiz, _question = self.make_quiz()
        attempt = QuizAttempt.objects.create(
            tenant=self.tenant, student=self.student, quiz=quiz, status='completed',
        )
        with mock.patch.object(tasks.recompute_recommendations, 'apply_async') as apply_async:
            hooks.on_attempt_graded(attempt, course=self.course)
        self.assert_capped(apply_async, [str(self.student.id), str(self.course.id)])

    def test_ai_grading_enqueue_is_capped(self):
        from intelligence import hooks

        mock_test, item = self.make_rich_mock()
        item.item_type = 'subjective'
        item.save(update_fields=['item_type'])
        attempt = MockTestAttempt.objects.create(
            tenant=self.tenant, student=self.student, mock_test=mock_test,
            status='completed', completed_at=timezone.now(), grading_status='pending_manual',
        )
        MockTestAnswer.objects.create(
            tenant=self.tenant, attempt=attempt, item=item, answer_text='because',
            needs_manual_grading=True, max_marks=4,
        )
        with mock.patch.object(tasks.grade_subjective_answers, 'apply_async') as apply_async:
            hooks.maybe_enqueue_ai_grading(attempt)
        self.assert_capped(apply_async, [str(attempt.id)])


class AdminTaggingRunTests(TestCase):
    URL = '/api/v1/tenant-admin/intelligence/tagging/run/'

    def post_as_admin(self, features):
        tenant = Tenant.objects.create(name='Run Academy', is_active=True, features=features)
        admin = User.objects.create_user(
            email='run-admin@example.com', password='pw-run-1', tenant=tenant, role='admin',
        )
        client = APIClient()
        client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(admin).access_token}',
            HTTP_X_TENANT_ID=str(tenant.id),
        )
        with mock.patch.object(tasks.tag_items_for_tenant, 'delay') as delay:
            response = client.post(self.URL, format='json')
        return tenant, response, delay

    def test_disabled_tenant_is_refused_without_an_enqueue(self):
        _tenant, response, delay = self.post_as_admin({})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json(), {'queued': False, 'reason': 'learning_layer_disabled'})
        delay.assert_not_called()

    def test_enabled_tenant_is_queued(self):
        tenant, response, delay = self.post_as_admin({'practice': True})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json(), {'queued': True})
        delay.assert_called_once_with(str(tenant.id))
