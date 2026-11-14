# assignments

Source: `main`, `backend/assignments/`. Verified from code unless marked "unverified".

- **Purpose**: Admin/instructor-authored assignments attached to a Topic (like quizzes). Students submit text and/or a PDF/ZIP file; admins track submitted vs pending students and grade with marks + feedback, which awards XP once.
- Timed (due date, then closed) or timeless; question paper attachment is optional (PDF viewed inline, ZIP downloaded).

## Key models (`backend/assignments/models.py`; both extend `core.models.OrderedModel` -> UUID pk, nullable base `tenant`, `order`)
- `Assignment`: `tenant` (re-declared, **required** FK, related_name `assignments`), `course` (required, CASCADE), `subject` (nullable SET_NULL), `topic` (required, CASCADE), `title`, `instructions` (HTML/Markdown), `submission_type` text | pdf | either (default either), `attachment` (FileField `assignment_papers/`, validators pdf/zip), `is_timed` + `due_at`, `max_marks` (nullable PositiveInteger), `status` draft/published/archived. `is_open` property: published and (not timed or now <= due_at).
- `AssignmentSubmission`: `assignment`, `student` (users.StudentProfile), `submission_text`, `submission_file` (`assignment_submissions/`, pdf/zip), `submitted_at`, `status` submitted | graded, `marks` (Decimal 6,2, nullable), `feedback`, `graded_at`, `graded_by`. **Unique `(assignment, student)`** -> one submission row per student, overwritten on resubmit.
- Migrations: `0001_initial`, `0002_alter_assignment_attachment_and_more`.

## API (prefix `/api/v1/assignments/`, `backend/assignments/urls.py`)
Student (`AssignmentViewSet`, read-only, `IsAuthenticated`, parsers JSON/multipart; router registered at the empty prefix `''`):
- `GET /` list, `GET /{id}/` detail (adds `instructions`, `subject`), filter `?topic=`. Queryset = published assignments in the student's approved+active enrollments (`course_id__in`); NOT paginated (custom `list`); no explicit tenant filter (enrollment implies tenant).
- `POST /{id}/submit/` (multipart `submission_text`, `submission_file`): rejects closed assignments (403), file ext must be pdf/zip (extension check only), per-`submission_type` required-field validation, `get_or_create` submission then overwrites text/file, sets `submitted_at=now`, **resets grade** (status submitted, marks/feedback/graded_* cleared). Returns 201 with assignment + `my_submission`.
- `GET /{id}/paper/` streams the attachment (`serving.serve_assignment_file`).
Admin (`/api/v1/assignments/admin/`, both extend `exams.admin_views.TenantAdminModelViewSet`, permission `IsCourseEditor`: tenant admins + instructors assigned to the course; instructors see only their courses via `course_lookup`):
- `assignments/` `AdminAssignmentViewSet`: CRUD (multipart supported), filters course/subject/topic/status/submission_type, `reorder`, `{id}/submissions/` (submitted list + `pending` students from enrolled approved+active students + counts enrolled/submitted/pending/graded).
- `submissions/` `AdminSubmissionViewSet`: GET/PATCH only; PATCH grades; `{id}/file/` streams the student's file (authenticated; `file_stream_url` in serializer points here).

## Business logic
- Grading (`AdminSubmissionViewSet.perform_update`): if `marks` or `feedback` present -> status `graded`, `graded_at`, `graded_by`; then awards XP **once per submission** (checks `XPTransaction(transaction_type='assignment_graded', reference_id=submission.id)`), amount `core.utils.calculate_xp_for_assignment(marks, max_marks)` = `max(ASSIGNMENT_XP_MIN=5, round(ASSIGNMENT_XP_MAX=30 x clamp(marks/max_marks, 0..1)))`, or 30 when `max_marks` missing. Uses `GamificationService.award_xp(..., 'assignment_graded', ref=str(submission.id))`.
- `serve_assignment_file`: PDF `Content-Disposition: inline`, others attachment, `X-Content-Type-Options: nosniff`, `Cache-Control: private, no-store`.
- No signals, Celery tasks or management commands.

## Integrations / settings
- Django storage backend for media (`MEDIA_ROOT`; nginx `location /media/` aliases `/app/media/`), no env vars specific to this app.

## Cross-app dependencies
- Imports: `core` (OrderedModel), `exams` (Course/Subject/Topic, `TenantAdminModelViewSet`), `users` (CourseEnrollment, StudentProfile, User), `gamification` (XPTransaction, `award_xp`), `core.utils`.
- Imported by: `certificates` (`compute_course_progress` + `bulk_progress` count published assignments and any submission as "done"), `exams` (study flow; unverified detail), `coursegen`/`exams.course_copy` (unverified).

## Tests
None in this app.

## Gotchas / risks
- **Cross-tenant references not validated**: `AdminAssignmentSerializer` accepts `course`, `subject`, `topic` UUIDs without checking they belong to the request tenant (unlike quiz admin serializers). `TenantAdminModelViewSet.perform_create` forces `tenant=request.tenant`, but a tenant admin could attach an assignment to another tenant's course/topic by id (instructors are checked against `instructing_courses` for `course` only).
- **Marks not validated against `max_marks`** (or >= 0) in `AdminSubmissionSerializer`; `marks` > max is accepted (XP calc clamps, display does not).
- `marks` alone must be non-None or `feedback` non-empty to flip status to graded; clearing marks leaves `status` as graded.
- Resubmission wipes the grade but not previously awarded XP; a re-graded resubmission never earns XP again (reference_id is the same submission id).
- Upload validation = file extension only (no MIME/magic-bytes check, no size limit in this app; relies on `DATA_UPLOAD_MAX_MEMORY_SIZE`/nginx limits - unverified).
- Serializer `file_url` for submissions returns the raw `MEDIA_URL` path; nginx serves `/media/` directly, so if filenames are guessable/known, student submissions may be fetchable without auth. The authenticated route is `submissions/{id}/file/` (what the frontend PdfReader uses). Filenames are Django-storage defaults, not random UUIDs (unverified).
- Student `AssignmentViewSet.get_object` uses `get_queryset()` (published + enrolled), so a student can submit only to published assignments in enrolled courses.
- Late submissions: `is_open` is evaluated per request (server clock); a resubmission before the due date overwrites any file already submitted.
- Student list endpoint is unpaginated (custom `list`), potentially large for big courses.
- Class-wide pending list in `submissions` action iterates enrollments in Python (N for roster, includes enrollments of inactive students filtered by `is_active=True`).
- No notification/email on grading from this app.

## Key files
- `backend/assignments/models.py` - Assignment, AssignmentSubmission.
- `backend/assignments/views.py` - student list/submit/paper.
- `backend/assignments/admin_views.py` - admin CRUD, submissions overview, grading + XP.
- `backend/assignments/admin_serializers.py`, `backend/assignments/serializers.py` - serializers.
- `backend/assignments/serving.py` - safe file streaming.
- `backend/assignments/urls.py` - routes.
