# Response Diagnosis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture real per-question interaction timelines on every attempt
screen, classify every (attempt × item) into an outcome label (guess, slip,
time pressure, concept gap, …), collect student self-reports as ground
truth, and weight mastery evidence by those labels.

**Architecture:**
- The browser records raw events only (`useResponseTimeline`) and syncs
  them to `AttemptTimeline`.
- On finalization, one Celery task runs the pure classifier
  (`services/diagnosis.py`) over facts gathered by `services/diagnose.py`
  and writes `ResponseDiagnosis`. It then recomputes learner state, which
  now multiplies evidence weight by the diagnosis label.
- Self-reports are a separate observation table, reconciled into
  `final_label`.

**Tech Stack:** Django 4 + DRF, Celery (eager in tests), Django `TestCase`;
React 18 + Vite, TanStack Query, Zustand (`tenantStore`).

**Spec:** `docs/superpowers/specs/2026-10-19-response-diagnosis-design.md`

## Global Constraints

- Run backend commands from `backend/` with `venv/Scripts/python.exe` (Windows venv). Test command shape: `venv/Scripts/python.exe manage.py test <dotted.path> -v 2`.
- Git identity: this machine has no `user.email` configured. Before executing, the user must run `git config user.email <their email>` in the repo (or tell you the identity to pass with `git -c`). Never change global git config yourself.
- Every commit message ends with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Never push. Work stays on local branch `feat/response-diagnosis`.
- Other apps call the intelligence layer only through `intelligence/api.py` and `intelligence/hooks.py`. Those are fail-safe: an intelligence error must never fail a student submit.
- Inference is always recomputed from observations. Never increment state in place. Bump the version constant when an algorithm changes.
- Item keys everywhere: `bank:<Question uuid>` or `item:<MockTestItem uuid>`.
- Timeline event tuple: `[t_ms, code, key, value?]`, codes `e l h s a c`, ≤ 5000 events per session, request body ≤ 256 KB.
- Version constants: `CLASSIFIER_VERSION = '1'`, `STATE_MODEL_VERSION = '2'`.
- New tenant feature key: `response_diagnosis` (label "Answer Diagnosis"), opt-in (default off). It gates only the self-report UI and API. Capture and classification always run.
- Frontend lint: run `npx eslint <changed files> --max-warnings 0` from `frontend/exam-frontend` (the repo-wide `npm run lint` may already fail for unrelated files).

## File map

**Backend — create**
- `backend/intelligence/diagnosis_config.py` — thresholds, default usual times, label weights, self-report mapping.
- `backend/intelligence/services/timeline.py` — pure event validation and reduction to per-key timing.
- `backend/intelligence/services/timeline_sync.py` — attempt resolution, offset anchoring, session upsert.
- `backend/intelligence/services/diagnosis.py` — pure `classify` / `reconcile` / `slip_match`.
- `backend/intelligence/services/diagnose.py` — gathers facts per attempt and persists `ResponseDiagnosis`.
- `backend/intelligence/management/commands/recompute_diagnoses.py`
- `backend/intelligence/tests/diagnosis_fixtures.py` — shared `DiagnosisTestCase`.
- `backend/intelligence/tests/test_timeline.py`, `test_diagnosis_rules.py`, `test_diagnose.py`, `test_self_report.py`

**Backend — modify**
- `backend/intelligence/models.py` — 3 new models and 2 `ItemStats` fields.
- `backend/intelligence/versions.py`
- `backend/core/models.py` — feature key.
- `backend/intelligence/services/events.py` — extract `item_score_fraction`.
- `backend/intelligence/services/state.py` — diagnosis weights.
- `backend/intelligence/services/itemstats.py` — median active time.
- `backend/intelligence/services/practice.py` — diagnose before state recompute.
- `backend/intelligence/tasks.py`, `backend/intelligence/api.py`
- `backend/intelligence/views.py`, `urls.py`, `admin_views.py`, `admin_urls.py`
- `backend/quiz/mock_grading.py` — `ref_id` on review entries.

**Frontend — create**
- `frontend/exam-frontend/src/services/timelineService.js`
- `frontend/exam-frontend/src/hooks/useResponseTimeline.js`
- `frontend/exam-frontend/src/components/review/WhatHappened.jsx`

**Frontend — modify**
- `src/pages/QuizAttempt.jsx`, `MockTestAttempt.jsx`, `RichMockAttempt.jsx`, `PracticeSession.jsx`
- `src/pages/QuizReview.jsx`, `MockTestReview.jsx`, `RichMockReview.jsx`

---

### Task 1: Merge `main` into the branch (sub-project 0)

The branch is 23 commits behind `main`. Six files conflict, and the quiz and
chatbot migration graphs fork. Every conflict hunk is "keep both sides".

**Files:**
- Modify (conflicts): `backend/chatbot/models.py`, `backend/core/models.py`, `backend/dailytaiyari/settings.py`, `backend/dailytaiyari/urls.py`, `backend/docker-compose.yml`, `frontend/exam-frontend/src/components/layout/Sidebar.jsx`
- Create (generated): `backend/quiz/migrations/0014_merge_*.py`, `backend/chatbot/migrations/0013_merge_*.py`, plus one chatbot `AlterField` migration

- [ ] **Step 1: Start the merge**

Run (repo root): `git merge main --no-ff --no-commit`
Expected: `CONFLICT (content)` for exactly the six files above. `git status` lists them as "both modified".

- [ ] **Step 2: Resolve `backend/chatbot/models.py`**

In `AIUsageRecord`, keep all four feature constants and all four choice tuples:

```python
    FEATURE_ITEMTAG = 'itemtag'
    FEATURE_PRACTICEGEN = 'practicegen'
    FEATURE_GRADING = 'grading'
    FEATURE_HACKATHONGEN = 'hackathongen'
```

```python
        (FEATURE_ITEMTAG, 'Item tagging'),
        (FEATURE_PRACTICEGEN, 'Practice generator'),
        (FEATURE_GRADING, 'Subjective grading'),
        (FEATURE_HACKATHONGEN, 'Hackathon builder'),
```

- [ ] **Step 3: Resolve `backend/core/models.py`**

`FEATURE_CHOICES` keeps `'practice'`, `'ai_grading'` **and** `'hackathons'`,
followed by the closing `}` and main's entire `ADVANCED_SETTING_CHOICES`
block, unchanged. The resolved region reads:

```python
        'practice': 'Smart Practice',
        'ai_grading': 'AI Subjective Grading',
        'hackathons': 'Hackathons',
    }

    # Canonical list of "advanced" behaviour switches ...   (main's block, verbatim)
    ADVANCED_SETTING_CHOICES = {
        ...
    }
```

Then confirm `OPT_IN_FEATURES` (auto-merged) still contains `'practice'` and `'ai_grading'`.

- [ ] **Step 4: Resolve settings, urls, docker-compose, Sidebar**

`backend/dailytaiyari/settings.py` — `INSTALLED_APPS` keeps both:
```python
    'intelligence.apps.IntelligenceConfig',
    'hackathons.apps.HackathonsConfig',
```

`backend/dailytaiyari/urls.py` — keep all three:
```python
    path('api/v1/intelligence/', include('intelligence.urls')),
    path('api/v1/tenant-admin/intelligence/', include('intelligence.admin_urls')),
    path('api/v1/hackathons/', include('hackathons.urls')),
```

`backend/docker-compose.yml` — keep the `celery-beat` service (HEAD) **and** the `celery-mediaworker` service (main), one after the other, each with its own comment block.

`frontend/exam-frontend/src/components/layout/Sidebar.jsx` — the icon import list keeps `Bookmark`, `Target` and `Rocket`. The nav list is main's version plus the Smart Practice row:
```jsx
  { path: '/quiz', label: 'Practice Quiz', icon: PenTool, feature: 'quiz', renamable: true },
  { path: '/practice', label: 'Smart Practice', icon: Target, feature: 'practice', renamable: true },
  { path: '/mock-test', label: 'Mock Tests', icon: ClipboardList, feature: 'mock_tests', renamable: true },
  { path: '/pyp', label: 'PYQ Papers', icon: FileText, feature: 'pyq', renamable: true },
  { path: '/community', label: 'Community', icon: Users, feature: 'community', renamable: true },
  { path: '/jobs', label: 'Careers', icon: Briefcase, feature: 'jobs', renamable: true },
  { path: '/hackathons', label: 'Hackathons', icon: Rocket, feature: 'hackathons', renamable: true },
  { path: '/analytics', label: 'Analytics', icon: BarChart3, feature: 'analytics', renamable: true },
  { path: '/leaderboard', label: 'Leaderboard', icon: Trophy, feature: 'leaderboard', renamable: true },
  { path: '/doubt-solver', label: 'AI Doubt Solver', icon: MessageSquareText, feature: 'ai', renamable: true },
```

Verify no markers remain. Run: `git diff --check` and `grep -rn "^<<<<<<<\|^>>>>>>>" backend frontend/exam-frontend/src`
Expected: no output.

- [ ] **Step 5: Merge the migration graphs**

Run (from `backend/`): `venv/Scripts/python.exe manage.py makemigrations --merge --noinput`
Expected: creates `quiz/migrations/0014_merge_<timestamp>.py` (merging `0012_quizattempt_proctoring` + `0013_mocktestanswer_ai_confidence_and_more`) and `chatbot/migrations/0013_merge_<timestamp>.py`.

Run: `venv/Scripts/python.exe manage.py makemigrations`
Expected: one new chatbot migration altering `aiusagerecord.feature` (the merged choice list). Nothing else.

Run: `venv/Scripts/python.exe manage.py makemigrations --check --dry-run`
Expected: `No changes detected`.

- [ ] **Step 6: Run the affected suites**

Run: `venv/Scripts/python.exe manage.py test intelligence quiz chatbot core -v 1`
Expected: all pass (the branch alone had 55 passing in `intelligence quiz`).

- [ ] **Step 7: Commit the merge**

```bash
git add -A
git commit -m "Merge main into feat/response-diagnosis

Keep-both resolutions for feature registries, settings, urls, compose and
sidebar; merge migrations for quiz and chatbot plus the combined
AIUsageRecord.feature choices.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Schema — timeline, self-report, diagnosis models, feature key, versions

**Files:**
- Modify: `backend/intelligence/models.py` (append; extend `ItemStats`)
- Modify: `backend/intelligence/versions.py`
- Modify: `backend/core/models.py` (`FEATURE_CHOICES`, `OPT_IN_FEATURES`)
- Create: `backend/intelligence/tests/diagnosis_fixtures.py`
- Create: `backend/intelligence/tests/test_diagnose.py` (schema tests now; integration tests are appended in Task 6)
- Create (generated): `backend/intelligence/migrations/0003_response_diagnosis.py`

**Interfaces:**
- Produces:
  - `ATTEMPT_KIND_CHOICES`
  - `AttemptTimeline` (`student`, `attempt_kind`, `attempt_id`, `clock`, `sessions`, `finalized_at`)
  - `ResponseSelfReport` (`student`, `attempt_kind`, `attempt_id`, `question`, `mock_item`, `choice`; `CHOICE_CHOICES`)
  - `ResponseDiagnosis` (fields per spec §3.3; `LABEL_CHOICES`, `CONFIDENCE_CHOICES`)
  - `ItemStats.median_active_seconds`, `ItemStats.active_time_n`
  - `versions.CLASSIFIER_VERSION`
  - `DiagnosisTestCase` fixture

- [ ] **Step 1: Write the shared fixture**

Create `backend/intelligence/tests/diagnosis_fixtures.py`:

```python
"""Shared fixtures for the response-diagnosis tests: one tenant with the
feature on, a student, a 60-minute rich mock test and helpers to build
items, attempts, answers and timelines."""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from core.models import Tenant
from exams.models import Course, Subject, Topic
from intelligence.models import AttemptTimeline, Concept, ConceptLink
from quiz.models import MockTest, MockTestAnswer, MockTestAttempt, MockTestItem
from users.models import User


class DiagnosisTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create(
            name='Diagnosis Academy', is_active=True,
            features={'response_diagnosis': True},
        )
        cls.user = User.objects.create_user(
            email='diag-student@example.com', password='pw-diag-1',
            tenant=cls.tenant, role='student',
        )
        cls.student = cls.user.profile
        cls.other_user = User.objects.create_user(
            email='diag-other@example.com', password='pw-diag-2',
            tenant=cls.tenant, role='student',
        )
        cls.course = Course.objects.create(
            tenant=cls.tenant, name='Physics', code='physics', course_type='competitive',
        )
        cls.subject = Subject.objects.create(
            tenant=cls.tenant, course=cls.course, name='Mechanics', code='mech',
        )
        cls.topic = Topic.objects.create(
            tenant=cls.tenant, subject=cls.subject, name='Kinematics', code='kin',
        )
        cls.concept = Concept.objects.create(
            tenant=cls.tenant, subject=cls.subject, name='Velocity', slug='velocity',
        )
        cls.mock_test = MockTest.objects.create(
            tenant=cls.tenant, course=cls.course, title='Paper',
            duration_minutes=60, total_marks=16,
        )

    def make_item(self, *, item_type='mcq', difficulty='medium', numerical=None):
        options = [] if item_type == 'numerical' else [
            {'text': 'A', 'is_correct': True},
            {'text': 'B', 'is_correct': False},
            {'text': 'C', 'is_correct': False},
        ]
        item = MockTestItem.objects.create(
            tenant=self.tenant, mock_test=self.mock_test, item_type=item_type,
            question_text=f'Question {MockTestItem.objects.count() + 1}?', marks=4,
            topic=self.topic, subject=self.subject, difficulty=difficulty,
            options=options, numerical_answer=numerical,
        )
        ConceptLink.objects.create(
            tenant=self.tenant, concept=self.concept, mock_item=item,
            is_primary=True, weight=1.0, source='generator',
        )
        return item

    def make_attempt(self, *, minutes_ago=30, student=None):
        attempt = MockTestAttempt.objects.create(
            tenant=self.tenant, student=student or self.student,
            mock_test=self.mock_test, status='in_progress',
        )
        # started_at is auto_now_add — move it back with a plain update.
        MockTestAttempt.objects.filter(id=attempt.id).update(
            started_at=timezone.now() - timedelta(minutes=minutes_ago),
        )
        attempt.refresh_from_db()
        return attempt

    def answer(self, attempt, item, *, selected=None, numerical=None, correct=False):
        return MockTestAnswer.objects.create(
            tenant=self.tenant, attempt=attempt, item=item,
            selected_options=selected or [], numerical_answer=numerical,
            is_correct=correct, marks_obtained=4 if correct else 0, max_marks=4,
        )

    def finish(self, attempt, *, after_minutes=20, status='completed'):
        attempt.status = status
        attempt.completed_at = attempt.started_at + timedelta(minutes=after_minutes)
        attempt.save()
        return attempt

    def make_timeline(self, attempt, events, *, clock='server', offset_ms=0, kind='mock'):
        return AttemptTimeline.objects.create(
            tenant=self.tenant, student=attempt.student, attempt_kind=kind,
            attempt_id=attempt.id, clock=clock,
            sessions={'s1': {'offset_ms': offset_ms, 'events': events,
                             'received_at': '', 'truncated': False}},
        )
```

- [ ] **Step 2: Write the failing schema tests**

Create `backend/intelligence/tests/test_diagnose.py`:

```python
"""Response diagnosis: schema, fact assembly, persistence and state weights."""
from django.db import IntegrityError, transaction

from intelligence.models import AttemptTimeline, ResponseDiagnosis, ResponseSelfReport
from intelligence.tests.diagnosis_fixtures import DiagnosisTestCase
from intelligence.versions import CLASSIFIER_VERSION, STATE_MODEL_VERSION


