# intelligence (UNDEPLOYED)

Learner Intelligence Layer: learning events, concept/skill tagging, mastery state, adaptive practice, AI grading of subjective answers, answer diagnosis, "My Progress" and teacher Learning Insights. Doc written 2026-11-14 from a read-only review of the code; nothing here was executed (tests not run by the author of this doc).

## Status

- **Not on `main` / `production`.** `main` (tip `7287616`, 2026-11-11) has no `backend/intelligence/`, no `celery-beat` service and no `OPT_IN_FEATURES`.
- **Most complete version:** remote branch `origin/saksham/learning-layer-2b`, tip `da91ad3` (2026-10-30, "walkthrough fixes for heatmap, breakdown and tag card"). 157 commits over merge-base `6ef5a04` (older main, ~2026-10-17): 13 by arpit-iitb (foundation, Aug 2026, commits `c5a8cb8`..`9b04686`) + 144 by Saksham-Gupta-off (Oct 2026: response diagnosis, tagging v2, syllabus tools, My Progress, visibility).
- **True delta vs its merge base:** 215 files, +52,176 / -154 lines. Breakdown: `backend/intelligence` 115 files / 25.0k lines (incl. ~550 tests), `docs/superpowers` plans+specs 9 files / 21.7k lines (docs only), `frontend/exam-frontend` 47 files / 3.8k, `backend/quiz` 11 files, `backend/mockgen` 6, `backend/chatbot` 7, `backend/coursegen` 2, `backend/core` 3, `backend/exams` 2, `backend/analytics` 2, compose/entrypoint/settings/urls/requirements, wiki (3 files). Real production code outside `intelligence/` is small (~1.5k lines excluding tests).
- **Local checkout** (`feat/intelligence-foundation`, also pushed to `origin/feat/intelligence-foundation` at `9b04686`) is a strict ancestor subset of the 2b branch: the 13 arpit commits are the first 13 of the 2b branch (same hashes). The only local-only commit is `840bb5a` (eager-Celery env toggle), superseded by `634ae46` on 2b. No file exists only on the local branch. **Local branch is superseded; do not merge it separately.**
- Authors: arpit-iitb (foundation: events, state, item tagging v1, practice, AI grading, insights pages), Saksham-Gupta-off (everything from diagnosis onward).
- Specs/plans in the 2b export: `docs/superpowers/specs/2026-10-19-question-tagging-{design,decisions}.md`, `...-response-diagnosis-design.md`, `2026-10-24-learning-layer-2b-design.md`; plans under `docs/superpowers/plans/`. Operator guide: `wiki/backend-guide.md` sections "Response diagnosis", "Analytics counting fix", "Question tagging v2", "Syllabus & tagging tools", "My Progress". Known issues: `docs/TODO.md`.
- Rollout plan: see `project-knowledge/infra/intelligence-rollout.md`.

## Purpose

Turn every graded answer into an observation (LearningEvent), tag every question with what it measures (concept/subtopic, thinking level, skills, difficulty), infer per-student mastery/retention/transfer per concept, and use that to (a) recommend and generate practice sets, (b) auto-grade subjective answers with confidence gating, (c) explain why a mark was won/lost (diagnosis), (d) show students "My Progress" and teachers class/student insights. Entirely opt-in per tenant.

## Architecture

Three strictly separated layers (see docstring of `backend/intelligence/models.py`):

1. **Observation** (append-only): `LearningEvent` (one per graded response; deduped by `dedup_key`; a manual regrade appends a superseding `regraded` event), `AttemptTimeline` (raw per-question interaction log), `ResponseSelfReport`.
2. **Inference** (always recomputed, never mutated incrementally): `LearnerConceptState`, `LearnerFacetState`, `ItemStats`, `ResponseDiagnosis`.
3. **Semantics**: `Concept`/`ConceptAlias`/`ConceptLink` (legacy v1), `SyllabusNode`/`ItemTagging`/`ItemSkillTag`/`TagDefinition`/`SkillPack` (v2 tagging tree).

Data flow:

