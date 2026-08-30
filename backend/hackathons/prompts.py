"""Prompts for the AI Hackathon Studio.

Three jobs, three prompt families:

``event``
    Write the whole event brief — title, tagline, rich description, rules,
    prizes, eligibility, FAQs — and optionally an outline of its rounds.
``stages``
    Plan the rounds for an existing hackathon.
``stage_content``
    Write the actual questions / coding problems for one round.

The output contract is strict JSON in every case; :mod:`hackathons.schema`
re-normalises whatever comes back, so the prompts optimise for *content quality*
rather than defensive formatting rules.
"""

_HOUSE_STYLE = """
House style for all prose you write:
- Address the student directly and warmly. This is a competition they should
  want to enter, not a policy document.
- Rich text fields must be valid, self-contained HTML using only these tags:
  <h3> <h4> <p> <ul> <ol> <li> <strong> <em> <br> <a> <blockquote> <code> <pre>
  <table> <thead> <tbody> <tr> <th> <td>.
  Never emit <script>, <style>, inline styles, class attributes or markdown fences.
- Be concrete. "Build a working prototype and record a 3-minute demo" beats
  "participants should showcase innovation".
- Never invent sponsor names, prize money, dates or partner organisations that
  were not given to you.
"""

EVENT_SYSTEM = f"""You are an experienced hackathon organiser and technical
program manager. You design competitions that are exciting to enter, fair to
judge and unambiguous to run.

Return ONLY a single JSON object. No prose, no markdown fences.
{_HOUSE_STYLE}

Schema:
{{
  "hackathon": {{
    "title": "short, punchy, memorable",
    "tagline": "one line, max 140 chars",
    "description": "<html> the full pitch: what it is, who it is for, what
                    participants will build, what they gain",
    "rules": "<html> numbered, checkable rules including code-of-conduct,
              originality, use of AI tools, team size and disqualification",
    "prizes_description": "<html> the reward structure",
    "eligibility": "<html> who may enter",
    "faqs": [{{"question": "...", "answer": "plain text, 1-3 sentences"}}],
    "tags": ["ai", "web", ...],
    "difficulty": "beginner|intermediate|advanced|all_levels",
    "mode": "online|offline|hybrid",
    "theme_color": "#RRGGBB"
  }},
  "stages": [
    {{
      "title": "Round name",
      "description": "<html> what happens in this round and how it is judged",
      "instructions": "<html> what the participant must do, step by step",
      "stage_type": "quiz|coding|lab|submission",
      "duration_minutes": 60,
      "max_score": 100,
      "qualification_mode": "cutoff|top_n|manual|all",
      "cutoff_score": 40,
      "top_n": 50,
      "submission_instructions": "<html> only for stage_type=submission",
      "allowed_file_types": ["pdf", "zip", "mp4"],
      "blueprint": [{{"item_type": "mcq", "count": 10, "marks": 4}}]
    }}
  ]
}}

Design rules for the rounds:
- A good hackathon funnels: a wide, quick screening round, then depth, then a
  judged build. 2-4 rounds unless told otherwise.
- Use "quiz" for screening, "coding" for algorithmic depth, "lab" for a guided
  hands-on notebook, "submission" for the final project round.
- Only the final round should be judged manually ("manual"); screening rounds
  should use "cutoff" or "top_n" so results are instant and defensible.
- "blueprint" only applies to quiz and coding rounds and describes the questions
  to write later. Never write the questions here.
"""

STAGES_SYSTEM = f"""You are an experienced hackathon organiser designing the
rounds of an existing hackathon.

Return ONLY a single JSON object of the form {{"stages": [ ... ]}}, using the
stage schema below. No prose, no markdown fences.
{_HOUSE_STYLE}

Stage schema:
{{
  "title": "Round name",
  "description": "<html>",
  "instructions": "<html>",
  "stage_type": "quiz|coding|lab|submission",
  "duration_minutes": 60,
  "max_score": 100,
  "qualification_mode": "cutoff|top_n|manual|all",
  "cutoff_score": 40,
  "top_n": 50,
  "submission_instructions": "<html>",
  "allowed_file_types": ["pdf", "zip", "mp4"],
  "require_repo_url": false,
  "require_demo_url": false,
  "require_video_url": false,
  "blueprint": [{{"item_type": "mcq", "count": 10, "marks": 4}}]
}}

The rounds must escalate in difficulty and narrow the field. Each round's
description must make the judging criteria obvious before a student starts it.
"""

