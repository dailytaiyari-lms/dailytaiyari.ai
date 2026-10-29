# Learning Layer 2B, Part A — Diagnosis Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show response diagnoses inside the product. Teachers get an
answer-behaviour panel per assessment, an "Answers" tab per student, and an
answer-behaviour tile per course. Students get a short note per answer on
their review pages. Admins get a diagnosis-quality page.

**Architecture:**
- **Switches:** two opt-in view switches, `diagnosis_teacher_view` and
  `diagnosis_student_view`, each requiring `response_diagnosis`. The
  requirement is enforced in `Tenant.get_features()`, so every caller sees
  the effective value.
- **Scope:** one module, `intelligence/access.py`, decides which courses and
  students a user may see. New views use it, and the existing Insights views
  switch to it.
- **Computation:** every number is computed on read from `ResponseDiagnosis`
  rows. The rules are pure functions in `intelligence/services/visibility.py`,
  and their thresholds and wording live in `intelligence/visibility_config.py`.
- **Views:** three new teacher endpoints and one new student endpoint. The
  existing calibration endpoint becomes admin-only and also reports its
  thresholds.
- **Frontend:** new panels on existing pages (AssessmentReport,
  StudentDiagnosis, InsightsHome, the three review pages) plus one new
  admin page.

**Tech Stack:** Django 5 / DRF, SQLite (tests), React 18 + Vite +
TanStack Query + Tailwind (exam-frontend), React (superadmin-frontend).

**Spec:** `docs/superpowers/specs/2026-10-24-learning-layer-2b-design.md`
§2, §3 and §4.

## Global Constraints

**Environment**
- Run backend commands from `backend/` with `venv/Scripts/python.exe`. The
  system python has no Django.
- Test command shape:
  `venv/Scripts/python.exe manage.py test <dotted.path> -v 2`.
- Frontend check: from `frontend/exam-frontend/`, `npx vite build`. From
  `frontend/superadmin-frontend/`, `npx vite build`. There is no frontend
  test runner.

**Git**
- Work on local branch `saksham/learning-layer-2b` (stacked on
  `saksham/learning-layer`, PR #213). Never push.
- Never change git config.
- Stage only the files your task names. Never `git add -A` or `git add .`.
- End every commit message with the `Co-Authored-By:` line given in your
  dispatch.

**Architecture rules**
- Other apps reach the intelligence layer only through
  `intelligence/api.py` and `intelligence/hooks.py`. Part A adds no calls
  from other apps.
- Part A adds **no models and no migrations** (the latest intelligence
  migration stays `0005_tagging_v2`). It reads `ResponseDiagnosis` (the
  student's self-report choice is copied onto its `self_report` CharField,
  so `ResponseSelfReport` is not queried), quiz/mock attempts, practice
  sets and course membership.
- Everything is computed per request. Each endpoint caps its work (constants
  in `visibility_config.py`) and paginates lists.
- Every new endpoint returns **403** when its switch is off and **403** when
  the course or student is out of the user's scope. A missing course, student
  or assessment stays **404**.
- Students never receive a bare label. The student endpoint returns note
  text only.
- `LEARNING_FEATURES` in `intelligence/api.py` is **not** changed in Part A.
  The two view switches collect nothing; they need `response_diagnosis`,
  which already turns collection on. (Plans B and C add `syllabus_tools`
  and `my_progress` to it.)

**Labels** (from `ResponseDiagnosis.LABEL_CHOICES`, display order):
`correct`, `correct_lucky`, `correct_slow`, `guess`, `second_guess`,
`careless_slip`, `time_pressure`, `concept_gap`, `skipped`, `not_seen`,
`unclear`. Every aggregate uses `final_label`.

**Decisions this plan makes where the spec is silent**
1. **Faculty see only in-scope attempts.** On the Answers tab, faculty see a
   student's attempts only for quizzes, mocks and practice sets that belong
   to one of their courses. Admins see every attempt. A mock linked to no
   course (open to the whole tenant) is admin-only.
2. **Calibration endpoint.** It becomes admin-only (spec §4.4 "Who: admin
   only") and gains two keys, `thresholds` and `classifier_version`, for
   the Diagnosis quality page. Its existing keys are unchanged.
3. **`CoursePracticeConfigView`** is narrowed to `can_manage_course` with the
   other Insights views, so faculty cannot change practice settings on a
   course they are not assigned to.
4. **Pattern code for topic slips** is `slips_in_topic`, with the topic in a
   separate `topic` field, so the frontend matches one stable code.
5. **`rushes_end` position.** An answered item is "in the last 10%" when
   `time_left_s ≤ 0.10 × (final_answer_at_s + time_left_s)`. An unanswered
   `time_pressure` item always counts, because that label only fires at the
   end of a timed window. An attempt is "timed" when its rows carry
   `metrics.ended_late`, which the classifier sets only for timed windows.
6. **Course tile rates** use all diagnosed rows in the window as the
   denominator. Weeks are bucketed by the attempt's `completed_at`.
7. **Recent assessments on the course tile.** Nothing links to the
   assessment report today, so the course behaviour payload also lists the 5
   most recent assessments with diagnoses in the window. The tile links to
   their reports.
8. **Attempt order on the Answers tab** is the time an attempt was first
   diagnosed (`Min(ResponseDiagnosis.created_at)`), which matches submit
   order. History labelled later by `recompute_diagnoses` sorts by when it
   was recomputed.
9. **Learning Insights in the menu** shows when `practice` **or**
   `diagnosis_teacher_view` is on. The Smart Practice tiles on Insights home
   show only when `practice` is on.

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/core/models.py` (modify) | two new feature keys, `FEATURE_REQUIRES`, dependency in `get_features()` |
| `backend/core/admin_serializers.py` (modify) | `requires` / `requires_label` on `available_features` |
| `backend/core/superadmin_serializers.py` (modify) | the same for the super-admin payload |
| `backend/intelligence/access.py` (create) | `teachable_course_ids`, `can_view_student`, `can_manage_course`, `diagnosis_scope_q`, `assessment_in_scope` |
| `backend/intelligence/visibility_config.py` (create) | flag and pattern thresholds, tile window, page sizes, student notes |
| `backend/intelligence/services/visibility.py` (create) | pure: label distribution, flags, patterns, evidence sentences, student note, rates, trend, students to check |
| `backend/intelligence/admin_views.py` (modify) | narrow existing views; `AssessmentBehaviourView`, `StudentAnswersView`, `CourseBehaviourView`; calibration admin-only |
| `backend/intelligence/admin_urls.py` (modify) | three routes |
| `backend/intelligence/views.py` (modify) | `MyAttemptDiagnosisView` |
| `backend/intelligence/urls.py` (modify) | one route |
| `backend/intelligence/tests/test_visibility_switches.py` (create) | switch dependency + settings payload |
| `backend/intelligence/tests/test_access.py` (create) | helpers + narrowing of existing views |
| `backend/intelligence/tests/test_visibility_rules.py` (create) | pure rules |
| `backend/intelligence/tests/test_visibility_api.py` (create) | the four new endpoints + calibration |
| `backend/intelligence/tests/visibility_fixtures.py` (create) | shared tenant / staff / attempts / diagnosis rows |
| `frontend/exam-frontend/src/context/tenantStore.js` (modify) | opt-in list; `isAnyOptInFeatureEnabled` |
| `frontend/exam-frontend/src/services/insightsService.js` (modify) | four calls |
| `frontend/exam-frontend/src/services/diagnosisService.js` (create) | student notes call |
| `frontend/exam-frontend/src/components/insights/labels.js` (create) | teacher label names + colours |
| `frontend/exam-frontend/src/components/insights/LabelBar.jsx` (create) | stacked bar |
| `frontend/exam-frontend/src/components/insights/AnswerBehaviourPanel.jsx` (create) | assessment panel |
| `frontend/exam-frontend/src/components/insights/StudentAnswersTab.jsx` (create) | Answers tab |
| `frontend/exam-frontend/src/components/insights/AnswerBehaviourTile.jsx` (create) | course tile |
| `frontend/exam-frontend/src/components/review/DiagnosisNote.jsx` (create) | `useDiagnosisNotes` + one-line note |
| `frontend/exam-frontend/src/components/review/WhatHappened.jsx` (modify) | relabel the row |
| `frontend/exam-frontend/src/pages/AssessmentReport.jsx` (modify) | mount the panel |
| `frontend/exam-frontend/src/pages/StudentDiagnosis.jsx` (modify) | tabs |
| `frontend/exam-frontend/src/pages/InsightsHome.jsx` (modify) | tile, scoped course picker, practice gating, quality link |
| `frontend/exam-frontend/src/pages/DiagnosisQuality.jsx` (create) | admin calibration page |
| `frontend/exam-frontend/src/pages/QuizReview.jsx`, `MockTestReview.jsx`, `RichMockReview.jsx` (modify) | notes |
| `frontend/exam-frontend/src/components/layout/AdminSidebar.jsx` (modify) | `features` (any of) on nav items |
| `frontend/exam-frontend/src/App.jsx` (modify) | quality route |
| `frontend/exam-frontend/src/pages/AdminDashboard.jsx` (modify) | greyed dependent switches |
| `frontend/superadmin-frontend/src/pages/TenantDetail.jsx` (modify) | dependency hint |
| `wiki/backend-guide.md` (modify) | diagnosis visibility ops notes + local walkthrough |

---

### Task 1: Feature switches and their dependency

**Files:**
- Modify: `backend/core/models.py` (`FEATURE_CHOICES`, `OPT_IN_FEATURES`, new `FEATURE_REQUIRES`, `get_features`)
- Modify: `backend/core/admin_serializers.py` (`TenantSettingsSerializer.to_representation`)
- Modify: `backend/core/superadmin_serializers.py` (`to_representation`, the `available_features` list)
- Modify: `frontend/exam-frontend/src/context/tenantStore.js`
- Test: `backend/intelligence/tests/test_visibility_switches.py`

**Interfaces:**
- Produces:
  - feature keys `diagnosis_teacher_view` and `diagnosis_student_view`, off by default;
  - `Tenant.FEATURE_REQUIRES = {'diagnosis_teacher_view': 'response_diagnosis', 'diagnosis_student_view': 'response_diagnosis'}`;
  - `get_features()` reports a dependent key `True` only when its requirement is also `True`;
  - each `available_features` entry (tenant-admin and super-admin payloads) gains `requires` (key or `null`) and `requires_label` (label or `null`);
  - frontend `OPT_IN_FEATURES` lists the two keys, and `isAnyOptInFeatureEnabled(keys)` exists.

- [ ] **Step 1: Write the failing test**

Create `backend/intelligence/tests/test_visibility_switches.py`:

```python
"""Diagnosis view switches: opt-in, and only on while Answer Diagnosis is on."""
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.models import Tenant
from users.models import User

VIEW_KEYS = ('diagnosis_teacher_view', 'diagnosis_student_view')


class SwitchDependencyTests(TestCase):
    def test_view_switches_are_off_by_default(self):
        features = Tenant.objects.create(name='Default Academy').get_features()
        for key in VIEW_KEYS:
            self.assertIs(features[key], False)

    def test_view_switch_is_off_while_requirement_is_off(self):
        tenant = Tenant.objects.create(
            name='Half Academy',
            features={'diagnosis_teacher_view': True, 'diagnosis_student_view': True},
        )
        features = tenant.get_features()
        for key in VIEW_KEYS:
            self.assertIs(features[key], False)

    def test_view_switch_is_on_with_requirement(self):
        tenant = Tenant.objects.create(
            name='Full Academy',
            features={'response_diagnosis': True, 'diagnosis_teacher_view': True},
        )
        features = tenant.get_features()
        self.assertIs(features['diagnosis_teacher_view'], True)
        self.assertIs(features['diagnosis_student_view'], False)

    def test_force_on_lock_still_needs_requirement(self):
        tenant = Tenant.objects.create(
            name='Locked Academy', feature_locks={'diagnosis_teacher_view': True},
        )
        self.assertIs(tenant.get_features()['diagnosis_teacher_view'], False)
        tenant.feature_locks = {'diagnosis_teacher_view': True, 'response_diagnosis': True}
        self.assertIs(tenant.get_features()['diagnosis_teacher_view'], True)

    def test_requirement_map_names_known_keys(self):
        for key, required in Tenant.FEATURE_REQUIRES.items():
            self.assertIn(key, Tenant.FEATURE_CHOICES)
            self.assertIn(required, Tenant.FEATURE_CHOICES)
            self.assertIn(key, Tenant.OPT_IN_FEATURES)


class SettingsPayloadTests(TestCase):
    def test_tenant_settings_mark_the_dependency(self):
        tenant = Tenant.objects.create(name='Payload Academy', is_active=True)
        admin = User.objects.create_user(
            email='payload-admin@example.com', password='pw-payload-1',
            tenant=tenant, role='admin',
        )
        client = APIClient()
        client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(admin).access_token}',
            HTTP_X_TENANT_ID=str(tenant.id),
        )
        response = client.get('/api/v1/tenant-admin/settings/')
        self.assertEqual(response.status_code, 200, response.content)
        by_key = {row['key']: row for row in response.json()['available_features']}
        self.assertEqual(by_key['diagnosis_teacher_view']['requires'], 'response_diagnosis')
        self.assertEqual(by_key['diagnosis_student_view']['requires_label'], 'Answer Diagnosis')
        self.assertIsNone(by_key['quiz']['requires'])
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_visibility_switches -v 2`
Expected: FAIL / ERROR (`KeyError: 'diagnosis_teacher_view'`, `AttributeError: ... FEATURE_REQUIRES`).

- [ ] **Step 3: Implement**

In `backend/core/models.py`, add two entries to `FEATURE_CHOICES` directly after `'response_diagnosis': 'Answer Diagnosis',`:

```python
        'diagnosis_teacher_view': 'Diagnosis: teacher view',
        'diagnosis_student_view': 'Diagnosis: student view',
```

Replace the `OPT_IN_FEATURES` line, and add `FEATURE_REQUIRES` under it:

```python
    OPT_IN_FEATURES = {
        'practice', 'ai_grading', 'response_diagnosis',
        'diagnosis_teacher_view', 'diagnosis_student_view',
    }

    # Features that only work on top of another one: {feature: required}.
    # get_features() reports a dependent feature as on only while its
    # requirement is on; the stored value is kept, so switching the
    # requirement back on restores it.
    FEATURE_REQUIRES = {
        'diagnosis_teacher_view': 'response_diagnosis',
        'diagnosis_student_view': 'response_diagnosis',
    }
```

Replace the body of `get_features` (keep the method name and docstring's first paragraph; extend the docstring):

```python
    def get_features(self):
        """Return the full *effective* feature map.

        Resolution per feature key: a super-admin lock (``feature_locks``) wins
        and forces its value; otherwise the tenant's own ``features`` value is
        used, defaulting any missing key to enabled. Finally a feature listed
        in ``FEATURE_REQUIRES`` is off while its requirement is off.
        """
        stored = self.features or {}
        locks = self.feature_locks or {}
        result = {}
        for key in self.FEATURE_CHOICES:
            if key in locks:
                result[key] = bool(locks[key])
            else:
                default = key not in self.OPT_IN_FEATURES
                result[key] = bool(stored.get(key, default))
        for key, required in self.FEATURE_REQUIRES.items():
            if not result.get(required):
                result[key] = False
        return result
```

In `backend/core/admin_serializers.py` `to_representation`, replace the `data['available_features'] = [...]` block with:

```python
        data['available_features'] = [
            {
                'key': key,
                'label': labels.get(key, label),
                'default_label': label,
                'is_renamed': key in overrides,
                'requires': Tenant.FEATURE_REQUIRES.get(key),
                'requires_label': (
                    labels.get(Tenant.FEATURE_REQUIRES[key])
                    if key in Tenant.FEATURE_REQUIRES else None
                ),
            }
            for key, label in Tenant.FEATURE_CHOICES.items()
        ]
