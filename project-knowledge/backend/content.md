# content

- **Purpose**: study material (notes, video, PDF, interactive, revision, formula sheets) attached to topics/subjects/courses; per-student progress/bookmarks; rule-based daily study plans; the admin Content Builder CRUD; and the background media pipeline that makes uploaded lecture videos streamable (faststart remux/transcode + adaptive-bitrate HLS).

## Key models (backend/content/models.py)
- `Content(OrderedModel)`: `title`, **`slug` unique globally**, `description`, `content_type` notes|video|pdf|interactive|revision|formula, `material_kind` study|practice, FKs `topic` (related `contents`), `subject` (related `contents`), M2M `courses` (related `contents`); body fields `content_html`, `video_url` (YouTube/Vimeo/Drive), `video_file` (`content_videos/`), `pdf_file` (`content_pdfs/`), `thumbnail`; pipeline state `video_status` pending|processing|ready|failed (or blank), `video_progress` 0-100, `video_duration_minutes/seconds`, `hls_playlist` (storage path of master .m3u8), `hls_status`, `hls_progress`; `difficulty` beginner|intermediate|advanced, `status` draft|published|archived, `is_free`, `is_premium`, `estimated_time_minutes`, counters `views_count/likes_count/bookmarks_count`, `author_name`. Indexes (topic, content_type), (subject, status). `tenant` is the inherited NULLABLE field (not reliably set - scoping goes via `subject__course__tenant`).
- `ContentProgress(TimeStampedModel)`: student (`users.StudentProfile`, related `content_progress`), content (related `progress`), `is_completed`, `completed_at`, `progress_percentage`, `video_position_seconds`, `time_spent_minutes`, `is_bookmarked`, `is_liked`, `personal_notes`. Unique `(student, content)`.
- `StudyPlan(TimeStampedModel)`: student, course, `date`, `is_completed`, targets/actuals (study minutes, questions), `xp_earned`. Unique `(student, course, date)`; ordering `-date`.
- `StudyPlanItem(OrderedModel)`: `study_plan` (related `items`), `item_type` content|quiz|revision|mock, `title`, `description`, `content` FK (SET_NULL), `topic` FK (SET_NULL), `status` pending|in_progress|completed|skipped, `completed_at`, `estimated_minutes`, `actual_minutes`, `is_priority`, `is_revision`.

## API (prefix `/api/v1/content/`; X-Tenant-ID required)
| Route | View | Permission / behaviour |
|---|---|---|
| `` (list/retrieve) | `ContentViewSet` (ReadOnly, `lookup_value_regex` uuid) | IsAuthenticated. Only `status='published'`, `subject__course__tenant=tenant`. Admin/superuser: all tenant content; instructor: content in `instructing_courses`; student: content whose `courses` intersect approved+active enrolments (none => empty). Filters `topic, subject, content_type, difficulty, is_free`; search title/description; `retrieve` increments `views_count`. Actions: `pdf` (streams PDF inline via the API, blob URL hidden), `by_topic?topic_id=`, `recommended` |
| `progress/` | `ContentProgressViewSet` (TenantAwareViewSet) | authenticated; own rows only; `create` is upsert by `content`; actions `complete` (awards XP once: notes/revision/formula 5, video/interactive 8, pdf 6 via `gamification.GamificationService.award_xp`, plus `analytics.AnalyticsService.update_daily_activity` and profile study time), `toggle_bookmark` |
| `study-plans/` | `StudyPlanViewSet` | own plans; actions `today` (get-or-create for the resolved enrolled course + generate items), `generate` (POST: deletes and regenerates items) |
| `study-plan-items/` | `StudyPlanItemViewSet` | own items; actions `start`, `complete`, `skip` |
| `admin/contents/` | `AdminContentViewSet` (extends `exams.admin_views.TenantAdminModelViewSet`) | `IsCourseEditor` (admin + assigned instructors), tenant via `subject__course__tenant`, instructor scope via `subject__course`. Filters topic/subject/content_type/difficulty/status/is_free; action `reprocess_video` (POST) |
| `admin/upload-image/` | `AdminImageUploadView` | `IsCourseEditor`; multipart `image` or JSON data URL; returns `{url}` (stored under `content_images/`) |

