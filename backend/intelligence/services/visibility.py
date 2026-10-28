"""Diagnosis visibility rules (pure functions, spec 2B §4).

No database: views gather ResponseDiagnosis rows into plain dicts and these
functions turn them into distributions, flags, patterns, sentences and notes.
Thresholds and wording live in ``intelligence/visibility_config.py``.
"""
import re
from collections import Counter, defaultdict
from statistics import median as _median

from intelligence import visibility_config as C

LABELS = (
    'correct', 'correct_lucky', 'correct_slow', 'guess', 'second_guess',
    'careless_slip', 'time_pressure', 'concept_gap', 'skipped', 'not_seen', 'unclear',
)
RATE_LABELS = ('guess', 'careless_slip', 'time_pressure')


def median(values):
    present = [value for value in values if value is not None]
    return _median(present) if present else None


def _share(part, total):
    return round(part / total, 3) if total else 0.0


def label_distribution(labels):
    """Counts and shares of every final label (missing labels count 0)."""
    counts = Counter(labels)
    total = sum(counts.values())
    return {
        'total': total,
        'counts': {label: counts.get(label, 0) for label in LABELS},
        'shares': {label: _share(counts.get(label, 0), total) for label in LABELS},
    }


def question_flags(distribution):
    """Question flags for one item, in QUESTION_FLAGS order."""
    total = distribution['total']
    if total < C.MIN_FLAG_ANSWERS:
        return []
    flags = []
    for code, labels, threshold, message in C.QUESTION_FLAGS:
        share = sum(distribution['counts'][label] for label in labels) / total
        if share >= threshold:
            flags.append({'code': code, 'message': message, 'share': round(share, 3)})
    return flags


def in_last_part(label, metrics, share):
    """Did this answer happen in the last ``share`` of a timed window?

    Answered items: from the answer time and the time left. Unanswered
    ``time_pressure`` items always count — that label only fires at the end.
    """
    metrics = metrics or {}
    at, left = metrics.get('final_answer_at_s'), metrics.get('time_left_s')
    if at is not None and left is not None:
        duration = at + left
        return duration > 0 and left <= share * duration
    return label == 'time_pressure'


def _timed(answers):
    return any('ended_late' in (row.get('metrics') or {}) for row in answers)


def _rushes_end(attempts):
    rule = C.RUSHES_END
    timed = [attempt for attempt in attempts if _timed(attempt['answers'])]
    hits = []
    for attempt in timed[:rule['timed_attempts']]:
        rushed = [
            row['id'] for row in attempt['answers']
            if row['label'] in rule['labels']
            and in_last_part(row['label'], row.get('metrics'), rule['last_share'])
        ]
        if rushed:
            hits.append(rushed)
    if len(hits) < rule['min_attempts']:
        return None
    return {'code': 'rushes_end', 'message': C.PATTERN_MESSAGES['rushes_end'],
            'count': len(hits), 'answer_ids': [i for ids in hits for i in ids]}


def _slips_in_topic(rows):
    rule = C.SLIPS_IN_TOPIC
    slips = [row for row in rows if row['label'] == 'careless_slip']
    by_topic = defaultdict(list)
    for row in slips:
        if row.get('topic'):
            by_topic[row['topic']].append(row['id'])
    if not by_topic:
        return None
    topic, ids = max(by_topic.items(), key=lambda pair: (len(pair[1]), pair[0]))
    if len(ids) < rule['min_slips'] or len(ids) / len(slips) < rule['min_share']:
        return None
    return {'code': 'slips_in_topic', 'topic': topic,
            'message': C.PATTERN_MESSAGES['slips_in_topic'].format(topic=topic),
            'count': len(ids), 'answer_ids': ids}


def _changes_right_to_wrong(rows):
    ids = [row['id'] for row in rows
           if row['label'] == 'second_guess' and not row.get('is_correct')]
    if len(ids) < C.CHANGES_RIGHT_TO_WRONG['min_count']:
        return None
    return {'code': 'changes_right_to_wrong',
            'message': C.PATTERN_MESSAGES['changes_right_to_wrong'],
            'count': len(ids), 'answer_ids': ids}


def _guesses_often(rows):
    rule = C.GUESSES_OFTEN
    answered = [row for row in rows if row.get('answered')]
    ids = [row['id'] for row in answered if row['label'] == 'guess']
    if len(answered) < rule['min_answers'] or len(ids) / len(answered) < rule['min_share']:
        return None
    return {'code': 'guesses_often', 'message': C.PATTERN_MESSAGES['guesses_often'],
            'count': len(ids), 'answer_ids': ids}


