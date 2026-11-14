# Azure PRODUCTION subscription — inventory (read-only, 2026-11-14)

> Collected with `az` (list/show only) as the subscription Owner via an isolated CLI profile. **Management plane only**: nothing was run inside the VM, no keys/secrets/connection strings/app settings were read. IPs, subscription/tenant IDs and admin usernames are deliberately omitted (keep it that way).
> Scope: ONE subscription ("Azure subscription 1", Microsoft personal-account guest tenant "Default Directory"). **Pre-prod VM/DB/Blob are NOT in this subscription** (separate account per wiki) — still to inspect.
> Sign-in note: device-code login is blocked by the tenant's security defaults (AADSTS530035); interactive browser login works → CI/CD auth must use a service principal / OIDC, not device code.

## Resource groups
| RG | Region | Contents |
|---|---|---|
| `dailytaiyari-prod-rg` | centralindia | the production app: VM, network, Postgres, Storage, 2× Azure AI Services |
| `rg-dailytaiyari-email-prod` | centralindia | ACS Email + Communication Services for prod |
| `rg-dailytaiyari-email-preprod` | centralindia | ACS Email + Communication Services for **pre-prod** (so pre-prod *email* lives in this subscription though pre-prod compute/DB do not — unverified where) |
| `rg-uparpit603-0360` | southindia | personal AI Foundry project + App Insights + Log Analytics (named after the user; not part of the app as far as visible) |
| `NetworkWatcherRG` | centralindia | auto-created |

## Compute & network (`dailytaiyari-prod-rg`)
- **VM `dailytaiyari-prod-vm`**: Ubuntu 24.04 LTS, **Standard_B2as_v2 (burstable, 2 vCPU / 8 GiB)**, Premium_LRS OS disk, **no data disks**, no zones, SSH-key-only login, **no managed identity, no VM extensions (no monitoring/backup agent)**, boot diagnostics on, no tags, running. This single VM is meant to host: web, nginx, redis, 4 Celery workers, piston (privileged), nbrunner, ffmpeg transcoding, plus the unused local `db` container.
- Network: one VNet (172.16.0.0/16, one subnet), Standard static public IP, no DNS label. **NSG allows inbound 80, 443 and 22 from `*` (SSH open to the internet).**
- No Azure Load Balancer / Front Door / App Gateway / Container Registry / Key Vault / Recovery Services (VM backup) vault / Log Analytics for prod found in the subscription.

## Database
- **`dailytaiyari-prod-pg`** Azure Database for PostgreSQL Flexible Server **v16**, **Burstable Standard_B1ms (1 vCPU, ~2 GiB)**, 32 GB (P4 tier, **auto-grow disabled**), zone 1, **no HA**, **7-day backup retention, no geo-redundant backup**, password auth only (Entra auth disabled), **public network access enabled (no VNet integration)**, `require_secure_transport=on`, TLS ≥1.2, **`max_connections = 50`**, no custom maintenance window.
- Firewall: rule "Allow all Azure services (0.0.0.0)" + one individual client IP rule from 2026-07-30. The VM is therefore reaching the DB via the all-Azure rule.
- Databases: `dailytaiyari` (app) + system DBs.
- Capacity risk (inference): gunicorn = (2×CPU+1)=5 workers × 4 threads + Celery processes (default 1 + nb 1 + ai 4 + media 1) with `CONN_MAX_AGE=60` can approach the 50-connection cap, esp. with the 5 intelligence-layer services added.

## Storage
- **`dtprodmedia2026`**: StorageV2, **Standard_RAGRS**, Hot, HTTPS-only, TLS1.2, **public blob access allowed**, **shared-key access allowed**, network default Allow, blob + container soft-delete 7 days, **versioning off**, no CORS rules. (Container names not enumerated: needs data-plane access.) Matches the app: `STORAGE_BACKEND=azure`, public read URLs.

## AI
- `dailytaiyari-models-resource` (AIServices S0, southindia): deployment **`gpt-5.1`** (model gpt-5.1 2025-11-13, GlobalStandard, capacity 15000), public access enabled, local (key) auth enabled.
- `dailytaiyari-prod-azure-foundry` (AIServices S0, centralindia): **no model deployments** visible.
- How the app consumes these (per-tenant `azure_openai` provider config in the DB vs platform grant vs env) is unknown from Azure alone — check `chatbot.AIProviderConfig`/`TenantAIAllocation` data.

## Email (Azure Communication Services)
- Prod: `dt-email-prod` (+ `dt-comm-prod`): domains `mail.dailytaiyari.in` (**verified: domain/SPF/DKIM/DKIM2**), `mail.codeminors.in` and `classroom.codeminors.in` (customer domains; **verification failed / not started** — DNS records presumably not published).
- Pre-prod: `dt-email-preprod` (+ `dt-comm-preprod`): `preprod-mail.dailytaiyari.in`, `demoppe.dailytaiyari.in`.
- Two service principals hold **Contributor on each email RG** (one per RG) — these are the ARM credentials behind the tenant "verified email domain" feature (`AZURE_CLIENT_ID/SECRET` in `/etc/dailytaiyari/azure-email-management.env`). Activity log (30 d) shows them creating domains / sender usernames / initiating verification; the Owner also cancelled a verification and created 2 role assignments.

