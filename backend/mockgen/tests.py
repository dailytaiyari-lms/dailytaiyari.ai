"""Tests for the AI Mock Test Builder.

The feature's promise is the same as the course builder's: **the AI proposes and
the admin disposes**. These tests pin that down — generation must never create
mock-test rows, apply must require an explicit confirmation, a draft can never be
applied twice, and a "Modify with AI" run must never silently delete a question
a student has already answered.

The LLM itself is stubbed; what is under test is the pipeline around it
(normalisation, review gating, the write, and tenant scoping).
"""
import json
from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.models import Tenant
from exams.models import Chapter, ChapterTopic, Course, Subject, Topic
from mockgen.models import MockTestGenerationJob
from mockgen.schema import normalize_mock
from quiz.models import MockTest, MockTestItem
from users.models import User

BASE = '/api/v1/tenant-admin/mock-ai'

PAPER_RESPONSE = """
Sure, here is the paper:
```json
{
  "test": {"title": "Physics Unit Test", "description": "Covers kinematics.",
           "duration_minutes": 45, "negative_marking": true},
  "sections": [{"name": "Section A", "description": "Objective"}],
  "items": [
    {"key": "q1", "item_type": "mcq", "section": 0,
     "question_text": "A body starts from rest. What is its initial velocity?",
     "options": [{"text": "0 m/s", "is_correct": true}, {"text": "9.8 m/s", "is_correct": false},
                 {"text": "1 m/s", "is_correct": false}, {"text": "Cannot say", "is_correct": false}],
     "explanation": "From rest means v = 0.", "marks": 4, "negative_marks": 1},
    {"key": "q2", "item_type": "numerical", "section": 0,
     "question_text": "A car covers 100 m in 10 s. Average speed in m/s?",
     "numerical_answer": 10, "numerical_tolerance": 0.1,
     "explanation": "100/10.", "marks": 4},
    {"key": "q3", "item_type": "subjective", "section": 0,
     "question_text": "Explain the difference between speed and velocity.",
     "rubric": "2 marks for scalar/vector, 3 for an example.",
     "model_answer": "Speed is scalar; velocity is a vector.", "marks": 5},
    {"key": "q4", "item_type": "coding", "section": 0,
     "question_text": "Read n numbers and print their sum.",
     "allowed_languages": ["python"],
     "coding_test_cases": [{"stdin": "3\\n1 2 3", "expected_output": "6", "points": 1,
                            "is_sample": true}],
     "explanation": "Sum the list.", "marks": 10}
  ]
}
```
"""

BLUEPRINT = [
    {'item_type': 'mcq', 'count': 1, 'marks': 4, 'negative_marks': 1},
    {'item_type': 'numerical', 'count': 1, 'marks': 4},
    {'item_type': 'subjective', 'count': 1, 'marks': 5},
    {'item_type': 'coding', 'count': 1, 'marks': 10},
]


