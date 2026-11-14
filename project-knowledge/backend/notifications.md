# notifications

Source: branch `main`.

- **Purpose**: (1) In-app notifications (bell, unread badge, notifications page), (2) tenant-branded HTML email (logo, name, theme accent, optional tenant-owned sender domain via Azure Communication Services), (3) admin announcements fan-out (in-app + email), (4) editable per-tenant lifecycle email templates, (5) automated birthday greetings. It is also the shared email pipeline: `users/`, `core/`, `hackathons/` call `notifications.emails.send_branded_email` / `notifications.services`.
- **Mount**: `/api/v1/notifications/` (backend/dailytaiyari/urls.py).

## Key models (backend/notifications/models.py; plain `models.Model`, UUID pk)
| Model | Notes |
|---|---|
| `Notification` | one row per recipient per event: `tenant` (nullable), `recipient`->User, `type` (enrollment_request/approved/rejected, announcement, ai_allowance, account_created, course_assigned, birthday, birthday_digest, hackathon_registered/stage/result/winner/announcement), `title`, `body`, `link` (frontend-relative path), `data` JSON, `is_read`, `read_at`. Index (recipient, is_read, -created_at). Adding a type needs a migration (choices; migrations 0003/0004/0005/0007 are all type-choice alterations). |
| `Announcement` | admin broadcast: `tenant`, `created_by`, `title`, `body`, `audience` all/courses, `courses` M2M, `send_email`, `send_in_app`, `status` sending/sent/failed, `recipients_count`, `sent_at`. |
| `TenantEmailTemplate` | override of subject/heading/body per `(tenant, type)` (unique_together). Types: enrollment_request, enrollment_approved, enrollment_rejected, account_created, course_assigned, credentials_reset, birthday_student, birthday_past_student, birthday_digest. Blank part = packaged default (`email_templates.DEFAULT_EMAIL_TEMPLATES`). |
| `BirthdayGreetingLog` | unique `(user, year)` — never greet the same person twice per year. |
| `BirthdayDispatchRun` | unique `(tenant, run_date)`; atomic claim of the daily sweep; `attempts`, `last_attempt_at`, `completed_at` (null while in flight/failed -> retried after 30 min). |
Related (in core): `core.TenantEmailDomain` (Azure-provisioned sender domain, one per tenant), `Tenant.notification_email`/`notification_recipient_emails()`, `Tenant.advanced_setting(key)`, `Tenant.custom_email_domains_enabled`, `Tenant.allowed_origins`.

