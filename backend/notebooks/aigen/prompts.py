"""Prompts for the AI Notebook Builder.

The model is asked to return a single JSON object describing a full, runnable
notebook: an ordered list of cells (markdown prose + Python code, each tagged
with a DailyTaiyari role) plus a set of autograder tests. The shape is
deliberately small and strict so :mod:`notebooks.aigen.schema` can normalise it
into a real nbformat template and NotebookTest rows.

Everything the notebook uses must run in **Pyodide** (CPython on WebAssembly):
numpy, pandas, matplotlib and scikit-learn are available as prebuilt wheels,
plus the rest of ``KNOWN_PACKAGES``. No file/network I/O, no threads, no
system calls.
"""
from .schema import KNOWN_PACKAGES_HINT

NOTEBOOK_SYSTEM = f"""\
You are an expert computer-science and data-science instructor who authors
interactive, auto-graded Jupyter notebooks for students learning on a
browser-based Python kernel (Pyodide / CPython on WebAssembly).

You ALWAYS reply with a single JSON object and nothing else — no prose, no
markdown fences. The JSON object has exactly these keys:

{{
  "title": string,                 // concise, specific
  "description": string,           // 1-3 sentence HTML brief shown above the notebook
  "difficulty": "easy"|"medium"|"hard",
  "estimated_time_minutes": integer,
  "packages": [string],            // pip names actually imported; subset of the allowed list
  "max_marks": integer,            // total marks for the notebook
  "cells": [
    {{
      "cell_type": "markdown"|"code",
      "role": "readonly"|"editable"|"answer",
      "grade_id": string,          // REQUIRED and unique for every answer cell; else ""
      "points": integer,           // display hint for answer cells; else 0
      "source": string             // full cell text (real, runnable code for code cells)
    }}
  ],
  "tests": [
    {{
      "grade_id": string,          // must match an answer cell's grade_id
      "name": string,              // short human label
      "source": string,            // Python that raises/asserts to FAIL; passes silently
      "points": integer,           // > 0
      "is_hidden": boolean,        // hidden tests are the real grade; visible ones self-check
      "failure_hint": string       // shown to the student when this test fails
    }}
  ]
}}

Hard rules:
- Cell roles: "readonly" = locked setup/instructions (imports, data, scaffolding);
  "answer" = a CODE cell the student must complete (this is what gets graded);
  "editable" = free scratch. Only code cells may be "answer".
- Every notebook MUST begin with a markdown intro (readonly) and a readonly
  setup code cell that imports libraries and prepares any data DETERMINISTICALLY
  (always pass random_state / a fixed seed) so the browser and the server grader
  agree on the numbers.
- Answer cells must contain a real, self-contained stub: a function signature or
  clearly-marked TODO with `raise NotImplementedError`, NOT the full solution.
  Reference the exact variable/function name the tests will check.
- Tests run in the SAME kernel namespace AFTER every cell has executed, so they
  can read the student's variables and functions. A test passes when it runs
  without raising; use `assert` with a helpful message. Provide at least one
  VISIBLE self-check and at least one HIDDEN test per answer cell.
- Prefer numeric/behavioural checks with tolerances (e.g. abs(a-b) < 1e-6) over
  brittle string comparisons.
- Only use packages from this allowed set: {KNOWN_PACKAGES_HINT}. No file or
  network access.
- The sum of all test points should equal max_marks.
"""


def _opt(options, key, default=None):
    value = (options or {}).get(key)
    return value if value not in (None, '') else default


def notebook_user_prompt(*, brief, options, topic, subject_name='', course_name=''):
    """Build the user turn for a fresh notebook generation."""
    options = options or {}
    graded = _opt(options, 'graded', True)
    difficulty = _opt(options, 'difficulty', 'easy')
    answer_cells = _opt(options, 'answer_cells', 2)
    packages = _opt(options, 'packages') or []
    language = _opt(options, 'language', 'English')
    extra = _opt(options, 'notes', '')

    lines = [
        'Author one interactive notebook for the following placement.',
        '',
        f'Course: {course_name or "—"}',
        f'Subject: {subject_name or "—"}',
        f'Topic: {getattr(topic, "name", "") or "—"}',
    ]
    topic_desc = (getattr(topic, 'description', '') or '').strip()
    if topic_desc:
        lines.append(f'Topic notes (for context): {topic_desc[:1500]}')

    lines += [
        '',
        f'What to build: {brief.strip() or "an instructive, hands-on notebook for this topic"}',
        '',
        f'Difficulty: {difficulty}.',
        f'Language for prose: {language}.',
    ]
    if graded:
        lines.append(
            f'Make it GRADED: include about {answer_cells} answer cell(s), each with a '
            'unique grade_id, and matching visible + hidden autograder tests.'
        )
    else:
        lines.append(
            'Make it an ungraded, exploratory notebook: no answer cells and no tests '
            '(use empty "cells" roles of readonly/editable and an empty "tests" list).'
        )
    if packages:
        lines.append(f'Prefer these packages if relevant: {", ".join(map(str, packages))}.')
    if extra:
        lines.append(f'Extra instructions: {extra}')

    lines += [
        '',
        'Return ONLY the JSON object described in the system message.',
    ]
    return '\n'.join(lines)


def refine_user_prompt(*, draft, instruction):
    """Build the user turn for refining an existing draft in place."""
    import json

    current = json.dumps(draft, ensure_ascii=False)[:12000]
    return (
        'Here is the current notebook draft as JSON:\n\n'
        f'{current}\n\n'
        'Revise it according to this instruction, keeping the same JSON shape and '
        'all the hard rules (deterministic setup, real stubs in answer cells, '
        'visible + hidden tests whose points sum to max_marks):\n\n'
        f'{instruction.strip()}\n\n'
        'Return ONLY the complete updated JSON object.'
    )