```

In `backend/core/superadmin_serializers.py` `to_representation`, replace the `data['available_features'] = [...]` block with:

```python
        data['available_features'] = [
            {
                'key': k,
                'label': label,
                'tenant_label': instance.get_feature_labels().get(k, label),
                'requires': Tenant.FEATURE_REQUIRES.get(k),
                'requires_label': (
                    Tenant.FEATURE_CHOICES[Tenant.FEATURE_REQUIRES[k]]
                    if k in Tenant.FEATURE_REQUIRES else None
                ),
            }
            for k, label in Tenant.FEATURE_CHOICES.items()
        ]
```

In `frontend/exam-frontend/src/context/tenantStore.js`, replace the `OPT_IN_FEATURES` line:

```js
export const OPT_IN_FEATURES = [
    'practice', 'ai_grading', 'response_diagnosis',
    'diagnosis_teacher_view', 'diagnosis_student_view',
];
```

and add, directly after `isOptInFeatureEnabled`:

```js
    // True when any of the given opt-in keys is explicitly enabled.
    isAnyOptInFeatureEnabled: (keys) => keys.some((key) => get().tenant?.features?.[key] === true),
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_visibility_switches intelligence.tests.test_gate core -v 2`
Expected: all PASS. (`test_gate` covers PR #213's opt-in behaviour; `core` covers the settings serializers.)

- [ ] **Step 5: Commit**

```bash
git add backend/core/models.py backend/core/admin_serializers.py backend/core/superadmin_serializers.py frontend/exam-frontend/src/context/tenantStore.js backend/intelligence/tests/test_visibility_switches.py
git commit -m "feat(core): diagnosis view switches that need Answer Diagnosis"
```

---

### Task 2: Access helpers and narrowing the existing Insights views

**Files:**
- Create: `backend/intelligence/access.py`
- Create: `backend/intelligence/tests/visibility_fixtures.py`
- Modify: `backend/intelligence/admin_views.py` (`OverviewView`, `AssessmentReportView`, `StudentDiagnosisView`, `GeneratedItemsView`, `GenerationJobsView`, `CoursePracticeConfigView`)
- Test: `backend/intelligence/tests/test_access.py`

**Interfaces:**
- Produces (`intelligence/access.py`):
  - `teachable_course_ids(user) -> set[UUID]`;
  - `can_view_student(user, student_profile) -> bool`;
  - `can_manage_course(user, course) -> bool`;
  - `assessment_course_ids(kind, assessment) -> list[UUID]`;
  - `assessment_in_scope(user, kind, assessment) -> bool`;
  - `diagnosis_scope_q(user, student) -> Q` over `ResponseDiagnosis`.
- Produces (`tests/visibility_fixtures.py`): `VisibilityTestCase` with `tenant`, `admin`, `faculty` (assigned to `course`), `other_faculty` (assigned to `other_course`), `student` (approved in `course`), `outsider` (approved in `other_course`), `subject`, `topic`, `quiz`, `client_for(user)`, `make_question(n)`, `quiz_attempt(student, questions, minutes_ago)`, `diagnose(attempt, question, label, **fields)`.
- Consumes: `Course.instructors` (`User.instructing_courses`), `CourseEnrollment(status='approved')`.

- [ ] **Step 1: Write the shared fixture**

Create `backend/intelligence/tests/visibility_fixtures.py`:

```python
"""Shared fixtures for the diagnosis-visibility tests: one tenant with
Answer Diagnosis and both view switches on, an admin, two faculty on two
courses, a student in each course, and helpers for attempts and rows."""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.models import Tenant
from exams.models import Course, Subject, Topic
from intelligence.models import ResponseDiagnosis
from quiz.models import Question, QuestionOption, Quiz, QuizAttempt, QuizQuestion
from users.models import CourseEnrollment, User

ALL_ON = {
    'response_diagnosis': True,
    'diagnosis_teacher_view': True,
    'diagnosis_student_view': True,
}


class VisibilityTestCase(TestCase):
    features = ALL_ON

    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create(
            name='Visibility Academy', is_active=True, features=dict(cls.features),
        )

        def user(email, role):
            return User.objects.create_user(
                email=email, password='pw-vis-1', tenant=cls.tenant, role=role,
            )

        cls.admin = user('vis-admin@example.com', 'admin')
        cls.faculty = user('vis-faculty@example.com', 'instructor')
        cls.other_faculty = user('vis-faculty-2@example.com', 'instructor')
        cls.student_user = user('vis-student@example.com', 'student')
        cls.outsider_user = user('vis-outsider@example.com', 'student')
        cls.student = cls.student_user.profile
        cls.outsider = cls.outsider_user.profile

        cls.course = Course.objects.create(
            tenant=cls.tenant, name='Physics', code='vis-physics',
            course_type='competitive', status='active',
        )
        cls.other_course = Course.objects.create(
            tenant=cls.tenant, name='Chemistry', code='vis-chem',
            course_type='competitive', status='active',
        )
        cls.course.instructors.add(cls.faculty)
        cls.other_course.instructors.add(cls.other_faculty)
        CourseEnrollment.objects.create(
            tenant=cls.tenant, student=cls.student, course=cls.course,
            status='approved', is_active=True,
        )
        CourseEnrollment.objects.create(
            tenant=cls.tenant, student=cls.outsider, course=cls.other_course,
            status='approved', is_active=True,
        )
        cls.subject = Subject.objects.create(
            tenant=cls.tenant, course=cls.course, name='Mechanics', code='vis-mech',
        )
        cls.topic = Topic.objects.create(
            tenant=cls.tenant, subject=cls.subject, name='Kinematics', code='vis-kin',
        )
        cls.quiz = Quiz.objects.create(
            tenant=cls.tenant, course=cls.course, title='Kinematics quiz',
            quiz_type='topic', duration_minutes=30,
        )

    def client_for(self, user):
        client = APIClient()
        client.credentials(
            HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(user).access_token}',
            HTTP_X_TENANT_ID=str(self.tenant.id),
        )
        return client

    def make_question(self, n, *, quiz=None):
        question = Question.objects.create(
            tenant=self.tenant, topic=self.topic, subject=self.subject,
            question_text=f'Question {n}?', question_type='mcq',
            difficulty='medium', status='published', correct_answer='0', marks=1,
        )
        QuestionOption.objects.create(
            tenant=self.tenant, question=question, option_text='A', is_correct=True, order=0,
        )
        # QuizQuestion declares its own Meta, so it has no default ordering:
        # set ``order`` so paper order is deterministic.
        QuizQuestion.objects.create(quiz=quiz or self.quiz, question=question, order=n)
        return question

    def quiz_attempt(self, student, *, quiz=None, minutes_ago=60, status='completed'):
        attempt = QuizAttempt.objects.create(
            student=student, quiz=quiz or self.quiz, status=status,
        )
        done = timezone.now() - timedelta(minutes=minutes_ago)
        QuizAttempt.objects.filter(id=attempt.id).update(
            started_at=done - timedelta(minutes=20), completed_at=done,
        )
        attempt.refresh_from_db()
        return attempt

    def diagnose(self, attempt, question, label, *, confidence='high', metrics=None,
                 evidence=None, self_report='', is_correct=None, answered=True,
                 kind='quiz', student=None):
        if is_correct is None:
            is_correct = label in ('correct', 'correct_lucky', 'correct_slow')
        return ResponseDiagnosis.objects.create(
            tenant=self.tenant, student=student or attempt.student,
            attempt_kind=kind, attempt_id=attempt.id, question=question,
            answered=answered, is_correct=is_correct,
            score_fraction=1.0 if is_correct else 0.0,
            metrics=metrics or {}, flags=[], evidence=evidence or [],
            label=label, final_label=label, confidence=confidence,
            self_report=self_report, computed_at=timezone.now(),
        )
```

- [ ] **Step 2: Write the failing test**

Create `backend/intelligence/tests/test_access.py`:

```python
"""Who sees which students and courses (spec 2B §3.2), and the narrowing of
the existing Insights views for faculty."""
from intelligence.access import (
    can_manage_course, can_view_student, diagnosis_scope_q, teachable_course_ids,
)
from intelligence.models import ResponseDiagnosis
from intelligence.tests.visibility_fixtures import VisibilityTestCase
from quiz.models import Quiz

INSIGHTS = '/api/v1/tenant-admin/intelligence'


class HelperTests(VisibilityTestCase):
    def test_teachable_course_ids(self):
        self.assertEqual(teachable_course_ids(self.admin), {self.course.id, self.other_course.id})
        self.assertEqual(teachable_course_ids(self.faculty), {self.course.id})
        self.assertEqual(teachable_course_ids(self.student_user), set())

    def test_can_view_student(self):
        self.assertTrue(can_view_student(self.admin, self.outsider))
        self.assertTrue(can_view_student(self.faculty, self.student))
        self.assertFalse(can_view_student(self.faculty, self.outsider))
        self.assertFalse(can_view_student(self.student_user, self.student))

    def test_pending_enrollment_is_not_in_scope(self):
        enrollment = self.student.enrollments.get(course=self.course)
        enrollment.status = 'pending'
        enrollment.save()
        self.assertFalse(can_view_student(self.faculty, self.student))

    def test_can_manage_course(self):
        self.assertTrue(can_manage_course(self.admin, self.other_course))
        self.assertTrue(can_manage_course(self.faculty, self.course))
        self.assertFalse(can_manage_course(self.faculty, self.other_course))
        self.assertFalse(can_manage_course(self.student_user, self.course))

    def test_diagnosis_scope_limits_faculty_to_their_courses(self):
        question = self.make_question(1)
        mine = self.diagnose(self.quiz_attempt(self.student), question, 'guess')
        other_quiz = Quiz.objects.create(
            tenant=self.tenant, course=self.other_course, title='Chem quiz',
            quiz_type='topic', duration_minutes=10,
        )
        theirs = self.diagnose(
            self.quiz_attempt(self.student, quiz=other_quiz),
            self.make_question(2, quiz=other_quiz), 'guess',
        )
        rows = ResponseDiagnosis.objects.filter(student=self.student)
        self.assertEqual(
            set(rows.filter(diagnosis_scope_q(self.faculty, self.student))
                .values_list('id', flat=True)),
            {mine.id},
        )
        self.assertEqual(
            set(rows.filter(diagnosis_scope_q(self.admin, self.student))
                .values_list('id', flat=True)),
            {mine.id, theirs.id},
        )


class ExistingViewNarrowingTests(VisibilityTestCase):
    def test_overview_refuses_unassigned_course_for_faculty(self):
        client = self.client_for(self.faculty)
        self.assertEqual(
            client.get(f'{INSIGHTS}/overview/', {'course': str(self.course.id)}).status_code, 200)
        self.assertEqual(
            client.get(f'{INSIGHTS}/overview/', {'course': str(self.other_course.id)}).status_code,
            403)
        self.assertEqual(
            self.client_for(self.admin).get(
                f'{INSIGHTS}/overview/', {'course': str(self.other_course.id)}).status_code,
            200)

    def test_assessment_report_refuses_unassigned_course_for_faculty(self):
        url = f'{INSIGHTS}/assessments/quiz/{self.quiz.id}/report/'
        self.assertEqual(self.client_for(self.faculty).get(url).status_code, 200)
        self.assertEqual(self.client_for(self.other_faculty).get(url).status_code, 403)

    def test_student_diagnosis_refuses_out_of_scope_student(self):
        client = self.client_for(self.faculty)
        self.assertEqual(
            client.get(f'{INSIGHTS}/students/{self.student.id}/diagnosis/').status_code, 200)
        self.assertEqual(
            client.get(f'{INSIGHTS}/students/{self.outsider.id}/diagnosis/').status_code, 403)

    def test_practice_config_refuses_unassigned_course_for_faculty(self):
        url = f'{INSIGHTS}/courses/{self.other_course.id}/practice-config/'
        self.assertEqual(self.client_for(self.faculty).get(url).status_code, 403)
        self.assertEqual(self.client_for(self.other_faculty).get(url).status_code, 200)

    def test_generation_jobs_are_filtered_for_faculty(self):
        from intelligence.models import PracticeGenerationJob

        PracticeGenerationJob.objects.create(
            tenant=self.tenant, course=self.other_course, deficit_kind='low_mastery',
            deficit_signature='sig',
        )
        self.assertEqual(self.client_for(self.faculty).get(f'{INSIGHTS}/generation-jobs/').json(), [])
        self.assertEqual(len(self.client_for(self.admin).get(f'{INSIGHTS}/generation-jobs/').json()), 1)
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_access -v 2`
Expected: ImportError (`No module named 'intelligence.access'`).

- [ ] **Step 4: Implement `access.py`**

Create `backend/intelligence/access.py`:

```python
"""Who may see which students and courses in the learning layer (spec 2B §3.2).

- Students see only themselves; their endpoints never take a student id.
- Faculty (``role='instructor'``) see the courses they are assigned to
  (``Course.instructors``) and the students with an approved enrollment in
  one of them.
- Admins see every course and student in their tenant.

Every teacher-facing intelligence view goes through these helpers, so the
rule lives in one place.
"""
from django.db.models import Q

from exams.models import Course

STAFF_ROLES = ('admin', 'instructor')


def _role(user):
    return getattr(user, 'role', '') if user is not None else ''


def teachable_course_ids(user):
    """Ids of the courses ``user`` may see, as a set (empty for students)."""
    role = _role(user)
    if role not in STAFF_ROLES or not getattr(user, 'tenant_id', None):
        return set()
    courses = Course.objects.filter(tenant_id=user.tenant_id)
    if role != 'admin':
        courses = courses.filter(instructors=user)
    return set(courses.values_list('id', flat=True))


def can_manage_course(user, course):
    """Admins: any course in their tenant. Faculty: their assigned courses."""
    role = _role(user)
    if course is None or role not in STAFF_ROLES:
        return False
    if course.tenant_id != getattr(user, 'tenant_id', None):
        return False
    if role == 'admin':
        return True
    return course.instructors.filter(id=user.id).exists()


def can_view_student(user, student):
    """Admins: any student in their tenant. Faculty: students with an
    approved enrollment in one of their courses."""
    from users.models import CourseEnrollment

    role = _role(user)
    if student is None or role not in STAFF_ROLES:
        return False
    if student.user.tenant_id != getattr(user, 'tenant_id', None):
        return False
    if role == 'admin':
        return True
    return CourseEnrollment.objects.filter(
        student=student, status='approved', course__instructors=user,
    ).exists()


def assessment_course_ids(kind, assessment):
    """The courses a quiz or mock belongs to (a mock can have several, or none)."""
    if kind == 'quiz':
        return [assessment.course_id] if assessment.course_id else []
    ids = list(assessment.courses.values_list('id', flat=True))
    if not ids and assessment.course_id:
        ids = [assessment.course_id]
    return ids


def assessment_in_scope(user, kind, assessment):
    """Admins see every assessment. Faculty see those linked to one of their
    courses; a mock linked to no course is open to the whole tenant, so it is
    admin-only."""
    if _role(user) == 'admin':
        return True
    return bool(set(assessment_course_ids(kind, assessment)) & teachable_course_ids(user))


def diagnosis_scope_q(user, student):
    """A ``Q`` over ResponseDiagnosis limiting ``student``'s rows to the
    attempts ``user`` may see: everything for admins; for faculty, quizzes,
    mocks and practice sets that belong to one of their courses."""
    from quiz.models import MockTestAttempt, QuizAttempt

    from intelligence.models import PracticeSet

    if _role(user) == 'admin':
        return Q()
    ids = teachable_course_ids(user)
    quiz_ids = QuizAttempt.objects.filter(
        student=student, quiz__course_id__in=ids).values('id')
    mock_ids = MockTestAttempt.objects.filter(student=student).filter(
        Q(mock_test__course_id__in=ids) | Q(mock_test__courses__id__in=ids)).values('id')
    practice_ids = PracticeSet.objects.filter(
        student=student, course_id__in=ids).values('id')
    return (
        Q(attempt_kind='quiz', attempt_id__in=quiz_ids)
        | Q(attempt_kind='mock', attempt_id__in=mock_ids)
        | Q(attempt_kind='practice', attempt_id__in=practice_ids)
    )
