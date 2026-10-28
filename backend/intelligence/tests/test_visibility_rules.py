"""Pure diagnosis-visibility rules, against hand-computed fixtures."""
from django.test import SimpleTestCase

from intelligence.services import visibility as v


def row(label, *, id=None, topic=None, metrics=None, answered=True, is_correct=None):
    if is_correct is None:
        is_correct = label in ('correct', 'correct_lucky', 'correct_slow')
    return {'id': id or f'{label}-{topic}', 'label': label, 'topic': topic,
            'metrics': metrics or {}, 'answered': answered, 'is_correct': is_correct}


class DistributionAndFlagTests(SimpleTestCase):
    def test_distribution_fills_every_label(self):
        dist = v.label_distribution(['guess', 'guess', 'correct', 'not_seen'])
        self.assertEqual(dist['total'], 4)
        self.assertEqual(dist['counts']['guess'], 2)
        self.assertEqual(dist['counts']['unclear'], 0)
        self.assertEqual(dist['shares']['guess'], 0.5)
        self.assertEqual(set(dist['counts']), set(v.LABELS))

    def test_empty_distribution(self):
        dist = v.label_distribution([])
        self.assertEqual(dist['total'], 0)
        self.assertEqual(dist['shares']['guess'], 0.0)

    def test_many_guesses_fires_at_35_percent_with_8_answers(self):
        # 2 guess + 1 correct_lucky = 3 of 8 = 37.5 %
        labels = ['guess', 'guess', 'correct_lucky'] + ['correct'] * 5
        codes = [f['code'] for f in v.question_flags(v.label_distribution(labels))]
        self.assertEqual(codes, ['many_guesses'])

    def test_flags_need_8_answers(self):
        labels = ['guess'] * 7
        self.assertEqual(v.question_flags(v.label_distribution(labels)), [])

    def test_slips_and_time_crunch(self):
        labels = (['second_guess', 'careless_slip']           # 2/8 = 25 %
                  + ['time_pressure', 'not_seen', 'not_seen']  # 3/8 = 37.5 %
                  + ['correct'] * 3)
        flags = v.question_flags(v.label_distribution(labels))
        self.assertEqual([f['code'] for f in flags],
                         ['many_second_guesses_or_slips', 'time_crunch'])
        self.assertEqual(flags[1]['message'], 'Most students ran out of time before this.')
        self.assertEqual(flags[1]['share'], 0.375)

    def test_median_ignores_none(self):
        self.assertEqual(v.median([None, 3, 1, 2]), 2)
        self.assertEqual(v.median([4, 2]), 3)
        self.assertIsNone(v.median([None]))


class LastPartTests(SimpleTestCase):
    def test_answer_in_last_ten_percent(self):
        # 1800 s window: answered at 1700 s with 100 s left (5.6 %)
        self.assertTrue(v.in_last_part('guess', {'final_answer_at_s': 1700, 'time_left_s': 100}, 0.1))
        self.assertFalse(v.in_last_part('guess', {'final_answer_at_s': 900, 'time_left_s': 900}, 0.1))

    def test_unanswered_time_pressure_counts(self):
        self.assertTrue(v.in_last_part('time_pressure', {'final_answer_at_s': None}, 0.1))
        self.assertFalse(v.in_last_part('guess', {}, 0.1))


LATE = {'final_answer_at_s': 1750, 'time_left_s': 50, 'ended_late': True}
TIMED = {'ended_late': False, 'final_answer_at_s': 100, 'time_left_s': 1700}