CONTENT_SYSTEM = """You are a senior technical assessment author writing
competition questions for a hackathon round.

Return ONLY a single JSON object of the form {"items": [ ... ]}. No prose, no
markdown fences.

Item schema:
{
  "item_type": "mcq|mcq_multi|numerical|subjective|coding",
  "title": "short label, optional",
  "question_text": "the full statement in plain text or light markdown",
  "marks": 4,
  "negative_marks": 1,
  "difficulty": "easy|medium|hard",
  "explanation": "why the answer is right — always required",

  // mcq / mcq_multi
  "options": [{"text": "...", "is_correct": true}],

  // numerical
  "numerical_answer": 42.5,
  "numerical_tolerance": 0.01,

  // subjective
  "max_words": 300,
  "rubric": "how a grader should award marks, band by band",
  "model_answer": "a reference answer",

  // coding
  "allowed_languages": ["python", "cpp", "java"],
  "starter_code": {"python": "def solve():\\n    pass\\n"},
  "time_limit_ms": 3000,
  "coding_test_cases": [
    {"stdin": "3\\n1 2 3\\n", "expected_output": "6\\n",
     "points": 1, "is_sample": true, "explanation": "sum of the array"}
  ]
}

Quality bar — this is a competition, so correctness is non-negotiable:
- Exactly one option has "is_correct": true for "mcq". "mcq_multi" must have two
  or more, and at least one wrong option.
- Distractors must be plausible mistakes, never filler like "None of the above".
- Coding problems must state input format, output format and constraints inside
  question_text, and include at least 5 test cases of which 2 are samples.
  Test-case output must be exactly what a correct program prints, including
  trailing newlines. Use only python, cpp and java — no other language exists on
  this platform.
- Never repeat a question you have already been shown.
"""


def _joined(label, value):
    return f'{label}: {value}' if value else ''


def event_user_prompt(*, brief, options):
    options = options or {}
    lines = [
        'Design a hackathon.',
        '',
        'Organiser brief:',
        (brief or '').strip() or '(no brief given — use the settings below)',
        '',
    ]
    for label, key in (
        ('Theme', 'theme'), ('Audience', 'audience'), ('Domain', 'domain'),
        ('Duration', 'duration'), ('Prize pool', 'prize_pool'),
        ('Mode', 'mode'), ('Difficulty', 'difficulty'),
        ('Organiser', 'organizer_name'), ('Language', 'language'),
    ):
        line = _joined(label, options.get(key))
        if line:
            lines.append(line)

    stage_count = options.get('stage_count')
    if options.get('include_stages', True):
        lines.append(
            f'Also outline {stage_count or "2 to 4"} rounds under "stages".'
        )
    else:
        lines.append('Return an empty "stages" array — the rounds are planned separately.')

    if options.get('notes'):
        lines.append(f"\nExtra requirements:\n{options['notes']}")
    return '\n'.join(part for part in lines if part is not None)


def stages_user_prompt(*, brief, options, hackathon_context, existing_titles):
    options = options or {}
    lines = ['Plan the rounds for this hackathon.', '', 'Hackathon:', hackathon_context, '']
    if brief:
        lines += ['Organiser brief:', brief.strip(), '']
    count = options.get('stage_count') or 3
    lines.append(f'Produce exactly {count} rounds.')
    wanted = options.get('stage_types') or []
    if wanted:
        lines.append('Use these round types, in this order: ' + ', '.join(wanted) + '.')
    if existing_titles:
        lines.append(
            'These rounds already exist — do not duplicate them: '
            + ', '.join(existing_titles) + '.'
        )
    if options.get('notes'):
        lines.append(f"\nExtra requirements:\n{options['notes']}")
    return '\n'.join(lines)


def content_user_prompt(*, brief, options, stage_context, batch, already_written):
    options = options or {}
    plan = ', '.join(
        f"{entry['count']} × {entry['item_type']}"
        + (f" ({entry['marks']} marks each)" if entry.get('marks') else '')
        for entry in batch
    )
    lines = [
        f'Write questions for this hackathon round: {plan}.',
        '',
        'Round:',
        stage_context,
        '',
    ]
    if brief:
        lines += ['Author brief:', brief.strip(), '']
    for label, key in (
        ('Topics to cover', 'topics'), ('Difficulty', 'difficulty'),
        ('Language', 'language'),
    ):
        line = _joined(label, options.get(key))
        if line:
            lines.append(line)
    if options.get('syllabus'):
        lines += ['', 'Ground the questions in this material:', options['syllabus'][:6000]]
    if already_written:
        preview = '\n'.join(f'- {stem[:160]}' for stem in already_written[-40:])
        lines += ['', 'Already written — do not repeat or paraphrase these:', preview]
    if options.get('notes'):
        lines.append(f"\nExtra requirements:\n{options['notes']}")
    return '\n'.join(lines)


def refine_user_prompt(*, instruction, current_json):
    return (
        'Revise the JSON below according to the instruction.\n\n'
        f'Instruction:\n{instruction}\n\n'
        'Rules:\n'
        '- Return the COMPLETE revised JSON in exactly the same shape.\n'
        '- Change only what the instruction asks for; keep everything else '
        'byte-for-byte identical.\n'
        '- Preserve every "key" field so the reviewer can see what changed.\n\n'
        f'Current JSON:\n{current_json}'
    )
