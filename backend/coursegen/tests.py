"""Tests for the AI Course Builder.

The feature's whole promise is that **the AI proposes and the admin disposes**.
These tests pin that down: generation must never create course rows, apply must
require an explicit confirmation, and a draft must never be applied twice.

The LLM itself is stubbed — what is under test is the pipeline around it
(normalisation, review gating, the write, and tenant/role scoping).
"""
from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from assignments.models import Assignment
from coding.models import CodingProblem
from content.models import Content
from core.models import Tenant
from coursegen.models import CourseGenerationJob
from coursegen.schema import normalize_content, normalize_outline
from exams.models import Chapter, ChapterTopic, Course, Subject, Topic
from quiz.models import Question, Quiz
from users.models import User

BASE = '/api/v1/tenant-admin/course-ai'

OUTLINE_RESPONSE = """
Sure! Here is the outline:
```json
{
  "course": {"name": "Intro to Python", "code": "intro-python",
             "course_type": "skill", "description": "Learn Python."},
  "subjects": [{
    "name": "Foundations", "code": "foundations", "weightage": 100,
    "chapters": [{
      "name": "Getting Started", "code": "getting-started",
      "topics": [
        {"name": "Variables", "code": "variables", "difficulty": "easy"},
        {"name": "Loops", "code": "loops", "difficulty": "medium"}
      ]
    }]
  }]
}
```
"""

CONTENT_RESPONSE = """
{"topics": [{
  "topic_code": "variables", "topic_name": "Variables",
  "note": {"title": "Understanding Variables", "blocks": [
    {"type": "lead", "text": "A variable is a labelled box."},
    {"type": "heading", "text": "Why they matter"},
    {"type": "paragraph", "text": "They let you name a value."},
    {"type": "callout", "variant": "recap", "text": "Names point at values."}
  ]},
  "quiz": {"title": "Variables Quiz", "duration_minutes": 8, "questions": [
    {"question_text": "What does x = 5 do?",
     "options": ["Deletes x", "Binds x to 5", "Prints 5", "Nothing"],
     "correct_option": 1, "explanation": "Assignment binds the name.",
     "concept": "Assignment"}
  ]}
}]}
"""


@override_settings(COURSEGEN_ASYNC=False)
class _StudioTestCase(TestCase):
    """Shared fixtures: a tenant with a configured provider and a small course.

    Generation is forced inline here: the suite stubs the provider call
    in-process, so dispatching to a Celery worker would bypass the stub (and
    there is no broker in CI). The async path itself is exercised separately by
    :class:`AsyncGenerationTests`.
    """

    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create(name='Test Academy', is_active=True)
        cls.other_tenant = Tenant.objects.create(name='Rival Academy', is_active=True)

        cls.admin = User.objects.create_user(
            email='admin@example.com', password='pw-admin-123', tenant=cls.tenant, role='admin'
        )
        cls.instructor = User.objects.create_user(
            email='teach@example.com', password='pw-teach-123',
            tenant=cls.tenant, role='instructor',
        )
        cls.outsider = User.objects.create_user(
            email='rival@example.com', password='pw-rival-123',
            tenant=cls.other_tenant, role='admin',
        )

        cls.course = Course.objects.create(
            tenant=cls.tenant, name='Python', code='python-test', course_type='skill'
        )
        cls.subject = Subject.objects.create(
            tenant=cls.tenant, course=cls.course, name='Core', code='core'
        )
        cls.chapter = Chapter.objects.create(
            tenant=cls.tenant, subject=cls.subject, name='Basics', code='basics'
        )
        cls.topic = Topic.objects.create(
            tenant=cls.tenant, subject=cls.subject, name='Variables', code='variables'
        )
        ChapterTopic.objects.create(
            tenant=cls.tenant, chapter=cls.chapter, topic=cls.topic, order=0
        )

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
            f'{BASE}{path}', HTTP_X_TENANT_ID=str((tenant or self.tenant).id)
        )

    def patch(self, user, path, payload, tenant=None):
        return self.client_for(user).patch(
            f'{BASE}{path}', payload, format='json',
            HTTP_X_TENANT_ID=str((tenant or self.tenant).id),
        )

    @staticmethod
    def stub_llm(response_text):
        """Patch the provider call so no network request is ever made."""
        from chatbot.providers import Usage

        return patch(
            'coursegen.generation.complete',
            return_value=(response_text, Usage(100, 200, 300), 1200),
        )

    @staticmethod
    def stub_provider():
        """Pretend the tenant has a working provider configured."""
        from chatbot.providers import ResolvedProvider

        return patch(
            'coursegen.generation.resolve_for_admin',
            return_value=ResolvedProvider(provider='openai', api_key='k', model='gpt-4o-mini'),
        )


