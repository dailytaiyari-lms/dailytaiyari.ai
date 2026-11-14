# UAT environment + CI/CD — design

Status: **design approved 2026-11-14; nothing has been created yet** (no Azure resources, no workflows, no code changes). Every Azure write needs the owner's explicit go-ahead at implementation time.
Related: `azure-prod-inventory.md` (what exists today), `cicd-readiness.md` (gates/constraints), `deployment-current.md` (manual flow being replaced), `known-issues.md`.
Conventions: no secrets, IPs, subscription/tenant IDs or tenant UUIDs in this file. Prices are Azure retail list prices (centralindia, USD), approximate, and the disk/IP lines are unverified.

## 1. Goal

A cost-efficient UAT that exists only while someone is testing, with a real CI/CD pipeline in front of it:
- every PR is gated by automated checks (no Azure needed);
- any commit can be deployed to UAT on demand, tested end to end including a staging frontend, then torn down to near-zero cost;
- UAT replaces the old pre-prod (which lives in a different Azure account and is not touched by this work);
- the same immutable image that passed UAT is what later goes to prod (prod promotion is a separate design, section 12).

Non-goals: changing prod, merging the intelligence layer, fixing the high-severity findings in `known-issues.md`, monitoring/alerting stack.

## 2. Decisions

| Topic | Decision |
|---|---|
| Home | This subscription, **own resource group** (e.g. `dailytaiyari-uat-rg`), never mixed with prod resources |
| Compute | **One on-demand VM, same size as prod (B2as_v2)**, same Docker Compose stack; deallocated when idle |
| Database | Postgres 16 as the compose `db` container on the VM disk (not managed Postgres: a stopped Flexible Server auto-restarts after 7 days and still bills storage) |
| Frontend staging | **Azure Static Web Apps, Free tier** |
| Registry | Azure Container Registry Basic (VM managed identity pulls: no registry password on the VM). Fallback to save ~$5/mo: GHCR |
| CI/CD | GitHub Actions; Azure auth by **OIDC** (no stored Azure secrets); infra as **Bicep** |
| Deploy transport | `az vm run-command` (no inbound SSH) |
| DNS | Hostinger (owner adds records by hand; we never touch it) under `dailytaiyari.in` |
| UAT data | **Never raw prod data in UAT.** Two synthetic "shadow tenants" cloned from the *configuration* of `codeminors` and `joinloop` |
| Migration safety | Optional **migration rehearsal** job against a throwaway restore of prod data, run only on releases that touch migrations, only with per-run owner approval |

## 3. Why not the alternatives
- **Azure Container Apps scale-to-zero:** cannot run Piston (needs privileged mode) and handles long-running Celery workers poorly.
- **Smaller always-on UAT:** simple, but pays 24x7 for something used a few hours a month.
- **Managed Postgres for UAT:** see Decisions.
- **Netlify for staging frontend:** works, but the user accepted SWA and it keeps UAT billing/identity inside Azure and OIDC.

## 4. Resources in the UAT resource group
| Resource | Notes |
|---|---|
| VM (B2as_v2, Ubuntu 24.04, centralindia) | system-assigned managed identity; **NSG: 80/443 only, 22 closed** (break-glass = owner adds a temporary NSG rule); Standard SSD OS disk ~64 GB (Piston/images need room; prod uses 16/29 GB) |
| Static public IP (Standard) | stays allocated while the VM is deallocated, so `uat-api` DNS never changes |
| Key Vault (Standard, RBAC) | runtime secrets; VM identity reads them; deploy renders `.env` (mode 600) |
| ACR Basic | images tagged with git SHA; VM identity has AcrPull |
| Storage account (Standard_LRS) | separate media container; separate account/key from prod |
| Static Web Apps (Free) | one per frontend (see section 9) |
| Budget alert | monthly, on the RG, emails owner at 50/80/100 % |
| VM auto-shutdown schedule | daily fixed time; independent of GitHub, so a dead workflow cannot leave UAT running |

Pre-check before creating: regional vCPU quota (`az vm list-usage`, read-only). Prod already uses 2 vCPUs; a low-quota subscription may not allow a second B-series VM.

## 5. Lifecycle (cost control)
1. **`uat-up`** (manual `workflow_dispatch` with `ref`, or PR label `deploy-uat`): start VM -> wait for agent -> render `.env` from Key Vault -> pull images for `<sha>` -> run migrate (explicitly, see section 10) -> start compose -> smoke tests -> deploy staging frontends -> post URL + TTL on the PR/run summary. Sets VM tag `expires-at` (default +4 h, input to extend).
2. **`uat-down`** (manual): deallocate VM (compute billing stops; disk and IP remain).
3. **`uat-ttl`** (hourly schedule): deallocate if `expires-at` has passed.
4. Backstops, independent of the workflows: VM auto-shutdown schedule; budget alert.
5. A `concurrency: uat` group serialises all three so they cannot race.
6. UAT DB persists on the VM disk across stop/start; an input `reset-data: true` rebuilds it from the shadow-tenant seed.

