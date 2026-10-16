"""Prompts for the AI Course Builder.

Three jobs, three prompts, one shape rule: **JSON only, matching the schema in
the prompt**. Everything the model returns is then re-validated by
:mod:`coursegen.schema`, so these prompts optimise for *quality of teaching*
rather than defensive formatting — the parser handles the rest.

The notes prompt deliberately asks for typed content *blocks*, never HTML: the
platform renders the house style itself (see :mod:`coursegen.notehtml`), which
keeps every generated note visually identical to the hand-authored ones.
"""
from __future__ import annotations

from .notehtml import BLOCK_TYPES, CALLOUT_VARIANTS

JSON_RULES = """
OUTPUT RULES (strict):
- Reply with ONE JSON object and nothing else. No prose, no markdown, no ``` fences.
- Use the exact keys shown in the schema. Omit keys you have no value for.
- All strings must be plain text (no HTML tags). Keep them free of trailing whitespace.
- Never invent placeholder text such as "TBD", "Lorem ipsum" or "Topic 1".
""".strip()


BLOCK_SCHEMA = f"""
A note is an ordered list of "blocks". Allowed block types: {', '.join(BLOCK_TYPES)}.

  {{"type": "lead",      "text": "One-sentence hook that frames the topic."}}
  {{"type": "heading",   "text": "Section title", "level": 3}}
  {{"type": "paragraph", "text": "Explanatory prose. **bold**, *italic* and `code` are allowed inline."}}
  {{"type": "bullets",   "items": ["point one", "point two"]}}
  {{"type": "numbers",   "items": ["first step", "second step"]}}
  {{"type": "code",      "language": "python", "text": "x = 5\\nprint(x)"}}
  {{"type": "callout",   "variant": "tip", "text": "A helpful aside.", "title": "optional"}}
  {{"type": "table",     "headers": ["Col A", "Col B"], "rows": [["a1", "b1"]]}}
  {{"type": "quote",     "text": "A memorable line.", "attribution": "optional"}}
  {{"type": "divider"}}

Callout variants: {', '.join(CALLOUT_VARIANTS)}.
""".strip()


TEACHING_STYLE = """
TEACHING STYLE:
- Write for a motivated learner who is new to the topic but not to studying.
- Explain the "why" before the "how"; use a concrete example for every abstract idea.
- Prefer short paragraphs (2-4 sentences) over walls of text.
- Use analogies from everyday Indian life where they genuinely clarify.
- Define jargon the first time it appears.
- Be accurate. If something is contested or version-specific, say so plainly.
- Never address the reader as "students"; write to one person, warmly and directly.
""".strip()


# ─────────────────────────────────────────────────────────────────────────────
# Outline
# ─────────────────────────────────────────────────────────────────────────────

OUTLINE_SYSTEM = f"""
You are a senior curriculum designer for an Indian online learning platform.
You design course structures that a working instructor can actually teach and a
self-paced learner can actually finish.

{JSON_RULES}

SCHEMA:
{{
  "course": {{
    "name": "Course name",
    "code": "url-safe-slug",
    "subtitle": "One compelling line (max 120 chars)",
    "description": "2-4 sentence plain-text overview",
    "course_type": "competitive | board | entrance | government | skill",
    "level": "Beginner | Intermediate | Advanced",
    "audience": "Who this course is for",
    "estimated_hours": 40,
    "highlights": ["What the learner gets, 4-6 short phrases"]
  }},
  "subjects": [
    {{
      "name": "Module / subject name",
      "code": "url-safe-slug",
      "description": "1-2 sentences",
      "weightage": 25,
      "chapters": [
        {{
          "name": "Chapter name",
          "code": "url-safe-slug",
          "description": "1-2 sentences",
          "estimated_hours": 3,
          "topics": [
            {{
              "name": "Topic name",
              "code": "url-safe-slug",
              "summary": "1-2 sentences on what this topic covers",
              "difficulty": "easy | medium | hard",
              "importance": "low | medium | high | critical",
              "estimated_study_hours": 1.5,
              "objectives": ["By the end the learner can ..."]
            }}
          ]
        }}
      ]
    }}
  ]
}}

DESIGN RULES:
- Order everything as it should be taught: prerequisites always come first.
- Every topic must be a single teachable idea, not a bucket. "Loops" is a topic;
  "Python basics" is a chapter.
- Topic names must be specific enough to write a lesson from, on their own.
- Codes are lowercase, hyphenated, unique within their parent, and derived from
  the name.
- Subject weightages should add up to roughly 100.
- Difficulty should rise across the course, not randomly.
""".strip()