class GenerationNeverWritesTests(_StudioTestCase):
    """The central guarantee: generating produces a draft and nothing else."""

    def test_outline_generation_creates_no_course_rows(self):
        before = Course.objects.count()
        with self.stub_provider(), self.stub_llm(OUTLINE_RESPONSE):
            response = self.post(self.admin, '/jobs/', {
                'kind': 'outline', 'prompt': 'A beginner Python course',
            })

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], 'preview')
        self.assertEqual(response.data['summary'], {'subjects': 1, 'chapters': 1, 'topics': 2})
        # Nothing was written.
        self.assertEqual(Course.objects.count(), before)
        self.assertFalse(Subject.objects.filter(code='foundations').exists())

    def test_content_generation_creates_no_content_rows(self):
        with self.stub_provider(), self.stub_llm(CONTENT_RESPONSE):
            response = self.post(self.admin, '/jobs/', {
                'kind': 'content', 'prompt': '', 'course': str(self.course.id),
                'topic_ids': [str(self.topic.id)],
            })

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['summary']['questions'], 1)
        self.assertFalse(Content.objects.filter(topic=self.topic).exists())
        self.assertFalse(Quiz.objects.filter(topic=self.topic).exists())

    def test_failed_generation_is_reported_not_raised(self):
        with self.stub_provider(), self.stub_llm('I am afraid I cannot do that.'):
            response = self.post(self.admin, '/jobs/', {
                'kind': 'outline', 'prompt': 'Something',
            })
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.data['status'], 'failed')
        self.assertIn('JSON', response.data['error'])


class ApplyRequiresConfirmationTests(_StudioTestCase):
    """Applying is a separate, explicit, one-shot action."""

    def _outline_job(self):
        with self.stub_provider(), self.stub_llm(OUTLINE_RESPONSE):
            response = self.post(self.admin, '/jobs/', {
                'kind': 'outline', 'prompt': 'A beginner Python course',
            })
        return response.data['id']

    def test_apply_without_confirm_is_rejected(self):
        job_id = self._outline_job()
        response = self.post(self.admin, f'/jobs/{job_id}/apply/', {'confirm': False})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Course.objects.filter(code='intro-python').exists())

    def test_confirmed_apply_creates_the_tree(self):
        job_id = self._outline_job()
        response = self.post(self.admin, f'/jobs/{job_id}/apply/', {'confirm': True})

        self.assertEqual(response.status_code, 200)
        course = Course.objects.get(code='intro-python')
        self.assertEqual(course.tenant, self.tenant)
        # A generated course is never live until an admin publishes it.
        self.assertEqual(course.status, 'coming_soon')
        self.assertEqual(Topic.objects.filter(subject__course=course).count(), 2)
        self.assertEqual(response.data['summary']['topics'], 2)

    def test_a_draft_cannot_be_applied_twice(self):
        job_id = self._outline_job()
        self.post(self.admin, f'/jobs/{job_id}/apply/', {'confirm': True})
        again = self.post(self.admin, f'/jobs/{job_id}/apply/', {'confirm': True})

        self.assertEqual(again.status_code, 409)
        self.assertEqual(Course.objects.filter(code='intro-python').count(), 1)

    def test_discarded_draft_cannot_be_applied(self):
        job_id = self._outline_job()
        self.post(self.admin, f'/jobs/{job_id}/discard/')
        response = self.post(self.admin, f'/jobs/{job_id}/apply/', {'confirm': True})

        self.assertEqual(response.status_code, 409)
        self.assertFalse(Course.objects.filter(code='intro-python').exists())

    def test_unticking_everything_writes_nothing(self):
        # An empty selection means "none of it" — not "all of it".
        job_id = self._outline_job()
        response = self.post(self.admin, f'/jobs/{job_id}/apply/', {
            'confirm': True, 'selection': {'topics': []},
        })
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Course.objects.filter(code='intro-python').exists())

    def test_selection_limits_what_is_written(self):
        job_id = self._outline_job()
        response = self.post(self.admin, f'/jobs/{job_id}/apply/', {
            'confirm': True,
            'selection': {'topics': ['variables']},
        })
        self.assertEqual(response.status_code, 200)
        course = Course.objects.get(code='intro-python')
        names = set(Topic.objects.filter(subject__course=course).values_list('name', flat=True))
        self.assertEqual(names, {'Variables'})


