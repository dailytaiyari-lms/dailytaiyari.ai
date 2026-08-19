"""Recommendation engine + practice session flow, end to end at service level."""
from django.test import TestCase
from django.utils import timezone

from core.models import Tenant
from exams.models import Course, Subject, Topic
from intelligence import recommendation
from intelligence.models import (
    Concept, ConceptLink, LearnerConceptState, LearningEvent, PracticeSet,
)
from intelligence.services import practice as practice_service
from quiz.models import Question, QuestionOption
from users.models import User


class PracticeTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create(
            name='Practice Academy', is_active=True, features={'practice': True},
        )
        cls.user = User.objects.create_user(
            email='practice-student@example.com', password='pw-student-1',
            tenant=cls.tenant, role='student',
        )
        cls.student = cls.user.profile
        cls.course = Course.objects.create(
            tenant=cls.tenant, name='Physics', code='physics', course_type='competitive',
        )
        cls.subject = Subject.objects.create(
            tenant=cls.tenant, course=cls.course, name='Mechanics', code='mech',
        )
        cls.topic = Topic.objects.create(
            tenant=cls.tenant, subject=cls.subject, name='Kinematics', code='kin',
        )
        cls.concept = Concept.objects.create(
            tenant=cls.tenant, subject=cls.subject, name='Projectile Motion',
            slug='projectile-motion',
        )

    @classmethod
    def make_question(cls, n, difficulty='medium', concept=None, correct_index=0):
        question = Question.objects.create(
            tenant=cls.tenant, topic=cls.topic, subject=cls.subject,
            question_text=f'Practice question {n}?', question_type='mcq',
            difficulty=difficulty, status='published',
            correct_answer=str(correct_index), marks=1,
        )
        for i in range(3):
            QuestionOption.objects.create(
                tenant=cls.tenant, question=question,
                option_text=f'Option {i}', is_correct=(i == correct_index), order=i,
            )
        question.courses.set([cls.course])
        ConceptLink.objects.create(
            tenant=cls.tenant, concept=concept or cls.concept, question=question,
            is_primary=True, weight=1.0, source='generator',
        )
        return question

    def make_low_mastery_state(self, mastery=0.3):
        return LearnerConceptState.objects.create(
            tenant=self.tenant, student=self.student, concept=self.concept,
            mastery=mastery, evidence_count=6, effective_evidence=5.0,
            confidence='medium', computed_at=timezone.now(),
        )


class RecommendationTests(PracticeTestCase):
    def test_low_mastery_builds_a_laddered_set(self):
        self.make_low_mastery_state(mastery=0.3)
        for n in range(6):
            self.make_question(n, difficulty='easy')
        for n in range(6, 12):
            self.make_question(n, difficulty='medium')

        built = recommendation.refresh_recommendations(self.student, self.course)
        self.assertEqual(len(built), 1)
        practice_set = built[0]
        self.assertEqual(practice_set.deficit_kind, 'low_mastery')
        self.assertEqual(practice_set.item_count, 8)
        self.assertIn('30%', practice_set.reason['text'])
        self.assertIn(self.concept, practice_set.target_concepts.all())
        roles = set(practice_set.items.values_list('role', flat=True))
        self.assertIn('core', roles)
        # mastery 0.3 → target easy; ladder stretches one band up.
        self.assertIn('ladder_stretch', roles)

        # Re-running doesn't duplicate the suggestion.
        again = recommendation.refresh_recommendations(self.student, self.course)
        self.assertEqual(len(again), 0)

    def test_no_deficit_no_set(self):
        LearnerConceptState.objects.create(
            tenant=self.tenant, student=self.student, concept=self.concept,
            mastery=0.9, evidence_count=10, effective_evidence=8.0,
            confidence='high', computed_at=timezone.now(),
        )
        for n in range(12):
            self.make_question(n)
        built = recommendation.refresh_recommendations(self.student, self.course)
        self.assertEqual(built, [])

    def test_evidence_floor_blocks_thin_diagnoses(self):
        # Two observations must never produce a confident diagnosis — the
        # student gets a neutral starter set instead of a "low mastery" story.
        LearnerConceptState.objects.create(
            tenant=self.tenant, student=self.student, concept=self.concept,
            mastery=0.1, evidence_count=2, effective_evidence=1.5,
            confidence='low', computed_at=timezone.now(),
        )
        for n in range(12):
            self.make_question(n)
        built = recommendation.refresh_recommendations(self.student, self.course)
        self.assertEqual([s.deficit_kind for s in built], ['starter'])

    def test_recently_seen_questions_are_excluded(self):
        self.make_low_mastery_state()
        questions = [self.make_question(n, difficulty='easy') for n in range(12)]
        seen = questions[0]
        LearningEvent.objects.create(
            tenant=self.tenant, student=self.student, question=seen,
            source_type='quiz_answer', occurred_at=timezone.now(),
            dedup_key='quiz_answer:seen:0', attempt_kind='quiz',
        )
        built = recommendation.refresh_recommendations(self.student, self.course)
        served = {item.question_id for item in built[0].items.all()}
        self.assertNotIn(seen.id, served)

    def test_cold_start_builds_a_starter_set(self):
        # No learner state at all — instead of a fake diagnosis, a starter set.
        for n in range(12):
            self.make_question(n, difficulty='easy' if n < 4 else 'medium')
        built = recommendation.refresh_recommendations(self.student, self.course)
        self.assertEqual(len(built), 1)
        self.assertEqual(built[0].deficit_kind, 'starter')
        self.assertIn(self.course.name, built[0].reason['text'])
        # Not duplicated on the next refresh.
        self.assertEqual(recommendation.refresh_recommendations(self.student, self.course), [])

    def test_completed_starter_set_does_not_deal_another_immediately(self):
        for n in range(24):
            self.make_question(n, difficulty='easy' if n < 8 else 'medium')
        starter = recommendation.refresh_recommendations(self.student, self.course)[0]
        item = starter.items.select_related('question').first()
        practice_service.answer_item(starter, str(item.id), selected_options=[0])
        practice_service.submit_set(starter)
        # Completing the starter seeds state from the answered question's
        # concept, and the 14-day starter cooldown blocks a second deal.
        self.assertEqual(
            [s.deficit_kind for s in
             recommendation.refresh_recommendations(self.student, self.course)],
            [],
        )
        state = LearnerConceptState.objects.get(student=self.student, concept=self.concept)
        self.assertEqual(state.evidence_count, 1)

    def test_disabled_course_config_builds_nothing(self):
        self.make_low_mastery_state()
        for n in range(12):
            self.make_question(n)
        config = recommendation.practice_config_for(self.course)
        config.practice_enabled = False
        config.save()
        self.assertEqual(recommendation.refresh_recommendations(self.student, self.course), [])


