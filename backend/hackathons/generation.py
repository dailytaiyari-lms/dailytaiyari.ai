"""LLM generation for the AI Hackathon Studio.

Produces **drafts only**. Nothing here writes to the hackathon tables — that is
:mod:`hackathons.apply`, and only once an admin confirms the preview.

Provider resolution, JSON extraction, usage metering and budget checks are
shared with :mod:`coursegen.generation` so an academy configures its AI providers
once, under "AI Features", and every authoring tool resolves them identically.
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
logger = logging.getLogger(__name__)

FEATURE = AIUsageRecord.FEATURE_HACKATHONGEN

__all__ = [
    'GenerationError', 'available_models', 'resolve_for_admin',
    'run_job', 'apply_refinement',
]

# Event briefs and question batches are both long-form; the chat default of
# 2 000 tokens truncates them mid-JSON.
DEFAULT_MAX_TOKENS = 8000
BATCH_SIZE = 8
CODING_BATCH_SIZE = 2


# ── context builders ─────────────────────────────────────────────────────────

def _hackathon_context(hackathon):
    if hackathon is None:
        return '(no hackathon selected)'
    lines = [f'Title: {hackathon.title}']
    if hackathon.tagline:
        lines.append(f'Tagline: {hackathon.tagline}')
    lines.append(f'Mode: {hackathon.get_mode_display()}')
    lines.append(f'Difficulty: {hackathon.get_difficulty_display()}')
    if hackathon.starts_at:
        lines.append(f"Starts: {hackathon.starts_at.strftime('%d %b %Y')}")
    if hackathon.ends_at:
        lines.append(f"Ends: {hackathon.ends_at.strftime('%d %b %Y')}")
    if hackathon.tags:
        lines.append('Tags: ' + ', '.join(hackathon.tags[:12]))
    summary = schema.plain(hackathon.description, 1500)
    if summary:
        lines.append(f'About: {summary}')
    return '\n'.join(lines)


def _stage_context(stage):
    if stage is None:
        return '(no round selected)'
    lines = [
        f'Round: {stage.title}',
        f'Type: {stage.get_stage_type_display()}',
        f'Max score: {stage.max_score}',
    ]
    if stage.duration_minutes:
        lines.append(f'Duration: {stage.duration_minutes} minutes')
    detail = schema.plain(stage.description, 1200)
    if detail:
        lines.append(f'Description: {detail}')
    lines.append(f'Hackathon: {stage.hackathon.title}')
    context = schema.plain(stage.hackathon.description, 800)
    if context:
        lines.append(f'Hackathon context: {context}')
    return '\n'.join(lines)


def _batches(entries):
    """Split a blueprint into LLM-sized chunks, never overfilling a coding batch."""
    batches, current, count = [], [], 0
    for entry in entries:
        size = CODING_BATCH_SIZE if entry['item_type'] == 'coding' else BATCH_SIZE
        remaining = entry['count']
        while remaining > 0:
            if count >= size:
                batches.append(current)
                current, count = [], 0
            take = min(remaining, size - count)
            current.append({**entry, 'count': take})
            count += take
            remaining -= take
    if current:
        batches.append(current)
    return batches


# ── generators ───────────────────────────────────────────────────────────────

def generate_event(job):
    """Write the whole hackathon brief (and, usually, an outline of its rounds)."""
    _check_budget(job.tenant)
    resolved = resolve_for_admin(
        job.tenant, provider=job.provider, model=job.model, max_tokens=DEFAULT_MAX_TOKENS,
    )
    meter = _Meter()
    user = prompts.event_user_prompt(brief=job.prompt, options=job.options or {})
    raw = _call(resolved, prompts.EVENT_SYSTEM, user, meter, job.tenant, feature=FEATURE)
    draft = schema.normalize_draft(extract_json(raw), 'event', job.options)
    if not draft['hackathon'].get('description'):
        raise GenerationError(
            'The model returned an empty hackathon description. Try again with a '
            'more specific brief.'
        )
    return draft, meter, resolved


def generate_stages(job):
    """Plan rounds for an existing hackathon."""
    _check_budget(job.tenant)
    if job.hackathon is None:
        raise GenerationError('Choose the hackathon these rounds belong to.')
    resolved = resolve_for_admin(
        job.tenant, provider=job.provider, model=job.model, max_tokens=DEFAULT_MAX_TOKENS,
    )
    meter = _Meter()
    existing = list(job.hackathon.stages.values_list('title', flat=True))
    user = prompts.stages_user_prompt(
        brief=job.prompt,
        options=job.options or {},
        hackathon_context=_hackathon_context(job.hackathon),
        existing_titles=existing,
    )
    raw = _call(resolved, prompts.STAGES_SYSTEM, user, meter, job.tenant, feature=FEATURE)
    draft = schema.normalize_draft(extract_json(raw), 'stages', job.options)
    if not draft['stages']:
        raise GenerationError('No usable rounds came back. Try again.')
    return draft, meter, resolved


def generate_stage_content(job):
    """Write the questions or coding problems for one round, batch by batch."""
    _check_budget(job.tenant)
    if job.stage is None:
        raise GenerationError('Choose the round these questions belong to.')

    options = job.options or {}
    entries = schema.normalize_blueprint(options.get('blueprint'))
    if not entries:
        raise GenerationError(
            'Tell the studio how many questions of each type you want before generating.'
        )
    total = sum(entry['count'] for entry in entries)
    if total > schema.MAX_ITEMS_PER_REQUEST:
        raise GenerationError(
            f'Generate at most {schema.MAX_ITEMS_PER_REQUEST} questions at a time '
            'so you can review them properly.'
        )

    resolved = resolve_for_admin(
        job.tenant, provider=job.provider, model=job.model, max_tokens=DEFAULT_MAX_TOKENS,
    )
    meter = _Meter()
    context = _stage_context(job.stage)

    items, stems, failures = [], [], []
    for batch in _batches(entries):
        user = prompts.content_user_prompt(
            brief=job.prompt, options=options, stage_context=context,
            batch=batch, already_written=stems,
        )
        try:
            raw = _call(
                resolved, prompts.CONTENT_SYSTEM, user, meter, job.tenant, feature=FEATURE,
            )
            partial = schema.normalize_draft(extract_json(raw), 'stage_content', options)
        except GenerationError as exc:
            # One bad batch must not throw away the batches that succeeded.
            logger.warning('hackathongen: batch failed: %s', exc)
            failures.append({
                'types': sorted({entry['item_type'] for entry in batch}),
                'error': str(exc),
            })
            continue
        items = schema.merge_items(items, partial.get('items') or [])
        stems = [item['question_text'] for item in items]

    if not items:
        detail = failures[0]['error'] if failures else 'no usable questions were returned'
        raise GenerationError(f'Generation failed — {detail}')

    draft = {'kind': 'stage_content', 'items': items}
    if failures:
        draft['partial_failures'] = failures
    draft['stats'] = schema.draft_summary(draft)
    return draft, meter, resolved


_GENERATORS = {
    'event': generate_event,
    'stages': generate_stages,
    'stage_content': generate_stage_content,
}
_SYSTEMS = {
    'event': prompts.EVENT_SYSTEM,
    'stages': prompts.STAGES_SYSTEM,
    'stage_content': prompts.CONTENT_SYSTEM,
}


def refine(job, instruction):
    """Regenerate ``job.draft`` with an admin's correction applied."""
    _check_budget(job.tenant)
    resolved = resolve_for_admin(
        job.tenant, provider=job.provider, model=job.model, max_tokens=DEFAULT_MAX_TOKENS,
    )
    meter = _Meter()
    current = json.dumps(_for_prompt(job.draft or {}), ensure_ascii=False)[:60000]
    user = prompts.refine_user_prompt(instruction=instruction, current_json=current)
    raw = _call(
        resolved, _SYSTEMS.get(job.kind, prompts.EVENT_SYSTEM), user, meter,
        job.tenant, feature=FEATURE,
    )
    draft = schema.normalize_draft(extract_json(raw), job.kind, job.options)
    if job.kind == 'stage_content' and not draft.get('items'):
        raise GenerationError('The revised draft had no questions — nothing was changed.')
    if job.kind == 'stages' and not draft.get('stages'):
        raise GenerationError('The revised draft had no rounds — nothing was changed.')
    return draft, meter, resolved