class ContentApplyTests(_StudioTestCase):
    def _content_job(self):
        with self.stub_provider(), self.stub_llm(CONTENT_RESPONSE):
            response = self.post(self.admin, '/jobs/', {
                'kind': 'content', 'course': str(self.course.id),
                'topic_ids': [str(self.topic.id)],
                'options': {'publish_immediately': True},
            })
        return response.data['id']

    def test_apply_writes_note_and_quiz(self):
        job_id = self._content_job()
        response = self.post(self.admin, f'/jobs/{job_id}/apply/', {'confirm': True})
        self.assertEqual(response.status_code, 200)

        note = Content.objects.get(topic=self.topic, content_type='notes')
        self.assertEqual(note.status, 'published')
        self.assertIn('labelled box', note.content_html)
        self.assertEqual(note.subject, self.subject)
        self.assertIn(self.course, note.courses.all())

        quiz = Quiz.objects.get(topic=self.topic)
        self.assertEqual(quiz.questions.count(), 1)
        question = Question.objects.get(topic=self.topic)
        # The player compares the submitted option index against this string.
        self.assertEqual(question.correct_answer, '1')
        self.assertTrue(question.options.get(order=1).is_correct)
        self.assertEqual(question.tags, ['Assignment'])

    def test_reapplying_updates_the_note_instead_of_duplicating(self):
        self.post(self.admin, f'/jobs/{self._content_job()}/apply/', {'confirm': True})
        self.post(self.admin, f'/jobs/{self._content_job()}/apply/', {'confirm': True})
        self.assertEqual(Content.objects.filter(topic=self.topic, content_type='notes').count(), 1)

    def test_quiz_with_attempts_is_not_overwritten(self):
        job_id = self._content_job()
        self.post(self.admin, f'/jobs/{job_id}/apply/', {'confirm': True})
        quiz = Quiz.objects.get(topic=self.topic)
        Quiz.objects.filter(pk=quiz.pk).update(total_attempts=4)

        self.post(self.admin, f'/jobs/{self._content_job()}/apply/', {'confirm': True})
        # The attempted quiz survives; the new material lands in a second quiz.
        self.assertEqual(Quiz.objects.filter(topic=self.topic).count(), 2)
        self.assertEqual(Quiz.objects.get(pk=quiz.pk).total_attempts, 4)


class DraftEditingTests(_StudioTestCase):
    def test_admin_edits_are_renormalised(self):
        with self.stub_provider(), self.stub_llm(OUTLINE_RESPONSE):
            job_id = self.post(self.admin, '/jobs/', {
                'kind': 'outline', 'prompt': 'Python',
            }).data['id']

        job = CourseGenerationJob.objects.get(id=job_id)
        edited = job.draft
        edited['subjects'][0]['chapters'][0]['topics'][0]['name'] = '  Renamed   Topic  '
        edited['subjects'][0]['chapters'][0]['topics'][0]['difficulty'] = 'impossible'

        response = self.patch(self.admin, f'/jobs/{job_id}/', {'draft': edited})
        self.assertEqual(response.status_code, 200)
        topic = response.data['draft']['subjects'][0]['chapters'][0]['topics'][0]
        self.assertEqual(topic['name'], 'Renamed Topic')
        # An invalid choice falls back rather than reaching the database.
        self.assertEqual(topic['difficulty'], 'medium')

    def test_applied_draft_cannot_be_edited(self):
        with self.stub_provider(), self.stub_llm(OUTLINE_RESPONSE):
            job_id = self.post(self.admin, '/jobs/', {
                'kind': 'outline', 'prompt': 'Python',
            }).data['id']
        self.post(self.admin, f'/jobs/{job_id}/apply/', {'confirm': True})

        response = self.patch(self.admin, f'/jobs/{job_id}/', {'draft': {'subjects': []}})
        self.assertEqual(response.status_code, 409)


