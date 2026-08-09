"""Tests for platform-supplied LLMs.

The feature exists so a non-technical academy gets working AI without ever
touching an API key — but it spends *our* money, so the interesting cases are
all about boundaries: what a tenant may use, when it must stop, and who gets
told. The LLM itself is never called here; what is under test is the resolution
and accounting around it.
"""
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.models import Tenant
from notifications.models import Notification
from users.models import User

from .models import (
    AIProviderConfig,
    AISettings,
    AIUsageRecord,
    PlatformAIModel,
    PlatformAIProvider,
    TenantAIAllocation,
)
from . import providers
from .providers import Usage, estimate_cost_usd
from . import resolver

SUPER = '/api/v1/superadmin'
TENANT_AI = '/api/v1/tenant-admin/ai'


class _PlatformAICase(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name='Alpha Academy', is_active=True)
        self.other_tenant = Tenant.objects.create(name='Beta Academy', is_active=True)

        self.superadmin = User.objects.create_user(
            email='root@platform.test', password='pw12345!', is_superuser=True,
            is_staff=True, role='admin',
        )
        self.admin = User.objects.create_user(
            email='admin@alpha.test', password='pw12345!', role='admin',
            tenant=self.tenant,
        )

        self.account = PlatformAIProvider.objects.create(
            name='Platform OpenAI', provider=AIProviderConfig.PROVIDER_OPENAI,
        )
        self.account.api_key = 'sk-platform-secret-key'
        self.account.save()

        self.cheap = PlatformAIModel.objects.create(
            provider=self.account, model_name='gpt-4o-mini', label='Fast',
            input_cost_per_million=Decimal('0.15'),
            output_cost_per_million=Decimal('0.60'),
        )
        self.smart = PlatformAIModel.objects.create(
            provider=self.account, model_name='gpt-4o', label='Best quality',
            input_cost_per_million=Decimal('2.50'),
            output_cost_per_million=Decimal('10.00'),
        )

    def auth(self, user, tenant=None):
        client = APIClient()
        token = RefreshToken.for_user(user).access_token
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        if tenant is not None:
            client.credentials(
                HTTP_AUTHORIZATION=f'Bearer {token}', HTTP_X_TENANT_ID=str(tenant.id)
            )
        return client

    def grant(self, *models, **kwargs):
        allocation = resolver.get_allocation(self.tenant)
        allocation.is_enabled = kwargs.pop('is_enabled', True)
        for field, value in kwargs.items():
            setattr(allocation, field, value)
        allocation.save()
        allocation.granted_models.set(models or [self.cheap])
        return allocation

    def meter(self, tokens, cost='0', tenant=None):
        return AIUsageRecord.objects.create(
            tenant=tenant or self.tenant,
            source=AIUsageRecord.SOURCE_PLATFORM,
            provider='openai', model='gpt-4o-mini',
            prompt_tokens=tokens, completion_tokens=0, total_tokens=tokens,
            estimated_cost_usd=Decimal(cost),
        )


