# Learning Layer 2B, Part B — Syllabus and Tagging Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let admins and assigned faculty build a course's syllabus tree from
the UI, edit it, run tagging, and work a tag review queue, without the
command line.

**Architecture:**
- **Switch:** one opt-in switch, `syllabus_tools`, which also joins
  `LEARNING_FEATURES`.
- **Jobs:** two job tables, `TreeBuildJob` and `TaggingRun`, record each
  background run on the `aigen` queue (status, summary, tokens, cost). The
  workers call the existing `build_course_tree` and `tag_v2_for_tenant`.
- **Services:**
  - `services/tree_editor.py` — tree payload and edit operations;
  - `services/tag_review.py` — review actions, including the manual lock.
  - The views stay thin.
- **Tagger changes:**
  - `build_course_tree` now creates LLM subtopics as `proposed`;
  - the tagger reads both `active` and `proposed` nodes;
  - the sweep reports tagged / needs-review / failed counts.
- **Local testing:** a `CELERY_TASK_ALWAYS_EAGER` env switch runs tasks
  inside the request, so Build and Tag finish without a worker.
- **Frontend:**
  - a "Syllabus" view on the course editor (build, exam mapping, tagging,
    job history, tree editor, filtered review queue);
  - a tenant-wide Tag review page under Learning Insights;
  - a read-only Tags panel in the question editors.

**Tech Stack:** Django 5 / DRF, Celery (`aigen`, `intelligence` queues),
SQLite (tests), React 18 + Vite + TanStack Query + Tailwind.

**Spec:** `docs/superpowers/specs/2026-10-24-learning-layer-2b-design.md`
§2, §3 and §5. Part A's plan
(`2026-10-28-learning-layer-2b-a-diagnosis-visibility.md`) must be done
first: this plan uses `intelligence/access.py`, `IsTenantAdminOrInstructor`,
`isAnyOptInFeatureEnabled` and the `features` list on admin nav items.

## Global Constraints

**Environment**
- Run backend commands from `backend/` with `venv/Scripts/python.exe`.
- Test command shape:
  `venv/Scripts/python.exe manage.py test <dotted.path> -v 2`.
- Frontend check: `npx vite build` in `frontend/exam-frontend/`.

**Git**
- Local branch `saksham/learning-layer-2b`. Never push. Never change git
  config.
- Stage only the files your task names. Never `git add -A` / `git add .`.
- End every commit message with the `Co-Authored-By:` line in your dispatch.

**Architecture rules**
- Other apps reach the intelligence layer only through `api.py` / `hooks.py`.
  The question editors call intelligence endpoints over HTTP only.
- New models inherit `core.models.TimeStampedModel`. Migrations are additive.
- LLM calls go through `services/llm.tenant_tagging_call(tenant)` (metered
  into `AIUsageRecord`, feature `itemtag`). Only question text, topic names
  and objectives are sent to the model, never student data.
- Every endpoint requires `syllabus_tools` (403 when off) and, for course,
  node, job or tagging-scoped calls, `can_manage_course` (403 out of scope).
  A missing object is 404. Refused edits are 400 with `{'error': message}`.
- Manual tags (`ItemTagging.source == 'manual'`, `ItemSkillTag.source ==
  'manual'`, `ConceptLink.source == 'manual'`) are never overwritten by the
  tagger. This plan only adds ways to create them.
- `CELERY_TASK_ALWAYS_EAGER` is never set in production.

**Values**
- Job statuses: `queued` → `running` → `done` / `failed`.
- Build estimate: `TOKENS_PER_CALL = 1500`. Tagging estimate:
  `TOKENS_PER_QUESTION = 1000`. One tagging run tags at most
  `TAGGING_RUN_LIMIT = 500` items.
- Review page size: 25. Job history: last 10 runs (both kinds together).
- Review reasons: `low_confidence`, `invalid_key`, `proposed_subtopic`,
  `stage_disagreement`.

**Decisions this plan makes where the spec is silent**
1. **Exam tree and built tree don't mix.** Build is refused for a course
   mapped to an exam tree, and exam mapping is refused for a course that
   already has a built tree. Mixing them would leave two parallel trees
   under one subject.
2. **One active job per course and kind.** A second Build or Tag while one is
   `queued` / `running` returns 409 with the running job.
3. **Tree version.** Add, rename, archive and merge change the tree version
   (they change the node set, names or descriptions that `compute_tree_version`
   hashes). Moving a topic, weightage, accepting a suggestion and skill packs
   don't. They don't change which subtopic a question belongs to, and
   changing the hash would re-tag every item. Re-tagging after a pack change
   is done per item with Re-tag.
4. **Two extra read endpoints:**
   - `GET review/<tagging_id>/` returns one row plus its edit choices (the
     form needs the tree and vocabulary);
   - `GET items/<kind>/<id>/tags/` feeds the question editors' Tags panel.
5. **Manual edit drops tagger links.** Saving an edit deletes the item's
   `llm_tagger` ConceptLinks and writes `manual` ones. Generator links stay.
