# hackathons

Source: branch `main`. **Wired in on main**: `'hackathons.apps.HackathonsConfig'` is in `INSTALLED_APPS` (backend/dailytaiyari/settings.py) and urls.py mounts `api/v1/hackathons/` (`hackathons.urls`) and `api/v1/tenant-admin/hackathon-ai/` (`hackathons.ai_urls`). Single migration `0001_initial`. Tenant feature flag `hackathons` ("Hackathons") exists in `core.Tenant.FEATURE_CHOICES` (UI-only; backend does not enforce it).

- **Purpose**: Standalone, multi-round competitions authored by tenant admins. Public event page; logged-in students register and progress through ordered rounds (quiz / coding / lab / project submission) with cut-off, top-N or manual qualification; admins grade, publish results, declare winners, broadcast announcements. Plus an **AI Hackathon Studio** (LLM drafts event brief, stage plan, or per-stage questions; admin reviews then explicitly applies).

## Key models (backend/hackathons/models.py; `TimeStampedModel`/`OrderedModel` => UUID pk + nullable `tenant`, which code always stamps)
| Model | Notes |
|---|---|
| `Hackathon` | `tenant` required; `title`, auto `slug` (title + 6 hex), branding (`thumbnail`, `banner`, `theme_color`), rich-HTML `description/rules/prizes_description/eligibility`, `faqs`/`tags` JSON, `mode` online/offline/hybrid, `difficulty`, `organizer_name`, `contact_email`, prize pool, timeline (`registration_opens_at`, `registration_deadline`, `starts_at`, `ends_at`), `max_participants`, toggles `show_registration_count`, `show_leaderboard`, `email_notifications`, `status` draft/published/completed/archived, `results_announced(_at)`, `related_courses` M2M, `created_by`, `views_count`. Derived `registration_open`, `registration_state` (not_open/opening_soon/open/full/closed). |
| `HackathonStage` | ordered round; `stage_type` quiz/coding/lab/submission; `status` draft/published/completed; window `starts_at/ends_at`; `duration_minutes`, `shuffle_items`, `max_attempts`; lab: `notebook`->`notebooks.Notebook`; submission: `allowed_file_types`, `max_file_mb`, `max_files`, `require_repo/demo/video_url`, `allow_resubmission`; progression `qualification_mode` manual/cutoff/top_n/all, `cutoff_score`, `top_n`, `max_score`, `results_published`. |
| `HackathonStageItem` | inline question: `item_type` mcq/mcq_multi/numerical/subjective/coding; marks/negative_marks; `options` JSON `[{text,image,is_correct}]`; numerical answer+tolerance; subjective rubric/model_answer (admin-only); coding: `allowed_languages`, `starter_code`, limits, `coding_test_cases` JSON (stdin/expected/points/is_sample). Mirrors `quiz.MockTestItem` semantics. |
| `HackathonRegistration` | `participant`->StudentProfile, contact/profile snapshot, `status` registered/withdrawn/disqualified, `total_score`, `final_rank`, `is_winner`, `winner_title`, `prize`, `admin_notes`. **unique_together (hackathon, participant)**. |
| `StageParticipation` | per (registration, stage), unique_together `[stage, registration]`; `status` locked/pending/in_progress/submitted/evaluated; `qualification` undecided/qualified/not_qualified; `attempt_number`, timestamps, `score`, `auto_score`, `override_score` (wins via `effective_score`), `needs_manual_grading`, `rank`, `feedback`. |
| `StageItemAnswer` | unique (participation, item); selected options / numerical / text / code+language / `coding_results`, marks, auto-graded flags. |
| `StageSubmission` (1:1 participation) + `StageSubmissionFile` | project deliverables: title/summary/repo/demo/video URLs, `is_late`; files in `hackathons/submissions/`. |
| `HackathonAnnouncement` | admin broadcast: audience all/active/qualified(stage)/winners, `send_email`, `recipients_count`. |
| `HackathonGenerationJob` | AI job: `kind` event/stages/stage_content; status pending/generating/preview/applied/failed/discarded (`RUNNABLE_STATUSES` pending/preview/failed); `draft` JSON, `revisions` log (last 25), token/cost metering, `applied_summary`. |