class DiagnosisSchemaTests(DiagnosisTestCase):
    def test_versions(self):
        self.assertEqual(CLASSIFIER_VERSION, '1')
        self.assertEqual(STATE_MODEL_VERSION, '2')

    def test_feature_is_opt_in(self):
        from core.models import Tenant
        self.assertIn('response_diagnosis', Tenant.FEATURE_CHOICES)
        self.assertIn('response_diagnosis', Tenant.OPT_IN_FEATURES)
        plain = Tenant.objects.create(name='Plain', is_active=True)
        self.assertFalse(plain.get_features()['response_diagnosis'])

    def test_one_timeline_per_attempt(self):
        attempt = self.make_attempt()
        self.make_timeline(attempt, [])
        with self.assertRaises(IntegrityError), transaction.atomic():
            AttemptTimeline.objects.create(
                tenant=self.tenant, student=self.student, attempt_kind='mock',
                attempt_id=attempt.id,
            )

    def test_diagnosis_requires_exactly_one_item(self):
        attempt = self.make_attempt()
        with self.assertRaises(IntegrityError), transaction.atomic():
            ResponseDiagnosis.objects.create(
                tenant=self.tenant, student=self.student, attempt_kind='mock',
                attempt_id=attempt.id, label='unclear', final_label='unclear',
            )

    def test_one_self_report_per_attempt_item(self):
        attempt = self.make_attempt()
        item = self.make_item()
        ResponseSelfReport.objects.create(
            tenant=self.tenant, student=self.student, attempt_kind='mock',
            attempt_id=attempt.id, mock_item=item, choice='guessed',
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            ResponseSelfReport.objects.create(
                tenant=self.tenant, student=self.student, attempt_kind='mock',
                attempt_id=attempt.id, mock_item=item, choice='slipped',
            )
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_diagnose -v 2`
Expected: ERROR — `ImportError: cannot import name 'AttemptTimeline'`.

- [ ] **Step 4: Bump versions**

In `backend/intelligence/versions.py` change `STATE_MODEL_VERSION = '1'` to `'2'`, and append:

```python

# Response diagnosis rules + thresholds (services/diagnosis.py,
# diagnosis_config.py). Bump, then run ``recompute_diagnoses``.
CLASSIFIER_VERSION = '1'
```

- [ ] **Step 5: Add the feature key**

In `backend/core/models.py`, `Tenant.FEATURE_CHOICES`: add `'response_diagnosis': 'Answer Diagnosis',` after `'ai_grading': 'AI Subjective Grading',`. Change the opt-in set to include it:

```python
    OPT_IN_FEATURES = {'practice', 'ai_grading', 'response_diagnosis'}
```

(Keep any other members main added to `OPT_IN_FEATURES`.)

- [ ] **Step 6: Add the models**

In `backend/intelligence/models.py`, change the versions import to:

```python
from .versions import (
    CLASSIFIER_VERSION, EVENT_SCHEMA_VERSION, ONTOLOGY_VERSION, STATE_MODEL_VERSION,
)
```

In `ItemStats`, after `avg_time_seconds`, add:

```python
    # Median on-screen time from interaction timelines (guesses excluded);
    # the "usual time" the diagnosis classifier trusts once n is large enough.
    median_active_seconds = models.FloatField(null=True, blank=True)
    active_time_n = models.PositiveIntegerField(default=0)
```

Append to the end of the file:

```python
ATTEMPT_KIND_CHOICES = [
    ('quiz', 'Quiz'),
    ('mock', 'Mock test'),
    ('practice', 'Practice set'),
]


def _per_attempt_item_constraints(prefix):
    """XOR item arm + one row per (attempt, item), as ConceptLink does it."""
    return [
        models.CheckConstraint(
            name=f'{prefix}_exactly_one_item',
            check=(
                (Q(question__isnull=False) & Q(mock_item__isnull=True))
                | (Q(question__isnull=True) & Q(mock_item__isnull=False))
            ),
        ),
        models.UniqueConstraint(
            fields=['attempt_kind', 'attempt_id', 'question'],
            condition=Q(question__isnull=False), name=f'uniq_{prefix}_question',
        ),
        models.UniqueConstraint(
            fields=['attempt_kind', 'attempt_id', 'mock_item'],
            condition=Q(mock_item__isnull=False), name=f'uniq_{prefix}_mock_item',
        ),
    ]


class AttemptTimeline(TimeStampedModel):
    """Observation: the raw per-question interaction log of one attempt.

    ``sessions`` maps a page-load session id to
    ``{offset_ms, events, received_at, truncated}``. Each sync replaces its own
    session wholesale, so resends are harmless. ``offset_ms`` is the session
    start relative to the attempt's anchor (``started_at``; ``created_at``
    for practice sets), computed server-side — the client clock is never
    trusted. ``clock`` says how the attempt is timed, which decides where the
    timing window starts (see services/timeline.py).
    """

    CLOCK_CHOICES = [
        ('client', 'Client-timed (timer restarts per page load)'),
        ('server', 'Server-timed (anchored to started_at)'),
        ('none', 'Untimed'),
    ]

    student = models.ForeignKey(
        'users.StudentProfile', on_delete=models.CASCADE, related_name='attempt_timelines',
    )
    attempt_kind = models.CharField(max_length=10, choices=ATTEMPT_KIND_CHOICES)
    attempt_id = models.UUIDField()
    clock = models.CharField(max_length=10, choices=CLOCK_CHOICES, default='server')
    sessions = models.JSONField(default=dict, blank=True)
    # Set once diagnosis has consumed the timeline; later syncs are refused.
    finalized_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Attempt Timeline'
        verbose_name_plural = 'Attempt Timelines'
        constraints = [
            models.UniqueConstraint(
                fields=['attempt_kind', 'attempt_id'], name='uniq_attempt_timeline',
            ),
        ]

    def __str__(self):
        return f'timeline {self.attempt_kind}:{self.attempt_id}'


class ResponseSelfReport(TimeStampedModel):
    """Observation: the student's own "what happened?" on one item."""

    CHOICE_CHOICES = [
        ('slipped', 'Knew it, slipped'),
        ('ran_out_of_time', 'Ran out of time'),
        ('guessed', 'Guessed'),
        ('didnt_know', "Didn't know"),
    ]

    student = models.ForeignKey(
        'users.StudentProfile', on_delete=models.CASCADE, related_name='response_self_reports',
    )
    attempt_kind = models.CharField(max_length=10, choices=ATTEMPT_KIND_CHOICES)
    attempt_id = models.UUIDField()
    question = models.ForeignKey(
        'quiz.Question', on_delete=models.CASCADE, null=True, blank=True, related_name='+',
    )
    mock_item = models.ForeignKey(
        'quiz.MockTestItem', on_delete=models.CASCADE, null=True, blank=True, related_name='+',
    )
    choice = models.CharField(max_length=20, choices=CHOICE_CHOICES)

    class Meta:
        verbose_name = 'Response Self-Report'
        verbose_name_plural = 'Response Self-Reports'
        constraints = _per_attempt_item_constraints('selfreport')

    def __str__(self):
        return f'{self.attempt_kind}:{self.attempt_id} → {self.choice}'


class ResponseDiagnosis(TimeStampedModel):
    """Inference: why one item in one attempt was won or lost.

    Exists for answered *and* unanswered items. Always recomputed by
    ``services.diagnose`` from timeline + grading + prior state; ``label`` is
    the classifier's call, ``final_label`` folds in the self-report.
    """

    LABEL_CHOICES = [
        ('not_seen', 'Never looked at'),
        ('skipped', 'Seen and skipped'),
        ('time_pressure', 'Time pressure'),
        ('correct', 'Correct'),
        ('correct_lucky', 'Correct, likely a guess'),
        ('correct_slow', 'Correct but slow'),
        ('guess', 'Guess'),
        ('second_guess', 'Changed a right answer'),
        ('careless_slip', 'Careless slip'),
        ('concept_gap', 'Concept gap'),
        ('unclear', 'Unclear'),
    ]
    CONFIDENCE_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
    ]

    student = models.ForeignKey(
        'users.StudentProfile', on_delete=models.CASCADE, related_name='response_diagnoses',
    )
    attempt_kind = models.CharField(max_length=10, choices=ATTEMPT_KIND_CHOICES)
    attempt_id = models.UUIDField()
    question = models.ForeignKey(
        'quiz.Question', on_delete=models.CASCADE, null=True, blank=True,
        related_name='response_diagnoses',
    )
    mock_item = models.ForeignKey(
        'quiz.MockTestItem', on_delete=models.CASCADE, null=True, blank=True,
        related_name='response_diagnoses',
    )

    answered = models.BooleanField(default=False)
    is_correct = models.BooleanField(null=True, blank=True)
    score_fraction = models.FloatField(default=0.0)

    metrics = models.JSONField(default=dict, blank=True)
    flags = models.JSONField(default=list, blank=True)
    label = models.CharField(max_length=20, choices=LABEL_CHOICES)
    confidence = models.CharField(max_length=10, choices=CONFIDENCE_CHOICES, default='low')
    evidence = models.JSONField(default=list, blank=True)  # [{code, detail}]

    self_report = models.CharField(max_length=20, blank=True, default='')
    final_label = models.CharField(max_length=20, choices=LABEL_CHOICES)

    has_timeline = models.BooleanField(default=False)
    classifier_version = models.CharField(max_length=10, default=CLASSIFIER_VERSION)
    computed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Response Diagnosis'
        verbose_name_plural = 'Response Diagnoses'
        constraints = _per_attempt_item_constraints('diagnosis')
        indexes = [
            models.Index(fields=['student', 'computed_at']),
            models.Index(fields=['tenant', 'final_label']),
        ]

    def __str__(self):
        return f'{self.attempt_kind}:{self.attempt_id} {self.final_label}'
```

- [ ] **Step 7: Generate the migration**

Run: `venv/Scripts/python.exe manage.py makemigrations intelligence -n response_diagnosis`
Expected: `intelligence/migrations/0003_response_diagnosis.py` creating 3 models and adding 2 ItemStats fields. Then `venv/Scripts/python.exe manage.py makemigrations --check --dry-run` → `No changes detected`.

- [ ] **Step 8: Run tests to verify they pass**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_diagnose -v 2`
Expected: 5 tests PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/intelligence backend/core/models.py
git commit -m "feat(intelligence): response diagnosis schema and opt-in feature key

AttemptTimeline (raw per-question interaction log), ResponseSelfReport,
ResponseDiagnosis, ItemStats active-time fields; CLASSIFIER_VERSION and
STATE_MODEL_VERSION 2.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Pure timeline reducer

**Files:**
- Create: `backend/intelligence/services/timeline.py`
- Test: `backend/intelligence/tests/test_timeline.py`

**Interfaces:**
- Produces:
  - `TimelineError(ValueError)`, `MAX_EVENTS = 5000`
  - `clean_events(events) -> list[tuple[float, str, str | None, dict | None]]`
  - `KeyTimeline` dataclass: `active_s, hidden_s, visits, first_enter_at_s, first_answer_active_s, final_answer_at_s, answers: list[(at_s, digest | None)]`
  - `window_start_s(sessions, clock) -> float`
  - `reduce_sessions(sessions, *, clock, known_keys=None) -> dict[str, KeyTimeline]` — all `*_at_s` values are seconds relative to the window start.

- [ ] **Step 1: Write the failing tests**

Create `backend/intelligence/tests/test_timeline.py`:

```python
"""Timeline reduction (pure) — raw browser events to per-question timing."""
from django.test import SimpleTestCase

from intelligence.services.timeline import (
    MAX_EVENTS, TimelineError, clean_events, reduce_sessions, window_start_s,
)


def one(events, *, offset_ms=0, clock='server', known_keys=None):
    sessions = {'s1': {'offset_ms': offset_ms, 'events': events}}
    return reduce_sessions(sessions, clock=clock, known_keys=known_keys)


class CleanEventsTests(SimpleTestCase):
    def test_accepts_and_sorts(self):
        cleaned = clean_events([[5, 'l', 'bank:a'], [0, 'e', 'bank:a'], [2, 'h', None]])
        self.assertEqual([e[0] for e in cleaned], [0.0, 2.0, 5.0])

    def test_rejects_bad_shapes(self):
        for bad in (
            'nope',
            [[0]],
            [[-1, 'e', 'bank:a']],
            [[0, 'x', 'bank:a']],
            [[0, 'e', None]],
            [[0, 'a', 'bank:a', 'not-a-dict']],
            [[True, 'e', 'bank:a']],
        ):
            with self.assertRaises(TimelineError, msg=repr(bad)):
                clean_events(bad)

    def test_rejects_too_many(self):
        with self.assertRaises(TimelineError):
            clean_events([[i, 'h', None] for i in range(MAX_EVENTS + 1)])


class ReduceTests(SimpleTestCase):
    def test_single_visit(self):
        lines = one([[0, 'e', 'bank:a'], [10000, 'l', 'bank:a']])
        self.assertAlmostEqual(lines['bank:a'].active_s, 10.0)
        self.assertEqual(lines['bank:a'].visits, 1)
        self.assertEqual(lines['bank:a'].first_enter_at_s, 0.0)

    def test_hidden_time_inside_a_visit_is_not_active(self):
        lines = one([[0, 'e', 'bank:a'], [2000, 'h', None], [5000, 's', None],
                     [10000, 'l', 'bank:a']])
        self.assertAlmostEqual(lines['bank:a'].active_s, 7.0)
        self.assertAlmostEqual(lines['bank:a'].hidden_s, 3.0)

    def test_hidden_when_the_visit_closes(self):
        lines = one([[0, 'e', 'bank:a'], [8000, 'h', None], [10000, 'l', 'bank:a']])
        self.assertAlmostEqual(lines['bank:a'].active_s, 8.0)
        self.assertAlmostEqual(lines['bank:a'].hidden_s, 2.0)

    def test_unmatched_enter_closes_at_next_enter_and_session_end(self):
        lines = one([[0, 'e', 'bank:a'], [4000, 'e', 'bank:b'],
                     [6000, 'a', 'bank:b', {'sel': [1]}]])
        self.assertAlmostEqual(lines['bank:a'].active_s, 4.0)
        self.assertAlmostEqual(lines['bank:b'].active_s, 2.0)
        self.assertAlmostEqual(lines['bank:b'].first_answer_active_s, 2.0)
        self.assertEqual(lines['bank:b'].answers, [(6.0, {'sel': [1]})])
        self.assertAlmostEqual(lines['bank:b'].final_answer_at_s, 6.0)

    def test_clear_is_recorded_as_none(self):
        lines = one([[0, 'e', 'bank:a'], [1000, 'a', 'bank:a', {'sel': [0]}],
                     [2000, 'c', 'bank:a'], [3000, 'l', 'bank:a']])
        self.assertEqual(lines['bank:a'].answers, [(1.0, {'sel': [0]}), (2.0, None)])

    def test_sessions_merge_in_offset_order_on_server_clock(self):
        sessions = {
            'late': {'offset_ms': 100000, 'events': [
                [0, 'e', 'item:x'], [2000, 'a', 'item:x', {'sel': [1]}], [3000, 'l', 'item:x']]},
            'early': {'offset_ms': 0, 'events': [[0, 'e', 'item:x'], [5000, 'l', 'item:x']]},
        }
        line = reduce_sessions(sessions, clock='server')['item:x']
        self.assertAlmostEqual(line.active_s, 8.0)
        self.assertEqual(line.visits, 2)
        self.assertAlmostEqual(line.first_enter_at_s, 0.0)
        self.assertAlmostEqual(line.final_answer_at_s, 102.0)
        # first answer happened after 5s (session 1) + 2s (session 2) on screen
        self.assertAlmostEqual(line.first_answer_active_s, 7.0)

    def test_client_clock_window_starts_at_the_session(self):
        sessions = {'s1': {'offset_ms': 50000, 'events': [[1000, 'e', 'bank:a'],
                                                          [3000, 'l', 'bank:a']]}}
        self.assertAlmostEqual(window_start_s(sessions, 'client'), 50.0)
        self.assertAlmostEqual(window_start_s(sessions, 'server'), 0.0)
        line = reduce_sessions(sessions, clock='client')['bank:a']
        self.assertAlmostEqual(line.first_enter_at_s, 1.0)

    def test_unknown_keys_are_ignored(self):
        lines = one([[0, 'e', 'bank:ghost'], [1000, 'l', 'bank:ghost']],
                    known_keys={'bank:a'})
        self.assertNotIn('bank:ghost', lines)

    def test_corrupt_stored_session_is_skipped_not_fatal(self):
        sessions = {'bad': {'offset_ms': 0, 'events': [[0, 'zz', 'x']]},
                    'ok': {'offset_ms': 0, 'events': [[0, 'e', 'bank:a'], [1000, 'l', 'bank:a']]}}
        self.assertAlmostEqual(reduce_sessions(sessions, clock='server')['bank:a'].active_s, 1.0)
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_timeline -v 2`
Expected: ERROR — `ModuleNotFoundError: No module named 'intelligence.services.timeline'`.

- [ ] **Step 3: Implement**

Create `backend/intelligence/services/timeline.py`:

```python
"""Raw interaction timelines → per-question timing facts (pure reduction).

The browser records only raw events (``hooks/useResponseTimeline.js``); every
interpretation happens here so it is versioned and testable. Event tuples are
``[t_ms, code, key, value?]`` with ``t_ms`` relative to the session start:

    e / l   enter / leave a question       h / s   tab hidden / shown
    a       answer set (value = digest)    c       answer cleared

Digests: ``{"sel": [1, 3]}``, ``{"num": "3.14"}``, ``{"txt": 120}``,
``{"code": 480}``.
"""
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

MAX_EVENTS = 5000
CODES = {'e', 'l', 'h', 's', 'a', 'c'}
KEYED_CODES = {'e', 'l', 'a', 'c'}
MAX_KEY_LENGTH = 80


class TimelineError(ValueError):
    """Malformed payload — rejected whole, never partially stored."""


@dataclass
class KeyTimeline:
    """What one question's timeline says. ``*_at_s`` are seconds relative to
    the timing window start; durations are seconds."""
    active_s: float = 0.0
    hidden_s: float = 0.0
    visits: int = 0
    first_enter_at_s: float | None = None
    first_answer_active_s: float | None = None
    final_answer_at_s: float | None = None
    answers: list = field(default_factory=list)  # [(at_s, digest | None)]; None = cleared


def clean_events(events):
    """Validate a session's events; return (t_ms, code, key, value) sorted by t."""
    if not isinstance(events, list):
        raise TimelineError('events must be a list')
    if len(events) > MAX_EVENTS:
        raise TimelineError(f'at most {MAX_EVENTS} events per session')
    cleaned = []
    for index, raw in enumerate(events):
        if not isinstance(raw, (list, tuple)) or len(raw) < 2:
            raise TimelineError(f'event {index} is not a tuple')
        t, code = raw[0], raw[1]
        key = raw[2] if len(raw) > 2 else None
        value = raw[3] if len(raw) > 3 else None
        if isinstance(t, bool) or not isinstance(t, (int, float)) or t < 0:
            raise TimelineError(f'event {index} has a bad time')
        if code not in CODES:
            raise TimelineError(f'event {index} has an unknown code')
        if code in KEYED_CODES and (
                not isinstance(key, str) or not key or len(key) > MAX_KEY_LENGTH):
            raise TimelineError(f'event {index} needs a question key')
        if value is not None and not isinstance(value, dict):
            raise TimelineError(f'event {index} has a bad value')
        cleaned.append((float(t), code, key, value))
    cleaned.sort(key=lambda event: event[0])  # stable: equal times keep order
    return cleaned


def _offset_s(session):
    return float(session.get('offset_ms') or 0) / 1000.0


def window_start_s(sessions, clock):
    """Where the timing window starts, in seconds after the attempt anchor.

    Server-timed attempts run from ``started_at`` itself; client-timed and
    untimed ones from their earliest session (a client-timed row only ever
    keeps one session — see timeline_sync).
    """
    if clock == 'server' or not sessions:
        return 0.0
    return min(_offset_s(session) for session in sessions.values())


def _fold_session(events, base_s, out, known_keys):
    """Fold one session's cleaned events into ``out`` (key → KeyTimeline).
    ``base_s`` is this session's start relative to the window start."""
    current = None        # key on screen
    entered = None        # t (ms) the current visit began
    visit_hidden = 0.0    # hidden ms already closed inside this visit
    hidden_since = None   # t (ms) the tab went hidden; None while visible

    def line(key):
        return out.setdefault(key, KeyTimeline())

    def open_hidden(t):
        return (t - max(hidden_since, entered)) if hidden_since is not None else 0.0

    def close(t):
        nonlocal current, entered, visit_hidden
        if current is None:
            return
        duration = max(0.0, t - entered)
        hidden = min(max(0.0, visit_hidden + open_hidden(t)), duration)
        kt = line(current)
        kt.active_s += (duration - hidden) / 1000.0
        kt.hidden_s += hidden / 1000.0
        current, entered, visit_hidden = None, None, 0.0

    def active_so_far(key, t):
        total = line(key).active_s
        if current == key:
            total += max(0.0, (t - entered) - visit_hidden - open_hidden(t)) / 1000.0
        return total

    last_t = 0.0
    for t, code, key, value in events:
        last_t = t
        if key is not None and known_keys is not None and key not in known_keys:
            continue
        at_s = base_s + t / 1000.0
        if code == 'e':
            close(t)
            current, entered, visit_hidden = key, t, 0.0
            kt = line(key)
            kt.visits += 1
            if kt.first_enter_at_s is None or at_s < kt.first_enter_at_s:
                kt.first_enter_at_s = at_s
        elif code == 'l':
            close(t)
        elif code == 'h':
            if hidden_since is None:
                hidden_since = t
        elif code == 's':
            if hidden_since is not None:
                if current is not None:
                    visit_hidden += t - max(hidden_since, entered)
                hidden_since = None
        else:  # 'a' / 'c'
            kt = line(key)
            if code == 'a' and kt.first_answer_active_s is None:
                kt.first_answer_active_s = active_so_far(key, t)
            kt.answers.append((at_s, value if code == 'a' else None))
            if kt.final_answer_at_s is None or at_s > kt.final_answer_at_s:
                kt.final_answer_at_s = at_s
    close(last_t)


def reduce_sessions(sessions, *, clock, known_keys=None):
    """key → KeyTimeline across every session, times relative to the window.

    A stored session that no longer validates is skipped (logged), so one
    corrupt session never hides the others.
    """
    out = {}
    start = window_start_s(sessions, clock)
    for session in sorted((sessions or {}).values(), key=_offset_s):
        try:
            events = clean_events(session.get('events') or [])
        except TimelineError:
            logger.warning('timeline: skipping a corrupt stored session')
            continue
        _fold_session(events, _offset_s(session) - start, out, known_keys)
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_timeline -v 2`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/intelligence/services/timeline.py backend/intelligence/tests/test_timeline.py
git commit -m "feat(intelligence): pure reducer from raw timelines to per-question timing

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Timeline sync service + endpoint

