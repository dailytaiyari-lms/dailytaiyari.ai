# gamification

Source: `main`, `backend/gamification/` + `backend/docs/XP_ARCHITECTURE.md`, `XP_CALCULATION_SUMMARY.md`. Verified from code unless marked "unverified".

- **Purpose**: XP economy (awards, levels, transaction ledger), badges, period leaderboards (computed live from `analytics.DailyActivity`), and challenges.
- The central entry point is `GamificationService.award_xp`; every XP source in the platform funnels through it (except community, which has its own `CommunityXPService`).

## Key models (`backend/gamification/models.py`; `TimeStampedModel` base: UUID pk, nullable `tenant`)
| Model | Purpose / key facts |
|---|---|
| `Badge` | name, description, `category` streak/quiz/mastery/milestone/special, `rarity`, icon/color/image, `requirements` JSON (single key, e.g. `{"streak_days": 7}`), `xp_reward`, `is_active`, `is_secret`. **No tenant scoping in practice** (global). |
| `StudentBadge` | **unique `(student, badge)`**; `progress` JSON, `is_complete`. |
| `XPTransaction` | ledger: `transaction_type` choices (quiz_complete, mock_complete, content_complete, ai_quiz, coding_solved, assignment_graded, notebook_graded, daily_goal, streak_bonus, badge_earned, level_up, referral, challenge_win, community, manual), `xp_amount` (can be negative), `reference_id` UUID (attempt/session/submission id), `balance_after`. |
| `LeaderboardEntry` | snapshot table, **unique `(student, course, period, period_start)`**, period daily/weekly/monthly/all_time, rank fields. **Effectively unused**: live endpoints compute from DailyActivity; only `GamificationService.update_leaderboard` (never called) and `seed_data` write it. |
| `Challenge` | type daily/weekly/event/competition, `status` upcoming/active/ended, optional `course`, window, `goal` JSON, `xp_reward` (100), `badge_reward`, counters. |
| `ChallengeParticipation` | **unique `(student, challenge)`**; `progress` JSON, `is_completed`, `xp_claimed`, `badge_claimed`, `final_rank`. |

Migrations 0001-0009 (several only alter `transaction_type` choices; 0004 adds tenant; 0006 rename exam->course). No RunPython seeding: **badges and challenges are never created by migrations**; only `core/management/commands/seed_data.py` (dev seed) and Django admin create them. Production needs them seeded manually or badges silently never award.

## API (prefix `/api/v1/gamification/`, `backend/gamification/urls.py`; all `IsAuthenticated`, student-oriented via `request.user.profile`)
- `leaderboard/` `LeaderboardView` (GET `period` daily|weekly|monthly|all_time, `course_id`, `limit` default 50) -> `{entries, user_rank, total_participants}`; requires `request.tenant` (400 otherwise).
- `badges/` `BadgeViewSet` (read-only; active non-secret + earned secret via `.union()`), `my-badges/` `StudentBadgeViewSet` (+ `check_new` POST: runs badge check with empty context), `xp-history/` `XPTransactionViewSet` (+ `summary`), `challenges/` `ChallengeViewSet` (+ `active`, `{id}/join` POST), `my-challenges/` `ChallengeParticipationViewSet` (+ `{id}/claim_rewards` POST).
- There is no tenant-admin API for badges/challenges (Django admin only; `gamification/admin.py` registers all models).

## Business logic (`backend/gamification/services.py`, `GamificationService`)
- `award_xp(student, xp_amount, transaction_type, description, reference_id, update_daily_activity=True)`: in `transaction.atomic()` locks `StudentProfile` row (`select_for_update`), `total_xp = max(0, total_xp + amount)`, recalculates level via `StudentProfile.calculate_level()` (100 XP for L1->L2, each next level x1.5, int-truncated), grants **level-up bonus `LEVEL_UP_BONUS_PER_LEVEL=20` x each new level number** as a separate `level_up` transaction, writes `XPTransaction` (`balance_after`), updates caller's in-memory student. DailyActivity bump (`_bump_daily_activity`, clamped >= 0 with `Greatest`) is **skipped for `quiz_complete` and `mock_complete`** (`_SKIP_DAILY_ACTIVITY_TYPES`) because quiz views add XP via `AnalyticsService.update_daily_activity`; level-up bonus always bumps.
- `check_and_award_badges(student, context)`: loads all active badges not yet earned; matches on the first recognised requirement key: `streak_days`, `quizzes_completed`, `min_accuracy`, `total_xp`, `topics_mastered` (level>=4), `questions_answered`, `perfect_quiz` (needs context + count), `speed_quiz`/`early_study`/`night_study`/`weekend_study`/`comeback` (context-only), `mock_tests_completed`, `top_10` (daily tenant rank <= 10), `physics_mastery`/`chemistry_mastery`/`biology_mastery` (topic mastery by subject-name substring). Creates `StudentBadge` rows then one `badge_earned` award for the summed `xp_reward`. Unknown requirement keys never qualify. Called from quiz submit (legacy flows) and `check_new`.
- `get_leaderboard` / `get_student_rank`: grouped SQL over `DailyActivity` (period bounds: daily = today, weekly = Monday-Sunday, monthly = calendar month, all_time = no bound), tenant scoped (`student__user__tenant`), optional course via enrolled-student-id subquery, sorted by XP then accuracy, rows with zero XP and zero questions excluded. `rank_change` is hard-coded 0 (TODO).
- `update_leaderboard`: per-student loop writing `LeaderboardEntry` (dead code path; not scheduled).
- `claim_rewards`: awards `challenge.xp_reward` as `challenge_win` (ref=challenge.id) once (`xp_claimed > 0` guard) and badge via `get_or_create`.
- XP sources (from `docs/XP_ARCHITECTURE.md`, cross-checked): content complete (notes 5, video 8, pdf 6; `content/views.py`), quiz (5 x questions x accuracy, cap 25, daily x1.5 cap 40, first completion only), mock (same x2, max 50, first completion only; rich mocks with subjective items defer XP to admin finalize), AI quiz (`chatbot`: cap 25/attempt, 75/day), community (`CommunityXPService`, 2-20 per action, idempotent flags), daily goal (analytics study timer: 25 + min(25, 3 x streak)), assignment graded (`core.utils.calculate_xp_for_assignment`: `ASSIGNMENT_XP_MAX=30`, `ASSIGNMENT_XP_MIN=5`), coding solved (`coding/grading.py`), notebook graded (`notebooks/grading.py`), badges, level-up, challenge claims. Callers of `award_xp`: analytics/views, assignments/admin_views, chatbot/views, coding/grading, content/views, gamification/views + services, notebooks/grading, quiz/views + quiz/admin_views.
- No Celery tasks, signals, or management commands in this app.

