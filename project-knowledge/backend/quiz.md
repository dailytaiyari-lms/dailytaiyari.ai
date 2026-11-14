# quiz

Source: production branch `main`, `backend/quiz/`. Everything below verified from code unless marked "unverified".

- **Purpose**: Question bank, topic/subject/daily quizzes, full-length mock tests (legacy bank-question mocks, "rich" mocks with inline items incl. subjective + coding, and Previous Year Papers), student attempts, auto/manual grading, XP/analytics side effects, admin builders.
- Two parallel mock flows coexist: **legacy** (`start` / `submit`, bank questions only) and **rich** (`paper` / `start_rich` / `save_rich` / `submit_rich` / `run_item`, bank + inline `MockTestItem`). The rich flow is the current one; legacy endpoints are still live and weaker (see Gotchas).

## Key models (`backend/quiz/models.py`)
All inherit `core.models.TimeStampedModel` (UUID pk, nullable `tenant` FK, created/updated). `OrderedModel` adds `order`.

| Model | Purpose / notable fields |
|---|---|
| `Question` | Bank question. `question_type` in mcq, mcq_multi, true_false, numerical, fill_blank, match. `difficulty` easy/medium/hard. `status` draft/review/published/archived. FKs `topic`, `subject`, M2M `courses`. `correct_answer` = string index of correct option (mcq/true_false) or expected text (fill_blank). `numerical_answer`+`numerical_tolerance` (default 0.01). `marks` (1), `negative_marks` (0.25). Stats `times_attempted/times_correct`. `tags` JSON. **No required tenant**: tenant is the nullable base field. |
| `QuestionOption` | Ordered options (`option_text`, `option_image`, `is_correct`). |
| `Quiz` | `quiz_type` topic/subject/chapter/daily/custom/pyq; `status` draft/published/archived. **tenant required** (non-null FK), `course` required, `subject`/`topic` nullable. M2M `questions` through `QuizQuestion` (unique `quiz+question`). Flags: shuffle_*, `show_answer_after_each`, `allow_skip`, `is_free`, `is_daily_challenge`, `challenge_date`. Stats `total_attempts`, `average_score` (average never updated by code found). |
| `MockTest` | **tenant required**. Legacy `course` FK (nullable) + `courses` M2M (rich access control). `sections` JSON. M2M `questions` through `MockTestQuestion` (unique `mock_test+question`, `marks_override`/`negative_marks_override`, `section`). `status` draft/published/archived. `result_visibility` immediate/on_release + `results_released` bool. `start_deadline`, `fullscreen_required`, `max_attempts` (default 1), PYP fields (`is_pyp`, `pyp_year/shift/session/date`), `available_from/until` (never enforced), `negative_marking` (never used in grading), stats `total_attempts/average_score/highest_score`. |
| `MockTestItem` | Inline authored question (UUID pk). `item_type` mcq, mcq_multi, numerical, subjective, coding. Options stored as JSON `[{text,image,is_correct}]`. Subjective: `max_words/rubric/model_answer`. Coding: `allowed_languages`, `starter_code`, `time_limit_ms`, `memory_limit_mb`, `coding_test_cases` JSON (`stdin, expected_output, points, is_sample, explanation`). `is_auto_gradable`, `correct_option_indices` helpers. |
| `QuizAttempt` | student(`users.StudentProfile`), quiz, `status` in_progress/completed/abandoned/timed_out, counters, `marks_obtained` (can be negative), `percentage` (floored at 0), `xp_earned`, proctoring counters (`proctoring_violations`, `tab_switch_count`, `fullscreen_exit_count`, `restricted_shortcut_count`, `last_proctoring_event_at`). `calculate_results()` recomputes from `answers` and saves. |
| `MockTestAttempt` | Same status enum; `section_results` JSON, `rank`/`percentile` (**never computed anywhere**), `grading_status` auto_graded / pending_manual / graded, `xp_earned`. |
| `Answer` | Bank-question answer linked to EITHER `quiz_attempt` OR `mock_test_attempt` (both nullable). `check_answer(marks_override, negative_marks_override)` grades mcq/true_false (string equality of `selected_option` vs `correct_answer`), numerical (abs diff <= tolerance), fill_blank (case-insensitive trim). **mcq_multi and match are never graded correct.** Wrong = `-negative_marks`; unanswered rows submitted blank are also penalised. |
| `MockTestAnswer` | Answer to a `MockTestItem` (unique `attempt+item`): `selected_options`, `numerical_answer`, `answer_text`, `code`, `language`, `coding_results`, `passed_count/total_count`, `is_auto_graded`, `needs_manual_grading`, `marks_obtained`, `max_marks`, `feedback`, `graded_by`, `graded_at`. |
| `QuestionReport` | Student-reported problem on a question (9 report types; status pending/reviewing/resolved/dismissed). Duplicate open report per student+question blocked in view. |