def outline_user_prompt(*, brief, options, course=None, existing_outline=None):
    """The admin's brief, plus the shape they asked for."""
    subjects = options.get('subject_count') or 'as many as the subject needs'
    chapters = options.get('chapters_per_subject') or '4-8'
    topics = options.get('topics_per_chapter') or '3-6'

    parts = [f'BRIEF FROM THE ADMIN:\n"""\n{brief.strip()}\n"""']

    if course is not None:
        parts.append(
            'This outline extends an EXISTING course:\n'
            f'- Name: {course.name}\n'
            f'- Type: {course.get_course_type_display()}\n'
            f'- Description: {(course.description or "(none)")[:600]}\n'
            'Keep the "course" object consistent with it; design only the tree.'
        )
    if existing_outline:
        parts.append(
            'The course already contains the structure below. Do NOT repeat any of '
            'it — design only what is missing or newly requested:\n' + existing_outline
        )

    shape = [f'- Subjects/modules: {subjects}',
             f'- Chapters per subject: {chapters}',
             f'- Topics per chapter: {topics}']
    if options.get('level'):
        shape.append(f'- Target level: {options["level"]}')
    if options.get('audience'):
        shape.append(f'- Audience: {options["audience"]}')
    if options.get('language') and options['language'].lower() not in ('english', 'en'):
        shape.append(
            f'- Write all learner-facing text in {options["language"]} '
            '(keep codes in lowercase English slugs).'
        )
    if options.get('duration_hours'):
        shape.append(f'- Total course length: about {options["duration_hours"]} hours')
    parts.append('REQUESTED SHAPE:\n' + '\n'.join(shape))

    parts.append('Return the JSON object now.')
    return '\n\n'.join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Topic content (notes + quiz)
# ─────────────────────────────────────────────────────────────────────────────

#: Every material type the studio can write for a single topic.
MATERIAL_TYPES = ('notes', 'quiz', 'assignment', 'coding')

MATERIAL_LABELS = {
    'notes': 'reading notes',
    'quiz': 'practice quiz',
    'assignment': 'assignments',
    'coding': 'coding problems',
}


def requested_materials(options):
    """Which material types this job asked for, in canonical order.

    ``options['materials']`` is the modern form. The older ``include_notes`` /
    ``include_quiz`` booleans are still honoured so jobs created before
    assignments existed keep generating exactly what they used to.
    """
    options = options or {}
    raw = options.get('materials')
    if isinstance(raw, (list, tuple, set)):
        wanted = [m for m in MATERIAL_TYPES if m in {str(x).strip().lower() for x in raw}]
        if wanted:
            return wanted
    legacy = []
    if options.get('include_notes', True):
        legacy.append('notes')
    if options.get('include_quiz', True):
        legacy.append('quiz')
    return legacy or ['notes']