class ResolutionTests(_PlatformAICase):
    """Which LLM answers, and whose money pays for it."""

    def test_ungranted_tenant_gets_no_ai(self):
        with self.assertRaises(resolver.AIUnavailable) as ctx:
            resolver.resolve(self.tenant)
        self.assertEqual(ctx.exception.reason, 'not_configured')

    def test_granted_tenant_uses_platform_model(self):
        self.grant(self.cheap)
        resolution = resolver.resolve(self.tenant)
        self.assertEqual(resolution.provider.source, AIUsageRecord.SOURCE_PLATFORM)
        self.assertEqual(resolution.provider.model, 'gpt-4o-mini')
        self.assertEqual(resolution.provider.api_key, 'sk-platform-secret-key')

    def test_tenant_own_key_beats_the_grant(self):
        """We should never pay for a tenant that can pay for itself."""
        self.grant(self.cheap)
        config = AIProviderConfig.objects.create(
            tenant=self.tenant, provider=AIProviderConfig.PROVIDER_OPENAI,
            model='gpt-4o', is_active=True,
        )
        config.api_key = 'sk-tenant-owned'
        config.save()

        resolution = resolver.resolve(self.tenant)
        self.assertEqual(resolution.provider.source, AIUsageRecord.SOURCE_TENANT)
        self.assertEqual(resolution.provider.api_key, 'sk-tenant-owned')

    def test_disabled_provider_account_revokes_every_grant(self):
        """Turning off an account must stop tenants instantly, not on next deploy."""
        self.grant(self.cheap)
        self.account.is_enabled = False
        self.account.save()

        with self.assertRaises(resolver.AIUnavailable):
            resolver.resolve(self.tenant)

    def test_the_platform_default_leads_the_chain(self):
        self.grant(self.cheap, self.smart, default_model=self.smart)
        resolution = resolver.resolve(self.tenant)
        self.assertEqual(resolution.provider.model, 'gpt-4o')
        self.assertEqual([p.model for p in resolution.chain], ['gpt-4o', 'gpt-4o-mini'])

    def test_every_granted_model_is_queued_as_a_fallback(self):
        """Extra grants are resilience, not a menu."""
        self.grant(self.cheap, self.smart)
        self.assertEqual(len(resolver.resolve(self.tenant).chain), 2)

    def test_an_unusable_model_is_dropped_from_the_chain(self):
        second = PlatformAIProvider.objects.create(
            name='Backup', provider=AIProviderConfig.PROVIDER_OPENAI, is_enabled=False,
        )
        second.api_key = 'sk-backup'
        second.save()
        spare = PlatformAIModel.objects.create(
            provider=second, model_name='gpt-4o', label='Spare',
        )
        self.grant(self.cheap, spare)
        self.assertEqual([p.model for p in resolver.resolve(self.tenant).chain], ['gpt-4o-mini'])


class LimitTests(_PlatformAICase):
    """Ceilings are the only thing standing between us and an unbounded bill."""

    def test_token_ceiling_stops_the_tenant(self):
        self.grant(self.cheap, monthly_token_limit=1000)
        self.meter(1000)
        with self.assertRaises(resolver.AIUnavailable) as ctx:
            resolver.resolve(self.tenant)
        self.assertEqual(ctx.exception.reason, 'platform_exhausted')

    def test_cost_ceiling_stops_the_tenant_independently(self):
        """Cheap-but-huge and dear-but-small both have to be caught."""
        self.grant(self.cheap, monthly_cost_limit_usd=Decimal('5.00'))
        self.meter(10, cost='5.00')
        with self.assertRaises(resolver.AIUnavailable) as ctx:
            resolver.resolve(self.tenant)
        self.assertEqual(ctx.exception.reason, 'platform_exhausted')

    def test_zero_limits_mean_unlimited(self):
        self.grant(self.cheap, monthly_token_limit=0, monthly_cost_limit_usd=0)
        self.meter(10_000_000, cost='999')
        self.assertEqual(resolver.resolve(self.tenant).provider.source, 'platform')

    def test_another_tenants_usage_does_not_count(self):
        self.grant(self.cheap, monthly_token_limit=1000)
        self.meter(5000, tenant=self.other_tenant)
        self.assertEqual(resolver.resolve(self.tenant).provider.source, 'platform')

    def test_only_platform_usage_counts_against_the_grant(self):
        """A tenant burning its own key must not exhaust our allowance."""
        self.grant(self.cheap, monthly_token_limit=1000)
        AIUsageRecord.objects.create(
            tenant=self.tenant, source=AIUsageRecord.SOURCE_TENANT,
            total_tokens=9999, prompt_tokens=9999,
        )
        self.assertEqual(resolver.resolve(self.tenant).provider.source, 'platform')


