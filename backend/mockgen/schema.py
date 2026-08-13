"""The mock-test draft shape, and the normalisers that enforce it.

An LLM is a best-effort JSON producer, not a validator. Everything it returns
passes through here first, so the preview, the editor and the apply step only
ever deal with a paper that is *structurally guaranteed*:

* every item is one of the five types :class:`quiz.models.MockTestItem` supports;
* an MCQ has at least two distinct options and exactly one correct answer
  (``mcq_multi`` needs at least one);
* a numerical item has an answer, a coding item has at least one runnable test
  case in a language the judge actually runs;
* marks are numbers in range, sections are contiguous from zero, and each item
  carries a stable ``key`` so the preview's tick-boxes survive a refine.

The same normalisers run again when an admin hand-edits a draft, so a typed edit
can never produce something the apply step would choke on.
"""
from __future__ import annotations

from coding.languages import LANGUAGE_KEYS
from quiz.models import MockTest, MockTestItem

# Hard ceilings, so one over-eager prompt can't produce a paper that takes an
# hour to review or thousands of rows to write.
MAX_ITEMS_PER_TEST = 100
MAX_ITEMS_PER_REQUEST = 60
MAX_SECTIONS = 10
MAX_OPTIONS_PER_ITEM = 8
MAX_TEST_CASES = 15
MAX_DURATION_MINUTES = 600

ITEM_TYPES = [value for value, _label in MockTestItem.ITEM_TYPES]
ITEM_TYPE_SET = set(ITEM_TYPES)
CODING_LANGUAGES = set(LANGUAGE_KEYS)
RESULT_VISIBILITIES = {value for value, _label in MockTest.RESULT_VISIBILITY_CHOICES}

# Types that need no manual grading. Used for the preview's "needs grading"
# warning, since a subjective-heavy paper changes an admin's workflow.
AUTO_GRADED_TYPES = {'mcq', 'mcq_multi', 'numerical', 'coding'}


# ─────────────────────────────────────────────────────────────────────────────
# Small coercers
# ─────────────────────────────────────────────────────────────────────────────

def _text(value, limit, default=''):
    if value is None:
        return default
    cleaned = ' '.join(str(value).split())
    return cleaned[:limit] if cleaned else default


def _long_text(value, limit=6000, default=''):
    if value is None:
        return default
    cleaned = str(value).strip()
    return cleaned[:limit] if cleaned else default


def _choice(value, allowed, default):
    candidate = str(value or '').strip().lower().replace(' ', '_')
    return candidate if candidate in allowed else default


def _number(value, default, minimum, maximum, ndigits=2):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, round(number, ndigits)))


def _int(value, default, minimum, maximum):
    return int(_number(value, default, minimum, maximum, ndigits=0))


def _bool(value, default=False):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ('true', 'yes', '1'):
            return True
        if lowered in ('false', 'no', '0'):
            return False
    return default


def _key(value, index, used):
    """A stable, unique handle for one item.

    The preview ticks items by key and the apply step writes only the ticked
    ones, so a key must survive an edit and never collide.
    """
    base = _text(value, 40).lower().replace(' ', '-') or f'q{index + 1}'
    base = ''.join(ch for ch in base if ch.isalnum() or ch in '-_') or f'q{index + 1}'
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f'{base}-{suffix}'
        suffix += 1
    used.add(candidate)
    return candidate


# ─────────────────────────────────────────────────────────────────────────────
# Items
# ─────────────────────────────────────────────────────────────────────────────

