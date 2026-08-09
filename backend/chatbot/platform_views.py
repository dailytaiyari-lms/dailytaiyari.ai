"""Super-admin endpoints for the platform's own LLM fleet.

Mounted under ``/api/v1/superadmin/ai/`` and gated by
:class:`core.permissions.IsSuperAdmin`. Three jobs:

* register the platform's LLM accounts and the models each one serves,
* grant a set of those models to a tenant with token and dollar ceilings,
* report what every tenant is costing us.

Nothing here is reachable by a tenant admin — these are the platform owner's
credentials and its margin.
"""
from datetime import timedelta

from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import Tenant
from core.permissions import IsSuperAdmin

from . import resolver
from .models import AIUsageRecord, PlatformAIModel, PlatformAIProvider
from .platform_serializers import (
    PlatformAIModelSerializer,
    PlatformAIProviderSerializer,
    TenantAIAllocationSerializer,
)
from .providers import ResolvedProvider, test_connection


class _SuperAdminView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsSuperAdmin]


def _audit(request, action, *, target_tenant=None, target_name='', changes=None):
    """Mirror super-admin AI changes into the existing audit trail."""
    from core.superadmin_views import _record_action

    _record_action(
        request, action, target_tenant=target_tenant,
        target_name=target_name, changes=changes or {},
    )


class PlatformProviderListCreateView(_SuperAdminView):
    """``GET`` every platform LLM account, ``POST`` a new one."""

    def get(self, request):
        providers = PlatformAIProvider.objects.prefetch_related('models').all()
        return Response({
            'providers': PlatformAIProviderSerializer(providers, many=True).data,
            'catalog': _provider_catalog(),
        })

    def post(self, request):
        serializer = PlatformAIProviderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        provider = serializer.save()
        _audit(request, 'ai_provider_created', target_name=provider.name,
               changes={'provider': provider.provider})
        return Response(
            PlatformAIProviderSerializer(provider).data, status=status.HTTP_201_CREATED
        )


