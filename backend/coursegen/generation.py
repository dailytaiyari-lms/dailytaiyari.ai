"""Runs the AI Course Builder's generation, and nothing else.

This module talks to the LLM and produces a **draft**. It never touches the
course tables — that is :mod:`coursegen.apply`, and only after an admin confirms.

Two things it takes seriously:

* **Model choice is the admin's.** Unlike the doubt solver (which uses whichever
  provider is marked active), the course builder lets an admin pick any provider
  they have configured under "AI Features" and any model that provider serves.
  ``resolve_for_admin`` implements exactly that, falling back to the active
  provider when nothing was chosen.
* **A model's JSON is a suggestion.** :func:`extract_json` copes with fences,
  preambles, trailing commas and truncation before the payload is handed to the
  schema normalisers.
"""
from __future__ import annotations

import json
import logging
import re
import time

from django.conf import settings

from chatbot import resolver
from chatbot.models import AIProviderConfig, AIUsageRecord
from chatbot.providers import AIProviderError, ResolvedProvider, Usage, complete

from . import prompts, schema
from .material import existing_material_text
from .models import CourseGenerationJob

logger = logging.getLogger(__name__)

# Course material is long-form: a note plus a five-question quiz for several
# topics does not fit in the 2 000 tokens the chat assistant defaults to.
DEFAULT_MAX_TOKENS = 8000
OUTLINE_MAX_TOKENS = 6000
# Topics per LLM call. Small batches keep each request inside provider limits
# and mean a single bad response only costs one batch.
CONTENT_BATCH_SIZE = 3


class GenerationError(Exception):
    """A generation attempt failed in a way worth showing the admin."""


# ─────────────────────────────────────────────────────────────────────────────
# Provider / model selection
# ─────────────────────────────────────────────────────────────────────────────

def available_models(tenant):
    """Every provider+model the admin may pick for a generation run.

    Each entry pairs a configured provider with its saved model and the catalog
    suggestions for it, so the UI can offer a dropdown without a second call.
    """
    entries = []
    configs = AIProviderConfig.objects.filter(tenant=tenant).order_by('provider')
    for config in configs:
        if not config.is_configured:
            continue
        suggestions = list(dict.fromkeys(
            [config.effective_model] + _model_suggestions(config.provider)
        ))
        entries.append({
            'provider': config.provider,
            'provider_label': config.get_provider_display(),
            'default_model': config.effective_model,
            'models': [m for m in suggestions if m],
            'is_active': config.is_active,
            'allows_custom_model': True,
            'last_test_ok': config.last_test_ok,
        })

    allocation = resolver.get_allocation(tenant)
    granted_model, reason = resolver.platform_available(tenant, allocation)
    if granted_model is not None:
        # Only the models the super admin granted, so an admin cannot spend the
        # platform's money on a model it never agreed to pay for.
        selectable = allocation.selectable_models()
        entries.append({
            'provider': 'platform',
            'provider_label': 'Included DailyTaiyari allowance',
            'default_model': granted_model.model_name,
            'models': [m.model_name for m in selectable],
            'model_labels': {m.model_name: m.display_label for m in selectable},
            'is_active': not any(e['is_active'] for e in entries),
            'allows_custom_model': False,
            'last_test_ok': None,
        })
    elif reason == 'no_models' and allocation.is_enabled and getattr(settings, 'OPENAI_API_KEY', ''):
        # Legacy grant: one env key, one cheap model.
        entries.append({
            'provider': 'platform',
            'provider_label': 'Included DailyTaiyari allowance',
            'default_model': resolver.PLATFORM_MODEL,
            'models': [resolver.PLATFORM_MODEL],
            'is_active': not any(e['is_active'] for e in entries),
            'allows_custom_model': False,
            'last_test_ok': None,
        })
    return entries


def _model_suggestions(provider):
    """Catalog suggestions for a provider (shared with the AI Features screen)."""
    from chatbot.admin_views import _catalog

    for entry in _catalog():
        if entry['id'] == provider:
            return list(entry.get('model_suggestions') or [])
    return []


