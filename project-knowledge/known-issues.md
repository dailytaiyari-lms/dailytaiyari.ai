# Known issues, risks & tech debt (as found by code reading — NOT runtime-verified)

> Source: parallel code review of `origin/main` @ 7287616. "unverified" = inferred from code, not reproduced. Each item names the app doc with detail.
> No secret values are recorded here. Severity is my triage (H/M/L) for planning, not a CVSS score. Verify before acting; some may already be mitigated on the VMs.

## HIGH — security / money / data integrity
| # | Area | Issue | Detail |
|---|---|---|---|
| H1 | payments | `VerifyOrderView` never checks the provider order/txn id in the payload equals the order's `provider_order_id`; a valid signature/payment for a cheap order can be replayed against another unpaid order → free enrolment. `mark_order_paid` also doesn't guard refunded/cancelled orders; no webhook replay protection; amounts never compared | `backend/payments.md` |
| H2 | exams | `/api/v1/courses/explorer/` (`TenantContentExplorerView`) has no tenant filter → any tenant admin sees every tenant's courses/subjects/chapters | `backend/exams.md` |
| H3 | users | `is_active`/`is_suspended` writable through `UserSerializer`; `/auth/profile/` is whitelisted for suspended users → a suspended user can probably un-suspend themselves (unverified) | `backend/users.md` |
| H4 | auth | JWT access = 365 d, refresh = 730 d; `token_blacklist` app not installed (blacklist setting is a no-op); no logout route → tokens cannot be revoked | `backend/_foundation.md` |
| H5 | community | `PostViewSet`/`CommentViewSet` lack update guards → any authenticated tenant user can PUT/PATCH others' posts/comments; `QuizAttemptViewSet` (AI quiz) has no tenant/visibility check | `backend/community.md` |
| H6 | chatbot/coursegen | SSRF: tenant admins can set arbitrary AI provider `base_url` (no validation); "test connection" echoes upstream errors; coursegen `TranscribeView` similar | `backend/chatbot.md` |
| H7 | notebooks | nbrunner sits on the default compose network (not `internal`) so student code can reach db/redis/internet (Redis has no auth); student code shares process/namespace with hidden tests → grading tamperable; `NOTEBOOKS_SERVER_GRADING` default False in settings (compose sets True) | `backend/notebooks.md` |
| H8 | quiz | correct answers exposed via `/quiz/mock-attempts/{id}/` & `/review/` regardless of `result_visibility`/`results_released`; `questions/{id}/?with_answer=1` leaks the key to any enrolled student | `backend/quiz.md` |
| H9 | defaults | `DEBUG` defaults True, `SECRET_KEY` insecure default, `FIELD_ENCRYPTION_KEY` empty → if unset in prod, tenant secrets keyed off `SECRET_KEY` (rotation silently breaks all stored gateway/AI/Zoom secrets because `decrypt()` returns '' on failure) | `infra/env-vars.md` |
| H10 | ops | Public Swagger/ReDoc in prod; public tenant config endpoint enumerable by UUID | `backend/_foundation.md` |

