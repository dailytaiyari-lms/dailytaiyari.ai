"""Runs the AI Notebook Builder's generation, and nothing else.

This talks to the LLM and produces a **draft**. It never writes to the notebook
tables — that is :mod:`notebooks.aigen.apply`, and only after an admin confirms.

It reuses the platform LLM plumbing the Course Builder already established
(provider/model resolution, robust JSON extraction, budget checks, usage
metering) from :mod:`coursegen.generation`, so notebook generation bills and
resolves models exactly like every other AI feature — only the prompts, the
schema and the metering ``feature`` differ.
"""
from __future__ import annotations

import logging
import time

from chatbot import resolver
from chatbot.models import AIUsageRecord
from chatbot.providers import AIProviderError, Usage, complete, estimate_cost_usd

# Shared, provider-agnostic helpers — identical needs to the course builder.
from coursegen.generation import (
    GenerationError,
    _Meter,
    _check_budget,
    available_models,
    extract_json,
    resolve_for_admin,
)

from ..models import NotebookGenerationJob
from . import prompts, schema

logger = logging.getLogger(__name__)

# A full graded notebook (setup + several answer cells + tests) is long-form.
NOTEBOOK_MAX_TOKENS = 8000

__all__ = ['GenerationError', 'available_models', 'run_job', 'apply_refinement']


def _call(resolved, system, user, meter, tenant):
    """One completion, metered into AIUsageRecord under the notebook feature."""
    messages = [
        {'role': 'system', 'content': system},
        {'role': 'user', 'content': user},
    ]
    started = time.time()
    try:
        content, usage, elapsed = complete(resolved, messages)
    except AIProviderError as exc:
        resolver.record_usage(
            tenant=tenant, student=None, session=None, resolved=resolved,
            usage=Usage(), response_time_ms=int((time.time() - started) * 1000),
            was_successful=False, error_message=str(exc),
            feature=AIUsageRecord.FEATURE_NOTEBOOKGEN,
        )
        raise GenerationError(str(exc)) from exc

    if not usage.total_tokens and content:
        approx_out = max(1, len(content) // 4)
        approx_in = max(1, (len(system) + len(user)) // 4)
        usage = Usage(approx_in, approx_out, approx_in + approx_out)

    meter.add(usage, elapsed)
    resolver.record_usage(
        tenant=tenant, student=None, session=None, resolved=resolved,
        usage=usage, response_time_ms=elapsed, was_successful=True,
        feature=AIUsageRecord.FEATURE_NOTEBOOKGEN,
    )
    return content


def _is_graded(job):
    return bool((job.options or {}).get('graded', True))


def _generate(job):
    """Produce a fresh draft for ``job`` (does not persist)."""
    tenant = job.tenant
    _check_budget(tenant)
    resolved = resolve_for_admin(
        tenant, provider=job.provider, model=job.model, max_tokens=NOTEBOOK_MAX_TOKENS,
    )
    meter = _Meter()
    user = prompts.notebook_user_prompt(
        brief=job.prompt,
        options=job.options or {},
        topic=job.topic,
        subject_name=job.subject.name if job.subject_id else '',
        course_name=job.course.name if job.course_id else '',
    )
    raw = _call(resolved, prompts.NOTEBOOK_SYSTEM, user, meter, tenant)
    try:
        draft = schema.normalize_draft(extract_json(raw), graded=_is_graded(job))
    except schema.DraftError as exc:
        raise GenerationError(str(exc)) from exc
    return draft, meter, resolved


def _refine(job, instruction):
    """Revise the existing draft in place (does not persist)."""
    tenant = job.tenant
    _check_budget(tenant)
    resolved = resolve_for_admin(
        tenant, provider=job.provider, model=job.model, max_tokens=NOTEBOOK_MAX_TOKENS,
    )
    meter = _Meter()
    user = prompts.refine_user_prompt(draft=job.draft or {}, instruction=instruction)
    raw = _call(resolved, prompts.NOTEBOOK_SYSTEM, user, meter, tenant)
    try:
        draft = schema.normalize_draft(extract_json(raw), graded=_is_graded(job))
    except schema.DraftError as exc:
        raise GenerationError(str(exc)) from exc
    return draft, meter, resolved


def _store_result(job, draft, meter, resolved, *, accumulate=False):
    job.draft = draft
    job.status = NotebookGenerationJob.STATUS_PREVIEW
    job.error = ''
    job.provider = (
        resolved.provider if resolved.source != AIUsageRecord.SOURCE_PLATFORM else 'platform'
    )
    job.model = resolved.model
    cost = _decimal(estimate_cost_usd(resolved.model, meter.usage))
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


def run_job(job):
    """Execute a fresh generation for ``job``, storing the draft or the failure.

    Always leaves the job in ``preview`` (draft ready) or ``failed``. Never
    writes to the notebook tables.
    """
    job.status = NotebookGenerationJob.STATUS_GENERATING
    job.error = ''
    job.save(update_fields=['status', 'error', 'updated_at'])
    try:
        draft, meter, resolved = _generate(job)
    except GenerationError as exc:
        job.status = NotebookGenerationJob.STATUS_FAILED
        job.error = str(exc)[:2000]
        job.save(update_fields=['status', 'error', 'updated_at'])
        return job
    except Exception as exc:  # noqa: BLE001 - never leak a stack trace to an admin
        logger.exception('notebookgen: unexpected generation failure')
        job.status = NotebookGenerationJob.STATUS_FAILED
        job.error = f'Unexpected error while generating: {str(exc)[:300]}'
        job.save(update_fields=['status', 'error', 'updated_at'])
        return job

    _store_result(job, draft, meter, resolved)
    job.record_revision('generated', job.prompt)
    job.save()
    return job


def apply_refinement(job, instruction):
    """Refine an existing draft in place; a failure keeps the previous draft."""
    job.status = NotebookGenerationJob.STATUS_GENERATING
    job.error = ''
    job.save(update_fields=['status', 'error', 'updated_at'])
    try:
        draft, meter, resolved = _refine(job, instruction)
    except GenerationError as exc:
        # Restore the reviewable draft so a failed refine never costs it.
        job.status = NotebookGenerationJob.STATUS_PREVIEW
        job.error = str(exc)[:2000]
        job.save(update_fields=['status', 'error', 'updated_at'])
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception('notebookgen: unexpected refine failure')
        job.status = NotebookGenerationJob.STATUS_PREVIEW
        job.error = f'Unexpected error while refining: {str(exc)[:300]}'
        job.save(update_fields=['status', 'error', 'updated_at'])
        raise GenerationError(job.error)

    _store_result(job, draft, meter, resolved, accumulate=True)
    job.record_revision('refined', instruction)
    job.save()
    return job


def _decimal(value):
    from decimal import Decimal
    try:
        return Decimal(str(value or 0))
    except Exception:  # noqa: BLE001
        return Decimal('0')
