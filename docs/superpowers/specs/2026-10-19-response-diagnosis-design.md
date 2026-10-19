# Response Diagnosis — Design (Learning Layer, sub-project 1)

**Status:** approved approach, pending spec review · **Date:** 2026-10-19
**Builds on:** `feat/intelligence-foundation` (events → learner state → practice)

## 0. Where this sits

The learning layer is delivered as seven sub-projects, each with its own
spec → plan → build cycle:

| # | Sub-project | Ideas covered |
|---|---|---|
| 0 | Land `feat/intelligence-foundation` on `main` | merge, quiz migration `0012` collision |
| **1** | **Response diagnosis (this spec)** | real per-question timing, answer-change log (3), per-response outcome classifier (core of 22), self-report ground truth |
| 2 | Syllabus model | prerequisite graph, topic weightage, tagger model comparison |
| 3 | Adaptive practice | root-cause remediation (7), Today's 10 (8), adaptive practice tests + retry twins (9→14), mistake notebook (16), strength sets, before/after measurement (34) |
| 4 | Tutor & explanations | tutor questions as signal (4), wrong-option explanations (17), learner-aware tutor (18) |
| 5 | Student analytics | weak/strong topic split (20), best-return map (21), lost-marks view (22 UI), skip strategy (23), personal-best goals (33) |
| 6 | Teacher analytics & outreach | predicted score — teacher-only (24), mistake clusters (26), bad-question alerts (29), weekly digest (25) |

Measurement (34) moved from sub-project 1 to 3: it measures practice
outcomes, and needs no timing data. Decision recorded: no randomized
hold-out; report before/after gain measured on subsequent *non-practice*
evidence, plus the completed-vs-dismissed set comparison.

## 1. Problem

Per-question timing is fabricated today and nothing reads it:

- `QuizAttempt.jsx` sends `total_elapsed / question_count` for every question.
- `MockTestAttempt.jsx` sends `0`.
- `RichMockAttempt.jsx` sends only the attempt total.
- `services/state.py` never reads `time_taken_seconds`.

So a 4-second guess and a 3-minute wrong answer are identical mastery
evidence, and there is no way to say *why* a mark was lost. Unanswered
questions leave no row at all (`Answer` exists only when answered), so
"never saw it" and "chose to skip it" are invisible.

## 2. Goals / non-goals

**Goals**

1. Capture an accurate, raw per-question interaction timeline on all four
   attempt screens (Quiz, Mock, Rich Mock, Practice).
2. Classify every (attempt × item) — answered or not — into one outcome
   label with a confidence and machine-readable evidence.
3. Collect student self-reports on review pages as ground truth, and an
   admin calibration report comparing them to classifier labels.
4. Feed labels back into mastery: guesses and slips stop counting as full
   evidence of not knowing.
5. Make existing `time_taken_seconds` fields truthful.

**Non-goals (later sub-projects)**

- Any student- or teacher-facing view of the labels (sub-projects 5, 6).
- LLM error classification of subjective/coding answers.
- AI chat quizzes (`chatbot.AIQuizAttempt`).
- Per-tenant threshold tuning UI.

## 3. Architecture

Same three layers the intelligence app already uses: **observation**
(append/overwrite raw facts) → **inference** (always recomputed, versioned).

```
browser: useResponseTimeline ──sync every 30s / on hide / before submit──▶
  POST /api/v1/intelligence/timeline/  ──▶ AttemptTimeline   (observation)

review page tap ──▶ POST /api/v1/intelligence/self-report/ ──▶ ResponseSelfReport (observation)

attempt finalized ─▶ record_attempt_events (existing)
                  ─▶ task diagnose_and_update_state(kind, id)
                        1. diagnosis.diagnose_attempt  ──▶ ResponseDiagnosis (inference)
                        2. state.update_for_attempt    ──▶ LearnerConceptState (reads diagnosis weights)
```

