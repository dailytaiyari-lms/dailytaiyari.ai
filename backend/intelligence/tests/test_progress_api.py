"""My Progress: switch, endpoints, scope and opt-out."""
from django.test import TestCase

from core.models import Tenant
from intelligence import api


class SwitchTests(TestCase):
    def test_my_progress_is_opt_in_and_a_learning_feature(self):
        self.assertIn('my_progress', Tenant.FEATURE_CHOICES)
        self.assertIn('my_progress', Tenant.OPT_IN_FEATURES)
        self.assertIn('my_progress', api.LEARNING_FEATURES)
        tenant = Tenant.objects.create(name='Progress Switch Academy')
        self.assertFalse(tenant.get_features()['my_progress'])
        self.assertFalse(api.intelligence_enabled(tenant))
        tenant.features = {'my_progress': True}
        self.assertTrue(api.intelligence_enabled(tenant))
