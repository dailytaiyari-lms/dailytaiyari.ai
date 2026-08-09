"""Tenant-admin endpoints for the "AI Features" screen.

Scoped to the tenant resolved by ``TenantMiddleware`` from the ``X-Tenant-ID``
header and restricted to the ``admin`` role. Covers three things:

* provider credentials (bring your own OpenAI / Azure / Gemini / Claude /
  open-source endpoint) and a "test connection" probe,
* behaviour + spend guardrails,
* a usage/cost report, including whatever platform-key allowance the super
  admin has granted this tenant.
"""
from django.db import transaction
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import IsTenantAdmin

from . import resolver
from .admin_serializers import AIProviderConfigSerializer, AISettingsSerializer
from .models import AIProviderConfig
from .providers import ResolvedProvider, test_connection
from .tenancy import request_tenant


class _TenantScopedView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsTenantAdmin]

    def tenant(self):
        return request_tenant(self.request)


def _catalog():
    """Provider metadata the admin UI renders its form from.

    Keeping this server-side means adding a provider is a backend-only change.
    """
    docs = {
        AIProviderConfig.PROVIDER_OPENAI: 'https://platform.openai.com/api-keys',
        AIProviderConfig.PROVIDER_AZURE: 'https://portal.azure.com',
        AIProviderConfig.PROVIDER_GEMINI: 'https://aistudio.google.com/apikey',
        AIProviderConfig.PROVIDER_ANTHROPIC: 'https://console.anthropic.com/settings/keys',
        AIProviderConfig.PROVIDER_GROQ: 'https://console.groq.com/keys',
        AIProviderConfig.PROVIDER_OPENROUTER: 'https://openrouter.ai/keys',
        AIProviderConfig.PROVIDER_TOGETHER: 'https://api.together.ai/settings/api-keys',
        AIProviderConfig.PROVIDER_OLLAMA: 'https://ollama.com/download',
        AIProviderConfig.PROVIDER_CUSTOM: '',
    }
    blurbs = {
        AIProviderConfig.PROVIDER_OPENAI: 'Paid, highest quality. GPT-4o mini is the cheapest good option.',
        AIProviderConfig.PROVIDER_AZURE: 'Your own Azure OpenAI deployment — enterprise billing and data residency.',
        AIProviderConfig.PROVIDER_GEMINI: 'Google AI Studio keys include a generous free tier — a good zero-cost start.',
        AIProviderConfig.PROVIDER_ANTHROPIC: 'Claude models. Strong at long, careful explanations.',
        AIProviderConfig.PROVIDER_GROQ: 'Runs open-source models (Llama, Mixtral) very fast, with a free tier.',
        AIProviderConfig.PROVIDER_OPENROUTER: 'One key for many models, including several free open-source ones (names ending in :free).',
        AIProviderConfig.PROVIDER_TOGETHER: 'Hosted open-source models, including a free Llama endpoint.',
        AIProviderConfig.PROVIDER_OLLAMA: 'Fully free and private: run Llama/Mistral/Qwen on your own server. No API key needed.',
        AIProviderConfig.PROVIDER_CUSTOM: 'Any other OpenAI-compatible endpoint (vLLM, LM Studio, LiteLLM…).',
    }
    suggestions = {
        AIProviderConfig.PROVIDER_OPENAI: ['gpt-4o-mini', 'gpt-4.1-mini', 'gpt-4o'],
        AIProviderConfig.PROVIDER_AZURE: [],
        AIProviderConfig.PROVIDER_GEMINI: ['gemini-2.0-flash', 'gemini-2.5-flash'],
        AIProviderConfig.PROVIDER_ANTHROPIC: ['claude-3-5-haiku-latest', 'claude-sonnet-4-0'],
        AIProviderConfig.PROVIDER_GROQ: ['llama-3.3-70b-versatile', 'llama-3.1-8b-instant'],
        AIProviderConfig.PROVIDER_OPENROUTER: [
            'meta-llama/llama-3.3-70b-instruct:free',
            'deepseek/deepseek-chat-v3-0324:free',
            'qwen/qwen3-8b:free',
        ],
        AIProviderConfig.PROVIDER_TOGETHER: ['meta-llama/Llama-3.3-70B-Instruct-Turbo-Free'],
        AIProviderConfig.PROVIDER_OLLAMA: ['llama3.1', 'mistral', 'qwen2.5'],
        AIProviderConfig.PROVIDER_CUSTOM: [],
    }
    return [
        {
            'id': key,
            'label': label,
            'description': blurbs.get(key, ''),
            'default_base_url': AIProviderConfig.DEFAULT_BASE_URLS.get(key, ''),
            'default_model': AIProviderConfig.DEFAULT_MODELS.get(key, ''),
            'model_suggestions': suggestions.get(key, []),
            'requires_api_key': key not in AIProviderConfig.KEYLESS_PROVIDERS,
            'requires_base_url': key in (
                AIProviderConfig.PROVIDER_AZURE,
                AIProviderConfig.PROVIDER_CUSTOM,
                AIProviderConfig.PROVIDER_OLLAMA,
            ),
            'uses_api_version': key == AIProviderConfig.PROVIDER_AZURE,
            'is_open_source': key in (
                AIProviderConfig.PROVIDER_GROQ,
                AIProviderConfig.PROVIDER_OPENROUTER,
                AIProviderConfig.PROVIDER_TOGETHER,
                AIProviderConfig.PROVIDER_OLLAMA,
            ),
            'docs_url': docs.get(key, ''),
        }
        for key, label in AIProviderConfig.PROVIDER_CHOICES
    ]


