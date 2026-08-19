"""Prompts for the AI Mock Test Builder.

Two jobs, one shape rule: **JSON only, matching the schema in the prompt**.
Everything the model returns is re-validated by :mod:`mockgen.schema`, so these
prompts optimise for *quality of assessment* rather than defensive formatting —
the parser handles the rest.

The house style for a good paper, encoded below: questions that discriminate
between a learner who understands and one who memorised, distractors that are
plausible rather than silly, and an explanation for every single item.
"""
from __future__ import annotations

JSON_RULES = """
OUTPUT RULES (strict):
- Reply with ONE JSON object and nothing else. No prose, no markdown, no ``` fences.
- Use the exact keys shown in the schema. Omit keys you have no value for.
- Question text may use inline markdown (**bold**, `code`, LaTeX like $x^2$) but never HTML tags.
- Never invent placeholder text such as "TBD", "Question 1" or "Lorem ipsum".
""".strip()


ITEM_SCHEMA = """
Every question is one object in "items". The keys depend on "item_type":

  MCQ (exactly one correct option):
  {"key": "q1", "item_type": "mcq", "section": 0, "question_text": "...",
   "options": [{"text": "...", "is_correct": true}, {"text": "...", "is_correct": false}],
   "explanation": "Why the right answer is right AND why the others are wrong.",
   "marks": 4, "negative_marks": 1, "difficulty": "easy|medium|hard",
   "concepts": ["primary concept", "secondary concept (only if genuinely tested)"],
   "cognitive_type": "recall|application|multi_concept"}

  "concepts" lists 1-4 short concept names the question actually tests, most
  central first — reuse the syllabus topic names where they fit. Use
  "cognitive_type": "recall" for remembering a fact/definition, "application"
  for applying one concept, and "multi_concept" when solving genuinely requires
  combining two or more concepts (then list each in "concepts").

  MCQ multi (two or more correct options):
  {"key": "q2", "item_type": "mcq_multi", ... same keys, several options with "is_correct": true}

  Numerical (a single number the learner types in):
  {"key": "q3", "item_type": "numerical", "question_text": "...",
   "numerical_answer": 12.5, "numerical_tolerance": 0.01, "unit": "m/s",
   "explanation": "Full worked solution.", "marks": 4, "negative_marks": 0}

  Subjective (written answer, graded by a human):
  {"key": "q4", "item_type": "subjective", "question_text": "...",
   "max_words": 250, "rubric": "How to award each mark, band by band.",
   "model_answer": "A full-marks answer.", "marks": 10}

  Coding (auto-graded by running the learner's program):
  {"key": "q5", "item_type": "coding", "question_text": "Problem statement with input/output format and constraints.",
   "allowed_languages": ["python", "cpp", "java"],
   "starter_code": {"python": "def solve():\\n    pass"},
   "coding_test_cases": [
     {"stdin": "3\\n1 2 3", "expected_output": "6", "points": 1, "is_sample": true,
      "explanation": "Sum of the three numbers."}
   ],
   "time_limit_ms": 3000, "memory_limit_mb": 256,
   "explanation": "The intended approach and its complexity.", "marks": 20}
""".strip()


QUALITY_RULES = """
QUALITY RULES:
- Each question must test one clear idea, and be answerable from the stated syllabus alone.
- Distractors must be *plausible*: each one should correspond to a specific, common mistake.
- Never write "All of the above", "None of the above" or options that overlap in meaning.
- Vary the position of the correct option; do not favour any one slot.
- Numerical answers must be exact and reproducible from the numbers in the question.
- Coding test cases must be byte-exact: the expected output is compared literally,
  so include no trailing prose, and cover the edge cases (empty, minimum, maximum).
- Subjective questions need a rubric an examiner can apply without knowing your intent.
- Every question needs an explanation. It is what the learner reads after the test.
- Do not repeat a question, a stem, or the same numbers in a different disguise.
""".strip()


MOCK_SYSTEM = f"""
You are a senior assessment designer for an Indian online learning platform. You
write exam papers that are fair, unambiguous and genuinely discriminating — the
kind a serious institute would put in front of paying students.

{JSON_RULES}

SCHEMA:
{{
  "test": {{
    "title": "Paper title",
    "description": "2-4 sentences: what this paper covers and how to attempt it.",
    "duration_minutes": 60,
    "negative_marking": true
  }},
  "sections": [
    {{"name": "Section A — Physics", "description": "20 single-answer MCQs"}}
  ],
  "items": [ ... ]
}}

{ITEM_SCHEMA}

{QUALITY_RULES}
""".strip()