## MEDIUM — correctness / abuse
- **Analytics double/triple counting**: `quiz/signals.py` post_save + explicit submit calls both update `TopicMastery`; legacy mock also double-updates `SubjectPerformance`. Rich mock submit probably raises IntegrityError in the signal when `mock_test.course` is NULL (`SubjectPerformance.course` NOT NULL) (unverified). *(quiz.md, analytics.md — this is what the unmerged intelligence branch was designed to fix.)*
- **Two mock-test flows**: legacy ignores `max_attempts`/`start_deadline`/server timer; rich flow enforces them but skips DailyActivity/streaks/badges. A mock with no `course`/`courses` is open to the whole tenant (mockgen apply without `course_ids` → tenant-wide). `negative_marking`, availability window, rank/percentile never enforced/computed; `mcq_multi`/`match` never graded correct. *(quiz.md)*
- **Concurrency**: no locking on mock finalisation (double XP), coupon usage limits counted only when paid (can be exceeded), Piston submissions sequential per case (can exceed 150 s soft limit / 120 s gunicorn). *(quiz.md, marketing.md, coding.md)*
- **Cross-tenant validation gaps**: `AdminAssignmentSerializer`, admin Content serializer (`courses/subject/topic`), `ContentProgress.create` (any content UUID → XP), `BadgeViewSet` ignore tenant; `generate_daily_challenges` creates quizzes for every tenant×course pair. `Course.code` and `Content.slug` are **globally** unique (not per tenant). *(assignments.md, content.md, gamification.md)*
- **Tenant feature flags are UI-only** (no backend enforcement beyond plan quotas / suspension); `max_admins` never enforced; superadmin-created tenants get unlimited quotas and a trial that never expires. *(core.md)*
- **Uploads**: no type/size validation on `AdminImageUploadView`, resumes (jobs), landing images (5 MB only); extension taken from client; assignment files may be reachable at raw `/media/` URLs; video blob/HLS URLs not access-controlled. *(content.md, jobs.md, assignments.md)*
- **PayU** callback redirects to unverified `udf1` (open redirect); `return_url` never allow-listed; surl/furl built from request Host. **Zoom** webhook lacks timestamp freshness check. *(payments.md, liveclass.md)*
- **Open endpoints/rates**: public leads share one `platform_lead` throttle (20/h); quiz submit accepts any `question_id` (stat skew); AI-quiz correctness is client-asserted (XP capped 25/attempt, 75/day); study-timer heartbeat trusts client `elapsed_seconds` (daily-goal XP farmable). *(quiz.md, chatbot.md, analytics.md)*
- **Hardcoded personal email** is the code default of `PLATFORM_NOTIFICATION_EMAIL` (also repeated in `core/emails.py` and `seed_data.py`) → leads/notifications go there unless env set.
- `seed_data` is stale (no tenant, shared weak password) — never run on pre-prod/prod; `backend/deploy/README.md` documents a default super-admin credential.
- **Cost bug**: substring price lookup in `chatbot/providers.py` prices `gpt-4o-mini`, `gpt-4.1-mini/nano` as `gpt-4o`/`gpt-4.1` (over-estimate); `CourseGenerationJob.estimated_cost_usd` never uses platform prices. *(chatbot.md)*
- **Time zone**: analytics "today" uses UTC `timezone.now().date()` → day rolls at 05:30 IST despite `TIME_ZONE=Asia/Kolkata`. *(analytics.md)*
- Likely 500: `/gamification/badges/<id>/` (`.get()` after `.union()`); `ChallengeParticipation.is_completed` never set → challenge rewards unclaimable except via Django admin; badges/challenges are never seeded by migrations (production needs seeding). *(gamification.md)*

## OPERATIONAL (deploy-relevant)
- Celery workers are not restarted by `docker compose restart web` → version skew. Missing worker for a queue = silent `queued` forever; hard-killed jobs stay `generating/running` with no reaper.
- Async paths fall back to inline in the web request when broker is down (AI jobs → gunicorn 120 s kill).
- No scheduler on main: `send_birthday_greetings`, `generate_daily_challenges`, `sync_live_attendance`, `optimize_videos` rely on cron/manual; birthday sweep is also lazily triggered by notification polls.
- `NOTEBOOKS_ENABLED` is defined but read nowhere; `CODE_JUDGE_ASYNC` False by default; `NOTIFICATIONS_ASYNC` False by default (emails sent inline in requests).
- Per-process cache of tenant CORS allow-list lags up to 5 min unless `REDIS_URL` set; per-customer origins hardcoded in `settings.py`.
- `exams/urls.py` router collision (course detail at `''` may shadow `subjects|topics|chapters` list routes) (unverified).
- Superadmin frontend: lists capped at DRF `PAGE_SIZE=20` (sends `page_size=200`, ignored; never follows `next`) → tenants/users/audit rows >20 invisible; token refresh path lacks `X-Tenant-ID` and 403s (masked by 365-day tokens) — same latent bug in exam-frontend `api.js`.
- Frontend lint scripts declared with no ESLint config (exam, superadmin) → would fail; no frontend tests; lockfile generated on macOS (add `@rollup/rollup-linux-x64-gnu` optional dep pin present for Linux CI).
- Docs drift: wiki says `production` is ff-only (actually PR-merge commits), `notebooks` docstrings say queue `notebooks` for generation (it's `aigen`), landing "Book demo" dialogs only mounted on `/`, `zoom_start_url` exposed in admin serializer contrary to wiki.

## Migration notes
- Fresh DB gets a "Default Tenant" with a hardcoded UUID from `exams` migration 0006; `users` 0012 marks all pre-existing users email-verified; `quiz` 0007 backfills tenant onto Quiz/MockTest using the **first active tenant** as fallback (check before restoring dumps).
- No risky schema migrations found in apps reviewed; video-pipeline fields in `content` are nullable/defaulted.
