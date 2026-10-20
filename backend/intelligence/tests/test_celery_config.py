"""Celery settings the learning layer depends on."""
from django.conf import settings
from django.test import SimpleTestCase


class BrokerTransportOptionsTests(SimpleTestCase):
    def test_retry_cap_and_visibility_timeout_live_in_one_dict(self):
        options = settings.CELERY_BROKER_TRANSPORT_OPTIONS
        self.assertIn('visibility_timeout', options)
        self.assertEqual(options['max_retries'], 2)
        for key in ('interval_start', 'interval_step', 'interval_max'):
            self.assertIn(key, options)
