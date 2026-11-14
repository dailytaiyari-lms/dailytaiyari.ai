# DailyTaiyari.ai — project overview

> Snapshot of `origin/main` @ 7287616 (2026-11-11) = production. Undeployed work is marked **UNDEPLOYED** (see `infra/feature-status.md`).

## What it is
A **multi-tenant, AI-enabled LMS** sold B2B to coaching institutes / academies ("tenants"). Each tenant gets its own branded student site; one shared Django backend and one shared Postgres schema serve everyone, isolated by a `tenant` FK. Originally an Indian exam-prep app (NEET/JEE; README still says so), now a general learning platform: courses → subjects → topics/chapters → content (video/PDF/notes) + quizzes + mock tests + coding problems + Python labs + assignments, with AI authoring tools for teachers and an AI doubt-solver for students.

Company/org: GitHub `dailytaiyari-lms/dailytaiyari.ai`; domains `dailytaiyari.in` (infra) / `.ai` (brand); legal agreements in `legal_docs/` are with a customer ("code_minors"), not part of the product.

## Stack
| Layer | Tech |
|---|---|
| Backend | Python 3.12, Django 5, DRF, SimpleJWT, drf-yasg (Swagger at `/api/docs/`), django-filter, Celery + Redis, gunicorn (gthread) |
| DB | PostgreSQL 16 (Azure Flexible Server in cloud; SQLite for local/tests) |
| Storage | Azure Blob (prod) / S3 (legacy) / local FS; static via nginx volume |
| Email | Azure Communication Services Email (+ tenant verified sender domains via Azure ARM); SMTP/console alternatives |
| AI | multi-provider LLM layer in `chatbot` (OpenAI, Azure OpenAI, Gemini, Anthropic, Groq, OpenRouter, Together, Ollama, custom); per-tenant keys or platform grant |
| Code exec | Piston (coding problems), `nbrunner` (Python labs grading); Pyodide in-browser for labs |
| Video | ffmpeg faststart remux + HLS transcode on a `media` Celery queue |
| Payments | Razorpay / Cashfree / PayU (per-tenant gateway credentials in DB) |
| Live class | Zoom (per-tenant integration) |
| Frontends | exam-frontend (Vite+React18+Tailwind+Zustand+React Query), superadmin-frontend (Vite+React), landing-page (Next.js 16/React 19/Tailwind 4) |
| Hosting | 1 Azure VM per environment (Docker Compose) for backend; Netlify for frontends |

## Repo map
```
backend/                Django project (settings in dailytaiyari/), 21 apps, Dockerfile, docker-compose.yml, nginx/, deploy/{nbrunner,piston}
frontend/exam-frontend/        student + instructor + tenant-admin SPA (one build per tenant)
frontend/superadmin-frontend/  platform operator console (tenants, billing, leads, AI allocations)
frontend/landing-page/main/    Next.js marketing site + demo portal (note nested main/)
wiki/                   human docs (architecture, deployment, branching, env vars, labs, zoom, birthdays)
.github/skills/         runbooks for AI agents: deploy-backend, manage-tenants, populate-data, create-course, post-job
legal_docs/, marketing/ business documents (not code; locally gitignored, uncommitted)
data_dump/              local pg_dump of a real DB (untracked, NOT gitignored — never commit)
project-knowledge/      THIS folder
```

## Roles & surfaces
- **Platform super-admin** (Django superuser, tenant-less) → superadmin-frontend → `/api/v1/superadmin/*` (tenant-exempt).
- **Tenant admin** (`User.role='admin'`) → exam-frontend admin screens → `/api/v1/tenant-admin/*`. Cannot be created via API (Django admin/shell only).
- **Instructor** (`role='instructor'`) → editor screens (EditorRoute = admin|instructor).
- **Student** (`role='student'`).
- **Anonymous/marketing visitor** → landing-page → `/api/v1/platform/*` (leads: demo bookings, contact, job applications).

## Backend apps (one line each; details in `backend/<app>.md`)
| App | Purpose |
|---|---|
| core | Tenant model, middleware, base classes, encryption, superadmin/landing/tenant-admin APIs, platform leads, audit log, announcements |
| users | custom User (email unique per tenant), JWT auth, OTP email verify, registration config, guardian consent, admin provisioning |
| exams | Course/Subject/Topic/Chapter hierarchy, enrolment, syllabus seeders |
| content | notes/video/PDF content, progress, video pipeline (remux/HLS), study flow |
| quiz | question bank, quizzes, legacy + "rich" mock tests, attempts, grading |
| mockgen | AI mock-test builder (draft → apply) |
| analytics | TopicMastery, SubjectPerformance, DailyActivity, streaks, dashboards |
| gamification | XP, levels, badges, challenges, leaderboards (`award_xp` single entry) |
| chatbot | AI doubt solver + **shared LLM provider/budget layer** (also tenant-admin AI endpoints) |
| coursegen | AI Course/Topic Studio (draft → apply) |
| notebooks | Python labs (Pyodide client-side + nbrunner server grading), AI lab generator |
| coding | coding problems judged via Piston |
| assignments | creator-controlled assignments + grading |
| certificates | course-completion certificates + public verify |
| community | posts/comments/moderation/events/course communities |
| liveclass | Zoom live classes + attendance sync |
| jobs | job portal (postings, applications, reports) |
| payments | student pay-to-enrol (Razorpay/Cashfree/PayU), orders, webhooks |
| marketing | promotions / coupons |
| notifications | in-app notifications, branded email, birthday greetings, announcements |
| hackathons | hackathons (quiz/coding stages, AI generation) — on main, wired in settings |
| intelligence | **UNDEPLOYED** learner-intelligence layer (events, tagging, mastery, adaptive practice, AI grading, My Progress) |

API prefix map: `backend/dailytaiyari/urls.py` — `/api/v1/{auth,courses,content,quiz,analytics,gamification,chatbot,community,assignments,coding,live-classes,jobs,certificates,payments,marketing,notifications,notebooks,hackathons,platform,superadmin,landing,tenant-admin[/ai|/course-ai|/mock-ai|/hackathon-ai]}/`, plus `/api/v1/tenant/<uuid>/` (public branding).

## People / process
Contributors: Balbir Yadav (owner, ~537 commits), Saksham-Gupta-off (~149; learning-layer, humanizer), arpit-iitb (~14; intelligence foundation — the user of this session). Flow: feature branch → PR → squash into `main` (pre-prod) → promote to `production` (prod) with tag. Details `wiki/branching-strategy.md`, reality check in `infra/deployment-current.md`.
