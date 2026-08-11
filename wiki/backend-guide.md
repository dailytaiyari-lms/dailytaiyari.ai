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
