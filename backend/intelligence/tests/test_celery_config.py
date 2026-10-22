"""Celery settings the learning layer depends on."""
from django.conf import settings
from django.test import SimpleTestCase


class BrokerTransportOptionsTests(SimpleTestCase):
    def test_transport_options_are_unchanged_from_main(self):
        # The learning layer caps its own publish retries per call
        # (intelligence.api.ENQUEUE_RETRY_POLICY); the global setting, which
        # every other app's enqueues use, stays exactly as on main.
        self.assertEqual(set(settings.CELERY_BROKER_TRANSPORT_OPTIONS), {'visibility_timeout'})


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