## Integrations / settings
- None external. Constants live in `core/utils.py` (`QUIZ_XP_CAP`, `QUIZ_XP_CAP_DAILY_CHALLENGE`, `ASSIGNMENT_XP_*`, `calculate_streak_bonus` (unused as a standalone award)), `chatbot/models.py` (`AI_QUIZ_XP_CAP_PER_ATTEMPT`, `AI_QUIZ_XP_DAILY_CAP`).

## Cross-app dependencies
- Imports: `core` (TimeStampedModel, TenantAwareReadOnlyViewSet), `exams.Course`, `users` (StudentProfile, CourseEnrollment), `analytics.models` (DailyActivity, Streak, TopicMastery), `quiz.models` (QuizAttempt, MockTestAttempt).
- Imported by: `quiz`, `analytics`, `assignments`, `content`, `chatbot`, `coding`, `notebooks`, `community` (parallel `CommunityXPService`, not via this service), `exams` (study leaderboard uses `XPTransaction.reference_id`), `core.management.commands.seed_data`.

## Tests (`backend/gamification/tests.py`, 77 lines)
- `QuizXPCapTests` (cap constants, daily bonus), `AIQuizXPTests` (`AIQuizAttempt.calculate_xp`), `AwardXPTests` (level-up bonus transaction = level x 20, negative clamped at 0, `balance_after`).
- Not covered: leaderboard queries, badge logic, challenges, concurrency.

## Gotchas / risks
- **Docs vs code**: `XP_ARCHITECTURE.md` says mock max XP 50 (matches); the `award_xp` docstring says level bonus "N x 50" but code constant is 20 (doc says 20). `quiz/views.py` comment about "max 200" for mocks is stale (cap 25 x 2 = 50).
- **Rich-flow mock XP never reaches `DailyActivity`** (type `mock_complete` is skipped in `award_xp` and the rich flow does not call `update_daily_activity`), so daily/weekly leaderboards miss it; total_xp is correct.
- **Badges are global, not tenant-scoped**: `check_and_award_badges` uses every active `Badge` regardless of `Badge.tenant`; `BadgeViewSet` (a `TenantAwareReadOnlyViewSet`) overrides `get_queryset` and ignores tenant. Any badge created in Django admin applies to all tenants.
- `BadgeViewSet.get_queryset` returns a `.union()` queryset; DRF `get_object()` for `badges/<id>/` applies filter backends on it, which Django disallows after union (likely 500 on detail; list path unverified). Treat detail route as suspect.
- **Challenges cannot complete via code**: nothing sets `ChallengeParticipation.is_completed` or updates `progress` (no signal/task); `claim_rewards` only works if an admin flips `is_completed` in Django admin. `Challenge.status` transitions (upcoming/active/ended) are also manual. `join` requires `status == 'active'` but `ChallengeViewSet` queryset only lists active/upcoming for the tenant.
- `XPTransactionViewSet.summary.level_progress` uses hard-coded `current_level * 150` as the level span, which does not match `calculate_level` (100 x 1.5^(n-1)); progress % is wrong.
- `StudentProfile.xp_for_next_level` returns cumulative threshold minus total_xp (note level-up bonus XP can push total past thresholds).
- `LeaderboardView`: `limit` unvalidated `int()` (500 on garbage, unbounded size); `total_participants = len(entries)` (capped by limit, not true total); `course_id` is not verified to belong to the tenant (scoping still comes from tenant filter).
- `top_10` badge uses the *daily* tenant leaderboard only.
- Idempotency of XP relies on callers: quiz/mock only award on first completion; assignments check `XPTransaction(reference_id=submission.id)`; challenge claim checks `xp_claimed`. `award_xp` itself has no dedupe. Quiz/mock concurrency can double-award (see quiz.md).
- `check_and_award_badges` iterates all badges and issues several count queries each call; called on every legacy quiz/mock submit. `StudentBadge.objects.create` can race on the unique constraint (no get_or_create).
- Leaderboards include all `StudentProfile`s in the tenant (role filter absent; the response includes `role` field).

## Key files
- `backend/gamification/services.py` - XP awarding, badges, leaderboard queries.
- `backend/gamification/models.py` - ledger, badges, challenges.
- `backend/gamification/views.py` - API.
- `backend/gamification/tests.py` - XP tests.
- `backend/docs/XP_ARCHITECTURE.md`, `backend/docs/XP_CALCULATION_SUMMARY.md` - XP source tables, history of fixes.
- `backend/core/utils.py` - XP formulas/caps.
- `backend/users/models.py` - `StudentProfile.calculate_level/xp_for_next_level`.
- `backend/core/management/commands/seed_data.py` - only place default badges/challenges are defined.
