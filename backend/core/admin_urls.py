"""Tenant-admin URLs — branding + feature toggles + payment gateway.

Mounted under a non-tenant-exempt path so ``TenantMiddleware`` resolves the
current tenant from the ``X-Tenant-ID`` header before the view runs.
"""
from django.urls import path

from .admin_views import TenantSettingsView, PaymentGatewayView, ZoomIntegrationView
from .landing_views import (
    LandingPageAdminView, LegalDocumentAdminView, LandingImageUploadView,
)

urlpatterns = [
    path('settings/', TenantSettingsView.as_view(), name='tenant-admin-settings'),
    path('payment-gateway/', PaymentGatewayView.as_view(), name='tenant-admin-payment-gateway'),
    path('zoom/', ZoomIntegrationView.as_view(), name='tenant-admin-zoom'),
    path('landing/', LandingPageAdminView.as_view(), name='tenant-admin-landing'),
    path('landing/upload-image/', LandingImageUploadView.as_view(), name='tenant-admin-landing-upload-image'),
    path('landing/legal/<str:doc_type>/', LegalDocumentAdminView.as_view(), name='tenant-admin-legal'),
]