6. **Re-tag on a manually edited item** turns it back into a tagger item
   (`source='llm_tagger'`) first, because the teacher asked for it
   explicitly. Its `manual` ConceptLinks and `ItemSkillTag`s become
   `llm_tagger` rows too, so the re-tag replaces them (otherwise the item
   would keep the manual primary link beside the tagger's new one).
7. **Merge recomputes learner state.** After a merge, the target concept's
   learner states are recomputed on the `intelligence` queue. `merge_concept`
   drops the loser's states, and nothing else would rebuild them.
8. **Add to tree** finds the topic from the tagger's located topic, now saved
   as `ItemTagging.raw['topic_key']`, or else the item's course topic. The
   request may also name a topic node.
9. **Tagging needs a tree.** A tagging run covers only the course's subjects
   that have a tree. With none, or with no taxonomy release synced, it is
   refused with a message saying what to do.

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/core/models.py` (modify) | `syllabus_tools` feature (opt-in) |
| `backend/intelligence/api.py` (modify) | `syllabus_tools` in `LEARNING_FEATURES` |
| `backend/dailytaiyari/settings.py` (modify) | `CELERY_TASK_ALWAYS_EAGER` env switch |
| `backend/intelligence/models.py` (modify) | `TreeBuildJob`, `TaggingRun` |
| `backend/intelligence/migrations/0006_syllabus_jobs.py` | generated |
| `backend/intelligence/services/course_tree.py` (modify) | proposals are `proposed`; `estimate_build` |
| `backend/intelligence/services/syllabus.py` (modify) | `tagging_context` uses active + proposed; `exam_tree_options` |
| `backend/intelligence/services/tagging_sweep.py` (modify) | proposed nodes; `stats`; `candidate_querysets`; `estimate_tagging`; `tag_one_item`; `topic_key` in raw |
| `backend/intelligence/services/llm.py` (modify) | `budget_status(tenant)` |
| `backend/intelligence/services/tree_editor.py` (create) | tree payload; add / update / merge nodes; skill packs; weight warnings |
| `backend/intelligence/services/tag_review.py` (create) | accept, bulk accept, edit (manual), re-tag, add-to-tree, edit choices, row payload |
| `backend/intelligence/tasks.py` (modify) | `run_tree_build`, `run_tagging_run`, `retag_item`, `recompute_concept_states` |
| `backend/intelligence/syllabus_views.py` (create) | every Part B endpoint |
| `backend/intelligence/syllabus_urls.py` (create) | routes |
| `backend/intelligence/admin_urls.py` (modify) | `include('intelligence.syllabus_urls')` at `syllabus/` |
| `backend/intelligence/tests/syllabus_fixtures.py` (create) | tenant, staff, course with a mini exam tree and a custom course |
| `backend/intelligence/tests/test_syllabus_jobs.py`, `test_tree_editor.py`, `test_tag_review.py`, `test_syllabus_api.py` (create) | tests |
| `backend/intelligence/tests/test_course_tree.py`, `test_tagging_sweep.py` (modify) | proposed status; counts |
| `frontend/exam-frontend/src/context/tenantStore.js`, `hooks/useResponseTimeline.js` (modify) | opt-in / learning lists |
| `frontend/exam-frontend/src/services/syllabusService.js` (create) | API calls |
| `frontend/exam-frontend/src/components/syllabus/SyllabusPanel.jsx` (create) | build, exam mapping, tagging, jobs, editor, filtered queue |
| `frontend/exam-frontend/src/components/syllabus/TreeEditor.jsx` (create) | collapsible editor |
| `frontend/exam-frontend/src/components/syllabus/TagReviewList.jsx` (create) | the queue (page + tab) |
| `frontend/exam-frontend/src/components/syllabus/TagEditForm.jsx` (create) | edit modal |
| `frontend/exam-frontend/src/components/syllabus/ItemTagsPanel.jsx` (create) | read-only Tags panel |
| `frontend/exam-frontend/src/pages/TagReview.jsx` (create) | tenant-wide queue |
| `frontend/exam-frontend/src/pages/CourseManager.jsx` (modify) | "Syllabus" view |
| `frontend/exam-frontend/src/components/admin/builderShared.jsx` (modify) | Tags panel in `QuestionModal` |
| `frontend/exam-frontend/src/pages/MockTestBuilder.jsx` (modify) | Tags panel in `ItemEditor` |
| `frontend/exam-frontend/src/pages/InsightsHome.jsx`, `components/layout/AdminSidebar.jsx`, `App.jsx` (modify) | Tag review link, menu, route |
| `wiki/backend-guide.md`, `wiki/environment-variables.md` (modify) | ops + eager switch |

---

### Task 1: The `syllabus_tools` switch and the eager-tasks setting

**Files:**
- Modify: `backend/core/models.py`, `backend/intelligence/api.py`, `backend/dailytaiyari/settings.py`
- Modify: `frontend/exam-frontend/src/context/tenantStore.js`, `frontend/exam-frontend/src/hooks/useResponseTimeline.js`
- Modify: `wiki/environment-variables.md` (`wiki/backend-guide.md` is Task 13)
- Test: `backend/intelligence/tests/test_syllabus_jobs.py` (create; first class)

**Interfaces:**
- Produces: feature key `syllabus_tools` (label "Syllabus & tagging tools", opt-in); `'syllabus_tools' in api.LEARNING_FEATURES`; setting `CELERY_TASK_ALWAYS_EAGER` read from env outside tests.

- [ ] **Step 1: Write the failing test**

Create `backend/intelligence/tests/test_syllabus_jobs.py`:

```python
"""Syllabus tools: switch, job models, workers."""
from django.test import TestCase

from core.models import Tenant
from intelligence import api


class SwitchTests(TestCase):
    def test_syllabus_tools_is_opt_in_and_a_learning_feature(self):
        self.assertIn('syllabus_tools', Tenant.FEATURE_CHOICES)
        self.assertIn('syllabus_tools', Tenant.OPT_IN_FEATURES)
        self.assertIn('syllabus_tools', api.LEARNING_FEATURES)
        tenant = Tenant.objects.create(name='Switch Academy')
        self.assertFalse(tenant.get_features()['syllabus_tools'])
        self.assertFalse(api.intelligence_enabled(tenant))
        tenant.features = {'syllabus_tools': True}
        self.assertTrue(api.intelligence_enabled(tenant))
```

- [ ] **Step 2: Run it to verify it fails**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_syllabus_jobs -v 2`
Expected: FAIL (`'syllabus_tools' not found`).

- [ ] **Step 3: Implement**

`backend/core/models.py`: add to `FEATURE_CHOICES` after the two diagnosis view keys:

```python
        'syllabus_tools': 'Syllabus & tagging tools',
```

and add `'syllabus_tools'` to `OPT_IN_FEATURES`.

`backend/intelligence/api.py`: replace the `LEARNING_FEATURES` line:

```python
# Any one of these switches the learning layer on for a tenant (background
# data collection: events, timelines, diagnosis and state jobs, tagging).
LEARNING_FEATURES = ('practice', 'ai_grading', 'response_diagnosis', 'syllabus_tools')
```

`backend/dailytaiyari/settings.py`: replace

```python
if 'test' in sys.argv:
    CELERY_TASK_ALWAYS_EAGER = True
    CELERY_TASK_EAGER_PROPAGATES = False
```

with

```python
if 'test' in sys.argv:
    CELERY_TASK_ALWAYS_EAGER = True
    CELERY_TASK_EAGER_PROPAGATES = False
else:
    # Local testing only: run every task inside the request, so diagnosis
    # happens right after submit and syllabus Build / Tag finish without a
    # worker. Never set in production (a 20-minute build would hold a web
    # worker for 20 minutes).
    CELERY_TASK_ALWAYS_EAGER = config('CELERY_TASK_ALWAYS_EAGER', default=False, cast=bool)
```

`frontend/exam-frontend/src/context/tenantStore.js`: add `'syllabus_tools'` to `OPT_IN_FEATURES`.

`frontend/exam-frontend/src/hooks/useResponseTimeline.js`: change the `LEARNING_FEATURES` line to

```js
const LEARNING_FEATURES = ['practice', 'ai_grading', 'response_diagnosis', 'syllabus_tools']
```

`wiki/environment-variables.md`: add a row to the table (columns: Variable | Required | Default | Description):

```markdown
| `CELERY_TASK_ALWAYS_EAGER` | No | `False` | Local testing only. `true` runs Celery tasks inside the request (diagnosis right after submit; syllabus Build and Tag without a worker). Never set in production. |
```

- [ ] **Step 4: Run tests**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_syllabus_jobs intelligence.tests.test_gate -v 2`
Expected: PASS. Then check the switch is read:

Run: `CELERY_TASK_ALWAYS_EAGER=true venv/Scripts/python.exe manage.py shell -c "from django.conf import settings; print(settings.CELERY_TASK_ALWAYS_EAGER)"`
Expected: `True` (and `False` without the variable).

- [ ] **Step 5: Commit**

```bash
git add backend/core/models.py backend/intelligence/api.py backend/dailytaiyari/settings.py frontend/exam-frontend/src/context/tenantStore.js frontend/exam-frontend/src/hooks/useResponseTimeline.js wiki/environment-variables.md backend/intelligence/tests/test_syllabus_jobs.py
git commit -m "feat(intelligence): syllabus_tools switch; CELERY_TASK_ALWAYS_EAGER for local runs"
```

---

### Task 2: Job models and migration

**Files:**
- Modify: `backend/intelligence/models.py` (append)
- Create: `backend/intelligence/migrations/0006_syllabus_jobs.py` (generated)
- Test: `backend/intelligence/tests/test_syllabus_jobs.py` (add a class)

**Interfaces:**
- Produces: `TreeBuildJob` and `TaggingRun`, both with `course` (FK, related names `tree_build_jobs` / `tagging_runs`), `started_by` (FK user, nullable), `status`, `options` (JSON), `summary` (JSON), `error`, `tokens`, `cost_usd`, `started_at`, `finished_at`; `STATUS_*` constants; `ACTIVE_STATUSES = ('queued', 'running')`; `payload()` → dict for the API.

- [ ] **Step 1: Write the failing test**

Append to `backend/intelligence/tests/test_syllabus_jobs.py`:

```python
from exams.models import Course
from intelligence.models import TaggingRun, TreeBuildJob


class JobModelTests(TestCase):
    def test_defaults_and_payload(self):
        tenant = Tenant.objects.create(name='Job Academy')
        course = Course.objects.create(tenant=tenant, name='C', code='job-c', course_type='skill')
        job = TreeBuildJob.objects.create(tenant=tenant, course=course)
        self.assertEqual(job.status, 'queued')
        payload = job.payload()
        self.assertEqual(payload['kind'], 'tree_build')
        self.assertEqual(payload['status'], 'queued')
        self.assertEqual(payload['course'], str(course.id))
        run = TaggingRun.objects.create(tenant=tenant, course=course, summary={'tagged': 3})
        self.assertEqual(run.payload()['kind'], 'tagging')
        self.assertEqual(list(course.tagging_runs.all()), [run])
```

- [ ] **Step 2: Run it to verify it fails**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_syllabus_jobs -v 2`
Expected: ImportError (`cannot import name 'TaggingRun'`).

- [ ] **Step 3: Implement**

Append to `backend/intelligence/models.py`:

```python
# ─── Syllabus tools: background job history (spec 2B §5.1) ───────────────────


class SyllabusJob(TimeStampedModel):
    """Shared shape of a background syllabus job (one row per run)."""

    STATUS_QUEUED = 'queued'
    STATUS_RUNNING = 'running'
    STATUS_DONE = 'done'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_QUEUED, 'Queued'),
        (STATUS_RUNNING, 'Running'),
        (STATUS_DONE, 'Done'),
        (STATUS_FAILED, 'Failed'),
    ]
    ACTIVE_STATUSES = (STATUS_QUEUED, STATUS_RUNNING)
    KIND = ''

    started_by = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_QUEUED)
    # What was asked (e.g. explicit skill packs, subject ids); never student data.
    options = models.JSONField(default=dict, blank=True)
    summary = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True, default='')
    tokens = models.PositiveIntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True
        ordering = ['-created_at']

    def payload(self):
        return {
            'id': str(self.id),
            'kind': self.KIND,
            'course': str(self.course_id),
            'status': self.status,
            'summary': self.summary,
            'error': self.error,
            'tokens': self.tokens,
            'cost_usd': float(self.cost_usd),
            'started_by': (getattr(self.started_by, 'full_name', '') or getattr(self.started_by, 'email', ''))
            if self.started_by_id else '',
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'finished_at': self.finished_at.isoformat() if self.finished_at else None,
        }


class TreeBuildJob(SyllabusJob):
    """One "Build syllabus tree" run (services.course_tree.build_course_tree)."""

    KIND = 'tree_build'
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='tree_build_jobs')

    class Meta(SyllabusJob.Meta):
        verbose_name = 'Tree Build Job'
        verbose_name_plural = 'Tree Build Jobs'
        indexes = [models.Index(fields=['course', 'status'])]


class TaggingRun(SyllabusJob):
    """One "Tag questions" run over a course's treed subjects."""

    KIND = 'tagging'
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='tagging_runs')

    class Meta(SyllabusJob.Meta):
        verbose_name = 'Tagging Run'
        verbose_name_plural = 'Tagging Runs'
        indexes = [models.Index(fields=['course', 'status'])]
```

Generate the migration:

Run: `venv/Scripts/python.exe manage.py makemigrations intelligence -n syllabus_jobs`
Expected: creates `intelligence/migrations/0006_syllabus_jobs.py` with two `CreateModel` operations and nothing else. If it contains any other operation, stop and report.

- [ ] **Step 4: Run tests**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_syllabus_jobs intelligence.tests.test_tagging_v2_models -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/intelligence/models.py backend/intelligence/migrations/0006_syllabus_jobs.py backend/intelligence/tests/test_syllabus_jobs.py
git commit -m "feat(intelligence): TreeBuildJob and TaggingRun job history"
```

---

### Task 3: Proposed subtopics, tagger counts, candidate selection

**Files:**
- Modify: `backend/intelligence/services/course_tree.py` (`_propose_subtopics`; new `estimate_build`)
- Modify: `backend/intelligence/services/syllabus.py` (`tagging_context`; new `exam_tree_options`)
- Modify: `backend/intelligence/services/tagging_sweep.py` (`LIVE_STATUSES`; `write_result`; `_tag_group`; `candidate_querysets`; `tag_v2_for_tenant`; new `estimate_tagging`, `tag_one_item`)
- Modify: `backend/intelligence/services/llm.py` (new `budget_status`)
- Modify: `backend/intelligence/tests/test_course_tree.py`, `backend/intelligence/tests/test_tagging_sweep.py`
- Test: `backend/intelligence/tests/test_syllabus_jobs.py` (add a class)

**Interfaces:**
- Produces:
  - LLM-proposed subtopics are created with `status='proposed'` (seeded ones stay `active`);
  - `tagging_context(subject)` and the sweep's node lookup include `active` and `proposed` nodes;
  - `ItemTagging.raw['topic_key']` holds the tagger's located topic;
  - `tag_v2_for_tenant(..., stats=None)` — when a dict is given, it is filled with `tagged`, `needs_review`, `failed`, `locked`;
  - `candidate_querysets(tenant, subject_ids) -> (questions_qs, mock_items_qs, context_for)`;
  - `estimate_tagging(tenant, subject_ids) -> {'questions', 'approx_tokens'}`;
  - `tag_one_item(item, call, stats=None) -> int`;
  - `course_tree.estimate_build(course, packs=None) -> {'llm_calls', 'calls': {grouping, subtopics, packs}, 'approx_tokens'}`;
  - `syllabus.exam_tree_options() -> [{'key', 'label', 'subjects': [{'key', 'label'}]}]`;
  - `llm.budget_status(tenant) -> {'monthly_budget', 'used', 'remaining', 'exhausted'}`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/intelligence/tests/test_syllabus_jobs.py`:

```python
import json
from unittest.mock import patch

from exams.models import Subject, Topic
from intelligence.models import ItemTagging, SyllabusNode
from intelligence.services import course_tree, syllabus, tagging_sweep
from intelligence.tests.test_course_tree import FakeCall as BuildCall
from intelligence.tests.test_tagging_sweep import FakeCall as TagCall, patched_tree, tag_entry
from intelligence.tests.taxonomy_fixtures import sync_mini_vocabulary
from quiz.models import Question


class ProposedNodeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create(name='Proposed Academy', features={'syllabus_tools': True})
        cls.course = Course.objects.create(
            tenant=cls.tenant, name='DSA', code='prop-dsa', course_type='skill')
        cls.subject = Subject.objects.create(
            tenant=cls.tenant, course=cls.course, name='Arrays', code='arrays')
        cls.topic = Topic.objects.create(
            tenant=cls.tenant, subject=cls.subject, name='Two Sum', code='two-sum')

    def test_llm_subtopics_are_proposed_and_the_tagger_sees_them(self):
        course_tree.build_course_tree(
            self.course, call=BuildCall(subtopics={'Two Sum': ['Hash map lookup']}), packs=[])
        node = SyllabusNode.objects.get(subject=self.subject, name='Hash map lookup')
        self.assertEqual(node.status, 'proposed')
        context = syllabus.tagging_context(self.subject)
        keys = [sub['key'] for topic in context['topics'] for sub in topic['subtopics']]
        self.assertIn(node.key, keys)

    def test_estimate_build_counts_calls(self):
        estimate = course_tree.estimate_build(self.course)
        # 1 topic → 1 subtopic call; no grouping (≤ 6 topics); 1 packs call.
        self.assertEqual(estimate['calls'], {'grouping': 0, 'subtopics': 1, 'packs': 1})
        self.assertEqual(estimate['approx_tokens'], 2 * course_tree.TOKENS_PER_CALL)
        # A topic counts as planned once it has a subtopic; a build that got no
        # subtopics back would ask again next time (the builder does the same).
        course_tree.build_course_tree(
            self.course, call=BuildCall(subtopics={'Two Sum': ['Hash map lookup']}), packs=[])
        self.assertEqual(course_tree.estimate_build(self.course, packs=[])['llm_calls'], 0)


class SweepCountTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create(name='Count Academy', features={'syllabus_tools': True})
        cls.course = Course.objects.create(
            tenant=cls.tenant, name='Mini', code='count-mini', course_type='competitive')
        cls.subject = Subject.objects.create(
            tenant=cls.tenant, course=cls.course, name='Physics', code='physics')
        cls.laws = Topic.objects.create(
            tenant=cls.tenant, subject=cls.subject, name='Laws of Motion', code='laws-of-motion')
        sync_mini_vocabulary()
        with patched_tree():
            syllabus.instantiate_exam_tree(cls.course, 'mini', {'physics': cls.subject})
        cls.good = Question.objects.create(
            tenant=cls.tenant, subject=cls.subject, topic=cls.laws, question_type='numerical',
            question_text='Friction on a 2 kg block?', numerical_answer=10)
        cls.unsure = Question.objects.create(
            tenant=cls.tenant, subject=cls.subject, topic=cls.laws, question_type='numerical',
            question_text='Tension in a rope?', numerical_answer=5)
        cls.broken = Question.objects.create(
            tenant=cls.tenant, subject=cls.subject, topic=cls.laws, question_type='numerical',
            question_text='Something odd?', numerical_answer=1)

    def test_stats_and_topic_key(self):
        call = TagCall(tag={
            str(self.good.id): tag_entry(),
            str(self.unsure.id): tag_entry(confidence=0.2),
        })
        stats = {}
        with patched_tree():
            self.assertEqual(
                tagging_sweep.tag_v2_for_tenant(self.tenant, {self.subject.id}, call, stats=stats), 2)
        self.assertEqual(stats, {'tagged': 2, 'needs_review': 1, 'failed': 1, 'locked': 0})
        raw = ItemTagging.objects.get(question=self.good).raw
        self.assertEqual(raw['topic_key'], 'mini.physics.mechanics.laws_of_motion')

    def test_estimate_and_tag_one(self):
        with patched_tree():
            self.assertEqual(
                tagging_sweep.estimate_tagging(self.tenant, {self.subject.id})['questions'], 3)
            call = TagCall(tag={str(self.good.id): tag_entry()})
            self.assertEqual(tagging_sweep.tag_one_item(self.good, call), 1)
            self.assertEqual(
                tagging_sweep.estimate_tagging(self.tenant, {self.subject.id})['questions'], 2)

    def test_budget_status_without_budget(self):
        status = budget_status(self.tenant)
        self.assertEqual(status['monthly_budget'], None)
        self.assertFalse(status['exhausted'])
```

Also add `from intelligence.services.llm import budget_status` to the imports at the top of the file (next to `from intelligence import api`).

- [ ] **Step 2: Run them to verify they fail**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_syllabus_jobs -v 2`
Expected: FAIL / ERROR (`status == 'active'`, `estimate_build` missing, `stats` unexpected keyword).

- [ ] **Step 3: Implement**

**`services/course_tree.py`**

In `_propose_subtopics`, add `status='proposed',` to the `SyllabusNode.objects.create(...)` call (after `source='llm_proposed',`). Update the module docstring's last sentence block by adding:

```
LLM proposals are created as ``status='proposed'`` ("suggested" in the
editor) until a teacher accepts or edits them; the tagger already uses them.
```

Append:

```python
TOKENS_PER_CALL = 1500   # rough prompt + reply size of one builder call


def estimate_build(course, packs=None):
    """LLM calls and tokens the next ``build_course_tree`` run would make.

    Mirrors the builder: one grouping call per subject with more than
    GROUP_THRESHOLD new topics and no sub-subject yet, one subtopic call per
    topic not planned before, one packs call when a subject has no packs.
    """
    from exams.models import Topic
    from intelligence.models import CourseSyllabus, SyllabusNode

    calls = {'grouping': 0, 'subtopics': 0, 'packs': 0}
    subjects = list(course.subjects.all())
    for subject in subjects:
        topics = list(Topic.objects.filter(subject=subject, parent_topic__isnull=True))
        nodes = {node.course_topic_id: node for node in
                 SyllabusNode.objects.filter(subject=subject, level='topic').exclude(status='archived')}
        new = [topic for topic in topics if topic.id not in nodes]
        has_group = (SyllabusNode.objects.filter(subject=subject, level='sub_subject')
                     .exclude(status='archived').exists())
        if new and not has_group and len(new) > GROUP_THRESHOLD:
            calls['grouping'] += 1
        planned = set(
            SyllabusNode.objects.filter(subject=subject, level='subtopic', parent__in=list(nodes.values()))
            .exclude(status='archived').values_list('parent_id', flat=True)
        )
        calls['subtopics'] += sum(
            1 for topic in topics if topic.id not in nodes or nodes[topic.id].id not in planned)
    if packs is None:
        record = CourseSyllabus.objects.filter(course=course).first()
        existing = (record.skill_packs or {}) if record else {}
        if any(str(subject.id) not in existing for subject in subjects):
            calls['packs'] = 1
    total = sum(calls.values())
    return {'llm_calls': total, 'calls': calls, 'approx_tokens': total * TOKENS_PER_CALL}
```

**`services/syllabus.py`**

In `tagging_context`, change the node filter to include suggestions:

```python
    nodes = list(
        SyllabusNode.objects.filter(subject=subject, status__in=('active', 'proposed'), in_syllabus=True)
        .order_by('order', 'name')
    )
```

Append:

```python
def exam_tree_options():
    """Shipped exam trees and their subjects, for the "Use an exam syllabus" form."""
    from intelligence.services.taxonomy import shipped_exam_keys

    options = []
    for key in shipped_exam_keys():
        try:
            tree = load_exam_tree(key)
        except TaxonomyError:
            continue
        options.append({
            'key': key,
            'label': tree['label'],
            'subjects': [{'key': node['subject'], 'label': node['label']}
                         for node in flatten_tree(tree) if node['level'] == 'subject'],
        })
    return options
```

**`services/tagging_sweep.py`**

1. After `CACHE_TREE_VERSION_CHARS = 64 …` add:

```python
LIVE_STATUSES = ('active', 'proposed')  # suggested subtopics are taggable straight away
TOKENS_PER_QUESTION = 1000              # rough, from the first evaluation runs
```

2. In `write_result`, replace `tagging.raw = result.raw` with:

```python
    tagging.raw = {**result.raw, 'topic_key': result.topic_key}
```

3. Replace `_tag_group` with:

```python
def _tag_group(tenant, subject, context, items, call, *, arm, stats=None):
    stats = stats if stats is not None else {}
    for key in ('tagged', 'needs_review', 'failed', 'locked'):
        stats.setdefault(key, 0)
    nodes = {
        node.key: node for node in
        SyllabusNode.objects.filter(subject=subject, status__in=LIVE_STATUSES)
        .select_related('parent', 'concept')
    }
    hints = {topic['course_topic_id']: topic['key'] for topic in context['topics'] if topic['course_topic_id']}
    by_id, hashes, payloads = {}, {}, []
    for item in items:
        payload = item_payload(item)
        payload['topic_hint'] = hints.get(str(item.topic_id), '') if item.topic_id else ''
        payloads.append(payload)
        by_id[payload['id']] = item
        hashes[payload['id']] = content_hash_for(item)
    results = tag_payloads(context, payloads, call=call,
                           cache=DbCache(tenant, context, call.model_ref, hashes))
    tagger_version = f'{TAGGER_V2_PROMPT_VERSION}:{call.model_ref}'
    written = 0
    for result in results:
        if result.error == 'no_topic':
            # Locate found no valid topic: a result (needs review), not a retry.
            result.error = ''
            result.review_reasons = ['invalid_key']
            result.needs_review = True
        if result.error:
            logger.info('tagging v2: %s %s not tagged (%s)', arm, result.id, result.error)
            stats['failed'] += 1
            continue
        if write_result(by_id[result.id], result, context, nodes, tagger_version,
                        subject=subject, allow_difficulty=(arm == 'mock_item')):
            written += 1
            stats['tagged'] += 1
            stats['needs_review'] += 1 if result.needs_review else 0
        else:
            stats['locked'] += 1
    return written
```

4. Split selection out of `tag_v2_for_tenant`. Replace the whole function with:

```python
def candidate_querysets(tenant, subject_ids):
    """(questions, mock items, context_for) the v2 sweep would consider.

    The querysets are coarse (they select not-current items by versions);
    ``tag_v2_for_tenant`` re-checks each item with ``_is_current``.
    """
    from exams.models import Subject
    from quiz.models import MockTestItem, Question

    contexts = {}

    def context_for(subject):
        if subject.id not in contexts:
            contexts[subject.id] = tagging_context(subject)
        return contexts[subject.id]

    base = _base_candidate_q()
    test_ids = _single_subject_test_ids(tenant, set(subject_ids))
    question_q, mock_q = Q(pk__in=[]), Q(pk__in=[])
    for subject in Subject.objects.filter(id__in=subject_ids):
        stale_tree = base | ~Q(tagging__tree_version=context_for(subject)['tree_version'])
        question_q |= Q(subject_id=subject.id) & stale_tree
        mock_q |= _mock_owned_by(subject.id, test_ids.get(subject.id, [])) & stale_tree

    questions = (
        Question.objects.filter(tenant=tenant).filter(question_q).exclude(status='archived')
        .exclude(tagging__source='manual')
        .select_related('subject__course', 'topic', 'tagging').order_by('created_at')
    )
    items = (
        MockTestItem.objects.filter(tenant=tenant).filter(mock_q)
        .exclude(tagging__source='manual')
        .select_related('mock_test__course', 'subject__course', 'topic__subject__course', 'tagging')
        .prefetch_related('mock_test__courses__subjects')
        .order_by('created_at')
    )
    return questions, items, context_for


def tag_v2_for_tenant(tenant, subject_ids, call, *, limit=200, stats=None):
    """Tag up to ``limit`` not-current items of these (treed) subjects.

    ``stats``, when given, is filled with tagged / needs_review / failed /
    locked counts. Returns the number of items written.
    """
    subject_ids = set(subject_ids)
    questions, items, context_for = candidate_querysets(tenant, subject_ids)
    subjects = {}
    picked = defaultdict(list)

    def take(arm, item, subject, tagging):
        if _is_current(item, tagging, context_for(subject)):
            return False
        picked[(arm, subject.id)].append(item)
        subjects[subject.id] = subject
        return True

    taken = 0
    for question in questions[:limit]:
        if taken >= limit:
            break
        taken += take('question', question, question.subject, getattr(question, 'tagging', None))
    if taken < limit:
        for item in items[:limit - taken]:
            subject = _mock_item_subject(item)
            if subject is None or subject.id not in subject_ids:
                continue
            taken += take('mock_item', item, subject, getattr(item, 'tagging', None))

    tagged = 0
    for (arm, subject_id), group in picked.items():
        subject = subjects[subject_id]
        tagged += _tag_group(tenant, subject, context_for(subject), group, call, arm=arm, stats=stats)
    return tagged


def estimate_tagging(tenant, subject_ids):
    """About how many items the next run would tag, and the tokens it would use."""
    questions, items, _context_for = candidate_querysets(tenant, set(subject_ids))
    count = questions.count() + items.count()
    return {'questions': count, 'approx_tokens': count * TOKENS_PER_QUESTION}


def tag_one_item(item, call, stats=None):
    """Tag one bank question or mock item now (the review queue's Re-tag)."""
    arm = _arm(item)
    subject = item.subject if arm == 'question' else _mock_item_subject(item)
    if subject is None:
        return 0
    if not SyllabusNode.objects.filter(subject=subject, level='topic', status='active').exists():
        return 0
    return _tag_group(item.tenant, subject, tagging_context(subject), [item], call, arm=arm, stats=stats)
```

**`services/llm.py`** — append:

```python
def budget_status(tenant):
    """The tenant's monthly token budget on its own key (None = no budget)."""
    from chatbot import resolver

    budget = resolver.get_ai_settings(tenant).monthly_token_budget or None
    used = resolver.tokens_used(tenant, resolver.month_start(), source=AIUsageRecord.SOURCE_TENANT)
    return {
        'monthly_budget': budget,
        'used': used,
        'remaining': max(0, budget - used) if budget else None,
        'exhausted': bool(budget) and used >= budget,
    }
```

**Existing tests**

- `test_course_tree.py` and `test_tagging_sweep.py`: on this branch no test asserts the status of an `llm_proposed` node or compares `ItemTagging.raw` exactly, so both files pass unchanged (verified against the plan's code). Only touch them if Step 4 shows a failure; drop them from the commit if unchanged.

- [ ] **Step 4: Run tests**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_syllabus_jobs intelligence.tests.test_course_tree intelligence.tests.test_tagging_sweep intelligence.tests.test_syllabus -v 2`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/intelligence/services/course_tree.py backend/intelligence/services/syllabus.py backend/intelligence/services/tagging_sweep.py backend/intelligence/services/llm.py backend/intelligence/tests/test_syllabus_jobs.py backend/intelligence/tests/test_course_tree.py backend/intelligence/tests/test_tagging_sweep.py
git commit -m "feat(intelligence): suggested subtopics, tagger run counts, build and tagging estimates"
```

---

### Task 4: Tree editor service

**Files:**
- Create: `backend/intelligence/services/tree_editor.py`
- Create: `backend/intelligence/tests/syllabus_fixtures.py`
- Test: `backend/intelligence/tests/test_tree_editor.py`

**Interfaces:**
- Produces (`tree_editor.py`):
  - `EditError(ValueError)`;
  - `tree_payload(course) -> dict` (see Step 3 for the shape);
  - `add_node(subject, *, level, name, parent=None, description='') -> SyllabusNode`;
  - `update_node(node, data) -> list[str]` (weight warnings);
  - `merge_nodes(source, target) -> {'primary_moved', 'secondary_moved', 'concept_id'}`;
  - `set_skill_packs(course, packs) -> dict`;
  - `weight_warnings(node) -> list[str]`.
- Produces (`syllabus_fixtures.py`): `SyllabusTestCase` with `tenant` (`syllabus_tools` on), `admin`, `faculty` (on `course`), `other_faculty` (on `custom`), `course` (exam-mapped to the mini tree, subject `physics`, topic `laws`), `custom` (custom course: subject `arrays`, topic `two_sum`), node shortcuts `friction`, `newton`, `laws_node`, `mechanics`, `client_for(user)`, `question(text, *, subject=None, topic=None)`.

- [ ] **Step 1: Shared fixture**

Create `backend/intelligence/tests/syllabus_fixtures.py`:

```python
"""Shared fixtures for the syllabus-tools tests: an exam-mapped course on the
mini tree and a custom course, with an admin and two faculty."""
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.models import Tenant
from exams.models import Course, Subject, Topic
from intelligence.models import SyllabusNode
from intelligence.services import syllabus
from intelligence.tests.taxonomy_fixtures import sync_mini_vocabulary
from intelligence.tests.test_tagging_sweep import FRICTION, LAWS, NEWTON, patched_tree
from quiz.models import Question
from users.models import User


class SyllabusTestCase(TestCase):
    features = {'syllabus_tools': True}

    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create(
            name='Syllabus Academy', is_active=True, features=dict(cls.features))

        def user(email, role):
            return User.objects.create_user(
                email=email, password='pw-syl-1', tenant=cls.tenant, role=role)

        cls.admin = user('syl-admin@example.com', 'admin')
        cls.faculty = user('syl-faculty@example.com', 'instructor')
        cls.other_faculty = user('syl-faculty-2@example.com', 'instructor')

        cls.course = Course.objects.create(
            tenant=cls.tenant, name='Mini Prep', code='syl-mini', course_type='competitive')
        cls.physics = Subject.objects.create(
            tenant=cls.tenant, course=cls.course, name='Physics', code='physics')
        cls.laws = Topic.objects.create(
            tenant=cls.tenant, subject=cls.physics, name='Laws of Motion', code='laws-of-motion')
        cls.custom = Course.objects.create(
            tenant=cls.tenant, name='DSA Sheet', code='syl-dsa', course_type='skill')
        cls.arrays = Subject.objects.create(
            tenant=cls.tenant, course=cls.custom, name='Arrays', code='arrays')
        cls.two_sum = Topic.objects.create(
            tenant=cls.tenant, subject=cls.arrays, name='Two Sum', code='two-sum')
        cls.course.instructors.add(cls.faculty)
        cls.custom.instructors.add(cls.other_faculty)

        sync_mini_vocabulary()
        with patched_tree():
            syllabus.instantiate_exam_tree(cls.course, 'mini', {'physics': cls.physics})

    def setUp(self):
        self.friction = SyllabusNode.objects.get(key=FRICTION)
        self.newton = SyllabusNode.objects.get(key=NEWTON)
        self.laws_node = SyllabusNode.objects.get(key=LAWS)
        self.mechanics = self.laws_node.parent

    def client_for(self, user):
        client = APIClient()
        client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(user).access_token}',
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )
        return client

    def question(self, text, *, subject=None, topic=None):
        return Question.objects.create(
            tenant=self.tenant, subject=subject or self.physics, topic=topic or self.laws,
            question_type='numerical', question_text=text, numerical_answer=1)
```

- [ ] **Step 2: Write the failing test**

Create `backend/intelligence/tests/test_tree_editor.py`:

```python
"""Tree editor operations (spec 2B §5.2)."""
from intelligence.models import (
    ConceptLink, CourseSyllabus, ItemTagging, LearnerConceptState, SyllabusNode,
)
from intelligence.services import syllabus, tree_editor
from intelligence.services.tree_editor import EditError
from intelligence.tests.syllabus_fixtures import SyllabusTestCase


class PayloadTests(SyllabusTestCase):
    def test_tree_payload_nests_and_skips_archived(self):
        payload = tree_editor.tree_payload(self.course)
        self.assertEqual(payload['kind'], 'exam')
        self.assertEqual(payload['exam_tree'], 'mini')
        subject = payload['subjects'][0]
        self.assertTrue(subject['has_tree'])
        mechanics = subject['nodes'][0]
        self.assertEqual(mechanics['level'], 'sub_subject')
        laws = next(n for n in mechanics['children'] if n['key'] == self.laws_node.key)
        self.assertEqual([c['name'] for c in laws['children']], ['Friction', "Newton's Laws"])
        self.assertIn('exam_trees', payload)

    def test_custom_course_without_tree(self):
        payload = tree_editor.tree_payload(self.custom)
        self.assertEqual(payload['kind'], 'none')
        self.assertFalse(payload['subjects'][0]['has_tree'])


