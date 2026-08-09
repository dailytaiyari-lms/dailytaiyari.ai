"""Picks which LLM answers a request, and enforces the spend guardrails.

Resolution order for a tenant:

1. Its own active, fully-configured :class:`~chatbot.models.AIProviderConfig`
   → billed to the tenant, capped only by the tenant's own budget.
2. A model the super admin granted it from the platform's own accounts
   (:class:`~chatbot.models.TenantAIAllocation`) → billed to *us*, and therefore
   capped on both tokens and dollars. This is the path for the non-technical
   academy that will never obtain an API key of its own.
3. The legacy single platform key (``settings.OPENAI_API_KEY``), kept so
   deployments that predate platform providers keep working unchanged.

Allocations are disabled by default, so an unconfigured tenant costs the
platform nothing and simply gets a clear "ask your admin to connect an AI
provider" message.

Every successful call is metered into :class:`~chatbot.models.AIUsageRecord`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from .models import AIProviderConfig, AISettings, AIUsageRecord, TenantAIAllocation
from .providers import ResolvedProvider, Usage, estimate_cost_usd

logger = logging.getLogger(__name__)

# Model used when falling back to the *legacy* single platform key. Kept cheap
# on purpose. Superseded by PlatformAIModel rows wherever those exist.
PLATFORM_MODEL = getattr(settings, 'AI_PLATFORM_MODEL', 'gpt-4o-mini')


class AIUnavailable(Exception):
    """No usable provider. ``reason`` is a code the frontend can branch on."""

    def __init__(self, message, reason='not_configured'):
        super().__init__(message)
        self.message = message
        self.reason = reason


@dataclass
class Resolution:
    """The provider chosen for a request plus the settings that shaped it."""

    provider: ResolvedProvider
    settings_obj: AISettings


def month_start(now=None):
    now = now or timezone.now()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def get_ai_settings(tenant) -> AISettings:
    """The tenant's AI settings row, created with defaults on first access."""
    obj, _created = AISettings.objects.get_or_create(tenant=tenant)
    return obj


def tokens_used(tenant, since, source=None):
    qs = AIUsageRecord.objects.filter(tenant=tenant, created_at__gte=since)
    if source:
        qs = qs.filter(source=source)
    return qs.aggregate(total=Sum('total_tokens'))['total'] or 0


def cost_used(tenant, since, source=None):
    """USD spent by a tenant in the window, as metered at call time."""
    qs = AIUsageRecord.objects.filter(tenant=tenant, created_at__gte=since)
    if source:
        qs = qs.filter(source=source)
    return float(qs.aggregate(total=Sum('estimated_cost_usd'))['total'] or 0)


def get_allocation(tenant) -> TenantAIAllocation:
    """The tenant's platform-model allocation, created (disabled) on demand."""
    obj, _created = TenantAIAllocation.objects.get_or_create(tenant=tenant)
    return obj


def allocation_status(tenant, allocation=None):
    """Everything the UI and the guardrails need about this month's platform use.

    Returns token and cost ceilings alongside consumption, plus a single
    ``percent_used`` that is the *worst* of the two axes — that is the number a
    tenant admin should be warned on, since either one can stop their AI.
    """
    allocation = allocation or get_allocation(tenant)
    since = month_start()
    tokens = tokens_used(tenant, since, source=AIUsageRecord.SOURCE_PLATFORM)
    cost = cost_used(tenant, since, source=AIUsageRecord.SOURCE_PLATFORM)

    token_limit = allocation.monthly_token_limit or 0
    cost_limit = float(allocation.monthly_cost_limit_usd or 0)

    percents = []
    if token_limit:
        percents.append(tokens / token_limit * 100)
    if cost_limit:
        percents.append(cost / cost_limit * 100)
    percent = min(100.0, round(max(percents), 1)) if percents else 0.0

    return {
        'is_enabled': allocation.is_enabled,
        'tokens_used': tokens,
        'token_limit': token_limit,
        'tokens_remaining': max(0, token_limit - tokens) if token_limit else None,
        'cost_used_usd': round(cost, 4),
        'cost_limit_usd': cost_limit,
        'cost_remaining_usd': round(max(0.0, cost_limit - cost), 4) if cost_limit else None,
        'percent_used': percent,
        'is_exhausted': bool(
            (token_limit and tokens >= token_limit) or (cost_limit and cost >= cost_limit)
        ),
    }


