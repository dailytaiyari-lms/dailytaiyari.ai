# Deployment Guide

How the DailyTaiyari backend is deployed and operated. The frontend (student
app) and landing site deploy automatically via Netlify and are out of scope
here.

> **No secrets in this doc.** IPs, SSH keys, DB credentials, storage keys and
> passwords live only on the VMs / in the secrets store — never in the repo.
> Placeholders like `<prod-vm-ip>` are used below.

## Environments

DailyTaiyari runs two independent backend environments. They share **no data**
and live in **separate Azure accounts / resource groups**.

| Aspect         | Pre-prod (testing)            | Prod                              |
| -------------- | ----------------------------- | --------------------------------- |
| Branch         | `main`                        | `production`                      |
| API hostname   | `api.dailytaiyari.in`         | `api-prod.dailytaiyari.in`        |
| Purpose        | Validate every merge          | Live customer traffic             |
| Database       | Its own Azure PostgreSQL      | Its own Azure PostgreSQL          |
| Media storage  | Its own Azure Blob container  | Its own Azure Blob container      |

See [branching-strategy.md](./branching-strategy.md) for how code flows between
them and [environment-variables.md](./environment-variables.md) for the full
list of required env keys.

## Architecture (per environment)

Each VM runs the same Docker Compose stack:

| Service        | Role                                            |
| -------------- | ----------------------------------------------- |
| `web`          | Django + Gunicorn (API)                         |
| `nginx`        | TLS termination + reverse proxy                 |
| `redis`        | Celery broker / cache                           |
| `celery-worker`| Async tasks (email, async code judging, etc.)   |
| `celery-nbworker` | Notebook/lab grading (`notebooks` queue)     |
| `celery-aiworker` | AI authoring — course + lab generation (`aigen` queue) |
| `piston`       | Sandboxed code execution engine                 |
| `piston-init`  | One-shot: installs Piston's language runtimes   |
| `nbrunner`     | Sandboxed notebook/lab execution engine         |

The three Celery workers are split by queue so a multi-minute LLM call or a
notebook that trains a model can't head-of-line block a quick coding
submission. See [Labs](./notebooks-labs.md) for the split and its rationale.

> **If `celery-aiworker` isn't running**, AI generation jobs are enqueued and
> then silently never execute — they sit at `queued` with no error. Check all
> workers are up after any deploy.

- **Database:** managed **Azure PostgreSQL Flexible Server** (SSL required). The
  `db` service in `docker-compose.yml` is unused in cloud deploys.
- **Media:** **Azure Blob Storage**, served as public blob URLs.
- **TLS:** Let's Encrypt certs per hostname, auto-renewed via a certbot deploy
  hook that reloads nginx.
- **Sandboxes:** neither `piston` nor `nbrunner` publishes ports — they are
  reachable only on the internal Docker network. Never add a `ports:` mapping.

### Piston language runtimes

Piston starts with an **empty package store**. Its language runtimes live in the
`piston_data` volume, so any fresh volume — first boot, `docker compose down -v`,
a volume prune, or a VM rebuild — leaves `piston` running and reporting **"Up"**
while it has *zero* languages installed. In that state every `/api/v2/execute`
call fails, `coding/services.py` raises `EngineError`, and the API returns **503
on every Run/Submit**. This exact failure went unnoticed on prod for five weeks.

Two guards make this self-healing; neither should be removed:

- **`piston-init`** (`backend/deploy/piston/provision.sh`) runs on every
  `compose up` and idempotently installs the runtimes listed in
  `backend/coding/languages.py`. It exits 0 immediately when they're all present.
  Keep the script's `PACKAGES` list in sync when adding a language — note that
  installing `gcc` is what provides the `c++` runtime.
- **`piston`'s healthcheck** asserts `/api/v2/runtimes` is *non-empty* rather
  than merely that the port is open, so a runtime-less engine shows as
  `unhealthy`. Its `start_period` is deliberately long (10m) because a cold
  install of gcc takes several minutes.

To check the engine by hand:

```bash
# On the VM — should list python 3.12.0, java 15.0.2 and c++ 10.2.0:
docker compose exec -T web python -c \
  "import requests;print(requests.get('http://piston:2000/api/v2/runtimes',timeout=10).text)"
```

`GET /api/v1/coding/meta/?health=1` reports the same thing through the API and is
`{"ok": false, "missing": [...]}` whenever a required runtime is absent.

## Configuration