class ScopingTests(_StudioTestCase):
    """Tenant and role boundaries hold for every studio endpoint."""

    def test_another_tenants_admin_cannot_see_the_job(self):
        with self.stub_provider(), self.stub_llm(OUTLINE_RESPONSE):
            job_id = self.post(self.admin, '/jobs/', {
                'kind': 'outline', 'prompt': 'Python',
            }).data['id']

        response = self.get(self.outsider, f'/jobs/{job_id}/', tenant=self.other_tenant)
        self.assertEqual(response.status_code, 404)

    def test_instructor_cannot_create_a_new_course(self):
        with self.stub_provider(), self.stub_llm(OUTLINE_RESPONSE):
            response = self.post(self.instructor, '/jobs/', {
                'kind': 'outline', 'prompt': 'A brand new course',
            })
        self.assertEqual(response.status_code, 403)

    def test_instructor_cannot_generate_for_an_unassigned_course(self):
        with self.stub_provider(), self.stub_llm(CONTENT_RESPONSE):
            response = self.post(self.instructor, '/jobs/', {
                'kind': 'content', 'course': str(self.course.id),
                'topic_ids': [str(self.topic.id)],
            })
        self.assertEqual(response.status_code, 404)

    def test_instructor_can_generate_for_an_assigned_course(self):
        self.course.instructors.add(self.instructor)
        with self.stub_provider(), self.stub_llm(CONTENT_RESPONSE):
            response = self.post(self.instructor, '/jobs/', {
                'kind': 'content', 'course': str(self.course.id),
                'topic_ids': [str(self.topic.id)],
            })
        self.assertEqual(response.status_code, 201)

    def test_topics_from_another_course_are_refused(self):
        other = Course.objects.create(
            tenant=self.tenant, name='Other', code='other-test', course_type='skill'
        )
        other_subject = Subject.objects.create(
            tenant=self.tenant, course=other, name='S', code='s'
        )
        stray = Topic.objects.create(
            tenant=self.tenant, subject=other_subject, name='Stray', code='stray'
        )
        with self.stub_provider(), self.stub_llm(CONTENT_RESPONSE):
            response = self.post(self.admin, '/jobs/', {
                'kind': 'content', 'course': str(self.course.id),
                'topic_ids': [str(stray.id)],
            })
        self.assertEqual(response.status_code, 400)


