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


class ScheduleAndQueueTests(SimpleTestCase):
    def test_beat_schedule_runs_in_ist(self):
        self.assertEqual(settings.CELERY_TIMEZONE, settings.TIME_ZONE)

    def test_statistical_tasks_run_on_their_own_queue(self):
        from intelligence import tasks

        for task in (
            tasks.update_learner_state_for_attempt,
            tasks.diagnose_and_update_state,
            tasks.refresh_learner_state,
            tasks.recompute_item_stats,
            tasks.recompute_recommendations,
        ):
            with self.subTest(task=task.name):
                self.assertEqual(task.queue, 'intelligence')
