# jobs

Source: branch `main`.

- **Purpose**: Tenant job/internship board. Admins author `internal` jobs (full hiring pipeline inside the platform: resume + cover letter, stage board, notes, audit trail) or `external` jobs (link-out; click is logged as "applied externally"). Students browse (publicly), apply, withdraw, and report dead listings (3 distinct reports auto-archive).
- **Mount**: `/api/v1/jobs/` (backend/dailytaiyari/urls.py). Tenant feature flag `jobs` ("Job Portal") exists in `core.Tenant.FEATURE_CHOICES` but is **UI-only; backend endpoints do not check it**. (Not to be confused with `core.JobApplication`, which is a marketing-site career lead model in `backend/core/models.py`.)

## Key models (backend/jobs/models.py; all `TimeStampedModel`, UUID pk)
| Model | Notes |
|---|---|
| `Job` | `tenant` overridden to be required (non-null). `job_type` internal/external, `category` job/internship, `employment_type` full_time/part_time/internship/contract/temporary, `work_mode` onsite/remote/hybrid, `status` draft/published/closed/archived, experience & salary ranges (INR default, period `year`), rich-HTML `description`/`requirements`, `external_url`, `openings`, `deadline`, `created_by`, `related_courses` M2M (upskill tiles), `views_count`. `is_open` = published and before deadline. `REPORT_ARCHIVE_THRESHOLD = 3`. Indexes (tenant,status,-created_at), (tenant,job_type), (tenant,category). |
| `JobApplication` | `job`, `applicant`->StudentProfile, contact snapshot (name/email/phone), `resume` FileField (`jobs/resumes/`), `cover_letter`, portfolio/linkedin URLs, `stage` in applied/under_review/shortlisted/interview/offer/hired/rejected/withdrawn/applied_external, `is_external`, `applied_at`. **unique_together (job, applicant)**. `PIPELINE_STAGES` = applied..hired (board order). |
| `JobReport` | student "this job is closed" report; reason closed/expired/other; unique (job, reporter). |
| `ApplicationEvent` | audit trail: event_type applied/stage_change/note, from/to stage, note, `created_by` user. |

## API
Student `JobViewSet` (ReadOnlyModelViewSet, backend/jobs/views.py), router registered at `''`:
- `GET /` list and `GET /<id>/` retrieve: **AllowAny** (public browsing; still needs `X-Tenant-ID`). Only `status=published` jobs of the request tenant; `?job_type=internal|external`; retrieve bumps `views_count`; list/detail attach `my_application`, `my_report`, `reports_count` when logged in.
- `GET my-applications/`, `POST <id>/apply/` (multipart: `resume` required PDF-ish file, `cover_letter`, `full_name`, `email`, `phone`, `portfolio_url`, `linkedin_url`; re-apply allowed after withdrawal/external click; closed or deadline-passed -> 403), `POST <id>/apply-external/` (get_or_create external application, returns `external_url`), `POST <id>/withdraw/` (internal only), `POST <id>/report/` (reason/note; auto-archives at threshold). All `IsAuthenticated`, need a StudentProfile.
Admin (backend/jobs/admin_views.py, `IsTenantAdmin` = role admin only; instructors are NOT allowed), base `admin/`:
- `admin/jobs/` `AdminJobViewSet` CRUD (search title/department/location; filters status/job_type/employment_type/work_mode); actions `restore` (republish + clear reports), `applications` (kanban payload with `stage_counts`).
- `admin/applications/` `AdminApplicationViewSet` (read-only list/retrieve; filters job/stage/is_external); actions `move-stage` (POST `stage`, optional `note`; external applications cannot be moved), `add-note`, `resume` (streams file inline, `nosniff`, `no-store`; filename always `resume.pdf`), `overview` (tenant hiring stats).

## Business logic
No services/signals/tasks/management commands. All logic is inline in views. Every state change writes an `ApplicationEvent`. **No notifications or emails** are sent on apply/stage change (no call into `notifications`). Admin `related_course_ids` validated to be same-tenant; student-side serializers expose course price/thumbnail.

## Integrations / settings / env
None external. File storage via Django default storage (`MEDIA_ROOT` locally; Azure/S3 via `storages` in prod). Uses `JobsPagination` (page_size 100, max 1000) for admin lists.

## Cross-app dependencies
Imports `core` (TimeStampedModel, IsTenantAdmin, Tenant), `exams.Course`, `users` (User, StudentProfile). Frontend: `frontend/exam-frontend/src/pages/Jobs.jsx`, `JobDetail.jsx`, `JobManager.jsx`, `JobApplicants.jsx`, `JobApplicationReview.jsx`.

## Tests
None (`backend/jobs` has no tests file; grep of backend found no test referencing the jobs app).

## Gotchas / risks
- **No server-side validation of resume file type/size** — view only checks presence; despite the "PDF" wording any file type is accepted and stored; admin download is served inline with a content-type guessed from the filename (nosniff set, but still an uploaded-file risk).
- Report flow is gameable by 3 colluding/sock-puppet student accounts (auto-archive removes a job from the board; admin `restore` clears reports).
- `apply` returns "already applied" for any existing internal application whose stage is not `withdrawn` (so a `rejected` applicant cannot re-apply; a withdrawn one can, reusing the same row and resetting stage to `applied`).
- Students whose tenant has the `jobs` flag off can still hit the API directly.
- `JobViewSet.get_queryset` filters by tenant+published only; `my-applications` filters by `job__tenant`.
- `applicants_count` on list payload is effectively always null (`_applicants_count` is never set).

## Key files
- backend/jobs/models.py — Job, JobApplication, JobReport, ApplicationEvent
- backend/jobs/views.py — student board + apply/withdraw/report
- backend/jobs/admin_views.py — admin CRUD, pipeline, resume streaming, overview
- backend/jobs/serializers.py, admin_serializers.py — student/admin serializers (course tiles, stage displays)
- backend/jobs/urls.py — router wiring (admin router mounted before student router)
- backend/jobs/migrations/0001..0005 — incl. category, JobReport, related_courses
