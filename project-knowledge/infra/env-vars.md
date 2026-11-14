# Environment variables & secrets catalogue (names only — NO values)

> Derived from `backend/dailytaiyari/settings.py`, `backend/docker-compose.yml`, `content/hls.py`, `content/tasks.py`, `deploy/nbrunner`
> on `origin/main` @ 7287616, plus the frontend `VITE_*` usage. Read with `python-decouple` (`config()`): real env vars win, else `backend/.env`
> (bind-mounted into the container at `/app/.env`). "Secret" = must come from a secret store in CI/CD / Key Vault, never plaintext in a repo or workflow.

## Backend — core / security
| Var | Secret | Default | Purpose |
|---|---|---|---|
| `SECRET_KEY` | **yes** | insecure dev key | Django secret; also fallback Fernet key source if `FIELD_ENCRYPTION_KEY` unset (rotating it then breaks stored tenant secrets) |
| `FIELD_ENCRYPTION_KEY` | **yes** | derive from SECRET_KEY | Fernet key for encrypting tenant payment/AI/Zoom secrets at rest (`core/encryption.py`). Set explicitly in prod |
| `DEBUG` | no | `True` (!) | Must be `False` in cloud; also flips EMAIL_PROVIDER default and enables security headers/HSTS/SSL-redirect when False |
| `ALLOWED_HOSTS` | no | localhost | per-env API hostname |
| `CORS_ALLOWED_ORIGINS` | no | localhost:3000 | CSV; settings.py additionally hardcodes 3 external tenant origins + regexes `*.dailytaiyari.in/.ai` |
| `SECURE_SSL_REDIRECT` | no | `True` when not DEBUG | |

## Database
`DB_HOST` (presence switches from SQLite to Postgres), `DB_NAME`, `DB_USER`, `DB_PASSWORD` (**secret**), `DB_PORT` (5432), `DB_SSLMODE` (`require` on Azure), `DB_CONN_MAX_AGE` (60). Compose also passes `DB_*` into the unused local `db` service.

## Storage
`STORAGE_BACKEND` = `azure` | `s3` | `local` (legacy `USE_S3=True` forces s3). Azure: `AZURE_ACCOUNT_NAME`, `AZURE_ACCOUNT_KEY` (**secret**), `AZURE_CONTAINER` (media), `AZURE_CUSTOM_DOMAIN`, `AZURE_URL_EXPIRATION_SECS`. S3 (legacy): `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` (**secret**), `AWS_STORAGE_BUCKET_NAME`, `AWS_S3_REGION_NAME`. Static files are served by nginx from a volume (collectstatic at boot), not from blob storage.

## Email
`EMAIL_PROVIDER` (`azure`|`smtp`|`console`), `DEFAULT_FROM_EMAIL`, `AZURE_COMMUNICATION_CONNECTION_STRING` (**secret**, ACS data-plane send), SMTP alt: `EMAIL_HOST/PORT/USE_TLS/HOST_USER/HOST_PASSWORD(secret)`, `PLATFORM_NOTIFICATION_EMAIL` (lead inbox; a personal address is the default in code), `BACKEND_PUBLIC_URL`, `FRONTEND_URL`.
Tenant **verified email domains** (Azure ARM management plane — separate root-owned file `/etc/dailytaiyari/azure-email-management.env`, injected into `web` only): `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET` (**secret**), `AZURE_SUBSCRIPTION_ID`, `AZURE_EMAIL_RESOURCE_GROUP`, `AZURE_EMAIL_SERVICE_NAME`, `AZURE_COMMUNICATION_RESOURCE_GROUP`, `AZURE_COMMUNICATION_SERVICE_NAME`, `AZURE_COMMUNICATION_API_VERSION`; compose var `AZURE_EMAIL_MANAGEMENT_ENV_FILE` overrides the file path. Service principal needs Communication + Email Service Contributor.

