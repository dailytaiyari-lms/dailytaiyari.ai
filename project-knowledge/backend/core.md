# core

(Tenant model, middleware, base classes, roles, auth overview are in `_foundation.md`; this file is the app-level reference.)

- **Purpose**: platform foundation. Owns `Tenant` (multi-tenancy, branding, feature flags, plans/quotas, suspension), per-tenant integrations (payment gateway, Zoom, Azure sender domain), tenant landing pages + legal docs, platform-owned marketing leads, the super-admin dashboard API, tenant-admin settings API, the Tenant/Suspension middleware, base abstract models/viewsets/permissions, and Fernet field encryption.

## Key models (backend/core/models.py)
- `Tenant`: see `_foundation.md` section 2 for every field. Methods: `get_features/get_feature_locks/locked_feature_keys/get_feature_labels/feature_label`, `get_advanced_settings/advanced_setting`, `get_registration_settings/public_registration_schema`, `usage_counts/quota_limits/quota_status/can_add/apply_plan_defaults`, `is_billing_frozen`, `access_block()`, `active_payment_gateway/has_active_payment_gateway`, `zoom_integration/has_zoom`, `enroll_mode_for(course)`, `notification_recipient_emails()`.
- `PaymentGateway`: FK tenant; provider razorpay|cashfree|payu; `key_id`, encrypted `key_secret_encrypted`, `webhook_secret_encrypted`; `is_active` (one active per tenant, enforced in view), `is_test_mode`. Unique `uniq_tenant_provider_gateway(tenant, provider)`.
- `TenantEmailDomain`: OneToOne tenant; unique `domain`; sender_username (default `notifications`), `sender_name`, `is_active`, `azure_resource_id`, `provisioning_state`, `verification_records/states` JSON, `sender_provisioned`, `is_linked`, `last_synced_at`, `last_error`. Props `from_email`, `is_verified` (Domain+SPF+DKIM+DKIM2 == Verified), `is_ready`.
- `ZoomIntegration`: OneToOne tenant; `account_id, client_id`, encrypted `client_secret_encrypted`, `webhook_secret_token_encrypted`, `host_email`, `use_registration`, `pull_reports`, `attendance_threshold_percent` (default 60, API validates 1-100), `is_active`, `last_verified_at`, `last_error`, `webhook_validation_until` (30 min window via `open_webhook_validation()`).
- `LandingPage`: OneToOne tenant; `template` (default `aurora`; choices in `landing_defaults.TEMPLATE_CHOICES`), `is_published` (default True), `sections` JSON list, `footer` JSON, `meta` JSON. No row => platform defaults served.
- `LegalDocument`: FK tenant; `doc_type` in `landing_defaults.LEGAL_DOC_TYPES` (refund/privacy/terms); `title`, `content` (HTML). Unique `uniq_tenant_legal_doc(tenant, doc_type)`.
- Abstract bases: `TimeStampedModel` (nullable tenant FK, related_name '+'), `SoftDeleteModel`, `OrderedModel`, `PlatformLead`.
- `DemoBooking` (phone, organization, organization_type creator|coaching|school|college|edtech|other, message), `ContactMessage` (subject, message), `JobApplication` (phone, position, experience, portfolio_url, cover_letter). Status enum new|contacted|closed; `source` default `landing`.
- `SuperAdminAuditLog`: actor (FK users.User SET_NULL), actor_email, action, target_tenant (SET_NULL), target_name, `changes` JSON `{field: [old, new]}`.
- `PlatformAnnouncement`: title, body, level info|warning|critical, `target_tenant` (null = global, CASCADE), is_active, starts_at, ends_at, created_by. `is_live()`, `live_for_tenant()`.

## API
Mounted in `dailytaiyari/urls.py`.

