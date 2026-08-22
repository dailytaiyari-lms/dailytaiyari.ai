"""
Core models - Base classes for all models in the platform.
"""
from django.db import models
from django.utils import timezone
from datetime import timedelta
import uuid


class Tenant(models.Model):
    """
    Model representing a Tenant (e.g. an Institute, Coaching Center, or School).
    All data in the platform will be scopes to a Tenant.
    """

    # Canonical list of toggleable product features. Keys are stable identifiers
    # consumed by the frontend to show/hide navigation and routes; values are the
    # human-readable labels shown in the tenant-admin settings UI. To add a new
    # toggleable feature, add it here — existing tenants default it to enabled.
    FEATURE_CHOICES = {
        'courses': 'Courses',
        'study': 'Study Material',
        'quiz': 'Practice Quiz',
        'mock_tests': 'Mock Tests',
        'pyq': 'Previous Year Papers (PYQ)',
        'community': 'Community',
        'analytics': 'Analytics',
        'leaderboard': 'Leaderboard',
        'ai': 'AI Learning & Doubt Solver',
        'jobs': 'Job Portal',
    }

    # Canonical list of selectable colour themes. Keys are stable identifiers the
    # frontend maps to a full colour palette; values are the human-readable
    # labels shown in the tenant-admin settings UI. Keep in sync with the
    # frontend theme config (src/config/themes.js).
    THEME_CHOICES = {
        'sunrise': 'Sunrise Orange',
        'ocean': 'Ocean Blue',
        'emerald': 'Emerald Green',
        'violet': 'Royal Purple',
        'rose': 'Crimson Rose',
        'indigo': 'Midnight Indigo',
        'slate': 'Graphite Slate',
        'amber': 'Golden Amber',
        'cherry': 'Cherry Red',
        'lime': 'Fresh Lime',
    }
    DEFAULT_THEME = 'sunrise'

    # ── Subscription plans & billing (Phase 2) ─────────────────────────────
    # A tenant's commercial plan. The plan is informational + drives default
    # quota caps (see PLAN_DEFAULTS); the super admin may still override any
    # individual cap per tenant. Keys are stable identifiers.
    PLAN_TRIAL = 'trial'
    PLAN_STARTER = 'starter'
    PLAN_GROWTH = 'growth'
    PLAN_ENTERPRISE = 'enterprise'
    PLAN_CHOICES = {
        PLAN_TRIAL: 'Trial',
        PLAN_STARTER: 'Starter',
        PLAN_GROWTH: 'Growth',
        PLAN_ENTERPRISE: 'Enterprise',
    }

    # Billing lifecycle status. ``trialing`` freezes once ``trial_ends_at``
    # passes; ``past_due`` is a soft grace state (warned, not frozen);
    # ``expired``/``canceled`` freeze immediately; ``active`` is healthy.
    BILLING_TRIALING = 'trialing'
    BILLING_ACTIVE = 'active'
    BILLING_PAST_DUE = 'past_due'
    BILLING_EXPIRED = 'expired'
    BILLING_CANCELED = 'canceled'
    BILLING_STATUS_CHOICES = {
        BILLING_TRIALING: 'Trialing',
        BILLING_ACTIVE: 'Active',
        BILLING_PAST_DUE: 'Past Due',
        BILLING_EXPIRED: 'Expired',
        BILLING_CANCELED: 'Canceled',
    }

    # Default per-resource caps applied when a plan is assigned. ``None`` means
    # unlimited. The super admin may override any cap independently afterwards.
    PLAN_DEFAULTS = {
        PLAN_TRIAL:      {'max_students': 50,   'max_courses': 3,   'max_admins': 2},
        PLAN_STARTER:    {'max_students': 300,  'max_courses': 15,  'max_admins': 5},
        PLAN_GROWTH:     {'max_students': 2000, 'max_courses': 100, 'max_admins': 15},
        PLAN_ENTERPRISE: {'max_students': None, 'max_courses': None, 'max_admins': None},
    }

    # Quota-guarded resources. Each maps to a usage counter + a max_* field.
    QUOTA_RESOURCES = ('students', 'courses', 'admins')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    tagline = models.CharField(max_length=255, blank=True, default='')
    subdomain = models.CharField(max_length=100, unique=True, null=True, blank=True)
    logo = models.ImageField(upload_to='tenant_logos/', null=True, blank=True)
    favicon = models.ImageField(upload_to='tenant_favicons/', null=True, blank=True)
    theme = models.CharField(
        max_length=32,
        choices=[(k, v) for k, v in THEME_CHOICES.items()],
        default=DEFAULT_THEME,
    )
    # When False, the frontend hides the text name and shows the logo alone
    # (full-width) — useful when the logo already contains the institution name.
    show_name = models.BooleanField(default=True)

    # Editable content for the branding panel on the login/register screens
    # (the left-hand marketing column of the auth pages). Shape:
    #   {heading, heading_highlight, subtitle, stats: [{value, label}, ...]}
    # An empty dict means "use the platform's generic defaults" — the frontend
    # merges any provided keys over those defaults, so tenants only override
    # what they care about.
    auth_panel = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)

    # Per-tenant feature toggles: {feature_key: bool}. Missing keys default to
    # enabled so newly introduced features are on until an admin turns them off.
    features = models.JSONField(default=dict, blank=True)

    # Super-admin feature locks: {feature_key: bool}. A key present here is
    # *locked* — the tenant admin cannot change it and the value given here is
    # forced (True = force-enabled, False = force-disabled), overriding whatever
    # sits in ``features``. Only the platform super admin edits this map; the
    # tenant-admin UI shows locked features as read-only with a "contact the
    # DailyTaiyari team" note. Missing keys are tenant-controlled as usual.
    feature_locks = models.JSONField(default=dict, blank=True)

    # Per-tenant display-name overrides for features: {feature_key: label}.
    # Feature *keys* stay canonical everywhere (toggles, routes, permissions);
    # only the words shown to students/admins change. A missing or blank entry
    # falls back to the platform default in ``FEATURE_CHOICES``.
    feature_labels = models.JSONField(default=dict, blank=True)

    # ── Suspension (super-admin freeze) ────────────────────────────────────
    # A suspended tenant stays ``is_active`` (so its public config, and thus the
    # suspension notice, still loads) but every authenticated API call and login
    # is blocked with ``suspension_message``. Use it for billing/compliance
    # holds; use ``is_active=False`` to quietly retire a tenant instead.
    is_suspended = models.BooleanField(default=False)
    suspension_message = models.TextField(blank=True, default='')

    # ── Subscription plan & quota caps (Phase 2) ───────────────────────────
    # The commercial plan and its billing lifecycle. ``max_*`` are the effective
    # per-tenant caps (None = unlimited); they seed from PLAN_DEFAULTS when a
    # plan is applied but can be overridden individually by the super admin.
    plan = models.CharField(
        max_length=32,
        choices=[(k, v) for k, v in PLAN_CHOICES.items()],
        default=PLAN_TRIAL,
    )
    billing_status = models.CharField(
        max_length=32,
        choices=[(k, v) for k, v in BILLING_STATUS_CHOICES.items()],
        default=BILLING_TRIALING,
    )
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    max_students = models.PositiveIntegerField(null=True, blank=True)
    max_courses = models.PositiveIntegerField(null=True, blank=True)
    max_admins = models.PositiveIntegerField(null=True, blank=True)

    # ── Enrollment mode flags ──────────────────────────────────────────────
    # These decide how a student joins a course:
    #   * request_enrollment_* = True  → student sends a request, admin approves
    #     (the current, gateway-independent behaviour).
    #   * request_enrollment_free = False → free courses allow instant self-enrol.
    #   * request_enrollment_paid = False → paid courses enrol only after online
    #     payment, so this may only be turned off when an active payment gateway
    #     is configured (enforced in the admin serializer). Defaults keep every
    #     existing tenant on the request/approve flow.
    request_enrollment_free = models.BooleanField(default=True)
    request_enrollment_paid = models.BooleanField(default=True)

    # ── Notification recipient address(es) ─────────────────────────────────
    # Where admin-facing notification emails (e.g. new enrollment requests) are
    # delivered. Accepts one or more comma-separated addresses. When blank, the
    # system falls back to the email addresses of the tenant's admin accounts.
    notification_email = models.CharField(max_length=500, blank=True, default='')

    # ── Allowed frontend origins (self-serve CORS, Phase 3) ────────────────
    # Exact browser origins (scheme + host [+ port]) that this tenant's own
    # frontend is served from and which may call the public platform API
    # cross-origin. Managed by the super admin from the dashboard so onboarding
    # a new tenant frontend no longer needs a settings.py code deploy. Honoured
    # dynamically by a corsheaders ``check_request_enabled`` signal handler.
    allowed_origins = models.JSONField(default=list, blank=True)

    # ── AI platform-key allowance (super-admin controlled) ─────────────────
    # Tenants normally bring their own LLM key (see chatbot.AIProviderConfig).
    # When a tenant has no working key of its own, the AI assistant is simply
    # unavailable — *unless* the super admin grants an allowance here, in which
    # case the platform's own key answers up to this many tokens per calendar
    # month. 0 (the default) means "no platform spend for this tenant", which
    # keeps the platform's LLM bill at zero unless it is deliberately gifted.
    ai_platform_monthly_tokens = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Tenant'
        verbose_name_plural = 'Tenants'
        ordering = ['name']

    def __str__(self):
        return self.name

    def notification_recipient_emails(self):
        """Parsed list of admin notification recipient addresses.

        Reads the comma/newline-separated ``notification_email`` field and
        returns a de-duplicated list of trimmed addresses. Empty when unset,
        signalling callers to fall back to the tenant admins' own emails.
        """
        raw = (self.notification_email or '').replace('\n', ',').replace(';', ',')
        seen = []
        for part in raw.split(','):
            addr = part.strip()
            if addr and addr.lower() not in [s.lower() for s in seen]:
                seen.append(addr)
        return seen

    def get_features(self):
        """Return the full *effective* feature map.

        Resolution per feature key: a super-admin lock (``feature_locks``) wins
        and forces its value; otherwise the tenant's own ``features`` value is
        used, defaulting any missing key to enabled.
        """
        stored = self.features or {}
        locks = self.feature_locks or {}
        result = {}
        for key in self.FEATURE_CHOICES:
            if key in locks:
                result[key] = bool(locks[key])
            else:
                result[key] = bool(stored.get(key, True))
        return result

    def get_feature_locks(self):
        """Return the sanitized lock map: only known keys, coerced to bool."""
        locks = self.feature_locks or {}
        return {k: bool(v) for k, v in locks.items() if k in self.FEATURE_CHOICES}

    def locked_feature_keys(self):
        """List of feature keys currently locked by the super admin."""
        return list(self.get_feature_locks().keys())

    # ── Feature naming ─────────────────────────────────────────────────────
    #: Max length of a tenant's custom feature label (fits navigation UI).
    FEATURE_LABEL_MAX_LENGTH = 40

    def get_feature_label_overrides(self):
        """Sanitized override map: only known keys with a non-empty label."""
        overrides = self.feature_labels or {}
        cleaned = {}
        for key, label in overrides.items():
            if key not in self.FEATURE_CHOICES:
                continue
            text = str(label or '').strip()[: self.FEATURE_LABEL_MAX_LENGTH]
            if text and text != self.FEATURE_CHOICES[key]:
                cleaned[key] = text
        return cleaned

    def get_feature_labels(self):
        """Full effective label map: tenant override, else platform default."""
        overrides = self.get_feature_label_overrides()
        return {
            key: overrides.get(key, default)
            for key, default in self.FEATURE_CHOICES.items()
        }

    def feature_label(self, key):
        """Effective label for a single feature key."""
        return self.get_feature_labels().get(key, key)

    # ── Quotas & billing helpers (Phase 2) ─────────────────────────────────
    def usage_counts(self):
        """Live usage for each quota-guarded resource."""
        return {
            'students': self.users.filter(role='student').count(),
            'courses': self.courses.count(),
            'admins': self.users.filter(role='admin').count(),
        }

    def quota_limits(self):
        """Effective caps per resource. ``None`` means unlimited."""
        return {
            'students': self.max_students,
            'courses': self.max_courses,
            'admins': self.max_admins,
        }

    def quota_status(self):
        """Per-resource {used, limit, remaining, over} for dashboards/enforcement."""
        used = self.usage_counts()
        limits = self.quota_limits()
        status = {}
        for resource in self.QUOTA_RESOURCES:
            limit = limits[resource]
            count = used[resource]
            status[resource] = {
                'used': count,
                'limit': limit,
                'remaining': None if limit is None else max(limit - count, 0),
                'over': limit is not None and count >= limit,
            }
        return status

    def can_add(self, resource, count=1):
        """True when ``count`` more of ``resource`` fits under the cap."""
        limit = self.quota_limits().get(resource)
        if limit is None:
            return True
        return self.usage_counts().get(resource, 0) + count <= limit

    def apply_plan_defaults(self):
        """Seed the ``max_*`` caps from the current plan's defaults."""
        defaults = self.PLAN_DEFAULTS.get(self.plan)
        if defaults:
            self.max_students = defaults['max_students']
            self.max_courses = defaults['max_courses']
            self.max_admins = defaults['max_admins']

    @property
    def is_billing_frozen(self):
        """True when the subscription lifecycle should freeze the tenant.

        ``expired``/``canceled`` freeze immediately; a ``trialing`` tenant
        freezes once its trial has lapsed. ``past_due`` is a soft grace state
        (surfaced as a warning) and ``active`` is healthy.
        """
        now = timezone.now()
        if self.billing_status in (self.BILLING_EXPIRED, self.BILLING_CANCELED):
            return True
        if (self.billing_status == self.BILLING_TRIALING
                and self.trial_ends_at is not None and self.trial_ends_at < now):
            return True
        return False

    @property
    def billing_freeze_message(self):
        return (
            'Your DailyTaiyari subscription is inactive. '
            'Please contact the DailyTaiyari team to restore access.'
        )

    def access_block(self):
        """Consolidated freeze check used by login + middleware.

        Returns ``(blocked, message, code)``. Suspension takes precedence over a
        billing freeze so an explicit hold keeps its custom message.
        """
        if self.is_suspended:
            return (
                True,
                self.suspension_message
                or 'This academy is temporarily suspended. Please contact the DailyTaiyari team.',
                'tenant_suspended',
            )
        if self.is_billing_frozen:
            return True, self.billing_freeze_message, 'subscription_inactive'
        return False, '', ''

    @property
    def active_payment_gateway(self):
        """The single gateway currently used for checkout, if any.

        A tenant may store several providers' credentials but only one is
        marked ``is_active`` at a time (enforced when saving from the admin).
        """
        return self.payment_gateways.filter(is_active=True).first()

    @property
    def has_active_payment_gateway(self):
        """True when this tenant has a fully-configured, active payment gateway."""
        gateway = self.active_payment_gateway
        return bool(gateway and gateway.is_configured)

    @property
    def zoom_integration(self):
        """This tenant's Zoom connection, if one has been saved."""
        return getattr(self, 'zoom', None)

    @property
    def has_zoom(self):
        """True when this tenant has an active, fully-credentialed Zoom connection."""
        zoom = self.zoom_integration
        return bool(zoom and zoom.is_active and zoom.is_configured)

    def enroll_mode_for(self, course):
        """Resolve how a student joins ``course`` given this tenant's flags.

        Returns one of:
          * ``'request'`` — student requests, an admin approves (default).
          * ``'self'``    — instant self-enrolment (free course, flag off).
          * ``'payment'`` — enrol after online payment (paid course, flag off
            and an active gateway is configured).
        """
        is_free = getattr(course, 'is_free', False)
        if is_free:
            return 'request' if self.request_enrollment_free else 'self'
        # Paid course.
        if not self.request_enrollment_paid and self.has_active_payment_gateway:
            return 'payment'
        return 'request'


