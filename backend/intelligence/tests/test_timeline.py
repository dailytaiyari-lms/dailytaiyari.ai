"""Timeline reduction (pure) — raw browser events to per-question timing."""
from django.test import SimpleTestCase

from intelligence.services.timeline import (
    MAX_EVENTS, TimelineError, clean_events, reduce_sessions, window_start_s,
)


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
