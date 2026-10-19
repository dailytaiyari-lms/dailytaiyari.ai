"""The diagnosis rules as the pure functions they are — one case per label,
plus the edges that make the labels trustworthy."""
from django.test import SimpleTestCase

from intelligence.services.diagnosis import (
    ItemFacts, TimingFacts, WindowFacts, classify, reconcile, slip_match, usual_seconds,
)

HOUR = WindowFacts(duration_s=3600, elapsed_s=1800, timed_out=False)
UNTIMED = WindowFacts(duration_s=None, elapsed_s=600, timed_out=False)


def item(**kw):
    base = {'item_type': 'mcq', 'difficulty': 'medium', 'answered': True, 'score_fraction': 0.0}
    base.update(kw)
    return ItemFacts(**base)


def timing(active, **kw):
    base = {'active_s': active, 'visits': 1, 'first_enter_at_s': 100.0,
            'final_answer_at_s': 100.0 + active}
    base.update(kw)
    return TimingFacts(**base)


class UsualTimeTests(SimpleTestCase):
    def test_stats_beat_defaults(self):
        self.assertEqual(usual_seconds(item(usual_s=33.0)), (33.0, 'stats'))
        self.assertEqual(usual_seconds(item()), (70.0, 'default'))
        self.assertEqual(usual_seconds(item(item_type='numerical', difficulty='hard')),
                         (160.0, 'default'))
        self.assertEqual(usual_seconds(item(difficulty='')), (70.0, 'default'))
        self.assertEqual(usual_seconds(item(item_type='subjective')), (None, 'none'))

    def test_timeless_ignores_stats(self):
        self.assertEqual(usual_seconds(ItemFacts(item_type='subjective', usual_s=300.0)),
                         (None, 'none'))
        d = classify(item(item_type='subjective', usual_s=300.0), timing(10.0), HOUR)
        self.assertNotEqual(d.label, 'guess')
        self.assertNotIn('too_fast', d.flags)


class SlipMatchTests(SimpleTestCase):
    def test_transforms(self):
        self.assertTrue(slip_match(-9.81, 9.81, 0.01))      # sign
        self.assertTrue(slip_match(98.1, 9.81, 0.01))       # ×10
        self.assertTrue(slip_match(0.00981, 9.81, 0.01))    # ÷1000
        self.assertTrue(slip_match(588.6, 9.81, 0.01))      # ×60
        self.assertTrue(slip_match(9.8, 9.81, 0.001))       # 2 sig figs
        self.assertFalse(slip_match(7.0, 9.81, 0.01))
        self.assertFalse(slip_match(0, 9.81, 0.01))
        self.assertFalse(slip_match(5.0, 0, 0.01))
        self.assertFalse(slip_match(None, 9.81, 0.01))

    def test_slip_tolerance_scales_with_candidate(self):
        self.assertFalse(slip_match(0.3, 5.0, 0.5))
        self.assertFalse(slip_match(0.01, 9.81, 0.01))
        self.assertFalse(slip_match(-0.005, 9.81, 0.01))


