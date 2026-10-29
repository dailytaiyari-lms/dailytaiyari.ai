"""Syllabus tools: switch, job models, workers."""
from django.test import TestCase

from core.models import Tenant
from exams.models import Course
from intelligence import api
from intelligence.models import TaggingRun, TreeBuildJob
from intelligence.services.llm import budget_status


class SwitchTests(TestCase):
    def test_syllabus_tools_is_opt_in_and_a_learning_feature(self):
        self.assertIn('syllabus_tools', Tenant.FEATURE_CHOICES)
        self.assertIn('syllabus_tools', Tenant.OPT_IN_FEATURES)
        self.assertIn('syllabus_tools', api.LEARNING_FEATURES)
        tenant = Tenant.objects.create(name='Switch Academy')
        self.assertFalse(tenant.get_features()['syllabus_tools'])
        self.assertFalse(api.intelligence_enabled(tenant))
        tenant.features = {'syllabus_tools': True}
        self.assertTrue(api.intelligence_enabled(tenant))


class JobModelTests(TestCase):
    def test_defaults_and_payload(self):
        tenant = Tenant.objects.create(name='Job Academy')
        course = Course.objects.create(tenant=tenant, name='C', code='job-c', course_type='skill')
        job = TreeBuildJob.objects.create(tenant=tenant, course=course)
        self.assertEqual(job.status, 'queued')
        payload = job.payload()
        self.assertEqual(payload['kind'], 'tree_build')
        self.assertEqual(payload['status'], 'queued')
        self.assertEqual(payload['course'], str(course.id))
        run = TaggingRun.objects.create(tenant=tenant, course=course, summary={'tagged': 3})
        self.assertEqual(run.payload()['kind'], 'tagging')
        self.assertEqual(list(course.tagging_runs.all()), [run])


import json
from unittest.mock import patch

from exams.models import Subject, Topic
from intelligence.models import ItemTagging, SyllabusNode
from intelligence.services import course_tree, syllabus, tagging_sweep
from intelligence.tests.test_course_tree import FakeCall as BuildCall
from intelligence.tests.test_tagging_sweep import FakeCall as TagCall, patched_tree, tag_entry
from intelligence.tests.taxonomy_fixtures import sync_mini_vocabulary
from quiz.models import Question


class ProposedNodeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create(name='Proposed Academy', features={'syllabus_tools': True})
        cls.course = Course.objects.create(
            tenant=cls.tenant, name='DSA', code='prop-dsa', course_type='skill')
        cls.subject = Subject.objects.create(
            tenant=cls.tenant, course=cls.course, name='Arrays', code='arrays')
        cls.topic = Topic.objects.create(
            tenant=cls.tenant, subject=cls.subject, name='Two Sum', code='two-sum')

    def test_llm_subtopics_are_proposed_and_the_tagger_sees_them(self):
        course_tree.build_course_tree(
            self.course, call=BuildCall(subtopics={'Two Sum': ['Hash map lookup']}), packs=[])
        node = SyllabusNode.objects.get(subject=self.subject, name='Hash map lookup')
        self.assertEqual(node.status, 'proposed')
        context = syllabus.tagging_context(self.subject)
        keys = [sub['key'] for topic in context['topics'] for sub in topic['subtopics']]
        self.assertIn(node.key, keys)

    def test_estimate_build_counts_calls(self):
        estimate = course_tree.estimate_build(self.course)
        # 1 topic → 1 subtopic call; no grouping (≤ 6 topics); 1 packs call.
        self.assertEqual(estimate['calls'], {'grouping': 0, 'subtopics': 1, 'packs': 1})
        self.assertEqual(estimate['approx_tokens'], 2 * course_tree.TOKENS_PER_CALL)
        # A topic counts as planned once it has a subtopic; a build that got no
        # subtopics back would ask again next time (the builder does the same).
        course_tree.build_course_tree(
            self.course, call=BuildCall(subtopics={'Two Sum': ['Hash map lookup']}), packs=[])
        self.assertEqual(course_tree.estimate_build(self.course, packs=[])['llm_calls'], 0)


class SweepCountTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create(name='Count Academy', features={'syllabus_tools': True})
        cls.course = Course.objects.create(
            tenant=cls.tenant, name='Mini', code='count-mini', course_type='competitive')
        cls.subject = Subject.objects.create(
            tenant=cls.tenant, course=cls.course, name='Physics', code='physics')
        cls.laws = Topic.objects.create(
            tenant=cls.tenant, subject=cls.subject, name='Laws of Motion', code='laws-of-motion')
        sync_mini_vocabulary()
        with patched_tree():
            syllabus.instantiate_exam_tree(cls.course, 'mini', {'physics': cls.subject})
        cls.good = Question.objects.create(
            tenant=cls.tenant, subject=cls.subject, topic=cls.laws, question_type='numerical',
            question_text='Friction on a 2 kg block?', numerical_answer=10)
        cls.unsure = Question.objects.create(
            tenant=cls.tenant, subject=cls.subject, topic=cls.laws, question_type='numerical',
            question_text='Tension in a rope?', numerical_answer=5)
        cls.broken = Question.objects.create(
            tenant=cls.tenant, subject=cls.subject, topic=cls.laws, question_type='numerical',
            question_text='Something odd?', numerical_answer=1)

    def test_stats_and_topic_key(self):
        call = TagCall(tag={
            str(self.good.id): tag_entry(),
            str(self.unsure.id): tag_entry(confidence=0.2),
        })
        stats = {}
        with patched_tree():
            self.assertEqual(
                tagging_sweep.tag_v2_for_tenant(self.tenant, {self.subject.id}, call, stats=stats), 2)
        self.assertEqual(stats, {'tagged': 2, 'needs_review': 1, 'failed': 1, 'locked': 0})
        raw = ItemTagging.objects.get(question=self.good).raw
        self.assertEqual(raw['topic_key'], 'mini.physics.mechanics.laws_of_motion')

    def test_estimate_and_tag_one(self):
        with patched_tree():
            self.assertEqual(
                tagging_sweep.estimate_tagging(self.tenant, {self.subject.id})['questions'], 3)
            call = TagCall(tag={str(self.good.id): tag_entry()})
            self.assertEqual(tagging_sweep.tag_one_item(self.good, call), 1)
            self.assertEqual(
                tagging_sweep.estimate_tagging(self.tenant, {self.subject.id})['questions'], 2)

    def test_budget_status_without_budget(self):
        status = budget_status(self.tenant)
        self.assertEqual(status['monthly_budget'], None)
        self.assertFalse(status['exhausted'])


from django.utils import timezone

from coursegen.generation import GenerationError
from intelligence import tasks
from intelligence.models import Concept, ConceptLink, LearningEvent
from users.models import User


class WorkerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create(name='Worker Academy', features={'syllabus_tools': True})
        cls.course = Course.objects.create(
            tenant=cls.tenant, name='DSA', code='work-dsa', course_type='skill')
        cls.subject = Subject.objects.create(
            tenant=cls.tenant, course=cls.course, name='Arrays', code='arrays')
        Topic.objects.create(tenant=cls.tenant, subject=cls.subject, name='Two Sum', code='two-sum')

    def fake_call(self, call):
        call.meter = type('M', (), {'usage': type('U', (), {'total_tokens': 1234})()})()
        call.cost_usd = lambda: 0.01
        return patch('intelligence.services.llm.tenant_tagging_call', return_value=call)

    def test_build_job_runs_and_records(self):
        job = TreeBuildJob.objects.create(tenant=self.tenant, course=self.course, options={'packs': []})
        with self.fake_call(BuildCall(subtopics={'Two Sum': ['Hash map']})):
            tasks.run_tree_build(str(job.id))
        job.refresh_from_db()
        self.assertEqual(job.status, 'done', job.error)
        self.assertEqual(job.summary['proposed_subtopics'], 1)
        self.assertEqual(job.tokens, 1234)
        self.assertIsNotNone(job.finished_at)

    def test_second_delivery_is_a_no_op(self):
        job = TreeBuildJob.objects.create(tenant=self.tenant, course=self.course, status='done')
        with self.fake_call(BuildCall()) as patched:
            tasks.run_tree_build(str(job.id))
        patched.assert_not_called()

    def test_budget_refusal_fails_the_job(self):
        job = TreeBuildJob.objects.create(tenant=self.tenant, course=self.course)
        with patch('coursegen.generation._check_budget', side_effect=GenerationError('over budget')):
            tasks.run_tree_build(str(job.id))
        job.refresh_from_db()
        self.assertEqual((job.status, job.error), ('failed', 'over budget'))

    def test_switch_off_fails_the_job(self):
        self.tenant.features = {}
        self.tenant.save()
        run = TaggingRun.objects.create(tenant=self.tenant, course=self.course)
        tasks.run_tagging_run(str(run.id))
        run.refresh_from_db()
        self.assertEqual(run.status, 'failed')

    def test_unexpected_error_never_leaves_running(self):
        job = TreeBuildJob.objects.create(tenant=self.tenant, course=self.course)
        with self.fake_call(BuildCall()), patch(
                'intelligence.services.course_tree.build_course_tree', side_effect=RuntimeError('boom')):
            tasks.run_tree_build(str(job.id))
        job.refresh_from_db()
        self.assertEqual(job.status, 'failed')

    def test_tagging_run_without_a_tree_says_what_to_do(self):
        run = TaggingRun.objects.create(tenant=self.tenant, course=self.course)
        with self.fake_call(TagCall()):
            tasks.run_tagging_run(str(run.id))
        run.refresh_from_db()
        self.assertEqual(run.status, 'failed')
        self.assertIn('tree', run.error)


class TaggingWorkerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create(name='Tagrun Academy', features={'syllabus_tools': True})
        cls.course = Course.objects.create(
            tenant=cls.tenant, name='Mini', code='tagrun-mini', course_type='competitive')
        cls.subject = Subject.objects.create(
            tenant=cls.tenant, course=cls.course, name='Physics', code='physics')
        cls.laws = Topic.objects.create(
            tenant=cls.tenant, subject=cls.subject, name='Laws of Motion', code='laws-of-motion')
        sync_mini_vocabulary()
        with patched_tree():
            syllabus.instantiate_exam_tree(cls.course, 'mini', {'physics': cls.subject})

    def fake_call(self, call):
        call.meter = type('M', (), {'usage': type('U', (), {'total_tokens': 50})()})()
        call.cost_usd = lambda: 0.002
        return patch('intelligence.services.llm.tenant_tagging_call', return_value=call)

    def make_question(self, text='Friction on a 2 kg block?'):
        return Question.objects.create(
            tenant=self.tenant, subject=self.subject, topic=self.laws, question_type='numerical',
            question_text=text, numerical_answer=10)

    def test_empty_run_finishes_with_zero_counts(self):
        run = TaggingRun.objects.create(tenant=self.tenant, course=self.course)
        with self.fake_call(TagCall()), patched_tree():
            tasks.run_tagging_run(str(run.id))
        run.refresh_from_db()
        self.assertEqual(run.status, 'done', run.error)
        self.assertEqual(run.summary, {'tagged': 0, 'needs_review': 0, 'failed': 0, 'locked': 0})

    def test_run_tags_items_and_records_counts(self):
        question = self.make_question()
        run = TaggingRun.objects.create(tenant=self.tenant, course=self.course)
        with self.fake_call(TagCall(tag={str(question.id): tag_entry()})), patched_tree():
            tasks.run_tagging_run(str(run.id))
        run.refresh_from_db()
        self.assertEqual(run.status, 'done', run.error)
        self.assertEqual(run.summary['tagged'], 1)
        self.assertEqual(run.tokens, 50)
        self.assertTrue(ItemTagging.objects.filter(question=question).exists())

    def test_retag_item_tags_one_question(self):
        question = self.make_question()
        with self.fake_call(TagCall(tag={str(question.id): tag_entry()})), patched_tree():
            self.assertEqual(tasks.retag_item('bank', str(question.id)), 1)
        self.assertTrue(ItemTagging.objects.filter(question=question).exists())

    def test_retag_item_ignores_unknown_kind_missing_item_and_switch_off(self):
        question = self.make_question()
        self.assertEqual(tasks.retag_item('nonsense', str(question.id)), 0)
        self.assertEqual(tasks.retag_item('bank', '00000000-0000-0000-0000-000000000000'), 0)
        self.tenant.features = {}
        self.tenant.save()
        with self.fake_call(TagCall()) as patched:
            self.assertEqual(tasks.retag_item('bank', str(question.id)), 0)
        patched.assert_not_called()

    def test_retag_item_swallows_budget_refusal(self):
        question = self.make_question()
        with patch('coursegen.generation._check_budget', side_effect=GenerationError('over')):
            self.assertEqual(tasks.retag_item('bank', str(question.id)), 0)


class RecomputeWorkerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create(name='Recompute Academy', features={'syllabus_tools': True})
        cls.user = User.objects.create_user(
            email='recompute-student@example.com', password='pw-student-1',
            tenant=cls.tenant, role='student')
        cls.student = cls.user.profile
        cls.course = Course.objects.create(
            tenant=cls.tenant, name='DSA', code='rec-dsa', course_type='skill')
        cls.subject = Subject.objects.create(
            tenant=cls.tenant, course=cls.course, name='Arrays', code='arrays')
        cls.concept = Concept.objects.create(
            tenant=cls.tenant, subject=cls.subject, name='Hash map', slug='hash-map')
        cls.topic = Topic.objects.create(
            tenant=cls.tenant, subject=cls.subject, name='Two Sum', code='two-sum')
        cls.question = Question.objects.create(
            tenant=cls.tenant, subject=cls.subject, topic=cls.topic, question_type='numerical',
            question_text='Count pairs?', numerical_answer=2)
        ConceptLink.objects.create(
            tenant=cls.tenant, concept=cls.concept, question=cls.question,
            is_primary=True, weight=1.0, source='llm_tagger')
        LearningEvent.objects.create(
            tenant=cls.tenant, student=cls.student, question=cls.question,
            source_type='quiz_answer', occurred_at=timezone.now(),
            dedup_key='quiz_answer:rec:0', attempt_kind='quiz')

    def test_recomputes_each_student_with_events_on_the_concept(self):
        with patch('intelligence.services.state.recompute_state') as recompute:
            self.assertEqual(tasks.recompute_concept_states(str(self.concept.id)), 1)
        recompute.assert_called_once_with(self.student, self.concept)

    def test_missing_concept_is_a_no_op(self):
        self.assertEqual(
            tasks.recompute_concept_states('00000000-0000-0000-0000-000000000000'), 0)
