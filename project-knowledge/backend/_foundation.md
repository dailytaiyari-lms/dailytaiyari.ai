# Backend foundations (cross-cutting)

Source of truth: production branch `main`. Verified from code in `backend/core`, `backend/users`, `backend/dailytaiyari`. Items marked "unverified" were not confirmed from code.

## 1. Request pipeline (settings.MIDDLEWARE order)
`CorsMiddleware` -> `SecurityMiddleware` -> `SessionMiddleware` -> `CommonMiddleware` -> `CsrfViewMiddleware` -> `AuthenticationMiddleware` -> `MessageMiddleware` -> `XFrameOptionsMiddleware` -> **`core.middleware.TenantMiddleware`** -> **`core.middleware.BlockSuspendedUsersMiddleware`**.

### TenantMiddleware (backend/core/middleware.py)
- Applies to EVERY path (not only /api/), except prefixes in `TENANT_EXEMPT_PATHS` (sets `request.tenant = None`):
  `/admin/`, `/api/v1/tenant/` (public branding config), `/api/v1/platform/` (marketing leads), `/api/v1/superadmin/`, `/api/v1/certificates/verify/`, `/api/v1/payments/webhook/`, `/api/v1/payments/payu/callback/`, `/api/v1/live-classes/zoom/webhook/`, `/api/docs/`, `/api/redoc/`, `/static/`, `/media/`.
- Everything else REQUIRES header `X-Tenant-ID: <uuid>`:
  - missing -> 403 `{"error": "X-Tenant-ID header is required."}`; bad UUID -> 403; unknown/`is_active=False` tenant -> 403.
  - Sets `request.tenant` (Tenant instance).
- **Tenant/user binding**: `resolve_request_user()` decodes the JWT itself (middleware runs before DRF) and caches on `request._resolved_api_user`. If the user is authenticated, not `is_superuser`, has a non-null `tenant_id` and it differs from the header tenant -> 403 `code: tenant_mismatch`. Anonymous requests and superusers are exempt (superusers are tenant-less by design).
- **Freeze check**: `tenant.access_block()` -> `(blocked, message, code)`. Suspension wins (`code: tenant_suspended`, custom `suspension_message`), else billing freeze (`code: subscription_inactive`). Blocked tenants get 403 `{detail, code}` on everything except `TENANT_SUSPENSION_BYPASS_PATHS` (`/api/v1/auth/login/`, `refresh/`, `logout/`, `profile/`). NOTE: this applies to anonymous calls too (e.g. public catalogue, register).
- Side effect: JWT is authenticated twice per request (middleware + DRF) = two user lookups.

### BlockSuspendedUsersMiddleware
- For paths starting `/api/` not in `SUSPENSION_EXEMPT_PATHS` (`auth/login|register|refresh|logout|verify-email|resend-otp|password/|profile/`): if resolved user has `is_suspended=True` -> 403 `code: account_suspended` (403 not 401, so the frontend keeps the session and shows an overlay). Per-USER suspension (User.is_suspended), distinct from per-TENANT suspension.
- Suspended users CAN still log in (login view only blocks `is_active=False` and tenant freeze). Frontend shows blocking overlay.

## 2. Tenant model (backend/core/models.py) - every field
Table `core_tenant`; PK UUID. Related names: `users`, `courses`, `payment_gateways`, `email_domain`, `zoom`, `landing_page`, `legal_documents`, `audit_logs`, `announcements`.

