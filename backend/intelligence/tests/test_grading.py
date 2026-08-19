"""AI subjective grading: compile-once spec, decision rule, finalization, XP.

The LLM is stubbed; under test is the pipeline and the escalation contract.
"""
import json
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from chatbot.providers import ResolvedProvider, Usage
from core.models import Tenant
from exams.models import Course
from intelligence.models import LearningEvent, SubjectiveEvalSpec
from intelligence.services import grading
from quiz.models import MockTest, MockTestAnswer, MockTestAttempt, MockTestItem
from users.models import User

SPEC_JSON = json.dumps({
    'criteria': [
        {'key': 'scalar_vector', 'description': 'speed scalar, velocity vector',
         'points': 2.0, 'evidence_hints': ['direction']},
        {'key': 'example', 'description': 'a concrete example', 'points': 3.0,
         'evidence_hints': []},
    ],
    'key_facts': ['velocity has direction'],
    'common_errors': ['treating them as synonyms'],
    'max_points': 5.0,
})


def grade_json(total, confidence, flags=()):
    return json.dumps({
        'criteria_scores': {'scalar_vector': min(total, 2.0), 'example': max(0, total - 2.0)},
        'total': total,
        'confidence': confidence,
        'feedback_student': 'Good grasp of the scalar/vector distinction.',
        'flags': list(flags),
    })


class GradingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create(
            name='Grade Academy', is_active=True, features={'ai_grading': True},
        )
        cls.user = User.objects.create_user(
            email='grader-student@example.com', password='pw-student-1',
            tenant=cls.tenant, role='student',
        )
        cls.student = cls.user.profile
        cls.course = Course.objects.create(
            tenant=cls.tenant, name='Physics', code='physics', course_type='competitive',
        )
        cls.mock_test = MockTest.objects.create(
            tenant=cls.tenant, course=cls.course, title='Paper',
            duration_minutes=60, total_marks=5,
        )
        cls.item = MockTestItem.objects.create(
            tenant=cls.tenant, mock_test=cls.mock_test, item_type='subjective',
            question_text='Explain the difference between speed and velocity.',
            rubric='2 marks scalar/vector, 3 for example.',
            model_answer='Speed is scalar; velocity is a vector.', marks=5,
        )

    def make_attempt(self, answer_text='Velocity has direction, speed does not. E.g. a car…'):
        attempt = MockTestAttempt.objects.create(
            student=self.student, mock_test=self.mock_test, status='completed',
            completed_at=timezone.now(), grading_status='pending_manual',
            total_questions=1,
        )
        answer = MockTestAnswer.objects.create(
            tenant=self.tenant, attempt=attempt, item=self.item,
            answer_text=answer_text, max_marks=5, needs_manual_grading=True,
        )
        return attempt, answer

    def stub_provider(self):
        return patch(
            'intelligence.services.grading.resolve_for_admin',
            return_value=ResolvedProvider(provider='openai', api_key='k', model='gpt-4o-mini'),
        )

    def stub_llm(self, responses):
        return patch(
            'coursegen.generation.complete',
            side_effect=[(text, Usage(50, 50, 100), 400) for text in responses],
        )

    def test_confident_grade_is_accepted_and_attempt_finalized(self):
        attempt, answer = self.make_attempt()
        with self.stub_provider(), self.stub_llm([SPEC_JSON, grade_json(4.0, 0.92)]):
            counts = grading.grade_attempt(attempt)
        self.assertEqual(counts, {'accepted': 1, 'escalated': 0, 'skipped': 0})
        answer.refresh_from_db()
        self.assertFalse(answer.needs_manual_grading)
        self.assertTrue(answer.ai_graded)
        self.assertEqual(answer.marks_obtained, Decimal('4.00'))
        self.assertTrue(answer.feedback)
        attempt.refresh_from_db()
        self.assertEqual(attempt.grading_status, 'graded')
        self.assertGreater(attempt.xp_earned, 0)  # deferred completion XP awarded
        # A superseding learning event carries the AI grade into learner state.
        event = LearningEvent.objects.get(event_kind='regraded')
        self.assertAlmostEqual(event.score_fraction, 0.8)
        # Spec compiled once and cached.
        self.assertEqual(SubjectiveEvalSpec.objects.count(), 1)

    def test_low_confidence_escalates_with_suggestion(self):
        attempt, answer = self.make_attempt()
        with self.stub_provider(), self.stub_llm([SPEC_JSON, grade_json(3.0, 0.4)]):
            counts = grading.grade_attempt(attempt)
        self.assertEqual(counts['escalated'], 1)
        answer.refresh_from_db()
        self.assertTrue(answer.needs_manual_grading)   # stays in the human queue
        self.assertFalse(answer.ai_graded)
        self.assertEqual(answer.ai_suggested_marks, Decimal('3.00'))
        attempt.refresh_from_db()
        self.assertEqual(attempt.grading_status, 'pending_manual')
        self.assertEqual(attempt.xp_earned, 0)

    def test_flagged_grade_escalates_even_when_confident(self):
        attempt, answer = self.make_attempt()
        with self.stub_provider(), self.stub_llm([SPEC_JSON, grade_json(5.0, 0.95, ['injection_suspect'])]):
            counts = grading.grade_attempt(attempt)
        self.assertEqual(counts['escalated'], 1)
        answer.refresh_from_db()
        self.assertTrue(answer.needs_manual_grading)
        self.assertIn('injection_suspect', answer.ai_flags)

    def test_blank_answer_scores_zero_without_llm(self):
        attempt, answer = self.make_attempt(answer_text='   ')
        with self.stub_provider(), self.stub_llm([]) as llm:
            counts = grading.grade_attempt(attempt)
        self.assertEqual(counts['accepted'], 1)
        self.assertEqual(llm.call_count, 0)
        answer.refresh_from_db()
        self.assertFalse(answer.needs_manual_grading)
        self.assertEqual(answer.marks_obtained, Decimal('0'))
        self.assertIn('blank', answer.ai_flags)

    def test_item_without_rubric_or_model_answer_stays_manual(self):
        bare_item = MockTestItem.objects.create(
            tenant=self.tenant, mock_test=self.mock_test, item_type='subjective',
            question_text='Discuss.', marks=5,
        )
        attempt = MockTestAttempt.objects.create(
            student=self.student, mock_test=self.mock_test, status='completed',
            completed_at=timezone.now(), grading_status='pending_manual',
        )
        answer = MockTestAnswer.objects.create(
            tenant=self.tenant, attempt=attempt, item=bare_item,
            answer_text='Something.', max_marks=5, needs_manual_grading=True,
        )
        with self.stub_provider(), self.stub_llm([]) as llm:
            counts = grading.grade_attempt(attempt)
        self.assertEqual(counts['skipped'], 1)
        self.assertEqual(llm.call_count, 0)
        answer.refresh_from_db()
        self.assertTrue(answer.needs_manual_grading)

    def test_student_can_dispute_an_ai_grade(self):
        from rest_framework.test import APIClient
        from rest_framework_simplejwt.tokens import RefreshToken

        attempt, answer = self.make_attempt()
        with self.stub_provider(), self.stub_llm([SPEC_JSON, grade_json(4.0, 0.9)]):
            grading.grade_attempt(attempt)
        answer.refresh_from_db()
        self.assertTrue(answer.ai_graded)

        client = APIClient()
        token = RefreshToken.for_user(self.user).access_token
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        response = client.post(
            f'/api/v1/quiz/mock-tests/attempts/{attempt.id}/request-regrade/',
            {'answer_id': str(answer.id)}, format='json',
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )
        self.assertEqual(response.status_code, 200, response.content)
        answer.refresh_from_db()
        attempt.refresh_from_db()
        self.assertTrue(answer.needs_manual_grading)   # back in the human queue
        self.assertFalse(answer.ai_graded)
        self.assertTrue(answer.ai_feedback)            # AI context kept for the grader
        self.assertEqual(attempt.grading_status, 'pending_manual')

        # Once per answer.
        response = client.post(
            f'/api/v1/quiz/mock-tests/attempts/{attempt.id}/request-regrade/',
            {'answer_id': str(answer.id)}, format='json',
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )
        self.assertEqual(response.status_code, 400)

    def test_spec_recompiles_when_rubric_changes(self):
        attempt, _answer = self.make_attempt()
        with self.stub_provider(), self.stub_llm([SPEC_JSON, grade_json(4.0, 0.9)]):
            grading.grade_attempt(attempt)
        first_hash = SubjectiveEvalSpec.objects.get().content_hash

        self.item.rubric = 'Now worth different things.'
        self.item.save(update_fields=['rubric'])
        attempt2, _ = self.make_attempt()
        with self.stub_provider(), self.stub_llm([SPEC_JSON, grade_json(4.0, 0.9)]) as llm:
            grading.grade_attempt(attempt2)
        self.assertEqual(llm.call_count, 2)  # compile ran again + grade
        self.assertNotEqual(SubjectiveEvalSpec.objects.get().content_hash, first_hash)