class PaymentGateway(models.Model):
    """A tenant's online payment gateway credentials (Razorpay / Cashfree / PayU).

    Secrets are encrypted at rest via :mod:`core.encryption`; the plaintext
    secret is only ever exposed through the :pyattr:`key_secret` property and is
    never serialized back to API clients. Each tenant has at most one gateway.
    """

    PROVIDER_RAZORPAY = 'razorpay'
    PROVIDER_CASHFREE = 'cashfree'
    PROVIDER_PAYU = 'payu'
    PROVIDER_CHOICES = [
        (PROVIDER_RAZORPAY, 'Razorpay'),
        (PROVIDER_CASHFREE, 'Cashfree'),
        (PROVIDER_PAYU, 'PayU'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name='payment_gateways'
    )
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES)

    # Public-ish identifier: Razorpay ``key_id`` / Cashfree ``app_id`` / PayU merchant key.
    key_id = models.CharField(max_length=255, blank=True, default='')
    # Encrypted secret: Razorpay ``key_secret`` / Cashfree ``secret_key`` / PayU salt.
    key_secret_encrypted = models.TextField(blank=True, default='')
    # Encrypted webhook signing secret. Razorpay uses a dedicated webhook secret
    # (set in its dashboard); Cashfree signs webhooks with the account secret and
    # PayU signs with its salt, so this is optional for them and falls back to
    # ``key_secret``.
    webhook_secret_encrypted = models.TextField(blank=True, default='')

    # When False the gateway is stored but not used for checkout yet.
    is_active = models.BooleanField(default=False)
    # Test/sandbox vs. live credentials.
    is_test_mode = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Payment Gateway'
        verbose_name_plural = 'Payment Gateways'
        constraints = [
            # A tenant configures each provider at most once.
            models.UniqueConstraint(
                fields=['tenant', 'provider'], name='uniq_tenant_provider_gateway'
            ),
        ]

    def __str__(self):
        return f'{self.tenant.name} — {self.get_provider_display()}'

    @property
    def key_secret(self):
        """Decrypted secret (empty string when not set)."""
        from .encryption import decrypt
        return decrypt(self.key_secret_encrypted)

    @key_secret.setter
    def key_secret(self, raw):
        from .encryption import encrypt
        self.key_secret_encrypted = encrypt(raw or '')

    @property
    def webhook_secret(self):
        """Decrypted webhook secret; falls back to the account secret when unset."""
        from .encryption import decrypt
        if self.webhook_secret_encrypted:
            return decrypt(self.webhook_secret_encrypted)
        return decrypt(self.key_secret_encrypted)

    @webhook_secret.setter
    def webhook_secret(self, raw):
        from .encryption import encrypt
        self.webhook_secret_encrypted = encrypt(raw or '')

    @property
    def is_configured(self):
        """True once both the id and secret are present."""
        return bool(self.key_id and self.key_secret_encrypted)