```
student submits quiz / mock / rich mock / practice set
  -> quiz/views.py calls intelligence.api.record_attempt_events(attempt)      (sync, fail-safe, opt-in gated)
       -> services/events.py bulk_create LearningEvents (dedup_key unique, ignore_conflicts)
       -> enqueue intelligence.diagnose_and_update_state (queue `intelligence`)
            -> services/diagnose.py gathers facts (grading, timeline, prior mastery, ItemStats) -> services/diagnosis.py (pure rules) -> ResponseDiagnosis
            -> services/state.py recompute LearnerConceptState (diagnosis-weighted evidence) ; services/facets.py (my_progress tenants)
  -> intelligence.hooks.on_attempt_graded -> enqueue intelligence.recompute_recommendations (practice tenants) -> recommendation.py makes PracticeSets
  -> hooks.maybe_enqueue_ai_grading (rich mock with pending subjective answers, ai_grading tenants) -> intelligence.grade_subjective (queue `aigen`)
weekly/on-demand: intelligence.tagging_sweep -> tagging.py (v1, flat concepts) / tagging_v2.py (tree-bound, two stage) -> ConceptLink / ItemTagging
nightly: recompute_item_stats (02:00 IST), refresh_learner_state (03:00 IST) ; every 15 min: grading_sweep
```

- **Recompute convention (`backend/intelligence/versions.py`):** versions `EVENT_SCHEMA_VERSION=1, STATE_MODEL_VERSION=2, ITEM_STATS_VERSION=1, TAGGER_PROMPT_VERSION=1, ONTOLOGY_VERSION=1, CLASSIFIER_VERSION=1, TAGGER_V2_PROMPT_VERSION=2, FACET_MODEL_VERSION=1`. Changing algorithm/prompt/threshold = bump the constant, re-run the matching command (`recompute_diagnoses` for classifier, `recompute_learner_state` for state/facets, `sync_taxonomy --retag-subjects` for tags). Never a migration.
- **Fail-safe boundary:** other apps may only import `intelligence.api` and `intelligence.hooks` (docstring rule in `models.py`; `mockgen/apply.py` and `coursegen/apply.py` also import `services.itemtags` directly). Every function there swallows exceptions and logs (`logger.exception`) so a Redis blip or bug never fails a student submit. Lost enqueues are healed by the nightly `refresh_learner_state` (re-processes attempts finalized in the last 48h) and `grading_sweep`.
- **Enqueue retry cap:** `api.ENQUEUE_RETRY_POLICY` (max 1 retry, <1s) applied per call via `api.enqueue(...)`; global `CELERY_BROKER_TRANSPORT_OPTIONS` deliberately unchanged from main (test `test_celery_config.py` asserts it).
- **Opt-in gate:** `api.intelligence_enabled(tenant)` is true if the tenant has ANY of `LEARNING_FEATURES = practice, ai_grading, response_diagnosis, syllabus_tools, my_progress`. For other tenants every hook is a no-op, the timeline endpoint answers 204 and writes nothing, nightly jobs skip them, generators produce main's exact output.
- **Tenant dependency:** `diagnosis_teacher_view` and `diagnosis_student_view` require `response_diagnosis` (`Tenant.FEATURE_REQUIRES`; `get_features()` reports them off while it is off).

## Key models (backend/intelligence/models.py; all inherit core `TimeStampedModel`: UUID pk, nullable `tenant` FK, timestamps)

