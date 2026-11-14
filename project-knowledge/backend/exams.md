# exams

(Despite the name this app is the **course** catalogue/curriculum. It was renamed Exam -> Course in migration `0007_rename_exam_to_course`; docstrings still say "exam". URL prefix is `/api/v1/courses/`.)

- **Purpose**: tenant-owned course hierarchy `Course -> Subject -> Chapter -> Topic (via ChapterTopic)`, the student "Study flow" APIs with per-subject/chapter progress and sequential chapter unlock, course visibility rules (hidden courses), the admin Course Builder CRUD (tenant admins + assigned instructors), deep course copy, and syllabus seeders (JEE Main, NEET).

## Key models (backend/exams/models.py)
- `Course(TimeStampedModel)`: `tenant` FK (REQUIRED here, related_name `courses`, CASCADE), `name`, **`code` unique GLOBALLY (not per tenant)**, `description`, `course_type` competitive|board|entrance|government|skill, `icon`, `thumbnail`, `color`, `status` active|coming_soon|inactive, `is_featured`, `is_hidden` (hide from catalogue and non-enrolled students; approved enrolled students still have access), `duration_minutes`, `total_marks`, `negative_marking`, `negative_marking_ratio` (0.25), denormalised `total_students`, `total_questions` (never updated by code), pricing (`pricing_type` free|paid, `price`, `original_price`, `currency` INR; props `is_free`, `discount_percent`), marketing (`subtitle`, `highlights` JSON list, `refund_policy`), certificate (`certificate_enabled`, `certificate_template` classic|modern|elegant|minimal), `sequential_chapter_unlock`, `instructors` M2M users.User (`limit_choices_to role=instructor`, related_name `instructing_courses`).
- `Subject(OrderedModel)`: `course` FK (related_name `subjects`), `name`, `code`, `icon` (string), `color`, `weightage`, `total_topics`, `total_questions` (denormalised, unmaintained). Unique `(code, course)`. One subject belongs to exactly one course.
- `Topic(OrderedModel)`: `subject` FK, `parent_topic` self-FK (subtopics), `name`, `code`, `difficulty` easy|medium|hard, `importance` low|medium|high|critical, `estimated_study_hours`, `courses` M2M through `TopicCourseRelevance`, `total_questions`, `total_content`.
- `TopicCourseRelevance`: topic, course, importance, `average_questions`, `marks_weightage`. Unique `(topic, course)`.
- `Chapter(OrderedModel)`: `subject` FK (related_name `chapters`), `name`, `code`, `grade`, `book_reference`, `estimated_hours`; topics via `ChapterTopic`.
- `ChapterTopic(OrderedModel)`: chapter, topic, `order`. Unique `(chapter, topic)`. The order here is what students follow inside a chapter.
- Tenant scoping: only `Course.tenant` is reliable. `Subject/Topic/Chapter/ChapterTopic` inherit a NULLABLE `tenant` (legacy rows may be null); all views scope through `course__tenant` / `subject__course__tenant`.
- Enum/state facts: course visibility depends on `status='active'` plus `is_hidden`; access depends on `users.CourseEnrollment` `status='approved' & is_active=True`.

