# liveclass

Source: branch `main`. Companion doc already in repo: `wiki/live-classes-zoom.md` (accurate as of main; this file adds code-verified detail and risks).

- **Purpose**: Scheduled live sessions authored under a course Topic. Two live providers: `gmeet` (instructor pastes a link) and `zoom` (meeting created on the tenant's own Zoom account via Server-to-Server OAuth, per-student registered join links, attendance from webhooks + Zoom participant report). `in_house` exists as a provider choice but is rejected by the authoring serializer ("coming soon").
- **Mount**: `/api/v1/live-classes/`. Zoom webhook paths are in `TENANT_EXEMPT_PATHS` (backend/core/middleware.py) -> no `X-Tenant-ID`, no auth.

## Key models (backend/liveclass/models.py)
| Model | Notes |
|---|---|
| `LiveClass` (OrderedModel) | `tenant` (required, non-null), `course`, `subject?`, `topic`, `title`, `description`, `provider`, `meeting_url`, `scheduled_start`, `duration_minutes` (default 60), `host_name`, `status` draft/published/archived. Zoom fields: `zoom_meeting_id` (indexed), `zoom_meeting_uuid` (occurrence), `zoom_start_url` (host-only, never in student payloads), `zoom_passcode`, `zoom_registration_enabled`, `zoom_started_at/ended_at`, `attendance_synced_at`, `attendance_sync_error`. Derived: `live_status` upcoming/live/ended (from schedule), `zoom_linked`, `supports_attendance` (= zoom_linked). `ENABLED_PROVIDERS = {gmeet, zoom}`. |
| `LiveClassRegistrant` | (live_class, student) unique `uniq_liveclass_student_registrant`; stores email sent to Zoom, `zoom_registrant_id`, personal `join_url`. |
| `LiveClassAttendance` | one row per student per class (partial unique `uniq_liveclass_student_attendance` where student not null); guests (Zoom participants not matched to a student) have `student=NULL`. `source` portal/webhook/report/manual; `status` present/partial/absent; `duration_minutes`, `join_count`, `is_currently_in_call`, `is_manual_override` (pins status against later syncs), `notes`. `recompute_status(threshold%)`. |
| `core.ZoomIntegration` (in core) | OneToOne per tenant: `account_id`, `client_id`, `client_secret_encrypted`, `webhook_secret_token_encrypted`, `host_email`, `use_registration`, `pull_reports`, `attendance_threshold_percent` (60), `is_active`, `last_verified_at/last_error`, `webhook_validation_until`. Secrets Fernet-encrypted (`core/encryption.py`, key = `FIELD_ENCRYPTION_KEY` else derived from `SECRET_KEY`). |

## API
Student (`backend/liveclass/views.py`, `IsAuthenticated`): `GET classes/?topic=<id>` — published classes for courses the student is approved+active enrolled in; `POST classes/<id>/join/` — returns personal join URL (lazy Zoom registration, falls back to shared `meeting_url`) and records a `portal` attendance hit. For registered Zoom meetings the shared `meeting_url` is blanked in list payloads (`requires_join_request=true`).

Admin/instructor (`backend/liveclass/admin_views.py`, `AdminLiveClassViewSet(TenantAdminModelViewSet)`, permission `IsCourseEditor` = tenant admin or instructor assigned to the course; instructors tenant+course scoped via `course_lookup='course'`), base `admin/classes/`: CRUD (create/update push to Zoom; delete removes Zoom meeting first), `<id>/zoom-sync/` (retry create), `<id>/host-link/` (host start URL), `<id>/attendance/` (register + summary; lazily syncs if stale and materialises absent rows once ended), `<id>/attendance/sync/` (force pull), `PATCH <id>/attendance/<row_id>/` (override status/notes/`clear_override`), `<id>/attendance/export/` (CSV). Filters: course, subject, topic, status, provider.

Webhook (`backend/liveclass/webhooks.py`, `AllowAny`, no authentication classes, csrf_exempt): `POST zoom/webhook/<tenant_uuid>/` (current, tenant-scoped) and `POST zoom/webhook/` (legacy unscoped, tenant resolved from `payload.object.id` = meeting id).

Tenant admin Zoom settings (lives in core): `/api/v1/tenant-admin/zoom/` GET/PUT/POST(test connection or `{"action":"start_verification"}`)/DELETE — `core.admin_views.ZoomIntegrationView`, `IsTenantAdmin`.

## Business logic
- `backend/liveclass/zoom.py`: `ZoomClient` (requests, no SDK). Token endpoint `https://zoom.us/oauth/token` (grant `account_credentials`), API `https://api.zoom.us/v2`; token cached in Django cache `zoom:token:<integration pk>` (TTL = expires_in - 120s); retries once on 401 (fresh token) and once on 429 (1.5s sleep). Methods: create/update/get/delete meeting, add_registrant, get_participants (falls back /report -> /metrics -> /past_meetings), `verify`. Helpers: `verify_webhook_signature` (HMAC-SHA256 of `v0:<ts>:<raw body>`, `compare_digest`), `is_valid_plain_token` (`^[A-Za-z0-9_\-.]{1,128}$` — blocks use of the URL-validation challenge as a signing oracle), `webhook_validation_response`.
- `backend/liveclass/services.py`: `sync_zoom_meeting` (never raises; returns (ok, error), class saved even if Zoom fails -> `zoom_error` in response), `join_url_for_student`, `record_portal_join`, `_match_student` (registrant_id -> registrant/account email -> exact unambiguous display name), `handle_participant_joined/left`, `sync_attendance_from_zoom` (idempotent; sums stints per person; sets absent for no-shows; honours manual overrides), `ensure_absent_rows`, `attendance_summary`.
- Webhook events handled: `endpoint.url_validation`, `meeting.started`, `meeting.ended` (triggers immediate sync, often too early), `meeting.participant_joined/left`. Unknown meetings acked 200; bad signature 401; handler exceptions swallowed (200) so Zoom does not retry.
- URL-validation: scoped URL uses that tenant's token; legacy URL only answers while `ZoomIntegration.webhook_validation_until` is in the future (30 min, opened on saving a Secret Token or via `start_verification`).
- Celery (`backend/liveclass/tasks.py`): `liveclass.sync_attendance` (retries up to 3x, 300s countdown) and `liveclass.sync_recent_attendance(hours=24)`. **Neither is scheduled anywhere** (no beat config in repo); admin register view lazily syncs, so a worker is optional.
- Management command: `python manage.py sync_live_attendance --hours 24` (cron backstop; calls the task function synchronously).
- `exams/course_copy.py` clones LiveClass rows when a course is copied.

## Integrations / settings / env vars
- Zoom credentials are NOT env vars: stored per tenant in DB (`ZoomIntegration`, encrypted). Required Zoom app scopes: meeting:write:admin, meeting:read:admin, report:read:admin, user:read:admin; event subscriptions meeting.started/ended + participant_joined/left. Webhook URL to paste in Zoom: `https://<api-host>/api/v1/live-classes/zoom/webhook/<tenant-id>/` (shown in settings UI; **depends on the deployed API hostname**).
- Env: `FIELD_ENCRYPTION_KEY` (strongly recommended in prod; otherwise derived from `SECRET_KEY`, so rotating SECRET_KEY makes stored Zoom/PayU secrets undecryptable -> `decrypt` returns ''), Celery broker/result env (`CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`) for the optional tasks. Django cache backend must be shared across workers for the token cache to help.
- Zoom plan limits: registration needs paid plan, `/report` needs Pro+; otherwise attendance degrades to webhook durations + portal clicks.

## Cross-app dependencies
Imports: `core` (OrderedModel, TimeStampedModel, Tenant, ZoomIntegration, encryption), `exams` (Course, Subject, Topic, TenantAdminModelViewSet), `users` (CourseEnrollment, StudentProfile). Called by: `exams/course_copy.py`; frontend `contentBuilderService.js`, `liveClassService.js`, CourseManager.jsx (scheduling + attendance drawer), StudyTopicContent.jsx (join flow).

## Tests (backend/liveclass/tests.py, ~361 lines)
`ZoomSignatureTests` (valid/wrong secret/missing headers/no secret; challenge response; signing payload not a valid plainToken), `ParticipantMatchingTests` (registrant id, account email, exact display name, guest), `AttendanceDurationTests` (accumulate, partial, rejoin, manual override, absent roster fill), `ZoomWebhookEndpointTests` (scoped/unscoped validation, signing-oracle defence, other tenant's meeting ignored, forged signature, valid join, unknown meeting, no tenant header), `StudentSerializerTests` (registered link hidden). No tests for admin viewset permissions, Zoom client HTTP, CSV export, student `join`.

## Gotchas / risks
- Webhook signature check does not validate `x-zm-request-timestamp` freshness -> captured events are replayable (effects are idempotent-ish: join counts/duration could be inflated). Signature still required (empty secret = reject).
- Legacy unscoped webhook resolves tenant from meeting id alone (`order_by('-created_at').first()`); signature then verified with that tenant's token, so a collision just fails verification.
- `LiveClassViewSet` (student) does not filter by tenant explicitly — scoped via the student's own enrolments (`course_id__in`), which are tenant-bound.
- Admin serializer `course/topic/subject` PrimaryKeyRelatedFields use unrestricted querysets (cross-tenant FK injection possible if IDs known) — unverified exploitability; `perform_create` only guards instructor course ownership.
- `zoom_start_url` is exposed to admin/instructor serializer `AdminLiveClassSerializer` list payload fields (`zoom_start_url` is in `fields`, read-only) despite the wiki saying it is kept out of list payloads — the code lists it in `fields`. Treat host URL as sensitive; student serializer does not include it.
- Provider `in_house` still in `PROVIDER_CHOICES`/DB, blocked only by serializer validation.
- `ZoomClient` uses `time.sleep(1.5)` in-request on 429.

## Key files
- backend/liveclass/models.py — LiveClass, LiveClassRegistrant, LiveClassAttendance
- backend/liveclass/zoom.py — Zoom REST client + signature helpers
- backend/liveclass/services.py — meeting lifecycle, registration, attendance reconciliation
- backend/liveclass/webhooks.py — Zoom event receiver
- backend/liveclass/views.py / serializers.py — student API
- backend/liveclass/admin_views.py / admin_serializers.py — authoring + attendance API + CSV
- backend/liveclass/tasks.py, management/commands/sync_live_attendance.py — attendance backstops
- backend/core/models.py (`ZoomIntegration`), backend/core/admin_views.py (`ZoomIntegrationView`), backend/core/encryption.py — credentials + encryption
- backend/core/middleware.py — `TENANT_EXEMPT_PATHS`
- wiki/live-classes-zoom.md — admin-facing guide
