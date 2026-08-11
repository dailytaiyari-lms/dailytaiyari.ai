from django.contrib import admin

from .models import LiveClass, LiveClassAttendance, LiveClassRegistrant


@admin.register(LiveClass)
class LiveClassAdmin(admin.ModelAdmin):
    list_display = ['title', 'course', 'topic', 'provider', 'status', 'scheduled_start', 'zoom_meeting_id']
    list_filter = ['status', 'provider', 'course']
    search_fields = ['title', 'zoom_meeting_id']


@admin.register(LiveClassAttendance)
class LiveClassAttendanceAdmin(admin.ModelAdmin):
    list_display = ['live_class', 'display_name', 'email', 'status', 'duration_minutes', 'source']
    list_filter = ['status', 'source', 'is_manual_override']
    search_fields = ['display_name', 'email']
    raw_id_fields = ['live_class', 'student']


@admin.register(LiveClassRegistrant)
class LiveClassRegistrantAdmin(admin.ModelAdmin):
    list_display = ['live_class', 'email', 'zoom_registrant_id']
    search_fields = ['email', 'zoom_registrant_id']
    raw_id_fields = ['live_class', 'student']
