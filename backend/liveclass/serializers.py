"""Student-facing serializers for live classes."""
from rest_framework import serializers

from .models import LiveClass


class LiveClassSerializer(serializers.ModelSerializer):
    topic_name = serializers.CharField(source='topic.name', read_only=True)
    provider_display = serializers.CharField(source='get_provider_display', read_only=True)
    scheduled_end = serializers.DateTimeField(read_only=True)
    live_status = serializers.CharField(read_only=True)
    # True when the student must call ``/join/`` to get their personal link
    # instead of opening ``meeting_url`` directly.
    requires_join_request = serializers.SerializerMethodField()

    class Meta:
        model = LiveClass
        fields = [
            'id', 'title', 'description', 'provider', 'provider_display',
            'meeting_url', 'scheduled_start', 'duration_minutes', 'scheduled_end',
            'host_name', 'status', 'live_status', 'order', 'topic', 'topic_name',
            'requires_join_request',
        ]

    def get_requires_join_request(self, obj):
        return bool(obj.zoom_linked and obj.zoom_registration_enabled)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # A registered Zoom meeting's shared link would let a student join
        # unregistered and break attendance matching, so hide it: the join
        # endpoint hands out the personal one.
        if data.get('requires_join_request'):
            data['meeting_url'] = ''
        return data