MODIFY_SYSTEM = f"""
You are a senior assessment designer revising an existing exam paper for an
Indian online learning platform. You make exactly the change that was asked for
and nothing else: untouched questions come back byte-identical, with the same
"key", so the admin can see precisely what moved.

{JSON_RULES}

SCHEMA: identical to the paper you are given — a "test" object, a "sections"
list and an "items" list.

{ITEM_SCHEMA}

{QUALITY_RULES}

REVISION RULES:
- Return the COMPLETE paper, not a diff: every question that should survive must
  appear in "items", keeping its original "key".
- A question you rewrite keeps its "key". A question you add gets a new one.
  A question you remove is simply absent.
- Never change the marking scheme, duration or section structure unless the
  instruction asks you to.
""".strip()


def _blueprint_lines(options):
    """Render the admin's per-type question plan as instructions."""
    lines = []
    for entry in options.get('blueprint') or []:
        if not isinstance(entry, dict):
            continue
        count = entry.get('count')
        item_type = entry.get('item_type')
        if not count or not item_type:
            continue
        parts = [f'- {count} × {item_type}']
        if entry.get('marks') is not None:
            parts.append(f'{entry["marks"]} marks each')
        if entry.get('negative_marks'):
            parts.append(f'{entry["negative_marks"]} negative')
        if entry.get('difficulty'):
            parts.append(f'{entry["difficulty"]} difficulty')
        if entry.get('section') is not None:
            parts.append(f'in section {entry["section"]}')
        if entry.get('note'):
            parts.append(str(entry['note'])[:200])
        lines.append(', '.join(parts))
    return lines


def _section_lines(options):
    lines = []
    for index, entry in enumerate(options.get('sections') or []):
        if isinstance(entry, str):
            entry = {'name': entry}
        if not isinstance(entry, dict):
            continue
        name = entry.get('name') or f'Section {index + 1}'
        description = entry.get('description') or ''
        lines.append(f'- index {index}: {name}{f" — {description}" if description else ""}')
    return lines


def mock_user_prompt(*, brief, options, syllabus_text='', batch=None, already_written=None):
    """The admin's brief plus the blueprint, for one batch of questions.

    ``batch`` narrows the request to a slice of the blueprint so a 60-question
    paper is written in several sane requests instead of one that runs out of
    tokens. ``already_written`` is the stems produced so far, so later batches
    do not repeat them.
    """
    options = options or {}
    parts = []

    if brief:
        parts.append(f'BRIEF FROM THE ADMIN:\n"""\n{brief.strip()}\n"""')

    meta = []
    if options.get('title'):
        meta.append(f'- Working title: {options["title"]}')
    if options.get('duration_minutes'):
        meta.append(f'- Duration: {options["duration_minutes"]} minutes')
    if options.get('audience'):
        meta.append(f'- Who is sitting it: {options["audience"]}')
    if options.get('difficulty'):
        meta.append(f'- Overall difficulty: {options["difficulty"]}')
    if options.get('language'):
        meta.append(f'- Write everything in: {options["language"]}')
    meta.append(
        '- Negative marking is '
        + ('ON — set a sensible negative_marks on objective questions.'
           if options.get('negative_marking', True)
           else 'OFF — set negative_marks to 0 everywhere.')
    )
    if meta:
        parts.append('PAPER SETTINGS:\n' + '\n'.join(meta))

    sections = _section_lines(options)
    if sections:
        parts.append(
            'SECTIONS (use these exact indices in each item\'s "section"):\n'
            + '\n'.join(sections)
        )

    plan = _blueprint_lines(batch if batch is not None else options)
    if plan:
        parts.append('WRITE EXACTLY THIS, NO MORE AND NO LESS:\n' + '\n'.join(plan))

    if options.get('coding_languages'):
        parts.append(
            'Coding questions must accept these languages: '
            + ', '.join(options['coding_languages'])
        )

    if syllabus_text:
        parts.append(
            'SYLLABUS TO EXAMINE (stay strictly inside it):\n' + syllabus_text[:8000]
        )

    if already_written:
        parts.append(
            'These questions are already in the paper. Do NOT repeat or rephrase '
            'any of them:\n' + '\n'.join(f'- {stem[:160]}' for stem in already_written[:60])
        )

    if batch is not None:
        parts.append(
            'Return ONLY the "items" for this batch (plus "test" and "sections" '
            'if you have them); the batches are merged into one paper afterwards.'
        )

    return '\n\n'.join(parts)


