# coursegen

Source of truth: `main` branch. Paths repo-relative. Frontend name: "Course Studio" / "topic studio" (tenant admin dashboard).

- **Purpose**
  - AI Course Builder. A tenant admin or instructor describes a course (typed or dictated); an LLM produces a reviewable JSON **draft** (course outline, per-topic material, or marketing copy). Nothing touches real course tables until an explicit, confirmed `apply`.
  - Three job kinds: `outline` (subjects -> chapters -> topics), `content` (per-topic notes + quiz + assignments + coding problems), `meta` (subtitle/description/highlights/refund policy). Jobs run on the Celery `aigen` queue and the client polls.

## Key models (`backend/coursegen/models.py`)
Only one model, `CourseGenerationJob(TimeStampedModel)` (UUID pk, nullable `tenant`):
- `created_by`, `applied_by` -> `users.User` (SET_NULL); `course` -> `exams.Course` (CASCADE; null for an outline that creates a brand-new course).
- `kind`: `outline` | `content` | `meta`. `input_mode`: `text` | `voice` (voice = dictated text; audio itself is never stored).
- `prompt` (<=8000 chars via serializer), `options` JSON (knobs: `topics_per_chapter`, `chapters_per_subject`, `questions_per_quiz`, `materials` list, `mode` replace|add, `depth`, `language`, `publish_immediately`, `batch_size`, assignment/coding settings; content jobs also store `topics_snapshot` = resolved topics so regenerate needs no re-authorisation).
- `provider`, `model`: what the admin picked; after a run they are overwritten with the actual provider (`'platform'` when platform-billed) and model.
- `status` enum: `pending -> generating -> preview -> applied`, plus `failed`, `discarded`. `RUNNABLE_STATUSES = (pending, preview, failed)`. `is_reviewable` = `preview` (the only status `apply`, edit and refine accept). `is_running` = pending|generating (UI polls while true).
- `draft` JSON (shape per kind, see `schema.py`), `revisions` JSON (audit trail, capped to last 25 entries), `error`.
- Metering copy on the row: `prompt_tokens`, `completion_tokens`, `total_tokens`, `estimated_cost_usd`, `generation_ms` (accumulated across refines).
- `applied_at`, `applied_summary` JSON (counts + ids created).
- Indexes: (tenant,status), (course,kind). No unique constraints. Migrations 0001, 0002 (kind choices widened for `meta`).

## API
Mounted at `/api/v1/tenant-admin/course-ai/` (`backend/coursegen/urls.py`). All views extend `_StudioView`: `IsAuthenticated` + `core.permissions.IsCourseEditor` (role `admin` or `instructor`). Tenant comes from `request.tenant` (TenantMiddleware via `X-Tenant-ID`). Instructors are limited to `user.instructing_courses` and to jobs on those courses (or their own new-course jobs); only `admin` may create new courses (403 otherwise).

| Route | View | Notes |
|---|---|---|
| `GET options/` | `StudioOptionsView` | composer data: `is_ready`, `providers` (`generation.available_models`), editable courses, limits, material types, coding languages (from `coding.languages`), defaults, `async_generation`, `not_ready_reason`. |
| `GET health/` | `studio_health` | cheap readiness probe (`is_ready`, `provider_count`). |
| `GET courses/<uuid>/tree/` | `CourseTreeView` | course tree with per-topic `has_notes/quiz/assignment/coding/notebook` flags. |
| `GET courses/<uuid>/topics/<uuid>/material/` | `TopicMaterialView` | inventory of existing material for a topic (`material.topic_material`). |
| `POST transcribe/` | `TranscribeView` | audio (<=25 MB) forwarded to the tenant's own OpenAI/Groq/custom provider `/audio/transcriptions` (models `whisper-1`, Groq `whisper-large-v3-turbo`). Uses web `READ_TIMEOUT`. |
| `GET/POST jobs/` | `JobListCreateView` | list filters: `course`, `kind`, `status` (`open` or comma list), `topic` (matches content jobs by `topics_snapshot` in Python); paginated 20/page (max 100). POST validates, creates job, resolves topics (max 12 per content job), enqueues; returns **202** (queued), 201 (inline done) or 502 (inline failed). |
| `GET/PATCH/DELETE jobs/<id>/` | `JobDetailView` | PATCH = admin hand-edit of draft (only in `preview`, re-normalised through `schema`); 409 otherwise. |
| `POST jobs/<id>/refine/` | `JobRefineView` | natural-language revision (`instruction` <=4000 chars); only from `preview`. |
| `POST jobs/<id>/regenerate/` | `JobRegenerateView` | retry; only `failed` or `pending` jobs. |
| `POST jobs/<id>/apply/` | `JobApplyView` | the **only writer**. Requires `confirm=true`, status `preview`; optional `selection` (`subjects`/`chapters`/`topics`/`fields` code lists). 400 on `ApplyError`. |
| `POST jobs/<id>/discard/` | `JobDiscardView` | marks `discarded`; applied jobs cannot be discarded. |