| Field | Type / default | Meaning |
|---|---|---|
| id | UUID pk | sent by clients as `X-Tenant-ID` |
| name, tagline | Char | branding; `name` is used in emails |
| subdomain | Char(100) unique, nullable | e.g. `<sub>.dailytaiyari.in/.ai`; used to trust request Origin in guardian links |
| logo, favicon | ImageField (`tenant_logos/`, `tenant_favicons/`) | storage backend decides absolute vs relative URL |
| theme | choice, default `sunrise` | keys: sunrise, ocean, emerald, violet, rose, indigo, slate, amber, cherry, lime (keep in sync with frontend `src/config/themes.js`) |
| show_name | bool True | hide text name if logo already has it |
| auth_panel | JSON dict | login/register left-panel copy `{heading, heading_highlight, subtitle, stats[<=4]{value,label}}` |
| is_active | bool True | False = quietly retired (middleware 403 "Tenant not found or inactive") |
| custom_email_domains_enabled | bool False | platform-owned capability gate for Azure sender domains; superadmin-only to set (read-only in tenant-admin serializer) |
| features | JSON {key: bool} | tenant toggles; missing key = ENABLED |
| feature_locks | JSON {key: bool} | superadmin locks: key present => forced to that value and tenant cannot change (validation error telling them to contact DailyTaiyari team); replaced wholesale on update |
| feature_labels | JSON {key: label} | cosmetic rename (<=40 chars); blank = reset |
| advanced_settings | JSON {key: bool} | behaviour switches, defaults in `ADVANCED_SETTING_CHOICES` |
| registration_settings | JSON | per-field `{enabled, required}` + `guardian_consent: {enabled}` |
| is_suspended, suspension_message | bool / Text | superadmin freeze (login + all API blocked) |
| plan | choice, default `trial` | trial/starter/growth/enterprise |
| billing_status | choice, default `trialing` | trialing/active/past_due/expired/canceled |
| trial_ends_at, current_period_end | DateTime null | `trialing` freezes after `trial_ends_at` (null = never) |
| max_students / max_courses / max_admins | PositiveInt null | caps; None = unlimited |
| request_enrollment_free / request_enrollment_paid | bool True/True | enrolment mode flags (see 4) |
| notification_email | Char(500) | comma/newline/; separated admin-notification recipients; blank => tenant admin accounts' emails |
| allowed_origins | JSON list | exact browser origins for this tenant's frontend: (a) dynamic CORS allow-list, (b) deep-link base URL in emails |
| ai_platform_monthly_tokens | PositiveInt 0 | monthly token gift from the PLATFORM LLM key (0 = tenant must bring own key; see chatbot) |
| created_at / updated_at | auto | |

### FEATURE_CHOICES (toggleable product areas; frontend shows/hides nav+routes)
`courses, study, quiz, mock_tests, pyq, community, analytics, leaderboard, ai, jobs, hackathons`. Resolution (`get_features()`): lock wins, else stored value, else True. **There is NO `OPT_IN_FEATURES` concept on `main`** (grep: zero hits) - every feature defaults ON for new keys. To add a feature: add to `FEATURE_CHOICES`, no migration needed.
- **Backend does NOT enforce `features` anywhere outside core** (grep of other apps shows no `get_features()` use). Flags are frontend/UI gating only; a disabled feature's API still works.

### ADVANCED_SETTING_CHOICES (default)
`birthday_greetings` (True), `birthday_email_student` (True), `birthday_include_past_students` (True), `birthday_notify_admins` (True), `birthday_email_admins` (False). Consumed by `notifications/birthdays.py` via `tenant.advanced_setting(key)`.

### REGISTRATION_FIELD_CHOICES
`phone` (default enabled), `date_of_birth, gender, preferred_language, grade, board, school, coaching, medium, stream, city, state, admission_number, batch_section`. Enabling `guardian_consent` forces `date_of_birth` enabled+required. `public_registration_schema()` is exposed on the public tenant config endpoint. Registration serializer drops fields the tenant has disabled and enforces `required`. Note `preferred_language` is a User field but accepted via the schema.

### Plans / quotas
`PLAN_DEFAULTS`: trial 50 students/3 courses/2 admins; starter 300/15/5; growth 2000/100/15; enterprise unlimited. `apply_plan_defaults()` runs ONLY when superadmin changes `plan` without sending explicit `max_*`. `can_add(resource)` checks `usage_counts()` (live COUNT queries). Enforced in: public `RegisterView` + admin student create (students), `AdminCourseViewSet.create/copy` and `coursegen/apply.py` (courses). `admins` cap is NEVER enforced (no API creates admins).
- Tenant created via superadmin `TenantCreateSerializer` does NOT call `apply_plan_defaults()` -> new tenants have `max_*=NULL` (unlimited) until a plan is set, and `trial_ends_at=NULL` (trial never expires). Likely oversight.
- `is_billing_frozen`: expired/canceled, or trialing with lapsed `trial_ends_at`. `past_due` is a soft state (not frozen).

