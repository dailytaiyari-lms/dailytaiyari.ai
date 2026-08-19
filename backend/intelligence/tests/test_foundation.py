"""Foundation tests: concept resolution, event emission, analytics single-fire.

These pin the layer's two core guarantees:
- everything is idempotent (double calls change nothing), and
- the old signal-driven analytics double-count stays dead.
"""
from django.test import TestCase
from django.utils import timezone

from analytics.models import TopicMastery
from analytics.services import AnalyticsService
from core.models import Tenant
from exams.models import Course, Subject, Topic
from intelligence.models import Concept, ConceptAlias, LearningEvent
from intelligence.services import events as event_service
from intelligence.services.normalize import merge_concept, resolve_concept
from quiz.models import (
    Answer, MockTest, MockTestAnswer, MockTestAttempt, MockTestItem,
    Question, Quiz, QuizAttempt, QuizQuestion,
)
from users.models import User


class IntelligenceTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create(name='Test Academy', is_active=True)
        cls.student_user = User.objects.create_user(
            email='student@example.com', password='pw-student-1',
            tenant=cls.tenant, role='student',
        )
        cls.student = cls.student_user.profile
        cls.course = Course.objects.create(
            tenant=cls.tenant, name='Physics', code='physics', course_type='competitive',
        )
        cls.subject = Subject.objects.create(
            tenant=cls.tenant, course=cls.course, name='Mechanics', code='mechanics',
        )
        cls.topic = Topic.objects.create(
            tenant=cls.tenant, subject=cls.subject, name='Motion', code='motion',
        )

    def make_question(self, **overrides):
        defaults = dict(
            tenant=self.tenant, topic=self.topic, subject=self.subject,
            question_text='What is v for a body at rest?', question_type='mcq',
            correct_answer='0', status='published',
        )
        defaults.update(overrides)
        return Question.objects.create(**defaults)

    def make_completed_quiz_attempt(self, n_correct=2, n_wrong=1):
        quiz = Quiz.objects.create(
            tenant=self.tenant, course=self.course, title='Kinematics quiz',
        )
        attempt = QuizAttempt.objects.create(
            student=self.student, quiz=quiz, status='completed',
            completed_at=timezone.now(),
        )
        for i in range(n_correct + n_wrong):
            question = self.make_question()
            QuizQuestion.objects.create(tenant=self.tenant, quiz=quiz, question=question, order=i)
            Answer.objects.create(
                tenant=self.tenant, quiz_attempt=attempt, question=question,
                selected_option='0' if i < n_correct else '1',
                is_correct=i < n_correct,
                marks_obtained=1 if i < n_correct else 0,
                time_taken_seconds=30,
            )
        return attempt


class ConceptResolutionTests(IntelligenceTestCase):
    def test_variant_spellings_resolve_to_one_concept(self):
        c1 = resolve_concept(self.tenant, self.subject, "Newton's Laws", source='mockgen')
        c2 = resolve_concept(self.tenant, self.subject, "  newton's laws ", source='llm_tagger')
        c3 = resolve_concept(self.tenant, self.subject, "The Newton's Law", source='manual')
        self.assertEqual(c1.id, c2.id)
        self.assertEqual(c1.id, c3.id)
        self.assertEqual(Concept.objects.count(), 1)
        # Both raw spellings left aliases behind.
        self.assertGreaterEqual(ConceptAlias.objects.count(), 1)

    def test_generic_labels_are_refused(self):
        self.assertIsNone(resolve_concept(self.tenant, self.subject, 'Practice Quiz'))
        self.assertIsNone(resolve_concept(self.tenant, self.subject, 'general'))
        self.assertIsNone(resolve_concept(self.tenant, self.subject, ''))
        self.assertEqual(Concept.objects.count(), 0)

    def test_merge_repoints_aliases_and_resolution(self):
        loser = resolve_concept(self.tenant, self.subject, 'Velocity Concepts', source='manual')
        winner = resolve_concept(self.tenant, self.subject, 'Velocity', source='manual')
        merge_concept(loser, winner)
        again = resolve_concept(self.tenant, self.subject, 'Velocity Concepts')
        self.assertEqual(again.id, winner.id)
        loser.refresh_from_db()
        self.assertEqual(loser.status, 'merged')

    def test_topic_anchoring(self):
        concept = resolve_concept(
            self.tenant, self.subject, 'Relative Motion', source='mockgen', topic=self.topic,
        )
        self.assertIn(self.topic, concept.topics.all())


