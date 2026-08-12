from django.contrib import admin
from .models import Tenant, DemoBooking, ContactMessage, JobApplication, PaymentGateway, ZoomIntegration, LandingPage, LegalDocument


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ('name', 'tagline', 'theme', 'subdomain', 'is_active', 'created_at')
    search_fields = ('name', 'tagline', 'subdomain')
    list_filter = ('is_active', 'theme')


@admin.register(PaymentGateway)
class PaymentGatewayAdmin(admin.ModelAdmin):
    list_display = ('tenant', 'provider', 'is_active', 'is_test_mode', 'is_configured', 'updated_at')
    list_filter = ('provider', 'is_active', 'is_test_mode')
    search_fields = ('tenant__name', 'key_id')
    # Never expose the encrypted secret blobs for editing in the Django admin.
    exclude = ('key_secret_encrypted', 'webhook_secret_encrypted')
    readonly_fields = ('id', 'is_configured', 'created_at', 'updated_at')


@admin.register(ZoomIntegration)
class ZoomIntegrationAdmin(admin.ModelAdmin):
    list_display = ('tenant', 'account_id', 'is_active', 'is_configured',
                    'use_registration', 'last_verified_at')
    list_filter = ('is_active', 'use_registration', 'pull_reports')
    search_fields = ('tenant__name', 'account_id', 'client_id', 'host_email')
    # Never expose the encrypted secret blobs for editing in the Django admin.
    exclude = ('client_secret_encrypted', 'webhook_secret_token_encrypted')
    readonly_fields = ('id', 'is_configured', 'last_verified_at', 'last_error',
                       'created_at', 'updated_at')


@admin.register(DemoBooking)
class DemoBookingAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'organization', 'organization_type', 'status', 'created_at')
    list_filter = ('status', 'organization_type', 'created_at')
    search_fields = ('name', 'email', 'organization', 'phone')
    readonly_fields = ('id', 'name', 'email', 'phone', 'organization',
                       'organization_type', 'message', 'source', 'created_at', 'updated_at')
    list_editable = ('status',)
    ordering = ('-created_at',)


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'subject', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('name', 'email', 'subject', 'message')
    readonly_fields = ('id', 'name', 'email', 'subject', 'message',
                       'source', 'created_at', 'updated_at')
    list_editable = ('status',)
    ordering = ('-created_at',)


@admin.register(JobApplication)
class JobApplicationAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'position', 'experience', 'status', 'created_at')
    list_filter = ('status', 'position', 'created_at')
    search_fields = ('name', 'email', 'position', 'phone', 'cover_letter')
    readonly_fields = ('id', 'name', 'email', 'phone', 'position', 'experience',
                       'portfolio_url', 'cover_letter', 'source', 'created_at', 'updated_at')
    list_editable = ('status',)
    ordering = ('-created_at',)


@admin.register(LandingPage)
class LandingPageAdmin(admin.ModelAdmin):
    list_display = ('tenant', 'template', 'is_published', 'updated_at')
    list_filter = ('template', 'is_published')
    search_fields = ('tenant__name',)
    readonly_fields = ('id', 'created_at', 'updated_at')


@admin.register(LegalDocument)
class LegalDocumentAdmin(admin.ModelAdmin):
    list_display = ('tenant', 'doc_type', 'title', 'updated_at')
    list_filter = ('doc_type',)
    search_fields = ('tenant__name', 'title')
    readonly_fields = ('id', 'created_at', 'updated_at')
