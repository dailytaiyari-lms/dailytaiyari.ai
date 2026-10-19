"""Shared fixtures for the response-diagnosis tests: one tenant with the
feature on, a student, a 60-minute rich mock test and helpers to build
items, attempts, answers and timelines."""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from core.models import Tenant
from exams.models import Course, Subject, Topic
from intelligence.models import AttemptTimeline, Concept, ConceptLink
from quiz.models import MockTest, MockTestAnswer, MockTestAttempt, MockTestItem
from users.models import User


class DiagnosisTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create(
            name='Diagnosis Academy', is_active=True,
            features={'response_diagnosis': True},
        )
        cls.user = User.objects.create_user(
            email='diag-student@example.com', password='pw-diag-1',
            tenant=cls.tenant, role='student',
        )
        cls.student = cls.user.profile
        cls.other_user = User.objects.create_user(
            email='diag-other@example.com', password='pw-diag-2',
            tenant=cls.tenant, role='student',
        )
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
            tenant=cls.tenant, subject=cls.subject, name='Velocity', slug='velocity',
        )
        cls.mock_test = MockTest.objects.create(
            tenant=cls.tenant, course=cls.course, title='Paper',
            duration_minutes=60, total_marks=16,
        )

    def make_item(self, *, item_type='mcq', difficulty='medium', numerical=None):
        options = [] if item_type in ('numerical', 'subjective') else [
            {'text': 'A', 'is_correct': True},
            {'text': 'B', 'is_correct': False},
            {'text': 'C', 'is_correct': False},
        ]
        item = MockTestItem.objects.create(
            tenant=self.tenant, mock_test=self.mock_test, item_type=item_type,
            question_text=f'Question {MockTestItem.objects.count() + 1}?', marks=4,
            topic=self.topic, subject=self.subject, difficulty=difficulty,
            options=options, numerical_answer=numerical,
        )
        ConceptLink.objects.create(
            tenant=self.tenant, concept=self.concept, mock_item=item,
            is_primary=True, weight=1.0, source='generator',
        )
        return item

    def make_attempt(self, *, minutes_ago=30, student=None):
        attempt = MockTestAttempt.objects.create(
            tenant=self.tenant, student=student or self.student,
            mock_test=self.mock_test, status='in_progress',
        )
        # started_at is auto_now_add — move it back with a plain update.
        MockTestAttempt.objects.filter(id=attempt.id).update(
            started_at=timezone.now() - timedelta(minutes=minutes_ago),
        )
        attempt.refresh_from_db()
        return attempt

    def answer(self, attempt, item, *, selected=None, numerical=None, correct=False,
               text='', needs_manual=False):
        return MockTestAnswer.objects.create(
            tenant=self.tenant, attempt=attempt, item=item,
            selected_options=selected or [], numerical_answer=numerical,
            answer_text=text, needs_manual_grading=needs_manual,
            is_correct=correct, marks_obtained=4 if correct else 0, max_marks=4,
        )

    def finish(self, attempt, *, after_minutes=20, status='completed'):
        attempt.status = status
        attempt.completed_at = attempt.started_at + timedelta(minutes=after_minutes)
        attempt.save()
        return attempt

    def make_timeline(self, attempt, events, *, clock='server', offset_ms=0, kind='mock'):
        return AttemptTimeline.objects.create(
            tenant=self.tenant, student=attempt.student, attempt_kind=kind,
            attempt_id=attempt.id, clock=clock,
            sessions={'s1': {'offset_ms': offset_ms, 'events': events,
                             'received_at': '', 'truncated': False}},
        )