```

- [ ] **Step 5: Narrow the existing views**

In `backend/intelligence/admin_views.py`:

1. Add to the imports:

```python
from .access import (
    assessment_course_ids, assessment_in_scope, can_manage_course, can_view_student,
    teachable_course_ids,
)
```

2. Below `_course_or_404`, add (a fresh `Response` per call; never share one instance):

```python
def _forbidden():
    return Response({'error': 'Not in your courses.'}, status=status.HTTP_403_FORBIDDEN)
```

3. `OverviewView.get`: after the `if course is None:` block add:

```python
        if not can_manage_course(request.user, course):
            return _forbidden()
```

4. `AssessmentReportView.get`: after the `if assessment is None:` block add:

```python
        if not assessment_in_scope(request.user, kind, assessment):
            return _forbidden()
```

and replace the body of its `_courses` staticmethod with:

```python
        return list(Course.objects.filter(id__in=assessment_course_ids(kind, assessment)))
```

5. `StudentDiagnosisView.get`: after the `if student is None:` block add:

```python
        if not can_view_student(request.user, student):
            return _forbidden()
```

and replace

```python
        course_id = request.query_params.get('course')
        if course_id:
            states = states.filter(concept__subject__course_id=course_id)
```

with

```python
        course_id = request.query_params.get('course')
        if course_id:
            states = states.filter(concept__subject__course_id=course_id)
        elif request.user.role != 'admin':
            states = states.filter(
                concept__subject__course_id__in=teachable_course_ids(request.user))
```

and filter the practice history the same way for faculty, replacing the `sets = (...)` statement with:

```python
        sets = PracticeSet.objects.filter(student=student)
        if request.user.role != 'admin':
            sets = sets.filter(course_id__in=teachable_course_ids(request.user))
        sets = (
            sets.select_related('course').prefetch_related('target_concepts', 'items')
            .order_by('-created_at')[:30]
        )
```

6. `GeneratedItemsView.get`: after `rows = (...)` add:

```python
        if request.user.role != 'admin':
            rows = rows.filter(question__courses__id__in=teachable_course_ids(request.user)).distinct()
```

`GeneratedItemsView.post`: after the `if row is None:` block add:

```python
        if request.user.role != 'admin' and not row.question.courses.filter(
                id__in=teachable_course_ids(request.user)).exists():
            return _forbidden()
```

7. `GenerationJobsView.get`: replace the `jobs = (...)` statement with:

```python
        jobs = PracticeGenerationJob.objects.filter(tenant=request.tenant)
        if request.user.role != 'admin':
            jobs = jobs.filter(course_id__in=teachable_course_ids(request.user))
        jobs = jobs.select_related('course').order_by('-created_at')[:100]
```

8. `CoursePracticeConfigView.get` and `.patch`: after each `if course is None:` block add:

```python
        if not can_manage_course(request.user, course):
            return _forbidden()
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_access intelligence.tests.test_practice intelligence.tests.test_self_report -v 2`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/intelligence/access.py backend/intelligence/admin_views.py backend/intelligence/tests/visibility_fixtures.py backend/intelligence/tests/test_access.py
git commit -m "feat(intelligence): one scope rule for Insights; faculty see only their courses"
```

---

### Task 3: Visibility config and pure rules

**Files:**
- Create: `backend/intelligence/visibility_config.py`
- Create: `backend/intelligence/services/visibility.py`
- Test: `backend/intelligence/tests/test_visibility_rules.py`

**Interfaces:**
- Produces (`visibility.py`, all pure, no database):
  - `LABELS` — the label display order (tuple of 11 keys);
  - `median(values) -> float | None` (ignores `None`);
  - `label_distribution(labels) -> {'total', 'counts', 'shares'}` with every key of `LABELS` present;
  - `question_flags(distribution) -> [{'code', 'message', 'share'}]`;
  - `in_last_part(label, metrics, share) -> bool`;
  - `detect_patterns(attempts) -> [{'code', 'message', 'count', 'answer_ids', 'topic'?}]` where `attempts` is newest-first `[{'answers': [row]}]` and a row is `{'id', 'label', 'is_correct', 'answered', 'metrics', 'topic'}`;
  - `describe_evidence(evidence, metrics) -> [str]`;
  - `student_note(label, confidence, metrics) -> str | None`;
  - `behaviour_rates(labels) -> {'answers', 'guess', 'careless_slip', 'time_pressure'}` (rates `None` when there are no answers);
  - `students_to_check(per_student) -> [{'student_id', 'answers', 'careless_slip', 'time_pressure'}]` where `per_student` maps id → list of labels.

- [ ] **Step 1: Write the failing test**

Create `backend/intelligence/tests/test_visibility_rules.py`:

```python
"""Pure diagnosis-visibility rules, against hand-computed fixtures."""
from django.test import SimpleTestCase

from intelligence.services import visibility as v


def row(label, *, id=None, topic=None, metrics=None, answered=True, is_correct=None):
    if is_correct is None:
        is_correct = label in ('correct', 'correct_lucky', 'correct_slow')
    return {'id': id or f'{label}-{topic}', 'label': label, 'topic': topic,
            'metrics': metrics or {}, 'answered': answered, 'is_correct': is_correct}


class DistributionAndFlagTests(SimpleTestCase):
    def test_distribution_fills_every_label(self):
        dist = v.label_distribution(['guess', 'guess', 'correct', 'not_seen'])
        self.assertEqual(dist['total'], 4)
        self.assertEqual(dist['counts']['guess'], 2)
        self.assertEqual(dist['counts']['unclear'], 0)
        self.assertEqual(dist['shares']['guess'], 0.5)
        self.assertEqual(set(dist['counts']), set(v.LABELS))

    def test_empty_distribution(self):
        dist = v.label_distribution([])
        self.assertEqual(dist['total'], 0)
        self.assertEqual(dist['shares']['guess'], 0.0)

    def test_many_guesses_fires_at_35_percent_with_8_answers(self):
        # 2 guess + 1 correct_lucky = 3 of 8 = 37.5 %
        labels = ['guess', 'guess', 'correct_lucky'] + ['correct'] * 5
        codes = [f['code'] for f in v.question_flags(v.label_distribution(labels))]
        self.assertEqual(codes, ['many_guesses'])

    def test_flags_need_8_answers(self):
        labels = ['guess'] * 7
        self.assertEqual(v.question_flags(v.label_distribution(labels)), [])

    def test_slips_and_time_crunch(self):
        labels = (['second_guess', 'careless_slip']           # 2/8 = 25 %
                  + ['time_pressure', 'not_seen', 'not_seen']  # 3/8 = 37.5 %
                  + ['correct'] * 3)
        flags = v.question_flags(v.label_distribution(labels))
        self.assertEqual([f['code'] for f in flags],
                         ['many_second_guesses_or_slips', 'time_crunch'])
        self.assertEqual(flags[1]['message'], 'Most students ran out of time before this.')
        self.assertEqual(flags[1]['share'], 0.375)

    def test_median_ignores_none(self):
        self.assertEqual(v.median([None, 3, 1, 2]), 2)
        self.assertEqual(v.median([4, 2]), 3)
        self.assertIsNone(v.median([None]))


class LastPartTests(SimpleTestCase):
    def test_answer_in_last_ten_percent(self):
        # 1800 s window: answered at 1700 s with 100 s left (5.6 %)
        self.assertTrue(v.in_last_part('guess', {'final_answer_at_s': 1700, 'time_left_s': 100}, 0.1))
        self.assertFalse(v.in_last_part('guess', {'final_answer_at_s': 900, 'time_left_s': 900}, 0.1))

    def test_unanswered_time_pressure_counts(self):
        self.assertTrue(v.in_last_part('time_pressure', {'final_answer_at_s': None}, 0.1))
        self.assertFalse(v.in_last_part('guess', {}, 0.1))


LATE = {'final_answer_at_s': 1750, 'time_left_s': 50, 'ended_late': True}
TIMED = {'ended_late': False, 'final_answer_at_s': 100, 'time_left_s': 1700}


class PatternTests(SimpleTestCase):
    def attempts(self, *answer_lists):
        return [{'answers': answers} for answers in answer_lists]

    def test_rushes_end_needs_3_of_last_5_timed_attempts(self):
        rushed = [row('time_pressure', metrics=LATE), row('correct', metrics=TIMED)]
        calm = [row('correct', metrics=TIMED)]
        patterns = v.detect_patterns(self.attempts(rushed, calm, rushed, rushed, calm))
        found = {p['code']: p for p in patterns}
        self.assertIn('rushes_end', found)
        self.assertEqual(found['rushes_end']['count'], 3)
        self.assertEqual(found['rushes_end']['message'], 'Rushes the last part of tests')

    def test_rushes_end_ignores_untimed_attempts(self):
        untimed = [row('guess', metrics={'final_answer_at_s': 10})]
        rushed = [row('time_pressure', metrics=LATE)]
        patterns = v.detect_patterns(self.attempts(rushed, rushed, untimed, untimed, untimed))
        self.assertNotIn('rushes_end', [p['code'] for p in patterns])

    def test_slips_concentrated_in_one_topic(self):
        answers = ([row('careless_slip', id=f'k{i}', topic='Kinematics') for i in range(3)]
                   + [row('careless_slip', id='o1', topic='Optics')])
        patterns = v.detect_patterns(self.attempts(answers))
        slip = next(p for p in patterns if p['code'] == 'slips_in_topic')
        self.assertEqual(slip['topic'], 'Kinematics')
        self.assertEqual(slip['count'], 3)
        self.assertEqual(slip['message'], 'Careless slips mostly in Kinematics')
        self.assertEqual(sorted(slip['answer_ids']), ['k0', 'k1', 'k2'])

    def test_slips_spread_out_do_not_fire(self):
        answers = ([row('careless_slip', id=f'k{i}', topic='Kinematics') for i in range(3)]
                   + [row('careless_slip', id=f'o{i}', topic='Optics') for i in range(4)])
        codes = [p['code'] for p in v.detect_patterns(self.attempts(answers))]
        self.assertIn('slips_in_topic', codes)   # Optics: 4 of 7 = 57 %
        answers = ([row('careless_slip', id=f'k{i}', topic='Kinematics') for i in range(3)]
                   + [row('careless_slip', id=f'o{i}', topic='Optics') for i in range(3)]
                   + [row('careless_slip', id='w1', topic='Waves')])
        codes = [p['code'] for p in v.detect_patterns(self.attempts(answers))]
        self.assertNotIn('slips_in_topic', codes)  # top topic 3 of 7 = 43 %

    def test_changes_right_to_wrong(self):
        answers = [row('second_guess', id=f's{i}') for i in range(3)]
        patterns = v.detect_patterns(self.attempts(answers))
        self.assertEqual([p['code'] for p in patterns], ['changes_right_to_wrong'])

    def test_guesses_often_needs_20_answers(self):
        answers = [row('guess', id=f'g{i}') for i in range(5)] + [row('correct', id=f'c{i}') for i in range(14)]
        self.assertEqual(v.detect_patterns(self.attempts(answers)), [])  # 19 answers
        answers.append(row('correct', id='c14'))
        patterns = v.detect_patterns(self.attempts(answers))
        self.assertEqual([p['code'] for p in patterns], ['guesses_often'])  # 5/20 = 25 %

    def test_only_the_last_10_attempts_count(self):
        guessy = [row('guess', id='g')] * 3
        attempts = self.attempts(*([[row('correct')]] * 10 + [guessy] * 10))
        self.assertEqual(v.detect_patterns(attempts), [])


class EvidenceTests(SimpleTestCase):
    def test_sentences_use_metrics(self):
        sentences = v.describe_evidence(
            [{'code': 'too_fast', 'detail': '3s on screen; usually 45s'},
             {'code': 'right_to_wrong', 'detail': ''},
             {'code': 'prior_mastery', 'detail': '0.82 (high)'}],
            {'active_s': 3.2, 'usual_s': 45.0, 'prior_mastery': 0.82},
        )
        self.assertEqual(sentences, [
            'Answered in 3 s; usual is 45 s.',
            'Changed a correct answer to a wrong one.',
            'Mastery before this test: 82% (high confidence).',
        ])

    def test_unknown_code_falls_back_to_detail(self):
        self.assertEqual(
            v.describe_evidence([{'code': 'new_rule', 'detail': 'something odd'}], {}),
            ['Something odd.'])

    def test_missing_metric_falls_back_to_detail(self):
        self.assertEqual(
            v.describe_evidence([{'code': 'too_long', 'detail': '300s on screen; usually 60s'}], {}),
            ['300s on screen; usually 60s.'])

    def test_bad_items_are_skipped(self):
        self.assertEqual(v.describe_evidence(['x', {'code': 'other'}], None), [])


class StudentNoteTests(SimpleTestCase):
    def test_note_with_active_seconds(self):
        self.assertEqual(
            v.student_note('guess', 'high', {'active_s': 4.4}),
            'Looks like a quick guess — you spent 4s here.')

    def test_low_confidence_is_hidden(self):
        self.assertIsNone(v.student_note('guess', 'low', {'active_s': 4}))

    def test_silent_labels(self):
        for label in ('correct', 'skipped', 'not_seen', 'unclear'):
            self.assertIsNone(v.student_note(label, 'high', {}))

    def test_note_needing_seconds_without_them_is_hidden(self):
        self.assertIsNone(v.student_note('correct_slow', 'medium', {}))

    def test_plain_note(self):
        self.assertEqual(v.student_note('time_pressure', 'medium', {}), 'You ran short of time here.')


class RatesTests(SimpleTestCase):
    def test_rates(self):
        rates = v.behaviour_rates(['guess', 'careless_slip', 'correct', 'correct'])
        self.assertEqual(rates, {'answers': 4, 'guess': 0.25, 'careless_slip': 0.25,
                                 'time_pressure': 0.0})
        self.assertEqual(v.behaviour_rates([]), {'answers': 0, 'guess': None,
                                                 'careless_slip': None, 'time_pressure': None})

    def test_students_to_check(self):
        per_student = {
            'a': ['careless_slip'] * 5 + ['correct'] * 10,   # 33 % slips
            'b': ['time_pressure'] * 9 + ['correct'] * 6,    # 60 % time pressure
            'c': ['careless_slip'] * 14,                     # 14 answers: too few
            'd': ['correct'] * 15,                           # nothing to check
        }
        rows = v.students_to_check(per_student)
        self.assertEqual([r['student_id'] for r in rows], ['b', 'a'])
        self.assertEqual(rows[0]['time_pressure'], 0.6)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_visibility_rules -v 2`
Expected: ImportError (`cannot import name 'visibility'`).

- [ ] **Step 3: Write the config**

Create `backend/intelligence/visibility_config.py`:

```python
"""Diagnosis-visibility knobs (spec 2B §4): question flags, student patterns,
course-tile windows, page sizes and the plain-language notes students see.

Nothing stored depends on these values: changing one only changes what the
next request shows. No version bump, no recompute.
"""

# ── Assessment panel: question flags ─────────────────────────────────────────
MIN_FLAG_ANSWERS = 8            # diagnosed answers on a question before any flag
QUESTION_FLAGS = [
    # (code, labels counted, fires at or above this share, message)
    ('many_guesses', ('guess', 'correct_lucky'), 0.35, 'May be too hard or unclear.'),
    ('many_second_guesses_or_slips', ('second_guess', 'careless_slip'), 0.25,
     'Check the wording or the answer key.'),
    ('time_crunch', ('time_pressure', 'not_seen'), 0.30,
     'Most students ran out of time before this.'),
]
BEHAVIOUR_MAX_ATTEMPTS = 500    # newest finished attempts read per assessment

# ── Student Answers tab: patterns over recent attempts ──────────────────────
ANSWERS_PAGE_SIZE = 20          # attempts per page
PATTERN_ATTEMPTS = 10           # patterns look at the newest N attempts
RUSHES_END = {
    'labels': ('time_pressure', 'guess'),
    'last_share': 0.10,         # "the last 10% of the test"
    'timed_attempts': 5,        # among the newest 5 timed attempts…
    'min_attempts': 3,          # …at least 3 show it
}
SLIPS_IN_TOPIC = {'min_slips': 3, 'min_share': 0.5}
CHANGES_RIGHT_TO_WRONG = {'min_count': 3}
GUESSES_OFTEN = {'min_share': 0.25, 'min_answers': 20}
PATTERN_MESSAGES = {
    'rushes_end': 'Rushes the last part of tests',
    'slips_in_topic': 'Careless slips mostly in {topic}',
    'changes_right_to_wrong': 'Changes right answers to wrong ones',
    'guesses_often': 'Guesses often',
}

# ── Insights home: course answer-behaviour tile ─────────────────────────────
COURSE_TILE_DAYS = 28
COURSE_TILE_WEEKS = 4
STUDENTS_TO_CHECK = {'top': 5, 'min_answers': 15}
RECENT_ASSESSMENTS = 5

# ── Students: notes on review pages (spec §4.2) ─────────────────────────────
# Only these diagnosis confidences are shown to students; for anything else
# the student sees just the "Not quite? Tell us what happened." row.
STUDENT_NOTE_CONFIDENCE = {'medium', 'high'}
# {active} is the seconds the question was on screen, rounded. Labels not
# listed here (correct, skipped, not_seen, unclear) show no note.
STUDENT_NOTES = {
    'guess': 'Looks like a quick guess — you spent {active}s here.',
    'correct_lucky': "Correct, but quickly — worth checking you're sure.",
    'correct_slow': 'Correct — took longer than usual ({active}s).',
    'second_guess': 'You changed this answer — your first choice was right.',
    'careless_slip': 'You usually get this kind of question right — possibly a slip.',
    'time_pressure': 'You ran short of time here.',
    'concept_gap': 'This one needs more practice — see My Progress.',
}
```

- [ ] **Step 4: Write the rules**

Create `backend/intelligence/services/visibility.py`:

```python
"""Diagnosis visibility rules (pure functions, spec 2B §4).

No database: views gather ResponseDiagnosis rows into plain dicts and these
functions turn them into distributions, flags, patterns, sentences and notes.
Thresholds and wording live in ``intelligence/visibility_config.py``.
"""
import re
from collections import Counter, defaultdict
from statistics import median as _median

from intelligence import visibility_config as C

LABELS = (
    'correct', 'correct_lucky', 'correct_slow', 'guess', 'second_guess',
    'careless_slip', 'time_pressure', 'concept_gap', 'skipped', 'not_seen', 'unclear',
)
RATE_LABELS = ('guess', 'careless_slip', 'time_pressure')


def median(values):
    present = [value for value in values if value is not None]
    return _median(present) if present else None


def _share(part, total):
    return round(part / total, 3) if total else 0.0


def label_distribution(labels):
    """Counts and shares of every final label (missing labels count 0)."""
    counts = Counter(labels)
    total = sum(counts.values())
    return {
        'total': total,
        'counts': {label: counts.get(label, 0) for label in LABELS},
        'shares': {label: _share(counts.get(label, 0), total) for label in LABELS},
    }


def question_flags(distribution):
    """Question flags for one item, in QUESTION_FLAGS order."""
    total = distribution['total']
    if total < C.MIN_FLAG_ANSWERS:
        return []
    flags = []
    for code, labels, threshold, message in C.QUESTION_FLAGS:
        share = sum(distribution['counts'][label] for label in labels) / total
        if share >= threshold:
            flags.append({'code': code, 'message': message, 'share': round(share, 3)})
    return flags


def in_last_part(label, metrics, share):
    """Did this answer happen in the last ``share`` of a timed window?

    Answered items: from the answer time and the time left. Unanswered
    ``time_pressure`` items always count — that label only fires at the end.
    """
    metrics = metrics or {}
    at, left = metrics.get('final_answer_at_s'), metrics.get('time_left_s')
    if at is not None and left is not None:
        duration = at + left
        return duration > 0 and left <= share * duration
    return label == 'time_pressure'


def _timed(answers):
    return any('ended_late' in (row.get('metrics') or {}) for row in answers)


def _rushes_end(attempts):
    rule = C.RUSHES_END
    timed = [attempt for attempt in attempts if _timed(attempt['answers'])]
    hits = []
    for attempt in timed[:rule['timed_attempts']]:
        rushed = [
            row['id'] for row in attempt['answers']
            if row['label'] in rule['labels']
            and in_last_part(row['label'], row.get('metrics'), rule['last_share'])
        ]
        if rushed:
            hits.append(rushed)
    if len(hits) < rule['min_attempts']:
        return None
    return {'code': 'rushes_end', 'message': C.PATTERN_MESSAGES['rushes_end'],
            'count': len(hits), 'answer_ids': [i for ids in hits for i in ids]}


def _slips_in_topic(rows):
    rule = C.SLIPS_IN_TOPIC
    slips = [row for row in rows if row['label'] == 'careless_slip']
    by_topic = defaultdict(list)
    for row in slips:
        if row.get('topic'):
            by_topic[row['topic']].append(row['id'])
    if not by_topic:
        return None
    topic, ids = max(by_topic.items(), key=lambda pair: (len(pair[1]), pair[0]))
    if len(ids) < rule['min_slips'] or len(ids) / len(slips) < rule['min_share']:
        return None
    return {'code': 'slips_in_topic', 'topic': topic,
            'message': C.PATTERN_MESSAGES['slips_in_topic'].format(topic=topic),
            'count': len(ids), 'answer_ids': ids}


def _changes_right_to_wrong(rows):
    ids = [row['id'] for row in rows
           if row['label'] == 'second_guess' and not row.get('is_correct')]
    if len(ids) < C.CHANGES_RIGHT_TO_WRONG['min_count']:
        return None
    return {'code': 'changes_right_to_wrong',
            'message': C.PATTERN_MESSAGES['changes_right_to_wrong'],
            'count': len(ids), 'answer_ids': ids}


def _guesses_often(rows):
    rule = C.GUESSES_OFTEN
    answered = [row for row in rows if row.get('answered')]
    ids = [row['id'] for row in answered if row['label'] == 'guess']
    if len(answered) < rule['min_answers'] or len(ids) / len(answered) < rule['min_share']:
        return None
    return {'code': 'guesses_often', 'message': C.PATTERN_MESSAGES['guesses_often'],
            'count': len(ids), 'answer_ids': ids}


def detect_patterns(attempts):
    """Patterns over the newest ``PATTERN_ATTEMPTS`` attempts (newest first)."""
    window = attempts[:C.PATTERN_ATTEMPTS]
    rows = [row for attempt in window for row in attempt['answers']]
    found = [
        _rushes_end(window), _slips_in_topic(rows),
        _changes_right_to_wrong(rows), _guesses_often(rows),
    ]
    return [pattern for pattern in found if pattern]


# ── Evidence sentences (teachers) ────────────────────────────────────────────

def _secs(value):
    return f'{round(value)} s'


def _pct(value):
    return f'{round(value * 100)}%'


def _confidence_suffix(detail):
    match = re.search(r'\((low|medium|high)\)', detail or '')
    return f' ({match.group(1)} confidence)' if match else ''


def _sentence(code, detail, m):
    """One sentence for one evidence item, or None to fall back to detail."""
    active, usual = m.get('active_s'), m.get('usual_s')
    if code == 'too_fast' and active is not None and usual:
        return f'Answered in {_secs(active)}; usual is {_secs(usual)}.'
    if code == 'too_long' and active is not None and usual:
        return f'Spent {_secs(active)} on it; usual is {_secs(usual)}.'
    if code == 'last_minute' and m.get('time_left_s') is not None:
        return f"Answered with {_secs(m['time_left_s'])} left."
    if code == 'rushed' and m.get('rel_speed') is not None:
        return f"Took {_pct(m['rel_speed'])} of the usual time, near the end."
    if code == 'right_to_wrong':
        return 'Changed a correct answer to a wrong one.'
    if code == 'wrong_to_right':
        return 'Fixed an earlier wrong answer.'
    if code == 'tab_hidden' and m.get('hidden_s') is not None:
        return f"The tab was hidden for {_secs(m['hidden_s'])}."
    if code == 'late_third':
        return 'Answered in the last third of the test.'
    if code == 'slip_match':
        return f'The wrong value is a common slip away from the answer ({detail}).'
    if code == 'misconception_pick':
        return 'Picked the same wrong option as on an earlier attempt.'
    if code == 'prior_mastery' and m.get('prior_mastery') is not None:
        return (f"Mastery before this test: {_pct(m['prior_mastery'])}"
                f'{_confidence_suffix(detail)}.')
    if code == 'no_timeline':
        return 'No timing data was recorded for this answer.'
    return None


def describe_evidence(evidence, metrics):
    """Plain sentences for a diagnosis' evidence (teachers only).

    Unknown codes, or known codes whose metrics are missing, fall back to the
    stored ``detail``; items with neither are skipped.
    """
    metrics = metrics or {}
    sentences = []
    for item in evidence or []:
        if not isinstance(item, dict):
            continue
        detail = str(item.get('detail') or '').strip()
        sentence = _sentence(item.get('code'), detail, metrics)
        if sentence is None and detail:
            sentence = detail[0].upper() + detail[1:]
            if not sentence.endswith('.'):
                sentence += '.'
        if sentence:
            sentences.append(sentence)
    return sentences


# ── Student notes ────────────────────────────────────────────────────────────

def student_note(label, confidence, metrics):
    """The note a student sees for one answer, or None.

    Low-confidence diagnoses show nothing. A note that needs the on-screen
    seconds is dropped when they are unknown.
    """
    if confidence not in C.STUDENT_NOTE_CONFIDENCE:
        return None
    template = C.STUDENT_NOTES.get(label)
    if template is None:
        return None
    if '{active}' in template:
        active = (metrics or {}).get('active_s')
        if active is None:
            return None
        return template.format(active=round(active))
    return template


# ── Course tile ──────────────────────────────────────────────────────────────

def behaviour_rates(labels):
    """Guess, careless-slip and time-pressure shares of all diagnosed answers."""
    counts = Counter(labels)
    total = sum(counts.values())
    rates = {'answers': total}
    for label in RATE_LABELS:
        rates[label] = round(counts.get(label, 0) / total, 3) if total else None
    return rates


def students_to_check(per_student):
    """Top students by careless-slip or time-pressure rate (enough answers only)."""
    rule = C.STUDENTS_TO_CHECK
    rows = []
    for student_id, labels in per_student.items():
        if len(labels) < rule['min_answers']:
            continue
        rates = behaviour_rates(labels)
        worst = max(rates['careless_slip'], rates['time_pressure'])
        if worst <= 0:
            continue
        rows.append((worst, str(student_id), {
            'student_id': student_id, 'answers': rates['answers'],
            'careless_slip': rates['careless_slip'], 'time_pressure': rates['time_pressure'],
        }))
    rows.sort(key=lambda entry: (-entry[0], entry[1]))
    return [entry[2] for entry in rows[:rule['top']]]
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_visibility_rules -v 2`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/intelligence/visibility_config.py backend/intelligence/services/visibility.py backend/intelligence/tests/test_visibility_rules.py
git commit -m "feat(intelligence): pure rules for question flags, patterns, evidence and student notes"
```

---

### Task 4: Teacher endpoints — assessment behaviour and student answers

**Files:**
- Modify: `backend/intelligence/admin_views.py` (new permission, two views, shared loaders)
- Modify: `backend/intelligence/admin_urls.py`
- Test: `backend/intelligence/tests/test_visibility_api.py` (create; this task adds the first two classes)

**Interfaces:**
- Produces:
  - `GET /api/v1/tenant-admin/intelligence/assessments/<kind>/<uuid>/behaviour/` →
    `{'assessment': {id, title, kind}, 'labels': [...LABELS], 'answers': int, 'flagged': int, 'items': [{'item_key', 'question_text', 'distribution': {total, counts, shares}, 'median_active_s', 'usual_s', 'self_reports', 'flags': [...]}]}`;
  - `GET /api/v1/tenant-admin/intelligence/students/<uuid>/answers/?page=` →
    `{'student': {id, name}, 'page', 'pages', 'total_attempts', 'patterns': [...] (page 1 only, else []), 'attempts': [{'attempt_kind', 'attempt_id', 'title', 'completed_at', 'answers': [{'id', 'item_key', 'question_text', 'topic', 'label', 'label_display', 'confidence', 'is_correct', 'answered', 'active_s', 'evidence': [str], 'self_report'}]}]}`;
  - permission class `TeacherDiagnosisPermission` (feature `diagnosis_teacher_view`).
- Consumes: `access.*` (Task 2), `visibility.*` (Task 3).

- [ ] **Step 1: Write the failing test**

Create `backend/intelligence/tests/test_visibility_api.py`:

```python
"""Diagnosis-visibility endpoints: switches, scope and payloads."""
from intelligence.tests.visibility_fixtures import VisibilityTestCase

INSIGHTS = '/api/v1/tenant-admin/intelligence'


class AssessmentBehaviourTests(VisibilityTestCase):
    def url(self, quiz=None):
        return f'{INSIGHTS}/assessments/quiz/{(quiz or self.quiz).id}/behaviour/'

    def setUp(self):
        self.q1 = self.make_question(1)
        self.q2 = self.make_question(2)
        # 8 attempts on q1: 3 guesses (37.5 %) → many_guesses; q2 all correct.
        for n in range(8):
            attempt = self.quiz_attempt(self.student, minutes_ago=100 + n)
            label = 'guess' if n < 3 else 'correct'
            self.diagnose(attempt, self.q1, label,
                          metrics={'active_s': 10 + n, 'usual_s': 70.0},
                          self_report='guessed' if n == 0 else '')
            self.diagnose(attempt, self.q2, 'correct', metrics={'active_s': 30, 'usual_s': 70.0})

    def test_payload(self):
        response = self.client_for(self.faculty).get(self.url())
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual(data['answers'], 16)
        self.assertEqual(data['flagged'], 1)
        first = data['items'][0]
        self.assertEqual(first['item_key'], f'bank:{self.q1.id}')
        self.assertEqual(first['distribution']['counts']['guess'], 3)
        self.assertEqual(first['median_active_s'], 13.5)
        self.assertEqual(first['usual_s'], 70.0)
        self.assertEqual(first['self_reports'], 1)
        self.assertEqual([f['code'] for f in first['flags']], ['many_guesses'])
        self.assertEqual(data['items'][1]['flags'], [])

    def test_in_progress_attempts_are_ignored(self):
        attempt = self.quiz_attempt(self.student, status='in_progress')
        self.diagnose(attempt, self.q2, 'guess')
        self.assertEqual(self.client_for(self.admin).get(self.url()).json()['answers'], 16)

    def test_switch_off_is_403(self):
        self.tenant.features = {'response_diagnosis': True}
        self.tenant.save()
        self.assertEqual(self.client_for(self.admin).get(self.url()).status_code, 403)

    def test_requirement_off_is_403(self):
        self.tenant.features = {'diagnosis_teacher_view': True}
        self.tenant.save()
        self.assertEqual(self.client_for(self.admin).get(self.url()).status_code, 403)

    def test_scope(self):
        self.assertEqual(self.client_for(self.other_faculty).get(self.url()).status_code, 403)
        self.assertEqual(self.client_for(self.student_user).get(self.url()).status_code, 403)
        self.assertEqual(self.client_for(self.admin).get(self.url()).status_code, 200)

    def test_unknown_assessment_is_404(self):
        response = self.client_for(self.admin).get(
            f'{INSIGHTS}/assessments/quiz/{self.student.id}/behaviour/')
        self.assertEqual(response.status_code, 404)


