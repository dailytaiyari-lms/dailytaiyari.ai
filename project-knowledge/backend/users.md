# users

- **Purpose**: custom email-based `User` (tenant-scoped, three roles), student profile + enrolment workflow, email OTP verification/password reset, parent/guardian consent for minors, and the tenant-admin student/faculty roster management API. Authentication endpoints (JWT login/refresh) live here and are mounted at `/api/v1/auth/`. See `_foundation.md` section 5 for the auth narrative.

## Key models (backend/users/models.py)
- `User(AbstractUser)`: UUID pk; `username=None`; `email` (NOT unique globally); `USERNAME_FIELD='email'`; `tenant` FK core.Tenant (CASCADE, null, related_name `users`); `role` student|instructor ("Faculty" label; stored value must not change)|admin; `is_suspended`; `is_email_verified`, `email_verified_at`; `guardian_consent_required`, `guardian_consent_granted_at`; `phone`, `avatar`; `is_onboarded`, `onboarded_at`; `preferred_language`, `notification_enabled`, `dark_mode`; `created_at`, `updated_at`, `last_active` (auto_now => updates on every save). Unique: `unique_together(email, tenant)`. Manager `UserManager.create_user(email, tenant=None, password=None, **extra)`; `create_superuser` is tenant-less. Does NOT extend `TimeStampedModel`.
- `EmailOTP(TimeStampedModel)`: user FK, `code_hash` (Django password hash), `purpose` email_verification|password_reset, `attempts` (max 5), `is_used`, `expires_at` (10 min), index (user, purpose, is_used). Constants `MAX_ATTEMPTS=5, EXPIRY_MINUTES=10, RESEND_COOLDOWN_SECONDS=60`.
- `StudentProfile(TimeStampedModel)`: OneToOne user (`related_name='profile'`); personal (`date_of_birth, gender, bio, instagram_handle, parent_phone`), academic (`grade, school, coaching, stream, board, medium, target_year`), location (`city, state, admission_number, batch_section`), prefs (`daily_study_goal_minutes` 60, `preferred_study_time` morning|afternoon|evening|night), denormalised stats (`total_xp, current_level, total_questions_attempted, total_correct_answers, total_study_time_minutes`). `add_xp()` / `calculate_level()` (100 XP for L1->L2, each next level x1.5), `overall_accuracy`, `xp_for_next_level`. Created for EVERY user (admins/instructors/superusers too) by signal.
- `GuardianConsent(TimeStampedModel)`: OneToOne user; tenant FK declared explicitly; guardian_name/email/phone, `relationship`; `status` pending|granted|withdrawn; `token_hash` (sha256, unique); `expires_at` (24 h); `email_verified_at`, `granted_at`, `withdrawn_at`; `consent_version` ('1.0'), `consent_text_hash`, `verification_method` (default `verified_email_declaration`).
- `CourseEnrollment(TimeStampedModel)`: FK `student` (StudentProfile), FK `course` (exams.Course); `status` pending|approved|rejected (default pending); `is_active`; `enrolled_at`; `reviewed_at`, `reviewed_by` (User SET_NULL), `rejection_reason`; `course_xp`, `course_rank`, `target_score`, `target_rank`. Unique `(student, course)`. "Usable access" everywhere = `status='approved' AND is_active=True`.
- Tenant scoping: `User.tenant` is authoritative; `StudentProfile/CourseEnrollment.tenant` (inherited, nullable) is filled by signal/`TenantAwareViewSet` but queries here scope through `user__tenant` / `student__user__tenant`.

