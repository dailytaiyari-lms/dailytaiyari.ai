"""Shared fixtures for the diagnosis-visibility tests: one tenant with
Answer Diagnosis and both view switches on, an admin, two faculty on two
courses, a student in each course, and helpers for attempts and rows."""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.models import Tenant
from exams.models import Course, Subject, Topic
from intelligence.models import ResponseDiagnosis
from quiz.models import Question, QuestionOption, Quiz, QuizAttempt, QuizQuestion
from users.models import CourseEnrollment, User

ALL_ON = {
    'response_diagnosis': True,
    'diagnosis_teacher_view': True,
    'diagnosis_student_view': True,
}


class VisibilityTestCase(TestCase):
    features = ALL_ON

    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create(
            name='Visibility Academy', is_active=True, features=dict(cls.features),
        )

        def user(email, role):
            return User.objects.create_user(
                email=email, password='pw-vis-1', tenant=cls.tenant, role=role,
            )

        cls.admin = user('vis-admin@example.com', 'admin')
        cls.faculty = user('vis-faculty@example.com', 'instructor')
        cls.other_faculty = user('vis-faculty-2@example.com', 'instructor')
        cls.student_user = user('vis-student@example.com', 'student')
        cls.outsider_user = user('vis-outsider@example.com', 'student')
        cls.student = cls.student_user.profile
        cls.outsider = cls.outsider_user.profile

        cls.course = Course.objects.create(
            tenant=cls.tenant, name='Physics', code='vis-physics',
            course_type='competitive', status='active',
        )
        cls.other_course = Course.objects.create(
            tenant=cls.tenant, name='Chemistry', code='vis-chem',
            course_type='competitive', status='active',
        )
        cls.course.instructors.add(cls.faculty)
        cls.other_course.instructors.add(cls.other_faculty)
        CourseEnrollment.objects.create(
            tenant=cls.tenant, student=cls.student, course=cls.course,
            status='approved', is_active=True,
        )
        CourseEnrollment.objects.create(
            tenant=cls.tenant, student=cls.outsider, course=cls.other_course,
            status='approved', is_active=True,
        )
        cls.subject = Subject.objects.create(
            tenant=cls.tenant, course=cls.course, name='Mechanics', code='vis-mech',
        )
        cls.topic = Topic.objects.create(
            tenant=cls.tenant, subject=cls.subject, name='Kinematics', code='vis-kin',
        )
        cls.quiz = Quiz.objects.create(
            tenant=cls.tenant, course=cls.course, title='Kinematics quiz',
            quiz_type='topic', duration_minutes=30,
        )

    def client_for(self, user):
        client = APIClient()
        client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(user).access_token}',
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )
        return client

    def make_question(self, n, *, quiz=None):
        question = Question.objects.create(
            tenant=self.tenant, topic=self.topic, subject=self.subject,
            question_text=f'Question {n}?', question_type='mcq',
            difficulty='medium', status='published', correct_answer='0', marks=1,
        )
        QuestionOption.objects.create(
            tenant=self.tenant, question=question, option_text='A', is_correct=True, order=0,
        )
        # QuizQuestion declares its own Meta, so it has no default ordering:
        # set ``order`` so paper order is deterministic.
        QuizQuestion.objects.create(quiz=quiz or self.quiz, question=question, order=n)
        return question

    def quiz_attempt(self, student, *, quiz=None, minutes_ago=60, status='completed'):
        attempt = QuizAttempt.objects.create(
            student=student, quiz=quiz or self.quiz, status=status,
        )
        done = timezone.now() - timedelta(minutes=minutes_ago)
        QuizAttempt.objects.filter(id=attempt.id).update(
            started_at=done - timedelta(minutes=20), completed_at=done,
        )
        attempt.refresh_from_db()
        return attempt

    def diagnose(self, attempt, question, label, *, confidence='high', metrics=None,
                 evidence=None, self_report='', is_correct=None, answered=True,
                 kind='quiz', student=None):
        if is_correct is None:
            is_correct = label in ('correct', 'correct_lucky', 'correct_slow')
        return ResponseDiagnosis.objects.create(
            tenant=self.tenant, student=student or attempt.student,
            attempt_kind=kind, attempt_id=attempt.id, question=question,
            answered=answered, is_correct=is_correct,
            score_fraction=1.0 if is_correct else 0.0,
            metrics=metrics or {}, flags=[], evidence=evidence or [],
            label=label, final_label=label, confidence=confidence,
            self_report=self_report, computed_at=timezone.now(),
        )
