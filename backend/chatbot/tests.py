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

    def test_tenant_default_wins_over_platform_default(self):
        allocation = self.grant(self.cheap, self.smart, default_model=self.cheap)
        allocation.tenant_default_model = self.smart
        allocation.save()
        self.assertEqual(resolver.resolve(self.tenant).provider.model, 'gpt-4o')

    def test_tenant_narrowing_cannot_lock_itself_out(self):
        """A tenant that pinned a model we later revoked still gets AI."""
        allocation = self.grant(self.cheap)
        allocation.tenant_enabled_models.set([self.smart])  # never granted
        self.assertEqual(resolver.resolve(self.tenant).provider.model, 'gpt-4o-mini')


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


class TenantIncludedModelsApiTests(_PlatformAICase):
    """The non-technical admin's view: models, no keys, no prices."""

    def test_pricing_is_never_exposed_to_a_tenant(self):
        self.grant(self.cheap, self.smart)
        response = self.auth(self.admin, self.tenant).get(f'{TENANT_AI}/included-models/')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body['models']), 2)
        for entry in body['models']:
            self.assertNotIn('input_cost_per_million', entry)
            self.assertNotIn('provider', entry)

    def test_tenant_can_narrow_and_set_a_default(self):
        self.grant(self.cheap, self.smart)
        client = self.auth(self.admin, self.tenant)
        response = client.put(
            f'{TENANT_AI}/included-models/',
            {
                'enabled_model_ids': [str(self.smart.id)],
                'default_model_id': str(self.smart.id),
            },
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['default_model_id'], str(self.smart.id))
        self.assertEqual(resolver.resolve(self.tenant).provider.model, 'gpt-4o')

    def test_tenant_cannot_enable_a_model_it_was_not_given(self):
        self.grant(self.cheap)
        response = self.auth(self.admin, self.tenant).put(
            f'{TENANT_AI}/included-models/',
            {'enabled_model_ids': [str(self.smart.id)]}, format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_a_revoked_model_does_not_wedge_the_panel(self):
        """The GET must never hand back ids the PUT would reject."""
        self.grant(self.cheap, self.smart)
        client = self.auth(self.admin, self.tenant)
        client.put(
            f'{TENANT_AI}/included-models/',
            {'enabled_model_ids': [str(self.cheap.id), str(self.smart.id)]},
            format='json',
        )
        allocation = resolver.get_allocation(self.tenant)
        allocation.granted_models.remove(self.smart)

        body = client.get(f'{TENANT_AI}/included-models/').json()
        self.assertEqual(body['enabled_model_ids'], [str(self.cheap.id)])
        echo = client.put(
            f'{TENANT_AI}/included-models/',
            {
                'enabled_model_ids': body['enabled_model_ids'],
                'default_model_id': body['default_model_id'],
            },
            format='json',
        )
        self.assertEqual(echo.status_code, 200)

    def test_saving_does_not_pin_the_platform_default(self):
        """A tenant that never chose a default must keep following ours."""
        self.grant(self.cheap, self.smart, default_model=self.cheap)
        client = self.auth(self.admin, self.tenant)
        body = client.get(f'{TENANT_AI}/included-models/').json()
        self.assertIsNone(body['default_model_id'])
        self.assertEqual(body['effective_model_id'], str(self.cheap.id))

        client.put(
            f'{TENANT_AI}/included-models/',
            {
                'enabled_model_ids': [str(self.cheap.id), str(self.smart.id)],
                'default_model_id': body['default_model_id'],
            },
            format='json',
        )
        allocation = resolver.get_allocation(self.tenant)
        self.assertIsNone(allocation.tenant_default_model)

        allocation.default_model = self.smart
        allocation.save(update_fields=['default_model'])
        self.assertEqual(resolver.resolve(self.tenant).provider.model, 'gpt-4o')

    def test_platform_costs_are_hidden_from_the_usage_panel(self):
        self.grant(self.cheap)
        allocation = resolver.get_allocation(self.tenant)
        allocation.monthly_cost_limit_usd = Decimal('25')
        allocation.save(update_fields=['monthly_cost_limit_usd'])

        summary = resolver.usage_summary(self.tenant)
        self.assertNotIn('cost_limit_usd', summary['allocation'])
        self.assertNotIn('cost_used_usd', summary['allocation'])
        self.assertIn('tokens_used', summary['allocation'])

    def test_ungranted_tenant_sees_nothing_on_offer(self):
        response = self.auth(self.admin, self.tenant).get(f'{TENANT_AI}/included-models/')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body['is_available'])
        self.assertEqual(body['models'], [])


class CourseBuilderGrantTests(_PlatformAICase):
    """The course builder spends the grant too, so it needs the same boundary."""

    def test_included_models_are_offered(self):
        from coursegen import generation

        self.grant(self.cheap, self.smart)
        entry = next(
            e for e in generation.available_models(self.tenant) if e['provider'] == 'platform'
        )
        self.assertEqual(sorted(entry['models']), ['gpt-4o', 'gpt-4o-mini'])

    def test_an_ungranted_model_is_refused(self):
        """Otherwise an admin could type any model and bill it to us."""
        from coursegen import generation

        self.grant(self.cheap)
        with self.assertRaises(generation.GenerationError):
            generation.resolve_for_admin(self.tenant, provider='platform', model='gpt-4o')

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
