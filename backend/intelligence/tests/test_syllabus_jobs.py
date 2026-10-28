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