#: What each modify intent is allowed to do. The admin picks one in the studio,
#: which is far more reliable than hoping a free-form sentence implies scope.
INTENT_RULES = {
    'improve': (
        'INTENT — IMPROVE THE EXISTING QUESTIONS:\n'
        '- Do NOT add a question and do NOT remove one. The paper must come back '
        'with exactly the same number of items and the same keys.\n'
        '- Sharpen wording, fix ambiguity, strengthen weak distractors, and make '
        'every explanation complete.\n'
        '- Keep each question testing the same concept at the same difficulty.'
    ),
    'add': (
        'INTENT — ADD NEW QUESTIONS:\n'
        '- Every existing question must come back UNCHANGED, with its original "key".\n'
        '- Append the new questions after them, each with a new key (n1, n2, …).\n'
        '- New questions must not duplicate or rephrase anything already in the paper, '
        'and must match the style, level and marking of what is there.'
    ),
    'replace': (
        'INTENT — REPLACE QUESTIONS:\n'
        '- Replace only the questions named below (or in the instruction). A replaced '
        'question keeps its original "key" so it is updated in place, not duplicated.\n'
        '- Every other question comes back byte-identical.\n'
        '- A replacement keeps the same marks, negative marks, section and item_type '
        'unless the instruction says otherwise.'
    ),
    'difficulty': (
        'INTENT — RETUNE DIFFICULTY:\n'
        '- Keep the same number of questions, the same keys and the same concepts.\n'
        '- Change only how demanding each question is, and update the explanation to match.'
    ),
}


def _target_lines(targets):
    """Name the questions the admin ticked, so scope is unambiguous."""
    lines = []
    for entry in targets or []:
        if isinstance(entry, dict):
            key = entry.get('key')
            text = (entry.get('question_text') or '').strip()
        else:
            key, text = entry, ''
        if not key:
            continue
        lines.append(f'- key "{key}"' + (f': {text[:160]}' if text else ''))
    return lines


def modify_user_prompt(
    *, instruction, current_json, brief='', intent='', targets=None, add_plan=None,
):
    """Revise an existing paper with the admin's instruction applied.

    ``intent`` narrows what the model is permitted to touch, ``targets`` names
    the exact questions it may rewrite, and ``add_plan`` is a blueprint for the
    questions to append. All three come from explicit choices in the studio,
    which keeps a vague instruction from quietly rewriting a whole paper.
    """
    parts = [
        'THE PAPER AS IT STANDS. This is the only source of truth — the revision '
        'must stay on its topics, level and style:\n' + current_json,
    ]

    rule = INTENT_RULES.get(intent)
    if rule:
        parts.append(rule)

    target_lines = _target_lines(targets)
    if target_lines:
        parts.append(
            'CHANGE ONLY THESE QUESTIONS. Everything else comes back exactly as it '
            'is, with the same "key":\n' + '\n'.join(target_lines[:60])
        )

    plan = _blueprint_lines({'blueprint': add_plan or []})
    if plan:
        parts.append('ADD EXACTLY THESE NEW QUESTIONS, NO MORE AND NO LESS:\n' + '\n'.join(plan))

    parts.append(f'WHAT THE ADMIN WANTS CHANGED:\n"""\n{instruction.strip()}\n"""')

    if brief:
        parts.append(f'ORIGINAL BRIEF FOR CONTEXT:\n"""\n{brief.strip()}\n"""')
    parts.append(
        'Apply that change and return the complete revised paper as one JSON object. '
        'Anything the instruction did not mention must come back exactly as it was, '
        'with the same "key".'
    )
    return '\n\n'.join(parts)


def refine_user_prompt(*, instruction, current_json):
    """Refine a draft that has not been applied yet."""
    return (
        'CURRENT DRAFT PAPER:\n' + current_json + '\n\n'
        f'REVISION REQUESTED:\n"""\n{instruction.strip()}\n"""\n\n'
        'Return the complete revised paper as one JSON object. Keep every question '
        'the instruction did not touch, with its original "key".'
    )
