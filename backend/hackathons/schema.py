"""Normalisation and safety rules for AI-generated hackathon drafts.

The model's JSON is never trusted. Every draft that reaches an admin's preview —
and therefore everything :mod:`hackathons.apply` may write — has been through
this module: unknown fields dropped, numbers clamped, enums coerced to real
choices, HTML reduced to a small safe tag set, and every item given a stable
``key`` so the reviewer can tick items on and off across refinements.
"""
from __future__ import annotations

import html as _html
import re
import uuid

# ── limits ───────────────────────────────────────────────────────────────────
MAX_ITEMS_PER_REQUEST = 25
MAX_ITEMS_PER_STAGE = 200
MAX_STAGES = 10
MAX_FAQS = 12
MAX_TAGS = 12
MAX_OPTIONS = 8
MAX_TEST_CASES = 20

ITEM_TYPES = ('mcq', 'mcq_multi', 'numerical', 'subjective', 'coding')
ITEM_TYPE_SET = set(ITEM_TYPES)
STAGE_TYPES = ('quiz', 'coding', 'lab', 'submission')
QUALIFICATION_MODES = ('manual', 'cutoff', 'top_n', 'all')
DIFFICULTIES = ('beginner', 'intermediate', 'advanced', 'all_levels')
MODES = ('online', 'offline', 'hybrid')
CODING_LANGUAGES = ('python', 'cpp', 'java')
FILE_TYPES = ('pdf', 'zip', 'doc', 'docx', 'ppt', 'pptx', 'mp4', 'mov',
              'png', 'jpg', 'jpeg', 'csv', 'ipynb', 'txt')

# ── HTML safety ──────────────────────────────────────────────────────────────
# A deliberately small whitelist. The studio preview and the student page both
# render this HTML, so anything outside the list is stripped server-side rather
# than relying on the client sanitiser alone.
_ALLOWED_TAGS = {
    'h3', 'h4', 'h5', 'p', 'ul', 'ol', 'li', 'strong', 'b', 'em', 'i', 'u',
    'br', 'hr', 'a', 'blockquote', 'code', 'pre', 'span',
    'table', 'thead', 'tbody', 'tr', 'th', 'td',
}
_BLOCK_STRIP = re.compile(
    r'<(script|style|iframe|object|embed|form|input|svg)\b.*?</\1\s*>',
    re.IGNORECASE | re.DOTALL,
)
_TAG = re.compile(r'<\s*(/?)\s*([a-zA-Z0-9]+)((?:\s[^<>]*)?)/?>')
_HREF = re.compile(r'href\s*=\s*(["\'])(.*?)\1', re.IGNORECASE | re.DOTALL)
_FENCE = re.compile(r'^\s*```(?:html)?\s*|\s*```\s*$', re.IGNORECASE)


def clean_html(value, limit=20000):
    """Reduce model HTML to the whitelisted subset, dropping all attributes.

    ``<a>`` keeps a http(s)/mailto ``href`` (plus ``target``/``rel``, which we
    add ourselves) because links are genuinely useful in rules and FAQs.
    """
    if not value:
        return ''
    text = _FENCE.sub('', str(value)).strip()
    text = _BLOCK_STRIP.sub('', text)

    def _replace(match):
        closing, name, attrs = match.group(1), match.group(2).lower(), match.group(3) or ''
        if name not in _ALLOWED_TAGS:
            return ''
        if closing:
            return f'</{name}>'
        if name == 'a':
            href = _HREF.search(attrs)
            url = (href.group(2).strip() if href else '')
            if not re.match(r'^(https?://|mailto:|/)', url, re.IGNORECASE):
                return '<a>'
            safe = _html.escape(url, quote=True)
            return f'<a href="{safe}" target="_blank" rel="noopener noreferrer">'
        return f'<{name}>'

    text = _TAG.sub(_replace, text)
    # Any stray angle bracket that was not a recognised tag is now literal text.
    text = re.sub(r'<(?![/a-zA-Z])', '&lt;', text)
    return text[:limit].strip()


def plain(value, limit=2000):
    if value is None:
        return ''
    text = re.sub(r'<[^>]+>', ' ', str(value))
    text = _html.unescape(text)
    return re.sub(r'\s+', ' ', text).strip()[:limit]


def text_of(value, limit=8000):
    """Question statements keep their line breaks — only fences are stripped."""
    if value is None:
        return ''
    return _FENCE.sub('', str(value)).strip()[:limit]


# ── scalar coercion ──────────────────────────────────────────────────────────

def _choice(value, allowed, default):
    candidate = str(value or '').strip().lower().replace(' ', '_').replace('-', '_')
    return candidate if candidate in allowed else default


