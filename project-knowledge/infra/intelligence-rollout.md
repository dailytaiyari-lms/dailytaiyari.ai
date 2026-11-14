# Intelligence layer: production rollout plan

Companion to `project-knowledge/backend/intelligence.md`. Written 2026-11-14 from read-only inspection of `origin/main` (`7287616`) and `origin/saksham/learning-layer-2b` (`da91ad3`). Nothing was executed or tested by the author; items marked "unverified" need confirming on a pre-prod copy.

## 1. What is being deployed

- Source: `origin/saksham/learning-layer-2b`, 157 commits over merge-base `6ef5a04`; `main` has moved 8 commits since (all Balbir Yadav, Nov 2-11: tenant registration/guardian consent, tenant email domains, hidden courses).
- True delta vs merge base: 215 files, +52,176 / -154 (25k lines in `backend/intelligence`, 21.7k lines of plan/spec docs, 3.8k frontend, rest small touches). See intelligence.md for breakdown.
- The user's local `feat/intelligence-foundation` is a strict subset (first 13 commits) of this branch. Ship the 2b branch, not the local one.

## 2. Pre-merge work (before any deploy)

Merge `origin/main` INTO the 2b branch (or cut an integration branch from main and merge 2b into it). A dry run with `git merge-tree --write-tree origin/main origin/saksham/learning-layer-2b` shows:

**Files changed by both sides (13):** `backend/core/models.py` (REAL CONFLICT), `backend/core/admin_serializers.py`, `backend/core/superadmin_serializers.py`, `backend/dailytaiyari/settings.py`, `backend/docker-compose.yml`, `backend/exams/models.py`, `backend/quiz/views.py`, `frontend/exam-frontend/src/App.jsx`, `.../components/admin/builderShared.jsx`, `.../pages/AdminDashboard.jsx`, `.../pages/CourseManager.jsx`, `frontend/superadmin-frontend/src/pages/TenantDetail.jsx`, `wiki/environment-variables.md`. Git auto-merges all but `core/models.py`.

1. **`backend/core/models.py` conflict:** adjacent insertions after `ADVANCED_SETTING_CHOICES`. Keep BOTH: main's `REGISTRATION_FIELD_CHOICES` block and the branch's `OPT_IN_FEATURES` / `FEATURE_REQUIRES` blocks. Also confirm `FEATURE_CHOICES` ends with `practice ... my_progress` plus main's `hackathons` and that `get_features()` keeps the branch's version.
2. **Migration graph conflict (not a text conflict, so git will NOT flag it):** `exams` gets two leaf nodes: `0015_course_is_hidden` (main) and `0015_topic_objectives` (branch), both depending on `0014_course_sequential_chapter_unlock`. `migrate` fails with "Conflicting migrations detected". Fix: `python manage.py makemigrations --merge exams` (creates `exams/0016_merge_...`), commit it. `intelligence 0001/0002/0005/0006/0007` and `quiz 0012` depend on `exams.0015_topic_objectives`, which stays valid. Other apps are fine: main added `core 0025-0027` and `users 0015`; branch migrations depend on `core 0022/0024` and `users 0014`, all present. The branch already contains its own merge migrations (`quiz 0014_merge_20261019_1113`, `chatbot 0013_merge_20261019_1113`).
3. Run `python manage.py makemigrations --check --dry-run` (must be clean) and `python manage.py sync_taxonomy --check`.
4. Run the test suites (section 9) on the merged tree, and ideally `migrate` + smoke on a restored copy of the production DB.
5. Frontend: confirm `npm ci`/build on the merged tree (docs/TODO.md says `package-lock.json` is out of sync on main and `npm ci` fails; unverified whether Netlify is affected).
6. Decide whether to include the 9 plan/spec docs (21.7k lines under `docs/superpowers/`); harmless but noisy. Drop `docs/TODO.md` content into the issue tracker if desired.

## 3. New Compose services and env