CONTENT_SYSTEM = f"""
You are a subject-matter expert who writes the reading material and practice
questions for an online course. Your notes are the primary way a learner meets
the topic, so they must teach it completely and stand on their own.

{JSON_RULES}

{BLOCK_SCHEMA}

SCHEMA:
{{
  "topics": [
    {{
      "topic_code": "the code you were given for this topic",
      "topic_name": "the name you were given",
      "note": {{
        "title": "A specific, inviting title for the reading",
        "difficulty": "beginner | intermediate | advanced",
        "blocks": [ ...content blocks... ]
      }},
      "quiz": {{
        "title": "<Topic name> Quiz",
        "duration_minutes": 10,
        "questions": [
          {{
            "question_text": "A question that tests understanding, not recall of wording",
            "options": ["option A", "option B", "option C", "option D"],
            "correct_option": 1,
            "explanation": "Why that option is right AND why the tempting wrong one is not",
            "difficulty": "easy | medium | hard",
            "concept": "The specific concept this question tests"
          }}
        ]
      }},
      "assignments": [
        {{
          "title": "A specific deliverable, not 'Assignment 1'",
          "submission_type": "text | pdf | either",
          "max_marks": 20,
          "instructions": [ ...content blocks: the brief, the tasks, what to submit... ]
        }}
      ],
      "coding_problems": [
        {{
          "title": "The problem name",
          "difficulty": "easy | medium | hard",
          "allowed_languages": ["python", "cpp", "java"],
          "time_limit_ms": 3000,
          "memory_limit_mb": 256,
          "max_marks": 10,
          "statement": [ ...content blocks: story, input format, output format, constraints... ],
          "starter_code": {{ "python": "def solve():\\n    pass" }},
          "test_cases": [
            {{
              "stdin": "exact text fed to standard input",
              "expected_output": "exact text the program must print",
              "is_sample": true,
              "points": 1,
              "explanation": "Shown next to sample cases only"
            }}
          ]
        }}
      ]
    }}
  ]
}}

NOTE STRUCTURE (per topic):
- Open with exactly one "lead" block.
- Then 3-6 "heading" sections, each followed by paragraphs, bullets, a table or
  code as the content demands.
- Include at least one "callout" (tip / key / warn / example) where it genuinely helps.
- Close with a "callout" of variant "recap" summarising the takeaways.
- Include code blocks only for topics where code is the subject matter.

QUIZ RULES:
- "correct_option" is the ZERO-BASED index into "options".
- Exactly one option is correct; the other three must be plausible, not silly.
- Spread the correct answer across different indexes — do not always use 0.
- "concept" must name a real sub-concept from this topic (e.g. "Newton's First
  Law"), never a generic label like "Quiz" or "Practice".
- Every question must be answerable from the note you just wrote.

ASSIGNMENT RULES:
- An assignment is graded work a human reads — it must ask for something the
  learner produces, not something they tick.
- The creator's requested format, difficulty and instructions are authoritative.
  Do not replace them with a recurring template or make the task harder.
- Keep assignments age-appropriate and simple by default. Do not require code,
  implementation, advanced analysis or extra deliverables unless the creator
  explicitly asks for them.
- A marking scheme is optional. Include one only when the creator asks for it
  or when it naturally helps; never let it dominate a simple classroom task.
- Use "text" when the answer is written prose, "pdf" when a file or scan is the
  natural artefact, "either" when both are acceptable.
- Never invent a due date; timing is set by the admin.

CODING PROBLEM RULES:
- Only write coding problems when the topic is genuinely about programming.
- The statement must fully specify input format, output format and constraints —
  a solver should never have to guess.
- "stdin" and "expected_output" must be the EXACT text, with real newlines. The
  expected output must be what a correct program prints, character for character.
- Give 2-3 "is_sample": true cases (visible, with an explanation) and 3-5 hidden
  cases that cover the edge conditions the samples do not.
- "allowed_languages" may only contain: python, cpp, java.
- Starter code is a skeleton with the signature and a TODO — never the solution.

OMISSION RULE:
- Return an empty list (or an empty "blocks"/"questions" list) for any material
  type you were not asked for. Never invent material the admin did not request.

{TEACHING_STYLE}
""".strip()


