# coding

Source of truth: `main` branch. Paths repo-relative.

- **Purpose**
  - Competitive-programming style coding problems authored under a Topic (like Assignment/Quiz placement). Students write code in Monaco, "Run" against sample cases, "Submit" for scored grading against all (sample + hidden) test cases. Code execution is delegated to a self-hosted **Piston** sandbox over HTTP.
  - `coding.services` is also the **shared judge engine** reused by mock tests (`quiz`) and hackathons for their inline coding items.
  - Problems can alternatively be "solved" on an external judge (LeetCode etc.) and self-reported.

## Key models (`backend/coding/models.py`)
| Model | Notes |
|---|---|
| `CodingProblem(OrderedModel)` | `tenant` (NOT NULL, related `coding_problems`), `course`, `subject?`, `topic`, `title`, `statement` (HTML/Markdown), `difficulty` easy/medium/hard, `allowed_languages` JSON (subset of language keys; empty = all), `starter_code` JSON `{lang: code}`, `time_limit_ms` (3000), `memory_limit_mb` (256), `max_marks`, `status` draft/published/archived (`is_open` = published), `solve_mode` `in_app` \| `external` \| `both`, `external_url` (required by the admin serializer when mode is external/both). |
| `TestCase(OrderedModel)` | `problem`, `stdin`, `expected_output`, `is_sample` (visible + runnable), `points`, `explanation`. Hidden cases = `is_sample False`. |
| `CodingSubmission(OrderedModel)` | `problem`, `student`, `language` (choices from `languages.py`), `source_code`, `status` `queued` \| `running` \| `done` \| `error` (default `done`), `results` JSON (per-case verdicts), `compile_output`, `passed_count/total_count/passed_points/total_points`, `marks` (scaled to `max_marks`), `submitted_at`. Index (problem, student). **`tenant` is not set on creation** (nullable inherited field stays NULL). |
| `CodingProblemCompletion(TimeStampedModel)` | One row per (problem, student) - UniqueConstraint `uniq_problem_student_completion`; `method` `in_app` \| `external`; tenant NOT NULL. External completions are reversible (row deleted); in-app solves are not. |

Migrations: 0001 initial, 0002 (`solve_mode`, `external_url`, completions), 0003 (queued/running status values). No management commands, no signals.

## API
Prefix `/api/v1/coding/` (`backend/coding/urls.py`).
- **Student** `CodingProblemViewSet` (`IsAuthenticated`, read-only + actions): list/retrieve published problems in the student's approved+active enrollments (`?topic=`). Detail exposes only sample cases, allowed languages, starter code. Actions:
  - `POST <id>/run/` - runs against samples (`reveal_io=True`) or a custom `stdin`; not stored; throttle scope `code_run` 120/hour; 503 on engine error.
  - `POST <id>/submit/` - throttle `code_submit` 120/hour. Validates language/source/test cases, creates a `queued` `CodingSubmission`, then **if `CODE_JUDGE_ASYNC`** enqueues `coding.grade_submission` and returns 202 (client polls); on broker failure or when sync, grades in-request and returns 201 (an engine failure in sync mode **deletes** the submission and returns 503).
  - `GET <id>/submissions/<uuid>/` (poll, owner-scoped, not throttled; returns display-only `xp_awarded`), `GET <id>/my-submissions/`, `POST <id>/toggle-external-solved/` (honour-based; only if `allows_external`; awards solve XP once).
- `GET /api/v1/coding/meta/` (`CodingMetaView`, authenticated): `{enabled (CODING_ENABLED), languages[]}`; `?health=1` adds `engine_health()` (checks Piston `/api/v2/runtimes` AND that every advertised runtime is installed).
- **Admin/instructor** (`/api/v1/coding/admin/`, `TenantAdminModelViewSet`, `IsCourseEditor`): `problems/` CRUD with nested `test_cases` (an update with `test_cases` **deletes and recreates all cases**), action `problems/<id>/submissions/` (best submission per student, pending students, counts); `submissions/` read-only (includes hidden-case I/O and source code).

