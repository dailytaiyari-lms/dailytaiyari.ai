# mockgen

Source: `main`, `backend/mockgen/`. Verified from code unless marked "unverified".

- **Purpose**: AI Mock Test Builder ("Mock Studio") for tenant admins. An LLM produces a *draft* paper (JSON) stored on a job row; the admin reviews / edits / refines it; only an explicit confirmed `apply` writes real `quiz.MockTest` + `quiz.MockTestItem` rows. Also supports "Modify with AI" on any existing mock test (hand-made or generated).
- Core invariant: **generation never writes to quiz tables**. Statuses move forward only: `pending -> generating -> preview -> applied` (or `failed`, `discarded`). `apply` is accepted only from `preview`, so a draft cannot be written twice.

## Key models (`backend/mockgen/models.py`, single migration `0001_initial`)
- `MockTestGenerationJob(TimeStampedModel)` (tenant = nullable base FK, set by views; indexes `(tenant,status)`, `(mock_test,kind)`):
  - `kind` create | modify; `status` pending/generating/preview/applied/failed/discarded (`RUNNING_STATUSES` = pending, generating; `is_reviewable` = preview).
  - `created_by` (User, SET_NULL), `mock_test` (quiz.MockTest, CASCADE, null; set for modify jobs, back-filled on apply of create jobs), `course` (exams.Course, SET_NULL, syllabus grounding).
  - `prompt`, `input_mode` text|voice, `options` JSON (blueprint, sections, syllabus, topic_ids, course_ids, intent, target_keys, add_blueprint, apply_mode replace|append, publish_immediately, language, difficulty, duration/marks/negative_marking/result_visibility/max_attempts defaults).
  - `provider`, `model` (stored as `'platform'` when platform-provided key), token counters, `estimated_cost_usd`, `generation_ms`.
  - `draft` JSON (normalised paper), `revisions` JSON (audit trail, last 25), `error`, `applied_at`, `applied_by`, `applied_summary`.
- No other tables. Draft shape (`schema.normalize_mock`): `{test:{title,description,duration_minutes,negative_marking,is_free,result_visibility,fullscreen_required,max_attempts}, sections:[{name,description}], items:[{key,item_type,section,question_text,explanation,marks,negative_marks,difficulty,concept,options|numerical_*|max_words/rubric/model_answer|allowed_languages/starter_code/coding_test_cases/time_limit_ms/memory_limit_mb,order,include}], stats, partial_failures?}`.

## API (prefix `/api/v1/tenant-admin/mock-ai/`, `backend/mockgen/urls.py`)
All views extend `_StudioView(APIView)` with `permission_classes = [IsAuthenticated, IsTenantAdmin]` (role `admin` only; instructors are blocked, test-covered). Everything filtered by `request.tenant`.

| Route | View | Behaviour |
|---|---|---|
| `GET options/` | `StudioOptionsView` | composer data: models available, `is_ready`, courses, item types, coding languages, limits, defaults |
| `GET health/` | `studio_health` | `{is_ready, provider_count}` |
| `GET courses/<uuid>/syllabus/` | `CourseSyllabusView` | subject -> chapter -> topic tree |
| `GET mock-tests/<uuid>/snapshot/` | `MockTestSnapshotView` | existing paper rendered as a draft (keys = `MockTestItem.id`) |
| `GET/POST jobs/` | `JobListCreateView` | list (filters `mock_test`, `kind`, `status=open|running|csv`; page 20, max 100); POST creates job and enqueues (202 queued, 201 inline OK, 502 inline failure) |
| `GET/PATCH/DELETE jobs/<id>/` | `JobDetailView` | PATCH = admin hand-edit, re-normalised, only in `preview` (409 otherwise) |
| `POST jobs/<id>/refine/` | `JobRefineView` | `{instruction}` (3-4000 chars), only in `preview` |
| `POST jobs/<id>/regenerate/` | `JobRegenerateView` | allowed from failed/pending/preview |
| `POST jobs/<id>/apply/` | `JobApplyView` | the only writer; body `{confirm: true, selection: {items: [keys]}}`; `selection.items` missing = all, present-but-empty = none |
| `POST jobs/<id>/discard/` | `JobDiscardView` | 409 if already applied |