| Model | Purpose / key fields |
|---|---|
| `Concept`, `ConceptAlias`, `ConceptLink` | v1 concept vocabulary per tenant+subject (unique `tenant,subject,slug`); alias funnel in `services/normalize.py`; `ConceptLink` links a concept to exactly one Question XOR MockTestItem (check constraint), has `is_primary`, `weight`, `source` (generator/llm_tagger/manual), `tagger_version` |
| `LearningEvent` | append-only graded response: student, `source_type` (quiz_answer / mock_bank_answer / mock_item_answer / practice_answer), `event_kind` graded/regraded, SET_NULL FKs to answer/question/mock_item, topic+subject snapshots, `occurred_at`, `score_fraction`, time, `response_digest`, unique `dedup_key`. Index `(tenant, occurred_at)` |
| `LearnerConceptState` | per student x concept: mastery, retention/stability, transfer, confidence, `computed_at`, version stamp |
| `LearnerFacetState` | per student x subject x skill/thinking-level (migration 0007; My Progress) |
| `ItemStats` | per-item empirical stats (OneToOne question or mock_item): attempts, p-value, discrimination, distractors, active-time aggregates |
| `CoursePracticeConfig` | per-course practice knobs (OneToOne course) |
| `PracticeSet`, `PracticeSetItem` | recommended 8-item set per diagnosed deficit; statuses suggested/in_progress/...; TTL 14 days |
| `PracticeGenerationJob`, `GeneratedItem` | LLM generation for thin pools; generated items are real `quiz.Question` rows + provenance sidecar |
| `SubjectiveEvalSpec` | compiled grading spec (rubric -> criteria) per subjective item, cached |
| `AITaggingResult` | LLM tag payload cache keyed `(tenant, content_hash, prompt_version, taxonomy_version, ...)` |
| `AttemptTimeline` | raw per-question event sessions per attempt |
| `ResponseSelfReport` | student's own "what happened?" choice per item |
| `ResponseDiagnosis` | label per item per attempt (not_seen, skipped, time_pressure, correct, correct_lucky, correct_slow, guess, second_guess, careless_slip, concept_gap, unclear) + confidence + evidence; indexes `(attempt_kind, attempt_id)`, `(tenant, final_label)`, `(tenant, computed_at)` |
| `TaxonomyRelease`, `SkillPack`, `TagDefinition` | platform-wide (tenant NULL) tag vocabulary loaded from `taxonomy/tags.yaml` by `sync_taxonomy`; current release = highest `sequence` |
| `SyllabusNode`, `CourseSyllabus` | per-subject tree (sub-subject/topic/subtopic; unique `tenant,subject,key`); `CourseSyllabus` says course uses an exam tree OR a built tree |
| `ItemTagging`, `ItemSkillTag` | v2 tag set per item (primary node, thinking level, difficulty, confidence, `review_status` auto/needs_review/..., source llm/manual); skills core(1.0)/supporting(0.5) |
| `SyllabusJob` -> `TreeBuildJob`, `TaggingRun` | background job rows (multi-table inheritance) with status, summary JSON, tokens, cost_usd |

Added to existing apps: `quiz.Question` and `quiz.MockTestItem` gain `cognitive_type, content_hash, tagging_status, tagged_at` (MockTestItem also `topic, subject, difficulty` + index `(topic, difficulty)`); `quiz.MockTestAnswer` gains `ai_graded, ai_confidence, ai_suggested_marks, ai_feedback, ai_flags`; `exams.Topic.objectives` (JSON list); `chatbot.AISettings.tagging_model/grading_model`; `chatbot.AIUsageRecord.feature` choices `itemtag, practicegen, grading`.

## API

Mounted in `backend/dailytaiyari/urls.py`: `api/v1/intelligence/` -> `intelligence.urls`; `api/v1/tenant-admin/intelligence/` -> `intelligence.admin_urls` (which includes `intelligence.syllabus_urls` under `syllabus/`).

**Student prefix `/api/v1/intelligence/`** (`views.py`; all `IsAuthenticated` + a tenant-feature permission):

| Route | View | Gate |
|---|---|---|
| `practice/sets/` (list/retrieve) + POST `.../{id}/start|answer|submit|dismiss/` | `PracticeSetViewSet` | `practice` |
| `practice/refresh/` POST (6/hour throttle `RefreshThrottle`) | `PracticeRefreshView` | `practice` |
| `mastery/` GET | `MasteryView` | `practice` |
| `timeline/` POST (own throttle scope `timeline`, 20/min, 256 KB cap; returns 204 for non-opted tenants) | `TimelineSyncView` | any learning feature |
| `self-report/` POST | `SelfReportView` | `response_diagnosis` |
| `my/progress/?course=` GET | `MyProgressView` | `my_progress` (recent answers only if `diagnosis_student_view`) |
| `my/attempts/<kind>/<uuid>/diagnosis/` GET | `MyAttemptDiagnosisView` | `diagnosis_student_view` |

**Admin prefix `/api/v1/tenant-admin/intelligence/`** (`admin_views.py`, `syllabus_views.py`); roles `admin` + `instructor` (faculty) unless noted; faculty scoping via `access.py` (assigned courses + approved-enrolled students; admins = whole tenant):

