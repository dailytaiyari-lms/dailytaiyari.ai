"""Views for the platform super-admin dashboard.

Every endpoint here is restricted to Django superusers (``is_superuser=True``)
via :class:`core.permissions.IsSuperAdmin`. Because super admins are
tenant-less, this URL tree is registered under a tenant-exempt path (see
``core.middleware.TENANT_EXEMPT_PATHS``), so no ``X-Tenant-ID`` header is
required.
"""
from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import IsSuperAdmin
from .models import (
    Tenant, SuperAdminAuditLog, PlatformAnnouncement,
    DemoBooking, ContactMessage, JobApplication,
)
from .superadmin_serializers import (
    SuperAdminLoginSerializer,
    SuperAdminUserSerializer,
    SuperAdminUserListSerializer,
    TenantListSerializer,
    TenantDetailSerializer,
    TenantCreateSerializer,
    SuperAdminAuditLogSerializer,
    AnnouncementSerializer,
    LEAD_REGISTRY,
)

User = get_user_model()


# Tenant fields whose changes are worth recording in the audit trail.
_AUDITED_FIELDS = [
    'name', 'tagline', 'subdomain', 'theme', 'show_name', 'is_active',
    'is_suspended', 'suspension_message', 'features', 'feature_locks',
    'custom_email_domains_enabled',
    'request_enrollment_free', 'request_enrollment_paid',
    'plan', 'billing_status', 'trial_ends_at', 'current_period_end',
    'max_students', 'max_courses', 'max_admins',
    'allowed_origins',
]

_PLAN_FIELDS = {
    'plan', 'billing_status', 'trial_ends_at', 'current_period_end',
    'max_students', 'max_courses', 'max_admins',
}


def _snapshot(tenant):
    """Capture the audited fields of a tenant as a plain dict."""
    return {f: getattr(tenant, f) for f in _AUDITED_FIELDS}


def _json_safe(value):
    """Coerce a field value to something the audit JSONField can store."""
    if hasattr(value, 'isoformat'):  # date / datetime
        return value.isoformat()
    return value


def _diff(before, after):
    """Return {field: [old, new]} for fields that actually changed."""
    changes = {}
    for field in _AUDITED_FIELDS:
        old, new = before.get(field), after.get(field)
        if old != new:
            changes[field] = [_json_safe(old), _json_safe(new)]
    return changes


def _record_audit(request, action, tenant, changes=None):
    SuperAdminAuditLog.objects.create(
        actor=request.user if request.user.is_authenticated else None,
        actor_email=getattr(request.user, 'email', '') or '',
        action=action,
        target_tenant=tenant,
        target_name=tenant.name if tenant else '',
        changes=changes or {},
    )


def _record_action(request, action, *, target_tenant=None, target_name='', changes=None):
    """Audit an action whose target is not a tenant (user / announcement).

    ``target_tenant`` is still set when known (e.g. the user's tenant) so the
    per-tenant audit view can surface it; ``target_name`` carries the human
    label (an email or an announcement title).
    """
    SuperAdminAuditLog.objects.create(
        actor=request.user if request.user.is_authenticated else None,
        actor_email=getattr(request.user, 'email', '') or '',
        action=action,
        target_tenant=target_tenant,
        target_name=target_name or (target_tenant.name if target_tenant else ''),
        changes=changes or {},
    )


