"""Runs the AI Mock Test Builder's generation, and nothing else.

This module talks to the LLM and produces a **draft paper**. It never touches
the mock-test tables — that is :mod:`mockgen.apply`, and only after an admin
confirms.

Provider resolution, JSON extraction, usage metering and budget checks are
deliberately shared with :mod:`coursegen.generation`: an academy configures its
AI providers once, under "AI Features", and every authoring tool on the platform
resolves them the same way.
"""
from __future__ import annotations

import json
import logging

from chatbot.models import AIUsageRecord
from coursegen.generation import (
    GenerationError,
    _Meter,
    _call,
    _check_budget,
    available_models,
    extract_json,
    resolve_for_admin,
)

from . import prompts, schema
from .models import MockTestGenerationJob

logger = logging.getLogger(__name__)

# Every call this module makes is billed to the mock-test builder.
FEATURE = AIUsageRecord.FEATURE_MOCKGEN

__all__ = [
    'GenerationError', 'available_models', 'resolve_for_admin',
    'run_job', 'apply_refinement',
]

# A paper is long-form: twenty MCQs with explanations does not fit in the 2 000
# tokens the chat assistant defaults to.
DEFAULT_MAX_TOKENS = 8000
# Questions per LLM call. Small batches keep each request inside provider limits
# and mean one bad response only costs one batch.
BATCH_SIZE = 8
# Coding questions carry statements, starter code and test cases, so they cost
# far more tokens per item than an MCQ.
CODING_BATCH_SIZE = 2


# ─────────────────────────────────────────────────────────────────────────────
# Blueprint batching
# ─────────────────────────────────────────────────────────────────────────────

def _blueprint_entries(options):
    """The admin's plan, cleaned into ``{item_type, count, …}`` rows."""
    entries = []
    for raw in (options or {}).get('blueprint') or []:
        if not isinstance(raw, dict):
            continue
        item_type = str(raw.get('item_type') or '').strip().lower()
        if item_type not in schema.ITEM_TYPE_SET:
            continue
        try:
            count = int(raw.get('count') or 0)
        except (TypeError, ValueError):
            continue
        if count <= 0:
            continue
        entry = {'item_type': item_type, 'count': min(count, schema.MAX_ITEMS_PER_REQUEST)}
        for key in ('marks', 'negative_marks', 'difficulty', 'section', 'note'):
            if raw.get(key) not in (None, ''):
                entry[key] = raw[key]
        entries.append(entry)
    return entries


def _batches(entries):
    """Split the blueprint into LLM-sized chunks, never mixing an oversized type.

    Each chunk is a list of blueprint rows, so the prompt can still say
    "5 MCQs and 2 numericals" when that fits in one request.
    """
    batches = []
    current = []
    current_count = 0

    for entry in entries:
        size = CODING_BATCH_SIZE if entry['item_type'] == 'coding' else BATCH_SIZE
        remaining = entry['count']
        while remaining > 0:
            # A coding question costs several times an MCQ, so a batch that is
            # already full for the *current* type gets flushed before mixing.
            if current_count >= size:
                batches.append(current)
                current, current_count = [], 0
            take = min(remaining, size - current_count)
            current.append({**entry, 'count': take})
            current_count += take
            remaining -= take
    if current:
        batches.append(current)
    return batches


def syllabus_text_for(job):
    """Curriculum context for the prompt: the admin's own text, plus the course.

    Grounding a paper in the course the students actually studied is the single
    biggest quality lever, so an admin who picked a course gets its tree (and,
    when they narrowed to topics, only those topics) pasted into the prompt.
    """
    options = job.options or {}
    parts = []

    typed = (options.get('syllabus') or '').strip()
    if typed:
        parts.append(typed[:6000])

    course = job.course
    if course is not None:
        topic_ids = {str(value) for value in (options.get('topic_ids') or [])}
        lines = [f'Course: {course.name}']
        for subject in course.subjects.all().order_by('order', 'name'):
            subject_lines = []
            for chapter in subject.chapters.all().order_by('order', 'name'):
                topic_lines = []
                links = chapter.chapter_topics.select_related('topic').order_by('order')
                for link in links:
                    if topic_ids and str(link.topic_id) not in topic_ids:
                        continue
                    summary = (link.topic.description or '').strip()
                    topic_lines.append(
                        f'    - {link.topic.name}' + (f': {summary[:160]}' if summary else '')
                    )
                if topic_lines:
                    subject_lines.append(f'  - {chapter.name}')
                    subject_lines.extend(topic_lines)
            if subject_lines:
                lines.append(f'- {subject.name}')
                lines.extend(subject_lines)
            if len(lines) > 200:
                lines.append('  - …')
                break
        if len(lines) > 1:
            parts.append('\n'.join(lines))

    return '\n\n'.join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Generators
