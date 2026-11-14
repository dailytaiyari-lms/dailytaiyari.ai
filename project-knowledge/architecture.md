# Architecture (how the pieces fit)

> Deep detail: `backend/_foundation.md` (tenancy/auth/middleware), `backend/chatbot.md` (LLM layer), `infra/deployment-current.md` (runtime topology).

## Runtime topology (per environment)
```
Browser (tenant SPA on Netlify, VITE_TENANT_ID baked in) ──HTTPS──► nginx(443, Let's Encrypt)
      Header X-Tenant-ID + Bearer JWT                                  │
                                                                        ▼
                                                          web: gunicorn (gthread) + Django/DRF
                                                            │      │       │            │
                                         Azure PostgreSQL ◄─┘      │       │            └► Azure Blob (media, public URLs)
                                                                   ▼       ├► piston (code sandbox, HTTP, internal)
                                                              redis (broker)├► nbrunner (lab sandbox, HTTP, internal)
                                                                   │       └► LLM providers (outbound HTTPS), ACS Email, Zoom, PayU/Razorpay/Cashfree
                          ┌───────────────┬───────────────┬───────────────┐
                    celery-worker   celery-nbworker  celery-aiworker  celery-mediaworker     (+ celery-beat on UNDEPLOYED branches)
                    default queue   notebooks        aigen            media
```
Everything (web, 4 workers, nginx, redis, 2 sandboxes) runs on a **single VM via Docker Compose**; Postgres and Blob are managed Azure services.

## Multi-tenancy (shared DB, shared schema)
- `core.Tenant` row per customer. Clients send `X-Tenant-ID`; `TenantMiddleware` validates it, attaches `request.tenant`, and (for authenticated users) requires the JWT user's tenant == header tenant (`tenant_mismatch` 403; superusers exempt).
- Exempt path prefixes (no tenant): `/admin/`, `/api/v1/tenant/`, `/api/v1/platform/`, `/api/v1/superadmin/`, certificate verify, payment + Zoom webhooks, API docs, static/media.
- Isolation is **by convention**: models inherit `TimeStampedModel` (UUID pk, nullable `tenant` FK); viewsets filter `tenant=request.tenant` via `TenantAwareViewSet` or custom `get_queryset`. No global manager, so each new view must scope explicitly (several bugs exist — `known-issues.md`).
- Per-tenant config on the Tenant row: feature toggles/locks/labels (UI-only), advanced settings, registration schema, plan/billing/suspension (enforced in middleware), `allowed_origins` (dynamic CORS + email deep links), AI platform token grant, verified email domains.
- Per-tenant secrets in DB, Fernet-encrypted (`core/encryption.py`): payment gateways, Zoom, AI provider keys.
- Frontends: **one build per tenant** (`VITE_TENANT_ID`). Tenants on non-dailytaiyari domains need their origin added to `settings.CORS_ALLOWED_ORIGINS` (or tenant `allowed_origins`).

## Auth
Email+password → SimpleJWT (access 365 days!, refresh 730 days), custom `RegistrationAwareJWTAuthentication` on main. Email OTP verification via ACS; optional guardian consent for minors (tenant-configurable, non-blocking). `BlockSuspendedUsersMiddleware` for per-user suspension. No server-side token revocation.

## Async work (Celery on Redis; queue per workload)
| Queue / worker | Jobs | Time limits |
|---|---|---|
| default / `celery-worker` | coding judging (if `CODE_JUDGE_ASYNC`), notification fan-out (if `NOTIFICATIONS_ASYNC`), email | global 180s hard / 150s soft |
| `notebooks` / `celery-nbworker` | lab grading via nbrunner | 300s / 280s |
| `aigen` / `celery-aiworker` | course studio, mock builder, lab & hackathon AI generation | 1560s / 1500s (per task) |
| `media` / `celery-mediaworker` | ffmpeg remux + HLS transcode of uploaded video | env-driven (up to 6h); Redis `visibility_timeout` 7h |
Every async path **falls back to inline execution** if the broker is down (can exceed gunicorn's 120s). A missing worker = jobs stuck `queued` with no error. No periodic scheduler on main (cron/manual for management commands).

## AI layer (in `chatbot`, reused by coursegen, mockgen, notebooks.aigen, hackathons)
Provider resolution: tenant's own active key → platform grant (`TenantAIAllocation`, token + USD ceilings set by super-admin) → legacy env `OPENAI_API_KEY`. Usage metered in `AIUsageRecord`. Generation features follow **draft → preview → apply(confirm)**: the LLM only writes JSON onto a job row; real quiz/course rows are written by an explicit apply step. Web-request LLM timeout 90s (< gunicorn 120s); background 600s.

## Code execution
- Coding problems: web → `coding.services.run_against_cases` → Piston `/api/v2/execute` (python 3.12, java 15, gcc/c++ 10.2 installed by `piston-init`). Also used inline by mock tests and hackathons.
- Labs: student runs in browser (Pyodide, from jsDelivr CDN); on submit `notebooks.grade_submission` (nbrunner) is the authoritative grade only when `NOTEBOOKS_SERVER_GRADING=True`.
- Sandboxes publish no ports but sit on the default compose network (see known-issues).

## Media / video
Uploads → Blob; `content/tasks.py` remuxes (faststart) then `content/hls.py` builds adaptive HLS on the `media` queue; `optimize_videos` command backfills.

## Gamification / analytics data flow
Quiz/mock/content actions → `GamificationService.award_xp` (XP, levels, badges, DailyActivity) and `AnalyticsService` (TopicMastery, SubjectPerformance, streaks). On main both a `post_save` signal and explicit calls update mastery (double counting — see known-issues). UNDEPLOYED intelligence layer replaces this with an append-only `LearningEvent` log + recomputed state.

## Frontend architecture (exam-frontend)
Vite SPA, Zustand stores (auth, tenant, theme) + React Query, axios instance adds `Authorization` + `X-Tenant-ID`; route guards (`ProtectedRoute`, `AdminRoute`, `EditorRoute`, `FeatureRoute`); tenant branding/theme/feature flags loaded from `/api/v1/tenant/<uuid>/`; `inject-meta.mjs` writes per-tenant OG tags at build time. Details `frontend/exam-frontend.md`.