class PatternTests(SimpleTestCase):
    def attempts(self, *answer_lists):
        return [{'answers': answers} for answers in answer_lists]

    def test_rushes_end_needs_3_of_last_5_timed_attempts(self):
        rushed = [row('time_pressure', metrics=LATE), row('correct', metrics=TIMED)]
        calm = [row('correct', metrics=TIMED)]
        patterns = v.detect_patterns(self.attempts(rushed, calm, rushed, rushed, calm))
        found = {p['code']: p for p in patterns}
        self.assertIn('rushes_end', found)
        self.assertEqual(found['rushes_end']['count'], 3)
        self.assertEqual(found['rushes_end']['message'], 'Rushes the last part of tests')

    def test_rushes_end_ignores_untimed_attempts(self):
        untimed = [row('guess', metrics={'final_answer_at_s': 10})]
        rushed = [row('time_pressure', metrics=LATE)]
        patterns = v.detect_patterns(self.attempts(rushed, rushed, untimed, untimed, untimed))
        self.assertNotIn('rushes_end', [p['code'] for p in patterns])

    def test_slips_concentrated_in_one_topic(self):
        answers = ([row('careless_slip', id=f'k{i}', topic='Kinematics') for i in range(3)]
                   + [row('careless_slip', id='o1', topic='Optics')])
        patterns = v.detect_patterns(self.attempts(answers))
        slip = next(p for p in patterns if p['code'] == 'slips_in_topic')
        self.assertEqual(slip['topic'], 'Kinematics')
        self.assertEqual(slip['count'], 3)
        self.assertEqual(slip['message'], 'Careless slips mostly in Kinematics')
        self.assertEqual(sorted(slip['answer_ids']), ['k0', 'k1', 'k2'])

    def test_slips_spread_out_do_not_fire(self):
        answers = ([row('careless_slip', id=f'k{i}', topic='Kinematics') for i in range(3)]
                   + [row('careless_slip', id=f'o{i}', topic='Optics') for i in range(4)])
        codes = [p['code'] for p in v.detect_patterns(self.attempts(answers))]
        self.assertIn('slips_in_topic', codes)   # Optics: 4 of 7 = 57 %
        answers = ([row('careless_slip', id=f'k{i}', topic='Kinematics') for i in range(3)]
                   + [row('careless_slip', id=f'o{i}', topic='Optics') for i in range(3)]
                   + [row('careless_slip', id='w1', topic='Waves')])
        codes = [p['code'] for p in v.detect_patterns(self.attempts(answers))]
        self.assertNotIn('slips_in_topic', codes)  # top topic 3 of 7 = 43 %

    def test_changes_right_to_wrong(self):
        answers = [row('second_guess', id=f's{i}') for i in range(3)]
        patterns = v.detect_patterns(self.attempts(answers))
        self.assertEqual([p['code'] for p in patterns], ['changes_right_to_wrong'])

    def test_guesses_often_needs_20_answers(self):
        answers = [row('guess', id=f'g{i}') for i in range(5)] + [row('correct', id=f'c{i}') for i in range(14)]
        self.assertEqual(v.detect_patterns(self.attempts(answers)), [])  # 19 answers
        answers.append(row('correct', id='c14'))
        patterns = v.detect_patterns(self.attempts(answers))
        self.assertEqual([p['code'] for p in patterns], ['guesses_often'])  # 5/20 = 25 %

    def test_only_the_last_10_attempts_count(self):
        guessy = [row('guess', id='g')] * 3
        attempts = self.attempts(*([[row('correct')]] * 10 + [guessy] * 10))
        self.assertEqual(v.detect_patterns(attempts), [])


class EvidenceTests(SimpleTestCase):
    def test_sentences_use_metrics(self):
        sentences = v.describe_evidence(
            [{'code': 'too_fast', 'detail': '3s on screen; usually 45s'},
             {'code': 'right_to_wrong', 'detail': ''},
             {'code': 'prior_mastery', 'detail': '0.82 (high)'}],
            {'active_s': 3.2, 'usual_s': 45.0, 'prior_mastery': 0.82},
        )
        self.assertEqual(sentences, [
            'Answered in 3 s; usual is 45 s.',
            'Changed a correct answer to a wrong one.',
            'Mastery before this test: 82% (high confidence).',
        ])

    def test_unknown_code_falls_back_to_detail(self):
        self.assertEqual(
            v.describe_evidence([{'code': 'new_rule', 'detail': 'something odd'}], {}),
            ['Something odd.'])

    def test_missing_metric_falls_back_to_detail(self):
        self.assertEqual(
            v.describe_evidence([{'code': 'too_long', 'detail': '300s on screen; usually 60s'}], {}),
            ['300s on screen; usually 60s.'])

    def test_bad_items_are_skipped(self):
        self.assertEqual(v.describe_evidence(['x', {'code': 'other'}], None), [])


class StudentNoteTests(SimpleTestCase):
    def test_note_with_active_seconds(self):
        self.assertEqual(
            v.student_note('guess', 'high', {'active_s': 4.4}),
            'Looks like a quick guess — you spent 4s here.')

    def test_low_confidence_is_hidden(self):
        self.assertIsNone(v.student_note('guess', 'low', {'active_s': 4}))

    def test_silent_labels(self):
        for label in ('correct', 'skipped', 'not_seen', 'unclear'):
            self.assertIsNone(v.student_note(label, 'high', {}))

    def test_note_needing_seconds_without_them_is_hidden(self):
        self.assertIsNone(v.student_note('correct_slow', 'medium', {}))

    def test_plain_note(self):
        self.assertEqual(v.student_note('time_pressure', 'medium', {}), 'You ran short of time here.')


class RatesTests(SimpleTestCase):
    def test_rates(self):
        rates = v.behaviour_rates(['guess', 'careless_slip', 'correct', 'correct'])
        self.assertEqual(rates, {'answers': 4, 'guess': 0.25, 'careless_slip': 0.25,
                                 'time_pressure': 0.0})
        self.assertEqual(v.behaviour_rates([]), {'answers': 0, 'guess': None,
                                                 'careless_slip': None, 'time_pressure': None})

    def test_students_to_check(self):
        per_student = {
            'a': ['careless_slip'] * 5 + ['correct'] * 10,   # 33 % slips
            'b': ['time_pressure'] * 9 + ['correct'] * 6,    # 60 % time pressure
            'c': ['careless_slip'] * 14,                     # 14 answers: too few
            'd': ['correct'] * 15,                           # nothing to check
        }
        rows = v.students_to_check(per_student)
        self.assertEqual([r['student_id'] for r in rows], ['b', 'a'])
        self.assertEqual(rows[0]['time_pressure'], 0.6)