@override_settings(MOCKGEN_ASYNC=False)
class _MockStudioTestCase(TestCase):
    """Shared fixtures. Generation is forced inline so the stub is actually used."""

    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create(name='Test Academy', is_active=True)
        cls.other_tenant = Tenant.objects.create(name='Rival Academy', is_active=True)

        cls.admin = User.objects.create_user(
            email='mockadmin@example.com', password='pw-admin-123',
            tenant=cls.tenant, role='admin',
        )
        cls.instructor = User.objects.create_user(
            email='mockteach@example.com', password='pw-teach-123',
            tenant=cls.tenant, role='instructor',
        )
        cls.outsider = User.objects.create_user(
            email='mockrival@example.com', password='pw-rival-123',
            tenant=cls.other_tenant, role='admin',
        )

        cls.course = Course.objects.create(
            tenant=cls.tenant, name='Physics', code='physics-mock', course_type='competitive',
        )
        cls.subject = Subject.objects.create(
            tenant=cls.tenant, course=cls.course, name='Mechanics', code='mechanics',
        )
        cls.chapter = Chapter.objects.create(
            tenant=cls.tenant, subject=cls.subject, name='Kinematics', code='kinematics',
        )
        cls.topic = Topic.objects.create(
            tenant=cls.tenant, subject=cls.subject, name='Motion', code='motion',
        )
        ChapterTopic.objects.create(
            tenant=cls.tenant, chapter=cls.chapter, topic=cls.topic, order=0,
        )

    # ── helpers ─────────────────────────────────────────────────────────────

    def client_for(self, user):
        client = APIClient()
        token = RefreshToken.for_user(user).access_token
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        return client

    def post(self, user, path, payload=None, tenant=None):
        return self.client_for(user).post(
            f'{BASE}{path}', payload or {}, format='json',
            HTTP_X_TENANT_ID=str((tenant or self.tenant).id),
        )

    def get(self, user, path, tenant=None):
        return self.client_for(user).get(
            f'{BASE}{path}', HTTP_X_TENANT_ID=str((tenant or self.tenant).id),
        )

    def patch(self, user, path, payload, tenant=None):
        return self.client_for(user).patch(
            f'{BASE}{path}', payload, format='json',
            HTTP_X_TENANT_ID=str((tenant or self.tenant).id),
        )

    @staticmethod
    def stub_llm(response_text):
        from chatbot.providers import Usage

        return patch(
            'coursegen.generation.complete',
            return_value=(response_text, Usage(100, 200, 300), 1200),
        )

    @staticmethod
    def stub_provider():
        from chatbot.providers import ResolvedProvider

        return patch(
            'mockgen.generation.resolve_for_admin',
            return_value=ResolvedProvider(provider='openai', api_key='k', model='gpt-4o-mini'),
        )

    def generate(self, blueprint=None, **overrides):
        payload = {
            'kind': 'create',
            'prompt': 'A 45-minute kinematics unit test',
            'options': {'blueprint': blueprint or BLUEPRINT, 'duration_minutes': 45},
        }
        payload.update(overrides)
        with self.stub_provider(), self.stub_llm(PAPER_RESPONSE):
            return self.post(self.admin, '/jobs/', payload)

    def make_mock_test(self, **overrides):
        fields = {
            'tenant': self.tenant, 'title': 'Hand-typed Paper',
            'duration_minutes': 30, 'total_marks': 0,
        }
        fields.update(overrides)
        return MockTest.objects.create(**fields)


class GenerationNeverWritesTests(_MockStudioTestCase):
    """The central guarantee: generating produces a draft and nothing else."""

    def test_generation_creates_no_mock_test_rows(self):
        before = MockTest.objects.count()
        response = self.generate()

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], 'preview')
        self.assertEqual(response.data['summary']['items'], 4)
        self.assertEqual(MockTest.objects.count(), before)
        self.assertEqual(MockTestItem.objects.count(), 0)

    def test_every_supported_item_type_survives_normalisation(self):
        response = self.generate()
        types = [item['item_type'] for item in response.data['draft']['items']]
        self.assertEqual(sorted(types), ['coding', 'mcq', 'numerical', 'subjective'])

    def test_failed_generation_is_reported_not_raised(self):
        with self.stub_provider(), self.stub_llm('I am afraid I cannot do that.'):
            response = self.post(self.admin, '/jobs/', {
                'kind': 'create', 'prompt': 'Something',
                'options': {'blueprint': [{'item_type': 'mcq', 'count': 2}]},
            })
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.data['status'], 'failed')
        self.assertEqual(MockTestItem.objects.count(), 0)

    def test_blueprint_is_required(self):
        response = self.post(self.admin, '/jobs/', {'kind': 'create', 'prompt': 'Hi'})
        self.assertEqual(response.status_code, 400)


