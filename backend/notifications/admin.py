from django.contrib import admin

from .models import (
    Announcement,
    BirthdayDispatchRun,
    BirthdayGreetingLog,
    Notification,
    TenantEmailTemplate,
)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('title', 'type', 'recipient', 'tenant', 'is_read', 'created_at')
    list_filter = ('type', 'is_read', 'tenant')
    search_fields = ('title', 'body', 'recipient__email')
    readonly_fields = ('created_at', 'read_at')
    raw_id_fields = ('recipient', 'tenant')


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ('title', 'tenant', 'audience', 'status', 'recipients_count', 'created_at')
    list_filter = ('audience', 'status', 'tenant')
    search_fields = ('title', 'body')
    readonly_fields = ('recipients_count', 'status', 'sent_at', 'created_at')
    raw_id_fields = ('tenant', 'created_by')
    filter_horizontal = ('courses',)


@admin.register(TenantEmailTemplate)
class TenantEmailTemplateAdmin(admin.ModelAdmin):
    list_display = ('type', 'tenant', 'subject', 'updated_at')
    list_filter = ('type', 'tenant')
    search_fields = ('subject', 'heading', 'body')
    readonly_fields = ('created_at', 'updated_at')
    raw_id_fields = ('tenant',)


@admin.register(BirthdayGreetingLog)
class BirthdayGreetingLogAdmin(admin.ModelAdmin):
    list_display = ('user', 'tenant', 'year', 'is_past_student', 'emailed', 'created_at')
    list_filter = ('year', 'is_past_student', 'emailed', 'tenant')
    search_fields = ('user__email', 'user__first_name', 'user__last_name')
    readonly_fields = ('created_at',)
    raw_id_fields = ('tenant', 'user')


@admin.register(BirthdayDispatchRun)
class BirthdayDispatchRunAdmin(admin.ModelAdmin):
    list_display = ('run_date', 'tenant', 'greeted_count', 'created_at')
    list_filter = ('run_date', 'tenant')
    readonly_fields = ('created_at',)
    raw_id_fields = ('tenant',)