## Business logic
- **Celery** (`backend/coursegen/tasks.py`): `coursegen.generate` -> `run_generation_job(job_id, mode='generate'|'refine', instruction, topics)`, `queue='aigen'`, `max_retries=0`, **`soft_time_limit=1500`, `time_limit=1560`** (task-level override of the global `CELERY_TASK_TIME_LIMIT=180` / soft 150). Claims the job atomically (`UPDATE ... WHERE status IN allowed`): generate needs pending|failed, refine needs preview; a redelivery of an already-claimed job is a no-op.
- Worker service in `backend/docker-compose.yml`: `celery-aiworker` (`--queues=aigen`, concurrency `CELERY_AI_CONCURRENCY` default 4). The default `celery-worker` has no `--queues` flag and only serves the default queue, so **if `celery-aiworker` is down, jobs stay `pending` forever** (no error).
- `_enqueue()` in `views.py`: if `COURSEGEN_ASYNC` is true it calls `.delay`; on any broker exception it logs and **runs the generation inline in the web request** (can take minutes, bounded by gunicorn timeout 120s and web `AI_READ_TIMEOUT` 90s). `COURSEGEN_ASYNC=False` forces inline.
- `generation.py`:
  - `available_models(tenant)`: every configured tenant provider (with default + catalogue suggestions) plus a synthetic `provider: 'platform'` entry ("Included DailyTaiyari allowance") when the platform grant is usable (only granted/selectable models) or the legacy env-key grant applies.
  - `resolve_for_admin(tenant, provider, model, max_tokens, temperature)`: honours the admin's chosen provider/model for tenant keys (any model string); for `platform` the model must be in the grant. Forces `max_tokens` (outline 6000, content/refine 8000, meta 4000) and temperature 0.4 default.
  - `_check_budget(tenant)`: refuses to start when tenant-source token usage this month >= `AISettings.monthly_token_budget`. Only checked once at job start. Also respects `AISettings.is_enabled`.
  - Content jobs batch topics in groups of 3 (`CONTENT_BATCH_SIZE`, overridable by `options.batch_size`); one failed batch is recorded in `draft.partial_failures` and does not discard successful batches. Only if every batch fails does the job fail.
  - `extract_json()` tolerates fenced JSON, preambles, trailing commas, and **repairs truncated output** (closes open strings/brackets, trims back to last clean boundary).
  - `_call()` wraps `chatbot.providers.complete`, meters each call to `AIUsageRecord` with `feature='coursegen'` (`chatbot.resolver.record_usage`), approximates tokens as chars/4 when the provider omits usage.
  - `run_job` / `apply_refinement`: always end in `preview` or `failed` (a failed refine restores `preview` with the old draft and an error message). Unexpected exceptions are converted to a generic failure message.
- `schema.py`: normalisers that enforce draft structure on **both** LLM output and admin edits: unique slug codes, clamped lengths, enum validation against real model choices (`Course.COURSE_TYPES`, `Topic.DIFFICULTY_CHOICES`, `Question.DIFFICULTY_CHOICES`, etc.), quiz questions need valid correct option, coding problems need test cases, languages limited to `coding.languages.LANGUAGE_KEYS`, only requested material types are kept. Ceilings: 12 subjects, 30 chapters/subject, 30 topics/chapter, 12 topics/content job, 20 questions/quiz, 60 blocks/note, 5 assignments and 5 coding problems per topic, 15 test cases.
- `notehtml.py`: LLM returns typed **blocks** (lead, heading, paragraph, bullets, numbers, code, callout, table, quote, divider); HTML is rendered server-side (escaped, house style, accent colour) so notes look hand-authored and client HTML is never trusted. `prompts.py` holds system/user prompts for outline/content/meta/refine (`SYSTEM_PROMPTS[kind]`).
- `apply.py` (`apply_draft(job, user, selection)`; all appliers `@transaction.atomic`):
  - `apply_outline`: creates/extends `Course` (new courses start `status='coming_soon'`, `code` made unique **platform-wide**, gated by `tenant.can_add('courses')`), `Subject`, `Chapter`, `Topic`, `ChapterTopic` via `get_or_create` on natural keys (idempotent; existing rows only get blank descriptions filled). Raises `ApplyError` if nothing new.
  - `apply_content`: per topic writes `Content` (notes; `content_type='notes'`, global-unique slug), `Quiz`+`Question`/`QuestionOption`/`QuizQuestion`, `Assignment`, `CodingProblem`+`TestCase` (`solve_mode='in_app'`). `options.mode`: `replace` (update in place) vs `add` (always new rows). **Never rewrites a quiz that has attempts, an assignment/coding problem that has submissions** (creates a new one, coding title gets " (new)"). Status `published` only if `options.publish_immediately`, else `draft`.
  - `apply_meta`: writes `subtitle`, `description` (HTML), `highlights`, `refund_policy` onto the course.
  - Sets `job.status=applied`, `applied_*`, revision entry.
- `material.py`: existing-material inventory for the API and for prompt context ("complement, don't repeat").
- No management commands, no signals.

