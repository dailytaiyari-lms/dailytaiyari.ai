"""Shared fixtures for the syllabus-tools tests: an exam-mapped course on the
mini tree and a custom course, with an admin and two faculty."""
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.models import Tenant
from exams.models import Course, Subject, Topic
from intelligence.models import SyllabusNode
from intelligence.services import syllabus
from intelligence.tests.taxonomy_fixtures import sync_mini_vocabulary
from intelligence.tests.test_tagging_sweep import FRICTION, LAWS, NEWTON, patched_tree
from quiz.models import Question
from users.models import User


class SyllabusTestCase(TestCase):
    features = {'syllabus_tools': True}

    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create(
            name='Syllabus Academy', is_active=True, features=dict(cls.features))

        def user(email, role):
            return User.objects.create_user(
                email=email, password='pw-syl-1', tenant=cls.tenant, role=role)

        cls.admin = user('syl-admin@example.com', 'admin')
        cls.faculty = user('syl-faculty@example.com', 'instructor')
        cls.other_faculty = user('syl-faculty-2@example.com', 'instructor')

        cls.course = Course.objects.create(
            tenant=cls.tenant, name='Mini Prep', code='syl-mini', course_type='competitive')
        cls.physics = Subject.objects.create(
            tenant=cls.tenant, course=cls.course, name='Physics', code='physics')
        cls.laws = Topic.objects.create(
            tenant=cls.tenant, subject=cls.physics, name='Laws of Motion', code='laws-of-motion')
        cls.custom = Course.objects.create(
            tenant=cls.tenant, name='DSA Sheet', code='syl-dsa', course_type='skill')
        cls.arrays = Subject.objects.create(
            tenant=cls.tenant, course=cls.custom, name='Arrays', code='arrays')
        cls.two_sum = Topic.objects.create(
            tenant=cls.tenant, subject=cls.arrays, name='Two Sum', code='two-sum')
        cls.course.instructors.add(cls.faculty)
        cls.custom.instructors.add(cls.other_faculty)

        sync_mini_vocabulary()
        with patched_tree():
            syllabus.instantiate_exam_tree(cls.course, 'mini', {'physics': cls.physics})

    def setUp(self):
        self.friction = SyllabusNode.objects.get(key=FRICTION)
        self.newton = SyllabusNode.objects.get(key=NEWTON)
        self.laws_node = SyllabusNode.objects.get(key=LAWS)
        self.mechanics = self.laws_node.parent

    def client_for(self, user):
        client = APIClient()
        client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(user).access_token}',
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )
        return client

    def question(self, text, *, subject=None, topic=None):
        return Question.objects.create(
            tenant=self.tenant, subject=subject or self.physics, topic=topic or self.laws,
            question_type='numerical', question_text=text, numerical_answer=1)
