"""Completion callables for the tagging tools: ``call(system, user) -> text``.

Every call goes through ``coursegen.generation._call``, so it is metered into
AIUsageRecord (feature ``itemtag``) like any other AI call.
"""
from chatbot.models import AIUsageRecord, PlatformAIModel
from chatbot.providers import ResolvedProvider, estimate_cost_usd
from coursegen.generation import GenerationError, _Meter, _call

TAGGING_MAX_TOKENS = 8000


class MeteredCall:
    """A completion callable that also keeps tokens and per-call latency."""

    def __init__(self, resolved, tenant, *, feature=AIUsageRecord.FEATURE_ITEMTAG):
        self.resolved = resolved
        self.tenant = tenant
        self.feature = feature
        self.meter = _Meter()
        self.latencies_ms = []

    @property
    def model_ref(self):
        return f'{self.resolved.provider}:{self.resolved.model}'

    def cost_usd(self):
        return estimate_cost_usd(self.resolved.model, self.meter.usage,
                                 getattr(self.resolved, 'platform_model', None))

    def __call__(self, system, user):
        before = self.meter.elapsed_ms
        content = _call(self.resolved, system, user, self.meter, self.tenant, feature=self.feature)
        self.latencies_ms.append(self.meter.elapsed_ms - before)
        return content


def platform_call(model_name, tenant=None, *, max_tokens=TAGGING_MAX_TOKENS):
    """A call on a super-admin platform model (experiments and evaluation)."""
    platform_model = (
        PlatformAIModel.objects.select_related('provider')
        .filter(model_name=model_name, is_enabled=True, provider__is_enabled=True).first()
    )
    if platform_model is None:
        raise GenerationError(f'No enabled platform model named {model_name!r}.')
    return MeteredCall(ResolvedProvider.from_platform_model(platform_model, max_tokens=max_tokens), tenant)


def tenant_tagging_call(tenant):
    """A call on the tenant's tagging model (its own key, else the platform's)."""
    from intelligence.services.tagging import _resolve_tagging_model

    resolved = _resolve_tagging_model(tenant)
    # Stage-2 replies for 12 questions need more room than v1's 4000 tokens.
    resolved.max_tokens = max(resolved.max_tokens or 0, TAGGING_MAX_TOKENS)
    return MeteredCall(resolved, tenant)


def budget_status(tenant):
    """The tenant's monthly token budget on its own key (None = no budget)."""
    from chatbot import resolver

    budget = resolver.get_ai_settings(tenant).monthly_token_budget or None
    used = resolver.tokens_used(tenant, resolver.month_start(), source=AIUsageRecord.SOURCE_TENANT)
    return {
        'monthly_budget': budget,
        'used': used,
        'remaining': max(0, budget - used) if budget else None,
        'exhausted': bool(budget) and used >= budget,
    }