class AddAndUpdateTests(SyllabusTestCase):
    def test_add_subtopic_gets_key_and_concept(self):
        node = tree_editor.add_node(self.physics, level='subtopic', name='Static friction',
                                    parent=self.laws_node)
        self.assertEqual(node.key, f'{self.laws_node.key}.static_friction')
        self.assertEqual(node.source, 'manual')
        self.assertIsNotNone(node.concept_id)

    def test_add_topic_is_refused(self):
        with self.assertRaises(EditError):
            tree_editor.add_node(self.physics, level='topic', name='Optics', parent=self.mechanics)

    def test_add_sub_subject_uses_sibling_prefix(self):
        node = tree_editor.add_node(self.physics, level='sub_subject', name='Modern Physics')
        self.assertEqual(node.key, 'mini.physics.modern_physics')

    def test_rename_changes_tree_version_and_concept(self):
        before = syllabus.compute_tree_version(self.physics)
        tree_editor.update_node(self.friction, {'name': 'Kinetic friction'})
        self.friction.refresh_from_db()
        self.assertEqual(self.friction.concept.name, 'Kinetic friction')
        self.assertNotEqual(syllabus.compute_tree_version(self.physics), before)

    def test_topic_rename_is_refused(self):
        with self.assertRaises(EditError):
            tree_editor.update_node(self.laws_node, {'name': 'Newton'})

    def test_move_topic_to_another_sub_subject(self):
        target = tree_editor.add_node(self.physics, level='sub_subject', name='Dynamics')
        tree_editor.update_node(self.laws_node, {'parent': str(target.id)})
        self.laws_node.refresh_from_db()
        self.assertEqual(self.laws_node.parent_id, target.id)
        with self.assertRaises(EditError):
            tree_editor.update_node(self.friction, {'parent': str(target.id)})

    def test_weightage_warning_when_siblings_do_not_sum_to_one(self):
        self.assertEqual(tree_editor.update_node(self.friction, {'weightage': 0.5}), [])
        warnings = tree_editor.update_node(self.friction, {'weightage': 0.7})
        self.assertEqual(len(warnings), 1)
        self.assertIn('1.20', warnings[0])
        with self.assertRaises(EditError):
            tree_editor.update_node(self.friction, {'weightage': 2})

    def test_editing_a_suggestion_accepts_it(self):
        self.friction.status = 'proposed'
        self.friction.save()
        tree_editor.update_node(self.friction, {'name': 'Friction forces'})
        self.friction.refresh_from_db()
        self.assertEqual(self.friction.status, 'active')

    def test_accept_and_archive(self):
        self.friction.status = 'proposed'
        self.friction.save()
        tree_editor.update_node(self.friction, {'status': 'active'})
        tree_editor.update_node(self.friction, {'status': 'archived'})
        self.friction.refresh_from_db()
        self.assertEqual(self.friction.status, 'archived')
        with self.assertRaises(EditError):
            tree_editor.update_node(self.mechanics, {'status': 'archived'})  # has live topics


class MergeTests(SyllabusTestCase):
    def test_merge_moves_links_taggings_and_archives_source(self):
        question = self.question('A block slides…')
        other = self.question('A rope pulls…')
        friction_concept = syllabus.ensure_node_concept(self.friction)
        newton_concept = syllabus.ensure_node_concept(self.newton)
        ConceptLink.objects.create(tenant=self.tenant, concept=friction_concept, question=question,
                                   is_primary=True, source='llm_tagger')
        primary = ItemTagging.objects.create(tenant=self.tenant, question=question,
                                             primary_node=self.friction)
        secondary = ItemTagging.objects.create(tenant=self.tenant, question=other,
                                               primary_node=self.newton)
        secondary.secondary_nodes.add(self.friction)

        summary = tree_editor.merge_nodes(self.friction, self.newton)

        self.assertEqual(summary['primary_moved'], 1)
        self.assertEqual(summary['secondary_moved'], 1)
        self.friction.refresh_from_db()
        self.assertEqual(self.friction.status, 'archived')
        primary.refresh_from_db()
        self.assertEqual(primary.primary_node_id, self.newton.id)
        self.assertEqual(list(secondary.secondary_nodes.all()), [])  # target is already primary
        self.assertEqual(ConceptLink.objects.get(question=question).concept_id, newton_concept.id)
        friction_concept.refresh_from_db()
        self.assertEqual(friction_concept.status, 'merged')
        self.assertFalse(LearnerConceptState.objects.filter(concept=friction_concept).exists())

    def test_merge_needs_two_live_subtopics_of_one_subject(self):
        with self.assertRaises(EditError):
            tree_editor.merge_nodes(self.friction, self.friction)
        with self.assertRaises(EditError):
            tree_editor.merge_nodes(self.friction, self.laws_node)


class SkillPackTests(SyllabusTestCase):
    def test_set_skill_packs(self):
        tree_editor.set_skill_packs(self.course, {str(self.physics.id): ['physics', 'nope']})
        self.assertEqual(CourseSyllabus.objects.get(course=self.course).skill_packs,
                         {str(self.physics.id): ['physics']})
        with self.assertRaises(EditError):
            tree_editor.set_skill_packs(self.course, {str(self.arrays.id): ['physics']})
```

- [ ] **Step 3: Run it to verify it fails**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_tree_editor -v 2`
Expected: ImportError (`cannot import name 'tree_editor'`).

- [ ] **Step 4: Implement**

Create `backend/intelligence/services/tree_editor.py`:

```python
"""Teacher edits to a course's syllabus tree (spec 2B §5.2).

Course topics are read-only: their names and order come from the course.
Sub-subjects and subtopics can be added, renamed and archived; topics move
between sub-subjects; any node takes a weightage; suggested (``proposed``)
subtopics are accepted explicitly or by editing; two subtopics merge.
Add, rename, archive and merge change the subject's tree version, so the
next tagging run re-tags the affected items.
"""
import uuid
from collections import defaultdict

from django.db import transaction

from intelligence.models import CourseSyllabus, ItemTagging, SkillPack, SyllabusNode
from intelligence.services.course_tree import _slug, _subject_code, _unique_key
from intelligence.services.normalize import merge_concept
from intelligence.services.syllabus import (
    compute_tree_version, ensure_node_concept, exam_tree_options, packs_for_subject,
)

LIVE = ('active', 'proposed')
WEIGHT_TOLERANCE = 0.01


class EditError(ValueError):
    """A refused edit; the message is shown to the teacher as is."""


def as_uuid(value):
    """``value`` as a UUID string, or None when it is not one.

    Ids from request bodies and query strings go through this before any
    ``filter(id=...)``: a malformed id raises ValidationError inside the ORM,
    which would be a 500 instead of a 400.
    """
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        return None


def _clean_name(value):
    name = ' '.join(str(value or '').split())[:300]
    if not name:
        raise EditError('A name is required.')
    return name


# ── Payload ──────────────────────────────────────────────────────────────────

def _node_payload(node, children):
    return {
        'id': str(node.id),
        'key': node.key,
        'level': node.level,
        'name': node.name,
        'description': node.description,
        'weightage': node.weightage,
        'status': node.status,
        'source': node.source,
        'in_syllabus': node.in_syllabus,
        'course_topic_id': str(node.course_topic_id) if node.course_topic_id else None,
        'children': [_node_payload(child, children) for child in children.get(node.id, [])],
    }


def tree_payload(course):
    """Everything the Syllabus tab shows except job history."""
    record = CourseSyllabus.objects.filter(course=course).first()
    explicit = (record.skill_packs or {}) if record else {}
    subjects = []
    for subject in course.subjects.all().order_by('order', 'name'):
        nodes = list(
            SyllabusNode.objects.filter(subject=subject).exclude(status='archived')
            .order_by('order', 'name')
        )
        children = defaultdict(list)
        for node in nodes:
            children[node.parent_id].append(node)
        subjects.append({
            'id': str(subject.id),
            'name': subject.name,
            'has_tree': any(node.level == 'topic' for node in nodes),
            'tree_version': compute_tree_version(subject) if nodes else '',
            'proposed': sum(1 for node in nodes if node.status == 'proposed'),
            'packs': [pack.key for pack in packs_for_subject(subject)],
            'explicit_packs': str(subject.id) in explicit,
            'nodes': [_node_payload(node, children) for node in children.get(None, [])],
        })
    if record and record.exam_tree:
        kind = 'exam'
    elif any(subject['has_tree'] for subject in subjects):
        kind = 'custom'
    else:
        kind = 'none'
    return {
        'course': {'id': str(course.id), 'name': course.name, 'course_type': course.course_type},
        'kind': kind,
        'exam_tree': record.exam_tree if record else '',
        'subject_map': (record.subject_map or {}) if record else {},
        'subjects': subjects,
        'skill_packs_available': [
            {'key': pack.key, 'label': pack.label}
            for pack in SkillPack.objects.filter(active=True).order_by('key')
        ],
        'exam_trees': exam_tree_options(),
    }


# ── Edits ────────────────────────────────────────────────────────────────────

def add_node(subject, *, level, name, parent=None, description=''):
    """Add a subtopic (under a topic) or a sub-subject (top level)."""
    name = _clean_name(name)
    used = set(SyllabusNode.objects.filter(subject=subject).values_list('key', flat=True))
    if level == 'subtopic':
        if (parent is None or parent.subject_id != subject.id or parent.level != 'topic'
                or parent.status == 'archived'):
            raise EditError('A subtopic goes under a topic of this subject.')
        key = _unique_key(f'{parent.key}.{_slug(name)}', used)
    elif level == 'sub_subject':
        if parent is not None:
            raise EditError('A sub-subject sits at the top of the subject.')
        sibling = (SyllabusNode.objects.filter(subject=subject, level='sub_subject')
                   .order_by('order').first())
        prefix = sibling.key.rsplit('.', 1)[0] if sibling else f'course.{_subject_code(subject)}.group'
        key = _unique_key(f'{prefix}.{_slug(name)}', used)
    else:
        raise EditError('Topics come from the course itself. Add the topic to the course instead.')
    order = SyllabusNode.objects.filter(subject=subject, parent=parent, level=level).count()
    node = SyllabusNode.objects.create(
        tenant=subject.tenant, subject=subject, parent=parent, level=level, key=key,
        name=name, description=str(description or '').strip()[:2000],
        source='manual', status='active', order=order,
    )
    if level == 'subtopic':
        ensure_node_concept(node)
    return node


def weight_warnings(node):
    """A note when weighted siblings don't add up to 1 (never blocks the edit)."""
    siblings = SyllabusNode.objects.filter(
        subject=node.subject, parent=node.parent, level=node.level, status__in=LIVE)
    weights = [sibling.weightage for sibling in siblings]
    if not any(weights):
        return []
    total = sum(weights)
    if abs(total - 1) <= WEIGHT_TOLERANCE:
        return []
    where = node.parent.name if node.parent_id else node.subject.name
    return [f'Weightages under "{where}" add up to {total:.2f}, not 1.']


def _check_archivable(node):
    if node.level == 'topic':
        raise EditError('Topics come from the course. Remove the topic from the course instead.')
    if node.level == 'sub_subject' and SyllabusNode.objects.filter(
            parent=node, status__in=LIVE).exists():
        raise EditError('Move its topics to another sub-subject first.')


def update_node(node, data):
    """Apply one PATCH (name, description, parent, weightage, status).

    Returns weightage warnings. Editing a suggestion accepts it.
    """
    if node.status == 'archived':
        raise EditError('This node is archived.')
    fields = set()
    if 'name' in data or 'description' in data:
        if node.level == 'topic':
            raise EditError('Topic names come from the course.')
        if 'name' in data:
            node.name = _clean_name(data['name'])
            fields.add('name')
        if 'description' in data:
            node.description = str(data['description'] or '').strip()[:2000]
            fields.add('description')
    if 'parent' in data:
        if node.level != 'topic':
            raise EditError('Only topics move between sub-subjects.')
        parent_id = as_uuid(data['parent'])
        target = (SyllabusNode.objects.filter(
            id=parent_id, subject=node.subject, level='sub_subject', status__in=LIVE).first()
            if parent_id else None)
        if target is None:
            raise EditError('Pick a sub-subject of this subject.')
        node.parent = target
        fields.add('parent')
    if 'weightage' in data:
        try:
            weight = float(data['weightage'])
        except (TypeError, ValueError):
            raise EditError('Weightage is a number from 0 to 1.') from None
        if not 0 <= weight <= 1:
            raise EditError('Weightage is a number from 0 to 1.')
        node.weightage = weight
        fields.add('weightage')
    if 'status' in data:
        if data['status'] == 'active':
            node.status = 'active'
        elif data['status'] == 'archived':
            _check_archivable(node)
            node.status = 'archived'
        else:
            raise EditError('Status is "active" or "archived".')
        fields.add('status')
    if not fields:
        raise EditError('Nothing to change.')
    if node.status == 'proposed' and fields & {'name', 'description', 'weightage'}:
        node.status = 'active'
        fields.add('status')
    node.save(update_fields=[*fields, 'updated_at'])
    if node.level == 'subtopic' and node.status != 'archived':
        ensure_node_concept(node)  # keeps the Concept's name in step
    return weight_warnings(node)


@transaction.atomic
def merge_nodes(source, target):
    """Merge subtopic ``source`` into ``target`` and archive ``source``.

    The target keeps its Concept: ``merge_concept`` moves ConceptLinks and
    aliases and drops the source's learner states (callers queue a
    recompute of the target concept). ItemTagging primary and secondary
    nodes move from source to target. Skill tags are per item: untouched.
    """
    if source.id == target.id:
        raise EditError('Pick a different subtopic to merge into.')
    if source.level != 'subtopic' or target.level != 'subtopic':
        raise EditError('Only subtopics can be merged.')
    if source.subject_id != target.subject_id:
        raise EditError('Both subtopics must be in the same subject.')
    if source.status == 'archived' or target.status == 'archived':
        raise EditError('Archived subtopics cannot be merged.')
    target_concept = ensure_node_concept(target)
    if source.concept_id and source.concept_id != target_concept.id:
        merge_concept(source.concept, target_concept)

    primary_moved = ItemTagging.objects.filter(primary_node=source).update(primary_node=target)
    secondary_moved = 0
    for tagging in ItemTagging.objects.filter(secondary_nodes=source):
        tagging.secondary_nodes.remove(source)
        if tagging.primary_node_id != target.id:
            tagging.secondary_nodes.add(target)
        secondary_moved += 1
    for tagging in ItemTagging.objects.filter(primary_node=target, secondary_nodes=target):
        tagging.secondary_nodes.remove(target)

    source.status = 'archived'
    source.save(update_fields=['status', 'updated_at'])
    if target.status == 'proposed':
        target.status = 'active'
        target.save(update_fields=['status', 'updated_at'])
    return {'primary_moved': primary_moved, 'secondary_moved': secondary_moved,
            'concept_id': str(target_concept.id)}


def set_skill_packs(course, packs):
    """Explicit skill packs per subject: ``{subject_id: [pack_key, …]}``.

    Unknown pack keys are dropped; an empty list removes the subject's
    explicit choice (it falls back to name matching).
    """
    if not isinstance(packs, dict):
        raise EditError('Send packs as {subject_id: [pack keys]}.')
    subject_ids = {str(sid) for sid in course.subjects.values_list('id', flat=True)}
    active = set(SkillPack.objects.filter(active=True).values_list('key', flat=True))
    record, _ = CourseSyllabus.objects.get_or_create(course=course, defaults={'tenant': course.tenant})
    current = dict(record.skill_packs or {})
    for subject_id, keys in packs.items():
        if str(subject_id) not in subject_ids:
            raise EditError('That subject is not in this course.')
        cleaned = [key for key in (keys if isinstance(keys, list) else []) if key in active]
        if cleaned:
            current[str(subject_id)] = cleaned
        else:
            current.pop(str(subject_id), None)
    record.skill_packs = current
    record.save(update_fields=['skill_packs', 'updated_at'])
    return current
```

- [ ] **Step 5: Run tests**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_tree_editor -v 2`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/intelligence/services/tree_editor.py backend/intelligence/tests/syllabus_fixtures.py backend/intelligence/tests/test_tree_editor.py
git commit -m "feat(intelligence): syllabus tree editor service (add, rename, move, weight, accept, archive, merge)"
```

---

### Task 5: Tag review service

**Files:**
- Create: `backend/intelligence/services/tag_review.py`
- Test: `backend/intelligence/tests/test_tag_review.py`

**Interfaces:**
- Produces (`tag_review.py`):
  - `ReviewError(ValueError)`; `REVIEW_REASONS`;
  - `item_of(tagging)`, `subject_of(tagging)`, `course_of(tagging)`;
  - `row_payload(tagging) -> dict`;
  - `edit_choices(subject) -> {'topics': [{'id', 'name', 'subtopics': [{'id', 'name', 'status'}]}], 'thinking_levels', 'skills', 'special_formats'}`;
  - `accept(tagging)`, `bulk_accept(queryset) -> int`;
  - `save_manual(tagging, data, *, require_thinking=True) -> ItemTagging`;
  - `mark_for_retag(tagging) -> item`;
  - `add_to_tree(tagging, topic_node=None) -> SyllabusNode`.
- Consumes: `tree_editor.add_node`, `itemtags.replace_links`, `tagging_sweep._mock_item_subject`.

- [ ] **Step 1: Write the failing test**

Create `backend/intelligence/tests/test_tag_review.py`:

```python
"""Tag review actions (spec 2B §5.3)."""
from intelligence.models import ConceptLink, ItemSkillTag, ItemTagging, SyllabusNode, TagDefinition
from intelligence.services import syllabus, tag_review, tagging_sweep
from intelligence.services.tag_review import ReviewError
from intelligence.tests.syllabus_fixtures import SyllabusTestCase
from intelligence.tests.test_tagging_sweep import FakeCall, patched_tree, tag_entry


class ReviewTestCase(SyllabusTestCase):
    def setUp(self):
        super().setUp()
        self.item = self.question('A 2 kg block on a rough floor…')
        friction = syllabus.ensure_node_concept(self.friction)
        ConceptLink.objects.create(tenant=self.tenant, concept=friction, question=self.item,
                                   is_primary=True, source='llm_tagger')
        self.tagging = ItemTagging.objects.create(
            tenant=self.tenant, question=self.item, primary_node=self.friction,
            thinking_level='recall', confidence=0.4, review_status='needs_review',
            review_reasons=['low_confidence'], raw={'topic_key': self.laws_node.key},
        )
        ItemSkillTag.objects.create(
            tenant=self.tenant, question=self.item, role='core', source='llm_tagger',
            skill=TagDefinition.objects.get(kind='skill', key='free_body_diagram'))


class AcceptAndPayloadTests(ReviewTestCase):
    def test_row_payload(self):
        row = tag_review.row_payload(self.tagging)
        self.assertEqual(row['item_kind'], 'bank')
        self.assertEqual(row['primary']['name'], 'Friction')
        self.assertEqual(row['skills'][0]['key'], 'free_body_diagram')
        self.assertEqual(row['review_reasons'], ['low_confidence'])
        self.assertEqual(row['topic'], 'Laws of Motion')

    def test_accept_and_bulk_accept(self):
        tag_review.accept(self.tagging)
        self.tagging.refresh_from_db()
        self.assertEqual(self.tagging.review_status, 'reviewed')
        self.tagging.review_status = 'needs_review'
        self.tagging.save()
        self.assertEqual(tag_review.bulk_accept(ItemTagging.objects.all()), 1)

    def test_edit_choices(self):
        choices = tag_review.edit_choices(self.physics)
        laws = next(t for t in choices['topics'] if t['name'] == 'Laws of Motion')
        self.assertEqual([s['name'] for s in laws['subtopics']], ['Friction', "Newton's Laws"])
        self.assertIn('recall', [t['key'] for t in choices['thinking_levels']])
        self.assertIn('free_body_diagram', [s['key'] for s in choices['skills']])


class ManualEditTests(ReviewTestCase):
    def edit(self, **overrides):
        data = {
            'primary': str(self.newton.id), 'secondary': [str(self.friction.id)],
            'thinking_level': 'single_application',
            'skills': [{'key': 'formula_application', 'role': 'core', 'reason': 'F = ma'}],
            'special_format': '', 'difficulty_prior': 'hard', 'est_solve_seconds': 90,
        }
        data.update(overrides)
        return tag_review.save_manual(self.tagging, data)

    def test_edit_locks_tags_and_rewrites_links(self):
        self.edit()
        self.tagging.refresh_from_db()
        self.assertEqual((self.tagging.source, self.tagging.review_status), ('manual', 'reviewed'))
        self.assertEqual(self.tagging.primary_node_id, self.newton.id)
        links = ConceptLink.objects.filter(question=self.item)
        self.assertEqual({link.source for link in links}, {'manual'})
        self.assertEqual(links.get(is_primary=True).concept_id, self.newton.concept_id)
        skills = ItemSkillTag.objects.filter(question=self.item)
        self.assertEqual([(s.skill.key, s.source) for s in skills], [('formula_application', 'manual')])
        self.item.refresh_from_db()
        self.assertEqual(self.item.cognitive_type, 'application')

    def test_next_sweep_skips_a_manual_item(self):
        self.edit()
        call = FakeCall(tag={str(self.item.id): tag_entry()})
        with patched_tree():
            tagging_sweep.tag_v2_for_tenant(self.tenant, {self.physics.id}, call)
        self.tagging.refresh_from_db()
        self.assertEqual(self.tagging.primary_node_id, self.newton.id)
        self.assertEqual(call.calls, [])

    def test_validation(self):
        with self.assertRaises(ReviewError):
            self.edit(primary=str(self.laws_node.id))          # a topic, not a subtopic
        with self.assertRaises(ReviewError):
            self.edit(thinking_level='wizardry')
        with self.assertRaises(ReviewError):
            self.edit(skills=[{'key': 'nope', 'role': 'core'}])
        with self.assertRaises(ReviewError):
            self.edit(difficulty_prior='impossible')
        self.edit(est_solve_seconds=99999)
        self.tagging.refresh_from_db()
        self.assertEqual(self.tagging.est_solve_seconds, 1800)


class RetagAndAddToTreeTests(ReviewTestCase):
    def test_mark_for_retag_unlocks_and_stales(self):
        self.tagging.source = 'manual'
        self.tagging.save()
        tag_review.mark_for_retag(self.tagging)
        self.tagging.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(self.tagging.source, 'llm_tagger')
        self.assertEqual(self.item.tagging_status, 'stale')

    def test_mark_for_retag_hands_manual_links_and_skills_back(self):
        tag_review.save_manual(self.tagging, {
            'primary': str(self.newton.id), 'secondary': [str(self.friction.id)],
            'thinking_level': 'single_application',
            'skills': [{'key': 'formula_application', 'role': 'core', 'reason': 'F = ma'}],
            'special_format': '', 'difficulty_prior': 'hard', 'est_solve_seconds': 90,
        })
        tag_review.mark_for_retag(self.tagging)
        self.assertFalse(ConceptLink.objects.filter(question=self.item, source='manual').exists())
        self.assertFalse(ItemSkillTag.objects.filter(question=self.item, source='manual').exists())
        self.assertTrue(ConceptLink.objects.filter(question=self.item, source='llm_tagger').exists())

    def test_add_to_tree_creates_and_assigns(self):
        self.tagging.primary_node = None
        self.tagging.proposed_subtopic = 'Rolling friction'
        self.tagging.review_reasons = ['proposed_subtopic']
        self.tagging.save()
        node = tag_review.add_to_tree(self.tagging)
        self.assertEqual(node.parent_id, self.laws_node.id)
        self.assertEqual(node.name, 'Rolling friction')
        self.tagging.refresh_from_db()
        self.assertEqual((self.tagging.primary_node_id, self.tagging.source), (node.id, 'manual'))
        self.assertEqual(self.tagging.proposed_subtopic, '')

    def test_add_to_tree_reuses_a_same_named_subtopic(self):
        self.tagging.proposed_subtopic = 'friction'
        self.tagging.save()
        self.assertEqual(tag_review.add_to_tree(self.tagging).id, self.friction.id)

    def test_add_to_tree_needs_a_proposal(self):
        with self.assertRaises(ReviewError):
            tag_review.add_to_tree(self.tagging)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_tag_review -v 2`