class CostAttributionTests(_PlatformAICase):
    """Cost reporting has to use the price we actually pay."""

    def test_super_admin_prices_beat_the_builtin_table(self):
        self.smart.input_cost_per_million = Decimal('1.00')
        self.smart.output_cost_per_million = Decimal('1.00')
        self.smart.save()
        cost = estimate_cost_usd(
            'gpt-4o', Usage(1_000_000, 1_000_000, 2_000_000), platform_model=self.smart
        )
        self.assertEqual(cost, 2.0)

    def test_free_platform_model_costs_nothing(self):
        free = PlatformAIModel.objects.create(
            provider=self.account, model_name='llama-3.3-70b-free',
        )
        cost = estimate_cost_usd(
            'llama-3.3-70b', Usage(1_000_000, 0, 1_000_000), platform_model=free
        )
        self.assertEqual(cost, 0.0)

    def test_usage_is_attributed_to_the_platform_model(self):
        self.grant(self.smart)
        resolution = resolver.resolve(self.tenant)
        record = resolver.record_usage(
            tenant=self.tenant, student=None, session=None,
            resolved=resolution.provider, usage=Usage(1_000_000, 0, 1_000_000),
            feature=AIUsageRecord.FEATURE_COURSEGEN,
        )
        self.assertEqual(record.platform_model, self.smart)
        self.assertEqual(record.feature, 'coursegen')
        self.assertEqual(float(record.estimated_cost_usd), 2.5)


class ExhaustionNoticeTests(_PlatformAICase):
    """An academy must find out before its students do."""

    def test_admins_are_warned_at_the_threshold_once(self):
        self.grant(self.cheap, monthly_token_limit=1000, notify_at_percent=80)
        self.meter(850)
        resolver.maybe_warn_allowance(self.tenant)
        resolver.maybe_warn_allowance(self.tenant)

        notices = Notification.objects.filter(
            recipient=self.admin, type=Notification.TYPE_AI_ALLOWANCE
        )
        self.assertEqual(notices.count(), 1)
        self.assertIn('85%', notices.first().title)

    def test_exhaustion_warns_again_after_the_threshold_warning(self):
        allocation = self.grant(self.cheap, monthly_token_limit=1000, notify_at_percent=80)
        self.meter(850)
        resolver.maybe_warn_allowance(self.tenant)
        self.meter(200)
        resolver.maybe_warn_allowance(self.tenant)

        notices = Notification.objects.filter(type=Notification.TYPE_AI_ALLOWANCE)
        self.assertEqual(notices.count(), 2)
        self.assertTrue(notices.first().data['exhausted'])
        allocation.refresh_from_db()
        self.assertEqual(allocation.last_notified_percent, 100)

    def test_unlimited_allocation_never_warns(self):
        self.grant(self.cheap, monthly_token_limit=0, monthly_cost_limit_usd=0)
        self.meter(10_000_000)
        resolver.maybe_warn_allowance(self.tenant)
        self.assertEqual(Notification.objects.count(), 0)

    def test_a_failed_notification_does_not_break_the_call(self):
        self.grant(self.cheap, monthly_token_limit=100)
        self.meter(100)
        with patch('notifications.services.on_ai_allowance_warning', side_effect=RuntimeError('smtp down')):
            resolver.maybe_warn_allowance(self.tenant)  # must not raise