New services in `backend/docker-compose.yml` (both `build: .`, `restart: unless-stopped`, `entrypoint: []`, share `*app-env`, depend on healthy `db` and `redis`):

| Service | Command | Notes |
|---|---|---|
| `celery-intelworker` | `celery -A dailytaiyari worker --queues=intelligence --concurrency=${CELERY_INTEL_CONCURRENCY:-1}` | per-attempt diagnosis/state, recommendations, nightly jobs. If down, learning-layer statistics silently never run |
| `celery-beat` | `celery -A dailytaiyari beat --schedule=/tmp/celerybeat-schedule` | main has NO beat today. Schedules are in code (`CELERY_BEAT_SCHEDULE`); schedule file is disposable. Run exactly ONE beat instance |

Other facts:
- Existing `celery-aiworker` (`aigen` queue, concurrency `CELERY_AI_CONCURRENCY` default 4) now also carries `intelligence.grade_subjective`, `grading_sweep` (every 15 min), `tagging_sweep` (Sun 04:00 IST), `tag_items`, `build_course_tree`, `tagging_run`, `retag_item`, `practice_generation`. It must be running.
- New env vars: `CELERY_INTEL_CONCURRENCY` (optional, default 1). `CELERY_TASK_ALWAYS_EAGER` exists but must NOT be set in production (it runs every task inside the web request; a 20-minute tree build would hold a gunicorn worker).
- `CELERY_TIMEZONE` is now `TIME_ZONE` (Asia/Kolkata) globally; main has no crontab schedules so nothing else changes (task ETAs are unaffected since UTC stays enabled).
- **New dependency `PyYAML==6.0.3` in `backend/requirements.txt` -> the image MUST be rebuilt** (`docker compose build web celery-worker celery-aiworker celery-intelworker celery-beat`; they all use the same Dockerfile).
- `backend/entrypoint.sh` now runs `python manage.py sync_taxonomy || echo WARNING...` after `migrate` on every web start (non-fatal, idempotent). Check web logs for `WARNING: taxonomy sync failed`.
- No new secrets. Per the deploy-backend skill (`.github/skills/deploy-backend/SKILL.md` section 4b): build + `up -d` the new services, then `up -d web`, verify each service is consuming its queue, not merely running.
- Expected resource cost: two more small containers (concurrency 1 each).

## 4. Migrations (all additive; no RunPython/RunSQL anywhere in the branch)

| App | Migration(s) | What | Risk on large Postgres tables |
|---|---|---|---|
| `chatbot` | `0011_aisettings_tagging_model_alter_aiusagerecord_feature`, `0012_aisettings_grading_model`, `0013_merge_...`, `0014_alter_aiusagerecord_feature` | 2 CharField columns (default '') on `AISettings`; choices-only AlterField on `AIUsageRecord.feature` (no SQL) | Negligible (tiny table) |
| `exams` | `0015_topic_objectives` (+ new `0016` merge) | JSONField default `[]` on `exams_topic` | Low; constant default is metadata-only on PG >= 11 (PG version unverified) |
| `quiz` | `0012_mocktestitem_cognitive_type_and_more`, `0013_mocktestanswer_ai_confidence_and_more`, `0014_merge_...` | `quiz_question`: +4 NOT NULL/nullable columns; `quiz_mocktestitem`: +7 columns incl. 2 nullable FKs (`topic`, `subject`) and index `(topic, difficulty)`; `quiz_mocktestanswer`: +5 columns (`ai_graded` bool default false, `ai_flags` JSON default `[]`, others nullable/blank) | Column adds with constant defaults are fast on PG >= 11. The FK constraints + 3 non-concurrent `CREATE INDEX` on `quiz_mocktestitem` briefly block writes to that table (seconds at the data volume in the Oct-19 prod copy: ~446 completed quiz attempts per `docs/TODO.md`). `quiz_mocktestanswer` is probably the largest touched table; still metadata-only |
| `intelligence` | `0001_initial` .. `0007_learner_facet_state` | creates ~30 new tables, constraints, indexes; 0003/0005 `AddField` only on intelligence's own empty tables | None (new, empty tables). 0005 is the biggest (309 lines) |
| `core` | none | feature flags live in the existing JSON `features` field | none |

