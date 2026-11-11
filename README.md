# DailyTaiyari

**A multi-tenant, white-label B2B learning platform for education and training providers.**

DailyTaiyari enables academies, schools, colleges, coaching institutes, online
education businesses, and corporate training teams to launch and operate their
own branded learning experience. Each organization receives an isolated tenant
workspace with configurable branding, courses, learners, instructors,
assessments, live classes, labs, analytics, AI features, and commercial limits.

![Django](https://img.shields.io/badge/Django-5.x-0C4B33)
![Python](https://img.shields.io/badge/Python-3.12-3776AB)
![React](https://img.shields.io/badge/React-18-61DAFB)
![Node](https://img.shields.io/badge/Node.js-20+-339933)
![License](https://img.shields.io/badge/License-Proprietary-red)

## Platform capabilities

### Tenant and platform management

- Shared-platform, tenant-isolated architecture
- Platform super-admin portal for creating and managing tenants
- Tenant plans, billing lifecycle, suspension, and configurable quotas
- Per-tenant limits for learners, courses, and administrators
- Tenant-specific allowed frontend origins
- Configurable feature availability and platform-enforced feature locks
- Tenant administration for users, instructors, enrollments, and content

### White-label experience

- Tenant logo, favicon, name, tagline, and color theme
- Configurable authentication and landing-page content
- Tenant-specific feature names and navigation visibility
- Custom registration fields and enrollment rules
- Separate frontend deployments configured with `VITE_TENANT_ID`

### Learning delivery

- Courses, subjects, chapters, topics, and rich study content
- Videos, documents, notes, and progress tracking
- Assignments and instructor-managed learning activities
- Quizzes, mock assessments, question banks, and previous papers
- Coding problems executed through an isolated Piston sandbox
- Gradeable Python labs with in-browser Pyodide and server-side regrading
- Live classes through each tenant's own Zoom account
- Certificates, jobs, hackathons, community, and notifications

### AI and analytics

- AI-assisted course, assessment, hackathon, and lab authoring
- Learner-facing AI tutor and doubt-solving workflows
- Tenant-provided AI credentials or platform-supplied model allowances
- Dedicated Celery queue for long-running AI generation
- Learner progress, assessment performance, activity, and tenant-admin reports
- Gamification, streaks, badges, XP, and leaderboards

## User roles

| Role | Scope |
|---|---|
| **Platform super admin** | Manages every tenant, platform plans, quotas, feature locks, and platform-provided AI models |
| **Tenant admin** | Operates one organization: branding, users, courses, features, integrations, analytics, and enrollments |
| **Instructor** | Authors and manages assigned learning content and activities |
| **Learner** | Consumes courses, completes assessments and labs, joins live classes, and tracks progress |

## Multi-tenant architecture

DailyTaiyari uses a **shared database, shared schema** architecture. Tenant-owned
records carry a tenant foreign key and tenant-aware APIs scope queries to the
organization handling the request.

```text
Tenant frontend
  VITE_TENANT_ID
        |
        v
X-Tenant-ID request header
        |
        v
TenantMiddleware
  validates tenant and sets request.tenant
        |
        v
Tenant-aware views and serializers
        |
        v
Shared PostgreSQL database
  records filtered by tenant
```

Most tenant APIs require:

```http
X-Tenant-ID: <tenant-uuid>
```

Platform administration, API documentation, static assets, and selected public
configuration endpoints are tenant-exempt. See
[`wiki/architecture.md`](./wiki/architecture.md) for the isolation model and
request flow.

## Repository structure

```text
DailyTaiyari/
├── backend/
│   ├── core/                 # Tenants, platform admin, branding, plans, quotas
│   ├── users/                # Authentication, roles, learners, enrollments
│   ├── exams/                # Courses and curriculum hierarchy
│   ├── content/              # Learning content and progress
│   ├── quiz/                 # Questions, quizzes, and mock assessments
│   ├── analytics/            # Learner and tenant analytics
│   ├── gamification/         # XP, badges, streaks, and leaderboards
│   ├── chatbot/              # AI tutor and AI provider configuration
│   ├── coursegen/            # AI course authoring
│   ├── mockgen/              # AI assessment authoring
│   ├── assignments/          # Assignments and submissions
│   ├── coding/               # Coding problems and sandboxed judging
│   ├── notebooks/            # Gradeable Python labs
│   ├── liveclass/            # Zoom classes and attendance
│   ├── community/            # Discussions and community activity
│   ├── certificates/         # Certificate issuing
│   ├── payments/             # Tenant-configurable payment workflows
│   ├── jobs/                 # Tenant job board
│   ├── hackathons/           # Tenant hackathons
│   ├── notifications/        # In-app and email notifications
│   ├── marketing/            # Landing and marketing workflows
│   ├── deploy/               # Sandbox and deployment resources
│   └── dailytaiyari/         # Django settings and URL configuration
├── frontend/
│   ├── exam-frontend/        # Tenant learner/admin portal (legacy directory name)
│   ├── superadmin-frontend/  # Platform super-admin portal
│   └── landing-page/         # DailyTaiyari marketing site
├── wiki/                     # Architecture and operational documentation
└── .github/skills/           # Repository-specific operational runbooks
```

## Technology stack

### Backend

- Python 3.12
- Django 5.x and Django REST Framework
- JWT authentication
- PostgreSQL in deployed environments; SQLite is available for local work
- Redis and Celery with workload-specific queues
- Gunicorn and Nginx
- Swagger/OpenAPI through `drf-yasg`
- Azure Blob Storage in deployed environments
- Piston for isolated code execution
- Pyodide and the isolated `nbrunner` service for Python labs

### Frontend

- React 18 and Vite 5
- Node.js 20+
- Tailwind CSS and Material UI
- Zustand and TanStack Query
- Axios, React Router, Recharts, Monaco Editor, and KaTeX

## Local development

### Prerequisites

- Python 3.12+
- Node.js 20+
- npm
- Docker and Docker Compose for the complete service stack

### 1. Start the backend

```bash
cd backend

python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create `backend/.env`:

```dotenv
SECRET_KEY=replace-with-a-local-secret
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://localhost:3100
```

Without `DB_HOST`, Django uses the local SQLite database. Then initialize and
start the application:

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

The backend is available at:

| Service | URL |
|---|---|
| API root | `http://localhost:8000/api/v1/` |
| Swagger | `http://localhost:8000/api/docs/` |
| ReDoc | `http://localhost:8000/api/redoc/` |
| Django admin | `http://localhost:8000/admin/` |

### 2. Create a tenant

Create a tenant through Django admin or the Django shell, then copy its UUID.
The UUID identifies the organization in tenant-scoped requests.

```bash
python manage.py shell
```

```python
from core.models import Tenant

tenant = Tenant.objects.create(
    name="Example Learning Academy",
    subdomain="example-learning",
)
print(tenant.id)
```

See [`wiki/tenant-setup.md`](./wiki/tenant-setup.md) for tenant provisioning and
frontend deployment details.

### 3. Start the tenant portal

The directory is still named `exam-frontend` for historical reasons; it is the
main white-label learner and tenant-admin portal.

```bash
cd frontend/exam-frontend
npm install
```

Create `frontend/exam-frontend/.env`:

```dotenv
VITE_API_URL=/api/v1
VITE_TENANT_ID=<tenant-uuid>
```

Start Vite:

```bash
npm run dev
```

The tenant portal runs at `http://localhost:3000`.

### 4. Start the platform super-admin portal

```bash
cd frontend/superadmin-frontend
npm install
cp .env.example .env
npm run dev
```

The super-admin portal runs at `http://localhost:3100` and is restricted to
tenant-less Django superusers.

### Docker Compose

`backend/docker-compose.yml` defines the production-like backend stack,
including PostgreSQL, Redis, Django, Nginx, Celery workers, Piston, and the
notebook runner. It requires environment-specific configuration and should be
operated using the deployment documentation:

```bash
cd backend
docker compose up -d
```

Never expose the Piston or notebook-runner ports publicly.

## API groups

The canonical URL configuration is in
[`backend/dailytaiyari/urls.py`](./backend/dailytaiyari/urls.py). Major API
groups include:

| Prefix | Purpose |
|---|---|
| `/api/v1/superadmin/` | Platform-wide tenant administration |
| `/api/v1/tenant-admin/` | Tenant settings, branding, plans, and administration |
| `/api/v1/auth/` | Authentication, profiles, and enrollment workflows |
| `/api/v1/courses/` | Courses and curriculum |
| `/api/v1/content/` | Learning content and progress |
| `/api/v1/quiz/` | Questions, quizzes, mock assessments, and attempts |
| `/api/v1/analytics/` | Learner and tenant analytics |
| `/api/v1/chatbot/` | AI tutor and chat sessions |
| `/api/v1/assignments/` | Assignments and submissions |
| `/api/v1/coding/` | Coding problems and judging |
| `/api/v1/notebooks/` | Python labs and grading |
| `/api/v1/live-classes/` | Zoom classes and attendance |
| `/api/v1/community/` | Community features |
| `/api/v1/payments/` | Payment and enrollment payment workflows |
| `/api/v1/notifications/` | Notifications and announcements |

Use the live Swagger documentation or
[`wiki/api-reference.md`](./wiki/api-reference.md) for endpoint-level details.

## Async and sandboxed workloads

Redis and Celery separate long-running workloads so they do not block API
requests:

| Service | Workload |
|---|---|
| `celery-worker` | General tasks and asynchronous code judging |
| `celery-nbworker` | Notebook and lab grading |
| `celery-aiworker` | AI course, assessment, hackathon, and lab generation |
| `celery-mediaworker` | Uploaded-video processing |
| `piston` | Isolated coding-question execution |
| `nbrunner` | Isolated server-side notebook execution |

Both execution services are internal-only and must not be given public port
mappings.

## Deployment

The backend has separate pre-production and production environments:

| Environment | Branch | API |
|---|---|---|
| Pre-production | `main` | `https://api.dailytaiyari.in` |
| Production | `production` | `https://api-prod.dailytaiyari.in` |

Each environment runs on an Azure VM with its own Azure PostgreSQL database and
Azure Blob Storage container. Backend releases are deployed from the branch
tracked by that VM. Tenant frontends and the landing site deploy separately as
static Netlify applications.

Read [`wiki/deployment.md`](./wiki/deployment.md) before operating an
environment. The canonical deployment and tenant-provisioning runbooks are in
the repository skills under `.github/skills/`.

## Branching

Changes flow in one direction:

```text
feature/* or fix/* -> main (pre-production) -> production
```

Development changes are reviewed through pull requests into `main`. Production
is promoted from a tested `main` using a fast-forward-only merge. See
[`wiki/branching-strategy.md`](./wiki/branching-strategy.md).

## Documentation

| Document | Description |
|---|---|
| [`wiki/README.md`](./wiki/README.md) | Documentation index |
| [`wiki/architecture.md`](./wiki/architecture.md) | Tenant isolation and system architecture |
| [`wiki/tenant-setup.md`](./wiki/tenant-setup.md) | Tenant creation and frontend provisioning |
| [`wiki/backend-guide.md`](./wiki/backend-guide.md) | Backend conventions and tenant-aware APIs |
| [`wiki/frontend-guide.md`](./wiki/frontend-guide.md) | Tenant frontend configuration and branding |
| [`wiki/api-reference.md`](./wiki/api-reference.md) | API reference |
| [`wiki/environment-variables.md`](./wiki/environment-variables.md) | Backend and frontend configuration |
| [`wiki/notebooks-labs.md`](./wiki/notebooks-labs.md) | Python lab architecture and operations |
| [`wiki/live-classes-zoom.md`](./wiki/live-classes-zoom.md) | Per-tenant Zoom integration |
| [`wiki/deployment.md`](./wiki/deployment.md) | Deployment and rollback procedures |

## Security notes

- Tenant-owned data must always be filtered by `request.tenant`.
- Tenant frontends must send a valid `X-Tenant-ID`.
- Secrets belong in environment-specific secret storage and must never be
  committed.
- Piston and `nbrunner` are internal sandbox services and must not expose ports.
- Platform super-admin endpoints are tenant-exempt but require Django
  superuser authorization.
- New tenant frontend origins must be explicitly allowed before browser clients
  can call the API.

## License

Copyright DailyTaiyari. All rights reserved.

This repository contains proprietary and confidential software. Unauthorized
copying, distribution, or use is prohibited.