def _for_prompt(draft):
    """The draft trimmed of derived data the model neither needs nor should edit."""
    clone = json.loads(json.dumps(draft or {}))
    clone.pop('stats', None)
    clone.pop('partial_failures', None)
    for collection in ('items', 'stages'):
        for entry in clone.get(collection) or []:
            entry.pop('order', None)
            entry.pop('include', None)
            entry.pop('issues', None)
    return clone


# ── job orchestration ────────────────────────────────────────────────────────

def run_job(job):
    """Execute ``job``, storing the draft (or the failure) on the row."""
    job.status = 'generating'
    job.error = ''
    job.save(update_fields=['status', 'error', 'updated_at'])

    try:
        draft, meter, resolved = _GENERATORS.get(job.kind, generate_event)(job)
    except GenerationError as exc:
        job.status = 'failed'
        job.error = str(exc)[:2000]
        job.save(update_fields=['status', 'error', 'updated_at'])
        return job
    except Exception as exc:  # noqa: BLE001 - never leak a stack trace to an admin
        logger.exception('hackathongen: unexpected generation failure')
        job.status = 'failed'
        job.error = f'Unexpected error while generating: {str(exc)[:300]}'
        job.save(update_fields=['status', 'error', 'updated_at'])
        return job

    _store_result(job, draft, meter, resolved)
    job.log('generated', job.prompt[:200])
    job.save()
    return job