Migrations 0001-0012. 0005 added tenant to all models; 0007 backfills tenant on Quiz/MockTest (falls back to the first active tenant when the course has none) and makes it required; 0008 rename exam->course; 0010-0012 added rich mock fields, `max_attempts`, proctoring. No quiz tests exist.

## API (prefix `/api/v1/quiz/`, `backend/quiz/urls.py`)
Student routes (all `IsAuthenticated`, any role at permission level but code uses `request.user.profile`, so non-students 500/AttributeError on start/submit):

| Route | View | Notes |
|---|---|---|
| `questions/` (read-only), `questions/by_topic/` | `QuestionViewSet` | published only, tenant + enrolled-course scoped. `?with_answer=<anything>` on retrieve returns `QuestionWithAnswerSerializer` (correct answer + explanation) for ANY accessible published question, even before attempting. |
| `quizzes/`, `filter_options/`, `daily_challenge/`, `{id}/my_attempts|start|proctoring_event|submit|leaderboard` | `QuizViewSet` | List hides daily challenges unless `is_daily_challenge` param passed. |
| `mock-tests/`, `filter_options/`, `{id}/my_attempts|start|submit|leaderboard`, `{id}/paper|start_rich|save_rich|submit_rich|run_item`, `attempts/{attempt_id}/review/` | `MockTestViewSet` (excludes `is_pyp`) | rich review gated by `results_visible_for`. |
| `pyp/` (+ `by_year`, `filter_options`) | `PreviousYearPaperViewSet(MockTestViewSet)` | inherits every mock action incl. rich flow. Filters `year`, `session`. |
| `attempts/` (+ `recent`, `{id}/review`) | `QuizAttemptViewSet` | own attempts only. |
| `mock-attempts/` (+ `recent`, `{id}/review`) | `MockTestAttemptViewSet` | own attempts only. |
| `reports/` (+ `my_reports`) | `QuestionReportViewSet(TenantAwareViewSet)` | create report; queryset = own reports. |

Admin routes `/api/v1/quiz/admin/` (router `admin_router`):
- `quizzes/` `AdminQuizViewSet`, `questions/` `AdminQuestionViewSet` - extend `exams.admin_views.TenantAdminModelViewSet` (permission `IsCourseEditor`: tenant admins + instructors assigned to the course). Tenant scoping via `course__tenant` / `subject__course__tenant`; instructors limited by `course_lookup`. `questions/?quiz=<id>` returns questions in quiz order. Writable nested options (matched by id), base64 images, `quiz` write-only field links question into quiz. Serializer `validate()` rejects cross-tenant topic/subject/quiz/course.
- `mock-tests/` `AdminMockTestViewSet` - `IsTenantAdmin` only (role `admin`; instructors excluded). Extra actions: `bank_questions`, `add_bank_questions` (only questions with `subject__course__tenant == tenant`), `remove_bank_question`, `recompute_marks`, `pending-grading`, `{id}/submissions`, `attempts/{attempt_id}` (grading view), `grade-answer` (POST answer_id, marks 0..max, feedback), `finalize-attempt` (POST attempt_id; marks `graded`, awards deferred XP).
- `mock-items/` `AdminMockTestItemViewSet` - `IsTenantAdmin`; `?mock_test=` filter; `reorder`; create/update/delete recompute `MockTest.total_marks`.