| Prefix | Views (file) | Permission |
|---|---|---|
| `/api/v1/tenant/<uuid:pk>/` | `TenantDetailView` (core/views.py) | AllowAny; returns branding, `features` (effective), `feature_labels`, `registration_schema`, suspension + freeze (`is_frozen, freeze_message, freeze_code`), enrolment flags, safe gateway summary `{provider,is_test_mode}`, live promo banner (from `marketing`), `announcements` |
| `/api/v1/platform/` | `DemoBookingCreateView`, `ContactMessageCreateView`, `JobApplicationCreateView` | AllowAny, no auth, throttle scope `platform_lead` (20/h); each emails the platform team (failure swallowed) |
| `/api/v1/superadmin/` | `core/superadmin_views.py` | `IsAuthenticated + IsSuperAdmin` (login view AllowAny) |
| `/api/v1/landing/` | `PublicLandingView`, `PublicLegalView` (core/landing_views.py) | AllowAny, `authentication_classes=[]`, tenant header required |
| `/api/v1/tenant-admin/` | `core/admin_views.py`, `landing_views.py` | `IsAuthenticated + IsTenantAdmin` |

Super-admin routes (`core/superadmin_urls.py`): `auth/login/` (email+password, superusers only; returns access/refresh/user), `auth/me/`, `stats/` (tenant/user/course counts, plan distribution, billing-frozen/near-quota/over-quota counts, new leads, active announcements), `tenants/` (list w/ counts + `?search&is_active`, create with `TenantCreateSerializer` fields id,name,tagline,subdomain,theme,is_active), `tenants/<uuid>/` (GET/PATCH only; `TenantDetailSerializer` writes name, tagline, subdomain, theme, show_name, is_active, is_suspended, suspension_message, custom_email_domains_enabled, features (merged), feature_locks (replaced), request_enrollment_*, plan, billing_status, trial_ends_at, current_period_end, max_*, ai_platform_monthly_tokens, allowed_origins), `audit-logs/` (`?tenant=`), `users/` (all tenant users; `?search,tenant,role,status=active|suspended|unverified`), `users/<uuid>/action/` (`suspend|unsuspend|verify|reset_password` - reset sends an OTP email), `leads/` (`?type=demo|contact|job&status&search&limit`), `leads/<type>/<uuid>/` (GET/PATCH only `status`, `internal_notes`), `announcements/` + detail (CRUD; delete allowed), and chatbot platform-LLM routes (`ai/providers/`, `ai/providers/<id>/test|models/`, `ai/models/<id>/`, `ai/usage/`, `tenants/<id>/ai-allocation/`) imported from `chatbot.platform_views`.

Tenant-admin routes (`core/admin_urls.py`): `settings/` (GET/PATCH `TenantSettingsView`; multipart or JSON; read-only: id, subdomain, custom_email_domains_enabled; response adds `locked_features, available_features, available_themes, available_advanced_settings, available_registration_fields, plan/billing/quota_status, is_billing_frozen, has_active_payment_gateway`), `payment-gateway/` (GET list, PUT upsert by `provider` in body, DELETE `?provider=`), `email-domain/` (GET/PUT/POST actions `verify|refresh|test`/DELETE; needs `custom_email_domains_enabled`), `zoom/` (GET/PUT/POST test connection or `action=start_verification`/DELETE), `landing/` (GET/PUT), `landing/upload-image/` (POST, 5 MB cap), `landing/legal/<doc_type>/` (GET/PUT).