class SuperAdminApiTests(_PlatformAICase):
    """The platform's keys and margins are super-admin-only."""

    def test_tenant_admin_cannot_reach_platform_providers(self):
        response = self.auth(self.admin, self.tenant).get(f'{SUPER}/ai/providers/')
        self.assertIn(response.status_code, (401, 403))

    def test_api_key_is_never_returned(self):
        response = self.auth(self.superadmin).get(f'{SUPER}/ai/providers/')
        self.assertEqual(response.status_code, 200)
        body = response.json()['providers'][0]
        self.assertNotIn('api_key', body)
        self.assertTrue(body['has_api_key'])
        self.assertNotIn('secret', body['api_key_hint'])

    def test_updating_a_provider_keeps_the_stored_key(self):
        """An omitted key means 'leave it alone' — not 'wipe it'."""
        client = self.auth(self.superadmin)
        response = client.patch(
            f'{SUPER}/ai/providers/{self.account.id}/', {'name': 'Renamed'}, format='json'
        )
        self.assertEqual(response.status_code, 200)
        self.account.refresh_from_db()
        self.assertEqual(self.account.api_key, 'sk-platform-secret-key')

    def test_granting_models_to_a_tenant(self):
        client = self.auth(self.superadmin)
        response = client.put(
            f'{SUPER}/tenants/{self.tenant.id}/ai-allocation/',
            {
                'is_enabled': True,
                'granted_models': [str(self.cheap.id)],
                'default_model': str(self.cheap.id),
                'monthly_token_limit': 50000,
            },
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(resolver.resolve(self.tenant).provider.model, 'gpt-4o-mini')

    def test_default_must_be_one_of_the_granted_models(self):
        response = self.auth(self.superadmin).put(
            f'{SUPER}/tenants/{self.tenant.id}/ai-allocation/',
            {
                'is_enabled': True,
                'granted_models': [str(self.cheap.id)],
                'default_model': str(self.smart.id),
            },
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_topping_up_reopens_the_warning(self):
        """Otherwise a re-funded tenant would silently run dry next time."""
        allocation = self.grant(self.cheap, monthly_token_limit=1000)
        allocation.last_notified_period = timezone.now().strftime('%Y-%m')
        allocation.last_notified_percent = 100
        allocation.save()

        self.auth(self.superadmin).put(
            f'{SUPER}/tenants/{self.tenant.id}/ai-allocation/',
            {'monthly_token_limit': 100000}, format='json',
        )
        allocation.refresh_from_db()
        self.assertEqual(allocation.last_notified_percent, 0)

    def test_usage_report_breaks_down_by_tenant(self):
        self.meter(500, cost='0.10')
        self.meter(300, cost='0.05', tenant=self.other_tenant)
        response = self.auth(self.superadmin).get(f'{SUPER}/ai/usage/')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['totals']['tokens'], 800)
        self.assertEqual(body['totals']['tenants'], 2)
        self.assertEqual(body['tenants'][0]['tenant_name'], 'Alpha Academy')


class TenantIncludedApiTests(_PlatformAICase):
    """What an academy is told about the AI we include: that it exists.

    Naming the models would turn an operational choice into a promise — we
    could not retire, reprice or fail over between them without an academy
    noticing. So the panel is a status readout, not a settings screen.
    """

    def test_no_model_is_ever_named(self):
        self.grant(self.cheap, self.smart)
        body = self.auth(self.admin, self.tenant).get(f'{TENANT_AI}/included/').json()
        serialised = str(body)
        self.assertNotIn('gpt-4o', serialised)
        self.assertNotIn('openai', serialised.lower())
        self.assertEqual(body['model_count'], 2)

    def test_costs_are_never_shown(self):
        self.grant(self.cheap)
        body = self.auth(self.admin, self.tenant).get(f'{TENANT_AI}/included/').json()
        self.assertFalse([k for k in body if 'cost' in k or 'usd' in k])

    def test_there_is_nothing_for_a_tenant_to_change(self):
        self.grant(self.cheap)
        response = self.auth(self.admin, self.tenant).put(
            f'{TENANT_AI}/included/', {'model_count': 99}, format='json',
        )
        self.assertEqual(response.status_code, 405)

    def test_the_usage_table_never_names_an_included_model(self):
        """The usage panel is the other place a model name could slip out."""
        self.grant(self.cheap)
        self.meter(500, cost='0.42')
        body = self.auth(self.admin, self.tenant).get(f'{TENANT_AI}/usage/').json()

        rows = body['by_model']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['model'], 'Included AI')
        self.assertIsNone(rows[0]['estimated_cost_usd'])
        self.assertNotIn('gpt-4o-mini', str(rows))
        # Nor may the headline figure quote what we paid.
        self.assertEqual(body['estimated_cost_usd'], 0)

    def test_a_tenants_own_spend_is_still_broken_out(self):
        AIUsageRecord.objects.create(
            tenant=self.tenant, source=AIUsageRecord.SOURCE_TENANT,
            provider='openai', model='gpt-4o', prompt_tokens=10,
            completion_tokens=0, total_tokens=10, estimated_cost_usd=Decimal('1.50'),
        )
        body = self.auth(self.admin, self.tenant).get(f'{TENANT_AI}/usage/').json()
        self.assertEqual(body['by_model'][0]['model'], 'gpt-4o')
        self.assertEqual(body['estimated_cost_usd'], 1.5)

    def test_platform_costs_are_hidden_from_the_usage_panel(self):
        self.grant(self.cheap)
        allocation = resolver.get_allocation(self.tenant)
        allocation.monthly_cost_limit_usd = Decimal('25')
        allocation.save(update_fields=['monthly_cost_limit_usd'])

        summary = resolver.usage_summary(self.tenant)
        self.assertNotIn('cost_limit_usd', summary['allocation'])
        self.assertNotIn('cost_used_usd', summary['allocation'])
        self.assertIn('tokens_used', summary['allocation'])

    def test_an_ungranted_tenant_is_told_nothing_is_included(self):
        body = self.auth(self.admin, self.tenant).get(f'{TENANT_AI}/included/').json()
        self.assertFalse(body['is_available'])
        self.assertEqual(body['model_count'], 0)


