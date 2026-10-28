"""Diagnosis-visibility knobs (spec 2B §4): question flags, student patterns,
course-tile windows, page sizes and the plain-language notes students see.

Nothing stored depends on these values: changing one only changes what the
next request shows. No version bump, no recompute.
"""

# ── Assessment panel: question flags ─────────────────────────────────────────
MIN_FLAG_ANSWERS = 8            # diagnosed answers on a question before any flag
QUESTION_FLAGS = [
    # (code, labels counted, fires at or above this share, message)
    ('many_guesses', ('guess', 'correct_lucky'), 0.35, 'May be too hard or unclear.'),
    ('many_second_guesses_or_slips', ('second_guess', 'careless_slip'), 0.25,
     'Check the wording or the answer key.'),
    ('time_crunch', ('time_pressure', 'not_seen'), 0.30,
     'Most students ran out of time before this.'),
]
BEHAVIOUR_MAX_ATTEMPTS = 500    # newest finished attempts read per assessment

# ── Student Answers tab: patterns over recent attempts ──────────────────────
ANSWERS_PAGE_SIZE = 20          # attempts per page
PATTERN_ATTEMPTS = 10           # patterns look at the newest N attempts
RUSHES_END = {
    'labels': ('time_pressure', 'guess'),
    'last_share': 0.10,         # "the last 10% of the test"
    'timed_attempts': 5,        # among the newest 5 timed attempts…
    'min_attempts': 3,          # …at least 3 show it
}
SLIPS_IN_TOPIC = {'min_slips': 3, 'min_share': 0.5}
CHANGES_RIGHT_TO_WRONG = {'min_count': 3}
GUESSES_OFTEN = {'min_share': 0.25, 'min_answers': 20}
PATTERN_MESSAGES = {
    'rushes_end': 'Rushes the last part of tests',
    'slips_in_topic': 'Careless slips mostly in {topic}',
    'changes_right_to_wrong': 'Changes right answers to wrong ones',
    'guesses_often': 'Guesses often',
}

# ── Insights home: course answer-behaviour tile ─────────────────────────────
COURSE_TILE_DAYS = 28
COURSE_TILE_WEEKS = 4
STUDENTS_TO_CHECK = {'top': 5, 'min_answers': 15}
RECENT_ASSESSMENTS = 5

# ── Students: notes on review pages (spec §4.2) ─────────────────────────────
# Only these diagnosis confidences are shown to students; for anything else
# the student sees just the "Not quite? Tell us what happened." row.
STUDENT_NOTE_CONFIDENCE = {'medium', 'high'}
# {active} is the seconds the question was on screen, rounded. Labels not
# listed here (correct, skipped, not_seen, unclear) show no note.
STUDENT_NOTES = {
    'guess': 'Looks like a quick guess — you spent {active}s here.',
    'correct_lucky': "Correct, but quickly — worth checking you're sure.",
    'correct_slow': 'Correct — took longer than usual ({active}s).',
    'second_guess': 'You changed this answer — your first choice was right.',
    'careless_slip': 'You usually get this kind of question right — possibly a slip.',
    'time_pressure': 'You ran short of time here.',
    'concept_gap': 'This one needs more practice — see My Progress.',
}
