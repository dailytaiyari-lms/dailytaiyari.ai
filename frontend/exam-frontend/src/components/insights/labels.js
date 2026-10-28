// Teacher-facing names for diagnosis labels (never shown to students).
export const LABEL_ORDER = [
  'correct', 'correct_lucky', 'correct_slow', 'guess', 'second_guess',
  'careless_slip', 'time_pressure', 'concept_gap', 'skipped', 'not_seen', 'unclear',
]

export const LABEL_TEXT = {
  correct: 'Correct',
  correct_lucky: 'Correct, likely a guess',
  correct_slow: 'Correct but slow',
  guess: 'Guess',
  second_guess: 'Changed a right answer',
  careless_slip: 'Careless slip',
  time_pressure: 'Time pressure',
  concept_gap: 'Concept gap',
  skipped: 'Skipped',
  not_seen: 'Not seen',
  unclear: 'Unclear',
}

export const LABEL_COLOR = {
  correct: 'bg-success-500',
  // Only shades defined in tailwind.config.js: success/warning have no 300,
  // and the red palette is `error` (there is no `danger`).
  correct_lucky: 'bg-success-400',
  correct_slow: 'bg-success-200',
  guess: 'bg-warning-500',
  second_guess: 'bg-orange-400',
  careless_slip: 'bg-amber-300',
  time_pressure: 'bg-error-400',
  concept_gap: 'bg-error-600',
  skipped: 'bg-surface-300',
  not_seen: 'bg-surface-400',
  unclear: 'bg-surface-200',
}

export const CONFIDENCE_TEXT = { low: 'low confidence', medium: 'medium confidence', high: 'high confidence' }