class LabelTests(SimpleTestCase):
    def test_not_seen(self):
        d = classify(item(answered=False), timing(1.0), HOUR)
        self.assertEqual((d.label, d.confidence), ('not_seen', 'high'))
        d = classify(item(answered=False), TimingFacts(), HOUR)
        self.assertEqual(d.label, 'not_seen')

    def test_skipped(self):
        d = classify(item(answered=False), timing(40.0, final_answer_at_s=None), HOUR)
        self.assertEqual(d.label, 'skipped')

    def test_unanswered_time_pressure(self):
        window = WindowFacts(duration_s=3600, elapsed_s=3600, timed_out=True)
        late = timing(20.0, first_enter_at_s=3300.0, final_answer_at_s=None)
        self.assertEqual(classify(item(answered=False), late, window).label, 'time_pressure')
        # same item, but the test was submitted early: just a skip
        early = WindowFacts(duration_s=3600, elapsed_s=2000, timed_out=False)
        self.assertEqual(classify(item(answered=False), late, early).label, 'skipped')

    def test_ended_late_is_recorded_without_timed_out(self):
        window = WindowFacts(duration_s=3600, elapsed_s=3590, timed_out=False)
        late = timing(20.0, first_enter_at_s=3300.0, final_answer_at_s=None)
        d = classify(item(answered=False), late, window)
        self.assertTrue(d.metrics['ended_late'])
        early = WindowFacts(duration_s=3600, elapsed_s=2000, timed_out=False)
        self.assertFalse(classify(item(answered=False), late, early).metrics['ended_late'])

    def test_unanswered_without_timeline_is_unclear(self):
        d = classify(item(answered=False), None, HOUR)
        self.assertEqual((d.label, d.confidence), ('unclear', 'low'))

    def test_correct_variants(self):
        self.assertEqual(classify(item(score_fraction=1.0), timing(60.0), HOUR).label, 'correct')
        self.assertEqual(classify(item(score_fraction=1.0), timing(3.0), HOUR).label,
                         'correct_lucky')
        self.assertEqual(classify(item(score_fraction=1.0), timing(200.0), HOUR).label,
                         'correct_slow')
        # numerical can't be lucky-guessed the way an MCQ can
        fast_numeric = item(item_type='numerical', score_fraction=1.0)
        self.assertEqual(classify(fast_numeric, timing(3.0), HOUR).label, 'correct')

    def test_guess(self):
        d = classify(item(), timing(3.0), HOUR)
        self.assertEqual(d.label, 'guess')
        self.assertIn('too_fast', d.flags)
        self.assertEqual(d.confidence, 'medium')            # default usual time
        d = classify(item(usual_s=60.0), timing(3.0), HOUR)
        self.assertEqual(d.confidence, 'high')              # stats usual time

    def test_second_guess(self):
        t = timing(60.0, answer_correctness=[True, False])
        d = classify(item(), t, HOUR)
        self.assertEqual((d.label, d.confidence), ('second_guess', 'high'))
        self.assertIn('right_to_wrong', d.flags)

    def test_time_pressure_when_rushed_in_the_last_minute(self):
        t = timing(20.0, final_answer_at_s=3570.0)
        d = classify(item(), t, HOUR)
        self.assertEqual(d.label, 'time_pressure')
        self.assertIn('last_minute', d.flags)
        self.assertIn('rushed', d.flags)

    def test_careless_slip_by_numeric_transform(self):
        f = item(item_type='numerical', numeric_value=98.1, numeric_correct=9.81,
                 numeric_tolerance=0.01)
        d = classify(f, timing(60.0), HOUR)
        self.assertEqual((d.label, d.confidence), ('careless_slip', 'high'))

    def test_careless_slip_by_mastery(self):
        f = item(prior_mastery=0.85, prior_confidence='high')
        self.assertEqual(classify(f, timing(60.0), HOUR).label, 'careless_slip')

    def test_concept_gap(self):
        weak = item(prior_mastery=0.3, prior_confidence='medium')
        self.assertEqual(classify(weak, timing(60.0), HOUR).label, 'concept_gap')
        self.assertEqual(classify(item(misconception_pick=True), timing(60.0), HOUR).label,
                         'concept_gap')
        self.assertEqual(classify(item(), timing(200.0), HOUR).label, 'concept_gap')

    def test_conflict_is_unclear(self):
        strong_but_slow = item(prior_mastery=0.9, prior_confidence='high')
        d = classify(strong_but_slow, timing(200.0), HOUR)
        self.assertEqual((d.label, d.confidence), ('unclear', 'low'))

    def test_low_confidence_mastery_is_ignored(self):
        f = item(prior_mastery=0.9, prior_confidence='low')
        self.assertEqual(classify(f, timing(60.0), HOUR).label, 'unclear')

    def test_no_timeline_still_uses_non_time_signals(self):
        f = item(item_type='numerical', numeric_value=-9.81, numeric_correct=9.81,
                 numeric_tolerance=0.01)
        d = classify(f, None, HOUR)
        self.assertEqual(d.label, 'careless_slip')
        self.assertIn('no_timeline', [e['code'] for e in d.evidence])

    def test_untimed_never_has_time_pressure(self):
        d = classify(item(), timing(20.0, final_answer_at_s=599.0), UNTIMED)
        self.assertNotIn('last_minute', d.flags)
        self.assertNotEqual(d.label, 'time_pressure')

    def test_pending_grade_is_unclear(self):
        f = item(item_type='subjective', pending_grade=True)
        self.assertEqual(classify(f, timing(300.0), HOUR).label, 'unclear')

    def test_near_threshold_on_default_usual_lowers_confidence(self):
        # default usual 70s → too_long cut 175s; 180s is within 20% of it
        d = classify(item(score_fraction=1.0), timing(180.0), HOUR)
        self.assertEqual((d.label, d.confidence), ('correct_slow', 'low'))

    def test_metrics_are_recorded(self):
        d = classify(item(), timing(35.0), HOUR)
        self.assertEqual(d.metrics['usual_s'], 70.0)
        self.assertEqual(d.metrics['usual_source'], 'default')
        self.assertAlmostEqual(d.metrics['rel_speed'], 0.5)
        self.assertEqual(d.metrics['active_s'], 35.0)
    def test_mastery_slip_near_threshold_downgrades(self):
        facts = item(prior_mastery=0.85, prior_confidence='high')
        d = classify(facts, timing(36.0), HOUR)
        self.assertEqual((d.label, d.confidence), ('careless_slip', 'low'))
        d = classify(facts, timing(60.0), HOUR)
        self.assertEqual((d.label, d.confidence), ('careless_slip', 'medium'))

    def test_unanswered_short_rule_near_threshold_downgrades(self):
        window = WindowFacts(duration_s=3600, elapsed_s=3600, timed_out=True)
        t = timing(29.0, first_enter_at_s=1000.0, final_answer_at_s=None)
        d = classify(item(answered=False), t, window)
        self.assertEqual((d.label, d.confidence), ('time_pressure', 'low'))

    def test_zero_visit_answered_is_no_timeline(self):
        d = classify(item(), TimingFacts(), HOUR)
        self.assertNotEqual(d.label, 'guess')
        self.assertIn('no_timeline', [e['code'] for e in d.evidence])

    def test_time_left_metric_clamped(self):
        d = classify(item(), timing(30.0, final_answer_at_s=3700.0), HOUR)
        self.assertEqual(d.metrics['time_left_s'], 0.0)
        self.assertIn('last_minute', d.flags)

    def test_rushed_time_pressure_far_from_its_cut_stays_medium(self):
        # rel 0.43: 29% from the rushed cut (0.6); only the slip cut is near
        d = classify(item(), timing(30.0, final_answer_at_s=3570.0), HOUR)
        self.assertEqual((d.label, d.confidence), ('time_pressure', 'medium'))

    def test_mastery_slip_far_from_slip_cuts_stays_medium(self):
        # rel 0.70: near the rushed cut, which did not decide this label
        facts = item(prior_mastery=0.85, prior_confidence='high')
        d = classify(facts, timing(49.0), HOUR)
        self.assertEqual((d.label, d.confidence), ('careless_slip', 'medium'))

    def test_unanswered_late_entry_involves_no_cut(self):
        window = WindowFacts(duration_s=3600, elapsed_s=3600, timed_out=True)
        late = timing(20.0, first_enter_at_s=3300.0, final_answer_at_s=None)
        d = classify(item(answered=False), late, window)
        self.assertEqual((d.label, d.confidence), ('time_pressure', 'medium'))

    def test_labels_decided_without_time_never_downgrade(self):
        weak = item(prior_mastery=0.3, prior_confidence='medium')
        d = classify(weak, timing(36.0), HOUR)
        self.assertEqual((d.label, d.confidence), ('concept_gap', 'medium'))
        d = classify(item(misconception_pick=True), timing(36.0), HOUR)
        self.assertEqual((d.label, d.confidence), ('concept_gap', 'medium'))



class ReconcileTests(SimpleTestCase):
    def test_confident_label_wins(self):
        self.assertEqual(reconcile('concept_gap', 'medium', [], 'slipped', False), 'concept_gap')

    def test_unclear_adopts_self_report(self):
        self.assertEqual(reconcile('unclear', 'low', [], 'slipped', False), 'careless_slip')
        self.assertEqual(reconcile('unclear', 'low', [], 'guessed', False), 'guess')
        self.assertEqual(reconcile('unclear', 'low', [], 'didnt_know', False), 'concept_gap')

    def test_behaviour_vetoes_implausible_reports(self):
        self.assertEqual(reconcile('unclear', 'low', ['too_fast'], 'slipped', False), 'unclear')
        self.assertEqual(reconcile('unclear', 'low', [], 'ran_out_of_time', False), 'unclear')
        self.assertEqual(reconcile('unclear', 'low', ['last_minute'], 'ran_out_of_time', False),
                         'time_pressure')
        self.assertEqual(reconcile('unclear', 'low', [], 'ran_out_of_time', True),
                         'time_pressure')

    def test_no_report(self):
        self.assertEqual(reconcile('unclear', 'low', [], '', False), 'unclear')
