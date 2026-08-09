"""Super-admin dashboard URLs.

Mounted under a tenant-exempt path (``/api/v1/superadmin/``) so no
``X-Tenant-ID`` header is required — super admins are tenant-less. Every view is
gated by :class:`core.permissions.IsSuperAdmin`.
"""
from django.urls import path

from chatbot.platform_views import (
    PlatformAIUsageView,
    PlatformModelDetailView,
    PlatformModelListCreateView,
    PlatformProviderDetailView,
    PlatformProviderListCreateView,
    PlatformProviderTestView,
    TenantAIAllocationView,
)

from .superadmin_views import (
    SuperAdminLoginView,
    SuperAdminMeView,
    PlatformStatsView,
    TenantListCreateView,
    TenantDetailView,
    AuditLogListView,
    UserListView,
    UserActionView,
    LeadListView,
    LeadDetailView,
    AnnouncementListCreateView,
    AnnouncementDetailView,
)

urlpatterns = [
    path('auth/login/', SuperAdminLoginView.as_view(), name='superadmin-login'),
    path('auth/me/', SuperAdminMeView.as_view(), name='superadmin-me'),
    path('stats/', PlatformStatsView.as_view(), name='superadmin-stats'),
    path('tenants/', TenantListCreateView.as_view(), name='superadmin-tenant-list'),
    path('tenants/<uuid:pk>/', TenantDetailView.as_view(), name='superadmin-tenant-detail'),
    path('audit-logs/', AuditLogListView.as_view(), name='superadmin-audit-logs'),
    path('users/', UserListView.as_view(), name='superadmin-user-list'),
    path('users/<uuid:pk>/action/', UserActionView.as_view(), name='superadmin-user-action'),
    path('leads/', LeadListView.as_view(), name='superadmin-lead-list'),
    path('leads/<str:lead_type>/<uuid:pk>/', LeadDetailView.as_view(), name='superadmin-lead-detail'),
    path('announcements/', AnnouncementListCreateView.as_view(), name='superadmin-announcement-list'),
    path('announcements/<uuid:pk>/', AnnouncementDetailView.as_view(), name='superadmin-announcement-detail'),

    # ── Platform-supplied LLMs ──────────────────────────────────────────────
    path('ai/providers/', PlatformProviderListCreateView.as_view(), name='superadmin-ai-providers'),
    path('ai/providers/<uuid:pk>/', PlatformProviderDetailView.as_view(), name='superadmin-ai-provider-detail'),
    path('ai/providers/<uuid:pk>/test/', PlatformProviderTestView.as_view(), name='superadmin-ai-provider-test'),
    path('ai/providers/<uuid:pk>/models/', PlatformModelListCreateView.as_view(), name='superadmin-ai-provider-models'),
    path('ai/models/<uuid:pk>/', PlatformModelDetailView.as_view(), name='superadmin-ai-model-detail'),
    path('ai/usage/', PlatformAIUsageView.as_view(), name='superadmin-ai-usage'),
    path('tenants/<uuid:pk>/ai-allocation/', TenantAIAllocationView.as_view(), name='superadmin-tenant-ai-allocation'),
]