## API (mounted at `/api/v1/auth/`; X-Tenant-ID required for all)
| Route | View | Permission / notes |
|---|---|---|
| `login/` | `CustomTokenObtainPairView` | AllowAny (anon throttle 100/h); tenant-scoped email+password; blocked if tenant frozen/suspended; returns `{access, refresh, user}` |
| `refresh/` | simplejwt `TokenRefreshView` | not tenant-aware itself; bypasses tenant-suspension block |
| `register/` | `RegisterView` | AllowAny; student quota check; returns 201 with `requires_email_verification`, `requires_guardian_consent`, `guardian_email_sent`, `user` |
| `verify-email/`, `resend-otp/` | `VerifyEmailView`, `ResendOTPView` | AllowAny; generic responses; 429 on cooldown |
| `password/forgot/`, `password/reset/` | `PasswordResetRequestView`, `PasswordResetConfirmView` | AllowAny |
| `password/change/` | `PasswordChangeView` | authenticated |
| `guardian-consent/<token>/` | `GuardianConsentView` | AllowAny GET (page data, masked student email) / POST (grant) |
| `guardian-consent/status/`, `guardian-consent/resend/`, `compliance-status/` | status / resend / `ExistingStudentComplianceView` | authenticated; compliance POST `action=save_date_of_birth` or `request_guardian_approval` |
| `user/`, `profile/` | `UserView`, `ProfileView` (RetrieveUpdate) | authenticated; profile nests user for update |
| `onboarding/` | `OnboardingView` | authenticated; saves study goals only, sets `is_onboarded` (course selection is NOT part of onboarding) |
| `enrollments/`, `enrollments/<uuid>/` | `CourseEnrollmentListView`, `CourseEnrollmentDetailView` | authenticated; student requests enrolment: course must be in request tenant and not `is_hidden`; mode from `tenant.enroll_mode_for(course)` => `payment` returns 402 `payment_required`, `self` auto-approves, else pending (+admin notification); re-request allowed after rejection |
| `tenant-students/` | `TenantStudentViewSet` (router) | `IsAuthenticated + IsTenantAdmin`; pagination 100 (max 5000); search/order; filters `?role&status=active or suspended&course (alias primary_course)` |
| `tenant-students/<id>/` actions | `course-progress` (GET list), `assign-courses`, `remove-course`, `reset-password`, `reset_progress`, `toggle_status` | admin only |
| `enrollment-requests/` | `TenantEnrollmentRequestViewSet` (GET/POST only) | admin; `?status=`; actions `approve`, `reject` (`reason`) |

Notes on `tenant-students`: `create` makes a `student` or `instructor` account (never `admin`), generates a temp password, sets `is_email_verified=True` (skips OTP), assigns courses (approved immediately), emails credentials via `notifications.services.on_student_account_created`; temp password returned in the response ONLY if the email failed. Student quota enforced (instructors not counted). `reset-password` refuses to reset another admin. `toggle_status` flips `User.is_suspended` for any user except self (can suspend admins/instructors). `reset_progress` zeroes profile counters and deletes analytics rows (daily_activities, topic_masteries, subject_performances, streaks, weekly_reports, study_sessions) but keeps quiz attempts.

## Business logic
- `users/signals.py`: `post_save(User)` creates `StudentProfile(tenant=user.tenant)` when created; second receiver re-saves the profile on EVERY user save (extra write, bumps `updated_at`).
- `users/emails.py`: OTP generation/verification (`create_and_send_otp`, `verify_otp`, `can_resend`), `generate_temp_password` (CSPRNG, avoids ambiguous glyphs), branded OTP email with plain-text fallback.
- `users/guardian_consent.py`: `guardian_consent_state(user, mask_email=False)` -> status one of `not_required`, `date_of_birth_required`, `guardian_details_required`, `guardian_approval_pending`, `compliant`; applies only to students whose tenant has guardian consent enabled and who are < 18.
- `users/views.py` helpers: `_issue_guardian_consent` (token mint, 24 h expiry, tenant-branded email, origin via `notifications.emails.tenant_frontend_origin`), `_guardian_consent_text`, `TenantStudentViewSet._assign_courses`.
- `users/authentication.py`: `RegistrationAwareJWTAuthentication` is a no-op subclass kept for compatibility.
- Serializers: `CustomTokenObtainPairSerializer` (tenant-scoped login; claims email/name/is_onboarded/is_suspended), `UserRegistrationSerializer` (honours tenant registration schema; guardian fields required for minors), `AdminStudentCreateSerializer`, `AdminAssignCourseSerializer`, `AdminEnrollmentRequestSerializer`, `StudentProfileSerializer` (includes `enrolled_courses`, `guardian_consent` state), `CourseEnrollmentSerializer`.
- No Celery tasks or management commands in this app.

## Integrations / settings / env vars / feature flags
- `SIMPLE_JWT` (365 d access, 730 d refresh), `REST_FRAMEWORK` auth class, throttles (anon 100/h), `EMAIL_PROVIDER`/`EMAIL_BACKEND`, `DEFAULT_FROM_EMAIL`, `FRONTEND_URL`, tenant `allowed_origins`.
- Tenant flags: `registration_settings` (fields + guardian_consent), `request_enrollment_free/paid`, `max_students` quota.