class AIProviderView(_TenantScopedView):
    """Manage the tenant's providers (one row per provider, one active).

    * ``GET``    — providers, catalog, settings, usage and the platform grant.
    * ``PUT``    — create/update the provider named in the body.
    * ``DELETE`` — remove the provider named in ``?provider=``.
    """

    def _configs(self):
        return AIProviderConfig.objects.filter(tenant=self.tenant())

    def _payload(self):
        tenant = self.tenant()
        configs = self._configs().order_by('provider')
        data = AIProviderConfigSerializer(configs, many=True).data
        active = next((c['provider'] for c in data if c.get('is_active')), None)
        included = _included_payload(tenant)
        return {
            'providers': data,
            'active_provider': active,
            'catalog': _catalog(),
            'settings': AISettingsSerializer(resolver.get_ai_settings(tenant)).data,
            'platform_fallback': included['legacy_shape'],
            'included': included['included'],
            'is_ready': bool(active) or included['included']['is_available'],
        }

    def get(self, request, *args, **kwargs):
        return Response(self._payload())

    def put(self, request, *args, **kwargs):
        tenant = self.tenant()
        provider = request.data.get('provider')
        if not provider:
            return Response({'provider': ['This field is required.']}, status=400)

        existing = self._configs().filter(provider=provider).first()
        serializer = AIProviderConfigSerializer(
            existing, data=request.data, partial=existing is not None
        )
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            instance = serializer.save(tenant=tenant)
            if instance.is_active:
                self._configs().exclude(pk=instance.pk).update(is_active=False)
        return Response(self._payload())

    def delete(self, request, *args, **kwargs):
        provider = request.query_params.get('provider') or request.data.get('provider')
        config = self._configs().filter(provider=provider).first()
        if config is not None:
            config.delete()
        return Response(self._payload())


class AIProviderTestView(_TenantScopedView):
    """Send a tiny prompt through a provider to verify it really works.

    Accepts an inline ``api_key`` so an admin can validate credentials before
    saving them; otherwise the stored key for ``provider`` is used.
    """

    def post(self, request, *args, **kwargs):
        tenant = self.tenant()
        provider = request.data.get('provider')
        if not provider:
            return Response({'provider': ['This field is required.']}, status=400)

        stored = AIProviderConfig.objects.filter(tenant=tenant, provider=provider).first()
        api_key = request.data.get('api_key') or (stored.api_key if stored else '')
        base_url = (
            request.data.get('base_url')
            or (stored.base_url if stored else '')
            or AIProviderConfig.DEFAULT_BASE_URLS.get(provider, '')
        )
        model = (
            request.data.get('model')
            or (stored.model if stored else '')
            or AIProviderConfig.DEFAULT_MODELS.get(provider, '')
        )
        if not model:
            return Response({'model': ['Choose a model to test.']}, status=400)
        if provider not in AIProviderConfig.KEYLESS_PROVIDERS and not api_key:
            return Response({'api_key': ['Add an API key to test this provider.']}, status=400)

        ok, message = test_connection(
            ResolvedProvider(
                provider=provider,
                api_key=api_key,
                base_url=base_url,
                model=model,
                api_version=request.data.get('api_version')
                or (stored.api_version if stored else '2024-10-21'),
            )
        )

        if stored is not None:
            stored.last_tested_at = timezone.now()
            stored.last_test_ok = ok
            stored.last_test_error = '' if ok else message[:500]
            stored.save(update_fields=['last_tested_at', 'last_test_ok', 'last_test_error'])

        return Response(
            {'ok': ok, 'message': message},
            status=status.HTTP_200_OK if ok else status.HTTP_400_BAD_REQUEST,
        )