### Enrolment mode (`enroll_mode_for(course)`)
free course: `request` if `request_enrollment_free` else `self` (auto-approve); paid course: `payment` only if `request_enrollment_paid=False` AND active configured gateway, else `request`. Tenant-admin serializer refuses `request_enrollment_paid=False` without an active gateway.

### Payment secrets / encryption (backend/core/encryption.py)
- Fernet. Key = `settings.FIELD_ENCRYPTION_KEY` if set, else sha256(`SECRET_KEY`) urlsafe-b64. `decrypt()` returns '' on invalid token (silently!) - rotating SECRET_KEY without a dedicated `FIELD_ENCRYPTION_KEY` makes all stored secrets read as empty (gateway `is_configured` still True because it checks the encrypted column).
- Encrypted columns: `PaymentGateway.key_secret_encrypted`, `webhook_secret_encrypted`; `ZoomIntegration.client_secret_encrypted`, `webhook_secret_token_encrypted`. Plaintext only via model properties (`key_secret`, `webhook_secret`, `client_secret`, `webhook_secret_token`); serializers are write-only + `has_*` booleans; blank on update keeps stored secret.
- `PaymentGateway`: unique (tenant, provider); providers razorpay/cashfree/payu; only one `is_active` per tenant (PUT view deactivates others in a transaction); `webhook_secret` falls back to account secret. `key_id` stored plaintext.
- Docstring says "each tenant has at most one gateway" but the constraint is one per PROVIDER.

### Other core models
- `TenantEmailDomain` (OneToOne tenant, unique `domain`): Azure Communication Services sender domain. `is_verified` needs Domain/SPF/DKIM/DKIM2 all `Verified`; `is_ready` = verified + sender_provisioned + is_linked. Tenant admin manages via `/api/v1/tenant-admin/email-domain/` (403 `custom_email_domains_disabled` unless superadmin enabled the capability). `notifications.emails.send_branded_email` uses it when `is_ready and is_active` and falls back to platform sender.
- `ZoomIntegration` (OneToOne): Server-to-Server OAuth creds; `webhook_validation_until` opens a 30-minute window in which the legacy unscoped webhook URL answers Zoom's URL-validation challenge. Scoped webhook URL: `/api/v1/live-classes/zoom/webhook/<tenant_id>/`.
- `LandingPage` (OneToOne): `template` (default `aurora`), `is_published`, `sections` JSON `[{id,type,enabled,data}]`, `footer`, `meta`. `LegalDocument` unique (tenant, doc_type) for refund/privacy/terms; defaults generated in `core/landing_defaults.py`.
- `PlatformAnnouncement` (global when `target_tenant` null; `level` info/warning/critical; `starts_at/ends_at/is_active`; `is_live()`); surfaced in public tenant config as `announcements`.
- `SuperAdminAuditLog` (actor FK SET_NULL, `actor_email`, `action`, `target_tenant` SET_NULL, `target_name`, `changes {field:[old,new]}`; indexes on (target_tenant,-created_at), (-created_at)).
- Platform leads (abstract `PlatformLead`: name, email, status new/contacted/closed, source, internal_notes): `DemoBooking`, `ContactMessage`, `JobApplication`. NOT tenant-scoped.

