# community

Source: branch `main` export. All paths repo-relative.

- **Purpose**: Tenant-scoped student forum. Post types: question, poll, quiz (single-question), event (staff-only, schedule + join link). Comments with nested replies, likes, best-answer, profanity moderation, community XP, per-user stats, weekly/monthly/all-time community leaderboard.
- **Mount**: `/api/v1/community/` (backend/dailytaiyari/urls.py). Tenant feature flag key `community` (core.Tenant.FEATURE_CHOICES) — **UI-only toggle; the backend never checks it** (`get_features()` is only used to serialize to the frontend).

## Key models (backend/community/models.py)
All inherit `core.TimeStampedModel` (UUID pk, nullable `tenant` FK, created/updated_at). Tenant stamped in view `perform_create`; migration `0009_backfill_tenant` backfilled legacy NULL-tenant rows from `author.user.tenant`.
| Model | Notes |
|---|---|
| `Post` | `post_type` question/poll/quiz/event; `status` active/closed/hidden; `author`->StudentProfile; legacy `course` FK + new `courses` M2M (visibility scope); `subject`; `tags` JSON; counters (`likes_count`, `comments_count`, `views_count`); `is_solved`, `best_answer`->Comment; `image`. Title min 10 chars, content min 20. |
| `Comment` | `post`, self-FK `parent` (nested replies), `is_best_answer`, `likes_count`, idempotency latches `answer_xp_awarded`, `best_answer_xp_awarded`. Ordering: best first, likes desc. |
| `Like` | post OR comment target; **soft toggle** (`is_active`), `xp_awarded` latch. Partial unique constraints `unique_post_like (user, post)` / `unique_comment_like (user, comment)`. |
| `PollOption` / `PollVote` | votes_count denormalised; `PollVote` unique_together (user, option) — one vote per post is enforced in code (vote change moves the vote). |
| `CommunityQuiz` | 1:1 with Post; `options` JSON list, `correct_answer` index, `explanation`, attempts/correct counters. |
| `QuizAttempt` | unique (user, quiz). |
| `CommunityEvent` | 1:1 with Post (type=event): `start_at`, `end_at`, `meeting_url`; derived `state` upcoming/live/ended. |
| `CommunityStats` | per-student aggregates (posts, answers, best answers, likes, `total_community_xp`). |
| `CommunityLeaderboard` | cached rows per (user, period weekly/monthly/all_time, period_start); unique (user, period, period_start). |

## API (backend/community/urls.py, DRF DefaultRouter; all `IsAuthenticated` unless noted)
- `posts/` `PostViewSet(TenantAwareViewSet)`: list/retrieve/create/update/destroy. Query: `type`, `course` (id or `global`), `subject`, `is_solved`, `sort=recent|popular|unanswered`, `my_posts=true`, `status=hidden|closed|active|all` (staff only).
  - Actions: `like`, `mark_solved` (author only, toggles), `select_best_answer` (author only), `vote_poll`, `hide` / `unhide` (staff only), `filter_options` (courses user can post into), **`course_preview` (AllowAny)** — public teaser for course landing pages (title + excerpt + counters only; hidden courses 404 for non-enrolled/non-staff).
  - Delete: author or staff (admin/instructor/is_staff) only.
- `comments/` `CommentViewSet`: filter `?post=`, `?include_replies=true` (default: top-level only); action `like`; delete author-or-staff.
- `quiz-attempts/` `QuizAttemptViewSet` (create only).
- `stats/my_stats/`, `stats/user_stats/?user_id=` (same-tenant only).
- `leaderboard/weekly|monthly|all_time/` (top 50, tenant-scoped).
- Visibility: non-staff see only `status=active`, and posts with no course links (global) OR linked to a course they are approved+active enrolled in OR their own. Staff = role admin/instructor/is_staff, bypass.