## API (prefix `/api/v1/courses/`; X-Tenant-ID required)
Public/learner routes (`backend/exams/urls.py`, `views.py`):
- `''` `CourseViewSet` (ReadOnly, **AllowAny**, only `status='active'` courses, filtered by `visible_courses_for_request`; actions `subjects`, `topics`; list serializer `CourseListSerializer`, detail `CourseDetailSerializer` includes nested curriculum subjects/chapters). Search `name, code`; filter `course_type, is_featured`.
- `subjects/`, `topics/`, `chapters/` (`SubjectViewSet`, `TopicViewSet`, `ChapterViewSet`; ReadOnly, AllowAny, limited to courses visible to the requester; for authenticated users without `?course|subject` param they are further narrowed to enrolled courses). Actions: subject `topics`, `chapters`; topic `subtopics`.
- `available-for-enrollment/` `AvailableCoursesForEnrollmentView` (AllowAny): public catalogue with instructors, pricing, `enroll_mode` (`request|self|payment`).
- `study/courses/` -> approved + pending courses for the student. `study/subjects/?course_id=` -> subjects with progress (needs approved enrolment else 403 "Enrollment pending admin approval"). `study/chapters/<subject_id>/` -> chapters + topics + per-chapter progress + `is_locked` (sequential unlock). `study/chapter/<chapter_id>/` -> topics with reading/videos/quizzes/assignments/coding/labs and the student's progress. `study/leaderboard/?scope=subject|chapter|quiz|course&scope_id=` (top 20). All `IsAuthenticated`; chapters/chapter detail use `can_access_course` (403 "Enrollment required").
- `explorer/` `TenantContentExplorerView`: admin/superuser only (role check inside view) returns every ACTIVE course with subjects and chapters. **Not tenant-filtered** (see gotchas).
- Admin Course Builder at `admin/` (`admin_views.py`, router): `courses`, `subjects`, `chapters`, `topics` (`TenantAdminModelViewSet`, `permission_classes=[IsCourseEditor]`, `BuilderPagination` 200/2000). Extra actions: `reorder` (POST `{order:[ids]}`; for topics with `chapter` in the body it reorders `ChapterTopic`), courses `copy` (POST `{name}`; admin only; quota-checked), courses `instructors` (admin only list of tenant instructors). Content builder (`content` app) reuses `TenantAdminModelViewSet`.
- Builder permission model: admins full access; instructors see/edit only courses in `instructing_courses` (queryset filter + object-level check + create guard that deletes the row and 403s if the new object is outside their courses); only admins create/delete/copy courses, and instructors cannot change `instructors` or `is_hidden`. `perform_create` stamps `tenant`; new rows are appended to the end of sibling `order` (`order_scope_field`).

## Business logic
- `exams/access.py`: `has_approved_course_enrollment`, `can_access_course(user, course, tenant)` (same tenant + admin/superuser, or assigned instructor, or approved enrolment), `visible_courses_for_request(qs, request)` (anon: not hidden; admin: all; instructor: not hidden or assigned; student: not hidden or approved-enrolled).
- Study progress (views.py): per subject/chapter combines published `content.Content` (reading types notes/pdf/revision/formula + video), `quiz.Quiz` + completed `QuizAttempt`, `assignments`, `coding` (fully-passed submission), `notebooks` (labs). Many sequential queries per subject/chapter (N+1-ish); heavy for big courses.
- Sequential unlock: when `Course.sequential_chapter_unlock`, a chapter is locked until all preceding chapters (by `order`) that have content are fully completed. Locking is advisory in `study/chapter/` (returns topics with `locked` + `locked_by`; UI prevents entry) and is NOT enforced by content/quiz APIs.
- `exams/course_copy.py` `clone_course(source, new_name)`: single transaction, deep-clones authored graph under the same tenant: Course (copy status forced `inactive`, `is_featured=False`, `total_students=0`, instructors carried over), Subjects, Topics (parents first), TopicCourseRelevance, Chapters, ChapterTopic, `content.Content` (new unique slug, counters reset, courses M2M set to new course), `quiz` Questions + Options, Quizzes + QuizQuestions, MockTests (+ questions/items, `sections` JSON `subject_id` remapped, `total_attempts=0`, `results_released=False`), `coding` CodingProblem + TestCase, `assignments.Assignment`, `liveclass.LiveClass`. Student data is not copied. **Not copied: notebooks/labs (`notebooks.Notebook`), hackathons, community, certificates config beyond Course fields.** New course `code` = slugified name made unique globally (max 50 chars).
- Syllabus seeding (management commands): `seed_jee_main`, `seed_neet` (args `--course-code`, `--tenant "<tenant name>"`, default tenant name "Test Academy"; idempotent) using `_seeder.seed_syllabus` + `_jee_main_syllabus.py`/`_neet_syllabus.py`: creates course, subjects, chapters, topics, notes/formula content, topic quizzes and mock tests with GENERIC auto-generated placeholder question text (not real exam content).
- No signals, no Celery tasks.

## Integrations / settings / env vars / feature flags
- None specific. Tenant plan cap `max_courses` via `tenant.can_add('courses')` in builder create/copy (also `coursegen/apply.py`). Tenant feature keys `courses`, `study` are frontend-only.

