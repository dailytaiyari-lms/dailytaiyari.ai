# TODO — known issues not yet fixed

## Deleting a question, topic or subject wipes students' answer history

**Status:** open. Found on 2026-10-19 while auditing a production copy.

**Evidence (production copy):**
- 267 of 446 completed quiz attempts have no `quiz.Answer` rows left.
- 264 of them still record about 5 questions attempted and a 68.8% average score in the attempt summary, so the per-question answers existed once and were deleted.
- 5 quizzes now have no questions at all.

**Cause:** cascading foreign keys.
- `quiz.Answer.question` is `on_delete=CASCADE` (`backend/quiz/models.py`).
- `quiz.Question.topic` and `quiz.Question.subject` are `on_delete=CASCADE`.
- So deleting a question in admin (`quiz/admin_views.py`, question destroy) erases every student's answers to it. Deleting a topic or subject (`exams/admin_views.py`) cascades through its questions as well.

**Impact:**
- Review pages, leaderboards and analytics lose history, while attempt summaries still claim answers.
- The learning layer itself is protected. `intelligence.LearningEvent` uses `SET_NULL` and keeps topic and subject snapshots, so mastery evidence survives deletions from now on. History deleted before the backfill is gone for good.

**Fix options (decide one):**
1. Soft-delete questions, topics and subjects: an `is_deleted` flag hidden from authoring and serving.
2. `on_delete=PROTECT` on `Answer.question`, with admin "delete" becoming archive (`Question.status='archived'` already exists) once answers exist.
3. `SET_NULL` on `Answer.question` with a snapshot of the question text and correct answer on the answer row, which keeps review pages working.

Write a data migration test against a production copy before shipping any of these.

## Other deferred items

- `intelligence.views.RefreshThrottle` inherits DRF's `'user'` scope, so it shares its request history with every default-throttled view. Give it its own scope.
- Set nginx `client_max_body_size` (about 300 KB is enough) for `/api/v1/intelligence/timeline/`. The app-level 256 KB cap relies on `Content-Length`.
- The legacy (non-rich, non-PYP) mock test screen never starts an attempt (`startMockTest` has no caller), so its submit and timeline sync have no in-progress attempt.
- `frontend/exam-frontend/package-lock.json` is out of sync with `package.json` on `main`, so `npm ci` fails. `hls.js` is missing from fresh installs.
- `chatbot.tests.ExhaustionNoticeTests.test_exhaustion_warns_again_after_the_threshold_warning` is flaky on Windows. Two notifications created in the same clock tick make `notices.first()` ambiguous.
