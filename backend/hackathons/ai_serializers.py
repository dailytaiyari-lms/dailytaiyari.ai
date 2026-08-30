"""Serializers for the AI Hackathon Studio admin API."""
from rest_framework import serializers

from .models import HackathonGenerationJob
from .schema import (
    ITEM_TYPES,
    MAX_ITEMS_PER_REQUEST,
    MAX_STAGES,
    draft_summary,
    normalize_draft,
)


class AIJobSerializer(serializers.ModelSerializer):
    """Full job, including the reviewable draft."""

    hackathon_title = serializers.CharField(
        source='hackathon.title', read_only=True, default='',
    )
    stage_title = serializers.CharField(source='stage.title', read_only=True, default='')
    created_by_name = serializers.SerializerMethodField()
    summary = serializers.SerializerMethodField()
    is_running = serializers.BooleanField(read_only=True)
    can_apply = serializers.BooleanField(read_only=True)

    class Meta:
        model = HackathonGenerationJob
        fields = [
            'id', 'kind', 'status', 'is_running', 'can_apply', 'prompt', 'options',
            'provider', 'model', 'hackathon', 'hackathon_title', 'stage', 'stage_title',
            'draft', 'revisions', 'error', 'summary',
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


class AIJobListSerializer(serializers.ModelSerializer):
    """Lightweight history row — no draft payload."""

    hackathon_title = serializers.CharField(
        source='hackathon.title', read_only=True, default='',
    )
    stage_title = serializers.CharField(source='stage.title', read_only=True, default='')
    summary = serializers.SerializerMethodField()
    is_running = serializers.BooleanField(read_only=True)

    class Meta:
        model = HackathonGenerationJob
        fields = [
            'id', 'kind', 'status', 'is_running', 'prompt', 'provider', 'model',
            'hackathon', 'hackathon_title', 'stage', 'stage_title', 'summary', 'error',
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
    note = serializers.CharField(required=False, allow_blank=True, max_length=300)


class GenerateSerializer(serializers.Serializer):
    """A generation request from the hackathon studio."""

    kind = serializers.ChoiceField(
        choices=[c[0] for c in HackathonGenerationJob.KIND_CHOICES],
        required=False, default='event',
    )
    prompt = serializers.CharField(allow_blank=True, required=False, max_length=8000)
    hackathon = serializers.UUIDField(required=False, allow_null=True)
    stage = serializers.UUIDField(required=False, allow_null=True)
    provider = serializers.CharField(required=False, allow_blank=True, max_length=32)
    model = serializers.CharField(required=False, allow_blank=True, max_length=200)
    options = serializers.DictField(required=False, default=dict)

    def validate(self, attrs):
        kind = attrs.get('kind') or 'event'
        prompt = (attrs.get('prompt') or '').strip()
        options = dict(attrs.get('options') or {})

        if kind == 'event':
            if len(prompt) < 10 and not options.get('theme'):
                raise serializers.ValidationError({
                    'prompt': 'Describe the hackathon you want — theme, audience and goal.'
                })
            count = options.get('stage_count')
            if count is not None:
                try:
                    options['stage_count'] = max(0, min(int(count), MAX_STAGES))
                except (TypeError, ValueError):
                    raise serializers.ValidationError(
                        {'options': 'stage_count must be a number.'}
                    )

        elif kind == 'stages':
            if not attrs.get('hackathon'):
                raise serializers.ValidationError(
                    {'hackathon': 'Choose the hackathon these rounds belong to.'}
                )
            try:
                options['stage_count'] = max(1, min(int(options.get('stage_count') or 3),
                                                    MAX_STAGES))
            except (TypeError, ValueError):
                raise serializers.ValidationError({'options': 'stage_count must be a number.'})

        else:  # stage_content
            if not attrs.get('stage'):
                raise serializers.ValidationError(
                    {'stage': 'Choose the round these questions belong to.'}
                )
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
            options['blueprint'] = entries.validated_data

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
        instance.draft = normalize_draft(
            validated_data['draft'], instance.kind, instance.options,
        )
        instance.log('edited', 'Draft edited by admin')
        instance.save(update_fields=['draft', 'revisions', 'updated_at'])
        return instance


class ApplySerializer(serializers.Serializer):
    """The final confirmation. Nothing is written without ``confirm=true``."""

    confirm = serializers.BooleanField()
    selection = serializers.DictField(required=False, default=dict)

    def validate_confirm(self, value):
        if not value:
            raise serializers.ValidationError(
                'Confirm the preview before this draft can be saved.'
            )
        return value