class StudioSurfaceTests(_StudioTestCase):
    """The read-only endpoints the composer depends on."""

    def test_options_reports_not_ready_without_a_provider(self):
        response = self.get(self.admin, '/options/')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['is_ready'])
        self.assertIn('AI Features', response.data['not_ready_reason'])
        self.assertTrue(response.data['can_create_courses'])
        self.assertIn(
            str(self.course.id), [c['id'] for c in response.data['courses']]
        )

    def test_instructor_only_sees_their_own_courses(self):
        response = self.get(self.instructor, '/options/')
        self.assertEqual(response.data['courses'], [])
        self.assertFalse(response.data['can_create_courses'])

    def test_health_is_a_cheap_probe(self):
        response = self.get(self.admin, '/health/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('is_ready', response.data)

    def test_course_tree_flags_existing_material(self):
        response = self.get(self.admin, f'/courses/{self.course.id}/tree/')
        self.assertEqual(response.status_code, 200)
        topic = response.data['subjects'][0]['chapters'][0]['topics'][0]
        self.assertEqual(topic['name'], 'Variables')
        self.assertFalse(topic['has_notes'])
        self.assertFalse(topic['has_quiz'])

    def test_course_tree_is_tenant_scoped(self):
        response = self.get(self.outsider, f'/courses/{self.course.id}/tree/',
                            tenant=self.other_tenant)
        self.assertEqual(response.status_code, 404)


class NormalisationTests(TestCase):
    """The normalisers are the trust boundary for anything a model returns."""

    def test_note_text_is_escaped(self):
        draft = normalize_content(
            {'topics': [{'topic_name': 'T', 'note': {'blocks': [
                {'type': 'paragraph', 'text': '<img src=x onerror=alert(1)>'}
            ]}}]},
            requested_topics=[{'id': '1', 'name': 'T', 'code': 't'}],
        )
        html = draft['topics'][0]['note']['html']
        self.assertNotIn('<img', html)
        self.assertIn('&lt;img', html)

    def test_question_without_enough_options_is_dropped(self):
        draft = normalize_content(
            {'topics': [{'topic_name': 'T', 'quiz': {'questions': [
                {'question_text': 'Only one?', 'options': ['a'], 'correct_option': 0},
                {'question_text': 'Duplicates?', 'options': ['a', 'A'], 'correct_option': 0},
                {'question_text': 'Fine?', 'options': ['a', 'b'], 'correct_option': 1},
            ]}}]},
            requested_topics=[{'id': '1', 'name': 'T', 'code': 't'}],
        )
        questions = draft['topics'][0]['quiz']['questions']
        self.assertEqual([q['question_text'] for q in questions], ['Fine?'])

    def test_out_of_range_correct_option_is_clamped(self):
        draft = normalize_content(
            {'topics': [{'topic_name': 'T', 'quiz': {'questions': [
                {'question_text': 'Q', 'options': ['a', 'b'], 'correct_option': 9},
            ]}}]},
            requested_topics=[{'id': '1', 'name': 'T', 'code': 't'}],
        )
        self.assertEqual(draft['topics'][0]['quiz']['questions'][0]['correct_option'], 0)

    def test_outline_codes_are_unique_slugs(self):
        draft = normalize_outline({'course': {'name': 'C'}, 'subjects': [{
            'name': 'S', 'chapters': [{'name': 'Ch', 'topics': [
                {'name': 'Same Name'}, {'name': 'Same Name'},
            ]}],
        }]})
        codes = [t['code'] for t in draft['subjects'][0]['chapters'][0]['topics']]
        self.assertEqual(codes, ['same-name', 'same-name-2'])

    def test_empty_chapters_are_dropped(self):
        draft = normalize_outline({'course': {'name': 'C'}, 'subjects': [{
            'name': 'S', 'chapters': [{'name': 'Empty', 'topics': []}],
        }]})
        self.assertEqual(draft['subjects'], [])


RICH_CONTENT_RESPONSE = """
{"topics": [{
  "topic_code": "variables", "topic_name": "Variables",
  "assignments": [{
    "title": "Name three things",
    "submission_type": "text",
    "max_marks": 15,
    "instructions": [
      {"type": "paragraph", "text": "Write a short program using three variables."},
      {"type": "bullets", "items": ["Use clear names", "Explain each choice"]}
    ]
  }],
  "coding_problems": [{
    "title": "Swap two numbers",
    "difficulty": "easy",
    "allowed_languages": ["python", "brainfuck"],
    "max_marks": 12,
    "statement": [{"type": "paragraph", "text": "Read two integers and print them swapped."}],
    "starter_code": {"python": "def solve():\\n    pass", "brainfuck": "+++"},
    "test_cases": [
      {"stdin": "1 2", "expected_output": "2 1", "is_sample": true, "explanation": "Swapped."},
      {"stdin": "5 9", "expected_output": "9 5"},
      {"stdin": "", "expected_output": "   "}
    ]
  }]
}]}
"""


class RichMaterialNormalisationTests(TestCase):
    """Assignments and coding problems get the same structural guarantees."""

    def _topic(self):
        import json
        draft = normalize_content(json.loads(RICH_CONTENT_RESPONSE))
        return draft['topics'][0], draft

    def test_assignment_is_normalised_and_rendered(self):
        topic, _ = self._topic()
        assignment = topic['assignments'][0]
        self.assertEqual(assignment['title'], 'Name three things')
        self.assertEqual(assignment['submission_type'], 'text')
        self.assertEqual(assignment['max_marks'], 15)
        # Rendered server-side so the preview is byte-for-byte what is stored.
        self.assertIn('<', assignment['html'])
        self.assertIn('Use clear names', assignment['html'])

    def test_unsupported_language_is_dropped(self):
        topic, _ = self._topic()
        problem = topic['coding_problems'][0]
        self.assertEqual(problem['allowed_languages'], ['python'])
        # Starter code for a language we cannot run must go with it.
        self.assertEqual(list(problem['starter_code']), ['python'])

    def test_blank_expected_output_case_is_dropped(self):
        topic, _ = self._topic()
        cases = topic['coding_problems'][0]['test_cases']
        self.assertEqual(len(cases), 2)
        self.assertTrue(cases[0]['is_sample'])

    def test_stats_count_the_new_material(self):
        _, draft = self._topic()
        stats = draft['stats']
        self.assertEqual(stats['assignments'], 1)
        self.assertEqual(stats['coding_problems'], 1)
        self.assertEqual(stats['test_cases'], 2)

    def test_problem_without_test_cases_is_rejected(self):
        draft = normalize_content({'topics': [{
            'topic_name': 'Variables',
            'coding_problems': [{
                'title': 'No cases',
                'statement': [{'type': 'paragraph', 'text': 'Do something.'}],
            }],
        }]})
        # A problem nobody can pass is worse than no problem at all.
        self.assertEqual(draft['topics'], [])


class RichMaterialApplyTests(_StudioTestCase):
    """Applying assignments and coding problems, in both modes."""

    def _job(self, mode='replace'):
        with self.stub_provider(), self.stub_llm(RICH_CONTENT_RESPONSE):
            response = self.post(self.admin, '/jobs/', {
                'kind': 'content', 'course': str(self.course.id),
                'topic_ids': [str(self.topic.id)],
                'options': {'materials': ['assignment', 'coding'], 'mode': mode},
            })
        self.assertEqual(response.status_code, 201, response.data)
        return response.data['id']

    def test_generation_still_writes_nothing(self):
        self._job()
        self.assertEqual(Assignment.objects.count(), 0)
        self.assertEqual(CodingProblem.objects.count(), 0)

    def test_apply_creates_assignment_and_problem(self):
        self.post(self.admin, f'/jobs/{self._job()}/apply/', {'confirm': True})

        assignment = Assignment.objects.get(topic=self.topic)
        self.assertEqual(assignment.submission_type, 'text')
        self.assertEqual(assignment.max_marks, 15)
        self.assertEqual(assignment.course, self.course)
        self.assertEqual(assignment.status, 'draft')
        self.assertIn('Use clear names', assignment.instructions)

        problem = CodingProblem.objects.get(topic=self.topic)
        self.assertEqual(problem.allowed_languages, ['python'])
        self.assertEqual(problem.test_cases.count(), 2)
        self.assertEqual(problem.test_cases.filter(is_sample=True).count(), 1)

    def test_replace_mode_updates_in_place(self):
        self.post(self.admin, f'/jobs/{self._job()}/apply/', {'confirm': True})
        self.post(self.admin, f'/jobs/{self._job()}/apply/', {'confirm': True})

        self.assertEqual(Assignment.objects.filter(topic=self.topic).count(), 1)
        self.assertEqual(CodingProblem.objects.filter(topic=self.topic).count(), 1)
        # Test cases are replaced wholesale, never appended to.
        self.assertEqual(CodingProblem.objects.get(topic=self.topic).test_cases.count(), 2)

    def test_add_mode_stacks_new_material(self):
        self.post(self.admin, f'/jobs/{self._job()}/apply/', {'confirm': True})
        self.post(self.admin, f'/jobs/{self._job(mode="add")}/apply/', {'confirm': True})

        self.assertEqual(Assignment.objects.filter(topic=self.topic).count(), 2)
        self.assertEqual(CodingProblem.objects.filter(topic=self.topic).count(), 2)

    def test_unknown_material_type_is_rejected(self):
        response = self.post(self.admin, '/jobs/', {
            'kind': 'content', 'course': str(self.course.id),
            'topic_ids': [str(self.topic.id)],
            'options': {'materials': ['podcast']},
        })
        self.assertEqual(response.status_code, 400)

    def test_topic_material_endpoint_lists_what_exists(self):
        self.post(self.admin, f'/jobs/{self._job()}/apply/', {'confirm': True})
        response = self.get(
            self.admin, f'/courses/{self.course.id}/topics/{self.topic.id}/material/'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['counts']['assignments'], 1)
        self.assertEqual(response.data['counts']['coding_problems'], 1)
        self.assertFalse(response.data['assignments'][0]['locked'])


class RequestedMaterialsAreEnforcedTests(_StudioTestCase):
    """A model that volunteers extra material must not be able to write it.

    The prompt asks for a specific set, but LLMs routinely return more. In
    'replace' mode an unrequested note would overwrite a hand-written one the
    admin never offered up, so the set is enforced server-side too.
    """

    def test_unrequested_note_is_dropped(self):
        handwritten = Content.objects.create(
            tenant=self.tenant, topic=self.topic, subject=self.subject,
            title='Written by a human', slug='written-by-a-human',
            content_type='notes', content_html='<p>Careful prose.</p>',
        )
        # CONTENT_RESPONSE contains BOTH a note and a quiz; only a quiz is asked for.
        with self.stub_provider(), self.stub_llm(CONTENT_RESPONSE):
            job_id = self.post(self.admin, '/jobs/', {
                'kind': 'content', 'course': str(self.course.id),
                'topic_ids': [str(self.topic.id)],
                'options': {'materials': ['quiz'], 'mode': 'replace'},
            }).data['id']

        job = CourseGenerationJob.objects.get(id=job_id)
        entry = job.draft['topics'][0]
        self.assertFalse(entry['note']['include'])
        self.assertTrue(entry['quiz']['include'])

        self.post(self.admin, f'/jobs/{job_id}/apply/', {'confirm': True})
        handwritten.refresh_from_db()
        self.assertEqual(handwritten.content_html, '<p>Careful prose.</p>')
        self.assertEqual(Quiz.objects.filter(topic=self.topic).count(), 1)

    def test_unrequested_assignment_is_dropped(self):
        with self.stub_provider(), self.stub_llm(RICH_CONTENT_RESPONSE):
            self.post(self.admin, '/jobs/', {
                'kind': 'content', 'course': str(self.course.id),
                'topic_ids': [str(self.topic.id)],
                'options': {'materials': ['coding']},
            })
        job = CourseGenerationJob.objects.latest('created_at')
        entry = job.draft['topics'][0]
        self.assertEqual(entry['assignments'], [])
        self.assertEqual(len(entry['coding_problems']), 1)


class LooseModelOutputTests(TestCase):
    """Shapes a model gets subtly wrong must degrade, not vanish."""

    def test_language_casing_is_canonicalised(self):
        draft = normalize_content({'topics': [{
            'topic_name': 'Loops',
            'coding_problems': [{
                'title': 'Sum',
                'statement': [{'type': 'paragraph', 'text': 'Add them.'}],
                'allowed_languages': ['Python', 'PYTHON', 'C++'],
                'starter_code': {'Python': 'def solve(): pass'},
                'test_cases': [{'stdin': '1', 'expected_output': '1'}],
            }],
        }]})
        problem = draft['topics'][0]['coding_problems'][0]
        # Non-canonical keys would make normalized_languages() fall back to
        # *every* language, silently widening what the problem accepts.
        self.assertEqual(problem['allowed_languages'], ['python'])
        self.assertEqual(problem['starter_code'], {'python': 'def solve(): pass'})

    def test_prose_instead_of_blocks_is_accepted(self):
        draft = normalize_content({'topics': [{
            'topic_name': 'Loops',
            'assignments': [{'title': 'Essay', 'instructions': 'Write 500 words on loops.'}],
            'coding_problems': [{
                'title': 'Sum',
                'statement': 'Read two integers and print the sum.',
                'test_cases': [{'stdin': '1 2', 'expected_output': '3'}],
            }],
        }]})
        topic = draft['topics'][0]
        self.assertIn('500 words', topic['assignments'][0]['html'])
        self.assertIn('print the sum', topic['coding_problems'][0]['html'])


@override_settings(COURSEGEN_ASYNC=True)
class AsyncGenerationTests(_StudioTestCase):
    """The background path: the view queues and returns, the worker generates.

    Long authoring runs must not be held open on an HTTP request, so `POST
    /jobs/` answers 202 with a still-`pending` job and the studio polls it.
    """

    def test_generate_queues_and_returns_a_pending_job(self):
        with patch('coursegen.tasks.run_generation_job.delay') as delay:
            response = self.post(self.admin, '/jobs/', {
                'kind': 'outline', 'prompt': 'A beginner Python course',
            })

        self.assertEqual(response.status_code, 202, response.data)
        self.assertEqual(response.data['status'], 'pending')
        self.assertTrue(response.data['is_running'])
        delay.assert_called_once()
        # Nothing was generated on the request thread.
        job = CourseGenerationJob.objects.get(id=response.data['id'])
        self.assertEqual(job.draft, {})

    def test_content_job_snapshots_its_topics_for_a_later_retry(self):
        with patch('coursegen.tasks.run_generation_job.delay'):
            response = self.post(self.admin, '/jobs/', {
                'kind': 'content', 'prompt': '', 'course': str(self.course.id),
                'topic_ids': [str(self.topic.id)],
            })

        job = CourseGenerationJob.objects.get(id=response.data['id'])
        snapshot = job.options.get('topics_snapshot')
        self.assertEqual([t['id'] for t in snapshot], [str(self.topic.id)])

    def test_a_broker_outage_falls_back_to_inline_generation(self):
        with patch(
            'coursegen.tasks.run_generation_job.delay', side_effect=OSError('no broker')
        ), self.stub_provider(), self.stub_llm(OUTLINE_RESPONSE):
            response = self.post(self.admin, '/jobs/', {
                'kind': 'outline', 'prompt': 'A beginner Python course',
            })

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['status'], 'preview')

    def test_worker_runs_the_job_and_leaves_it_reviewable(self):
        from coursegen.tasks import run_generation_job

        job = CourseGenerationJob.objects.create(
            tenant=self.tenant, created_by=self.admin, kind='outline',
            prompt='A beginner Python course',
        )
        with self.stub_provider(), self.stub_llm(OUTLINE_RESPONSE):
            run_generation_job(str(job.id))

        job.refresh_from_db()
        self.assertEqual(job.status, 'preview')
        self.assertTrue(job.draft.get('subjects'))
        self.assertFalse(job.is_running)

    def test_worker_ignores_a_job_that_is_not_runnable(self):
        from coursegen.tasks import run_generation_job

        job = CourseGenerationJob.objects.create(
            tenant=self.tenant, created_by=self.admin, kind='outline',
            prompt='x', status='applied',
        )
        # A broker redelivery must not re-run an already-applied job.
        self.assertIsNone(run_generation_job(str(job.id)))
        job.refresh_from_db()
        self.assertEqual(job.status, 'applied')

    def test_only_a_failed_job_can_be_regenerated(self):
        job = CourseGenerationJob.objects.create(
            tenant=self.tenant, created_by=self.admin, kind='outline',
            prompt='x', status='preview', draft={'subjects': []},
        )
        response = self.post(self.admin, f'/jobs/{job.id}/regenerate/')
        self.assertEqual(response.status_code, 409)

    def test_regenerate_requeues_a_failed_job(self):
        job = CourseGenerationJob.objects.create(
            tenant=self.tenant, created_by=self.admin, kind='outline',
            prompt='x', status='failed', error='boom',
        )
        with patch('coursegen.tasks.run_generation_job.delay') as delay:
            response = self.post(self.admin, f'/jobs/{job.id}/regenerate/')

        self.assertEqual(response.status_code, 202, response.data)
        self.assertEqual(response.data['status'], 'pending')
        self.assertEqual(response.data['error'], '')
        delay.assert_called_once()

    def test_a_failed_refine_restores_the_previous_draft(self):
        from coursegen import generation

        job = CourseGenerationJob.objects.create(
            tenant=self.tenant, created_by=self.admin, kind='outline',
            prompt='x', status='preview',
            draft=normalize_outline({
                'course': {'name': 'Intro', 'code': 'intro'},
                'subjects': [{'name': 'S', 'code': 's', 'chapters': [
                    {'name': 'C', 'code': 'c', 'topics': [{'name': 'T', 'code': 't'}]},
                ]}],
            }),
        )
        keep = job.draft
        with self.stub_provider(), self.stub_llm('not json at all'):
            with self.assertRaises(generation.GenerationError):
                generation.apply_refinement(job, 'make it harder')

        job.refresh_from_db()
        self.assertEqual(job.status, 'preview')
        self.assertEqual(job.draft, keep)
        self.assertTrue(job.error)