## Business logic
- `backend/coding/languages.py` is the single source of truth: keys `python` (Piston `python 3.12.0`, `main.py`), `cpp` (`c++ 10.2.0`, `main.cpp`), `java` (`java 15.0.2`, `Main.java`) with Monaco modes. **Must be kept in sync with `backend/deploy/piston/provision.sh`** (which installs `python:3.12.0`, `java:15.0.2`, `gcc:10.2.0`). Adding a language = edit `LANGUAGES`, `provision.sh`, rebuild; `coursegen`, `mockgen`, `quiz` validators import `LANGUAGE_KEYS`.
- `backend/coding/services.py`:
  - `run_code()` POSTs to `PISTON_URL/api/v2/execute` with `compile_timeout=10000`, `run_timeout=min(problem limit, 10000ms)`, memory capped at 512 MB, HTTP timeout 20s. Non-200 or transport failure -> `EngineError` (user-safe message).
  - Verdicts per case: `passed`, `wrong_answer`, `compile_error`, `time_limit`, `output_limit`, `runtime_error`. Output comparison strips trailing whitespace per line and trailing blank lines (`_normalize`).
  - `run_against_cases()`: runs case 0 first; if it fails to compile, remaining cases are skipped and marked `compile_error`; otherwise remaining cases run on a thread pool of size `CODE_JUDGE_PARALLELISM` (default 1 = sequential). `reveal_io` controls whether stdin/expected/stdout/stderr go back (samples always reveal; hidden cases never do for students).
  - `engine_health()` checks runtimes, used by meta endpoint.
- `backend/coding/grading.py::finalize_submission`: loads cases, runs all with `reveal_io=False`, computes `marks = max_marks * passed_points / total_points`, sets status `error` only if compile error with 0 passes else `done`; on full pass writes `CodingProblemCompletion(method='in_app')` and awards solve XP once (`XPTransaction` type `coding_solved`, `reference_id=problem.id`, `core.utils.calculate_xp_for_coding(difficulty)`). Problems with no test cases -> submission `error`.
- **Celery** `backend/coding/tasks.py`: `coding.grade_submission` (`max_retries=0`), **no explicit queue and no per-task limits** -> default queue (`celery-worker` service, concurrency `CELERY_CONCURRENCY` default 1) and global `CELERY_TASK_TIME_LIMIT=180` / soft `150`. Atomic claim `queued -> running`; engine error -> status `error` already set by `finalize_submission`; any other exception (incl. `SoftTimeLimitExceeded`) -> `error` with generic message. No retries by design.
- Other consumers of the engine: `quiz/views.py` (mock test `run_item`) and `quiz/mock_grading.py::_grade_coding` (mock test auto-grading; on `EngineError` the item falls back to manual grading), `hackathons/grading.py` and `hackathons/views.py` (same pattern). These run the judge **synchronously inside web requests** with no async path.

