"""Serializers for the AI Notebook Builder admin API."""
from rest_framework import serializers

from ..models import NotebookGenerationJob
from .schema import draft_summary


class NotebookGenerationJobSerializer(serializers.ModelSerializer):
    """Full job, including the reviewable draft."""

    created_by_name = serializers.SerializerMethodField()
    course_name = serializers.CharField(source='course.name', read_only=True, default='')
    topic_name = serializers.CharField(source='topic.name', read_only=True, default='')
    summary = serializers.SerializerMethodField()
    can_apply = serializers.SerializerMethodField()
    is_running = serializers.BooleanField(read_only=True)

    class Meta:
        model = NotebookGenerationJob
        fields = [
            'id', 'kind', 'status', 'is_running', 'prompt', 'options',
            'provider', 'model',
            'course', 'course_name', 'subject', 'topic', 'topic_name', 'notebook',
            'draft', 'revisions', 'error', 'summary', 'can_apply',
            'prompt_tokens', 'completion_tokens', 'total_tokens',
            'estimated_cost_usd', 'generation_ms',
            'created_by', 'created_by_name', 'applied_at', 'applied_summary',
            'created_at', 'updated_at',
        ]
        read_only_fields = fields

    def get_created_by_name(self, obj):
        user = obj.created_by
        if user is None:
            return ''
        return getattr(user, 'full_name', '') or user.email

    def get_summary(self, obj):
        return draft_summary(obj.draft)

    def get_can_apply(self, obj):
        return obj.is_reviewable


class NotebookGenerationJobListSerializer(serializers.ModelSerializer):
    """Lightweight history row — no full draft payload."""

    course_name = serializers.CharField(source='course.name', read_only=True, default='')
    topic_name = serializers.CharField(source='topic.name', read_only=True, default='')
    summary = serializers.SerializerMethodField()
    is_running = serializers.BooleanField(read_only=True)

    class Meta:
        model = NotebookGenerationJob
        fields = [
            'id', 'kind', 'status', 'is_running', 'prompt', 'provider', 'model',
            'course', 'course_name', 'topic', 'topic_name', 'notebook',
            'summary', 'error', 'total_tokens', 'estimated_cost_usd',
            'applied_at', 'created_at',
        ]
        read_only_fields = fields

    def get_summary(self, obj):
        return draft_summary(obj.draft)


class GenerateSerializer(serializers.Serializer):
    """A notebook generation request from the studio."""

    prompt = serializers.CharField(max_length=8000)
    course = serializers.UUIDField()
    topic = serializers.UUIDField()
    subject = serializers.UUIDField(required=False, allow_null=True)
    provider = serializers.CharField(required=False, allow_blank=True, max_length=32)
    model = serializers.CharField(required=False, allow_blank=True, max_length=200)
    options = serializers.DictField(required=False, default=dict)

    def validate_prompt(self, value):
        cleaned = (value or '').strip()
        if len(cleaned) < 3:
            raise serializers.ValidationError('Describe the notebook you want.')
        return cleaned

    def validate_options(self, value):
        value = value or {}
        difficulty = value.get('difficulty')
        if difficulty is not None and difficulty not in ('easy', 'medium', 'hard'):
            raise serializers.ValidationError('difficulty must be easy, medium or hard.')
        answer_cells = value.get('answer_cells')
        if answer_cells is not None:
            try:
                n = int(answer_cells)
            except (TypeError, ValueError):
                raise serializers.ValidationError('answer_cells must be a number.')
            if not (0 <= n <= 10):
                raise serializers.ValidationError('answer_cells must be between 0 and 10.')
        return value


class RefineSerializer(serializers.Serializer):
    instruction = serializers.CharField(max_length=4000)

    def validate_instruction(self, value):
        cleaned = (value or '').strip()
        if len(cleaned) < 3:
            raise serializers.ValidationError('Tell the AI what to change.')
        return cleaned


class ApplySerializer(serializers.Serializer):
    """The final confirmation. Nothing is written without ``confirm=true``."""

    confirm = serializers.BooleanField()

    def validate_confirm(self, value):
        if not value:
            raise serializers.ValidationError(
                'Confirm the preview before this draft can be saved.'
            )
        return value