| Route | Gate / role |
|---|---|
| `overview/`, `assessments/<kind>/<id>/report/`, `students/<id>/diagnosis/`, `generated-items/`, `generation-jobs/`, `courses/<id>/practice-config/`, `tagging/run/` (POST, queues `tag_items_for_tenant`; returns `queued:false` if tenant not opted in) | admin or instructor |
| `assessments/<kind>/<id>/behaviour/`, `students/<id>/answers/`, `courses/<id>/behaviour/` | admin/instructor + `diagnosis_teacher_view` |
| `diagnosis/calibration/?days=` | **admin only** |
| `students/<id>/progress/`, `courses/<id>/heatmap/` | admin/instructor + `my_progress` |
| `syllabus/courses/<id>/tree/` (+ `tree/estimate/`, `tree/build/`, `tree/exam/`), `courses/<id>/nodes/`, `nodes/<id>/` (+ `merge/`), `courses/<id>/skill-packs/`, `courses/<id>/tagging/estimate|run/`, `jobs/<id>/`, `review/` (+ `bulk-accept/`, `<id>/`, `<id>/accept|retag|add-to-tree/`), `items/<kind>/<id>/tags/` | admin/instructor + `syllabus_tools` |

Also changed in quiz: new `POST <quiz prefix>/mock-tests/attempts/<attempt_id>/request-regrade/` (`MockTestViewSet.request_regrade`; student disputes an AI-graded subjective answer; one-shot; returns it to the human queue) in `backend/quiz/views.py`; admin attempt detail now returns `ai_*` fields.

## Business logic

Modules under `backend/intelligence/` (services = DB shells, pure cores separate): `services/events.py` (emission), `state.py` (decayed mastery, half-life 30d, Laplace prior, spacing-based retention, transfer split), `facets.py`, `diagnose.py`/`diagnosis.py` (+ `diagnosis_config.py` thresholds, `visibility.py`/`visibility_config.py` display rules, `progress_config.py` bands), `timeline.py`/`timeline_sync.py`, `itemstats.py`, `recommendation.py` (tag-algebra, no LLM; set size 8, 21-day seen cooldown, min 4 observations), `practice.py`, `practice_generation.py` (8 items/job, max 20 jobs and 160 items per tenant/day, 30-day cooldown per deficit signature), `grading.py` (compile spec once per item, grade per answer; `ACCEPT_CONFIDENCE=0.75`), `tagging.py` (v1: batch 12/call, cached), `tagging_v2.py`+`tagging_sweep.py` (two stage: topic from tree, then subtopics/thinking/skills/format/difficulty), `taxonomy.py`, `syllabus.py`/`course_tree.py`/`tree_editor.py` (tree build/edit), `tag_review.py`, `rollup.py` (progress roll-up subtopic->subject, computed on read), `itemtags.py`, `normalize.py`, `llm.py` (MeteredCall, `budget_status`), `eval_jee.py`/`tag_eval.py` (dev-only evaluation).

**Celery tasks** (`backend/intelligence/tasks.py`; schedule from `CELERY_BEAT_SCHEDULE` in `backend/dailytaiyari/settings.py`, `CELERY_TIMEZONE = TIME_ZONE` = Asia/Kolkata):

| Task name | Queue | Schedule / trigger |
|---|---|---|
| `intelligence.update_learner_state`, `intelligence.diagnose_and_update_state` | `intelligence` | per finalized attempt |
| `intelligence.recompute_recommendations`, `intelligence.recompute_concept_states` | `intelligence` | after attempt (practice) / after node merge |
| `intelligence.recompute_item_stats` (limit 1800s) | `intelligence` | beat `crontab(02:00)` IST |
| `intelligence.refresh_learner_state` (limit 1800s; also catches lost enqueues, 48h window) | `intelligence` | beat 03:00 IST |
| `intelligence.grade_subjective` (soft 1500s) | `aigen` | on rich-mock submit with pending subjective answers |
| `intelligence.grading_sweep` (300s) | `aigen` | beat every 15 min |
| `intelligence.practice_generation` | `aigen` | when recommendation finds thin pool |
| `intelligence.tag_items` | `aigen` | admin "run tagging" / sweep |
| `intelligence.tagging_sweep` | `aigen` | beat Sunday 04:00 IST |
| `intelligence.build_course_tree`, `intelligence.tagging_run` (<=500 items), `intelligence.retag_item` | `aigen` | syllabus tools UI |