Admin serializer (`AdminContentSerializer`): slug auto-generated and made globally unique (`-2`, `-3`...), `courses` defaults to the subject's course, pipeline fields (`video_status/progress`, `hls_*`) and counters are read-only.

## Business logic
- **Video pipeline** (`content/signals.py` + `content/tasks.py` + `hls.py` + `ffmpeg_utils.py`):
  1. `post_init` remembers the original `video_file` name; `post_save` detects a NEW/changed upload (ignores names ending `-faststart.mp4`), resets `video_status='pending'`, and calls `enqueue_video_optimization` which uses `transaction.on_commit` -> `dispatch_video_optimization` -> Celery task `content.optimize_video` on queue **`media`** (`retry=False`).
  2. `optimize_content_video` (soft limit = transcode budget + 120 s, `acks_late`, max_retries 2): downloads the file, probes duration, inspects MP4 atoms (`inspect_mp4`: faststart / fragmented fMP4), probes codecs (`needs_transcode`: non-H.264 video or non-AAC/MP3 audio). Already-good => mark `ready`; bad codecs => `transcode_h264` (capped 1920 on the long edge; audio-only re-encode keeps the picture); else `remux_faststart` (stream copy). Saves a new `<stem>-faststart.mp4` file, updates duration/status, deletes the original, then `enqueue_hls_packaging`.
  3. `package_content_hls` (task `content.package_video_hls`, queue `media`, max_retries 1): builds an ABR ladder (360p/480p/720p/1080p, only rungs <= source height; segment length `VIDEO_HLS_SEGMENT_SECONDS` default 4, preset `VIDEO_HLS_PRESET` default veryfast) into `content_hls/<content_id>/<generation>/`, uploads to default storage, sets `hls_playlist`/`hls_status='ready'`, deletes the previous generation. `ContentDetailSerializer.hls_url` returns the absolute playlist URL only when ready.
  4. `reprocess_video` admin action re-runs it (409 if `pending/processing`, 503 if the broker is unreachable, 400 if no file or `VIDEO_OPTIMIZATION_ENABLED` is false).
- `content/services.py` `StudyPlanService.generate_daily_items`: rule-based - up to 2 revision items for weak topics (`analytics.TopicMastery.mastery_level <= 2`) using published `revision` content, up to 5 unseen notes/pdf/revision/formula items for the course until the target minutes are met, then a practice-quiz placeholder item (no quiz FK). Also `get_next_content`, `get_revision_topics`.
- Management command `optimize_videos`: flags `--all`, `--content-id <uuid>`, `--dry-run`, `--sync` (inline, no Celery), `--hls-only`, `--status` (pipeline health). Backfills videos uploaded before the pipeline existed.