## Cross-app dependencies
- Imports: `core.models.TimeStampedModel`, `core.permissions.IsTenantAdmin`, `core.views.TenantAwareViewSet`, `exams.models.Course`, `notifications.services` (on_enrollment_requested/approved/rejected, on_course_assigned, on_student_account_created, on_credentials_reset), `notifications.emails` (branded email, frontend origin), `certificates.bulk_progress.bulk_course_progress` (roster progress).
- Imported by: all apps use `users.StudentProfile` / `User` (`request.user.profile`), `CourseEnrollment` for access checks (`exams.access`, content, quiz, etc.), `core.superadmin_*` (user admin actions), `analytics` (reset_progress related names), `gamification` (XP).

## Tests
- `users/tests_admin_provisioning.py`: admin student creation (generated password emailed, duplicate email, cross-tenant course, no-email returns password), assign courses/approve pending, non-admin forbidden, reset password (cannot reset another admin), cannot create an admin account, tenant isolation, remove course; roster `course-progress` percentages + constant query count + tenant scoping.
- `users/tests_otp_email.py`: OTP email uses tenant branding (name, sender display name, HTML + code, platform fallback).
- `users/tests_registration_consent.py`: registration settings defaults, guardian consent forced DOB, underage flow, consent expiry, existing-student compliance reminders (non-blocking), admin payload includes consent state, change guardian email, guardian approval link origin rules (first-party, other tenant, configured, untrusted fallback, missing origin => no user created), neutral brand for platform-named tenant.

## Gotchas / non-obvious conventions / risks
- Email uniqueness is per tenant; login/OTP lookups use exact `email=` (case-sensitive) while registration/provisioning check `iexact` (provisioning lower-cases; registration stores `normalize_email` which only lower-cases the domain). A user registering "Foo@x.com" cannot log in with "foo@x.com".
- JWT access tokens last 1 year; no logout route exists in `users/urls.py` even though `/api/v1/auth/logout/` is whitelisted in middleware paths; token blacklist app is not installed. Revocation = `is_active=False` or tenant/user suspension only.
- Unverified-email users and guardian-pending minors are not blocked by the API (frontend gating only; consent is "reminder-only").
- `CourseEnrollmentListView.create` is custom; `perform_create` (forces pending) is dead code. The detail view allows `PUT/PATCH/DELETE` of own enrollment: a student can DELETE their own enrollment; read-only fields prevent status changes.
- **Self-unsuspend risk**: `role` is NOT in `UserSerializer.fields` (so no self role escalation), but `is_active` and `is_suspended` ARE writable (read-only list is only `id, email, created_at, last_active, is_email_verified, guardian_consent_*`). `ProfileView` (`/auth/profile/`) is whitelisted in `BlockSuspendedUsersMiddleware` and its `StudentProfileSerializer.update` applies a nested `user` payload via `UserSerializer(partial=True)`, so a suspended user can PATCH `{"user": {"is_suspended": false}}` and lift their own suspension (`/auth/user/` is blocked by the middleware for suspended users, `/auth/profile/` is not). Derived from serializer/middleware code, not reproduced at runtime.
- `StudentProfile` rows exist for admins/instructors/superusers; the leaderboard uses `request.user.profile` for any role.
- `last_active` uses `auto_now` => it is "last saved", not true activity; the `save_student_profile` signal causes extra writes.
- `TenantStudentViewSet` inherits `TenantAwareViewSet` but overrides `get_queryset`; `perform_create` from the base is not used (custom `create`). `TenantEnrollmentRequestViewSet` is tenant-scoped via `student__user__tenant`.
- Admin `toggle_status` can suspend any user (including other admins); `reset_progress` and `toggle_status` do not check the profile's role.
- Migration `0012_grandfather_existing_users_verified` marks every pre-existing user as email-verified (data migration, noop reverse). `0009_rename_exam_to_course` renames models (historic). 15 migrations total.
- `seed_data` (core) creates sample users with a shared weak password - never run against production.

## Key files
- `backend/users/models.py` - User, EmailOTP, StudentProfile, GuardianConsent, CourseEnrollment.
- `backend/users/views.py` - auth, registration, consent, profile, roster, enrolment-request views.
- `backend/users/serializers.py` - login/registration/profile/admin serializers.
- `backend/users/urls.py` - route table (router for tenant-students and enrollment-requests).
- `backend/users/emails.py` - OTP + temp password + branded OTP email.
- `backend/users/guardian_consent.py` - consent state machine.
- `backend/users/signals.py` - auto StudentProfile creation.
- `backend/users/authentication.py` - JWT auth class used by DRF.
- `backend/users/admin.py` - Django admin (UserAdmin with tenant + role).
- `backend/users/tests_*.py` - tests above.