class LearningEventTests(IntelligenceTestCase):
    def test_quiz_events_recorded_once_even_if_called_twice(self):
        attempt = self.make_completed_quiz_attempt(n_correct=2, n_wrong=1)
        first = event_service.record_attempt_events(attempt)
        event_service.record_attempt_events(attempt)
        self.assertEqual(first, 3)
        self.assertEqual(LearningEvent.objects.count(), 3)
        event = LearningEvent.objects.filter(is_correct=True).first()
        self.assertEqual(event.score_fraction, 1.0)
        self.assertEqual(event.tenant, self.tenant)
        self.assertEqual(event.topic, self.topic)
        self.assertEqual(event.attempt_kind, 'quiz')

    def test_negative_marking_never_produces_negative_score_fraction(self):
        attempt = self.make_completed_quiz_attempt(n_correct=0, n_wrong=1)
        answer = attempt.answers.first()
        answer.marks_obtained = -1
        answer.save(update_fields=['marks_obtained'])
        event_service.record_attempt_events(attempt)
        event = LearningEvent.objects.get()
        self.assertEqual(event.score_fraction, 0.0)

    def _make_mock_attempt_with_item(self, needs_manual=False):
        mock_test = MockTest.objects.create(
            tenant=self.tenant, course=self.course, title='Unit test',
            duration_minutes=45, total_marks=5,
        )
        item = MockTestItem.objects.create(
            tenant=self.tenant, mock_test=mock_test, item_type='subjective',
            question_text='Explain velocity.', marks=5,
            topic=self.topic, subject=self.subject,
        )
        attempt = MockTestAttempt.objects.create(
            student=self.student, mock_test=mock_test, status='completed',
            completed_at=timezone.now(),
        )
        item_answer = MockTestAnswer.objects.create(
            tenant=self.tenant, attempt=attempt, item=item,
            answer_text='It has direction.', max_marks=5,
            needs_manual_grading=needs_manual,
            marks_obtained=0 if needs_manual else 3,
            is_correct=False,
        )
        return attempt, item_answer

    def test_pending_manual_item_scores_zero_until_regraded(self):
        attempt, item_answer = self._make_mock_attempt_with_item(needs_manual=True)
        event_service.record_attempt_events(attempt)
        event = LearningEvent.objects.get()
        self.assertEqual(event.score_fraction, 0.0)
        self.assertTrue(event.response_digest.get('needs_manual'))

        # Manual grade appends a superseding event with partial credit.
        item_answer.marks_obtained = 4
        item_answer.needs_manual_grading = False
        item_answer.graded_at = timezone.now()
        item_answer.save()
        event_service.record_regrade_event(item_answer)
        self.assertEqual(LearningEvent.objects.count(), 2)
        latest = LearningEvent.objects.order_by('-occurred_at', '-created_at').first()
        self.assertEqual(latest.event_kind, 'regraded')
        self.assertAlmostEqual(latest.score_fraction, 0.8)

    def test_partial_credit_score_fraction(self):
        attempt, _ = self._make_mock_attempt_with_item(needs_manual=False)
        event_service.record_attempt_events(attempt)
        event = LearningEvent.objects.get()
        self.assertAlmostEqual(event.score_fraction, 0.6)  # 3 of 5 marks


class BackfillCommandTests(IntelligenceTestCase):
    def test_backfill_is_idempotent_and_scans_both_attempt_kinds(self):
        from django.core.management import call_command

        attempt = self.make_completed_quiz_attempt(n_correct=1, n_wrong=1)
        # Events already recorded live for this attempt — backfill must not duplicate.
        event_service.record_attempt_events(attempt)
        self.assertEqual(LearningEvent.objects.count(), 2)

        call_command('backfill_learning_events', verbosity=0)
        self.assertEqual(LearningEvent.objects.count(), 2)
        call_command('backfill_learning_events', tenant=str(self.tenant.id), verbosity=0)
        self.assertEqual(LearningEvent.objects.count(), 2)


class AnalyticsSingleFireTests(IntelligenceTestCase):
    """Regression tests for the removed post_save analytics signals."""

    def test_resaving_completed_attempt_does_not_double_count(self):
        attempt = self.make_completed_quiz_attempt(n_correct=2, n_wrong=1)
        AnalyticsService.update_topic_mastery_from_attempt(attempt)
        mastery = TopicMastery.objects.get(student=self.student, topic=self.topic)
        attempted_once = mastery.total_questions_attempted
        self.assertEqual(attempted_once, 3)

        # The old signals fired on *every* save of a completed attempt.
        attempt.save()
        attempt.save(update_fields=['xp_earned'])
        mastery.refresh_from_db()
        self.assertEqual(mastery.total_questions_attempted, attempted_once)

    def test_mastery_rows_carry_tenant(self):
        attempt = self.make_completed_quiz_attempt()
        AnalyticsService.update_topic_mastery_from_attempt(attempt)
        mastery = TopicMastery.objects.get(student=self.student, topic=self.topic)
        self.assertEqual(mastery.tenant, self.tenant)