Expected: ImportError (`cannot import name 'tag_review'`).

- [ ] **Step 3: Implement**

Create `backend/intelligence/services/tag_review.py`:

```python
"""The tag review queue (spec 2B §5.3).

Accept keeps the tagger's tags. Edit saves a teacher's tags as ``manual``:
ItemTagging, ConceptLinks and ItemSkillTags all carry source ``manual``, so
the tagger never overwrites them. Re-tag sends the item back to the tagger.
Add to tree turns a proposed subtopic into a real node and assigns it.
"""
from django.db import transaction
from django.utils import timezone

from intelligence.models import ConceptLink, ItemSkillTag, ItemTagging, SyllabusNode, TagDefinition
from intelligence.services.itemtags import content_hash_for, replace_links
from intelligence.services.normalize import concept_slug
from intelligence.services.syllabus import ensure_node_concept, packs_for_subject
from intelligence.services.tagging_v2 import cognitive_projection
from intelligence.services.tree_editor import as_uuid

REVIEW_REASONS = ('low_confidence', 'invalid_key', 'proposed_subtopic', 'stage_disagreement')
DIFFICULTIES = ('easy', 'medium', 'hard')
SOLVE_SECONDS = (10, 1800)
LIVE = ('active', 'proposed')
REASON_CHARS = 200


class ReviewError(ValueError):
    """A refused review action; the message is shown to the teacher."""


def item_of(tagging):
    return tagging.question or tagging.mock_item


def _arm(tagging):
    return 'question' if tagging.question_id else 'mock_item'


def subject_of(tagging):
    from intelligence.services.tagging_sweep import _mock_item_subject

    item = item_of(tagging)
    if item is None:
        return None
    return item.subject if tagging.question_id else _mock_item_subject(item)


def course_of(tagging):
    subject = subject_of(tagging)
    return subject.course if subject else None


def _node_brief(node):
    if node is None:
        return None
    return {'id': str(node.id), 'name': node.name, 'status': node.status,
            'topic': node.parent.name if node.parent_id else ''}


def row_payload(tagging):
    """One review row: the question and every tag the tagger gave it."""
    item = item_of(tagging)
    arm = _arm(tagging)
    skills = (ItemSkillTag.objects.filter(**{arm: item}).select_related('skill')
              .order_by('-role', 'skill__key'))
    topic = getattr(item, 'topic', None)
    return {
        'id': str(tagging.id),
        'item_kind': 'bank' if arm == 'question' else 'item',
        'item_id': str(item.id),
        'question_text': (item.question_text or '')[:400],
        'topic': topic.name if topic else '',
        'primary': _node_brief(tagging.primary_node),
        'secondary': [_node_brief(node) for node in tagging.secondary_nodes.select_related('parent')],
        'thinking_level': tagging.thinking_level,
        'skills': [
            {'key': tag.skill.key, 'label': tag.skill.label, 'role': tag.role,
             'reason': tag.reason, 'source': tag.source}
            for tag in skills
        ],
        'special_format': tagging.special_format,
        'difficulty_prior': tagging.difficulty_prior,
        'est_solve_seconds': tagging.est_solve_seconds,
        'confidence': tagging.confidence,
        'review_status': tagging.review_status,
        'review_reasons': tagging.review_reasons,
        'proposed_subtopic': tagging.proposed_subtopic,
        'source': tagging.source,
    }


def edit_choices(subject):
    """The tree and vocabulary an edit may choose from, for one subject."""
    nodes = list(SyllabusNode.objects.filter(subject=subject, status__in=LIVE).order_by('order', 'name'))
    topics = [
        {'id': str(topic.id), 'name': topic.name,
         'subtopics': [{'id': str(child.id), 'name': child.name, 'status': child.status}
                       for child in nodes if child.parent_id == topic.id and child.level == 'subtopic']}
        for topic in nodes if topic.level == 'topic'
    ]

    def vocabulary(kind, packs=None):
        rows = TagDefinition.objects.filter(kind=kind, active=True)
        if kind == TagDefinition.KIND_SKILL:
            from django.db.models import Q
            rows = rows.filter(Q(pack__isnull=True) | Q(pack__in=packs or []))
        return [{'key': row.key, 'label': row.label} for row in rows.order_by('order', 'key')]

    return {
        'topics': topics,
        'thinking_levels': vocabulary(TagDefinition.KIND_THINKING),
        'skills': vocabulary(TagDefinition.KIND_SKILL, packs_for_subject(subject)),
        'special_formats': vocabulary(TagDefinition.KIND_FORMAT),
    }


def accept(tagging):
    tagging.review_status = ItemTagging.REVIEW_DONE
    tagging.save(update_fields=['review_status', 'updated_at'])
    return tagging


def bulk_accept(queryset):
    return queryset.filter(review_status=ItemTagging.REVIEW_NEEDED).update(
        review_status=ItemTagging.REVIEW_DONE, updated_at=timezone.now())


def _subtopic(subject, node_id):
    node_id = as_uuid(node_id)
    node = SyllabusNode.objects.filter(
        id=node_id, subject=subject, level='subtopic', status__in=LIVE).first() if node_id else None
    if node is None:
        raise ReviewError('Pick a subtopic from this subject\'s tree.')
    return node


def _clean(tagging, data, subject, require_thinking):
    if not isinstance(data, dict):
        raise ReviewError('Send the tags as an object.')
    choices = edit_choices(subject)
    primary = _subtopic(subject, data.get('primary'))
    secondary = []
    for node_id in data.get('secondary') or []:
        node = _subtopic(subject, node_id)
        if node.id != primary.id and node not in secondary:
            secondary.append(node)
    thinking = str(data.get('thinking_level') or '')
    if thinking not in {row['key'] for row in choices['thinking_levels']} and (thinking or require_thinking):
        raise ReviewError('Pick a thinking level.')
    skill_keys = {row['key'] for row in choices['skills']}
    skills, seen = [], set()
    for raw in data.get('skills') or []:
        key = raw.get('key') if isinstance(raw, dict) else None
        if key not in skill_keys:
            raise ReviewError('Pick skills from the list for this subject.')
        if key in seen:
            continue
        seen.add(key)
        skills.append({'key': key, 'role': 'core' if raw.get('role') == 'core' else 'supporting',
                       'reason': str(raw.get('reason') or '')[:REASON_CHARS]})
    special = str(data.get('special_format') or '')
    if special and special not in {row['key'] for row in choices['special_formats']}:
        raise ReviewError('Unknown special format.')
    difficulty = str(data.get('difficulty_prior') or '')
    if difficulty and difficulty not in DIFFICULTIES:
        raise ReviewError('Difficulty is easy, medium or hard.')
    seconds = data.get('est_solve_seconds')
    if seconds in (None, ''):
        seconds = None
    else:
        try:
            seconds = min(SOLVE_SECONDS[1], max(SOLVE_SECONDS[0], int(seconds)))
        except (TypeError, ValueError):
            raise ReviewError('Solve time is a number of seconds.') from None
    return primary, secondary, thinking, skills, special, difficulty, seconds


@transaction.atomic
def save_manual(tagging, data, *, require_thinking=True):
    """Save a teacher's tags and lock them against the tagger."""
    subject = subject_of(tagging)
    if subject is None:
        raise ReviewError('This question has no subject, so it has no tree to tag against.')
    primary, secondary, thinking, skills, special, difficulty, seconds = _clean(
        tagging, data, subject, require_thinking)
    item = item_of(tagging)
    arm = _arm(tagging)

    concepts = [ensure_node_concept(node) for node in [primary, *secondary]]
    replace_links(item, [], source='llm_tagger')
    replace_links(item, concepts, source='manual')

    ItemSkillTag.objects.filter(**{arm: item}).delete()
    definitions = {row.key: row for row in TagDefinition.objects.filter(
        kind=TagDefinition.KIND_SKILL, key__in=[skill['key'] for skill in skills])}
    ItemSkillTag.objects.bulk_create([
        ItemSkillTag(tenant=item.tenant, skill=definitions[skill['key']], role=skill['role'],
                     reason=skill['reason'], source='manual', **{arm: item})
        for skill in skills
    ])

    tagging.primary_node = primary
    tagging.thinking_level = thinking
    tagging.special_format = special
    tagging.difficulty_prior = difficulty
    tagging.est_solve_seconds = seconds
    tagging.review_status = ItemTagging.REVIEW_DONE
    tagging.review_reasons = []
    tagging.proposed_subtopic = ''
    tagging.source = 'manual'
    tagging.save()
    tagging.secondary_nodes.set(secondary)

    update_fields = ['content_hash', 'tagging_status', 'tagged_at', 'updated_at']
    item.content_hash = content_hash_for(item)
    item.tagging_status = 'tagged'
    item.tagged_at = timezone.now()
    projection = cognitive_projection(thinking)
    if projection:
        item.cognitive_type = projection
        update_fields.append('cognitive_type')
    item.save(update_fields=update_fields)
    return tagging


def mark_for_retag(tagging):
    """Hand the item back to the tagger: unlock it and mark it stale."""
    item = item_of(tagging)
    if tagging.source == 'manual':
        tagging.source = 'llm_tagger'
        tagging.save(update_fields=['source', 'updated_at'])
        # The teacher's links and skills become tagger rows, so the re-tag
        # replaces them instead of sitting beside the new primary link.
        ConceptLink.objects.filter(**{_arm(tagging): item}, source='manual').update(source='llm_tagger')
        ItemSkillTag.objects.filter(**{_arm(tagging): item}, source='manual').update(source='llm_tagger')
    item.tagging_status = 'stale'
    item.save(update_fields=['tagging_status', 'updated_at'])
    return item


def _topic_for(tagging, subject):
    key = (tagging.raw or {}).get('topic_key')
    if key:
        node = SyllabusNode.objects.filter(subject=subject, key=key, level='topic', status__in=LIVE).first()
        if node:
            return node
    item = item_of(tagging)
    if getattr(item, 'topic_id', None):
        return SyllabusNode.objects.filter(
            subject=subject, level='topic', course_topic_id=item.topic_id, status__in=LIVE).first()
    return None


@transaction.atomic
def add_to_tree(tagging, topic_node=None):
    """Create the proposed subtopic under the item's topic and assign it."""
    from intelligence.services.tree_editor import EditError, add_node

    name = ' '.join((tagging.proposed_subtopic or '').split())
    if not name:
        raise ReviewError('This question has no proposed subtopic.')
    subject = subject_of(tagging)
    if subject is None:
        raise ReviewError('This question has no subject.')
    topic = topic_node or _topic_for(tagging, subject)
    if topic is None or topic.subject_id != subject.id or topic.level != 'topic':
        raise ReviewError('Pick the topic the new subtopic belongs to.')
    slug = concept_slug(name)
    node = next((child for child in SyllabusNode.objects.filter(
        parent=topic, level='subtopic', status__in=LIVE) if concept_slug(child.name) == slug), None)
    if node is None:
        try:
            node = add_node(subject, level='subtopic', name=name, parent=topic)
        except EditError as exc:
            raise ReviewError(str(exc)) from exc
    arm = _arm(tagging)
    save_manual(tagging, {
        'primary': str(node.id),
        'secondary': [str(n.id) for n in tagging.secondary_nodes.filter(status__in=LIVE)],
        'thinking_level': tagging.thinking_level,
        'skills': [{'key': tag.skill.key, 'role': tag.role, 'reason': tag.reason}
                   for tag in ItemSkillTag.objects.filter(**{arm: item_of(tagging)}).select_related('skill')],
        'special_format': tagging.special_format,
        'difficulty_prior': tagging.difficulty_prior,
        'est_solve_seconds': tagging.est_solve_seconds,
    }, require_thinking=False)
    return node
```

- [ ] **Step 4: Run tests**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_tag_review -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/intelligence/services/tag_review.py backend/intelligence/tests/test_tag_review.py
git commit -m "feat(intelligence): tag review actions with a manual lock"
```

---

### Task 6: Workers

**Files:**
- Modify: `backend/intelligence/tasks.py`
- Test: `backend/intelligence/tests/test_syllabus_jobs.py` (add a class)

**Interfaces:**
- Produces (tasks):
  - `intelligence.build_course_tree` → `run_tree_build(job_id)` (queue `aigen`);
  - `intelligence.tagging_run` → `run_tagging_run(run_id)` (queue `aigen`);
  - `intelligence.retag_item` → `retag_item(kind, item_id)` (queue `aigen`; kind `bank` / `item`);
  - `intelligence.recompute_concept_states` → `recompute_concept_states(concept_id)` (queue `intelligence`).
- Every job worker: claims `queued → running` atomically (a second delivery is a no-op), refuses if `syllabus_tools` is off, checks the budget, records tokens and cost, and never leaves a job `running` on an exception.

- [ ] **Step 1: Write the failing test**

Append to `backend/intelligence/tests/test_syllabus_jobs.py`:

```python
from coursegen.generation import GenerationError
from intelligence import tasks
from intelligence.models import TaggingRun, TreeBuildJob


class WorkerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create(name='Worker Academy', features={'syllabus_tools': True})
        cls.course = Course.objects.create(
            tenant=cls.tenant, name='DSA', code='work-dsa', course_type='skill')
        cls.subject = Subject.objects.create(
            tenant=cls.tenant, course=cls.course, name='Arrays', code='arrays')
        Topic.objects.create(tenant=cls.tenant, subject=cls.subject, name='Two Sum', code='two-sum')

    def fake_call(self, call):
        call.meter = type('M', (), {'usage': type('U', (), {'total_tokens': 1234})()})()
        call.cost_usd = lambda: 0.01
        return patch('intelligence.services.llm.tenant_tagging_call', return_value=call)

    def test_build_job_runs_and_records(self):
        job = TreeBuildJob.objects.create(tenant=self.tenant, course=self.course, options={'packs': []})
        with self.fake_call(BuildCall(subtopics={'Two Sum': ['Hash map']})):
            tasks.run_tree_build(str(job.id))
        job.refresh_from_db()
        self.assertEqual(job.status, 'done', job.error)
        self.assertEqual(job.summary['proposed_subtopics'], 1)
        self.assertEqual(job.tokens, 1234)
        self.assertIsNotNone(job.finished_at)

    def test_second_delivery_is_a_no_op(self):
        job = TreeBuildJob.objects.create(tenant=self.tenant, course=self.course, status='done')
        with self.fake_call(BuildCall()) as patched:
            tasks.run_tree_build(str(job.id))
        patched.assert_not_called()

    def test_budget_refusal_fails_the_job(self):
        job = TreeBuildJob.objects.create(tenant=self.tenant, course=self.course)
        with patch('coursegen.generation._check_budget', side_effect=GenerationError('over budget')):
            tasks.run_tree_build(str(job.id))
        job.refresh_from_db()
        self.assertEqual((job.status, job.error), ('failed', 'over budget'))

    def test_switch_off_fails_the_job(self):
        self.tenant.features = {}
        self.tenant.save()
        run = TaggingRun.objects.create(tenant=self.tenant, course=self.course)
        tasks.run_tagging_run(str(run.id))
        run.refresh_from_db()
        self.assertEqual(run.status, 'failed')

    def test_unexpected_error_never_leaves_running(self):
        job = TreeBuildJob.objects.create(tenant=self.tenant, course=self.course)
        with self.fake_call(BuildCall()), patch(
                'intelligence.services.course_tree.build_course_tree', side_effect=RuntimeError('boom')):
            tasks.run_tree_build(str(job.id))
        job.refresh_from_db()
        self.assertEqual(job.status, 'failed')
```

- [ ] **Step 2: Run it to verify it fails**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_syllabus_jobs -v 2`
Expected: AttributeError (`module 'intelligence.tasks' has no attribute 'run_tree_build'`).

- [ ] **Step 3: Implement**

Append to `backend/intelligence/tasks.py`:

```python
# ─────────────────────────────────────────────────────────────────────────────
# Syllabus tools (queue: aigen) — spec 2B §5
# ─────────────────────────────────────────────────────────────────────────────

TAGGING_RUN_LIMIT = 500


def _claim(model, job_id):
    """queued → running, atomically. None when already claimed or gone."""
    from django.utils import timezone

    claimed = model.objects.filter(id=job_id, status=model.STATUS_QUEUED).update(
        status=model.STATUS_RUNNING, started_at=timezone.now())
    if not claimed:
        return None
    return model.objects.filter(id=job_id).select_related('tenant', 'course').first()


def _finish(job, *, status, summary=None, error='', call=None):
    from django.utils import timezone

    job.status = status
    job.summary = summary if summary is not None else job.summary
    job.error = error[:1000]
    if call is not None:
        try:
            job.tokens = call.meter.usage.total_tokens
            job.cost_usd = call.cost_usd()
        except Exception:  # noqa: BLE001 — metering must never fail the job
            logger.exception('syllabus job %s: metering failed', job.id)
    job.finished_at = timezone.now()
    job.save()


def _run_syllabus_job(model, job_id, work, label):
    """Shared worker shell: claim, gate, budget, run, record."""
    from coursegen.generation import GenerationError, _check_budget

    from .services import llm

    job = _claim(model, job_id)
    if job is None:
        logger.info('%s: %s not runnable, skipping', label, job_id)
        return None
    call = None
    try:
        if not job.tenant.get_features().get('syllabus_tools'):
            raise GenerationError('Syllabus & tagging tools are turned off for this academy.')
        _check_budget(job.tenant)
        call = llm.tenant_tagging_call(job.tenant)
        summary = work(job, call)
        _finish(job, status=model.STATUS_DONE, summary=summary, call=call)
    except GenerationError as exc:
        _finish(job, status=model.STATUS_FAILED, error=str(exc), call=call)
    except Exception:  # noqa: BLE001 — never leave a job 'running'
        logger.exception('%s failed for %s', label, job_id)
        _finish(job, status=model.STATUS_FAILED, error='The run failed unexpectedly.', call=call)
    return str(job_id)


@shared_task(
    name='intelligence.build_course_tree', bind=True, max_retries=0,
    queue='aigen', soft_time_limit=1500, time_limit=1560,
)
def run_tree_build(self, job_id):
    """Build or extend a custom course's syllabus tree (one TreeBuildJob)."""
    from .models import TreeBuildJob
    from .services import course_tree

    def work(job, call):
        packs = job.options.get('packs') if isinstance(job.options, dict) else None
        return course_tree.build_course_tree(job.course, call=call, packs=packs)

    return _run_syllabus_job(TreeBuildJob, job_id, work, 'intelligence.build_course_tree')


@shared_task(
    name='intelligence.tagging_run', bind=True, max_retries=0,
    queue='aigen', soft_time_limit=1500, time_limit=1560,
)
def run_tagging_run(self, run_id):
    """Tag a course's not-current items with tagger v2 (one TaggingRun)."""
    from coursegen.generation import GenerationError

    from .models import SyllabusNode, TaggingRun
    from .services import taxonomy, tagging_sweep

    def work(run, call):
        subject_ids = set(
            SyllabusNode.objects.filter(subject__course=run.course, level='topic', status='active')
            .values_list('subject_id', flat=True))
        if not subject_ids:
            raise GenerationError('Build or map a syllabus tree for this course first.')
        if taxonomy.current_release() is None:
            raise GenerationError('No tag vocabulary is loaded. Run manage.py sync_taxonomy.')
        stats = {}
        tagging_sweep.tag_v2_for_tenant(
            run.tenant, subject_ids, call, limit=TAGGING_RUN_LIMIT, stats=stats)
        return stats

    return _run_syllabus_job(TaggingRun, run_id, work, 'intelligence.tagging_run')


@shared_task(
    name='intelligence.retag_item', max_retries=0,
    queue='aigen', soft_time_limit=280, time_limit=300,
)
def retag_item(kind, item_id):
    """Re-tag one bank question ('bank') or mock item ('item') now."""
    from coursegen.generation import GenerationError, _check_budget
    from quiz.models import MockTestItem, Question

    from .services import llm, tagging_sweep

    model = {'bank': Question, 'item': MockTestItem}.get(kind)
    item = model.objects.filter(id=item_id).select_related('tenant').first() if model else None
    if item is None or not item.tenant.get_features().get('syllabus_tools'):
        return 0
    try:
        _check_budget(item.tenant)
        return tagging_sweep.tag_one_item(item, llm.tenant_tagging_call(item.tenant))
    except GenerationError as exc:
        logger.info('intelligence.retag_item %s %s: %s', kind, item_id, exc)
        return 0
    except Exception:  # noqa: BLE001 — the item stays stale; the weekly sweep retries
        logger.exception('intelligence.retag_item failed for %s %s', kind, item_id)
        return 0


@shared_task(name='intelligence.recompute_concept_states', max_retries=0, queue='intelligence')
def recompute_concept_states(concept_id):
    """Recompute every learner state on one concept (after a subtopic merge)."""
    from django.db.models import Q

    from users.models import StudentProfile

    from .models import Concept, ConceptLink, LearningEvent
    from .services import state

    concept = Concept.objects.filter(id=concept_id).first()
    if concept is None:
        return 0
    links = ConceptLink.objects.filter(concept=concept)
    question_ids = [qid for qid in links.values_list('question_id', flat=True) if qid]
    item_ids = [mid for mid in links.values_list('mock_item_id', flat=True) if mid]
    student_ids = (
        LearningEvent.objects.filter(Q(question_id__in=question_ids) | Q(mock_item_id__in=item_ids))
        .values_list('student_id', flat=True).distinct()
    )
    done = 0
    for student in StudentProfile.objects.filter(id__in=list(student_ids)):
        state.recompute_state(student, concept)
        done += 1
    return done
```

