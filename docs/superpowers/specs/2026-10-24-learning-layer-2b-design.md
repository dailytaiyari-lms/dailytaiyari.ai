# Learning Layer 2B — Diagnosis Visibility, Syllabus Tools, My Progress (Design)

**Status:** approved in design discussion, 2026-10-24.
**Branch:** `saksham/learning-layer-2b`, stacked on `saksham/learning-layer` (PR #213).
**Builds on:**
- [`2026-10-19-response-diagnosis-design.md`](2026-10-19-response-diagnosis-design.md) (sub-project 1);
- [`2026-10-19-question-tagging-design.md`](2026-10-19-question-tagging-design.md) (plan 2A, whose §8 sketched plan 2B).

## 1. Goal and scope

Make the learning layer visible and usable inside the product.

- **Part A — Diagnosis visibility.**
  - Teachers see each answer's diagnosis, with label, confidence and evidence, for every student they teach, plus class aggregates.
  - Students see their own diagnoses.
  - Admins get a calibration page.
- **Part B — Syllabus and tagging tools.**
  - Admins and assigned faculty build a course's syllabus tree from the UI, edit it, run tagging, and work a tag review queue.
- **Part C — My Progress.**
  - Students get a progress page: mastery rolled up from subtopic to topic, sub-subject and subject; weak and strong topics; skill and thinking-level profiles; recent answers.
  - Teachers see the same data per student, and a class topic heatmap.

Build order: **A → B → C**. Each part is one implementation plan and ships working software on its own. A uses data that already exists. B fills in trees and tags for real courses. C's skill and thinking-level profile needs B's tags; its topic roll-up has a fallback that works without them.

**Out of scope:**
- generators emitting v2 tags;
- recomputing `review_status` when the threshold changes;
- `mcq_multi` grading;
- the answer-history cascade-delete fix;
- the synthetic-student harness.

These stay in `docs/TODO.md` and the tagging spec §8.

## 2. Global rules (bind every part)

1. **Opt-in, as on PR #213.** A tenant with every learning-layer switch off behaves exactly as on `main`.
   - `intelligence.api.LEARNING_FEATURES` is the set of switches that turn on background data collection: event recording, timeline capture, diagnosis and state jobs, and the tagging sweep.
   - **Add `my_progress` and `syllabus_tools` to it.**
   - The two view switches in §3 do **not** collect data. They require `response_diagnosis`, which already does.
2. **Server-side enforcement.**
   - Every new endpoint checks the relevant switch, and returns 403 when the switch is off.
   - Every new endpoint checks the scope rules in §3.2.
   - The UI hides what is gated, but the server is the authority.
3. **No new data collection.** Parts A and C read existing tables (`ResponseDiagnosis`, `LearnerConceptState`, `ItemTagging`, `ItemSkillTag`, `SyllabusNode`, `LearningEvent`). The only new tables:
   - `LearnerFacetState` (Part C);
   - `TreeBuildJob` and `TaggingRun` for job history (Part B).
4. **Computed on read.** Roll-ups, patterns, aggregates and heatmaps are calculated per request from existing rows; there are no summary tables. Each endpoint caps its work, for example the last N attempts, and paginates lists.
5. **Kind wording to students.** Students never see a bare label such as "guess" or "careless slip". They see a plain-language note (§4.2).

## 3. Feature switches and access

### 3.1 Switches

New entries in `core.models.Tenant.FEATURE_CHOICES`, all in `OPT_IN_FEATURES` (off by default). The super-admin can lock any of them with the existing `feature_locks`.

| Key | Label | Turns on | Requires |
|---|---|---|---|
| `response_diagnosis` (exists) | Answer Diagnosis | Timeline capture, diagnosis, the student's "What happened?" self-report | — |
| `diagnosis_teacher_view` | Diagnosis: teacher view | Labels, evidence and confidence in Learning Insights; patterns; class answer-behaviour tile | `response_diagnosis` |
| `diagnosis_student_view` | Diagnosis: student view | The student's own diagnosis notes on review pages and in My Progress | `response_diagnosis` |
| `my_progress` | My Progress | The student My Progress page; roll-ups and profiles in Learning Insights | — |
| `syllabus_tools` | Syllabus & tagging tools | Course Syllabus tab: tree build, editor, Tag questions; Tag review queue | — |

**Dependencies.** Add `Tenant.FEATURE_REQUIRES = {'diagnosis_teacher_view': 'response_diagnosis', 'diagnosis_student_view': 'response_diagnosis'}`.
- **Effective value:** `get_features()` reports a dependent switch as on only when its requirement is also on.
- **Settings UI:** the tenant-admin and super-admin settings pages show a dependent switch greyed out while its requirement is off, with the hint "Needs Answer Diagnosis".

### 3.2 Who sees what

| Role | Diagnosis, mastery, progress | Syllabus and tagging tools |
|---|---|---|
| Student | Own data only | None |
| Faculty (`role='instructor'`) | Students with an **approved** `CourseEnrollment` in a course they are assigned to (`Course.instructors`), and those courses' aggregates | Only their assigned courses |
| Admin (`role='admin'`) | Every student and course in the tenant | Every course in the tenant |

- **Shared helper:** one module, `intelligence/access.py`, with:
  - `teachable_course_ids(user)`;
  - `can_view_student(user, student_profile)`;
  - `can_manage_course(user, course)`.
- **Existing views use it too.** The existing Insights views (`OverviewView`, `AssessmentReportView`, `StudentDiagnosisView`, `GeneratedItemsView` and `GenerationJobsView`) switch to these helpers. Today faculty can see any course in the tenant; this narrows them to their assigned courses. That is an intended change, and it only matters where `practice` is on.

## 4. Part A — Diagnosis visibility

### 4.1 Teacher view (`diagnosis_teacher_view`)

1. **Assessment report: an "Answer behaviour" panel.** It sits in the existing per-assessment Insights report and covers one quiz, mock or rich mock.
   - **Per question:**
     - counts and shares of each final label (`correct`, `correct_lucky`, `correct_slow`, `guess`, `second_guess`, `careless_slip`, `time_pressure`, `concept_gap`, `skipped`, `not_seen`, `unclear`), drawn as a stacked bar;
     - median active seconds, against the item's usual time;
     - the self-report count.
   - **Question flags**, with thresholds in `intelligence/visibility_config.py`. Each needs at least 8 diagnosed answers:

     | Flag | Fires when | Message |
     |---|---|---|
     | `many_guesses` | `guess` + `correct_lucky` ≥ 35% | "May be too hard or unclear." |
     | `many_second_guesses_or_slips` | `second_guess` + `careless_slip` ≥ 25% | "Check the wording or the answer key." |
     | `time_crunch` | `time_pressure` + `not_seen` ≥ 30% | "Most students ran out of time before this." |

2. **Student page: an "Answers" tab.** It sits on the existing per-student Insights page.
   - Attempts are listed newest first, 20 per page.
   - Each answer shows:
     - the label, with confidence;
     - the evidence as plain sentences (§4.3), e.g. "Answered in 3 s; usual is 45 s";
     - active time;
     - the self-report, if any.
   - **Patterns** at the top cover the last 10 attempts and are computed on read. The rules are in `visibility_config.py`:

     | Pattern | Fires when | Message |
     |---|---|---|
     | `rushes_end` | `time_pressure` or `guess` in the last 10% of the test, in ≥ 3 of the last 5 timed attempts | "Rushes the last part of tests" |
     | `slips_in_<topic>` | `careless_slip` concentrated in one topic: ≥ 3 slips and ≥ 50% of the student's slips | "Careless slips mostly in <topic>" |
     | `changes_right_to_wrong` | ≥ 3 `second_guess` answers that ended wrong | "Changes right answers to wrong ones" |
     | `guesses_often` | `guess` share ≥ 25% over at least 20 answers | "Guesses often" |

     Each pattern shows its count and links to the answers it is based on.

3. **Insights home: an "Answer behaviour" tile** for the selected course.
   - Guess, careless-slip and time-pressure rates over the last 28 days, with a weekly trend: 4 points.
   - **Students to check:** the top 5 students by slip or time-pressure rate, each with at least 15 answers in the window.

4. **Diagnosis quality (admin only).** A page under Learning Insights over the existing `DiagnosisCalibrationView`. It shows:
   - the agreement between self-reports and system labels, per label;
   - the thresholds in use;
   - `CLASSIFIER_VERSION`.

### 4.2 Student view (`diagnosis_student_view`)

- **Review pages** (quiz, legacy mock, rich mock) show a one-line note per answer, above the existing self-report row. That row is relabelled "Not quite? Tell us what happened."
- **Only medium- and high-confidence diagnoses are shown.** For a low-confidence one, no note is shown and the student sees only the self-report question.
- **Notes per label**, in `visibility_config.py`, so they are easy to edit:

  | Label | Note |
  |---|---|
  | `guess` | "Looks like a quick guess — you spent {active}s here." |
  | `correct_lucky` | "Correct, but quickly — worth checking you're sure." |
  | `correct_slow` | "Correct — took longer than usual ({active}s)." |
  | `second_guess` | "You changed this answer — your first choice was right." |
  | `careless_slip` | "You usually get this kind of question right — possibly a slip." |
  | `time_pressure` | "You ran short of time here." |
  | `concept_gap` | "This one needs more practice — see My Progress." |

  `correct`, `skipped`, `not_seen` and `unclear` show no note.
- Students only ever receive their own attempts. The endpoint checks that the attempt belongs to the requesting user's student profile.

### 4.3 Evidence wording

`ResponseDiagnosis.evidence` holds `[{code, detail}]` items, produced by `services/diagnosis.py`.
- **Function:** add `describe_evidence(evidence, metrics)` to `visibility.py`, returning plain sentences. Teachers get these sentences; students get only the label note above.
- **Unknown codes** fall back to the stored `detail` text.

### 4.4 Endpoints (Part A)

The `<kind>` values match the existing report route.

| Method and path | Who | Returns |
|---|---|---|
| `GET /tenant-admin/intelligence/assessments/<kind>/<id>/behaviour/` | teacher view; course in scope | per-question label distribution, timings, flags |
| `GET /tenant-admin/intelligence/students/<student_id>/answers/?page=` | teacher view; student in scope | attempts with answers, evidence sentences, patterns |
| `GET /tenant-admin/intelligence/courses/<course_id>/behaviour/` | teacher view; course in scope | rates, trend, students to check |
| `GET /tenant-admin/intelligence/diagnosis/calibration/` (exists) | admin only | unchanged |
| `GET /intelligence/my/attempts/<kind>/<attempt_id>/diagnosis/` | student view; own attempt | per-item note (medium/high only) |

## 5. Part B — Syllabus and tagging tools (`syllabus_tools`)

### 5.1 Course "Syllabus" tab (admin course editor)

This is visible to admins and to faculty on their assigned courses.

- **Build syllabus tree (custom courses).**
  - It calls `services/course_tree.build_course_tree` as a background job, a new `TreeBuildJob` row on the `aigen` queue.
  - Before running, it shows an estimate: the number of LLM calls (one grouping call per subject with more than 6 topics, one subtopic call per topic, one packs call) and approximate tokens (about 1,500 per call). It also shows the tenant's remaining monthly budget.
  - It refuses to start when the budget is exhausted (`_check_budget`).
  - Status values: `queued` → `running` → `done` / `failed`. A successful job produces the summary counts.
- **Use an exam syllabus (exam courses).**
  - Pick a shipped exam tree (today `jee_main`), then map each course subject to a tree subject.
  - It calls `instantiate_exam_tree` synchronously, with no LLM calls.
- **Tag questions.**
  - It estimates the questions to tag (not current, not manual) and the approximate tokens (about 1,000 per question, from the first evaluation).
  - It runs `tag_v2_for_tenant` restricted to this course's subjects, as a new `TaggingRun` row on `aigen`.
  - It reports counts: tagged, needs review, failed.
- **Job history.**
  - `TreeBuildJob` fields: `course`, `started_by`, `status`, `summary` JSON, `error`, `tokens`, `cost_usd`, timestamps.
  - `TaggingRun` has the same fields.
  - The tab lists the last 10 runs.

### 5.2 Tree editor (same tab)

- A collapsible tree of sub-subjects → topics → subtopics, per subject.
- **Operations:**
  - add, rename or archive a subtopic;
  - rename, add or archive a sub-subject;
  - move a topic to another sub-subject;
  - set weightage, with optional validation that siblings sum to 1 when any is set;
  - choose skill packs per subject (`CourseSyllabus.skill_packs`);
  - **merge two subtopics.**
- **Merge** keeps the target node and its Concept. It uses `normalize.merge_concept`, so ConceptLinks and aliases move and the loser's learner states are dropped for recompute. It re-points `ItemTagging.primary_node` and `secondary_nodes` from the source to the target, then archives the source node. Skill tags are per item, not per node, so they are unaffected.
- **Course topics stay read-only.** Their names and order come from the course itself.
- **Suggested subtopics.**
  - `build_course_tree` creates proposals with `status='proposed'` and a "suggested" badge in the editor. Today they are created as `active`.
  - Accepting a suggestion makes it `active`; editing it also accepts it.
  - **The tagger uses `active` and `proposed` nodes.** `tagging_context` and the node lookups in `tagging_sweep` include both, so tagging works straight after a build.
- **Re-tagging after edits.** Any edit changes the subject's tree version, so the next Tag questions run re-tags the affected items, with cache misses where the prompt changed.
- **Permissions.** The editor writes only through endpoints that check `can_manage_course`.

### 5.3 Tag review queue

- **Where:** Learning Insights → "Tag review", tenant-wide within the user's scope, and filtered on each course's Syllabus tab.
- **List:** `ItemTagging` rows with `review_status='needs_review'`, filterable by course, topic and reason, 25 per page.
- **Each row shows:**
  - the question text;
  - the primary and secondary subtopics;
  - thinking level;
  - skills (core or supporting, with the model's reason);
  - special format;
  - difficulty prior;
  - estimated solve time;
  - confidence;
  - review reasons.
- **Actions:**
  - **Accept:** `review_status='reviewed'`.
  - **Edit:** a form over the same fields, choosing from the tree and the vocabulary. Saving sets `source='manual'` and `review_status='reviewed'`, and rewrites ConceptLinks (source `manual`) and `ItemSkillTag` (source `manual`), so the tagger never overwrites them.
  - **Re-tag:** marks the item stale and runs it immediately on `aigen`.
  - **Add to tree:** for a `proposed_subtopic`, creates the subtopic under the item's topic and assigns it, then counts as Edit.
  - **Bulk accept:** on selected rows.
- **Question bank editor:** gets a read-only **Tags** panel with an "Edit tags" link to the same form.

### 5.4 Endpoints (Part B)

All endpoints are under `/tenant-admin/intelligence/syllabus/` and require `syllabus_tools`, plus `can_manage_course` for course-scoped calls.

| Method and path | Purpose |
|---|---|
| `GET courses/<id>/tree/` | tree, skill packs, exam mapping, job history |
| `POST courses/<id>/tree/estimate/` | build estimate |
| `POST courses/<id>/tree/build/` | start a `TreeBuildJob` |
| `POST courses/<id>/tree/exam/` | map to an exam tree |
| `POST courses/<id>/nodes/` | add a node |
| `PATCH nodes/<id>/` | rename, move, weightage, accept, archive |
| `POST nodes/<id>/merge/` | merge into another node |
| `PATCH courses/<id>/skill-packs/` | skill packs |
| `POST courses/<id>/tagging/estimate/` | tagging estimate |
| `POST courses/<id>/tagging/run/` | start a `TaggingRun` |
| `GET jobs/<id>/` | job status |
| `GET review/?course=&topic=&reason=&page=` | review queue |
| `POST review/<tagging_id>/accept/` | accept one |
| `POST review/bulk-accept/` | accept many |
| `PUT review/<tagging_id>/` | edit tags (manual) |
| `POST review/<tagging_id>/retag/` | re-tag one |
| `POST review/<tagging_id>/add-to-tree/` | add the proposed subtopic |

### 5.5 Local-testing convenience

- In `settings.py`, `CELERY_TASK_ALWAYS_EAGER = config('CELERY_TASK_ALWAYS_EAGER', default=False, cast=bool)`, applied when not under tests; the test runner keeps its own eager rule.
- When it is true, tasks run inside the request: diagnosis right after submit, and Build and Tag finishing without a worker.
- It is never set in production.
- Document it in `wiki/backend-guide.md`.

## 6. Part C — My Progress (`my_progress`)

### 6.1 Roll-ups

- **Function:** `services/rollup.py` `rollup_for(student, course)` returns a nested structure: subject → sub-subject → topic → subtopic.
- **Each node carries:**
  - `mastery` (0–1);
  - `coverage` (subtopics with evidence / total subtopics);
  - `evidence` (sum of `effective_evidence`);
  - `confidence` (low, medium or high, from evidence);
  - `trend_4w`: four weekly points, each the share of correct, diagnosis-weighted answers (`score_fraction × LABEL_WEIGHTS`) among the student's `LearningEvent`s on that node's subtopic concepts that week. A week with fewer than 2 events is `null`. `LearnerConceptState` holds only the current value, so the trend comes from events.
- **Leaves** are `LearnerConceptState` for each subtopic's Concept.
- **Parents** are the weighted mean of children with evidence. The weight is `effective_evidence × (node.weightage if the tree has weightage else 1)`.
- **Children without evidence** count towards coverage, but not towards mastery.
- **Fallback when the course has no tree:**
  - levels are subject → course Topic → Concept, using `Concept.topics`;
  - sub-subjects are omitted;
  - a concept linked to several topics counts under each of them.
- **Not enough data:** a node with `evidence < 3` reports `mastery: null` and `status: "not_enough_data"`.

### 6.2 Weak and strong topics

The thresholds are in `intelligence/progress_config.py`:
- `WEAK_BELOW = 0.5`;
- `STRONG_AT = 0.8`;
- `MIN_EVIDENCE = 3`.

Topics are labelled `weak`, `strong`, `in_progress` or `not_enough_data`. The page lists the top 5 weak topics (lowest mastery first) and the top 5 strong topics (highest first). When `practice` is on, each weak topic gets "Practise this", which opens Smart Practice filtered to that topic's concepts.

### 6.3 Skill and thinking-level profiles

- **New model `LearnerFacetState`:** `student`, `subject`, `kind` (`skill` or `thinking_level`), `key`, `mastery`, `evidence_count`, `effective_evidence`, `confidence`, `model_version`, `computed_at`. Unique on (`student`, `subject`, `kind`, `key`).
- **Recompute:** in `services/facets.py`, recomputed from the student's graded `LearningEvent`s, using the same decay, `LABEL_WEIGHTS` diagnosis weighting and confidence rules as `services/state.py`.
  - An event's item contributes to every `ItemSkillTag` of that item: weight 1.0 if `core`, 0.5 if `supporting`.
  - It also contributes to the item's `ItemTagging.thinking_level`, at weight 1.0.
- **When it runs:**
  - inside `diagnose_and_update_state`, after the concept state;
  - in the nightly `refresh_learner_state`;
  - in `recompute_learner_state`, which gains a `--facets` flag defaulting to on.
- **Version constant:** `FACET_MODEL_VERSION = '1'`.
- **Untagged subjects** return an empty profile with `status: "needs_tagging"`.

### 6.4 Student page `/progress`

The student menu item is "My Progress". The page has:
- a course picker covering the student's approved enrolments;
- subject cards: mastery, coverage and a 4-week sparkline;
- expandable subject → (sub-subject) → topic → subtopic rows;
- the weak and strong lists;
- the skills and thinking-level panel per subject;
- **Recent answers** (only when `diagnosis_student_view` is also on): the last 5 attempts, each with label-note counts such as "2 quick guesses, 1 ran out of time", linking to the review page.

### 6.5 Teacher side

- **Student page in Learning Insights:** a "Progress" tab with the same roll-up, weak and strong lists and profiles.
- **Course home: a class topic heatmap.**
  - Rows are topics; columns are mastery bands (< 0.5, 0.5–0.8, ≥ 0.8, not enough data). Each cell is a student count, and clicking it lists the students.
  - Coverage is shown per topic.
  - Students are limited to the teacher's scope (§3.2).

### 6.6 Endpoints (Part C)

| Method and path | Who | Returns |
|---|---|---|
| `GET /intelligence/my/progress/?course=` | `my_progress`; own | roll-up, weak and strong lists, profiles, recent answers (if student view) |
| `GET /tenant-admin/intelligence/students/<id>/progress/?course=` | `my_progress`; student in scope | the same, for that student |
| `GET /tenant-admin/intelligence/courses/<id>/heatmap/` | `my_progress`; course in scope | topic × band counts, coverage |

## 7. Testing

- **Access.** Every new endpoint is tested:
  - with its switch off, it returns 403;
  - a student requesting another student's data gets 403;
  - faculty requesting an unassigned course or student get 403;
  - an admin gets 200.

  The narrowing of the existing Insights views for faculty is tested too.
- **Switch dependencies.** `get_features()` reports a view switch as off while `response_diagnosis` is off. The settings payload marks the dependency.
- **Pure computations, with hand-computed fixtures:**
  - label distribution and flags;
  - patterns;
  - `describe_evidence`;
  - student-note selection, including the low-confidence hide;
  - roll-up weighting, coverage and `not_enough_data`;
  - the fallback without a tree;
  - weak and strong classification;
  - facet recompute: core and supporting weights, diagnosis down-weighting, decay.
- **Part B:**
  - Build and Tag jobs with a fake LLM, covering estimate, budget refusal, status flow and counts;
  - every editor operation, including merge moving ConceptLinks and ItemTaggings and archiving the source;
  - proposed nodes being used by the tagger;
  - review actions: accept, bulk accept, edit (manual lock, the next sweep skips it), re-tag and add-to-tree.
- **Opt-out regression.** With every switch off: no new background work, no new endpoints reachable, and no new nav items. The `main`-equivalence tests from PR #213 must still pass.
- **Frontend:** `npx vite build` passes. No frontend test runner exists, so new pages get a manual checklist in the PR.
- **Manual walkthrough:** extend the local guide with the new switches, using the CodeMinors and DailyTaiyari test tenants and `CELERY_TASK_ALWAYS_EAGER=true`.

## 8. Rollout

- **Migrations:** additive only.
  - `LearnerFacetState`, `TreeBuildJob` and `TaggingRun` tables;
  - no changes to existing columns.
- **Feature switches:** new keys default to off.
- **No new services.** Jobs reuse the `aigen` and `intelligence` queues.
- **After enabling `my_progress` on a tenant:** run `recompute_learner_state --tenant <id>` once to fill `LearnerFacetState`.
