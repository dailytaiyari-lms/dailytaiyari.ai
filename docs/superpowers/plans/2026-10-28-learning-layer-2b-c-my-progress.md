# Learning Layer 2B, Part C — My Progress Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give students a My Progress page: mastery rolled up from subtopic
to topic, sub-subject and subject, weak and strong topics, skill and
thinking-level profiles, and recent answers. Give teachers the same view per
student and a class topic heatmap per course.

**Architecture:**
- **Switch:** one opt-in switch, `my_progress`, which also joins
  `LEARNING_FEATURES`.
- **Roll-ups are computed on read.** `services/rollup.py` builds each course
  subject's structure (the syllabus tree, or subject → Topic → Concept when
  there is no tree) and rolls `LearnerConceptState` leaves up through it. The
  4-week trend comes from `LearningEvent`s. The roll-up arithmetic is pure
  and tested against hand-computed fixtures.
- **Facets are stored.** One new table, `LearnerFacetState`, holds a
  student's mastery per skill and per thinking level per subject.
  `services/facets.py` recomputes it from events with the same rules as
  `services/state.py` (it calls `state.compute_state_fields`). It runs after
  each diagnosed attempt, nightly, and from `recompute_learner_state`, and
  only for tenants with `my_progress` on.
- **Payloads:** `services/progress.py` assembles the page payload (roll-up,
  weak/strong lists, profiles, recent answers) and the class heatmap. Three
  thin views serve them.
- **Frontend:** a student `/progress` page and a teacher "Progress" tab share
  one `ProgressView` component. Insights home gains a class heatmap tile.
  Smart Practice accepts a topic filter for "Practise this".

**Tech Stack:** Django 5 / DRF, Celery (`intelligence` queue), SQLite
(tests), React 18 + Vite + TanStack Query + Tailwind (exam-frontend).

**Spec:** `docs/superpowers/specs/2026-10-24-learning-layer-2b-design.md`
§2, §3 and §6. Parts A and B must be done first:
- Part A (`2026-10-28-learning-layer-2b-a-diagnosis-visibility.md`) provides
  `intelligence/access.py`, `VisibilityTestCase`, `visibility_config`
  (`STUDENT_NOTE_CONFIDENCE`), the effective `get_features()`, the
  StudentDiagnosis tabs and the `features` list on admin nav items.
- Part B (`2026-10-28-learning-layer-2b-b-syllabus-tools.md`) provides
  migration `0006_syllabus_jobs`, `proposed` subtopics and the tags the
  profiles read. Without B's tags the profiles show "needs tagging" and the
  roll-up uses its fallback.

## Global Constraints

**Environment**
- Run backend commands from `backend/` with `venv/Scripts/python.exe`.
- Test command shape:
  `venv/Scripts/python.exe manage.py test <dotted.path> -v 2`.
- Frontend check: `npx vite build` in `frontend/exam-frontend/`. There is no
  frontend test runner.

**Git**
- Local branch `saksham/learning-layer-2b`. Never push. Never change git
  config.
- Stage only the files your task names. Never `git add -A` / `git add .`.
- End every commit message with the `Co-Authored-By:` line in your dispatch.

**Architecture rules**
- Other apps reach the intelligence layer only through `api.py` /
  `hooks.py`. Part C adds no calls from other apps.
- One new model, `LearnerFacetState` (inherits `TimeStampedModel`), and one
  additive migration, `0007_learner_facet_state`. Roll-ups, lists, recent
  answers and heatmaps are never stored.
- Every endpoint requires `my_progress` (403 when off) and the scope rules
  of `intelligence/access.py` (403 out of scope). A missing student or
  course is 404.
- Students never receive a bare diagnosis label. Recent answers carry only
  a plain-language summary.
- Facets are recomputed only for tenants with `my_progress` on, so a tenant
  with it off gets no new rows and no new background work.

**Values** (in `intelligence/progress_config.py`)
- Bands: `WEAK_BELOW = 0.5`, `STRONG_AT = 0.8`, `MIN_EVIDENCE = 3`
  (effective evidence before a node shows a mastery).
- Status names: `weak`, `in_progress`, `strong`, `not_enough_data`.
- Lists: top 5 weak and top 5 strong topics; last 5 attempts in recent
  answers.
- Trend: 4 weekly points, oldest first; a week with fewer than 2 answers
  is `null`.
- Facet weights: core skill 1.0, supporting skill 0.5, thinking level 1.0.
  `FACET_MODEL_VERSION = '1'`.
- Heatmap: at most 500 students per course.

**Decisions this plan makes where the spec is silent**
1. **Which tree nodes count.** The roll-up reads `active` and `proposed`
   nodes with `in_syllabus=True`, the same live set the tagger uses after
   Part B. Archived nodes, out-of-syllabus nodes and everything beneath them
   are left out. A subject uses its tree once it has at least one such
   subtopic; until then it uses the fallback.
2. **Weightage per sibling group.** A group of siblings is "weighted" when
   any of them has `weightage > 0`; then each child's weight is
   `evidence × weightage`. Otherwise it is `evidence` alone. A child with
   evidence but zero weightage in a weighted group adds to evidence and
   coverage, but not to mastery.
3. **Leaf evidence below the floor still counts upward.** A subtopic with
   evidence under 3 shows `mastery: null`, but its raw mastery and evidence
   still feed its parent, so three subtopics with one answer each can give
   a topic a mastery.
4. **Trend value.** Each weekly point is the weighted mean `score_fraction`
   of the student's latest answers that week on the node's concepts. The
   weight is the diagnosis weight (`LABEL_WEIGHTS`, 1.0 without a
   diagnosis) times the practice weight (0.6 for practice answers), as in
   `state.py`. Weeks count back from now in 7-day steps.
5. **Fallback details.** Without a tree, topics are the subject's course
   `Topic`s that have at least one active Concept linked through
   `Concept.topics`. A concept under several topics counts under each, so
   subject-level coverage can count it twice. Active concepts of the subject
   with no topic go into one extra topic, "Other concepts".
6. **Facet subject.** A contribution belongs to the subject of the item's
   `ItemTagging.primary_node`, else the event's subject snapshot. Items with
   no tags are skipped. Tags count whatever their `review_status`, like the
   tagger's concept links.
7. **"Needs tagging"** means no item is tagged against the subject's tree
   (no `ItemTagging` with a `primary_node` in that subject). A tagged
   subject where the student has no facet rows yet shows empty lists with
   status `ok`.
8. **Course picker.** The progress payload lists the courses the viewer may
   pick: the student's approved enrolments (for faculty, only those they
   teach). Without `?course=`, the first one by name is used. A course
   outside the list is 403; an unknown or malformed id is 404. A student
   with no approved course gets 200 with `course: null`.
9. **Recent answers.** For the student endpoint they appear when
   `diagnosis_student_view` is on. For the teacher endpoint they appear when
   `diagnosis_teacher_view` is on (the teacher can already see labels on the
   Answers tab), with the same wording. They cover the selected course's
   quizzes and mocks, the last 5 finished attempts, counting only medium-
   and high-confidence diagnoses (the review-page note rule). Teacher rows
   do not link to the student's review pages.
10. **"Practise this"** opens `/practice?concepts=<ids>&topic=<name>`. The
    Practice page filters its suggested sets and its mastery map to those
    concepts and offers "Show all". `PracticeSetSerializer` gains an
    additive `concept_ids` field for this. No new set is generated.
11. **Heatmap coverage** per topic is the mean of the students' coverage of
    that topic. Cells hold student counts and the names behind them.
12. **Who has a progress page.** Only users with `role='student'`. Staff
    calling `my/progress/` get 403.

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/core/models.py` (modify) | `my_progress` feature (opt-in) |
| `backend/intelligence/api.py` (modify) | `my_progress` in `LEARNING_FEATURES` |
| `backend/intelligence/versions.py` (modify) | `FACET_MODEL_VERSION` |
| `backend/intelligence/progress_config.py` (create) | bands, trend, list sizes, facet weights, recent-answer wording, heatmap cap |
| `backend/intelligence/models.py` (modify) | `LearnerFacetState` |
| `backend/intelligence/migrations/0007_learner_facet_state.py` | generated |
| `backend/intelligence/services/rollup.py` (create) | pure roll-up, trend, topic lists; course structure and `rollup_for` |
| `backend/intelligence/services/facets.py` (create) | facet observations, recompute, `update_for_attempt`, `profile_for` |
| `backend/intelligence/services/progress.py` (create) | page payload, recent answers, summary wording, heatmap |
| `backend/intelligence/tasks.py` (modify) | facets after diagnosis; nightly facet sweep |
| `backend/intelligence/management/commands/recompute_learner_state.py` (modify) | `--facets` / `--no-facets` |
| `backend/intelligence/serializers.py` (modify) | `concept_ids` on practice sets |
| `backend/intelligence/views.py` (modify) | `ProgressFeaturePermission`, `progress_course`, `MyProgressView` |
| `backend/intelligence/urls.py` (modify) | `my/progress/` |
| `backend/intelligence/admin_views.py` (modify) | `StudentProgressView`, `CourseHeatmapView` |
| `backend/intelligence/admin_urls.py` (modify) | two routes |
| `backend/intelligence/tests/progress_fixtures.py` (create) | tree, concepts, states, events, tags on top of `VisibilityTestCase` |
| `backend/intelligence/tests/test_progress_rules.py` (create) | pure roll-up, trend, lists, summary |
| `backend/intelligence/tests/test_rollup.py` (create) | roll-up from the database |
| `backend/intelligence/tests/test_facets.py` (create) | facet recompute, profiles, jobs, command |
| `backend/intelligence/tests/test_progress_api.py` (create) | endpoints, scope, opt-out |
| `frontend/exam-frontend/src/context/tenantStore.js`, `hooks/useResponseTimeline.js` (modify) | opt-in / learning lists |
| `frontend/exam-frontend/src/services/progressService.js` (create) | student call |
| `frontend/exam-frontend/src/services/insightsService.js` (modify) | two teacher calls |
| `frontend/exam-frontend/src/components/progress/progressUi.jsx` (create) | status text/colours, percent, sparkline, band bar |
| `frontend/exam-frontend/src/components/progress/RollupTree.jsx` (create) | expandable breakdown |
| `frontend/exam-frontend/src/components/progress/ProfilesPanel.jsx` (create) | skills and thinking levels |
| `frontend/exam-frontend/src/components/progress/ProgressView.jsx` (create) | the shared page body |
| `frontend/exam-frontend/src/pages/MyProgress.jsx` (create) | student page |
| `frontend/exam-frontend/src/components/insights/StudentProgressTab.jsx` (create) | teacher tab |
| `frontend/exam-frontend/src/components/insights/ClassHeatmap.jsx` (create) | course heatmap tile |
| `frontend/exam-frontend/src/pages/Practice.jsx` (modify) | topic filter |
| `frontend/exam-frontend/src/pages/StudentDiagnosis.jsx` (modify) | Progress tab |
| `frontend/exam-frontend/src/pages/InsightsHome.jsx` (modify) | heatmap tile |
| `frontend/exam-frontend/src/components/layout/Sidebar.jsx`, `AdminSidebar.jsx`, `App.jsx` (modify) | menu items, route |
| `wiki/backend-guide.md` (modify) | ops notes |

---

### Task 1: The `my_progress` switch

**Files:**
- Modify: `backend/core/models.py`, `backend/intelligence/api.py`
- Modify: `frontend/exam-frontend/src/context/tenantStore.js`, `frontend/exam-frontend/src/hooks/useResponseTimeline.js`
- Test: `backend/intelligence/tests/test_progress_api.py` (create; first class)

**Interfaces:**
- Produces: feature key `my_progress` (label "My Progress", opt-in); `'my_progress' in api.LEARNING_FEATURES`.

- [ ] **Step 1: Write the failing test**

Create `backend/intelligence/tests/test_progress_api.py`:

```python
"""My Progress: switch, endpoints, scope and opt-out."""
from django.test import TestCase

from core.models import Tenant
from intelligence import api


class SwitchTests(TestCase):
    def test_my_progress_is_opt_in_and_a_learning_feature(self):
        self.assertIn('my_progress', Tenant.FEATURE_CHOICES)
        self.assertIn('my_progress', Tenant.OPT_IN_FEATURES)
        self.assertIn('my_progress', api.LEARNING_FEATURES)
        tenant = Tenant.objects.create(name='Progress Switch Academy')
        self.assertFalse(tenant.get_features()['my_progress'])
        self.assertFalse(api.intelligence_enabled(tenant))
        tenant.features = {'my_progress': True}
        self.assertTrue(api.intelligence_enabled(tenant))
```

- [ ] **Step 2: Run it to verify it fails**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_progress_api -v 2`
Expected: FAIL (`'my_progress' not found`).

- [ ] **Step 3: Implement**

`backend/core/models.py`: add to `FEATURE_CHOICES` after `'syllabus_tools'`:

```python
        'my_progress': 'My Progress',
```

and add `'my_progress'` to `OPT_IN_FEATURES`.

`backend/intelligence/api.py`: replace the `LEARNING_FEATURES` line with:

```python
LEARNING_FEATURES = (
    'practice', 'ai_grading', 'response_diagnosis', 'syllabus_tools', 'my_progress',
)
```

(keep the comment Part B wrote above it).

`frontend/exam-frontend/src/context/tenantStore.js`: add `'my_progress'` to `OPT_IN_FEATURES`.

`frontend/exam-frontend/src/hooks/useResponseTimeline.js`: change the `LEARNING_FEATURES` line to

```js
const LEARNING_FEATURES = ['practice', 'ai_grading', 'response_diagnosis', 'syllabus_tools', 'my_progress']
```

- [ ] **Step 4: Run tests**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_progress_api intelligence.tests.test_gate -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/core/models.py backend/intelligence/api.py frontend/exam-frontend/src/context/tenantStore.js frontend/exam-frontend/src/hooks/useResponseTimeline.js backend/intelligence/tests/test_progress_api.py
git commit -m "feat(intelligence): my_progress switch"
```

---

### Task 2: Config, `LearnerFacetState` and migration

**Files:**
- Create: `backend/intelligence/progress_config.py`
- Modify: `backend/intelligence/versions.py`, `backend/intelligence/models.py`
- Create: `backend/intelligence/migrations/0007_learner_facet_state.py` (generated)
- Test: `backend/intelligence/tests/test_facets.py` (create; first class)

**Interfaces:**
- Produces: `progress_config` constants (see the file); `versions.FACET_MODEL_VERSION = '1'`; model `LearnerFacetState(student, subject, kind, key, mastery, evidence_count, effective_evidence, confidence, model_version, computed_at)`, unique on (`student`, `subject`, `kind`, `key`), `related_name='facet_states'` on the student.

- [ ] **Step 1: Write the failing test**

Create `backend/intelligence/tests/test_facets.py`:

```python
"""Skill and thinking-level profiles (spec 2B §6.3)."""
from django.db import IntegrityError, transaction
from django.test import TestCase

from core.models import Tenant
from exams.models import Course, Subject
from intelligence.models import LearnerFacetState
from users.models import User