- [ ] **Step 4: Run tests**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_syllabus_jobs intelligence.tests.test_celery_config -v 2`
Expected: PASS. (If `test_celery_config` asserts every task name is routed to a known queue, it will cover the four new names; fix any routing table it checks.)

- [ ] **Step 5: Commit**

```bash
git add backend/intelligence/tasks.py backend/intelligence/tests/test_syllabus_jobs.py
git commit -m "feat(intelligence): workers for tree builds, tagging runs, re-tag and merge recompute"
```

---

### Task 7: Course-scoped endpoints (tree, build, exam, nodes, packs, tagging, jobs)

**Files:**
- Create: `backend/intelligence/syllabus_views.py`
- Create: `backend/intelligence/syllabus_urls.py`
- Modify: `backend/intelligence/admin_urls.py`
- Test: `backend/intelligence/tests/test_syllabus_api.py`

**Interfaces:**
- Produces, under `/api/v1/tenant-admin/intelligence/syllabus/`:

| Method and path | Body | Returns |
|---|---|---|
| `GET courses/<id>/tree/` | — | `tree_payload(course)` + `jobs` (last 10, both kinds) + `budget` |
| `POST courses/<id>/tree/estimate/` | `{packs?}` | `estimate_build` + `budget` |
| `POST courses/<id>/tree/build/` | `{packs?}` | 202 job payload; 400 exam course / budget; 409 active job |
| `POST courses/<id>/tree/exam/` | `{exam, subjects: {subject_id: tree_subject_key}}` | instantiate summary + fresh tree |
| `POST courses/<id>/nodes/` | `{subject, level, name, parent?, description?}` | 201 node |
| `PATCH nodes/<id>/` | any of `name, description, parent, weightage, status` | node + `warnings` |
| `POST nodes/<id>/merge/` | `{into}` | merge summary |
| `PATCH courses/<id>/skill-packs/` | `{packs: {subject_id: [keys]}}` | `{skill_packs}` |
| `POST courses/<id>/tagging/estimate/` | — | `estimate_tagging` + `budget` + `subjects_with_tree` |
| `POST courses/<id>/tagging/run/` | — | 202 run payload; 400 no tree / budget; 409 active run |
| `GET jobs/<id>/` | — | job payload (either kind) |

- Consumes: `tree_editor`, `course_tree.estimate_build`, `tagging_sweep.estimate_tagging`, `llm.budget_status`, `api.enqueue`, the workers (Task 6), `access.can_manage_course`.

- [ ] **Step 1: Write the failing test**

Create `backend/intelligence/tests/test_syllabus_api.py`:

```python
"""Syllabus tools API: switch, scope, and each operation end to end."""
from unittest.mock import patch

from intelligence.models import SyllabusNode, TaggingRun, TreeBuildJob
from intelligence.tests.syllabus_fixtures import SyllabusTestCase
from intelligence.tests.test_course_tree import FakeCall as BuildCall

BASE = '/api/v1/tenant-admin/intelligence/syllabus'


def fake_call(call):
    call.meter = type('M', (), {'usage': type('U', (), {'total_tokens': 10})()})()
    call.cost_usd = lambda: 0
    return patch('intelligence.services.llm.tenant_tagging_call', return_value=call)