## API (backend/notifications/urls.py)
Any authenticated user (own notifications only; filtered by `recipient=request.user`): `GET ''` (paginated 20, `?unread=1`, `?type=a,b`, adds `unread_count`), `GET unread-count/` (the bell poll — also **triggers the lazy birthday sweep**), `GET birthday/` (today's unread birthday notification for the confetti overlay; also triggers the sweep), `POST mark-all-read/`, `POST <uuid>/read/`.
Tenant admin (`IsAuthenticated + IsTenantAdmin`): `GET/POST announcements/` (create fans out via `services.dispatch_announcement`), `GET email-templates/`, `GET/PUT/DELETE email-templates/<type>/` (PUT with all parts blank deletes the override; responses include effective + default parts, placeholder list, rendered preview with sample data).
Announcement recipients: active, non-suspended users of the tenant with role student or instructor (courses audience: approved enrolments in the chosen courses; course ids filtered to the tenant).

## Business logic
- `backend/notifications/services.py`: event handlers called from other apps, each swallowing/logging errors so notification failure never breaks the triggering action: `on_enrollment_requested` (alerts tenant admins in-app + email to `notification_email` list or admin emails), `on_enrollment_approved/rejected`, `on_student_account_created(user, temp_password)` and `on_credentials_reset` (**always sent inline, never queued**, so temp passwords never sit in a broker payload), `on_course_assigned`, `on_ai_allowance_warning` (called from `chatbot/resolver.py`), `deliver_announcement` / `dispatch_announcement`, low-level `notify(...)` and `_dispatch_email(...)`. Callers are in `users/views.py` (many) and `hackathons/notify.py`.
- Async switch: setting `NOTIFICATIONS_ASYNC` (env, default False). When True, `_dispatch_email` enqueues `notifications.send_branded_email` and announcements enqueue `notifications.deliver_announcement`; on any enqueue exception it falls back to inline. Announcement email = one task per recipient (no shared To/BCC).
- `backend/notifications/emails.py` `send_branded_email(tenant, to, subject, heading, body_html, cta_text, cta_url, preheader, ...)`: renders `backend/notifications/templates/emails/base_email.html` with logo + accent from tenant theme (`_THEME_ACCENTS`), builds multipart text+HTML, never raises (returns bool). Sender: if `tenant.custom_email_domains_enabled` and the tenant's `TenantEmailDomain` is ready and active, send from that verified domain; on failure records `last_error` and falls back to the platform sender (`DEFAULT_FROM_EMAIL` address with tenant name as display name) unless `fallback_to_platform=False`. Link building (`tenant_link`/`tenant_frontend_origin`): prefers the request `Origin` only if it is in `tenant.allowed_origins` or an `https://<subdomain>.dailytaiyari.in|.ai` host owned by that tenant; else first `allowed_origins`; else `FRONTEND_URL`. Relative media URLs made absolute with `BACKEND_PUBLIC_URL`.
- `backend/notifications/email_templates.py`: default templates with `{placeholder}` tokens, `render_email(tenant, type, context)` (HTML-escaped substitution, plain-text paragraphs -> `<p>`).
- `backend/notifications/birthdays.py`: sweep for students whose DOB month/day is today (29 Feb celebrated on 28 Feb in non-leap years); "past students" (no active approved enrolment) get a re-engagement variant; optional emails to students and admin digest, all controlled by `Tenant.advanced_setting`: `birthday_greetings`, `birthday_email_student`, `birthday_include_past_students`, `birthday_notify_admins`, `birthday_email_admins`. Skipped for inactive, suspended or billing-frozen tenants. `maybe_run_for_tenant` = request-time trigger (per-process memo + `BirthdayDispatchRun` claim; runs via Celery if `NOTIFICATIONS_ASYNC` else a daemon thread). Cron path: management command.
- Celery tasks (`backend/notifications/tasks.py`): `notifications.send_branded_email` (max_retries=2), `notifications.deliver_announcement`, `notifications.send_birthday_greetings` ("for deployments that add a beat scheduler" — none configured in repo), `notifications.run_tenant_birthday_sweep`.
- Management command: `python manage.py send_birthday_greetings [--date YYYY-MM-DD] [--tenant <id|subdomain|name>] [--force] [--dry-run]` (idempotent; suggested cron `30 3 * * *`).

## Integrations / settings / env vars (names only)
- `EMAIL_PROVIDER` = `azure` | `smtp` | `console` (default `console` when `DEBUG`, else `azure`). Azure/ACS backend: `django_azure_communication_email.EmailBackend` with `AZURE_COMMUNICATION_CONNECTION_STRING` (sending credential; env only). Tenant-domain provisioning uses Azure Resource Manager service-principal env vars: `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_SUBSCRIPTION_ID`, `AZURE_EMAIL_RESOURCE_GROUP`, `AZURE_EMAIL_SERVICE_NAME`, `AZURE_COMMUNICATION_RESOURCE_GROUP`, `AZURE_COMMUNICATION_SERVICE_NAME`, `AZURE_COMMUNICATION_API_VERSION` (default 2023-03-31); these are only defined when `EMAIL_PROVIDER=azure`. SMTP: `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`.
- Also: `DEFAULT_FROM_EMAIL`, `NOTIFICATIONS_ASYNC`, `BACKEND_PUBLIC_URL`, `FRONTEND_URL`, `PLATFORM_NOTIFICATION_EMAIL` (inbound marketing-lead recipient, used by core), Celery `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND`.
- Tenant-owned credentials in DB: none for ACS sending (platform-wide connection string in env); tenant sender domain state in `core.TenantEmailDomain` (DNS records + Azure resource id, no passwords).
- Celery worker: tasks run on the default queue (`celery-worker` in backend/docker-compose.yml).

## Cross-app dependencies
Imports `core` (Tenant, IsTenantAdmin, TenantEmailDomain), `exams.Course`, `users` (User, CourseEnrollment). Called by `users/views.py` (enrolment, account creation, credential reset), `users/emails.py`, `core/admin_views.py` (test email), `chatbot/resolver.py` (AI allowance warning), `hackathons/notify.py`, plus tests in `core/tests_email_domain.py`, `chatbot/tests.py`. Frontend: `frontend/exam-frontend/src/services/notificationService.js`.

## Tests
No dedicated `backend/notifications/tests*`. Indirect coverage: `core/tests_email_domain.py` (branded email + tenant domain fallback via `send_branded_email`, mocks `EmailMultiAlternatives`), `chatbot/tests.py` (allowance warning), `users/tests_registration_consent.py` (`tenant_link`). Birthdays, announcements and templates are untested.

## Gotchas / risks
- Notification polling endpoints (`unread-count/`, `birthday/`) perform side effects (birthday sweep). With `NOTIFICATIONS_ASYNC=False` the sweep runs in a daemon thread inside the web worker (`threading.Thread`), which can be killed on gunicorn worker recycle; the 30-minute stale-claim logic retries it.
- Inline email sending (`NOTIFICATIONS_ASYNC` off, the default) blocks the request: an announcement to N students sends N emails serially inside the POST.
- Notification `type` is a CharField with choices; new types require a migration (see 0003-0007 history).
- Announcement body is escaped line-by-line into `<p>` (safe), but `on_ai_allowance_warning` builds HTML from a constructed string (no user input).
- `account_created`/`credentials_reset` emails contain plaintext temp passwords (inline-only by design).
- `PLATFORM_NOTIFICATION_EMAIL` ships with a hardcoded personal-address default in settings.py (should be required env) — value intentionally not recorded here.
- `TenantEmailTemplate` / email domain feature relies on the hostname patterns `*.dailytaiyari.in` / `*.dailytaiyari.ai` hardcoded in `emails._request_frontend_origin`.
- Notification list/mark-read are scoped by `recipient` only (not tenant), which is fine since users are tenant-bound.

## Key files
- backend/notifications/models.py — Notification, Announcement, TenantEmailTemplate, Birthday* models
- backend/notifications/services.py — event handlers + announcement fan-out + `_dispatch_email`
- backend/notifications/emails.py — branded sender, tenant domain fallback, link/origin safety
- backend/notifications/email_templates.py — default templates, placeholders, `render_email`
- backend/notifications/templates/emails/base_email.html — HTML shell
- backend/notifications/birthdays.py — birthday engine; management/commands/send_birthday_greetings.py — CLI
- backend/notifications/tasks.py — Celery tasks
- backend/notifications/views.py, serializers.py, urls.py — API
- backend/dailytaiyari/settings.py — email/Azure/async settings; backend/core/azure_email_domains.py — ARM client for tenant domains