## Business logic
- **Quiz submit** (`QuizViewSet.submit`): get-or-create in-progress attempt (no attempt needed beforehand) -> per answer `Answer.get_or_create` + `check_answer` + bump `Question.times_attempted/correct` -> `attempt.calculate_results()` -> XP only on **first completed attempt** per student+quiz (`core.utils.calculate_xp_for_quiz`: 5 XP/question x accuracy, daily x1.5, caps `QUIZ_XP_CAP=25`, `QUIZ_XP_CAP_DAILY_CHALLENGE=40`) -> `GamificationService.award_xp(..., 'quiz_complete', ref=attempt.id)` -> `AnalyticsService.update_daily_activity` (study minutes, questions, `quizzes_completed` only if xp>0) -> student totals -> `update_topic_mastery_from_attempt` -> `check_and_award_badges` with context (perfect_quiz, speed_quiz, early/night/weekend) -> `Quiz.total_attempts += 1`.
- **Legacy mock submit** (`MockTestViewSet.submit`): needs existing in_progress attempt; same pattern, XP = quiz formula x 2 (max 50, first completion only), `update_mock_test_analytics`, badges, `highest_score`. Percentage uses sum of `effective_marks` of linked bank questions.
- **Rich mock flow**: `paper` (merged ordered paper via `mock_grading.build_paper`, no answers), `start_rich` (access check, resumes in-progress, auto-submits if server timer expired, enforces `max_attempts` and `start_deadline`, sets attempt tenant), `save_rich` (autosave ungraded; auto-finalizes if expired), `submit_rich` (grade then `_finalize_rich_attempt`), `run_item` (runs only `is_sample` cases of a coding item; 503 on `coding.services.EngineError`). Timer is server-authoritative: `expires_at = attempt.started_at + duration_minutes`; `time_taken` capped at duration.
- `_finalize_rich_attempt`: regrade everything, aggregate, `grading_status = pending_manual` if any `needs_manual_grading`, status `timed_out` or `completed`. XP awarded (x2 formula) only when not pending manual and no other finished attempt exists; otherwise deferred to admin `finalize-attempt`.
- **Access rule** (`mock_grading.accessible_mock_tests_q` / `student_can_access`): linked `courses` M2M non-empty -> must be enrolled in one; else legacy `course` -> enrolled; else **open to every student in the tenant**. Student course scope = `_get_student_course_ids` (approved + active enrollments in `status='active'` courses; three-valued: `None` non-student, `[]` none, list).
- **Grading helpers** (`backend/quiz/mock_grading.py`): `grade_item_answer` (mcq/mcq_multi exact set match; numerical tolerance; coding via `coding.services.run_against_cases` with hidden-IO never revealed; falls back to `needs_manual_grading` if `CODING_ENABLED` false / engine error; subjective always manual), `recompute_attempt`, `results_visible_for`, `build_review`.
- **Daily challenge**: lazy-built on `GET quizzes/daily_challenge/` (`_build_daily_challenge`: 10 questions, deterministic rotation by `today.toordinal() % pool`, `get_or_create` with no DB unique constraint) + management command.
- **Signals** (`quiz/signals.py`, wired in `QuizConfig.ready`): `post_save` on `QuizAttempt` / `MockTestAttempt` with `status == 'completed'` call `AnalyticsService.update_topic_mastery_from_attempt` / `update_mock_test_analytics`. See Gotchas: double counting.
- **Management command**: `generate_daily_challenges [--days N] [--force]` creates a daily Quiz per (tenant x course) from 10 random published questions (needs >= 5). Not scheduled anywhere in repo (no Celery beat / cron found).
- **Throttles**: `QuizSubmitThrottle` (3000/h, `UserRateThrottle` subclass), `ProctoringEventThrottle` (120/min). `quiz_submit: 60/hour` in REST_FRAMEWORK rates is unused.
- Leaderboards (`quizzes|mock-tests/{id}/leaderboard`): best attempt per student, top 50 (scans first 200 attempts), tenant filtered via `student__user__tenant`.

## Integrations / settings / env vars
- `CODING_ENABLED` (default True), `PISTON_URL` (code execution engine, via `coding.services`).
- `TenantMiddleware` supplies `request.tenant`; `TenantAwareReadOnlyViewSet` returns `.none()` without tenant.
- Frontend media: images stored under `questions/`, `explanations/`, `options/`, `mock_items/` (served via `/media/`).

## Cross-app dependencies
- Imports: `core` (TimeStampedModel, OrderedModel, TenantAware viewsets, `IsTenantAdmin`, `core.utils.calculate_xp_for_quiz`, `core.serializer_fields.Base64ImageField`), `exams` (Topic/Subject/Course, `TenantAdminModelViewSet`, `BuilderPagination`), `users` (StudentProfile, CourseEnrollment), `analytics.services`, `gamification.services/models`, `coding.services` + `coding.languages`.
- Imported by: `mockgen` (MockTest/MockTestItem, `recompute_mock_total`), `coursegen` (apply/material/schema create Question/Quiz), `exams` (study views use Quiz/QuizAttempt; course_copy; seeder), `certificates` (progress), `chatbot` (context), `core.management.commands.seed_data`.

## Tests
None in `backend/quiz/`. Indirect coverage only: `mockgen/tests.py` exercises MockTest/MockTestItem apply paths; `gamification/tests.py` covers `calculate_xp_for_quiz` caps.