class PracticeSessionTests(PracticeTestCase):
    def build_set(self):
        self.make_low_mastery_state()
        for n in range(12):
            self.make_question(n, difficulty='easy')
        return recommendation.refresh_recommendations(self.student, self.course)[0]

    def test_answer_and_submit_flow(self):
        practice_set = self.build_set()
        items = list(practice_set.items.select_related('question').order_by('order')[:4])

        for i, item in enumerate(items):
            correct = i < 2  # answer two right, two wrong
            result = practice_service.answer_item(
                practice_set, str(item.id),
                selected_options=[0] if correct else [1],
                time_taken_seconds=20,
            )
            self.assertEqual(result['is_correct'], correct)
            self.assertTrue(result['explanation'] is not None)

        practice_set.refresh_from_db()
        self.assertEqual(practice_set.status, 'in_progress')

        summary = practice_service.submit_set(practice_set)
        practice_set.refresh_from_db()
        self.assertEqual(practice_set.status, 'completed')
        self.assertEqual(summary['score_correct'], 2)
        self.assertEqual(summary['score_total'], 4)
        self.assertEqual(summary['xp_awarded'], practice_service.PRACTICE_SET_XP)

        events = LearningEvent.objects.filter(source_type='practice_answer')
        self.assertEqual(events.count(), 4)
        # The targeted concept's state was recomputed from the new evidence.
        state = LearnerConceptState.objects.get(student=self.student, concept=self.concept)
        self.assertEqual(state.evidence_count, 4)
        self.assertIn(str(self.concept.id), summary['mastery_after'])

    def test_double_answer_and_double_submit_are_rejected(self):
        practice_set = self.build_set()
        item = practice_set.items.first()
        practice_service.answer_item(practice_set, str(item.id), selected_options=[0])
        with self.assertRaises(practice_service.PracticeError):
            practice_service.answer_item(practice_set, str(item.id), selected_options=[0])
        practice_service.submit_set(practice_set)
        with self.assertRaises(practice_service.PracticeError):
            practice_service.submit_set(practice_set)

    def test_practice_evidence_weighs_less_than_exam_evidence(self):
        practice_set = self.build_set()
        item = practice_set.items.first()
        practice_service.answer_item(practice_set, str(item.id), selected_options=[0])
        practice_service.submit_set(practice_set)
        state = LearnerConceptState.objects.get(student=self.student, concept=self.concept)
        # One correct practice answer: weight 0.6 → (0.6 + 1.5) / (0.6 + 3).
        self.assertAlmostEqual(state.mastery, 0.5833, places=3)
