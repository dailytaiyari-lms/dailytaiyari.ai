"""Validate and normalise an AI-generated notebook draft.

The model's JSON is a *suggestion*. Everything here defends against missing
keys, wrong types, bad roles, dangling tests and truncated output, and produces:

* a canonical ``draft`` dict (safe to store on the job and re-serialise), and
* on apply, a real nbformat ``template_json`` (via :func:`draft_to_template`)
  plus the list of test rows.

It never trusts points/roles/grade_ids blindly — an answer cell with no grade_id
is downgraded to editable, a test pointing at no answer cell is dropped, etc.
"""
from notebooks.nbformat_utils import (
    CELL_ROLES, KNOWN_PACKAGES, META_KEY, NBFORMAT, NBFORMAT_MINOR,
    ROLE_ANSWER, ROLE_EDITABLE, ROLE_READONLY, normalize_notebook,
)

# Reused by prompts.py so the model is told exactly what it may import.
KNOWN_PACKAGES_HINT = ', '.join(KNOWN_PACKAGES)

DIFFICULTIES = ('easy', 'medium', 'hard')
MAX_CELLS = 40
MAX_TESTS = 40


class DraftError(Exception):
    """The model's payload could not be turned into a usable notebook draft."""


def _clean_str(value, limit=None):
    text = '' if value is None else str(value)
    text = text.replace('\x00', '').strip()
    return text[:limit] if limit else text


def _source_text(value):
    if isinstance(value, list):
        return ''.join(str(part) for part in value)
    return '' if value is None else str(value)


def _int(value, default, lo=None, hi=None):
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = default
    if lo is not None:
        n = max(lo, n)
    if hi is not None:
        n = min(hi, n)
    return n


def _packages(value):
    out = []
    for item in value or []:
        name = _clean_str(item)
        if not name or not all(ch.isalnum() or ch in '-_.' for ch in name):
            continue
        if name not in out:
            out.append(name)
    return out


def _normalize_cell(raw):
    if not isinstance(raw, dict):
        return None
    cell_type = raw.get('cell_type')
    if cell_type not in ('markdown', 'code'):
        # Coerce anything unexpected to markdown prose rather than dropping it.
        cell_type = 'markdown'

    role = raw.get('role')
    if role not in CELL_ROLES:
        role = ROLE_EDITABLE if cell_type == 'code' else ROLE_READONLY
    if role == ROLE_ANSWER and cell_type != 'code':
        role = ROLE_READONLY

    grade_id = _clean_str(raw.get('grade_id'), 100)
    points = _int(raw.get('points'), 0, lo=0, hi=1000)
    source = _source_text(raw.get('source'))

    cell = {
        'cell_type': cell_type,
        'role': role,
        'grade_id': grade_id if role == ROLE_ANSWER else '',
        'points': points if role == ROLE_ANSWER else 0,
        'source': source,
    }
    # An answer cell with no grade_id can't be graded; make it plain scratch.
    if cell['role'] == ROLE_ANSWER and not cell['grade_id']:
        cell['role'] = ROLE_EDITABLE
        cell['points'] = 0
    return cell


def _normalize_test(raw, valid_grade_ids):
    if not isinstance(raw, dict):
        return None
    grade_id = _clean_str(raw.get('grade_id'), 100)
    source = _source_text(raw.get('source')).strip()
    if not source:
        return None
    # Drop tests that reference an answer cell that doesn't exist.
    if grade_id and grade_id not in valid_grade_ids:
        grade_id = ''
    name = _clean_str(raw.get('name'), 300) or 'Check'
    return {
        'grade_id': grade_id,
        'name': name,
        'source': source,
        'points': _int(raw.get('points'), 1, lo=1, hi=1000),
        'is_hidden': bool(raw.get('is_hidden', True)),
        'failure_hint': _clean_str(raw.get('failure_hint'), 500),
    }


def normalize_draft(payload, *, graded=True):
    """Turn raw model JSON into a canonical, storable draft dict."""
    if not isinstance(payload, dict):
        raise DraftError('The model did not return a notebook object.')

    raw_cells = payload.get('cells')
    if not isinstance(raw_cells, list) or not raw_cells:
        raise DraftError('The model returned a notebook with no cells.')

    cells = []
    for raw in raw_cells[:MAX_CELLS]:
        cell = _normalize_cell(raw)
        if cell is not None:
            cells.append(cell)
    if not cells:
        raise DraftError('None of the generated cells were usable.')

    answer_ids = [c['grade_id'] for c in cells if c['role'] == ROLE_ANSWER and c['grade_id']]
    valid_ids = set(answer_ids)

    tests = []
    for raw in (payload.get('tests') or [])[:MAX_TESTS]:
        test = _normalize_test(raw, valid_ids)
        if test is not None:
            tests.append(test)

    if graded:
        if not answer_ids:
            raise DraftError(
                'A graded notebook needs at least one answer cell. Try regenerating '
                'or switch the request to an ungraded notebook.'
            )
        if not tests:
            raise DraftError(
                'The model produced no autograder tests. Try regenerating.'
            )

    difficulty = payload.get('difficulty')
    if difficulty not in DIFFICULTIES:
        difficulty = 'easy'

    total_points = sum(t['points'] for t in tests)
    max_marks = _int(payload.get('max_marks'), total_points or 10, lo=0, hi=100000)

    packages = _packages(payload.get('packages'))

    return {
        'title': _clean_str(payload.get('title'), 500) or 'Untitled notebook',
        'description': _clean_str(payload.get('description'), 5000),
        'difficulty': difficulty,
        'estimated_time_minutes': _int(payload.get('estimated_time_minutes'), 25, lo=1, hi=1000),
        'packages': packages,
        'max_marks': max_marks,
        'cells': cells,
        'tests': tests,
    }


def draft_to_template(draft):
    """Build a normalised nbformat v4 template_json from a draft's cells."""
    nb_cells = []
    for cell in draft.get('cells') or []:
        dt = {'role': cell.get('role') or ROLE_READONLY}
        if dt['role'] == ROLE_ANSWER and cell.get('grade_id'):
            dt['grade_id'] = cell['grade_id']
        if cell.get('points'):
            dt['points'] = cell['points']
        nb_cells.append({
            'cell_type': cell.get('cell_type') or 'markdown',
            'metadata': {META_KEY: dt},
            'source': cell.get('source') or '',
        })
    document = {
        'cells': nb_cells,
        'metadata': {
            'kernelspec': {'name': 'python3', 'display_name': 'Python 3', 'language': 'python'},
            'language_info': {'name': 'python', 'version': '3.11'},
        },
        'nbformat': NBFORMAT,
        'nbformat_minor': NBFORMAT_MINOR,
    }
    # Run it through the canonical normaliser so it is byte-for-byte what the
    # authoring API would have produced.
    return normalize_notebook(document)


def draft_summary(draft):
    """A compact overview for list rows and the preview header."""
    draft = draft or {}
    cells = draft.get('cells') or []
    tests = draft.get('tests') or []
    return {
        'title': draft.get('title') or '',
        'difficulty': draft.get('difficulty') or '',
        'cells': len(cells),
        'code_cells': sum(1 for c in cells if c.get('cell_type') == 'code'),
        'answer_cells': sum(1 for c in cells if c.get('role') == ROLE_ANSWER),
        'tests': len(tests),
        'hidden_tests': sum(1 for t in tests if t.get('is_hidden')),
        'total_points': sum(int(t.get('points') or 0) for t in tests),
        'max_marks': draft.get('max_marks') or 0,
        'packages': draft.get('packages') or [],
    }
