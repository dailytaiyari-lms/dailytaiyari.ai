# Labs (Python Notebooks)

Labs are gradeable Python notebooks. A student writes and runs code in the
browser, submits once, and the server re-executes the notebook against a set of
tests to produce the authoritative grade.

> **Naming:** the feature is called **"Lab" / "Labs"** everywhere a student or
> admin can see it. Everything in the code — the Django app, the models, the API
> paths (`/api/v1/notebooks/`), the React route (`/notebooks/:id`) and the query
> keys — is still named `notebook`. This is a **label-only** distinction, chosen
> because an **Assignments** content type already exists (file/text submissions)
> and "Programming Assignment" would have collided with it. Don't rename the
> code to match the label.

## Why it is built this way

Interactive execution runs **client-side in Pyodide** (CPython compiled to
WebAssembly). Every keystroke-to-output loop therefore costs zero server compute
— which is what makes labs affordable to run for a whole cohort at once.

But a browser is fully under the student's control, so a browser-computed score
is worthless as a grade. On submit, the notebook is re-executed **server-side**
in the sandboxed `nbrunner` container and *that* result is the real grade. The
browser's score is kept alongside it as a *provisional* score, so a student sees
an instant number while the authoritative one is computed.

```
Browser (Pyodide)                Django (web)              Worker + sandbox
─────────────────                ────────────              ────────────────
run cells interactively   ─┐
compute provisional score  ├─ POST submit ─► NotebookSubmission
                          ─┘                  status=queued
                                                  │
                                       enqueue ► `notebooks` queue
                                                  │
                                       celery-nbworker ─► nbrunner (HTTP)
                                                  │        re-executes notebook
                                                  ▼        + runs tests
client polls submission_status ◄── status=graded, results[], marks
```

## Backend

The `notebooks` Django app owns the whole feature.

```
backend/notebooks/
├── models.py            # Notebook, NotebookTest, NotebookDataset, NotebookDraft,
│                        # NotebookSubmission, NotebookCompletion, NotebookGenerationJob
├── views.py             # Student-facing NotebookViewSet
├── admin_views.py       # Author/admin CRUD + submission review
├── grading.py           # Talks to nbrunner, scores a submission
├── services.py          # Completion / best-attempt bookkeeping
├── nbformat_utils.py    # .ipynb <-> internal document shape
├── tasks.py             # Celery tasks (grading + AI generation)
└── aigen/               # AI lab generator (prompt -> draft notebook)
```

### Models

| Model | Purpose |
|---|---|
| `Notebook` | The lab itself: template cells, packages, limits, marks, due date, attempt policy |
| `NotebookTest` | One graded check. Has `points`, `is_hidden`, an optional `failure_hint` |
| `NotebookDataset` | A file uploaded alongside the lab and mounted for the student's code |
| `NotebookDraft` | A student's in-progress work, autosaved. One per student per lab |
| `NotebookSubmission` | One graded attempt: results, points, marks, provisional score, late flag |
| `NotebookCompletion` | Per-student rollup — best submission, best marks, attempts used, `is_complete` |
| `NotebookGenerationJob` | An async AI generation/refine job and its produced draft |

All of them are tenant-scoped through the usual `TimeStampedModel` /
`OrderedModel` bases — see [architecture.md](./architecture.md).

Attempt policy lives on `Notebook`: `allow_resubmission`, `max_attempts`,
`is_timed` + `due_at`. The student API derives `can_submit`, `attempts_used` and
`attempts_remaining` from those so the client never has to reimplement the rule.

### Grading modes

`NOTEBOOKS_SERVER_GRADING` decides where the real grade comes from:

- **`True` (both deployed environments)** — the submission is re-executed in
  `nbrunner` and scored there. Authoritative.
- **`False`** — the browser's provisional score is recorded as-is. Useful for
  local dev, or an environment that hasn't started the runner yet.

`NOTEBOOKS_JUDGE_ASYNC` decides *when*: when `True` grading is enqueued on the
`notebooks` queue and the client polls; when `False` it runs inline in the
request. Async falls back to inline automatically if the broker is unreachable,
so a Redis outage degrades latency rather than breaking submission.

### The `nbrunner` sandbox

`backend/deploy/nbrunner/` is a small HTTP service that executes untrusted
student notebooks. It is deliberately minimal: **no app code, no credentials, no
database access**.

- Never gets a `ports:` mapping — reachable only on the internal Docker network
  at `http://nbrunner:2100`.
- Runs as non-root, `read_only`, `cap_drop: ALL`, `no-new-privileges`.
- Each request executes in a **fresh forked subprocess** with `RLIMIT_AS` /
  `RLIMIT_CPU` / `RLIMIT_FSIZE` caps and a hard wall-clock kill.
