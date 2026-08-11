# DailyTaiyari — Developer Wiki

Welcome to the DailyTaiyari developer documentation. This wiki covers the platform's **multi-tenant architecture**, APIs, and developer workflows.

## Table of Contents

| Document | Description |
|---|---|
| [Architecture Overview](./architecture.md) | System design, data flow, and multi-tenant approach |
| [Tenant Setup Guide](./tenant-setup.md) | How to create and configure tenants |
| [Backend Guide](./backend-guide.md) | Models, middleware, ViewSets, and services |
| [Frontend Guide](./frontend-guide.md) | Tenant integration, API layer, and branding |
| [Labs (Python Notebooks)](./notebooks-labs.md) | Gradeable notebooks: Pyodide kernel, sandboxed grading, AI generation |
| [Live Classes & Zoom](./live-classes-zoom.md) | Zoom setup per tenant, meeting creation, attendance tracking & export |
| [API Reference](./api-reference.md) | All API endpoints with request/response examples |
| [Environment Variables](./environment-variables.md) | All configurable env vars for backend & frontend |
| [Data Migration Guide](./data-migration.md) | How to migrate data between tenants or backfill |

## Quick Start

```bash
# Backend
cd backend
source .venv/bin/activate
python manage.py runserver

# Frontend
cd frontend
npm run dev
```

## Key Concepts

- **Tenant**: An isolated organizational unit (e.g., a coaching institute). Each tenant has its own students, quizzes, content, and analytics.
- **X-Tenant-ID**: A required HTTP header on all API requests that identifies which tenant the request belongs to.
- **VITE_TENANT_ID**: Frontend environment variable that controls which tenant the deployed frontend instance serves.
- **Lab**: The student-facing name for a gradeable Python notebook. The code, models and API paths still say `notebook` — see [Labs](./notebooks-labs.md).