def platform_allowance(tenant):
    """``(granted, used, remaining)`` platform tokens for this calendar month.

    Retained with its original shape because the tenant admin usage panel and
    the course builder both read it. Token ceilings now live on the allocation;
    the legacy tenant field is honoured only until a super admin sets one.
    """
    allocation = get_allocation(tenant)
    granted = allocation.monthly_token_limit or 0
    if not allocation.is_enabled:
        # An allocation the super admin has switched off grants nothing, even
        # if a stale ceiling is still stored on it.
        granted = 0
    used = tokens_used(tenant, month_start(), source=AIUsageRecord.SOURCE_PLATFORM)
    return granted, used, max(0, granted - used)


def active_config(tenant):
    """The tenant's active provider config, or ``None``."""
    for config in AIProviderConfig.objects.filter(tenant=tenant, is_active=True):
        if config.is_configured:
            return config
    return None


def check_student_quota(student, tenant, ai_settings=None):
    """Raise :class:`AIUnavailable` when the student hit their daily message cap."""
    ai_settings = ai_settings or get_ai_settings(tenant)
    limit = ai_settings.student_daily_message_limit
    if not limit:
        return
    since = timezone.now() - timedelta(days=1)
    used = AIUsageRecord.objects.filter(
        student=student, created_at__gte=since, was_successful=True
    ).count()
    if used >= limit:
        raise AIUnavailable(
            f'You have reached your daily limit of {limit} AI messages. '
            'It resets 24 hours after your first message today.',
            reason='student_limit',
        )


def platform_available(tenant, allocation=None):
    """``(model, reason)`` — the granted model to use, or why there isn't one.

    ``reason`` is ``''`` on success and otherwise one of ``not_granted``,
    ``no_models`` or ``exhausted``. Callers that merely want to *offer* platform
    models (the course builder dropdown, the admin panel) use this too, so the
    "can I?" question is answered in exactly one place.
    """
    allocation = allocation or get_allocation(tenant)
    if not allocation.is_enabled:
        return None, 'not_granted'
    status = allocation_status(tenant, allocation)
    if status['is_exhausted']:
        return None, 'exhausted'
    model = allocation.effective_model()
    if model is None:
        # 'no_models' means nothing was ever granted — a legacy grant, which may
        # still fall back to the env key. 'models_unusable' means the super admin
        # granted models and then disabled or unconfigured them, which must stop
        # the tenant rather than quietly bill a different account.
        if allocation.granted_models.exists():
            return None, 'models_unusable'
        return None, 'no_models'
    return model, ''


def _legacy_platform_provider(tenant, allocation):
    """The pre-allocation fallback: one env key, one cheap model.

    Only reachable when the super admin enabled the allocation but granted no
    models — which is exactly the state every tenant migrated from the old
    ``ai_platform_monthly_tokens`` grant lands in.
    """
    key = getattr(settings, 'OPENAI_API_KEY', '')
    if not key or not allocation.is_enabled:
        return None
    return ResolvedProvider(
        provider=AIProviderConfig.PROVIDER_OPENAI,
        api_key=key,
        model=PLATFORM_MODEL,
        temperature=0.7,
        max_tokens=1500,
        source=AIUsageRecord.SOURCE_PLATFORM,
    )


def resolve(tenant, student=None) -> Resolution:
    """Choose the provider for this tenant, enforcing every guardrail.

    Raises :class:`AIUnavailable` with a student-friendly message when the AI
    cannot be used (disabled, unconfigured, or out of budget).
    """
    if tenant is None:
        raise AIUnavailable(
            'The AI assistant is not available on this workspace.', reason='no_tenant'
        )

    ai_settings = get_ai_settings(tenant)
    if not ai_settings.is_enabled:
        raise AIUnavailable(
            'The AI assistant has been turned off by your institute.', reason='disabled'
        )

    if student is not None:
        check_student_quota(student, tenant, ai_settings)

    config = active_config(tenant)
    if config is not None:
        # The tenant's own monthly budget guards their spend, not the platform's.
        budget = ai_settings.monthly_token_budget
        if budget:
            used = tokens_used(tenant, month_start(), source=AIUsageRecord.SOURCE_TENANT)
            if used >= budget:
                raise AIUnavailable(
                    'Your institute has used its AI budget for this month. '
                    'Please ask an administrator to raise it.',
                    reason='tenant_budget',
                )
        return Resolution(
            provider=ResolvedProvider.from_config(config, source=AIUsageRecord.SOURCE_TENANT),
            settings_obj=ai_settings,
        )

    # No tenant key → the platform pays, so only proceed within an explicit grant.
    allocation = get_allocation(tenant)
    model, reason = platform_available(tenant, allocation)
    if model is not None:
        return Resolution(
            provider=ResolvedProvider.from_platform_model(model),
            settings_obj=ai_settings,
        )

    if reason == 'no_models':
        legacy = _legacy_platform_provider(tenant, allocation)
        if legacy is not None:
            return Resolution(provider=legacy, settings_obj=ai_settings)

    if reason == 'exhausted':
        raise AIUnavailable(
            'The included AI allowance for this month has run out. Your institute '
            'can connect its own AI provider key to continue right away.',
            reason='platform_exhausted',
        )

    if reason == 'models_unusable':
        raise AIUnavailable(
            'The included AI models are temporarily unavailable. Please try again '
            'shortly, or ask your institute to connect its own AI provider key.',
            reason='platform_unavailable',
        )

    raise AIUnavailable(
        'The AI assistant has not been set up yet. Ask your institute admin to '
        'connect an AI provider under Admin → AI Features.',
        reason='not_configured',
    )