class ZoomIntegration(models.Model):
    """A tenant's Zoom connection (Server-to-Server OAuth credentials).

    Each academy connects its *own* Zoom account so meetings are created under
    their host, recordings stay in their cloud, and attendance reports come from
    their plan. Credentials come from a Zoom Marketplace "Server-to-Server OAuth"
    app: ``account_id`` + ``client_id`` + ``client_secret``.

    Secrets are encrypted at rest via :mod:`core.encryption` and are never
    serialized back to API clients — the API only exposes ``has_*`` booleans.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.OneToOneField(
        Tenant, on_delete=models.CASCADE, related_name='zoom'
    )

    # Server-to-Server OAuth app credentials.
    account_id = models.CharField(max_length=255, blank=True, default='')
    client_id = models.CharField(max_length=255, blank=True, default='')
    client_secret_encrypted = models.TextField(blank=True, default='')

    # Zoom event-subscription "Secret Token", used to verify webhook signatures
    # and to answer Zoom's endpoint URL validation challenge.
    webhook_secret_token_encrypted = models.TextField(blank=True, default='')

    # The Zoom user (email or userId) meetings are created under. Blank means
    # ``me`` — the account owner tied to the S2S app.
    host_email = models.CharField(max_length=255, blank=True, default='')

    # Registration gives each student a unique join URL, which makes attendance
    # matching exact. It requires a paid Zoom plan, so it stays togglable.
    use_registration = models.BooleanField(
        default=True,
        help_text='Register each enrolled student so they get a personal join '
                  'link and attendance maps exactly to a student.',
    )
    # Pull the authoritative participant report after a class ends. Needs a
    # Pro (or higher) Zoom plan; free accounts have no /report API access.
    pull_reports = models.BooleanField(default=True)

    # Minimum share of the class a student must be present for to count as
    # "present" rather than "partial".
    attendance_threshold_percent = models.PositiveIntegerField(default=60)

    is_active = models.BooleanField(default=False)

    # Result of the last "Test connection" / token fetch, for admin feedback.
    last_verified_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default='')

    # Answering Zoom's endpoint.url_validation challenge means HMAC-ing an
    # attacker-supplied value with the same Secret Token that signs real events,
    # so the unscoped webhook URL only answers it while an admin has explicitly
    # opened a short verification window from the settings screen.
    webhook_validation_until = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Zoom Integration'
        verbose_name_plural = 'Zoom Integrations'

    def __str__(self):
        return f'{self.tenant.name} — Zoom'

    @property
    def client_secret(self):
        from .encryption import decrypt
        return decrypt(self.client_secret_encrypted)

    @client_secret.setter
    def client_secret(self, raw):
        from .encryption import encrypt
        self.client_secret_encrypted = encrypt(raw or '')

    @property
    def webhook_secret_token(self):
        from .encryption import decrypt
        return decrypt(self.webhook_secret_token_encrypted)

    @webhook_secret_token.setter
    def webhook_secret_token(self, raw):
        from .encryption import encrypt
        self.webhook_secret_token_encrypted = encrypt(raw or '')

    @property
    def is_configured(self):
        """True once all three S2S OAuth credentials are present."""
        return bool(self.account_id and self.client_id and self.client_secret_encrypted)

    # How long a verification window stays open after an admin asks for one.
    WEBHOOK_VALIDATION_WINDOW = timedelta(minutes=30)

    @property
    def webhook_validation_open(self):
        """True while this integration may answer Zoom's URL-validation challenge."""
        from django.utils import timezone as _tz
        return bool(
            self.webhook_validation_until and self.webhook_validation_until > _tz.now()
        )

    def open_webhook_validation(self, save=True):
        """Allow the unscoped webhook URL to answer Zoom's challenge for a while."""
        from django.utils import timezone as _tz
        self.webhook_validation_until = _tz.now() + self.WEBHOOK_VALIDATION_WINDOW
        if save:
            self.save(update_fields=['webhook_validation_until', 'updated_at'])
        return self.webhook_validation_until