class StudentAnswersTests(VisibilityTestCase):
    def url(self, student=None, page=None):
        base = f'{INSIGHTS}/students/{(student or self.student).id}/answers/'
        return f'{base}?page={page}' if page else base

    def setUp(self):
        self.question = self.make_question(1)
        # 22 attempts taken (and diagnosed) oldest first; the newest 3 are
        # second guesses. Attempts are listed in the order they were first
        # diagnosed, newest first.
        self.attempts = []
        for n in range(22):
            attempt = self.quiz_attempt(self.student, minutes_ago=200 - n)
            label = 'second_guess' if n >= 19 else 'correct'
            self.diagnose(
                attempt, self.question, label,
                metrics={'active_s': 12.0, 'usual_s': 45.0},
                evidence=[{'code': 'right_to_wrong', 'detail': ''}] if n >= 19 else [],
            )
            self.attempts.append(attempt)

    def test_first_page_has_20_attempts_and_patterns(self):
        response = self.client_for(self.faculty).get(self.url())
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual((data['page'], data['pages'], data['total_attempts']), (1, 2, 22))
        self.assertEqual(len(data['attempts']), 20)
        self.assertEqual(data['attempts'][0]['attempt_id'], str(self.attempts[-1].id))
        answer = data['attempts'][0]['answers'][0]
        self.assertEqual(answer['label'], 'second_guess')
        self.assertEqual(answer['label_display'], 'Changed a right answer')
        self.assertEqual(answer['evidence'], ['Changed a correct answer to a wrong one.'])
        self.assertEqual(answer['topic'], 'Kinematics')
        self.assertEqual([p['code'] for p in data['patterns']], ['changes_right_to_wrong'])

    def test_second_page_has_no_patterns(self):
        data = self.client_for(self.admin).get(self.url(page=2)).json()
        self.assertEqual(len(data['attempts']), 2)
        self.assertEqual(data['patterns'], [])

    def test_bad_page_falls_back_to_1(self):
        self.assertEqual(self.client_for(self.admin).get(self.url(page='x')).json()['page'], 1)

    def test_scope(self):
        self.assertEqual(self.client_for(self.faculty).get(self.url(self.outsider)).status_code, 403)
        self.assertEqual(self.client_for(self.other_faculty).get(self.url()).status_code, 403)
        self.assertEqual(self.client_for(self.student_user).get(self.url()).status_code, 403)

    def test_switch_off_is_403(self):
        self.tenant.features = {'response_diagnosis': True}
        self.tenant.save()
        self.assertEqual(self.client_for(self.admin).get(self.url()).status_code, 403)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_visibility_api -v 2`
Expected: FAIL (404 for the unknown routes).

- [ ] **Step 3: Implement the views**

In `backend/intelligence/admin_views.py`:

1. Extend the imports:

```python
from django.db.models import Avg, Count, F, Min, Q

from . import visibility_config as VC
from .access import diagnosis_scope_q
from .services import visibility
```

(Merge `F` and `Min` into the existing `django.db.models` import line; merge `diagnosis_scope_q` into the `.access` import from Task 2.)

2. Below `IsTenantAdminOrInstructor`, add:

```python
class TeacherDiagnosisPermission(permissions.BasePermission):
    """The tenant must have the diagnosis teacher view on (which needs
    Answer Diagnosis; ``get_features`` folds that in)."""

    message = 'The diagnosis teacher view is not enabled for this academy.'

    def has_permission(self, request, view):
        tenant = getattr(request, 'tenant', None)
        return bool(tenant and tenant.get_features().get('diagnosis_teacher_view'))


TEACHER_DIAGNOSIS = [
    permissions.IsAuthenticated, IsTenantAdminOrInstructor, TeacherDiagnosisPermission,
]
LABEL_DISPLAY = dict(ResponseDiagnosis.LABEL_CHOICES)


def _load_assessment(request, kind, assessment_id):
    from quiz.models import MockTest, Quiz

    model = {'quiz': Quiz, 'mock': MockTest}.get(kind)
    if model is None:
        return None
    return model.objects.filter(id=assessment_id, tenant=request.tenant).first()


def _finished_attempt_ids(kind, assessment, limit):
    """Ids of the newest ``limit`` finished attempts on an assessment."""
    from quiz.models import MockTestAttempt, QuizAttempt

    if kind == 'quiz':
        attempts = QuizAttempt.objects.filter(quiz=assessment)
    else:
        attempts = MockTestAttempt.objects.filter(mock_test=assessment)
    # nulls_last: on Postgres a plain '-completed_at' puts abandoned attempts
    # with no completed_at first and can crowd real ones out of the cap.
    return list(
        attempts.exclude(status='in_progress')
        .order_by(F('completed_at').desc(nulls_last=True))
        .values_list('id', flat=True)[:limit]
    )


def _assessment_items(kind, assessment):
    """[(item_key, question_text)] in paper order: bank questions, then a
    mock's inline items."""
    from quiz.models import MockTestItem, MockTestQuestion

    # QuizQuestion / MockTestQuestion declare their own Meta and so have no
    # default ordering: order explicitly, or Postgres returns any order.
    if kind == 'quiz':
        rows = [(f'bank:{qq.question_id}', qq.question.question_text)
                for qq in assessment.quizquestion_set.select_related('question')
                .order_by('order', 'created_at')]
    else:
        rows = [(f'bank:{mtq.question_id}', mtq.question.question_text)
                for mtq in MockTestQuestion.objects.filter(mock_test=assessment)
                .select_related('question').order_by('section', 'order', 'created_at')]
        rows += [(f'item:{item.id}', item.question_text)
                 for item in MockTestItem.objects.filter(mock_test=assessment)]
    return [(key, (text or '')[:200]) for key, text in rows]


def _item_key(question_id, mock_item_id):
    return f'bank:{question_id}' if question_id else f'item:{mock_item_id}'
```

3. Add the two views (after `StudentDiagnosisView`):

```python
class AssessmentBehaviourView(APIView):
    """Per-question answer behaviour for one quiz or mock (spec 2B §4.1.1)."""

    permission_classes = TEACHER_DIAGNOSIS

    def get(self, request, kind, assessment_id):
        assessment = _load_assessment(request, kind, assessment_id)
        if assessment is None:
            return Response({'error': 'Assessment not found.'}, status=status.HTTP_404_NOT_FOUND)
        if not assessment_in_scope(request.user, kind, assessment):
            return _forbidden()

        attempt_ids = _finished_attempt_ids(kind, assessment, VC.BEHAVIOUR_MAX_ATTEMPTS)
        grouped = defaultdict(list)
        for question_id, mock_item_id, label, metrics, report in (
            ResponseDiagnosis.objects.filter(attempt_kind=kind, attempt_id__in=attempt_ids)
            .values_list('question_id', 'mock_item_id', 'final_label', 'metrics', 'self_report')
            .iterator()
        ):
            grouped[_item_key(question_id, mock_item_id)].append((label, metrics or {}, report))

        items = []
        for key, text in _assessment_items(kind, assessment):
            rows = grouped.get(key, [])
            distribution = visibility.label_distribution([label for label, _m, _r in rows])
            items.append({
                'item_key': key,
                'question_text': text,
                'distribution': distribution,
                'median_active_s': visibility.median([m.get('active_s') for _l, m, _r in rows]),
                'usual_s': visibility.median([m.get('usual_s') for _l, m, _r in rows]),
                'self_reports': sum(1 for _l, _m, report in rows if report),
                'flags': visibility.question_flags(distribution),
            })
        return Response({
            'assessment': {'id': str(assessment.id), 'title': assessment.title, 'kind': kind},
            'labels': list(visibility.LABELS),
            'answers': sum(item['distribution']['total'] for item in items),
            'flagged': sum(1 for item in items if item['flags']),
            'items': items,
        })


def _attempt_titles(pairs):
    """{(kind, attempt_id): (title, completed_at)} for quiz/mock/practice attempts."""
    from quiz.models import MockTestAttempt, QuizAttempt

    from .models import PracticeSet

    ids = defaultdict(list)
    for kind, attempt_id in pairs:
        ids[kind].append(attempt_id)
    titles = {}
    for attempt in QuizAttempt.objects.filter(id__in=ids['quiz']).select_related('quiz'):
        titles[('quiz', attempt.id)] = (attempt.quiz.title, attempt.completed_at)
    for attempt in MockTestAttempt.objects.filter(id__in=ids['mock']).select_related('mock_test'):
        titles[('mock', attempt.id)] = (attempt.mock_test.title, attempt.completed_at)
    for practice_set in PracticeSet.objects.filter(id__in=ids['practice']):
        titles[('practice', practice_set.id)] = ('Practice set', practice_set.completed_at)
    return titles


def _answer_rows(student, pairs):
    """Diagnosis rows of the given attempts, as dicts, grouped per attempt."""
    if not pairs:
        return {}
    match = Q()
    for kind, attempt_id in pairs:
        match |= Q(attempt_kind=kind, attempt_id=attempt_id)
    grouped = defaultdict(list)
    rows = (
        ResponseDiagnosis.objects.filter(student=student).filter(match)
        .select_related('question__topic', 'mock_item__topic')
        .order_by('created_at', 'id')
    )
    for row in rows:
        item = row.question or row.mock_item
        topic = getattr(item, 'topic', None) if item else None
        grouped[(row.attempt_kind, row.attempt_id)].append({
            'id': str(row.id),
            'item_key': _item_key(row.question_id, row.mock_item_id),
            'question_text': ((item.question_text if item else '') or '')[:200],
            'topic': topic.name if topic else None,
            'label': row.final_label,
            'label_display': LABEL_DISPLAY.get(row.final_label, row.final_label),
            'confidence': row.confidence,
            'is_correct': row.is_correct,
            'answered': row.answered,
            'active_s': (row.metrics or {}).get('active_s'),
            'metrics': row.metrics or {},
            'evidence': visibility.describe_evidence(row.evidence, row.metrics),
            'self_report': row.self_report,
        })
    return grouped


