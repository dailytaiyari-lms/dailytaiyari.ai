# Backend Guide

## Project Structure

```
backend/
├── core/                  # Multi-tenant foundation
│   ├── models.py          # Tenant model, TimeStampedModel base
│   ├── middleware.py       # TenantMiddleware (X-Tenant-ID enforcement)
│   ├── views.py           # TenantAwareViewSet, TenantDetailView
│   └── admin.py           # TenantAdmin
├── users/                 # Authentication & user profiles
├── exams/                 # Exam, Subject, Topic, Chapter
├── quiz/                  # Questions, Quizzes, Mock Tests, Attempts
├── content/               # Study content, progress, plans
├── analytics/             # Dashboard, streaks, performance, study timer
├── gamification/          # Badges, XP, leaderboard, challenges
├── community/             # Posts, comments, polls, community quizzes
├── chatbot/               # AI chat sessions, FAQ, AI quizzes
├── coursegen/             # AI course/content authoring (async, `aigen` queue)
├── notebooks/             # Labs — gradeable Python notebooks + AI lab generator
├── deploy/nbrunner/       # Sandboxed notebook execution service (no app code)
└── dailytaiyari/          # Django project settings & URLs
```

---

## Core Models

### `Tenant` — `core/models.py`

The central tenant model. All other models reference it via a foreign key.

```python
class Tenant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    name = models.CharField(max_length=255)
    subdomain = models.CharField(max_length=100, unique=True, null=True, blank=True)
    logo = models.ImageField(upload_to='tenant_logos/', null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

### `TimeStampedModel` — `core/models.py`

Abstract base model that all data models inherit from. Automatically adds `tenant`, `id`, `created_at`, `updated_at`.

```python
class TimeStampedModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
```

### `User` — `users/models.py`

Custom user model with **mandatory** tenant association.

```python
class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    tenant = models.ForeignKey('core.Tenant', on_delete=models.CASCADE)  # NOT nullable
    email = models.EmailField(unique=True)
    # ...
```

---

## TenantMiddleware — `core/middleware.py`

Intercepts **every** incoming request and enforces tenant identification.

### Behavior

| Scenario | Result |
|---|---|
| Valid `X-Tenant-ID` header | `request.tenant` = Tenant object, request proceeds |
| Missing header (non-exempt path) | **403** `{"error": "X-Tenant-ID header is required."}` |
| Invalid UUID format | **403** `{"error": "Invalid Tenant ID format."}` |
| UUID not found / inactive tenant | **403** `{"error": "Tenant not found or inactive."}` |
| Exempt path (admin, docs, etc.) | `request.tenant` = None, request proceeds |

### Exempt Paths

These paths do **not** require the `X-Tenant-ID` header:

```python
TENANT_EXEMPT_PATHS = [
    '/admin/',
    '/api/v1/tenant/',
    '/api/docs/',
    '/api/redoc/',
    '/static/',
    '/media/',
]
```

To add new exempt paths, update the `TENANT_EXEMPT_PATHS` list in `core/middleware.py`.

---

## TenantAwareViewSet — `core/views.py`

### `TenantAwareViewSet` (for read-write endpoints)

```python
class TenantAwareViewSet(viewsets.ModelViewSet):
    def get_queryset(self):
        queryset = super().get_queryset()
        if not hasattr(self.request, 'tenant') or not self.request.tenant:
            return queryset.none()
        return queryset.filter(tenant=self.request.tenant)

    def perform_create(self, serializer):
        if not hasattr(self.request, 'tenant') or not self.request.tenant:
            raise PermissionDenied("A valid Tenant is required.")
        serializer.save(tenant=self.request.tenant)
```

### `TenantAwareReadOnlyViewSet` (for read-only endpoints)

Same as above but inherits from `ReadOnlyModelViewSet`.

### Usage — How to Make a ViewSet Tenant-Aware

**Before:**
```python
class QuizViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Quiz.objects.filter(status='published')
    # ...
```

**After:**
```python
from core.views import TenantAwareReadOnlyViewSet

class QuizViewSet(TenantAwareReadOnlyViewSet):
    queryset = Quiz.objects.filter(status='published')
    # ... (no other changes needed!)
```

### When `perform_create` is Overridden

If your ViewSet overrides `perform_create`, you must also pass `tenant`:

```python
def perform_create(self, serializer):
    serializer.save(
        student=self.request.user.profile,
        tenant=self.request.tenant  # Don't forget this!
    )