def _normalize_options(raw, *, multi):
    """Options for an MCQ, guaranteed distinct with a workable correct answer."""
    options = []
    seen = set()
    for entry in (raw or [])[:MAX_OPTIONS_PER_ITEM]:
        if isinstance(entry, dict):
            text = _long_text(entry.get('text') or entry.get('option_text'), 1000)
            correct = _bool(entry.get('is_correct'))
        else:
            text = _long_text(entry, 1000)
            correct = False
        if not text or text.lower() in seen:
            continue
        seen.add(text.lower())
        options.append({'text': text, 'is_correct': correct})

    if len(options) < 2:
        return None

    flagged = [index for index, option in enumerate(options) if option['is_correct']]
    if not flagged:
        # The model answered by index instead of by flag, or forgot entirely.
        return options, False
    if not multi and len(flagged) > 1:
        # Single-answer MCQ: keep the first, so the paper stays gradable.
        for index in flagged[1:]:
            options[index]['is_correct'] = False
    return options, True


def _apply_correct_index(options, raw):
    """Fall back to ``correct_option`` / ``correct_index`` / ``answer``."""
    for field in ('correct_option', 'correct_index', 'answer', 'correct'):
        value = raw.get(field)
        if value is None:
            continue
        if isinstance(value, str) and len(value.strip()) == 1 and value.strip().isalpha():
            # "B" → index 1.
            index = ord(value.strip().upper()) - ord('A')
        else:
            try:
                index = int(value)
            except (TypeError, ValueError):
                continue
        if 0 <= index < len(options):
            options[index]['is_correct'] = True
            return True
    return False


def normalize_item(raw, index=0, *, used_keys=None, section_count=1, negative_marking=True):
    """One question of any supported type, or ``None`` when unsalvageable."""
    if not isinstance(raw, dict):
        return None

    used_keys = used_keys if used_keys is not None else set()
    item_type = _choice(raw.get('item_type') or raw.get('type'), ITEM_TYPE_SET, 'mcq')
    text = _long_text(raw.get('question_text') or raw.get('question') or raw.get('statement'), 8000)
    if not text:
        return None

    marks = _number(raw.get('marks'), 1, 0, 1000)
    negative = _number(raw.get('negative_marks'), 0, 0, 1000) if negative_marking else 0

    item = {
        'key': _key(raw.get('key'), index, used_keys),
        'item_type': item_type,
        'section': _int(raw.get('section'), 0, 0, max(0, section_count - 1)),
        'question_text': text,
        'explanation': _long_text(raw.get('explanation'), 4000),
        'marks': marks,
        'negative_marks': negative,
        'difficulty': _choice(raw.get('difficulty'), {'easy', 'medium', 'hard'}, 'medium'),
        'concept': _text(raw.get('concept') or raw.get('topic'), 200),
        'options': [],
        'order': index,
        'include': True,
    }

    if item_type in ('mcq', 'mcq_multi'):
        prepared = _normalize_options(raw.get('options'), multi=item_type == 'mcq_multi')
        if not prepared:
            return None
        options, has_correct = prepared
        if not has_correct and not _apply_correct_index(options, raw):
            # An MCQ nobody can get right is worse than no question at all.
            return None
        item['options'] = options

    elif item_type == 'numerical':
        answer = raw.get('numerical_answer')
        if answer is None:
            answer = raw.get('answer')
        try:
            item['numerical_answer'] = round(float(answer), 6)
        except (TypeError, ValueError):
            return None
        item['numerical_tolerance'] = _number(
            raw.get('numerical_tolerance'), 0.01, 0, 1000, ndigits=5
        )
        item['unit'] = _text(raw.get('unit'), 40)

    elif item_type == 'subjective':
        item['max_words'] = _int(raw.get('max_words'), 0, 0, 5000) or None
        item['rubric'] = _long_text(raw.get('rubric'), 4000)
        item['model_answer'] = _long_text(raw.get('model_answer') or raw.get('answer'), 8000)
        # Subjective items are hand-graded; a negative mark makes no sense.
        item['negative_marks'] = 0

    elif item_type == 'coding':
        languages = []
        for entry in raw.get('allowed_languages') or []:
            key = str(entry or '').strip().lower()
            if key in CODING_LANGUAGES and key not in languages:
                languages.append(key)
        item['allowed_languages'] = languages or ['python']

        starter = {}
        raw_starter = raw.get('starter_code')
        if isinstance(raw_starter, dict):
            for key, value in list(raw_starter.items())[:10]:
                key = str(key).strip().lower()
                if key in item['allowed_languages']:
                    starter[key] = str(value or '')[:4000]
        item['starter_code'] = starter

        cases = []
        for raw_case in (raw.get('coding_test_cases') or raw.get('test_cases') or [])[:MAX_TEST_CASES]:
            case = _normalize_test_case(raw_case)
            if case:
                cases.append(case)
        if not cases:
            # A coding item with no case can never be auto-graded.
            return None
        if not any(case['is_sample'] for case in cases):
            cases[0]['is_sample'] = True
        item['coding_test_cases'] = cases
        item['time_limit_ms'] = _int(raw.get('time_limit_ms'), 3000, 500, 15000)
        item['memory_limit_mb'] = _int(raw.get('memory_limit_mb'), 256, 32, 1024)
        item['negative_marks'] = 0

    return item