class AISettingsView(generics.RetrieveUpdateAPIView):
    """GET / PATCH the tenant's AI behaviour and guardrails."""

    serializer_class = AISettingsSerializer
    permission_classes = [permissions.IsAuthenticated, IsTenantAdmin]

    def get_object(self):
        return resolver.get_ai_settings(request_tenant(self.request))


class AIUsageView(_TenantScopedView):
    """Usage + estimated cost for the last ``?days=`` (default 30) days."""

    def get(self, request, *args, **kwargs):
        from datetime import timedelta

        from django.db.models import Count, Sum

        from .models import AIUsageRecord

        tenant = self.tenant()
        try:
            days = max(1, min(365, int(request.query_params.get('days', 30))))
        except (TypeError, ValueError):
            days = 30

        summary = resolver.usage_summary(tenant, days=days)
        since = timezone.now() - timedelta(days=days)

        # Only the tenant's own providers are broken out by model. Everything
        # run on the included allowance collapses into one unnamed row: which
        # models we use, and what we pay for them, is not theirs to see — and
        # naming them here would undo the whole point of the included panel.
        by_model = (
            AIUsageRecord.objects.filter(
                tenant=tenant, created_at__gte=since, source=AIUsageRecord.SOURCE_TENANT,
            )
            .values('provider', 'model')
            .annotate(
                messages=Count('id'),
                tokens=Sum('total_tokens'),
                cost=Sum('estimated_cost_usd'),
            )
            .order_by('-tokens')[:10]
        )
        rows = [
            {
                'provider': row['provider'],
                'model': row['model'],
                'messages': row['messages'],
                'tokens': row['tokens'] or 0,
                'estimated_cost_usd': float(row['cost'] or 0),
            }
            for row in by_model
        ]
        included = AIUsageRecord.objects.filter(
            tenant=tenant, created_at__gte=since, source=AIUsageRecord.SOURCE_PLATFORM,
        ).aggregate(messages=Count('id'), tokens=Sum('total_tokens'))
        if included['messages']:
            rows.append({
                'provider': 'included',
                'model': 'Included AI',
                'messages': included['messages'],
                'tokens': included['tokens'] or 0,
                'estimated_cost_usd': None,
            })
        summary['by_model'] = sorted(rows, key=lambda r: r['tokens'], reverse=True)
        summary['failures'] = AIUsageRecord.objects.filter(
            tenant=tenant, created_at__gte=since, was_successful=False
        ).count()
        return Response(summary)


# ─────────────────────────────────────────────────────────────────────────────
# Included (platform-supplied) models
# ─────────────────────────────────────────────────────────────────────────────

def _included_payload(tenant):
    """What the tenant gets from the platform's own LLMs — deliberately vague.

    A tenant is told *that* AI is included and how much of the allowance is
    left, never which models sit behind it or what they cost. Naming them would
    turn our operational choices into a promise: we could no longer retire a
    model, reprice one, or fail over to another without an academy noticing and
    asking why. An academy that needs a specific model connects its own key,
    which always wins.
    """
    allocation = resolver.get_allocation(tenant)
    status_ = resolver.allocation_status(tenant, allocation)
    chain = allocation.candidate_models()

    # A tenant with a granted-but-model-less allocation is on the legacy single
    # platform key, which still works and should still read as available.
    is_available = bool(
        allocation.is_enabled and not status_['is_exhausted']
        and (chain or allocation.granted_models.count() == 0)
    )

    return {
        'included': {
            'is_enabled': allocation.is_enabled,
            'is_available': is_available,
            'is_exhausted': status_['is_exhausted'],
            'percent_used': status_['percent_used'],
            'tokens_used': status_['tokens_used'],
            'token_limit': status_['token_limit'],
            'tokens_remaining': status_['tokens_remaining'],
            # Count only, never identity: enough to explain that a second model
            # stands ready if the first has a bad day.
            'model_count': len(chain),
        },
        'legacy_shape': {
            'granted_tokens': status_['token_limit'],
            'used_tokens': status_['tokens_used'],
            'remaining_tokens': status_['tokens_remaining'],
            'is_available': is_available,
        },
    }


class IncludedAIView(_TenantScopedView):
    """Read-only status of the AI we include for this tenant.

    There is nothing to configure: the academy either uses what we provide or
    connects its own key. Keeping this read-only is the point — it is the
    difference between an admin screen a non-technical owner can ignore and one
    they can break.
    """

    def get(self, request, *args, **kwargs):
        return Response(_included_payload(self.tenant())['included'])