class LandingPage(models.Model):
    """Per-tenant public landing page configuration.

    One record per tenant. The page is section-based: ``sections`` is an ordered
    list of ``{id, type, enabled, data}`` dicts the frontend renders through a
    section registry. A tenant admin edits everything from the Home Page Builder.

    A brand-new tenant has no record; the API serves platform defaults (see
    :mod:`core.landing_defaults`) so the page is never empty, and the first save
    from the admin persists a real record.
    """

    from .landing_defaults import TEMPLATE_CHOICES, DEFAULT_TEMPLATE

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.OneToOneField(
        Tenant, on_delete=models.CASCADE, related_name='landing_page'
    )

    # Visual design/skin applied to the whole page.
    template = models.CharField(
        max_length=32,
        choices=[(k, v) for k, v in TEMPLATE_CHOICES.items()],
        default=DEFAULT_TEMPLATE,
    )
    # When False the public page falls back to the generic default layout so an
    # unfinished draft is never exposed. Admin can preview regardless.
    is_published = models.BooleanField(default=True)

    # Ordered list of section dicts: {id, type, enabled, data}.
    sections = models.JSONField(default=list, blank=True)
    # Footer configuration dict (about, contacts, socials, columns, copyright).
    footer = models.JSONField(default=dict, blank=True)

    # Optional hero background / SEO extras kept simple for now.
    meta = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Landing Page'
        verbose_name_plural = 'Landing Pages'

    def __str__(self):
        return f'Landing page — {self.tenant.name}'