## Gotchas / tech debt / risks
- **Double/triple analytics counting**: `update_topic_mastery_from_attempt` is not idempotent (`TopicMastery.update_mastery` adds to totals each call). Quiz submit triggers it via the `post_save` signal on every save of a completed attempt (`calculate_results()` save, then `attempt.save()` after XP) AND an explicit call => ~3x per submit. Legacy mock: signal on each completed save + explicit `update_mock_test_analytics` (also inflates `SubjectPerformance`). Rich flow: signal fires on each completed save (`attempt.save()`, `save(update_fields=['xp_earned'])`, plus admin `grade_answer`/`finalize_attempt` saves) with no explicit call. `timed_out` attempts never trigger the signal.
- **Likely crash path (unverified at runtime)**: `update_mock_test_analytics` does `SubjectPerformance.get_or_create(course=mock_attempt.mock_test.course)` but `SubjectPerformance.course` is NOT NULL and rich mocks have `course=None` (links via `courses` M2M) -> IntegrityError inside the post_save signal when a rich mock has bank questions.
- Rich flow does NOT update `DailyActivity`/streaks, `StudentProfile.total_questions_attempted/total_correct_answers/total_study_time_minutes`, or run badge checks (only legacy flow does). So rich mocks don't count toward streaks/leaderboard activity (only XP via `award_xp`, which bumps `DailyActivity` unless type in `_SKIP_DAILY_ACTIVITY_TYPES` = quiz_complete, mock_complete -> **mock XP from the rich flow never reaches DailyActivity/period leaderboards**).
- **Result-visibility bypass**: `/mock-attempts/{id}/` and `/mock-attempts/{id}/review/` (and legacy `submit` response) return answers with correct options/explanations for any `completed` attempt regardless of `result_visibility`/`results_released`/`pending_manual`. Only `mock-tests/attempts/{id}/review/` honours `results_visible_for`.
- Legacy `start`/`submit` ignore `max_attempts`, `start_deadline`, server timer, tenant-open access check (only queryset scoping). `available_from/available_until`, `MockTest.negative_marking`, `is_free` are not enforced in views. Quiz duration is never enforced server-side; `time_taken_seconds` and thus `speed_quiz` badge are client-supplied.
- Quiz/legacy submit accept any `question_id` (`Question.objects.get(id=...)`, not restricted to the quiz/mock or tenant) so a student can feed arbitrary questions and skew `Question.times_*` stats. Stats updates are read-modify-write (`times_attempted += 1`), racy.
- No locking on attempt finalization: concurrent double `submit_rich` could double-award XP and double-increment `MockTest.total_attempts` (guard is only an in_progress read).
- `with_answer` query param on `questions/{id}/` leaks the answer key to any enrolled student.
- Quiz attempts/answers created by legacy flows have NULL tenant (only rich `MockTestAttempt` sets tenant); tenant scoping for attempts relies on `student__user__tenant`.
- `QuizAttemptViewSet`, `MockTestAttemptViewSet`, `QuestionReportViewSet` override `get_queryset` and thus skip `TenantAwareViewSet` tenant filtering (they scope by student instead).
- `generate_daily_challenges` loops every Tenant x every (featured) Course without checking `course.tenant == tenant` -> creates cross-tenant junk quizzes; also uses `total_marks = n*4` while the lazy builder uses `n` (inconsistent). Lazy builder has no unique constraint (duplicates possible under concurrency).
- `filter_options` quiz_types references `'mixed'` which is not a `Quiz.QUIZ_TYPES` value (`custom`/`chapter` are missing).
- `MockTestAttempt.rank/percentile` and `Quiz.average_score`/`MockTest.average_score` are never written.
- `AdminMockTestItemViewSet.perform_create` verifies the target mock test belongs to the tenant; `AdminMockTestSerializer.validate` checks `course`/`courses` tenant. `AdminMockTestViewSet` has no instructor support (role `admin` only), unlike quiz/question admin.
- Admin `recompute_mock_total` counts only inline items + bank questions; `MockTest.sections` is a free-form JSON and not validated.

## Key files
- `backend/quiz/models.py` - all models, `Answer.check_answer`.
- `backend/quiz/views.py` - student API (quiz/mock/PYP, rich flow, timers, XP).
- `backend/quiz/mock_grading.py` - access Q, paper builder, item grading, coding grading, review builders.
- `backend/quiz/admin_views.py` - quiz/question CRUD, rich mock builder, manual grading, finalize.
- `backend/quiz/admin_serializers.py` - writable serializers with cross-tenant validation.
- `backend/quiz/serializers.py` - student serializers (note answer-bearing serializers).
- `backend/quiz/signals.py` - analytics post_save hooks.
- `backend/quiz/management/commands/generate_daily_challenges.py` - batch daily challenges.
- `backend/core/utils.py` - `calculate_xp_for_quiz`, caps.