def detect_patterns(attempts):
    """Patterns over the newest ``PATTERN_ATTEMPTS`` attempts (newest first)."""
    window = attempts[:C.PATTERN_ATTEMPTS]
    rows = [row for attempt in window for row in attempt['answers']]
    found = [
        _rushes_end(window), _slips_in_topic(rows),
        _changes_right_to_wrong(rows), _guesses_often(rows),
    ]
    return [pattern for pattern in found if pattern]


# ── Evidence sentences (teachers) ────────────────────────────────────────────

def _secs(value):
    return f'{round(value)} s'


def _pct(value):
    return f'{round(value * 100)}%'


def _confidence_suffix(detail):
    match = re.search(r'\((low|medium|high)\)', detail or '')
    return f' ({match.group(1)} confidence)' if match else ''


def _sentence(code, detail, m):
    """One sentence for one evidence item, or None to fall back to detail."""
    active, usual = m.get('active_s'), m.get('usual_s')
    if code == 'too_fast' and active is not None and usual:
        return f'Answered in {_secs(active)}; usual is {_secs(usual)}.'
    if code == 'too_long' and active is not None and usual:
        return f'Spent {_secs(active)} on it; usual is {_secs(usual)}.'
    if code == 'last_minute' and m.get('time_left_s') is not None:
        return f"Answered with {_secs(m['time_left_s'])} left."
    if code == 'rushed' and m.get('rel_speed') is not None:
        return f"Took {_pct(m['rel_speed'])} of the usual time, near the end."
    if code == 'right_to_wrong':
        return 'Changed a correct answer to a wrong one.'
    if code == 'wrong_to_right':
        return 'Fixed an earlier wrong answer.'
    if code == 'tab_hidden' and m.get('hidden_s') is not None:
        return f"The tab was hidden for {_secs(m['hidden_s'])}."
    if code == 'late_third':
        return 'Answered in the last third of the test.'
    if code == 'slip_match':
        return f'The wrong value is a common slip away from the answer ({detail}).'
    if code == 'misconception_pick':
        return 'Picked the same wrong option as on an earlier attempt.'
    if code == 'prior_mastery' and m.get('prior_mastery') is not None:
        return (f"Mastery before this test: {_pct(m['prior_mastery'])}"
                f'{_confidence_suffix(detail)}.')
    if code == 'no_timeline':
        return 'No timing data was recorded for this answer.'
    return None


def describe_evidence(evidence, metrics):
    """Plain sentences for a diagnosis' evidence (teachers only).

    Unknown codes, or known codes whose metrics are missing, fall back to the
    stored ``detail``; items with neither are skipped.
    """
    metrics = metrics or {}
    sentences = []
    for item in evidence or []:
        if not isinstance(item, dict):
            continue
        detail = str(item.get('detail') or '').strip()
        sentence = _sentence(item.get('code'), detail, metrics)
        if sentence is None and detail:
            sentence = detail[0].upper() + detail[1:]
            if not sentence.endswith('.'):
                sentence += '.'
        if sentence:
            sentences.append(sentence)
    return sentences


# ── Student notes ────────────────────────────────────────────────────────────

def student_note(label, confidence, metrics):
    """The note a student sees for one answer, or None.

    Low-confidence diagnoses show nothing. A note that needs the on-screen
    seconds is dropped when they are unknown.
    """
    if confidence not in C.STUDENT_NOTE_CONFIDENCE:
        return None
    template = C.STUDENT_NOTES.get(label)
    if template is None:
        return None
    if '{active}' in template:
        active = (metrics or {}).get('active_s')
        if active is None:
            return None
        return template.format(active=round(active))
    return template


# ── Course tile ──────────────────────────────────────────────────────────────

def behaviour_rates(labels):
    """Guess, careless-slip and time-pressure shares of all diagnosed answers."""
    counts = Counter(labels)
    total = sum(counts.values())
    rates = {'answers': total}
    for label in RATE_LABELS:
        rates[label] = round(counts.get(label, 0) / total, 3) if total else None
    return rates


def students_to_check(per_student):
    """Top students by careless-slip or time-pressure rate (enough answers only)."""
    rule = C.STUDENTS_TO_CHECK
    rows = []
    for student_id, labels in per_student.items():
        if len(labels) < rule['min_answers']:
            continue
        rates = behaviour_rates(labels)
        worst = max(rates['careless_slip'], rates['time_pressure'])
        if worst <= 0:
            continue
        rows.append((worst, str(student_id), {
            'student_id': student_id, 'answers': rates['answers'],
            'careless_slip': rates['careless_slip'], 'time_pressure': rates['time_pressure'],
        }))
    rows.sort(key=lambda entry: (-entry[0], entry[1]))
    return [entry[2] for entry in rows[:rule['top']]]
