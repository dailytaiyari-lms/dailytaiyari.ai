"""Serializers for the AI Course Builder admin API."""
from rest_framework import serializers

from .models import CourseGenerationJob
from .prompts import MATERIAL_TYPES, requested_materials
from .schema import (
    MAX_TOPICS_PER_CONTENT_JOB,
    draft_summary,
    normalize_content,
    normalize_meta,
    normalize_outline,
)


class CourseGenerationJobSerializer(serializers.ModelSerializer):
    """Full job, including the reviewable draft."""

    course_name = serializers.CharField(source='course.name', read_only=True, default='')
    created_by_name = serializers.SerializerMethodField()
    summary = serializers.SerializerMethodField()
    can_apply = serializers.SerializerMethodField()
    is_running = serializers.BooleanField(read_only=True)

    class Meta:
        model = CourseGenerationJob
        fields = [
            'id', 'kind', 'status', 'is_running', 'prompt', 'input_mode', 'options',
            'provider', 'model', 'course', 'course_name',
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
        return draft_summary(obj.kind, obj.draft)

    def get_can_apply(self, obj):
        return obj.is_reviewable


class CourseGenerationJobListSerializer(serializers.ModelSerializer):
    """Lightweight row for the history list — no draft payload."""

    course_name = serializers.CharField(source='course.name', read_only=True, default='')
    summary = serializers.SerializerMethodField()

    class Meta:
        model = CourseGenerationJob
        fields = [
            'id', 'kind', 'status', 'prompt', 'provider', 'model',
            'course', 'course_name', 'summary', 'error',
            'total_tokens', 'estimated_cost_usd',
            'applied_at', 'created_at',
        ]
        read_only_fields = fields

    def get_summary(self, obj):
        return draft_summary(obj.kind, obj.draft)


class GenerateSerializer(serializers.Serializer):
    """A generation request from the studio."""

    kind = serializers.ChoiceField(choices=[c[0] for c in CourseGenerationJob.KIND_CHOICES])
    prompt = serializers.CharField(allow_blank=True, required=False, max_length=8000)
    input_mode = serializers.ChoiceField(
        choices=[c[0] for c in CourseGenerationJob.INPUT_CHOICES],
        required=False, default=CourseGenerationJob.INPUT_TEXT,
    )
    course = serializers.UUIDField(required=False, allow_null=True)
    provider = serializers.CharField(required=False, allow_blank=True, max_length=32)
    model = serializers.CharField(required=False, allow_blank=True, max_length=200)
    options = serializers.DictField(required=False, default=dict)
    # Content jobs only: which topics to write material for.
    topic_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, default=list
    )

    def validate(self, attrs):
        kind = attrs['kind']
        prompt = (attrs.get('prompt') or '').strip()

        if kind == CourseGenerationJob.KIND_OUTLINE and not prompt:
            raise serializers.ValidationError(
                {'prompt': 'Describe the course you want before generating.'}
            )
        if kind in (CourseGenerationJob.KIND_CONTENT, CourseGenerationJob.KIND_META):
            if not attrs.get('course'):
                raise serializers.ValidationError(
                    {'course': 'Choose the course this material belongs to.'}
                )
        if kind == CourseGenerationJob.KIND_CONTENT:
            topic_ids = attrs.get('topic_ids') or []
            if not topic_ids:
                raise serializers.ValidationError(
                    {'topic_ids': 'Select at least one topic to write material for.'}
                )
            if len(topic_ids) > MAX_TOPICS_PER_CONTENT_JOB:
                raise serializers.ValidationError({
                    'topic_ids': (
                        f'Generate material for at most {MAX_TOPICS_PER_CONTENT_JOB} '
                        'topics at a time so you can review it properly.'
                    )
                })

            options = attrs.get('options') or {}
            materials = options.get('materials')
            if materials is not None:
                if not isinstance(materials, (list, tuple)):
                    raise serializers.ValidationError(
                        {'options': 'materials must be a list.'}
                    )
                unknown = {str(m) for m in materials} - set(MATERIAL_TYPES)
                if unknown:
                    raise serializers.ValidationError({
                        'options': (
                            f'Unknown material type(s): {", ".join(sorted(unknown))}. '
                            f'Choose from {", ".join(MATERIAL_TYPES)}.'
                        )
                    })
                if not materials:
                    raise serializers.ValidationError(
                        {'options': 'Pick at least one kind of material to generate.'}
                    )
            mode = options.get('mode')
            if mode is not None and mode not in ('replace', 'add'):
                raise serializers.ValidationError(
                    {'options': 'mode must be either "replace" or "add".'}
                )
        attrs['prompt'] = prompt
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
        payload = validated_data['draft']
        if instance.kind == CourseGenerationJob.KIND_OUTLINE:
            draft = normalize_outline(payload, existing_course=instance.course)
        elif instance.kind == CourseGenerationJob.KIND_CONTENT:
            requested = [
                {
                    'id': entry.get('topic_id'),
                    'name': entry.get('topic_name'),
                    'code': entry.get('topic_code'),
                }
                for entry in (instance.draft or {}).get('topics') or []
            ]
            draft = normalize_content(
                payload,
                requested_topics=requested,
                materials=requested_materials(instance.options),
            )
        else:
            draft = normalize_meta(payload)

        instance.draft = draft
        instance.record_revision('edited', 'Draft edited by admin')
        instance.save(update_fields=['draft', 'revisions', 'updated_at'])
        return instance


class ApplySerializer(serializers.Serializer):
    """The final confirmation. Nothing is written without ``confirm=true``."""

    confirm = serializers.BooleanField()
    # Codes/ids the admin left ticked in the preview; empty means "everything".
    selection = serializers.DictField(required=False, default=dict)

    def validate_confirm(self, value):
        if not value:
            raise serializers.ValidationError(
                'Confirm the preview before this draft can be saved.'
            )
        return value