class CourseBuilderGrantTests(_PlatformAICase):
    """The course builder spends the grant too, so it needs the same boundary."""

    def test_the_included_option_names_no_models(self):
        from coursegen import generation

        self.grant(self.cheap, self.smart)
        entry = next(
            e for e in generation.available_models(self.tenant) if e['provider'] == 'platform'
        )
        self.assertEqual(entry['models'], [])
        self.assertTrue(entry['is_managed'])
        self.assertFalse(entry['allows_custom_model'])

    def test_a_requested_model_is_ignored_on_the_included_path(self):
        """Otherwise an admin could type any model and bill it to us."""
        from coursegen import generation

        self.grant(self.cheap, default_model=self.cheap)
        resolved = generation.resolve_for_admin(
            self.tenant, provider='platform', model='gpt-4-turbo',
        )
        self.assertEqual(resolved.model, 'gpt-4o-mini')

    def test_generation_falls_back_across_granted_models(self):
        from coursegen import generation

        self.grant(self.cheap, self.smart, default_model=self.cheap)
        resolved = generation.resolve_for_admin(self.tenant, provider='platform')
        self.assertEqual([p.model for p in resolved.chain], ['gpt-4o-mini', 'gpt-4o'])

    def test_a_granted_model_is_accepted(self):
        from coursegen import generation

        self.grant(self.cheap, self.smart)
        resolved = generation.resolve_for_admin(
            self.tenant, provider='platform', model='gpt-4o'
        )
        self.assertEqual(resolved.model, 'gpt-4o')
        self.assertEqual(resolved.source, 'platform')


class LegacyGrantTests(_PlatformAICase):
    """Tenants migrated from the old env-key grant must keep working."""

    def test_enabled_allocation_without_models_falls_back_to_the_env_key(self):
        allocation = resolver.get_allocation(self.tenant)
        allocation.is_enabled = True
        allocation.monthly_token_limit = 50000
        allocation.save()

        with self.settings(OPENAI_API_KEY='sk-legacy-env-key'):
            resolution = resolver.resolve(self.tenant)
        self.assertEqual(resolution.provider.api_key, 'sk-legacy-env-key')
        self.assertEqual(resolution.provider.source, 'platform')

    def test_a_disabled_allocation_grants_nothing(self):
        with self.settings(OPENAI_API_KEY='sk-legacy-env-key'):
            with self.assertRaises(resolver.AIUnavailable):
                resolver.resolve(self.tenant)


