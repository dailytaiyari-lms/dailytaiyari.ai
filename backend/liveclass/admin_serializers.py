"""Admin/instructor authoring serializers for live classes."""
from rest_framework import serializers

from .models import LiveClass, LiveClassAttendance


class AdminLiveClassSerializer(serializers.ModelSerializer):
    topic_name = serializers.CharField(source='topic.name', read_only=True)
    subject_name = serializers.CharField(source='subject.name', read_only=True, default=None)
    provider_display = serializers.CharField(source='get_provider_display', read_only=True)
    scheduled_end = serializers.DateTimeField(read_only=True)
    live_status = serializers.CharField(read_only=True)
    zoom_linked = serializers.BooleanField(read_only=True)
    supports_attendance = serializers.BooleanField(read_only=True)
    # Surfaced so the modal can explain *why* a Zoom meeting was not created.
    zoom_error = serializers.SerializerMethodField()

    class Meta:
        model = LiveClass
        fields = [
            'id', 'course', 'subject', 'subject_name', 'topic', 'topic_name',
            'title', 'description', 'provider', 'provider_display', 'meeting_url',
            'scheduled_start', 'duration_minutes', 'scheduled_end', 'host_name',
            'status', 'live_status', 'order', 'created_at', 'updated_at',
            # Zoom
            'zoom_meeting_id', 'zoom_start_url', 'zoom_passcode',
            'zoom_registration_enabled', 'zoom_started_at', 'zoom_ended_at',
            'zoom_linked', 'supports_attendance',
            'attendance_synced_at', 'attendance_sync_error', 'zoom_error',
        ]
        read_only_fields = [
            'created_at', 'updated_at', 'zoom_meeting_id', 'zoom_start_url',
            'zoom_passcode', 'zoom_registration_enabled', 'zoom_started_at',
            'zoom_ended_at', 'attendance_synced_at', 'attendance_sync_error',
        ]

    def get_zoom_error(self, obj):
        # Set transiently by the viewset when Zoom rejected a create/update.
        return getattr(obj, '_zoom_error', '')

    def validate_provider(self, value):
        if value not in LiveClass.ENABLED_PROVIDERS:
            label = dict(LiveClass.PROVIDER_CHOICES).get(value, value)
            raise serializers.ValidationError(
                f'{label} is coming soon and cannot be used yet. '
                'Please use Google Meet or Zoom.'
            )
        return value

    def validate(self, attrs):
        # Resolve provider/url whether creating or partially updating.
        provider = attrs.get('provider', getattr(self.instance, 'provider', LiveClass.PROVIDER_GMEET))
        meeting_url = attrs.get('meeting_url', getattr(self.instance, 'meeting_url', ''))
        if provider == LiveClass.PROVIDER_GMEET and not (meeting_url or '').strip():
            raise serializers.ValidationError(
                {'meeting_url': 'A Google Meet link is required for a Google Meet live class.'}
            )
        if provider == LiveClass.PROVIDER_ZOOM:
            # A Zoom class needs a start time so we can schedule the meeting.
            start = attrs.get(
                'scheduled_start', getattr(self.instance, 'scheduled_start', None)
            )
            if not start:
                raise serializers.ValidationError(
                    {'scheduled_start': 'A start time is required to schedule a Zoom meeting.'}
                )
            # When Zoom is not connected the admin may still paste a link by
            # hand; that fallback is validated in the viewset, which knows the
            # tenant's connection state.
        return attrs


class AdminLiveClassAttendanceSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    student_email = serializers.SerializerMethodField()
    attendance_percent = serializers.IntegerField(read_only=True)
    is_guest = serializers.SerializerMethodField()

    class Meta:
        model = LiveClassAttendance
        fields = [
            'id', 'student', 'student_name', 'student_email', 'is_guest',
            'display_name', 'email', 'first_joined_at', 'last_left_at',
            'duration_minutes', 'attendance_percent', 'join_count',
            'is_currently_in_call', 'status', 'source', 'is_manual_override',
            'notes', 'created_at', 'updated_at',
        ]
        read_only_fields = fields

    def get_student_name(self, obj):
        user = getattr(obj.student, 'user', None) if obj.student_id else None
        return (getattr(user, 'full_name', '') or obj.display_name or '').strip()

    def get_student_email(self, obj):
        user = getattr(obj.student, 'user', None) if obj.student_id else None
        return getattr(user, 'email', '') or obj.email

    def get_is_guest(self, obj):
        return obj.student_id is None
