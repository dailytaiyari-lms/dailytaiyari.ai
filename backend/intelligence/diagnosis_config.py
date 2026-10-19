"""Response-diagnosis tuning knobs, in one place.

Changing any value changes labels: bump ``versions.CLASSIFIER_VERSION`` and
run ``manage.py recompute_diagnoses``. Calibrate against self-reports with
GET /api/v1/tenant-admin/intelligence/diagnosis/calibration/.
"""

THRESHOLDS = {
    'not_seen_active_s': 2.0,       # under this on screen = never really looked
    'too_fast_floor_s': 5.0,        # too_fast: active < max(floor, ratio × usual)
    'too_fast_ratio': 0.25,
    'too_long_ratio': 2.5,          # too_long: active > ratio × usual
    'last_minute_floor_s': 60.0,    # last-minute zone: max(floor, ratio × duration)
    'last_minute_ratio': 0.05,
    'rushed_ratio': 0.6,            # rushed: last_minute and rel_speed < ratio
    'late_entry_ratio': 0.15,       # unanswered time pressure: first seen in last 15%
    'unanswered_short_ratio': 0.5,  # … or seen for under half the usual time
    'slip_mastery': 0.75,           # prior mastery that makes a wrong answer a slip
    'gap_mastery': 0.5,             # prior mastery that makes it a concept gap
    'slip_speed_min': 0.5,          # a slip happens at a normal pace
    'slip_speed_max': 2.5,
    'stats_min_n': 20,              # ItemStats median trusted from this many timings
    'near_threshold_band': 0.2,     # default-usual call within 20% of a cut → low
    'correct_score': 0.5,           # score_fraction at or above this counts as correct
    'slip_rel_tolerance': 1e-9,     # relative floor on the numeric slip-match tolerance
}

# Seconds a question usually takes, until ItemStats has enough timings.
_SINGLE = {'easy': 40.0, 'medium': 70.0, 'hard': 110.0}
_MULTI = {'easy': 60.0, 'medium': 95.0, 'hard': 140.0}
_WORKED = {'easy': 60.0, 'medium': 100.0, 'hard': 160.0}
DEFAULT_USUAL_S = {
    'mcq': _SINGLE,
    'true_false': _SINGLE,
    'mcq_multi': _MULTI,
    'match': _MULTI,
    'numerical': _WORKED,
    'fill_blank': _WORKED,
}
TIMELESS_TYPES = {'subjective', 'coding'}   # time rules never apply
MCQ_TYPES = {'mcq', 'mcq_multi', 'true_false'}
MASTERY_CONFIDENT = {'medium', 'high'}      # prior-mastery confidences the rules trust

# Mastery evidence multiplier by final label (services/state.py).
LABEL_WEIGHTS = {
    'guess': 0.2,
    'correct_lucky': 0.2,
    'careless_slip': 0.5,
    'time_pressure': 0.5,
}

# Self-report choice → the label it asserts.
SELF_REPORT_LABEL = {
    'slipped': 'careless_slip',
    'ran_out_of_time': 'time_pressure',
    'guessed': 'guess',
    'didnt_know': 'concept_gap',
}
