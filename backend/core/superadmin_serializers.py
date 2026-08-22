"""Serializers for the platform super-admin dashboard.

The super admin is a Django superuser (``is_superuser=True``, ``tenant=None``)
who owns the whole platform. These serializers power login and tenant
management for the dedicated super-admin frontend — they are never exposed to
tenant users.
"""
from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from .models import Tenant, SuperAdminAuditLog, PlatformAnnouncement, DemoBooking, ContactMessage, JobApplication

User = get_user_model()


class SuperAdminLoginSerializer(serializers.Serializer):
    """Authenticate a platform super admin by email + password.

    Only ``is_superuser`` accounts may authenticate here. Super admins are
    tenant-less, so — unlike the tenant login — no ``X-Tenant-ID`` is required.
    """

    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, style={'input_type': 'password'})

    def validate(self, attrs):
        email = attrs.get('email')
        password = attrs.get('password')

        # An email may exist under multiple tenants; only superusers count here.
        user = None
        for candidate in User.objects.filter(email__iexact=email, is_superuser=True):
            if candidate.check_password(password):
                user = candidate
                break

        if user is None:
            raise serializers.ValidationError('Invalid credentials or not a super admin.')
        if not user.is_active:
            raise serializers.ValidationError('This account is disabled.')

        refresh = RefreshToken.for_user(user)
        refresh['email'] = user.email
        refresh['is_superuser'] = True

        self.user = user
        return {
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'user': SuperAdminUserSerializer(user).data,
        }


class SuperAdminUserSerializer(serializers.ModelSerializer):
    """Minimal identity payload for the logged-in super admin."""

    name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'email', 'name', 'first_name', 'last_name', 'is_superuser']
        read_only_fields = fields

    def get_name(self, obj):
        return obj.full_name or obj.email


class TenantListSerializer(serializers.ModelSerializer):
    """A tenant row for the dashboard list, with rolled-up counts."""

    user_count = serializers.SerializerMethodField()
    student_count = serializers.SerializerMethodField()
    admin_count = serializers.SerializerMethodField()
    course_count = serializers.SerializerMethodField()
    is_billing_frozen = serializers.BooleanField(read_only=True)

    class Meta:
        model = Tenant
        fields = [
            'id', 'name', 'tagline', 'subdomain', 'theme', 'is_active',
            'is_suspended', 'plan', 'billing_status', 'is_billing_frozen',
            'user_count', 'student_count', 'admin_count', 'course_count',
            'created_at', 'updated_at',
        ]
        read_only_fields = fields

    def get_user_count(self, obj):
        return getattr(obj, 'user_count', None) if hasattr(obj, 'user_count') else obj.users.count()

    def get_student_count(self, obj):
        if hasattr(obj, 'student_count'):
            return obj.student_count
        return obj.users.filter(role='student').count()

    def get_admin_count(self, obj):
        if hasattr(obj, 'admin_count'):
            return obj.admin_count
        return obj.users.filter(role='admin').count()

    def get_course_count(self, obj):
        if hasattr(obj, 'course_count'):
            return obj.course_count
        return obj.courses.count()