## 3. Base classes
- `core.models.TimeStampedModel` (abstract): UUID `id`, **`tenant` FK (null=True, blank=True, related_name='+')**, `created_at`, `updated_at`, default ordering `-created_at`. Tenant is NULLABLE: most child models inherit it but many rows (subjects, topics, chapters, content...) have a null tenant in legacy data and must be scoped via their parent course.
- `SoftDeleteModel` (adds `is_deleted`, `deleted_at`, `soft_delete()`), `OrderedModel` (adds `order` int indexed; ordering `['order','-created_at']`).
- `core.views.TenantAwareViewSet` (ModelViewSet) / `TenantAwareReadOnlyViewSet`: `get_queryset()` filters `tenant=request.tenant` (returns `.none()` if no tenant); `perform_create` sets `tenant=request.tenant` (403 if none). Because it filters on the model's OWN `tenant` column, any model whose tenant is null (legacy) disappears; subclasses frequently override `get_queryset` entirely (users, content, exams do) and then tenant isolation depends on that override.
- No global manager/queryset tenant filter exists; isolation is by convention (view-level filtering) + middleware header/user binding.
- `core.serializer_fields.Base64ImageField`: accepts `data:image/...;base64,` (stored via default storage), `None` (clear), or an existing URL (SkipField = unchanged).
- `core.utils`: XP/quiz scoring helpers (`calculate_xp_for_quiz`: 5 XP/question x accuracy, cap 25 (40 daily challenge, x1.5), `calculate_streak_bonus`, `get_mastery_level`, coding XP 15/25/40, assignment XP 5-30). Uses non-crypto `random` for `generate_code`.

