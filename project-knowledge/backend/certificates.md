# certificates

Source: `main`, `backend/certificates/`. Verified from code unless marked "unverified".

- **Purpose**: Course-completion certificates. A student who reaches 100% completion of a course whose admin enabled certificates gets a `CourseCertificate` issued lazily on first status request; anyone can verify a certificate by number via a public endpoint. Rendering/PDF generation is done by the frontend (backend only supplies data).
- Also provides roster-wide progress computation for admin screens (`bulk_progress.py`).

## Key models (`backend/certificates/models.py`, migration `0001_initial`)
- `CourseCertificate(TimeStampedModel)` (UUID pk, nullable base `tenant`, set at issue): `student` (StudentProfile), `course` (exams.Course), `certificate_number` (unique, indexed, format `DT-<year>-<8 chars from 31-char unambiguous alphabet>`), `template` (snapshot of `Course.certificate_template`, default `classic`), snapshots `student_name`, `course_name`, `tenant_name`, `issued_at`. **Unique `(student, course)`** - one certificate per student per course, never reissued.
- Course-level settings live on `exams.Course`: `certificate_enabled` (default False), `certificate_template` (choices `CERTIFICATE_TEMPLATES` in exams).

## API (prefix `/api/v1/certificates/`, `backend/certificates/urls.py`)
| Route | View | Auth |
|---|---|---|
| `GET course/<uuid:course_id>/` | `CourseCertificateView` | `IsAuthenticated`; needs `request.user.profile` (403 otherwise). Returns `{enabled, template, progress, completed, total, eligible, certificate}`; **issues the certificate as a side effect of the GET** when eligible. |
| `GET verify/<str:number>/` | `CertificateVerifyView` | `AllowAny` (public). Returns `{valid, certificate}` (student name, course name, tenant name/logo, issue date, number) or 404. |
Serializer `CourseCertificateSerializer`: `id, certificate_number, template, student_name, course_name, tenant_name, tenant_logo_url, issued_at, issued_date_display ("%d %B %Y"), verify_url` (built as `/api/v1/certificates/verify/<number>/`).

## Business logic
- `services.compute_course_progress(student, course)` -> `(completed, total, percent)` summed over every `Subject` of the course: published reading content (`notes, pdf, revision, formula`), published videos, published quizzes (`subject=subj, course=course`; done = distinct completed quiz attempts), published assignments under the subject's topics (done = any submission), published coding problems under the subject's topics (done = a `CodingSubmission` with `passed_count == total_count > 0`). ~10 queries per subject.
- `is_course_complete`: `total > 0 and percent >= 100`. `get_or_issue_certificate`: returns existing; else requires `certificate_enabled` and completion; then `get_or_create` (race-safe via unique constraint) with snapshots, tenant = course tenant.
- `bulk_progress.bulk_course_progress(enrollments)`: same item definitions via grouped aggregates (4 queries for totals, 4 for done) for the admin roster; used by `users/views.py` (admin student progress, ~line 902). Caps `completed` at `total`.
- No signals, tasks or management commands. Issuance is request-driven only (no batch/backfill job for students who completed before enabling certificates; they get it on next visit to the endpoint).

## Integrations / settings
- None (no env vars). Tenant logo served via media URL.

## Cross-app dependencies
- Imports: `core.models.TimeStampedModel`, `exams` (Course, Subject), `content` (Content, ContentProgress), `quiz` (Quiz, QuizAttempt), `assignments`, `coding` (CodingProblem, CodingSubmission).
- Imported by: `users/views.py` (bulk_course_progress). Frontend student course-completion panel and public verify page consume the API (unverified here).

## Tests
None in this app.

## Gotchas / risks
- **Progress definitions diverge between the single and bulk implementations** despite the docstring claiming they mirror: `compute_course_progress` counts quizzes with `subject == subj` only (quizzes with `subject=NULL`, including every daily-challenge quiz built by `quiz`, are excluded), while `bulk_progress._totals_by_course` counts all published quizzes by `course_id` (includes subject-less/daily quizzes). Admin roster percentages can therefore be lower than the student's own certificate eligibility. Also bulk counts `QuizAttempt` by `quiz__course_id`.
- `CourseCertificateView.get` does not check that the student is enrolled in the course or that the course belongs to the caller's tenant (`Course.objects.get(pk=...)`); progress is per-student so eligibility needs real completion data, but metadata about any course id is reachable. Treat as low risk, unverified exploitability.
- A GET that creates data (non-idempotent verb with side effects); safe because of `unique_together` + `get_or_create`.
- Completion is count-based on *published* items at request time: publishing a new item later lowers percent, but an issued certificate stays valid forever (no revocation flow; delete via Django admin).
- Assignment "done" = any submission (even ungraded); quiz "done" = any completed attempt regardless of score.
- Snapshot names (`student_name`) are taken once; later profile renames do not update the certificate.
- Public verify endpoint is subject to the global AnonRateThrottle (100/hour). Exposes student full name + course + tenant to anyone holding/guessing the number (~31^8 space); no email or ID leaked.
- Verify URL is built from the request host, so behind a proxy it depends on correct host/forwarded headers.

## Key files
- `backend/certificates/models.py` - CourseCertificate, number generator.
- `backend/certificates/services.py` - progress computation + issuance.
- `backend/certificates/bulk_progress.py` - grouped-query roster progress.
- `backend/certificates/views.py`, `serializers.py`, `urls.py` - API.
- `backend/exams/models.py` - `certificate_enabled`, `certificate_template` on Course.