def content_user_prompt(*, brief, options, course, subject_name, topics, context='', existing=''):
    """Ask for the requested material for a specific batch of real topics."""
    depth = options.get('depth') or 'standard'
    depth_hint = {
        'concise': 'Aim for a 4-6 minute read: 3 sections, tight prose.',
        'standard': 'Aim for an 8-12 minute read: 4-5 sections with examples.',
        'deep': 'Aim for a 15-20 minute read: 6+ sections, worked examples, edge cases.',
    }.get(depth, 'Aim for an 8-12 minute read: 4-5 sections with examples.')

    listing = '\n'.join(
        f'{index + 1}. name: "{topic["name"]}" | topic_code: "{topic.get("code") or ""}"'
        + (f'\n   context: {topic["summary"]}' if topic.get('summary') else '')
        for index, topic in enumerate(topics)
    )

    parts = [
        f'COURSE: {course.name}' + (f' — {course.description[:300]}' if course.description else ''),
        f'SUBJECT / MODULE: {subject_name}',
        'WRITE MATERIAL FOR EXACTLY THESE TOPICS, in this order, reusing the '
        'topic_code verbatim:\n' + listing,
    ]
    if context:
        parts.append(
            'SURROUNDING CURRICULUM (for continuity — do not write material for these):\n'
            + context
        )
    if existing:
        parts.append(
            'MATERIAL THAT ALREADY EXISTS ON THESE TOPICS:\n' + existing + '\n'
            + (
                'The admin chose ADD MORE: your material sits ALONGSIDE the above. '
                'Do not repeat any of it — cover angles, examples and questions it '
                'does not already cover.'
                if (options.get('mode') or 'replace') == 'add'
                else 'The admin chose REPLACE: write the definitive version that '
                     'supersedes the above.'
            )
        )
    if brief and brief.strip():
        parts.append(f'ADDITIONAL INSTRUCTIONS FROM THE ADMIN:\n"""\n{brief.strip()}\n"""')

    wanted = requested_materials(options)
    settings = [
        'WRITE ONLY THESE MATERIAL TYPES: '
        + ', '.join(MATERIAL_LABELS[m] for m in wanted)
        + '. Leave every other field empty.'
    ]

    if 'notes' in wanted:
        settings.append(depth_hint)
    if 'quiz' in wanted:
        count = options.get('questions_per_quiz') or 5
        settings.append(f'Write exactly {count} quiz questions per topic.')
    if 'assignment' in wanted:
        count = options.get('assignments_per_topic') or 1
        settings.append(
            f'Write exactly {count} assignment(s) per topic.'
        )
        difficulty = str(options.get('assignment_difficulty') or 'easy').strip()
        settings.append(
            f'Assignment difficulty: {difficulty}. Do not exceed this difficulty.'
        )
        assignment_type = str(options.get('assignment_type') or '').strip()
        if assignment_type:
            settings.append(
                f'Assignment type / format: {assignment_type}. Preserve this format; '
                'do not substitute a standard coding problem, essay or project.'
            )
        assignment_instructions = str(
            options.get('assignment_instructions') or ''
        ).strip()
        if assignment_instructions:
            settings.append(
                'Creator-controlled assignment brief (follow this literally; do not '
                'add harder requirements):\n"""\n'
                + assignment_instructions
                + '\n"""'
            )
    if 'coding' in wanted:
        count = options.get('coding_problems_per_topic') or 1
        languages = options.get('coding_languages') or ['python']
        settings.append(
            f'Write {count} coding problem(s) per topic, allowing these languages: '
            f'{", ".join(languages)}. Each needs 2-3 sample and 3-5 hidden test cases.'
        )

    if options.get('language') and options['language'].lower() not in ('english', 'en'):
        settings.append(f'Write everything in {options["language"]}.')
    if options.get('tone'):
        settings.append(f'Tone: {options["tone"]}.')
    parts.append('SETTINGS:\n- ' + '\n- '.join(settings))

    parts.append('Return the JSON object now.')
    return '\n\n'.join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Course marketing copy
# ─────────────────────────────────────────────────────────────────────────────

META_SYSTEM = f"""
You write the public-facing copy for online courses in India. It must be
honest, specific and free of hype — describe what the learner will actually be
able to do, not how "amazing" the course is.

{JSON_RULES}

{BLOCK_SCHEMA}

SCHEMA:
{{
  "course": {{
    "subtitle": "One line under the title (max 120 chars)",
    "description": "2-4 sentence plain-text summary for cards and search",
    "description_blocks": [ ...content blocks for the course detail page... ],
    "highlights": ["4-6 short 'what you get' phrases"],
    "refund_policy": "Optional short refund policy"
  }}
}}

RULES:
- No exclamation marks, no "world-class", "revolutionary", "guaranteed selection".
- Highlights are concrete: "12 hours of video", "220 practice questions",
  "Certificate on completion" — not "Great content".
- Do not promise outcomes the platform cannot deliver (jobs, ranks, marks).
""".strip()


def meta_user_prompt(*, brief, options, course, outline_text=''):
    parts = [
        f'COURSE: {course.name}',
        f'TYPE: {course.get_course_type_display()}',
    ]
    if course.description:
        parts.append(f'CURRENT DESCRIPTION:\n{course.description[:1500]}')
    if outline_text:
        parts.append(f'CURRICULUM:\n{outline_text}')
    if brief and brief.strip():
        parts.append(f'ADMIN BRIEF:\n"""\n{brief.strip()}\n"""')
    if options.get('language') and options['language'].lower() not in ('english', 'en'):
        parts.append(f'Write everything in {options["language"]}.')
    parts.append('Return the JSON object now.')
    return '\n\n'.join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Refinement
# ─────────────────────────────────────────────────────────────────────────────

def refine_user_prompt(*, instruction, current_json):
    """Ask for a revised draft, given the current one and what to change."""
    return (
        'Here is the current draft you produced:\n'
        f'```json\n{current_json}\n```\n\n'
        'The admin reviewed it and asked for this change:\n'
        f'"""\n{instruction.strip()}\n"""\n\n'
        'Return the COMPLETE revised JSON object in the same schema. Apply the '
        'requested change and keep everything else exactly as it was — do not '
        'silently rewrite parts the admin did not mention, and do not drop any '
        'existing items unless the instruction asks you to.'
    )


SYSTEM_PROMPTS = {
    'outline': OUTLINE_SYSTEM,
    'content': CONTENT_SYSTEM,
    'meta': META_SYSTEM,
}
