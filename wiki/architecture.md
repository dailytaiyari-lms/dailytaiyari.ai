# Architecture Overview

## Multi-Tenant Approach

DailyTaiyari uses a **Shared Database, Shared Schema** multi-tenant architecture. All tenants share the same database and tables, with data isolation enforced by a `tenant` foreign key on every data model.

### Why This Approach?

| Approach | Pros | Cons |
|---|---|---|
| **Separate Database** | Full isolation | Expensive, complex migrations |
| **Separate Schema** | Good isolation | Not supported by SQLite |
| **Shared Schema** ✅ | Simple, cost-effective, easy migrations | Requires careful query filtering |

We chose Shared Schema because:
- Works with SQLite (development) and PostgreSQL (production)
- Single migration path for all tenants
- Easy to scale — adding a tenant is just a database row
- Lower infrastructure cost

---

## System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Frontend (Vite + React)               │
│                                                         │
│  .env: VITE_TENANT_ID=<uuid>                           │
│                                                         │
│  Every API request includes:                            │
│    Header: X-Tenant-ID: <uuid>                         │
└─────────────────┬───────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────────┐
│                Django Backend                            │
│                                                         │
│  ┌───────────────────────────────────────────────────┐  │
│  │ TenantMiddleware                                   │  │
│  │  • Reads X-Tenant-ID header                       │  │
│  │  • Validates UUID & fetches Tenant from DB        │  │
│  │  • Attaches tenant to request.tenant              │  │
│  │  • Returns 403 if missing/invalid (non-exempt)    │  │
│  └───────────────────┬───────────────────────────────┘  │
│                      │                                   │
│  ┌───────────────────▼───────────────────────────────┐  │
│  │ TenantAwareViewSet / TenantAwareReadOnlyViewSet    │  │
│  │  • Filters queryset by request.tenant             │  │
│  │  • Auto-assigns tenant on create                  │  │
│  └───────────────────┬───────────────────────────────┘  │
│                      │                                   │
│  ┌───────────────────▼───────────────────────────────┐  │
│  │ Database (SQLite / PostgreSQL)                     │  │
│  │  • Every table has a tenant_id FK column           │  │
│  │  • Users MUST have a tenant (non-nullable)         │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

---

## Data Isolation Layers

Data isolation is enforced at **three levels**:

### Layer 1: Middleware (Gate)
`core/middleware.py` — `TenantMiddleware`

All API requests (except exempt paths) **must** include a valid `X-Tenant-ID` header. If missing or invalid, the middleware returns a `403 Forbidden` response. The request never reaches any view.

**Exempt paths** (no tenant required):
- `/admin/` — Django admin panel
- `/api/v1/tenant/` — Tenant configuration endpoint
- `/api/docs/`, `/api/redoc/` — API documentation
- `/static/`, `/media/` — Static file serving

### Layer 2: ViewSets (Query Filtering)
`core/views.py` — `TenantAwareViewSet` / `TenantAwareReadOnlyViewSet`

All ViewSets inherit from these base classes which:
- **Filter querysets**: `queryset.filter(tenant=request.tenant)`
- **Auto-assign tenant on create**: `serializer.save(tenant=request.tenant)`
- **Return empty queryset** if no tenant (defense in depth)

### Layer 3: Model Constraints (Database)
`users/models.py` — `User.tenant` is **non-nullable**

A user cannot exist without a tenant. Since all data queries are scoped by the authenticated user (who is tenant-bound), data naturally stays within tenant boundaries.

---

## Tenant Identification Flow

```
Frontend .env          HTTP Request            Middleware              ViewSet
─────────────     ──────────────────     ─────────────────     ──────────────
VITE_TENANT_ID → X-Tenant-ID header → Validate & attach   → Filter queryset
                                        request.tenant        by tenant
```

1. Frontend reads `VITE_TENANT_ID` from `.env`
2. Axios interceptor attaches it as `X-Tenant-ID` header on every request
3. `TenantMiddleware` validates the UUID, fetches the Tenant model, attaches to `request.tenant`
4. ViewSets filter all queries by `request.tenant`

---

## Model Hierarchy

```
Tenant (core.models.Tenant)
├── User (users.models.User) — tenant FK (non-nullable)
│   └── StudentProfile (users.models.StudentProfile) — via TimeStampedModel
├── Exam, Subject, Topic, Chapter — via TimeStampedModel
├── Question, Quiz, MockTest — via TimeStampedModel
├── QuizAttempt, MockTestAttempt, Answer — via TimeStampedModel
├── Content, ContentProgress, StudyPlan — via TimeStampedModel
├── TopicMastery, SubjectPerformance, DailyActivity — via TimeStampedModel
├── Badge, StudentBadge, XPTransaction — via TimeStampedModel
├── Post, Comment, Like — via TimeStampedModel
├── ChatSession, ChatMessage, AIQuizAttempt — via TimeStampedModel
├── Notebook, NotebookTest, NotebookDataset — via TimeStampedModel
│   └── NotebookDraft, NotebookSubmission, NotebookCompletion
└── ... (all models inherit tenant from TimeStampedModel)
```

The `TimeStampedModel` base class includes:
- `id` (UUID, primary key)
- `tenant` (FK to Tenant, nullable for backward compatibility)
- `created_at`, `updated_at` (auto timestamps)

---

## Async Processing

Long-running work runs on Celery rather than in the request thread, with
**queue-per-workload** so a slow job can't block a fast one:

```
                    ┌─ default   ─► celery-worker     (email, code judging)
Django (web) ─ redis ├─ notebooks ─► celery-nbworker   ─► nbrunner  (lab grading)
                    └─ aigen     ─► celery-aiworker   (LLM authoring jobs)
```

Untrusted student code never runs in `web`. It runs in one of two sandboxes —
`piston` for coding questions, `nbrunner` for labs — neither of which publishes
ports, holds credentials, or has database access.

Each async path falls back to inline execution if the broker is unreachable, so
a Redis outage degrades latency rather than breaking the feature. See
[Labs](./notebooks-labs.md) for the full pipeline.
