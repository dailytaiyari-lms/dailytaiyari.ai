"""Timeline reduction (pure) — raw browser events to per-question timing."""
import json
from datetime import timedelta

from django.core.cache import cache
from django.test import SimpleTestCase
from django.utils import timezone
from rest_framework.test import APIClient, APIRequestFactory, force_authenticate
from rest_framework_simplejwt.tokens import RefreshToken

from intelligence.models import AttemptTimeline, PracticeSet
from intelligence.services.timeline import (
    MAX_EVENTS, TimelineError, clean_events, reduce_sessions, window_start_s,
)
from intelligence.tests.diagnosis_fixtures import DiagnosisTestCase


def one(events, *, offset_ms=0, clock='server', known_keys=None):
    sessions = {'s1': {'offset_ms': offset_ms, 'events': events}}
    return reduce_sessions(sessions, clock=clock, known_keys=known_keys)


class CleanEventsTests(SimpleTestCase):
    def test_accepts_and_sorts(self):
        cleaned = clean_events([[5, 'l', 'bank:a'], [0, 'e', 'bank:a'], [2, 'h', None]])
        self.assertEqual([e[0] for e in cleaned], [0.0, 2.0, 5.0])

    def test_rejects_bad_shapes(self):
        for bad in (
            'nope',
            [[0]],
            [[-1, 'e', 'bank:a']],
            [[0, 'x', 'bank:a']],
            [[0, 'e', None]],
            [[0, 'a', 'bank:a', 'not-a-dict']],
            [[True, 'e', 'bank:a']],
        ):
            with self.assertRaises(TimelineError, msg=repr(bad)):
                clean_events(bad)

    def test_rejects_non_finite_times(self):
        for bad_t in (float('nan'), float('inf'), float('-inf')):
            with self.assertRaises(TimelineError, msg=repr(bad_t)):
                clean_events([[bad_t, 'e', 'bank:a']])

    def test_rejects_huge_integer_times(self):
        with self.assertRaises(TimelineError):
            clean_events([[10**400, 'e', 'bank:a']])

    def test_answer_without_a_digest_is_rejected(self):
        with self.assertRaises(TimelineError):
            clean_events([[0, 'a', 'bank:a']])

    def test_rejects_too_many(self):
        with self.assertRaises(TimelineError):
            clean_events([[i, 'h', None] for i in range(MAX_EVENTS + 1)])