def _num(value, default=0.0, low=None, high=None):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number or number in (float('inf'), float('-inf')):
        return default
    if low is not None:
        number = max(low, number)
    if high is not None:
        number = min(high, number)
    return round(number, 4)


def _int(value, default=0, low=None, high=None):
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return default
    if low is not None:
        number = max(low, number)
    if high is not None:
        number = min(high, number)
    return number


def _bool(value, default=False):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ('1', 'true', 'yes', 'y', 'on')
    return default


def _key(raw=None):
    candidate = str(raw or '').strip()
    if candidate and len(candidate) <= 64:
        return candidate
    return uuid.uuid4().hex[:12]


_HEX = re.compile(r'^#[0-9a-fA-F]{6}$')


# ── hackathon ────────────────────────────────────────────────────────────────

def normalize_hackathon(raw):
    raw = raw if isinstance(raw, dict) else {}
    color = str(raw.get('theme_color') or '').strip()
    faqs = []
    for entry in (raw.get('faqs') or [])[:MAX_FAQS]:
        if not isinstance(entry, dict):
            continue
        question = plain(entry.get('question') or entry.get('q'), 300)
        answer = plain(entry.get('answer') or entry.get('a'), 1200)
        if question and answer:
            faqs.append({'question': question, 'answer': answer})

    tags = []
    for tag in (raw.get('tags') or [])[:MAX_TAGS]:
        cleaned = plain(tag, 40).lower()
        if cleaned and cleaned not in tags:
            tags.append(cleaned)

    return {
        'title': plain(raw.get('title'), 200) or 'Untitled Hackathon',
        'tagline': plain(raw.get('tagline'), 250),
        'description': clean_html(raw.get('description')),
        'rules': clean_html(raw.get('rules')),
        'prizes_description': clean_html(raw.get('prizes_description') or raw.get('prizes')),
        'eligibility': clean_html(raw.get('eligibility')),
        'faqs': faqs,
        'tags': tags,
        'difficulty': _choice(raw.get('difficulty'), DIFFICULTIES, 'all_levels'),
        'mode': _choice(raw.get('mode'), MODES, 'online'),
        'theme_color': color if _HEX.match(color) else '#4f46e5',
    }


# ── stages ───────────────────────────────────────────────────────────────────

def normalize_blueprint(raw, cap=MAX_ITEMS_PER_REQUEST):
    entries = []
    for row in (raw or [])[:12]:
        if not isinstance(row, dict):
            continue
        item_type = _choice(row.get('item_type'), ITEM_TYPE_SET, '')
        count = _int(row.get('count'), 0, 0, cap)
        if not item_type or count <= 0:
            continue
        entry = {'item_type': item_type, 'count': count}
        if row.get('marks') is not None:
            entry['marks'] = _num(row.get('marks'), 1, 0, 1000)
        if row.get('negative_marks') is not None:
            entry['negative_marks'] = _num(row.get('negative_marks'), 0, 0, 1000)
        if row.get('difficulty'):
            entry['difficulty'] = plain(row['difficulty'], 20).lower()
        if row.get('note'):
            entry['note'] = plain(row['note'], 300)
        entries.append(entry)
    return entries


def normalize_stage(raw, index=0):
    raw = raw if isinstance(raw, dict) else {}
    stage_type = _choice(raw.get('stage_type'), STAGE_TYPES, 'quiz')
    mode = _choice(raw.get('qualification_mode'), QUALIFICATION_MODES, 'manual')

    file_types = []
    for value in (raw.get('allowed_file_types') or [])[:10]:
        cleaned = plain(value, 10).lower().lstrip('.')
        if cleaned in FILE_TYPES and cleaned not in file_types:
            file_types.append(cleaned)
    if stage_type == 'submission' and not file_types:
        file_types = ['pdf', 'zip', 'mp4']

    stage = {
        'key': _key(raw.get('key')),
        'include': _bool(raw.get('include', True), True),
        'order': index,
        'title': plain(raw.get('title'), 200) or f'Round {index + 1}',
        'description': clean_html(raw.get('description'), 8000),
        'instructions': clean_html(raw.get('instructions'), 8000),
        'stage_type': stage_type,
        'duration_minutes': _int(raw.get('duration_minutes'), 0, 0, 60 * 24 * 30),
        'max_score': _num(raw.get('max_score'), 100, 0, 100000),
        'qualification_mode': mode,
        'cutoff_score': (
            _num(raw.get('cutoff_score'), 0, 0, 100000)
            if raw.get('cutoff_score') is not None else None
        ),
        'top_n': _int(raw.get('top_n'), 0, 0, 100000) or None,
        'submission_instructions': (
            clean_html(raw.get('submission_instructions'), 8000)
            if stage_type == 'submission' else ''
        ),
        'allowed_file_types': file_types,
        'require_repo_url': _bool(raw.get('require_repo_url')),
        'require_demo_url': _bool(raw.get('require_demo_url')),
        'require_video_url': _bool(raw.get('require_video_url')),
        'blueprint': (
            normalize_blueprint(raw.get('blueprint'))
            if stage_type in ('quiz', 'coding') else []
        ),
    }

    # A qualification rule the admin cannot act on is worse than none: fall back
    # to a manual pick rather than silently letting everybody through.
    if mode == 'cutoff' and not stage['cutoff_score']:
        stage['cutoff_score'] = round(stage['max_score'] * 0.4, 2) or None
        if not stage['cutoff_score']:
            stage['qualification_mode'] = 'manual'
    if mode == 'top_n' and not stage['top_n']:
        stage['qualification_mode'] = 'manual'
    return stage