## 4. Roles & permission classes
- `User.role` in {`student`, `instructor` (label "Faculty"; do NOT rename the stored value), `admin`}. Superadmin = Django `is_superuser=True`, `tenant=None` (role default `student`!).
- `core.permissions`: `IsSuperAdmin` (is_superuser), `IsTenantAdmin` (`role == 'admin'`; tenant binding comes from middleware, the class itself does not compare tenants - superusers with role student FAIL it), `IsCourseEditor` (role admin or instructor; object-level: instructors only objects of courses in `user.instructing_courses`, resolved through the view's `course_lookup` path like `subject__course`).
- DRF default permission = `IsAuthenticated`; most public views set `AllowAny` explicitly (catalogue, landing, register).
- Tenant admin accounts are NOT creatable via any API (admin-create serializer only allows `student`/`instructor`); created in Django admin/shell. Instructors count toward no quota.

## 5. Auth flow (backend/users)
- JWT via `rest_framework_simplejwt`; DRF auth class `users.authentication.RegistrationAwareJWTAuthentication` (plain `JWTAuthentication` subclass; guardian consent is reminder-only, does not block).
- **SIMPLE_JWT: access lifetime 365 days, refresh 730 days**, `ROTATE_REFRESH_TOKENS=True`, `BLACKLIST_AFTER_ROTATION=True` BUT `rest_framework_simplejwt.token_blacklist` is NOT in INSTALLED_APPS => rotation does not actually invalidate old refresh tokens; there is no logout route (see gotchas) so tokens cannot be revoked server-side except by `is_active=False` / suspension.
- Tenant login `POST /api/v1/auth/login/` (needs X-Tenant-ID): `CustomTokenObtainPairSerializer.validate` looks up `User(email=<exact>, tenant=request.tenant)`, checks password, `is_active`, then `tenant.access_block()`. Unverified and suspended users CAN log in. Response `{access, refresh, user}`; token claims add `email, name, is_onboarded, is_suspended`. Email match is case-sensitive on login (registration uniqueness check is `iexact`).
- Email is unique PER TENANT: `unique_together(email, tenant)`; Postgres treats NULL tenant as distinct, so multiple tenant-less (superuser) rows with the same email are not blocked by the DB. `UserManager.create_user(email, tenant=None, ...)`.
- Registration `POST /api/v1/auth/register/`: tenant required; `tenant.can_add('students')` quota; serializer enforces tenant registration schema, password >= 8 + confirm; creates User(role=student, `is_email_verified=False`) + StudentProfile (post_save signal); sends OTP email (swallows failures); if guardian consent required (tenant `guardian_consent.enabled` and DOB < 18) validates a trusted absolute frontend origin first (503 if none) then creates `GuardianConsent` and emails a link `{origin}/guardian-consent/<raw token>`.
- **Email OTP** (`users/emails.py`, model `EmailOTP`): 6-digit CSPRNG code, stored hashed (`make_password`), 10 min expiry, max 5 attempts, 60 s resend cooldown (`can_resend`), single-use; creating a new OTP invalidates older unused ones. Purposes `email_verification`, `password_reset`. Sent through `notifications.emails.send_branded_email` (tenant logo/name) with plain-text `send_mail` fallback. Endpoints: `verify-email/`, `resend-otp/`, `password/forgot/`, `password/reset/` (also marks email verified), `password/change/` (authenticated). Responses are generic to avoid user enumeration (except the 429 cooldown).
- **Email verification is not enforced server-side**; the frontend gates the UI. Direct API calls by unverified users work.
- **Guardian consent** (`GuardianConsent`, one per user): raw token `secrets.token_urlsafe(32)`, only sha256 hash stored (`token_hash` unique), 24 h expiry, statuses pending/granted/withdrawn, tenant-scoped lookup. `POST guardian-consent/<token>/` requires `adult_confirmed, guardian_confirmed, privacy_accepted` all `true`; stores sha256 of consent text; sets `user.guardian_consent_granted_at`. `guardian-consent/status/`, `guardian-consent/resend/` (60 s cooldown), `compliance-status/` (non-blocking DOB + guardian reminder for existing students). Link origin must be in `tenant.allowed_origins`, or an https `<subdomain>.dailytaiyari.in/.ai` host, else falls back to `allowed_origins[0]` / `FRONTEND_URL`. Platform-named tenants (name contains "dailytaiyari") get a neutral "Your institution" brand in these mails.
- Admin provisioning: tenant admin creates students/faculty with a server-generated temp password (`generate_temp_password`, CSPRNG 12 chars) emailed to the user; returned in the API response only if the email failed.
- Superadmin login `POST /api/v1/superadmin/auth/login/` (no tenant header; only `is_superuser` accounts; separate JWT with `is_superuser` claim). Superadmin tokens are not role `admin`, so they cannot use tenant-admin endpoints (`IsTenantAdmin`), but pass the middleware mismatch check and may read some `is_superuser`-allowed endpoints.

## 6. URL groups (dailytaiyari/urls.py)
| Prefix | Tenant header | Auth | Purpose |
|---|---|---|---|
| `/api/v1/tenant/<uuid>/` | exempt | AllowAny | public tenant config: branding, features, feature_labels, registration_schema, suspension/freeze flags, enrolment flags, payment gateway (provider + test-mode only), promo banner, live announcements |
| `/api/v1/platform/` | exempt | AllowAny, throttle `platform_lead` 20/h | `demo-bookings/`, `contact-messages/`, `job-applications/` (create-only) |
| `/api/v1/superadmin/` | exempt | `IsSuperAdmin` | dashboard: auth/login, auth/me, stats, tenants (+detail PATCH), audit-logs, users (+`users/<id>/action/` suspend/unsuspend/verify/reset_password), leads (+detail PATCH status/internal_notes), announcements, platform AI providers/models/usage, `tenants/<id>/ai-allocation/` |
| `/api/v1/landing/` | required | AllowAny | public landing config + legal docs (defaults if none) |
| `/api/v1/tenant-admin/` | required | `IsTenantAdmin` | `settings/`, `payment-gateway/`, `email-domain/`, `zoom/`, `landing/`, `landing/upload-image/`, `landing/legal/<type>/` |
| `/api/v1/tenant-admin/{ai,course-ai,mock-ai,hackathon-ai}/` | required | tenant admin | other apps (chatbot, coursegen, mockgen, hackathons) |
| `/api/v1/auth/` `courses/` `content/` ... | required | per view | learner/admin APIs |
- `/api/docs/` (swagger) and `/api/redoc/` are public (`AllowAny`, `public=True`). Django admin at `/admin/` exempt from tenant header.
- Audited superadmin actions (`SuperAdminAuditLog.action`): `tenant.create|update|suspend|unsuspend|feature_locks|plan|origins|email_domains`, `user.suspend|unsuspend|verify|reset_password`, `announcement.create|update|delete`. Audited tenant fields: name, tagline, subdomain, theme, show_name, is_active, is_suspended, suspension_message, features, feature_locks, custom_email_domains_enabled, request_enrollment_*, plan, billing_status, trial_ends_at, current_period_end, max_*, allowed_origins. NOT audited: `ai_platform_monthly_tokens`.
- Tenant-admin settings serializer sanitises unknown keys for features/labels/advanced/registration/auth_panel and merges onto stored JSON (partial-safe).

## 7. Self-serve CORS (core/signals.py)
`corsheaders.signals.check_request_enabled` handler allows any Origin present in some ACTIVE tenant's `allowed_origins` (cached in `tenant_allowed_origins`, TTL 300 s, invalidated on Tenant post_save/post_delete). With the default LocMem cache the invalidation is per-process; multi-worker deployments see up to 5 min lag unless `REDIS_URL` is set. Static settings also hardcode some customer frontend origins and regexes for `*.dailytaiyari.in/.ai`; `CORS_ALLOW_CREDENTIALS=True`; `x-tenant-id` is in `CORS_ALLOW_HEADERS`.

## 8. Platform leads / super admin dashboard facts
- Leads are tenant-less and emailed to `settings.PLATFORM_NOTIFICATION_EMAIL` (settings default is a hardcoded personal Gmail address - override in prod). `core/emails.py` repeats the same hardcoded address as a fallback via `getattr`.
- Super admin `LeadListView` merges all three lead tables in memory (limit default 200, max 500).

## 9. Other cross-cutting settings worth knowing (beyond the lead's summary)
- Insecure defaults: `SECRET_KEY` default `django-insecure-...`, `DEBUG` default True (when DEBUG is true email falls back to console and SSL/HSTS options are off), `ALLOWED_HOSTS` default localhost.
- DRF throttles: `anon` 100/h, `user` 1000/h applied globally (also to login/register by IP; `NUM_PROXIES` is not set); scoped: quiz_submit, code_run, code_submit, notebook_submit, platform_lead.
- `PageNumberPagination` PAGE_SIZE 20 default; several admin viewsets override (builder 200, student roster 100/5000).
- `TIME_ZONE='Asia/Kolkata'`, `USE_TZ=True`.
- `SILENCED_SYSTEM_CHECKS=["auth.E003"]` (User.email not globally unique).
- Celery: video tasks are sent explicitly to queue `media` (`apply_async(queue='media')`); there is no `CELERY_TASK_ROUTES`, so a worker must be started with `--queues=media` (docker-compose service `celery-mediaworker`). Other queues referenced in compose: default, `notebooks`, `aigen`.
- Env vars read by settings and tasks that matter for these apps: `SECRET_KEY, FIELD_ENCRYPTION_KEY, DEBUG, ALLOWED_HOSTS, DB_*, STORAGE_BACKEND/AZURE_ACCOUNT_*/AZURE_CONTAINER/AZURE_CUSTOM_DOMAIN, EMAIL_PROVIDER, AZURE_COMMUNICATION_CONNECTION_STRING, AZURE_TENANT_ID/CLIENT_ID/CLIENT_SECRET/SUBSCRIPTION_ID/EMAIL_RESOURCE_GROUP/EMAIL_SERVICE_NAME/COMMUNICATION_RESOURCE_GROUP/COMMUNICATION_SERVICE_NAME/COMMUNICATION_API_VERSION, DEFAULT_FROM_EMAIL, PLATFORM_NOTIFICATION_EMAIL, FRONTEND_URL, BACKEND_PUBLIC_URL, CORS_ALLOWED_ORIGINS, REDIS_URL, CELERY_BROKER_URL, CELERY_RESULT_BACKEND, CELERY_VISIBILITY_TIMEOUT, VIDEO_OPTIMIZATION_ENABLED, VIDEO_HLS_ENABLED`. NOT in settings.py (read via `os.environ` in `content/tasks.py`/`hls.py`): `FFMPEG_BINARY, FFPROBE_BINARY, VIDEO_REMUX_TIMEOUT, VIDEO_TRANSCODE_TIMEOUT, VIDEO_HLS_PRESET, VIDEO_HLS_SEGMENT_SECONDS`.
- Deploy: `entrypoint.sh` runs `migrate --noinput` + `collectstatic --noinput` only. No management command is required on deploy for these apps. First superadmin: `python manage.py createsuperuser` (per deploy/README).
- Fresh DB gotcha: `exams` migration 0006 `get_or_create`s a "Default Tenant" (hardcoded UUID, subdomain `default`) on every new database.