def _normalize_test_case(raw):
    if not isinstance(raw, dict):
        return None
    # stdin/expected_output are compared byte-for-byte by the judge, so they
    # must never be whitespace-squashed the way prose is.
    expected = str(raw.get('expected_output') or raw.get('output') or '')[:4000]
    if not expected.strip():
        return None
    return {
        'stdin': str(raw.get('stdin') or raw.get('input') or '')[:4000],
        'expected_output': expected,
        'is_sample': _bool(raw.get('is_sample')),
        'points': _int(raw.get('points'), 1, 1, 100),
        'explanation': _text(raw.get('explanation'), 500),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Whole paper
# ─────────────────────────────────────────────────────────────────────────────

def normalize_sections(raw, *, fallback_name='Section'):
    sections = []
    for index, entry in enumerate((raw or [])[:MAX_SECTIONS]):
        if isinstance(entry, str):
            entry = {'name': entry}
        if not isinstance(entry, dict):
            continue
        sections.append({
            'index': len(sections),
            'name': _text(entry.get('name') or entry.get('title'), 120,
                          default=f'{fallback_name} {len(sections) + 1}'),
            'description': _text(entry.get('description'), 500),
        })
    return sections


def normalize_mock(payload, *, existing_test=None, options=None):
    """Coerce a model's JSON into the canonical mock-test draft.

    ``existing_test`` fills the paper's settings for a *modify* job, so an admin
    who only asked for "swap section B for harder questions" keeps their
    duration, marking scheme and visibility rules untouched.
    """
    payload = payload if isinstance(payload, dict) else {}
    options = options or {}
    raw_test = payload.get('test') if isinstance(payload.get('test'), dict) else {}

    defaults = _defaults_from(existing_test, options)
    negative_marking = _bool(raw_test.get('negative_marking'), defaults['negative_marking'])

    test = {
        'title': _text(raw_test.get('title'), 300, default=defaults['title']),
        'description': _long_text(raw_test.get('description'), 4000, default=defaults['description']),
        'duration_minutes': _int(
            raw_test.get('duration_minutes'), defaults['duration_minutes'], 1, MAX_DURATION_MINUTES
        ),
        'negative_marking': negative_marking,
        'is_free': _bool(raw_test.get('is_free'), defaults['is_free']),
        'result_visibility': _choice(
            raw_test.get('result_visibility'), RESULT_VISIBILITIES, defaults['result_visibility']
        ),
        'fullscreen_required': _bool(
            raw_test.get('fullscreen_required'), defaults['fullscreen_required']
        ),
        'max_attempts': _int(raw_test.get('max_attempts'), defaults['max_attempts'], 1, 100),
    }

    sections = normalize_sections(payload.get('sections'))
    raw_items = payload.get('items') or payload.get('questions') or []
    if not isinstance(raw_items, list):
        raw_items = []

    used_keys = set()
    items = []
    for index, raw_item in enumerate(raw_items[:MAX_ITEMS_PER_TEST]):
        item = normalize_item(
            raw_item, index=len(items), used_keys=used_keys,
            section_count=max(1, len(sections)),
            negative_marking=negative_marking,
        )
        if item is None:
            continue
        if 'include' in (raw_item if isinstance(raw_item, dict) else {}):
            item['include'] = _bool(raw_item.get('include'), True)
        items.append(item)

    # Sections are an index space: an item can never point past the list, and a
    # paper with items but no declared sections gets one implicit section.
    if not sections and items:
        sections = [{'index': 0, 'name': 'Section 1', 'description': ''}]
    for item in items:
        if item['section'] >= len(sections):
            item['section'] = 0

    draft = {
        'test': test,
        'sections': sections,
        'items': items,
        'stats': mock_stats(items, sections),
    }
    return draft


def _defaults_from(existing_test, options):
    """Settings to fall back on: the paper being modified, else the blueprint."""
    if existing_test is not None:
        return {
            'title': existing_test.title,
            'description': existing_test.description or '',
            'duration_minutes': existing_test.duration_minutes or 60,
            'negative_marking': bool(existing_test.negative_marking),
            'is_free': bool(existing_test.is_free),
            'result_visibility': existing_test.result_visibility,
            'fullscreen_required': bool(existing_test.fullscreen_required),
            'max_attempts': existing_test.max_attempts or 1,
        }
    return {
        'title': _text(options.get('title'), 300, default='Untitled Mock Test'),
        'description': '',
        'duration_minutes': _int(options.get('duration_minutes'), 60, 1, MAX_DURATION_MINUTES),
        'negative_marking': _bool(options.get('negative_marking'), True),
        'is_free': _bool(options.get('is_free'), False),
        'result_visibility': _choice(
            options.get('result_visibility'), RESULT_VISIBILITIES, 'immediate'
        ),
        'fullscreen_required': _bool(options.get('fullscreen_required'), True),
        'max_attempts': _int(options.get('max_attempts'), 1, 1, 100),
    }


def mock_stats(items, sections=None):
    by_type = {}
    by_difficulty = {}
    total_marks = 0.0
    needs_grading = 0
    for item in items or []:
        by_type[item['item_type']] = by_type.get(item['item_type'], 0) + 1
        by_difficulty[item.get('difficulty', 'medium')] = (
            by_difficulty.get(item.get('difficulty', 'medium'), 0) + 1
        )
        total_marks += float(item.get('marks') or 0)
        if item['item_type'] not in AUTO_GRADED_TYPES:
            needs_grading += 1
    return {
        'items': len(items or []),
        'sections': len(sections or []),
        'by_type': by_type,
        'by_difficulty': by_difficulty,
        'total_marks': round(total_marks, 2),
        'needs_manual_grading': needs_grading,
    }


def merge_items(existing, incoming, *, limit=MAX_ITEMS_PER_TEST):
    """Append ``incoming`` to ``existing``, re-keying and re-ordering.

    Generation runs in batches; each batch is normalised on its own and then
    merged here so one bad batch never costs the batches that worked. A later
    batch is told what has already been written, but models still repeat
    themselves, so an identical stem is dropped rather than duplicated.
    """
    merged = []
    used_keys = set()
    seen_stems = set()
    for item in list(existing or []) + list(incoming or []):
        if len(merged) >= limit:
            break
        stem = ' '.join((item.get('question_text') or '').lower().split())
        if stem and stem in seen_stems:
            continue
        seen_stems.add(stem)
        clone = dict(item)
        clone['key'] = _key(clone.get('key'), len(merged), used_keys)
        clone['order'] = len(merged)
        merged.append(clone)
    return merged


def draft_summary(draft):
    """One-line-ish summary used by the history list and the job serializer."""
    draft = draft or {}
    stats = draft.get('stats') or mock_stats(draft.get('items') or [], draft.get('sections') or [])
    test = draft.get('test') or {}
    return {
        'title': test.get('title') or '',
        'duration_minutes': test.get('duration_minutes') or 0,
        **stats,
    }