**Files:**
- Create: `backend/intelligence/services/timeline_sync.py`
- Modify: `backend/intelligence/views.py` (append `TimelineThrottle`, `TimelineSyncView`)
- Modify: `backend/intelligence/urls.py`
- Test: append to `backend/intelligence/tests/test_timeline.py`

**Interfaces:**
- Consumes: `clean_events`, `TimelineError` (Task 3); `AttemptTimeline` (Task 2).
- Produces:
  - `TimelineFinalized(TimelineError)`
  - `resolve_attempt(kind, student, *, attempt_id=None, parent_id=None, now=None) -> (uuid, anchor_datetime, clock)`
  - `save_session(*, kind, student, session_id, elapsed_ms, events, truncated, attempt_id=None, parent_id=None, now=None) -> AttemptTimeline`
  - route `POST /api/v1/intelligence/timeline/`

- [ ] **Step 1: Write the failing endpoint tests**

Add these imports to the **top** of `backend/intelligence/tests/test_timeline.py` (merge with the existing import block):

```python
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from intelligence.models import AttemptTimeline, PracticeSet
from intelligence.tests.diagnosis_fixtures import DiagnosisTestCase
```

Then append to the end of the file:

```python
URL = '/api/v1/intelligence/timeline/'


class TimelineSyncTests(DiagnosisTestCase):
    def setUp(self):
        cache.clear()  # the 20/min throttle must not leak between tests

    def client_for(self, user):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(user).access_token}')
        return client

    def post(self, payload, user=None):
        return self.client_for(user or self.user).post(
            URL, payload, format='json', HTTP_X_TENANT_ID=str(self.tenant.id),
        )

    def payload(self, **overrides):
        body = {'attempt_kind': 'mock', 'session_id': 'sess-1', 'elapsed_ms': 1000,
                'truncated': False, 'events': [[0, 'e', 'item:a'], [900, 'l', 'item:a']]}
        body.update(overrides)
        return body

    def test_rich_mock_sync_anchors_offset_on_the_server(self):
        attempt = self.make_attempt(minutes_ago=30)
        response = self.post(self.payload(attempt_id=str(attempt.id)))
        self.assertEqual(response.status_code, 200, response.content)
        row = AttemptTimeline.objects.get(attempt_id=attempt.id)
        self.assertEqual(row.clock, 'server')
        self.assertEqual(row.student, self.student)
        offset = row.sessions['sess-1']['offset_ms']
        self.assertAlmostEqual(offset, 30 * 60 * 1000 - 1000, delta=5000)

    def test_resend_replaces_the_session(self):
        attempt = self.make_attempt()
        self.post(self.payload(attempt_id=str(attempt.id)))
        self.post(self.payload(attempt_id=str(attempt.id), events=[[0, 'e', 'item:a']]))
        row = AttemptTimeline.objects.get(attempt_id=attempt.id)
        self.assertEqual(len(row.sessions), 1)
        self.assertEqual(len(row.sessions['sess-1']['events']), 1)

    def test_parent_id_resolves_in_progress_attempt_with_client_clock(self):
        attempt = self.make_attempt()
        self.post(self.payload(parent_id=str(self.mock_test.id)))
        self.post(self.payload(parent_id=str(self.mock_test.id), session_id='sess-2'))
        row = AttemptTimeline.objects.get(attempt_id=attempt.id)
        self.assertEqual(row.clock, 'client')
        # a client-timed screen restarted: only the newest session survives
        self.assertEqual(list(row.sessions), ['sess-2'])

    def test_other_students_attempt_is_rejected(self):
        attempt = self.make_attempt(student=self.other_user.profile)
        response = self.post(self.payload(attempt_id=str(attempt.id)))
        self.assertEqual(response.status_code, 400)
        self.assertFalse(AttemptTimeline.objects.exists())

    def test_finished_attempt_window(self):
        attempt = self.make_attempt(minutes_ago=30)
        attempt.status = 'completed'
        attempt.completed_at = timezone.now() - timedelta(seconds=30)
        attempt.save()
        self.assertEqual(self.post(self.payload(attempt_id=str(attempt.id))).status_code, 200)
        attempt.completed_at = timezone.now() - timedelta(minutes=10)
        attempt.save()
        self.assertEqual(
            self.post(self.payload(attempt_id=str(attempt.id), session_id='late')).status_code, 400)

    def test_finalized_timeline_is_refused(self):
        attempt = self.make_attempt()
        row = self.make_timeline(attempt, [])
        row.finalized_at = timezone.now()
        row.save()
        self.assertEqual(self.post(self.payload(attempt_id=str(attempt.id))).status_code, 409)

    def test_bad_events_and_ids_are_400(self):
        attempt = self.make_attempt()
        self.assertEqual(self.post(self.payload(
            attempt_id=str(attempt.id), events=[[0, 'zz', 'x']])).status_code, 400)
        self.assertEqual(self.post(self.payload(attempt_id='not-a-uuid')).status_code, 400)
        self.assertEqual(self.post(self.payload(attempt_kind='exam',
                                                attempt_id=str(attempt.id))).status_code, 400)

    def test_oversized_body_is_413(self):
        attempt = self.make_attempt()
        key = 'item:' + 'x' * 70
        events = [[i, 'a', key, {'txt': i}] for i in range(4000)]
        response = self.post(self.payload(attempt_id=str(attempt.id), events=events))
        self.assertEqual(response.status_code, 413)

    def test_suggested_practice_set_syncs_untimed(self):
        practice_set = PracticeSet.objects.create(
            tenant=self.tenant, student=self.student, course=self.course,
            status='suggested', deficit_kind='starter', deficit_signature='starter:test',
        )
        response = self.post(self.payload(attempt_kind='practice',
                                          attempt_id=str(practice_set.id)))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(AttemptTimeline.objects.get(attempt_id=practice_set.id).clock, 'none')
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_timeline.TimelineSyncTests -v 2`
Expected: FAIL — 404 responses (route missing).

- [ ] **Step 3: Implement the service**

Create `backend/intelligence/services/timeline_sync.py`:

```python
"""Timeline sync: attach one browser session's raw events to its attempt.

Attempt resolution mirrors the submit endpoints: rich mocks and practice
sets send their id; quizzes and legacy mocks/PYPs send their parent (quiz or
mock test) id and the student's in-progress attempt is used.
"""
import uuid
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from intelligence.models import AttemptTimeline
from intelligence.services.timeline import TimelineError, clean_events

SYNC_GRACE = timedelta(seconds=120)  # a late flush right after submit still lands
KINDS = ('quiz', 'mock', 'practice')


class TimelineFinalized(TimelineError):
    """Diagnosis already consumed this attempt's timeline."""


def _uuid_or_none(value):
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError:
        raise TimelineError('bad id')


def _open(obj, now):
    """In progress, or finished within the grace window."""
    return obj.completed_at is None or now - obj.completed_at <= SYNC_GRACE


def resolve_attempt(kind, student, *, attempt_id=None, parent_id=None, now=None):
    """Return ``(attempt uuid, anchor datetime, clock)`` or raise TimelineError."""
    from quiz.models import MockTestAttempt, QuizAttempt

    from intelligence.models import PracticeSet

    now = now or timezone.now()
    if kind not in KINDS:
        raise TimelineError('unknown attempt kind')
    attempt_id = _uuid_or_none(attempt_id)
    parent_id = _uuid_or_none(parent_id)

    if kind == 'practice':
        practice_set = (
            PracticeSet.objects.filter(id=attempt_id, student=student).first()
            if attempt_id else None
        )
        if practice_set is None:
            raise TimelineError('practice set not found')
        if practice_set.status not in ('suggested', 'in_progress') and not (
                practice_set.status == 'completed' and _open(practice_set, now)):
            raise TimelineError('practice set is closed')
        return practice_set.id, practice_set.created_at, 'none'

    model = QuizAttempt if kind == 'quiz' else MockTestAttempt
    if attempt_id:
        attempt = model.objects.filter(id=attempt_id, student=student).first()
    elif parent_id:
        parent_field = 'quiz_id' if kind == 'quiz' else 'mock_test_id'
        attempt = (
            model.objects.filter(student=student, status='in_progress',
                                 **{parent_field: parent_id})
            .order_by('-started_at').first()
        )
    else:
        attempt = None
    if attempt is None:
        raise TimelineError('attempt not found')
    if attempt.status != 'in_progress' and not (
            attempt.completed_at and _open(attempt, now)):
        raise TimelineError('attempt is closed')
    clock = 'client' if (kind == 'quiz' or not attempt_id) else 'server'
    return attempt.id, attempt.started_at, clock


def save_session(*, kind, student, session_id, elapsed_ms, events, truncated,
                 attempt_id=None, parent_id=None, now=None):
    """Validate and store one session snapshot. Returns the AttemptTimeline."""
    now = now or timezone.now()
    if not isinstance(session_id, str) or not 1 <= len(session_id) <= 64:
        raise TimelineError('bad session id')
    if isinstance(elapsed_ms, bool) or not isinstance(elapsed_ms, (int, float)) or elapsed_ms < 0:
        raise TimelineError('bad elapsed_ms')
    cleaned = clean_events(events)
    resolved_id, anchor, clock = resolve_attempt(
        kind, student, attempt_id=attempt_id, parent_id=parent_id, now=now,
    )
    offset_ms = max(0.0, (now - anchor).total_seconds() * 1000.0 - float(elapsed_ms))
    stored_events = [
        [t, code, key] + ([value] if value is not None else [])
        for t, code, key, value in cleaned
    ]

    with transaction.atomic():
        row, _created = AttemptTimeline.objects.select_for_update().get_or_create(
            attempt_kind=kind, attempt_id=resolved_id,
            defaults={'student': student, 'tenant': student.user.tenant, 'clock': clock},
        )
        if row.student_id != student.id:
            raise TimelineError('attempt not found')
        if row.finalized_at is not None:
            raise TimelineFinalized('attempt already diagnosed')
        sessions = dict(row.sessions or {})
        if clock == 'client' and session_id not in sessions:
            # The client timer restarted with the page; older sessions are void.
            sessions = {}
        sessions[session_id] = {
            'offset_ms': round(offset_ms, 1),
            'events': stored_events,
            'received_at': now.isoformat(),
            'truncated': bool(truncated),
        }
        row.sessions = sessions
        row.clock = clock
        row.save(update_fields=['sessions', 'clock', 'updated_at'])
    return row
```

- [ ] **Step 4: Implement the view and route**

Append to `backend/intelligence/views.py`:

```python
class TimelineThrottle(UserRateThrottle):
    rate = '20/min'


MAX_TIMELINE_BODY = 256 * 1024


class TimelineSyncView(APIView):
    """Browser → raw per-question timeline for an attempt.

    Always on (no feature gate): capture accrues regardless, exactly like the
    learning-event log, so enabling Answer Diagnosis later has history.
    """

    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [TimelineThrottle]

    def post(self, request):
        from .services.timeline import TimelineError
        from .services.timeline_sync import TimelineFinalized, save_session

        try:
            length = int(request.META.get('CONTENT_LENGTH') or 0)
        except ValueError:
            length = 0
        if length > MAX_TIMELINE_BODY:
            return Response({'error': 'Timeline too large.'},
                            status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        student = _student_or_none(request)
        if student is None:
            return Response({'error': 'Students only.'}, status=status.HTTP_403_FORBIDDEN)
        data = request.data
        try:
            save_session(
                kind=data.get('attempt_kind'), student=student,
                attempt_id=data.get('attempt_id'), parent_id=data.get('parent_id'),
                session_id=data.get('session_id'), elapsed_ms=data.get('elapsed_ms'),
                events=data.get('events'), truncated=bool(data.get('truncated')),
            )
        except TimelineFinalized:
            return Response({'error': 'This attempt was already diagnosed.'},
                            status=status.HTTP_409_CONFLICT)
        except TimelineError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'ok': True})
```

Replace `backend/intelligence/urls.py` with:

```python
"""Student-facing intelligence routes, mounted at /api/v1/intelligence/."""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import MasteryView, PracticeRefreshView, PracticeSetViewSet, TimelineSyncView

router = DefaultRouter()
router.register(r'practice/sets', PracticeSetViewSet, basename='practice-sets')

urlpatterns = [
    path('', include(router.urls)),
    path('practice/refresh/', PracticeRefreshView.as_view(), name='practice-refresh'),
    path('mastery/', MasteryView.as_view(), name='intelligence-mastery'),
    path('timeline/', TimelineSyncView.as_view(), name='intelligence-timeline'),
]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_timeline -v 2`
Expected: all PASS. If `test_oversized_body_is_413` returns 400, confirm the payload exceeds 256 KB (`len(json.dumps(events)) > 262144`) and increase the event count. It must stay ≤ 5000.

- [ ] **Step 6: Commit**

```bash
git add backend/intelligence/services/timeline_sync.py backend/intelligence/views.py backend/intelligence/urls.py backend/intelligence/tests/test_timeline.py
git commit -m "feat(intelligence): timeline sync endpoint with server-anchored offsets

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Pure classifier — config, `classify`, `reconcile`, `slip_match`

**Files:**
- Create: `backend/intelligence/diagnosis_config.py`
- Create: `backend/intelligence/services/diagnosis.py`
- Test: `backend/intelligence/tests/test_diagnosis_rules.py`

**Interfaces:**
- Produces:
  - `diagnosis_config.THRESHOLDS`, `DEFAULT_USUAL_S`, `MCQ_TYPES`, `TIMELESS_TYPES`, `LABEL_WEIGHTS`, `SELF_REPORT_LABEL`
  - dataclasses `ItemFacts`, `TimingFacts`, `WindowFacts`, `Diagnosis(label, confidence, flags, evidence, metrics)`
  - `usual_seconds(facts) -> (float | None, 'stats' | 'default' | 'none')`
  - `slip_match(value, correct, tolerance) -> bool`
  - `classify(facts, timing: TimingFacts | None, window) -> Diagnosis`
  - `reconcile(label, confidence, flags, self_report, timed_out) -> str`

- [ ] **Step 1: Write the failing tests**

Create `backend/intelligence/tests/test_diagnosis_rules.py`:

```python
"""The diagnosis rules as the pure functions they are — one case per label,
plus the edges that make the labels trustworthy."""
from django.test import SimpleTestCase

from intelligence.services.diagnosis import (
    ItemFacts, TimingFacts, WindowFacts, classify, reconcile, slip_match, usual_seconds,
)

HOUR = WindowFacts(duration_s=3600, elapsed_s=1800, timed_out=False)
UNTIMED = WindowFacts(duration_s=None, elapsed_s=600, timed_out=False)


def item(**kw):
    base = {'item_type': 'mcq', 'difficulty': 'medium', 'answered': True, 'score_fraction': 0.0}
    base.update(kw)
    return ItemFacts(**base)


def timing(active, **kw):
    base = {'active_s': active, 'visits': 1, 'first_enter_at_s': 100.0,
            'final_answer_at_s': 100.0 + active}
    base.update(kw)
    return TimingFacts(**base)


class UsualTimeTests(SimpleTestCase):
    def test_stats_beat_defaults(self):
        self.assertEqual(usual_seconds(item(usual_s=33.0)), (33.0, 'stats'))
        self.assertEqual(usual_seconds(item()), (70.0, 'default'))
        self.assertEqual(usual_seconds(item(item_type='numerical', difficulty='hard')),
                         (160.0, 'default'))
        self.assertEqual(usual_seconds(item(difficulty='')), (70.0, 'default'))
        self.assertEqual(usual_seconds(item(item_type='subjective')), (None, 'none'))


class SlipMatchTests(SimpleTestCase):
    def test_transforms(self):
        self.assertTrue(slip_match(-9.81, 9.81, 0.01))      # sign
        self.assertTrue(slip_match(98.1, 9.81, 0.01))       # ×10
        self.assertTrue(slip_match(0.00981, 9.81, 0.01))    # ÷1000
        self.assertTrue(slip_match(588.6, 9.81, 0.01))      # ×60
        self.assertTrue(slip_match(9.8, 9.81, 0.001))       # 2 sig figs
        self.assertFalse(slip_match(7.0, 9.81, 0.01))
        self.assertFalse(slip_match(0, 9.81, 0.01))
        self.assertFalse(slip_match(5.0, 0, 0.01))
        self.assertFalse(slip_match(None, 9.81, 0.01))


