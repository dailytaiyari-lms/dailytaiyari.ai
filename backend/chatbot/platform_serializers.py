"""Serializers for the super admin's "AI Platform" screen.

These describe the platform's *own* LLM accounts and how they are lent to
tenants. API keys are write-only everywhere: a key that has been saved is
reported only as a masked hint, never in full, not even to a super admin.
"""
from rest_framework import serializers

from .models import (
    AIProviderConfig,
    PlatformAIModel,
    PlatformAIProvider,
    TenantAIAllocation,
)


def mask_key(raw):
    """A recognisable-but-useless hint, e.g. ``sk-…4f2a``."""
    if not raw:
        return ''
    if len(raw) <= 8:
        return '•' * len(raw)
    return f'{raw[:3]}…{raw[-4:]}'


class PlatformAIModelSerializer(serializers.ModelSerializer):
    display_label = serializers.CharField(read_only=True)
    is_usable = serializers.BooleanField(read_only=True)
    provider_name = serializers.CharField(source='provider.name', read_only=True)
    provider_key = serializers.CharField(source='provider.provider', read_only=True)

    class Meta:
        model = PlatformAIModel
        fields = [
            'id', 'provider', 'provider_name', 'provider_key', 'model_name',
            'label', 'display_label', 'description', 'input_cost_per_million',
            'output_cost_per_million', 'max_output_tokens', 'is_enabled',
            'sort_order', 'is_usable',
        ]
        read_only_fields = ['id', 'provider']


class PlatformAIProviderSerializer(serializers.ModelSerializer):
    """A platform LLM account. ``api_key`` is write-only by design."""

    models = PlatformAIModelSerializer(many=True, read_only=True)
    api_key = serializers.CharField(write_only=True, required=False, allow_blank=True)
    api_key_hint = serializers.SerializerMethodField()
    has_api_key = serializers.SerializerMethodField()
    is_configured = serializers.BooleanField(read_only=True)
    provider_label = serializers.CharField(source='get_provider_display', read_only=True)

    class Meta:
        model = PlatformAIProvider
        fields = [
            'id', 'name', 'provider', 'provider_label', 'base_url', 'api_version',
            'is_enabled', 'notes', 'sort_order', 'api_key', 'api_key_hint',
            'has_api_key', 'is_configured', 'models',
            'last_tested_at', 'last_test_ok', 'last_test_error',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'last_tested_at', 'last_test_ok', 'last_test_error',
            'created_at', 'updated_at',
        ]

    def get_api_key_hint(self, obj):
        return mask_key(obj.api_key)

    def get_has_api_key(self, obj):
        return bool(obj.api_key_encrypted)

    def validate(self, attrs):
        provider = attrs.get('provider', getattr(self.instance, 'provider', ''))
        base_url = attrs.get('base_url', getattr(self.instance, 'base_url', ''))
        needs_url = provider in (
            AIProviderConfig.PROVIDER_AZURE,
            AIProviderConfig.PROVIDER_CUSTOM,
            AIProviderConfig.PROVIDER_OLLAMA,
        )
        if needs_url and not base_url:
            raise serializers.ValidationError({
                'base_url': 'This provider needs an endpoint URL.'
            })
        return attrs

    def _apply_key(self, instance, validated):
        # An omitted key means "leave it alone"; an explicitly blank one clears it.
        if 'api_key' in validated:
            instance.api_key = validated.pop('api_key')

    def create(self, validated_data):
        key = validated_data.pop('api_key', '')
        instance = PlatformAIProvider(**validated_data)
        instance.api_key = key
        instance.save()
        return instance

    def update(self, instance, validated_data):
        self._apply_key(instance, validated_data)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        return instance


class TenantAIAllocationSerializer(serializers.ModelSerializer):
    """The super admin's half of a tenant's grant."""

    granted_models = serializers.PrimaryKeyRelatedField(
        many=True, queryset=PlatformAIModel.objects.all(), required=False
    )
    default_model = serializers.PrimaryKeyRelatedField(
        queryset=PlatformAIModel.objects.all(), required=False, allow_null=True
    )
    tenant_name = serializers.CharField(source='tenant.name', read_only=True)

    class Meta:
        model = TenantAIAllocation
        fields = [
            'id', 'tenant', 'tenant_name', 'is_enabled', 'granted_models',
            'default_model', 'monthly_token_limit', 'monthly_cost_limit_usd',
            'notify_at_percent', 'updated_at',
        ]
        read_only_fields = ['id', 'tenant', 'updated_at']

    def validate(self, attrs):
        granted = attrs.get('granted_models')
        default = attrs.get('default_model', serializers.empty)
        if default not in (serializers.empty, None):
            pool = granted if granted is not None else list(
                self.instance.granted_models.all() if self.instance else []
            )
            if default not in pool:
                raise serializers.ValidationError({
                    'default_model': 'The default must be one of the granted models.'
                })
        percent = attrs.get('notify_at_percent')
        if percent is not None and not (1 <= percent <= 100):
            raise serializers.ValidationError({
                'notify_at_percent': 'Must be between 1 and 100.'
            })
        return attrs