class FacetModelTests(TestCase):
    def test_one_row_per_student_subject_kind_key(self):
        tenant = Tenant.objects.create(name='Facet Academy')
        student = User.objects.create_user(
            email='facet@example.com', password='pw-facet-1', tenant=tenant, role='student',
        ).profile
        course = Course.objects.create(tenant=tenant, name='Physics', code='facet-phy',
                                       course_type='competitive')
        subject = Subject.objects.create(tenant=tenant, course=course, name='Mechanics',
                                         code='facet-mech')
        LearnerFacetState.objects.create(
            tenant=tenant, student=student, subject=subject, kind='skill', key='vectors',
            mastery=0.6, evidence_count=2, effective_evidence=2.0, confidence='low',
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            LearnerFacetState.objects.create(
                tenant=tenant, student=student, subject=subject, kind='skill', key='vectors',
            )
        self.assertEqual(student.facet_states.get().model_version, '1')
```

- [ ] **Step 2: Run it to verify it fails**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_facets -v 2`
Expected: ImportError (`cannot import name 'LearnerFacetState'`).

- [ ] **Step 3: Write the config**

Create `backend/intelligence/progress_config.py`:

```python
"""My Progress knobs (spec 2B §6): topic bands, the evidence floor, the
trend window, list sizes, facet weights, recent-answer wording and the
heatmap cap.

Bands, list sizes and wording are display-only: changing them changes the
next request, nothing stored. Facet weights change stored LearnerFacetState
values: bump FACET_MODEL_VERSION and run ``recompute_learner_state``.
"""

# ── Topic bands (§6.2) ───────────────────────────────────────────────────────
WEAK_BELOW = 0.5
STRONG_AT = 0.8
MIN_EVIDENCE = 3            # effective evidence before a node shows a mastery
TOP_TOPICS = 5              # weak / strong list length

# ── Trend (§6.1) ─────────────────────────────────────────────────────────────
TREND_WEEKS = 4
TREND_MIN_EVENTS = 2        # a week with fewer answers is null
TREND_MAX_EVENTS = 2000     # newest events read per request

# ── Facets (§6.3) ────────────────────────────────────────────────────────────
SKILL_ROLE_WEIGHTS = {'core': 1.0, 'supporting': 0.5}
THINKING_LEVEL_WEIGHT = 1.0
FACET_REFRESH_LIMIT = 2000  # students per nightly facet sweep

# ── Recent answers (§6.4) ────────────────────────────────────────────────────
RECENT_ATTEMPTS = 5
# (singular, plural) per label, for "2 quick guesses, 1 ran out of time".
# Labels not listed (correct, skipped, not_seen, unclear) are not counted;
# neither are low-confidence diagnoses (visibility_config.STUDENT_NOTE_CONFIDENCE).
RECENT_PHRASES = {
    'guess': ('quick guess', 'quick guesses'),
    'correct_lucky': ('quick correct answer', 'quick correct answers'),
    'correct_slow': ('slow correct answer', 'slow correct answers'),
    'second_guess': ('changed right answer', 'changed right answers'),
    'careless_slip': ('possible slip', 'possible slips'),
    'time_pressure': ('ran out of time', 'ran out of time'),
    'concept_gap': ('needs more practice', 'need more practice'),
}

# ── Class heatmap (§6.5) ─────────────────────────────────────────────────────
HEATMAP_MAX_STUDENTS = 500
HEATMAP_BANDS = ('weak', 'in_progress', 'strong', 'not_enough_data')
```

- [ ] **Step 4: Version and model**

Append to `backend/intelligence/versions.py`:

```python

# Skill / thinking-level facet algorithm (services/facets.py, the facet
# weights in progress_config.py). Bump, then run ``recompute_learner_state``.
FACET_MODEL_VERSION = '1'
```

In `backend/intelligence/models.py`, add `FACET_MODEL_VERSION` to the `.versions` import, and add after `LearnerConceptState`:

```python
class LearnerFacetState(TimeStampedModel):
    """Inferred state of one student on one skill or thinking level, per
    subject (spec 2B §6.3).

    Fully recomputed from LearningEvents by ``services.facets`` with the same
    rules as LearnerConceptState; never incremented in place.
    """

    KIND_SKILL = 'skill'
    KIND_THINKING = 'thinking_level'
    KIND_CHOICES = [(KIND_SKILL, 'Skill'), (KIND_THINKING, 'Thinking level')]

    student = models.ForeignKey(
        'users.StudentProfile', on_delete=models.CASCADE, related_name='facet_states',
    )
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='learner_facet_states')
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    key = models.CharField(max_length=60)

    mastery = models.FloatField(default=0.0)
    evidence_count = models.PositiveIntegerField(default=0)
    effective_evidence = models.FloatField(default=0.0)
    confidence = models.CharField(
        max_length=10, choices=LearnerConceptState.CONFIDENCE_CHOICES, default='low',
    )

    model_version = models.CharField(max_length=10, default=FACET_MODEL_VERSION)
    computed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Learner Facet State'
        verbose_name_plural = 'Learner Facet States'
        constraints = [
            models.UniqueConstraint(
                fields=['student', 'subject', 'kind', 'key'], name='uniq_learner_facet_state',
            ),
        ]
        indexes = [models.Index(fields=['tenant', 'subject'])]

    def __str__(self):
        return f'{self.student_id} × {self.kind}:{self.key}: {self.mastery:.2f}'
```

- [ ] **Step 5: Generate the migration**

Run: `venv/Scripts/python.exe manage.py makemigrations intelligence --name learner_facet_state`
Expected: `intelligence/migrations/0007_learner_facet_state.py` with one `CreateModel`, depending on `0006_syllabus_jobs`. Open it and confirm it touches no existing model.

- [ ] **Step 6: Run tests**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_facets -v 2`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/intelligence/progress_config.py backend/intelligence/versions.py backend/intelligence/models.py backend/intelligence/migrations/0007_learner_facet_state.py backend/intelligence/tests/test_facets.py
git commit -m "feat(intelligence): LearnerFacetState and My Progress config"
```

---

### Task 3: Pure roll-up rules

**Files:**
- Create: `backend/intelligence/services/rollup.py` (pure part)
- Test: `backend/intelligence/tests/test_progress_rules.py`

**Interfaces:**
- Produces (all pure, no database):
  - `LEAF_LEVELS = ('subtopic', 'concept')`, `LIVE_STATUSES = ('active', 'proposed')`;
  - `classify(mastery, evidence) -> 'weak' | 'in_progress' | 'strong' | 'not_enough_data'`;
  - `confidence_for(evidence) -> 'low' | 'medium' | 'high'` (the `state.py` cut-offs);
  - `rollup_node(node, states, trends=None) -> payload`. `node` is `{'id', 'name', 'level', 'weightage', 'concept_id' (leaves), 'children'}`; `states` maps concept id → `(mastery, effective_evidence)`; `trends` maps node id (str) → 4 points. The payload is `{'id', 'name', 'level', 'mastery', 'status', 'coverage', 'covered', 'total', 'evidence', 'confidence', 'trend_4w', 'concept_ids', 'children'}`;
  - `iter_nodes(payload)` (depth-first, the node first);
  - `weekly_trend(points, now) -> [4 values]` where `points` is `[(occurred_at, score, weight)]`;
  - `node_event_sets(node, events_by_concept) -> {node id: set(event index)}`;
  - `topic_lists(subjects) -> (weak, strong)`; each entry `{'id', 'name', 'subject', 'mastery', 'evidence', 'coverage', 'status', 'concept_ids'}`.

- [ ] **Step 1: Write the failing test**

Create `backend/intelligence/tests/test_progress_rules.py`:

```python
"""Pure My Progress rules, against hand-computed fixtures."""
from datetime import datetime, timedelta, timezone as dt_timezone

from django.test import SimpleTestCase

from intelligence.services import rollup

A, B, C, D = 'concept-a', 'concept-b', 'concept-c', 'concept-d'


def leaf(id, concept, weightage=0.0):
    return {'id': id, 'name': id.title(), 'level': 'subtopic', 'weightage': weightage,
            'concept_id': concept, 'children': []}


def branch(id, level, children, weightage=0.0):
    return {'id': id, 'name': id.title(), 'level': level, 'weightage': weightage,
            'children': children}


# subject → Mechanics (sub-subject) → Kinematics (0.6) / Dynamics (0.4) → subtopics
TREE = branch('physics', 'subject', [
    branch('mechanics', 'sub_subject', [
        branch('kinematics', 'topic', [
            leaf('velocity', A), leaf('projectile', B), leaf('relative', C),
        ], weightage=0.6),
        branch('dynamics', 'topic', [leaf('friction', D)], weightage=0.4),
    ]),
])
STATES = {A: (0.9, 6.0), B: (0.3, 2.0), D: (0.4, 4.0)}


def find(payload, node_id):
    return next(node for node in rollup.iter_nodes(payload) if node['id'] == node_id)


class ClassifyTests(SimpleTestCase):
    def test_bands(self):
        self.assertEqual(rollup.classify(0.49, 3), 'weak')
        self.assertEqual(rollup.classify(0.5, 3), 'in_progress')
        self.assertEqual(rollup.classify(0.79, 3), 'in_progress')
        self.assertEqual(rollup.classify(0.8, 3), 'strong')
        self.assertEqual(rollup.classify(0.9, 2.99), 'not_enough_data')
        self.assertEqual(rollup.classify(None, 10), 'not_enough_data')

    def test_confidence_uses_state_cut_offs(self):
        self.assertEqual(rollup.confidence_for(2.9), 'low')
        self.assertEqual(rollup.confidence_for(3.0), 'medium')
        self.assertEqual(rollup.confidence_for(10.0), 'high')


class RollupTests(SimpleTestCase):
    def setUp(self):
        self.payload = rollup.rollup_node(TREE, STATES)

    def test_leaves(self):
        velocity = find(self.payload, 'velocity')
        self.assertEqual((velocity['mastery'], velocity['status']), (0.9, 'strong'))
        self.assertEqual((velocity['covered'], velocity['total']), (1, 1))
        self.assertEqual(velocity['concept_ids'], [A])
        projectile = find(self.payload, 'projectile')   # evidence 2 < 3
        self.assertIsNone(projectile['mastery'])
        self.assertEqual(projectile['status'], 'not_enough_data')
        relative = find(self.payload, 'relative')       # no state at all
        self.assertEqual((relative['covered'], relative['evidence']), (0, 0.0))

    def test_unweighted_topic_uses_evidence_and_keeps_thin_leaves(self):
        # siblings all weightage 0 → weights 6 and 2: (6×0.9 + 2×0.3) / 8 = 0.75
        kinematics = find(self.payload, 'kinematics')
        self.assertEqual(kinematics['mastery'], 0.75)
        self.assertEqual(kinematics['status'], 'in_progress')
        self.assertEqual(kinematics['evidence'], 8.0)
        self.assertEqual((kinematics['covered'], kinematics['total']), (2, 3))
        self.assertEqual(kinematics['coverage'], 0.6667)
        self.assertEqual(kinematics['concept_ids'], [A, B, C])

    def test_weighted_parent(self):
        # 8×0.6 = 4.8 and 4×0.4 = 1.6: (4.8×0.75 + 1.6×0.4) / 6.4 = 0.6625
        mechanics = find(self.payload, 'mechanics')
        self.assertEqual(mechanics['mastery'], 0.6625)
        self.assertEqual(mechanics['evidence'], 12.0)
        self.assertEqual(mechanics['coverage'], 0.75)
        self.assertEqual(mechanics['confidence'], 'high')
        self.assertEqual(self.payload['mastery'], 0.6625)
        self.assertEqual(find(self.payload, 'dynamics')['status'], 'weak')

    def test_zero_weightage_child_in_weighted_group_adds_no_mastery(self):
        tree = branch('topic', 'topic', [
            leaf('weighted', A, weightage=1.0), leaf('unweighted', D, weightage=0.0)])
        payload = rollup.rollup_node(tree, {A: (0.9, 6.0), D: (0.1, 6.0)})
        self.assertEqual(payload['mastery'], 0.9)
        self.assertEqual(payload['evidence'], 12.0)

    def test_node_without_leaves_has_no_coverage(self):
        payload = rollup.rollup_node(branch('empty', 'topic', []), {})
        self.assertIsNone(payload['coverage'])
        self.assertEqual(payload['status'], 'not_enough_data')

    def test_trend_defaults_to_nulls(self):
        self.assertEqual(self.payload['trend_4w'], [None, None, None, None])
        payload = rollup.rollup_node(TREE, STATES, {'kinematics': [0.5, None, None, 1.0]})
        self.assertEqual(find(payload, 'kinematics')['trend_4w'], [0.5, None, None, 1.0])


class TopicListTests(SimpleTestCase):
    def test_weak_and_strong(self):
        tree = branch('physics', 'subject', [
            branch(name, 'topic', [leaf(f'{name}-leaf', concept)])
            for name, concept in (('alpha', A), ('beta', B), ('gamma', C), ('delta', D))
        ])
        states = {A: (0.2, 5.0), B: (0.4, 5.0), C: (0.95, 5.0), D: (0.85, 1.0)}
        weak, strong = rollup.topic_lists([rollup.rollup_node(tree, states)])
        self.assertEqual([t['name'] for t in weak], ['Alpha', 'Beta'])
        self.assertEqual([t['name'] for t in strong], ['Gamma'])     # delta: too little evidence
        self.assertEqual(weak[0]['subject'], 'Physics')
        self.assertEqual(weak[0]['concept_ids'], [A])


NOW = datetime(2026, 10, 28, 12, 0, tzinfo=dt_timezone.utc)


class TrendTests(SimpleTestCase):
    def test_weekly_weighted_mean_oldest_first(self):
        points = [
            (NOW - timedelta(days=1), 1.0, 1.0),
            (NOW - timedelta(days=2), 0.0, 0.2),    # a guess: weight 0.2
            (NOW - timedelta(days=10), 1.0, 1.0),   # week 1 has one answer → null
            (NOW - timedelta(days=22), 1.0, 1.0),
            (NOW - timedelta(days=23), 1.0, 0.5),
            (NOW - timedelta(days=40), 0.0, 1.0),   # outside the window
        ]
        # week 0: (1×1 + 0×0.2) / 1.2 = 0.8333
        self.assertEqual(rollup.weekly_trend(points, NOW), [1.0, None, None, 0.8333])

    def test_event_sets_union_children(self):
        sets = rollup.node_event_sets(TREE, {A: [0, 1], B: [1, 2], D: [3]})
        self.assertEqual(sets['velocity'], {0, 1})
        self.assertEqual(sets['kinematics'], {0, 1, 2})
        self.assertEqual(sets['physics'], {0, 1, 2, 3})
        self.assertEqual(sets['relative'], set())
```

- [ ] **Step 2: Run it to verify it fails**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_progress_rules -v 2`
Expected: ImportError (`cannot import name 'rollup'`).

- [ ] **Step 3: Implement the pure part**

Create `backend/intelligence/services/rollup.py`:

```python
"""Mastery roll-ups for My Progress (spec 2B §6.1–6.2).

Mastery lives at the leaves (one LearnerConceptState per subtopic Concept).
Every figure above a leaf is computed on read and never stored:

- a parent's mastery is the mean of its children that have evidence,
  weighted by ``evidence × weightage``, or by evidence alone when no sibling
  carries a weightage;
- coverage is leaves with evidence over all leaves beneath a node;
- a node under ``MIN_EVIDENCE`` effective evidence shows no mastery, though
  its raw figures still feed its parent;
- the 4-week trend comes from LearningEvents, because state rows hold only
  the current value.

A course subject without a syllabus tree falls back to subject → course
Topic → Concept (``Concept.topics``), with no sub-subject level.

Everything above the "Database" line is pure.
"""
from collections import defaultdict
from datetime import timedelta

from django.utils import timezone

from intelligence import progress_config as C
from intelligence.services.state import CONFIDENCE_HIGH, CONFIDENCE_MEDIUM

LEAF_LEVELS = ('subtopic', 'concept')
LIVE_STATUSES = ('active', 'proposed')
WEEK = timedelta(days=7)


def classify(mastery, evidence):
    if mastery is None or evidence < C.MIN_EVIDENCE:
        return 'not_enough_data'
    if mastery < C.WEAK_BELOW:
        return 'weak'
    if mastery >= C.STRONG_AT:
        return 'strong'
    return 'in_progress'


def confidence_for(evidence):
    if evidence < CONFIDENCE_MEDIUM:
        return 'low'
    if evidence < CONFIDENCE_HIGH:
        return 'medium'
    return 'high'


def _round(value):
    return round(value, 4) if value is not None else None


def rollup_node(node, states, trends=None):
    """Roll ``node`` and its subtree up from leaf states; returns the payload."""
    payload, _raw, _evidence = _roll(node, states, trends or {})
    return payload


def _roll(node, states, trends):
    children = node.get('children') or []
    if node['level'] in LEAF_LEVELS:
        concept_id = node.get('concept_id')
        mastery, evidence = states.get(concept_id, (None, 0.0)) if concept_id else (None, 0.0)
        raw = mastery if evidence > 0 else None
        covered, total = (1 if evidence > 0 else 0), 1
        concept_ids = [str(concept_id)] if concept_id else []
        child_payloads = []
    else:
        rolled = [_roll(child, states, trends) for child in children]
        weighted = any((child.get('weightage') or 0) > 0 for child in children)
        numerator = denominator = evidence = 0.0
        covered = total = 0
        concept_ids = []
        for child, (child_payload, child_raw, child_evidence) in zip(children, rolled):
            evidence += child_evidence
            covered += child_payload['covered']
            total += child_payload['total']
            concept_ids.extend(child_payload['concept_ids'])
            if child_raw is None or child_evidence <= 0:
                continue
            factor = (child.get('weightage') or 0) if weighted else 1.0
            numerator += child_evidence * factor * child_raw
            denominator += child_evidence * factor
        raw = numerator / denominator if denominator > 0 else None
        child_payloads = [payload for payload, _, _ in rolled]

    status = classify(raw, evidence)
    payload = {
        'id': str(node['id']),
        'name': node['name'],
        'level': node['level'],
        'mastery': _round(raw) if status != 'not_enough_data' else None,
        'status': status,
        'coverage': _round(covered / total) if total else None,
        'covered': covered,
        'total': total,
        'evidence': round(evidence, 4),
        'confidence': confidence_for(evidence),
        'trend_4w': trends.get(str(node['id']), [None] * C.TREND_WEEKS),
        'concept_ids': list(dict.fromkeys(concept_ids)),
        'children': child_payloads,
    }
    return payload, raw, evidence


def iter_nodes(payload):
    yield payload
    for child in payload['children']:
        yield from iter_nodes(child)


def weekly_trend(points, now):
    """``[(occurred_at, score, weight)]`` → weekly weighted mean scores,
    oldest first. A week with fewer than ``TREND_MIN_EVENTS`` answers is None."""
    weeks = [[0, 0.0, 0.0] for _ in range(C.TREND_WEEKS)]   # n, Σw, Σw·score
    for occurred_at, score, weight in points:
        index = (now - occurred_at) // WEEK
        if not 0 <= index < C.TREND_WEEKS:
            continue
        bucket = weeks[index]
        bucket[0] += 1
        bucket[1] += weight
        bucket[2] += weight * score
    values = [
        round(weighted / weights, 4) if count >= C.TREND_MIN_EVENTS and weights > 0 else None
        for count, weights, weighted in weeks
    ]
    return list(reversed(values))


def node_event_sets(node, events_by_concept):
    """{node id: set of event indexes} over each node's leaf concepts."""
    found = {}
    _collect(node, events_by_concept, found)
    return found


def _collect(node, events_by_concept, found):
    if node['level'] in LEAF_LEVELS:
        indexes = set(events_by_concept.get(node.get('concept_id'), ()))
    else:
        indexes = set()
        for child in node.get('children') or []:
            indexes |= _collect(child, events_by_concept, found)
    found[str(node['id'])] = indexes
    return indexes


def topic_lists(subjects):
    """(weak, strong): the weakest and strongest topics across subjects."""
    topics = [
        {
            'id': node['id'], 'name': node['name'], 'subject': subject['name'],
            'mastery': node['mastery'], 'evidence': node['evidence'],
            'coverage': node['coverage'], 'status': node['status'],
            'concept_ids': node['concept_ids'],
        }
        for subject in subjects
        for node in iter_nodes(subject)
        if node['level'] == 'topic'
    ]
    weak = sorted((t for t in topics if t['status'] == 'weak'),
                  key=lambda t: (t['mastery'], t['name']))
    strong = sorted((t for t in topics if t['status'] == 'strong'),
                    key=lambda t: (-t['mastery'], t['name']))
    return weak[:C.TOP_TOPICS], strong[:C.TOP_TOPICS]


# ── Database ─────────────────────────────────────────────────────────────────
```

(Task 4 fills in the database section.)

- [ ] **Step 4: Run tests**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_progress_rules -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/intelligence/services/rollup.py backend/intelligence/tests/test_progress_rules.py
git commit -m "feat(intelligence): pure mastery roll-up, trend and topic lists"
```

---

### Task 4: Roll-up from the database

**Files:**
- Modify: `backend/intelligence/services/rollup.py` (database section)
- Create: `backend/intelligence/tests/progress_fixtures.py`
- Test: `backend/intelligence/tests/test_rollup.py`

**Interfaces:**
- Produces (`rollup.py`):
  - `course_structure(course) -> [{'subject': Subject, 'has_tree': bool, 'node': subject node}]`, subjects in `order`, `name` order;
  - `leaf_concept_ids(node) -> set`;
  - `rollup_for(student, course, *, now=None, with_trend=True) -> [subject payload + 'has_tree']`.
- Produces (`tests/progress_fixtures.py`): `ProgressTestCase(VisibilityTestCase)` with features `ALL_ON + my_progress`; a tree under `subject` (`mechanics` sub-subject; topics `kinematics` (0.6) and `dynamics` (0.4); subtopics `velocity`, `projectile`, `relative` under kinematics and `friction` under dynamics, each with a Concept in `concepts[name]`); a second subject `optics` with no tree; helpers `node(...)`, `concept(name, subject=None)`, `set_state(concept, mastery, evidence, student=None)`, `link(question, concept)`, `event(question, *, score, days_ago, attempt=None, student=None, source='quiz_answer')`, `hand_states()` (the Task 3 numbers).
- Consumes: Task 3, `VisibilityTestCase` (Part A).

- [ ] **Step 1: Write the fixture**

Create `backend/intelligence/tests/progress_fixtures.py`:

```python
"""Shared fixtures for the My Progress tests: Part A's tenant, staff and
students, plus a small syllabus tree on ``subject`` and a second subject
(``optics``) without a tree."""
import uuid
from datetime import timedelta

from django.utils import timezone

from exams.models import Subject
from intelligence.models import (
    Concept, ConceptLink, LearnerConceptState, LearningEvent, SyllabusNode,
)
from intelligence.tests.visibility_fixtures import ALL_ON, VisibilityTestCase

PROGRESS_ON = {**ALL_ON, 'my_progress': True}


class ProgressTestCase(VisibilityTestCase):
    features = PROGRESS_ON

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.concepts = {}
        cls.mechanics = cls.node('mechanics', 'Mechanics', 'sub_subject')
        cls.kinematics = cls.node('kinematics', 'Kinematics', 'topic', cls.mechanics, weightage=0.6)
        cls.dynamics = cls.node('dynamics', 'Dynamics', 'topic', cls.mechanics, weightage=0.4)
        cls.velocity = cls.node('velocity', 'Velocity', 'subtopic', cls.kinematics)
        cls.projectile = cls.node('projectile', 'Projectile motion', 'subtopic', cls.kinematics)
        cls.relative = cls.node('relative', 'Relative motion', 'subtopic', cls.kinematics)
        cls.friction = cls.node('friction', 'Friction', 'subtopic', cls.dynamics)
        cls.optics = Subject.objects.create(
            tenant=cls.tenant, course=cls.course, name='Optics', code='vis-optics', order=1,
        )

    @classmethod
    def concept(cls, name, subject=None):
        concept = Concept.objects.create(
            tenant=cls.tenant, subject=subject or cls.subject, name=name.title(),
            slug=f'progress-{name}',
        )
        cls.concepts[name] = concept
        return concept

    @classmethod
    def node(cls, key, name, level, parent=None, *, weightage=0.0, status='active',
             in_syllabus=True, order=0):
        return SyllabusNode.objects.create(
            tenant=cls.tenant, subject=cls.subject, parent=parent, level=level,
            key=f'phy.{key}', name=name, weightage=weightage, status=status,
            in_syllabus=in_syllabus, order=order,
            concept=cls.concept(key) if level == 'subtopic' else None,
        )

    def set_state(self, concept, mastery, evidence, student=None):
        return LearnerConceptState.objects.create(
            tenant=self.tenant, student=student or self.student, concept=concept,
            mastery=mastery, evidence_count=max(1, round(evidence)),
            effective_evidence=evidence, computed_at=timezone.now(),
        )

    def hand_states(self, student=None):
        """The Task 3 fixture numbers: velocity 0.9/6, projectile 0.3/2,
        friction 0.4/4, relative motion untouched."""
        self.set_state(self.concepts['velocity'], 0.9, 6.0, student)
        self.set_state(self.concepts['projectile'], 0.3, 2.0, student)
        self.set_state(self.concepts['friction'], 0.4, 4.0, student)

    def link(self, question, concept):
        return ConceptLink.objects.create(
            tenant=self.tenant, concept=concept, question=question, source='generator',
        )

    def event(self, question, *, score, days_ago=0, attempt=None, student=None,
              source='quiz_answer', now=None):
        occurred = (now or timezone.now()) - timedelta(days=days_ago)
        return LearningEvent.objects.create(
            tenant=self.tenant, student=student or self.student, source_type=source,
            question=question, attempt_kind='quiz' if attempt else '',
            attempt_id=attempt.id if attempt else None, subject=question.subject,
            occurred_at=occurred, is_correct=score >= 1.0, score_fraction=score,
            dedup_key=f'{source}:{uuid.uuid4()}:0',
        )
```

- [ ] **Step 2: Write the failing test**

Create `backend/intelligence/tests/test_rollup.py`:

```python
"""My Progress roll-up from real rows (spec 2B §6.1)."""
from exams.models import Topic
from intelligence.models import Concept, LearningEvent
from intelligence.services import rollup
from intelligence.tests.progress_fixtures import ProgressTestCase


def find(payload, node_id):
    return next(node for node in rollup.iter_nodes(payload) if node['id'] == str(node_id))


class TreeRollupTests(ProgressTestCase):
    def test_matches_the_hand_computed_tree(self):
        self.hand_states()
        physics, optics = rollup.rollup_for(self.student, self.course)
        self.assertTrue(physics['has_tree'])
        self.assertEqual(physics['level'], 'subject')
        self.assertEqual(physics['mastery'], 0.6625)
        self.assertEqual(physics['coverage'], 0.75)
        self.assertEqual(find(physics, self.kinematics.id)['mastery'], 0.75)
        self.assertEqual(find(physics, self.dynamics.id)['status'], 'weak')
        self.assertIsNone(find(physics, self.projectile.id)['mastery'])
        self.assertFalse(optics['has_tree'])

    def test_other_students_states_do_not_leak(self):
        self.hand_states(student=self.outsider)
        physics = rollup.rollup_for(self.student, self.course)[0]
        self.assertEqual(physics['evidence'], 0.0)

    def test_proposed_counts_archived_and_out_of_syllabus_do_not(self):
        self.hand_states()
        proposed = self.node('waves', 'Waves', 'subtopic', self.kinematics, status='proposed')
        archived = self.node('old', 'Old', 'subtopic', self.kinematics, status='archived')
        outside = self.node('extra', 'Extra', 'subtopic', self.kinematics, in_syllabus=False)
        hidden_topic = self.node('hidden', 'Hidden', 'topic', self.mechanics, status='archived')
        under_hidden = self.node('under', 'Under', 'subtopic', hidden_topic)
        for node in (proposed, archived, outside, under_hidden):
            self.set_state(node.concept, 0.1, 5.0)
        physics = rollup.rollup_for(self.student, self.course)[0]
        kinematics = find(physics, self.kinematics.id)
        self.assertEqual(kinematics['total'], 4)
        ids = {node['id'] for node in rollup.iter_nodes(physics)}
        self.assertIn(str(proposed.id), ids)
        self.assertFalse(ids & {str(archived.id), str(outside.id), str(under_hidden.id)})


class FallbackTests(ProgressTestCase):
    def test_subject_topic_concept_without_a_tree(self):
        lenses = Topic.objects.create(tenant=self.tenant, subject=self.optics, name='Lenses',
                                      code='lenses')
        mirrors = Topic.objects.create(tenant=self.tenant, subject=self.optics, name='Mirrors',
                                       code='mirrors', order=1)
        focal = self.concept('focal', subject=self.optics)
        image = self.concept('image', subject=self.optics)
        loose = self.concept('loose', subject=self.optics)
        focal.topics.add(lenses)
        image.topics.add(lenses, mirrors)
        Concept.objects.create(tenant=self.tenant, subject=self.optics, name='Gone',
                               slug='progress-gone', status='merged')
        self.set_state(focal, 0.9, 6.0)
        self.set_state(image, 0.3, 2.0)

        optics = rollup.rollup_for(self.student, self.course)[1]
        self.assertFalse(optics['has_tree'])
        self.assertEqual([t['name'] for t in optics['children']],
                         ['Lenses', 'Mirrors', 'Other concepts'])
        lenses_row, mirrors_row, other = optics['children']
        self.assertEqual(lenses_row['mastery'], 0.75)          # (6×0.9 + 2×0.3) / 8
        self.assertEqual(mirrors_row['status'], 'not_enough_data')
        self.assertEqual(mirrors_row['coverage'], 1.0)
        self.assertEqual([c['name'] for c in other['children']], [loose.name])
        self.assertTrue(all(c['level'] == 'concept' for c in lenses_row['children']))


class TrendTests(ProgressTestCase):
    def setUp(self):
        self.question = self.make_question(1)
        self.link(self.question, self.concepts['velocity'])

    def test_trend_weighs_diagnoses(self):
        attempt = self.quiz_attempt(self.student)
        self.event(self.question, score=1.0, days_ago=1)
        self.event(self.question, score=0.0, days_ago=2, attempt=attempt)
        self.diagnose(attempt, self.question, 'guess')            # weight 0.2
        self.event(self.question, score=1.0, days_ago=10)         # alone in week 1

        physics = rollup.rollup_for(self.student, self.course)[0]
        # week 0: (1×1 + 0×0.2) / 1.2 = 0.8333
        self.assertEqual(find(physics, self.velocity.id)['trend_4w'], [None, None, None, 0.8333])
        self.assertEqual(find(physics, self.kinematics.id)['trend_4w'], [None, None, None, 0.8333])
        self.assertEqual(find(physics, self.dynamics.id)['trend_4w'], [None] * 4)

    def test_a_regrade_replaces_the_original_answer(self):
        right = self.event(self.question, score=1.0, days_ago=1)
        self.event(self.question, score=1.0, days_ago=2)
        LearningEvent.objects.create(
            tenant=self.tenant, student=self.student, source_type='quiz_answer',
            question=self.question, subject=self.question.subject,
            occurred_at=right.occurred_at, is_correct=False, score_fraction=0.0,
            event_kind='regraded',
            dedup_key=right.dedup_key.rsplit(':', 1)[0] + ':1700000000',
        )
        physics = rollup.rollup_for(self.student, self.course)[0]
        # week 0: the regrade (0.0) and the day-2 answer (1.0) → 0.5
        self.assertEqual(find(physics, self.velocity.id)['trend_4w'], [None, None, None, 0.5])

    def test_without_trend(self):
        physics = rollup.rollup_for(self.student, self.course, with_trend=False)[0]
        self.assertEqual(physics['trend_4w'], [None] * 4)
```

- [ ] **Step 3: Run it to verify it fails**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_rollup -v 2`
Expected: FAIL (`module 'intelligence.services.rollup' has no attribute 'rollup_for'`).

- [ ] **Step 4: Implement the database section**

Append to `backend/intelligence/services/rollup.py`, under the `# ── Database` line:

```python
def _tree_children(subject):
    """The subject's live, in-syllabus nodes as nested node dicts."""
    from intelligence.models import SyllabusNode

    nodes = (
        SyllabusNode.objects.filter(subject=subject, status__in=LIVE_STATUSES, in_syllabus=True)
        .order_by('order', 'name')
    )
    by_parent = defaultdict(list)
    for node in nodes:
        by_parent[node.parent_id].append(node)

    def build(node):
        return {
            'id': node.id, 'name': node.name, 'level': node.level,
            'weightage': node.weightage, 'concept_id': node.concept_id,
            'children': [build(child) for child in by_parent.get(node.id, [])],
        }

    # Walking down from the roots drops anything under an excluded parent.
    return [build(node) for node in by_parent.get(None, [])]


def _has_subtopic(node):
    return node['level'] == 'subtopic' or any(_has_subtopic(c) for c in node['children'])


def _fallback_children(subject):
    """subject → course Topic → Concept, from ``Concept.topics``."""
    from intelligence.models import Concept

    concepts = (
        Concept.objects.filter(subject=subject, status='active')
        .prefetch_related('topics').order_by('name')
    )
    groups, loose = {}, []
    for concept in concepts:
        topics = [topic for topic in concept.topics.all() if topic.subject_id == subject.id]
        if not topics:
            loose.append(concept)
        for topic in topics:
            groups.setdefault(topic.id, (topic, []))[1].append(concept)

    def leaf(concept):
        return {'id': concept.id, 'name': concept.name, 'level': 'concept',
                'weightage': 0.0, 'concept_id': concept.id, 'children': []}

    children = [
        {'id': topic.id, 'name': topic.name, 'level': 'topic', 'weightage': 0.0,
         'children': [leaf(concept) for concept in members]}
        for topic, members in sorted(groups.values(), key=lambda pair: (pair[0].order, pair[0].name))
    ]
    if loose:
        children.append({
            'id': f'other:{subject.id}', 'name': 'Other concepts', 'level': 'topic',
            'weightage': 0.0, 'children': [leaf(concept) for concept in loose],
        })
    return children


def course_structure(course):
    """Each course subject as a node tree: its syllabus tree when it has a
    live subtopic, else the Topic → Concept fallback."""
    structures = []
    for subject in course.subjects.order_by('order', 'name'):
        children = _tree_children(subject)
        has_tree = any(_has_subtopic(child) for child in children)
        if not has_tree:
            children = _fallback_children(subject)
        structures.append({
            'subject': subject,
            'has_tree': has_tree,
            'node': {'id': subject.id, 'name': subject.name, 'level': 'subject',
                     'weightage': 0.0, 'children': children},
        })
    return structures


def leaf_concept_ids(node):
    if node['level'] in LEAF_LEVELS:
        return {node['concept_id']} if node.get('concept_id') else set()
    ids = set()
    for child in node.get('children') or []:
        ids |= leaf_concept_ids(child)
    return ids


def _trend_events(student, concept_ids, now):
    """(points, {concept_id: [point index]}) for the student's latest answers
    on these concepts inside the trend window."""
    from intelligence.models import ConceptLink, LearningEvent
    from intelligence.services.state import (
        PRACTICE_WEIGHT, _diagnosis_key, _diagnosis_weights, _items_condition,
    )

    concepts_by_item = defaultdict(set)
    for concept_id, question_id, mock_item_id in ConceptLink.objects.filter(
            concept_id__in=concept_ids).values_list('concept_id', 'question_id', 'mock_item_id'):
        key = ('q', question_id) if question_id else ('m', mock_item_id)
        concepts_by_item[key].add(concept_id)
    if not concepts_by_item:
        return [], {}

    question_ids = [item_id for arm, item_id in concepts_by_item if arm == 'q']
    mock_item_ids = [item_id for arm, item_id in concepts_by_item if arm == 'm']
    newest = list(
        LearningEvent.objects.filter(
            student=student, occurred_at__gte=now - WEEK * C.TREND_WEEKS, occurred_at__lte=now,
        ).filter(_items_condition(question_ids, mock_item_ids))
        .order_by('-occurred_at', '-created_at')[:C.TREND_MAX_EVENTS]
    )
    latest = {}
    for event in reversed(newest):   # oldest first, so a regrade wins
        latest[event.dedup_key.rsplit(':', 1)[0]] = event

    diagnosis = _diagnosis_weights(student, latest.values())
    points, by_concept = [], defaultdict(list)
    for event in latest.values():
        key = ('q', event.question_id) if event.question_id else ('m', event.mock_item_id)
        source = PRACTICE_WEIGHT if event.source_type == LearningEvent.SOURCE_PRACTICE_ANSWER else 1.0
        points.append((
            event.occurred_at,
            max(0.0, min(1.0, event.score_fraction)),
            source * diagnosis.get(_diagnosis_key(event), 1.0),
        ))
        for concept_id in concepts_by_item.get(key, ()):
            by_concept[concept_id].append(len(points) - 1)
    return points, by_concept


def rollup_for(student, course, *, now=None, with_trend=True):
    """The student's roll-up for one course: one payload per subject."""
    from intelligence.models import LearnerConceptState

    now = now or timezone.now()
    structures = course_structure(course)
    concept_ids = set()
    for structure in structures:
        concept_ids |= leaf_concept_ids(structure['node'])
    states = {
        concept_id: (mastery, evidence)
        for concept_id, mastery, evidence in LearnerConceptState.objects.filter(
            student=student, concept_id__in=concept_ids,
        ).values_list('concept_id', 'mastery', 'effective_evidence')
    }

    trends = {}
    if with_trend and concept_ids:
        points, by_concept = _trend_events(student, concept_ids, now)
        for structure in structures:
            for node_id, indexes in node_event_sets(structure['node'], by_concept).items():
                trends[node_id] = weekly_trend([points[i] for i in indexes], now)

    subjects = []
    for structure in structures:
        payload = rollup_node(structure['node'], states, trends)
        payload['has_tree'] = structure['has_tree']
        subjects.append(payload)
    return subjects
```

- [ ] **Step 5: Run tests**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_rollup intelligence.tests.test_progress_rules -v 2`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/intelligence/services/rollup.py backend/intelligence/tests/progress_fixtures.py backend/intelligence/tests/test_rollup.py
git commit -m "feat(intelligence): course roll-up from states, trees and the topic fallback"
```

---

### Task 5: Facet recompute and profiles

**Files:**
- Create: `backend/intelligence/services/facets.py`
- Test: `backend/intelligence/tests/test_facets.py` (add classes)

**Interfaces:**
- Produces (`facets.py`):
  - `facets_enabled(tenant) -> bool` (the tenant's effective `my_progress`);
  - `facet_observations(student) -> {(subject_id, kind, key): [state._Observation]}`;
  - `compute_facet_fields(observations, now=None) -> dict | None`;
  - `recompute_facets(student, now=None) -> int` (rows written; rows no longer backed by events are deleted);
  - `update_for_attempt(kind, attempt_id) -> int` (0 when the tenant has `my_progress` off);
  - `profile_for(student, course) -> [{'subject_id', 'subject', 'status': 'ok' | 'needs_tagging', 'skills': [facet], 'thinking_levels': [facet]}]`, a facet being `{'key', 'label', 'mastery', 'evidence', 'confidence', 'status'}`.
- Consumes: `state.compute_state_fields`, `state._Observation`, `state._diagnosis_weights`, `state._diagnosis_key`, `state._items_condition`, `state.PRACTICE_WEIGHT`; `rollup.classify`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/intelligence/tests/test_facets.py`:

```python
from django.utils import timezone

from intelligence.models import ItemSkillTag, ItemTagging, TagDefinition
from intelligence.services import facets
from intelligence.tests.progress_fixtures import ProgressTestCase


class FacetFixture(ProgressTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.vectors = TagDefinition.objects.create(
            kind='skill', key='vector_resolution', label='Vector resolution', definition='-')
        cls.units = TagDefinition.objects.create(
            kind='skill', key='unit_conversion', label='Unit conversion', definition='-')
        TagDefinition.objects.create(
            kind='thinking_level', key='apply', label='Apply', definition='-', order=2)

    def setUp(self):
        self.now = timezone.now()

    def tagged_question(self, n, *, skills=(), thinking='apply', node=None):
        question = self.make_question(n)
        ItemTagging.objects.create(
            tenant=self.tenant, question=question, primary_node=node or self.velocity,
            thinking_level=thinking, confidence=0.9,
        )
        for skill, role in skills:
            ItemSkillTag.objects.create(tenant=self.tenant, question=question, skill=skill, role=role)
        return question

    def rows(self):
        return {(row.kind, row.key): row for row in self.student.facet_states.all()}


class RecomputeTests(FacetFixture):
    def test_core_supporting_and_thinking_level_weights(self):
        question = self.tagged_question(
            1, skills=[(self.vectors, 'core'), (self.units, 'supporting')])
        self.event(question, score=1.0, now=self.now)
        self.assertEqual(facets.recompute_facets(self.student, now=self.now), 3)
        rows = self.rows()
        # prior 3 pseudo-answers at 0.5: core (1 + 1.5) / (1 + 3) = 0.625
        self.assertAlmostEqual(rows[('skill', 'vector_resolution')].mastery, 0.625, places=4)
        # supporting, weight 0.5: (0.5 + 1.5) / (0.5 + 3) = 0.5714
        self.assertAlmostEqual(rows[('skill', 'unit_conversion')].mastery, 0.5714, places=4)
        self.assertAlmostEqual(rows[('skill', 'unit_conversion')].effective_evidence, 0.5)
        self.assertAlmostEqual(rows[('thinking_level', 'apply')].mastery, 0.625, places=4)
        row = rows[('skill', 'vector_resolution')]
        self.assertEqual((row.subject, row.tenant, row.model_version), (self.subject, self.tenant, '1'))

    def test_diagnosis_down_weights_a_guess(self):
        question = self.tagged_question(1, skills=[(self.vectors, 'core')], thinking='')
        attempt = self.quiz_attempt(self.student)
        self.event(question, score=1.0, attempt=attempt, now=self.now)
        self.diagnose(attempt, question, 'correct_lucky')       # weight 0.2
        facets.recompute_facets(self.student, now=self.now)
        # (0.2 + 1.5) / (0.2 + 3) = 0.53125
        self.assertAlmostEqual(self.rows()[('skill', 'vector_resolution')].mastery, 0.53125, places=4)
        self.assertNotIn(('thinking_level', ''), self.rows())

    def test_old_evidence_decays(self):
        question = self.tagged_question(1, skills=[(self.vectors, 'core')])
        self.event(question, score=1.0, days_ago=60, now=self.now)   # two half-lives: 0.25
        facets.recompute_facets(self.student, now=self.now)
        row = self.rows()[('skill', 'vector_resolution')]
        self.assertAlmostEqual(row.effective_evidence, 0.25, places=4)
        self.assertAlmostEqual(row.mastery, 1.75 / 3.25, places=4)

    def test_practice_answers_count_at_practice_weight(self):
        question = self.tagged_question(1, skills=[(self.vectors, 'core')])
        self.event(question, score=1.0, source='practice_answer', now=self.now)
        facets.recompute_facets(self.student, now=self.now)
        self.assertAlmostEqual(
            self.rows()[('skill', 'vector_resolution')].effective_evidence, 0.6, places=4)

    def test_recompute_is_idempotent_and_drops_stale_rows(self):
        question = self.tagged_question(1, skills=[(self.vectors, 'core')])
        self.event(question, score=1.0, now=self.now)
        facets.recompute_facets(self.student, now=self.now)
        first = self.rows()[('skill', 'vector_resolution')].mastery
        facets.recompute_facets(self.student, now=self.now)
        self.assertEqual(self.rows()[('skill', 'vector_resolution')].mastery, first)
        ItemSkillTag.objects.filter(question=question).delete()
        facets.recompute_facets(self.student, now=self.now)
        self.assertNotIn(('skill', 'vector_resolution'), self.rows())

    def test_untagged_items_add_nothing(self):
        self.event(self.make_question(1), score=1.0, now=self.now)
        self.assertEqual(facets.recompute_facets(self.student, now=self.now), 0)

    def test_update_for_attempt_needs_my_progress(self):
        question = self.tagged_question(1, skills=[(self.vectors, 'core')])
        attempt = self.quiz_attempt(self.student)
        self.event(question, score=1.0, attempt=attempt, now=self.now)
        self.assertEqual(facets.update_for_attempt('quiz', str(attempt.id)), 2)
        self.student.facet_states.all().delete()
        self.tenant.features = {'response_diagnosis': True}
        self.tenant.save()
        self.assertEqual(facets.update_for_attempt('quiz', str(attempt.id)), 0)
        self.assertFalse(self.student.facet_states.exists())


class ProfileTests(FacetFixture):
    def test_tagged_subject_lists_facets_and_untagged_needs_tagging(self):
        question = self.tagged_question(1, skills=[(self.vectors, 'core')])
        for _ in range(3):
            self.event(question, score=1.0, now=self.now)
        facets.recompute_facets(self.student, now=self.now)
        mechanics, optics = facets.profile_for(self.student, self.course)
        self.assertEqual(optics, {
            'subject_id': str(self.optics.id), 'subject': 'Optics',
            'status': 'needs_tagging', 'skills': [], 'thinking_levels': [],
        })
        self.assertEqual(mechanics['status'], 'ok')
        skill = mechanics['skills'][0]
        self.assertEqual(skill['label'], 'Vector resolution')
        self.assertEqual(skill['mastery'], 0.75)                # (3 + 1.5) / (3 + 3)
        self.assertEqual(skill['status'], 'in_progress')
        self.assertEqual(mechanics['thinking_levels'][0]['label'], 'Apply')

    def test_thin_facets_show_no_mastery(self):
        question = self.tagged_question(1, skills=[(self.vectors, 'core')])
        self.event(question, score=1.0, now=self.now)
        facets.recompute_facets(self.student, now=self.now)
        skill = facets.profile_for(self.student, self.course)[0]['skills'][0]
        self.assertIsNone(skill['mastery'])
        self.assertEqual(skill['status'], 'not_enough_data')
```

- [ ] **Step 2: Run them to verify they fail**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_facets -v 2`
Expected: ImportError (`cannot import name 'facets'`).

- [ ] **Step 3: Implement**

Create `backend/intelligence/services/facets.py`:

```python
"""Skill and thinking-level profiles (spec 2B §6.3).

LearnerFacetState is recomputed from the student's graded LearningEvents,
like LearnerConceptState and with the same decay, prior, diagnosis weighting
and confidence rules (it calls ``state.compute_state_fields``):

- an answered item counts towards each of its ItemSkillTags, at 1.0 for a
  core skill and 0.5 for a supporting one;
- and towards its ItemTagging.thinking_level, at 1.0.

A contribution belongs to the subject of the item's syllabus node
(``ItemTagging.primary_node``), else the event's subject snapshot.
Recompute is per student and idempotent, and runs only for tenants with
``my_progress`` on.
"""
from collections import defaultdict

from django.db.models import Q
from django.utils import timezone

from intelligence import progress_config as C
from intelligence.models import ItemSkillTag, ItemTagging, LearnerFacetState, LearningEvent
from intelligence.services import state
from intelligence.versions import FACET_MODEL_VERSION

KINDS = (LearnerFacetState.KIND_SKILL, LearnerFacetState.KIND_THINKING)
FIELDS = ('mastery', 'evidence_count', 'effective_evidence', 'confidence', 'computed_at')


def facets_enabled(tenant):
    """True when the tenant has My Progress on. Never raises."""
    try:
        return bool(tenant and tenant.get_features().get('my_progress'))
    except Exception:  # noqa: BLE001 — a broken features blob counts as off
        return False


def _item_key(event):
    return ('q', event.question_id) if event.question_id else ('m', event.mock_item_id)


def _latest_events(student):
    """Latest graded event per source answer, oldest first."""
    latest = {}
    for event in (
        LearningEvent.objects.filter(student=student)
        .filter(Q(question__isnull=False) | Q(mock_item__isnull=False))
        .order_by('occurred_at', 'created_at')
    ):
        latest[event.dedup_key.rsplit(':', 1)[0]] = event
    return list(latest.values())


def _item_tags(keys):
    """({item: tagging values}, {item: [(skill key, role)]}) for these items."""
    question_ids = [item_id for arm, item_id in keys if arm == 'q']
    mock_item_ids = [item_id for arm, item_id in keys if arm == 'm']
    condition = state._items_condition(question_ids, mock_item_ids)
    taggings = {}
    for row in ItemTagging.objects.filter(condition).values(
            'question_id', 'mock_item_id', 'thinking_level', 'primary_node__subject_id'):
        key = ('q', row['question_id']) if row['question_id'] else ('m', row['mock_item_id'])
        taggings[key] = row
    skills = defaultdict(list)
    for question_id, mock_item_id, skill_key, role in ItemSkillTag.objects.filter(condition).values_list(
            'question_id', 'mock_item_id', 'skill__key', 'role'):
        skills[('q', question_id) if question_id else ('m', mock_item_id)].append((skill_key, role))
    return taggings, skills


def facet_observations(student):
    """{(subject_id, kind, key): [observation]} from the student's latest answers."""
    events = _latest_events(student)
    if not events:
        return {}
    taggings, skills = _item_tags({_item_key(event) for event in events})
    diagnosis = state._diagnosis_weights(student, events)

    groups = defaultdict(list)
    for event in events:
        key = _item_key(event)
        tagging = taggings.get(key)
        item_skills = skills.get(key, [])
        if tagging is None and not item_skills:
            continue
        subject_id = (tagging or {}).get('primary_node__subject_id') or event.subject_id
        if subject_id is None:
            continue
        source = (state.PRACTICE_WEIGHT
                  if event.source_type == LearningEvent.SOURCE_PRACTICE_ANSWER else 1.0)
        base = source * diagnosis.get(state._diagnosis_key(event), 1.0)
        contributions = [
            (LearnerFacetState.KIND_SKILL, skill_key, C.SKILL_ROLE_WEIGHTS.get(role, 0.5))
            for skill_key, role in item_skills
        ]
        if tagging and tagging['thinking_level']:
            contributions.append(
                (LearnerFacetState.KIND_THINKING, tagging['thinking_level'], C.THINKING_LEVEL_WEIGHT))
        for kind, facet_key, weight in contributions:
            groups[(subject_id, kind, facet_key)].append(state._Observation(
                occurred_at=event.occurred_at,
                score=max(0.0, min(1.0, event.score_fraction)),
                link_weight=base * weight,
                is_multi=False,
                item_ref=str(key[1]),
            ))
    return groups


def compute_facet_fields(observations, now=None):
    fields = state.compute_state_fields(observations, now=now)
    if fields is None:
        return None
    return {**{name: fields[name] for name in FIELDS}, 'model_version': FACET_MODEL_VERSION}


def recompute_facets(student, now=None):
    """Recompute every facet row of one student; returns rows written."""
    now = now or timezone.now()
    tenant = student.user.tenant
    kept = []
    for (subject_id, kind, key), observations in facet_observations(student).items():
        fields = compute_facet_fields(observations, now=now)
        if fields is None:
            continue
        row, _created = LearnerFacetState.objects.update_or_create(
            student=student, subject_id=subject_id, kind=kind, key=key,
            defaults={'tenant': tenant, **fields},
        )
        kept.append(row.id)
    LearnerFacetState.objects.filter(student=student).exclude(id__in=kept).delete()
    return len(kept)


def update_for_attempt(kind, attempt_id):
    """Recompute the attempt's student's facets when My Progress is on."""
    from quiz.models import MockTestAttempt, QuizAttempt

    model = QuizAttempt if kind == 'quiz' else MockTestAttempt
    attempt = model.objects.filter(id=attempt_id).select_related('student__user__tenant').first()
    if attempt is None or not facets_enabled(attempt.student.user.tenant):
        return 0
    return recompute_facets(attempt.student)


def profile_for(student, course):
    """Skill and thinking-level rows per course subject (spec 2B §6.3)."""
    from intelligence.models import TagDefinition
    from intelligence.services.rollup import classify

    subjects = list(course.subjects.order_by('order', 'name'))
    tagged = set(
        ItemTagging.objects.filter(primary_node__subject__in=subjects)
        .values_list('primary_node__subject_id', flat=True).distinct()
    )
    definitions = {
        (kind, key): (label, order)
        for kind, key, label, order in TagDefinition.objects.filter(kind__in=KINDS)
        .values_list('kind', 'key', 'label', 'order')
    }
    rows = defaultdict(list)
    for row in LearnerFacetState.objects.filter(student=student, subject__in=subjects):
        rows[(row.subject_id, row.kind)].append(row)

    def facet(row):
        status = classify(row.mastery, row.effective_evidence)
        label = definitions.get((row.kind, row.key), (row.key.replace('_', ' ').capitalize(), 0))[0]
        return {
            'key': row.key, 'label': label,
            'mastery': round(row.mastery, 4) if status != 'not_enough_data' else None,
            'evidence': round(row.effective_evidence, 4),
            'confidence': row.confidence, 'status': status,
        }

    def definition_order(row):
        return (definitions.get((row.kind, row.key), ('', 999))[1], row.key)

    profiles = []
    for subject in subjects:
        base = {'subject_id': str(subject.id), 'subject': subject.name}
        if subject.id not in tagged:
            profiles.append({**base, 'status': 'needs_tagging', 'skills': [], 'thinking_levels': []})
            continue
        skills = sorted(rows[(subject.id, LearnerFacetState.KIND_SKILL)],
                        key=lambda row: (-row.effective_evidence, row.key))
        levels = sorted(rows[(subject.id, LearnerFacetState.KIND_THINKING)], key=definition_order)
        profiles.append({
            **base, 'status': 'ok',
            'skills': [facet(row) for row in skills],
            'thinking_levels': [facet(row) for row in levels],
        })
    return profiles
```

- [ ] **Step 4: Run tests**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_facets intelligence.tests.test_state -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/intelligence/services/facets.py backend/intelligence/tests/test_facets.py
git commit -m "feat(intelligence): skill and thinking-level facets from the event log"
```

---

### Task 6: Facets in the jobs and the recompute command

**Files:**
- Modify: `backend/intelligence/tasks.py` (`diagnose_and_update_state`, `refresh_learner_state`)
- Modify: `backend/intelligence/management/commands/recompute_learner_state.py`
- Test: `backend/intelligence/tests/test_facets.py` (add one class)

**Interfaces:**
- Produces: facets recomputed after each diagnosed quiz/mock attempt, in the nightly sweep (students with answers in the last 48 h or facet rows older than 24 h, at most `FACET_REFRESH_LIMIT`), and by `recompute_learner_state` unless `--no-facets` is passed. All three skip tenants with `my_progress` off.

- [ ] **Step 1: Write the failing tests**

Append to `backend/intelligence/tests/test_facets.py`:

```python
import io
from unittest.mock import patch

from django.core.management import call_command

from intelligence.tasks import diagnose_and_update_state, refresh_learner_state


class JobTests(FacetFixture):
    def test_diagnosis_job_recomputes_facets(self):
        attempt = self.quiz_attempt(self.student)
        with patch('intelligence.services.facets.update_for_attempt', return_value=1) as hook:
            diagnose_and_update_state('quiz', str(attempt.id))
        hook.assert_called_once_with('quiz', str(attempt.id))

    def test_facet_failure_does_not_break_the_job(self):
        attempt = self.quiz_attempt(self.student)
        with patch('intelligence.services.facets.update_for_attempt', side_effect=RuntimeError):
            self.assertEqual(diagnose_and_update_state('quiz', str(attempt.id)), 0)

    def test_nightly_sweep_fills_facets_only_with_my_progress(self):
        question = self.tagged_question(1, skills=[(self.vectors, 'core')])
        self.event(question, score=1.0)
        refresh_learner_state()
        self.assertTrue(self.student.facet_states.exists())

        self.student.facet_states.all().delete()
        self.tenant.features = {'response_diagnosis': True}
        self.tenant.save()
        refresh_learner_state()
        self.assertFalse(self.student.facet_states.exists())

    def test_command_recomputes_facets_unless_told_not_to(self):
        question = self.tagged_question(1, skills=[(self.vectors, 'core')])
        self.event(question, score=1.0)
        call_command('recompute_learner_state', '--no-facets', tenant=str(self.tenant.id),
                     stdout=io.StringIO())
        self.assertFalse(self.student.facet_states.exists())
        call_command('recompute_learner_state', tenant=str(self.tenant.id), stdout=io.StringIO())
        self.assertEqual(self.student.facet_states.count(), 2)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_facets.JobTests -v 2`
Expected: FAIL (the hook is not called; the command rejects `--no-facets`).

- [ ] **Step 3: The diagnosis job**

In `backend/intelligence/tasks.py`, replace the body of `diagnose_and_update_state` after the
docstring with:

```python
    from .services import diagnose, facets, state

    try:
        diagnose.diagnose_attempt(kind, attempt_id)
    except Exception:  # noqa: BLE001
        logger.exception('intelligence.diagnose failed for %s %s', kind, attempt_id)
    if kind not in ('quiz', 'mock'):
        return 0
    try:
        updated = state.update_for_attempt(kind, attempt_id)
    except Exception:  # noqa: BLE001 — the nightly refresh catches up
        logger.exception('intelligence.update_learner_state failed for %s %s', kind, attempt_id)
        updated = 0
    try:
        facets.update_for_attempt(kind, attempt_id)
    except Exception:  # noqa: BLE001 — the nightly refresh catches up
        logger.exception('intelligence.update_facets failed for %s %s', kind, attempt_id)
    return updated
```

and add one line to its docstring: `Facets (My Progress) follow the concept states.`

- [ ] **Step 4: The nightly sweep**

In `refresh_learner_state`, insert before the final `logger.info(...)` line:

```python
    # My Progress facets: students with fresh answers, and rows due for decay.
    from core.models import Tenant
    from users.models import StudentProfile

    from .models import LearnerFacetState
    from .progress_config import FACET_REFRESH_LIMIT
    from .services import facets

    facet_tenants = {
        tenant.id for tenant in Tenant.objects.filter(id__in=enabled)
        if facets.facets_enabled(tenant)
    }
    student_ids = set(
        LearningEvent.objects.filter(created_at__gte=recent, tenant_id__in=facet_tenants)
        .values_list('student_id', flat=True).distinct()[:FACET_REFRESH_LIMIT]
    )
    student_ids |= set(
        LearnerFacetState.objects.filter(computed_at__lt=cutoff, tenant_id__in=facet_tenants)
        .values_list('student_id', flat=True).distinct()[:FACET_REFRESH_LIMIT]
    )
    profiled = 0
    for student in StudentProfile.objects.filter(
            id__in=list(student_ids)[:FACET_REFRESH_LIMIT]).select_related('user__tenant'):
        try:
            facets.recompute_facets(student)
            profiled += 1
        except Exception:  # noqa: BLE001 — one bad student must not stop the sweep
            logger.exception('nightly facet recompute failed for %s', student.id)
```

and change the final log line to:

```python
    logger.info('intelligence.refresh_learner_state: %d refreshed, %d catch-up concepts, '
                '%d facet profiles', refreshed, caught_up, profiled)
```

- [ ] **Step 5: The command**

In `backend/intelligence/management/commands/recompute_learner_state.py`:
- add `from argparse import BooleanOptionalAction` at the top;
- add to the docstring: `Also recomputes My Progress facets (tenants with it on) unless --no-facets.`;
- in `add_arguments`, add:

```python
        parser.add_argument(
            '--facets', action=BooleanOptionalAction, default=True,
            help='Also recompute skill / thinking-level facets for tenants with My Progress on '
                 '(default: on).',
        )
```

- at the end of `handle`, after the success line, add:

```python
        if not options['facets']:
            return
        from intelligence.services import facets

        profiled = 0
        student_ids = set(events.values_list('student_id', flat=True).distinct())
        for student in StudentProfile.objects.filter(id__in=student_ids).select_related('user__tenant'):
            if facets.facets_enabled(student.user.tenant):
                facets.recompute_facets(student)
                profiled += 1
        self.stdout.write(self.style.SUCCESS(f'{profiled} student facet profiles recomputed.'))
```

- [ ] **Step 6: Run tests**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_facets intelligence.tests.test_state intelligence.tests.test_diagnose intelligence.tests.test_gate -v 2`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/intelligence/tasks.py backend/intelligence/management/commands/recompute_learner_state.py backend/intelligence/tests/test_facets.py
git commit -m "feat(intelligence): recompute facets after diagnosis, nightly and from the command"
```

---

### Task 7: Progress payload, recent answers and the class heatmap

**Files:**
- Create: `backend/intelligence/services/progress.py`
- Test: `backend/intelligence/tests/test_progress_rules.py` (add one class), `backend/intelligence/tests/test_rollup.py` (add classes)

**Interfaces:**
- Produces (`progress.py`):
  - `summarize(counts) -> str` (pure; `Counter` of labels → "2 quick guesses, 1 ran out of time", most frequent first, ties in `RECENT_PHRASES` order);
  - `recent_answers(student, course) -> [{'kind', 'attempt_id', 'title', 'completed_at', 'review': 'quiz' | 'mock' | 'rich_mock', 'noted', 'summary'}]`;
  - `empty_payload() -> dict`;
  - `progress_payload(student, course, courses, *, recent) -> {'courses', 'course', 'subjects', 'weak', 'strong', 'profiles', 'recent_answers' (list or None), 'thresholds'}`;
  - `heatmap(course) -> {'course', 'students', 'capped', 'bands', 'topics': [{'id', 'name', 'subject', 'coverage', 'counts': {band: n}, 'students': {band: [{'id', 'name'}]}}]}`.
- Consumes: `rollup`, `facets.profile_for`, `visibility_config.STUDENT_NOTE_CONFIDENCE` (Part A).

- [ ] **Step 1: Write the failing tests**

Append to `backend/intelligence/tests/test_progress_rules.py`:

```python
from collections import Counter

from intelligence.services import progress


class SummaryTests(SimpleTestCase):
    def test_counts_most_first_with_plurals(self):
        counts = Counter({'time_pressure': 1, 'guess': 2})
        self.assertEqual(progress.summarize(counts), '2 quick guesses, 1 ran out of time')

    def test_ties_follow_config_order_and_singulars(self):
        counts = Counter({'careless_slip': 1, 'guess': 1, 'concept_gap': 2})
        self.assertEqual(progress.summarize(counts),
                         '2 need more practice, 1 quick guess, 1 possible slip')

    def test_empty(self):
        self.assertEqual(progress.summarize(Counter()), '')
```

Append to `backend/intelligence/tests/test_rollup.py`:

```python
from quiz.models import MockTest, MockTestAttempt, MockTestItem

from intelligence.services import progress


class RecentAnswersTests(ProgressTestCase):
    def test_counts_noted_answers_per_attempt(self):
        attempt = self.quiz_attempt(self.student, minutes_ago=30)
        questions = [self.make_question(n) for n in range(5)]
        self.diagnose(attempt, questions[0], 'guess')
        self.diagnose(attempt, questions[1], 'guess', confidence='medium')
        self.diagnose(attempt, questions[2], 'time_pressure', answered=False)
        self.diagnose(attempt, questions[3], 'careless_slip', confidence='low')   # not counted
        self.diagnose(attempt, questions[4], 'correct')                            # not counted
        older = self.quiz_attempt(self.student, minutes_ago=600)

        rows = progress.recent_answers(self.student, self.course)
        self.assertEqual([row['attempt_id'] for row in rows], [str(attempt.id), str(older.id)])
        self.assertEqual(rows[0]['summary'], '2 quick guesses, 1 ran out of time')
        self.assertEqual((rows[0]['noted'], rows[0]['review'], rows[0]['title']),
                         (3, 'quiz', 'Kinematics quiz'))
        self.assertEqual((rows[1]['noted'], rows[1]['summary']), (0, ''))

    def test_rich_mocks_and_course_filter(self):
        rich = MockTest.objects.create(tenant=self.tenant, course=self.course, title='Rich',
                                       duration_minutes=60, total_marks=4)
        MockTestItem.objects.create(tenant=self.tenant, mock_test=rich, item_type='mcq',
                                    question_text='Q?', marks=4,
                                    options=[{'text': 'A', 'is_correct': True}])
        MockTestAttempt.objects.create(student=self.student, mock_test=rich, status='completed')
        other = MockTest.objects.create(tenant=self.tenant, course=self.other_course,
                                        title='Elsewhere', duration_minutes=60, total_marks=4)
        MockTestAttempt.objects.create(student=self.student, mock_test=other, status='completed')
        MockTestAttempt.objects.create(student=self.student, mock_test=rich, status='in_progress')
        rows = progress.recent_answers(self.student, self.course)
        self.assertEqual([(row['title'], row['review']) for row in rows], [('Rich', 'rich_mock')])


class PayloadTests(ProgressTestCase):
    def test_payload_shape(self):
        self.hand_states()
        data = progress.progress_payload(self.student, self.course, [self.course], recent=False)
        self.assertEqual(data['course'], {'id': str(self.course.id), 'name': 'Physics'})
        self.assertEqual(data['courses'], [{'id': str(self.course.id), 'name': 'Physics'}])
        self.assertEqual([t['name'] for t in data['weak']], ['Dynamics'])
        self.assertEqual(data['strong'], [])
        self.assertIsNone(data['recent_answers'])
        self.assertEqual([p['status'] for p in data['profiles']], ['needs_tagging', 'needs_tagging'])
        self.assertEqual(data['thresholds'], {'weak_below': 0.5, 'strong_at': 0.8, 'min_evidence': 3})


class HeatmapTests(ProgressTestCase):
    def test_bands_and_coverage(self):
        from users.models import CourseEnrollment, User

        self.hand_states()                      # student: kinematics 0.75, dynamics 0.4
        second = User.objects.create_user(email='prog-2@example.com', password='pw-prog-2',
                                          tenant=self.tenant, role='student').profile
        CourseEnrollment.objects.create(tenant=self.tenant, student=second, course=self.course,
                                        status='approved', is_active=True)
        self.set_state(self.concepts['velocity'], 0.95, 5.0, student=second)
        self.hand_states(student=self.outsider)   # not in this course

        data = progress.heatmap(self.course)
        self.assertEqual(data['students'], 2)
        rows = {row['name']: row for row in data['topics']}
        self.assertEqual(rows['Kinematics']['counts'],
                         {'weak': 0, 'in_progress': 1, 'strong': 1, 'not_enough_data': 0})
        self.assertEqual(rows['Dynamics']['counts']['weak'], 1)
        self.assertEqual(rows['Dynamics']['counts']['not_enough_data'], 1)
        # kinematics coverage: student 2/3, second 1/3 → mean 0.5
        self.assertEqual(rows['Kinematics']['coverage'], 0.5)
        self.assertEqual(rows['Dynamics']['students']['weak'],
                         [{'id': str(self.student.id), 'name': self.student_user.email}])
        self.assertEqual(list(rows), ['Dynamics', 'Kinematics'])   # tree order: order, then name
```

(Test users have no first or last name, so `full_name` is empty and the name falls back to
the email.)

- [ ] **Step 2: Run them to verify they fail**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_progress_rules intelligence.tests.test_rollup -v 2`
Expected: ImportError (`cannot import name 'progress'`).

- [ ] **Step 3: Implement**

Create `backend/intelligence/services/progress.py`:

```python
"""My Progress payloads (spec 2B §6.4–6.5): the progress page (student and
teacher) and the class topic heatmap. Thin assembly over ``rollup`` and
``facets``; nothing here is stored.
"""
from collections import Counter, defaultdict

from django.db.models import Q

from intelligence import progress_config as C
from intelligence.services import facets, rollup


def _name(student):
    return getattr(student.user, 'full_name', '') or student.user.email


def summarize(counts):
    """Counter of labels → "2 quick guesses, 1 ran out of time"."""
    order = list(C.RECENT_PHRASES)
    parts = []
    for label, count in sorted(counts.items(), key=lambda pair: (-pair[1], order.index(pair[0]))):
        singular, plural = C.RECENT_PHRASES[label]
        parts.append(f'{count} {singular if count == 1 else plural}')
    return ', '.join(parts)


def recent_answers(student, course):
    """The student's last finished attempts in this course, each with a
    plain-language count of its noted answers. Never a bare label."""
    from quiz.models import MockTestAttempt, QuizAttempt

    from intelligence.models import ResponseDiagnosis
    from intelligence.visibility_config import STUDENT_NOTE_CONFIDENCE

    quizzes = (
        QuizAttempt.objects.filter(student=student, quiz__course=course)
        .exclude(status='in_progress').select_related('quiz')
        .order_by('-completed_at')[:C.RECENT_ATTEMPTS]
    )
    mocks = (
        MockTestAttempt.objects.filter(student=student)
        .filter(Q(mock_test__course=course) | Q(mock_test__courses=course))
        .exclude(status='in_progress').select_related('mock_test').distinct()
        .order_by('-completed_at')[:C.RECENT_ATTEMPTS]
    )
    attempts = [('quiz', attempt, attempt.quiz.title, 'quiz') for attempt in quizzes]
    attempts += [
        ('mock', attempt, attempt.mock_test.title,
         'rich_mock' if attempt.mock_test.items.exists() else 'mock')
        for attempt in mocks
    ]
    attempts.sort(key=lambda row: row[1].completed_at or row[1].started_at, reverse=True)
    attempts = attempts[:C.RECENT_ATTEMPTS]

    counts = defaultdict(Counter)
    for kind, attempt_id, label in ResponseDiagnosis.objects.filter(
        student=student, attempt_id__in=[attempt.id for _, attempt, _, _ in attempts],
        confidence__in=STUDENT_NOTE_CONFIDENCE,
    ).values_list('attempt_kind', 'attempt_id', 'final_label'):
        if label in C.RECENT_PHRASES:
            counts[(kind, attempt_id)][label] += 1

    rows = []
    for kind, attempt, title, review in attempts:
        noted = counts[(kind, attempt.id)]
        done = attempt.completed_at or attempt.started_at
        rows.append({
            'kind': kind, 'attempt_id': str(attempt.id), 'title': title,
            'completed_at': done.isoformat() if done else None, 'review': review,
            'noted': sum(noted.values()), 'summary': summarize(noted),
        })
    return rows


def _thresholds():
    return {'weak_below': C.WEAK_BELOW, 'strong_at': C.STRONG_AT, 'min_evidence': C.MIN_EVIDENCE}


def empty_payload():
    return {
        'courses': [], 'course': None, 'subjects': [], 'weak': [], 'strong': [],
        'profiles': [], 'recent_answers': None, 'thresholds': _thresholds(),
    }


def progress_payload(student, course, courses, *, recent):
    subjects = rollup.rollup_for(student, course)
    weak, strong = rollup.topic_lists(subjects)
    return {
        'courses': [{'id': str(c.id), 'name': c.name} for c in courses],
        'course': {'id': str(course.id), 'name': course.name},
        'subjects': subjects,
        'weak': weak,
        'strong': strong,
        'profiles': facets.profile_for(student, course),
        'recent_answers': recent_answers(student, course) if recent else None,
        'thresholds': _thresholds(),
    }


def heatmap(course):
    """Topic × mastery-band student counts for one course (spec 2B §6.5)."""
    from users.models import StudentProfile

    from intelligence.models import LearnerConceptState

    students = list(
        StudentProfile.objects.filter(enrollments__course=course, enrollments__status='approved')
        .select_related('user').distinct().order_by('user__email')[:C.HEATMAP_MAX_STUDENTS + 1]
    )
    capped = len(students) > C.HEATMAP_MAX_STUDENTS
    students = students[:C.HEATMAP_MAX_STUDENTS]

    structures = rollup.course_structure(course)
    concept_ids = set()
    for structure in structures:
        concept_ids |= rollup.leaf_concept_ids(structure['node'])
    states = defaultdict(dict)
    for student_id, concept_id, mastery, evidence in LearnerConceptState.objects.filter(
        student__in=students, concept_id__in=concept_ids,
    ).values_list('student_id', 'concept_id', 'mastery', 'effective_evidence'):
        states[student_id][concept_id] = (mastery, evidence)

    rows, coverage = {}, defaultdict(list)
    for structure in structures:   # seed every topic, in tree order
        for node in rollup.iter_nodes(rollup.rollup_node(structure['node'], {})):
            if node['level'] == 'topic':
                rows[node['id']] = {
                    'id': node['id'], 'name': node['name'], 'subject': structure['subject'].name,
                    'coverage': None,
                    'counts': dict.fromkeys(C.HEATMAP_BANDS, 0),
                    'students': {band: [] for band in C.HEATMAP_BANDS},
                }
    for student in students:
        for structure in structures:
            payload = rollup.rollup_node(structure['node'], states.get(student.id, {}))
            for node in rollup.iter_nodes(payload):
                if node['level'] != 'topic':
                    continue
                row = rows[node['id']]
                row['counts'][node['status']] += 1
                row['students'][node['status']].append({'id': str(student.id), 'name': _name(student)})
                if node['coverage'] is not None:
                    coverage[node['id']].append(node['coverage'])
    for topic_id, values in coverage.items():
        rows[topic_id]['coverage'] = round(sum(values) / len(values), 4)

    return {
        'course': {'id': str(course.id), 'name': course.name},
        'students': len(students),
        'capped': capped,
        'bands': list(C.HEATMAP_BANDS),
        'topics': list(rows.values()),
    }
```

- [ ] **Step 4: Run tests**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_progress_rules intelligence.tests.test_rollup -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/intelligence/services/progress.py backend/intelligence/tests/test_progress_rules.py backend/intelligence/tests/test_rollup.py
git commit -m "feat(intelligence): progress payload, recent answers and class heatmap"
```

---

### Task 8: Endpoints

**Files:**
- Modify: `backend/intelligence/views.py`, `backend/intelligence/urls.py`
- Modify: `backend/intelligence/admin_views.py`, `backend/intelligence/admin_urls.py`
- Modify: `backend/intelligence/serializers.py` (`concept_ids`)
- Test: `backend/intelligence/tests/test_progress_api.py` (add classes)

**Interfaces:**
- Produces:
  - `GET /api/v1/intelligence/my/progress/?course=` → `progress_payload` (or `empty_payload`). 403 without `my_progress` or for non-students.
  - `GET /api/v1/tenant-admin/intelligence/students/<uuid>/progress/?course=` → the same plus `'student': {id, name}`.
  - `GET /api/v1/tenant-admin/intelligence/courses/<uuid>/heatmap/` → `heatmap(course)`.
  - `ProgressFeaturePermission` and `progress_course(request, allowed)` in `views.py`.
  - `PracticeSetSerializer` field `concept_ids` (list of str).
- Consumes: `access.can_view_student`, `access.can_manage_course`, `access.teachable_course_ids`, `admin_views._forbidden`, `IsTenantAdminOrInstructor`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/intelligence/tests/test_progress_api.py`:

```python
import uuid

from intelligence.tests.progress_fixtures import ProgressTestCase

MY = '/api/v1/intelligence/my/progress/'
INSIGHTS = '/api/v1/tenant-admin/intelligence'


class MyProgressTests(ProgressTestCase):
    def test_student_gets_their_course(self):
        self.hand_states()
        response = self.client_for(self.student_user).get(MY)
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual(data['course']['id'], str(self.course.id))
        self.assertEqual(data['subjects'][0]['mastery'], 0.6625)
        self.assertEqual([t['name'] for t in data['weak']], ['Dynamics'])
        self.assertEqual(data['recent_answers'], [])

    def test_recent_answers_need_the_student_view(self):
        attempt = self.quiz_attempt(self.student)
        self.diagnose(attempt, self.make_question(1), 'guess')
        data = self.client_for(self.student_user).get(MY).json()
        self.assertEqual(data['recent_answers'][0]['summary'], '1 quick guess')
        self.assertNotIn('label', data['recent_answers'][0])
        self.tenant.features = {**self.tenant.features, 'diagnosis_student_view': False}
        self.tenant.save()
        self.assertIsNone(self.client_for(self.student_user).get(MY).json()['recent_answers'])

    def test_course_scope(self):
        client = self.client_for(self.student_user)
        self.assertEqual(client.get(MY, {'course': str(self.other_course.id)}).status_code, 403)
        self.assertEqual(client.get(MY, {'course': str(uuid.uuid4())}).status_code, 404)
        self.assertEqual(client.get(MY, {'course': 'nope'}).status_code, 404)

    def test_student_without_courses_gets_an_empty_page(self):
        from users.models import User

        loner = User.objects.create_user(email='loner@example.com', password='pw-loner-1',
                                         tenant=self.tenant, role='student')
        data = self.client_for(loner).get(MY).json()
        self.assertEqual((data['course'], data['subjects']), (None, []))

    def test_staff_have_no_progress_page(self):
        self.assertEqual(self.client_for(self.admin).get(MY).status_code, 403)


class StudentProgressTests(ProgressTestCase):
    def url(self, student):
        return f'{INSIGHTS}/students/{student.id}/progress/'

    def test_faculty_see_their_students(self):
        response = self.client_for(self.faculty).get(self.url(self.student))
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual(data['student']['id'], str(self.student.id))
        self.assertEqual(data['courses'], [{'id': str(self.course.id), 'name': 'Physics'}])
        self.assertEqual(data['recent_answers'], [])      # teacher view is on

    def test_scope(self):
        self.assertEqual(self.client_for(self.faculty).get(self.url(self.outsider)).status_code, 403)
        self.assertEqual(self.client_for(self.other_faculty).get(self.url(self.student)).status_code,
                         403)
        self.assertEqual(
            self.client_for(self.faculty).get(
                self.url(self.student), {'course': str(self.other_course.id)}).status_code,
            403)
        admin = self.client_for(self.admin).get(self.url(self.outsider))
        self.assertEqual(admin.status_code, 200)
        self.assertEqual(admin.json()['course']['id'], str(self.other_course.id))
        self.assertEqual(self.client_for(self.admin).get(
            f'{INSIGHTS}/students/{uuid.uuid4()}/progress/').status_code, 404)

    def test_students_cannot_call_it(self):
        self.assertEqual(self.client_for(self.student_user).get(self.url(self.student)).status_code,
                         403)


class HeatmapApiTests(ProgressTestCase):
    def url(self, course):
        return f'{INSIGHTS}/courses/{course.id}/heatmap/'

    def test_scope_and_payload(self):
        self.hand_states()
        response = self.client_for(self.faculty).get(self.url(self.course))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['students'], 1)
        self.assertEqual(self.client_for(self.faculty).get(self.url(self.other_course)).status_code,
                         403)
        self.assertEqual(self.client_for(self.admin).get(self.url(self.other_course)).status_code,
                         200)


class PracticeSerializerTests(ProgressTestCase):
    def test_practice_sets_carry_concept_ids(self):
        from intelligence.models import PracticeSet
        from intelligence.serializers import PracticeSetSerializer

        practice_set = PracticeSet.objects.create(
            tenant=self.tenant, student=self.student, course=self.course,
            deficit_kind='low_mastery', deficit_signature='sig',
        )
        practice_set.target_concepts.add(self.concepts['velocity'])
        self.assertEqual(PracticeSetSerializer(practice_set).data['concept_ids'],
                         [str(self.concepts['velocity'].id)])
```

- [ ] **Step 2: Run them to verify they fail**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_progress_api -v 2`
Expected: FAIL (404s from the missing routes; `KeyError: 'concept_ids'`).

- [ ] **Step 3: Student endpoint**

In `backend/intelligence/views.py`, add after `MasteryView`:

```python
class ProgressFeaturePermission(permissions.BasePermission):
    """The tenant must have My Progress on."""

    message = 'My Progress is not enabled for this academy.'

    def has_permission(self, request, view):
        tenant = getattr(request, 'tenant', None)
        return bool(tenant and tenant.get_features().get('my_progress'))


def progress_course(request, allowed):
    """Resolve ``?course=`` against the courses this viewer may pick.

    Returns ``(course, None)`` or ``(None, error response)``. Without the
    parameter the first allowed course is used, or ``(None, None)`` when
    there is none.
    """
    import uuid

    from exams.models import Course

    raw = request.query_params.get('course')
    if not raw:
        return (allowed[0] if allowed else None), None
    try:
        course_id = uuid.UUID(str(raw))
    except ValueError:
        return None, Response({'error': 'Course not found.'}, status=status.HTTP_404_NOT_FOUND)
    for course in allowed:
        if course.id == course_id:
            return course, None
    if Course.objects.filter(id=course_id, tenant=request.tenant).exists():
        return None, Response({'error': 'Not one of your courses.'},
                              status=status.HTTP_403_FORBIDDEN)
    return None, Response({'error': 'Course not found.'}, status=status.HTTP_404_NOT_FOUND)


class MyProgressView(APIView):
    """The student's own My Progress page (spec 2B §6.4)."""

    permission_classes = [permissions.IsAuthenticated, ProgressFeaturePermission]

    def get(self, request):
        from exams.models import Course

        from .services import progress

        student = _student_or_none(request)
        if student is None or getattr(request.user, 'role', '') != 'student':
            return Response({'error': 'Only students have a progress page.'},
                            status=status.HTTP_403_FORBIDDEN)
        allowed = list(
            Course.objects.filter(
                tenant=request.tenant, enrollments__student=student,
                enrollments__status='approved',
            ).distinct().order_by('name')
        )
        course, error = progress_course(request, allowed)
        if error is not None:
            return error
        if course is None:
            return Response(progress.empty_payload())
        recent = bool(request.tenant.get_features().get('diagnosis_student_view'))
        return Response(progress.progress_payload(student, course, allowed, recent=recent))
```

In `backend/intelligence/urls.py`, import `MyProgressView` and add:

```python
    path('my/progress/', MyProgressView.as_view(), name='intelligence-my-progress'),
```

- [ ] **Step 4: Teacher endpoints**

In `backend/intelligence/admin_views.py`, add to the imports:

```python
from .views import ProgressFeaturePermission, progress_course
```

and add at the end of the file:

```python
TEACHER_PROGRESS = [
    permissions.IsAuthenticated, IsTenantAdminOrInstructor, ProgressFeaturePermission,
]


class StudentProgressView(APIView):
    """One student's My Progress data for a teacher (spec 2B §6.5)."""

    permission_classes = TEACHER_PROGRESS

    def get(self, request, student_id):
        from users.models import StudentProfile

        from .services import progress

        student = StudentProfile.objects.filter(
            id=student_id, user__tenant=request.tenant,
        ).select_related('user').first()
        if student is None:
            return Response({'error': 'Student not found.'}, status=status.HTTP_404_NOT_FOUND)
        if not can_view_student(request.user, student):
            return _forbidden()
        allowed = Course.objects.filter(
            tenant=request.tenant, enrollments__student=student, enrollments__status='approved',
        )
        if request.user.role != 'admin':
            allowed = allowed.filter(id__in=teachable_course_ids(request.user))
        allowed = list(allowed.distinct().order_by('name'))
        course, error = progress_course(request, allowed)
        if error is not None:
            return error
        if course is None:
            payload = progress.empty_payload()
        else:
            recent = bool(request.tenant.get_features().get('diagnosis_teacher_view'))
            payload = progress.progress_payload(student, course, allowed, recent=recent)
        payload['student'] = {
            'id': str(student.id),
            'name': getattr(student.user, 'full_name', '') or student.user.email,
        }
        return Response(payload)


class CourseHeatmapView(APIView):
    """Class topic heatmap for one course (spec 2B §6.5)."""

    permission_classes = TEACHER_PROGRESS

    def get(self, request, course_id):
        from .services import progress

        course = _course_or_404(request, course_id)
        if course is None:
            return Response({'error': 'Course not found.'}, status=status.HTTP_404_NOT_FOUND)
        if not can_manage_course(request.user, course):
            return _forbidden()
        return Response(progress.heatmap(course))
```

In `backend/intelligence/admin_urls.py`, import both views and add:

```python
    path('students/<uuid:student_id>/progress/', StudentProgressView.as_view(),
         name='intelligence-student-progress'),
    path('courses/<uuid:course_id>/heatmap/', CourseHeatmapView.as_view(),
         name='intelligence-course-heatmap'),
```

- [ ] **Step 5: `concept_ids` on practice sets**

In `backend/intelligence/serializers.py`, `PracticeSetSerializer`:
- add `concept_ids = serializers.SerializerMethodField()` next to `concepts`;
- add `'concept_ids'` to `Meta.fields` right after `'concepts'`;
- add:

```python
    def get_concept_ids(self, practice_set):
        return [str(concept.id) for concept in practice_set.target_concepts.all()]
```

- [ ] **Step 6: Run tests**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_progress_api intelligence.tests.test_practice intelligence.tests.test_access -v 2`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/intelligence/views.py backend/intelligence/urls.py backend/intelligence/admin_views.py backend/intelligence/admin_urls.py backend/intelligence/serializers.py backend/intelligence/tests/test_progress_api.py
git commit -m "feat(intelligence): My Progress, student progress and class heatmap endpoints"
```

---

### Task 9: Opt-out regression for Part C

**Files:**
- Test: `backend/intelligence/tests/test_progress_api.py` (add one class)

- [ ] **Step 1: Write the test**

Append to `backend/intelligence/tests/test_progress_api.py`:

```python
from unittest.mock import patch

from intelligence.models import ItemSkillTag, ItemTagging, LearnerFacetState, TagDefinition


class OptOutTests(ProgressTestCase):
    """With every learning-layer switch off: no Part C endpoint is reachable,
    no facet rows appear, and the nightly sweep does no facet work."""

    features = {}

    def test_every_endpoint_is_403(self):
        urls = [
            (self.student_user, MY),
            (self.admin, f'{INSIGHTS}/students/{self.student.id}/progress/'),
            (self.admin, f'{INSIGHTS}/courses/{self.course.id}/heatmap/'),
        ]
        for user, url in urls:
            self.assertEqual(self.client_for(user).get(url).status_code, 403, url)

    def test_no_facets_without_my_progress(self):
        from intelligence.services import facets
        from intelligence.tasks import refresh_learner_state

        skill = TagDefinition.objects.create(kind='skill', key='k', label='K', definition='-')
        question = self.make_question(1)
        ItemTagging.objects.create(tenant=self.tenant, question=question,
                                   primary_node=self.velocity, thinking_level='apply')
        ItemSkillTag.objects.create(tenant=self.tenant, question=question, skill=skill, role='core')
        attempt = self.quiz_attempt(self.student)
        self.event(question, score=1.0, attempt=attempt)

        self.assertEqual(facets.update_for_attempt('quiz', str(attempt.id)), 0)
        with patch('intelligence.services.facets.recompute_facets') as recompute:
            refresh_learner_state()
        recompute.assert_not_called()
        self.assertFalse(LearnerFacetState.objects.exists())

    def test_practice_alone_does_not_turn_on_facets(self):
        from intelligence.services import facets

        self.tenant.features = {'practice': True}
        self.tenant.save()
        self.assertFalse(facets.facets_enabled(self.tenant))
        self.assertEqual(
            self.client_for(self.student_user).get(MY).status_code, 403)
```

- [ ] **Step 2: Run the whole intelligence suite**

Run: `venv/Scripts/python.exe manage.py test intelligence core quiz -v 1`
Expected: all PASS, including `test_gate` (PR #213's main-equivalence tests) and the Part A
and Part B opt-out classes.

- [ ] **Step 3: Commit**

```bash
git add backend/intelligence/tests/test_progress_api.py
git commit -m "test(intelligence): Part C endpoints and facets are inert with the layer off"
```

---

### Task 10: Frontend — shared progress view and the student page

**Files:**
- Create: `frontend/exam-frontend/src/services/progressService.js`
- Modify: `frontend/exam-frontend/src/services/insightsService.js`
- Create: `frontend/exam-frontend/src/components/progress/progressUi.jsx`
- Create: `frontend/exam-frontend/src/components/progress/RollupTree.jsx`
- Create: `frontend/exam-frontend/src/components/progress/ProfilesPanel.jsx`
- Create: `frontend/exam-frontend/src/components/progress/ProgressView.jsx`
- Create: `frontend/exam-frontend/src/pages/MyProgress.jsx`
- Modify: `frontend/exam-frontend/src/components/layout/Sidebar.jsx`, `frontend/exam-frontend/src/App.jsx`
- Modify: `frontend/exam-frontend/src/pages/Practice.jsx`

**Interfaces:**
- Produces:
  - `progressService.getMyProgress(courseId?)`;
  - `insightsService.getStudentProgress(studentId, courseId?)`, `getCourseHeatmap(courseId)`;
  - `STATUS_TEXT`, `STATUS_CLASS`, `BAR_CLASS`, `pct`, `<Sparkline points />`, `<BandBar node />` from `progressUi.jsx`;
  - `<ProgressView data onCourseChange practiceOn linkReviews />`.
- Consumes: the Task 8 payloads.

- [ ] **Step 1: Services**

Create `frontend/exam-frontend/src/services/progressService.js`:

```js
import api from './api'

export const progressService = {
  getMyProgress: async (courseId) => {
    const response = await api.get('/intelligence/my/progress/', {
      params: courseId ? { course: courseId } : {},
    })
    return response.data
  },
}
```

Append inside the `insightsService` object in `insightsService.js`:

```js
  getStudentProgress: async (studentId, courseId) => {
    const response = await api.get(`${BASE}/students/${studentId}/progress/`, {
      params: courseId ? { course: courseId } : {},
    })
    return response.data
  },

  getCourseHeatmap: async (courseId) => {
    const response = await api.get(`${BASE}/courses/${courseId}/heatmap/`)
    return response.data
  },
```

- [ ] **Step 2: Shared bits**

Create `frontend/exam-frontend/src/components/progress/progressUi.jsx`:

```jsx
// Shared presentation for My Progress (student page and teacher tab).

export const STATUS_TEXT = {
  weak: 'Needs work',
  in_progress: 'Getting there',
  strong: 'Strong',
  not_enough_data: 'Not enough data yet',
}

export const STATUS_CLASS = {
  weak: 'text-danger-600 dark:text-danger-400',
  in_progress: 'text-warning-600 dark:text-warning-400',
  strong: 'text-success-600 dark:text-success-400',
  not_enough_data: 'text-surface-400',
}

export const BAR_CLASS = {
  weak: 'bg-danger-500',
  in_progress: 'bg-warning-500',
  strong: 'bg-success-500',
  not_enough_data: 'bg-surface-300 dark:bg-surface-600',
}

export const pct = (value) => (value == null ? '—' : `${Math.round(value * 100)}%`)

/** Four weekly points (nulls skipped) as a small line. */
export function Sparkline({ points }) {
  const coords = (points || [])
    .map((value, index) => (value == null ? null : [(index * 60) / 3, 20 - value * 18]))
    .filter(Boolean)
  if (coords.length === 0) {
    return <span className="text-xs text-surface-400">no recent answers</span>
  }
  return (
    <svg viewBox="0 0 60 20" className="w-16 h-5 text-primary-500" aria-label="4-week trend">
      {coords.length > 1 && (
        <polyline fill="none" stroke="currentColor" strokeWidth="2"
          points={coords.map(([x, y]) => `${x},${y}`).join(' ')} />
      )}
      {coords.map(([x, y]) => <circle key={x} cx={x} cy={y} r="1.8" fill="currentColor" />)}
    </svg>
  )
}

/** Mastery bar coloured by band; empty when there is not enough data. */
export function BandBar({ node }) {
  return (
    <div className="w-full h-2 rounded-full bg-surface-200 dark:bg-surface-700 overflow-hidden">
      {node.mastery != null && (
        <div
          className={`h-full rounded-full ${BAR_CLASS[node.status]}`}
          style={{ width: `${Math.round(node.mastery * 100)}%` }}
        />
      )}
    </div>
  )
}
```

- [ ] **Step 3: Breakdown tree**

Create `frontend/exam-frontend/src/components/progress/RollupTree.jsx`:

```jsx
import { useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { STATUS_CLASS, STATUS_TEXT, pct } from './progressUi'

function Row({ node, depth }) {
  const [open, setOpen] = useState(false)
  const hasChildren = node.children?.length > 0
  return (
    <>
      <div
        className="flex items-center gap-3 py-2 border-b border-surface-100 dark:border-surface-700/50"
        style={{ paddingLeft: depth * 18 }}
      >
        <button
          type="button"
          disabled={!hasChildren}
          onClick={() => setOpen(!open)}
          className="w-5 shrink-0 text-surface-400 disabled:opacity-0"
          aria-label={open ? 'Collapse' : 'Expand'}
        >
          {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        </button>
        <span className="flex-1 min-w-0 truncate text-sm">{node.name}</span>
        <span className="hidden sm:block text-xs text-surface-400 w-28 text-right shrink-0">
          {node.total ? `${node.covered}/${node.total} covered` : ''}
        </span>
        <span className={`text-xs w-36 text-right shrink-0 ${STATUS_CLASS[node.status]}`}>
          {node.mastery != null ? `${pct(node.mastery)} · ${STATUS_TEXT[node.status]}` : STATUS_TEXT.not_enough_data}
        </span>
      </div>
      {open && node.children.map((child) => (
        <Row key={child.id} node={child} depth={depth + 1} />
      ))}
    </>
  )
}

/** Expandable subject breakdown: (sub-subject) → topic → subtopic. */
export default function RollupTree({ subject }) {
  if (!subject.children?.length) {
    return <p className="text-sm text-surface-400">No topics in this subject yet.</p>
  }
  return (
    <div>
      {subject.children.map((child) => <Row key={child.id} node={child} depth={0} />)}
    </div>
  )
}
```

- [ ] **Step 4: Profiles panel**

Create `frontend/exam-frontend/src/components/progress/ProfilesPanel.jsx`:

```jsx
import { BandBar, STATUS_CLASS, STATUS_TEXT, pct } from './progressUi'

function FacetList({ title, rows }) {
  if (!rows.length) return null
  return (
    <div>
      <p className="text-xs font-semibold text-surface-500 mb-2">{title}</p>
      <ul className="space-y-2">
        {rows.map((row) => (
          <li key={row.key}>
            <div className="flex justify-between gap-2 text-sm mb-1">
              <span className="truncate">{row.label}</span>
              <span className={`text-xs shrink-0 ${STATUS_CLASS[row.status]}`}>
                {row.mastery != null ? pct(row.mastery) : STATUS_TEXT.not_enough_data}
              </span>
            </div>
            <BandBar node={row} />
          </li>
        ))}
      </ul>
    </div>
  )
}

/** Skills and thinking levels per subject. */
export default function ProfilesPanel({ profiles }) {
  if (!profiles?.length) return null
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {profiles.map((profile) => (
        <div
          key={profile.subject_id}
          className="p-5 rounded-2xl bg-white dark:bg-surface-800 border border-surface-200 dark:border-surface-700"
        >
          <h3 className="text-sm font-semibold mb-3">{profile.subject}: skills and thinking</h3>
          {profile.status === 'needs_tagging' ? (
            <p className="text-sm text-surface-400">
              This appears once the subject's questions have been tagged.
            </p>
          ) : profile.skills.length || profile.thinking_levels.length ? (
            <div className="space-y-4">
              <FacetList title="Skills" rows={profile.skills} />
              <FacetList title="Thinking levels" rows={profile.thinking_levels} />
            </div>
          ) : (
            <p className="text-sm text-surface-400">No tagged answers yet.</p>
          )}
        </div>
      ))}
    </div>
  )
}
```

- [ ] **Step 5: The shared view**

Create `frontend/exam-frontend/src/components/progress/ProgressView.jsx`:

```jsx
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Target, TrendingDown, TrendingUp } from 'lucide-react'
import RollupTree from './RollupTree'
import ProfilesPanel from './ProfilesPanel'
import { BandBar, STATUS_CLASS, STATUS_TEXT, Sparkline, pct } from './progressUi'

const REVIEW_PATH = {
  quiz: (id) => `/quiz/review/${id}`,
  mock: (id) => `/mock-test/review/${id}`,
  rich_mock: (id) => `/mock-test/live-review/${id}`,
}

const Card = ({ title, children }) => (
  <div className="p-5 rounded-2xl bg-white dark:bg-surface-800 border border-surface-200 dark:border-surface-700">
    {title && <h3 className="text-sm font-semibold text-surface-500 mb-3">{title}</h3>}
    {children}
  </div>
)

function TopicList({ title, icon: Icon, topics, practiceOn, empty }) {
  return (
    <Card title={<span className="flex items-center gap-2"><Icon size={15} /> {title}</span>}>
      {topics.length === 0 ? (
        <p className="text-sm text-surface-400">{empty}</p>
      ) : (
        <ul className="space-y-3">
          {topics.map((topic) => (
            <li key={topic.id}>
              <div className="flex items-center justify-between gap-2 text-sm mb-1">
                <span className="truncate">
                  {topic.name}
                  <span className="text-surface-400"> · {topic.subject}</span>
                </span>
                <span className={`shrink-0 ${STATUS_CLASS[topic.status]}`}>{pct(topic.mastery)}</span>
              </div>
              <BandBar node={topic} />
              {practiceOn && topic.status === 'weak' && topic.concept_ids.length > 0 && (
                <Link
                  to={`/practice?concepts=${topic.concept_ids.join(',')}&topic=${encodeURIComponent(topic.name)}`}
                  className="inline-flex items-center gap-1 mt-1.5 text-xs font-medium text-primary-500 hover:text-primary-600"
                >
                  <Target size={12} /> Practise this
                </Link>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

/**
 * The body of My Progress: course picker, subject cards, weak / strong
 * topics, breakdown, skill profiles and recent answers. Used by the student
 * page and by the teacher's Progress tab.
 */
export default function ProgressView({ data, onCourseChange, practiceOn = false, linkReviews = false }) {
  const [subjectId, setSubjectId] = useState(null)
  const subject = data.subjects.find((s) => s.id === subjectId) || data.subjects[0]

  return (
    <div className="space-y-6">
      {data.courses.length > 1 && (
        <select
          value={data.course.id}
          onChange={(e) => { setSubjectId(null); onCourseChange(e.target.value) }}
          className="px-3 py-2 rounded-xl border border-surface-300 dark:border-surface-600 bg-white dark:bg-surface-800 text-sm"
        >
          {data.courses.map((course) => <option key={course.id} value={course.id}>{course.name}</option>)}
        </select>
      )}

      {/* Subject cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
        {data.subjects.map((s) => (
          <button
            key={s.id}
            type="button"
            onClick={() => setSubjectId(s.id)}
            className={`text-left p-5 rounded-2xl bg-white dark:bg-surface-800 border transition-colors ${
              subject?.id === s.id
                ? 'border-primary-400 dark:border-primary-500'
                : 'border-surface-200 dark:border-surface-700 hover:border-surface-300'
            }`}
          >
            <div className="flex items-start justify-between gap-2">
              <p className="font-semibold truncate">{s.name}</p>
              <Sparkline points={s.trend_4w} />
            </div>
            <p className={`text-2xl font-bold mt-2 ${STATUS_CLASS[s.status]}`}>
              {s.mastery != null ? pct(s.mastery) : '—'}
            </p>
            <p className="text-xs text-surface-400 mt-1">
              {s.mastery != null ? STATUS_TEXT[s.status] : STATUS_TEXT.not_enough_data}
              {s.total > 0 && ` · ${s.covered} of ${s.total} ${s.has_tree ? 'subtopics' : 'concepts'} practised`}
            </p>
          </button>
        ))}
      </div>

      {/* Weak and strong topics */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <TopicList
          title="Topics to work on" icon={TrendingDown} topics={data.weak}
          practiceOn={practiceOn} empty="Nothing weak with enough answers yet."
        />
        <TopicList
          title="Strong topics" icon={TrendingUp} topics={data.strong}
          practiceOn={false} empty="Keep going — strong topics show up here."
        />
      </div>

      {/* Breakdown */}
      {subject && (
        <Card title={`${subject.name}: breakdown`}>
          <RollupTree subject={subject} />
        </Card>
      )}

      <ProfilesPanel profiles={data.profiles} />

      {/* Recent answers (only when the payload carries them) */}
      {Array.isArray(data.recent_answers) && (
        <Card title="Recent answers">
          {data.recent_answers.length === 0 ? (
            <p className="text-sm text-surface-400">No finished tests in this course yet.</p>
          ) : (
            <ul className="divide-y divide-surface-100 dark:divide-surface-700/50">
              {data.recent_answers.map((row) => {
                const body = (
                  <div className="flex items-center justify-between gap-3 py-2.5">
                    <div className="min-w-0">
                      <p className="text-sm font-medium truncate">{row.title}</p>
                      <p className="text-xs text-surface-400">
                        {row.completed_at ? new Date(row.completed_at).toLocaleDateString() : ''}
                      </p>
                    </div>
                    <p className="text-xs text-surface-500 text-right">
                      {row.noted ? row.summary : 'Nothing to flag'}
                    </p>
                  </div>
                )
                return (
                  <li key={row.attempt_id}>
                    {linkReviews && REVIEW_PATH[row.review] ? (
                      <Link to={REVIEW_PATH[row.review](row.attempt_id)} className="block hover:bg-surface-50 dark:hover:bg-surface-700/40 rounded-lg px-1">
                        {body}
                      </Link>
                    ) : body}
                  </li>
                )
              })}
            </ul>
          )}
        </Card>
      )}
    </div>
  )
}
```

- [ ] **Step 6: The student page, menu and route**

Create `frontend/exam-frontend/src/pages/MyProgress.jsx`:

```jsx
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { LineChart } from 'lucide-react'
import { progressService } from '../services/progressService'
import { useTenantStore } from '../context/tenantStore'
import Loading from '../components/common/Loading'
import ProgressView from '../components/progress/ProgressView'

/** Student: mastery by subject and topic, skills, and recent answers. */
export default function MyProgress() {
  const [courseId, setCourseId] = useState('')
  const practiceOn = useTenantStore((s) => s.tenant?.features?.practice === true)
  const { data, isLoading } = useQuery({
    queryKey: ['myProgress', courseId],
    queryFn: () => progressService.getMyProgress(courseId || undefined),
  })

  if (isLoading) return <Loading fullScreen />
  if (!data) return null

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-display font-bold flex items-center gap-2">
          <LineChart className="text-primary-500" /> My Progress
        </h1>
        <p className="text-surface-500 mt-1">
          How well you know each part of your course, from your quizzes and tests
        </p>
      </div>
      {data.course ? (
        <ProgressView
          data={data}
          onCourseChange={setCourseId}
          practiceOn={practiceOn}
          linkReviews
        />
      ) : (
        <div className="p-8 rounded-2xl bg-surface-50 dark:bg-surface-800/50 border border-dashed border-surface-300 dark:border-surface-700 text-center text-surface-500">
          Join a course to see your progress here.
        </div>
      )}
    </div>
  )
}
```

In `frontend/exam-frontend/src/components/layout/Sidebar.jsx`:
- add `LineChart` to the `lucide-react` import;
- add after the Smart Practice item:

```js
  { path: '/progress', label: 'My Progress', icon: LineChart, feature: 'my_progress', renamable: true },
```

In `frontend/exam-frontend/src/App.jsx`, import `MyProgress` next to `Practice` and add after the `/practice/:setId` route:

```jsx
          <Route path="/progress" element={<LoginGate><FeatureRoute feature="my_progress"><MyProgress /></FeatureRoute></LoginGate>} />
```

- [ ] **Step 7: "Practise this" filter on Smart Practice**

In `frontend/exam-frontend/src/pages/Practice.jsx`:
- change the router import to `import { Link, useNavigate, useSearchParams } from 'react-router-dom'`;
- inside `Practice`, after `const queryClient = useQueryClient()`, add:

```jsx
  const [searchParams] = useSearchParams()
  const focusConcepts = (searchParams.get('concepts') || '').split(',').filter(Boolean)
  const focusTopic = searchParams.get('topic') || ''
  const inFocus = (ids) => !focusConcepts.length || (ids || []).some((id) => focusConcepts.includes(String(id)))
```

- replace the three lines that build `sets`, `history` and `masteryRows` with:

```jsx
  const sets = (suggested?.results ?? suggested ?? []).filter((set) => inFocus(set.concept_ids))
  const history = (completed?.results ?? completed ?? []).slice(0, 10)
  const masteryRows = (mastery ?? [])
    .filter((row) => row.confidence !== 'low' && inFocus([row.concept_id]))
    .slice(0, 12)
```

- directly under the header block (`<div className="flex flex-col md:flex-row …">…</div>`), add:

```jsx
      {focusConcepts.length > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-2 p-3 rounded-xl bg-primary-50 dark:bg-primary-900/30 text-sm">
          <span>Showing practice for <strong>{focusTopic || 'one topic'}</strong></span>
          <Link to="/practice" className="font-medium text-primary-600 hover:text-primary-700">Show all</Link>
        </div>
      )}
```

- in the "Suggested for you" empty state, replace the two `<p>` lines with:

```jsx
            <p className="font-medium">
              {focusConcepts.length ? 'No set for this topic yet.' : 'Nothing to practise right now.'}
            </p>
            <p className="text-sm mt-1">
              {focusConcepts.length
                ? 'Try "Refresh suggestions", or show all sets.'
                : 'Complete a quiz or mock test and suggestions will appear here as the system learns what you know.'}
            </p>
```

- [ ] **Step 8: Build**

Run (from `frontend/exam-frontend/`): `npx vite build`
Expected: build succeeds.

- [ ] **Step 9: Commit**

```bash
git add frontend/exam-frontend/src/services/progressService.js frontend/exam-frontend/src/services/insightsService.js frontend/exam-frontend/src/components/progress/progressUi.jsx frontend/exam-frontend/src/components/progress/RollupTree.jsx frontend/exam-frontend/src/components/progress/ProfilesPanel.jsx frontend/exam-frontend/src/components/progress/ProgressView.jsx frontend/exam-frontend/src/pages/MyProgress.jsx frontend/exam-frontend/src/components/layout/Sidebar.jsx frontend/exam-frontend/src/App.jsx frontend/exam-frontend/src/pages/Practice.jsx
git commit -m "feat(frontend): My Progress page and topic-filtered Smart Practice"
```

---

### Task 11: Frontend — teacher Progress tab and class heatmap

**Files:**
- Create: `frontend/exam-frontend/src/components/insights/StudentProgressTab.jsx`
- Create: `frontend/exam-frontend/src/components/insights/ClassHeatmap.jsx`
- Modify: `frontend/exam-frontend/src/pages/StudentDiagnosis.jsx`
- Modify: `frontend/exam-frontend/src/pages/InsightsHome.jsx`
- Modify: `frontend/exam-frontend/src/components/layout/AdminSidebar.jsx`

**Interfaces:**
- Consumes: `insightsService.getStudentProgress`, `getCourseHeatmap` (Task 10); `ProgressView`; Part A's tabs on StudentDiagnosis and `features` on admin nav items.

- [ ] **Step 1: Progress tab**

Create `frontend/exam-frontend/src/components/insights/StudentProgressTab.jsx`:

```jsx
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { insightsService } from '../../services/insightsService'
import Loading from '../common/Loading'
import ProgressView from '../progress/ProgressView'

/** Teacher: the student's My Progress data, limited to courses you teach. */
export default function StudentProgressTab({ studentId }) {
  const [courseId, setCourseId] = useState('')
  const { data, isLoading } = useQuery({
    queryKey: ['studentProgress', studentId, courseId],
    queryFn: () => insightsService.getStudentProgress(studentId, courseId || undefined),
  })
  if (isLoading) return <Loading />
  if (!data) return null
  if (!data.course) {
    return <p className="text-sm text-surface-400">This student has no approved course you teach.</p>
  }
  return <ProgressView data={data} onCourseChange={setCourseId} />
}
```

- [ ] **Step 2: Tabs on StudentDiagnosis**

In `frontend/exam-frontend/src/pages/StudentDiagnosis.jsx` (Part A added a Concepts / Answers tab bar shown only with the teacher view):
- add `import StudentProgressTab from '../components/insights/StudentProgressTab'`;
- next to the `teacherView` selector add:

```jsx
  const progressOn = useTenantStore((s) => s.tenant?.features?.my_progress === true)
  const tabs = [
    ['concepts', 'Concepts'],
    ...(teacherView ? [['answers', 'Answers']] : []),
    ...(progressOn ? [['progress', 'Progress']] : []),
  ]
```

- replace Part A's tab bar block (`{teacherView && ( <div className="flex gap-2"> {[['concepts', 'Concepts'], ['answers', 'Answers']].map(…)} </div> )}`) with the same markup driven by `tabs`, shown when there is more than one:

```jsx
      {tabs.length > 1 && (
        <div className="flex gap-2">
          {tabs.map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setTab(key)}
              className={`px-4 py-2 rounded-xl text-sm font-medium ${
                tab === key
                  ? 'bg-primary-500 text-white'
                  : 'bg-surface-100 dark:bg-surface-800 hover:bg-surface-200 dark:hover:bg-surface-700'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      )}
```

- below Part A's `{teacherView && tab === 'answers' && …}` line add:

```jsx
      {progressOn && tab === 'progress' && <StudentProgressTab studentId={studentId} />}
```

- [ ] **Step 3: Class heatmap tile**

Create `frontend/exam-frontend/src/components/insights/ClassHeatmap.jsx`:

```jsx
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { insightsService } from '../../services/insightsService'
import { pct } from '../progress/progressUi'

const BAND_TEXT = {
  weak: 'Below 50%',
  in_progress: '50–80%',
  strong: '80% and up',
  not_enough_data: 'Not enough data',
}
const BAND_CELL = {
  weak: 'bg-danger-100 text-danger-700 dark:bg-danger-900/40 dark:text-danger-300',
  in_progress: 'bg-warning-100 text-warning-700 dark:bg-warning-900/40 dark:text-warning-300',
  strong: 'bg-success-100 text-success-700 dark:bg-success-900/40 dark:text-success-300',
  not_enough_data: 'bg-surface-100 text-surface-500 dark:bg-surface-700 dark:text-surface-300',
}

/** Insights home: students per topic and mastery band, for one course. */
export default function ClassHeatmap({ courseId }) {
  const [selected, setSelected] = useState(null) // { topicId, band }
  const { data } = useQuery({
    queryKey: ['courseHeatmap', courseId],
    queryFn: () => insightsService.getCourseHeatmap(courseId),
    enabled: !!courseId,
  })
  if (!data) return null

  const picked = selected && data.topics.find((t) => t.id === selected.topicId)
  return (
    <div className="p-5 rounded-2xl bg-white dark:bg-surface-800 border border-surface-200 dark:border-surface-700">
      <h3 className="text-sm font-semibold text-surface-500 mb-3">
        Class topic heatmap ({data.students} students{data.capped ? ', first 500' : ''})
      </h3>
      {data.topics.length === 0 ? (
        <p className="text-sm text-surface-400">No topics yet. Add a syllabus or tag questions to see this.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-surface-400 border-b border-surface-200 dark:border-surface-700">
                <th className="py-2 pr-3">Topic</th>
                <th className="py-2 pr-3">Coverage</th>
                {data.bands.map((band) => <th key={band} className="py-2 pr-2 text-center">{BAND_TEXT[band]}</th>)}
              </tr>
            </thead>
            <tbody>
              {data.topics.map((topic) => (
                <tr key={topic.id} className="border-b border-surface-100 dark:border-surface-700/50">
                  <td className="py-2 pr-3">
                    <span className="block truncate max-w-[14rem]">{topic.name}</span>
                    <span className="text-xs text-surface-400">{topic.subject}</span>
                  </td>
                  <td className="py-2 pr-3 text-surface-500">{pct(topic.coverage)}</td>
                  {data.bands.map((band) => (
                    <td key={band} className="py-1 pr-2 text-center">
                      <button
                        type="button"
                        disabled={!topic.counts[band]}
                        onClick={() => setSelected({ topicId: topic.id, band })}
                        className={`w-full min-w-[3rem] px-2 py-1.5 rounded-lg font-semibold disabled:opacity-40 ${BAND_CELL[band]}`}
                      >
                        {topic.counts[band]}
                      </button>
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {picked && (
        <div className="mt-4 pt-3 border-t border-surface-200 dark:border-surface-700">
          <p className="text-xs font-semibold text-surface-500 mb-2">
            {picked.name} · {BAND_TEXT[selected.band]}
          </p>
          <ul className="flex flex-wrap gap-2 text-sm">
            {picked.students[selected.band].map((student) => (
              <li key={student.id}>
                <Link
                  to={`/admin/insights/students/${student.id}`}
                  className="px-2.5 py-1 rounded-full bg-surface-100 dark:bg-surface-700 hover:text-primary-500"
                >
                  {student.name}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Insights home and the menu**

In `frontend/exam-frontend/src/pages/InsightsHome.jsx`:
- add `import ClassHeatmap from '../components/insights/ClassHeatmap'`;
- next to the `teacherView` selector (Part A) add:

```jsx
  const progressOn = useTenantStore((s) => s.tenant?.features?.my_progress === true)
```

- in the class view, change the left column wrapper `<div className="lg:col-span-2">` to `<div className="lg:col-span-2 space-y-4">` and add after its "Class concept mastery" `Tile`:

```jsx
            {progressOn && <ClassHeatmap courseId={activeCourse} />}
```

In `frontend/exam-frontend/src/components/layout/AdminSidebar.jsx`, change the Insights item's `features` to:

```js
features: ['practice', 'diagnosis_teacher_view', 'syllabus_tools', 'my_progress']
```

- [ ] **Step 5: Build**

Run (from `frontend/exam-frontend/`): `npx vite build`
Expected: build succeeds.

- [ ] **Step 6: Commit**

```bash
git add frontend/exam-frontend/src/components/insights/StudentProgressTab.jsx frontend/exam-frontend/src/components/insights/ClassHeatmap.jsx frontend/exam-frontend/src/pages/StudentDiagnosis.jsx frontend/exam-frontend/src/pages/InsightsHome.jsx frontend/exam-frontend/src/components/layout/AdminSidebar.jsx
git commit -m "feat(frontend): teacher Progress tab and class topic heatmap"
```

---

### Task 12: Docs and manual walkthrough

**Files:**
- Modify: `wiki/backend-guide.md`

- [ ] **Step 1: Ops notes**

In `wiki/backend-guide.md`, after the Part A and Part B notes in the learning-layer section, add:

```markdown
- **My Progress (2B Part C).** Opt-in switch `my_progress` (also a
  `LEARNING_FEATURES` member).
  - Student page `/progress` (`GET /api/v1/intelligence/my/progress/?course=`):
    mastery rolled up subtopic → topic → sub-subject → subject, weak and
    strong topics, skill and thinking-level profiles, and recent answers
    when `diagnosis_student_view` is on.
  - Teachers: "Progress" tab on the student page
    (`…/students/<id>/progress/`) and a class topic heatmap on Insights home
    (`…/courses/<id>/heatmap/`), both scoped by `intelligence/access.py`.
  - Roll-ups, lists and heatmaps are computed per request from
    `LearnerConceptState` and `LearningEvent`; a subject without a syllabus
    tree falls back to course Topic → Concept. Bands and wording:
    `intelligence/progress_config.py` (display-only).
  - `LearnerFacetState` (skills and thinking levels per subject) is
    recomputed after each diagnosed attempt, nightly, and by
    `recompute_learner_state` (`--no-facets` to skip), only for tenants with
    `my_progress` on. After changing a facet weight, bump
    `FACET_MODEL_VERSION` and rerun the command.
  - **After turning `my_progress` on for a tenant**, run
    `python manage.py recompute_learner_state --tenant <id>` once to fill the
    facet profiles.
```

- [ ] **Step 2: Manual walkthrough (in the PR description, not committed)**

Write this checklist into the PR description under "Manual checks — Part C":

1. With `CELERY_TASK_ALWAYS_EAGER=true`, on the DailyTaiyari test tenant turn
   on My Progress and Answer Diagnosis + both view switches. Use a course
   whose syllabus was built and tagged in Part B's walkthrough.
2. Run `python manage.py recompute_learner_state --tenant <id>`; it reports
   concept states and facet profiles.
3. As a student enrolled in that course, open My Progress from the menu:
   subject cards with a sparkline, weak/strong topics, the breakdown
   expanding to subtopics, skills and thinking levels, and recent answers
   with a link to each review page.
4. Turn on Smart Practice: weak topics show "Practise this", which opens
   Smart Practice filtered to that topic with a "Show all" link.
5. As faculty assigned to the course, open Learning Insights: the class
   topic heatmap shows; clicking a cell lists students; a name opens the
   student page, whose Progress tab shows the same data.
6. As faculty of a different course, open that student's progress URL and
   the course heatmap URL: both are refused.
7. On a course with no syllabus tree, My Progress shows topics and concepts
   (fallback) and the profiles say they appear after tagging.
8. On the CodeMinors test tenant, with every learning-layer switch off,
   confirm no My Progress menu item, `/progress` redirects to the
   dashboard, and no requests to `/intelligence/my/progress/`.

- [ ] **Step 3: Final suite**

Run: `venv/Scripts/python.exe manage.py test -v 1` (whole backend) and `npx vite build` in both frontends.
Expected: all PASS; both builds succeed.

- [ ] **Step 4: Commit**

```bash
git add wiki/backend-guide.md
git commit -m "docs(wiki): My Progress switch, endpoints and facet recompute"
```
