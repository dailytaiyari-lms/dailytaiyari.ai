"""Syllabus tools: switch, job models, workers."""
from django.test import TestCase

from core.models import Tenant
from exams.models import Course
from intelligence import api
from intelligence.models import TaggingRun, TreeBuildJob


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