class LegalDocument(models.Model):
    """Per-tenant legal page (refund / privacy / terms).

    The platform ships generic defaults (see :mod:`core.landing_defaults`) so
    these pages are never empty; a tenant admin can override the title and rich
    HTML content. Unique per (tenant, doc_type).
    """

    from .landing_defaults import LEGAL_DOC_TYPES

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name='legal_documents'
    )
    doc_type = models.CharField(
        max_length=20,
        choices=[(k, v) for k, v in LEGAL_DOC_TYPES.items()],
    )
    title = models.CharField(max_length=255, blank=True, default='')
    content = models.TextField(blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Legal Document'
        verbose_name_plural = 'Legal Documents'
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'doc_type'], name='uniq_tenant_legal_doc'
            ),
        ]

    def __str__(self):
        return f'{self.tenant.name} — {self.get_doc_type_display()}'


class TimeStampedModel(models.Model):
    """
    Abstract base model with created and modified timestamps.
    All models should inherit from this.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ['-created_at']


class SoftDeleteModel(TimeStampedModel):
    """
    Abstract model with soft delete functionality.
    Records are marked as deleted instead of being removed.
    """
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True

    def soft_delete(self):
        from django.utils import timezone
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save()


class OrderedModel(TimeStampedModel):
    """
    Abstract model with ordering capability.
    """
    order = models.PositiveIntegerField(default=0, db_index=True)

    class Meta:
        abstract = True
        ordering = ['order', '-created_at']



class PlatformLead(models.Model):
    """Abstract base for platform-owned (non-tenant) inbound records.

    These belong to the DailyTaiyari platform team — NOT to any tenant — and
    will be managed later from a super-admin dashboard.
    """
    STATUS_CHOICES = [
        ('new', 'New'),
        ('contacted', 'Contacted'),
        ('closed', 'Closed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    email = models.EmailField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new', db_index=True)
    source = models.CharField(max_length=100, default='landing', blank=True)
    internal_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ['-created_at']


class DemoBooking(PlatformLead):
    """A 'Book a Demo' request submitted from the marketing site."""
    ORG_TYPE_CHOICES = [
        ('creator', 'Independent Creator'),
        ('coaching', 'Coaching Institute'),
        ('school', 'School'),
        ('college', 'College'),
        ('edtech', 'EdTech / Online Academy'),
        ('other', 'Other'),
    ]

    phone = models.CharField(max_length=30, blank=True)
    organization = models.CharField(max_length=255, blank=True)
    organization_type = models.CharField(max_length=20, choices=ORG_TYPE_CHOICES, blank=True)
    message = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Demo Booking'
        verbose_name_plural = 'Demo Bookings'

    def __str__(self):
        return f'{self.name} <{self.email}> ({self.organization or "—"})'


class ContactMessage(PlatformLead):
    """A 'Talk to us' message submitted from the marketing site."""
    subject = models.CharField(max_length=255, blank=True)
    message = models.TextField()

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Contact Message'
        verbose_name_plural = 'Contact Messages'

    def __str__(self):
        return f'{self.name} <{self.email}>'


class JobApplication(PlatformLead):
    """A careers-page job application submitted from the marketing site."""

    phone = models.CharField(max_length=30, blank=True)
    position = models.CharField(max_length=255)
    experience = models.CharField(max_length=100, blank=True)
    portfolio_url = models.URLField(max_length=500, blank=True)
    cover_letter = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Job Application'
        verbose_name_plural = 'Job Applications'

    def __str__(self):
        return f'{self.name} <{self.email}> — {self.position}'


class SuperAdminAuditLog(models.Model):
    """An immutable record of a super-admin action on the platform.

    Written whenever a super admin creates or changes a tenant (including
    feature locks and suspension) so there is an accountable who/what/when
    trail. ``changes`` holds a ``{field: [old, new]}`` diff for updates.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='superadmin_audit_logs',
    )
    actor_email = models.EmailField(blank=True, default='')
    action = models.CharField(max_length=64)
    target_tenant = models.ForeignKey(
        Tenant, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='audit_logs',
    )
    target_name = models.CharField(max_length=255, blank=True, default='')
    changes = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Super Admin Audit Log'
        verbose_name_plural = 'Super Admin Audit Logs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['target_tenant', '-created_at']),
            models.Index(fields=['-created_at']),
        ]

    def __str__(self):
        return f'{self.actor_email or "system"} {self.action} {self.target_name}'.strip()


