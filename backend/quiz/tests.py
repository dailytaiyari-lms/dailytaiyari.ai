"""Mock-test completion XP: paid once per student per mock, never lost."""
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.models import Tenant
from gamification.models import XPTransaction
from quiz.mock_grading import award_completion_xp
from quiz.models import MockTest, MockTestAttempt
from users.models import User


class CompletionXPTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create(name='XP Academy', is_active=True)
        cls.user = User.objects.create_user(
            email='xp-student@example.com', password='pw-xp-1',
            tenant=cls.tenant, role='student',
        )
        cls.student = cls.user.profile
        cls.mock_test = MockTest.objects.create(
            tenant=cls.tenant, title='Paper', duration_minutes=60, total_marks=40,
            max_attempts=3,
        )

    def finished(self, *, grading_status='pending_manual', percentage=80):
        return MockTestAttempt.objects.create(
            tenant=self.tenant, student=self.student, mock_test=self.mock_test,
            status='completed', completed_at=timezone.now(),
            grading_status=grading_status, total_questions=10,
            percentage=Decimal(percentage),
        )

    def paid(self):
        return XPTransaction.objects.filter(
            student=self.student, transaction_type='mock_complete',
        ).count()

    def test_two_attempts_finished_before_grading_pay_exactly_once(self):
        first = self.finished()
        second = self.finished()
        self.assertGreater(award_completion_xp(first), 0)
        self.assertEqual(award_completion_xp(second), 0)
        self.assertEqual(self.paid(), 1)

    def test_grading_order_does_not_matter(self):
        first = self.finished()
        second = self.finished()
        self.assertGreater(award_completion_xp(second), 0)
        self.assertEqual(award_completion_xp(first), 0)
        self.assertEqual(self.paid(), 1)

    def test_a_paid_attempt_blocks_a_later_finalize(self):
        """The original double-XP hole: a re-attempt finalized by the admin."""
        first = self.finished(grading_status='auto_graded')
        self.assertGreater(award_completion_xp(first, at_submit=True), 0)
        second = self.finished()
        self.assertEqual(award_completion_xp(second), 0)
        self.assertEqual(award_completion_xp(first), 0)   # finalize twice: still once
        self.assertEqual(self.paid(), 1)

    def test_submit_path_still_refuses_any_re_attempt(self):
        """At submit, any other finished attempt means a re-attempt (as before)."""
        pending = self.finished()
        resubmitted = self.finished(grading_status='auto_graded')
        self.assertEqual(award_completion_xp(resubmitted, at_submit=True), 0)
        # The first attempt is still paid once its grading completes.
        self.assertGreater(award_completion_xp(pending), 0)
        self.assertEqual(self.paid(), 1)