## Identity / access
- Subscription roles: the user = Owner (+ Foundry User); the two email SPs = Contributor on their RG only. No other human principals, no CI/CD service principal, no managed identities → **everything today is manual under one personal Owner account**.

## Gaps relevant to CI/CD & operations
1. No registry, no Key Vault, no VM backup, no monitoring/alerting (no Azure Monitor agent / Log Analytics for prod) → build images on VM, secrets in `.env` files, no recovery plan beyond DB 7-day PITR.
2. Single undersized burstable VM + burstable DB with 50 connections = performance and availability ceiling; no zero-downtime deploy possible. Pre-intelligence-layer already near capacity (unverified: check CPU credits/metrics).
3. Attack surface: SSH from anywhere, Postgres public with all-Azure rule, public blob access, shared-key auth on storage.
4. A DB restore/PITR test has never been evidenced (7-day retention, no geo-backup).
5. A CI/CD service principal (OIDC federated credential, least-privilege) does not exist yet and must be created by the Owner.

## Inside the prod VM (read-only run-command, 2026-11-14; 3 scripts, nothing modified, env VALUES not read except a non-secret allow-list)
- **Code**: checkout `~/dailytaiyari.ai` on branch `production` @ `b6d3277` (PR #225, 2026-11-06), upstream `origin/production`, last tag `prod-2026.09.13` (18 commits behind it). Remote is the plain HTTPS GitHub URL (no embedded token). Production branch tip is 4 commits newer but only README (#226/#227) → **effectively current**.
- **Working tree is dirty**: `backend/nginx/nginx.conf` locally modified (4 lines, = hostname/cert paths), plus **9 untracked `.env.bak.*` / `nginx.conf.bak.*` files inside the repo dir** (not gitignored; the `.env.bak.*` copies contain secrets; `git add -A` would stage them). `.env` itself is mode **644** (world-readable).
- **Containers up**: web 7 d, celery-worker / -nbworker / -aiworker / -mediaworker 7 d, nginx/redis/nbrunner/db 3 months, piston 2 months (healthy); `piston-init` is a one-shot (exited, expected). Images were **built ~2 months ago** (web/worker 1.76 GB, `:latest`, no registry) while code is live via the `.:/app` bind mount → the running image is older than the code; any Dockerfile/requirements change since Sept is NOT in the image unless rebuilt (media worker + ffmpeg imply it was rebuilt at least once after Aug). Pinned/old bases: nginx 1.25 (2 y), piston `:latest` (21 months old), postgres:16-alpine local `db` container still running unused.
- **Load**: idle (all containers <1% CPU, web 630 MiB, aiworker 330 MiB); 2.3 of 7.9 GiB RAM used, **no swap**; disk 16/29 GB (57%); Docker volumes 4.6 GB. 15 weeks uptime (no recent reboot/kernel patching evidence).
- **`.env` key names present**: ALLOWED_HOSTS, AZURE_ACCOUNT_KEY/NAME/CONTAINER, AZURE_COMMUNICATION_CONNECTION_STRING, CELERY_BROKER_URL/RESULT_BACKEND/NB_CONCURRENCY/AI_CONCURRENCY, CODE_JUDGE_ASYNC/PARALLELISM, CODING_ENABLED, CORS_ALLOWED_ORIGINS, DB_*, DEBUG, DEFAULT_FROM_EMAIL, EMAIL_PROVIDER, **GEMINI_API_KEY**, NBRUNNER_URL, NOTEBOOKS_*, **OPENAI_API_KEY**, PISTON_URL, SECRET_KEY, SECURE_SSL_REDIRECT, STORAGE_BACKEND. Values: DEBUG=False, DB_SSLMODE=require, STORAGE_BACKEND=azure, EMAIL_PROVIDER=azure, **CODE_JUDGE_ASYNC=True**, NOTEBOOKS_SERVER_GRADING=True, NOTEBOOKS_JUDGE_ASYNC=True.
- **NOT set** (so defaults apply): **FIELD_ENCRYPTION_KEY (tenant payment/AI/Zoom secrets are encrypted with a key derived from SECRET_KEY)**, REDIS_URL (Django cache = per-process LocMem), NOTIFICATIONS_ASYNC (emails sent inline), PLATFORM_NOTIFICATION_EMAIL (**leads go to the hardcoded personal Gmail default**), FRONTEND_URL, BACKEND_PUBLIC_URL, VIDEO_* (defaults), COURSEGEN_ASYNC/MOCKGEN_ASYNC (default True).
- **Azure ARM email-management env file** `/etc/dailytaiyari/azure-email-management.env` exists, root:root 0600 (as documented).
- **Scheduling**: `/etc/cron.d` has only `certbot` and `dt-cert-alert` (+ system); **no user crontabs** → `send_birthday_greetings`, `generate_daily_challenges`, `sync_live_attendance`, `optimize_videos` are NOT scheduled in prod. `certbot.timer` active; cert for the API host valid until 2026-12-31 (renewal due ~Dec 1).
- nginx file on host references only the prod hostname (local edit of the repo file).

## Still unknown (needs VM access, not Azure management plane)
Git commit checked out, branch, `docker compose ps`, which images/versions, `.env` key *names*, crontab, certbot state, nginx config in use, disk usage, whether celery-mediaworker/piston-init/aiworker are actually running. See the read-only command list proposed in the session / `infra/cicd-readiness.md` §6.