class ApplyTests(_MockStudioTestCase):
    """Applying is the only write, and it needs an explicit confirmation."""

    def test_apply_requires_confirmation(self):
        job_id = self.generate().data['id']
        response = self.post(self.admin, f'/jobs/{job_id}/apply/', {'confirm': False})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(MockTest.objects.count(), 0)

    def test_apply_creates_the_paper_and_its_items(self):
        job_id = self.generate().data['id']
        response = self.post(self.admin, f'/jobs/{job_id}/apply/', {'confirm': True})

        self.assertEqual(response.status_code, 200)
        mock_test = MockTest.objects.get(id=response.data['summary']['mock_test'])
        self.assertEqual(mock_test.tenant, self.tenant)
        self.assertEqual(mock_test.title, 'Physics Unit Test')
        self.assertEqual(mock_test.duration_minutes, 45)
        self.assertEqual(mock_test.status, 'draft')
        self.assertEqual(mock_test.items.count(), 4)
        # 4 + 4 + 5 + 10
        self.assertEqual(float(mock_test.total_marks), 23.0)

        coding = mock_test.items.get(item_type='coding')
        self.assertEqual(coding.allowed_languages, ['python'])
        self.assertEqual(len(coding.coding_test_cases), 1)

        mcq = mock_test.items.get(item_type='mcq')
        self.assertEqual(sum(1 for o in mcq.options if o['is_correct']), 1)

    def test_apply_writes_only_the_selected_questions(self):
        job = self.generate().data
        keys = [item['key'] for item in job['draft']['items'][:2]]
        response = self.post(self.admin, f'/jobs/{job["id"]}/apply/', {
            'confirm': True, 'selection': {'items': keys},
        })
        self.assertEqual(response.status_code, 200)
        mock_test = MockTest.objects.get(id=response.data['summary']['mock_test'])
        self.assertEqual(mock_test.items.count(), 2)

    def test_empty_selection_writes_nothing(self):
        job_id = self.generate().data['id']
        response = self.post(self.admin, f'/jobs/{job_id}/apply/', {
            'confirm': True, 'selection': {'items': []},
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(MockTest.objects.count(), 0)

    def test_a_draft_cannot_be_applied_twice(self):
        job_id = self.generate().data['id']
        self.post(self.admin, f'/jobs/{job_id}/apply/', {'confirm': True})
        again = self.post(self.admin, f'/jobs/{job_id}/apply/', {'confirm': True})
        self.assertEqual(again.status_code, 409)
        self.assertEqual(MockTest.objects.count(), 1)

    def test_publish_immediately_publishes_the_paper(self):
        with self.stub_provider(), self.stub_llm(PAPER_RESPONSE):
            job = self.post(self.admin, '/jobs/', {
                'kind': 'create', 'prompt': 'Kinematics test',
                'options': {'blueprint': BLUEPRINT, 'publish_immediately': True},
            }).data
        self.post(self.admin, f'/jobs/{job["id"]}/apply/', {'confirm': True})
        self.assertEqual(MockTest.objects.get().status, 'published')


class ModifyWithAITests(_MockStudioTestCase):
    """"Modify with AI" must work on any paper, generated or hand-typed."""

    def setUp(self):
        super().setUp()
        self.mock_test = self.make_mock_test()
        self.item = MockTestItem.objects.create(
            tenant=self.tenant, mock_test=self.mock_test, item_type='mcq', order=0,
            question_text='What is 2 + 2?', marks=2,
            options=[{'text': '3', 'is_correct': False}, {'text': '4', 'is_correct': True}],
        )

    def _revision_response(self, question_text='What is 2 + 3?'):
        return json.dumps({
            'test': {'title': 'Hand-typed Paper', 'duration_minutes': 30},
            'sections': [{'name': 'Section 1'}],
            'items': [{
                'key': str(self.item.id), 'item_type': 'mcq', 'section': 0,
                'question_text': question_text, 'marks': 2,
                'options': [{'text': '4', 'is_correct': False},
                            {'text': '5', 'is_correct': True}],
                'explanation': 'Simple arithmetic.',
            }],
        })

    def test_snapshot_renders_a_hand_typed_paper_as_a_draft(self):
        response = self.get(self.admin, f'/mock-tests/{self.mock_test.id}/snapshot/')
        self.assertEqual(response.status_code, 200)
        items = response.data['draft']['items']
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['key'], str(self.item.id))
        self.assertEqual(items[0]['question_text'], 'What is 2 + 2?')

    def test_modify_updates_the_original_row_rather_than_duplicating(self):
        with self.stub_provider(), self.stub_llm(self._revision_response()):
            job = self.post(self.admin, '/jobs/', {
                'kind': 'modify', 'mock_test': str(self.mock_test.id),
                'prompt': 'Change the arithmetic question to 2 + 3',
            }).data

        self.assertEqual(job['status'], 'preview')
        # Still untouched until the admin confirms.
        self.item.refresh_from_db()
        self.assertEqual(self.item.question_text, 'What is 2 + 2?')

        response = self.post(self.admin, f'/jobs/{job["id"]}/apply/', {'confirm': True})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['summary']['updated'], 1)
        self.assertEqual(response.data['summary']['created'], 0)
        self.assertEqual(MockTestItem.objects.filter(mock_test=self.mock_test).count(), 1)
        self.item.refresh_from_db()
        self.assertEqual(self.item.question_text, 'What is 2 + 3?')

    def test_modify_never_deletes_a_question_students_have_answered(self):
        from users.models import StudentProfile
        from quiz.models import MockTestAnswer, MockTestAttempt

        answered = MockTestItem.objects.create(
            tenant=self.tenant, mock_test=self.mock_test, item_type='mcq', order=1,
            question_text='Already answered', marks=2,
            options=[{'text': 'a', 'is_correct': True}, {'text': 'b', 'is_correct': False}],
        )
        student_user = User.objects.create_user(
            email='learner@example.com', password='pw-learner-123',
            tenant=self.tenant, role='student',
        )
        profile, _ = StudentProfile.objects.get_or_create(user=student_user)
        attempt = MockTestAttempt.objects.create(
            tenant=self.tenant, student=profile, mock_test=self.mock_test,
        )
        MockTestAnswer.objects.create(tenant=self.tenant, attempt=attempt, item=answered)

        # The revision drops `answered` entirely and rewrites the other item.
        with self.stub_provider(), self.stub_llm(self._revision_response()):
            job = self.post(self.admin, '/jobs/', {
                'kind': 'modify', 'mock_test': str(self.mock_test.id),
                'prompt': 'Remove the second question',
            }).data

        response = self.post(self.admin, f'/jobs/{job["id"]}/apply/', {'confirm': True})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['summary']['removed'], 0)
        self.assertTrue(MockTestItem.objects.filter(id=answered.id).exists())

    def test_modify_in_append_mode_keeps_untouched_questions(self):
        spare = MockTestItem.objects.create(
            tenant=self.tenant, mock_test=self.mock_test, item_type='mcq', order=1,
            question_text='Keep me', marks=2,
            options=[{'text': 'a', 'is_correct': True}, {'text': 'b', 'is_correct': False}],
        )
        with self.stub_provider(), self.stub_llm(self._revision_response()):
            job = self.post(self.admin, '/jobs/', {
                'kind': 'modify', 'mock_test': str(self.mock_test.id),
                'prompt': 'Rewrite the first question',
                'options': {'apply_mode': 'append'},
            }).data

        self.post(self.admin, f'/jobs/{job["id"]}/apply/', {'confirm': True})
        self.assertTrue(MockTestItem.objects.filter(id=spare.id).exists())

    def test_modify_requires_a_mock_test(self):
        response = self.post(self.admin, '/jobs/', {'kind': 'modify', 'prompt': 'change it'})
        self.assertEqual(response.status_code, 400)

    def test_modify_rejects_an_unknown_intent(self):
        response = self.post(self.admin, '/jobs/', {
            'kind': 'modify', 'mock_test': str(self.mock_test.id), 'prompt': 'change it',
            'options': {'intent': 'delete-everything'},
        })
        self.assertEqual(response.status_code, 400)

    def test_adding_questions_needs_a_plan(self):
        response = self.post(self.admin, '/jobs/', {
            'kind': 'modify', 'mock_test': str(self.mock_test.id), 'prompt': 'add a few',
            'options': {'intent': 'add'},
        })
        self.assertEqual(response.status_code, 400)

    def test_the_scope_the_admin_picked_reaches_the_prompt(self):
        """Intent and the ticked questions become hard rules, not hints."""
        seen = {}

        def capture(resolved, messages, *args, **kwargs):
            from chatbot.providers import Usage

            seen['user'] = messages[-1]['content']
            return self._revision_response(), Usage(10, 20, 30), 100

        with self.stub_provider(), patch('coursegen.generation.complete', side_effect=capture):
            response = self.post(self.admin, '/jobs/', {
                'kind': 'modify', 'mock_test': str(self.mock_test.id),
                'prompt': 'Swap this one out',
                'options': {'intent': 'replace', 'target_keys': [str(self.item.id)]},
            })

        self.assertEqual(response.status_code, 201)
        self.assertIn('INTENT — REPLACE QUESTIONS', seen['user'])
        self.assertIn('CHANGE ONLY THESE QUESTIONS', seen['user'])
        self.assertIn(str(self.item.id), seen['user'])
        # The paper itself is the grounding — no course syllabus is ever pasted in.
        self.assertIn('What is 2 + 2?', seen['user'])

    def test_an_add_run_states_exactly_what_to_add(self):
        seen = {}

        def capture(resolved, messages, *args, **kwargs):
            from chatbot.providers import Usage

            seen['user'] = messages[-1]['content']
            return self._revision_response(), Usage(10, 20, 30), 100

        with self.stub_provider(), patch('coursegen.generation.complete', side_effect=capture):
            response = self.post(self.admin, '/jobs/', {
                'kind': 'modify', 'mock_test': str(self.mock_test.id),
                'prompt': 'Add two more of the same flavour',
                'options': {
                    'intent': 'add',
                    'add_blueprint': [{'item_type': 'mcq', 'count': 2, 'marks': 4}],
                },
            })

        self.assertEqual(response.status_code, 201)
        self.assertIn('INTENT — ADD NEW QUESTIONS', seen['user'])
        self.assertIn('2 × mcq', seen['user'])


