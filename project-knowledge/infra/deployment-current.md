# Deployment — how it works TODAY (manual)

> Source of truth: `backend/docker-compose.yml`, `backend/Dockerfile`, `backend/entrypoint.sh`, `wiki/deployment.md`,
> `.github/skills/deploy-backend/SKILL.md`, as of `origin/main` @ 7287616 (2026-11-11).
> There is **no CI/CD**: no `.github/workflows/` has ever existed on any branch. Everything below is done by hand over SSH.

## Environments

| | Pre-prod | Prod |
|---|---|---|
| Git branch | `main` | `production` (tree identical to `main`; SHAs differ because it's updated via GitHub "Merge pull request" commits, despite wiki saying ff-only) |
| API host | `api.dailytaiyari.in` | `api-prod.dailytaiyari.in` |
| Infra | 1 Azure VM (Docker Compose) in its own Azure account/RG | 1 Azure VM (Docker Compose) in a **separate** Azure account/RG |
| DB | own Azure Database for PostgreSQL Flexible Server (SSL) | own, separate |
| Media | own Azure Blob container (public read) | own, separate |
| Email | Azure Communication Services (ACS) Email | same, separate resource |
| TLS | Let's Encrypt via certbot `--standalone` on the VM; deploy hook reloads nginx | same |

GitHub: `github.com/dailytaiyari-lms/dailytaiyari.ai` (org `dailytaiyari-lms`). Contributors: Balbir Yadav (owner/primary), Saksham-Gupta-off, arpit-iitb.
Tags: `prod-YYYY.MM.DD[-n]` — 29 tags, **last is `prod-2026.09.13`**; production moved on 2026-11-02/06/11 (PR merges #218/#223/#225/#227) **without tags** → rollback points are stale.

## Per-VM Docker Compose stack (`backend/docker-compose.yml` on main)

| Service | Image / build | Role | Notes |
|---|---|---|---|
| `web` | build `.` (python:3.12-slim + ffmpeg) | Django + Gunicorn (gthread, `cpu*2+1` workers × 4 threads, timeout 120s) | entrypoint waits for DB, runs `migrate --noinput` + `collectstatic --noinput` **on every start**. Bind-mounts `.:/app`. Optional `env_file` `/etc/dailytaiyari/azure-email-management.env` (Azure ARM service-principal creds; web only) |
| `nginx` | nginx:1.25-alpine | TLS termination, proxy to `web:8000`, serves `/static/` + `/media/` volumes | ports 80/443; certs from host `/etc/letsencrypt`; `server_name api.dailytaiyari.in` is **hardcoded** in `backend/nginx/nginx.conf` (prod VM must carry a different conf/edit); `client_max_body_size 1024M` |
| `redis` | redis:7-alpine | Celery broker/result (+ optional cache via REDIS_URL) | 256mb, noeviction, no persistence |
| `celery-worker` | same image | default queue: email, code judging, notifications | concurrency `CELERY_CONCURRENCY` (1) |
| `celery-nbworker` | same image | `notebooks` queue (lab grading) | `CELERY_NB_CONCURRENCY` (1) |
| `celery-aiworker` | same image | `aigen` queue (course/mock/notebook AI generation) | `CELERY_AI_CONCURRENCY` (4) |
| `celery-mediaworker` | same image | `media` queue: ffmpeg faststart remux + HLS transcode of lecture videos | `CELERY_MEDIA_CONCURRENCY` (1); **on main only** |
| `piston` | ghcr.io/engineer-man/piston | privileged code-exec sandbox | no published ports; 1 cpu / 1.5G |
| `piston-init` | curlimages/curl | one-shot: installs python 3.12 / java 15 / gcc 10.2 runtimes via `deploy/piston/provision.sh` | needed because Piston's package store is empty on a fresh volume (prod had 503s for 5 weeks before this) |
| `nbrunner` | build `./deploy/nbrunner` | sandboxed notebook grader (port 2100 internal) | read_only, cap_drop ALL, no-new-privileges |
| `db` | postgres:16-alpine | **UNUSED in cloud** (Azure PG used) — but `web` `depends_on: db: service_healthy`, so it still starts | local-dev convenience |
| ~~`celery-beat`~~, ~~`celery-intelworker`~~ | — | **only on the unmerged intelligence branch** (scheduler for nightly/weekly jobs; `intelligence` queue worker). Beat must run as exactly one instance | see `intelligence-rollout.md` |

Volumes: `postgres_data`, `static_volume`, `media_volume`, `piston_data`.
Same Docker image is built separately by every service that has `build: .` (web + 4 workers) on the VM — no registry, no image tags; images are built on the VM.

## Manual deploy procedure (per environment)

1. SSH to the VM (per-env key; transient first-attempt timeouts are common).
2. `cd <repo>` → `git pull --ff-only` (VM tracks `main` for pre-prod, `production` for prod).
3. Depending on diff:
   - code only → `docker compose restart web` (workers are **not** restarted by this — stale task code in workers is a latent bug!)
   - deps / Dockerfile → `docker compose up -d --build web` (+ workers need rebuild too to share the image)
   - new migration → applied by `entrypoint.sh` on web start (or `docker compose exec -T web python manage.py migrate <app>`)
   - new Compose service → append env keys to `backend/.env`, `docker compose build <svc>`, `up -d <svc>`, `up -d web`, verify with `docker compose ps` + worker logs. Missing this fails silently (jobs stay `queued`).
4. Verify: `curl https://<host>/api/docs/` → 200; `docker compose ps`; worker logs show their queues; a bare tenant endpoint returns `{"error":"X-Tenant-ID header is required."}` = API up.
5. Prod only: promote `main` → `production` (ff merge), tag `prod-YYYY.MM.DD`, push, then run the prod deploy.
6. Rollback: `git checkout prod-<prev>` + `docker compose up -d --build web` (migrations are not auto-reversed).

Runbook skills (the "canonical" procedures): `.github/skills/deploy-backend`, `manage-tenants` (create tenant/admin, CORS origin, move/copy course), `populate-data`, `create-course`, `post-job`.

## Configuration & secrets

- Backend config = `backend/.env` **on the VM** (never committed; gitignored). Compose passes selected vars through `environment:` (anything not listed in compose's `&app-env` list is NOT visible to the containers — e.g. `REDIS_URL`, `EMAIL_*`, `AZURE_COMMUNICATION_CONNECTION_STRING`, `FIELD_ENCRYPTION_KEY`, `NOTIFICATIONS_ASYNC` are not in the passthrough list on the older branch — **verify what is actually in prod's `.env`/compose before assuming**; the repo-bind-mounted `.env` is read by `python-decouple` from `/app/.env` anyway, so both paths work).
- Azure ARM management creds (tenant verified-email-domain feature) live in a root-owned `/etc/dailytaiyari/azure-email-management.env` (0600) injected into `web` only.
- Full variable catalogue → `env-vars.md`.
- Per-tenant secrets (payment gateway keys, per-tenant AI keys, Zoom creds) are stored **in the DB**, Fernet-encrypted (`core.encryption`, key = `FIELD_ENCRYPTION_KEY` or derived from `SECRET_KEY`).

## Frontends (not on the VM)

| App | Dir | Host | Build |
|---|---|---|---|
| Student/admin SPA ("exam-frontend") | `frontend/exam-frontend` | **Netlify, one site per tenant** (each has its own `VITE_TENANT_ID` + `VITE_API_URL`) | `npm run build` = `vite build && node scripts/inject-meta.mjs` (fetches tenant branding from the live API at build time to write OG tags; never fails build), publish `dist`, Node 20, SPA redirect |
| Super-admin console | `frontend/superadmin-frontend` | Netlify (`netlify.toml` + `vercel.json` both present) | Vite, `VITE_API_URL` only |
| Marketing/landing + demo portal | `frontend/landing-page/main` (Next.js, note the extra `main/` dir) | Netlify with `@netlify/plugin-nextjs` | `npm run build`, publish `.next` |

Netlify auto-builds on merge to `main`; no Netlify build config pins a branch→environment mapping in the repo (so pre-prod vs prod frontends = separate Netlify sites/contexts, configured in the Netlify UI — **unverified**, check with the owner). Tenant frontends hosted on non-dailytaiyari domains must be added to `CORS_ALLOWED_ORIGINS` in `settings.py` (code change + backend deploy): currently hardcoded entries exist for 3 external tenant origins.

## Known deployment hazards (from reading the repo)

1. `docker compose restart web` after a code change does **not** reload Celery workers → worker/web version skew.
2. Migrations run inside `web` startup; with `restart: unless-stopped` and multiple gunicorn workers a failing migration crash-loops the API.
3. `nginx.conf` hardcodes `api.dailytaiyari.in` for server_name and cert paths → prod VM necessarily has a divergent/edited copy (or the file is edited in place and conflicts on `git pull`). **Check on the VM.**
4. `web` bind-mounts the repo (`.:/app`) — a `git pull` changes live code under a running container; `.env` is also inside that mount.
5. Postgres `db` service is still a hard `depends_on` of `web`.
6. Images are built on the VM with no registry; a rebuild needs build tools + network on the prod host.
7. `backend/deploy/README.md` is an obsolete AWS EC2 guide and contains a default super-admin credential in plaintext (rotate/remove; seed_data default password).
8. Prod tags stopped at 2026-09-13.