## AI
`OPENAI_API_KEY` (**secret**, platform default LLM key; tenants can bring their own provider config stored in DB — `chatbot.AIProviderConfig` + resolver), `AI_READ_TIMEOUT` (90s, in-request, must stay < gunicorn `timeout` 120), `AI_READ_TIMEOUT_BACKGROUND` (600s, Celery). Async toggles: `COURSEGEN_ASYNC`, `MOCKGEN_ASYNC`, `NOTEBOOKS_GEN_ASYNC` (all default True → need `celery-aiworker` running or jobs sit in `queued`).
Note: Celery `CELERY_TASK_TIME_LIMIT=180`/`SOFT=150` is global — long LLM jobs rely on per-task overrides (check `coursegen`/`mockgen` task decorators) — see their app docs.

## Celery / Redis
`CELERY_BROKER_URL` (redis://redis:6379/0), `CELERY_RESULT_BACKEND` (…/1), `REDIS_URL` (optional → Django cache on Redis /2 else LocMem), `CELERY_VISIBILITY_TIMEOUT` (25200s = 7h, must exceed longest task), `CELERY_CONCURRENCY` (1), `CELERY_NB_CONCURRENCY` (1), `CELERY_AI_CONCURRENCY` (4), `CELERY_MEDIA_CONCURRENCY` (1), `CELERY_TASK_ALWAYS_EAGER` (intelligence branch only — local dev without Redis). Queues: `default`, `notebooks`, `aigen`, `media`.

## Feature switches
`CODING_ENABLED` (True), `CODE_JUDGE_ASYNC` (False), `CODE_JUDGE_PARALLELISM` (1; keep 1 unless Piston has dedicated cores), `NOTIFICATIONS_ASYNC` (False), `NOTEBOOKS_ENABLED` (True), `NOTEBOOKS_SERVER_GRADING` (False default; **True in real deployments**), `NOTEBOOKS_JUDGE_ASYNC` (True), `VIDEO_OPTIMIZATION_ENABLED` (True), `VIDEO_HLS_ENABLED` (True).
Per-tenant feature flags live in `core.Tenant.features` JSON (not env): classic features default-enabled when key missing; **opt-in** ones (`Tenant.OPT_IN_FEATURES`, e.g. `practice`, `ai_grading` on the intelligence branch) default-disabled.

## Sandboxes / media tooling
`PISTON_URL` (http://piston:2000), `NBRUNNER_URL` (http://nbrunner:2100), `NBRUNNER_PORT` (2100), `PISTON_OUTPUT_MAX_SIZE` (set on the piston container: 65536), `FFMPEG_BINARY`/`FFPROBE_BINARY`, `VIDEO_REMUX_TIMEOUT` (3600), `VIDEO_TRANSCODE_TIMEOUT` (6h), `VIDEO_HLS_SEGMENT_SECONDS` (4), `VIDEO_HLS_PRESET` (veryfast).

## Frontends (build-time, baked into bundle — public, not secret)
- exam-frontend: `VITE_API_URL` (e.g. `https://<api-host>/api/v1`), `VITE_TENANT_ID` (UUID — **one Netlify site per tenant**), optional `VITE_SITE_URL`; `inject-meta.mjs` also reads Netlify's `URL`.
- superadmin-frontend: `VITE_API_URL`.
- landing-page: see `frontend/landing-page.md` (written by the frontend explorer) for `NEXT_PUBLIC_*`.

## Things that need a human to confirm on the real VMs (not derivable from repo)
- Which of the above are actually set in each VM's `backend/.env` (pre-prod vs prod differ: separate DB/Blob/ACS/SECRET_KEY).
- Whether `FIELD_ENCRYPTION_KEY` is set in prod (if not, tenant secrets are encrypted with a key derived from `SECRET_KEY`).
- `DEBUG=False` in both envs; `CODE_JUDGE_ASYNC`/`NOTIFICATIONS_ASYNC` actual values.
- Tenant IDs and external tenant origins (kept out of the repo on purpose).