class LabelTests(SimpleTestCase):
    def test_not_seen(self):
        d = classify(item(answered=False), timing(1.0), HOUR)
        self.assertEqual((d.label, d.confidence), ('not_seen', 'high'))
        d = classify(item(answered=False), TimingFacts(), HOUR)
        self.assertEqual(d.label, 'not_seen')

    def test_skipped(self):
        d = classify(item(answered=False), timing(40.0, final_answer_at_s=None), HOUR)
        self.assertEqual(d.label, 'skipped')

    def test_unanswered_time_pressure(self):
        window = WindowFacts(duration_s=3600, elapsed_s=3600, timed_out=True)
        late = timing(20.0, first_enter_at_s=3300.0, final_answer_at_s=None)
        self.assertEqual(classify(item(answered=False), late, window).label, 'time_pressure')
        # same item, but the test was submitted early: just a skip
        early = WindowFacts(duration_s=3600, elapsed_s=2000, timed_out=False)
        self.assertEqual(classify(item(answered=False), late, early).label, 'skipped')

    def test_unanswered_without_timeline_is_unclear(self):
        d = classify(item(answered=False), None, HOUR)
        self.assertEqual((d.label, d.confidence), ('unclear', 'low'))

    def test_correct_variants(self):
        self.assertEqual(classify(item(score_fraction=1.0), timing(60.0), HOUR).label, 'correct')
        self.assertEqual(classify(item(score_fraction=1.0), timing(3.0), HOUR).label,
                         'correct_lucky')
        self.assertEqual(classify(item(score_fraction=1.0), timing(200.0), HOUR).label,
                         'correct_slow')
        # numerical can't be lucky-guessed the way an MCQ can
        fast_numeric = item(item_type='numerical', score_fraction=1.0)
        self.assertEqual(classify(fast_numeric, timing(3.0), HOUR).label, 'correct')

    def test_guess(self):
        d = classify(item(), timing(3.0), HOUR)
        self.assertEqual(d.label, 'guess')
        self.assertIn('too_fast', d.flags)
        self.assertEqual(d.confidence, 'medium')            # default usual time
        d = classify(item(usual_s=60.0), timing(3.0), HOUR)
        self.assertEqual(d.confidence, 'high')              # stats usual time

    def test_second_guess(self):
        t = timing(60.0, answer_correctness=[True, False])
        d = classify(item(), t, HOUR)
        self.assertEqual((d.label, d.confidence), ('second_guess', 'high'))
        self.assertIn('right_to_wrong', d.flags)

    def test_time_pressure_when_rushed_in_the_last_minute(self):
        t = timing(20.0, final_answer_at_s=3570.0)
        d = classify(item(), t, HOUR)
        self.assertEqual(d.label, 'time_pressure')
        self.assertIn('last_minute', d.flags)
        self.assertIn('rushed', d.flags)

    def test_careless_slip_by_numeric_transform(self):
        f = item(item_type='numerical', numeric_value=98.1, numeric_correct=9.81,
                 numeric_tolerance=0.01)
        d = classify(f, timing(60.0), HOUR)
        self.assertEqual((d.label, d.confidence), ('careless_slip', 'high'))

    def test_careless_slip_by_mastery(self):
        f = item(prior_mastery=0.85, prior_confidence='high')
        self.assertEqual(classify(f, timing(60.0), HOUR).label, 'careless_slip')

    def test_concept_gap(self):
        weak = item(prior_mastery=0.3, prior_confidence='medium')
        self.assertEqual(classify(weak, timing(60.0), HOUR).label, 'concept_gap')
        self.assertEqual(classify(item(misconception_pick=True), timing(60.0), HOUR).label,
                         'concept_gap')
        self.assertEqual(classify(item(), timing(200.0), HOUR).label, 'concept_gap')

    def test_conflict_is_unclear(self):
        strong_but_slow = item(prior_mastery=0.9, prior_confidence='high')
        d = classify(strong_but_slow, timing(200.0), HOUR)
        self.assertEqual((d.label, d.confidence), ('unclear', 'low'))

    def test_low_confidence_mastery_is_ignored(self):
        f = item(prior_mastery=0.9, prior_confidence='low')
        self.assertEqual(classify(f, timing(60.0), HOUR).label, 'unclear')

    def test_no_timeline_still_uses_non_time_signals(self):
        f = item(item_type='numerical', numeric_value=-9.81, numeric_correct=9.81,
                 numeric_tolerance=0.01)
        d = classify(f, None, HOUR)
        self.assertEqual(d.label, 'careless_slip')
        self.assertIn('no_timeline', [e['code'] for e in d.evidence])

    def test_untimed_never_has_time_pressure(self):
        d = classify(item(), timing(20.0, final_answer_at_s=599.0), UNTIMED)
        self.assertNotIn('last_minute', d.flags)
        self.assertNotEqual(d.label, 'time_pressure')

    def test_pending_grade_is_unclear(self):
        f = item(item_type='subjective', pending_grade=True)
        self.assertEqual(classify(f, timing(300.0), HOUR).label, 'unclear')

    def test_near_threshold_on_default_usual_lowers_confidence(self):
        # default usual 70s → too_long cut 175s; 180s is within 20% of it
        d = classify(item(score_fraction=1.0), timing(180.0), HOUR)
        self.assertEqual((d.label, d.confidence), ('correct_slow', 'low'))

    def test_metrics_are_recorded(self):
        d = classify(item(), timing(35.0), HOUR)
        self.assertEqual(d.metrics['usual_s'], 70.0)
        self.assertEqual(d.metrics['usual_source'], 'default')
        self.assertAlmostEqual(d.metrics['rel_speed'], 0.5)
        self.assertEqual(d.metrics['active_s'], 35.0)


class ReconcileTests(SimpleTestCase):
    def test_confident_label_wins(self):
        self.assertEqual(reconcile('concept_gap', 'medium', [], 'slipped', False), 'concept_gap')

    def test_unclear_adopts_self_report(self):
        self.assertEqual(reconcile('unclear', 'low', [], 'slipped', False), 'careless_slip')
        self.assertEqual(reconcile('unclear', 'low', [], 'guessed', False), 'guess')
        self.assertEqual(reconcile('unclear', 'low', [], 'didnt_know', False), 'concept_gap')

    def test_behaviour_vetoes_implausible_reports(self):
        self.assertEqual(reconcile('unclear', 'low', ['too_fast'], 'slipped', False), 'unclear')
        self.assertEqual(reconcile('unclear', 'low', [], 'ran_out_of_time', False), 'unclear')
        self.assertEqual(reconcile('unclear', 'low', ['last_minute'], 'ran_out_of_time', False),
                         'time_pressure')
        self.assertEqual(reconcile('unclear', 'low', [], 'ran_out_of_time', True),
                         'time_pressure')

    def test_no_report(self):
        self.assertEqual(reconcile('unclear', 'low', [], '', False), 'unclear')
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_diagnosis_rules -v 2`
Expected: ERROR — `ModuleNotFoundError: No module named 'intelligence.services.diagnosis'`.

- [ ] **Step 3: Write the config**

Create `backend/intelligence/diagnosis_config.py`:

```python
"""Response-diagnosis tuning knobs, in one place.

Changing any value changes labels: bump ``versions.CLASSIFIER_VERSION`` and
run ``manage.py recompute_diagnoses``. Calibrate against self-reports with
GET /api/v1/tenant-admin/intelligence/diagnosis/calibration/.
"""

THRESHOLDS = {
    'not_seen_active_s': 2.0,       # under this on screen = never really looked
    'too_fast_floor_s': 5.0,        # too_fast: active < max(floor, ratio × usual)
    'too_fast_ratio': 0.25,
    'too_long_ratio': 2.5,          # too_long: active > ratio × usual
    'last_minute_floor_s': 60.0,    # last-minute zone: max(floor, ratio × duration)
    'last_minute_ratio': 0.05,
    'rushed_ratio': 0.6,            # rushed: last_minute and rel_speed < ratio
    'late_entry_ratio': 0.15,       # unanswered time pressure: first seen in last 15%
    'unanswered_short_ratio': 0.5,  # … or seen for under half the usual time
    'slip_mastery': 0.75,           # prior mastery that makes a wrong answer a slip
    'gap_mastery': 0.5,             # prior mastery that makes it a concept gap
    'slip_speed_min': 0.5,          # a slip happens at a normal pace
    'slip_speed_max': 2.5,
    'stats_min_n': 20,              # ItemStats median trusted from this many timings
    'near_threshold_band': 0.2,     # default-usual call within 20% of a cut → low
}

# Seconds a question usually takes, until ItemStats has enough timings.
_SINGLE = {'easy': 40.0, 'medium': 70.0, 'hard': 110.0}
_MULTI = {'easy': 60.0, 'medium': 95.0, 'hard': 140.0}
_WORKED = {'easy': 60.0, 'medium': 100.0, 'hard': 160.0}
DEFAULT_USUAL_S = {
    'mcq': _SINGLE,
    'true_false': _SINGLE,
    'mcq_multi': _MULTI,
    'match': _MULTI,
    'numerical': _WORKED,
    'fill_blank': _WORKED,
}
TIMELESS_TYPES = {'subjective', 'coding'}   # time rules never apply
MCQ_TYPES = {'mcq', 'mcq_multi', 'true_false'}

# Mastery evidence multiplier by final label (services/state.py).
LABEL_WEIGHTS = {
    'guess': 0.2,
    'correct_lucky': 0.2,
    'careless_slip': 0.5,
    'time_pressure': 0.5,
}

# Self-report choice → the label it asserts.
SELF_REPORT_LABEL = {
    'slipped': 'careless_slip',
    'ran_out_of_time': 'time_pressure',
    'guessed': 'guess',
    'didnt_know': 'concept_gap',
}
```

- [ ] **Step 4: Write the rules**

Create `backend/intelligence/services/diagnosis.py`:

```python
"""Response diagnosis rules — why a mark was won or lost (pure functions).

No database and no LLM: ``classify`` turns gathered facts into exactly one
label with a confidence and machine-readable evidence; ``reconcile`` folds
in the student's own "what happened?" answer. Facts are gathered by
``services.diagnose``. Rule order and thresholds are the spec (§4).
"""
import math
from dataclasses import dataclass, field

from intelligence.diagnosis_config import (
    DEFAULT_USUAL_S, MCQ_TYPES, SELF_REPORT_LABEL, THRESHOLDS as T, TIMELESS_TYPES,
)


@dataclass
class ItemFacts:
    item_type: str
    difficulty: str = 'medium'
    usual_s: float | None = None        # ItemStats median, only when trustworthy
    answered: bool = False
    score_fraction: float = 0.0
    numeric_value: float | None = None
    numeric_correct: float | None = None
    numeric_tolerance: float = 0.0
    misconception_pick: bool = False
    prior_mastery: float | None = None
    prior_confidence: str | None = None
    pending_grade: bool = False


@dataclass
class TimingFacts:
    active_s: float = 0.0
    visits: int = 0
    first_answer_s: float | None = None
    final_answer_at_s: float | None = None
    first_enter_at_s: float | None = None
    hidden_s: float = 0.0
    answer_correctness: list = field(default_factory=list)  # graded digests, in order


@dataclass
class WindowFacts:
    duration_s: float | None = None     # None / 0 → untimed
    elapsed_s: float | None = None      # window-relative submit time
    timed_out: bool = False


@dataclass
class Diagnosis:
    label: str
    confidence: str
    flags: list
    evidence: list
    metrics: dict


def usual_seconds(facts):
    """(seconds this item usually takes, where that number came from)."""
    if facts.usual_s:
        return float(facts.usual_s), 'stats'
    if facts.item_type in TIMELESS_TYPES:
        return None, 'none'
    table = DEFAULT_USUAL_S.get(facts.item_type, DEFAULT_USUAL_S['mcq'])
    return table.get(facts.difficulty or 'medium', table['medium']), 'default'


def _round_sig(value, digits):
    return round(value, digits - 1 - int(math.floor(math.log10(abs(value)))))


def slip_match(value, correct, tolerance):
    """Does a wrong numerical answer equal the right one under a common slip?"""
    if value is None or correct is None or value == 0 or correct == 0:
        return False
    candidates = [-correct]
    for power in (1, 2, 3):
        candidates += [correct * 10 ** power, correct / 10 ** power]
    for factor in (60, 100, 1000, 3600):
        candidates += [correct * factor, correct / factor]
    for digits in (1, 2, 3):
        rounded = _round_sig(correct, digits)
        if rounded != correct:
            candidates.append(rounded)
    return any(
        abs(value - candidate) <= max(abs(tolerance), abs(candidate) * 1e-9)
        for candidate in candidates
    )


def _r(value):
    return round(value, 1) if value is not None else None


def _mastery_known(facts):
    return facts.prior_mastery is not None and facts.prior_confidence in ('medium', 'high')


def _near_threshold(rel, usual):
    cuts = (
        max(T['too_fast_floor_s'] / usual, T['too_fast_ratio']),
        T['too_long_ratio'],
        T['rushed_ratio'],
    )
    return any(abs(rel - cut) <= T['near_threshold_band'] * cut for cut in cuts)


def _label(facts, timing, window, flags, rel, zone):
    """(label, confidence, decided_by_time) — first matching rule wins."""
    has = set(flags).__contains__
    fast_confidence = 'high' if facts.usual_s else 'medium'

    if facts.pending_grade:
        return 'unclear', 'low', False

    if not facts.answered:
        if timing is None:
            return 'unclear', 'low', False
        if timing.visits == 0 or timing.active_s < T['not_seen_active_s']:
            return 'not_seen', 'high', False
        if window.duration_s:
            ended_late = window.timed_out or (
                window.elapsed_s is not None and window.duration_s - window.elapsed_s <= zone
            )
            late_entry = (
                timing.first_enter_at_s is not None
                and timing.first_enter_at_s >= window.duration_s * (1 - T['late_entry_ratio'])
            )
            short = rel is not None and rel < T['unanswered_short_ratio']
            if ended_late and (late_entry or short):
                return 'time_pressure', 'medium', True
        return 'skipped', 'medium', False

    if facts.score_fraction >= 0.5:
        if facts.item_type in MCQ_TYPES and has('too_fast'):
            return 'correct_lucky', fast_confidence, True
        if has('too_long'):
            return 'correct_slow', 'medium', True
        return 'correct', 'high', False

    if has('too_fast'):
        return 'guess', fast_confidence, True
    if has('right_to_wrong'):
        return 'second_guess', 'high', False
    if has('rushed'):
        return 'time_pressure', 'medium', True
    if has('slip_match'):
        return 'careless_slip', 'high', False

    known = _mastery_known(facts)
    strong = known and facts.prior_mastery >= T['slip_mastery'] and not has('misconception_pick')
    if strong and has('too_long'):
        return 'unclear', 'low', False   # strong on paper, yet struggled: conflict
    if strong and (rel is None or T['slip_speed_min'] <= rel <= T['slip_speed_max']):
        return 'careless_slip', 'medium', False
    if (known and facts.prior_mastery < T['gap_mastery']) or has('misconception_pick'):
        return 'concept_gap', 'medium', False
    if has('too_long'):
        return 'concept_gap', 'medium', True
    return 'unclear', 'low', False


def classify(facts, timing, window):
    """Facts → Diagnosis. ``timing`` is None when there is no usable timeline."""
    flags, evidence = [], []
    usual, source = usual_seconds(facts)
    metrics = {'usual_s': usual, 'usual_source': source}
    zone = None
    if window.duration_s:
        zone = max(T['last_minute_floor_s'], T['last_minute_ratio'] * window.duration_s)
    rel = None

    def flag(code, detail=''):
        flags.append(code)
        evidence.append({'code': code, 'detail': detail})

    if timing is None:
        evidence.append({'code': 'no_timeline', 'detail': 'no interaction timeline for this item'})
    else:
        metrics.update({
            'active_s': _r(timing.active_s), 'visits': timing.visits,
            'hidden_s': _r(timing.hidden_s), 'first_answer_s': _r(timing.first_answer_s),
            'final_answer_at_s': _r(timing.final_answer_at_s),
        })
        if usual:
            rel = timing.active_s / usual
            metrics['rel_speed'] = round(rel, 3)
            fast_cut = max(T['too_fast_floor_s'], T['too_fast_ratio'] * usual)
            if facts.answered and timing.active_s < fast_cut:
                flag('too_fast', f'{timing.active_s:.0f}s on screen; usually {usual:.0f}s')
            if timing.active_s > T['too_long_ratio'] * usual:
                flag('too_long', f'{timing.active_s:.0f}s on screen; usually {usual:.0f}s')
        if zone is not None and timing.final_answer_at_s is not None:
            time_left = window.duration_s - timing.final_answer_at_s
            metrics['time_left_s'] = _r(time_left)
            if time_left <= zone:
                flag('last_minute', f'answered with {max(0.0, time_left):.0f}s left')
                if rel is not None and rel < T['rushed_ratio']:
                    flag('rushed', f'{rel:.0%} of the usual time')
        graded = timing.answer_correctness
        if facts.answered and len(graded) >= 2:
            earlier = graded[:-1]
            final_correct = facts.score_fraction >= 0.5
            if not final_correct and any(earlier):
                flag('right_to_wrong', 'changed a correct answer to a wrong one')
            if final_correct and not all(earlier):
                flag('wrong_to_right', 'corrected an earlier wrong answer')
        if timing.hidden_s > 0:
            flag('tab_hidden', f'{timing.hidden_s:.0f}s with the tab hidden')
        if window.elapsed_s and timing.final_answer_at_s is not None:
            third = min(3, 1 + int(3 * timing.final_answer_at_s / window.elapsed_s))
            metrics['third'] = max(1, third)
            if third >= 3:
                flag('late_third', 'answered in the last third of the attempt')

    wrong = facts.answered and facts.score_fraction < 0.5 and not facts.pending_grade
    if wrong and slip_match(facts.numeric_value, facts.numeric_correct, facts.numeric_tolerance):
        flag('slip_match', f'{facts.numeric_value:g} vs {facts.numeric_correct:g}')
    if wrong and facts.misconception_pick:
        flag('misconception_pick', 'picked the same wrong option before')
    if facts.prior_mastery is not None:
        metrics['prior_mastery'] = round(facts.prior_mastery, 4)
        evidence.append({'code': 'prior_mastery',
                         'detail': f'{facts.prior_mastery:.2f} ({facts.prior_confidence})'})

    label, confidence, by_time = _label(facts, timing, window, flags, rel, zone)
    if by_time and confidence != 'low' and source == 'default' and rel is not None \
            and _near_threshold(rel, usual):
        confidence = 'low'
    return Diagnosis(label, confidence, flags, evidence, metrics)


