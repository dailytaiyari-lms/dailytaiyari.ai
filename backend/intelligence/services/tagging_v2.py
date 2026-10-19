"""Tagger v2 (decisions D1–D6): exam-aware, tree-bound, two-stage, with confidence.

Pure core — no database access. ``tag_payloads`` takes a *context* (plain data:
see ``syllabus.tagging_context``), question *payloads* and a completion
callable ``call(system, user) -> str``, and returns one TagResult per payload.

Stage 1 (locate) runs only for payloads without a valid ``topic_hint``: it
picks the topic. Stage 2 (tag) runs per topic, with that topic's subtopics
(plus any "also" topics) in the prompt, and returns every other level.
"""
import json
import re
from dataclasses import dataclass, field

from coursegen.generation import GenerationError, extract_json

BATCH_SIZE = 12
QUESTION_CHARS = 2000
OPTION_CHARS = 300
MAX_OPTIONS = 8
MAX_ALSO_TOPICS = 2
MIN_SOLVE_S, MAX_SOLVE_S = 10, 1800
DISAGREEMENT_FACTOR = 0.8
DIFFICULTIES = ('easy', 'medium', 'hard')
REASON_CHARS = 200

LOCATE_MARKER = 'syllabus locator'
TAG_MARKER = 'assessment tagger'

FORMAT_HINTS = [
    ('assertion_reason', re.compile(r'assertion\s*\(?\s*a\s*\)?.*reason\s*\(?\s*r\s*\)?', re.I | re.S)),
    ('statement_pair', re.compile(r'statement[\s-]*(i|1)\b.*statement[\s-]*(ii|2)\b', re.I | re.S)),
    ('match_list', re.compile(r'(list|column)[\s-]*(i|1)\b.*(list|column)[\s-]*(ii|2)\b', re.I | re.S)),
]

LOCATE_SYSTEM = """
You are a syllabus locator for <<EXAM>>. Audience: <<AUDIENCE>>.
For each question choose the ONE topic it mainly belongs to, using a key from
TOPICS exactly as written. Optionally list up to 2 further topic keys it also
draws on. Give your confidence (0 to 1) that the main topic is right.

Return ONE JSON object, no markdown fences, no commentary:
{"items": [{"id": "<id exactly as given>", "topic_key": "...", "also_topic_keys": [], "confidence": 0.0}]}
Include every question id exactly once.
""".strip()

TAG_SYSTEM = """
You are an assessment tagger for <<EXAM>>. Audience: <<AUDIENCE>>.
Tag each question on every level below, using ONLY keys listed in the context.
- "primary_subtopic": the one SUBTOPIC key the question mainly tests.
- "secondary_subtopics": every other SUBTOPIC key it genuinely needs (no limit; may be empty).
- "thinking_level": exactly one THINKING LEVEL key, the highest the question demands.
- "skills": EVERY applicable SKILL (no limit): [{"key": "...", "role": "core" or "supporting", "reason": "<one line>"}].
  "core" means the question cannot be solved without that skill.
- "special_format": a SPECIAL FORMAT key if the question has that structure, else "".
  A "format_hint" on a question is a regex guess; confirm or ignore it.
- "difficulty": "easy", "medium" or "hard" for this audience.
- "est_solve_seconds": typical seconds a well-prepared student of this audience needs.
- "proposed_subtopic": normally "". If NO listed subtopic fits, a short name for the
  missing one, and leave primary_subtopic "".
- "confidence": 0 to 1, your confidence that primary_subtopic is right.

Return ONE JSON object, no markdown fences, no commentary:
{"items": [{"id": "...", "primary_subtopic": "...", "secondary_subtopics": [], "thinking_level": "...",
            "skills": [], "special_format": "", "difficulty": "...", "est_solve_seconds": 0,
            "proposed_subtopic": "", "confidence": 0.0}]}
Include every question id exactly once.
""".strip()


@dataclass
class TagResult:
    id: str
    topic_key: str = ''
    primary_subtopic: str = ''
    secondary_subtopics: list = field(default_factory=list)
    thinking_level: str = ''
    skills: list = field(default_factory=list)
    special_format: str = ''
    difficulty: str = ''
    est_solve_seconds: int | None = None
    proposed_subtopic: str = ''
    confidence: float = 0.0
    review_reasons: list = field(default_factory=list)
    needs_review: bool = True
    raw: dict = field(default_factory=dict)
    error: str = ''


class _NoCache:
    def get(self, stage, payload_id):
        return None

    def put(self, stage, payload_id, entry):
        return None


def cognitive_projection(thinking_level):
    """Three-value quiz ``cognitive_type`` from the five-value thinking level."""
    if thinking_level in ('recall', 'multi_concept'):
        return thinking_level
    return 'application' if thinking_level else ''