class TopicJobVisibilityTests(_StudioTestCase):
    """In-flight work must be findable from the topic it was started on.

    The course builder shows generation in the tab the material will land in, so
    an admin who closes the studio never loses sight of a running job or an
    unreviewed draft.
    """

    def _content_job(self, status='generating', topic=None, materials=('quiz',)):
        topic = topic or self.topic
        return CourseGenerationJob.objects.create(
            tenant=self.tenant, created_by=self.admin, course=self.course,
            kind='content', prompt='x', status=status,
            options={
                'materials': list(materials),
                'topics_snapshot': [{'id': str(topic.id), 'name': topic.name}],
            },
        )

    def test_jobs_can_be_filtered_to_one_topic(self):
        wanted = self._content_job()
        other_topic = Topic.objects.create(
            subject=self.subject, name='Other', code='other', order=2,
        )
        self._content_job(topic=other_topic)

        response = self.get(
            self.admin, f'/jobs/?course={self.course.id}&topic={self.topic.id}'
        )

        self.assertEqual(response.status_code, 200, response.data)
        ids = [row['id'] for row in response.data['results']]
        self.assertEqual(ids, [str(wanted.id)])

    def test_open_status_returns_only_unfinished_work(self):
        running = self._content_job(status='generating')
        awaiting = self._content_job(status='preview')
        self._content_job(status='applied')
        self._content_job(status='discarded')

        response = self.get(
            self.admin,
            f'/jobs/?course={self.course.id}&topic={self.topic.id}&status=open',
        )

        self.assertEqual(response.status_code, 200, response.data)
        ids = {row['id'] for row in response.data['results']}
        self.assertEqual(ids, {str(running.id), str(awaiting.id)})

    def test_rows_say_which_tab_they_belong_to_and_whether_they_run(self):
        self._content_job(status='generating', materials=('notes', 'coding'))

        response = self.get(
            self.admin,
            f'/jobs/?course={self.course.id}&topic={self.topic.id}&status=open',
        )

        row = response.data['results'][0]
        self.assertEqual(row['options']['materials'], ['notes', 'coding'])
        self.assertTrue(row['is_running'])

    def test_an_instructor_cannot_see_another_course_s_jobs(self):
        self._content_job()

        response = self.get(
            self.instructor,
            f'/jobs/?course={self.course.id}&topic={self.topic.id}&status=open',
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['results'], [])