## Integrations / settings / env vars
- `COURSEGEN_ASYNC` (default True), `AI_READ_TIMEOUT` (90, web), `AI_READ_TIMEOUT_BACKGROUND` (600, per LLM call inside the worker), `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `CELERY_AI_CONCURRENCY` (compose), global `CELERY_TASK_TIME_LIMIT=180`/`SOFT=150` (overridden to 1560/1500 here), `CELERY_TASK_ACKS_LATE=True`, `CELERY_BROKER_TRANSPORT_OPTIONS.visibility_timeout` (`CELERY_VISIBILITY_TIMEOUT`, 25200).
- LLM access only through `backend/chatbot` (tenant BYO key, platform grant, or legacy `OPENAI_API_KEY`). Needs Redis + `celery-aiworker` to be asynchronous.

## Cross-app dependencies
- Imports `chatbot` (resolver, providers, models), `exams` (Course/Subject/Chapter/Topic/ChapterTopic), `content` (Content), `quiz` (Quiz/Question), `assignments` (Assignment), `coding` (CodingProblem/TestCase/languages), `notebooks` (Notebook for tree flags), `core.permissions`.
- Imported by: `notebooks.aigen.generation` reuses `coursegen.generation` helpers (`GenerationError`, `_Meter`, `_check_budget`, `available_models`, `extract_json`, `resolve_for_admin`). Changing signatures there breaks notebook generation. `mockgen` is a sibling feature with the same job/draft/apply pattern.

## Tests
`backend/coursegen/tests.py` (~930 lines, Django TestCase; the LLM is mocked): generation never writes course rows; apply requires `confirm`, cannot apply twice or after discard, selection semantics (empty selection writes nothing); content apply (note + quiz, re-apply updates not duplicates, quizzes with attempts untouched); draft-edit re-normalisation; tenant/instructor scoping (cross-tenant jobs hidden, instructors cannot create courses/unassigned course jobs, foreign topics rejected); studio options/health/tree; normaliser edge cases (escaping, invalid options, unique codes, enums, loose model output); rich material (assignments, coding) apply in replace/add modes; requested-materials enforcement; async behaviour (202 pending job, topic snapshot, broker outage falls back inline, worker leaves job reviewable, non-runnable job skipped, regenerate, failed refine preserves draft); topic job visibility/filtering.

## Gotchas / tech debt / risks
- **Stuck `generating` jobs**: a hard kill at `time_limit=1560`s, OOM, or worker crash leaves the row in `generating`. A redelivered message (acks_late + visibility timeout 7h) is skipped because the claim only accepts pending/failed, and `regenerate` rejects `generating`. There is no reaper; fix by manual DB update or discard.
- Soft limit (1500s) can be hit by large multi-batch content jobs on slow models: each LLM call may take up to 600s, 4 batches would already exceed it. A `SoftTimeLimitExceeded` is caught by the generic `except Exception` and the job becomes `failed` with a generic message (partial drafts lost).
- `CourseGenerationJob.estimated_cost_usd` is computed in `_store_result` with `estimate_cost_usd(model, usage)` **without** the platform model, so it uses the built-in table (which mis-prices `-mini` models, see chatbot.md) rather than the super-admin price list; the authoritative number is `AIUsageRecord`.
- The monthly token budget is only checked at job start, and platform ceiling at provider resolve; a large job can overshoot.
- Inline fallback (`_enqueue` on broker error) blocks a web thread for minutes; gunicorn `timeout=120` may kill it, leaving a `generating` row.
- `Course.code` and `Content.slug` uniqueness checks query across all tenants (global namespace); codes may therefore get numeric suffixes even for a tenant's first course.
- `TranscribeView` posts to the tenant-configured `base_url` (SSRF surface, same as chatbot providers) and the provider-must-be-OpenAI/Groq/custom rule is the only gate.
- `_StudioView.tenant` uses `request.tenant` (middleware) rather than `chatbot.tenancy.request_tenant`; relies on `TenantMiddleware` rejecting cross-tenant headers.
- The `topic=` job filter loads all content jobs of the tenant into Python (JSON field not indexed).
- Draft HTML is re-rendered server-side on apply (`render_blocks`); do not accept raw HTML from drafts.

## Key files
- `backend/coursegen/models.py` - `CourseGenerationJob` + status machine.
- `backend/coursegen/views.py` - studio API, `_enqueue` async/inline logic, transcription.
- `backend/coursegen/tasks.py` - `coursegen.generate` Celery task (queue `aigen`).
- `backend/coursegen/generation.py` - provider/model selection, JSON extraction/repair, LLM calls, metering, job orchestration.
- `backend/coursegen/schema.py` - draft normalisers, limits, `draft_summary`.
- `backend/coursegen/prompts.py` - system/user prompts and `requested_materials`.
- `backend/coursegen/apply.py` - the only code that writes course tables from a draft.
- `backend/coursegen/notehtml.py` - block-to-HTML renderer. `backend/coursegen/material.py` - existing material inventory.
- `backend/coursegen/serializers.py`, `backend/coursegen/urls.py`, `backend/coursegen/tests.py`.
