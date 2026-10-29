"""My Progress knobs (spec 2B §6): topic bands, the evidence floor, the
trend window, list sizes, facet weights, recent-answer wording and the
heatmap cap.

Bands, list sizes and wording are display-only: changing them changes the
next request, nothing stored. Facet weights change stored LearnerFacetState
values: bump FACET_MODEL_VERSION and run ``recompute_learner_state``.
"""

# ── Topic bands (§6.2) ───────────────────────────────────────────────────────
WEAK_BELOW = 0.5
STRONG_AT = 0.8
MIN_EVIDENCE = 3            # effective evidence before a node shows a mastery
TOP_TOPICS = 5              # weak / strong list length

# ── Trend (§6.1) ─────────────────────────────────────────────────────────────
TREND_WEEKS = 4
TREND_MIN_EVENTS = 2        # a week with fewer answers is null
TREND_MAX_EVENTS = 2000     # newest events read per request

# ── Facets (§6.3) ────────────────────────────────────────────────────────────
SKILL_ROLE_WEIGHTS = {'core': 1.0, 'supporting': 0.5}
THINKING_LEVEL_WEIGHT = 1.0
FACET_REFRESH_LIMIT = 2000  # students per nightly facet sweep

# ── Recent answers (§6.4) ────────────────────────────────────────────────────
RECENT_ATTEMPTS = 5
# (singular, plural) per label, for "2 quick guesses, 1 ran out of time".
# Labels not listed (correct, skipped, not_seen, unclear) are not counted;
# neither are low-confidence diagnoses (visibility_config.STUDENT_NOTE_CONFIDENCE).
RECENT_PHRASES = {
    'guess': ('quick guess', 'quick guesses'),
    'correct_lucky': ('quick correct answer', 'quick correct answers'),
    'correct_slow': ('slow correct answer', 'slow correct answers'),
    'second_guess': ('changed right answer', 'changed right answers'),
    'careless_slip': ('possible slip', 'possible slips'),
    'time_pressure': ('ran out of time', 'ran out of time'),
    'concept_gap': ('needs more practice', 'need more practice'),
}

# ── Class heatmap (§6.5) ─────────────────────────────────────────────────────
HEATMAP_MAX_STUDENTS = 500
HEATMAP_BANDS = ('weak', 'in_progress', 'strong', 'not_enough_data')
