"""Jupyter/Colab-style notebook helpers.

Notebooks are stored as standard nbformat v4 JSON so admins can import a real
``.ipynb`` exported from Jupyter, Colab or Kaggle and students can download
their work back into those tools.

DailyTaiyari-specific authoring metadata lives under each cell's
``metadata.dailytaiyari`` key, which nbformat preserves and other tools ignore:

    {
      "role": "readonly" | "editable" | "answer",
      "grade_id": "q1",          # links an answer cell to its NotebookTest(s)
      "points": 5                # display only; authoritative points live on the test
    }

Roles:
  * ``readonly`` — shown but not editable (setup code, imports, data loading)
  * ``editable`` — free scratch space; never graded
  * ``answer``   — the student's solution for ``grade_id``; graded
"""
import copy
import json

NBFORMAT = 4
NBFORMAT_MINOR = 5

META_KEY = 'dailytaiyari'

ROLE_READONLY = 'readonly'
ROLE_EDITABLE = 'editable'
ROLE_ANSWER = 'answer'
CELL_ROLES = (ROLE_READONLY, ROLE_EDITABLE, ROLE_ANSWER)

CELL_TYPES = ('code', 'markdown', 'raw')

# Pyodide ships these as prebuilt wheels; anything else must be a pure-Python
# wheel installable from PyPI via micropip at runtime.
DEFAULT_PACKAGES = ['numpy', 'pandas', 'matplotlib', 'scikit-learn']
KNOWN_PACKAGES = [
    'numpy', 'pandas', 'scipy', 'scikit-learn', 'matplotlib', 'sympy',
    'statsmodels', 'networkx', 'pillow', 'regex', 'nltk', 'seaborn',
    'scikit-image', 'opencv-python', 'xgboost', 'joblib', 'pyarrow',
    'beautifulsoup4', 'lxml', 'requests', 'micropip',
]


class NotebookFormatError(ValueError):
    """Raised when a supplied notebook document is not usable."""


def empty_notebook():
    """A minimal, valid notebook document."""
    return {
        'cells': [],
        'metadata': {
            'kernelspec': {
                'name': 'python3', 'display_name': 'Python 3', 'language': 'python',
            },
            'language_info': {'name': 'python', 'version': '3.11'},
        },
        'nbformat': NBFORMAT,
        'nbformat_minor': NBFORMAT_MINOR,
    }


def _source_to_text(source):
    """nbformat allows source as a string or a list of lines; normalize to text."""
    if isinstance(source, list):
        return ''.join(str(part) for part in source)
    if source is None:
        return ''
    return str(source)


def cell_meta(cell):
    """The DailyTaiyari authoring metadata for a cell (never None)."""
    meta = (cell.get('metadata') or {}).get(META_KEY)
    return meta if isinstance(meta, dict) else {}


def cell_role(cell):
    role = cell_meta(cell).get('role')
    if role in CELL_ROLES:
        return role
    return ROLE_EDITABLE if cell.get('cell_type') == 'code' else ROLE_READONLY


def cell_grade_id(cell):
    grade_id = cell_meta(cell).get('grade_id')
    return str(grade_id).strip() if grade_id else ''


def normalize_notebook(document, *, strip_outputs=False):
    """Validate and normalize a notebook document into canonical nbformat v4.

    Accepts a dict or a JSON string. Unknown top-level keys are dropped, cell
    sources are flattened to plain strings, and DailyTaiyari cell metadata is
    coerced into a valid shape. Raises NotebookFormatError on anything that
    isn't a usable notebook.
    """
    if isinstance(document, (str, bytes)):
        try:
            document = json.loads(document)
        except (ValueError, TypeError) as exc:
            raise NotebookFormatError(f'Not valid notebook JSON: {exc}')

    if document in (None, '', {}, []):
        return empty_notebook()
    if not isinstance(document, dict):
        raise NotebookFormatError('A notebook must be a JSON object.')

    raw_cells = document.get('cells')
    if raw_cells is None:
        raw_cells = []
    if not isinstance(raw_cells, list):
        raise NotebookFormatError('"cells" must be a list.')

    notebook = empty_notebook()
    incoming_meta = document.get('metadata')
    if isinstance(incoming_meta, dict):
        merged = copy.deepcopy(notebook['metadata'])
        merged.update({k: v for k, v in incoming_meta.items() if k != 'widgets'})
        notebook['metadata'] = merged

    cells = []
    for index, raw in enumerate(raw_cells):
        if not isinstance(raw, dict):
            raise NotebookFormatError(f'Cell {index + 1} is not an object.')
        cell_type = raw.get('cell_type')
        if cell_type not in CELL_TYPES:
            raise NotebookFormatError(
                f'Cell {index + 1} has unsupported type "{cell_type}".'
            )

        meta = raw.get('metadata')
        meta = copy.deepcopy(meta) if isinstance(meta, dict) else {}
        dt_meta = meta.get(META_KEY)
        dt_meta = dict(dt_meta) if isinstance(dt_meta, dict) else {}

        role = dt_meta.get('role')
        if role not in CELL_ROLES:
            # Unmarked cells default by type: prose is instructions (locked),
            # code is scratch the student may edit. An author can always
            # override either explicitly.
            role = ROLE_EDITABLE if cell_type == 'code' else ROLE_READONLY
        # Only code cells can be graded answers.
        if role == ROLE_ANSWER and cell_type != 'code':
            role = ROLE_READONLY
        clean_meta = {'role': role}
        grade_id = str(dt_meta.get('grade_id') or '').strip()
        if role == ROLE_ANSWER and grade_id:
            clean_meta['grade_id'] = grade_id
        points = dt_meta.get('points')
        if isinstance(points, (int, float)) and points >= 0:
            clean_meta['points'] = points
        meta[META_KEY] = clean_meta

        cell = {
            'cell_type': cell_type,
            'metadata': meta,
            'source': _source_to_text(raw.get('source')),
        }
        if cell_type == 'code':
            cell['execution_count'] = None if strip_outputs else raw.get('execution_count')
            outputs = [] if strip_outputs else raw.get('outputs')
            cell['outputs'] = outputs if isinstance(outputs, list) else []
        cells.append(cell)

    notebook['cells'] = cells
    return notebook