- Unlike `piston` it does **not** need privileged mode.

If you change anything here, keep those properties. The threat model is "the
student is hostile and controls the code being run."

### Queues and workers

Three Celery workers, split so that a slow job can never head-of-line block a
fast one:

| Worker | Queue | Carries |
|---|---|---|
| `celery-worker` | default | email, async code judging, misc |
| `celery-nbworker` | `notebooks` | `notebooks.grade_submission` — can re-run a notebook that trains a model |
| `celery-aiworker` | `aigen` | `notebooks.generate` + `coursegen.generate` — multi-minute LLM calls |

`celery-aiworker` runs higher concurrency (`CELERY_AI_CONCURRENCY`, default 4)
because AI generation is I/O-bound and several authors may generate at once.
`celery-nbworker` stays at 1 by default since notebook execution is CPU-bound.

> **Deploy gotcha:** if `celery-aiworker` isn't running, `notebooks.generate`
> and `coursegen.generate` are enqueued and then silently never execute — jobs
> sit at `queued` forever with no error. Always confirm all three workers are up
> after a deploy.

## API

Base path `/api/v1/notebooks/`. All routes require the usual `X-Tenant-ID`
header and JWT auth.

### Student

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/notebooks/` | Labs for the student's enrolled courses (filterable by topic) |
| `GET` | `/api/v1/notebooks/<id>/` | One lab, plus attempt state and best result |
| `GET`/`PUT`/`DELETE` | `/api/v1/notebooks/<id>/draft/` | Autosaved work-in-progress |
| `POST` | `/api/v1/notebooks/<id>/submit/` | Submit for grading. Returns a submission (often `queued`) |
| `GET` | `/api/v1/notebooks/<id>/submissions/<sub_id>/` | Poll a submission's status/result |
| `GET` | `/api/v1/notebooks/<id>/my-submissions/` | Attempt history |

A lab detail response carries the fields the UI needs to explain the policy
without extra calls: `can_submit`, `allow_resubmission`, `max_attempts`,
`attempts_used`, `attempts_remaining`, `is_past_due`, `hidden_test_count`,
`my_best`, `is_complete`.

### Author / admin

| Method | Path | Purpose |
|---|---|---|
| — | `/api/v1/notebooks/admin/notebooks/` | Lab CRUD (incl. nested tests) |
| — | `/api/v1/notebooks/admin/datasets/` | Dataset upload/management |
| — | `/api/v1/notebooks/admin/submissions/` | Review, override marks, leave feedback |
| `GET` | `/api/v1/notebooks/meta/` | Available packages, limits, defaults |

### AI lab generator

Generation is **always** a background job — the client creates a job and polls
it. A real `Notebook` row is only written on `apply/`.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `.../admin/generate/options/` | Supported models/params |
| `GET`/`POST` | `.../admin/generate/jobs/` | List / start a job |
| `GET` | `.../admin/generate/jobs/<id>/` | Poll status + draft |
| `POST` | `.../admin/generate/jobs/<id>/refine/` | Modify the draft with an instruction |
| `POST` | `.../admin/generate/jobs/<id>/regenerate/` | Retry a failed or unwanted generation |
| `POST` | `.../admin/generate/jobs/<id>/apply/` | Persist the draft as a real lab |
| `POST` | `.../admin/generate/jobs/<id>/discard/` | Throw the draft away |

Because a job outlives the modal that started it, the topic studio surfaces
in-flight jobs in the topic's own tabs with a "generating" status — closing the
dialog never loses the work.

## Frontend

```
frontend/exam-frontend/src/
├── workers/pyodideKernel.worker.js   # Pyodide in a Web Worker
├── hooks/usePyodideKernel.js         # Kernel state machine (boot/exec/restart)
├── components/notebook/
│   ├── NotebookEditor.jsx            # Cell list, run-all, per-cell run status
│   ├── NotebookCell.jsx              # One cell + run-status chip
│   ├── CellOutput.jsx                # Rendered stdout/plots/errors
│   ├── LabStatusCard.jsx             # Top-of-page grade + submit affordance
│   ├── LabSubmitFlow.jsx             # Confirm -> running -> result modal
│   ├── NotebookAIGenerator.jsx       # Author-side generation UI
│   └── notebookDoc.js                # Document shape helpers
└── pages/NotebookPage.jsx            # The student lab surface
```

### Kernel

The kernel runs in a **Web Worker** so a long-running cell never freezes the UI.
`usePyodideKernel.js` owns an explicit state machine.

> **Do not infer "busy" from the pending-message map.** That was the original
> design and it caused a class of bugs where the kernel wedged permanently on
> "Running": the worker's `init` reply didn't echo the message `id`, so one
> entry never cleared and the kernel could never return to READY. Busy state is
> now tracked by an explicit in-flight execution count plus a state variable.
> Every worker reply must echo `msg.id`.

Package loading memoises failures. `pyodide.loadPackage(batch)` fails the
**entire batch** if one name can't be resolved, so without memoisation a single
bad package name forced the slow per-package + micropip fallback on every
message — which is what made every run look like it was "Loading pandas…".

First boot legitimately downloads tens of MB from the jsDelivr CDN. A kernel
restart discards `loadedPackages` and re-downloads; that is inherent to
terminating the worker, not a bug.

### Submit flow

Submitting grades the **whole lab against every test, including hidden ones**,
so it is a deliberate action rather than a stray click:

1. `LabStatusCard` sits at the top of the page with the current grade, attempt
   number and resubmission policy. It is the primary submit affordance.
2. Clicking Submit opens `LabSubmitFlow` — a confirm step that states what will
   be graded and whether resubmission is allowed, then a running step, then the
   per-test result.
3. When no attempts remain or the due date has passed, the button is disabled
   **with the reason stated**, and reads "Resubmit" once an attempt exists.

## Progress and completion

Labs count toward progress like any other content type. Five aggregates include
them, and **all five must stay in sync** — if you add a content type, grep for
these:

| Where | Why it matters |
|---|---|
| `exams/views.py` → `_chapter_completion_counts` | Drives **sequential chapter unlock**. Omitting labs means a lab can never gate the next chapter |
| `exams/views.py` → `StudySubjectsView` | Subject progress bars |
| `exams/views.py` → `StudyChaptersView` | Chapter progress bars |
| `exams/views.py` → `_course_leaderboard` | Leaderboard denominator |
| `exams/serializers.py` → `chapter_content_type_counts` | Pre-enrollment curriculum preview |

> **Payload shape trap.** The chapter-detail endpoint returns a per-topic `labs`
> array using **`is_completed`**, while `notebookService.getByTopic` returns
> objects using **`is_complete`** plus `my_best`. Two different shapes for the
> same concept — `StudyCourse.jsx` uses the former, `StudyTopicContent.jsx` the
> latter. Check which one you're holding.

> **Rollout note.** Adding labs to these denominators makes existing students'
> completion percentages **drop** wherever labs exist. That is correct, not a
> regression, but it is user-visible — mention it when promoting to an
> environment that already has labs authored.

## Configuration

See [environment-variables.md](./environment-variables.md) for the table. In
short: `NOTEBOOKS_ENABLED`, `NOTEBOOKS_SERVER_GRADING`, `NOTEBOOKS_JUDGE_ASYNC`,
`NOTEBOOKS_GEN_ASYNC`, `NBRUNNER_URL`, `CELERY_NB_CONCURRENCY`,
`CELERY_AI_CONCURRENCY`.

## Operating notes

Deploying labs into an environment for the first time needs more than a
`restart` — see [deployment.md](./deployment.md#deploying-a-release-that-adds-a-service).
Checklist:

```bash
# 1. env vars present
grep -E '^(NOTEBOOKS_|NBRUNNER_URL|CELERY_NB_|CELERY_AI_)' backend/.env

# 2. images built (nbrunner is a new image; the workers reuse the web image)
docker compose build nbrunner celery-nbworker celery-aiworker

# 3. migrations
docker compose exec -T web python manage.py migrate notebooks

# 4. services up
docker compose up -d nbrunner celery-nbworker celery-aiworker

# 5. verify: nbrunner healthy and reachable from web
docker compose ps
docker compose exec -T web python -c \
  "import urllib.request;print(urllib.request.urlopen('http://nbrunner:2100/health',timeout=5).status)"

# 6. verify: both notebook tasks registered on the workers
docker compose logs celery-nbworker celery-aiworker | grep 'notebooks\.'
```

### Troubleshooting

| Symptom | Likely cause |
|---|---|
| Generation stuck at `queued` forever | `celery-aiworker` not running |
| Submission stuck at `queued` | `celery-nbworker` not running, or `nbrunner` unhealthy |
| Grades match the browser exactly, always | `NOTEBOOKS_SERVER_GRADING=False` |
| Every cell run says "Loading pandas…" | A package name in `Notebook.packages` can't be resolved |
| Kernel stuck on "Running" | A worker reply isn't echoing `msg.id` |
| Labs missing from progress totals | One of the five aggregates above wasn't updated |