class FailoverTests(TestCase):
    """Granting several models is a promise of uptime, not a menu.

    A student asked a question; which of our models answers it is our problem.
    """

    def setUp(self):
        self.first = providers.ResolvedProvider(
            provider='openai', api_key='k', model='model-a',
        )
        self.second = providers.ResolvedProvider(
            provider='openai', api_key='k', model='model-b',
        )
        self.first.fallbacks = [self.second]

    def test_a_failing_model_is_replaced_silently(self):
        def fake(rp, messages):
            if rp.model == 'model-a':
                raise providers.AIProviderError('rate limited')
            return 'answer', Usage(1, 1, 2), 10

        with patch.object(providers, 'complete', side_effect=fake):
            used, content, _usage, _ms = providers.complete_with_failover(
                self.first.chain, []
            )

        self.assertEqual(content, 'answer')
        self.assertEqual(used.model, 'model-b')

    def test_usage_is_billed_to_the_model_that_actually_answered(self):
        def fake(rp, messages):
            if rp.model == 'model-a':
                raise providers.AIProviderError('down')
            return 'answer', Usage(1, 1, 2), 10

        with patch.object(providers, 'complete', side_effect=fake):
            used, *_ = providers.complete_with_failover(self.first.chain, [])

        self.assertEqual(used.model, 'model-b')

    def test_the_last_error_surfaces_when_everything_is_down(self):
        with patch.object(
            providers, 'complete', side_effect=providers.AIProviderError('all down')
        ):
            with self.assertRaises(providers.AIProviderError):
                providers.complete_with_failover(self.first.chain, [])

    def test_a_stream_fails_over_before_the_first_token(self):
        def fake(rp, messages):
            if rp.model == 'model-a':
                raise providers.AIProviderError('cold start')
            yield 'hello', None
            yield '', Usage(1, 1, 2)

        with patch.object(providers, 'stream', side_effect=fake):
            chunks = list(providers.stream_with_failover(self.first.chain, []))

        self.assertEqual(''.join(c[1] for c in chunks), 'hello')
        self.assertTrue(all(c[0].model == 'model-b' for c in chunks))

    def test_a_stream_that_already_started_is_not_restarted(self):
        """Re-running it would repeat text the user is already reading."""
        def fake(rp, messages):
            yield 'partial', None
            raise providers.AIProviderError('died mid-stream')

        with patch.object(providers, 'stream', side_effect=fake):
            with self.assertRaises(providers.AIProviderError):
                list(providers.stream_with_failover(self.first.chain, []))


class StudentFacingOpacityTests(_PlatformAICase):
    """A student's browser is the easiest place to enumerate the grant."""

    def test_the_included_model_is_not_named_to_a_student(self):
        from .services import public_model_label

        self.grant(self.cheap)
        resolved = resolver.resolve(self.tenant).provider
        self.assertEqual(public_model_label(resolved), 'included')

    def test_a_tenants_own_model_is_still_named(self):
        from .services import public_model_label

        config = AIProviderConfig.objects.create(
            tenant=self.tenant, provider=AIProviderConfig.PROVIDER_OPENAI,
            model='gpt-4o', is_active=True,
        )
        config.api_key = 'sk-tenant'
        config.save()
        resolved = resolver.resolve(self.tenant).provider
        self.assertEqual(public_model_label(resolved), 'gpt-4o')


class CourseGenerationTuningTests(_PlatformAICase):
    """A fallback must be able to finish the job the primary started."""

    def test_every_model_in_the_chain_gets_the_jobs_budget(self):
        from coursegen import generation

        self.grant(self.cheap, self.smart, default_model=self.cheap)
        resolved = generation.resolve_for_admin(
            self.tenant, provider='platform', max_tokens=8000,
        )
        self.assertTrue(len(resolved.chain) > 1)
        for candidate in resolved.chain:
            self.assertEqual(candidate.max_tokens, 8000)
            self.assertEqual(candidate.temperature, 0.4)