def apply_refinement(job, instruction):
    """Refine an existing draft in place, never losing it on failure."""
    job.status = 'generating'
    job.error = ''
    job.save(update_fields=['status', 'error', 'updated_at'])
    try:
        draft, meter, resolved = refine(job, instruction)
    except GenerationError as exc:
        job.status = 'preview'
        job.error = str(exc)[:2000]
        job.save(update_fields=['status', 'error', 'updated_at'])
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception('hackathongen: unexpected refine failure')
        job.status = 'preview'
        job.error = f'Unexpected error while refining: {str(exc)[:300]}'
        job.save(update_fields=['status', 'error', 'updated_at'])
        raise GenerationError(job.error)

    _store_result(job, draft, meter, resolved, accumulate=True)
    job.log('refined', instruction[:200])
    job.save()
    return job


def _store_result(job, draft, meter, resolved, accumulate=False):
    from decimal import Decimal

    from chatbot.providers import estimate_cost_usd

    job.draft = draft
    job.status = 'preview'
    job.error = ''
    job.provider = (
        resolved.provider if resolved.source != AIUsageRecord.SOURCE_PLATFORM else 'platform'
    )
    job.model = resolved.model
    cost = Decimal(str(round(float(estimate_cost_usd(resolved.model, meter.usage) or 0), 6)))
    if accumulate:
        job.prompt_tokens += meter.usage.prompt_tokens
        job.completion_tokens += meter.usage.completion_tokens
        job.total_tokens += meter.usage.total_tokens
        job.generation_ms += meter.elapsed_ms
        job.estimated_cost_usd = job.estimated_cost_usd + cost
    else:
        job.prompt_tokens = meter.usage.prompt_tokens
        job.completion_tokens = meter.usage.completion_tokens
        job.total_tokens = meter.usage.total_tokens
        job.generation_ms = meter.elapsed_ms
        job.estimated_cost_usd = cost