## Business logic (backend/community/services.py, serializers.py)
- `ContentModerationService`: evasion-resistant profanity filter (English + Hinglish word lists, leetspeak/spacing/repeat normalisation, prefix list vs exact-word list) + `better_profanity` safety net. Applied in `PostCreateSerializer.validate` (title/content/poll options/quiz) and Comment serializers. No report/flag workflow, no moderation queue model — moderation = filter + staff hide/unhide/delete.
- `CommunityXPService.award_xp(profile, action, reference_id, description)`: atomic; bumps `StudentProfile.total_xp`, writes `gamification.XPTransaction(transaction_type='community')`, updates `CommunityStats`, increments `analytics.DailyActivity.xp_earned`. Rewards: ask_question 5, create_poll 5, create_quiz 8, answer_question 8, best_answer 20, receive_like_post/comment 2, vote_poll 2, quiz_correct 3.
- Anti-farming: no XP for liking/answering own content; like XP latched on `Like.xp_awarded`; answer/best-answer XP latched on Comment booleans.
- `CommunityLeaderboardService`: leaderboard is **computed lazily on read** — if the newest cached row for the tenant/period is >5 min old (or none), `update_leaderboard` rebuilds from `XPTransaction(type=community)` in the period (top 100, delete+bulk_create per tenant). Score = community XP. No Celery/cron.
- Event posts: staff-only; require `event_data{start_at, meeting_url, end_at?}`; no XP.
- No signals, no Celery tasks, no management commands, no notifications sent.

## Integrations / settings / env
None external. Uses `better_profanity` pip package, `ImageField` uploads (`community/posts/`, `community/comments/`) via default storage (local or Azure/S3 via `storages`).

## Cross-app dependencies
- Imports: `core` (TimeStampedModel, TenantAwareViewSet), `exams` (Course, Subject), `users` (StudentProfile, CourseEnrollment, UserSerializer), `gamification.XPTransaction`, `analytics.DailyActivity`.
- Called by: core landing/course pages use `posts/course_preview/` (frontend `CourseCommunityPreview.jsx`). `gamification.models` lists `'community'` as an XP transaction type.

## Tests (backend/community/tests.py, ~171 lines)
`PostLikeXPTests` (like/unlike/relike XP once, self-like none), `PostTenantIsolationTests`, `CoursePreviewTests` (anonymous teaser, plain-text excerpt, enrolled participation, no double count for dual-linked posts, cross-tenant course 404). No tests for polls, quizzes, events, leaderboard, moderation filter, comment endpoints.

## Gotchas / risks
- **No object-level permission on update**: `PostViewSet`/`CommentViewSet` are full ModelViewSets with only `IsAuthenticated`; `update`/`partial_update` are not overridden, so any authenticated tenant user who can see a post/comment can PUT/PATCH it (only `destroy`, `hide`, `mark_solved`, `select_best_answer` check author/staff). Verified by reading; not exercised.
- `QuizAttemptViewSet` has `queryset = QuizAttempt.objects.all()` and the `quiz` field accepts any quiz PK: no tenant or post-visibility check (cross-tenant / course-restricted quiz can be answered if the UUID is known, mutating its counters and awarding XP).
- Quiz XP inconsistency: serializer records `xp_earned=5` but `CommunityXPService` awards 3 for `quiz_correct`.
- `select_best_answer` does not check the comment is not a reply; `mark_solved` toggles.
- `ContentModerationService.contains_profanity` calls `profanity.load_censor_words()` on every call (performance).
- Counters (`likes_count`, `comments_count`) are `F()` updates but responses add +/-1 to the stale in-memory value; comment delete does not decrement `Post.comments_count` (no signal) — unverified beyond reading `destroy`.
- Leaderboard rebuild can run inside a user GET (heavy for large tenants).
- Public endpoint: `GET posts/course_preview/` (AllowAny) but still needs the `X-Tenant-ID` header (not in TENANT_EXEMPT_PATHS).

## Key files
- backend/community/models.py — all models above
- backend/community/views.py — viewsets, visibility rules (`accessible_posts_q`), `course_preview`
- backend/community/serializers.py — Post/Comment/Quiz/Event (de)serialisers; quiz hides `correct_answer`/`explanation` until attempted; creation validation incl. event staff-gate
- backend/community/services.py — moderation, XP, leaderboard
- backend/community/migrations/0009_backfill_tenant.py — legacy tenant backfill
- backend/community/tests.py — tests
- frontend/exam-frontend/src/pages/Community.jsx, CommunityPost.jsx, components/community/CourseCommunityPreview.jsx — student UI