class ReduceTests(SimpleTestCase):
    def test_single_visit(self):
        lines = one([[0, 'e', 'bank:a'], [10000, 'l', 'bank:a']])
        self.assertAlmostEqual(lines['bank:a'].active_s, 10.0)
        self.assertEqual(lines['bank:a'].visits, 1)
        self.assertEqual(lines['bank:a'].first_enter_at_s, 0.0)

    def test_hidden_time_inside_a_visit_is_not_active(self):
        lines = one([[0, 'e', 'bank:a'], [2000, 'h', None], [5000, 's', None],
                     [10000, 'l', 'bank:a']])
        self.assertAlmostEqual(lines['bank:a'].active_s, 7.0)
        self.assertAlmostEqual(lines['bank:a'].hidden_s, 3.0)

    def test_hidden_when_the_visit_closes(self):
        lines = one([[0, 'e', 'bank:a'], [8000, 'h', None], [10000, 'l', 'bank:a']])
        self.assertAlmostEqual(lines['bank:a'].active_s, 8.0)
        self.assertAlmostEqual(lines['bank:a'].hidden_s, 2.0)

    def test_unmatched_enter_closes_at_next_enter_and_session_end(self):
        lines = one([[0, 'e', 'bank:a'], [4000, 'e', 'bank:b'],
                     [6000, 'a', 'bank:b', {'sel': [1]}]])
        self.assertAlmostEqual(lines['bank:a'].active_s, 4.0)
        self.assertAlmostEqual(lines['bank:b'].active_s, 2.0)
        self.assertAlmostEqual(lines['bank:b'].first_answer_active_s, 2.0)
        self.assertEqual(lines['bank:b'].answers, [(6.0, {'sel': [1]})])
        self.assertAlmostEqual(lines['bank:b'].final_answer_at_s, 6.0)

    def test_open_visit_closes_at_the_session_elapsed_time(self):
        session = {'offset_ms': 0, 'elapsed_ms': 300000, 'events': [[0, 'e', 'bank:a']]}
        line = reduce_sessions({'s': session}, clock='server')['bank:a']
        self.assertAlmostEqual(line.active_s, 300.0)

    def test_open_hidden_interval_counts_up_to_the_session_end(self):
        session = {'offset_ms': 0, 'elapsed_ms': 300000,
                   'events': [[0, 'e', 'bank:a'], [100000, 'h', None]]}
        line = reduce_sessions({'s': session}, clock='server')['bank:a']
        self.assertAlmostEqual(line.active_s, 100.0)
        self.assertAlmostEqual(line.hidden_s, 200.0)

    def test_session_without_elapsed_keeps_closing_at_the_last_event(self):
        session = {'offset_ms': 0, 'events': [[0, 'e', 'bank:a'], [100000, 'h', None]]}
        line = reduce_sessions({'s': session}, clock='server')['bank:a']
        self.assertAlmostEqual(line.active_s, 100.0)
        self.assertAlmostEqual(line.hidden_s, 0.0)

    def test_bad_elapsed_is_ignored(self):
        for bad in ('x', -5, float('nan'), True):
            session = {'offset_ms': 0, 'elapsed_ms': bad, 'events': [[0, 'e', 'bank:a'], [2000, 'a', 'bank:a', {'sel': [1]}]]}
            line = reduce_sessions({'s': session}, clock='server')['bank:a']
            self.assertAlmostEqual(line.active_s, 2.0, msg=repr(bad))

    def test_clear_is_recorded_as_none(self):
        lines = one([[0, 'e', 'bank:a'], [1000, 'a', 'bank:a', {'sel': [0]}],
                     [2000, 'c', 'bank:a'], [3000, 'l', 'bank:a']])
        self.assertEqual(lines['bank:a'].answers, [(1.0, {'sel': [0]}), (2.0, None)])

    def test_sessions_merge_in_offset_order_on_server_clock(self):
        sessions = {
            'late': {'offset_ms': 100000, 'events': [
                [0, 'e', 'item:x'], [2000, 'a', 'item:x', {'sel': [1]}], [3000, 'l', 'item:x']]},
            'early': {'offset_ms': 0, 'events': [[0, 'e', 'item:x'], [5000, 'l', 'item:x']]},
        }
        line = reduce_sessions(sessions, clock='server')['item:x']
        self.assertAlmostEqual(line.active_s, 8.0)
        self.assertEqual(line.visits, 2)
        self.assertAlmostEqual(line.first_enter_at_s, 0.0)
        self.assertAlmostEqual(line.final_answer_at_s, 102.0)
        # first answer happened after 5s (session 1) + 2s (session 2) on screen
        self.assertAlmostEqual(line.first_answer_active_s, 7.0)

    def test_client_clock_window_starts_at_the_session(self):
        sessions = {'s1': {'offset_ms': 50000, 'events': [[1000, 'e', 'bank:a'],
                                                          [3000, 'l', 'bank:a']]}}
        self.assertAlmostEqual(window_start_s(sessions, 'client'), 50.0)
        self.assertAlmostEqual(window_start_s(sessions, 'server'), 0.0)
        line = reduce_sessions(sessions, clock='client')['bank:a']
        self.assertAlmostEqual(line.first_enter_at_s, 1.0)

    def test_unknown_keys_are_ignored(self):
        lines = one([[0, 'e', 'bank:ghost'], [1000, 'l', 'bank:ghost']],
                    known_keys={'bank:a'})
        self.assertNotIn('bank:ghost', lines)

    def test_corrupt_stored_session_is_skipped_not_fatal(self):
        sessions = {'bad': {'offset_ms': 0, 'events': [[0, 'zz', 'x']]},
                    'ok': {'offset_ms': 0, 'events': [[0, 'e', 'bank:a'], [1000, 'l', 'bank:a']]}}
        self.assertAlmostEqual(reduce_sessions(sessions, clock='server')['bank:a'].active_s, 1.0)

    def test_leave_for_a_non_current_question_is_ignored(self):
        lines = one([[0, 'e', 'bank:a'], [5000, 'e', 'bank:b'],
                     [5000, 'l', 'bank:a'], [9000, 'l', 'bank:b']])
        self.assertAlmostEqual(lines['bank:b'].active_s, 4.0)
        self.assertAlmostEqual(lines['bank:a'].active_s, 5.0)

    def test_unknown_key_enter_breaks_the_visit_chain(self):
        lines = one([[0, 'e', 'bank:a'], [2000, 'e', 'bank:ghost'],
                     [8000, 'e', 'bank:a'], [9000, 'l', 'bank:a']],
                    known_keys={'bank:a'})
        self.assertAlmostEqual(lines['bank:a'].active_s, 3.0)
        self.assertEqual(lines['bank:a'].visits, 2)
        self.assertNotIn('bank:ghost', lines)

    def test_malformed_sessions_are_skipped_not_fatal(self):
        ok = {'offset_ms': 0, 'events': [[0, 'e', 'bank:a'], [1000, 'l', 'bank:a']]}
        for bad in (
            'not-a-dict',
            {'offset_ms': 'x', 'events': [[0, 'e', 'bank:a'], [9000, 'l', 'bank:a']]},
            {'offset_ms': -5, 'events': [[0, 'e', 'bank:a'], [9000, 'l', 'bank:a']]},
            {'offset_ms': float('nan'), 'events': []},
        ):
            sessions = {'bad': bad, 'ok': ok}
            for clock in ('server', 'client'):
                lines = reduce_sessions(sessions, clock=clock)
                self.assertAlmostEqual(lines['bank:a'].active_s, 1.0, msg=repr(bad))
            self.assertEqual(window_start_s(sessions, 'client'), 0.0)

    def test_answers_are_ordered_by_time_across_sessions(self):
        sessions = {
            's1': {'offset_ms': 0, 'events': [
                [0, 'e', 'bank:a'], [1000, 'a', 'bank:a', {'sel': [1]}],
                [9000, 'a', 'bank:a', {'sel': [3]}], [10000, 'l', 'bank:a']]},
            's2': {'offset_ms': 3000, 'events': [
                [0, 'e', 'bank:a'], [1000, 'a', 'bank:a', {'sel': [2]}],
                [2000, 'l', 'bank:a']]},
        }
        answers = reduce_sessions(sessions, clock='server')['bank:a'].answers
        self.assertEqual([a[0] for a in answers], [1.0, 4.0, 9.0])