class PlatformAnnouncement(models.Model):
    """A super-admin authored notice shown to tenant apps as a banner.

    An announcement is either **global** (``target_tenant`` is null → shown to
    every tenant) or scoped to a single tenant. It surfaces through the public
    tenant-config endpoint so the tenant app / admin can render a banner. The
    optional ``starts_at`` / ``ends_at`` window and ``is_active`` flag decide
    whether it is currently live (see :meth:`is_live`).
    """
    LEVEL_INFO = 'info'
    LEVEL_WARNING = 'warning'
    LEVEL_CRITICAL = 'critical'
    LEVEL_CHOICES = {
        LEVEL_INFO: 'Info',
        LEVEL_WARNING: 'Warning',
        LEVEL_CRITICAL: 'Critical',
    }

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    body = models.TextField(blank=True, default='')
    level = models.CharField(
        max_length=20,
        choices=[(k, v) for k, v in LEVEL_CHOICES.items()],
        default=LEVEL_INFO,
    )
    # Null target = a platform-wide announcement shown to every tenant.
    target_tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, null=True, blank=True,
        related_name='announcements',
    )
    is_active = models.BooleanField(default=True)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='created_announcements',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Platform Announcement'
        verbose_name_plural = 'Platform Announcements'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['is_active', '-created_at']),
            models.Index(fields=['target_tenant', 'is_active']),
        ]

    def __str__(self):
        scope = self.target_tenant.name if self.target_tenant else 'ALL'
        return f'[{scope}] {self.title}'

    def is_live(self, now=None):
        """True when the announcement is active and within its time window."""
        if not self.is_active:
            return False
        now = now or timezone.now()
        if self.starts_at and now < self.starts_at:
            return False
        if self.ends_at and now > self.ends_at:
            return False
        return True

    @classmethod
    def live_for_tenant(cls, tenant, now=None):
        """Active, in-window announcements for a tenant (global + tenant-scoped)."""
        from django.db.models import Q
        now = now or timezone.now()
        qs = cls.objects.filter(is_active=True).filter(
            Q(target_tenant__isnull=True) | Q(target_tenant=tenant)
        )
        return [a for a in qs if a.is_live(now)]