def normalize_stages(raw):
    stages = []
    for index, entry in enumerate((raw or [])[:MAX_STAGES]):
        stage = normalize_stage(entry, index)
        if stage['title']:
            stages.append(stage)
    return stages


# ── items ────────────────────────────────────────────────────────────────────

def _normalize_options(raw, item_type):
    options = []
    for entry in (raw or [])[:MAX_OPTIONS]:
        if isinstance(entry, str):
            entry = {'text': entry}
        if not isinstance(entry, dict):
            continue
        text = text_of(entry.get('text'), 2000)
        if not text:
            continue
        options.append({'text': text, 'is_correct': _bool(entry.get('is_correct'))})

    correct = [i for i, opt in enumerate(options) if opt['is_correct']]
    if item_type == 'mcq' and len(correct) != 1 and options:
        # Single-answer MCQs must have exactly one key: keep the first claimed
        # correct option (or the first option) and clear the rest.
        winner = correct[0] if correct else 0
        for i, opt in enumerate(options):
            opt['is_correct'] = (i == winner)
    return options


def _normalize_test_cases(raw):
    cases = []
    for entry in (raw or [])[:MAX_TEST_CASES]:
        if not isinstance(entry, dict):
            continue
        cases.append({
            'stdin': text_of(entry.get('stdin') or entry.get('input') or '', 20000),
            'expected_output': text_of(
                entry.get('expected_output') or entry.get('output') or '', 20000
            ),
            'points': _int(entry.get('points'), 1, 0, 100),
            'is_sample': _bool(entry.get('is_sample')),
            'explanation': plain(entry.get('explanation'), 500),
        })
    if cases and not any(case['is_sample'] for case in cases):
        cases[0]['is_sample'] = True
    return cases


def normalize_item(raw, index=0, defaults=None):
    raw = raw if isinstance(raw, dict) else {}
    defaults = defaults or {}
    item_type = _choice(raw.get('item_type'), ITEM_TYPE_SET, 'mcq')

    item = {
        'key': _key(raw.get('key')),
        'include': _bool(raw.get('include', True), True),
        'order': index,
        'item_type': item_type,
        'title': plain(raw.get('title'), 200),
        'question_text': text_of(raw.get('question_text') or raw.get('question')),
        'explanation': text_of(raw.get('explanation'), 4000),
        'difficulty': plain(raw.get('difficulty'), 20).lower(),
        'marks': _num(raw.get('marks', defaults.get('marks', 1)), 1, 0, 1000),
        'negative_marks': _num(
            raw.get('negative_marks', defaults.get('negative_marks', 0)), 0, 0, 1000
        ),
        'options': [],
        'numerical_answer': None,
        'numerical_tolerance': 0.01,
        'max_words': None,
        'rubric': '',
        'model_answer': '',
        'allowed_languages': [],
        'starter_code': {},
        'time_limit_ms': 3000,
        'memory_limit_mb': 256,
        'coding_test_cases': [],
    }

    if item_type in ('mcq', 'mcq_multi'):
        item['options'] = _normalize_options(raw.get('options'), item_type)
    elif item_type == 'numerical':
        item['numerical_answer'] = (
            _num(raw.get('numerical_answer'), 0)
            if raw.get('numerical_answer') is not None else None
        )
        item['numerical_tolerance'] = _num(raw.get('numerical_tolerance'), 0.01, 0, 1e6)
    elif item_type == 'subjective':
        item['max_words'] = _int(raw.get('max_words'), 0, 0, 20000) or None
        item['rubric'] = text_of(raw.get('rubric'), 4000)
        item['model_answer'] = text_of(raw.get('model_answer'), 8000)
        item['negative_marks'] = 0  # nothing manual is ever penalised automatically
    elif item_type == 'coding':
        languages = [
            lang for lang in (
                plain(value, 20).lower() for value in (raw.get('allowed_languages') or [])
            ) if lang in CODING_LANGUAGES
        ]
        item['allowed_languages'] = list(dict.fromkeys(languages)) or list(CODING_LANGUAGES)
        starter = raw.get('starter_code')
        if isinstance(starter, dict):
            item['starter_code'] = {
                key: text_of(value, 8000)
                for key, value in starter.items()
                if key in CODING_LANGUAGES and value
            }
        elif isinstance(starter, str) and starter.strip():
            item['starter_code'] = {item['allowed_languages'][0]: text_of(starter, 8000)}
        item['time_limit_ms'] = _int(raw.get('time_limit_ms'), 3000, 500, 30000)
        item['memory_limit_mb'] = _int(raw.get('memory_limit_mb'), 256, 32, 2048)
        item['coding_test_cases'] = _normalize_test_cases(raw.get('coding_test_cases'))
        item['negative_marks'] = 0

    item['issues'] = item_issues(item)
    return item