## Business logic
- `core/middleware.py`: `TenantMiddleware`, `BlockSuspendedUsersMiddleware`, `resolve_request_user` (details in `_foundation.md`).
- `core/signals.py`: dynamic CORS allow-list from `Tenant.allowed_origins` (cache key `tenant_allowed_origins`, 300 s, invalidated on Tenant save/delete). Registered in `CoreConfig.ready()`.
- `core/azure_email_domains.py`: `AzureEmailDomainClient` - ARM REST client (client-credentials token against login.microsoftonline.com; scope management.azure.com). Methods: `ensure_domain/create_domain/get_domain/get_domain_if_exists/initiate_verification/create_sender/link_domain/unlink_domain/delete_domain`; linking uses ETag read-modify-write on the CommunicationService with 3 retries. Domain ownership guard: Azure resources carry tags `dailytaiyari-managed` and `dailytaiyari-tenant-id`; an existing domain is only attachable by the tenant whose id is in the tag (tests cover this). Raises `AzureEmailDomainError` when any required Azure setting is missing.
- `core/encryption.py`: Fernet helpers `encrypt/decrypt` (see `_foundation.md`).
- `core/landing_defaults.py`: default section list (`default_sections(name)`), footer, templates, and generic legal text (`default_legal`). `landing_serializers.LandingSectionField` validates `[{id,type,enabled,data}]` and fills missing ids.
- `core/emails.py`: platform-team notifications (`send_demo_booking_notification` etc.) via `send_mail` to `PLATFORM_NOTIFICATION_EMAIL`.
- `core/utils.py`: scoring/XP helper functions used by quiz/gamification (see `_foundation.md`).
- Management command `seed_data` (core/management/commands/seed_data.py): dev-only bulk seeder - creates courses (NEET, JEE...), subjects, topics, badges, questions, content, quizzes, mocks, 10 sample student users (all with the same weak password), challenges, progress. It does NOT create or pass a tenant (models need tenant now) - likely stale/broken on current schema; unverified whether it still runs. References a hardcoded personal email for a "main user".
- Audit helper functions in `superadmin_views.py`: `_snapshot/_diff/_record_audit/_record_action`; `TenantDetailView.update` derives the action name (suspend/unsuspend/feature_locks/plan/origins/email_domains/update).

## Integrations / settings / env vars / feature flags
- Settings: `SECRET_KEY`, `FIELD_ENCRYPTION_KEY`, `PLATFORM_NOTIFICATION_EMAIL`, `DEFAULT_FROM_EMAIL`, `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_SUBSCRIPTION_ID`, `AZURE_EMAIL_RESOURCE_GROUP`, `AZURE_EMAIL_SERVICE_NAME`, `AZURE_COMMUNICATION_RESOURCE_GROUP`, `AZURE_COMMUNICATION_SERVICE_NAME`, `AZURE_COMMUNICATION_API_VERSION` (these Azure ARM vars are only defined when `EMAIL_PROVIDER == 'azure'`), `CORS_ALLOWED_ORIGINS`, `REDIS_URL` (shared cache for CORS invalidation).
- Feature flags: `Tenant.FEATURE_CHOICES` (11 keys) + `feature_locks`; `ADVANCED_SETTING_CHOICES`; `custom_email_domains_enabled` capability; `request_enrollment_free/paid`. See `_foundation.md`.
- Zoom: `liveclass.zoom.ZoomClient` (outside core) consumes `ZoomIntegration`.

## Cross-app dependencies
- Imports: `chatbot.platform_views` (urls), `chatbot.models/resolver` (superadmin tenant `ai_usage`), `marketing.models/serializers` (promo banner in public config), `exams.models.Course` (stats), `users` (User for audit/stats/actions; `users.emails.create_and_send_otp`), `notifications.emails.send_branded_email` (domain test mail), `liveclass.zoom.ZoomClient`.
- Imported by: every app (`TimeStampedModel`, `OrderedModel`, `Tenant`, `TenantAwareViewSet`, `IsTenantAdmin`, `IsCourseEditor`, `utils`), `notifications` (sender domain, `allowed_origins`, `advanced_setting`), `payments` (PaymentGateway), `liveclass` (ZoomIntegration), `coursegen` (quota).

## Tests
- `core/tests.py` - `TenantIsolationTests`: header required/malformed/unknown/inactive, cross-tenant user rejected (mutual), superuser exempt, anonymous not a mismatch.
- `core/tests_email_domain.py` (~700 lines) - branded email delivery order (verified tenant domain -> platform fallback), capability gating, cross-tenant admin rejection, full domain lifecycle with mocked Azure client, remove retains Azure domain, serializer validation + DNS host expansion, `AzureEmailDomainClient` ARM calls, ownership tags, throttling/timeout errors, ETag retry on link.