```

---

## Apps & Their ViewSets

Below is every app and which ViewSets are tenant-aware:

### `exams`
| ViewSet | Base Class | Notes |
|---|---|---|
| `ExamViewSet` | `TenantAwareReadOnlyViewSet` | |
| `SubjectViewSet` | `TenantAwareReadOnlyViewSet` | |
| `TopicViewSet` | `TenantAwareReadOnlyViewSet` | |
| `ChapterViewSet` | `TenantAwareReadOnlyViewSet` | |

### `quiz`
| ViewSet | Base Class | Notes |
|---|---|---|
| `QuestionViewSet` | `TenantAwareReadOnlyViewSet` | |
| `QuizViewSet` | `TenantAwareReadOnlyViewSet` | |
| `MockTestViewSet` | `TenantAwareReadOnlyViewSet` | |
| `QuizAttemptViewSet` | `TenantAwareReadOnlyViewSet` | |
| `MockTestAttemptViewSet` | `TenantAwareReadOnlyViewSet` | |
| `QuestionReportViewSet` | `TenantAwareViewSet` | Write operations |

### `content`
| ViewSet | Base Class | Notes |
|---|---|---|
| `ContentViewSet` | `TenantAwareReadOnlyViewSet` | |
| `ContentProgressViewSet` | `TenantAwareViewSet` | Custom `perform_create` |
| `StudyPlanViewSet` | `TenantAwareViewSet` | |
| `StudyPlanItemViewSet` | `TenantAwareViewSet` | |

### `analytics`
| ViewSet | Base Class | Notes |
|---|---|---|
| `TopicMasteryViewSet` | `TenantAwareReadOnlyViewSet` | |
| `SubjectPerformanceViewSet` | `TenantAwareReadOnlyViewSet` | |
| `DailyActivityViewSet` | `TenantAwareReadOnlyViewSet` | |
| `StreakViewSet` | `TenantAwareReadOnlyViewSet` | |
| `WeeklyReportViewSet` | `TenantAwareReadOnlyViewSet` | |
| `DashboardView` | `APIView` | Protected by middleware |
| `StudyTimerView` | `APIView` | Protected by middleware |
| `StudyGoalView` | `APIView` | Protected by middleware |

### `gamification`
| ViewSet | Base Class | Notes |
|---|---|---|
| `BadgeViewSet` | `TenantAwareReadOnlyViewSet` | |
| `StudentBadgeViewSet` | `TenantAwareReadOnlyViewSet` | |
| `XPTransactionViewSet` | `TenantAwareReadOnlyViewSet` | |
| `ChallengeViewSet` | `TenantAwareReadOnlyViewSet` | |
| `ChallengeParticipationViewSet` | `TenantAwareReadOnlyViewSet` | |
| `LeaderboardView` | `APIView` | Protected by middleware |

### `community`
| ViewSet | Base Class | Notes |
|---|---|---|
| `PostViewSet` | `TenantAwareViewSet` | |
| `CommentViewSet` | `TenantAwareViewSet` | |
| `CommunityStatsViewSet` | `viewsets.GenericViewSet` | Protected by middleware |
| `CommunityLeaderboardViewSet` | `viewsets.GenericViewSet` | Protected by middleware |

### `chatbot`
| ViewSet | Base Class | Notes |
|---|---|---|
| `ChatSessionViewSet` | `TenantAwareViewSet` | |
| `ChatMessageViewSet` | `TenantAwareReadOnlyViewSet` | |
| `SavedResponseViewSet` | `TenantAwareViewSet` | |
| `FrequentQuestionViewSet` | `TenantAwareReadOnlyViewSet` | |
| `AIQuizAttemptViewSet` | `TenantAwareViewSet` | |

### `notebooks`
| ViewSet | Base Class | Notes |
|---|---|---|
| `NotebookViewSet` | `ReadOnlyModelViewSet` | Student-facing. Scoped to the student's **enrolled courses**, not just the tenant. Adds `draft/`, `submit/`, `my-submissions/` actions |
| `AdminNotebookViewSet` | `TenantAwareViewSet` | Lab authoring, incl. nested tests |
| `AdminNotebookDatasetViewSet` | `TenantAwareViewSet` | Dataset uploads |
| `AdminNotebookSubmissionViewSet` | `TenantAwareViewSet` | Submission review + mark override |

See [notebooks-labs.md](./notebooks-labs.md) for the grading pipeline and the
sandbox's security properties.

---

## Adding a New App or Model

When adding a new model to the system:

1. **Inherit from `TimeStampedModel`** — this gives you `tenant`, `id`, `created_at`, `updated_at` for free
2. **Use `TenantAwareViewSet`** or **`TenantAwareReadOnlyViewSet`** as your ViewSet base class
3. **If overriding `perform_create`**, include `tenant=self.request.tenant`
4. **Run migrations**: `python manage.py makemigrations && python manage.py migrate`

```python
# models.py
from core.models import TimeStampedModel

