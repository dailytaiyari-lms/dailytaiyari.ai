"""Serializers for tenant-admin managed settings (branding + feature toggles)."""
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from rest_framework import serializers

from .models import Tenant, PaymentGateway, ZoomIntegration


class TenantSettingsSerializer(serializers.ModelSerializer):
    """Read/update a tenant's branding (name, logo) and feature toggles.

    ``features`` is always represented as the full, defaulted feature map.
    Updates are merged onto the stored dict so partial updates are safe, and
    only known feature keys are accepted.
    """

    features = serializers.JSONField(required=False)
    auth_panel = serializers.JSONField(required=False)
    logo = serializers.ImageField(required=False, allow_null=True)
    favicon = serializers.ImageField(required=False, allow_null=True)

    class Meta:
        model = Tenant
        fields = [
            'id', 'name', 'tagline', 'subdomain', 'logo', 'favicon', 'theme',
            'show_name', 'features', 'auth_panel',
            'request_enrollment_free', 'request_enrollment_paid',
            'notification_email',
        ]
        read_only_fields = ['id', 'subdomain']

    def validate_notification_email(self, value):
        """Accept a comma/newline/semicolon-separated list of email addresses."""
        if not value or not value.strip():
            return ''
        raw = value.replace('\n', ',').replace(';', ',')
        cleaned = []
        for part in raw.split(','):
            addr = part.strip()
            if not addr:
                continue
            try:
                validate_email(addr)
            except DjangoValidationError:
                raise serializers.ValidationError(
                    f'"{addr}" is not a valid email address.'
                )
            if addr.lower() not in [a.lower() for a in cleaned]:
                cleaned.append(addr)
        return ', '.join(cleaned)

    def validate_theme(self, value):
        if value not in Tenant.THEME_CHOICES:
            raise serializers.ValidationError(
                'Unknown theme. Choose one of: '
                + ', '.join(Tenant.THEME_CHOICES)
            )
        return value

    def validate_features(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError(
                'features must be an object mapping feature keys to booleans.'
            )
        instance = self.instance
        locked = set(instance.locked_feature_keys()) if instance else set()
        cleaned = {}
        blocked = []
        for key, enabled in value.items():
            if key not in Tenant.FEATURE_CHOICES:
                continue
            if key in locked:
                # The super admin has locked this feature. Silently ignore a
                # no-op, but reject any attempt to actually change it.
                current = instance.get_features().get(key)
                if bool(enabled) != bool(current):
                    blocked.append(Tenant.FEATURE_CHOICES[key])
                continue
            cleaned[key] = bool(enabled)
        if blocked:
            raise serializers.ValidationError(
                'These features are managed by the DailyTaiyari team and can’t '
                'be changed here — please contact the DailyTaiyari team to '
                'enable or disable: ' + ', '.join(blocked) + '.'
            )
        return cleaned

    def validate_auth_panel(self, value):
        """Sanitise the login/register branding panel content.

        Accepts ``{heading, heading_highlight, subtitle, stats}``. Unknown keys
        are dropped, text is trimmed, and ``stats`` is capped to a short list of
        ``{value, label}`` pairs so a tenant can't inject arbitrary structures.
        """
        if not isinstance(value, dict):
            raise serializers.ValidationError(
                'auth_panel must be an object.'
            )

        cleaned = {}
        for key in ('heading', 'heading_highlight', 'subtitle'):
            if key in value:
                text = value.get(key)
                if text is None:
                    text = ''
                if not isinstance(text, str):
                    raise serializers.ValidationError(
                        f'{key} must be text.'
                    )
                cleaned[key] = text.strip()[:255]

        if 'stats' in value:
            stats = value.get('stats') or []
            if not isinstance(stats, list):
                raise serializers.ValidationError(
                    'stats must be a list of {value, label} items.'
                )
            cleaned_stats = []
            for item in stats[:4]:
                if not isinstance(item, dict):
                    continue
                stat_value = str(item.get('value', '')).strip()[:32]
                stat_label = str(item.get('label', '')).strip()[:48]
                if not stat_value and not stat_label:
                    continue
                cleaned_stats.append({'value': stat_value, 'label': stat_label})
            cleaned['stats'] = cleaned_stats

        return cleaned

    def validate(self, attrs):
        # Paid courses may only skip the request/approve flow when an active
        # payment gateway is configured — otherwise there is no way to collect
        # payment. Free courses are independent and can be toggled freely.
        instance = self.instance
        request_paid = attrs.get(
            'request_enrollment_paid',
            getattr(instance, 'request_enrollment_paid', True),
        )
        if request_paid is False:
            has_gateway = bool(instance and instance.has_active_payment_gateway)
            if not has_gateway:
                raise serializers.ValidationError({
                    'request_enrollment_paid': (
                        'Self-enrolment for paid courses requires an active '
                        'payment gateway. Configure and activate Razorpay, '
                        'Cashfree or PayU first, or keep request-based '
                        'enrolment enabled.'
                    )
                })
        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['features'] = instance.get_features()
        data['locked_features'] = instance.locked_feature_keys()
        data['available_features'] = [
            {'key': key, 'label': label}
            for key, label in Tenant.FEATURE_CHOICES.items()
        ]
        data['available_themes'] = [
            {'key': key, 'label': label}
            for key, label in Tenant.THEME_CHOICES.items()
        ]
        data['has_active_payment_gateway'] = instance.has_active_payment_gateway
        # Read-only plan + quota snapshot so the tenant admin can see their
        # plan, usage against caps, and any billing freeze (all managed by the
        # DailyTaiyari team).
        data['plan'] = instance.plan
        data['plan_label'] = Tenant.PLAN_CHOICES.get(instance.plan, instance.plan)
        data['billing_status'] = instance.billing_status
        data['trial_ends_at'] = (
            instance.trial_ends_at.isoformat() if instance.trial_ends_at else None
        )
        data['current_period_end'] = (
            instance.current_period_end.isoformat() if instance.current_period_end else None
        )
        data['quota_status'] = instance.quota_status()
        data['is_billing_frozen'] = instance.is_billing_frozen
        return data

    def update(self, instance, validated_data):
        features = validated_data.pop('features', None)
        if features is not None:
            instance.features = {**(instance.features or {}), **features}
        auth_panel = validated_data.pop('auth_panel', None)
        if auth_panel is not None:
            instance.auth_panel = {**(instance.auth_panel or {}), **auth_panel}
        return super().update(instance, validated_data)


class PaymentGatewaySerializer(serializers.ModelSerializer):
    """Read/write a tenant's payment gateway credentials.

    The secret is write-only: it is accepted on input, encrypted at rest, and
    never returned. Instead a boolean ``has_secret`` flag tells the UI whether a
    secret is already stored so it can leave the field blank to keep it.
    """

    # Write-only plaintext secret. Blank/omitted on update keeps the stored one.
    key_secret = serializers.CharField(
        write_only=True, required=False, allow_blank=True, style={'input_type': 'password'}
    )
    webhook_secret = serializers.CharField(
        write_only=True, required=False, allow_blank=True, style={'input_type': 'password'}
    )
    has_secret = serializers.SerializerMethodField()
    has_webhook_secret = serializers.SerializerMethodField()

    class Meta:
        model = PaymentGateway
        fields = [
            'id', 'provider', 'key_id', 'key_secret', 'has_secret',
            'webhook_secret', 'has_webhook_secret',
            'is_active', 'is_test_mode', 'is_configured',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'is_configured', 'created_at', 'updated_at']

    def get_has_secret(self, obj):
        return bool(obj.key_secret_encrypted)

    def get_has_webhook_secret(self, obj):
        return bool(obj.webhook_secret_encrypted)

    def validate_provider(self, value):
        valid = {c[0] for c in PaymentGateway.PROVIDER_CHOICES}
        if value not in valid:
            raise serializers.ValidationError(
                'Unsupported provider. Choose one of: ' + ', '.join(sorted(valid))
            )
        return value

    def validate(self, attrs):
        # A gateway can only be activated once fully configured (id + secret).
        is_active = attrs.get(
            'is_active', getattr(self.instance, 'is_active', False)
        )
        if is_active:
            key_id = attrs.get('key_id', getattr(self.instance, 'key_id', ''))
            secret = attrs.get('key_secret', None)
            has_secret = bool(secret) or bool(
                getattr(self.instance, 'key_secret_encrypted', '')
            )
            if not (key_id and has_secret):
                raise serializers.ValidationError(
                    'Provide both the key/app id and secret before activating the gateway.'
                )
        return attrs

    def create(self, validated_data):
        secret = validated_data.pop('key_secret', '')
        webhook = validated_data.pop('webhook_secret', '')
        instance = PaymentGateway(**validated_data)
        if secret:
            instance.key_secret = secret
        if webhook:
            instance.webhook_secret = webhook
        instance.save()
        return instance

    def update(self, instance, validated_data):
        # Only overwrite stored secrets when a non-blank value is supplied.
        secret = validated_data.pop('key_secret', None)
        webhook = validated_data.pop('webhook_secret', None)
        if secret:
            instance.key_secret = secret
        if webhook:
            instance.webhook_secret = webhook
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance


class ZoomIntegrationSerializer(serializers.ModelSerializer):
    """Read/write a tenant's Zoom Server-to-Server OAuth connection.

    Like the payment gateway, secrets are write-only: they are accepted on
    input, encrypted at rest and never returned. ``has_*`` booleans tell the UI
    whether a value is already stored so it can leave the field blank to keep it.
    """

    client_secret = serializers.CharField(
        write_only=True, required=False, allow_blank=True, style={'input_type': 'password'}
    )
    webhook_secret_token = serializers.CharField(
        write_only=True, required=False, allow_blank=True, style={'input_type': 'password'}
    )
    has_client_secret = serializers.SerializerMethodField()
    has_webhook_secret_token = serializers.SerializerMethodField()
    webhook_url = serializers.SerializerMethodField()
    webhook_validation_open = serializers.BooleanField(read_only=True)

    class Meta:
        model = ZoomIntegration
        fields = [
            'id', 'account_id', 'client_id', 'client_secret', 'has_client_secret',
            'webhook_secret_token', 'has_webhook_secret_token', 'webhook_url',
            'webhook_validation_open', 'webhook_validation_until',
            'host_email', 'use_registration', 'pull_reports',
            'attendance_threshold_percent', 'is_active', 'is_configured',
            'last_verified_at', 'last_error', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'is_configured', 'last_verified_at', 'last_error',
            'webhook_validation_until', 'created_at', 'updated_at',
        ]

    def get_has_client_secret(self, obj):
        return bool(obj.client_secret_encrypted)

    def get_has_webhook_secret_token(self, obj):
        return bool(obj.webhook_secret_token_encrypted)

    def get_webhook_url(self, obj):
        """The URL the admin must paste into their Zoom app's event subscription.

        Tenant-scoped, so events and the validation challenge are pinned to this
        academy's Secret Token instead of being resolved against every tenant.
        """
        request = self.context.get('request')
        tenant_id = getattr(obj, 'tenant_id', None) or getattr(
            getattr(request, 'tenant', None), 'id', None
        )
        if not tenant_id:
            return ''
        path = f'/api/v1/live-classes/zoom/webhook/{tenant_id}/'
        return request.build_absolute_uri(path) if request else path

    def validate_attendance_threshold_percent(self, value):
        if not 1 <= int(value) <= 100:
            raise serializers.ValidationError('Choose a threshold between 1 and 100 percent.')
        return value

    def validate(self, attrs):
        is_active = attrs.get('is_active', getattr(self.instance, 'is_active', False))
        if is_active:
            account_id = attrs.get('account_id', getattr(self.instance, 'account_id', ''))
            client_id = attrs.get('client_id', getattr(self.instance, 'client_id', ''))
            has_secret = bool(attrs.get('client_secret')) or bool(
                getattr(self.instance, 'client_secret_encrypted', '')
            )
            if not (account_id and client_id and has_secret):
                raise serializers.ValidationError(
                    'Provide the Account ID, Client ID and Client Secret before '
                    'turning the Zoom connection on.'
                )
        return attrs

    def create(self, validated_data):
        secret = validated_data.pop('client_secret', '')
        webhook = validated_data.pop('webhook_secret_token', '')
        instance = ZoomIntegration(**validated_data)
        if secret:
            instance.client_secret = secret
        if webhook:
            instance.webhook_secret_token = webhook
        instance.save()
        return instance

    def update(self, instance, validated_data):
        # Only overwrite stored secrets when a non-blank value is supplied.
        secret = validated_data.pop('client_secret', None)
        webhook = validated_data.pop('webhook_secret_token', None)
        if secret:
            instance.client_secret = secret
        if webhook:
            instance.webhook_secret_token = webhook
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance
