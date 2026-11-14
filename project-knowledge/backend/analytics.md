# analytics

Source: `main`, `backend/analytics/`. Verified from code unless marked "unverified".

- **Purpose**: Per-student learning analytics (topic mastery, subject performance, daily activity, streaks, weekly reports, real-time study timer + daily study goal) and tenant-admin aggregate dashboards.
- Mostly a write target for other apps (quiz, content, chatbot, gamification call `AnalyticsService`); its own API is largely read-only except the study timer / goal.

## Key models (`backend/analytics/models.py`; all `TimeStampedModel`, UUID pk, nullable `tenant` base FK)
| Model | Purpose / key facts |
|---|---|
| `TopicMastery` | per student+topic; **unique `(student, topic)`**. `mastery_level` 1-5 (Beginner..Master), `mastery_score` 0-100, totals, `accuracy_percentage`, `average_time_per_question`, `streak_correct`, `needs_revision`, `last_attempted` (auto_now). `update_mastery(correct,total,avg_time)` is **cumulative (adds)**: score = accuracy x (0.5 + 0.5 x min(1, total/50)); levels: >=90 L5, >=75 L4, >=60 L3, >=40 L2 else L1; `needs_revision` when level <= 2. avg time is a naive running mean of the previous avg and the new avg. |
| `SubjectPerformance` | per student+subject+**course (NOT NULL)**; **unique `(student, subject, course)`**; totals, accuracy, topics_attempted/mastered, overall_progress, total_study_minutes, average_speed (last four never updated by code found). Only written by `update_mock_test_analytics`. |
| `DailyActivity` | per student+date; **unique `(student, date)`**; study_time_minutes, questions_attempted/correct, notes_read, videos_watched, quizzes_completed, mock_tests_completed, `xp_earned`, `daily_goal_met`. Source of truth for period leaderboards (XP). |
| `Streak` | per student+course (course nullable; global streak uses `course=None`); **unique `(student, course)`** (note: with NULL course the DB unique does not prevent duplicates on most DBs). `current_streak`, `longest_streak(+start/end)`, `last_activity_date`, `total_active_days`. |
| `WeeklyReport` | **unique `(student, week_start)`**; study minutes, questions, accuracy, days_active, goals_met, weak_topics JSON (topic id strings), xp_earned, `rank_change` and `vs_last_week`/`topics_*` (never populated). |
| `StudySession` | per student+date; **unique `(student, date)`**; real-time timer: `total_seconds_today`, `goal_seconds` (copied from `StudentProfile.daily_study_goal_minutes`), `is_active`, `last_heartbeat`, `goal_achieved(_at)`, `goal_xp_awarded`. |

Migrations 0001-0006 (0003 StudySession, 0004 tenant, 0005 exam->course rename, 0006 alter course FKs: `Streak.course` nullable, `SubjectPerformance.course` required).

## API (prefix `/api/v1/analytics/`, `backend/analytics/urls.py`)
Student endpoints (`IsAuthenticated`; use `request.user.profile`; querysets filter by own student so no explicit tenant filter):
- Router: `topic-mastery/` (+ `weak_topics`, `strong_topics`, `by_subject?subject_id=`), `subject-performance/` (+ `by_course?course_id=`), `daily-activity/` (+ `today`, `weekly`, `chart_data?days=`), `streaks/` (+ `current?course_id=`), `weekly-reports/` (+ `latest` (creates/refreshes current-week report), `generate` POST). All `TenantAwareReadOnlyViewSet` with overridden `get_queryset`.
- `dashboard/` `DashboardView` -> `AnalyticsService.get_dashboard_stats(student, course_id)` (streak, today, weekly, mastery distribution, weak topics, profile XP/level).
- `study-timer/` `StudyTimerView`: GET state, POST start/resume session, PUT heartbeat `{elapsed_seconds}`, DELETE pause.
- `study-goal/` `StudyGoalView`: GET/PUT `daily_study_goal_minutes` (5..480).
Tenant-admin endpoints (`IsAuthenticated + IsTenantAdmin`, require `request.tenant`): `tenant-admin-stats/?days=` (1..365), `tenant-subject-stats/`, `tenant-leaderboard/?limit=`.

## Business logic (`backend/analytics/services.py`, class `AnalyticsService`, all static)
- `update_topic_mastery_from_attempt(attempt)`: groups `attempt.answers` by `question.topic`, calls `TopicMastery.update_mastery`. Used for both QuizAttempt and MockTestAttempt (bank answers only; inline `MockTestAnswer` ignored).
- `update_mock_test_analytics(attempt)`: topic mastery + `SubjectPerformance` accumulation using `attempt.mock_test.course`.
- `update_daily_activity(student, **kwargs)`: transactional get_or_create + `select_for_update`, adds integer kwargs (additive), sets `daily_goal_met` when `study_time_minutes >= student.daily_study_goal_minutes`, then `update_streak(student, today)` (global streak `course=None`). Every caller that passes `xp_earned` is adding to period-leaderboard XP.
- `get_dashboard_stats`: weekly = last 7 days; study time comes from `StudySession` (seconds) rather than DailyActivity.
- `generate_weekly_report` / `update_weekly_report`: aggregates DailyActivity (+ StudySession for minutes) for Monday..Sunday; `latest` endpoint lazily creates/refreshes. No scheduled job.
- `get_tenant_admin_stats(tenant, period_days)`: total students, active today, avg accuracy, total XP, level distribution, trend, growth vs previous window. `get_tenant_subject_performance`, `get_tenant_leaderboard` (by `StudentProfile.total_xp`).
- Study timer heartbeat (PUT): adds `elapsed_seconds` to the session; the first time total >= goal it awards daily-goal XP once per day: `25 + min(25, streak*3)` via `GamificationService.award_xp(..., 'daily_goal', ref=session.id, update_daily_activity=True)`, forces `update_streak`, sets `DailyActivity.daily_goal_met`; then also `update_daily_activity(study_time_minutes = elapsed//60 if >=60 else 0)`.
- No signals, no Celery tasks, no management commands in this app. (Quiz signals call into this app, see quiz.md.)

## Integrations / settings
- None beyond DB. Uses `StudentProfile` fields `daily_study_goal_minutes`, `total_xp`, `current_level`, `overall_accuracy`, `total_questions_attempted`, `total_correct_answers`, `total_study_time_minutes`, `xp_for_next_level`.

## Cross-app dependencies
- Imports: `core` (TimeStampedModel, TenantAwareReadOnlyViewSet, IsTenantAdmin), `exams` (Topic, Subject, Course), `users` (StudentProfile), `gamification.services` (award_xp in timer), `quiz.models` (Answer, lazily).
- Called by: `quiz` (signals + views: `update_topic_mastery_from_attempt`, `update_mock_test_analytics`, `update_daily_activity`), `content` (`content/views.py`, `content/services.py` read TopicMastery), `chatbot/views.py` (AI quiz -> `update_daily_activity`), `gamification` (DailyActivity for leaderboards, Streak/TopicMastery for badges, `_bump_daily_activity`), `community/services.py` (DailyActivity XP), `exams/views.py` (study leaderboard, DailyActivity), `users/views.py` (admin dashboards, unverified detail), `core.management.commands.seed_data`.

## Tests
None in `backend/analytics/`. `gamification/tests.py` indirectly touches nothing here.

## Gotchas / risks
- **Non-idempotent mastery updates + quiz signals => multiple counts per attempt** (see quiz.md Gotchas): inflated `total_questions_attempted` and distorted accuracy/volume factor in `TopicMastery`, inflated `SubjectPerformance` counts. Treat mastery numbers as approximate.
- `SubjectPerformance.course` NOT NULL vs rich mock tests having `course=None` -> likely IntegrityError in the signal path (unverified at runtime).
- `StudyTimerView.put`: `elapsed_seconds` is client-supplied, unvalidated and uncapped (and a non-int raises TypeError -> 500). A client can instantly "complete" the daily goal and farm the once-per-day XP, and inflate study time/`total_seconds_today`. Also `StudyGoalView.put` compares raw JSON value (`new_goal < 5`) so a string value raises 500.
- `StudySession.last_heartbeat` is `auto_now`, so any save (including DELETE pause) refreshes it; no server-side idle cut-off.
- Dates use `timezone.now().date()`; settings have `TIME_ZONE='Asia/Kolkata'`, `USE_TZ=True`, and `timezone.now()` is UTC, so "today" rolls over at 05:30 IST (UTC midnight), not IST midnight. Affects streaks, daily goals, DailyActivity and daily/weekly leaderboards (use `timezone.localdate()` to fix).
- Streak uniqueness: `unique_together (student, course)` with `course=NULL` is not enforced by Postgres/SQLite; `get_or_create(course=None)` race can create duplicates, and `check_and_award_badges` reads `Streak.objects.filter(student).first()` arbitrarily.
- Streak bonus for daily goal uses the highest `current_streak` across all Streak rows.
- `update_daily_activity` is called from the PUT heartbeat for every heartbeat (`study_time_minutes` only added when `elapsed >= 60`; sub-minute heartbeats are dropped from DailyActivity but counted in StudySession) so DailyActivity study time and StudySession time diverge; dashboard uses StudySession.
- `DashboardView` passes `course_id` string into `Streak.objects.filter(course=...)`; `None` filters the global streak row.
- `weekly` stats `days_active` counts DailyActivity rows (rows can exist with 0 activity because `_bump_daily_activity` creates them).
- `TopicMasteryViewSet` etc. inherit `TenantAwareReadOnlyViewSet` but override `get_queryset` -> no tenant filter, only student filter; non-student users (no `profile`) cause AttributeError.
- Admin `tenant-leaderboard` `limit` is unbounded `int()` (500 on non-int).

## Key files
- `backend/analytics/models.py` - models, mastery/streak update rules.
- `backend/analytics/services.py` - `AnalyticsService` (all business logic).
- `backend/analytics/views.py` - student + tenant-admin endpoints, study timer XP.
- `backend/analytics/serializers.py` - DRF serializers (dashboard/chart).
- `backend/analytics/urls.py` - routes.
