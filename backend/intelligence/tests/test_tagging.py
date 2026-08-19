"""LLM tagging pipeline: batching, cache hits, subject inference, guards.

The LLM is stubbed; under test is the pipeline around it.
"""
import json
from unittest.mock import patch

from django.test import TestCase

from chatbot.providers import ResolvedProvider, Usage
from core.models import Tenant
from exams.models import Course, Subject, Topic
from intelligence.models import AITaggingResult
from intelligence.services import tagging
from quiz.models import MockTest, MockTestItem, Question


def _llm_response(entries):
    return json.dumps({'items': entries})


class TaggingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create(name='Tag Academy', is_active=True)
        cls.course = Course.objects.create(
            tenant=cls.tenant, name='Physics', code='physics', course_type='competitive',
        )
        cls.subject = Subject.objects.create(
            tenant=cls.tenant, course=cls.course, name='Mechanics', code='mechanics',
        )
        cls.topic = Topic.objects.create(
            tenant=cls.tenant, subject=cls.subject, name='Kinematics', code='kinematics',
        )
        cls.mock_test = MockTest.objects.create(
            tenant=cls.tenant, title='Paper', duration_minutes=60, total_marks=10,
        )
        cls.mock_test.courses.set([cls.course])

    def stub_provider(self):
        return patch(
            'intelligence.services.tagging.resolve_for_admin',
            return_value=ResolvedProvider(provider='openai', api_key='k', model='gpt-4o-mini'),
        )

    def stub_llm(self, response_text):
        return patch(
            'coursegen.generation.complete',
            return_value=(response_text, Usage(50, 50, 100), 500),
        )

    def make_item(self, text):
        return MockTestItem.objects.create(
            tenant=self.tenant, mock_test=self.mock_test, item_type='mcq',
            question_text=text,
            options=[{'text': 'A', 'is_correct': True}, {'text': 'B', 'is_correct': False}],
            marks=4,
        )

    def test_mock_items_tagged_with_inferred_topic_and_subject(self):
        item = self.make_item('A train accelerates uniformly from rest…')
        response = _llm_response([{
            'id': str(item.id), 'concepts': ['Uniform Acceleration'],
            'topic': 'Kinematics', 'difficulty': 'easy', 'cognitive_type': 'application',
        }])
        with self.stub_provider(), self.stub_llm(response):
            tagged = tagging.tag_mock_items(self.tenant, [item])
        self.assertEqual(tagged, 1)
        item.refresh_from_db()
        self.assertEqual(item.tagging_status, 'tagged')
        self.assertEqual(item.subject, self.subject)
        self.assertEqual(item.topic, self.topic)
        self.assertEqual(item.difficulty, 'easy')
        link = item.concept_links.get()
        self.assertEqual(link.concept.name, 'Uniform Acceleration')
        self.assertEqual(link.source, 'llm_tagger')
        self.assertEqual(AITaggingResult.objects.count(), 1)

    def test_duplicate_content_hits_cache_without_llm_call(self):
        first = self.make_item('What is escape velocity of Earth?')
        response = _llm_response([{
            'id': str(first.id), 'concepts': ['Escape Velocity'],
            'topic': 'Kinematics', 'difficulty': 'medium', 'cognitive_type': 'recall',
        }])
        with self.stub_provider(), self.stub_llm(response) as llm:
            tagging.tag_mock_items(self.tenant, [first])
            self.assertEqual(llm.call_count, 1)

        duplicate = self.make_item('What is escape velocity of Earth?')
        with self.stub_provider(), self.stub_llm(response) as llm:
            tagged = tagging.tag_mock_items(self.tenant, [duplicate])
        self.assertEqual(tagged, 1)
        self.assertEqual(llm.call_count, 0)  # cache hit — no LLM call
        duplicate.refresh_from_db()
        self.assertEqual(duplicate.tagging_status, 'tagged')

    def test_bank_question_difficulty_is_never_overwritten(self):
        question = Question.objects.create(
            tenant=self.tenant, topic=self.topic, subject=self.subject,
            question_text='Define displacement.', question_type='mcq',
            correct_answer='0', difficulty='easy', status='published',
        )
        response = _llm_response([{
            'id': str(question.id), 'concepts': ['Displacement'],
            'topic': 'Kinematics', 'difficulty': 'hard', 'cognitive_type': 'recall',
        }])
        with self.stub_provider(), self.stub_llm(response):
            tagged = tagging.tag_questions(self.tenant, [question])
        self.assertEqual(tagged, 1)
        question.refresh_from_db()
        self.assertEqual(question.difficulty, 'easy')  # authored value kept
        self.assertEqual(question.cognitive_type, 'recall')

    def test_mock_test_without_course_is_skipped(self):
        orphan_test = MockTest.objects.create(
            tenant=self.tenant, title='Orphan', duration_minutes=30, total_marks=5,
        )
        item = MockTestItem.objects.create(
            tenant=self.tenant, mock_test=orphan_test, item_type='mcq',
            question_text='Q?', options=[{'text': 'A', 'is_correct': True},
                                         {'text': 'B', 'is_correct': False}],
        )
        with self.stub_provider(), self.stub_llm(_llm_response([])) as llm:
            tagged = tagging.tag_mock_items(self.tenant, [item])
        self.assertEqual(tagged, 0)
        self.assertEqual(llm.call_count, 0)
        item.refresh_from_db()
        self.assertEqual(item.tagging_status, '')