- Dependency quirk: `intelligence.0001` depends on `core.0022`, `exams.0015_topic_objectives`, `quiz.0011`, `users.0014`; later ones on `core.0024`, `quiz.0014`. All present after merge.
- Do not edit or renumber applied migrations. The two `chatbot/0011_*` files are deliberate (different names, merged by `0013`).
- Schedule the deploy for a quiet window anyway: `migrate` runs inside `web` start, and Django removes DB-level defaults after adding NOT NULL columns.

## 5. Deployment order (dark deploy first)

Everything user-visible is behind opt-in tenant flags that default OFF, so the whole branch can be deployed "dark". Caveat: a few behaviours apply to ALL tenants regardless of flags (section 8).

1. Pre-prod: merge, rebuild, `migrate`, smoke test with one lab tenant (section 6, 7). Pre-prod deploys from `main`, prod from `production` (wiki/branching-strategy.md).
2. Production backup (DB snapshot). Needed because rollback of schema is non-trivial (section 8).
3. Merge to `main`, promote to `production`.
4. On the VM: pull, `docker compose build`, `docker compose up -d celery-intelworker celery-beat celery-aiworker celery-worker` then `up -d web` (web start runs `migrate` and `sync_taxonomy`). Or `docker compose up -d --build` for all.
5. Verify (see 5b).
6. Frontend deploys via Netlify (auto). Because opt-in keys need an explicit `true` in tenant config, new nav items and routes are hidden until a tenant is enabled.
7. Announce to tenant admins: **analytics numbers change** (signals removed; Topic mastery/subject performance totals now count each attempt once, history stays inflated, timed-out rich attempts now count). Optionally recompute analytics history (no command exists in the branch; unverified).
8. Run `python manage.py backfill_analytics_tenant` (fills NULL `tenant` on 6 analytics tables, row by row, idempotent). Needed so tenant-scoped queries on analytics tables are correct; not tied to any flag.

### 5b. Post-deploy verification

```
docker compose ps                         # web, celery-worker, celery-aiworker, celery-intelworker, celery-beat Up
docker compose logs celery-intelworker | grep -A4 queues     # shows `intelligence`
docker compose logs celery-aiworker | grep -A4 queues        # shows `aigen`
docker compose logs celery-beat --tail=20                    # "beat: Starting..." and schedule entries
docker compose exec -T web python manage.py showmigrations | grep -E '\[ \]' || echo none pending
docker compose exec -T web python manage.py shell -c "from intelligence.models import TaxonomyRelease as T; print(T.objects.count())"   # >=1 after sync_taxonomy
docker compose exec -T web python -c "import yaml"           # PyYAML present
```

Expected beat entries: `intelligence-item-stats` (02:00 IST), `intelligence-learner-state-refresh` (03:00), `intelligence-tagging-sweep` (Sun 04:00), `intelligence-grading-sweep` (every 15 min).

## 6. Per-tenant enablement (opt-in flags)

Toggle in super-admin Tenant detail (or tenant-admin settings). Enabling ANY of the five learning flags starts event accrual, timelines, state jobs and enrolls the tenant in the weekly tagging sweep. Suggested order for a pilot tenant:

| Step | Flag(s) | LLM cost | Then run |
|---|---|---|---|
| 1 | `response_diagnosis` | none directly (rule-based), but enrolls tenant in tagging sweep (LLM) | `backfill_learning_events --tenant T`, optional `recompute_diagnoses --tenant T`, `recompute_learner_state --tenant T` |
| 2 | `diagnosis_teacher_view`, then `diagnosis_student_view` | none | none (display-only) |
| 3 | `my_progress` | none | `recompute_learner_state --tenant T` once (fills facet profiles) |
| 4 | `syllabus_tools` | tree build + tagging (LLM) | build/map syllabus trees, then Tag questions; `sync_taxonomy` already run |
| 5 | `practice` | tagging + practice generation (LLM) | `seed_concepts --tenant T`, `tag_items --tenant T` (repeat until clean), `recompute_learner_state --tenant T` |
| 6 | `ai_grading` | compile + per-answer grading (LLM); auto-grades | set `grading_model`; start with a tenant that tolerates AI marks |

Mandatory ordering for history (per tenant, after flag on): `backfill_learning_events --tenant T` -> `seed_concepts --tenant T` (optional, v1 labels) -> `tag_items --tenant T` -> `recompute_diagnoses --tenant T` -> `recompute_learner_state --tenant T`. Do NOT run the backfill/recompute commands without `--tenant` unless you want events for non-opted tenants (they are inert but cost DB rows; `backfill_learning_events` is not opt-in gated).

Mid-flag changes: feature dependency (`diagnosis_*_view` requires `response_diagnosis`) is enforced in `get_features()`.

## 7. LLM cost implications and budget guards

- **Tagging (v1/v2):** batched 12 items/call, cached by content hash in `AITaggingResult` (identical items across mock tests skip the LLM), roughly 1,000 tokens/question (estimate in `tagging_sweep.TOKENS_PER_QUESTION`, from first evaluation runs). Weekly sweep caps 200 items/tenant/pass; a UI "Tag questions" run caps 500 items; manual tags (`source='manual'`) are never overwritten; edited items are re-tagged. `AISettings.tagging_model` routes to a cheap model.
- **Tree build:** about 1,500 tokens per call; one grouping call per subject with > 6 topics, one subtopic call per topic, one packs call; UI shows an estimate and the tenant's remaining budget first.
- **Grading:** one spec compile per item (tenant default model), then one cheap-model call per subjective answer (`grading_model`); blank answers cost nothing; confidence >= 0.75 and unflagged = auto-accepted. `grading_sweep` retries every 15 min for attempts whose grading never finished.
- **Practice generation:** only when a diagnosed gap has a thin question pool; 8 items/job, max 20 jobs and 160 items per tenant per day, 30-day cooldown per deficit signature; generated items are reusable (once per gap, not per student).
- **Mock generator:** learning-layer tenants get a longer prompt and richer output (concepts, cognitive_type); other tenants unchanged.
- **Metering:** all spend recorded in `AIUsageRecord` with features `itemtag`, `practicegen`, `grading`.
- **Guard:** `_check_budget` blocks (tagging sweep, grading, generation, tree build, retag) when the tenant's `monthly_token_budget` is exhausted, but counts only tokens on the tenant's OWN key (`SOURCE_TENANT`). Spend through the platform-supplied model fleet is NOT capped by this check (whether platform allocation limits catch it is unverified). Set a `monthly_token_budget` on pilot tenants, and review per-tenant `AIUsageRecord` after the first Sunday sweep.
- Every learning flag (even `response_diagnosis` alone) makes the tenant eligible for the Sunday tagging sweep (the first sweep after enable can tag up to 200 items per tenant).

## 8. What is safe dark, what is not, and rollback

**Dark (flag off) means:** no LearningEvents, no timelines (endpoint answers 204), no tasks enqueued from submits, nightly jobs skip the tenant, generators/mockgen/coursegen outputs match main, nav/routes hidden. The new services idle.