def record_usage(
    *,
    tenant,
    student,
    session,
    resolved: ResolvedProvider,
    usage: Usage,
    response_time_ms=0,
    was_successful=True,
    error_message='',
    feature=AIUsageRecord.FEATURE_CHAT,
):
    """Persist one metered call. Never raises — metering must not break chat."""
    try:
        record = AIUsageRecord.objects.create(
            tenant=tenant,
            student=student,
            session=session,
            source=resolved.source,
            provider=resolved.provider,
            model=resolved.model,
            platform_model=getattr(resolved, 'platform_model', None),
            feature=feature,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
            estimated_cost_usd=estimate_cost_usd(
                resolved.model, usage, platform_model=getattr(resolved, 'platform_model', None)
            ),
            response_time_ms=response_time_ms,
            was_successful=was_successful,
            error_message=error_message[:500],
        )
    except Exception:  # noqa: BLE001 - metering is best-effort
        return None

    if resolved.source == AIUsageRecord.SOURCE_PLATFORM and tenant is not None:
        maybe_warn_allowance(tenant)
    return record


def maybe_warn_allowance(tenant):
    """Tell the tenant's admins when their included allowance is running out.

    Fires at most twice a month — once when usage crosses the configured warning
    threshold and once at exhaustion — because a nag on every message would be
    worse than no warning at all. Never raises: a notification failure must not
    fail the AI call that triggered it.
    """
    try:
        allocation = get_allocation(tenant)
        if not allocation.is_enabled:
            return
        status = allocation_status(tenant, allocation)
        if not (status['token_limit'] or status['cost_limit_usd']):
            return  # unlimited: nothing to run out of

        threshold = allocation.notify_at_percent or 0
        percent = status['percent_used']
        stage = 100 if status['is_exhausted'] else (threshold if threshold and percent >= threshold else 0)
        if not stage:
            return

        period = timezone.now().strftime('%Y-%m')
        if allocation.last_notified_period == period and allocation.last_notified_percent >= stage:
            return

        from notifications import services as notification_services

        notification_services.on_ai_allowance_warning(tenant, status, exhausted=stage == 100)

        allocation.last_notified_period = period
        allocation.last_notified_percent = stage
        allocation.save(update_fields=[
            'last_notified_period', 'last_notified_percent', 'updated_at',
        ])
    except Exception:  # noqa: BLE001 - warnings must never break a chat reply
        logger.exception('Failed to evaluate AI allowance warning for tenant %s',
                         getattr(tenant, 'id', None))


def usage_summary(tenant, days=30):
    """Aggregates for the admin "AI Features" usage panel."""
    since = timezone.now() - timedelta(days=days)
    window = AIUsageRecord.objects.filter(tenant=tenant, created_at__gte=since)
    totals = window.aggregate(
        total_tokens=Sum('total_tokens'),
        prompt_tokens=Sum('prompt_tokens'),
        completion_tokens=Sum('completion_tokens'),
        cost=Sum('estimated_cost_usd'),
    )
    granted, used, remaining = platform_allowance(tenant)
    return {
        'days': days,
        'messages': window.count(),
        'active_students': window.exclude(student=None).values('student').distinct().count(),
        'total_tokens': totals['total_tokens'] or 0,
        'prompt_tokens': totals['prompt_tokens'] or 0,
        'completion_tokens': totals['completion_tokens'] or 0,
        'estimated_cost_usd': float(totals['cost'] or 0),
        'month_tokens': tokens_used(tenant, month_start()),
        'platform_grant_tokens': granted,
        'platform_used_tokens': used,
        'platform_remaining_tokens': remaining,
        # Tenant-facing: the dollar figures are what the *platform* pays and
        # are deliberately withheld. Tenants see tokens and percent only.
        'allocation': {
            k: v for k, v in allocation_status(tenant).items()
            if not k.startswith('cost_')
        },
    }