def reconcile(label, confidence, flags, self_report, timed_out):
    """The label to act on, once the student's self-report is known.

    A confident classifier label stands. An unclear/low one adopts the
    report, unless behaviour makes the report implausible.
    """
    if not self_report or self_report not in SELF_REPORT_LABEL:
        return label
    if label != 'unclear' and confidence != 'low':
        return label
    if self_report == 'slipped' and 'too_fast' in flags:
        return label
    if self_report == 'ran_out_of_time' and not ('last_minute' in flags or timed_out):
        return label
    return SELF_REPORT_LABEL[self_report]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_diagnosis_rules -v 2`
Expected: all PASS.

If `test_near_threshold_on_default_usual_lowers_confidence` fails, check the arithmetic first. 180 / 70 = 2.571 and the too_long cut is 2.5, so |2.571 − 2.5| = 0.071 ≤ 0.5. It should be low; fix the code, not the test.

- [ ] **Step 6: Commit**

```bash
git add backend/intelligence/diagnosis_config.py backend/intelligence/services/diagnosis.py backend/intelligence/tests/test_diagnosis_rules.py
git commit -m "feat(intelligence): pure response-diagnosis rules and self-report reconciliation

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Fact assembly + persistence (`diagnose_attempt`) and ItemStats median

**Files:**
- Create: `backend/intelligence/services/diagnose.py`
- Modify: `backend/intelligence/services/events.py` (extract `item_score_fraction`)
- Modify: `backend/intelligence/services/itemstats.py` (median active time)
- Test: append to `backend/intelligence/tests/test_diagnose.py`

**Interfaces:**
- Consumes: `reduce_sessions`, `window_start_s`, `KeyTimeline` (Task 3); `classify`, `reconcile`, facts dataclasses (Task 5); models (Task 2); `state.observations_for`, `state.compute_state_fields` (existing).
- Produces:
  - `diagnose.diagnose_attempt(kind: str, attempt_id) -> int` (rows written; 0 when the attempt is missing or unfinished)
  - `events.item_score_fraction(item_answer) -> float`

- [ ] **Step 1: Write the failing integration tests**

Add to the import block at the **top** of `backend/intelligence/tests/test_diagnose.py`:

```python
from intelligence.models import ItemStats
from intelligence.services import diagnose, itemstats
from intelligence.services.events import record_attempt_events
```

Then append:

```python
class DiagnoseAttemptTests(DiagnosisTestCase):
    def build(self):
        """A finished 60-minute rich mock, 20 minutes in, four items:
        a 3-second wrong MCQ, an untouched MCQ, a ×10 numerical slip and an
        MCQ looked at for 40s and left blank."""
        self.guessed = self.make_item()
        self.untouched = self.make_item()
        self.slip = self.make_item(item_type='numerical', numerical=9.81)
        self.skipped = self.make_item()
        attempt = self.make_attempt(minutes_ago=30)
        self.answer(attempt, self.guessed, selected=[1])
        self.answer(attempt, self.slip, numerical=98.1)
        g, s, k = f'item:{self.guessed.id}', f'item:{self.slip.id}', f'item:{self.skipped.id}'
        self.make_timeline(attempt, [
            [0, 'e', g], [3000, 'a', g, {'sel': [1]}], [3000, 'l', g],
            [3000, 'e', s], [50000, 'a', s, {'num': '98.1'}], [60000, 'l', s],
            [60000, 'e', k], [100000, 'l', k],
        ])
        self.finish(attempt, after_minutes=20)
        record_attempt_events(attempt)
        return attempt

    def labels(self, attempt):
        return {
            row.mock_item_id: row
            for row in ResponseDiagnosis.objects.filter(attempt_id=attempt.id)
        }

    def test_every_item_gets_one_row_with_the_right_label(self):
        attempt = self.build()
        written = diagnose.diagnose_attempt('mock', str(attempt.id))
        self.assertEqual(written, 4)
        rows = self.labels(attempt)
        self.assertEqual(rows[self.guessed.id].label, 'guess')
        self.assertEqual(rows[self.untouched.id].label, 'not_seen')
        self.assertEqual(rows[self.slip.id].label, 'careless_slip')
        self.assertEqual(rows[self.skipped.id].label, 'skipped')
        row = rows[self.guessed.id]
        self.assertTrue(row.has_timeline)
        self.assertTrue(row.answered)
        self.assertEqual(row.final_label, 'guess')
        self.assertEqual(row.classifier_version, CLASSIFIER_VERSION)
        self.assertEqual(row.tenant, self.tenant)

    def test_is_idempotent_and_finalizes_the_timeline(self):
        attempt = self.build()
        diagnose.diagnose_attempt('mock', str(attempt.id))
        diagnose.diagnose_attempt('mock', str(attempt.id))
        self.assertEqual(ResponseDiagnosis.objects.filter(attempt_id=attempt.id).count(), 4)
        self.assertIsNotNone(AttemptTimeline.objects.get(attempt_id=attempt.id).finalized_at)

    def test_unfinished_attempt_is_not_diagnosed(self):
        attempt = self.make_attempt()
        self.assertEqual(diagnose.diagnose_attempt('mock', str(attempt.id)), 0)

    def test_no_timeline_degrades_without_inventing_time(self):
        item = self.make_item(item_type='numerical', numerical=9.81)
        attempt = self.make_attempt()
        self.answer(attempt, item, numerical=-9.81)
        self.finish(attempt)
        diagnose.diagnose_attempt('mock', str(attempt.id))
        row = ResponseDiagnosis.objects.get(attempt_id=attempt.id, mock_item=item)
        self.assertEqual(row.label, 'careless_slip')     # sign flip needs no timeline
        self.assertFalse(row.has_timeline)

    def test_self_report_is_kept_across_recompute(self):
        attempt = self.build()
        ResponseSelfReport.objects.create(
            tenant=self.tenant, student=self.student, attempt_kind='mock',
            attempt_id=attempt.id, mock_item=self.guessed, choice='guessed',
        )
        diagnose.diagnose_attempt('mock', str(attempt.id))
        row = ResponseDiagnosis.objects.get(attempt_id=attempt.id, mock_item=self.guessed)
        self.assertEqual(row.self_report, 'guessed')

    def test_right_to_wrong_from_the_answer_path(self):
        item = self.make_item()
        attempt = self.make_attempt(minutes_ago=30)
        self.answer(attempt, item, selected=[2])
        key = f'item:{item.id}'
        self.make_timeline(attempt, [
            [0, 'e', key], [30000, 'a', key, {'sel': [0]}],
            [60000, 'a', key, {'sel': [2]}], [70000, 'l', key],
        ])
        self.finish(attempt)
        diagnose.diagnose_attempt('mock', str(attempt.id))
        row = ResponseDiagnosis.objects.get(attempt_id=attempt.id, mock_item=item)
        self.assertEqual(row.label, 'second_guess')

    def test_item_stats_learn_the_median_active_time(self):
        attempt = self.build()
        diagnose.diagnose_attempt('mock', str(attempt.id))
        stats = itemstats.recompute_for_item(self.slip)
        self.assertEqual(stats.active_time_n, 1)
        self.assertAlmostEqual(stats.median_active_seconds, 57.0)
        # the 3-second guess is excluded from the usual-time sample
        stats = itemstats.recompute_for_item(self.guessed)
        self.assertEqual(stats.active_time_n, 0)
        self.assertIsNone(ItemStats.objects.get(mock_item=self.guessed).median_active_seconds)
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_diagnose.DiagnoseAttemptTests -v 2`
Expected: ERROR — `ImportError: cannot import name 'diagnose'`.

- [ ] **Step 3: Extract `item_score_fraction` in events.py**

In `backend/intelligence/services/events.py`, add above `_item_event_fields`:

```python
def item_score_fraction(item_answer):
    """Mastery signal in [0, 1] for an inline answer (partial credit kept;
    an ungraded subjective answer carries no signal yet)."""
    item = item_answer.item
    max_marks = item_answer.max_marks or item.marks
    if item_answer.needs_manual_grading:
        return 0.0
    if max_marks and float(max_marks) > 0:
        return _clamp01(float(item_answer.marks_obtained) / float(max_marks))
    return 1.0 if item_answer.is_correct else 0.0
```

And in `_item_event_fields`, replace the `if item_answer.needs_manual_grading: … else: score = …` block (the three branches computing `score`) with:

```python
    score = item_score_fraction(item_answer)
```

Keep `max_marks = item_answer.max_marks or item.marks` in `_item_event_fields`, since it is still used in the returned dict. Run `venv/Scripts/python.exe manage.py test intelligence.tests.test_foundation intelligence.tests.test_state -v 1` and expect everything to pass (a pure refactor).

- [ ] **Step 4: Implement `diagnose.py`**

Create `backend/intelligence/services/diagnose.py`:

```python
"""Gather classifier facts for every item of a finished attempt and persist
ResponseDiagnosis rows. The judgment itself lives in ``services.diagnosis``
(pure); this module only collects facts — grading, timeline, prior mastery,
item statistics — and writes results. Idempotent: a rerun overwrites.
"""
import logging
from dataclasses import dataclass

from django.utils import timezone

from intelligence.diagnosis_config import THRESHOLDS
from intelligence.models import (
    AttemptTimeline, ConceptLink, ItemStats, LearningEvent, ResponseDiagnosis,
    ResponseSelfReport,
)
from intelligence.services import diagnosis as rules
from intelligence.services.timeline import KeyTimeline, reduce_sessions, window_start_s
from intelligence.versions import CLASSIFIER_VERSION

logger = logging.getLogger(__name__)


@dataclass
class _Ref:
    """One item in the attempt plus the student's final answer facts."""
    arm: str                  # 'q' → quiz.Question, 'm' → quiz.MockTestItem
    item: object
    answered: bool
    score_fraction: float
    is_correct: object        # bool | None
    selected: list
    numeric: object           # float | None
    pending: bool = False

    @property
    def key(self):
        return f"{'bank' if self.arm == 'q' else 'item'}:{self.item.id}"

    @property
    def item_type(self):
        return self.item.question_type if self.arm == 'q' else self.item.item_type


@dataclass
class _Loaded:
    student: object
    refs: list
    anchor: object            # datetime the timeline offsets are relative to
    cutoff: object            # prior-mastery cutoff (attempt start)
    ended_at: object
    duration_s: float
    timed_out: bool
    finished: bool


def _f(value):
    return float(value) if value is not None else None


def _bank_ref(question, answer):
    if answer is None:
        return _Ref('q', question, False, 0.0, None, [], None)
    raw = (answer.selected_option or '').strip()
    answered = bool(raw or (answer.answer_text or '').strip()
                    or answer.numerical_answer is not None)
    return _Ref(
        'q', question, answered, 1.0 if answer.is_correct else 0.0,
        answer.is_correct if answered else None,
        [int(raw)] if raw.isdigit() else [], _f(answer.numerical_answer),
    )


def _item_ref(item, answer):
    from intelligence.services.events import item_score_fraction

    if answer is None:
        return _Ref('m', item, False, 0.0, None, [], None)
    answered = bool(answer.selected_options or answer.numerical_answer is not None
                    or (answer.answer_text or '').strip() or (answer.code or '').strip())
    pending = bool(answer.needs_manual_grading)
    return _Ref(
        'm', item, answered, item_score_fraction(answer),
        None if (pending or not answered) else answer.is_correct,
        [i for i in (answer.selected_options or []) if isinstance(i, int)],
        _f(answer.numerical_answer), pending,
    )


def _load(kind, attempt_id):
    from quiz.models import MockTestAttempt, MockTestItem, MockTestQuestion, QuizAttempt

    from intelligence.models import PracticeSet

    if kind == 'quiz':
        attempt = QuizAttempt.objects.filter(id=attempt_id).select_related(
            'quiz', 'student__user').first()
        if attempt is None:
            return None
        answers = {a.question_id: a for a in attempt.answers.all()}
        refs = [_bank_ref(q, answers.get(q.id))
                for q in attempt.quiz.questions.prefetch_related('options')]
        return _Loaded(attempt.student, refs, attempt.started_at, attempt.started_at,
                       attempt.completed_at, float((attempt.quiz.duration_minutes or 0) * 60),
                       attempt.status == 'timed_out', attempt.status != 'in_progress')

    if kind == 'mock':
        attempt = MockTestAttempt.objects.filter(id=attempt_id).select_related(
            'mock_test', 'student__user').first()
        if attempt is None:
            return None
        answers = {a.question_id: a for a in attempt.answers.all()}
        item_answers = {a.item_id: a for a in attempt.item_answers.all()}
        refs = [
            _bank_ref(mtq.question, answers.get(mtq.question_id))
            for mtq in MockTestQuestion.objects.filter(mock_test=attempt.mock_test)
            .select_related('question').prefetch_related('question__options')
        ]
        refs += [_item_ref(item, item_answers.get(item.id))
                 for item in MockTestItem.objects.filter(mock_test=attempt.mock_test)]
        return _Loaded(attempt.student, refs, attempt.started_at, attempt.started_at,
                       attempt.completed_at,
                       float((attempt.mock_test.duration_minutes or 0) * 60),
                       attempt.status == 'timed_out', attempt.status != 'in_progress')

    if kind == 'practice':
        practice_set = PracticeSet.objects.filter(id=attempt_id).select_related(
            'student__user').first()
        if practice_set is None:
            return None
        refs = []
        for set_item in practice_set.items.select_related('question').prefetch_related(
                'question__options'):
            answered = set_item.answered_at is not None
            refs.append(_Ref(
                'q', set_item.question, answered, 1.0 if set_item.is_correct else 0.0,
                set_item.is_correct if answered else None,
                [i for i in (set_item.selected_options or []) if isinstance(i, int)],
                _f(set_item.numerical_answer),
            ))
        return _Loaded(practice_set.student, refs, practice_set.created_at,
                       practice_set.started_at or practice_set.created_at,
                       practice_set.completed_at, 0.0, False,
                       practice_set.status == 'completed')
    return None


def _correct_indices(ref):
    item = ref.item
    if ref.arm == 'm':
        return {i for i, option in enumerate(item.options or [])
                if isinstance(option, dict) and option.get('is_correct')}
    if item.question_type in ('mcq', 'true_false'):
        raw = (item.correct_answer or '').strip()
        return {int(raw)} if raw.isdigit() else set()
    return {i for i, option in enumerate(item.options.all()) if option.is_correct}


def _digest_correct(ref, digest):
    """Grade one intermediate answer digest; None when it can't be graded."""
    if not isinstance(digest, dict):
        return None
    if isinstance(digest.get('sel'), list):
        correct = _correct_indices(ref)
        picks = {i for i in digest['sel'] if isinstance(i, int)}
        return bool(correct) and picks == correct
    if 'num' in digest:
        target = _f(getattr(ref.item, 'numerical_answer', None))
        try:
            value = float(digest['num'])
        except (TypeError, ValueError):
            return None
        if target is None:
            return None
        return abs(value - target) <= float(ref.item.numerical_tolerance or 0)
    return None


def _primary_concept(ref):
    arm = 'question' if ref.arm == 'q' else 'mock_item'
    link = (ConceptLink.objects.filter(**{arm: ref.item}).select_related('concept')
            .order_by('-is_primary', '-weight').first())
    return link.concept if link else None


def _prior_mastery(student, concept, cutoff, cache):
    """(mastery, confidence) from evidence strictly before the attempt."""
    if concept is None:
        return None, None
    if concept.id not in cache:
        from intelligence.services.state import compute_state_fields, observations_for

        prior = [o for o in observations_for(student, concept) if o.occurred_at < cutoff]
        fields = compute_state_fields(prior, now=cutoff)
        cache[concept.id] = (fields['mastery'], fields['confidence']) if fields else (None, None)
    return cache[concept.id]


def _digest_picks(digest):
    digest = digest or {}
    if isinstance(digest.get('selected'), list):
        return {i for i in digest['selected'] if isinstance(i, int)}
    raw = digest.get('selected_option')
    if isinstance(raw, str) and raw.strip().isdigit():
        return {int(raw.strip())}
    return set()


def _misconception_pick(student, ref, cutoff):
    """Picked this same wrong option on this same item before this attempt."""
    if ref.score_fraction >= 0.5 or not ref.selected:
        return False
    arm = 'question_id' if ref.arm == 'q' else 'mock_item_id'
    earlier = LearningEvent.objects.filter(
        student=student, occurred_at__lt=cutoff, score_fraction__lt=0.5,
        **{arm: ref.item.id},
    ).values_list('response_digest', flat=True)
    picks = set(ref.selected)
    return any(_digest_picks(digest) & picks for digest in earlier)


def _usual_from_stats(ref):
    arm = 'question' if ref.arm == 'q' else 'mock_item'
    row = ItemStats.objects.filter(**{arm: ref.item}).values_list(
        'median_active_seconds', 'active_time_n').first()
    if row and row[0] and row[1] >= THRESHOLDS['stats_min_n']:
        return row[0]
    return None


def _timing_for(ref, line, has_sessions, truncated):
    """TimingFacts for one item, or None when its timeline can't be trusted."""
    if not has_sessions:
        return None
    line = line or KeyTimeline()
    if line.visits == 0 and (ref.answered or truncated):
        # Answered but never seen on screen = lost events, not a 0s guess.
        return None
    graded = [_digest_correct(ref, digest) for _at, digest in line.answers if digest is not None]
    return rules.TimingFacts(
        active_s=line.active_s, visits=line.visits,
        first_answer_s=line.first_answer_active_s,
        final_answer_at_s=line.final_answer_at_s,
        first_enter_at_s=line.first_enter_at_s, hidden_s=line.hidden_s,
        answer_correctness=[c for c in graded if c is not None],
    )


def diagnose_attempt(kind, attempt_id):
    """(Re)diagnose every item of a finished attempt. Returns rows written."""
    loaded = _load(kind, attempt_id)
    if loaded is None or not loaded.finished:
        return 0
    tenant = loaded.student.user.tenant

    timeline = AttemptTimeline.objects.filter(attempt_kind=kind, attempt_id=attempt_id).first()
    sessions = (timeline.sessions or {}) if timeline else {}
    clock = timeline.clock if timeline else None
    keys = {ref.key for ref in loaded.refs}
    lines = reduce_sessions(sessions, clock=clock, known_keys=keys) if sessions else {}
    truncated = any(s.get('truncated') for s in sessions.values())
    offset_s = window_start_s(sessions, clock) if sessions else 0.0

    elapsed_s = None
    if loaded.ended_at:
        elapsed_s = (loaded.ended_at - loaded.anchor).total_seconds() - offset_s
    window = rules.WindowFacts(
        duration_s=loaded.duration_s if (loaded.duration_s and clock != 'none') else None,
        elapsed_s=elapsed_s, timed_out=loaded.timed_out,
    )

    reports = {
        (r.question_id, r.mock_item_id): r.choice
        for r in ResponseSelfReport.objects.filter(attempt_kind=kind, attempt_id=attempt_id)
    }
    mastery_cache = {}
    now = timezone.now()
    written = 0
    for ref in loaded.refs:
        mastery, confidence = _prior_mastery(
            loaded.student, _primary_concept(ref), loaded.cutoff, mastery_cache)
        facts = rules.ItemFacts(
            item_type=ref.item_type,
            difficulty=getattr(ref.item, 'difficulty', '') or 'medium',
            usual_s=_usual_from_stats(ref),
            answered=ref.answered, score_fraction=ref.score_fraction,
            numeric_value=ref.numeric,
            numeric_correct=_f(getattr(ref.item, 'numerical_answer', None)),
            numeric_tolerance=float(getattr(ref.item, 'numerical_tolerance', 0) or 0),
            misconception_pick=_misconception_pick(loaded.student, ref, loaded.cutoff),
            prior_mastery=mastery, prior_confidence=confidence,
            pending_grade=ref.pending,
        )
        timing = _timing_for(ref, lines.get(ref.key), bool(sessions), truncated)
        result = rules.classify(facts, timing, window)

        question_id = ref.item.id if ref.arm == 'q' else None
        mock_item_id = ref.item.id if ref.arm == 'm' else None
        self_report = reports.get((question_id, mock_item_id), '')
        lookup = {'attempt_kind': kind, 'attempt_id': attempt_id}
        lookup['question_id' if ref.arm == 'q' else 'mock_item_id'] = ref.item.id
        ResponseDiagnosis.objects.update_or_create(**lookup, defaults={
            'tenant': tenant,
            'student': loaded.student,
            'answered': ref.answered,
            'is_correct': ref.is_correct,
            'score_fraction': ref.score_fraction,
            'metrics': {**result.metrics, 'timed_out': loaded.timed_out},
            'flags': result.flags,
            'label': result.label,
            'confidence': result.confidence,
            'evidence': result.evidence,
            'self_report': self_report,
            'final_label': rules.reconcile(result.label, result.confidence, result.flags,
                                           self_report, loaded.timed_out),
            'has_timeline': timing is not None,
            'classifier_version': CLASSIFIER_VERSION,
            'computed_at': now,
        })
        written += 1

    if timeline is not None and timeline.finalized_at is None:
        timeline.finalized_at = now
        timeline.save(update_fields=['finalized_at', 'updated_at'])
    return written
```