## Gotchas / non-obvious conventions / risks
- `Tenant.features` is UI-only: no backend enforcement outside core (verify before assuming a disabled feature's API is closed).
- Tenant create (superadmin) leaves `max_*`/`trial_ends_at` null => unlimited + trial never ends; plan defaults only apply when `plan` is later patched.
- `decrypt()` swallows invalid tokens and returns '' (secret loss is silent). Deriving the key from `SECRET_KEY` couples secret rotation to stored gateway/Zoom secrets. Always set `FIELD_ENCRYPTION_KEY` in prod.
- `PaymentGateway.is_configured` checks the encrypted column non-empty, not that it decrypts.
- `TenantMiddleware` exempt list is prefix-based (`startswith`): anything added under an exempt prefix automatically skips tenant checks.
- `/api/v1/tenant/` exempt prefix does not match `/api/v1/tenant-admin/` (different char after `tenant`).
- Public tenant config endpoint (`TenantDetailView`, `/api/v1/tenant/<uuid>/`) is unauthenticated and enumerable by UUID; leaks name, branding, gateway provider.
- Swagger/ReDoc are public in production.
- Hardcoded fallback notification email address (a personal Gmail) exists in `dailytaiyari/settings.py`, `core/emails.py`, and `seed_data.py` (do not copy the value; override `PLATFORM_NOTIFICATION_EMAIL`).
- `LandingImageUploadView` (5 MB cap) and `content` `AdminImageUploadView` (no cap) save whatever the client sends under `landing_images/` / `content_images/` with a client-controlled extension taken from the data-URL header; only multipart path validates nothing either. Treat as unvalidated uploads (unverified XSS/SVG risk).
- Audit trail excludes `ai_platform_monthly_tokens` changes.
- `AuditLog` rows survive tenant deletion (SET_NULL) but `PlatformAnnouncement` for a tenant is CASCADE-deleted.
- Email-domain `DELETE` unlinks but intentionally leaves the Azure domain resource for platform cleanup; domain can't be changed without removing first.
- The `/api/v1/superadmin/leads/` view loads all three tables fully and merges in memory.
- Migrations: 27 files (`0001`-`0027`); no data migrations. `core.0027` adds `custom_email_domains_enabled`; `0026` TenantEmailDomain. `landing_defaults` is imported at class-body time inside `LandingPage`/`LegalDocument` (choices) - changing `TEMPLATE_CHOICES` creates a new migration.

## Key files
- `backend/core/models.py` - Tenant, integrations, landing, leads, audit, announcements, base abstract models.
- `backend/core/middleware.py` - TenantMiddleware + BlockSuspendedUsersMiddleware.
- `backend/core/views.py` - TenantAwareViewSet/ReadOnly base + public tenant config + lead create views.
- `backend/core/permissions.py` - IsSuperAdmin, IsTenantAdmin, IsCourseEditor.
- `backend/core/superadmin_views.py`, `superadmin_serializers.py`, `superadmin_urls.py` - platform dashboard API + audit.
- `backend/core/admin_views.py`, `admin_serializers.py`, `admin_urls.py` - tenant-admin settings/gateway/email-domain/Zoom.
- `backend/core/landing_views.py`, `landing_serializers.py`, `landing_urls.py`, `landing_defaults.py` - landing pages + legal docs.
- `backend/core/azure_email_domains.py` - Azure ARM email domain client.
- `backend/core/encryption.py` - Fernet encrypt/decrypt.
- `backend/core/signals.py` - dynamic CORS.
- `backend/core/serializer_fields.py` - Base64ImageField.
- `backend/core/emails.py`, `utils.py` - lead notifications; scoring/XP helpers.
- `backend/core/management/commands/seed_data.py` - dev seeder.
- `backend/core/tests.py`, `tests_email_domain.py` - isolation and email-domain tests.
