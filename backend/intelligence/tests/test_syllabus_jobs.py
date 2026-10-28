"""Syllabus tools: switch, job models, workers."""
from django.test import TestCase

from core.models import Tenant
from intelligence import api


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