- [ ] **Step 5: Median active time in `itemstats.py`**

In `backend/intelligence/services/itemstats.py`, add `import statistics` with the other imports, and add `ResponseDiagnosis` to the `intelligence.models` import. In `recompute_for_item`, after the `times = [...]` line, add:

```python
    active_times = [
        float(m['active_s'])
        for m in ResponseDiagnosis.objects.filter(
            **{f'{arm}_id': item.id}, has_timeline=True, answered=True,
        ).exclude(label__in=('guess', 'correct_lucky')).values_list('metrics', flat=True)
        if isinstance(m, dict) and m.get('active_s')
    ]
```

and add to the `defaults` dict of `ItemStats.objects.update_or_create`:

```python
            'median_active_seconds': (
                round(statistics.median(active_times), 2) if active_times else None
            ),
            'active_time_n': len(active_times),
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_diagnose -v 2`
Expected: all PASS. Expected labels in `build()`:
- **guess:** 3s against the default 70s; the too-fast cut is max(5, 17.5) = 17.5s.
- **careless_slip:** 98.1 is 9.81 × 10.
- **skipped:** 40s of active time, and the attempt ended 20 minutes into 60, so not late.
- **not_seen:** zero visits.

- [ ] **Step 7: Commit**

```bash
git add backend/intelligence/services/diagnose.py backend/intelligence/services/events.py backend/intelligence/services/itemstats.py backend/intelligence/tests/test_diagnose.py
git commit -m "feat(intelligence): diagnose every item of a finished attempt

Gathers grading, timeline, prior mastery and item stats per item, persists
ResponseDiagnosis (answered and unanswered), finalizes the timeline, and
teaches ItemStats the median on-screen time.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Mastery weights, task wiring, practice hook, nightly catch-up, recompute command

**Files:**
- Modify: `backend/intelligence/services/state.py`
- Modify: `backend/intelligence/tasks.py`
- Modify: `backend/intelligence/api.py`
- Modify: `backend/intelligence/services/practice.py`
- Create: `backend/intelligence/management/commands/recompute_diagnoses.py`
- Test: append to `backend/intelligence/tests/test_diagnose.py`

**Interfaces:**
- Consumes: `diagnose.diagnose_attempt` (Task 6); `LABEL_WEIGHTS` (Task 5).
- Produces:
  - Celery task `intelligence.diagnose_and_update_state(kind, attempt_id)`
  - command `recompute_diagnoses [--tenant ID] [--since YYYY-MM-DD]`

- [ ] **Step 1: Write the failing tests**

Add to the import block at the **top** of `backend/intelligence/tests/test_diagnose.py`:

```python
from django.core.management import call_command

from intelligence.models import LearnerConceptState
from intelligence.services.state import recompute_state
```

Then append:

```python
class DiagnosisWeightTests(DiagnosisTestCase):
    def wrong_attempt(self):
        item = self.make_item()
        attempt = self.make_attempt()
        self.answer(attempt, item, selected=[1])
        self.finish(attempt)
        record_attempt_events(attempt)
        return attempt, item

    def test_guess_weighs_less_than_an_honest_miss(self):
        attempt, item = self.wrong_attempt()
        recompute_state(self.student, self.concept)
        honest = LearnerConceptState.objects.get(student=self.student, concept=self.concept)
        # (0·1 + 3·0.5) / (1 + 3)
        self.assertAlmostEqual(honest.mastery, 0.375, places=3)

        ResponseDiagnosis.objects.create(
            tenant=self.tenant, student=self.student, attempt_kind='mock',
            attempt_id=attempt.id, mock_item=item, answered=True, is_correct=False,
            label='guess', final_label='guess', confidence='high',
        )
        recompute_state(self.student, self.concept)
        guessed = LearnerConceptState.objects.get(student=self.student, concept=self.concept)
        # (0·0.2 + 3·0.5) / (0.2 + 3)
        self.assertAlmostEqual(guessed.mastery, 0.4688, places=3)
        self.assertEqual(guessed.model_version, '2')

    def test_api_hook_diagnoses_then_updates_state(self):
        from intelligence import api

        attempt, item = self.wrong_attempt()
        api.record_attempt_events(attempt)   # Celery is eager in tests
        self.assertTrue(ResponseDiagnosis.objects.filter(attempt_id=attempt.id).exists())
        self.assertTrue(LearnerConceptState.objects.filter(
            student=self.student, concept=self.concept).exists())

    def test_recompute_command(self):
        attempt, _item = self.wrong_attempt()
        call_command('recompute_diagnoses', verbosity=0)
        self.assertEqual(ResponseDiagnosis.objects.filter(attempt_id=attempt.id).count(), 1)
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_diagnose.DiagnosisWeightTests -v 2`
Expected: FAIL. `test_guess_weighs_less…` gets mastery 0.375 for the guess case, the API test finds no diagnosis, and the command test errors with "Unknown command".

- [ ] **Step 3: Weight observations by diagnosis in `state.py`**

In `backend/intelligence/services/state.py`, add below `_cognitive_multi`:

```python
def _diagnosis_key(event):
    return (
        event.attempt_kind, str(event.attempt_id),
        str(event.question_id) if event.question_id else None,
        str(event.mock_item_id) if event.mock_item_id else None,
    )


def _diagnosis_weights(events):
    """(attempt, item) → evidence multiplier from its ResponseDiagnosis.

    Guesses and slips stop counting as full evidence of not knowing; an
    event without a diagnosis keeps weight 1.0 (v1 behaviour).
    """
    from intelligence.diagnosis_config import LABEL_WEIGHTS
    from intelligence.models import ResponseDiagnosis

    attempt_ids = {e.attempt_id for e in events if e.attempt_id}
    if not attempt_ids:
        return {}
    rows = ResponseDiagnosis.objects.filter(attempt_id__in=attempt_ids).values_list(
        'attempt_kind', 'attempt_id', 'question_id', 'mock_item_id', 'final_label')
    return {
        (kind, str(attempt_id), str(q) if q else None, str(m) if m else None):
            LABEL_WEIGHTS.get(label, 1.0)
        for kind, attempt_id, q, m, label in rows
    }
```

In `observations_for`, right after the `latest` dict is filled (before `observations = []`), add:

```python
    diagnosis_weights = _diagnosis_weights(latest.values())
```

and change the `link_weight=` argument of `_Observation(...)` to:

```python
            link_weight=(weights.get(item_key, 1.0) * source_weight
                         * diagnosis_weights.get(_diagnosis_key(event), 1.0)),
```

Update the module docstring's mastery bullet to mention it:

```
- mastery      recency-decayed weighted mean with a Laplace prior, so one
               lucky answer can't read as mastery and old evidence fades;
               evidence is down-weighted by its response diagnosis (guesses,
               slips, time pressure — diagnosis_config.LABEL_WEIGHTS);
```

- [ ] **Step 4: Add the task, rewire the API, extend the nightly sweep**

In `backend/intelligence/tasks.py`, add below `update_learner_state_for_attempt`, which stays registered for messages already in flight:

```python
@shared_task(name='intelligence.diagnose_and_update_state', max_retries=0)
def diagnose_and_update_state(kind, attempt_id):
    """Diagnose an attempt's responses, then recompute the states it touched.

    Ordered on purpose: state reads diagnosis weights. A diagnosis failure
    never blocks the state update (weights fall back to 1.0) and the nightly
    sweep retries it.
    """
    from .services import diagnose, state

    try:
        diagnose.diagnose_attempt(kind, attempt_id)
    except Exception:  # noqa: BLE001
        logger.exception('intelligence.diagnose failed for %s %s', kind, attempt_id)
    if kind not in ('quiz', 'mock'):
        return 0
    try:
        return state.update_for_attempt(kind, attempt_id)
    except Exception:  # noqa: BLE001 — the nightly refresh catches up
        logger.exception('intelligence.update_learner_state failed for %s %s', kind, attempt_id)
        return 0
```

In `refresh_learner_state`, replace the catch-up section (from `caught_up = 0` up to the end of its `for kind, attempt_id in pairs:` loop) with:

```python
    caught_up = 0
    recent = timezone.now() - timedelta(hours=48)
    from .models import LearningEvent, ResponseDiagnosis
    from .services import diagnose
    from .versions import CLASSIFIER_VERSION

    pairs = list(
        LearningEvent.objects.filter(created_at__gte=recent)
        .values_list('attempt_kind', 'attempt_id').distinct()
    )
    for kind, attempt_id in pairs:
        if not attempt_id:
            continue
        current = ResponseDiagnosis.objects.filter(
            attempt_kind=kind, attempt_id=attempt_id, classifier_version=CLASSIFIER_VERSION,
        ).exists()
        if not current:
            try:
                diagnose.diagnose_attempt(kind, attempt_id)
            except Exception:  # noqa: BLE001
                logger.exception('nightly diagnose failed for %s %s', kind, attempt_id)
        if kind in ('quiz', 'mock'):
            caught_up += state.update_for_attempt(kind, attempt_id)
```

In `backend/intelligence/api.py`, `_enqueue_state_update`: replace the import and the call with:

```python
        from intelligence.tasks import diagnose_and_update_state
        kind = 'quiz' if isinstance(attempt, QuizAttempt) else 'mock'
        diagnose_and_update_state.delay(kind, str(attempt.pk))
```

This one change covers first grading and manual regrade alike, because `record_regrade_event` uses the same helper.

- [ ] **Step 5: Diagnose practice sets before their synchronous state refresh**

In `backend/intelligence/services/practice.py`, `submit_set`, immediately before the line `from intelligence.models import ConceptLink` (the start of the "Refresh every concept…" block), insert:

```python
    # Diagnose first so the synchronous state refresh below sees the labels.
    try:
        from intelligence.services import diagnose
        diagnose.diagnose_attempt('practice', practice_set.id)
    except Exception:  # noqa: BLE001 — never fail the student's submit
        logger.exception('practice: diagnosis failed for set %s', practice_set.id)
```

`practice.py` already defines a module-level `logger`. `submit_set` saves `status='completed'` and calls `_emit_events` before this point, so `diagnose_attempt` sees a finished set.

- [ ] **Step 6: Add the management command**

Create `backend/intelligence/management/commands/recompute_diagnoses.py`:

```python
"""Re-run response diagnosis over finished attempts (after a classifier or
threshold change — bump CLASSIFIER_VERSION first). Idempotent."""
from datetime import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone

from intelligence.models import LearningEvent
from intelligence.services import diagnose


class Command(BaseCommand):
    help = 'Recompute ResponseDiagnosis rows for attempts with learning events.'

    def add_arguments(self, parser):
        parser.add_argument('--tenant', help='Only this tenant id.')
        parser.add_argument('--since', help='Only attempts with events on/after YYYY-MM-DD.')

    def handle(self, *args, **options):
        events = LearningEvent.objects.exclude(attempt_id=None)
        if options.get('tenant'):
            events = events.filter(tenant_id=options['tenant'])
        if options.get('since'):
            since = timezone.make_aware(datetime.strptime(options['since'], '%Y-%m-%d'))
            events = events.filter(occurred_at__gte=since)
        pairs = events.values_list('attempt_kind', 'attempt_id').distinct()
        attempts = rows = 0
        for kind, attempt_id in pairs.iterator():
            rows += diagnose.diagnose_attempt(kind, attempt_id)
            attempts += 1
        self.stdout.write(self.style.SUCCESS(
            f'Diagnosed {attempts} attempt(s), {rows} response row(s).'))
```

- [ ] **Step 7: Run tests to verify they pass, plus the existing suites**

Run: `venv/Scripts/python.exe manage.py test intelligence -v 1`
Expected: all PASS, including the existing `test_state`, `test_practice` and `test_foundation`.

`test_state.test_update_for_attempt_builds_states_for_touched_concepts` must still see mastery 0.625. It has no diagnosis row, so its weight stays 1.0.

- [ ] **Step 8: Commit**

```bash
git add backend/intelligence
git commit -m "feat(intelligence): weight mastery evidence by response diagnosis

Attempts now diagnose before the learner-state update (one task), practice
sets diagnose before their synchronous refresh, the nightly sweep catches up
missing/outdated diagnoses, and recompute_diagnoses reruns history.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Self-report API + calibration report

**Files:**
- Modify: `backend/intelligence/views.py` (append `DiagnosisFeaturePermission`, `SelfReportView`)
- Modify: `backend/intelligence/urls.py`
- Modify: `backend/intelligence/admin_views.py` (append `DiagnosisCalibrationView`)
- Modify: `backend/intelligence/admin_urls.py`
- Test: `backend/intelligence/tests/test_self_report.py`

**Interfaces:**
- Consumes: `reconcile` (Task 5); models (Task 2); `SELF_REPORT_LABEL`.
- Produces:
  - `GET /api/v1/intelligence/self-report/?attempt_kind=&attempt_id=` → `{reports: {"bank:<id>"|"item:<id>": choice}, not_seen: [keys]}`
  - `POST /api/v1/intelligence/self-report/` with `{attempt_kind, attempt_id, item_kind: 'bank'|'item', item_id, choice}` → `{saved: true, choice}`
  - `GET /api/v1/tenant-admin/intelligence/diagnosis/calibration/?days=30` → `{days, total, with_timeline, stats_usual, labels, confusion, agreement}`

- [ ] **Step 1: Write the failing tests**

Create `backend/intelligence/tests/test_self_report.py`:

```python
"""Self-report ground truth + the admin calibration report."""
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from intelligence.models import ResponseDiagnosis, ResponseSelfReport
from intelligence.tests.diagnosis_fixtures import DiagnosisTestCase
from users.models import User

URL = '/api/v1/intelligence/self-report/'
CALIBRATION = '/api/v1/tenant-admin/intelligence/diagnosis/calibration/'


class SelfReportTests(DiagnosisTestCase):
    def setUp(self):
        self.item = self.make_item()
        self.attempt = self.finish(self.make_attempt())
        self.diag = ResponseDiagnosis.objects.create(
            tenant=self.tenant, student=self.student, attempt_kind='mock',
            attempt_id=self.attempt.id, mock_item=self.item, answered=True,
            is_correct=False, label='unclear', final_label='unclear', confidence='low',
            flags=[], metrics={'timed_out': False},
        )

    def client_for(self, user):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(user).access_token}')
        return client

    def post(self, choice='slipped', user=None, **overrides):
        body = {'attempt_kind': 'mock', 'attempt_id': str(self.attempt.id),
                'item_kind': 'item', 'item_id': str(self.item.id), 'choice': choice}
        body.update(overrides)
        return self.client_for(user or self.user).post(
            URL, body, format='json', HTTP_X_TENANT_ID=str(self.tenant.id))

    def test_report_is_saved_and_reconciled(self):
        response = self.post('slipped')
        self.assertEqual(response.status_code, 200, response.content)
        self.diag.refresh_from_db()
        self.assertEqual(self.diag.self_report, 'slipped')
        self.assertEqual(self.diag.final_label, 'careless_slip')
        # changing your mind replaces the report
        self.post('didnt_know')
        self.assertEqual(ResponseSelfReport.objects.get().choice, 'didnt_know')

    def test_get_returns_reports_and_not_seen(self):
        self.post('guessed')
        unseen = self.make_item()
        ResponseDiagnosis.objects.create(
            tenant=self.tenant, student=self.student, attempt_kind='mock',
            attempt_id=self.attempt.id, mock_item=unseen, label='not_seen',
            final_label='not_seen', confidence='high',
        )
        response = self.client_for(self.user).get(
            URL, {'attempt_kind': 'mock', 'attempt_id': str(self.attempt.id)},
            HTTP_X_TENANT_ID=str(self.tenant.id))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['reports'], {f'item:{self.item.id}': 'guessed'})
        self.assertEqual(response.data['not_seen'], [f'item:{unseen.id}'])

    def test_correct_answers_take_no_report(self):
        self.diag.is_correct = True
        self.diag.save()
        self.assertEqual(self.post().status_code, 400)

    def test_validation(self):
        self.assertEqual(self.post('nope').status_code, 400)
        self.assertEqual(self.post(item_id=str(self.make_attempt().id)).status_code, 400)
        self.assertEqual(self.post(user=self.other_user).status_code, 404)

    def test_in_progress_attempt_is_404(self):
        live = self.make_attempt()
        self.assertEqual(self.post(attempt_id=str(live.id)).status_code, 404)

    def test_feature_gate(self):
        self.tenant.features = {}
        self.tenant.save()
        self.assertEqual(self.post().status_code, 403)


class CalibrationTests(DiagnosisTestCase):
    def test_confusion_and_agreement(self):
        admin = User.objects.create_user(
            email='diag-admin@example.com', password='pw-admin-1',
            tenant=self.tenant, role='admin',
        )
        attempt = self.finish(self.make_attempt())
        for label, report, timeline in (('guess', 'guessed', True), ('guess', 'slipped', True),
                                        ('concept_gap', '', False)):
            ResponseDiagnosis.objects.create(
                tenant=self.tenant, student=self.student, attempt_kind='mock',
                attempt_id=attempt.id, mock_item=self.make_item(), label=label,
                final_label=label, self_report=report, has_timeline=timeline,
                metrics={'usual_source': 'default'},
                computed_at=attempt.completed_at,
            )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(admin).access_token}')
        response = client.get(CALIBRATION, {'days': 30}, HTTP_X_TENANT_ID=str(self.tenant.id))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data['total'], 3)
        self.assertEqual(response.data['with_timeline'], 2)
        self.assertEqual(response.data['labels'], {'guess': 2, 'concept_gap': 1})
        self.assertEqual(response.data['confusion'], {'guess': {'guessed': 1, 'slipped': 1}})
        self.assertEqual(response.data['agreement'], {'guess': 0.5})

    def test_students_cannot_read_it(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(self.user).access_token}')
        response = client.get(CALIBRATION, HTTP_X_TENANT_ID=str(self.tenant.id))
        self.assertEqual(response.status_code, 403)
```

- [ ] **Step 2: Run to verify failure**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_self_report -v 2`
Expected: FAIL — 404s (routes missing).

- [ ] **Step 3: Implement the student view**

Append to `backend/intelligence/views.py`:

```python
class DiagnosisFeaturePermission(permissions.BasePermission):
    """The tenant must have opted into Answer Diagnosis."""

    message = 'Answer Diagnosis is not enabled for this academy.'

    def has_permission(self, request, view):
        tenant = getattr(request, 'tenant', None)
        return bool(tenant and tenant.get_features().get('response_diagnosis'))


def _item_key(question_id, mock_item_id):
    return f'bank:{question_id}' if question_id else f'item:{mock_item_id}'


def _owned_finished_attempt(kind, attempt_id, student):
    import uuid

    from quiz.models import MockTestAttempt, QuizAttempt

    model = {'quiz': QuizAttempt, 'mock': MockTestAttempt}.get(kind)
    if model is None or student is None:
        return None
    try:
        uuid.UUID(str(attempt_id))
    except ValueError:
        return None
    return model.objects.filter(id=attempt_id, student=student).exclude(
        status='in_progress').first()


def _attempt_item(kind, attempt, item_kind, item_id):
    """The Question / MockTestItem ``item_id`` names, only if it is in the attempt."""
    import uuid

    from quiz.models import MockTestItem, MockTestQuestion

    try:
        uuid.UUID(str(item_id))
    except ValueError:
        return None
    if item_kind == 'bank':
        if kind == 'quiz':
            return attempt.quiz.questions.filter(id=item_id).first()
        link = MockTestQuestion.objects.filter(
            mock_test=attempt.mock_test, question_id=item_id).select_related('question').first()
        return link.question if link else None
    if item_kind == 'item' and kind == 'mock':
        return MockTestItem.objects.filter(mock_test=attempt.mock_test, id=item_id).first()
    return None


class SelfReportView(APIView):
    """The student's own "what happened?" on wrong/unanswered review items."""

    permission_classes = [permissions.IsAuthenticated, DiagnosisFeaturePermission]

    def get(self, request):
        from .models import ResponseDiagnosis, ResponseSelfReport

        kind = request.query_params.get('attempt_kind')
        attempt = _owned_finished_attempt(
            kind, request.query_params.get('attempt_id'), _student_or_none(request))
        if attempt is None:
            return Response({'error': 'Attempt not found.'}, status=status.HTTP_404_NOT_FOUND)
        reports = {
            _item_key(q, m): choice
            for q, m, choice in ResponseSelfReport.objects.filter(
                attempt_kind=kind, attempt_id=attempt.id,
            ).values_list('question_id', 'mock_item_id', 'choice')
        }
        not_seen = [
            _item_key(q, m)
            for q, m in ResponseDiagnosis.objects.filter(
                attempt_kind=kind, attempt_id=attempt.id, final_label='not_seen',
            ).values_list('question_id', 'mock_item_id')
        ]
        return Response({'reports': reports, 'not_seen': not_seen})

    def post(self, request):
        from .models import ResponseDiagnosis, ResponseSelfReport
        from .services.diagnosis import reconcile

        data = request.data
        kind = data.get('attempt_kind')
        choice = data.get('choice')
        if choice not in dict(ResponseSelfReport.CHOICE_CHOICES):
            return Response({'error': 'Unknown choice.'}, status=status.HTTP_400_BAD_REQUEST)
        student = _student_or_none(request)
        attempt = _owned_finished_attempt(kind, data.get('attempt_id'), student)
        if attempt is None:
            return Response({'error': 'Attempt not found.'}, status=status.HTTP_404_NOT_FOUND)
        item = _attempt_item(kind, attempt, data.get('item_kind'), data.get('item_id'))
        if item is None:
            return Response({'error': 'Question not in this attempt.'},
                            status=status.HTTP_400_BAD_REQUEST)

        arm = {'question': item} if data.get('item_kind') == 'bank' else {'mock_item': item}
        diag = ResponseDiagnosis.objects.filter(
            attempt_kind=kind, attempt_id=attempt.id, **arm).first()
        if diag is not None and diag.is_correct:
            return Response({'error': 'Only wrong or unanswered questions take a self-report.'},
                            status=status.HTTP_400_BAD_REQUEST)

        ResponseSelfReport.objects.update_or_create(
            attempt_kind=kind, attempt_id=attempt.id, **arm,
            defaults={'student': student, 'tenant': student.user.tenant, 'choice': choice},
        )
        if diag is not None:
            # Cheap: reconcile only — the stored label, confidence and flags stand.
            diag.self_report = choice
            diag.final_label = reconcile(diag.label, diag.confidence, diag.flags, choice,
                                         bool((diag.metrics or {}).get('timed_out')))
            diag.save(update_fields=['self_report', 'final_label', 'updated_at'])
        return Response({'saved': True, 'choice': choice})
```

In `backend/intelligence/urls.py`, import `SelfReportView` alongside the others and add:

```python
    path('self-report/', SelfReportView.as_view(), name='intelligence-self-report'),
```

- [ ] **Step 4: Implement the calibration view**

In `backend/intelligence/admin_views.py`:
- add `from collections import Counter, defaultdict` and `from datetime import timedelta` to the imports;
- add `ResponseDiagnosis` to the `.models` import;
- append:

```python
class DiagnosisCalibrationView(APIView):
    """How well response-diagnosis labels match what students say happened.

    Label distribution, classifier-label × self-report confusion, per-label
    agreement, and how much of the data had a timeline / trusted usual time.
    """

    permission_classes = [permissions.IsAuthenticated, IsTenantAdminOrInstructor]

    def get(self, request):
        from .diagnosis_config import SELF_REPORT_LABEL

        try:
            days = max(1, min(365, int(request.query_params.get('days', 30))))
        except ValueError:
            days = 30
        since = timezone.now() - timedelta(days=days)
        rows = ResponseDiagnosis.objects.filter(
            tenant=request.tenant, computed_at__gte=since,
        ).values_list('label', 'self_report', 'has_timeline', 'metrics')

        labels = Counter()
        confusion = defaultdict(Counter)
        total = with_timeline = stats_usual = 0
        for label, report, has_timeline, metrics in rows.iterator():
            total += 1
            labels[label] += 1
            with_timeline += 1 if has_timeline else 0
            stats_usual += 1 if (metrics or {}).get('usual_source') == 'stats' else 0
            if report:
                confusion[label][report] += 1

        agreement = {
            label: round(
                sum(n for rep, n in reports.items() if SELF_REPORT_LABEL.get(rep) == label)
                / sum(reports.values()), 3)
            for label, reports in confusion.items()
        }
        return Response({
            'days': days, 'total': total, 'with_timeline': with_timeline,
            'stats_usual': stats_usual, 'labels': dict(labels),
            'confusion': {label: dict(reports) for label, reports in confusion.items()},
            'agreement': agreement,
        })
```

In `backend/intelligence/admin_urls.py`, add `DiagnosisCalibrationView` to the import and the route:

```python
    path('diagnosis/calibration/', DiagnosisCalibrationView.as_view(),
         name='intelligence-diagnosis-calibration'),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_self_report -v 2`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/intelligence
git commit -m "feat(intelligence): student self-report API and diagnosis calibration report

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Frontend capture — service, hook, and the four attempt screens

**Files:**
- Create: `frontend/exam-frontend/src/services/timelineService.js`
- Create: `frontend/exam-frontend/src/hooks/useResponseTimeline.js`
- Modify: `frontend/exam-frontend/src/pages/QuizAttempt.jsx`
- Modify: `frontend/exam-frontend/src/pages/MockTestAttempt.jsx`
- Modify: `frontend/exam-frontend/src/pages/RichMockAttempt.jsx`
- Modify: `frontend/exam-frontend/src/pages/PracticeSession.jsx`

**Interfaces:**
- Consumes: `POST /api/v1/intelligence/timeline/` (Task 4).
- Produces:
  - `timelineService.sync(payload)`, `timelineService.syncOnUnload(payload)`, `timelineService.getSelfReports(kind, attemptId)`, `timelineService.saveSelfReport(payload)`
  - `useResponseTimeline({ attemptKind, attemptId, parentId, currentKey, active })` → `{ recordAnswer(key, digest), clearAnswer(key), activeSeconds(key), flush() }`

No frontend test runner exists. Verify with lint, build and the manual run in Step 9.

- [ ] **Step 1: Create the service**

Create `frontend/exam-frontend/src/services/timelineService.js`:

```js
import api, { API_BASE_URL, TENANT_ID } from './api'

const TIMELINE_URL = '/intelligence/timeline/'

// fetch() with keepalive survives page hide/unload, which axios can't do —
// so it has to rebuild the auth + tenant headers the axios instance adds.
const authHeaders = () => {
  try {
    const raw = localStorage.getItem('auth-storage')
    const token = raw && JSON.parse(raw)?.state?.tokens?.access
    return token ? { Authorization: `Bearer ${token}` } : {}
  } catch {
    return {}
  }
}

export const timelineService = {
  // payload: { attempt_kind, attempt_id | parent_id, session_id, elapsed_ms, truncated, events }
  sync: (payload) => api.post(TIMELINE_URL, payload),

  syncOnUnload: (payload) => {
    try {
      fetch(`${API_BASE_URL}${TIMELINE_URL}`, {
        method: 'POST',
        keepalive: true,
        headers: {
          'Content-Type': 'application/json',
          ...(TENANT_ID ? { 'X-Tenant-ID': TENANT_ID } : {}),
          ...authHeaders(),
        },
        body: JSON.stringify(payload),
      }).catch(() => {})
    } catch {
      /* best effort */
    }
  },

  getSelfReports: async (attemptKind, attemptId) => {
    const response = await api.get('/intelligence/self-report/', {
      params: { attempt_kind: attemptKind, attempt_id: attemptId },
    })
    return response.data
  },

  // payload: { attempt_kind, attempt_id, item_kind: 'bank' | 'item', item_id, choice }
  saveSelfReport: async (payload) => {
    const response = await api.post('/intelligence/self-report/', payload)
    return response.data
  },
}
```

- [ ] **Step 2: Create the hook**

Create `frontend/exam-frontend/src/hooks/useResponseTimeline.js`:

```js
import { useCallback, useEffect, useRef } from 'react'
import { timelineService } from '../services/timelineService'

/**
 * Records a raw per-question interaction timeline for one attempt and syncs
 * it to the server. Raw events only — every interpretation (active time,
 * guesses, slips…) happens server-side in intelligence/services/timeline.py.
 *
 * Event tuples: [t_ms, code, key, value?] — e/l enter/leave a question,
 * h/s tab hidden/shown, a answer set (value = digest), c answer cleared.
 * Never throws and never blocks the attempt: sync failures retry next tick.
 */
const SYNC_MS = 30000
const MAX_EVENTS = 5000
const COALESCE_MS = 1500        // rapid re-answers (typing, toggling) collapse
const KEEPALIVE_LIMIT = 60000   // fetch keepalive bodies must stay small

const newSessionId = () =>
  (typeof crypto !== 'undefined' && crypto.randomUUID)
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`

export default function useResponseTimeline({ attemptKind, attemptId, parentId, currentKey, active }) {
  const enabled = Boolean(active && (attemptId || parentId))
  const targetRef = useRef({})
  targetRef.current = { attemptKind, attemptId, parentId, enabled }

  const sessionRef = useRef(null)     // { id, t0, events, truncated, dirty }
  const currentRef = useRef(null)     // key on screen
  const visibleSinceRef = useRef(null) // perf time the current visible stretch began
  const activeMsRef = useRef({})      // key → visible ms so far

  const now = () => performance.now()

  const session = () => {
    if (!sessionRef.current) {
      sessionRef.current = { id: newSessionId(), t0: now(), events: [], truncated: false, dirty: false }
    }
    return sessionRef.current
  }

  const push = useCallback((code, key = null, value) => {
    const s = session()
    const t = Math.round(now() - s.t0)
    const last = s.events[s.events.length - 1]
    if (code === 'a' && last && last[1] === 'a' && last[2] === key && t - last[0] < COALESCE_MS) {
      last[0] = t
      last[3] = value
      s.dirty = true
      return
    }
    if (s.events.length >= MAX_EVENTS && code !== 'a' && code !== 'c') {
      s.truncated = true
      return
    }
    s.events.push(value === undefined ? [t, code, key] : [t, code, key, value])
    s.dirty = true
  }, [])

  const pauseClock = () => {
    const key = currentRef.current
    if (key && visibleSinceRef.current != null) {
      activeMsRef.current[key] = (activeMsRef.current[key] || 0) + (now() - visibleSinceRef.current)
    }
    visibleSinceRef.current = null
  }

  const resumeClock = () => {
    if (currentRef.current && !document.hidden) visibleSinceRef.current = now()
  }

  const payload = () => {
    const s = sessionRef.current
    const { attemptKind: kind, attemptId: id, parentId: parent } = targetRef.current
    return {
      attempt_kind: kind,
      ...(id ? { attempt_id: id } : { parent_id: parent }),
      session_id: s.id,
      elapsed_ms: Math.round(now() - s.t0),
      truncated: s.truncated,
      events: s.events,
    }
  }

  const flush = useCallback(async () => {
    const s = sessionRef.current
    if (!targetRef.current.enabled || !s || !s.dirty) return
    s.dirty = false
    try {
      await timelineService.sync(payload())
    } catch {
      s.dirty = true
    }
  }, [])

  const flushOnHide = () => {
    const s = sessionRef.current
    if (!targetRef.current.enabled || !s || !s.dirty) return
    const body = payload()
    s.dirty = false
    if (JSON.stringify(body).length < KEEPALIVE_LIMIT) {
      timelineService.syncOnUnload(body)
    } else {
      timelineService.sync(body).catch(() => { s.dirty = true })
    }
  }

  // Enter/leave as the question on screen changes (or the hook switches off).
  useEffect(() => {
    const next = enabled ? currentKey || null : null
    if (next === currentRef.current) return
    if (currentRef.current) {
      pauseClock()
      push('l', currentRef.current)
    }
    currentRef.current = next
    if (next) {
      push('e', next)
      resumeClock()
    }
  }, [enabled, currentKey, push])

  // Tab visibility, periodic sync and unmount.
  useEffect(() => {
    if (!enabled) return undefined
    const onVisibility = () => {
      if (document.hidden) {
        pauseClock()
        push('h')
        flushOnHide()
      } else {
        push('s')
        resumeClock()
      }
    }
    document.addEventListener('visibilitychange', onVisibility)
    const timer = setInterval(() => { flush() }, SYNC_MS)
    return () => {
      document.removeEventListener('visibilitychange', onVisibility)
      clearInterval(timer)
      if (currentRef.current) {
        pauseClock()
        push('l', currentRef.current)
        currentRef.current = null
      }
      flushOnHide()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, push, flush])

  const recordAnswer = useCallback((key, digest) => {
    if (targetRef.current.enabled && key) push('a', key, digest)
  }, [push])

  const clearAnswer = useCallback((key) => {
    if (targetRef.current.enabled && key) push('c', key)
  }, [push])

  const activeSeconds = useCallback((key) => {
    let ms = activeMsRef.current[key] || 0
    if (key === currentRef.current && visibleSinceRef.current != null) ms += now() - visibleSinceRef.current
    return ms / 1000
  }, [])

  return { recordAnswer, clearAnswer, activeSeconds, flush }
}
```