Diagnosis runs before the state update in one task, so mastery always sees
the attempt's labels. Diagnosis uses *prior* mastery (events before the
attempt started), so there is no circularity.

### 3.1 Capture — `frontend/exam-frontend/src/hooks/useResponseTimeline.js`

The browser records raw events only. All interpretation is server-side and
tested in Python. The frontend has no test runner, so its logic stays thin.

```js
const tl = useResponseTimeline({
  attemptKind,          // 'quiz' | 'mock' | 'practice'
  attemptId,            // null until the attempt exists → hook is idle
  currentKey,           // e.g. 'bank:<uuid>' | 'item:<uuid>' — the question on screen
  active,               // false on result/instructions screens
})
tl.recordAnswer(key, digest)   // on every answer change; digest below
tl.activeSeconds(key)          // visible time on this key so far, for time_taken_seconds
await tl.flush()               // before submit; never throws
```

- **Session:** each page load gets a random `session_id`. Events carry
  `t` = ms since session start (`performance.now()`).
- **Event tuples:** `[t, code, key, value?]`
  - `e` enter key · `l` leave key
  - `h` tab hidden · `s` tab shown
  - `a` answer set — value is `{"sel":[1,3]}`, `{"num":"3.14"}`,
    `{"txt":<length>}` or `{"code":<length>}`
  - `c` answer cleared
- **Recording:** emits `l`+`e` when `currentKey` changes, and `h`/`s` on
  `visibilitychange`. On unmount or deactivation it emits `l`.
- **Sync:** every 30 s; on `visibilitychange→hidden` (`fetch` with
  `keepalive: true`); and on `flush()`. Each sync sends the session's full
  event list, so a resend is harmless.
- **Caps:** 5,000 events per session. Past the cap, only `a`/`c` events are
  kept, and the session is marked `truncated`.
- **Failure:** sync errors are swallowed and retried at the next tick.
  Capture never blocks or breaks an attempt.

Screens also replace their fabricated per-answer `time_taken_seconds` with
`Math.round(tl.activeSeconds(key))`.

### 3.2 Sync endpoint — `POST /api/v1/intelligence/timeline/`

```json
{"attempt_kind": "quiz|mock|practice", "attempt_id": "<uuid>",
 "session_id": "<uuid>", "elapsed_ms": 123456, "truncated": false,
 "events": [[0,"e","bank:…"], [5400,"a","bank:…",{"sel":[2]}], …]}
```

- **Auth:** the attempt belongs to `request.user.profile`. Quiz/Mock: status
  is `in_progress`, or completed less than 120 s ago (a late flush must not
  be lost). Practice set: status is `in_progress`, or completed less than
  120 s ago.
- **Clock anchoring:** the server computes the session's offset from attempt
  start as `received_at − elapsed_ms − attempt.started_at`. This needs no
  client clock trust and no clock sync. Practice uses
  `PracticeSet.started_at`.
- **Write:** upsert `AttemptTimeline` (one row per attempt) and replace
  `sessions[session_id]`. Rejected once `finalized` is set.
- **Limits:** body ≤ 256 KB (413 above that). `UserRateThrottle` at
  20/min/user.
- **Response:** `{"ok": true}`. Any validation failure returns 4xx and is
  never retried.

### 3.3 Models (in `intelligence/models.py`)

**`AttemptTimeline`** (observation)
- `student` FK, `attempt_kind`, `attempt_id` (UUID), `sessions` JSON
  `{session_id: {offset_ms, events, received_at, truncated}}`,
  `finalized_at` (nullable).
- Unique on (`attempt_kind`, `attempt_id`).
- Finalized by the diagnosis task.

**`ResponseSelfReport`** (observation)
- `student` FK, `attempt_kind`, `attempt_id`, `question` FK | `mock_item` FK
  (XOR check, the same pattern as `ConceptLink`).
- `choice` ∈ `slipped` · `ran_out_of_time` · `guessed` · `didnt_know`.
- Unique per (attempt, item); editable (update_or_create).