class PlatformProviderDetailView(_SuperAdminView):
    """``PATCH`` / ``DELETE`` one platform LLM account."""

    def patch(self, request, pk):
        provider = get_object_or_404(PlatformAIProvider, pk=pk)
        serializer = PlatformAIProviderSerializer(provider, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        provider = serializer.save()
        _audit(request, 'ai_provider_updated', target_name=provider.name)
        return Response(PlatformAIProviderSerializer(provider).data)

    def delete(self, request, pk):
        provider = get_object_or_404(PlatformAIProvider, pk=pk)
        name = provider.name
        # Grants referencing its models go with it (M2M rows cascade), which is
        # what we want: a deleted account cannot answer anyone.
        provider.delete()
        _audit(request, 'ai_provider_deleted', target_name=name)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PlatformProviderTestView(_SuperAdminView):
    """Probe an account's credentials with a tiny prompt."""

    def post(self, request, pk):
        provider = get_object_or_404(PlatformAIProvider, pk=pk)
        model_name = (request.data.get('model') or '').strip()
        if not model_name:
            first = provider.models.filter(is_enabled=True).first()
            model_name = first.model_name if first else ''
        if not model_name:
            return Response(
                {'detail': 'Add at least one model to this provider before testing.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ok, message = test_connection(ResolvedProvider(
            provider=provider.provider,
            api_key=provider.api_key,
            base_url=provider.effective_base_url,
            model=model_name,
            api_version=provider.api_version or '2024-10-21',
            source='platform',
        ))
        provider.last_tested_at = timezone.now()
        provider.last_test_ok = ok
        provider.last_test_error = '' if ok else message[:500]
        provider.save(update_fields=[
            'last_tested_at', 'last_test_ok', 'last_test_error', 'updated_at',
        ])
        return Response({'ok': ok, 'message': message, 'model': model_name})


class PlatformModelListCreateView(_SuperAdminView):
    """``POST`` a model onto a provider."""

    def post(self, request, pk):
        provider = get_object_or_404(PlatformAIProvider, pk=pk)
        serializer = PlatformAIModelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if provider.models.filter(
            model_name=serializer.validated_data['model_name']
        ).exists():
            return Response(
                {'model_name': ['This provider already offers that model.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        model = serializer.save(provider=provider)
        _audit(request, 'ai_model_created', target_name=f'{provider.name} / {model.model_name}')
        return Response(PlatformAIModelSerializer(model).data, status=status.HTTP_201_CREATED)


class PlatformModelDetailView(_SuperAdminView):
    """``PATCH`` / ``DELETE`` one model offering."""

    def patch(self, request, pk):
        model = get_object_or_404(PlatformAIModel.objects.select_related('provider'), pk=pk)
        serializer = PlatformAIModelSerializer(model, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        model = serializer.save()
        _audit(request, 'ai_model_updated', target_name=f'{model.provider.name} / {model.model_name}')
        return Response(PlatformAIModelSerializer(model).data)

    def delete(self, request, pk):
        model = get_object_or_404(PlatformAIModel.objects.select_related('provider'), pk=pk)
        label = f'{model.provider.name} / {model.model_name}'
        model.delete()
        _audit(request, 'ai_model_deleted', target_name=label)
        return Response(status=status.HTTP_204_NO_CONTENT)


class TenantAIAllocationView(_SuperAdminView):
    """``GET`` / ``PUT`` one tenant's grant of platform models."""

    def _payload(self, tenant, allocation):
        data = TenantAIAllocationSerializer(allocation).data
        data['status'] = resolver.allocation_status(tenant, allocation)
        data['has_own_provider'] = resolver.active_config(tenant) is not None
        return data

    def get(self, request, pk):
        tenant = get_object_or_404(Tenant, pk=pk)
        allocation = resolver.get_allocation(tenant)
        return Response({
            **self._payload(tenant, allocation),
            'available_models': PlatformAIModelSerializer(
                PlatformAIModel.objects.select_related('provider'), many=True
            ).data,
        })

    def put(self, request, pk):
        tenant = get_object_or_404(Tenant, pk=pk)
        allocation = resolver.get_allocation(tenant)
        serializer = TenantAIAllocationSerializer(allocation, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        allocation = serializer.save()

        # Raising a ceiling should un-silence the warnings: without this, a
        # tenant topped up after being warned would never be warned again.
        allocation.last_notified_period = ''
        allocation.last_notified_percent = 0
        allocation.save(update_fields=[
            'last_notified_period', 'last_notified_percent', 'updated_at',
        ])

        _audit(request, 'ai_allocation_updated', target_tenant=tenant, changes={
            'is_enabled': allocation.is_enabled,
            'monthly_token_limit': allocation.monthly_token_limit,
            'monthly_cost_limit_usd': str(allocation.monthly_cost_limit_usd),
            'granted_models': allocation.granted_models.count(),
        })
        return Response(self._payload(tenant, allocation))


class PlatformAIUsageView(_SuperAdminView):
    """What the platform's own models are costing, broken down by tenant."""

    def get(self, request):
        try:
            days = max(1, min(365, int(request.query_params.get('days', 30))))
        except (TypeError, ValueError):
            days = 30
        since = timezone.now() - timedelta(days=days)

        window = AIUsageRecord.objects.filter(
            source=AIUsageRecord.SOURCE_PLATFORM, created_at__gte=since
        )
        totals = window.aggregate(
            tokens=Sum('total_tokens'),
            cost=Sum('estimated_cost_usd'),
            calls=Count('id'),
        )

        rows = (
            window.values('tenant', 'tenant__name')
            .annotate(
                tokens=Sum('total_tokens'),
                cost=Sum('estimated_cost_usd'),
                calls=Count('id'),
            )
            .order_by('-cost')
        )
        tenants = []
        for row in rows:
            tenant_id = row['tenant']
            entry = {
                'tenant_id': str(tenant_id) if tenant_id else None,
                'tenant_name': row['tenant__name'] or 'Unassigned',
                'tokens': row['tokens'] or 0,
                'cost_usd': float(row['cost'] or 0),
                'calls': row['calls'],
            }
            if tenant_id:
                tenant = Tenant.objects.filter(pk=tenant_id).first()
                if tenant is not None:
                    entry['month'] = resolver.allocation_status(tenant)
            tenants.append(entry)

        by_model = list(
            window.values('model')
            .annotate(tokens=Sum('total_tokens'), cost=Sum('estimated_cost_usd'), calls=Count('id'))
            .order_by('-cost')[:20]
        )
        by_feature = list(
            window.values('feature')
            .annotate(tokens=Sum('total_tokens'), cost=Sum('estimated_cost_usd'), calls=Count('id'))
            .order_by('-cost')
        )

        return Response({
            'days': days,
            'totals': {
                'tokens': totals['tokens'] or 0,
                'cost_usd': float(totals['cost'] or 0),
                'calls': totals['calls'] or 0,
                'tenants': len([t for t in tenants if t['tenant_id']]),
            },
            'tenants': tenants,
            'by_model': [
                {**row, 'cost': float(row['cost'] or 0), 'tokens': row['tokens'] or 0}
                for row in by_model
            ],
            'by_feature': [
                {**row, 'cost': float(row['cost'] or 0), 'tokens': row['tokens'] or 0}
                for row in by_feature
            ],
        })


def _provider_catalog():
    """Reuse the tenant-facing provider catalog so both screens stay in step."""
    from .admin_views import _catalog

    return _catalog()