## Integrations / settings / env vars / feature flags
- Settings: `VIDEO_OPTIMIZATION_ENABLED` (default True), `VIDEO_HLS_ENABLED` (default True), `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `CELERY_BROKER_TRANSPORT_OPTIONS['visibility_timeout']` (env `CELERY_VISIBILITY_TIMEOUT`, 25200 s - must exceed the longest task), `STORAGE_BACKEND` (azure/s3/local) for `video_file`, `pdf_file`, HLS tree.
- Env (read directly via `os.environ`, not in settings.py): `FFMPEG_BINARY`, `FFPROBE_BINARY`, `VIDEO_REMUX_TIMEOUT` (3600), `VIDEO_TRANSCODE_TIMEOUT` (6 h), `VIDEO_HLS_PRESET`, `VIDEO_HLS_SEGMENT_SECONDS`.
- Requires the `ffmpeg`/`ffprobe` binaries on the media worker image and a worker consuming queue `media` (docker-compose service `celery-mediaworker`, `--queues=media`).
- Tenant feature flags `study`/`courses` gate UI only.

## Cross-app dependencies
- Imports: `core` (OrderedModel/TimeStampedModel, base viewsets, `IsCourseEditor`), `exams.models` (Topic, Subject, Course) and `exams.admin_views.TenantAdminModelViewSet`, `users.StudentProfile`, `gamification.services`, `analytics.services/models`.
- Imported by: `exams` (study progress counts, `course_copy`), `quiz`/`certificates`/`analytics` (progress), `coursegen` (creates Content), `notifications`.

## Tests (backend/content/tests_video_pipeline.py)
SimpleTestCase unit tests (no DB): ffmpeg progress-line parsing, task budgets (hard limit covers a full transcode, broker redelivery outlasts the limit), `run_with_progress` behaviour (monotonic progress never reaching 100, timeout enforcement, no pipe deadlock, stderr on failure, unknown duration fallback), `needs_transcode` decisions (browser-friendly left alone, audio-only mismatch spares the picture, undecodable video flagged, unreadable file does not claim a transcode). No API-level tests for content views.

## Gotchas / non-obvious conventions / risks
- **Content `slug` is globally unique** across tenants (cloning and admin serializer search globally); `Content.tenant` is inherited and often null - never filter content by `tenant=` directly.
- `AdminContentSerializer.courses` uses `Course.objects.all()` (not tenant-scoped) and `topic`/`subject` are unscoped PK fields: an admin/instructor can attach content to another tenant's subject/topic/course by passing its UUID; `TenantAdminModelViewSet.perform_create` only guards instructors' course ownership (after the write) and sets `tenant`, it does not validate the submitted `subject`'s tenant for admins (unverified by test; derived from code).
- `ContentProgressViewSet.create` does `get_or_create(content_id=<any uuid>)` without checking the content is visible/enrolled/tenant-matched, and `complete` then awards XP: a student can create progress rows for arbitrary content ids (including other tenants') and farm XP once per id. `ContentProgressSerializer` also exposes `is_completed`/`completed_at` as writable on PATCH, so completion can be set without XP via update; `complete` XP is only guarded by `is_completed`.
- `video_file` URLs (raw blob) and HLS segments are returned unauthenticated-capable (public container / permanent URL) - only PDFs are proxied through an authenticated endpoint. Draft/unpublished video URLs are visible only through the API, but the storage URL itself is not access-controlled.
- `AdminImageUploadView` has no size/type validation; extension comes from the client data-URL header.
- `Content.is_free`/`is_premium` are metadata only: no paywall logic in this app; access depends on enrolment.
- Redis visibility-timeout interplay: changing `CELERY_VISIBILITY_TIMEOUT` below the 6 h task budget causes duplicate encodes (documented in settings).
- Atomicity: `post_save` signal uses `queryset.update` + `transaction.on_commit`; if the broker is down the upload still succeeds with `video_status='pending'` forever (use `reprocess_video`/`optimize_videos` to recover).
- `retrieve` increments `views_count` with a read-modify-write (lost updates under concurrency) and saves twice (get_object called twice).
- `StudyPlanItemViewSet.complete` trusts client `actual_minutes` and `questions_count` (no int validation); `StudyPlan.xp_earned` is never incremented here.
- Migrations: 13 files; `0004_remove_video_content` is a data/schema removal of an older Video model (historic); `0011`-`0013` add the video pipeline fields (nullable/defaulted, safe).

## Key files
- `backend/content/models.py` - Content, ContentProgress, StudyPlan, StudyPlanItem.
- `backend/content/views.py` - learner viewsets (content, progress, study plans).
- `backend/content/admin_views.py`, `admin_serializers.py` - Content Builder CRUD, reprocess_video, image upload.
- `backend/content/serializers.py` - read serializers (`hls_url`, `has_pdf`).
- `backend/content/tasks.py` - `optimize_content_video`, `package_content_hls`, dispatch/enqueue helpers.
- `backend/content/hls.py` - ABR ladder build/upload/delete; `ffmpeg_utils.py` - progress-aware ffmpeg runner.
- `backend/content/signals.py` - triggers the pipeline on video upload.
- `backend/content/services.py` - `StudyPlanService`.
- `backend/content/management/commands/optimize_videos.py` - backfill/health command.
- `backend/content/tests_video_pipeline.py` - pipeline unit tests.
- `backend/content/urls.py` - routes.