class SuperAdminLoginView(APIView):
    """POST email + password → JWT. Super admins only; no tenant header."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = SuperAdminLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.validated_data, status=status.HTTP_200_OK)


class SuperAdminMeView(APIView):
    """The currently authenticated super admin."""

    permission_classes = [permissions.IsAuthenticated, IsSuperAdmin]

    def get(self, request):
        return Response(SuperAdminUserSerializer(request.user).data)


class PlatformStatsView(APIView):
    """Platform-wide roll-up numbers for the dashboard overview."""

    permission_classes = [permissions.IsAuthenticated, IsSuperAdmin]

    def get(self, request):
        tenants = Tenant.objects.all()
        total_tenants = tenants.count()
        active_tenants = tenants.filter(is_active=True).count()
        suspended_tenants = tenants.filter(is_suspended=True).count()

        # Users belonging to a tenant (exclude platform superusers).
        tenant_users = User.objects.filter(tenant__isnull=False)
        from exams.models import Course

        # Plan distribution across tenants.
        plan_rows = tenants.values('plan').annotate(count=Count('id'))
        plan_distribution = {k: 0 for k in Tenant.PLAN_CHOICES}
        for row in plan_rows:
            plan_distribution[row['plan']] = row['count']

        # Billing-frozen and near/over-quota tenants (computed in Python since
        # the freeze + quota checks span time + related counts).
        billing_frozen = 0
        over_quota = 0
        near_quota = 0
        quota_qs = tenants.annotate(
            _students=Count('users', filter=Q(users__role='student'), distinct=True),
            _admins=Count('users', filter=Q(users__role='admin'), distinct=True),
            _courses=Count('courses', distinct=True),
        )
        for t in quota_qs:
            if t.is_billing_frozen:
                billing_frozen += 1
            usage = {'students': t._students, 'admins': t._admins, 'courses': t._courses}
            limits = t.quota_limits()
            is_over = False
            is_near = False
            for resource in Tenant.QUOTA_RESOURCES:
                limit = limits[resource]
                if limit is None or limit == 0:
                    continue
                ratio = usage[resource] / limit
                if usage[resource] >= limit:
                    is_over = True
                elif ratio >= 0.8:
                    is_near = True
            if is_over:
                over_quota += 1
            elif is_near:
                near_quota += 1

        # Support inbox: leads awaiting a first response across all channels.
        new_leads = (
            DemoBooking.objects.filter(status='new').count()
            + ContactMessage.objects.filter(status='new').count()
            + JobApplication.objects.filter(status='new').count()
        )
        active_announcements = PlatformAnnouncement.objects.filter(is_active=True).count()

        return Response({
            'total_tenants': total_tenants,
            'active_tenants': active_tenants,
            'inactive_tenants': total_tenants - active_tenants,
            'suspended_tenants': suspended_tenants,
            'billing_frozen_tenants': billing_frozen,
            'over_quota_tenants': over_quota,
            'near_quota_tenants': near_quota,
            'plan_distribution': plan_distribution,
            'new_leads': new_leads,
            'active_announcements': active_announcements,
            'total_users': tenant_users.count(),
            'total_students': tenant_users.filter(role='student').count(),
            'total_admins': tenant_users.filter(role='admin').count(),
            'total_instructors': tenant_users.filter(role='instructor').count(),
            'total_courses': Course.objects.count(),
        })


class TenantListCreateView(generics.ListCreateAPIView):
    """GET a list of all tenants (with counts) / POST to create a tenant."""

    permission_classes = [permissions.IsAuthenticated, IsSuperAdmin]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return TenantCreateSerializer
        return TenantListSerializer

    def get_queryset(self):
        qs = Tenant.objects.annotate(
            user_count=Count('users', distinct=True),
            student_count=Count('users', filter=Q(users__role='student'), distinct=True),
            admin_count=Count('users', filter=Q(users__role='admin'), distinct=True),
            course_count=Count('courses', distinct=True),
        )
        search = self.request.query_params.get('search')
        if search:
            qs = qs.filter(Q(name__icontains=search) | Q(subdomain__icontains=search))
        active = self.request.query_params.get('is_active')
        if active in ('true', 'false'):
            qs = qs.filter(is_active=(active == 'true'))
        return qs.order_by('name')

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tenant = serializer.save()
        _record_audit(request, 'tenant.create', tenant)
        return Response(
            TenantDetailSerializer(tenant).data, status=status.HTTP_201_CREATED
        )


class TenantDetailView(generics.RetrieveUpdateAPIView):
    """GET / PATCH a single tenant."""

    permission_classes = [permissions.IsAuthenticated, IsSuperAdmin]
    serializer_class = TenantDetailSerializer
    queryset = Tenant.objects.all()
    lookup_field = 'pk'
    http_method_names = ['get', 'patch', 'head', 'options']

    def update(self, request, *args, **kwargs):
        tenant = self.get_object()
        before = _snapshot(tenant)
        partial = kwargs.pop('partial', True)
        serializer = self.get_serializer(tenant, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        tenant = serializer.save()
        tenant.refresh_from_db()
        changes = _diff(before, _snapshot(tenant))
        if changes:
            action = 'tenant.update'
            changed_keys = set(changes)
            if 'is_suspended' in changes:
                action = 'tenant.suspend' if tenant.is_suspended else 'tenant.unsuspend'
            elif 'feature_locks' in changes and len(changes) == 1:
                action = 'tenant.feature_locks'
            elif changed_keys and changed_keys <= _PLAN_FIELDS:
                action = 'tenant.plan'
            elif changed_keys == {'allowed_origins'}:
                action = 'tenant.origins'
            elif changed_keys == {'custom_email_domains_enabled'}:
                action = 'tenant.email_domains'
            _record_audit(request, action, tenant, changes)
        return Response(TenantDetailSerializer(tenant).data)


class AuditLogListView(generics.ListAPIView):
    """Read the super-admin audit trail, newest first.

    Optional ``?tenant=<uuid>`` filters to a single tenant's history.
    """

    permission_classes = [permissions.IsAuthenticated, IsSuperAdmin]
    serializer_class = SuperAdminAuditLogSerializer

    def get_queryset(self):
        qs = SuperAdminAuditLog.objects.select_related('target_tenant')
        tenant_id = self.request.query_params.get('tenant')
        if tenant_id:
            qs = qs.filter(target_tenant_id=tenant_id)
        return qs


# ── Phase 3: cross-tenant user management ──────────────────────────────────
class UserListView(generics.ListAPIView):
    """Every user across every tenant, with search + filters.

    Query params: ``search`` (email/name), ``tenant`` (uuid), ``role``,
    ``status`` (active|suspended|unverified).
    """

    permission_classes = [permissions.IsAuthenticated, IsSuperAdmin]
    serializer_class = SuperAdminUserListSerializer

    def get_queryset(self):
        qs = User.objects.filter(tenant__isnull=False).select_related('tenant')
        p = self.request.query_params
        search = p.get('search')
        if search:
            qs = qs.filter(
                Q(email__icontains=search)
                | Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
            )
        tenant_id = p.get('tenant')
        if tenant_id:
            qs = qs.filter(tenant_id=tenant_id)
        role = p.get('role')
        if role in dict(User.ROLE_CHOICES):
            qs = qs.filter(role=role)
        st = p.get('status')
        if st == 'active':
            qs = qs.filter(is_active=True, is_suspended=False)
        elif st == 'suspended':
            qs = qs.filter(is_suspended=True)
        elif st == 'unverified':
            qs = qs.filter(is_email_verified=False)
        return qs.order_by('-created_at')


class UserActionView(APIView):
    """POST an administrative action against a single user.

    Body: ``{"action": "suspend"|"unsuspend"|"verify"|"reset_password"}``.
    """

    permission_classes = [permissions.IsAuthenticated, IsSuperAdmin]

    def post(self, request, pk=None):
        try:
            user = User.objects.select_related('tenant').get(pk=pk, tenant__isnull=False)
        except User.DoesNotExist:
            return Response({'detail': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)

        action = (request.data.get('action') or '').strip()

        if action == 'suspend':
            user.is_suspended = True
            user.save(update_fields=['is_suspended'])
            _record_action(request, 'user.suspend', target_tenant=user.tenant,
                           target_name=user.email, changes={'is_suspended': [False, True]})
        elif action == 'unsuspend':
            user.is_suspended = False
            user.save(update_fields=['is_suspended'])
            _record_action(request, 'user.unsuspend', target_tenant=user.tenant,
                           target_name=user.email, changes={'is_suspended': [True, False]})
        elif action == 'verify':
            if not user.is_email_verified:
                from django.utils import timezone
                user.is_email_verified = True
                user.email_verified_at = timezone.now()
                user.save(update_fields=['is_email_verified', 'email_verified_at'])
            _record_action(request, 'user.verify', target_tenant=user.tenant,
                           target_name=user.email)
        elif action == 'reset_password':
            try:
                from users.emails import create_and_send_otp
                create_and_send_otp(user, purpose='password_reset')
            except Exception:
                return Response(
                    {'detail': 'Could not send the reset email. Try again shortly.'},
                    status=status.HTTP_502_BAD_GATEWAY,
                )
            _record_action(request, 'user.reset_password', target_tenant=user.tenant,
                           target_name=user.email)
        else:
            return Response(
                {'detail': 'Unknown action. Use suspend, unsuspend, verify or reset_password.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.refresh_from_db()
        return Response(SuperAdminUserListSerializer(user).data)


# ── Phase 3: support inbox (platform leads) ────────────────────────────────
class LeadListView(APIView):
    """Unified inbox across demo bookings, contact messages & job applications.

    Query params: ``type`` (demo|contact|job), ``status`` (new|contacted|closed),
    ``search`` (name/email). Returns newest-first with a small in-memory merge
    (lead volume is low). ``limit`` caps the result set (default 200).
    """

    permission_classes = [permissions.IsAuthenticated, IsSuperAdmin]

    def get(self, request):
        p = request.query_params
        wanted_type = p.get('type')
        status_filter = p.get('status')
        search = (p.get('search') or '').strip()
        try:
            limit = min(int(p.get('limit', 200)), 500)
        except (TypeError, ValueError):
            limit = 200

        items = []
        counts = {'demo': 0, 'contact': 0, 'job': 0, 'new': 0}
        by_status = {'new': 0, 'contacted': 0, 'closed': 0}
        for key, (model, serializer_cls) in LEAD_REGISTRY.items():
            qs = model.objects.all()
            counts[key] = qs.count()
            counts['new'] += qs.filter(status='new').count()
            for _st in by_status:
                by_status[_st] += qs.filter(status=_st).count()
            if wanted_type and wanted_type != key:
                continue
            if status_filter:
                qs = qs.filter(status=status_filter)
            if search:
                qs = qs.filter(Q(name__icontains=search) | Q(email__icontains=search))
            items.extend(serializer_cls(qs, many=True).data)

        items.sort(key=lambda x: x['created_at'], reverse=True)
        counts['by_status'] = by_status
        return Response({'results': items[:limit], 'total': len(items), 'counts': counts})


class LeadDetailView(APIView):
    """GET / PATCH a single lead identified by its type + id.

    Only ``status`` and ``internal_notes`` are writable.
    """

    permission_classes = [permissions.IsAuthenticated, IsSuperAdmin]

    def _resolve(self, lead_type, pk):
        entry = LEAD_REGISTRY.get(lead_type)
        if not entry:
            return None, None, None
        model, serializer_cls = entry
        try:
            obj = model.objects.get(pk=pk)
        except model.DoesNotExist:
            return model, serializer_cls, None
        return model, serializer_cls, obj

    def get(self, request, lead_type=None, pk=None):
        model, serializer_cls, obj = self._resolve(lead_type, pk)
        if serializer_cls is None:
            return Response({'detail': 'Unknown lead type.'}, status=status.HTTP_404_NOT_FOUND)
        if obj is None:
            return Response({'detail': 'Lead not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(serializer_cls(obj).data)

    def patch(self, request, lead_type=None, pk=None):
        model, serializer_cls, obj = self._resolve(lead_type, pk)
        if serializer_cls is None or obj is None:
            return Response({'detail': 'Lead not found.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = serializer_cls(obj, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer_cls(obj).data)


# ── Phase 3: platform announcements ────────────────────────────────────────
class AnnouncementListCreateView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated, IsSuperAdmin]
    serializer_class = AnnouncementSerializer

    def get_queryset(self):
        qs = PlatformAnnouncement.objects.select_related('target_tenant', 'created_by')
        p = self.request.query_params
        tenant_id = p.get('tenant')
        if tenant_id == 'global':
            qs = qs.filter(target_tenant__isnull=True)
        elif tenant_id:
            qs = qs.filter(target_tenant_id=tenant_id)
        if p.get('active') == 'true':
            qs = qs.filter(is_active=True)
        return qs

    def perform_create(self, serializer):
        announcement = serializer.save(created_by=self.request.user)
        _record_action(
            self.request, 'announcement.create',
            target_tenant=announcement.target_tenant,
            target_name=announcement.title,
        )


class AnnouncementDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [permissions.IsAuthenticated, IsSuperAdmin]
    serializer_class = AnnouncementSerializer
    queryset = PlatformAnnouncement.objects.select_related('target_tenant', 'created_by')
    lookup_field = 'pk'
    http_method_names = ['get', 'patch', 'delete', 'head', 'options']

    def perform_update(self, serializer):
        announcement = serializer.save()
        _record_action(
            self.request, 'announcement.update',
            target_tenant=announcement.target_tenant,
            target_name=announcement.title,
        )

    def perform_destroy(self, instance):
        title = instance.title
        target = instance.target_tenant
        instance.delete()
        _record_action(
            self.request, 'announcement.delete',
            target_tenant=target, target_name=title,
        )
