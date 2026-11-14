# notebooks

Source of truth: `main` branch. Paths repo-relative. User-facing name is **"Lab(s)"**; code, API paths, routes and query keys stay `notebook` (label-only rename, do not rename code). See also `wiki/notebooks-labs.md` (mostly accurate; two corrections in Gotchas).

- **Purpose**
  - Gradable Python notebooks (nbformat v4 JSON) authored by tenant admins/instructors under a Topic. Students run cells **client-side in Pyodide** (WebAssembly, zero server compute); on submit the notebook is **re-executed server-side in the sandboxed `nbrunner` container** and that result is the authoritative grade. The browser score is stored only as a display-only provisional score.
  - Includes an AI "Notebook Studio" generator (draft -> review -> apply) using the same job pattern as `coursegen`.

## Key models (`backend/notebooks/models.py`)
| Model | Notes |
|---|---|
| `Notebook(OrderedModel)` | `tenant` (NOT NULL FK, related `notebooks`), `course`, `subject?`, `topic`, `title`, `description` (HTML), `difficulty`, `template_json` (starter nbformat doc), `packages` JSON (defaults `numpy, pandas, matplotlib, scikit-learn` via `normalized_packages()`), `time_limit_ms` (30000), `memory_limit_mb` (512), `max_marks`, `status` (`draft`/`published`/`archived`), `is_timed` + `due_at`, `allow_resubmission`, `max_attempts` (null/0 = unlimited; `attempt_limit` returns 1 if resubmission off), `provisional_grading` (`none`/`visible` default/`all` = reveals hidden test source to the browser), `show_results_to_students`. Props `is_open`, `is_past_due`, `attempts_remaining()`, `total_points()`. Indexes (topic,status), (course,status). |
| `NotebookDataset` | File mounted into the working dir before execution (`filename` unique per notebook: `uniq_notebook_dataset_filename`; extensions csv/tsv/json/txt/xlsx/xls/parquet/npy/npz/zip; stored in `notebook_datasets/`). |
| `NotebookTest` | Autograder check: `grade_id` (links to answer cell), `name`, `source` (Python run in the notebook's namespace after all cells; passes if no exception, `assert` idiom), `points`, `is_hidden` (default True), `failure_hint` (shown instead of traceback). |
| `NotebookDraft` | Autosaved student working copy. UniqueConstraint (notebook, student). `time_spent_seconds` cumulative (client sends deltas). |
| `NotebookSubmission` | One attempt. UniqueConstraint (notebook, student, attempt_number). `notebook_json` (merged with template), `status` enum `queued` -> `running` -> `graded` \| `error`; `results` JSON per test, `execution_error`, point counters, `marks` (scaled to `max_marks`), provisional_* fields, `is_late`, `override_marks` + `feedback` + `graded_by` (manual override wins via `final_marks`). Indexes `nb_submission_ns_idx`, `nb_submission_status_idx`. |
| `NotebookCompletion` | Per (notebook, student) best result (UniqueConstraint `uniq_notebook_student_completion`); `is_complete` when best >= 60% of points (`PASS_RATIO=0.6`). |
| `NotebookGenerationJob` | AI generation job; mirrors `coursegen.CourseGenerationJob` (status `pending/generating/preview/applied/failed/discarded`, `draft`, `revisions`, token/cost fields, `applied_summary`) but requires `course`, `topic`; links `notebook` once applied. Only `kind='notebook'`. |

Tenant scoping: `Notebook` and `NotebookCompletion` carry a NOT NULL `tenant`; other models use the nullable `TimeStampedModel.tenant` (set explicitly in submit/draft paths; student queries filter by enrolled course ids rather than tenant). Migrations: 0001 (core), 0002 (generation job).

## API
Prefix `/api/v1/notebooks/` (`backend/notebooks/urls.py`). Auth is JWT + `X-Tenant-ID`.

**Student** (`NotebookViewSet`, `IsAuthenticated`; only `published` notebooks in courses where the student has an approved, active enrollment):
- `GET /`, `GET /<id>/` (detail incl. `notebook_json` = draft or template, visible tests with source, hidden tests name/points only, datasets, attempt state).
- `GET|PUT|DELETE /<id>/draft/` (autosave; DELETE resets to template). `POST /<id>/submit/` (throttle scope `notebook_submit` = 60/hour). `GET /<id>/submissions/<uuid>/` (poll, owner-scoped), `GET /<id>/my-submissions/`, `GET /<id>/submissions/<uuid>/notebook/`. Draft/poll actions are exempt from throttling.
- `GET /meta/` (`NotebookMetaView`): known packages, cell roles, modes.

**Admin/instructor** (`TenantAdminModelViewSet` from `exams/admin_views.py`; `IsCourseEditor` = role admin/instructor; instructors limited to assigned courses):
- `/admin/notebooks/` CRUD with nested tests; extra actions `import-ipynb` (multipart <=20 MB, strips outputs, does not create), `duplicate`, `test-run` (grades a reference solution through nbrunner; 503 if server grading disabled), `submissions` (per-student best/latest + pending students + counts), `stats` (per-test pass rates).
- `/admin/datasets/` (upload), `/admin/submissions/` (GET/PATCH/POST; actions `regrade` -> requeues, `grade` -> manual `override_marks` + `feedback`).

**AI generator** `/api/v1/notebooks/admin/generate/` (`notebooks/aigen/views.py`, `IsAuthenticated` + `IsCourseEditor`): `options/`, `jobs/` (GET list, POST create -> 202), `jobs/<id>/` (GET poll, DELETE), `jobs/<id>/refine/`, `regenerate/`, `apply/` (needs `confirm=true`, status `preview`), `discard/`. Note: the Course Studio under `/api/v1/tenant-admin/course-ai/` also lists notebook flags but does not generate notebooks.

## Business logic
### Student submit flow (`views.py::NotebookViewSet.submit`)
1. `normalize_notebook` validates the document; `merge_student_notebook(template, submitted)` rebuilds it from the template, taking only `editable`/`answer` cell sources from the student (matched by `grade_id`, then by position), so locked `readonly` setup cells cannot be tampered with; extra scratch cells are appended as editable.
2. Attempt claimed inside `transaction.atomic` + `select_for_update` (engine-error attempts don't count against the limit but keep their number); `IntegrityError` -> 409.
3. `grading.apply_provisional` re-derives provisional points from the notebook's own test rows (client payload cannot inflate it).
4. If `NOTEBOOKS_SERVER_GRADING` is false: provisional result is promoted to the recorded grade (`_grade_from_provisional`) - **the grade is then client-computed**.
5. Else if `NOTEBOOKS_JUDGE_ASYNC` (default True): `grade_notebook_submission.delay()` -> 202 with queued submission; on broker error grades synchronously in the request. Otherwise grades inline (201, or 503 on `EngineError`).

### Grading (`grading.py`, `services.py`)
- `services.grade_notebook` -> `execute_notebook` POSTs `{notebook, tests[{id,name,source,points}], files[b64], packages, time_limit_ms, memory_limit_mb}` to `NBRUNNER_URL/execute`. Hard ceilings: `MAX_RUN_TIMEOUT_MS=120000`, `MAX_MEMORY_MB=2048`, `HTTP_TIMEOUT_S=180`, datasets inline up to 25 MB total (excess datasets silently dropped with a warning). Runner failures -> `EngineError` -> submission `status='error'`.
- `grading.finalize_submission`: no tests => graded with 0 points (manual marking); else scores, `marks = max_marks * passed/total`, `refresh_completion` (best submission by `passed_points`), awards XP once per notebook (`XPTransaction` type `notebook_graded`, `reference_id=notebook.id`, via `core.utils.calculate_xp_for_assignment`) when complete.
- Student result serializers never include hidden test source; `show_results_to_students=False` hides per-test detail.

### Celery (`backend/notebooks/tasks.py`)
| Task name | Queue | Limits | Purpose |
|---|---|---|---|
| `notebooks.grade_submission` | `notebooks` | soft 280s / hard 300s | claim `queued -> running` atomically, `finalize_submission`; engine error -> row `error`, no retry; unexpected -> row `error` with generic message. `max_retries=0`. |
| `notebooks.generate` | **`aigen`** | soft 1500s / hard 1560s | AI generate/refine; same claim semantics as coursegen. |
- Workers: `celery-nbworker` (`--queues=notebooks`, concurrency `CELERY_NB_CONCURRENCY` default 1), `celery-aiworker` (`--queues=aigen`, `CELERY_AI_CONCURRENCY` default 4). Per-task limits override the global `CELERY_TASK_TIME_LIMIT=180`/soft 150. If a worker for a queue is not running, tasks sit queued silently.

### AI generation (`backend/notebooks/aigen/`)
- `generation.py` reuses `coursegen.generation` (`resolve_for_admin`, `_check_budget`, `extract_json`, `_Meter`, `available_models`); meters to `AIUsageRecord` with `feature='notebookgen'`; `NOTEBOOK_MAX_TOKENS=8000`; one LLM call per generate or refine; `options.graded` (default True) controls whether tests are produced. `NOTEBOOKS_GEN_ASYNC` (default True) with inline fallback on broker error.
- `schema.py` normalises drafts (MAX_CELLS 40, MAX_TESTS 40; answer cell without `grade_id` downgraded to editable; tests pointing at no answer cell dropped; package names validated alnum/`-_.`) and `draft_to_template` builds nbformat.
- `apply.py::apply_draft` (atomic): creates or updates the `Notebook` (matched by job's linked notebook, else tenant+topic+title), status `published` unless `options.publish` is false (**default publishes immediately**), rebuilds tests by name and deletes tests not in the draft.

### nbformat helpers (`nbformat_utils.py`)
Authoring metadata lives in `cell.metadata.dailytaiyari = {role: readonly|editable|answer, grade_id, points}`; `KNOWN_PACKAGES` (Pyodide-compatible list), `normalize_notebook`, `strip_outputs`, `merge_student_notebook`, `answer_grade_ids`.

## `nbrunner` sandbox (`backend/deploy/nbrunner/`)
- `Dockerfile`: `python:3.12-slim`, non-root user `runner`, pinned scientific stack (numpy 2.1.3, pandas 2.2.3, scipy 1.14.1, scikit-learn 1.5.2, matplotlib 3.9.2, sympy, statsmodels, networkx, pillow), `MPLBACKEND=Agg`, no app code. Keep package list in sync with Pyodide packages used in the browser.
- `runner.py`: stdlib `ThreadingHTTPServer` on `NBRUNNER_PORT` (2100); `GET /health`, `POST /execute` (<= 64 MB body). Each request runs in a **fresh forked subprocess** (`multiprocessing` fork) that: chdirs to a temp dir (deleted afterwards), writes datasets (basename only, no dotfiles), then applies `RLIMIT_AS`/`DATA` (memory), `RLIMIT_CPU` (= `time_limit_ms` seconds, max 180), `RLIMIT_FSIZE` 128 MB, `RLIMIT_NPROC` 256, then `exec`s each code cell in a shared namespace (stop at first error) and then each test source in the same namespace (tests still run after an execution error). Parent enforces wall-clock = cpu limit + 15s then terminate/SIGKILL; on timeout every test is reported failed ("notebook timed out"). stdout capped 20k chars, errors 4k, traceback shows only `<cell N>`/`<test name>` frames.
- Compose (`backend/docker-compose.yml` service `nbrunner`): no published ports, `read_only: true`, tmpfs `/tmp` 1g, `cap_drop: ALL`, `no-new-privileges`, `cpus: 1.0`, `mem_limit: 2g`, `pids_limit: 512`, healthcheck on `/health`. Not privileged (unlike piston).
- Environment contract: web container -> `http://nbrunner:2100` only; the runner has no credentials and no DB access by design.

## Integrations / settings / env vars
`NOTEBOOKS_ENABLED` (default True; defined in settings but **not read anywhere in backend code** - dead flag), `NOTEBOOKS_SERVER_GRADING` (settings default **False**, docker-compose default **True**), `NBRUNNER_URL` (default `http://nbrunner:2100`), `NOTEBOOKS_JUDGE_ASYNC` (True), `NOTEBOOKS_GEN_ASYNC` (True), `CELERY_BROKER_URL`/`CELERY_RESULT_BACKEND`, `CELERY_NB_CONCURRENCY`, `CELERY_AI_CONCURRENCY`, `AI_READ_TIMEOUT_BACKGROUND`. Dataset files use default media storage (Azure/S3/local). Throttle `notebook_submit` 60/hour in `REST_FRAMEWORK` settings.

## Cross-app dependencies
Imports `exams` (Course, Subject, Topic), `users` (CourseEnrollment, StudentProfile), `gamification` (XP award), `core` (TimeStampedModel/OrderedModel, utils XP calc), `chatbot` (LLM resolver/providers/usage) and `coursegen.generation` helpers, `exams.admin_views.TenantAdminModelViewSet`. Imported by (verified by grep): `coursegen` (`material.py`, `views.py` tree flags), `exams/views.py` + `exams/serializers.py` (course progress: counts of `Notebook` / `NotebookCompletion` as "labs"), `hackathons/grading.py` (reads `NotebookCompletion` for hackathon scoring), `exams/course_copy.py` is coding-only. Frontend: `NotebookPage`, `NotebookAIGenerator`.

## Tests
**None in `main`**: no `tests.py` for the `notebooks` app (nothing covers submit, merge, grading, runner contract, or AI generation). Only incidental coverage via other apps.

## Gotchas / tech debt / risks
- **Sandbox posture (read before relying on it)**: isolation is process-level inside one container. The claim in compose/comments of a "network-isolated" runner is not enforced by config: the service sits on the default compose network (no `internal: true` network, no egress filtering), so student code can open sockets to other compose services (db, redis, piston, web) and to the internet unless the host/network blocks it. Redis in compose has no auth. Student code `exec`s in the **same process and namespace as the harness and the test sources**, so a hostile student can read hidden tests (they are in memory in the child) or monkeypatch builtins/`AssertionError` to force passes; grading is therefore not tamper-proof against a determined attacker. `RLIMIT_NPROC` is per-UID across concurrent forks in the container. These are fine for honest cohorts, not for high-stakes exams. A fork-bomb/CPU abuse is bounded by container `pids_limit`/`cpus`/`mem_limit` but can starve other concurrent gradings (runner accepts concurrent requests via threads; only celery concurrency limits load).
- **`time_limit_ms` is whole-notebook, not per cell**: the runner applies it as the process CPU limit and wall-clock budget for the entire notebook run, while the model help text says "single cell execution". `memory_limit_mb`/`time_limit_ms` are clamped to 2048 MB / 120 s by `services.py` (runner max 180 s).
- `NOTEBOOKS_SERVER_GRADING` false means grades are browser-computed and forgeable; the compose default turns it on but the Django default is off, so a non-compose deployment silently trusts clients.
- `provisional_grading='all'` ships hidden test source to the browser (documented trade-off).
- If the `notebooks` worker is down submissions stay `queued`; if `aigen` worker is down generation jobs stay `pending`. A hard kill (300s/1560s) leaves `running`/`generating` rows with no reaper (grading task: only soft-limit path marks `error`).
- Model docstring in `models.py` says `NotebookGenerationJob` runs on the `notebooks` queue and `aigen/views.py` docstring repeats it; the code actually routes `notebooks.generate` to **`aigen`**. Also wiki says `grading.py` "talks to nbrunner": the HTTP client is `services.py`; `grading.py` does scoring/completion/XP. Wiki lists `services.py` as completion bookkeeping (wrong).
- `apply_draft` default `options.publish=True` publishes AI notebooks immediately and deletes any existing tests not in the draft (for an existing same-title notebook this rewrites its grading).
- Dataset size: >25 MB total datasets are truncated silently for grading (earlier files win), so grading can differ from the browser.
- `NotebookViewSet.get_queryset` filters by enrolled course ids only (no explicit tenant filter), relying on enrollment integrity.
- Pyodide packages vs nbrunner packages must be kept in sync manually; `packages` field is advisory for the runner (preinstalled image only; unknown package imports fail at grading time).
- Regrade from the admin API resets status to `queued` before enqueue; completion/XP side effects are idempotent (XP once per notebook).
- Hidden/visible naming: `NotebookTest.is_hidden` default True.

## Key files
- `backend/notebooks/models.py` - all models. `backend/notebooks/views.py` - student API + submit flow. `backend/notebooks/admin_views.py` - authoring/review. `backend/notebooks/urls.py`.
- `backend/notebooks/services.py` - HTTP client for nbrunner (limits, dataset payload). `backend/notebooks/grading.py` - scoring, completion, XP, provisional handling. `backend/notebooks/tasks.py` - Celery tasks.
- `backend/notebooks/nbformat_utils.py` - nbformat normalisation + template merge. `backend/notebooks/serializers.py` / `admin_serializers.py`.
- `backend/notebooks/aigen/` - `generation.py`, `schema.py`, `prompts.py`, `apply.py`, `views.py`, `serializers.py` (AI Notebook Studio).
- `backend/deploy/nbrunner/Dockerfile`, `backend/deploy/nbrunner/runner.py` - sandbox image and server.
- `backend/docker-compose.yml` (services `nbrunner`, `celery-nbworker`, `celery-aiworker`), `backend/dailytaiyari/settings.py` (NOTEBOOKS_* / NBRUNNER_URL).
- `wiki/notebooks-labs.md` - existing design doc. Frontend: `frontend/exam-frontend/src/pages/NotebookPage.jsx`, `components/notebook/*`, `workers/pyodideKernel.worker.js`.
