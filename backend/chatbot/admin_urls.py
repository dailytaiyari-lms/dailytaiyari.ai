"""Tenant-admin URLs for the AI Features screen.

Mounted under ``/api/v1/tenant-admin/ai/`` so ``TenantMiddleware`` resolves the
tenant from the ``X-Tenant-ID`` header before the view runs.
"""
from django.urls import path

from .admin_views import (
    AIProviderTestView,
    AIProviderView,
    AISettingsView,
    AIUsageView,
    IncludedModelsView,
)

urlpatterns = [
    path('providers/', AIProviderView.as_view(), name='tenant-admin-ai-providers'),
    path('providers/test/', AIProviderTestView.as_view(), name='tenant-admin-ai-provider-test'),
    path('settings/', AISettingsView.as_view(), name='tenant-admin-ai-settings'),
    path('usage/', AIUsageView.as_view(), name='tenant-admin-ai-usage'),
    path('included-models/', IncludedModelsView.as_view(), name='tenant-admin-ai-included-models'),
]