class CourseEndpointTests(SyllabusTestCase):
    def test_tree(self):
        response = self.client_for(self.faculty).get(f'{BASE}/courses/{self.course.id}/tree/')
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual(data['kind'], 'exam')
        self.assertEqual(data['jobs'], [])
        self.assertIn('budget', data)

    def test_scope_and_switch(self):
        url = f'{BASE}/courses/{self.custom.id}/tree/'
        self.assertEqual(self.client_for(self.faculty).get(url).status_code, 403)
        self.assertEqual(self.client_for(self.other_faculty).get(url).status_code, 200)
        self.assertEqual(self.client_for(self.admin).get(url).status_code, 200)
        self.tenant.features = {}
        self.tenant.save()
        self.assertEqual(self.client_for(self.admin).get(url).status_code, 403)

    def test_build_flow_runs_eagerly_in_tests(self):
        client = self.client_for(self.admin)
        estimate = client.post(f'{BASE}/courses/{self.custom.id}/tree/estimate/', {}, format='json')
        self.assertEqual(estimate.status_code, 200)
        self.assertEqual(estimate.json()['calls']['subtopics'], 1)
        with fake_call(BuildCall(subtopics={'Two Sum': ['Hash map lookup']})):
            response = client.post(f'{BASE}/courses/{self.custom.id}/tree/build/', {'packs': []},
                                   format='json')
        self.assertEqual(response.status_code, 202, response.content)
        job = TreeBuildJob.objects.get()
        self.assertEqual(job.status, 'done', job.error)
        status = client.get(f'{BASE}/jobs/{job.id}/').json()
        self.assertEqual(status['summary']['proposed_subtopics'], 1)
        tree = client.get(f'{BASE}/courses/{self.custom.id}/tree/').json()
        self.assertEqual(tree['subjects'][0]['proposed'], 1)
        self.assertEqual(tree['jobs'][0]['id'], str(job.id))

    def test_build_refusals(self):
        client = self.client_for(self.admin)
        self.assertEqual(
            client.post(f'{BASE}/courses/{self.course.id}/tree/build/', {}, format='json').status_code, 400)
        TreeBuildJob.objects.create(tenant=self.tenant, course=self.custom, status='running')
        self.assertEqual(
            client.post(f'{BASE}/courses/{self.custom.id}/tree/build/', {}, format='json').status_code, 409)
        TreeBuildJob.objects.all().delete()
        with patch('intelligence.syllabus_views.budget_status',
                   return_value={'exhausted': True, 'monthly_budget': 10, 'used': 10, 'remaining': 0}):
            response = client.post(f'{BASE}/courses/{self.custom.id}/tree/build/', {}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_exam_mapping_refused_for_a_built_course(self):
        client = self.client_for(self.admin)
        with fake_call(BuildCall()):
            client.post(f'{BASE}/courses/{self.custom.id}/tree/build/', {'packs': []}, format='json')
        response = client.post(f'{BASE}/courses/{self.custom.id}/tree/exam/',
                               {'exam': 'jee_main', 'subjects': {str(self.arrays.id): 'physics'}},
                               format='json')
        self.assertEqual(response.status_code, 400)

    def test_node_add_patch_merge(self):
        client = self.client_for(self.faculty)
        created = client.post(f'{BASE}/courses/{self.course.id}/nodes/', {
            'subject': str(self.physics.id), 'level': 'subtopic', 'name': 'Static friction',
            'parent': str(self.laws_node.id)}, format='json')
        self.assertEqual(created.status_code, 201, created.content)
        node_id = created.json()['id']
        patched = client.patch(f'{BASE}/nodes/{node_id}/', {'weightage': 0.3}, format='json')
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(len(patched.json()['warnings']), 1)
        refused = client.patch(f'{BASE}/nodes/{self.laws_node.id}/', {'name': 'X'}, format='json')
        self.assertEqual(refused.status_code, 400)
        merged = client.post(f'{BASE}/nodes/{node_id}/merge/', {'into': str(self.friction.id)},
                             format='json')
        self.assertEqual(merged.status_code, 200, merged.content)
        self.assertEqual(SyllabusNode.objects.get(id=node_id).status, 'archived')
        self.assertEqual(
            self.client_for(self.other_faculty).patch(
                f'{BASE}/nodes/{self.friction.id}/', {'weightage': 0.5}, format='json').status_code,
            403)

    def test_skill_packs(self):
        response = self.client_for(self.admin).patch(
            f'{BASE}/courses/{self.course.id}/skill-packs/',
            {'packs': {str(self.physics.id): ['physics']}}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['skill_packs'], {str(self.physics.id): ['physics']})

    def test_tagging_estimate_and_refusal_without_tree(self):
        client = self.client_for(self.admin)
        self.question('Friction on a block?')
        estimate = client.post(f'{BASE}/courses/{self.course.id}/tagging/estimate/', {}, format='json')
        self.assertEqual(estimate.status_code, 200, estimate.content)
        self.assertEqual(estimate.json()['questions'], 1)
        refused = client.post(f'{BASE}/courses/{self.custom.id}/tagging/run/', {}, format='json')
        self.assertEqual(refused.status_code, 400)
        self.assertFalse(TaggingRun.objects.exists())
```

- [ ] **Step 2: Run it to verify it fails**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_syllabus_api -v 2`
Expected: FAIL (404 routes).

- [ ] **Step 3: Implement the views**

Create `backend/intelligence/syllabus_views.py`:

```python
"""Syllabus & tagging tools (spec 2B §5) at
/api/v1/tenant-admin/intelligence/syllabus/.

Every view needs the ``syllabus_tools`` switch. Course, node, job and
tagging-scoped calls also need ``can_manage_course``: admins manage every
course in the tenant, faculty their assigned courses.
"""
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from exams.models import Course

from .access import can_manage_course, teachable_course_ids
from .admin_views import IsTenantAdminOrInstructor
from .models import CourseSyllabus, ItemTagging, SyllabusNode, TaggingRun, TreeBuildJob
from .services.llm import budget_status
from .services.tree_editor import EditError, as_uuid

JOB_HISTORY = 10


class SyllabusToolsPermission(permissions.BasePermission):
    message = 'Syllabus & tagging tools are not enabled for this academy.'

    def has_permission(self, request, view):
        tenant = getattr(request, 'tenant', None)
        return bool(tenant and tenant.get_features().get('syllabus_tools'))


SYLLABUS = [permissions.IsAuthenticated, IsTenantAdminOrInstructor, SyllabusToolsPermission]


def _error(message, code=status.HTTP_400_BAD_REQUEST):
    return Response({'error': message}, status=code)


def _not_found(what):
    return _error(f'{what} not found.', status.HTTP_404_NOT_FOUND)


def _forbidden():
    return _error('Not in your courses.', status.HTTP_403_FORBIDDEN)


def _course(request, course_id):
    """(course, None) or (None, error response)."""
    course = Course.objects.filter(id=course_id, tenant=request.tenant).first()
    if course is None:
        return None, _not_found('Course')
    if not can_manage_course(request.user, course):
        return None, _forbidden()
    return course, None


def _node(request, node_id):
    node = (SyllabusNode.objects.filter(id=node_id, tenant=request.tenant)
            .select_related('subject__course', 'parent').first())
    if node is None:
        return None, _not_found('Node')
    if not can_manage_course(request.user, node.subject.course):
        return None, _forbidden()
    return node, None


def _jobs(course):
    rows = (list(TreeBuildJob.objects.filter(course=course).select_related('started_by')[:JOB_HISTORY])
            + list(TaggingRun.objects.filter(course=course).select_related('started_by')[:JOB_HISTORY]))
    rows.sort(key=lambda job: job.created_at, reverse=True)
    return [job.payload() for job in rows[:JOB_HISTORY]]


def _start(model, course, request, task, options=None):
    """Create a queued job and enqueue it. 409 when one is already active."""
    from .api import enqueue

    active = model.objects.filter(course=course, status__in=model.ACTIVE_STATUSES).first()
    if active is not None:
        return Response({'error': 'A run is already in progress.', 'job': active.payload()},
                        status=status.HTTP_409_CONFLICT)
    job = model.objects.create(tenant=course.tenant, course=course, started_by=request.user,
                               options=options or {})
    try:
        enqueue(task, str(job.id))
    except Exception:  # noqa: BLE001 — broker down: say so, don't leave it queued forever
        job.status = model.STATUS_FAILED
        job.error = 'Could not queue the run. Try again in a minute.'
        job.save(update_fields=['status', 'error', 'updated_at'])
    job.refresh_from_db()
    return Response(job.payload(), status=status.HTTP_202_ACCEPTED)


def _packs_option(data):
    packs = data.get('packs') if isinstance(data, dict) else None
    if packs is None:
        return None
    return [key for key in packs if isinstance(key, str)] if isinstance(packs, list) else None


def _has_built_tree(course):
    return SyllabusNode.objects.filter(
        subject__course=course, source__in=('course', 'llm_proposed', 'manual'),
    ).exclude(status='archived').exists()


def _exam_course(course):
    record = CourseSyllabus.objects.filter(course=course).first()
    return record.exam_tree if record and record.exam_tree else ''


class CourseTreeView(APIView):
    permission_classes = SYLLABUS

    def get(self, request, course_id):
        from .services.tree_editor import tree_payload

        course, error = _course(request, course_id)
        if error:
            return error
        return Response({**tree_payload(course), 'jobs': _jobs(course),
                         'budget': budget_status(request.tenant)})


class TreeEstimateView(APIView):
    permission_classes = SYLLABUS

    def post(self, request, course_id):
        from .services.course_tree import estimate_build

        course, error = _course(request, course_id)
        if error:
            return error
        return Response({**estimate_build(course, packs=_packs_option(request.data)),
                         'budget': budget_status(request.tenant)})


class TreeBuildView(APIView):
    permission_classes = SYLLABUS

    def post(self, request, course_id):
        from .tasks import run_tree_build

        course, error = _course(request, course_id)
        if error:
            return error
        exam = _exam_course(course)
        if exam:
            return _error(f'This course uses the {exam} exam syllabus; edit that tree instead.')
        if budget_status(request.tenant)['exhausted']:
            return _error('This academy has used its monthly AI token budget.')
        packs = _packs_option(request.data)
        return _start(TreeBuildJob, course, request, run_tree_build,
                      {'packs': packs} if packs is not None else {})


class ExamMappingView(APIView):
    permission_classes = SYLLABUS

    def post(self, request, course_id):
        from .services.syllabus import instantiate_exam_tree
        from .services.taxonomy import TaxonomyError
        from .services.tree_editor import tree_payload

        course, error = _course(request, course_id)
        if error:
            return error
        data = request.data if isinstance(request.data, dict) else {}
        if _has_built_tree(course) and not _exam_course(course):
            return _error('This course already has its own built tree.')
        mapping = data.get('subjects')
        if not isinstance(data.get('exam'), str) or not isinstance(mapping, dict) or not mapping:
            return _error('Pick an exam tree and map at least one subject.')
        subjects = {str(s.id): s for s in course.subjects.all()}
        subject_map = {}
        for subject_id, tree_key in mapping.items():
            if str(subject_id) not in subjects or not isinstance(tree_key, str) or not tree_key:
                return _error('Map only this course\'s subjects, each to one tree subject.')
            if tree_key in subject_map:
                return _error('Each tree subject can be mapped once.')
            subject_map[tree_key] = subjects[str(subject_id)]
        try:
            summary = instantiate_exam_tree(course, data['exam'], subject_map)
        except TaxonomyError as exc:
            return _error('; '.join(exc.args[0]) if exc.args and isinstance(exc.args[0], list) else str(exc))
        return Response({'summary': summary, 'tree': tree_payload(course)})


def _node_out(node, warnings=None):
    return {'id': str(node.id), 'key': node.key, 'level': node.level, 'name': node.name,
            'status': node.status, 'weightage': node.weightage,
            'parent': str(node.parent_id) if node.parent_id else None,
            'warnings': warnings or []}


class NodeCreateView(APIView):
    permission_classes = SYLLABUS

    def post(self, request, course_id):
        from .services.tree_editor import add_node

        course, error = _course(request, course_id)
        if error:
            return error
        data = request.data if isinstance(request.data, dict) else {}
        subject_id = as_uuid(data.get('subject'))
        subject = course.subjects.filter(id=subject_id).first() if subject_id else None
        if subject is None:
            return _error('Pick a subject of this course.')
        parent = None
        if data.get('parent'):
            parent_id = as_uuid(data['parent'])
            parent = (SyllabusNode.objects.filter(id=parent_id, subject=subject).first()
                      if parent_id else None)
            if parent is None:
                return _error('That parent is not in this subject.')
        try:
            node = add_node(subject, level=data.get('level'), name=data.get('name'),
                            parent=parent, description=data.get('description', ''))
        except EditError as exc:
            return _error(str(exc))
        return Response(_node_out(node), status=status.HTTP_201_CREATED)


class NodeDetailView(APIView):
    permission_classes = SYLLABUS

    def patch(self, request, node_id):
        from .services.tree_editor import update_node

        node, error = _node(request, node_id)
        if error:
            return error
        data = request.data if isinstance(request.data, dict) else {}
        try:
            warnings = update_node(node, data)
        except EditError as exc:
            return _error(str(exc))
        return Response(_node_out(node, warnings))


class NodeMergeView(APIView):
    permission_classes = SYLLABUS

    def post(self, request, node_id):
        from .api import enqueue
        from .services.tree_editor import merge_nodes
        from .tasks import recompute_concept_states

        node, error = _node(request, node_id)
        if error:
            return error
        target_id = as_uuid(request.data.get('into')) if isinstance(request.data, dict) else None
        target = SyllabusNode.objects.filter(id=target_id, subject=node.subject).first() if target_id else None
        if target is None:
            return _error('Pick a subtopic of this subject to merge into.')
        try:
            summary = merge_nodes(node, target)
        except EditError as exc:
            return _error(str(exc))
        try:
            enqueue(recompute_concept_states, summary['concept_id'])
        except Exception:  # noqa: BLE001 — the nightly refresh re-decays states anyway
            pass
        return Response(summary)


class SkillPacksView(APIView):
    permission_classes = SYLLABUS

    def patch(self, request, course_id):
        from .services.tree_editor import set_skill_packs

        course, error = _course(request, course_id)
        if error:
            return error
        data = request.data if isinstance(request.data, dict) else {}
        try:
            packs = set_skill_packs(course, data.get('packs'))
        except EditError as exc:
            return _error(str(exc))
        return Response({'skill_packs': packs})


def _treed_subject_ids(course):
    return set(SyllabusNode.objects.filter(
        subject__course=course, level='topic', status='active').values_list('subject_id', flat=True))


class TaggingEstimateView(APIView):
    permission_classes = SYLLABUS

    def post(self, request, course_id):
        from .services.tagging_sweep import estimate_tagging

        course, error = _course(request, course_id)
        if error:
            return error
        subject_ids = _treed_subject_ids(course)
        estimate = (estimate_tagging(request.tenant, subject_ids) if subject_ids
                    else {'questions': 0, 'approx_tokens': 0})
        return Response({**estimate, 'subjects_with_tree': len(subject_ids),
                         'budget': budget_status(request.tenant)})


class TaggingRunStartView(APIView):
    permission_classes = SYLLABUS

    def post(self, request, course_id):
        from .services.taxonomy import current_release
        from .tasks import run_tagging_run

        course, error = _course(request, course_id)
        if error:
            return error
        if not _treed_subject_ids(course):
            return _error('Build or map a syllabus tree for this course first.')
        if current_release() is None:
            return _error('No tag vocabulary is loaded. Ask an admin to run manage.py sync_taxonomy.')
        if budget_status(request.tenant)['exhausted']:
            return _error('This academy has used its monthly AI token budget.')
        return _start(TaggingRun, course, request, run_tagging_run)


class JobDetailView(APIView):
    permission_classes = SYLLABUS

    def get(self, request, job_id):
        job = (TreeBuildJob.objects.filter(id=job_id, tenant=request.tenant).select_related('course').first()
               or TaggingRun.objects.filter(id=job_id, tenant=request.tenant).select_related('course').first())
        if job is None:
            return _not_found('Job')
        if not can_manage_course(request.user, job.course):
            return _forbidden()
        return Response(job.payload())
```

Create `backend/intelligence/syllabus_urls.py`:

```python
"""Syllabus & tagging tools, mounted at /api/v1/tenant-admin/intelligence/syllabus/."""
from django.urls import path

from . import syllabus_views as v

urlpatterns = [
    path('courses/<uuid:course_id>/tree/', v.CourseTreeView.as_view(), name='syllabus-tree'),
    path('courses/<uuid:course_id>/tree/estimate/', v.TreeEstimateView.as_view(),
         name='syllabus-tree-estimate'),
    path('courses/<uuid:course_id>/tree/build/', v.TreeBuildView.as_view(), name='syllabus-tree-build'),
    path('courses/<uuid:course_id>/tree/exam/', v.ExamMappingView.as_view(), name='syllabus-tree-exam'),
    path('courses/<uuid:course_id>/nodes/', v.NodeCreateView.as_view(), name='syllabus-node-create'),
    path('nodes/<uuid:node_id>/', v.NodeDetailView.as_view(), name='syllabus-node'),
    path('nodes/<uuid:node_id>/merge/', v.NodeMergeView.as_view(), name='syllabus-node-merge'),
    path('courses/<uuid:course_id>/skill-packs/', v.SkillPacksView.as_view(), name='syllabus-skill-packs'),
    path('courses/<uuid:course_id>/tagging/estimate/', v.TaggingEstimateView.as_view(),
         name='syllabus-tagging-estimate'),
    path('courses/<uuid:course_id>/tagging/run/', v.TaggingRunStartView.as_view(),
         name='syllabus-tagging-run'),
    path('jobs/<uuid:job_id>/', v.JobDetailView.as_view(), name='syllabus-job'),
]
```

In `backend/intelligence/admin_urls.py`, change `from django.urls import path` to `from django.urls import include, path` and append to `urlpatterns`:

```python
    path('syllabus/', include('intelligence.syllabus_urls')),
```

- [ ] **Step 4: Run tests**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_syllabus_api -v 2`
Expected: PASS. (Builds run inline because the test runner is eager.)

- [ ] **Step 5: Commit**

```bash
git add backend/intelligence/syllabus_views.py backend/intelligence/syllabus_urls.py backend/intelligence/admin_urls.py backend/intelligence/tests/test_syllabus_api.py
git commit -m "feat(intelligence): syllabus tools API for trees, builds, exam mapping, edits and tagging runs"
```

---

### Task 8: Review queue and item tags endpoints

**Files:**
- Modify: `backend/intelligence/syllabus_views.py`, `backend/intelligence/syllabus_urls.py`
- Test: `backend/intelligence/tests/test_syllabus_api.py` (add a class)

**Interfaces:**
- Produces, under `/api/v1/tenant-admin/intelligence/syllabus/`:

| Method and path | Body / query | Returns |
|---|---|---|
| `GET review/` | `?course=&topic=&reason=&page=` | `{'page', 'pages', 'total', 'results': [row_payload]}` (25 per page; needs_review only; in scope) |
| `POST review/<id>/accept/` | — | row |
| `POST review/bulk-accept/` | `{ids: [...]}` | `{'accepted': n}` (out-of-scope ids ignored) |
| `GET review/<id>/` | — | `{'row', 'choices'}` |
| `PUT review/<id>/` | edit fields | row |
| `POST review/<id>/retag/` | — | `{'queued': true}` |
| `POST review/<id>/add-to-tree/` | `{topic?}` | `{'node', 'row'}` |
| `GET items/<kind>/<id>/tags/` | kind `bank` / `item` | `{'tagging': row or null}` |

- [ ] **Step 1: Write the failing test**

Append to `backend/intelligence/tests/test_syllabus_api.py`:

```python
from intelligence.models import ItemTagging
from intelligence.services import syllabus as syllabus_service


class ReviewEndpointTests(SyllabusTestCase):
    def setUp(self):
        super().setUp()
        self.item = self.question('A block slides down…')
        self.tagging = ItemTagging.objects.create(
            tenant=self.tenant, question=self.item, primary_node=self.friction,
            thinking_level='recall', review_status='needs_review',
            review_reasons=['low_confidence'])
        other = self.question('Two sum?', subject=self.arrays, topic=self.two_sum)
        self.other_tagging = ItemTagging.objects.create(
            tenant=self.tenant, question=other, review_status='needs_review',
            review_reasons=['invalid_key'])

    def test_list_scope_filters_and_pagination(self):
        admin = self.client_for(self.admin).get(f'{BASE}/review/').json()
        self.assertEqual(admin['total'], 2)
        faculty = self.client_for(self.faculty).get(f'{BASE}/review/').json()
        self.assertEqual([r['id'] for r in faculty['results']], [str(self.tagging.id)])
        filtered = self.client_for(self.admin).get(f'{BASE}/review/', {'reason': 'invalid_key'}).json()
        self.assertEqual([r['id'] for r in filtered['results']], [str(self.other_tagging.id)])
        by_course = self.client_for(self.admin).get(f'{BASE}/review/', {'course': str(self.course.id)}).json()
        self.assertEqual(by_course['total'], 1)
        by_topic = self.client_for(self.admin).get(f'{BASE}/review/', {'topic': str(self.laws.id)}).json()
        self.assertEqual(by_topic['total'], 1)

    def test_accept_bulk_and_scope(self):
        client = self.client_for(self.faculty)
        self.assertEqual(client.post(f'{BASE}/review/{self.other_tagging.id}/accept/').status_code, 403)
        self.assertEqual(client.post(f'{BASE}/review/{self.tagging.id}/accept/').status_code, 200)
        self.tagging.review_status = 'needs_review'
        self.tagging.save()
        response = client.post(f'{BASE}/review/bulk-accept/',
                               {'ids': [str(self.tagging.id), str(self.other_tagging.id)]}, format='json')
        self.assertEqual(response.json(), {'accepted': 1})

    def test_detail_and_edit(self):
        client = self.client_for(self.faculty)
        detail = client.get(f'{BASE}/review/{self.tagging.id}/').json()
        self.assertIn('choices', detail)
        response = client.put(f'{BASE}/review/{self.tagging.id}/', {
            'primary': str(self.newton.id), 'thinking_level': 'conceptual', 'skills': [],
        }, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['source'], 'manual')
        bad = client.put(f'{BASE}/review/{self.tagging.id}/', {'primary': 'nope'}, format='json')
        self.assertEqual(bad.status_code, 400)

    def test_retag_queues(self):
        with patch('intelligence.syllabus_views._enqueue_retag') as queued:
            response = self.client_for(self.admin).post(f'{BASE}/review/{self.tagging.id}/retag/')
        self.assertEqual(response.json(), {'queued': True})
        queued.assert_called_once_with('bank', str(self.item.id))

    def test_add_to_tree(self):
        self.tagging.primary_node = None
        self.tagging.proposed_subtopic = 'Rolling friction'
        self.tagging.save()
        response = self.client_for(self.admin).post(
            f'{BASE}/review/{self.tagging.id}/add-to-tree/', {'topic': str(self.laws_node.id)}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['node']['name'], 'Rolling friction')

    def test_item_tags(self):
        client = self.client_for(self.faculty)
        data = client.get(f'{BASE}/items/bank/{self.item.id}/tags/').json()
        self.assertEqual(data['tagging']['id'], str(self.tagging.id))
        untagged = self.question('Untagged?')
        self.assertIsNone(client.get(f'{BASE}/items/bank/{untagged.id}/tags/').json()['tagging'])
```

- [ ] **Step 2: Run it to verify it fails**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_syllabus_api -v 2`
Expected: the new class FAILS (404 routes).

- [ ] **Step 3: Implement**

Append to `backend/intelligence/syllabus_views.py`:

```python
REVIEW_PAGE = 25


def _scope_q(user):
    """ItemTaggings whose item belongs to one of the user's courses."""
    from django.db.models import Q

    ids = teachable_course_ids(user)
    return Q(question__subject__course_id__in=ids) | Q(mock_item__subject__course_id__in=ids)


def _tagging(request, tagging_id):
    from .services.tag_review import course_of

    tagging = (ItemTagging.objects.filter(id=tagging_id, tenant=request.tenant)
               .select_related('question__subject__course', 'question__topic',
                               'mock_item__subject__course', 'mock_item__topic', 'primary_node__parent')
               .first())
    if tagging is None:
        return None, _not_found('Tagging')
    course = course_of(tagging)
    if course is None or not can_manage_course(request.user, course):
        return None, _forbidden()
    return tagging, None


def _enqueue_retag(kind, item_id):
    from .api import enqueue
    from .tasks import retag_item

    enqueue(retag_item, kind, item_id)


class ReviewListView(APIView):
    permission_classes = SYLLABUS

    def get(self, request):
        from django.db.models import Q

        from .services.tag_review import REVIEW_REASONS, row_payload

        rows = (ItemTagging.objects.filter(tenant=request.tenant, review_status='needs_review')
                .filter(_scope_q(request.user)))
        params = request.query_params
        course_id, topic_id = as_uuid(params.get('course')), as_uuid(params.get('topic'))
        if (params.get('course') and not course_id) or (params.get('topic') and not topic_id):
            return _error('Unknown course or topic.')
        if course_id:
            rows = rows.filter(Q(question__subject__course_id=course_id)
                               | Q(mock_item__subject__course_id=course_id))
        if topic_id:
            rows = rows.filter(Q(question__topic_id=topic_id) | Q(mock_item__topic_id=topic_id))
        if params.get('reason') in REVIEW_REASONS:
            rows = rows.filter(review_reasons__icontains=f'"{params["reason"]}"')
        rows = rows.distinct().order_by('confidence', 'created_at')
        total = rows.count()
        pages = max(1, -(-total // REVIEW_PAGE))
        try:
            page = min(pages, max(1, int(params.get('page', 1))))
        except (TypeError, ValueError):
            page = 1
        chunk = rows.select_related(
            'question__topic', 'mock_item__topic', 'primary_node__parent',
        )[(page - 1) * REVIEW_PAGE:page * REVIEW_PAGE]
        return Response({'page': page, 'pages': pages, 'total': total,
                         'results': [row_payload(tagging) for tagging in chunk]})


class ReviewAcceptView(APIView):
    permission_classes = SYLLABUS

    def post(self, request, tagging_id):
        from .services.tag_review import accept, row_payload

        tagging, error = _tagging(request, tagging_id)
        if error:
            return error
        return Response(row_payload(accept(tagging)))


class ReviewBulkAcceptView(APIView):
    permission_classes = SYLLABUS

    def post(self, request):
        from .services.tag_review import bulk_accept

        ids = request.data.get('ids') if isinstance(request.data, dict) else None
        if not isinstance(ids, list) or not ids:
            return _error('Pick at least one row.')
        clean = [value for value in (as_uuid(raw) for raw in ids) if value][:REVIEW_PAGE * 4]
        rows = ItemTagging.objects.filter(tenant=request.tenant, id__in=clean).filter(_scope_q(request.user))
        return Response({'accepted': bulk_accept(rows)})


class ReviewDetailView(APIView):
    permission_classes = SYLLABUS

    def get(self, request, tagging_id):
        from .services.tag_review import edit_choices, row_payload, subject_of

        tagging, error = _tagging(request, tagging_id)
        if error:
            return error
        subject = subject_of(tagging)
        return Response({'row': row_payload(tagging),
                         'choices': edit_choices(subject) if subject else None})

    def put(self, request, tagging_id):
        from .services.tag_review import ReviewError, row_payload, save_manual

        tagging, error = _tagging(request, tagging_id)
        if error:
            return error
        try:
            save_manual(tagging, request.data)
        except ReviewError as exc:
            return _error(str(exc))
        tagging.refresh_from_db()
        return Response(row_payload(tagging))


class ReviewRetagView(APIView):
    permission_classes = SYLLABUS

    def post(self, request, tagging_id):
        from .services.tag_review import mark_for_retag

        tagging, error = _tagging(request, tagging_id)
        if error:
            return error
        if budget_status(request.tenant)['exhausted']:
            return _error('This academy has used its monthly AI token budget.')
        item = mark_for_retag(tagging)
        try:
            _enqueue_retag('bank' if tagging.question_id else 'item', str(item.id))
        except Exception:  # noqa: BLE001 — still stale: the weekly sweep picks it up
            return Response({'queued': False, 'reason': 'queue_unavailable'})
        return Response({'queued': True})


class ReviewAddToTreeView(APIView):
    permission_classes = SYLLABUS

    def post(self, request, tagging_id):
        from .services.tag_review import ReviewError, add_to_tree, row_payload

        tagging, error = _tagging(request, tagging_id)
        if error:
            return error
        topic = None
        topic_id = as_uuid(request.data.get('topic')) if isinstance(request.data, dict) else None
        if topic_id:
            topic = SyllabusNode.objects.filter(id=topic_id, tenant=request.tenant, level='topic').first()
            if topic is None:
                return _error('That topic is not in the tree.')
        try:
            node = add_to_tree(tagging, topic)
        except ReviewError as exc:
            return _error(str(exc))
        tagging.refresh_from_db()
        return Response({'node': _node_out(node), 'row': row_payload(tagging)})


class ItemTagsView(APIView):
    permission_classes = SYLLABUS

    def get(self, request, kind, item_id):
        from quiz.models import MockTestItem, Question

        from .services.tag_review import course_of, row_payload
        from .services.tagging_sweep import _mock_item_subject

        model = {'bank': Question, 'item': MockTestItem}.get(kind)
        item = model.objects.filter(id=item_id, tenant=request.tenant).first() if model else None
        if item is None:
            return _not_found('Question')
        subject = item.subject if kind == 'bank' else _mock_item_subject(item)
        if subject is None or not can_manage_course(request.user, subject.course):
            return _forbidden()
        tagging = getattr(item, 'tagging', None)
        return Response({'tagging': row_payload(tagging) if tagging else None})
```

`_tagging` scope uses `course_of(tagging)`; leave the import inside the function as written.

Append to `syllabus_urls.py` `urlpatterns`:

```python
    path('review/', v.ReviewListView.as_view(), name='syllabus-review'),
    path('review/bulk-accept/', v.ReviewBulkAcceptView.as_view(), name='syllabus-review-bulk-accept'),
    path('review/<uuid:tagging_id>/', v.ReviewDetailView.as_view(), name='syllabus-review-detail'),
    path('review/<uuid:tagging_id>/accept/', v.ReviewAcceptView.as_view(), name='syllabus-review-accept'),
    path('review/<uuid:tagging_id>/retag/', v.ReviewRetagView.as_view(), name='syllabus-review-retag'),
    path('review/<uuid:tagging_id>/add-to-tree/', v.ReviewAddToTreeView.as_view(),
         name='syllabus-review-add-to-tree'),
    path('items/<str:kind>/<uuid:item_id>/tags/', v.ItemTagsView.as_view(), name='syllabus-item-tags'),
```

(`review/bulk-accept/` must come before `review/<uuid:tagging_id>/`; the UUID converter would not match it anyway, but keep the order.)

- [ ] **Step 4: Run tests**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_syllabus_api intelligence.tests.test_tag_review -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/intelligence/syllabus_views.py backend/intelligence/syllabus_urls.py backend/intelligence/tests/test_syllabus_api.py
git commit -m "feat(intelligence): tag review queue and item tags endpoints"
```

---

### Task 9: Opt-out regression for Part B

**Files:**
- Test: `backend/intelligence/tests/test_syllabus_api.py` (add a class)

- [ ] **Step 1: Write the test**

Append:

```python
class OptOutTests(SyllabusTestCase):
    """With every learning-layer switch off: no Part B endpoint is reachable
    and nothing is queued."""

    features = {}

    def test_every_endpoint_is_403_and_nothing_is_queued(self):
        node = self.friction
        urls = [
            ('get', f'{BASE}/courses/{self.course.id}/tree/'),
            ('post', f'{BASE}/courses/{self.course.id}/tree/estimate/'),
            ('post', f'{BASE}/courses/{self.custom.id}/tree/build/'),
            ('post', f'{BASE}/courses/{self.course.id}/tree/exam/'),
            ('post', f'{BASE}/courses/{self.course.id}/nodes/'),
            ('patch', f'{BASE}/nodes/{node.id}/'),
            ('post', f'{BASE}/nodes/{node.id}/merge/'),
            ('patch', f'{BASE}/courses/{self.course.id}/skill-packs/'),
            ('post', f'{BASE}/courses/{self.course.id}/tagging/estimate/'),
            ('post', f'{BASE}/courses/{self.course.id}/tagging/run/'),
            ('get', f'{BASE}/review/'),
            ('post', f'{BASE}/review/bulk-accept/'),
        ]
        client = self.client_for(self.admin)
        with patch('intelligence.api.enqueue') as enqueue:
            for method, url in urls:
                self.assertEqual(getattr(client, method)(url, {}, format='json').status_code, 403, url)
        enqueue.assert_not_called()
        self.assertFalse(TreeBuildJob.objects.exists())
        self.assertFalse(TaggingRun.objects.exists())
```

- [ ] **Step 2: Run the backend suite**

Run: `venv/Scripts/python.exe manage.py test intelligence core quiz exams -v 1`
Expected: all PASS, including `test_gate` and Part A's tests.

- [ ] **Step 3: Commit**

```bash
git add backend/intelligence/tests/test_syllabus_api.py
git commit -m "test(intelligence): Part B endpoints are unreachable with the layer off"
```

---

### Task 10: Frontend — service and the course "Syllabus" view

**Files:**
- Create: `frontend/exam-frontend/src/services/syllabusService.js`
- Create: `frontend/exam-frontend/src/components/syllabus/SyllabusPanel.jsx`
- Modify: `frontend/exam-frontend/src/pages/CourseManager.jsx`

**Interfaces:**
- Produces: `syllabusService.*` (one function per endpoint); `<SyllabusPanel courseId />`.
- Consumes: Task 11's `<TreeEditor>` and Task 12's `<TagReviewList>`. Build this task with a placeholder `<div />` where they mount, then replace it in those tasks; or implement Tasks 10–12 before building.

- [ ] **Step 1: Service**

Create `frontend/exam-frontend/src/services/syllabusService.js`:

```js
import api from './api'

const BASE = '/tenant-admin/intelligence/syllabus'
const data = (promise) => promise.then((response) => response.data)

export const syllabusService = {
  getTree: (courseId) => data(api.get(`${BASE}/courses/${courseId}/tree/`)),
  estimateBuild: (courseId, body = {}) => data(api.post(`${BASE}/courses/${courseId}/tree/estimate/`, body)),
  startBuild: (courseId, body = {}) => data(api.post(`${BASE}/courses/${courseId}/tree/build/`, body)),
  mapExam: (courseId, body) => data(api.post(`${BASE}/courses/${courseId}/tree/exam/`, body)),
  addNode: (courseId, body) => data(api.post(`${BASE}/courses/${courseId}/nodes/`, body)),
  updateNode: (nodeId, body) => data(api.patch(`${BASE}/nodes/${nodeId}/`, body)),
  mergeNode: (nodeId, into) => data(api.post(`${BASE}/nodes/${nodeId}/merge/`, { into })),
  setSkillPacks: (courseId, packs) => data(api.patch(`${BASE}/courses/${courseId}/skill-packs/`, { packs })),
  estimateTagging: (courseId) => data(api.post(`${BASE}/courses/${courseId}/tagging/estimate/`, {})),
  startTagging: (courseId) => data(api.post(`${BASE}/courses/${courseId}/tagging/run/`, {})),
  getJob: (jobId) => data(api.get(`${BASE}/jobs/${jobId}/`)),
  getReview: (params) => data(api.get(`${BASE}/review/`, { params })),
  getReviewRow: (id) => data(api.get(`${BASE}/review/${id}/`)),
  acceptReview: (id) => data(api.post(`${BASE}/review/${id}/accept/`)),
  bulkAccept: (ids) => data(api.post(`${BASE}/review/bulk-accept/`, { ids })),
  saveTags: (id, body) => data(api.put(`${BASE}/review/${id}/`, body)),
  retag: (id) => data(api.post(`${BASE}/review/${id}/retag/`)),
  addToTree: (id, topic) => data(api.post(`${BASE}/review/${id}/add-to-tree/`, topic ? { topic } : {})),
  getItemTags: (kind, id) => data(api.get(`${BASE}/items/${kind}/${id}/tags/`)),
}

// "Thing went wrong" text from a DRF error response.
export const errorText = (error) => error?.response?.data?.error || 'Something went wrong — try again.'
```

- [ ] **Step 2: The panel**

Create `frontend/exam-frontend/src/components/syllabus/SyllabusPanel.jsx`:

```jsx
import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { GitBranch, Loader2, Map, Tags } from 'lucide-react'
import { syllabusService, errorText } from '../../services/syllabusService'
import Loading from '../common/Loading'
import TreeEditor from './TreeEditor'
import TagReviewList from './TagReviewList'

const fmt = (n) => (n == null ? '—' : Number(n).toLocaleString())
const STATUS_STYLE = {
  queued: 'text-surface-500', running: 'text-primary-500', done: 'text-success-600', failed: 'text-error-600',
}

function Card({ icon: Icon, title, children }) {
  return (
    <div className="p-5 rounded-2xl bg-white dark:bg-surface-800 border border-surface-200 dark:border-surface-700">
      <h3 className="font-semibold mb-3 flex items-center gap-2"><Icon size={16} className="text-primary-500" /> {title}</h3>
      {children}
    </div>
  )
}

function BudgetLine({ budget }) {
  if (!budget || budget.monthly_budget == null) return <p className="text-xs text-surface-400">No monthly AI budget set.</p>
  return (
    <p className={`text-xs ${budget.exhausted ? 'text-error-600' : 'text-surface-400'}`}>
      Monthly budget: {fmt(budget.remaining)} of {fmt(budget.monthly_budget)} tokens left
    </p>
  )
}

// Poll one job until it finishes, then refresh the tree.
function useJobPoll(jobId, onDone) {
  const { data } = useQuery({
    queryKey: ['syllabusJob', jobId],
    queryFn: () => syllabusService.getJob(jobId),
    enabled: !!jobId,
    refetchInterval: (query) => (['queued', 'running'].includes(query.state.data?.status) ? 3000 : false),
  })
  useEffect(() => {
    if (data && ['done', 'failed'].includes(data.status)) onDone(data)
  }, [data?.status]) // eslint-disable-line react-hooks/exhaustive-deps
  return data
}

function BuildCard({ courseId, tree }) {
  const queryClient = useQueryClient()
  const [jobId, setJobId] = useState(null)
  const estimate = useQuery({
    queryKey: ['syllabusBuildEstimate', courseId],
    queryFn: () => syllabusService.estimateBuild(courseId),
  })
  const start = useMutation({
    mutationFn: () => syllabusService.startBuild(courseId),
    onSuccess: (job) => setJobId(job.id),
    onError: (error) => toast.error(errorText(error)),
  })
  const job = useJobPoll(jobId, (finished) => {
    queryClient.invalidateQueries({ queryKey: ['syllabusTree', courseId] })
    queryClient.invalidateQueries({ queryKey: ['syllabusBuildEstimate', courseId] })
    if (finished.status === 'failed') toast.error(finished.error || 'Build failed')
    else toast.success('Syllabus tree built')
  })
  const running = start.isPending || ['queued', 'running'].includes(job?.status)
  const e = estimate.data

  return (
    <Card icon={GitBranch} title="Build syllabus tree">
      <p className="text-sm text-surface-500 mb-3">
        Groups this course's topics, adds existing concepts as subtopics, and suggests missing ones.
        Suggestions show a “suggested” badge until you accept or edit them.
      </p>
      {e && (
        <p className="text-sm mb-1">
          About {fmt(e.llm_calls)} AI calls (~{fmt(e.approx_tokens)} tokens)
        </p>
      )}
      <BudgetLine budget={e?.budget} />
      <button
        type="button"
        onClick={() => start.mutate()}
        disabled={running || e?.budget?.exhausted || e?.llm_calls === 0}
        className="btn-primary mt-3 text-sm"
      >
        {running ? <><Loader2 size={14} className="animate-spin" /> Building…</> : (tree.kind === 'none' ? 'Build tree' : 'Update tree')}
      </button>
      {e?.llm_calls === 0 && <p className="text-xs text-surface-400 mt-2">Nothing new to build.</p>}
    </Card>
  )
}

function ExamCard({ courseId, tree }) {
  const queryClient = useQueryClient()
  const [exam, setExam] = useState(tree.exam_tree || tree.exam_trees[0]?.key || '')
  const [map, setMap] = useState(() => {
    const initial = {}
    Object.entries(tree.subject_map || {}).forEach(([subjectId, key]) => { initial[subjectId] = key })
    return initial
  })
  const option = tree.exam_trees.find((t) => t.key === exam)
  const save = useMutation({
    mutationFn: () => syllabusService.mapExam(courseId, {
      exam, subjects: Object.fromEntries(Object.entries(map).filter(([, key]) => key)),
    }),
    onSuccess: () => {
      toast.success('Exam syllabus applied')
      queryClient.invalidateQueries({ queryKey: ['syllabusTree', courseId] })
    },
    onError: (error) => toast.error(errorText(error)),
  })
  if (!tree.exam_trees.length) return null

  return (
    <Card icon={Map} title="Use an exam syllabus">
      <p className="text-sm text-surface-500 mb-3">Pick a shipped exam tree and match each subject. No AI calls.</p>
      <select value={exam} onChange={(e) => setExam(e.target.value)} className="input text-sm mb-3">
        {tree.exam_trees.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
      </select>
      <div className="space-y-2">
        {tree.subjects.map((subject) => (
          <label key={subject.id} className="flex items-center justify-between gap-3 text-sm">
            <span>{subject.name}</span>
            <select
              value={map[subject.id] || ''}
              onChange={(e) => setMap({ ...map, [subject.id]: e.target.value })}
              className="input py-1 text-sm max-w-[12rem]"
            >
              <option value="">— not mapped —</option>
              {option?.subjects.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
            </select>
          </label>
        ))}
      </div>
      <button type="button" onClick={() => save.mutate()} disabled={save.isPending} className="btn-primary mt-3 text-sm">
        {save.isPending ? 'Applying…' : 'Apply exam syllabus'}
      </button>
    </Card>
  )
}

function TagCard({ courseId }) {
  const queryClient = useQueryClient()
  const [runId, setRunId] = useState(null)
  const estimate = useQuery({
    queryKey: ['syllabusTagEstimate', courseId],
    queryFn: () => syllabusService.estimateTagging(courseId),
  })
  const start = useMutation({
    mutationFn: () => syllabusService.startTagging(courseId),
    onSuccess: (run) => setRunId(run.id),
    onError: (error) => toast.error(errorText(error)),
  })
  const run = useJobPoll(runId, (finished) => {
    queryClient.invalidateQueries({ queryKey: ['syllabusTree', courseId] })
    queryClient.invalidateQueries({ queryKey: ['syllabusTagEstimate', courseId] })
    queryClient.invalidateQueries({ queryKey: ['tagReview'] })
    if (finished.status === 'failed') toast.error(finished.error || 'Tagging failed')
  })
  const running = start.isPending || ['queued', 'running'].includes(run?.status)
  const e = estimate.data

  return (
    <Card icon={Tags} title="Tag questions">
      {e?.subjects_with_tree === 0 ? (
        <p className="text-sm text-surface-500">Build or map a syllabus tree first.</p>
      ) : (
        <>
          <p className="text-sm mb-1">About {fmt(e?.questions)} questions to tag (~{fmt(e?.approx_tokens)} tokens; up to 500 per run)</p>
          <BudgetLine budget={e?.budget} />
          <button
            type="button"
            onClick={() => start.mutate()}
            disabled={running || !e?.questions || e?.budget?.exhausted}
            className="btn-primary mt-3 text-sm"
          >
            {running ? <><Loader2 size={14} className="animate-spin" /> Tagging…</> : 'Tag questions'}
          </button>
          {run?.status === 'done' && (
            <p className="text-sm mt-2">
              Tagged {run.summary.tagged ?? 0} · needs review {run.summary.needs_review ?? 0} · failed {run.summary.failed ?? 0}
            </p>
          )}
        </>
      )}
    </Card>
  )
}

function JobHistory({ jobs }) {
  if (!jobs.length) return null
  return (
    <div className="p-5 rounded-2xl bg-white dark:bg-surface-800 border border-surface-200 dark:border-surface-700">
      <h3 className="font-semibold mb-3">Recent runs</h3>
      <ul className="divide-y divide-surface-100 dark:divide-surface-700/50 text-sm">
        {jobs.map((job) => (
          <li key={job.id} className="py-2 flex flex-wrap items-center justify-between gap-2">
            <span>
              {job.kind === 'tree_build' ? 'Tree build' : 'Tagging'}
              <span className={`ml-2 ${STATUS_STYLE[job.status]}`}>{job.status}</span>
              {job.error && <span className="ml-2 text-xs text-error-600">{job.error}</span>}
            </span>
            <span className="text-xs text-surface-400">
              {job.started_by && `${job.started_by} · `}
              {fmt(job.tokens)} tokens · {new Date(job.created_at).toLocaleString()}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** Course editor "Syllabus" view (syllabus & tagging tools). */
export default function SyllabusPanel({ courseId }) {
  const { data: tree, isLoading } = useQuery({
    queryKey: ['syllabusTree', courseId],
    queryFn: () => syllabusService.getTree(courseId),
  })
  if (isLoading) return <Loading />
  if (!tree) return null

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {tree.kind !== 'exam' && <BuildCard courseId={courseId} tree={tree} />}
        {tree.kind !== 'custom' && <ExamCard courseId={courseId} tree={tree} />}
        <TagCard courseId={courseId} />
      </div>
      <JobHistory jobs={tree.jobs} />
      <TreeEditor courseId={courseId} tree={tree} />
      <div className="p-5 rounded-2xl bg-white dark:bg-surface-800 border border-surface-200 dark:border-surface-700">
        <h3 className="font-semibold mb-3">Questions needing review</h3>
        <TagReviewList courseId={courseId} />
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Mount it in CourseManager**

In `frontend/exam-frontend/src/pages/CourseManager.jsx`:
- imports: `import { useTenantStore } from '../context/tenantStore'`, `import SyllabusPanel from '../components/syllabus/SyllabusPanel'`, and add `Network` to the `lucide-react` import.
- in `CourseManager`, after `const [thumbnailOpen, …]`:

```jsx
    const syllabusOn = useTenantStore((s) => s.tenant?.features?.syllabus_tools === true)
    const [view, setView] = useState('content') // content | syllabus
```

- in the header button group, before the "View as student" button:

```jsx
                    {course && syllabusOn && (
                        <button
                            onClick={() => setView(view === 'syllabus' ? 'content' : 'syllabus')}
                            className={`btn-secondary text-xs px-3 py-1.5 ${view === 'syllabus' ? 'ring-2 ring-primary-400' : ''}`}
                        >
                            <Network className="w-3.5 h-3.5" /> {view === 'syllabus' ? 'Back to content' : 'Syllabus'}
                        </button>
                    )}
```

- wrap the `{/* Body: navigator + panel */}` grid so it renders only when `view === 'content'`, and add after it:

```jsx
            {view === 'syllabus' && course && <SyllabusPanel courseId={courseId} />}
```

- [ ] **Step 4: Build** (after Tasks 11–12 exist, or with placeholders)

Run (from `frontend/exam-frontend/`): `npx vite build`
Expected: succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/exam-frontend/src/services/syllabusService.js frontend/exam-frontend/src/components/syllabus/SyllabusPanel.jsx frontend/exam-frontend/src/pages/CourseManager.jsx
git commit -m "feat(frontend): course Syllabus view with build, exam mapping, tagging and run history"
```

---

### Task 11: Frontend — tree editor

**Files:**
- Create: `frontend/exam-frontend/src/components/syllabus/TreeEditor.jsx`

**Interfaces:**
- Produces: `<TreeEditor courseId tree />` (tree = `getTree` payload).
- Operations map 1:1 to Task 7 endpoints: add subtopic / sub-subject, rename, archive, accept suggestion, move topic, weightage, merge, skill packs.

- [ ] **Step 1: Write the editor**

Create `frontend/exam-frontend/src/components/syllabus/TreeEditor.jsx`:

```jsx
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { Archive, Check, ChevronDown, ChevronRight, GitMerge, Pencil, Plus } from 'lucide-react'
import { syllabusService, errorText } from '../../services/syllabusService'

const LEVEL_TEXT = { sub_subject: 'Sub-subject', topic: 'Topic', subtopic: 'Subtopic' }

function useTreeMutation(courseId, fn, success) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['syllabusTree', courseId] })
      result?.warnings?.forEach((warning) => toast(warning, { icon: '⚖️' }))
      if (success) toast.success(success)
    },
    onError: (error) => toast.error(errorText(error)),
  })
}

function NodeRow({ node, subject, courseId, depth, siblingsForMerge, subSubjects }) {
  const [open, setOpen] = useState(depth < 1)
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(node.name)
  const [adding, setAdding] = useState(false)
  const [newName, setNewName] = useState('')
  const update = useTreeMutation(courseId, (body) => syllabusService.updateNode(node.id, body))
  const add = useTreeMutation(courseId, (body) => syllabusService.addNode(courseId, body), 'Subtopic added')
  const merge = useTreeMutation(courseId, (into) => syllabusService.mergeNode(node.id, into), 'Merged')
  const children = node.children || []
  const isTopic = node.level === 'topic'

  return (
    <li>
      <div className="flex flex-wrap items-center gap-2 py-1.5" style={{ paddingLeft: depth * 16 }}>
        {children.length > 0 || isTopic ? (
          <button type="button" onClick={() => setOpen(!open)} className="text-surface-400" aria-label="Toggle">
            {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </button>
        ) : <span className="w-3.5" />}
        <span className="text-[10px] uppercase tracking-wide text-surface-400 w-20 shrink-0">{LEVEL_TEXT[node.level]}</span>

        {editing ? (
          <form
            className="flex items-center gap-1"
            onSubmit={(e) => { e.preventDefault(); update.mutate({ name }); setEditing(false) }}
          >
            <input value={name} onChange={(e) => setName(e.target.value)} className="input py-1 text-sm" autoFocus />
            <button type="submit" className="p-1 text-success-600"><Check size={14} /></button>
          </form>
        ) : (
          <span className="text-sm font-medium">{node.name}</span>
        )}
        {node.status === 'proposed' && (
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-primary-50 dark:bg-primary-900/30 text-primary-600">suggested</span>
        )}

        <span className="ml-auto flex items-center gap-1">
          <input
            type="number" min="0" max="1" step="0.05"
            defaultValue={node.weightage || ''}
            placeholder="weight"
            title="Weightage within its parent (0–1)"
            onBlur={(e) => {
              const value = e.target.value === '' ? 0 : Number(e.target.value)
              if (value !== node.weightage) update.mutate({ weightage: value })
            }}
            className="input py-0.5 px-2 text-xs w-20"
          />
          {node.status === 'proposed' && (
            <button type="button" title="Accept suggestion" onClick={() => update.mutate({ status: 'active' })} className="p-1 text-success-600"><Check size={14} /></button>
          )}
          {!isTopic && (
            <button type="button" title="Rename" onClick={() => setEditing(true)} className="p-1 text-surface-400 hover:text-primary-500"><Pencil size={14} /></button>
          )}
          {isTopic && subSubjects.length > 1 && (
            <select
              value={node.parent || ''}
              onChange={(e) => update.mutate({ parent: e.target.value })}
              title="Move to sub-subject"
              className="input py-0.5 text-xs max-w-[10rem]"
            >
              <option value="" disabled>Move to…</option>
              {subSubjects.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          )}
          {node.level === 'subtopic' && siblingsForMerge.length > 0 && (
            <select
              value=""
              onChange={(e) => {
                const target = siblingsForMerge.find((s) => s.id === e.target.value)
                if (target && window.confirm(`Merge "${node.name}" into "${target.name}"? Questions and history move to "${target.name}".`)) {
                  merge.mutate(target.id)
                }
              }}
              title="Merge into…"
              className="input py-0.5 text-xs max-w-[10rem]"
            >
              <option value="">Merge into…</option>
              {siblingsForMerge.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          )}
          {!isTopic && (
            <button
              type="button"
              title="Archive"
              onClick={() => window.confirm(`Archive "${node.name}"?`) && update.mutate({ status: 'archived' })}
              className="p-1 text-surface-400 hover:text-error-500"
            >
              <Archive size={14} />
            </button>
          )}
          {isTopic && (
            <button type="button" title="Add subtopic" onClick={() => { setOpen(true); setAdding(true) }} className="p-1 text-surface-400 hover:text-primary-500"><Plus size={14} /></button>
          )}
        </span>
      </div>

      {open && (
        <ul>
          {children.map((child) => (
            <NodeRow
              key={child.id}
              node={{ ...child, parent: node.id }}
              subject={subject}
              courseId={courseId}
              depth={depth + 1}
              subSubjects={subSubjects}
              siblingsForMerge={child.level === 'subtopic'
                ? allSubtopics(subject).filter((s) => s.id !== child.id)
                : []}
            />
          ))}
          {adding && (
            <li style={{ paddingLeft: (depth + 1) * 16 }} className="py-1.5">
              <form
                className="flex items-center gap-2"
                onSubmit={(e) => {
                  e.preventDefault()
                  add.mutate({ subject: subject.id, level: 'subtopic', parent: node.id, name: newName })
                  setNewName('')
                  setAdding(false)
                }}
              >
                <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="New subtopic" className="input py-1 text-sm" autoFocus />
                <button type="submit" className="btn-primary text-xs px-3 py-1">Add</button>
                <button type="button" onClick={() => setAdding(false)} className="text-xs text-surface-500">Cancel</button>
              </form>
            </li>
          )}
        </ul>
      )}
    </li>
  )
}

function allSubtopics(subject) {
  const out = []
  const walk = (nodes) => nodes.forEach((n) => {
    if (n.level === 'subtopic') out.push({ id: n.id, name: n.name })
    walk(n.children || [])
  })
  walk(subject.nodes)
  return out
}

function SubjectTree({ subject, courseId, packsAvailable }) {
  const [newGroup, setNewGroup] = useState('')
  const addGroup = useTreeMutation(courseId, (body) => syllabusService.addNode(courseId, body), 'Sub-subject added')
  const savePacks = useTreeMutation(courseId, (keys) => syllabusService.setSkillPacks(courseId, { [subject.id]: keys }), 'Skill packs saved')
  const subSubjects = subject.nodes.filter((n) => n.level === 'sub_subject').map((n) => ({ id: n.id, name: n.name }))

  return (
    <div className="p-5 rounded-2xl bg-white dark:bg-surface-800 border border-surface-200 dark:border-surface-700">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-2">
        <h3 className="font-semibold">{subject.name}</h3>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="text-surface-500">Skill packs:</span>
          {packsAvailable.map((pack) => {
            const on = subject.packs.includes(pack.key)
            return (
              <button
                key={pack.key}
                type="button"
                onClick={() => savePacks.mutate(on ? subject.packs.filter((k) => k !== pack.key) : [...subject.packs, pack.key])}
                className={`px-2 py-0.5 rounded-full border ${on ? 'bg-primary-500 border-primary-500 text-white' : 'border-surface-300'}`}
              >
                {pack.label}
              </button>
            )
          })}
        </div>
      </div>
      {!subject.has_tree ? (
        <p className="text-sm text-surface-400">No tree yet.</p>
      ) : (
        <ul>
          {subject.nodes.map((node) => (
            <NodeRow key={node.id} node={node} subject={subject} courseId={courseId} depth={0} subSubjects={subSubjects} siblingsForMerge={[]} />
          ))}
        </ul>
      )}
      {subject.has_tree && (
        <form
          className="flex items-center gap-2 mt-3"
          onSubmit={(e) => { e.preventDefault(); addGroup.mutate({ subject: subject.id, level: 'sub_subject', name: newGroup }); setNewGroup('') }}
        >
          <input value={newGroup} onChange={(e) => setNewGroup(e.target.value)} placeholder="New sub-subject" className="input py-1 text-sm" />
          <button type="submit" disabled={!newGroup.trim()} className="btn-secondary text-xs px-3 py-1">Add</button>
        </form>
      )}
    </div>
  )
}

/** Collapsible syllabus tree per subject, with every editor operation. */
export default function TreeEditor({ courseId, tree }) {
  return (
    <div className="space-y-4">
      <p className="text-xs text-surface-500">
        Course topics come from the course and can't be renamed here. Editing a suggested subtopic accepts it.
        Adding, renaming, archiving or merging re-tags the affected questions on the next “Tag questions” run.
      </p>
      {tree.subjects.map((subject) => (
        <SubjectTree key={subject.id} subject={subject} courseId={courseId} packsAvailable={tree.skill_packs_available} />
      ))}
    </div>
  )
}
```

- [ ] **Step 2: Build**

Run (from `frontend/exam-frontend/`): `npx vite build`
Expected: succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/exam-frontend/src/components/syllabus/TreeEditor.jsx
git commit -m "feat(frontend): syllabus tree editor"
```

---

### Task 12: Frontend — tag review queue, edit form, Tags panel, menu

**Files:**
- Create: `frontend/exam-frontend/src/components/syllabus/TagReviewList.jsx`
- Create: `frontend/exam-frontend/src/components/syllabus/TagEditForm.jsx`
- Create: `frontend/exam-frontend/src/components/syllabus/ItemTagsPanel.jsx`
- Create: `frontend/exam-frontend/src/pages/TagReview.jsx`
- Modify: `frontend/exam-frontend/src/App.jsx`, `frontend/exam-frontend/src/pages/InsightsHome.jsx`, `frontend/exam-frontend/src/components/layout/AdminSidebar.jsx`
- Modify: `frontend/exam-frontend/src/components/admin/builderShared.jsx` (`QuestionModal`), `frontend/exam-frontend/src/pages/MockTestBuilder.jsx` (`ItemEditor`)

**Interfaces:**
- Produces: `<TagReviewList courseId? />`, `<TagEditForm taggingId onClose onSaved />`, `<ItemTagsPanel kind id />`, route `/admin/insights/tag-review`.

- [ ] **Step 1: Edit form**

Create `frontend/exam-frontend/src/components/syllabus/TagEditForm.jsx`:

```jsx
import { useEffect, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { X } from 'lucide-react'
import { syllabusService, errorText } from '../../services/syllabusService'

/** Edit one item's tags. Saving locks them: the tagger never overwrites manual tags. */
export default function TagEditForm({ taggingId, onClose, onSaved }) {
  const { data } = useQuery({
    queryKey: ['tagReviewRow', taggingId],
    queryFn: () => syllabusService.getReviewRow(taggingId),
  })
  const [form, setForm] = useState(null)
  useEffect(() => {
    if (!data) return
    const row = data.row
    setForm({
      primary: row.primary?.id || '',
      secondary: row.secondary.map((n) => n.id),
      thinking_level: row.thinking_level,
      skills: row.skills.map(({ key, role, reason }) => ({ key, role, reason })),
      special_format: row.special_format,
      difficulty_prior: row.difficulty_prior,
      est_solve_seconds: row.est_solve_seconds ?? '',
    })
  }, [data])
  const save = useMutation({
    mutationFn: () => syllabusService.saveTags(taggingId, form),
    onSuccess: (row) => { toast.success('Tags saved'); onSaved?.(row); onClose() },
    onError: (error) => toast.error(errorText(error)),
  })

  if (!data || !form) return null
  const { choices } = data
  if (!choices) {
    return <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4"><div className="card p-6">This question has no subject tree.<button onClick={onClose} className="btn-secondary ml-3">Close</button></div></div>
  }
  const set = (patch) => setForm({ ...form, ...patch })
  const toggleSkill = (key) => {
    const has = form.skills.find((s) => s.key === key)
    set({ skills: has ? form.skills.filter((s) => s.key !== key) : [...form.skills, { key, role: 'supporting', reason: '' }] })
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4" role="dialog" aria-modal="true">
      <div className="card w-full max-w-2xl max-h-[90vh] overflow-y-auto p-6 space-y-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="font-semibold">Edit tags</h3>
            <p className="text-sm text-surface-500 mt-1 line-clamp-3">{data.row.question_text}</p>
          </div>
          <button onClick={onClose} aria-label="Close"><X size={18} /></button>
        </div>

        <label className="block text-sm">
          <span className="font-medium">Primary subtopic</span>
          <select value={form.primary} onChange={(e) => set({ primary: e.target.value })} className="input mt-1">
            <option value="">— pick —</option>
            {choices.topics.map((topic) => (
              <optgroup key={topic.id} label={topic.name}>
                {topic.subtopics.map((s) => <option key={s.id} value={s.id}>{s.name}{s.status === 'proposed' ? ' (suggested)' : ''}</option>)}
              </optgroup>
            ))}
          </select>
        </label>

        <label className="block text-sm">
          <span className="font-medium">Secondary subtopics</span>
          <select
            multiple
            value={form.secondary}
            onChange={(e) => set({ secondary: [...e.target.selectedOptions].map((o) => o.value) })}
            className="input mt-1 h-28"
          >
            {choices.topics.map((topic) => (
              <optgroup key={topic.id} label={topic.name}>
                {topic.subtopics.filter((s) => s.id !== form.primary).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </optgroup>
            ))}
          </select>
        </label>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <label className="block text-sm">
            <span className="font-medium">Thinking level</span>
            <select value={form.thinking_level} onChange={(e) => set({ thinking_level: e.target.value })} className="input mt-1">
              <option value="">— pick —</option>
              {choices.thinking_levels.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
            </select>
          </label>
          <label className="block text-sm">
            <span className="font-medium">Difficulty</span>
            <select value={form.difficulty_prior} onChange={(e) => set({ difficulty_prior: e.target.value })} className="input mt-1">
              <option value="">—</option>
              {['easy', 'medium', 'hard'].map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
          </label>
          <label className="block text-sm">
            <span className="font-medium">Solve time (s)</span>
            <input type="number" min="10" max="1800" value={form.est_solve_seconds} onChange={(e) => set({ est_solve_seconds: e.target.value })} className="input mt-1" />
          </label>
        </div>

        <label className="block text-sm">
          <span className="font-medium">Special format</span>
          <select value={form.special_format} onChange={(e) => set({ special_format: e.target.value })} className="input mt-1">
            <option value="">None</option>
            {choices.special_formats.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
          </select>
        </label>

        <div className="text-sm">
          <span className="font-medium">Skills</span>
          <div className="mt-2 space-y-1.5">
            {choices.skills.map((skill) => {
              const chosen = form.skills.find((s) => s.key === skill.key)
              return (
                <div key={skill.key} className="flex flex-wrap items-center gap-2">
                  <label className="flex items-center gap-2 min-w-[12rem]">
                    <input type="checkbox" checked={!!chosen} onChange={() => toggleSkill(skill.key)} /> {skill.label}
                  </label>
                  {chosen && (
                    <>
                      <select
                        value={chosen.role}
                        onChange={(e) => set({ skills: form.skills.map((s) => (s.key === skill.key ? { ...s, role: e.target.value } : s)) })}
                        className="input py-0.5 text-xs w-28"
                      >
                        <option value="core">core</option>
                        <option value="supporting">supporting</option>
                      </select>
                      <input
                        value={chosen.reason}
                        placeholder="why (optional)"
                        onChange={(e) => set({ skills: form.skills.map((s) => (s.key === skill.key ? { ...s, reason: e.target.value } : s)) })}
                        className="input py-0.5 text-xs flex-1 min-w-[8rem]"
                      />
                    </>
                  )}
                </div>
              )
            })}
          </div>
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <button onClick={onClose} className="btn-secondary text-sm">Cancel</button>
          <button onClick={() => save.mutate()} disabled={save.isPending || !form.primary} className="btn-primary text-sm">
            {save.isPending ? 'Saving…' : 'Save (locks these tags)'}
          </button>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Review list**

Create `frontend/exam-frontend/src/components/syllabus/TagReviewList.jsx`:

```jsx
import { useState } from 'react'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { syllabusService, errorText } from '../../services/syllabusService'
import Loading from '../common/Loading'
import TagEditForm from './TagEditForm'

const REASON_TEXT = {
  low_confidence: 'Low confidence',
  invalid_key: 'No valid subtopic',
  proposed_subtopic: 'Suggests a new subtopic',
  stage_disagreement: 'Topic disagreement',
}

/** Tag review queue. With ``courseId`` it is filtered to one course. */
export default function TagReviewList({ courseId, courses }) {
  const queryClient = useQueryClient()
  const [filters, setFilters] = useState({ course: courseId || '', reason: '', page: 1 })
  const [selected, setSelected] = useState(new Set())
  const [editing, setEditing] = useState(null)
  const params = Object.fromEntries(Object.entries(filters).filter(([, v]) => v))
  const { data, isLoading } = useQuery({
    queryKey: ['tagReview', params],
    queryFn: () => syllabusService.getReview(params),
    placeholderData: keepPreviousData,
  })
  const refresh = () => {
    setSelected(new Set())
    queryClient.invalidateQueries({ queryKey: ['tagReview'] })
  }
  const act = (fn, message) => ({
    mutationFn: fn,
    onSuccess: () => { if (message) toast.success(message); refresh() },
    onError: (error) => toast.error(errorText(error)),
  })
  const accept = useMutation(act(syllabusService.acceptReview, 'Accepted'))
  const bulk = useMutation(act(() => syllabusService.bulkAccept([...selected]), 'Accepted'))
  const retag = useMutation(act(syllabusService.retag, 'Re-tag queued'))
  const addToTree = useMutation(act((id) => syllabusService.addToTree(id), 'Added to the tree'))

  if (isLoading) return <Loading />
  const rows = data?.results || []
  const toggle = (id) => {
    const next = new Set(selected)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setSelected(next)
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {!courseId && courses && (
          <select value={filters.course} onChange={(e) => setFilters({ ...filters, course: e.target.value, page: 1 })} className="input py-1 text-sm max-w-xs">
            <option value="">All my courses</option>
            {courses.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        )}
        <select value={filters.reason} onChange={(e) => setFilters({ ...filters, reason: e.target.value, page: 1 })} className="input py-1 text-sm max-w-xs">
          <option value="">Any reason</option>
          {Object.entries(REASON_TEXT).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
        </select>
        <span className="text-sm text-surface-500">{data?.total ?? 0} to review</span>
        {selected.size > 0 && (
          <button onClick={() => bulk.mutate()} className="btn-primary text-xs px-3 py-1 ml-auto">Accept {selected.size} selected</button>
        )}
      </div>

      {rows.length === 0 && <p className="text-sm text-surface-400">Nothing needs review.</p>}

      <ul className="divide-y divide-surface-100 dark:divide-surface-700/50">
        {rows.map((row) => (
          <li key={row.id} className="py-3 flex gap-3">
            <input type="checkbox" checked={selected.has(row.id)} onChange={() => toggle(row.id)} className="mt-1" />
            <div className="min-w-0 flex-1 text-sm space-y-1">
              <p className="line-clamp-2">{row.question_text}</p>
              <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-surface-500">
                <span>Primary: {row.primary ? `${row.primary.topic} › ${row.primary.name}` : '—'}</span>
                {row.secondary.length > 0 && <span>Also: {row.secondary.map((n) => n.name).join(', ')}</span>}
                {row.thinking_level && <span>Thinking: {row.thinking_level.replaceAll('_', ' ')}</span>}
                {row.special_format && <span>Format: {row.special_format.replaceAll('_', ' ')}</span>}
                {row.difficulty_prior && <span>Difficulty: {row.difficulty_prior}</span>}
                {row.est_solve_seconds && <span>~{row.est_solve_seconds}s</span>}
                <span>Confidence {Math.round(row.confidence * 100)}%</span>
              </div>
              {row.skills.length > 0 && (
                <p className="text-xs text-surface-500">
                  Skills: {row.skills.map((s) => `${s.label} (${s.role}${s.reason ? `: ${s.reason}` : ''})`).join('; ')}
                </p>
              )}
              <div className="flex flex-wrap gap-1">
                {row.review_reasons.map((reason) => (
                  <span key={reason} className="text-[10px] px-2 py-0.5 rounded-full bg-warning-50 dark:bg-warning-900/20 text-warning-700">{REASON_TEXT[reason] || reason}</span>
                ))}
                {row.proposed_subtopic && <span className="text-[10px] px-2 py-0.5 rounded-full bg-primary-50 text-primary-600">Suggests “{row.proposed_subtopic}”</span>}
              </div>
            </div>
            <div className="flex flex-col gap-1 shrink-0">
              <button onClick={() => accept.mutate(row.id)} className="btn-secondary text-xs px-2 py-1">Accept</button>
              <button onClick={() => setEditing(row.id)} className="btn-secondary text-xs px-2 py-1">Edit</button>
              <button onClick={() => retag.mutate(row.id)} className="btn-secondary text-xs px-2 py-1">Re-tag</button>
              {row.proposed_subtopic && (
                <button onClick={() => addToTree.mutate(row.id)} className="btn-secondary text-xs px-2 py-1">Add to tree</button>
              )}
            </div>
          </li>
        ))}
      </ul>

      {data?.pages > 1 && (
        <div className="flex justify-center items-center gap-3 text-sm">
          <button disabled={filters.page <= 1} onClick={() => setFilters({ ...filters, page: filters.page - 1 })} className="btn-secondary text-xs px-3 py-1 disabled:opacity-40">Previous</button>
          <span>Page {data.page} of {data.pages}</span>
          <button disabled={filters.page >= data.pages} onClick={() => setFilters({ ...filters, page: filters.page + 1 })} className="btn-secondary text-xs px-3 py-1 disabled:opacity-40">Next</button>
        </div>
      )}

      {editing && <TagEditForm taggingId={editing} onClose={() => setEditing(null)} onSaved={refresh} />}
    </div>
  )
}
```

- [ ] **Step 3: Page, route, menu, Insights link**

Create `frontend/exam-frontend/src/pages/TagReview.jsx`:

```jsx
import { useQuery } from '@tanstack/react-query'
import { ClipboardCheck } from 'lucide-react'
import { contentBuilderService } from '../services/contentBuilderService'
import TagReviewList from '../components/syllabus/TagReviewList'

/** Learning Insights → Tag review: every flagged question in the user's courses. */
export default function TagReview() {
  const { data: courses } = useQuery({ queryKey: ['insightCourses'], queryFn: contentBuilderService.getExams })
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-display font-bold flex items-center gap-2">
          <ClipboardCheck className="text-primary-500" /> Tag review
        </h1>
        <p className="text-surface-500 mt-1">Questions the tagger was unsure about. Accept, edit, re-tag, or add a suggested subtopic.</p>
      </div>
      <div className="p-5 rounded-2xl bg-white dark:bg-surface-800 border border-surface-200 dark:border-surface-700">
        <TagReviewList courses={courses || []} />
      </div>
    </div>
  )
}
```

`App.jsx`: import `TagReview` and add

```jsx
          <Route path="/admin/insights/tag-review" element={<LoginGate><EditorRoute><TagReview /></EditorRoute></LoginGate>} />
```

`AdminSidebar.jsx`: change the Insights item's `features` to `['practice', 'diagnosis_teacher_view', 'syllabus_tools']`.

`InsightsHome.jsx`: add `const syllabusOn = useTenantStore((s) => s.tenant?.features?.syllabus_tools === true)` and, in the header button group:

```jsx
          {syllabusOn && (
            <Link
              to="/admin/insights/tag-review"
              className="inline-flex items-center gap-2 px-3 py-2 rounded-xl bg-surface-100 dark:bg-surface-800 text-sm hover:bg-surface-200 dark:hover:bg-surface-700"
            >
              <ClipboardCheck size={14} /> Tag review
            </Link>
          )}
```

(add `ClipboardCheck` to its `lucide-react` import). When `practice` is off and only `syllabus_tools` is on, Insights home still renders: the overview endpoint is not feature-gated, and Part A already hides practice tiles.

- [ ] **Step 4: Tags panel in the question editors**

Create `frontend/exam-frontend/src/components/syllabus/ItemTagsPanel.jsx`:

```jsx
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Tags } from 'lucide-react'
import { syllabusService } from '../../services/syllabusService'
import { useTenantStore } from '../../context/tenantStore'
import TagEditForm from './TagEditForm'

/** Read-only tags for one question, with an "Edit tags" link (syllabus tools). */
export default function ItemTagsPanel({ kind, id }) {
  const on = useTenantStore((s) => s.tenant?.features?.syllabus_tools === true)
  const [editing, setEditing] = useState(false)
  const queryClient = useQueryClient()
  const { data } = useQuery({
    queryKey: ['itemTags', kind, id],
    queryFn: () => syllabusService.getItemTags(kind, id),
    enabled: on && !!id,
    retry: false,
  })
  if (!on || !id || !data) return null
  const t = data.tagging

  return (
    <div className="rounded-xl border border-surface-200 dark:border-surface-700 p-3 text-xs space-y-1">
      <div className="flex items-center justify-between">
        <span className="font-semibold flex items-center gap-1"><Tags size={12} /> Tags</span>
        {t && <button type="button" onClick={() => setEditing(true)} className="text-primary-600 hover:underline">Edit tags</button>}
      </div>
      {!t ? (
        <p className="text-surface-400">Not tagged yet.</p>
      ) : (
        <>
          <p>Subtopic: {t.primary ? `${t.primary.topic} › ${t.primary.name}` : '—'}{t.source === 'manual' && ' (set by a teacher)'}</p>
          {t.thinking_level && <p>Thinking: {t.thinking_level.replaceAll('_', ' ')}</p>}
          {t.skills.length > 0 && <p>Skills: {t.skills.map((s) => `${s.label} (${s.role})`).join(', ')}</p>}
          {t.review_status === 'needs_review' && <p className="text-warning-600">Needs review</p>}
        </>
      )}
      {editing && t && (
        <TagEditForm
          taggingId={t.id}
          onClose={() => setEditing(false)}
          onSaved={() => queryClient.invalidateQueries({ queryKey: ['itemTags', kind, id] })}
        />
      )}
    </div>
  )
}
```

In `builderShared.jsx` `QuestionModal`, import `ItemTagsPanel` and render `{isEdit && <ItemTagsPanel kind="bank" id={instance.id} />}` at the end of the form body (above the action buttons). In `MockTestBuilder.jsx` `ItemEditor`, render `{item?.id && <ItemTagsPanel kind="item" id={item.id} />}` in the same position.

- [ ] **Step 5: Build**

Run (from `frontend/exam-frontend/`): `npx vite build`
Expected: succeeds.

- [ ] **Step 6: Commit**

```bash
git add frontend/exam-frontend/src/components/syllabus/TagReviewList.jsx frontend/exam-frontend/src/components/syllabus/TagEditForm.jsx frontend/exam-frontend/src/components/syllabus/ItemTagsPanel.jsx frontend/exam-frontend/src/pages/TagReview.jsx frontend/exam-frontend/src/App.jsx frontend/exam-frontend/src/pages/InsightsHome.jsx frontend/exam-frontend/src/components/layout/AdminSidebar.jsx frontend/exam-frontend/src/components/admin/builderShared.jsx frontend/exam-frontend/src/pages/MockTestBuilder.jsx
git commit -m "feat(frontend): tag review queue, tag editor and Tags panel in question editors"
```

---

### Task 13: Docs and manual walkthrough

**Files:**
- Modify: `wiki/backend-guide.md` ("Question tagging v2" section)

- [ ] **Step 1: Ops notes**

At the end of the "Question tagging v2 (intelligence)" section in `wiki/backend-guide.md`, add:

```markdown
### Syllabus & tagging tools (2B Part B)

Opt-in switch `syllabus_tools` (also a learning-layer switch: turning it on
starts event collection like the other three). Admins, and faculty on their
assigned courses, get a **Syllabus** view on the course editor and
**Learning Insights → Tag review**.

- **Build syllabus tree** (custom courses) queues a `TreeBuildJob` on `aigen`
  (`intelligence.build_course_tree`). LLM-suggested subtopics are created as
  `proposed` and shown as "suggested"; the tagger uses them straight away.
- **Use an exam syllabus** instantiates a shipped tree synchronously (no LLM).
  A course has either an exam tree or a built tree, never both.
- **Tag questions** queues a `TaggingRun` (`intelligence.tagging_run`) over the
  course's treed subjects, at most 500 items per run, and records tagged /
  needs-review / failed counts.
- Both refuse to start when the tenant's monthly token budget is used up, and
  only one of each runs per course at a time.
- **Editor:** add / rename / archive sub-subjects and subtopics, move topics,
  set weightage, accept suggestions, merge subtopics (queues
  `intelligence.recompute_concept_states` for the target concept), choose
  skill packs. Course topics are read-only.
- **Review:** Accept, bulk accept, Edit (saves `manual` tags — the tagger
  never overwrites them), Re-tag (`intelligence.retag_item`), Add to tree.
- **Local testing:** `CELERY_TASK_ALWAYS_EAGER=true` runs every task inside the
  request (diagnosis right after submit; Build and Tag without a worker).
  Never set it in production.
```

- [ ] **Step 2: Manual walkthrough (PR description, not committed)**

Under "Manual checks — Part B" in the PR description:

1. Run the backend with `CELERY_TASK_ALWAYS_EAGER=true` and `manage.py sync_taxonomy` done once.
2. On the CodeMinors test tenant, turn on Syllabus & tagging tools. Open a
   custom course → Syllabus. The estimate shows AI calls and tokens; Build
   finishes in the request and the tree shows "suggested" subtopics.
3. Accept one suggestion, rename another (it becomes active), add a
   subtopic, move a topic to another sub-subject (create one first), set
   weightages that don't sum to 1 (a warning toast appears), merge two
   subtopics, archive one.
4. Tag questions: counts appear; flagged ones show under "Questions needing review".
5. In Tag review: Accept one, bulk accept two, Edit one (tags show "set by a
   teacher" in the question editor's Tags panel), Re-tag one, Add a
   suggested subtopic to the tree.
6. On the DailyTaiyari test tenant, map an exam course to `jee_main`; Build is
   not offered for it.
7. As faculty assigned to another course, open this course's Syllabus URL and
   the Tag review page: the course's rows are absent, and the API refuses.
8. Turn the switch off: no Syllabus button, no Tag review link, and the API
   answers 403.

- [ ] **Step 3: Final checks**

Run: `venv/Scripts/python.exe manage.py test -v 1` and `npx vite build` (exam-frontend).
Expected: all PASS; build succeeds.

- [ ] **Step 4: Commit**

```bash
git add wiki/backend-guide.md
git commit -m "docs(wiki): syllabus and tagging tools"
```