**Applies to ALL tenants on deploy (not flag-gated):**
1. `quiz/signals.py` removed: analytics counted once (see announcement above) and explicit `AnalyticsService` calls added at 3 submit sites.
2. `quiz/mock_grading.award_completion_xp` replaces inline XP code in `quiz/views.py` and `quiz/admin_views.py` (exactly-once XP; different re-attempt rule at grading time). Test the mock submit and admin finalize paths.
3. Analytics rows now get `tenant` on create; NULL history needs `backfill_analytics_tenant`.
4. `Topic.objectives` persisted by coursegen apply (column fill only).
5. `chatbot/providers.py`: retries without `temperature` for models that reject it; applies to all AI chat/generation calls.
6. `Tenant.get_features()` semantic change (opt-in keys default OFF, `FEATURE_REQUIRES`) and new `FEATURE_CHOICES` keys visible in settings UIs.
7. New `/api/v1/intelligence/` and `/api/v1/tenant-admin/intelligence/` routes exist (permission-gated), `sync_taxonomy` on every web start.

**Rollback:**
- Flags: turning a tenant's flags OFF is the fast, safe rollback. Data already written (events, states, tags) remains and is inert; nightly jobs skip the tenant.
- Services: stopping `celery-beat`/`celery-intelworker` just stops background work; enqueues pile up on the `intelligence` queue in Redis (bounded by opted-in tenants) and run when restarted.
- Code revert: redeploying the old (main) image against the migrated DB is UNSAFE. Django drops DB defaults after adding NOT NULL columns, so old code inserting into `quiz_question`, `quiz_mocktestitem`, `quiz_mocktestanswer`, `exams_topic`, `chatbot_aisettings` would fail with NOT NULL violations (reasoning from Django behaviour; confirm on pre-prod). Options: (a) roll forward with a hotfix, (b) reverse the branch's migrations before redeploying old code, targeting main's last migration of each app so main's own migrations stay applied: `migrate intelligence zero`, `migrate quiz 0012_quizattempt_proctoring`, `migrate exams 0015_course_is_hidden`, `migrate chatbot 0011_alter_aiusagerecord_feature` (Django unapplies the non-ancestor branch migrations; verify the plan with `migrate --plan` on pre-prod first). This destroys all intelligence data and AI-grading fields. In practice treat the schema as one-way: rely on flags, plus a pre-deploy DB snapshot.
- Restoring the quiz post_save signals by revert would reintroduce double counting.

## 9. Tests and how to run

- 550 tests in `backend/intelligence/tests/` plus ~22 added to `backend/quiz/tests.py`, `mockgen/tests.py`, `coursegen/tests.py`, `chatbot/tests_providers.py`.
- From `backend/`: `python manage.py test intelligence`, then `python manage.py test quiz mockgen coursegen chatbot core analytics`. `'test' in sys.argv` forces eager Celery. DB: SQLite fallback when `DB_NAME` unset; Postgres otherwise. No CI runs them (no `.github/workflows`).
- Known flaky on Windows: `chatbot.tests.ExhaustionNoticeTests.test_exhaustion_warns_again_after_the_threshold_warning`.
- Frontend: no tests added; manual walk-through per flag (student `/practice`, `/progress`, review-page notes; admin `/admin/insights`, tag review, Syllabus tab in Course Manager).
- Suggested pre-prod smoke: submit a quiz, a legacy mock and a rich mock on a flag-off tenant (no events, normal XP/analytics, one count) and on a flag-on tenant (events + diagnosis rows appear, `intelligence` queue consumed).

## 10. Rollout checklist (short)

1. Merge main into 2b branch; resolve `core/models.py`; add `exams` merge migration; `makemigrations --check` clean; tests green.
2. Pre-prod: rebuild image (PyYAML), `up -d` new services, verify queues and beat; enable flags on one lab tenant, run the command sequence.
3. Prod: DB snapshot; deploy; verify; run `backfill_analytics_tenant`; announce analytics-count change.
4. Pilot tenant: enable flags in the order of section 6 with a token budget set; watch `AIUsageRecord` and worker logs for 1 week (include the Sunday sweep).
5. Widen tenant by tenant. Move a flag out of `OPT_IN_FEATURES` only once it is on for everyone.