## 6. CI/CD pipelines
- **`ci.yml` (every PR, no Azure):** backend tests on a Postgres service container (`python manage.py test`), `makemigrations --check --dry-run` (also fails on two leaf migrations in one app, the exact conflict the intelligence merge hits), build the three frontends (`exam-frontend`, `superadmin-frontend`, `landing-page`), `docker build` of the backend image, secret scan (gitleaks), dependency audit as non-blocking report.
- **`build.yml` (push to `main`):** build backend image once, tag `:<sha>`, push to ACR; also push nothing mutable like `:latest` for deploys.
- **`uat-up` / `uat-down` / `uat-ttl`:** section 5.
- **Prod:** out of scope here; constraint is that prod deploys the **same image digest** UAT tested, behind a manual approval.
- **Azure identity:** one GitHub OIDC federated credential bound to the repo + `uat` GitHub Environment. Roles are minimal and scoped to the UAT RG only: start/deallocate/run-command on the VM, AcrPush on the registry. It has no access to the prod RG. Role assignments themselves are created once by the owner (the CI identity cannot grant roles).
- **Bootstrap vs. pipeline:** the owner applies the Bicep once (RG, network, VM, KV, ACR, storage, SWA, budget, schedule, identity, role assignments). The pipeline never creates infrastructure.
- **Branch flow:** PR -> CI -> merge to `main` -> image built -> deploy that SHA to UAT on demand -> promote to `production` branch/prod (prod mechanics unchanged until phase 4).

## 7. Runtime configuration & secrets
- UAT gets **its own** `SECRET_KEY` and `FIELD_ENCRYPTION_KEY` (prod does not set the latter; UAT should, so the encryption path used in future is exercised).
- Separate AI keys with spend caps (Gemini/OpenAI/Azure OpenAI); **never reuse prod keys**. Payment gateways in sandbox/test mode only.
- GitHub Environment `uat` holds only non-Azure CI secrets (SWA deployment tokens). Everything the app needs at runtime lives in Key Vault.
- `ALLOWED_HOSTS` / `CORS_ALLOWED_ORIGINS` set to the UAT hostnames; the dynamic CORS list from `Tenant.allowed_origins` is rewritten by the seed (section 8).
- Container image config: compose override `docker-compose.uat.yml` (image pulled by `IMAGE_TAG`, **no `.:/app` bind mount**, nginx server name templated, Piston and nbrunner on internal network only).

## 8. UAT data: shadow tenants for `codeminors` and `joinloop`
Why not just copy prod: real student data includes minors, and a prod dump carries live payment-gateway and AI credentials in `core_paymentgateway` and the tenant integration tables.

What carries over (configuration only): features and feature locks, registration schema, plan/quotas, enrolment flags, branding, landing-page sections and legal documents, advanced settings, Zoom/gateway *shape* (test mode, no secrets). Note `codeminors` has customer email domains registered in prod with failed verification; UAT does not register real domains (mail goes through the existing pre-prod sender domain, see section 11).

Mechanism:
1. **`export_tenant_config`** (new management command): read-only, run once on prod via run-command **with the owner's approval**; emits JSON containing only the config above for the two named tenants: no users, no student data, no secrets. Stored in a private blob container in the UAT storage account (not in git; it contains real branding/legal text and real hostnames).
2. **`load_tenant_config`** (new): creates the two UAT tenants with **freshly generated UUIDs**, rewrites `allowed_origins` and any hostnames to UAT hosts, blanks all credentials. The new UUIDs are what the UAT frontends bake in as `VITE_TENANT_ID`.
3. **`seed_uat_content`** (new, replaces the stale tenant-less `seed_data`): per tenant, one tenant admin, one teacher, a few students, a small course/questions/quiz set, all with generated passwords kept in Key Vault.
4. Re-run steps 1-2 whenever either tenant's configuration changes materially.

## 9. Staging frontend
- Azure Static Web Apps (Free). Builds: `exam-frontend` x2 (one per shadow tenant, each baking its UAT `VITE_TENANT_ID` + `VITE_API_URL`), `superadmin-frontend` x1. `landing-page` (Next.js 16) is phase 2 pending a check that it works on SWA (static export or the SWA hybrid mode).
- Hostnames (proposed): `uat-api.dailytaiyari.in` (A record to the static IP), `uat-codeminors.dailytaiyari.in`, `uat-joinloop.dailytaiyari.in`, `uat-admin.dailytaiyari.in` (CNAMEs to SWA). The owner adds these at Hostinger; the pipeline never edits DNS.
- Verified 2026-11-14: `exam-frontend/scripts/inject-meta.mjs` fetches tenant branding from the API at build time but **never fails the build** (it logs a warning and keeps default meta tags), so staging builds do not depend on the API being awake; only link-preview tags fall back to defaults. SWA Free limits (apps per subscription, custom domains per app) still to be confirmed.
- When the API is asleep the staging frontend should show a "UAT is asleep, run `uat-up`" notice instead of a broken page (small frontend change).
- TLS for the API: certbot HTTP-01 on the VM; certificates persist on the disk across stop/start.