## Integrations / settings / env vars
- `PISTON_URL` (default `http://piston:2000`), `CODING_ENABLED` (default True; also gates mock/hackathon coding grading), `CODE_JUDGE_ASYNC` (settings & compose default **False**), `CODE_JUDGE_PARALLELISM` (default 1; only raise on a multi-core Piston), `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `CELERY_CONCURRENCY`.
- Throttle scopes in `REST_FRAMEWORK`: `code_run`, `code_submit` (120/hour each).
- Compose services: `piston` (image `ghcr.io/engineer-man/piston`, **`privileged: true`** for Isolate, no published ports, `cpus: 1.0`, `mem_limit: 1536m`, `pids_limit: 1024`, `PISTON_OUTPUT_MAX_SIZE=65536`, volume `piston_data`, runtime-presence healthcheck with 600s start period) and `piston-init` (one-shot `curlimages/curl` running `backend/deploy/piston/provision.sh`, `restart: on-failure:3`, deliberately not a dependency of `web`). Piston starts with an **empty package store**; a fresh `piston_data` volume means every run/submit returns 503 until `piston-init` finishes (gcc install takes minutes).
- Gunicorn: `gthread`, 4 threads/worker, `timeout=120` (sync judging holds a thread).

## Cross-app dependencies
Imports `core` (OrderedModel/TimeStampedModel, XP util), `exams` (Course/Subject/Topic, `TenantAdminModelViewSet`), `users` (CourseEnrollment/StudentProfile), `gamification` (XP). Imported by: `coursegen` (apply/schema/material/views; AI-generated coding problems), `mockgen`, `hackathons` (ai_views, grading), `quiz` (mock grading, run_item, `LANGUAGE_KEYS`), `exams` (course progress, `course_copy.py` copies problems + test cases, serializers), `certificates` (completion counts), `chatbot/work_context.py` (failing-test summaries fed to the AI tutor).

## Tests
**None in `main`** for the `coding` app (no `tests.py`; `coursegen/tests.py` only exercises AI-generated coding problems). Judge verdict mapping, normalisation, short-circuit on compile error, async claim/redelivery, and completion/XP logic are untested.

## Gotchas / tech debt / risks
- **Sandbox posture**: untrusted code runs in Piston (Isolate) which needs `privileged: true`; the container is walled by cpu/mem/pids caps and no published ports but sits on the default compose network (not `internal`), so network isolation depends on Piston's own Isolate config (the code comment says network disabled; unverified here). Treat the Piston container as a high-value target; keep it unexposed and keep the Piston image pinned (currently an unpinned tag).
- Piston `run_timeout` is wall-clock, so the judge is only reliable with dedicated cores; with a shared single core and `CODE_JUDGE_PARALLELISM>1` correct solutions get spurious `time_limit`. Default concurrency 1 for both Celery and parallelism is intentional.
- Worst-case grading time = cases x (up to ~20s HTTP) sequential; a large hidden suite can exceed the 150s soft limit (task marks `error`, student must resubmit) and the sync path can exceed gunicorn's 120s (worker restart). Keep test suites small or raise limits for `coding.grade_submission`.
- `coding.grade_submission` runs on the default queue with the global 180s hard limit; a hard kill leaves a submission stuck `running` (soft-limit path is handled, hard kill is not). Redelivery is safe (claim is atomic) but the stuck row is never retried or reaped.
- `CodingSubmission` rows are created without `tenant` (NULL); tenant isolation relies on `problem`/enrollment joins, and admin filtering uses `problem__tenant`.
- Sync-mode engine failure deletes the submission (legacy behaviour) whereas async mode keeps it as `error`; the two modes differ in history.
- `CODE_JUDGE_ASYNC` default is False: a deploy that forgets to set it grades in the web request; the compose comments say to enable only once redis + celery-worker are running.
- Language additions require three synchronized edits (languages.py, provision.sh, frontend list is served from `/meta/`). Provision script's `PACKAGES` list is the source for installed runtimes.
- Mock-test and hackathon coding grading are synchronous and in-request (no queue); heavy exams can pile up on the single Piston core.
- Starter code / statements are stored as raw HTML/Markdown authored by staff; AI-generated statements are rendered server-side via `coursegen.notehtml`.
- Hidden test I/O is stripped in `SubmissionResultSerializer`, but `AdminSubmissionSerializer` returns everything; do not reuse it for student views.

## Key files
- `backend/coding/models.py` - problems, test cases, submissions, completions.
- `backend/coding/views.py` - student endpoints (run, submit, poll, external toggle). `backend/coding/admin_views.py`, `admin_serializers.py` - authoring + review. `backend/coding/meta_views.py`.
- `backend/coding/services.py` - Piston client, verdict logic, `run_against_cases`, `engine_health`.
- `backend/coding/grading.py` - scoring, completion, XP. `backend/coding/tasks.py` - `coding.grade_submission`.
- `backend/coding/languages.py` - language registry (sync with Piston provisioning).
- `backend/deploy/piston/provision.sh` - idempotent runtime installer; `backend/docker-compose.yml` services `piston`, `piston-init`, `celery-worker`.
- `backend/dailytaiyari/settings.py` - `PISTON_URL`, `CODING_ENABLED`, `CODE_JUDGE_*`, throttles, Celery limits.