Request limits (`schema.py`): `MAX_ITEMS_PER_REQUEST=60`, `MAX_ITEMS_PER_TEST=100`, `MAX_SECTIONS=10`, `MAX_OPTIONS_PER_ITEM=8`, `MAX_TEST_CASES=15`, `MAX_DURATION_MINUTES=600`; prompt max 8000 chars.

## Business logic
- **Pipeline** (`generation.py`): `run_job` -> `generate_paper` (create) or `generate_modification` (modify). Create: blueprint entries split by `_batches` (8 questions per LLM call, 2 for coding), each batch call = `_call(...)` with the system prompt + already-written stems for dedupe; per-batch failure is recorded in `draft['partial_failures']` and does not discard other batches; fails only when zero items. `syllabus_text_for` grounds prompt in admin text (6000 chars) + course tree (optionally narrowed by `topic_ids`, capped ~200 lines). `refine`/`apply_refinement` regenerate the whole draft with an instruction; on failure the previous draft is kept and the job returns to `preview` with an error. Prompt JSON truncated at 60000 chars.
- **Reused from coursegen** (`coursegen.generation`): `GenerationError`, `_Meter`, `_call`, `_check_budget`, `available_models`, `extract_json`, `resolve_for_admin`. Provider/budget resolution, metering and usage logging are shared with the course builder; usage is billed with `AIUsageRecord.FEATURE_MOCKGEN` (`chatbot.models`). `chatbot.resolver.get_ai_settings(tenant).is_enabled` gates the studio.
- **Schema normaliser** (`schema.py`): guarantees structurally valid items (MCQ >= 2 distinct options and exactly one correct, multi >= 1; numerical has an answer; coding has >= 1 runnable test case in a language from `coding.languages.LANGUAGE_KEYS`; marks clamped; negative marks zeroed when negative marking off; unique stable `key`s; section indices contiguous). Runs again on every admin PATCH. `merge_items` merges batches with a cap.
- **Apply** (`apply.py`, `@transaction.atomic`): create -> new `MockTest` (status `draft` unless `options.publish_immediately`), `sections` annotated with counts/marks, `courses` M2M set from `options.course_ids` + `job.course` filtered to the tenant, items written as `MockTestItem`, `recompute_mock_total`. Modify -> updates items whose draft `key` == existing item id, creates new ones, in `replace` mode deletes unmatched items **except those that already have `MockTestAnswer` rows**; `append` keeps untouched ones; mock-level fields (title, duration, visibility, max_attempts...) are overwritten from the draft. Bank questions (`MockTestQuestion`) are never touched.
- **Celery task** `mockgen.generate` (`tasks.py`): queue `aigen`, `max_retries=0`, `soft_time_limit=1500`, `time_limit=1560`. Claims job atomically (`filter(status in pending/failed).update(status=generating)`) so redelivery cannot double-run. Always catches exceptions -> job `failed` with generic message. `mode='refine'` calls `apply_refinement`.
- `_enqueue` (views): if `MOCKGEN_ASYNC` -> set status `pending`, `.delay()`; if broker enqueue throws, falls back to running inline in the request thread (can hit gunicorn timeout; `AI_READ_TIMEOUT` default 90s).
- No management commands, no signals.