class ScopingTests(_MockStudioTestCase):
    """Nothing leaks across tenants, and only admins may build papers."""

    def test_another_tenants_admin_cannot_see_the_job(self):
        job_id = self.generate().data['id']
        response = self.get(self.outsider, f'/jobs/{job_id}/', tenant=self.other_tenant)
        self.assertEqual(response.status_code, 404)

    def test_instructor_cannot_generate_mock_tests(self):
        response = self.post(self.instructor, '/jobs/', {
            'kind': 'create', 'prompt': 'A test',
            'options': {'blueprint': [{'item_type': 'mcq', 'count': 2}]},
        })
        self.assertEqual(response.status_code, 403)

    def test_cannot_modify_another_tenants_mock_test(self):
        foreign = MockTest.objects.create(
            tenant=self.other_tenant, title='Not yours', duration_minutes=30, total_marks=0,
        )
        response = self.post(self.admin, '/jobs/', {
            'kind': 'modify', 'mock_test': str(foreign.id), 'prompt': 'change it',
        })
        self.assertEqual(response.status_code, 404)


class DraftEditingTests(_MockStudioTestCase):
    """An admin's hand-edits are re-normalised, and only before an apply."""

    def test_admin_edits_are_saved_and_renormalised(self):
        job = self.generate().data
        draft = job['draft']
        draft['items'][0]['question_text'] = 'Rewritten by hand'
        draft['items'][0]['marks'] = 99999  # clamped by the normaliser

        response = self.patch(self.admin, f'/jobs/{job["id"]}/', {'draft': draft})
        self.assertEqual(response.status_code, 200)
        saved = response.data['draft']['items'][0]
        self.assertEqual(saved['question_text'], 'Rewritten by hand')
        self.assertEqual(saved['marks'], 1000)

    def test_an_applied_draft_can_no_longer_be_edited(self):
        job = self.generate().data
        self.post(self.admin, f'/jobs/{job["id"]}/apply/', {'confirm': True})
        response = self.patch(self.admin, f'/jobs/{job["id"]}/', {'draft': job['draft']})
        self.assertEqual(response.status_code, 409)

    def test_discard_leaves_nothing_behind(self):
        job_id = self.generate().data['id']
        response = self.post(self.admin, f'/jobs/{job_id}/discard/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'discarded')
        self.assertEqual(MockTest.objects.count(), 0)


class VisibleProgressTests(_MockStudioTestCase):
    """In-flight work must be discoverable after the admin navigates away."""

    def test_running_jobs_are_listed_for_the_tenant(self):
        job = MockTestGenerationJob.objects.create(
            tenant=self.tenant, created_by=self.admin, kind='create',
            prompt='Long paper', status=MockTestGenerationJob.STATUS_GENERATING,
        )
        response = self.get(self.admin, '/jobs/?status=running')
        self.assertEqual(response.status_code, 200)
        ids = [row['id'] for row in response.data['results']]
        self.assertIn(str(job.id), ids)
        self.assertTrue(response.data['results'][0]['is_running'])

    def test_jobs_can_be_filtered_to_one_mock_test(self):
        mock_test = self.make_mock_test()
        mine = MockTestGenerationJob.objects.create(
            tenant=self.tenant, created_by=self.admin, kind='modify',
            mock_test=mock_test, prompt='Harder',
            status=MockTestGenerationJob.STATUS_GENERATING,
        )
        MockTestGenerationJob.objects.create(
            tenant=self.tenant, created_by=self.admin, kind='create', prompt='Other',
            status=MockTestGenerationJob.STATUS_GENERATING,
        )
        response = self.get(self.admin, f'/jobs/?mock_test={mock_test.id}&status=open')
        ids = [row['id'] for row in response.data['results']]
        self.assertEqual(ids, [str(mine.id)])


class NormaliserTests(TestCase):
    """The normaliser is the last line of defence against a sloppy model."""

    def test_an_mcq_without_a_correct_option_falls_back_to_the_index(self):
        draft = normalize_mock({'items': [{
            'item_type': 'mcq', 'question_text': 'Pick one',
            'options': ['a', 'b', 'c'], 'correct_option': 2,
        }]})
        self.assertEqual(draft['items'][0]['options'][2]['is_correct'], True)

    def test_an_unanswerable_mcq_is_dropped(self):
        draft = normalize_mock({'items': [{
            'item_type': 'mcq', 'question_text': 'Pick one', 'options': ['a', 'b'],
        }]})
        self.assertEqual(draft['items'], [])

    def test_single_answer_mcq_keeps_exactly_one_correct_option(self):
        draft = normalize_mock({'items': [{
            'item_type': 'mcq', 'question_text': 'Pick one',
            'options': [{'text': 'a', 'is_correct': True}, {'text': 'b', 'is_correct': True}],
        }]})
        flags = [o['is_correct'] for o in draft['items'][0]['options']]
        self.assertEqual(flags, [True, False])

    def test_duplicate_options_are_removed(self):
        draft = normalize_mock({'items': [{
            'item_type': 'mcq', 'question_text': 'Pick one',
            'options': [{'text': 'a', 'is_correct': True}, {'text': 'A'}, {'text': 'b'}],
        }]})
        self.assertEqual(len(draft['items'][0]['options']), 2)

    def test_a_coding_item_without_test_cases_is_dropped(self):
        draft = normalize_mock({'items': [{
            'item_type': 'coding', 'question_text': 'Sum the input',
            'allowed_languages': ['python'],
        }]})
        self.assertEqual(draft['items'], [])

    def test_unsupported_coding_languages_are_ignored(self):
        draft = normalize_mock({'items': [{
            'item_type': 'coding', 'question_text': 'Sum the input',
            'allowed_languages': ['brainfuck', 'PYTHON'],
            'test_cases': [{'stdin': '1', 'expected_output': '1'}],
        }]})
        self.assertEqual(draft['items'][0]['allowed_languages'], ['python'])

    def test_item_keys_are_unique_even_when_the_model_repeats_them(self):
        draft = normalize_mock({'items': [
            {'key': 'q1', 'item_type': 'numerical', 'question_text': 'One?',
             'numerical_answer': 1},
            {'key': 'q1', 'item_type': 'numerical', 'question_text': 'Two?',
             'numerical_answer': 2},
        ]})
        keys = [item['key'] for item in draft['items']]
        self.assertEqual(len(set(keys)), 2)

    def test_section_indices_never_point_past_the_section_list(self):
        draft = normalize_mock({
            'sections': [{'name': 'Only section'}],
            'items': [{'item_type': 'numerical', 'section': 7,
                       'question_text': 'One?', 'numerical_answer': 1}],
        })
        self.assertEqual(draft['items'][0]['section'], 0)

    def test_negative_marks_are_zeroed_when_negative_marking_is_off(self):
        draft = normalize_mock({
            'test': {'negative_marking': False},
            'items': [{'item_type': 'numerical', 'question_text': 'One?',
                       'numerical_answer': 1, 'negative_marks': 2}],
        })
        self.assertEqual(draft['items'][0]['negative_marks'], 0)

    def test_stats_summarise_the_paper(self):
        draft = normalize_mock({'items': [
            {'item_type': 'numerical', 'question_text': 'One?', 'numerical_answer': 1,
             'marks': 4},
            {'item_type': 'subjective', 'question_text': 'Explain.', 'marks': 6},
        ]})
        self.assertEqual(draft['stats']['items'], 2)
        self.assertEqual(draft['stats']['total_marks'], 10)
        self.assertEqual(draft['stats']['needs_manual_grading'], 1)


@override_settings(MOCKGEN_ASYNC=True)
class AsyncGenerationTests(_MockStudioTestCase):
    """The background path: the view queues and returns, the worker generates.

    A full paper takes several LLM calls, so it must never be held open on an
    HTTP request. `POST /jobs/` answers 202 with a still-`pending` job and the
    studio polls it — which is also what keeps the progress visible after the
    admin navigates away.
    """

    def test_generate_queues_and_returns_a_pending_job(self):
        with patch('mockgen.tasks.run_generation_job.delay') as delay:
            response = self.post(self.admin, '/jobs/', {
                'kind': 'create', 'prompt': 'Kinematics test',
                'options': {'blueprint': BLUEPRINT},
            })

        self.assertEqual(response.status_code, 202, response.data)
        self.assertEqual(response.data['status'], 'pending')
        self.assertTrue(response.data['is_running'])
        delay.assert_called_once()
        self.assertEqual(MockTestGenerationJob.objects.get(id=response.data['id']).draft, {})

    def test_a_queued_refine_reports_itself_as_running(self):
        # Otherwise the studio would see a settled job and show the very draft
        # the refine is about to replace.
        job = MockTestGenerationJob.objects.create(
            tenant=self.tenant, created_by=self.admin, kind='create',
            prompt='Kinematics', status=MockTestGenerationJob.STATUS_PREVIEW,
            draft={'test': {'title': 'Old'}, 'items': [], 'sections': []},
        )
        with patch('mockgen.tasks.run_generation_job.delay') as delay:
            response = self.post(self.admin, f'/jobs/{job.id}/refine/', {
                'instruction': 'Make it harder',
            })

        self.assertEqual(response.status_code, 202, response.data)
        self.assertTrue(response.data['is_running'])
        delay.assert_called_once()

    def test_a_broker_outage_falls_back_to_inline_generation(self):
        with patch(
            'mockgen.tasks.run_generation_job.delay', side_effect=OSError('no broker')
        ), self.stub_provider(), self.stub_llm(PAPER_RESPONSE):
            response = self.post(self.admin, '/jobs/', {
                'kind': 'create', 'prompt': 'Kinematics test',
                'options': {'blueprint': BLUEPRINT},
            })

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['status'], 'preview')

    def test_worker_runs_the_job_and_leaves_it_reviewable(self):
        from mockgen.tasks import run_generation_job

        job = MockTestGenerationJob.objects.create(
            tenant=self.tenant, created_by=self.admin, kind='create',
            prompt='Kinematics test',
            options={'blueprint': [{'item_type': 'mcq', 'count': 1, 'marks': 4}]},
            status=MockTestGenerationJob.STATUS_PENDING,
        )
        with self.stub_provider(), self.stub_llm(PAPER_RESPONSE):
            run_generation_job(str(job.id))

        job.refresh_from_db()
        self.assertEqual(job.status, MockTestGenerationJob.STATUS_PREVIEW)
        self.assertTrue(job.draft['items'])
        self.assertEqual(MockTest.objects.count(), 0)

    def test_the_worker_ignores_a_job_it_cannot_claim(self):
        from mockgen.tasks import run_generation_job

        job = MockTestGenerationJob.objects.create(
            tenant=self.tenant, created_by=self.admin, kind='create',
            prompt='Kinematics', status=MockTestGenerationJob.STATUS_APPLIED,
        )
        self.assertIsNone(run_generation_job(str(job.id)))
        job.refresh_from_db()
        self.assertEqual(job.status, MockTestGenerationJob.STATUS_APPLIED)