class StudentAnswersView(APIView):
    """One student's diagnosed answers, newest attempt first, with patterns
    over the newest attempts (spec 2B §4.1.2)."""

    permission_classes = TEACHER_DIAGNOSIS

    def get(self, request, student_id):
        from users.models import StudentProfile

        student = StudentProfile.objects.filter(
            id=student_id, user__tenant=request.tenant,
        ).select_related('user').first()
        if student is None:
            return Response({'error': 'Student not found.'}, status=status.HTTP_404_NOT_FOUND)
        if not can_view_student(request.user, student):
            return _forbidden()

        try:
            page = max(1, int(request.query_params.get('page', 1)))
        except (TypeError, ValueError):
            page = 1
        attempts = (
            ResponseDiagnosis.objects.filter(student=student)
            .filter(diagnosis_scope_q(request.user, student))
            .values('attempt_kind', 'attempt_id')
            .annotate(first_seen=Min('created_at'))
            .order_by('-first_seen', 'attempt_id')
        )
        total = attempts.count()
        size = VC.ANSWERS_PAGE_SIZE
        pages = max(1, -(-total // size))
        page = min(page, pages)
        page_pairs = [(a['attempt_kind'], a['attempt_id'])
                      for a in attempts[(page - 1) * size:page * size]]
        rows = _answer_rows(student, page_pairs)
        titles = _attempt_titles(page_pairs)

        patterns = []
        if page == 1:
            window = page_pairs[:VC.PATTERN_ATTEMPTS]
            patterns = visibility.detect_patterns(
                [{'answers': rows.get(pair, [])} for pair in window])

        payload = []
        for pair in page_pairs:
            title, completed_at = titles.get(pair, ('Deleted attempt', None))
            payload.append({
                'attempt_kind': pair[0],
                'attempt_id': str(pair[1]),
                'title': title,
                'completed_at': completed_at.isoformat() if completed_at else None,
                'answers': [
                    {key: value for key, value in answer.items() if key != 'metrics'}
                    for answer in rows.get(pair, [])
                ],
            })
        return Response({
            'student': {
                'id': str(student.id),
                'name': getattr(student.user, 'full_name', '') or student.user.email,
            },
            'page': page,
            'pages': pages,
            'total_attempts': total,
            'patterns': patterns,
            'attempts': payload,
        })
```

4. In `backend/intelligence/admin_urls.py`, add `AssessmentBehaviourView` and `StudentAnswersView` to the import and these routes after the `report/` route:

```python
    path('assessments/<str:kind>/<uuid:assessment_id>/behaviour/',
         AssessmentBehaviourView.as_view(), name='intelligence-assessment-behaviour'),
    path('students/<uuid:student_id>/answers/', StudentAnswersView.as_view(),
         name='intelligence-student-answers'),
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_visibility_api intelligence.tests.test_access -v 2`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/intelligence/admin_views.py backend/intelligence/admin_urls.py backend/intelligence/tests/test_visibility_api.py
git commit -m "feat(intelligence): assessment answer behaviour and student Answers endpoints"
```

---

### Task 5: Course behaviour, calibration and the student notes endpoint

**Files:**
- Modify: `backend/intelligence/admin_views.py` (`CourseBehaviourView`; `DiagnosisCalibrationView` permission and two keys)
- Modify: `backend/intelligence/admin_urls.py`
- Modify: `backend/intelligence/views.py` (`StudentDiagnosisFeaturePermission`, `MyAttemptDiagnosisView`)
- Modify: `backend/intelligence/urls.py`
- Run (unchanged): `backend/intelligence/tests/test_self_report.py` (its calibration tests use only admin and student callers, so admin-only keeps them green)
- Test: `backend/intelligence/tests/test_visibility_api.py` (add three classes)

**Interfaces:**
- Produces:
  - `GET /api/v1/tenant-admin/intelligence/courses/<uuid>/behaviour/` →
    `{'course': {id, name}, 'days': 28, 'rates': {answers, guess, careless_slip, time_pressure}, 'trend': [{'week_start': 'YYYY-MM-DD', ...rates}] (4 points, oldest first), 'students_to_check': [{student_id, name, answers, careless_slip, time_pressure}], 'recent_assessments': [{kind, id, title, completed_at}]}`;
  - `GET /api/v1/tenant-admin/intelligence/diagnosis/calibration/` — admin only; adds `thresholds` (the `THRESHOLDS` dict) and `classifier_version`;
  - `GET /api/v1/intelligence/my/attempts/<kind>/<uuid>/diagnosis/` → `{'notes': {'bank:<id>' | 'item:<id>': 'note text'}}` (feature `diagnosis_student_view`; own finished quiz/mock attempt only; 404 otherwise).

- [ ] **Step 1: Write the failing tests**

Append to `backend/intelligence/tests/test_visibility_api.py`:

```python
from datetime import timedelta

from django.utils import timezone

from intelligence.diagnosis_config import THRESHOLDS
from intelligence.versions import CLASSIFIER_VERSION


class CourseBehaviourTests(VisibilityTestCase):
    def url(self, course=None):
        return f'{INSIGHTS}/courses/{(course or self.course).id}/behaviour/'

    def setUp(self):
        question = self.make_question(1)
        # 16 answers this week for student: 4 slips (25 %), 12 correct.
        for n in range(16):
            attempt = self.quiz_attempt(self.student, minutes_ago=60 + n)
            self.diagnose(attempt, question, 'careless_slip' if n < 4 else 'correct')
        # 2 answers 20 days ago: one guess.
        for n, label in enumerate(['guess', 'correct']):
            attempt = self.quiz_attempt(self.student, minutes_ago=20 * 24 * 60 + n)
            self.diagnose(attempt, question, label)
        # Outside the 28-day window: ignored.
        old = self.quiz_attempt(self.student, minutes_ago=40 * 24 * 60)
        self.diagnose(old, question, 'guess')

    def test_payload(self):
        response = self.client_for(self.faculty).get(self.url())
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual(data['rates']['answers'], 18)
        self.assertEqual(data['rates']['careless_slip'], round(4 / 18, 3))
        self.assertEqual(data['rates']['guess'], round(1 / 18, 3))
        self.assertEqual(len(data['trend']), 4)
        self.assertEqual(data['trend'][-1]['answers'], 16)
        self.assertEqual(data['trend'][-1]['careless_slip'], 0.25)
        self.assertEqual(data['trend'][1]['answers'], 2)
        self.assertIsNone(data['trend'][0]['guess'])
        self.assertEqual(len(data['students_to_check']), 1)
        self.assertEqual(data['students_to_check'][0]['student_id'], str(self.student.id))
        self.assertEqual(data['recent_assessments'][0]['id'], str(self.quiz.id))

    def test_scope_and_switch(self):
        self.assertEqual(self.client_for(self.faculty).get(self.url(self.other_course)).status_code, 403)
        self.tenant.features = {'response_diagnosis': True}
        self.tenant.save()
        self.assertEqual(self.client_for(self.admin).get(self.url()).status_code, 403)


class CalibrationTests(VisibilityTestCase):
    URL = f'{INSIGHTS}/diagnosis/calibration/'

    def test_admin_only(self):
        self.assertEqual(self.client_for(self.faculty).get(self.URL).status_code, 403)
        response = self.client_for(self.admin).get(self.URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['classifier_version'], CLASSIFIER_VERSION)
        self.assertEqual(response.json()['thresholds'], THRESHOLDS)


class MyAttemptDiagnosisTests(VisibilityTestCase):
    def setUp(self):
        self.q1 = self.make_question(1)
        self.q2 = self.make_question(2)
        self.q3 = self.make_question(3)
        self.attempt = self.quiz_attempt(self.student)
        self.diagnose(self.attempt, self.q1, 'guess', metrics={'active_s': 3.6})
        self.diagnose(self.attempt, self.q2, 'careless_slip', confidence='low')
        self.diagnose(self.attempt, self.q3, 'correct')

    def url(self, attempt=None, kind='quiz'):
        return f'/api/v1/intelligence/my/attempts/{kind}/{(attempt or self.attempt).id}/diagnosis/'

    def test_notes_are_medium_or_high_only(self):
        response = self.client_for(self.student_user).get(self.url())
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json(), {
            'notes': {f'bank:{self.q1.id}': 'Looks like a quick guess — you spent 4s here.'},
        })

    def test_payload_never_carries_a_label(self):
        body = self.client_for(self.student_user).get(self.url()).content.decode()
        self.assertNotIn('guess"', body)
        self.assertNotIn('careless_slip', body)

    def test_other_students_attempt_is_404(self):
        self.assertEqual(self.client_for(self.outsider_user).get(self.url()).status_code, 404)

    def test_in_progress_attempt_is_404(self):
        attempt = self.quiz_attempt(self.student, status='in_progress')
        self.assertEqual(self.client_for(self.student_user).get(self.url(attempt)).status_code, 404)

    def test_unknown_kind_is_404(self):
        self.assertEqual(
            self.client_for(self.student_user).get(self.url(kind='exam')).status_code, 404)

    def test_switch_off_is_403(self):
        self.tenant.features = {'response_diagnosis': True}
        self.tenant.save()
        self.assertEqual(self.client_for(self.student_user).get(self.url()).status_code, 403)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_visibility_api -v 2`
Expected: the three new classes FAIL (404 routes; calibration 200 for faculty).

- [ ] **Step 3: Implement**

In `backend/intelligence/admin_views.py`:

1. Add after `StudentAnswersView`:

```python
class CourseBehaviourView(APIView):
    """Answer-behaviour tile for one course (spec 2B §4.1.3): guess, slip and
    time-pressure rates over the last 28 days, a weekly trend, and the
    students most worth checking."""

    permission_classes = TEACHER_DIAGNOSIS

    def get(self, request, course_id):
        from quiz.models import MockTestAttempt, QuizAttempt
        from users.models import StudentProfile

        from .models import PracticeSet

        course = _course_or_404(request, course_id)
        if course is None:
            return Response({'error': 'Course not found.'}, status=status.HTTP_404_NOT_FOUND)
        if not can_manage_course(request.user, course):
            return _forbidden()

        now = timezone.now()
        since = now - timedelta(days=VC.COURSE_TILE_DAYS)
        completed = {}     # (kind, attempt_id) → completed_at
        assessments = {}   # (kind, assessment_id) → (title, latest completed_at)

        def collect(kind, rows):
            for attempt_id, done, assessment_id, title in rows:
                completed[(kind, attempt_id)] = done
                if assessment_id is None:
                    continue
                key = (kind, assessment_id)
                if key not in assessments or assessments[key][1] < done:
                    assessments[key] = (title, done)

        collect('quiz', QuizAttempt.objects.filter(
            quiz__course=course, completed_at__gte=since,
        ).values_list('id', 'completed_at', 'quiz_id', 'quiz__title'))
        collect('mock', MockTestAttempt.objects.filter(
            Q(mock_test__course=course) | Q(mock_test__courses=course),
            completed_at__gte=since,
        ).distinct().values_list('id', 'completed_at', 'mock_test_id', 'mock_test__title'))
        collect('practice', [
            (row_id, done, None, '')
            for row_id, done in PracticeSet.objects.filter(
                course=course, completed_at__gte=since,
            ).values_list('id', 'completed_at')
        ])

        ids_by_kind = defaultdict(list)
        for kind, attempt_id in completed:
            ids_by_kind[kind].append(attempt_id)
        match = Q(pk__in=[])
        for kind, ids in ids_by_kind.items():
            match |= Q(attempt_kind=kind, attempt_id__in=ids)
        rows = list(
            ResponseDiagnosis.objects.filter(tenant=request.tenant).filter(match)
            .values_list('attempt_kind', 'attempt_id', 'student_id', 'final_label')
        )

        weeks = [[] for _ in range(VC.COURSE_TILE_WEEKS)]
        per_student = defaultdict(list)
        for kind, attempt_id, student_id, label in rows:
            per_student[student_id].append(label)
            age_days = (now - completed[(kind, attempt_id)]).days
            index = VC.COURSE_TILE_WEEKS - 1 - min(age_days // 7, VC.COURSE_TILE_WEEKS - 1)
            weeks[index].append(label)

        trend = []
        for index, labels in enumerate(weeks):
            start = now - timedelta(days=7 * (VC.COURSE_TILE_WEEKS - index))
            trend.append({'week_start': start.date().isoformat(),
                          **visibility.behaviour_rates(labels)})

        check = visibility.students_to_check(per_student)
        names = {
            profile.id: (getattr(profile.user, 'full_name', '') or profile.user.email)
            for profile in StudentProfile.objects.filter(
                id__in=[row['student_id'] for row in check]).select_related('user')
        }
        recent = sorted(assessments.items(), key=lambda pair: pair[1][1], reverse=True)
        return Response({
            'course': {'id': str(course.id), 'name': course.name},
            'days': VC.COURSE_TILE_DAYS,
            'rates': visibility.behaviour_rates([row[3] for row in rows]),
            'trend': trend,
            'students_to_check': [
                {**row, 'student_id': str(row['student_id']), 'name': names.get(row['student_id'], '')}
                for row in check
            ],
            'recent_assessments': [
                {'kind': kind, 'id': str(assessment_id), 'title': title,
                 'completed_at': done.isoformat()}
                for (kind, assessment_id), (title, done) in recent[:VC.RECENT_ASSESSMENTS]
            ],
        })
```

2. In `DiagnosisCalibrationView`: replace its `permission_classes` with

```python
    permission_classes = [permissions.IsAuthenticated, IsTenantAdmin]
```

(import `IsTenantAdmin` from `core.permissions` at the top of the file), and extend the response dict with:

```python
            'thresholds': THRESHOLDS,
            'classifier_version': CLASSIFIER_VERSION,
```

importing inside `get` alongside `SELF_REPORT_LABEL`:

```python
        from .diagnosis_config import SELF_REPORT_LABEL, THRESHOLDS
        from .versions import CLASSIFIER_VERSION
```

Update its docstring's last line to: `Admin only. Also reports the thresholds and classifier version in use.`

3. In `backend/intelligence/admin_urls.py`, import `CourseBehaviourView` and add:

```python
    path('courses/<uuid:course_id>/behaviour/', CourseBehaviourView.as_view(),
         name='intelligence-course-behaviour'),
```

4. In `backend/intelligence/views.py`, add after `SelfReportView`:

```python
class StudentDiagnosisFeaturePermission(permissions.BasePermission):
    """The tenant must have the diagnosis student view on (which needs
    Answer Diagnosis; ``get_features`` folds that in)."""

    message = 'Answer notes are not enabled for this academy.'

    def has_permission(self, request, view):
        tenant = getattr(request, 'tenant', None)
        return bool(tenant and tenant.get_features().get('diagnosis_student_view'))


class MyAttemptDiagnosisView(APIView):
    """One-line notes for the student's own finished attempt (spec 2B §4.2).

    Only note text leaves the server — never a label — and only for
    medium- and high-confidence diagnoses.
    """

    permission_classes = [permissions.IsAuthenticated, StudentDiagnosisFeaturePermission]

    def get(self, request, kind, attempt_id):
        from .models import ResponseDiagnosis
        from .services.visibility import student_note

        attempt = _owned_finished_attempt(kind, str(attempt_id), _student_or_none(request))
        if attempt is None:
            return Response({'error': 'Attempt not found.'}, status=status.HTTP_404_NOT_FOUND)
        notes = {}
        for question_id, mock_item_id, label, confidence, metrics in (
            ResponseDiagnosis.objects.filter(attempt_kind=kind, attempt_id=attempt.id)
            .values_list('question_id', 'mock_item_id', 'final_label', 'confidence', 'metrics')
        ):
            note = student_note(label, confidence, metrics)
            if note:
                notes[_item_key(question_id, mock_item_id)] = note
        return Response({'notes': notes})
```

5. In `backend/intelligence/urls.py`, import `MyAttemptDiagnosisView` and add:

```python
    path('my/attempts/<str:kind>/<uuid:attempt_id>/diagnosis/', MyAttemptDiagnosisView.as_view(),
         name='intelligence-my-attempt-diagnosis'),
```

6. `backend/intelligence/tests/test_self_report.py` needs no change: its `CalibrationTests` call `CALIBRATION` only as an admin (expect 200) or as a student (expect 403), and both still hold with `IsTenantAdmin`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `venv/Scripts/python.exe manage.py test intelligence.tests.test_visibility_api intelligence.tests.test_self_report -v 2`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/intelligence/admin_views.py backend/intelligence/admin_urls.py backend/intelligence/views.py backend/intelligence/urls.py backend/intelligence/tests/test_visibility_api.py
git commit -m "feat(intelligence): course behaviour tile, admin-only calibration, student answer notes"
```

---

### Task 6: Opt-out regression for Part A

**Files:**
- Test: `backend/intelligence/tests/test_visibility_api.py` (add one class)

**Interfaces:**
- Consumes: every route from Tasks 4–5.

- [ ] **Step 1: Write the test**

Append to `backend/intelligence/tests/test_visibility_api.py`:

```python
class OptOutTests(VisibilityTestCase):
    """With every learning-layer switch off, no Part A endpoint is reachable
    and no diagnosis work is queued by reading them."""

    features = {}

    def test_every_new_endpoint_is_403(self):
        attempt = self.quiz_attempt(self.student)
        teacher_urls = [
            f'{INSIGHTS}/assessments/quiz/{self.quiz.id}/behaviour/',
            f'{INSIGHTS}/students/{self.student.id}/answers/',
            f'{INSIGHTS}/courses/{self.course.id}/behaviour/',
        ]
        for url in teacher_urls:
            self.assertEqual(self.client_for(self.admin).get(url).status_code, 403, url)
        student_url = f'/api/v1/intelligence/my/attempts/quiz/{attempt.id}/diagnosis/'
        self.assertEqual(self.client_for(self.student_user).get(student_url).status_code, 403)

    def test_features_payload_reports_view_switches_off(self):
        features = self.tenant.get_features()
        self.assertFalse(features['diagnosis_teacher_view'])
        self.assertFalse(features['diagnosis_student_view'])
```

- [ ] **Step 2: Run the whole intelligence suite**

Run: `venv/Scripts/python.exe manage.py test intelligence core quiz -v 1`
Expected: all PASS, including `test_gate` (PR #213's main-equivalence tests).

- [ ] **Step 3: Commit**

```bash
git add backend/intelligence/tests/test_visibility_api.py
git commit -m "test(intelligence): Part A endpoints are unreachable with the layer off"
```

---

### Task 7: Frontend — services, label palette, assessment panel

**Files:**
- Modify: `frontend/exam-frontend/src/services/insightsService.js`
- Create: `frontend/exam-frontend/src/services/diagnosisService.js`
- Create: `frontend/exam-frontend/src/components/insights/labels.js`
- Create: `frontend/exam-frontend/src/components/insights/LabelBar.jsx`
- Create: `frontend/exam-frontend/src/components/insights/AnswerBehaviourPanel.jsx`
- Modify: `frontend/exam-frontend/src/pages/AssessmentReport.jsx`

**Interfaces:**
- Produces:
  - `insightsService.getAssessmentBehaviour(kind, id)`, `getStudentAnswers(studentId, page)`, `getCourseBehaviour(courseId)`, `getCalibration(days)`;
  - `diagnosisService.getMyAttemptNotes(kind, attemptId)`;
  - `LABEL_TEXT`, `LABEL_COLOR` (Tailwind bg classes), `LABEL_ORDER` from `labels.js`;
  - `<LabelBar counts total />`.

- [ ] **Step 1: Services**

Append inside the `insightsService` object in `insightsService.js`:

```js
  getAssessmentBehaviour: async (kind, assessmentId) => {
    const response = await api.get(`${BASE}/assessments/${kind}/${assessmentId}/behaviour/`)
    return response.data
  },

  getStudentAnswers: async (studentId, page = 1) => {
    const response = await api.get(`${BASE}/students/${studentId}/answers/`, { params: { page } })
    return response.data
  },

  getCourseBehaviour: async (courseId) => {
    const response = await api.get(`${BASE}/courses/${courseId}/behaviour/`)
    return response.data
  },

  getCalibration: async (days = 30) => {
    const response = await api.get(`${BASE}/diagnosis/calibration/`, { params: { days } })
    return response.data
  },
```

Create `frontend/exam-frontend/src/services/diagnosisService.js`:

```js
import api from './api'

export const diagnosisService = {
  // { notes: { 'bank:<id>' | 'item:<id>': 'note text' } } — the student's own attempt
  getMyAttemptNotes: async (kind, attemptId) => {
    const response = await api.get(`/intelligence/my/attempts/${kind}/${attemptId}/diagnosis/`)
    return response.data
  },
}
```

- [ ] **Step 2: Label palette and bar**

Create `frontend/exam-frontend/src/components/insights/labels.js`:

```js
// Teacher-facing names for diagnosis labels (never shown to students).
export const LABEL_ORDER = [
  'correct', 'correct_lucky', 'correct_slow', 'guess', 'second_guess',
  'careless_slip', 'time_pressure', 'concept_gap', 'skipped', 'not_seen', 'unclear',
]

export const LABEL_TEXT = {
  correct: 'Correct',
  correct_lucky: 'Correct, likely a guess',
  correct_slow: 'Correct but slow',
  guess: 'Guess',
  second_guess: 'Changed a right answer',
  careless_slip: 'Careless slip',
  time_pressure: 'Time pressure',
  concept_gap: 'Concept gap',
  skipped: 'Skipped',
  not_seen: 'Not seen',
  unclear: 'Unclear',
}

export const LABEL_COLOR = {
  correct: 'bg-success-500',
  // Only shades defined in tailwind.config.js: success/warning have no 300,
  // and the red palette is `error` (there is no `danger`).
  correct_lucky: 'bg-success-400',
  correct_slow: 'bg-success-200',
  guess: 'bg-warning-500',
  second_guess: 'bg-orange-400',
  careless_slip: 'bg-amber-300',
  time_pressure: 'bg-error-400',
  concept_gap: 'bg-error-600',
  skipped: 'bg-surface-300',
  not_seen: 'bg-surface-400',
  unclear: 'bg-surface-200',
}

export const CONFIDENCE_TEXT = { low: 'low confidence', medium: 'medium confidence', high: 'high confidence' }
```

Create `frontend/exam-frontend/src/components/insights/LabelBar.jsx`:

```jsx
import { LABEL_COLOR, LABEL_ORDER, LABEL_TEXT } from './labels'

/** One stacked bar: the share of each diagnosis label for a question. */
export default function LabelBar({ counts, total }) {
  if (!total) return <div className="h-2.5 rounded-full bg-surface-100 dark:bg-surface-700" />
  return (
    <div className="flex h-2.5 rounded-full overflow-hidden bg-surface-100 dark:bg-surface-700">
      {LABEL_ORDER.filter((label) => counts[label]).map((label) => (
        <div
          key={label}
          className={LABEL_COLOR[label]}
          style={{ width: `${(counts[label] / total) * 100}%` }}
          title={`${LABEL_TEXT[label]}: ${counts[label]}`}
        />
      ))}
    </div>
  )
}

export function LabelLegend() {
  return (
    <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-surface-500">
      {LABEL_ORDER.map((label) => (
        <span key={label} className="inline-flex items-center gap-1">
          <span className={`w-2.5 h-2.5 rounded-sm ${LABEL_COLOR[label]}`} /> {LABEL_TEXT[label]}
        </span>
      ))}
    </div>
  )
}
```

- [ ] **Step 3: Assessment panel**

Create `frontend/exam-frontend/src/components/insights/AnswerBehaviourPanel.jsx`:

```jsx
import { useQuery } from '@tanstack/react-query'
import { Activity, Flag } from 'lucide-react'
import { insightsService } from '../../services/insightsService'
import LabelBar, { LabelLegend } from './LabelBar'

const secs = (value) => (value == null ? '—' : `${Math.round(value)} s`)

/** Per-question answer behaviour for one assessment (diagnosis teacher view). */
export default function AnswerBehaviourPanel({ kind, assessmentId }) {
  const { data, isLoading } = useQuery({
    queryKey: ['assessmentBehaviour', kind, assessmentId],
    queryFn: () => insightsService.getAssessmentBehaviour(kind, assessmentId),
  })
  if (isLoading || !data) return null

  return (
    <div className="p-5 rounded-2xl bg-white dark:bg-surface-800 border border-surface-200 dark:border-surface-700">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <h3 className="text-sm font-semibold text-surface-500 flex items-center gap-1">
          <Activity size={14} /> Answer behaviour
        </h3>
        <span className="text-xs text-surface-400">
          {data.answers} diagnosed answers · {data.flagged} questions flagged
        </span>
      </div>
      <LabelLegend />
      {data.answers === 0 ? (
        <p className="text-sm text-surface-400 mt-4">
          No diagnosed answers yet — they appear once students finish this assessment.
        </p>
      ) : (
        <ul className="mt-4 space-y-4">
          {data.items.map((item, index) => (
            <li key={item.item_key}>
              <div className="flex items-start justify-between gap-3 text-sm mb-1">
                <span className="truncate">
                  <span className="text-surface-400">Q{index + 1}.</span> {item.question_text}
                </span>
                <span className="text-xs text-surface-400 shrink-0">
                  {item.distribution.total} answers · median {secs(item.median_active_s)}
                  {item.usual_s != null && ` (usual ${secs(item.usual_s)})`}
                  {item.self_reports > 0 && ` · ${item.self_reports} self-reports`}
                </span>
              </div>
              <LabelBar counts={item.distribution.counts} total={item.distribution.total} />
              {item.flags.map((flag) => (
                <p key={flag.code} className="text-xs text-warning-600 mt-1 flex items-center gap-1">
                  <Flag size={12} /> {flag.message} ({Math.round(flag.share * 100)}%)
                </p>
              ))}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
```

In `frontend/exam-frontend/src/pages/AssessmentReport.jsx`:
- add imports:

```jsx
import { useTenantStore } from '../context/tenantStore'
import AnswerBehaviourPanel from '../components/insights/AnswerBehaviourPanel'
```

- inside the component, before the `useQuery` call:

```jsx
  const teacherView = useTenantStore((s) => s.tenant?.features?.diagnosis_teacher_view === true)
```

- directly before the `{/* Item table */}` block:

```jsx
      {teacherView && <AnswerBehaviourPanel kind={kind} assessmentId={assessmentId} />}
```

- [ ] **Step 4: Build**

Run (from `frontend/exam-frontend/`): `npx vite build`
Expected: build succeeds with no new errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/exam-frontend/src/services/insightsService.js frontend/exam-frontend/src/services/diagnosisService.js frontend/exam-frontend/src/components/insights/labels.js frontend/exam-frontend/src/components/insights/LabelBar.jsx frontend/exam-frontend/src/components/insights/AnswerBehaviourPanel.jsx frontend/exam-frontend/src/pages/AssessmentReport.jsx
git commit -m "feat(frontend): answer behaviour panel on the assessment report"
```

---

### Task 8: Frontend — student Answers tab

**Files:**
- Create: `frontend/exam-frontend/src/components/insights/StudentAnswersTab.jsx`
- Modify: `frontend/exam-frontend/src/pages/StudentDiagnosis.jsx`

**Interfaces:**
- Consumes: `insightsService.getStudentAnswers` (Task 7), `LABEL_TEXT`, `CONFIDENCE_TEXT`.

- [ ] **Step 1: The tab**

Create `frontend/exam-frontend/src/components/insights/StudentAnswersTab.jsx`:

```jsx
import { useState } from 'react'
import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { AlertTriangle, ChevronLeft, ChevronRight } from 'lucide-react'
import { insightsService } from '../../services/insightsService'
import Loading from '../common/Loading'
import { CONFIDENCE_TEXT, LABEL_COLOR } from './labels'

const SELF_REPORT_TEXT = {
  slipped: 'Knew it, slipped',
  ran_out_of_time: 'Ran out of time',
  guessed: 'Guessed',
  didnt_know: "Didn't know",
}

/** Teacher view: one student's diagnosed answers, newest attempt first. */
export default function StudentAnswersTab({ studentId }) {
  const [page, setPage] = useState(1)
  const [highlight, setHighlight] = useState(null) // Set of answer ids from a pattern
  const { data, isLoading } = useQuery({
    queryKey: ['studentAnswers', studentId, page],
    queryFn: () => insightsService.getStudentAnswers(studentId, page),
    placeholderData: keepPreviousData,
  })

  if (isLoading) return <Loading />
  if (!data) return null

  return (
    <div className="space-y-4">
      {page === 1 && data.patterns.length > 0 && (
        <div className="p-4 rounded-2xl bg-warning-50 dark:bg-warning-900/10 border border-warning-200 dark:border-warning-900/30">
          <h3 className="text-sm font-semibold mb-2 flex items-center gap-1">
            <AlertTriangle size={14} className="text-warning-500" /> Patterns in the last 10 attempts
          </h3>
          <ul className="flex flex-wrap gap-2">
            {data.patterns.map((pattern) => {
              const active = highlight && pattern.answer_ids.every((id) => highlight.has(id))
              return (
                <li key={pattern.code}>
                  <button
                    type="button"
                    onClick={() => setHighlight(active ? null : new Set(pattern.answer_ids))}
                    className={`text-xs px-3 py-1 rounded-full border ${
                      active ? 'bg-warning-500 border-warning-500 text-white' : 'border-warning-400'
                    }`}
                  >
                    {pattern.message} · {pattern.count}
                  </button>
                </li>
              )
            })}
          </ul>
        </div>
      )}

      {data.attempts.length === 0 && (
        <p className="text-sm text-surface-400">No diagnosed answers yet.</p>
      )}

      {data.attempts.map((attempt) => (
        <div
          key={`${attempt.attempt_kind}:${attempt.attempt_id}`}
          className="p-4 rounded-2xl bg-white dark:bg-surface-800 border border-surface-200 dark:border-surface-700"
        >
          <div className="flex items-center justify-between gap-2 mb-2">
            <h4 className="font-medium text-sm">{attempt.title}</h4>
            <span className="text-xs text-surface-400">
              {attempt.completed_at ? new Date(attempt.completed_at).toLocaleString() : ''}
            </span>
          </div>
          <ul className="divide-y divide-surface-100 dark:divide-surface-700/50">
            {attempt.answers.map((answer) => (
              <li
                key={answer.id}
                className={`py-2 text-sm ${highlight?.has(answer.id) ? 'bg-warning-50 dark:bg-warning-900/10 -mx-2 px-2 rounded-lg' : ''}`}
              >
                <div className="flex items-start justify-between gap-3">
                  <span className="truncate">{answer.question_text}</span>
                  <span className="inline-flex items-center gap-1.5 shrink-0 text-xs">
                    <span className={`w-2 h-2 rounded-full ${LABEL_COLOR[answer.label]}`} />
                    {answer.label_display}
                    <span className="text-surface-400">({CONFIDENCE_TEXT[answer.confidence]})</span>
                  </span>
                </div>
                <div className="text-xs text-surface-500 mt-0.5 space-y-0.5">
                  {answer.topic && <p className="text-surface-400">{answer.topic}</p>}
                  {answer.evidence.map((sentence) => <p key={sentence}>{sentence}</p>)}
                  {answer.active_s != null && <p>On screen {Math.round(answer.active_s)} s</p>}
                  {answer.self_report && (
                    <p>Student said: “{SELF_REPORT_TEXT[answer.self_report] || answer.self_report}”</p>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </div>
      ))}

      {data.pages > 1 && (
        <div className="flex items-center justify-center gap-3 text-sm">
          <button
            type="button"
            disabled={page <= 1}
            onClick={() => { setHighlight(null); setPage(page - 1) }}
            className="p-2 rounded-lg disabled:opacity-40 hover:bg-surface-100 dark:hover:bg-surface-800"
          >
            <ChevronLeft size={16} />
          </button>
          <span>Page {data.page} of {data.pages}</span>
          <button
            type="button"
            disabled={page >= data.pages}
            onClick={() => { setHighlight(null); setPage(page + 1) }}
            className="p-2 rounded-lg disabled:opacity-40 hover:bg-surface-100 dark:hover:bg-surface-800"
          >
            <ChevronRight size={16} />
          </button>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Tabs on StudentDiagnosis**

In `frontend/exam-frontend/src/pages/StudentDiagnosis.jsx`:
- the file has no `react` import today; add these imports at the top:

```jsx
import { useState } from 'react'
import { useTenantStore } from '../context/tenantStore'
import StudentAnswersTab from '../components/insights/StudentAnswersTab'
```

- inside the component, before the `useQuery`:

```jsx
  const teacherView = useTenantStore((s) => s.tenant?.features?.diagnosis_teacher_view === true)
  const [tab, setTab] = useState('concepts') // concepts | answers
```

- after the header `<div className="flex items-center gap-3">…</div>`, insert:

```jsx
      {teacherView && (
        <div className="flex gap-2">
          {[['concepts', 'Concepts'], ['answers', 'Answers']].map(([key, label]) => (
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

      {teacherView && tab === 'answers' && <StudentAnswersTab studentId={studentId} />}
```

- wrap the existing `<div className="grid grid-cols-1 lg:grid-cols-2 gap-4">…</div>` so it renders only when `tab === 'concepts'` (i.e. `{tab === 'concepts' && ( …existing grid… )}`).

- [ ] **Step 3: Build**

Run (from `frontend/exam-frontend/`): `npx vite build`
Expected: build succeeds.

- [ ] **Step 4: Commit**

```bash
git add frontend/exam-frontend/src/components/insights/StudentAnswersTab.jsx frontend/exam-frontend/src/pages/StudentDiagnosis.jsx
git commit -m "feat(frontend): Answers tab with patterns on the student Insights page"
```

---

### Task 9: Frontend — Insights home tile, menu, Diagnosis quality page

**Files:**
- Create: `frontend/exam-frontend/src/components/insights/AnswerBehaviourTile.jsx`
- Create: `frontend/exam-frontend/src/pages/DiagnosisQuality.jsx`
- Modify: `frontend/exam-frontend/src/pages/InsightsHome.jsx`
- Modify: `frontend/exam-frontend/src/components/layout/AdminSidebar.jsx`
- Modify: `frontend/exam-frontend/src/App.jsx`

**Interfaces:**
- Consumes: `insightsService.getCourseBehaviour`, `getCalibration`; `contentBuilderService.getExams` (instructor-scoped course list); `isAnyOptInFeatureEnabled` (Task 1).

- [ ] **Step 1: The tile**

Create `frontend/exam-frontend/src/components/insights/AnswerBehaviourTile.jsx`:

```jsx
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { insightsService } from '../../services/insightsService'

const RATES = [
  ['guess', 'Guesses'],
  ['careless_slip', 'Careless slips'],
  ['time_pressure', 'Time pressure'],
]
const pct = (value) => (value == null ? '—' : `${Math.round(value * 100)}%`)

function Spark({ points }) {
  const values = points.map((p) => p ?? 0)
  const max = Math.max(0.01, ...values)
  return (
    <svg viewBox="0 0 60 20" className="w-16 h-5" aria-hidden="true">
      <polyline
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        points={values.map((v, i) => `${(i * 60) / Math.max(1, values.length - 1)},${20 - (v / max) * 18}`).join(' ')}
      />
    </svg>
  )
}

/** Insights home: guess / slip / time-pressure rates for one course. */
export default function AnswerBehaviourTile({ courseId }) {
  const { data } = useQuery({
    queryKey: ['courseBehaviour', courseId],
    queryFn: () => insightsService.getCourseBehaviour(courseId),
    enabled: !!courseId,
  })
  if (!data) return null

  return (
    <div className="p-5 rounded-2xl bg-white dark:bg-surface-800 border border-surface-200 dark:border-surface-700">
      <h3 className="text-sm font-semibold text-surface-500 mb-3">
        Answer behaviour (last {data.days} days · {data.rates.answers} answers)
      </h3>
      <ul className="space-y-2 text-sm">
        {RATES.map(([key, label]) => (
          <li key={key} className="flex items-center justify-between gap-2">
            <span>{label}</span>
            <span className="flex items-center gap-2 text-primary-500">
              <Spark points={data.trend.map((week) => week[key])} />
              <span className="font-semibold text-surface-800 dark:text-surface-100 w-10 text-right">
                {pct(data.rates[key])}
              </span>
            </span>
          </li>
        ))}
      </ul>

      {data.students_to_check.length > 0 && (
        <div className="mt-4 pt-3 border-t border-surface-200 dark:border-surface-700">
          <p className="text-xs font-semibold text-surface-500 mb-2">Students to check</p>
          <ul className="space-y-1 text-sm">
            {data.students_to_check.map((row) => (
              <li key={row.student_id} className="flex justify-between gap-2">
                <Link to={`/admin/insights/students/${row.student_id}`} className="truncate hover:text-primary-500">
                  {row.name}
                </Link>
                <span className="text-xs text-surface-400 shrink-0">
                  slips {pct(row.careless_slip)} · time {pct(row.time_pressure)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {data.recent_assessments.length > 0 && (
        <div className="mt-4 pt-3 border-t border-surface-200 dark:border-surface-700">
          <p className="text-xs font-semibold text-surface-500 mb-2">Recent assessments</p>
          <ul className="space-y-1 text-sm">
            {data.recent_assessments.map((row) => (
              <li key={`${row.kind}:${row.id}`}>
                <Link to={`/admin/insights/assessments/${row.kind}/${row.id}`} className="truncate hover:text-primary-500">
                  {row.title}
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

- [ ] **Step 2: Insights home changes**

In `frontend/exam-frontend/src/pages/InsightsHome.jsx`:
- replace the `courseService` import with

```jsx
import { contentBuilderService } from '../services/contentBuilderService'
import { useTenantStore } from '../context/tenantStore'
import { useAuthStore } from '../context/authStore'
import { Link } from 'react-router-dom'
import AnswerBehaviourTile from '../components/insights/AnswerBehaviourTile'
```

and add `Gauge` to the `lucide-react` import.

- replace the courses query with the scoped admin list (faculty get only their assigned courses):

```jsx
  const { data: courses } = useQuery({
    queryKey: ['insightCourses'],
    queryFn: contentBuilderService.getExams,
  })
  const courseList = courses ?? []
```

- add, after the existing `useState` lines:

```jsx
  const practiceOn = useTenantStore((s) => s.tenant?.features?.practice === true)
  const teacherView = useTenantStore((s) => s.tenant?.features?.diagnosis_teacher_view === true)
  const { user, profile } = useAuthStore()
  const isAdmin = (user?.role || profile?.user?.role) === 'admin'
```

- in the header button group, render the "Tag questions" button only when `practiceOn`, and add before it:

```jsx
          {teacherView && isAdmin && (
            <Link
              to="/admin/insights/diagnosis-quality"
              className="inline-flex items-center gap-2 px-3 py-2 rounded-xl bg-surface-100 dark:bg-surface-800 text-sm hover:bg-surface-200 dark:hover:bg-surface-700"
            >
              <Gauge size={14} /> Diagnosis quality
            </Link>
          )}
```

- show the "Generated questions" tab only when `practiceOn` (filter the tabs array), and in the class view's right-hand column, put `{teacherView && <AnswerBehaviourTile courseId={activeCourse} />}` first, then wrap the "Active deficits", "Practice adoption" and "Smart Practice controls" tiles in `{practiceOn && (<>…</>)}`.

(Checked: `contentBuilderService.getExams` calls `/courses/admin/courses/` through its `list()` helper, which returns a plain array, and `AdminCourseViewSet` already limits instructors to their assigned courses.)

- [ ] **Step 3: Menu visibility**

In `frontend/exam-frontend/src/components/layout/AdminSidebar.jsx`:
- change the Insights item to

```js
  { path: '/admin/insights', label: 'Learning Insights', icon: Brain, features: ['practice', 'diagnosis_teacher_view'] },
```

- add the selector next to `isFeatureVisible`:

```js
  const isAnyOptInFeatureEnabled = useTenantStore((s) => s.isAnyOptInFeatureEnabled)
```

- replace the nav filter with:

```js
        {ADMIN_NAV_ITEMS.filter(
          (item) => (!item.feature || isFeatureVisible(item.feature))
            && (!item.features || isAnyOptInFeatureEnabled(item.features))
        ).map((item) => {
```

Then `grep -rn "ADMIN_NAV_ITEMS" frontend/exam-frontend/src` and apply the same `features` rule anywhere else the list is filtered.

- [ ] **Step 4: Diagnosis quality page**

Create `frontend/exam-frontend/src/pages/DiagnosisQuality.jsx`:

```jsx
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Gauge } from 'lucide-react'
import { insightsService } from '../services/insightsService'
import Loading from '../components/common/Loading'
import { LABEL_ORDER, LABEL_TEXT } from '../components/insights/labels'

const SELF_REPORTS = ['slipped', 'ran_out_of_time', 'guessed', 'didnt_know']
const SELF_REPORT_TEXT = {
  slipped: 'Slipped', ran_out_of_time: 'Out of time', guessed: 'Guessed', didnt_know: "Didn't know",
}

/** Admin: how well diagnosis labels agree with what students say happened. */
export default function DiagnosisQuality() {
  const [days, setDays] = useState(30)
  const { data, isLoading } = useQuery({
    queryKey: ['diagnosisCalibration', days],
    queryFn: () => insightsService.getCalibration(days),
  })
  if (isLoading) return <Loading fullScreen />
  if (!data) return null

  const labels = LABEL_ORDER.filter((label) => data.labels[label])
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-display font-bold flex items-center gap-2">
            <Gauge className="text-primary-500" /> Diagnosis quality
          </h1>
          <p className="text-surface-500 mt-1">
            Classifier v{data.classifier_version} · {data.total} answers ·
            {' '}{data.with_timeline} with timing · {data.stats_usual} with measured usual time
          </p>
        </div>
        <select
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
          className="px-3 py-2 rounded-xl border border-surface-300 dark:border-surface-600 bg-white dark:bg-surface-800 text-sm"
        >
          {[7, 30, 90, 365].map((d) => <option key={d} value={d}>Last {d} days</option>)}
        </select>
      </div>

      <div className="p-5 rounded-2xl bg-white dark:bg-surface-800 border border-surface-200 dark:border-surface-700 overflow-x-auto">
        <h3 className="text-sm font-semibold text-surface-500 mb-3">Labels vs self-reports</h3>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-surface-400 border-b border-surface-200 dark:border-surface-700">
              <th className="py-2 pr-3">Label</th>
              <th className="py-2 pr-3">Answers</th>
              {SELF_REPORTS.map((r) => <th key={r} className="py-2 pr-3">{SELF_REPORT_TEXT[r]}</th>)}
              <th className="py-2">Agreement</th>
            </tr>
          </thead>
          <tbody>
            {labels.map((label) => (
              <tr key={label} className="border-b border-surface-100 dark:border-surface-700/50">
                <td className="py-2 pr-3">{LABEL_TEXT[label]}</td>
                <td className="py-2 pr-3">{data.labels[label]}</td>
                {SELF_REPORTS.map((r) => (
                  <td key={r} className="py-2 pr-3">{data.confusion[label]?.[r] ?? 0}</td>
                ))}
                <td className="py-2">
                  {data.agreement[label] != null ? `${Math.round(data.agreement[label] * 100)}%` : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="p-5 rounded-2xl bg-white dark:bg-surface-800 border border-surface-200 dark:border-surface-700">
        <h3 className="text-sm font-semibold text-surface-500 mb-3">Thresholds in use</h3>
        <dl className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-1 text-sm">
          {Object.entries(data.thresholds).map(([key, value]) => (
            <div key={key} className="flex justify-between gap-2">
              <dt className="text-surface-500">{key}</dt>
              <dd className="font-mono">{value}</dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  )
}
```

In `frontend/exam-frontend/src/App.jsx`, import `DiagnosisQuality` next to `StudentDiagnosis` and add after the student route:

```jsx
          <Route path="/admin/insights/diagnosis-quality" element={<LoginGate><AdminRoute><DiagnosisQuality /></AdminRoute></LoginGate>} />
```

- [ ] **Step 5: Build**

Run (from `frontend/exam-frontend/`): `npx vite build`
Expected: build succeeds.

- [ ] **Step 6: Commit**

```bash
git add frontend/exam-frontend/src/components/insights/AnswerBehaviourTile.jsx frontend/exam-frontend/src/pages/DiagnosisQuality.jsx frontend/exam-frontend/src/pages/InsightsHome.jsx frontend/exam-frontend/src/components/layout/AdminSidebar.jsx frontend/exam-frontend/src/App.jsx
git commit -m "feat(frontend): answer behaviour tile, Diagnosis quality page, Insights menu for the teacher view"
```

---

### Task 10: Frontend — student notes on review pages

**Files:**
- Create: `frontend/exam-frontend/src/components/review/DiagnosisNote.jsx`
- Modify: `frontend/exam-frontend/src/components/review/WhatHappened.jsx`
- Modify: `frontend/exam-frontend/src/pages/QuizReview.jsx`, `MockTestReview.jsx`, `RichMockReview.jsx`

**Interfaces:**
- Produces: `useDiagnosisNotes(kind, attemptId) -> { notes }`; `<DiagnosisNote text />`.
- Consumes: `diagnosisService.getMyAttemptNotes` (Task 7).

- [ ] **Step 1: Hook and component**

Create `frontend/exam-frontend/src/components/review/DiagnosisNote.jsx`:

```jsx
import { useQuery } from '@tanstack/react-query'
import { Lightbulb } from 'lucide-react'
import { diagnosisService } from '../../services/diagnosisService'
import { useTenantStore } from '../../context/tenantStore'

/** The student's own answer notes for one attempt (diagnosis student view). */
export function useDiagnosisNotes(attemptKind, attemptId) {
  // Explicit true only, so no request is ever sent for an opted-out tenant.
  const optedIn = useTenantStore((s) => s.tenant?.features?.diagnosis_student_view === true)
  const { data } = useQuery({
    queryKey: ['diagnosisNotes', attemptKind, attemptId],
    queryFn: () => diagnosisService.getMyAttemptNotes(attemptKind, attemptId),
    enabled: optedIn && !!attemptId,
    staleTime: 60_000,
    retry: false,
  })
  return { notes: data?.notes || {} }
}

/** One plain-language line about how an answer went. Never a bare label. */
export default function DiagnosisNote({ text }) {
  if (!text) return null
  return (
    <p className="mt-3 text-sm text-surface-600 dark:text-surface-300 flex items-start gap-1.5">
      <Lightbulb size={14} className="mt-0.5 text-primary-500 shrink-0" />
      <span>{text}</span>
    </p>
  )
}
```

- [ ] **Step 2: Relabel the self-report row**

In `frontend/exam-frontend/src/components/review/WhatHappened.jsx`, change the group's `aria-label` to `"Not quite? Tell us what happened."` and the visible span text from `What happened?` to `Not quite? Tell us what happened.`

- [ ] **Step 3: Mount on the three review pages**

`QuizReview.jsx`:
- import: `import DiagnosisNote, { useDiagnosisNotes } from '../components/review/DiagnosisNote'`
- after `const selfReports = useSelfReports('quiz', attemptId)`: `const diagnosisNotes = useDiagnosisNotes('quiz', attemptId)`
- directly above `{showWhatHappened && (`: `<DiagnosisNote text={diagnosisNotes.notes[reviewKey]} />`

`MockTestReview.jsx`: the same with `'mock'`.

`RichMockReview.jsx`:
- import the same;
- in the page component after `const selfReports = useSelfReports('mock', attemptId)`: `const diagnosisNotes = useDiagnosisNotes('mock', attemptId)`;
- pass it to each card: `<ReviewCard … diagnosisNotes={diagnosisNotes} />` and add `diagnosisNotes` to `ReviewCard`'s props;
- directly above the `{selfReports.enabled && selfReports.ready && …` block: `<DiagnosisNote text={q.ref_id ? diagnosisNotes.notes[\`${q.kind}:${q.ref_id}\`] : null} />`

- [ ] **Step 4: Build**

Run (from `frontend/exam-frontend/`): `npx vite build`
Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/exam-frontend/src/components/review/DiagnosisNote.jsx frontend/exam-frontend/src/components/review/WhatHappened.jsx frontend/exam-frontend/src/pages/QuizReview.jsx frontend/exam-frontend/src/pages/MockTestReview.jsx frontend/exam-frontend/src/pages/RichMockReview.jsx
git commit -m "feat(frontend): plain-language answer notes on review pages"
```

---

### Task 11: Frontend — dependent switches in both settings pages

**Files:**
- Modify: `frontend/exam-frontend/src/pages/AdminDashboard.jsx` (`TenantSettings` feature list)
- Modify: `frontend/superadmin-frontend/src/pages/TenantDetail.jsx` (`FeatureRow`)

**Interfaces:**
- Consumes: `available_features[].requires` / `requires_label` (Task 1).

- [ ] **Step 1: Tenant-admin settings**

In `AdminDashboard.jsx`, inside `availableFeatures.map((f) => { … })` in `TenantSettings`:
- after `const locked = lockedFeatures.includes(f.key)` add:

```jsx
                        const waiting = Boolean(f.requires) && !features[f.requires]
```

- under the `{locked && (…)}` paragraph add:

```jsx
                                    {waiting && (
                                        <p className="text-xs text-surface-400 mt-0.5">Needs {f.requires_label}</p>
                                    )}
```

- on the switch `<button role="switch" …>`: change `disabled={featuresMutation.isPending || locked}` to `disabled={featuresMutation.isPending || locked || waiting}` and the title to `title={locked ? 'Locked by DailyTaiyari' : waiting ? `Needs ${f.requires_label}` : undefined}`.

In `toggleFeature`, add before the existing `next` line:

```jsx
        const feature = availableFeatures.find((f) => f.key === key)
        if (feature?.requires && !features[feature.requires]) {
            toast.error(`Turn on ${feature.requires_label} first.`)
            return
        }
```

- [ ] **Step 2: Super-admin hint**

Spec §3.1 asks for the dependent switch to be greyed out, with the hint, while its requirement is off. In `TenantDetail.jsx`:

- in the `FeatureRow` call inside the Feature Governance list, pass the requirement's effective state:

```jsx
                requirementOn={!f.requires || Boolean(tenant.features?.[f.requires])}
```

- add `requirementOn = true` to `FeatureRow`'s props (`function FeatureRow({ feature, mode, tenantValue, onChange, requirementOn = true })`), dim the row while it is false by changing the outer `<div className="flex items-center justify-between py-2.5">` to `<div className={`flex items-center justify-between py-2.5 ${requirementOn ? '' : 'opacity-60'}`}>`, and under the `text-[11px]` status line add:

```jsx
          {!requirementOn && (
            <div className="text-[11px] text-slate-400">Needs {feature.requires_label}</div>
          )}
```

(The buttons stay clickable: the super admin may still lock a dependent switch on; it takes effect only while its requirement is on, which the hint states.)

- [ ] **Step 3: Build both apps**

Run: `npx vite build` in `frontend/exam-frontend/` and in `frontend/superadmin-frontend/`.
Expected: both succeed.

- [ ] **Step 4: Commit**

```bash
git add frontend/exam-frontend/src/pages/AdminDashboard.jsx frontend/superadmin-frontend/src/pages/TenantDetail.jsx
git commit -m "feat(frontend): grey out diagnosis view switches until Answer Diagnosis is on"
```

---

### Task 12: Docs and manual walkthrough

**Files:**
- Modify: `wiki/backend-guide.md` (Response diagnosis section)

- [ ] **Step 1: Ops notes**

In `wiki/backend-guide.md`, at the end of the "Response diagnosis (intelligence)" bullet list, add:

```markdown
- **Diagnosis visibility (2B Part A).** Two more opt-in switches, both
  needing `response_diagnosis` (`Tenant.FEATURE_REQUIRES`;
  `get_features()` reports them off while it is off):
  - `diagnosis_teacher_view` — Insights: "Answer behaviour" panel on each
    assessment report (`…/assessments/<kind>/<id>/behaviour/`), "Answers"
    tab on each student (`…/students/<id>/answers/`), answer-behaviour tile
    on Insights home (`…/courses/<id>/behaviour/`), and the admin-only
    Diagnosis quality page over the calibration endpoint.
  - `diagnosis_student_view` — one-line notes on quiz, mock and rich-mock
    review pages (`GET /api/v1/intelligence/my/attempts/<kind>/<id>/diagnosis/`).
    Only medium/high-confidence diagnoses show a note; students never see a
    label.
  - Flags, patterns and student wording: `intelligence/visibility_config.py`.
    Display-only — no version bump or recompute after editing.
  - Scope (`intelligence/access.py`): faculty see only their assigned
    courses and the students approved in them; admins see the tenant. This
    also narrowed the older Insights views for faculty.
  - The calibration endpoint is admin-only and now also returns
    `thresholds` and `classifier_version`.
```

- [ ] **Step 2: Manual walkthrough (in the PR description, not committed)**

Write this checklist into the PR description under "Manual checks — Part A":

1. With `CELERY_TASK_ALWAYS_EAGER` unset and a worker running (or, once
   Part B lands, `CELERY_TASK_ALWAYS_EAGER=true`), on the DailyTaiyari test
   tenant turn on Answer Diagnosis only. Confirm Settings shows both view
   switches greyed with "Needs Answer Diagnosis".
2. Turn on both view switches. As a student, take a quiz quickly (answer
   two questions in under 5 s each) and submit. On the review page, the
   quick answers show "Looks like a quick guess — you spent Ns here." and the
   row reads "Not quite? Tell us what happened."
3. As an admin, open Learning Insights: the menu item shows even with Smart
   Practice off, the Answer behaviour tile lists the quiz under "Recent
   assessments", and the report shows the panel with stacked bars.
4. Open the student from "Students to check" (or by URL) → Answers tab:
   evidence sentences, active time, any self-report.
5. As faculty assigned to a different course, open the same student and
   assessment URLs: both are refused.
6. Open Diagnosis quality as admin (visible), and as faculty (no link;
   the URL redirects).
7. On the CodeMinors test tenant, with every learning-layer switch off,
   confirm no Insights menu item, no notes on review pages, and no
   requests to `/intelligence/my/attempts/` in the network tab.

- [ ] **Step 3: Final suite**

Run: `venv/Scripts/python.exe manage.py test -v 1` (whole backend) and `npx vite build` in both frontends.
Expected: all PASS; both builds succeed.

- [ ] **Step 4: Commit**

```bash
git add wiki/backend-guide.md
git commit -m "docs(wiki): diagnosis visibility switches, scope and endpoints"
```