def format_hint(text):
    for key, pattern in FORMAT_HINTS:
        if pattern.search(text or ''):
            return key
    return ''


def _system(template, context):
    return template.replace('<<EXAM>>', context['exam_label']).replace('<<AUDIENCE>>', context['audience'])


def _question(payload, allowed_formats):
    out = {
        'id': str(payload['id']),
        'type': payload.get('type') or '',
        'question': (payload.get('question') or '')[:QUESTION_CHARS],
        'options': [str(option)[:OPTION_CHARS] for option in (payload.get('options') or [])[:MAX_OPTIONS]],
    }
    if payload.get('answer'):
        out['answer'] = str(payload['answer'])[:OPTION_CHARS]
    hint = format_hint(payload.get('question') or '')
    if hint and hint in allowed_formats:
        out['format_hint'] = hint
    return out


def _definition_lines(title, entries):
    return [f'{title}:'] + [f'- {e["key"]} | {e["label"]} — {e["definition"]}' for e in entries]


def _questions_block(context, payloads):
    allowed = {entry['key'] for entry in context['special_formats']}
    body = {'questions': [_question(payload, allowed) for payload in payloads]}
    return 'QUESTIONS:\n' + json.dumps(body, ensure_ascii=False)


def build_locate_prompt(context, payloads):
    lines = [f'SUBJECT: {context["subject"]}', 'TOPICS:']
    for topic in context['topics']:
        group = f' ({topic["group"]})' if topic.get('group') else ''
        desc = f' — {topic["description"]}' if topic.get('description') else ''
        lines.append(f'- {topic["key"]} | {topic["label"]}{group}{desc}')
    return _system(LOCATE_SYSTEM, context), '\n'.join(lines) + '\n\n' + _questions_block(context, payloads)


def build_tag_prompt(context, topic_keys, payloads):
    wanted = set(topic_keys)
    lines = [f'SUBJECT: {context["subject"]}', 'TOPICS AND THEIR SUBTOPICS:']
    for topic in context['topics']:
        if topic['key'] not in wanted:
            continue
        lines.append(f'* {topic["label"]} ({topic["key"]})')
        for sub in topic['subtopics']:
            desc = f' — {sub["description"]}' if sub.get('description') else ''
            lines.append(f'  - {sub["key"]} | {sub["label"]}{desc}')
    lines += _definition_lines('THINKING LEVELS', context['thinking_levels'])
    lines += _definition_lines('SKILLS', context['skills'])
    lines += _definition_lines('SPECIAL FORMATS', context['special_formats'])
    return _system(TAG_SYSTEM, context), '\n'.join(lines) + '\n\n' + _questions_block(context, payloads)


def _ask(call, system, user):
    """({id: entry}, error) for one completion."""
    try:
        content = call(system, user)
    except GenerationError as exc:
        return {}, f'call_failed: {exc}'[:200]
    try:
        parsed = extract_json(content)
    except GenerationError:
        return {}, 'unparseable_reply'
    items = parsed.get('items') if isinstance(parsed, dict) else None
    if not isinstance(items, list):
        return {}, 'unparseable_reply'
    return {str(entry.get('id')): entry for entry in items if isinstance(entry, dict)}, ''


