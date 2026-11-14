# CI/CD readiness assessment (pre-Azure-access)

> Written from repo evidence only (nothing from the Azure accounts yet). Items marked **[ASK/CHECK]** need the Azure/VM/Netlify/GitHub
> side to confirm. Update this file after the Azure analysis.

## 1. What exists today
- **No CI at all.** No `.github/workflows/` on any branch, ever. GitHub org `dailytaiyari-lms`, repo `dailytaiyari.ai`.
- Branch protection (per wiki): `main` = PR required + linear history + no force-push; `production` = no PR requirement, fast-forward promotion; `enforce_admins` off. **[CHECK]** actual GitHub settings (required status checks = none can exist since there is no CI).
- Deploy = SSH + `git pull` + `docker compose` on one VM per environment (see `deployment-current.md`). Frontends = Netlify auto-build on merge, one site per tenant.
- Release markers: `prod-YYYY.MM.DD` tags, last on 2026-09-13 (stale).

## 2. Test & quality gates available to wire in
| Area | State | Implication for CI |
|---|---|---|
| Backend tests | ~335 Django `test_*` methods across 15 files (`manage.py test`); concentrated in coursegen, mockgen, chatbot, hackathons, core(email domain), liveclass, users | Runs on SQLite (no `DB_HOST`) and Celery runs eager under `manage.py test` (`'test' in sys.argv`). **No tests for quiz, payments, coding, notebooks, analytics, assignments, certificates, jobs, notifications, marketing** — the revenue/grade-critical paths are untested |
| Backend lint/type | none (no flake8/ruff/black/mypy config) | add `ruff` + `python manage.py check` + `makemigrations --check --dry-run` as cheap gates |
| Migration safety | 169 migration files on main; entrypoint auto-runs `migrate` on boot | CI should run `makemigrations --check` and `migrate` on a throwaway Postgres 16; pre-prod promotion gate before prod |
| Frontend tests | **none** in any of the 3 frontends | build is the only gate |
| Frontend lint | exam-frontend has `npm run lint` (`eslint src … --max-warnings 0`) but **no ESLint config file exists** → the script would fail as-is; superadmin has none; landing-page has `eslint` (flat config `eslint.config.mjs`) | either add configs or skip lint gate initially; build gate (`vite build`, `next build`) works |
| Frontend build | exam-frontend: Node 20, `vite build && inject-meta.mjs` (calls live API for tenant branding; non-fatal) | CI build needs `VITE_API_URL` + `VITE_TENANT_ID` per tenant |
| Container build | `backend/Dockerfile` multi-stage, python 3.12-slim + ffmpeg; `nbrunner` has its own Dockerfile; `piston` is a public image | all buildable in CI; push to **Azure Container Registry** instead of building on the VM |
| Security scan | none | add dependency audit (pip-audit / npm audit), secret scan (gitleaks) |