## API
Student `HackathonViewSet` (ReadOnly + actions; backend/hackathons/views.py; mount `/api/v1/hackathons/`, router at `''`). Queryset: tenant + `status in (published, completed)`. **AllowAny**: `list`, `retrieve`, `winners` (only if `results_announced`) (+ `stage_public` listed in `PUBLIC_ACTIONS` but no such action exists). `leaderboard` actually requires auth (not in `PUBLIC_ACTIONS`). Authenticated student actions: `register` (checks `registration_state`, seeds first published stage participation, sends confirmation), `withdraw`, `my-registrations`, `<id>/my-progress`, `stages/<sid>/` (detail), `stages/<sid>/start`, `stages/<sid>/run` (run code on sample cases only, nothing stored), `stages/<sid>/submit` (quiz/coding paper; grades inline), `stages/<sid>/submit-project` (multipart files + links), `stages/<sid>/sync-lab`, `submission-files/<fid>/download` (own files only). Round access gated by `grading.is_eligible_for` (round 1: any active registration; later rounds: `qualified` in the immediately preceding round).

Admin (`/api/v1/hackathons/admin/`, `IsTenantAdmin` = role admin only; backend/hackathons/admin_views.py): `hackathons/` CRUD + actions `stages` (GET/POST), `stages/reorder`, `registrations` (+ `registrations/export` CSV, PATCH `registrations/<reg_id>`), `overview`, `declare-winners`, `announcements` (GET/POST; sends immediately); `stages/` CRUD + `items` (GET/POST), `items/reorder`, `participants`, `qualify`, `publish-results`, `leaderboard`; `items/` CRUD; `participations/` (read) + `grade`; `submission-files/<id>/download`.

AI Studio (`/api/v1/tenant-admin/hackathon-ai/`, `IsAuthenticated + IsTenantAdmin`; backend/hackathons/ai_views.py): `options/`, `health/` (readiness: is any AI model available), `hackathons/<id>/stages/`, `jobs/` (list/create — produces a draft only), `jobs/<id>/` (GET poll / draft edit), `refine/`, `regenerate/`, `apply/` (the only call that writes hackathon tables; requires confirmed `preview` draft), `discard/`.