def _confidence(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(1.0, max(0.0, number))


def _seconds(value):
    try:
        seconds = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    return min(MAX_SOLVE_S, max(MIN_SOLVE_S, seconds))


def _batches(items):
    for start in range(0, len(items), BATCH_SIZE):
        yield items[start:start + BATCH_SIZE]


def _locate(entry, topic_keys):
    topic = entry.get('topic_key') if isinstance(entry.get('topic_key'), str) else ''
    if topic not in topic_keys:
        return None
    also = []
    for key in entry.get('also_topic_keys') or []:
        if isinstance(key, str) and key in topic_keys and key != topic and key not in also:
            also.append(key)
    return {'topic_key': topic, 'also': also[:MAX_ALSO_TOPICS], 'located': True}


def _apply_tag(result, entry, context, allowed, located):
    """Validate one stage-2 entry into ``result``. ``allowed``: subtopic → topic key."""
    reasons = set()
    primary = entry.get('primary_subtopic') if isinstance(entry.get('primary_subtopic'), str) else ''
    proposed = str(entry.get('proposed_subtopic') or '').strip()[:300]
    if primary and primary not in allowed:
        reasons.add('invalid_key')
        primary = ''
    if not primary and not proposed:
        reasons.add('invalid_key')
    result.primary_subtopic = primary
    secondaries = []
    for key in entry.get('secondary_subtopics') or []:
        if not isinstance(key, str) or key not in allowed:
            reasons.add('invalid_key')
        elif key != primary and key not in secondaries:
            secondaries.append(key)
    result.secondary_subtopics = secondaries if primary else []

    levels = {e['key'] for e in context['thinking_levels']}
    level = entry.get('thinking_level') or ''
    if level in levels:
        result.thinking_level = level
    elif level:
        reasons.add('invalid_key')

    skill_keys = {e['key'] for e in context['skills']}
    skills, seen = [], set()
    for raw in entry.get('skills') or []:
        if isinstance(raw, str):
            raw = {'key': raw}
        if not isinstance(raw, dict):
            continue
        key = raw.get('key')
        if key not in skill_keys:
            reasons.add('invalid_key')
            continue
        if key in seen:
            continue
        seen.add(key)
        skills.append({'key': key, 'role': 'core' if raw.get('role') == 'core' else 'supporting',
                       'reason': str(raw.get('reason') or '')[:REASON_CHARS]})
    result.skills = skills

    formats = {e['key'] for e in context['special_formats']}
    special = entry.get('special_format') or ''
    if special in formats:
        result.special_format = special
    elif special:
        reasons.add('invalid_key')

    result.difficulty = entry.get('difficulty') if entry.get('difficulty') in DIFFICULTIES else ''
    result.est_solve_seconds = _seconds(entry.get('est_solve_seconds'))
    result.proposed_subtopic = proposed
    if proposed:
        reasons.add('proposed_subtopic')

    confidence = _confidence(entry.get('confidence'))
    if primary:
        result.topic_key = allowed[primary]
        if located.get('located') and allowed[primary] != located['topic_key']:
            reasons.add('stage_disagreement')
            confidence *= DISAGREEMENT_FACTOR
    result.confidence = round(confidence, 4)
    if result.confidence < context['review_threshold']:
        reasons.add('low_confidence')
    result.review_reasons = sorted(reasons)
    result.needs_review = bool(reasons)


def tag_payloads(context, payloads, *, call, cache=None):
    """Tag ``payloads`` against ``context``. Never raises for model trouble."""
    cache = cache or _NoCache()
    results = {str(p['id']): TagResult(id=str(p['id'])) for p in payloads}
    topic_keys = {topic['key'] for topic in context['topics']}
    if not topic_keys:
        for result in results.values():
            result.error = 'no_tree'
        return [results[str(p['id'])] for p in payloads]

    # Stage 1 — locate the topic for payloads without a usable hint.
    located = {}
    pending = []
    for p in payloads:
        pid = str(p['id'])
        if p.get('topic_hint') in topic_keys:
            located[pid] = {'topic_key': p['topic_hint'], 'also': [], 'located': False}
            results[pid].topic_key = p['topic_hint']
            continue
        cached = cache.get('locate', pid)
        if cached is not None and _locate(cached, topic_keys):
            located[pid] = _locate(cached, topic_keys)
            results[pid].topic_key = located[pid]['topic_key']
            results[pid].raw['locate'] = cached
        else:
            pending.append(p)
    for batch in _batches(pending):
        system, user = build_locate_prompt(context, batch)
        entries, error = _ask(call, system, user)
        for p in batch:
            pid = str(p['id'])
            entry = entries.get(pid)
            if entry is None:
                results[pid].error = error or 'missing_from_reply'
                continue
            results[pid].raw['locate'] = entry
            found = _locate(entry, topic_keys)
            if found is None:
                results[pid].error = 'no_topic'
                continue
            cache.put('locate', pid, entry)
            located[pid] = found
            results[pid].topic_key = found['topic_key']

    # Stage 2 — tag, grouped by located topic.
    def allowed_for(keys):
        return {sub['key']: topic['key'] for topic in context['topics'] if topic['key'] in keys
                for sub in topic['subtopics']}

    groups = {}
    for p in payloads:
        pid = str(p['id'])
        if pid in located:
            groups.setdefault(located[pid]['topic_key'], []).append(p)
    for topic_key, group in groups.items():
        todo = []
        for p in group:
            pid = str(p['id'])
            cached = cache.get('tag', pid)
            if cached is not None:
                keys = [topic_key] + located[pid]['also']
                results[pid].raw['tag'] = cached
                _apply_tag(results[pid], cached, context, allowed_for(keys), located[pid])
            else:
                todo.append(p)
        for batch in _batches(todo):
            prompt_topics = [topic_key] + sorted(
                {key for p in batch for key in located[str(p['id'])]['also']} - {topic_key})
            system, user = build_tag_prompt(context, prompt_topics, batch)
            allowed = allowed_for(prompt_topics)
            entries, error = _ask(call, system, user)
            for p in batch:
                pid = str(p['id'])
                entry = entries.get(pid)
                if entry is None:
                    results[pid].error = error or 'missing_from_reply'
                    continue
                results[pid].raw['tag'] = entry
                cache.put('tag', pid, entry)
                _apply_tag(results[pid], entry, context, allowed, located[pid])
    return [results[str(p['id'])] for p in payloads]