URL = '/api/v1/intelligence/timeline/'


class TimelineSyncTests(DiagnosisTestCase):
    def setUp(self):
        cache.clear()  # the 20/min throttle must not leak between tests

    def client_for(self, user):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(user).access_token}')
        return client

    def post(self, payload, user=None):
        return self.client_for(user or self.user).post(
            URL, payload, format='json', HTTP_X_TENANT_ID=str(self.tenant.id),
        )

    def payload(self, **overrides):
        body = {'attempt_kind': 'mock', 'session_id': 'sess-1', 'elapsed_ms': 1000,
                'truncated': False, 'events': [[0, 'e', 'item:a'], [900, 'l', 'item:a']]}
        body.update(overrides)
        return body

    def test_rich_mock_sync_anchors_offset_on_the_server(self):
        attempt = self.make_attempt(minutes_ago=30)
        response = self.post(self.payload(attempt_id=str(attempt.id)))
        self.assertEqual(response.status_code, 200, response.content)
        row = AttemptTimeline.objects.get(attempt_id=attempt.id)
        self.assertEqual(row.clock, 'server')
        self.assertEqual(row.student, self.student)
        offset = row.sessions['sess-1']['offset_ms']
        self.assertAlmostEqual(offset, 30 * 60 * 1000 - 1000, delta=5000)
        self.assertEqual(row.sessions['sess-1']['elapsed_ms'], 1000.0)

    def test_resend_replaces_the_session(self):
        attempt = self.make_attempt()
        self.post(self.payload(attempt_id=str(attempt.id)))
        self.post(self.payload(attempt_id=str(attempt.id), events=[[0, 'e', 'item:a']]))
        row = AttemptTimeline.objects.get(attempt_id=attempt.id)
        self.assertEqual(len(row.sessions), 1)
        self.assertEqual(len(row.sessions['sess-1']['events']), 1)

    def test_parent_id_resolves_in_progress_attempt_with_client_clock(self):
        attempt = self.make_attempt()
        self.post(self.payload(parent_id=str(self.mock_test.id)))
        self.post(self.payload(parent_id=str(self.mock_test.id), session_id='sess-2'))
        row = AttemptTimeline.objects.get(attempt_id=attempt.id)
        self.assertEqual(row.clock, 'client')
        # a client-timed screen restarted: only the newest session survives
        self.assertEqual(list(row.sessions), ['sess-2'])

    def test_quiz_parent_id_uses_server_clock_and_keeps_sessions(self):
        from quiz.models import Quiz, QuizAttempt
        quiz = Quiz.objects.create(
            tenant=self.tenant, course=self.course, title='Q', quiz_type='topic',
            duration_minutes=30,
        )
        attempt = QuizAttempt.objects.create(
            tenant=self.tenant, student=self.student, quiz=quiz, status='in_progress',
        )
        QuizAttempt.objects.filter(pk=attempt.pk).update(
            started_at=timezone.now() - timedelta(minutes=30))
        body = self.payload(attempt_kind='quiz', parent_id=str(quiz.id))
        self.assertEqual(self.post(body).status_code, 200)
        self.assertEqual(self.post({**body, 'session_id': 'sess-2'}).status_code, 200)
        row = AttemptTimeline.objects.get(attempt_id=attempt.id)
        # the quiz timer is anchored to started_at, so it never restarts
        self.assertEqual(row.clock, 'server')
        self.assertEqual(sorted(row.sessions), ['sess-1', 'sess-2'])
        # offset is anchored to the attempt's started_at (30 min ago - elapsed)
        self.assertAlmostEqual(row.sessions['sess-1']['offset_ms'],
                               30 * 60 * 1000 - 1000, delta=5000)

    def test_other_students_attempt_is_rejected(self):
        attempt = self.make_attempt(student=self.other_user.profile)
        response = self.post(self.payload(attempt_id=str(attempt.id)))
        self.assertEqual(response.status_code, 400)
        self.assertFalse(AttemptTimeline.objects.exists())

    def test_finished_attempt_window(self):
        attempt = self.make_attempt(minutes_ago=30)
        attempt.status = 'completed'
        attempt.completed_at = timezone.now() - timedelta(seconds=30)
        attempt.save()
        self.assertEqual(self.post(self.payload(attempt_id=str(attempt.id))).status_code, 200)
        attempt.completed_at = timezone.now() - timedelta(minutes=10)
        attempt.save()
        self.assertEqual(
            self.post(self.payload(attempt_id=str(attempt.id), session_id='late')).status_code, 400)

    def test_finalized_timeline_is_refused(self):
        attempt = self.make_attempt()
        row = self.make_timeline(attempt, [])
        row.finalized_at = timezone.now()
        row.save()
        self.assertEqual(self.post(self.payload(attempt_id=str(attempt.id))).status_code, 409)

    def test_bad_events_and_ids_are_400(self):
        attempt = self.make_attempt()
        self.assertEqual(self.post(self.payload(
            attempt_id=str(attempt.id), events=[[0, 'zz', 'x']])).status_code, 400)
        self.assertEqual(self.post(self.payload(attempt_id='not-a-uuid')).status_code, 400)
        self.assertEqual(self.post(self.payload(attempt_kind='exam',
                                                attempt_id=str(attempt.id))).status_code, 400)

    def test_oversized_body_is_413(self):
        attempt = self.make_attempt()
        key = 'item:' + 'x' * 70
        events = [[i, 'a', key, {'txt': i}] for i in range(4000)]
        payload = self.payload(attempt_id=str(attempt.id), events=events)
        self.assertGreater(len(json.dumps(payload)), 256 * 1024)
        response = self.post(payload)
        self.assertEqual(response.status_code, 413)

    def test_oversized_body_without_content_length_is_413(self):
        from intelligence.views import TimelineSyncView
        attempt = self.make_attempt()
        key = 'item:' + 'x' * 70
        events = [[i, 'a', key, {'txt': i}] for i in range(4000)]
        payload = self.payload(attempt_id=str(attempt.id), events=events)
        self.assertGreater(len(json.dumps(payload['events'], separators=(',', ':'))), 256 * 1024)
        class HeaderlessView(TimelineSyncView):
            # Parse the real body, then hide the header, as a chunked upload would.
            def initial(self, request, *args, **kwargs):
                super().initial(request, *args, **kwargs)
                request.data  # noqa: B018 - force parsing
                request._request.META['CONTENT_LENGTH'] = ''

        request = APIRequestFactory().post(URL, payload, format='json')
        request.tenant = self.tenant
        force_authenticate(request, user=self.user)
        response = HeaderlessView.as_view()(request)
        self.assertEqual(response.status_code, 413)
        self.assertFalse(AttemptTimeline.objects.exists())

    def test_non_object_body_is_400(self):
        response = self.post([1, 2, 3])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {'error': 'Body must be a JSON object.'})

    def test_timed_out_attempt_within_grace_window_accepts_sync(self):
        attempt = self.make_attempt(minutes_ago=30)
        attempt.status = 'timed_out'
        attempt.completed_at = timezone.now() - timedelta(seconds=30)
        attempt.save()
        response = self.post(self.payload(attempt_id=str(attempt.id)))
        self.assertEqual(response.status_code, 200, response.content)

    def test_timeline_throttle_is_isolated_from_the_default_user_throttle(self):
        self.tenant.features = {**(self.tenant.features or {}), 'practice': True}
        self.tenant.save()
        cache.clear()
        client = self.client_for(self.user)
        for _ in range(20):
            other = client.get('/api/v1/intelligence/mastery/',
                               HTTP_X_TENANT_ID=str(self.tenant.id))
            self.assertEqual(other.status_code, 200, other.content)
        attempt = self.make_attempt()
        response = self.post(self.payload(attempt_id=str(attempt.id)))
        self.assertEqual(response.status_code, 200, response.content)

    def test_suggested_practice_set_syncs_untimed(self):
        practice_set = PracticeSet.objects.create(
            tenant=self.tenant, student=self.student, course=self.course,
            status='suggested', deficit_kind='starter', deficit_signature='starter:test',
        )
        response = self.post(self.payload(attempt_kind='practice',
                                          attempt_id=str(practice_set.id)))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(AttemptTimeline.objects.get(attempt_id=practice_set.id).clock, 'none')