class ReasoningModelParameterTests(TestCase):
    """gpt-5.x / o-series renamed ``max_tokens`` and fixed the temperature.

    Azure deployment names are free-form, so we can't rely on recognising the
    model: the client has to learn from the 400 and remember.
    """

    def setUp(self):
        providers._PARAM_QUIRKS.clear()
        self.rp = providers.ResolvedProvider(
            provider=AIProviderConfig.PROVIDER_OPENAI,
            api_key='sk-test', model='gpt-5.1', max_tokens=2000, temperature=0.7,
        )

    def _client(self, create):
        client = type('C', (), {})()
        client.chat = type('Chat', (), {})()
        client.chat.completions = type('Completions', (), {})()
        client.chat.completions.create = create
        return client

    def test_a_reasoning_model_is_called_with_the_new_parameter(self):
        seen = {}

        def create(**kwargs):
            seen.update(kwargs)
            return _fake_response('ok')

        with patch.object(providers, '_openai_client', return_value=self._client(create)):
            content, _usage = providers._openai_complete(self.rp, [])

        self.assertEqual(content, 'ok')
        self.assertNotIn('max_tokens', seen)
        self.assertNotIn('temperature', seen)
        self.assertGreaterEqual(seen['max_completion_tokens'], providers.MIN_REASONING_BUDGET)

    def test_an_unrecognised_deployment_learns_from_the_rejection(self):
        """The Azure case from the bug report: the name tells us nothing."""
        self.rp.model = 'prod-deployment'
        calls = []

        def create(**kwargs):
            calls.append(dict(kwargs))
            if 'max_tokens' in kwargs:
                raise RuntimeError(
                    "Error code: 400 - {'error': {'message': \"Unsupported parameter: "
                    "'max_tokens' is not supported with this model. Use "
                    "'max_completion_tokens' instead.\", 'code': 'unsupported_parameter'}}"
                )
            if 'temperature' in kwargs:
                raise RuntimeError(
                    "Error code: 400 - {'error': {'message': \"Unsupported value: "
                    "'temperature' does not support 0.7.\", 'code': 'unsupported_value'}}"
                )
            return _fake_response('ok')

        with patch.object(providers, '_openai_client', return_value=self._client(create)):
            content, _usage = providers._openai_complete(self.rp, [])

        self.assertEqual(content, 'ok')
        self.assertEqual(len(calls), 3)
        self.assertIn('max_completion_tokens', calls[-1])
        self.assertNotIn('temperature', calls[-1])

    def test_what_was_learned_is_reused_on_the_next_call(self):
        self.rp.model = 'prod-deployment'
        calls = []

        def create(**kwargs):
            calls.append(dict(kwargs))
            if 'max_tokens' in kwargs:
                raise RuntimeError(
                    "Error code: 400 - {'error': {'message': \"Unsupported parameter: "
                    "'max_tokens' is not supported with this model.\", "
                    "'code': 'unsupported_parameter'}}"
                )
            return _fake_response('ok')

        with patch.object(providers, '_openai_client', return_value=self._client(create)):
            providers._openai_complete(self.rp, [])
            before = len(calls)
            providers._openai_complete(self.rp, [])

        self.assertEqual(len(calls) - before, 1)

    def test_an_ordinary_model_keeps_the_old_parameters(self):
        seen = {}

        def create(**kwargs):
            seen.update(kwargs)
            return _fake_response('ok')

        self.rp.model = 'gpt-4o-mini'
        with patch.object(providers, '_openai_client', return_value=self._client(create)):
            providers._openai_complete(self.rp, [])

        self.assertEqual(seen['max_tokens'], 2000)
        self.assertEqual(seen['temperature'], 0.7)

    def test_a_real_error_is_not_retried(self):
        calls = []

        def create(**kwargs):
            calls.append(1)
            raise RuntimeError('Error code: 401 - invalid api key')

        with patch.object(providers, '_openai_client', return_value=self._client(create)):
            with self.assertRaises(RuntimeError):
                providers._openai_complete(self.rp, [])

        self.assertEqual(len(calls), 1)

    def test_budget_spent_entirely_on_reasoning_is_reported(self):
        def create(**kwargs):
            return _fake_response('', finish_reason='length')

        with patch.object(providers, '_openai_client', return_value=self._client(create)):
            with self.assertRaises(providers.AIProviderError) as ctx:
                providers._openai_complete(self.rp, [])

        self.assertIn('max output tokens', str(ctx.exception))


def _fake_response(content, finish_reason='stop'):
    message = type('M', (), {'content': content})()
    choice = type('C', (), {'message': message, 'finish_reason': finish_reason})()
    usage = type('U', (), {
        'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15,
    })()
    return type('R', (), {'choices': [choice], 'usage': usage})()