# ─────────────────────────────────────────────────────────────────────────────

def generate_paper(job):
    """Write a fresh paper from the blueprint, one batch of questions at a time."""
    tenant = job.tenant
    _check_budget(tenant)

    options = job.options or {}
    entries = _blueprint_entries(options)
    if not entries:
        raise GenerationError(
            'Tell the studio how many questions of each type you want before generating.'
        )

    resolved = resolve_for_admin(
        tenant, provider=job.provider, model=job.model, max_tokens=DEFAULT_MAX_TOKENS
    )
    meter = _Meter()
    syllabus = syllabus_text_for(job)

    test_meta = None
    sections = schema.normalize_sections(options.get('sections'))
    items = []
    stems = []
    failures = []

    for batch in _batches(entries):
        user = prompts.mock_user_prompt(
            brief=job.prompt,
            options=options,
            syllabus_text=syllabus,
            batch={'blueprint': batch},
            already_written=stems,
        )
        try:
            raw = _call(resolved, prompts.MOCK_SYSTEM, user, meter, tenant, feature=FEATURE)
            partial = schema.normalize_mock(extract_json(raw), options=options)
        except GenerationError as exc:
            # One bad batch must not throw away the batches that succeeded.
            logger.warning('mockgen: batch failed: %s', exc)
            failures.append({
                'types': sorted({entry['item_type'] for entry in batch}),
                'error': str(exc),
            })
            continue

        if test_meta is None:
            test_meta = partial.get('test')
        if not sections and partial.get('sections'):
            sections = partial['sections']
        items = schema.merge_items(items, partial.get('items') or [])
        stems = [item['question_text'] for item in items]

    if not items:
        detail = failures[0]['error'] if failures else 'no usable questions were returned'
        raise GenerationError(f'Generation failed — {detail}')

    draft = schema.normalize_mock(
        {'test': test_meta or {}, 'sections': sections, 'items': items},
        options=options,
    )
    if failures:
        draft['partial_failures'] = failures
    return draft, meter, resolved


def generate_modification(job):
    """Rewrite an existing, already-saved paper according to the admin's brief."""
    tenant = job.tenant
    _check_budget(tenant)

    mock_test = job.mock_test
    if mock_test is None:
        raise GenerationError('This job has no mock test to modify.')

    instruction = (job.prompt or '').strip()
    if not instruction:
        raise GenerationError('Describe the change you want before generating.')

    resolved = resolve_for_admin(
        tenant, provider=job.provider, model=job.model, max_tokens=DEFAULT_MAX_TOKENS
    )
    meter = _Meter()

    from .apply import draft_from_mock_test

    current = draft_from_mock_test(mock_test)
    if not current.get('items'):
        raise GenerationError(
            'This mock test has no inline questions for the AI to work from. '
            'Add a question by hand first, or generate a new paper.'
        )

    user = prompts.modify_user_prompt(
        instruction=instruction,
        current_json=json.dumps(_for_prompt(current), ensure_ascii=False)[:60000],
    )
    raw = _call(resolved, prompts.MODIFY_SYSTEM, user, meter, tenant, feature=FEATURE)
    draft = schema.normalize_mock(
        extract_json(raw), existing_test=mock_test, options=job.options
    )
    if not draft.get('items'):
        raise GenerationError(
            'The revised paper came back empty — nothing was changed. Try again '
            'with a more specific instruction.'
        )
    return draft, meter, resolved


def refine(job, instruction):
    """Regenerate ``job.draft`` with an admin's correction applied."""
    tenant = job.tenant
    _check_budget(tenant)
    resolved = resolve_for_admin(
        tenant, provider=job.provider, model=job.model, max_tokens=DEFAULT_MAX_TOKENS
    )
    meter = _Meter()

    current = json.dumps(_for_prompt(job.draft or {}), ensure_ascii=False)[:60000]
    system = (
        prompts.MODIFY_SYSTEM if job.kind == MockTestGenerationJob.KIND_MODIFY
        else prompts.MOCK_SYSTEM
    )
    user = prompts.refine_user_prompt(instruction=instruction, current_json=current)
    raw = _call(resolved, system, user, meter, tenant, feature=FEATURE)

    draft = schema.normalize_mock(
        extract_json(raw),
        existing_test=job.mock_test if job.kind == MockTestGenerationJob.KIND_MODIFY else None,
        options=job.options,
    )
    if not draft.get('items'):
        raise GenerationError('The revised paper had no questions — the change was not applied.')
    return draft, meter, resolved