class TenantDetailSerializer(serializers.ModelSerializer):
    """Read/update a single tenant from the super-admin dashboard.

    The super admin may edit branding, the subdomain, active status, theme and
    per-feature toggles. Feature updates are merged onto the stored map so
    partial updates are safe, and only known keys are accepted.
    """

    features = serializers.JSONField(required=False)
    feature_locks = serializers.JSONField(required=False)
    user_count = serializers.SerializerMethodField()
    student_count = serializers.SerializerMethodField()
    admin_count = serializers.SerializerMethodField()
    course_count = serializers.SerializerMethodField()
    ai_usage = serializers.SerializerMethodField()

    class Meta:
        model = Tenant
        fields = [
            'id', 'name', 'tagline', 'subdomain', 'theme', 'show_name',
            'is_active', 'is_suspended', 'suspension_message',
            'features', 'feature_locks',
            'request_enrollment_free', 'request_enrollment_paid',
            'plan', 'billing_status', 'trial_ends_at', 'current_period_end',
            'max_students', 'max_courses', 'max_admins',
            'ai_platform_monthly_tokens', 'ai_usage',
            'allowed_origins',
            'user_count', 'student_count', 'admin_count', 'course_count',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'created_at', 'updated_at',
            'user_count', 'student_count', 'admin_count', 'course_count',
            'ai_usage',
        ]

    def get_user_count(self, obj):
        return obj.users.count()

    def get_student_count(self, obj):
        return obj.users.filter(role='student').count()

    def get_admin_count(self, obj):
        return obj.users.filter(role='admin').count()

    def get_course_count(self, obj):
        return obj.courses.count()

    def get_ai_usage(self, obj):
        """Whether this tenant runs on its own LLM key, and what the platform key cost.

        ``platform_*`` numbers are the only ones the platform pays for, so this
        is what the super admin watches before raising a grant.
        """
        from django.db.models import Sum

        from chatbot.models import AIProviderConfig, AIUsageRecord
        from chatbot.resolver import month_start, platform_allowance, tokens_used

        active = (
            AIProviderConfig.objects.filter(tenant=obj, is_active=True)
            .values_list('provider', flat=True)
            .first()
        )
        granted, used, remaining = platform_allowance(obj)
        platform_cost = AIUsageRecord.objects.filter(
            tenant=obj,
            source=AIUsageRecord.SOURCE_PLATFORM,
            created_at__gte=month_start(),
        ).aggregate(total=Sum('estimated_cost_usd'))['total'] or 0
        return {
            'own_provider': active,
            'has_own_key': bool(active),
            'platform_granted_tokens': granted,
            'platform_used_tokens': used,
            'platform_remaining_tokens': remaining,
            'month_total_tokens': tokens_used(obj, month_start()),
            'month_platform_cost_usd': float(platform_cost),
        }

    def validate_theme(self, value):
        if value and value not in Tenant.THEME_CHOICES:
            raise serializers.ValidationError(
                'Unknown theme. Choose one of: ' + ', '.join(Tenant.THEME_CHOICES)
            )
        return value

    def validate_subdomain(self, value):
        if not value:
            return value
        value = value.strip().lower()
        qs = Tenant.objects.filter(subdomain=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError('This subdomain is already in use.')
        return value

    def validate_features(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError(
                'features must be an object mapping feature keys to booleans.'
            )
        return {k: bool(v) for k, v in value.items() if k in Tenant.FEATURE_CHOICES}

    def validate_feature_locks(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError(
                'feature_locks must be an object mapping feature keys to booleans.'
            )
        return {k: bool(v) for k, v in value.items() if k in Tenant.FEATURE_CHOICES}

    def validate_plan(self, value):
        if value and value not in Tenant.PLAN_CHOICES:
            raise serializers.ValidationError(
                'Unknown plan. Choose one of: ' + ', '.join(Tenant.PLAN_CHOICES)
            )
        return value

    def validate_billing_status(self, value):
        if value and value not in Tenant.BILLING_STATUS_CHOICES:
            raise serializers.ValidationError(
                'Unknown billing status. Choose one of: '
                + ', '.join(Tenant.BILLING_STATUS_CHOICES)
            )
        return value

    def validate_allowed_origins(self, value):
        """Normalize to a de-duplicated list of clean http(s) origins."""
        if value in (None, ''):
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError(
                'allowed_origins must be a list of origin URLs.'
            )
        cleaned = []
        seen = set()
        for raw in value:
            if not isinstance(raw, str):
                raise serializers.ValidationError('Each origin must be a string.')
            origin = raw.strip().rstrip('/')
            if not origin:
                continue
            if not (origin.startswith('http://') or origin.startswith('https://')):
                raise serializers.ValidationError(
                    f'"{raw}" must start with http:// or https://'
                )
            if '/' in origin.split('://', 1)[1]:
                raise serializers.ValidationError(
                    f'"{raw}" must be a bare origin (scheme + host [+ port]), no path.'
                )
            if origin not in seen:
                seen.add(origin)
                cleaned.append(origin)
        return cleaned

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['features'] = instance.get_features()
        data['feature_locks'] = instance.get_feature_locks()
        data['locked_features'] = instance.locked_feature_keys()
        data['available_features'] = [
            {
                'key': k,
                'label': label,
                'tenant_label': instance.get_feature_labels().get(k, label),
            }
            for k, label in Tenant.FEATURE_CHOICES.items()
        ]
        data['available_themes'] = [
            {'key': k, 'label': label} for k, label in Tenant.THEME_CHOICES.items()
        ]
        data['available_plans'] = [
            {'key': k, 'label': label, 'defaults': Tenant.PLAN_DEFAULTS.get(k, {})}
            for k, label in Tenant.PLAN_CHOICES.items()
        ]
        data['billing_statuses'] = [
            {'key': k, 'label': label}
            for k, label in Tenant.BILLING_STATUS_CHOICES.items()
        ]
        data['quota_status'] = instance.quota_status()
        data['is_billing_frozen'] = instance.is_billing_frozen
        return data

    def update(self, instance, validated_data):
        features = validated_data.pop('features', None)
        if features is not None:
            instance.features = {**(instance.features or {}), **features}
        # feature_locks is replaced wholesale (it is the complete lock map the
        # super admin intends), not merged, so unlocking removes the key.
        locks = validated_data.pop('feature_locks', None)
        if locks is not None:
            instance.feature_locks = locks
        # When the plan changes and the caller didn't also send explicit caps,
        # seed the max_* caps from the new plan's defaults. Explicit caps in the
        # same payload always win.
        new_plan = validated_data.get('plan')
        plan_changed = new_plan is not None and new_plan != instance.plan
        instance = super().update(instance, validated_data)
        if plan_changed and not any(
            k in validated_data for k in ('max_students', 'max_courses', 'max_admins')
        ):
            instance.apply_plan_defaults()
            instance.save(update_fields=['max_students', 'max_courses', 'max_admins'])
        return instance


class TenantCreateSerializer(serializers.ModelSerializer):
    """Create a brand-new tenant from the super-admin dashboard."""

    class Meta:
        model = Tenant
        fields = ['id', 'name', 'tagline', 'subdomain', 'theme', 'is_active']

    def validate_subdomain(self, value):
        if not value:
            return value
        value = value.strip().lower()
        if Tenant.objects.filter(subdomain=value).exists():
            raise serializers.ValidationError('This subdomain is already in use.')
        return value

    def validate_theme(self, value):
        if value and value not in Tenant.THEME_CHOICES:
            raise serializers.ValidationError(
                'Unknown theme. Choose one of: ' + ', '.join(Tenant.THEME_CHOICES)
            )
        return value


class SuperAdminAuditLogSerializer(serializers.ModelSerializer):
    """Read-only view of a super-admin audit trail entry."""

    tenant_name = serializers.CharField(source='target_name', read_only=True)
    tenant_id = serializers.PrimaryKeyRelatedField(
        source='target_tenant', read_only=True
    )

    class Meta:
        model = SuperAdminAuditLog
        fields = [
            'id', 'actor_email', 'action', 'tenant_id', 'tenant_name',
            'changes', 'created_at',
        ]
        read_only_fields = fields


# ── Phase 3: cross-tenant user management ──────────────────────────────────
class SuperAdminUserListSerializer(serializers.ModelSerializer):
    """A user row for the platform-wide user table (read-only)."""

    name = serializers.SerializerMethodField()
    tenant_id = serializers.PrimaryKeyRelatedField(source='tenant', read_only=True)
    tenant_name = serializers.SerializerMethodField()
    role_label = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'email', 'name', 'first_name', 'last_name',
            'role', 'role_label', 'tenant_id', 'tenant_name',
            'is_active', 'is_suspended', 'is_email_verified',
            'last_active', 'created_at',
        ]
        read_only_fields = fields

    def get_name(self, obj):
        return obj.full_name or obj.email

    def get_tenant_name(self, obj):
        return obj.tenant.name if obj.tenant_id else None

    def get_role_label(self, obj):
        return dict(User.ROLE_CHOICES).get(obj.role, obj.role)


# ── Phase 3: support inbox (platform leads) ────────────────────────────────
class _BaseLeadSerializer(serializers.ModelSerializer):
    """Shared representation for the three PlatformLead subclasses."""

    lead_type = serializers.SerializerMethodField()
    status_label = serializers.SerializerMethodField()

    LEAD_TYPE = ''

    def get_lead_type(self, obj):
        return self.LEAD_TYPE

    def get_status_label(self, obj):
        return dict(obj.STATUS_CHOICES).get(obj.status, obj.status)


class DemoBookingSerializer(_BaseLeadSerializer):
    LEAD_TYPE = 'demo'

    class Meta:
        model = DemoBooking
        fields = [
            'id', 'lead_type', 'name', 'email', 'phone', 'organization',
            'organization_type', 'message', 'status', 'status_label',
            'source', 'internal_notes', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'lead_type', 'name', 'email', 'phone', 'organization',
            'organization_type', 'message', 'status_label', 'source',
            'created_at', 'updated_at',
        ]


class ContactMessageSerializer(_BaseLeadSerializer):
    LEAD_TYPE = 'contact'

    class Meta:
        model = ContactMessage
        fields = [
            'id', 'lead_type', 'name', 'email', 'subject', 'message',
            'status', 'status_label', 'source', 'internal_notes',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'lead_type', 'name', 'email', 'subject', 'message',
            'status_label', 'source', 'created_at', 'updated_at',
        ]


class JobApplicationSerializer(_BaseLeadSerializer):
    LEAD_TYPE = 'job'

    class Meta:
        model = JobApplication
        fields = [
            'id', 'lead_type', 'name', 'email', 'phone', 'position',
            'experience', 'portfolio_url', 'cover_letter',
            'status', 'status_label', 'source', 'internal_notes',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'lead_type', 'name', 'email', 'phone', 'position',
            'experience', 'portfolio_url', 'cover_letter', 'status_label',
            'source', 'created_at', 'updated_at',
        ]


# Registry: lead type key -> (model, serializer). Used by the lead views.
LEAD_REGISTRY = {
    'demo': (DemoBooking, DemoBookingSerializer),
    'contact': (ContactMessage, ContactMessageSerializer),
    'job': (JobApplication, JobApplicationSerializer),
}


# ── Phase 3: platform announcements ────────────────────────────────────────
class AnnouncementSerializer(serializers.ModelSerializer):
    """Read/write a platform announcement from the super-admin dashboard."""

    target_tenant = serializers.PrimaryKeyRelatedField(
        queryset=Tenant.objects.all(), required=False, allow_null=True,
    )
    target_tenant_name = serializers.SerializerMethodField()
    level_label = serializers.SerializerMethodField()
    is_live = serializers.SerializerMethodField()
    created_by_email = serializers.EmailField(
        source='created_by.email', read_only=True, default='',
    )

    class Meta:
        model = PlatformAnnouncement
        fields = [
            'id', 'title', 'body', 'level', 'level_label',
            'target_tenant', 'target_tenant_name',
            'is_active', 'starts_at', 'ends_at', 'is_live',
            'created_by_email', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'level_label', 'target_tenant_name', 'is_live',
            'created_by_email', 'created_at', 'updated_at',
        ]

    def get_target_tenant_name(self, obj):
        return obj.target_tenant.name if obj.target_tenant_id else None

    def get_level_label(self, obj):
        return PlatformAnnouncement.LEVEL_CHOICES.get(obj.level, obj.level)

    def get_is_live(self, obj):
        return obj.is_live()

    def validate_level(self, value):
        if value not in PlatformAnnouncement.LEVEL_CHOICES:
            raise serializers.ValidationError(
                'Unknown level. Choose one of: '
                + ', '.join(PlatformAnnouncement.LEVEL_CHOICES)
            )
        return value

    def validate(self, attrs):
        starts = attrs.get('starts_at', getattr(self.instance, 'starts_at', None))
        ends = attrs.get('ends_at', getattr(self.instance, 'ends_at', None))
        if starts and ends and ends < starts:
            raise serializers.ValidationError(
                {'ends_at': 'End time must be after the start time.'}
            )
        return attrs