def resolve_for_admin(tenant, *, provider=None, model=None, max_tokens=DEFAULT_MAX_TOKENS,
                      temperature=None):
    """Build the :class:`ResolvedProvider` for an admin-chosen provider/model.

    ``provider`` of ``None`` (or ``'auto'``) uses the tenant's active provider,
    exactly like the rest of the platform. Raises :class:`GenerationError` with
    an admin-readable message when no usable provider exists.
    """
    ai_settings = resolver.get_ai_settings(tenant)
    if not ai_settings.is_enabled:
        raise GenerationError(
            'AI features are turned off for this academy. Enable them under '
            'Admin → AI Features to use the course builder.'
        )

    wanted = (provider or '').strip() or None
    if wanted in ('auto', ''):
        wanted = None

    if wanted and wanted != 'platform':
        config = AIProviderConfig.objects.filter(tenant=tenant, provider=wanted).first()
        if config is None or not config.is_configured:
            raise GenerationError(
                f'"{wanted}" is not configured for this academy. Add its API key '
                'under Admin → AI Features first.'
            )
        resolved = ResolvedProvider.from_config(config, source=AIUsageRecord.SOURCE_TENANT)
    elif wanted == 'platform':
        resolved = _platform_provider(tenant, model)
    else:
        config = resolver.active_config(tenant)
        if config is not None:
            resolved = ResolvedProvider.from_config(config, source=AIUsageRecord.SOURCE_TENANT)
        else:
            resolved = _platform_provider(tenant, model)

    chosen_model = (model or '').strip()
    # The platform picker has already validated the model against the grant and
    # set it; overriding here would let an admin spend our money on any model.
    if chosen_model and resolved.source != AIUsageRecord.SOURCE_PLATFORM:
        resolved.model = chosen_model
    if not resolved.model:
        raise GenerationError(
            'No model is set for this provider. Choose one under Admin → AI Features.'
        )

    resolved.max_tokens = max_tokens
    # Structure work wants consistency far more than flair.
    resolved.temperature = 0.4 if temperature is None else max(0.0, min(1.5, float(temperature)))
    return resolved


def _platform_provider(tenant, model=None):
    """Resolve a model from the tenant's platform grant.

    ``model`` is only honoured when the super admin actually granted it — the
    course builder lets an admin pick freely from *their own* providers, but the
    included allowance is our bill, so the grant is the hard boundary.
    """
    allocation = resolver.get_allocation(tenant)
    granted_model, reason = resolver.platform_available(tenant, allocation)

    if granted_model is not None:
        wanted = (model or '').strip()
        if wanted:
            match = next(
                (m for m in allocation.selectable_models() if m.model_name == wanted), None
            )
            if match is None:
                raise GenerationError(
                    f'"{wanted}" is not part of your included AI allowance. Pick one '
                    'of the included models, or connect your own provider key.'
                )
            granted_model = match
        return ResolvedProvider.from_platform_model(granted_model)

    if reason == 'exhausted':
        raise GenerationError(
            'Your included AI allowance for this month has run out. Connect your own '
            'AI provider key under Admin → AI Features to continue right away.'
        )

    if reason == 'models_unusable':
        raise GenerationError(
            'The included AI models are temporarily unavailable. Try again shortly, '
            'or connect your own AI provider key under Admin → AI Features.'
        )

    platform_key = getattr(settings, 'OPENAI_API_KEY', '')
    if reason == 'no_models' and allocation.is_enabled and platform_key:
        return ResolvedProvider(
            provider=AIProviderConfig.PROVIDER_OPENAI,
            api_key=platform_key,
            model=resolver.PLATFORM_MODEL,
            source=AIUsageRecord.SOURCE_PLATFORM,
        )

    raise GenerationError(
        'No AI provider is connected yet. Add your OpenAI, Gemini, Claude or '
        'self-hosted endpoint under Admin → AI Features to use the course builder.'
    )


# ─────────────────────────────────────────────────────────────────────────────
# JSON extraction
# ─────────────────────────────────────────────────────────────────────────────

_FENCE = re.compile(r'```(?:json)?\s*(.*?)```', re.DOTALL | re.IGNORECASE)
_TRAILING_COMMA = re.compile(r',\s*([}\]])')


def _scan(text):
    """Walk ``text`` from its first ``{``, tracking bracket depth and strings.

    Returns ``(start, end_or_None, stack, in_string)`` where ``end`` is the index
    just past a complete object, or ``None`` when the text ran out mid-object.
    """
    start = text.find('{')
    if start == -1:
        return None, None, [], False
    stack = []
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in '{[':
            stack.append(char)
        elif char in '}]':
            if stack:
                stack.pop()
            if not stack:
                return start, index + 1, [], False
    return start, None, stack, in_string


def _balanced_object(text):
    """The first complete ``{...}`` in ``text``, brace-counted and string-aware."""
    start, end, _stack, _in_string = _scan(text)
    if start is None or end is None:
        return None
    return text[start:end]


def _repair_truncated(text):
    """Best-effort recovery of an object the model got cut off mid-way through.

    Long course material is exactly the payload that hits a max-tokens ceiling.
    Rather than throw away a note that is 90% written, close the open string and
    brackets — and if that still won't parse, walk back to the last clean item
    boundary and close there.
    """
    start, end, stack, in_string = _scan(text)
    if start is None or end is not None:
        return None

    body = text[start:]
    closers = {'{': '}', '[': ']'}

    def attempt(candidate, open_stack, close_string):
        patched = candidate + ('"' if close_string else '')
        patched += ''.join(closers[b] for b in reversed(open_stack))
        try:
            parsed = json.loads(_TRAILING_COMMA.sub(r'\1', patched))
        except (ValueError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None

    parsed = attempt(body, stack, in_string)
    if parsed is not None:
        return parsed

    # Trim back to successively earlier item boundaries and re-close there.
    for cut in range(len(body) - 1, max(len(body) - 20000, 0), -1):
        if body[cut] not in ',}]':
            continue
        head = body[:cut] if body[cut] == ',' else body[:cut + 1]
        sub_start, sub_end, sub_stack, sub_in_string = _scan(head)
        if sub_start is None or sub_end is not None:
            continue
        parsed = attempt(head, sub_stack, sub_in_string)
        if parsed is not None:
            return parsed
    return None


def extract_json(text):
    """Parse the JSON object out of a model response.

    Handles ``` fences, chatty preambles, trailing commas and truncated output.
    Raises :class:`GenerationError` when nothing parseable is present.
    """
    if not text or not text.strip():
        raise GenerationError('The model returned an empty response. Try generating again.')

    candidates = []
    fenced = _FENCE.findall(text)
    candidates.extend(block.strip() for block in fenced)
    candidates.append(text.strip())
    balanced = _balanced_object(text)
    if balanced:
        candidates.append(balanced)

    for candidate in candidates:
        if not candidate:
            continue
        for attempt in (candidate, _TRAILING_COMMA.sub(r'\1', candidate)):
            try:
                parsed = json.loads(attempt)
            except (ValueError, TypeError):
                continue
            if isinstance(parsed, dict):
                return parsed
            if isinstance(parsed, list):
                return {'topics': parsed}

    # Nothing parsed cleanly — the response was most likely truncated.
    repaired = _repair_truncated(text)
    if repaired is not None:
        logger.info('coursegen: recovered a truncated model response')
        return repaired

    logger.warning('coursegen: unparseable model response (%d chars)', len(text))
    raise GenerationError(
        'The model did not return valid JSON. Try again, or pick a stronger '
        'model for course generation.'
    )


# ─────────────────────────────────────────────────────────────────────────────
# LLM invocation + metering
# ─────────────────────────────────────────────────────────────────────────────

class _Meter:
    """Accumulates usage across the several calls one job may make."""

    def __init__(self):
        self.usage = Usage()
        self.elapsed_ms = 0

    def add(self, usage, elapsed_ms):
        self.usage.prompt_tokens += usage.prompt_tokens
        self.usage.completion_tokens += usage.completion_tokens
        self.usage.total_tokens += usage.total_tokens
        self.elapsed_ms += elapsed_ms


def _call(resolved, system, user, meter, tenant):
    """One completion, metered into ``AIUsageRecord`` like every other AI call."""
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
            feature=AIUsageRecord.FEATURE_COURSEGEN,
        )
        raise GenerationError(str(exc)) from exc

    if not usage.total_tokens and content:
        # Some providers omit usage; approximate so budgets still move.
        approx_out = max(1, len(content) // 4)
        approx_in = max(1, (len(system) + len(user)) // 4)
        usage = Usage(approx_in, approx_out, approx_in + approx_out)

    meter.add(usage, elapsed)
    resolver.record_usage(
        tenant=tenant, student=None, session=None, resolved=resolved,
        usage=usage, response_time_ms=elapsed, was_successful=True,
        feature=AIUsageRecord.FEATURE_COURSEGEN,
    )
    return content


def _check_budget(tenant):
    """Refuse to start when the tenant is already over its monthly token budget."""
    ai_settings = resolver.get_ai_settings(tenant)
    budget = ai_settings.monthly_token_budget
    if not budget:
        return
    used = resolver.tokens_used(
        tenant, resolver.month_start(), source=AIUsageRecord.SOURCE_TENANT
    )
    if used >= budget:
        raise GenerationError(
            'This academy has used its monthly AI token budget. Raise it under '
            'Admin → AI Features to keep generating.'
        )


# ─────────────────────────────────────────────────────────────────────────────
# Curriculum context helpers
# ─────────────────────────────────────────────────────────────────────────────

def outline_text_for(course, limit=120):
    """A compact text rendering of a course's existing tree, for prompt context."""
    if course is None:
        return ''
    lines = []
    for subject in course.subjects.all().order_by('order', 'name'):
        lines.append(f'- {subject.name}')
        for chapter in subject.chapters.all().order_by('order', 'name'):
            lines.append(f'  - {chapter.name}')
            topic_names = list(
                chapter.chapter_topics.select_related('topic')
                .order_by('order')
                .values_list('topic__name', flat=True)[:20]
            )
            for name in topic_names:
                lines.append(f'    - {name}')
            if len(lines) > limit:
                lines.append('    - …')
                return '\n'.join(lines[:limit])
    return '\n'.join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Generators — each returns a normalised draft
# ─────────────────────────────────────────────────────────────────────────────

def generate_outline(job, *, course=None):
    tenant = job.tenant
    _check_budget(tenant)
    resolved = resolve_for_admin(
        tenant, provider=job.provider, model=job.model, max_tokens=OUTLINE_MAX_TOKENS
    )
    meter = _Meter()
    user = prompts.outline_user_prompt(
        brief=job.prompt,
        options=job.options or {},
        course=course,
        existing_outline=outline_text_for(course) if course is not None else '',
    )
    raw = _call(resolved, prompts.OUTLINE_SYSTEM, user, meter, tenant)
    draft = schema.normalize_outline(extract_json(raw), existing_course=course)
    if not draft.get('subjects'):
        raise GenerationError(
            'The model returned an outline with no topics. Try a more specific '
            'brief, or a stronger model.'
        )
    return draft, meter, resolved


def generate_content(job, *, course, topics):
    """Notes + quiz for ``topics`` (a list of ``{'id', 'name', 'code', 'summary',
    'subject_name'}``), generated in small batches and merged into one draft."""
    tenant = job.tenant
    _check_budget(tenant)
    if not topics:
        raise GenerationError('Select at least one topic to write material for.')

    options = job.options or {}
    resolved = resolve_for_admin(
        tenant, provider=job.provider, model=job.model, max_tokens=DEFAULT_MAX_TOKENS
    )
    meter = _Meter()
    context = outline_text_for(course, limit=60)
    # The prompt asks for these; the normaliser enforces them, so a model that
    # volunteers extra material can never overwrite something unrequested.
    wanted_materials = prompts.requested_materials(options)

    merged = []
    failures = []
    batch_size = max(1, int(options.get('batch_size') or CONTENT_BATCH_SIZE))
    for start in range(0, len(topics), batch_size):
        batch = topics[start:start + batch_size]
        user = prompts.content_user_prompt(
            brief=job.prompt,
            options=options,
            course=course,
            subject_name=batch[0].get('subject_name') or course.name,
            topics=batch,
            context=context,
            existing=existing_material_text(batch),
        )
        try:
            raw = _call(resolved, prompts.CONTENT_SYSTEM, user, meter, tenant)
            batch_draft = schema.normalize_content(
                extract_json(raw), requested_topics=batch, materials=wanted_materials,
            )
        except GenerationError as exc:
            # One bad batch must not throw away the batches that succeeded.
            logger.warning('coursegen: content batch failed: %s', exc)
            failures.append({'topics': [t['name'] for t in batch], 'error': str(exc)})
            continue
        merged.extend(batch_draft.get('topics') or [])

    if not merged:
        detail = failures[0]['error'] if failures else 'no usable material was returned'
        raise GenerationError(f'Generation failed — {detail}')

    draft = {'topics': merged, 'stats': schema.content_stats(merged)}
    if failures:
        draft['partial_failures'] = failures
    return draft, meter, resolved


def generate_meta(job, *, course):
    tenant = job.tenant
    _check_budget(tenant)
    resolved = resolve_for_admin(
        tenant, provider=job.provider, model=job.model, max_tokens=4000
    )
    meter = _Meter()
    user = prompts.meta_user_prompt(
        brief=job.prompt,
        options=job.options or {},
        course=course,
        outline_text=outline_text_for(course, limit=60),
    )
    raw = _call(resolved, prompts.META_SYSTEM, user, meter, tenant)
    return schema.normalize_meta(extract_json(raw)), meter, resolved


def refine(job, instruction):
    """Regenerate ``job.draft`` with an admin's correction applied."""
    tenant = job.tenant
    _check_budget(tenant)
    max_tokens = OUTLINE_MAX_TOKENS if job.kind == job.KIND_OUTLINE else DEFAULT_MAX_TOKENS
    resolved = resolve_for_admin(
        tenant, provider=job.provider, model=job.model, max_tokens=max_tokens
    )
    meter = _Meter()

    current = json.dumps(_draft_for_prompt(job), ensure_ascii=False)[:60000]
    user = prompts.refine_user_prompt(instruction=instruction, current_json=current)
    raw = _call(resolved, prompts.SYSTEM_PROMPTS[job.kind], user, meter, tenant)
    payload = extract_json(raw)

    if job.kind == job.KIND_OUTLINE:
        course = job.course
        draft = schema.normalize_outline(payload, existing_course=course)
        if not draft.get('subjects'):
            raise GenerationError('The revised outline had no topics — the change was not applied.')
    elif job.kind == job.KIND_CONTENT:
        requested = [
            {
                'id': entry.get('topic_id'),
                'name': entry.get('topic_name'),
                'code': entry.get('topic_code'),
            }
            for entry in (job.draft or {}).get('topics') or []
        ]
        draft = schema.normalize_content(
            payload,
            requested_topics=requested,
            materials=prompts.requested_materials(job.options),
        )
        if not draft.get('topics'):
            raise GenerationError('The revised material was empty — the change was not applied.')
    else:
        draft = schema.normalize_meta(payload)

    return draft, meter, resolved


def _draft_for_prompt(job):
    """The draft with rendered HTML stripped — the model only needs the blocks."""
    draft = json.loads(json.dumps(job.draft or {}))
    for topic in draft.get('topics') or []:
        (topic.get('note') or {}).pop('html', None)
    (draft.get('course') or {}).pop('description_html', None)
    draft.pop('stats', None)
    return draft


# ─────────────────────────────────────────────────────────────────────────────
# Job orchestration
# ─────────────────────────────────────────────────────────────────────────────

def run_job(job, *, topics=None):
    """Execute ``job``, storing the draft (or the failure) on the row.

    Always leaves the job in a terminal-for-now state: ``preview`` when a draft
    is ready for the admin to review, ``failed`` otherwise. It never writes to
    the course tables.
    """
    job.status = CourseGenerationJob.STATUS_GENERATING
    job.error = ''
    job.save(update_fields=['status', 'error', 'updated_at'])

    try:
        if job.kind == CourseGenerationJob.KIND_OUTLINE:
            draft, meter, resolved = generate_outline(job, course=job.course)
        elif job.kind == CourseGenerationJob.KIND_CONTENT:
            draft, meter, resolved = generate_content(job, course=job.course, topics=topics or [])
        else:
            draft, meter, resolved = generate_meta(job, course=job.course)
    except GenerationError as exc:
        job.status = CourseGenerationJob.STATUS_FAILED
        job.error = str(exc)[:2000]
        job.save(update_fields=['status', 'error', 'updated_at'])
        return job
    except Exception as exc:  # noqa: BLE001 - never leak a stack trace to an admin
        logger.exception('coursegen: unexpected generation failure')
        job.status = CourseGenerationJob.STATUS_FAILED
        job.error = f'Unexpected error while generating: {str(exc)[:300]}'
        job.save(update_fields=['status', 'error', 'updated_at'])
        return job

    _store_result(job, draft, meter, resolved)
    job.record_revision('generated', job.prompt)
    job.save()
    return job


def apply_refinement(job, instruction):
    """Refine an existing draft in place.

    A :class:`GenerationError` propagates untouched and the job keeps its
    previous draft — a failed refine must never cost the admin their draft.
    """
    draft, meter, resolved = refine(job, instruction)
    _store_result(job, draft, meter, resolved, accumulate=True)
    job.record_revision('refined', instruction)
    job.save()
    return job


def _store_result(job, draft, meter, resolved, accumulate=False):
    from chatbot.providers import estimate_cost_usd

    job.draft = draft
    job.status = CourseGenerationJob.STATUS_PREVIEW
    job.error = ''
    job.provider = resolved.provider if resolved.source != AIUsageRecord.SOURCE_PLATFORM else 'platform'
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