Compose: `celery-intelworker` (queue `intelligence`, `CELERY_INTEL_CONCURRENCY` default 1), `celery-beat` (scheduler only). `aigen` is served by the existing `celery-aiworker`.

**Management commands** (`backend/intelligence/management/commands/`):

| Command | Purpose |
|---|---|
| `sync_taxonomy [--check] [--retag-subjects ids]` | validate/load `taxonomy/tags.yaml` (+ exam trees). Idempotent; **runs automatically in `backend/entrypoint.sh` on every web start** (non-fatal) |
| `backfill_analytics_tenant` | fill NULL `tenant` on analytics tables (TopicMastery, SubjectPerformance, DailyActivity, Streak, WeeklyReport, StudySession) |
| `backfill_learning_events [--tenant --since --batch-size]` | LearningEvents from history (idempotent). NOT opt-in gated: run per opted-in tenant |
| `seed_concepts [--tenant]` | harvest `Question.tags` and `chatbot.AIQuizQuestion.topic` into Concepts |
| `tag_items [--tenant --limit --model]` | tagging sweep from CLI (budget-gated; explicit `--tenant` runs even for non-opted tenants with a note) |
| `recompute_diagnoses [--tenant --since]` | after classifier bump; also refreshes learner state for quiz/mock attempts |
| `recompute_learner_state [--tenant --student --no-facets]` | after backfill/tagging/merge/version bump |
| `recompute_item_stats [--tenant]` | same as nightly job |
| `map_course_to_exam --course --exam --subject-map`, `build_course_tree --course [--model --packs --dry-run]` | create syllabus trees (exam-mapped / LLM-built) |
| `make_gold`, `evaluate_tagger`, `import_eval_jee`, `draft_exam_tree` | dev/eval only. `import_eval_jee` refuses unless DEBUG, tenant subdomain starts `lab-`, DB local. Output must live under `data_dumps/` |

Typical order after first enable on a tenant: `backfill_analytics_tenant` -> `backfill_learning_events --tenant X` -> (`seed_concepts --tenant X`) -> `tag_items --tenant X` (repeat) -> `recompute_diagnoses --tenant X` (optional) -> `recompute_learner_state --tenant X`.

## Touch points in other apps

- `backend/quiz/views.py`: calls `intelligence_api.record_attempt_events` + `intelligence_hooks.on_attempt_graded` at the quiz submit, legacy mock submit and rich-mock submit sites; `maybe_enqueue_ai_grading` after rich submit when manual items pend; new `request_regrade` action; explicit `AnalyticsService.update_*` calls added at the three submit sites.
- `backend/quiz/signals.py` **deleted** and `quiz/apps.py ready()` no longer imports it: the old `post_save` signals re-ran analytics on every save of a completed attempt (2-3x double counting). **Applies to ALL tenants, not flag-gated.**
- `backend/quiz/mock_grading.py`: new `award_completion_xp()` (exactly-once XP; replaces inline XP code in `quiz/views.py` and `quiz/admin_views.py`). **Applies to all tenants**; re-attempt rule changed slightly at grading time (see docstring).
- `backend/quiz/admin_views.py`: `record_regrade_event` after manual regrade, `record_attempt_events` on finalize; `quiz/admin_serializers.py`: `mark_item_stale_if_changed` on create/update of items (gated).
- `backend/analytics/services.py`, `views.py`: `get_or_create(... defaults={'tenant': ...})` so new rows carry tenant (**all tenants**; previously NULL).
- `backend/mockgen/{apply,generation,prompts,schema,serializers}.py`: tenants with learning layer get a tagging-aware prompt/draft shape (`concepts`, `cognitive_type`) and `_tag_row` at apply; all other tenants get main's exact output (`tagged` flag).
- `backend/coursegen/apply.py`: `_tag_question` (gated) and persists `Topic.objectives` (**all tenants**, fills only the new column when empty).
- `backend/chatbot/`: `AISettings.tagging_model/grading_model`, `AIUsageRecord` features, `providers.py` now retries without `temperature` when a model rejects it (**all AI calls**, remembered per process in `_NO_TEMPERATURE`).
- `backend/core/models.py`: `FEATURE_CHOICES` +7 keys, `OPT_IN_FEATURES`, `FEATURE_REQUIRES`, `get_features()` changed (missing key -> disabled for opt-in keys; dependent features off while requirement off); `core/admin_serializers.py` & `superadmin_serializers.py` expose `requires`/`requires_label`.
- `backend/dailytaiyari/settings.py`: `intelligence.apps.IntelligenceConfig` in INSTALLED_APPS, `CELERY_BEAT_SCHEDULE`, `CELERY_TIMEZONE`, eager-task handling; `urls.py`; `requirements.txt` +`PyYAML==6.0.3`; `entrypoint.sh` runs `sync_taxonomy`; `docker-compose.yml` +2 services.