def item_issues(item):
    """Human-readable problems the reviewer should see before applying."""
    problems = []
    if not item['question_text']:
        problems.append('No question text.')
    if item['item_type'] in ('mcq', 'mcq_multi'):
        if len(item['options']) < 2:
            problems.append('Needs at least two options.')
        correct = sum(1 for opt in item['options'] if opt['is_correct'])
        if correct == 0:
            problems.append('No correct option marked.')
        if item['item_type'] == 'mcq_multi' and correct < 2:
            problems.append('Multi-answer questions need two or more correct options.')
        if item['item_type'] == 'mcq_multi' and correct == len(item['options']):
            problems.append('Every option is marked correct.')
    if item['item_type'] == 'numerical' and item['numerical_answer'] is None:
        problems.append('No numerical answer.')
    if item['item_type'] == 'coding':
        if len(item['coding_test_cases']) < 2:
            problems.append('Needs at least two test cases.')
        if not any(case['expected_output'] for case in item['coding_test_cases']):
            problems.append('Test cases have no expected output.')
    if item['item_type'] == 'subjective' and not item['rubric']:
        problems.append('No grading rubric.')
    return problems


def normalize_items(raw, defaults=None):
    items = []
    for index, entry in enumerate((raw or [])[:MAX_ITEMS_PER_STAGE]):
        items.append(normalize_item(entry, index, defaults))
    return items


def merge_items(existing, incoming, defaults=None):
    """Append a fresh batch, skipping near-duplicate stems."""
    merged = list(existing or [])
    seen = {_fingerprint(item['question_text']) for item in merged}
    for entry in incoming or []:
        item = entry if 'issues' in (entry or {}) else normalize_item(entry, 0, defaults)
        fingerprint = _fingerprint(item['question_text'])
        if not fingerprint or fingerprint in seen:
            continue
        seen.add(fingerprint)
        item['order'] = len(merged)
        merged.append(item)
    return merged[:MAX_ITEMS_PER_STAGE]


def _fingerprint(text):
    return re.sub(r'[^a-z0-9]+', '', plain(text, 400).lower())[:180]


# ── top-level draft ──────────────────────────────────────────────────────────

def normalize_draft(raw, kind, options=None):
    """Normalise whatever the model returned into this job kind's draft shape."""
    raw = raw if isinstance(raw, dict) else {}
    options = options or {}

    if kind == 'stage_content':
        items = raw.get('items')
        if items is None and isinstance(raw.get('questions'), list):
            items = raw['questions']
        draft = {'kind': kind, 'items': normalize_items(items)}
    elif kind == 'stages':
        draft = {'kind': kind, 'stages': normalize_stages(raw.get('stages'))}
    else:
        draft = {
            'kind': 'event',
            'hackathon': normalize_hackathon(raw.get('hackathon') or raw),
            'stages': normalize_stages(raw.get('stages')),
        }
    draft['stats'] = draft_summary(draft)
    return draft


def draft_summary(draft):
    draft = draft if isinstance(draft, dict) else {}
    items = draft.get('items') or []
    stages = draft.get('stages') or []
    by_type = {}
    for item in items:
        by_type[item.get('item_type', 'mcq')] = by_type.get(item.get('item_type', 'mcq'), 0) + 1
    return {
        'kind': draft.get('kind') or '',
        'title': (draft.get('hackathon') or {}).get('title', ''),
        'stages': len(stages),
        'stage_types': [stage.get('stage_type') for stage in stages],
        'items': len(items),
        'items_by_type': by_type,
        'total_marks': round(sum(float(item.get('marks') or 0) for item in items), 2),
        'flagged': sum(1 for item in items if item.get('issues')),
        'planned_items': sum(
            entry.get('count', 0)
            for stage in stages for entry in (stage.get('blueprint') or [])
        ),
    }