**`ResponseDiagnosis`** (inference)
- Keyed by (`attempt_kind`, `attempt_id`, `question` | `mock_item`), so it
  exists for answered *and* unanswered items.
- `student` FK, `answered` bool, `is_correct` (nullable), `score_fraction`.
- `metrics` JSON (§4.1).
- `flags` JSON list.
- `label`, `confidence` (`low|medium|high`).
- `evidence` JSON list of `{code, detail}`.
- `self_report` (copied in for querying), `final_label`.
- `has_timeline` bool, `classifier_version`, `computed_at`.
- Indexes: (`student`, `computed_at`), (`tenant`, `label`).

**`ItemStats`** gains `median_active_seconds` and `active_time_n`. Computed
from `ResponseDiagnosis` rows with `has_timeline`, `answered`, and a label
that is not a guess. Used once `active_time_n ≥ 20`.

`versions.py` gains `CLASSIFIER_VERSION = '1'` and bumps
`STATE_MODEL_VERSION` to `'2'`.

## 4. Classifier — `intelligence/services/diagnosis.py`

A pure function `classify(inputs) → (label, confidence, flags, evidence)`,
plus `diagnose_attempt(kind, id)`, which assembles inputs and upserts rows.
All thresholds live in one `THRESHOLDS` dict in
`intelligence/diagnosis_config.py`. Changing them means bumping
`CLASSIFIER_VERSION` and running `recompute_diagnoses`.

### 4.0 The attempt window

All "last minute" / "third" maths is relative to the window:

| Kind | Window start | Duration |
|---|---|---|
| Rich mock | `attempt.started_at` (server-timed already) | `mock_test.duration_minutes` |
| Quiz / legacy mock / PYP | earliest session start in the timeline (the client timer starts at page load; a reused in-progress attempt's `started_at` may be days old) | `duration_minutes` |
| Practice | `PracticeSet.started_at` | untimed: `last_minute`, `rushed` and `time_pressure` never apply |

A duration of 0 means untimed, with the same effect as practice.

### 4.1 Metrics (from the timeline reduced per key)

| Metric | Definition |
|---|---|
| `active_s` | Σ visit durations minus hidden overlap |
| `visits` | count of `e` events for the key |
| `first_answer_s` | `active_s` accumulated before the first `a` |
| `final_answer_at_s` | attempt-relative wall time of the last `a`/`c` |
| `time_left_s` | `duration − final_answer_at_s` (timed attempts only) |
| `usual_s`, `usual_source` | `ItemStats.median_active_seconds` (`n ≥ 20`) else default by type × difficulty (§4.3) |
| `rel_speed` | `active_s / usual_s` |
| `hidden_s` | hidden time while this key was on screen |
| `changes` | ordered answer digests, each graded server-side → `[{at_s, correct}]` |
| `third` | which third of the attempt's elapsed time the final answer fell in (1–3) |

### 4.2 Flags

| Flag | Rule |
|---|---|
| `too_fast` | `active_s < max(5, 0.25 × usual_s)` |
| `too_long` | `active_s > 2.5 × usual_s` |
| `last_minute` | final answer in the last `max(60 s, 5% of duration)` of the attempt's window |
| `rushed` | `last_minute` and `rel_speed < 0.6` |
| `right_to_wrong` | some earlier digest was correct, final is wrong |
| `wrong_to_right` | some earlier digest was wrong, final is correct |
| `tab_hidden` | `hidden_s > 0` |
| `late_third` | `third == 3` |
| `slip_match` | numerical only: final value matches a slip transform (§4.4) |
| `misconception_pick` | the student picked this same wrong option on this item ≥ 1 time before, or the item's primary-concept `LearnerConceptState.misconception_counts` already holds ≥ 2 picks for it (`GeneratedItem.target_misconception` is free text with no option index, so it is not used) |

### 4.3 Default usual times (seconds) when `ItemStats` is too thin

| type | easy | medium | hard |
|---|---|---|---|
| mcq / true_false | 40 | 70 | 110 |
| mcq_multi | 60 | 95 | 140 |
| numerical / fill_blank | 60 | 100 | 160 |
| subjective / coding | — (time rules skipped) | | |

Unknown difficulty → medium.

### 4.4 Slip transforms (numerical; tolerance = the item's own tolerance, min 1e-9 relative)

The student's value equals the correct value under one of:

- sign flip;
- × 10^k for k ∈ {±1, ±2, ±3};
- × or ÷ one of {60, 100, 1000, 3600};
- rounded to 1–2 fewer significant figures than given.

Applied only when the correct value is not 0 and the student's value is not
0.

### 4.5 Label rules — evaluated in order, first match wins

**Unanswered**

1. `not_seen` — `visits == 0` or `active_s < 2`.
2. `time_pressure` — **both** (a) the attempt timed out or was submitted
   within its last-minute zone, **and** (b) the item was first entered in
   the last 15% of the window, or `active_s < 0.5 × usual_s`.
3. `skipped` — otherwise (seen, considered, left blank).

**Correct**

1. `correct_lucky` — MCQ-type and `too_fast`.
2. `correct_slow` — `too_long`.
3. `correct`.

**Wrong / partial (`score_fraction < 0.5`)**

1. `guess` — `too_fast`.
2. `second_guess` — `right_to_wrong`.
3. `time_pressure` — `rushed`.
4. `careless_slip` — either:
   - `slip_match`, **or**
   - all of: prior mastery ≥ 0.75 at confidence ≥ medium,
     0.5 ≤ `rel_speed` ≤ 2.5, and not `misconception_pick`.
5. `concept_gap` — any of:
   - prior mastery < 0.5 at confidence ≥ medium;
   - `misconception_pick`;
   - `too_long`.
6. `unclear` — nothing matched, or signals conflict (rule 4 by mastery and
   `too_long` both true).

**No timeline** (historic attempts, or sync lost): time-based flags are not
computed. The rules still run with only `slip_match`, `misconception_pick`
and mastery. Any rule that needs time is skipped, and the evidence records
`no_timeline`.

**Confidence**
- *high* — `slip_match`, `right_to_wrong`, or `too_fast` on an item with
  `usual_source == 'stats'`.
- *medium* — other time-based or mastery-based rules.
- *low* — `unclear`, or any rule on a default usual time with
  `rel_speed` within 20% of a threshold.

**Prior mastery:** `compute_state_fields` over the student's observations
for the item's primary concept, restricted to events with `occurred_at <
attempt.started_at`. If the item has no concept, treat it as "unknown", so
mastery-based clauses never match.

### 4.6 Self-report reconciliation

| Choice | Maps to | Adopted as `final_label` when |
|---|---|---|
| `slipped` | `careless_slip` | label is `unclear` / confidence low, **and** not `too_fast` |
| `ran_out_of_time` | `time_pressure` | label is `unclear` / confidence low, **and** (`last_minute` or attempt timed out) |
| `guessed` | `guess` | label is `unclear` / confidence low (always plausible) |
| `didnt_know` | `concept_gap` | label is `unclear` / confidence low |

Otherwise `final_label = label`. Disagreements are kept, not overwritten;
they feed the calibration report and a per-student "self-report agreement"
rate (exposed in sub-project 5).

### 4.7 Mastery feedback (`services/state.py`, `STATE_MODEL_VERSION = '2'`)

`observations_for` joins each event to its `ResponseDiagnosis` by (attempt,
item), then multiplies `link_weight` by:

| final_label | weight |
|---|---|
| `guess`, `correct_lucky` | 0.2 |
| `careless_slip`, `time_pressure` | 0.5 |
| everything else, or no diagnosis | 1.0 |

`not_seen` / `skipped` / unanswered items have no event, so they are
unaffected. After deploy, `recompute_learner_state` is re-run.

## 5. Self-report UI

- A `WhatHappened` component on `QuizReview`, `MockTestReview` and
  `RichMockReview`. It appears beside each wrong or unanswered item, except
  `not_seen` ones, which have nothing to explain.
- Four chips: *Knew it, slipped* · *Ran out of time* · *Guessed* ·
  *Didn't know*. One tap saves; tapping another chip changes the answer.
  It is optional and never blocks.
- `GET /api/v1/intelligence/self-report/?attempt_kind=&attempt_id=` returns
  existing choices.
- `POST /api/v1/intelligence/self-report/` with `{attempt_kind, attempt_id,
  item_kind: 'bank'|'item', item_id, choice}`. This upserts, then
  synchronously re-runs reconciliation for that one row. It is cheap, and no
  re-classification is needed.
- Gated by a new opt-in tenant feature `response_diagnosis` ("Answer
  Diagnosis") added to `Tenant.FEATURE_CHOICES` and `OPT_IN_FEATURES`.
  Capture and classification run regardless; this matches how the
  foundation accrues data while features are off.

## 6. Calibration & operations

- `GET /api/v1/admin/intelligence/diagnosis-calibration/?days=30` (tenant
  admin) returns:
  - label distribution;
  - a classifier-label × self-report confusion matrix;
  - per-label agreement rate;
  - the share of rows with a timeline and the share with
    `usual_source == 'stats'`.
- Management command
  `recompute_diagnoses [--tenant] [--since YYYY-MM-DD]`.
- Nightly catch-up: the existing `refresh_learner_state` sweep also
  diagnoses any finalized attempt from the last 48 h that has no diagnosis
  rows at the current `CLASSIFIER_VERSION`.
- Hook wiring: `intelligence_api.record_attempt_events` enqueues
  `diagnose_and_update_state` in place of `update_learner_state_for_attempt`.
  Practice set submit already recomputes state synchronously (the student
  is on the results screen). It calls `diagnosis.diagnose_attempt('practice',
  set_id)` synchronously just before that recompute, so it gets no task.
- Attempt ids on the client: `QuizAttempt.jsx` and `MockTestAttempt.jsx`
  never receive an attempt id today (`Quiz.jsx` calls `start` and then
  navigates, and legacy mock submit get-or-creates). Both screens call their
  existing `start` endpoint on mount. It already returns the in-progress
  attempt instead of creating a second one, and it supplies the id the hook
  needs. Rich mock and practice already hold their ids.

## 7. Error handling

- Capture never interrupts an attempt (swallowed errors, retry next tick).
- The sync endpoint returns 4xx on any malformed input and never partially
  writes.
- Diagnosis is fail-safe per attempt: an exception is logged, the state
  update still runs (all weights 1.0), and the nightly sweep retries.
- A malformed or out-of-order event stream is reduced defensively:
  - unmatched `e` closes at the next `e`/`l` or at session end;
  - negative or overlapping intervals are clipped;
  - events for keys not in the attempt are ignored.

## 8. Testing (Django `TestCase`, matching `intelligence/tests/`)

- `test_timeline.py`
  - Reducer: visits, hidden overlap, unmatched enter, multi-session merge,
    offset anchoring, truncation.
  - Endpoint: ownership, status window, size cap, idempotent resend,
    rejection after finalize.
- `test_diagnosis.py`
  - The pure `classify` against a table of hand-built inputs, at least one
    per label plus the conflict → `unclear` case.
  - Slip transforms.
  - No-timeline degradation.
  - Confidence assignment.
  - Self-report reconciliation matrix.
- `test_state.py` additions: diagnosis weights reduce guess/slip impact; no
  diagnosis means unchanged results (regression guard for v1 behaviour).
- An integration test: rich mock attempt → timeline sync → submit → task →
  diagnosis rows (answered and unanswered) → state reflects weights.
- Calibration endpoint: shape and counts on fixture data.
- Frontend: manual verification of all four screens via the `run` skill
  (sync payloads in the network tab, `time_taken_seconds` no longer uniform).