## Settings / env vars / flags

- Env: `CELERY_TASK_ALWAYS_EAGER` (default False; LOCAL ONLY, `'test' in sys.argv` also forces eager with `CELERY_TASK_EAGER_PROPAGATES=False`), `CELERY_INTEL_CONCURRENCY` (default 1). No other new env var; no secrets.
- Tenant `features` JSON keys (opt-in: missing = OFF): `practice` (Smart Practice), `ai_grading` (AI Subjective Grading), `response_diagnosis` (Answer Diagnosis), `diagnosis_teacher_view`, `diagnosis_student_view` (both need `response_diagnosis`), `syllabus_tools` (Syllabus & tagging tools), `my_progress`. Toggle via super-admin Tenant detail or tenant-admin settings (labels renamable). `feature_locks` (super-admin) still win.
- `AISettings` (per tenant): `tagging_model`, `grading_model` (empty = tenant default model); `monthly_token_budget` (existing) gates tagging/grading/generation/tree-build via `coursegen.generation._check_budget` (counts only `SOURCE_TENANT` usage, i.e. tenant's own key).
- Tuning files (display-only unless noted): `diagnosis_config.py` (bump `CLASSIFIER_VERSION` after change), `visibility_config.py`, `progress_config.py` (facet weights -> bump `FACET_MODEL_VERSION`), `taxonomy/tags.yaml` (`version`, `review_confidence_threshold: 0.9`), `taxonomy/exams/jee_main.yaml`.
- DRF throttle scope: `timeline` 20/min is class-level on `TimelineThrottle` (not in `REST_FRAMEWORK` rates).

## Frontend (frontend/exam-frontend/src, 47 files, no new tests)

- Routes added in `App.jsx`: student `/practice`, `/practice/:setId`, `/progress` (FeatureRoute); admin `/admin/insights`, `/admin/insights/tag-review` (syllabus_tools), `/admin/insights/assessments/:kind/:assessmentId`, `/admin/insights/students/:studentId`, `/admin/insights/diagnosis-quality` (AdminRoute).
- Pages: `Practice.jsx`, `PracticeSession.jsx`, `MyProgress.jsx`, `InsightsHome.jsx`, `AssessmentReport.jsx`, `StudentDiagnosis.jsx`, `DiagnosisQuality.jsx`, `TagReview.jsx`; edited attempt/review pages (`QuizAttempt`, `MockTestAttempt`, `RichMockAttempt`, `*Review`) to capture timelines (`hooks/useResponseTimeline.js`, `services/timelineService.js`) and show diagnosis notes (`components/review/DiagnosisNote.jsx`, `WhatHappened.jsx`).
- Components: `components/insights/*`, `components/progress/*`, `components/syllabus/*` (`SyllabusPanel` embedded in `CourseManager.jsx` behind `syllabus_tools`), services `practiceService, insightsService, progressService, syllabusService, diagnosisService`.
- `context/tenantStore.js`: `OPT_IN_FEATURES`, `isFeatureVisible/isOptInFeatureEnabled/isAnyOptInFeatureEnabled` (opt-in keys need explicit `true`); `Sidebar.jsx` (Smart Practice, My Progress) and `AdminSidebar.jsx` (Learning Insights) filter on them. `superadmin-frontend/.../TenantDetail.jsx` greys out dependent flags.
- Non-opted tenants: attempt screens send the same payload as before (no timeline). Frontend deploys via Netlify separately from the backend; shipping frontend before backend is harmless only if the flags are off (opt-in keys absent -> hidden).

## Tests

- 550 `def test_` in `backend/intelligence/tests/` (38 files: diagnosis rules/classifier, tagging v1/v2/sweep, syllabus API/jobs/tree editor, progress rules/API/rollup, visibility API/rules/switches, grading, practice, state, facets, timeline, self-report, gate, access, taxonomy, eval_jee, celery config) + ~22 added in `backend/quiz/tests.py`, `mockgen/tests.py`, `coursegen/tests.py`, `chatbot/tests_providers.py`.
- Run from `backend/`: `python manage.py test intelligence` (then `quiz mockgen coursegen chatbot`). Under `test`, Celery is eager. With `DB_NAME` unset settings fall back to SQLite; with it set, Postgres. No CI workflow exists in the repo (`.github/` has only skills). Not run for this document.
- Known flaky: `chatbot.tests.ExhaustionNoticeTests.test_exhaustion_warns_again_after_the_threshold_warning` (Windows clock tick), per `docs/TODO.md`.
- `sync_taxonomy --check` validates YAML (suitable CI step).

## Gotchas / risks

1. **Migration conflict on merge:** `exams` will have two leaves, `0015_course_is_hidden` (main) and `0015_topic_objectives` (branch); `migrate` aborts until a merge migration is added. `intelligence/0005+` and `quiz/0012` depend on `exams.0015_topic_objectives`.
2. **Not everything is flag-gated:** signal removal (analytics now count once; student totals "grow slower", history stays inflated), analytics tenant defaults, XP refactor, `Topic.objectives`, provider temperature retry, `Tenant.get_features()` change, new migrations. These hit every tenant on deploy.
3. **Any single flag enrolls the tenant in LLM tagging** (weekly sweep up to 200 items, v1 or v2), even `response_diagnosis` alone. Budget guard only counts tenant-own-key tokens; platform-key spend is not capped by it (unverified whether platform allocation limits apply).
4. **AI grading auto-accepts** grades with confidence >= 0.75 and finalizes the attempt and awards XP; escalated/disputed answers go to the human queue. Student can dispute once.
5. **Backfill commands ignore the opt-in gate** (`backfill_learning_events`, `recompute_learner_state` default all tenants) but nightly jobs skip non-enabled tenants, so stray events stay inert.
6. **Rollback:** Django removes DB defaults after adding NOT NULL columns, so old code inserting `quiz_question`, `quiz_mocktestitem`, `quiz_mocktestanswer`, `exams_topic`, `chatbot_aisettings` rows would hit NOT NULL violations once the migrations are applied (reasoning, not tested). See rollout doc.
7. Spec 2b says "no new services"; reality: `celery-intelworker` and `celery-beat` were added to compose. The user's older memory note mentions only `celery-beat`.
8. Local-only dataset: `eval_jee` is unlicensed; `.gitignore` on 2b ignores `data_dumps/` (plural). The user's working tree has an untracked `data_dump/` (singular); not covered.
9. Open issues (`docs/TODO.md`): deleting a Question/Topic/Subject cascades and wipes quiz Answer history (LearningEvent is SET_NULL-safe); `RefreshThrottle` shares the `user` scope; nginx `client_max_body_size` is 1024M so the timeline 256 KB cap relies on Content-Length; `npm ci` fails (lockfile out of sync, `hls.js`); legacy mock screen timeline has no attempt.
10. Timeline clocks: quizzes/rich mocks server-clocked; legacy mock/PYP client-clocked (reload replaces sessions).
11. Frontend `package-lock.json` out of sync on main (per TODO) may break the Netlify build independent of this feature (unverified).

## Key files

- `backend/intelligence/api.py`, `hooks.py` (the boundary), `versions.py`, `models.py`, `tasks.py`, `urls.py`, `admin_urls.py`, `syllabus_urls.py`, `views.py`, `admin_views.py`, `syllabus_views.py`, `access.py`
- `backend/intelligence/services/{events,state,diagnose,diagnosis,grading,tagging_v2,tagging_sweep,practice_generation,rollup,facets}.py`, `recommendation.py`
- `backend/intelligence/migrations/0001..0007`, `taxonomy/tags.yaml`, `taxonomy/exams/jee_main.yaml`
- `backend/quiz/{views,admin_views,mock_grading,models}.py`, `backend/core/models.py` (flags), `backend/dailytaiyari/settings.py`, `backend/docker-compose.yml`, `backend/entrypoint.sh`
- `wiki/backend-guide.md` (operator guide), `docs/superpowers/specs/*`, `docs/TODO.md`