## Cross-app dependencies
- Imports: `core` (TimeStampedModel/OrderedModel, TenantAwareReadOnlyViewSet, IsCourseEditor), `users.models.CourseEnrollment/StudentProfile`, and lazily `content`, `quiz`, `assignments`, `coding`, `notebooks`, `analytics`, `gamification`, `liveclass` (progress aggregation, copy, leaderboard).
- Imported by: nearly every content-bearing app (FKs to `exams.Course/Subject/Topic/Chapter`), `users` (enrolment), `payments` (course price), `certificates`, `coursegen`.

## Tests (backend/exams/tests.py)
`HiddenCourseVisibilityTests`: hidden course invisible to anonymous/non-enrolled users in catalogue + direct URLs (detail, subjects, topics, chapters); enrolled students and admins/assigned instructors can see it; study chapters need approved+active enrolment; admin cannot open another tenant's subject/chapter; hidden/pending/inactive enrolments absent from study courses; non-enrolled student cannot retrieve hidden-course content.

## Gotchas / non-obvious conventions / risks
- **`Course.code` is globally unique, not per tenant** - two tenants cannot both create `neet`; seeders default to code `neet` and will collide/reuse across tenants. Same for `Content.slug`.
- **`TenantContentExplorerView` has no tenant filter** (`Course.objects.filter(status='active')`): any tenant admin calling `/courses/explorer/` receives every tenant's active courses (full `CourseSerializer` fields incl. pricing, refund policy, instructors names, counts) with nested subjects and chapters - cross-tenant data leak (verified from code, not run). Related unscoped lookups (guarded elsewhere): `StudySubjectsView` loads `Course.objects.get(pk=...)` without tenant but then requires an approved enrolment; `StudyLeaderboardView` loads `Chapter.objects.get(pk)` / `Course.objects.get(pk)` unscoped but filters the participants by tenant.
- Public viewsets (`CourseViewSet`, `SubjectViewSet`, `TopicViewSet`, `ChapterViewSet`) are `AllowAny`: anonymous visitors with a valid tenant id can read the curriculum of any non-hidden active course (curriculum structure, not content bodies).
- Router quirk: `router.register(r'', CourseViewSet)` is registered before `subjects/`, `topics/`, `chapters/`; with DRF's default lookup regex `[^/.]+` the course detail route can swallow `/courses/subjects/`, `/courses/topics/`, `/courses/chapters/` (list endpoints) - unverified at runtime; the frontend only uses nested detail routes (`subjects/<id>/topics/`, `topics/<id>/`), which do not collide. (`content.ContentViewSet` avoids this with `lookup_value_regex`.)
- Denormalised counters (`Course.total_students/total_questions`, `Subject.total_*`, `Topic.total_*`) are never updated by code; do not trust them.
- `Course.is_hidden` is enforced in catalogue/detail/study listing and enrolment creation, but access to content uses enrolment status only.
- Migration `0006_exam_tenant_required_backfill` is a data migration that `get_or_create`s a "Default Tenant" with a hardcoded UUID and subdomain `default`, so every fresh database (incl. test DBs and new environments) contains that tenant; later migrations rename models/fields (0007).
- Instructors' `instructing_courses` is the only source for instructor scoping; a builder `ModelViewSet` supports DELETE of subjects/chapters/topics (cascade). Topic delete explicitly removes `ChapterTopic` rows.
- Study-flow queries are heavy (dozens of COUNT queries per subject/chapter) and uncached.
- `StudyChaptersView`/`StudyChapterDetailView` use `student = request.user.profile`; admins/instructors have profiles, so previews work, but `ContentProgress` queries then return that admin's own empty data.

## Key files
- `backend/exams/models.py` - Course, Subject, Topic, TopicCourseRelevance, Chapter, ChapterTopic.
- `backend/exams/views.py` - public viewsets, catalogue, study-flow, leaderboard, explorer.
- `backend/exams/admin_views.py` - Course Builder base viewset + course/subject/chapter/topic admin CRUD, reorder, copy.
- `backend/exams/access.py` - visibility and access rules.
- `backend/exams/course_copy.py` - deep clone.
- `backend/exams/serializers.py`, `admin_serializers.py` - read and builder serializers (`AdminTopicSerializer` can link a topic to a chapter on write).
- `backend/exams/urls.py` - routes (`admin/` router + learner router).
- `backend/exams/management/commands/seed_jee_main.py`, `seed_neet.py`, `_seeder.py`, `_jee_main_syllabus.py`, `_neet_syllabus.py` - syllabus seeders.
- `backend/exams/tests.py` - visibility tests.