## 10. Migration rehearsal (optional gate)
Reason: 12 migration files on `main` use `RunPython`/`RunSQL` and several backfill data; migrations can pass on synthetic data and fail on real rows. Two shadow tenants cannot catch that.

Flow (headless, never reachable by humans or frontends): UAT VM `pg_dump`s the prod DB through a **read-only role** straight into a throwaway Postgres container, runs `migrate` with the candidate image, runs `manage.py check`, reports pass/fail, destroys the container and volume.
- Run only when the release adds/changes migrations; **the owner approves every run**.
- Needs one prod-side change, to be approved separately: a read-only DB role. Its credential lives in Key Vault. Run off-peak (prod Postgres allows only 50 connections).
- Residual risk accepted: raw prod rows briefly exist on an encrypted UAT disk inside a container nobody can reach. If the owner later dislikes this, fall back to sanitised-dump-only and accept that data-migration failures surface on the real deploy.
- Hardening note: if prod's "Allow all Azure services" firewall rule is ever removed, add a rule for the UAT static IP first.

## 11. Safety rails in UAT
- **Outbound email guard** (new, `EMAIL_ALLOWLIST` setting in the central send path in `notifications`/ACS backend; exact location found during planning): in UAT only allow-listed recipients get mail, everything else is logged and dropped. Sender uses the existing pre-prod ACS sender domain, not a prod domain.
- No real payment keys, no real Zoom, no prod AI keys (section 7).
- `PLATFORM_NOTIFICATION_EMAIL` explicitly set in UAT (prod currently falls back to a hardcoded personal address).
- UAT is publicly reachable but holds only synthetic data and test credentials; SWA Free has no password protection, so rely on that and rate limits.

## 12. Code/config changes this needs (small, none made yet)
1. `entrypoint.sh`: make `migrate` opt-in (`RUN_MIGRATIONS=1`) so CI/pipeline controls it.
2. `nginx.conf`: template the server name/cert paths (envsubst via nginx templates) instead of the hardcoded API host.
3. `docker-compose.uat.yml`: image pull + no bind mount + internal-only sandboxes.
4. `EMAIL_ALLOWLIST` guard.
5. Management commands: `export_tenant_config`, `load_tenant_config`, `seed_uat_content`.
6. Health endpoint for smoke tests (verify whether one exists on `main`).
7. Frontend "UAT is asleep" notice; `inject-meta.mjs` resilience if needed.
8. Repo hygiene already needed: `.gitignore` covers `data_dump/`, `.env*`, `*.bak*`.

## 13. Cost model (approximate)
| Item | Estimate / month |
|---|---|
| VM $0.0492/h x 40-100 h | $2-5 |
| OS disk, Standard SSD ~64 GB | ~$5 (unverified) |
| Static IP | ~$3.65 |
| ACR Basic | ~$5 |
| Key Vault, storage, SWA Free | ~$0-1 |
| **Total** | **~$15-20** |

Same VM always-on would be ~$36/month for compute alone. Budget alert threshold suggestion: $25.

## 14. Phasing
1. **Phase 0, no Azure:** `ci.yml`, `.gitignore`, baseline test run, fix whatever CI exposes.
2. **Phase 1, infrastructure (needs explicit approval per step):** quota check, Bicep review, owner applies it, OIDC identity, Hostinger DNS records, UAT secrets/keys created.
3. **Phase 2, deploy path:** `build.yml`, compose/nginx/entrypoint changes, `uat-up/down/ttl`, shadow-tenant commands (including the one approved read-only run on prod), staging frontends.
4. **Phase 3:** migration rehearsal job (includes the read-only DB role approval).
5. **Phase 4, separate design:** prod promotion pipeline (same digest + approval) and prod hardening (SSH closed, Postgres firewall, backups, Key Vault, `.env` perms, `FIELD_ENCRYPTION_KEY`, scheduler for periodic commands), then the intelligence-layer rollout (`intelligence-rollout.md`).

## 15. Open items
- Which of `codeminors`/`joinloop` has unusual settings beyond what the export captures (Zoom, custom domain, gateway) is unknown; the exporter captures whatever is in the config tables, and the first run will show the answer.
- UAT AI keys and sandbox payment keys must be created by the owner.
- Old pre-prod (other Azure account) is not inspected or modified; decommission is a later, separate decision.
- Baseline measured 2026-11-14 (local, sqlite, Windows): 334 backend tests, 1 real failure (stale guardian email in `users/views.py`; fix planned in Phase 0) and 4 ffmpeg errors that are Windows-only (`/dev/null`); Linux CI confirms. `makemigrations --check` is clean. `exam-frontend`'s lockfile lacks the Windows rollup binary, so it only builds on Linux/macOS.