## 3. Constraints that shape the pipeline design
1. **Multi-tenant frontends**: `VITE_TENANT_ID` is compiled in → one build (and Netlify site / Azure Static Web App) per tenant, per environment. CI needs a tenant matrix (tenant → site → env vars). Tenant list is operational data **[ASK]**.
2. **Two environments in two separate Azure accounts/RGs** (pre-prod from `main`, prod from `production`). Needs per-environment OIDC federation / service principals and GitHub Environments with approval on prod.
3. **Single VM per env running ~11 containers incl. privileged Piston** — not horizontally scalable as-is; zero-downtime deploys are not possible with a single `web` container + auto-migrations. Decide whether to keep VM+Compose (CI pushes images to ACR and SSHes/`az vm run-command` to `compose pull && up -d`) or move to Azure Container Apps/AKS (Piston `privileged: true` is a blocker for ACA; AKS or keep VM for sandboxes).
4. **Workers share the web image** but `restart web` leaves workers stale → pipeline must restart/recreate *all* app services (web + celery-worker/-nbworker/-aiworker/-mediaworker[/-beat]) together.
5. **Migrations on boot**: move to an explicit pre-deploy step (`migrate` one-off) and keep entrypoint migrate only for dev, or guard against concurrent runners.
6. **nginx.conf hardcodes `api.dailytaiyari.in`** and certs are host-level certbot → prod needs a templated/ENV-driven conf (or Azure Front Door / App Gateway TLS). Certbot `--standalone` needs port 80 free.
7. **Secrets**: today in `backend/.env` on the VM (+ `/etc/dailytaiyari/azure-email-management.env`). Target: Azure Key Vault + managed identity, GitHub Environment secrets for CI only. See `env-vars.md`.
8. **Branch model**: prod promotion is `main → production` (GitHub PR-merge commits in practice; tree-identical). A workflow can trigger on push to `production` and tag automatically (`prod-YYYY.MM.DD-n`).
9. **Rollback** = redeploy previous image tag (with registry-tagged images this becomes trivial; with migrations, only if backward-compatible).
10. **Undeployed work** (intelligence layer, Saksham's branches) adds a `celery-beat` service + ~4 migrations + backfill commands: the pipeline must support "new compose service" releases and one-off management commands (`infra/intelligence-rollout.md`).

## 4. Hygiene items to fix before/while building CI (found while reading)
- `data_dump/` (untracked, a real `pg_dump` of a DB, 3.6 MB) sits in the repo root and is **not gitignored** → add to `.gitignore` / move out; never commit. Local `.gitignore` edit (ignores `legal_docs/`, `marketing/`) is uncommitted.
- `backend/deploy/README.md` (obsolete AWS EC2 guide) documents a default super-admin email + password (and a `SUPERADMIN_PASSWORD` override that the current `core/management/commands/seed_data.py` does not actually read; that command sets a weak fixed password on the users it seeds). **Never run `seed_data` against pre-prod/prod**; rotate any real account that ever used the documented credential; delete/replace the doc.
- **Scheduled work has no scheduler on main**: management commands `send_birthday_greetings`, `generate_daily_challenges`, `sync_live_attendance --hours 24`, `optimize_videos` are meant to be run periodically, but there is no `celery-beat` on main and no cron/workflow in the repo → presumably VM cron **[ASK/CHECK `crontab -l` on both VMs]**. Move these into the pipeline/scheduler when CI/CD is built.
- `SIMPLE_JWT` access token lifetime = **365 days**, refresh 730 days → token theft window; consider shortening.
- `DEBUG` defaults to `True`, `SECRET_KEY` has an insecure default → CI/CD should fail the deploy if `DEBUG!=False` or key is the default.
- `PLATFORM_NOTIFICATION_EMAIL` defaults to a personal Gmail address in code.
- `db.sqlite3` is present in `backend/` of the working tree (gitignored `*.db`/`db.sqlite3`; confirm not tracked).
- Stale local branch: `feat/intelligence-foundation` is 31 commits behind `main`; the most complete intelligence work is `origin/saksham/learning-layer-2b`.
- Wiki `deployment.md` says prod is a ff-only promotion; actual `production` history is PR-merge commits.

## 5. Proposed pipeline shape (to validate against Azure)
```
PR → main:      ci.yml  = backend (ruff, check, makemigrations --check, manage.py test on Postgres service),
                          frontend builds (exam, superadmin, landing), docker build (no push), gitleaks, pip/npm audit
push → main:    deploy-preprod.yml = build+push images to ACR (tag = git sha) → migrate job → roll all services on pre-prod VM
                                      → smoke test (/api/docs/ 200, tenant endpoint, worker queues) ; frontends via Netlify/SWA
push → production: deploy-prod.yml = GitHub Environment "prod" (manual approval) → same image digest as pre-prod →
                                      migrate → roll services → smoke → auto-tag prod-YYYY.MM.DD-n → rollback job on failure
```
Open design decisions are listed in §6.

## 6. Questions for the Azure/ownership session
1. Two separate Azure **accounts** (tenants/subscriptions)? Which resource types per env: VM(s), PostgreSQL Flexible Server, Storage account, ACS Email (+ ARM service principal), Key Vault?, ACR?, Front Door/App Gateway?, Static Web Apps?, Monitor/Log Analytics?
2. VM size/OS/disk, NSG rules, how SSH keys are managed, whether Docker runs rootless, backup/snapshot policy, DB backup/PITR config.
3. Where do the frontends actually deploy (Netlify per tenant vs Azure SWA vs Vercel — both `netlify.toml` and `vercel.json` exist)? List of tenant sites and their env vars.
4. Is pre-prod ≈ prod in size? Is pre-prod data production-like (the `data_dump/` file suggests dumps are used locally)?
5. Preferred deploy target model: keep VM + Compose (lowest change) vs ACR+Container Apps/AKS (needs sandbox strategy for Piston).
6. Monitoring/alerting today (Sentry? Azure Monitor? uptime checks)? Logs are stdout only.
7. Branch protection settings & who can approve prod deployments.
8. Cost guardrails for LLM spend (per-tenant AI usage tracking exists in `chatbot.AIUsageRecord`).