def strip_outputs(document):
    """A copy of the notebook with all outputs and execution counts cleared."""
    return normalize_notebook(document, strip_outputs=True)


def code_sources(document):
    """Ordered list of (index, role, grade_id, source) for every code cell."""
    out = []
    for index, cell in enumerate((document or {}).get('cells') or []):
        if cell.get('cell_type') != 'code':
            continue
        out.append({
            'index': index,
            'role': cell_role(cell),
            'grade_id': cell_grade_id(cell),
            'source': _source_to_text(cell.get('source')),
        })
    return out


def answer_grade_ids(document):
    """Every grade_id declared by an answer cell, in document order (unique)."""
    seen = []
    for cell in code_sources(document):
        gid = cell['grade_id']
        if cell['role'] == ROLE_ANSWER and gid and gid not in seen:
            seen.append(gid)
    return seen


def merge_student_notebook(template, submitted):
    """Rebuild a submission from the template, taking only student-owned cells.

    Guards against a student rewriting locked setup cells (or deleting them) to
    game the grader: the authoritative structure and every ``readonly`` cell
    come from the template, while ``editable`` and ``answer`` cell sources come
    from the submission, matched by position among non-readonly code cells.

    Extra trailing cells the student added are preserved as editable scratch so
    their exploratory work isn't silently discarded, but they are appended after
    the template cells and can never overwrite locked setup.
    """
    template = normalize_notebook(template)
    submitted = normalize_notebook(submitted)

    # Map the student's editable/answer cells by grade_id first (robust to
    # reordering), then fall back to positional matching per cell type for
    # ungraded cells (so a markdown answer can never land in a code slot).
    by_grade_id = {}
    positional = {}
    for cell in submitted.get('cells') or []:
        role = cell_role(cell)
        if role == ROLE_READONLY:
            continue
        gid = cell_grade_id(cell)
        if role == ROLE_ANSWER and gid:
            by_grade_id.setdefault(gid, cell)
        else:
            positional.setdefault(cell.get('cell_type'), []).append(cell)

    merged = copy.deepcopy(template)
    consumed = {}
    for cell in merged.get('cells') or []:
        role = cell_role(cell)
        if role == ROLE_READONLY:
            continue
        cell_type = cell.get('cell_type')
        gid = cell_grade_id(cell)
        source_cell = None
        if role == ROLE_ANSWER and gid and gid in by_grade_id:
            source_cell = by_grade_id.pop(gid)
        else:
            queue = positional.get(cell_type) or []
            index = consumed.get(cell_type, 0)
            if index < len(queue):
                source_cell = queue[index]
                consumed[cell_type] = index + 1
        if source_cell is not None:
            cell['source'] = _source_to_text(source_cell.get('source'))
            if cell_type == 'code':
                outputs = source_cell.get('outputs')
                cell['outputs'] = outputs if isinstance(outputs, list) else []
                cell['execution_count'] = source_cell.get('execution_count')

    # Preserve any leftover scratch cells the student added.
    for cell_type, queue in positional.items():
        for cell in queue[consumed.get(cell_type, 0):]:
            extra = copy.deepcopy(cell)
            extra.setdefault('metadata', {})[META_KEY] = {'role': ROLE_EDITABLE}
            merged['cells'].append(extra)

    return merged