## Integrations / settings / env vars
- `MOCKGEN_ASYNC` (default True; falls back to `COURSEGEN_ASYNC`), `COURSEGEN_ASYNC`, `AI_READ_TIMEOUT` (web, 90), `AI_READ_TIMEOUT_BACKGROUND` (celery, 600), `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `CELERY_VISIBILITY_TIMEOUT`.
- Requires a Celery worker consuming queue **`aigen`** (docker-compose defines a dedicated worker `--queues=aigen`, shared with coursegen, hackathons, notebooks AI gen).
- AI providers are tenant-configured under "AI Features" (chatbot app); platform fallback key supported; budget check via coursegen `_check_budget`.
- Coding validation uses `coding.languages`.

## Cross-app dependencies
- Imports: `quiz.models` (MockTest, MockTestItem, MockTestAnswer, MockTestQuestion via admin), `quiz.admin_views.recompute_mock_total`, `exams.models` (Course, subjects/chapters/chapter_topics), `chatbot` (resolver, models AIUsageRecord, providers.estimate_cost_usd), `coursegen.generation`, `coding.languages`, `core.permissions.IsTenantAdmin`, `core.models.TimeStampedModel`, `users.User`.
- Imported by: none (mounted only in `dailytaiyari/urls.py`). Frontend admin Mock Studio calls these endpoints (unverified in this pass).

## Tests (`backend/mockgen/tests.py`, ~677 lines; LLM stubbed, `MOCKGEN_ASYNC=False` base class)
- GenerationNeverWritesTests (no quiz rows from generation, blueprint required), ApplyTests (confirm required, selection semantics, empty selection writes nothing, no double apply, publish_immediately), ModifyWithAITests (in-place update, never deletes answered items, append mode, intent validation, scoped targets reach prompt), ScopingTests (other tenant cannot see job / modify mock; instructor forbidden), DraftEditingTests, VisibleProgressTests, NormaliserTests, AsyncGenerationTests (202 queue, refine reports running, broker outage inline fallback, worker claim semantics).

## Gotchas / risks
- **An applied paper with no course selected is open to ALL students in the tenant** (quiz access rule: no `course` and no `courses` = tenant-wide). Admins must pick `course_ids` in the composer; `apply` does not warn.
- Apply by default creates a **draft** mock test; set `options.publish_immediately` to publish. Modify apply with `publish_immediately` sets status published.
- Modify apply overwrites mock-level settings (duration, `result_visibility`, `max_attempts`, `fullscreen_required`, `is_free`, `negative_marking`) with values from the draft's `test` object, which for modify is seeded from the existing test (`existing_test`) - an admin PATCH or model output that changes them takes effect on apply.
- Subjective/`needs_manual_grading` items produced by AI put attempts into `pending_manual` (XP deferred until admin finalizes). Preview warns via `AUTO_GRADED_TYPES`.
- Inline fallback when Celery/Redis is down runs multi-call LLM generation inside the HTTP request: likely to exceed gunicorn timeout for large papers.
- `regenerate` from `pending` can enqueue a second task, but the atomic claim makes the extra a no-op.
- Cost metering is accumulated on refine, overwritten on regenerate.
- A stuck `generating` job (worker killed hard) is never auto-recovered (the claim only accepts pending/failed); user must `regenerate` (allowed from pending/failed/preview only, NOT from generating) - unverified recovery path.
- Item `key` is the DB id for snapshot-derived drafts; custom keys from LLM are slugified and uniquified.

## Key files
- `backend/mockgen/views.py` - endpoints, `_enqueue` (async + inline fallback).
- `backend/mockgen/generation.py` - batching, syllabus, generate/modify/refine, job lifecycle.
- `backend/mockgen/schema.py` - draft normalisation + limits.
- `backend/mockgen/apply.py` - the only writer into quiz tables; `draft_from_mock_test`.
- `backend/mockgen/prompts.py` - system/user prompts for create, modify, refine.
- `backend/mockgen/serializers.py` - request validation (`GenerateSerializer`, `ApplySerializer`, `MODIFY_INTENTS`).
- `backend/mockgen/tasks.py` - Celery task `mockgen.generate`.
- `backend/mockgen/models.py` - `MockTestGenerationJob`.
- `backend/mockgen/tests.py` - test suite.