class MyNewModel(TimeStampedModel):
    title = models.CharField(max_length=200)
    # tenant, id, created_at, updated_at are inherited!

# views.py
from core.views import TenantAwareViewSet

class MyNewModelViewSet(TenantAwareViewSet):
    queryset = MyNewModel.objects.all()
    serializer_class = MyNewModelSerializer
    # Queryset is automatically filtered by tenant!
    # New records automatically get tenant assigned!
```

---

## Registration Flow

User registration **requires** a valid tenant. The flow:

1. Frontend sends `POST /api/v1/auth/register/` with `X-Tenant-ID` header
2. `TenantMiddleware` validates tenant and attaches to `request.tenant`
3. `RegisterView.create()` checks `request.tenant` exists
4. New `User` is created with `tenant=request.tenant`
5. A `StudentProfile` is automatically created (via signal/save)

```python
# users/views.py
class RegisterView(generics.CreateAPIView):
    def create(self, request, *args, **kwargs):
        if not hasattr(request, 'tenant') or not request.tenant:
            return Response(
                {'error': 'A valid Tenant is required to register.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save(tenant=request.tenant)
        # ...
```

---

## Response diagnosis (intelligence)

**Opt-in per tenant.** The whole learning layer runs only for tenants with at
least one of `practice`, `ai_grading` or `response_diagnosis` on
(`intelligence.api.intelligence_enabled`; all three are off by default). For
any other tenant: the attempt screens capture no timeline and send the same
payload as before the layer existed, `POST /intelligence/timeline/` answers
204 and writes nothing, submits and grading write no `LearningEvent` and
enqueue no task, the nightly jobs skip the tenant, and the tagging sweep never
tags it. Turning a feature on starts accrual from that moment; run
`manage.py backfill_learning_events` (and `recompute_diagnoses`) for history.

The statistical tasks (`diagnose_and_update_state`, `update_learner_state`,
`recompute_recommendations`, the nightly `recompute_item_stats` and
`refresh_learner_state`) run on the `intelligence` queue, consumed by the
`celery-intelworker` service (concurrency 1), never on the default worker.
Beat runs in IST: item stats at 02:00, learner-state refresh at 03:00.

On an opted-in tenant, every attempt screen records a raw per-question timeline
(`POST /api/v1/intelligence/timeline/` → `AttemptTimeline`). When an attempt
is finalized, the `intelligence.diagnose_and_update_state` task labels every
item, answered or not, as one of: not_seen, skipped, time_pressure, correct,
correct_lucky, correct_slow, guess, second_guess, careless_slip,
concept_gap, unclear. It writes `ResponseDiagnosis`, then recomputes learner
state with guesses and slips down-weighted.

- Thresholds: `intelligence/diagnosis_config.py`. After changing any value,
  bump `CLASSIFIER_VERSION` in `intelligence/versions.py` and run
  `manage.py recompute_diagnoses` (optionally `--tenant`, `--since`). The
  command also refreshes learner state for quiz and mock attempts, survives
  individual bad attempts, and reports the count of failures.
- After first deploy:
  1. Optionally run `manage.py recompute_diagnoses` to label history.
     Historic attempts have no timelines, so only non-time rules apply to
     them.
  2. Then run `manage.py recompute_learner_state` (`STATE_MODEL_VERSION` 2).
     It also covers practice-only states, which `recompute_diagnoses` doesn't
     refresh.

  Running `recompute_learner_state` alone changes nothing about weights,
  because no diagnoses exist yet.
- Students' "What happened?" taps on review pages need the opt-in tenant
  feature `response_diagnosis`. Capture and classification run for any
  opted-in tenant (any of the three features).
- Calibration: `GET /api/v1/tenant-admin/intelligence/diagnosis/calibration/?days=30`
  compares classifier labels with self-reports.
- Timeline clocks: quizzes and rich mocks are server-clocked (the window
  starts at `started_at`). Legacy mock/PYP screens are client-clocked: a page
  reload starts a new session that replaces the old ones. Practice is untimed.
- Request size: the timeline endpoint caps the body at 256 KB by
  `Content-Length`, with a post-parse check as defence in depth. The real limit
  for requests without a `Content-Length` header belongs at the proxy (nginx
  `client_max_body_size`).
- Throttle: the timeline endpoint allows 20 requests/min/user on its own
  `timeline` scope.

---

## Analytics counting fix

The old `quiz/signals.py` re-ran the incremental analytics updates on every
save of a completed attempt, so each quiz or mock was counted two to three
times (and every admin grade added another count). The signals are gone and
each finalization updates analytics exactly once. From the deploy date,
`TopicMastery` and `SubjectPerformance` totals, accuracy and mastery grow at
the correct rate, which looks slower than before; history stays inflated
unless recomputed. Timed-out rich attempts now count too. Tell tenant admins
before the release.

---

## Question tagging v2 (intelligence)

A two-stage, tree-bound tagger: stage 1 picks a topic from the subject's
syllabus tree (only when the item's topic is unknown, e.g. mock items),
stage 2 picks subtopics, thinking level, skills, format and difficulty
within that topic. Results go to `ItemTagging` and `ItemSkillTag`; the
subtopic Concept is the mastery unit. `intelligence.tagging_sweep` runs
weekly (Sunday 04:00 IST, on the `aigen` queue; also on demand: admin 'run
tagging' button or `manage.py tag_items`). It runs v2 for subjects with an
active syllabus tree and v1 for the rest (mock items are owned by v2 through
one ownership rule). Every opted-in tenant with a tree is queued, so v2 starts
after a tree is created or edited.

- Opt-in: the sweep and the admin button only tag tenants with at least one
  learning-layer feature on (see Response diagnosis above), so no other
  tenant's AI budget is ever spent on tagging. `manage.py tag_items --tenant`
  is an explicit operator action and still runs for any tenant, printing a
  note when the tenant has not opted in. Manual-edit staleness checks also run
  only for opted-in tenants.

- Never overwritten: manual tags (`ItemTagging.source='manual'`) are not
  re-tagged, and bank question difficulty is not touched.
- Items are re-tagged when the taxonomy version or the subject's tree changes.
- If stage 1 names no valid topic, the item is saved as `needs_review` with
  reason `invalid_key`.

**Editing tags.** Edit `backend/intelligence/taxonomy/tags.yaml`, then:

```bash
python manage.py sync_taxonomy --check                 # validate only
python manage.py sync_taxonomy                         # load into the DB
python manage.py sync_taxonomy --retag-subjects <id,id>
```

| Edit | Effect |
|---|---|
| Change a label | Display only; nothing is re-tagged |
| Add a tag | Run `--retag-subjects` for the subjects it affects |
| Change a meaning | Bump `version`, then re-tag |
| Remove a tag | Set `active: false`; history is kept |

**Exam-mapped courses** (tree from `taxonomy/exams/<exam>.yaml`):

```bash
python manage.py map_course_to_exam --course <id> --exam jee_main \
    --subject-map physics=<id>,chemistry=<id>,maths=<id>
```

If it reports merged concepts, run `manage.py recompute_learner_state`.

**Custom courses** (tree built by the model from the course content):

```bash
python manage.py build_course_tree --course <id> [--model <platform model>] \
    [--packs programming] [--dry-run]
```

Only question text, topic names and objectives are sent to the model.

**Running the sweep:**

```bash
python manage.py tag_items --tenant <id> [--model <platform model>] [--limit N]
```

**Review.** Items that need a human get `ItemTagging.review_status='needs_review'`
with reasons `low_confidence`, `invalid_key`, `proposed_subtopic` or
`stage_disagreement`. The confidence threshold is
`review_confidence_threshold` in `tags.yaml`. The shipped value is 0.9, set
from the first evaluation. Reset it from the threshold `evaluate_tagger`
suggests:
- it walks the confidence buckets that hold at least 5 items, from the top
  bucket down;
- the threshold is the floor of the lowest bucket reached while every bucket
  visited has at least 80% subtopic accuracy, stopping at the first bucket
  that fails;
- it suggests nothing when the top bucket already fails or no bucket has 5
  items.

The review UI is plan 2B.

**Evaluating:**

```bash
python manage.py make_gold --course <id> --out ../data_dumps/trackb/gold_x.jsonl --n 30 --seed 7
python manage.py evaluate_tagger --gold ../data_dumps/trackb/gold_x.jsonl \
    --models <model> --mode anchored --course <id> --out ../data_dumps/trackb/report_x.json
```

`make_gold` also takes `--eval-jee <file>` instead of `--course`;
`evaluate_tagger` takes `--exam <key>` instead of `--course`, and `--limit N`.
`--mode anchored` mirrors the bank path (the topic is known); `--mode blind`
mirrors the mock path (the tagger must choose the topic). Gold files and
reports must live under `data_dumps/` (the commands enforce it); saved items
hold ids and keys only. On Windows set `PYTHONIOENCODING=utf-8` when
redirecting output (it contains non-ASCII).

**Data rules:**

- `eval_jee` has no licence and is local-only. `import_eval_jee` refuses
  unless DEBUG is on, the tenant subdomain starts with `lab-`, and the
  database is local.
- Production keys are never used for experiments.
- Only question text goes to the model.