All config is via `backend/.env` on the VM (never committed). Each environment
has its own `.env` with its own `SECRET_KEY`, DB, storage, and `ALLOWED_HOSTS` /
`CORS_ALLOWED_ORIGINS`. See [environment-variables.md](./environment-variables.md).

## Which branch each VM tracks

Each VM's checkout is pinned to its environment's branch, so a plain
`git pull --ff-only` always pulls the right code:

| VM        | Tracks branch |
| --------- | ------------- |
| Pre-prod  | `main`        |
| Prod      | `production`  |

One-time pin on the prod VM:

```bash
git fetch origin
git checkout production
git branch --set-upstream-to=origin/production
```

## Deploy procedure

SSH to the target VM (use that environment's key), then in the repo root:

```bash
# 1. Pull the environment's branch
git pull --ff-only

# 2a. Code-only change (no new deps, no migration):
docker compose restart web

# 2b. Dependency change (requirements/Dockerfile):
docker compose up -d --build web

# 2c. Migration in the release:
#     entrypoint.sh auto-runs migrate + collectstatic on web start,
#     so a rebuild/restart applies them. To run manually:
docker compose exec -T web python manage.py migrate
```

Deploy **pre-prod from `main`** first; deploy **prod from `production`** only
after promotion (see branching doc). The canonical, secret-aware runbook lives
in the `deploy-backend` skill under `.github/skills/`.

## Deploying a release that adds a service

A `restart` only restarts what is already running, so a release that introduces
a **new Compose service** needs extra steps — and missing them fails *silently*
(the API is healthy, but jobs on the new worker's queue never run). The labs
release added `nbrunner`, `celery-nbworker` and `celery-aiworker`; use it as the
template.

```bash
# 1. New env keys first — check against docker-compose.yml and the env doc.
#    Back up before editing, and only append keys that are missing.
cp .env .env.bak.$(date +%Y%m%d%H%M%S)

# 2. Build the new images (a new sandbox is a new image; workers usually
#    reuse the web image but must still be built to exist locally).
docker compose build <new-services>

# 3. Migrations for any new app.
docker compose exec -T web python manage.py migrate <app>

# 4. Start the new services, then recreate web so it picks up new env.
docker compose up -d <new-services>
docker compose up -d web

# 5. Verify every service is up — not just web.
docker compose ps
```

Then confirm the new services are actually *doing* their job: check a worker
logged the queue and tasks you expect, and that `web` can reach a new sandbox
over the internal network. The labs checklist is in
[notebooks-labs.md](./notebooks-labs.md#operating-notes).

## Verify a deploy

```bash
# API docs should return 200 over HTTPS
curl -s -o /dev/null -w '%{http_code}\n' https://<hostname>/api/docs/

# Containers healthy
docker compose ps

# All three Celery workers consuming their queues
docker compose logs celery-worker celery-nbworker celery-aiworker | grep -A4 'queues'

# Recent logs if anything is off
docker compose logs web --tail=50
```

For prod, `<hostname>` is `api-prod.dailytaiyari.in`; for pre-prod,
`api.dailytaiyari.in`.

> A bare `curl` of a tenant-scoped endpoint returns
> `{"error": "X-Tenant-ID header is required."}` — that means the API is **up**,
> not broken.
>
> `[ERROR] Control server error: [Errno 13] Permission denied: '/nonexistent'`
> in the `web` logs is harmless gunicorn noise, not a deploy failure.

## TLS certificates

- Issued per hostname via certbot (`--standalone`; nginx must be stopped briefly
  to free port 80 on first issuance).
- A deploy hook reloads nginx automatically on renewal; no manual action needed.

## Rollback

Every prod deploy is tagged `prod-YYYY.MM.DD`. To roll back, check out the
previous tag on the prod VM and restart:

```bash
git checkout prod-<previous-date>
docker compose up -d --build web
```

If the bad release included a migration, assess whether it is
backward-compatible before rolling back the code.

## First-time environment provisioning

Standing up a brand-new environment (VM + Azure PostgreSQL + Blob + TLS + first
tenant/admin) is documented step-by-step in the `deploy-backend` and
`manage-tenants` skills under `.github/skills/`. High level:

1. Create RG, VM (x64), open ports 22/80/443.
2. Install Docker + Compose, clone the repo, check out the env branch.
3. Create Azure PostgreSQL Flexible Server + database; allow the VM IP; SSL on.
4. Create Storage account + `media` container (Blob public read).
5. Write `backend/.env`; bring up app services (without nginx) so migrations run.
6. Point DNS at the VM, issue Let's Encrypt cert, bring up nginx.
7. Create the first tenant + admin (see `manage-tenants`).
