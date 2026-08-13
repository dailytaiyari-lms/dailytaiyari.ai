"""Serializers for the AI Mock Test Builder admin API."""
from rest_framework import serializers

from .models import MockTestGenerationJob
from .schema import (
    ITEM_TYPES,
    MAX_ITEMS_PER_REQUEST,
    MAX_SECTIONS,
    draft_summary,
    normalize_mock,
)


class MockJobSerializer(serializers.ModelSerializer):
    """Full job, including the reviewable draft paper."""

    mock_test_title = serializers.CharField(source='mock_test.title', read_only=True, default='')
    course_name = serializers.CharField(source='course.name', read_only=True, default='')
    created_by_name = serializers.SerializerMethodField()
    summary = serializers.SerializerMethodField()
    can_apply = serializers.SerializerMethodField()
    is_running = serializers.BooleanField(read_only=True)

    class Meta:
        model = MockTestGenerationJob
        fields = [
            'id', 'kind', 'status', 'is_running', 'prompt', 'input_mode', 'options',
            'provider', 'model', 'mock_test', 'mock_test_title', 'course', 'course_name',
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


class MockJobListSerializer(serializers.ModelSerializer):
    """Lightweight row for history and the in-progress banners — no draft."""

    mock_test_title = serializers.CharField(source='mock_test.title', read_only=True, default='')
    summary = serializers.SerializerMethodField()
    is_running = serializers.BooleanField(read_only=True)

    class Meta:
        model = MockTestGenerationJob
        fields = [
            'id', 'kind', 'status', 'is_running', 'prompt', 'provider', 'model',
            'mock_test', 'mock_test_title', 'course', 'summary', 'error',
            'total_tokens', 'estimated_cost_usd', 'applied_at', 'applied_summary',
            'created_at', 'updated_at',
        ]
        read_only_fields = fields

    def get_summary(self, obj):
        return draft_summary(obj.draft)


class BlueprintEntrySerializer(serializers.Serializer):
    """One row of "how many questions of what kind"."""

    item_type = serializers.ChoiceField(choices=ITEM_TYPES)
    count = serializers.IntegerField(min_value=1, max_value=MAX_ITEMS_PER_REQUEST)
    marks = serializers.FloatField(required=False, min_value=0, max_value=1000)
    negative_marks = serializers.FloatField(required=False, min_value=0, max_value=1000)
    difficulty = serializers.ChoiceField(
        choices=['easy', 'medium', 'hard', 'mixed'], required=False,
    )
    section = serializers.IntegerField(required=False, min_value=0, max_value=MAX_SECTIONS - 1)
    note = serializers.CharField(required=False, allow_blank=True, max_length=300)


class GenerateSerializer(serializers.Serializer):
    """A generation request from the mock studio."""

    kind = serializers.ChoiceField(
        choices=[c[0] for c in MockTestGenerationJob.KIND_CHOICES],
        required=False, default=MockTestGenerationJob.KIND_CREATE,
    )
    prompt = serializers.CharField(allow_blank=True, required=False, max_length=8000)
    input_mode = serializers.ChoiceField(
        choices=[c[0] for c in MockTestGenerationJob.INPUT_CHOICES],
        required=False, default=MockTestGenerationJob.INPUT_TEXT,
    )
    mock_test = serializers.UUIDField(required=False, allow_null=True)
    course = serializers.UUIDField(required=False, allow_null=True)
    provider = serializers.CharField(required=False, allow_blank=True, max_length=32)
    model = serializers.CharField(required=False, allow_blank=True, max_length=200)
    options = serializers.DictField(required=False, default=dict)

    def validate(self, attrs):
        kind = attrs.get('kind') or MockTestGenerationJob.KIND_CREATE
        prompt = (attrs.get('prompt') or '').strip()
        options = attrs.get('options') or {}

        if kind == MockTestGenerationJob.KIND_MODIFY:
            if not attrs.get('mock_test'):
                raise serializers.ValidationError(
                    {'mock_test': 'Choose the mock test you want to change.'}
                )
            if len(prompt) < 3:
                raise serializers.ValidationError(
                    {'prompt': 'Describe the change you want the AI to make.'}
                )
        else:
            blueprint = options.get('blueprint')
            if not blueprint:
                raise serializers.ValidationError({
                    'options': 'Add at least one question type with a count to the blueprint.'
                })
            entries = BlueprintEntrySerializer(data=blueprint, many=True)
            entries.is_valid(raise_exception=True)
            total = sum(entry['count'] for entry in entries.validated_data)
            if total > MAX_ITEMS_PER_REQUEST:
                raise serializers.ValidationError({
                    'options': (
                        f'Generate at most {MAX_ITEMS_PER_REQUEST} questions at a time '
                        'so you can review them properly. Generate again to add more.'
                    )
                })
            if not prompt and not options.get('syllabus') and not attrs.get('course'):
                raise serializers.ValidationError({
                    'prompt': (
                        'Say what the paper should cover — a brief, a syllabus, or a '
                        'course to draw from.'
                    )
                })
            options['blueprint'] = entries.validated_data

        sections = options.get('sections')
        if sections is not None:
            if not isinstance(sections, list):
                raise serializers.ValidationError({'options': 'sections must be a list.'})
            if len(sections) > MAX_SECTIONS:
                raise serializers.ValidationError(
                    {'options': f'A paper can have at most {MAX_SECTIONS} sections.'}
                )

        mode = options.get('apply_mode')
        if mode is not None and mode not in ('replace', 'append'):
            raise serializers.ValidationError(
                {'options': 'apply_mode must be either "replace" or "append".'}
            )

        attrs['prompt'] = prompt
        attrs['options'] = options
        return attrs


class RefineSerializer(serializers.Serializer):
    instruction = serializers.CharField(max_length=4000)

    def validate_instruction(self, value):
        cleaned = value.strip()
        if len(cleaned) < 3:
            raise serializers.ValidationError('Tell the AI what to change.')
        return cleaned


class DraftUpdateSerializer(serializers.Serializer):
    """An admin's hand-edit of the draft, re-normalised before it is stored."""

    draft = serializers.DictField()

    def update(self, instance, validated_data):
        instance.draft = normalize_mock(
            validated_data['draft'],
            existing_test=(
                instance.mock_test
                if instance.kind == MockTestGenerationJob.KIND_MODIFY else None
            ),
            options=instance.options,
        )
        instance.record_revision('edited', 'Draft edited by admin')
        instance.save(update_fields=['draft', 'revisions', 'updated_at'])
        return instance


class ApplySerializer(serializers.Serializer):
    """The final confirmation. Nothing is written without ``confirm=true``."""

    confirm = serializers.BooleanField()
    # Item keys the admin left ticked in the preview; omitted means "everything".
    selection = serializers.DictField(required=False, default=dict)

    def validate_confirm(self, value):
        if not value:
            raise serializers.ValidationError(
                'Confirm the preview before this draft can be saved.'
            )
        return value