def _for_prompt(draft):
    """The draft trimmed of derived data the model neither needs nor should edit."""
    clone = json.loads(json.dumps(draft or {}))
    clone.pop('stats', None)
    clone.pop('partial_failures', None)
    for item in clone.get('items') or []:
        item.pop('order', None)
        item.pop('include', None)
    return clone


# ─────────────────────────────────────────────────────────────────────────────
# Job orchestration
# ─────────────────────────────────────────────────────────────────────────────

def run_job(job):
    """Execute ``job``, storing the draft (or the failure) on the row.

    Always leaves the job in a terminal-for-now state: ``preview`` when a paper
    is ready for review, ``failed`` otherwise. It never writes to the mock-test
    tables.
    """
    job.status = MockTestGenerationJob.STATUS_GENERATING
    job.error = ''
    job.save(update_fields=['status', 'error', 'updated_at'])

    try:
        if job.kind == MockTestGenerationJob.KIND_MODIFY:
            draft, meter, resolved = generate_modification(job)
        else:
            draft, meter, resolved = generate_paper(job)
    except GenerationError as exc:
        job.status = MockTestGenerationJob.STATUS_FAILED
        job.error = str(exc)[:2000]
        job.save(update_fields=['status', 'error', 'updated_at'])
        return job
    except Exception as exc:  # noqa: BLE001 - never leak a stack trace to an admin
        logger.exception('mockgen: unexpected generation failure')
        job.status = MockTestGenerationJob.STATUS_FAILED
        job.error = f'Unexpected error while generating: {str(exc)[:300]}'
        job.save(update_fields=['status', 'error', 'updated_at'])
        return job

    _store_result(job, draft, meter, resolved)
    job.record_revision('generated', job.prompt)
    job.save()
    return job


def apply_refinement(job, instruction):
    """Refine an existing draft in place.

    A failed refine must never cost the admin their draft, nor leave the job
    stuck in ``generating`` when it runs on the worker — so the previous draft
    is restored and the job goes back to ``preview`` with a readable error.
    """
    job.status = MockTestGenerationJob.STATUS_GENERATING
    job.error = ''
    job.save(update_fields=['status', 'error', 'updated_at'])
    try:
        draft, meter, resolved = refine(job, instruction)
    except GenerationError as exc:
        job.status = MockTestGenerationJob.STATUS_PREVIEW
        job.error = str(exc)[:2000]
        job.save(update_fields=['status', 'error', 'updated_at'])
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception('mockgen: unexpected refine failure')
        job.status = MockTestGenerationJob.STATUS_PREVIEW
        job.error = f'Unexpected error while refining: {str(exc)[:300]}'
        job.save(update_fields=['status', 'error', 'updated_at'])
        raise GenerationError(job.error)

    _store_result(job, draft, meter, resolved, accumulate=True)
    job.record_revision('refined', instruction)
    job.save()
    return job


def _store_result(job, draft, meter, resolved, accumulate=False):
    from chatbot.providers import estimate_cost_usd

    job.draft = draft
    job.status = MockTestGenerationJob.STATUS_PREVIEW
    job.error = ''
    job.provider = (
        resolved.provider if resolved.source != AIUsageRecord.SOURCE_PLATFORM else 'platform'
    )
    job.model = resolved.model
    if accumulate:
        job.prompt_tokens += meter.usage.prompt_tokens
        job.completion_tokens += meter.usage.completion_tokens
        job.total_tokens += meter.usage.total_tokens
        job.generation_ms += meter.elapsed_ms
        job.estimated_cost_usd = (
            job.estimated_cost_usd + _decimal(estimate_cost_usd(resolved.model, meter.usage))
        )
    else:
        job.prompt_tokens = meter.usage.prompt_tokens
        job.completion_tokens = meter.usage.completion_tokens
        job.total_tokens = meter.usage.total_tokens
        job.generation_ms = meter.elapsed_ms
        job.estimated_cost_usd = _decimal(estimate_cost_usd(resolved.model, meter.usage))


def _decimal(value):
    from decimal import Decimal

    return Decimal(str(round(float(value or 0), 6)))