## Business logic
- `grading.py`: `build_paper` (never leaks answers), `grade_answer` (negative marking on wrong MCQ/numerical, proportional coding score via Piston `coding.services`, subjective deferred to manual), `recompute_participation`, `sync_lab_score` (reads `notebooks.NotebookCompletion` best score), `apply_qualification` (cutoff/top_n/all/manual; unlocks next round for qualifiers, ranks everyone, others `not_qualified`), `open_next_stage`, `recompute_totals`, `leaderboard`, `stage_stats`. `qualify` refuses while submissions need manual review unless `force=true`.
- `notify.py`: in-app `Notification` + branded email via `notifications.services._dispatch_email`; honours `Hackathon.email_notifications`; events: registered, stage opened, stage results, winners declared, results announced, admin announcement. All wrapped in `_safe`.
- AI: `generation.py` + `prompts.py` + `schema.py` (strict normaliser/HTML sanitiser, caps: 25 items/request, 200 items/stage, 10 stages) + `apply.py` (`apply_draft`). Provider/budget/metering reuse `coursegen.generation` and `chatbot.resolver` (tenant's AI provider keys live in `chatbot.AIProviderConfig` DB rows, or platform provider/allowance; feature id `AIUsageRecord.FEATURE_HACKATHONGEN`).
- Celery: `hackathons.generate` (`backend/hackathons/tasks.py`) on queue **`aigen`**, soft limit 1500s / hard 1560s, `max_retries=0`, atomic claim by status update (no double run). Enqueue is skipped/falls back to inline when `HACKATHONGEN_ASYNC` (not defined in settings.py) -> `COURSEGEN_ASYNC` (env, default True) is False or the broker is down. Requires the `celery-aiworker` service (`--queues=aigen`) in backend/docker-compose.yml.
- No signals; no management commands.

## Integrations / settings / env vars
- `COURSEGEN_ASYNC`/(`HACKATHONGEN_ASYNC`), Celery env `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `CELERY_AI_CONCURRENCY` (compose), `AI_READ_TIMEOUT`, `AI_READ_TIMEOUT_BACKGROUND`, `PISTON_URL` + `CODING_ENABLED` (code judging, `piston` service in compose), notebooks stack (`NOTEBOOKS_ENABLED`) for lab rounds, `FRONTEND_URL`/`BACKEND_PUBLIC_URL` for email deep links.
- Credentials: AI provider keys per tenant in DB (`chatbot` app), not here. No other external credentials.
- Uploaded media: thumbnails/banners/question images/submission files use default storage.

## Cross-app dependencies
Imports: `core` (TimeStampedModel, OrderedModel, IsTenantAdmin), `users` (StudentProfile, User), `exams.Course`, `notebooks` (Notebook, NotebookCompletion), `coding` (services, languages; Piston), `chatbot` (resolver, AIUsageRecord, AIProviderConfig), `coursegen.generation` (shared LLM helpers), `notifications` (Notification, emails, services). `notifications.Notification` has 5 hackathon types (registered/stage/result/winner/announcement). Frontend: `HackathonDetail.jsx`, `HackathonManager.jsx`, `HackathonBuilder.jsx`, `components/admin/hackathon/*`, `components/admin/hackathonAi/AIHackathonStudio.jsx`.

## Tests (backend/hackathons/tests.py, ~613 lines)
`PublicAccessTests` (anon browse, drafts hidden, anon cannot register, single registration, deadline, cross-tenant isolation), `RegistrationCountVisibilityTests`, `StageGatingTests`, `QualificationTests` (cutoff/top_n/manual/next-round unlock/scores hidden until published), `AutoGradingTests` (mcq, negative marking, numerical tolerance, no answer-key leak, computed max score), `AdminApiTests` (student blocked, create, rounds reorder, winners idempotent/public, qualify blocked by pending review), `AIStudioTests` (draft writes nothing, HTML sanitised, apply requires confirmation, students blocked). Not covered: file-upload constraints, coding judge path, lab sync, announcements, CSV export.

## Gotchas / risks
- Per-attempt `duration_minutes` is returned to the client but grep shows no server-side timer enforcement on `submit` — only the stage window (`ends_at`) and `status` are checked, so the quiz timer is client-side (unverified beyond grep of views/grading).
- Coding items are judged inline in the web request on `stage_submit` (Piston calls per test case); large papers can hit gunicorn timeouts; `run` endpoint is a code-execution amplifier for any registered student (no rate limiting seen).
- Submission uploads: extension allow-list and per-file size limit enforced in the view, not content sniffing; `max_files` counts only files in the current request. File download is `attachment` + `nosniff` + `no-store`.
- `PUBLIC_ACTIONS` lists a non-existent `stage_public` action; the public leaderboard endpoint is auth-only.
- Participants' own `registration.full_name/email` snapshots are used for emails (could differ from account).
- `Hackathon.views_count` is updated read-modify-write (`views_count + 1` computed in Python), racy.
- `registration_open` counts registrations per call (N queries on list pages).
- Announcement send is synchronous in the admin request (per-recipient email via `_dispatch_email`, async only when `NOTIFICATIONS_ASYNC`).
- Hackathon tenant flag not enforced server-side.

## Key files
- backend/hackathons/models.py — all models
- backend/hackathons/views.py — student API; backend/hackathons/serializers.py
- backend/hackathons/admin_views.py, admin_serializers.py — admin API
- backend/hackathons/grading.py — autograding, qualification, leaderboards
- backend/hackathons/notify.py — in-app + email notifications
- backend/hackathons/ai_views.py, ai_urls.py, ai_serializers.py, generation.py, prompts.py, schema.py, apply.py, tasks.py — AI studio
- backend/hackathons/urls.py — student + admin routers
- backend/hackathons/tests.py — tests
- backend/docker-compose.yml — `celery-aiworker` (queue `aigen`) needed for async generation