- [ ] **Step 3: Wire `QuizAttempt.jsx`**

1. Add the import below the `quizService` import:
```js
import useResponseTimeline from '../hooks/useResponseTimeline'
```
2. Directly after the `const { data: quiz, isLoading } = useQuery({...})` block, add:
```js
  // Make sure an in-progress attempt exists for the timeline to attach to
  // (idempotent: returns the existing one when Quiz.jsx already started it).
  useEffect(() => {
    quizService.startQuiz(quizId).catch(() => {})
  }, [quizId])

  const currentQ = quiz?.questions?.[currentQuestion]
  const timeline = useResponseTimeline({
    attemptKind: 'quiz',
    parentId: quizId,
    currentKey: currentQ ? `bank:${currentQ.id}` : null,
    active: Boolean(quiz) && !result,
  })
```
3. Replace the body of `handleAnswerSelect` with:
```js
    timeline.recordAnswer(`bank:${questionId}`, { sel: [Number(optionIndex)] })
    setAnswers((prev) => ({
      ...prev,
      [questionId]: {
        question_id: questionId,
        selected_option: optionIndex.toString(),
      },
    }))
```
4. In `handleSubmit`, replace the `quizService.submitQuiz(quizId, {...})` call with:
```js
      await timeline.flush()
      const response = await quizService.submitQuiz(quizId, {
        answers: Object.values(answers).map((a) => ({
          ...a,
          time_taken_seconds: Math.round(timeline.activeSeconds(`bank:${a.question_id}`)),
        })),
        time_taken_seconds: quiz.duration_minutes * 60 - timeLeft,
      })
```

- [ ] **Step 4: Wire `MockTestAttempt.jsx`** (legacy mock + PYP; syncs by `parent_id`)

1. Add the import below the `quizService` import:
```js
import useResponseTimeline from '../hooks/useResponseTimeline'
```
2. Directly after the `const { data: test, isLoading } = useQuery({...})` block, add:
```js
  const currentQ = test?.questions?.[currentQuestion]
  const timeline = useResponseTimeline({
    attemptKind: 'mock',
    parentId: testId,
    currentKey: currentQ ? `bank:${currentQ.id}` : null,
    active: Boolean(test) && !result,
  })
```
3. Replace the body of `handleAnswerSelect` with:
```js
    timeline.recordAnswer(`bank:${questionId}`, { sel: [Number(optionIndex)] })
    setAnswers((prev) => ({
      ...prev,
      [questionId]: {
        question_id: questionId,
        selected_option: optionIndex.toString(),
      },
    }))
```
4. In `handleSubmit`, replace the `quizService.submitMockTest(testId, {...})` call with:
```js
      await timeline.flush()
      const response = await quizService.submitMockTest(testId, {
        answers: Object.values(answers).map((a) => ({
          ...a,
          time_taken_seconds: Math.round(timeline.activeSeconds(`bank:${a.question_id}`)),
        })),
        time_taken_seconds: test.duration_minutes * 60 - timeLeft,
      })
```

- [ ] **Step 5: Wire `RichMockAttempt.jsx`** (server-timed; syncs by `attempt_id`)

1. Add the import below the `mockTestBuilderService` import:
```js
import useResponseTimeline from '../hooks/useResponseTimeline'
```
2. Replace the three lines starting at `const q = questions[current]` (`q`, `setAns`, `cur`) with:
```js
  const q = questions[current]
  const timeline = useResponseTimeline({
    attemptKind: 'mock',
    attemptId,
    currentKey: q ? qKey(q) : null,
    active: phase === 'attempt' && !result,
  })
  const answerDigest = (patch) => {
    if (patch.selected !== undefined) return { sel: (patch.selected || []).map(Number) }
    if (patch.numerical_answer !== undefined) return { num: String(patch.numerical_answer ?? '') }
    if (patch.answer_text !== undefined) return { txt: (patch.answer_text || '').length }
    if (patch.code !== undefined) return { code: (patch.code || '').length }
    return null
  }
  const setAns = (patch) => {
    const digest = answerDigest(patch)
    if (digest) {
      const empty = (digest.sel && digest.sel.length === 0) || digest.num === '' ||
        digest.txt === 0 || digest.code === 0
      if (empty) timeline.clearAnswer(qKey(q))
      else timeline.recordAnswer(qKey(q), digest)
    }
    setAnswers((a) => ({ ...a, [qKey(q)]: { ...(a[qKey(q)] || {}), ...patch } }))
  }
  const cur = q ? (answers[qKey(q)] || {}) : {}
```
3. In `buildPayload`, add `time_taken_seconds` to both entry objects:
```js
        const entry = { question_id: question.ref_id, is_marked_for_review: marked,
          time_taken_seconds: Math.round(timeline.activeSeconds(qKey(question))) }
```
```js
        const entry = { item_id: question.ref_id, is_marked_for_review: marked,
          time_taken_seconds: Math.round(timeline.activeSeconds(qKey(question))) }
```
4. In `handleSubmit`, immediately before `const r = await mockTestBuilderService.submitRich(testId, buildPayload())`, add:
```js
      await timeline.flush()
```

`setAns` is also called with `language` alone; that yields no digest, which is fine.

- [ ] **Step 6: Wire `PracticeSession.jsx`** (untimed; the explanation screen is not "on the question")

1. Add the import below the `practiceService` import:
```js
import useResponseTimeline from '../hooks/useResponseTimeline'
```
2. Directly after `const item = items[index]`, add:
```js
  const timeline = useResponseTimeline({
    attemptKind: 'practice',
    attemptId: setId,
    // While the explanation is showing, the student is no longer answering.
    currentKey: item && !review ? `bank:${item.question_id}` : null,
    active: Boolean(set) && !summary,
  })
```
3. In `submitAnswer`, replace the payload construction with:
```js
    const key = `bank:${item.question_id}`
    const payload = {
      item_id: item.id,
      time_taken_seconds: Math.round(timeline.activeSeconds(key)),
    }
    if (item.question_type === 'numerical') {
      payload.numerical_answer = numerical
      timeline.recordAnswer(key, { num: String(numerical) })
    } else {
      payload.selected_options = selected
      timeline.recordAnswer(key, { sel: selected.map(Number) })
    }
    answerMutation.mutate(payload)
```
4. In `nextQuestion`, replace `submitMutation.mutate()` with:
```js
      timeline.flush().finally(() => submitMutation.mutate())
```
5. Remove the now-unused `startedAt` state and the `setStartedAt(Date.now())` line.

- [ ] **Step 7: Lint the changed files**

Run (from `frontend/exam-frontend`): `npx eslint src/hooks/useResponseTimeline.js src/services/timelineService.js src/pages/QuizAttempt.jsx src/pages/MockTestAttempt.jsx src/pages/RichMockAttempt.jsx src/pages/PracticeSession.jsx --max-warnings 0`

Expected: no errors. If a file already had lint errors before this task, run `git stash`, lint the original, then `git stash pop`, and fix only errors you introduced.

- [ ] **Step 8: Build**

Run (from `frontend/exam-frontend`): `npm run build`
Expected: build succeeds.

- [ ] **Step 9: Manual verification (use the `run` skill to start backend + frontend)**

- Take a quiz, open DevTools → Network:
  - `POST /api/v1/intelligence/timeline/` fires every 30 s and on tab hide, with `parent_id` and `e/l/a` events;
  - the submit payload's `time_taken_seconds` differ per question.
- Take a rich mock: syncs carry `attempt_id`. After submit, the Django shell shows `ResponseDiagnosis` rows for every item:
  `venv/Scripts/python.exe manage.py shell -c "from intelligence.models import ResponseDiagnosis as R; print(list(R.objects.values_list('label', flat=True)[:20]))"`
- Do a practice set: syncs carry `attempt_kind: practice`.

- [ ] **Step 10: Commit**

```bash
git add frontend/exam-frontend/src/hooks/useResponseTimeline.js frontend/exam-frontend/src/services/timelineService.js frontend/exam-frontend/src/pages/QuizAttempt.jsx frontend/exam-frontend/src/pages/MockTestAttempt.jsx frontend/exam-frontend/src/pages/RichMockAttempt.jsx frontend/exam-frontend/src/pages/PracticeSession.jsx
git commit -m "feat(frontend): record real per-question timelines on every attempt screen

Replaces fabricated per-answer time (total/n, 0, attempt total) with
visible on-screen time, and syncs raw enter/leave/answer events.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: "What happened?" on the three review pages

**Files:**
- Modify: `backend/quiz/mock_grading.py` (`ref_id` on review entries)
- Test: append to `backend/intelligence/tests/test_self_report.py`
- Create: `frontend/exam-frontend/src/components/review/WhatHappened.jsx`
- Modify: `frontend/exam-frontend/src/pages/QuizReview.jsx`, `MockTestReview.jsx`, `RichMockReview.jsx`

**Interfaces:**
- Consumes: `timelineService.getSelfReports`, `timelineService.saveSelfReport` (Task 9); self-report API (Task 8); `useTenantStore((s) => s.isFeatureEnabled)`.
- Produces:
  - `<WhatHappened attemptKind attemptId itemKind itemId initial />`
  - `useSelfReports(attemptKind, attemptId)` → `{ reports, notSeen: Set, enabled }`

- [ ] **Step 1: Write the failing backend test**

Append to `backend/intelligence/tests/test_self_report.py`:

```python
class RichReviewRefTests(DiagnosisTestCase):
    def test_review_entries_carry_ref_ids(self):
        from quiz.mock_grading import build_review

        item = self.make_item()
        attempt = self.finish(self.make_attempt())
        self.answer(attempt, item, selected=[1])
        entries = build_review(attempt)
        self.assertEqual(entries[0]['kind'], 'item')
        self.assertEqual(entries[0]['ref_id'], str(item.id))
```

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_self_report.RichReviewRefTests -v 2`
Expected: FAIL — `KeyError: 'ref_id'`.

- [ ] **Step 2: Add `ref_id`**

In `backend/quiz/mock_grading.py`:
- `_bank_review(answer)`: in the returned dict, next to `'kind': 'bank',`, add `'ref_id': str(answer.question_id),`.
- `_item_review(ans)`: next to `'kind': 'item',`, add `'ref_id': str(ans.item_id),`.

Re-run the test from Step 1. Expected: PASS.

- [ ] **Step 3: Create the component and hook**

Create `frontend/exam-frontend/src/components/review/WhatHappened.jsx`:

```jsx
import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { timelineService } from '../../services/timelineService'
import { useTenantStore } from '../../context/tenantStore'

const CHOICES = [
  ['slipped', 'Knew it, slipped'],
  ['ran_out_of_time', 'Ran out of time'],
  ['guessed', 'Guessed'],
  ['didnt_know', "Didn't know"],
]

/** Existing self-reports + never-seen items for one attempt (feature-gated). */
export function useSelfReports(attemptKind, attemptId) {
  const enabled = useTenantStore((s) => s.isFeatureEnabled)('response_diagnosis') && !!attemptId
  const { data } = useQuery({
    queryKey: ['selfReports', attemptKind, attemptId],
    queryFn: () => timelineService.getSelfReports(attemptKind, attemptId),
    enabled,
    staleTime: Infinity,
  })
  return {
    enabled,
    reports: data?.reports || {},
    notSeen: new Set(data?.not_seen || []),
  }
}

/** One-tap "what happened?" under a wrong or unanswered review item. Optional. */
export default function WhatHappened({ attemptKind, attemptId, itemKind, itemId, initial }) {
  const [choice, setChoice] = useState(initial || null)
  const [saving, setSaving] = useState(false)

  useEffect(() => { setChoice(initial || null) }, [initial])

  const pick = async (value) => {
    if (saving || value === choice) return
    const previous = choice
    setChoice(value)
    setSaving(true)
    try {
      await timelineService.saveSelfReport({
        attempt_kind: attemptKind,
        attempt_id: attemptId,
        item_kind: itemKind,
        item_id: itemId,
        choice: value,
      })
    } catch {
      setChoice(previous)
      toast.error('Could not save that — try again.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="mt-3 flex flex-wrap items-center gap-2">
      <span className="text-xs text-surface-500">What happened?</span>
      {CHOICES.map(([value, label]) => (
        <button
          key={value}
          type="button"
          disabled={saving}
          onClick={() => pick(value)}
          className={`text-xs px-3 py-1 rounded-full border transition-colors ${
            choice === value
              ? 'bg-primary-500 border-primary-500 text-white'
              : 'border-surface-300 dark:border-surface-700 hover:bg-surface-100 dark:hover:bg-surface-800'
          }`}
        >
          {label}
        </button>
      ))}
    </div>
  )
}
```

- [ ] **Step 4: Wire `QuizReview.jsx` and `MockTestReview.jsx`**

In each file:

1. Add the import:
```js
import WhatHappened, { useSelfReports } from '../components/review/WhatHappened'
```
2. Directly after the `const { data: attempt, isLoading, error } = useQuery({...})` block, add the line below. Use `'quiz'` in `QuizReview.jsx` and `'mock'` in `MockTestReview.jsx`. `attemptId` is the existing `useParams` value.
```js
  const selfReports = useSelfReports('quiz', attemptId)
```
3. Inside `filteredQuestions.map((item, index) => { ... })`, after `isSkipped` is defined, add:
```js
            const reviewKey = `bank:${question?.id}`
            const showWhatHappened = selfReports.enabled && !isCorrect && question?.id &&
              !selfReports.notSeen.has(reviewKey)
```
   and at the end of that item card's outer `<div>` (just before its closing tag), render:
```jsx
                {showWhatHappened && (
                  <WhatHappened
                    attemptKind="quiz"
                    attemptId={attemptId}
                    itemKind="bank"
                    itemId={question.id}
                    initial={selfReports.reports[reviewKey]}
                  />
                )}
```
   (`attemptKind="mock"` in `MockTestReview.jsx`.)

- [ ] **Step 5: Wire `RichMockReview.jsx`**

1. Add the import:
```js
import WhatHappened, { useSelfReports } from '../components/review/WhatHappened'
```
2. In the page component, after the `useQuery` for `data`, add:
```js
  const selfReports = useSelfReports('mock', attemptId)
```
3. Pass both values into each card: `<ReviewCard key={i} q={q} index={i} attemptId={attemptId} selfReports={selfReports} />`.
4. Change the `ReviewCard` signature to `function ReviewCard({ q, index, attemptId, selfReports })`. As the last child of its outer `<div className={`card p-5 border …`}>`, render:
```jsx
      {selfReports.enabled && !pending && !correct && q.ref_id &&
        !selfReports.notSeen.has(`${q.kind}:${q.ref_id}`) && (
        <WhatHappened
          attemptKind="mock"
          attemptId={attemptId}
          itemKind={q.kind}
          itemId={q.ref_id}
          initial={selfReports.reports[`${q.kind}:${q.ref_id}`]}
        />
      )}
```

- [ ] **Step 6: Lint, build, verify**

Run (from `frontend/exam-frontend`):
```
npx eslint src/components/review/WhatHappened.jsx src/pages/QuizReview.jsx src/pages/MockTestReview.jsx src/pages/RichMockReview.jsx --max-warnings 0
npm run build
```
Expected: clean lint, successful build.

Manual check (via the `run` skill):
- Enable "Answer Diagnosis" for the tenant: `features['response_diagnosis'] = True` in the Django shell or the feature settings UI.
- Open a finished quiz review: wrong and skipped questions show the four chips, correct ones don't.
- Tap a chip, reload: it stays selected.
- With the feature off, no chips appear and no `/self-report/` request is made.

- [ ] **Step 7: Commit**

```bash
git add backend/quiz/mock_grading.py backend/intelligence/tests/test_self_report.py frontend/exam-frontend/src/components/review/WhatHappened.jsx frontend/exam-frontend/src/pages/QuizReview.jsx frontend/exam-frontend/src/pages/MockTestReview.jsx frontend/exam-frontend/src/pages/RichMockReview.jsx
git commit -m "feat(review): one-tap 'what happened?' self-report on review pages

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Full verification and deploy notes

**Files:**
- Modify: `wiki/backend-guide.md` (append a short "Response diagnosis" section)

- [ ] **Step 1: Run the full backend suite**

Run (from `backend/`): `venv/Scripts/python.exe manage.py test -v 1`
Expected: all pass. Report any failure with its output. Do not skip tests.

- [ ] **Step 2: Migration sanity**

Run: `venv/Scripts/python.exe manage.py makemigrations --check --dry-run`
Expected: `No changes detected`.

- [ ] **Step 3: Document operations**

Append to `wiki/backend-guide.md`:

```markdown
## Response diagnosis (intelligence)

Every attempt screen records a raw per-question timeline
(`POST /api/v1/intelligence/timeline/` → `AttemptTimeline`). When an attempt
is finalized, the `intelligence.diagnose_and_update_state` task labels every
item, answered or not, as one of: not_seen, skipped, time_pressure, correct,
correct_lucky, correct_slow, guess, second_guess, careless_slip,
concept_gap, unclear. It writes `ResponseDiagnosis`, then recomputes learner
state with guesses and slips down-weighted.

- Thresholds: `intelligence/diagnosis_config.py`. After changing any value,
  bump `CLASSIFIER_VERSION` in `intelligence/versions.py` and run
  `manage.py recompute_diagnoses` (optionally `--tenant`, `--since`).
- After first deploy, run `manage.py recompute_learner_state`
  (`STATE_MODEL_VERSION` 2).
- Students' "What happened?" taps on review pages need the opt-in tenant
  feature `response_diagnosis`. Capture and classification run regardless.
- Calibration: `GET /api/v1/tenant-admin/intelligence/diagnosis/calibration/?days=30`
  compares classifier labels with self-reports.
```

- [ ] **Step 4: Commit**

```bash
git add wiki/backend-guide.md
git commit -m "docs: response diagnosis operations

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
