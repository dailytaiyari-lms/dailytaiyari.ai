"""Tagging v2 schema: uniqueness, XOR item constraint, protection."""
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase

from core.models import Tenant
from exams.models import Course, Subject, Topic
from intelligence.models import (
    Concept, CourseSyllabus, ItemSkillTag, ItemTagging, SyllabusNode, TagDefinition,
    TaxonomyRelease,
)
from quiz.models import Question


class TaggingV2ModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create(name='Model Academy', is_active=True)
        cls.course = Course.objects.create(
            tenant=cls.tenant, name='JEE', code='models-jee', course_type='competitive',
        )
        cls.subject = Subject.objects.create(
            tenant=cls.tenant, course=cls.course, name='Physics', code='physics',
        )
        cls.topic = Topic.objects.create(
            tenant=cls.tenant, subject=cls.subject, name='Laws of Motion', code='laws-of-motion',
        )
        cls.question = Question.objects.create(
            tenant=cls.tenant, subject=cls.subject, topic=cls.topic,
            question_text='A block slides down an incline.', question_type='mcq', correct_answer='0',
        )

    def test_node_key_unique_per_subject(self):
        key = 'jee_main.physics.mechanics.laws_of_motion'
        SyllabusNode.objects.create(
            tenant=self.tenant, subject=self.subject, level='topic', key=key, name='Laws of Motion',
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            SyllabusNode.objects.create(
                tenant=self.tenant, subject=self.subject, level='topic', key=key, name='Duplicate',
            )

    def test_item_tagging_needs_exactly_one_item(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            ItemTagging.objects.create(tenant=self.tenant)
        tagging = ItemTagging.objects.create(
            tenant=self.tenant, question=self.question, thinking_level='recall',
        )
        self.assertEqual(self.question.tagging, tagging)
        self.assertEqual(tagging.review_status, 'auto')

    def test_skill_tag_unique_per_item_and_definition_protected(self):
        skill = TagDefinition.objects.create(
            kind='skill', key='free_body_diagram', label='Free-body diagram', definition='Draw forces.',
        )
        ItemSkillTag.objects.create(tenant=self.tenant, question=self.question, skill=skill, role='core')
        with self.assertRaises(IntegrityError), transaction.atomic():
            ItemSkillTag.objects.create(tenant=self.tenant, question=self.question, skill=skill)
        with self.assertRaises(ProtectedError):
            skill.delete()

    def test_subtopic_node_owns_one_concept(self):
        concept = Concept.objects.create(
            tenant=self.tenant, subject=self.subject, name='Friction', slug='friction', source='syllabus',
        )
        node = SyllabusNode.objects.create(
            tenant=self.tenant, subject=self.subject, level='subtopic', key='k.friction',
            name='Friction', concept=concept,
        )
        self.assertEqual(concept.syllabus_node, node)
        with self.assertRaises(IntegrityError), transaction.atomic():
            SyllabusNode.objects.create(
                tenant=self.tenant, subject=self.subject, level='subtopic', key='k.friction_2',
                name='Friction again', concept=concept,
            )

    def test_tag_definition_unique_per_kind(self):
        TagDefinition.objects.create(kind='thinking_level', key='recall', label='Recall', definition='d')
        TagDefinition.objects.create(kind='skill', key='recall', label='Recall skill', definition='d')
        with self.assertRaises(IntegrityError), transaction.atomic():
            TagDefinition.objects.create(kind='thinking_level', key='recall', label='Again', definition='d')

    def test_release_sequence_unique_and_course_syllabus_one_per_course(self):
        TaxonomyRelease.objects.create(sequence=1, version='1', file_sha256='a' * 64)
        with self.assertRaises(IntegrityError), transaction.atomic():
            TaxonomyRelease.objects.create(sequence=1, version='2', file_sha256='b' * 64)
        CourseSyllabus.objects.create(tenant=self.tenant, course=self.course, exam_tree='jee_main')
        self.assertEqual(self.course.syllabus.exam_tree, 'jee_main')
        with self.assertRaises(IntegrityError), transaction.atomic():
            CourseSyllabus.objects.create(tenant=self.tenant, course=self.course)
