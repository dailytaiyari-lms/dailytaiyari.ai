# Phase 0 — PR CI Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every pull request to `dailytaiyari-lms/dailytaiyari.ai` is automatically checked (backend tests on Postgres, migration sanity, three frontend builds, backend Docker build, secret scan), and `main` is green so the checks mean something.

**Architecture:** One GitHub Actions workflow `.github/workflows/ci.yml` with four independent jobs (`backend`, `frontend` matrix of 3, `docker`, `secret-scan`). No Azure, no secrets, read-only token. Before the gates go in, `main`'s one real failing test is fixed and repo hygiene gaps (`.gitignore`, missing `.dockerignore`) are closed.

**Tech Stack:** GitHub Actions, Python 3.12 / Django 5 / PostgreSQL 16, Node 20 (Vite 5/React 18 x2, Next.js 16), Docker Buildx, gitleaks 8.18.4.

**Spec:** `project-knowledge/infra/uat-cicd-design.md` §6 (`ci.yml`) and §14 Phase 0. Later phases (Azure infra, deploy path, migration rehearsal) get their own plans because they need Azure approval and depend on what this phase learns.

## Facts verified against `origin/main` (2026-11-14) before writing this plan

- Test runner is Django's: `python manage.py test --noinput` (no `pytest.ini`/`conftest.py`; 15 test files). Full run locally on sqlite: **334 tests, 1 failure, 4 errors**, ~200 s.
- The 4 errors are `content.tests_video_pipeline.RunWithProgressTests.*`. They shell out to `ffmpeg ... -f mp4 /dev/null`, which cannot work on Windows. They are **expected to pass on Linux with ffmpeg installed** — unverified until CI runs, see Task 7.
- The 1 failure is real: `users.tests_registration_consent.ExistingStudentComplianceTests.test_pending_student_can_change_guardian_email`. In `users/views.py` the `request_guardian_approval` branch builds its response from a stale cached `user.guardian_consent`, so the API returns the *old* guardian email after a change. Adding `user.refresh_from_db()` before the final `return` was tried on a scratch copy and made all 19 tests in that module pass.
- `makemigrations --check --dry-run` on `main`: "No changes detected". `makemigrations` also raises on two leaf migrations in one app, which is the conflict the intelligence-layer merge will hit.
- Settings use sqlite unless `DB_HOST` is set; with `DB_HOST` they need `DB_NAME`, `DB_USER`, `DB_PASSWORD` (`DB_PORT` defaults to 5432, `DB_SSLMODE` to empty). `DEBUG` defaults to True.
- Frontends: `exam-frontend` (`npm run build` = `vite build && node scripts/inject-meta.mjs`; the script never fails the build when `VITE_*` is unset or the API is unreachable), `superadmin-frontend` (`vite build`), `landing-page` at `frontend/landing-page/main` (`next build`). All have `package-lock.json`; Netlify uses Node 20.
- `.github/` currently contains only agent `skills/`; there are no workflows. The repo is in a GitHub **organization**, so the `gitleaks-action` (which needs a licence for orgs) is avoided in favour of the gitleaks binary.
- `backend/` has **no `.dockerignore`**, and `Dockerfile` does `COPY . $APP_HOME`, so a local `docker build` would bake `.env` into the image. `.gitignore` on `main` ignores `.env` and `*.bak` but not `.env.bak.<date>` copies, and not `data_dump/`.
- Heads-up (not part of this plan): the uncommitted `.gitignore` edit in the owner's checkout adds a bare `marketing/` line, which also matches the Django app `backend/marketing/`. Do not copy that line into this work; tell the owner.

## File structure

| File | Action | Responsibility |
|---|---|---|
| `backend/users/views.py` | modify | one-line fix for the stale guardian response |
| `.gitignore` | modify | ignore secret-bearing backup files and local data dumps |
| `backend/.dockerignore` | create | keep `.env*`, backups, caches, local DB out of the image |
| `.github/workflows/ci.yml` | create | all PR gates; each job is one gate |

---

### Task 0: Isolated worktree from `origin/main`

The owner's main checkout is on a stale feature branch with uncommitted files. Work in a separate worktree so nothing there is touched.

**Files:** none (git setup only)

- [ ] **Step 1: Fetch and create the worktree**

Run (from `c:\Users\uparp\Desktop\dailytaiyari`):
```bash
git fetch origin
git worktree add ../dailytaiyari-ci -b ci/phase0-gates origin/main
```
Expected: `Preparing worktree (new branch 'ci/phase0-gates')` and `HEAD is now at <sha> docs: update README for B2B learning platform (#226)` (or a newer commit on `main`).

- [ ] **Step 2: Create a virtualenv and install backend requirements**

Run:
```bash
cd ../dailytaiyari-ci
python -m venv .venv
.venv/Scripts/python.exe -m pip install -q -r backend/requirements.txt
```
Expected: no errors (a pip upgrade notice is fine). `.venv` is already gitignored.

- [ ] **Step 3: Confirm the baseline failure**

Run:
```bash
cd backend
../.venv/Scripts/python.exe manage.py test users.tests_registration_consent --noinput 2>&1 | grep -E "^(ERROR|FAIL):|^Ran|^FAILED|^OK"
```
Expected: `FAIL: test_pending_student_can_change_guardian_email ...`, `Ran 19 tests`, `FAILED (failures=1)`.

All following tasks run inside `c:\Users\uparp\Desktop\dailytaiyari-ci`.

---

### Task 1: Fix the failing guardian-email test

**Files:**
- Modify: `backend/users/views.py` (the `request_guardian_approval` branch of `ExistingStudentComplianceView.post`, ends with `return Response(_existing_student_compliance(user))`, around line 401)
- Test (already exists, currently failing): `backend/users/tests_registration_consent.py::ExistingStudentComplianceTests::test_pending_student_can_change_guardian_email`

- [ ] **Step 1: Confirm the test is red**

Already shown in Task 0 Step 3. Do not proceed if it is already green (someone else fixed it; skip this task).

- [ ] **Step 2: Apply the fix**

In `backend/users/views.py`, replace this block (inside `if action_name == 'request_guardian_approval':`):
```python
                return Response(
                    {'error': 'Could not send the approval email. Please try again.'},
                    status=status.HTTP_502_BAD_GATEWAY,
                )
            return Response(_existing_student_compliance(user))
```
with:
```python
                return Response(
                    {'error': 'Could not send the approval email. Please try again.'},
                    status=status.HTTP_502_BAD_GATEWAY,
                )
            # _issue_guardian_consent wrote a new row; drop the cached
            # relation so the response reflects the freshly saved guardian.
            user.refresh_from_db()
            return Response(_existing_student_compliance(user))
```
The match is unique (it is the only `Could not send the approval email` 502 followed by that return).

- [ ] **Step 3: Run the module and see it green**

Run (from `backend/`):
```bash
../.venv/Scripts/python.exe manage.py test users --noinput 2>&1 | grep -E "^(ERROR|FAIL):|^Ran|^FAILED|^OK"
```
Expected: `OK` with no `FAIL`/`ERROR` lines (the whole `users` app, not just the one module, to catch side effects).

- [ ] **Step 4: Commit**

```bash
git add backend/users/views.py
git commit -m "fix(users): return the new guardian after a guardian-email change

The response was built from a cached user.guardian_consent, so a pending
student who changed the guardian email saw the old address in the reply.
Refresh the user before building the response. Fixes the only failing
test on main (test_pending_student_can_change_guardian_email).

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Repo hygiene — `.gitignore` and `backend/.dockerignore`

**Files:**
- Modify: `.gitignore` (append at end)
- Create: `backend/.dockerignore`

- [ ] **Step 1: Prove the gap exists (these files are NOT ignored today)**

Run:
```bash
mkdir -p data_dump
touch backend/.env.bak.20260101 backend/nginx/nginx.conf.bak.20260101 data_dump/x.sql
git check-ignore -v backend/.env.bak.20260101 backend/nginx/nginx.conf.bak.20260101 data_dump/x.sql; echo "exit=$?"
```
Expected: no lines printed and `exit=1` (nothing is ignored).

- [ ] **Step 2: Append ignore rules**

Run:
```bash
cat >> .gitignore <<'EOF'

# Operational leftovers that hold secrets or real data. Never commit.
.env.bak*
*.env.bak*
*.conf.bak*
data_dump/
EOF
```

- [ ] **Step 3: Verify they are now ignored, and a normal file is not**

Run:
```bash
git check-ignore -v backend/.env.bak.20260101 backend/nginx/nginx.conf.bak.20260101 data_dump/x.sql; echo "exit=$?"
git check-ignore backend/Dockerfile; echo "exit=$?"
```
Expected: three lines each naming a rule from `.gitignore`, `exit=0`; then no output and `exit=1` for `backend/Dockerfile`.

Clean up: `rm -rf data_dump backend/.env.bak.20260101 backend/nginx/nginx.conf.bak.20260101`

- [ ] **Step 4: Create `backend/.dockerignore`**

Write `backend/.dockerignore`:
```
# Keep secrets, local state and junk out of the image (Dockerfile does COPY .)
**/.env
**/.env.*
**/*.env.txt
**/*.bak
**/*.bak.*
**/*.pem
.git
**/__pycache__
**/*.pyc
**/*.log
db.sqlite3
media
staticfiles
```

- [ ] **Step 5: Commit**

```bash
git add .gitignore backend/.dockerignore
git commit -m "chore: ignore env/conf backups and data dumps; add backend .dockerignore

.env.bak.<date> copies and data_dump/ were not ignored, and the backend
image build copied the whole directory (including any local .env).

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: `ci.yml` skeleton + backend job

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Write the workflow with the `backend` job**

Create `.github/workflows/ci.yml`:
```yaml
name: CI

on:
  pull_request:
  push:
    branches: [main]

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

permissions:
  contents: read

jobs:
  backend:
    name: backend
    runs-on: ubuntu-24.04
    timeout-minutes: 25
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: postgres
          POSTGRES_DB: dailytaiyari
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U postgres"
          --health-interval 5s
          --health-timeout 5s
          --health-retries 10
    env:
      DEBUG: "True"
      SECRET_KEY: ci-only-not-a-secret
      DB_NAME: dailytaiyari
      DB_USER: postgres
      DB_PASSWORD: postgres
      DB_HOST: localhost
      DB_PORT: "5432"
    defaults:
      run:
        working-directory: backend
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
          cache-dependency-path: backend/requirements.txt

      - name: System packages (ffmpeg is used by the video pipeline tests)
        run: sudo apt-get update && sudo apt-get install -y --no-install-recommends ffmpeg

      - name: Install Python dependencies
        run: pip install -r requirements.txt

      - name: Django system check
        run: python manage.py check

      - name: Migrations match the models and have no conflicting leaves
        run: python manage.py makemigrations --check --dry-run

      - name: Tests
        run: python manage.py test --noinput

      - name: Dependency audit (report only)
        continue-on-error: true
        run: pip install pip-audit && pip-audit
```

- [ ] **Step 2: Validate the YAML parses and the job is present**

Run:
```bash
.venv/Scripts/python.exe -m pip install -q pyyaml
.venv/Scripts/python.exe -c "import yaml; d=yaml.safe_load(open('.github/workflows/ci.yml')); print(list(d['jobs']))"
```
Expected: `['backend']`. (Note: PyYAML parses the key `on` as boolean `True`; that is normal and not an error.)

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: backend job (Postgres 16, system check, migration check, tests)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Frontend job (3 builds)

**Files:**
- Modify: `.github/workflows/ci.yml` (append a job under `jobs:`)

- [ ] **Step 1: Append the `frontend` job**

Run:
```bash
cat >> .github/workflows/ci.yml <<'EOF'

  frontend:
    name: frontend (${{ matrix.app }})
    runs-on: ubuntu-24.04
    timeout-minutes: 15
    strategy:
      fail-fast: false
      matrix:
        include:
          - app: exam-frontend
            path: frontend/exam-frontend
          - app: superadmin-frontend
            path: frontend/superadmin-frontend
          - app: landing-page
            path: frontend/landing-page/main
    defaults:
      run:
        working-directory: ${{ matrix.path }}
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: npm
          cache-dependency-path: ${{ matrix.path }}/package-lock.json

      - name: Install
        run: npm ci --no-audit --no-fund

      - name: Build
        run: npm run build
EOF
```

- [ ] **Step 2: Reproduce the same commands locally for each app (proof they work)**

Run (one app per command; each is `npm ci` then `npm run build`):
```bash
(cd frontend/exam-frontend && npm ci --no-audit --no-fund && npm run build)
(cd frontend/superadmin-frontend && npm ci --no-audit --no-fund && npm run build)
(cd frontend/landing-page/main && npm ci --no-audit --no-fund && npm run build)
```
Expected: each ends with a successful build (`built in ...` for Vite; the route table for Next) and exit code 0. For `exam-frontend`, a log line `[inject-meta] VITE_TENANT_ID or VITE_API_URL not set — keeping default social meta tags.` is expected and fine.

Measured on 2026-11-14 (Windows, Node 22): `superadmin-frontend` and `landing-page` build fine. **`exam-frontend` fails on Windows only** with `Cannot find module @rollup/rollup-win32-x64-msvc`: its `package-lock.json` has an entry for `@rollup/rollup-linux-x64-gnu` but none for the Windows binary (`superadmin-frontend`'s lock has both). Linux CI is therefore expected to pass, and this is not a reason to change the job; Task 7 proves it. It does mean Windows developers cannot `npm ci && npm run build` the exam frontend until the lockfile is regenerated with all platforms (`rm -rf node_modules package-lock.json && npm install` on a machine, then commit). Report this to the owner; fixing it is optional and out of scope here.
If any other build fails, do **not** loosen the job; record the failure, check whether it fails the same way on `main`, and tell the owner (a red gate on day one is a finding, not something to hide).

- [ ] **Step 3: Validate YAML**

Run:
```bash
.venv/Scripts/python.exe -c "import yaml; d=yaml.safe_load(open('.github/workflows/ci.yml')); print(list(d['jobs']), [m['app'] for m in d['jobs']['frontend']['strategy']['matrix']['include']])"
```
Expected: `['backend', 'frontend'] ['exam-frontend', 'superadmin-frontend', 'landing-page']`.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: build exam-frontend, superadmin-frontend and landing-page

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Docker image build job

**Files:**
- Modify: `.github/workflows/ci.yml` (append a job)

- [ ] **Step 1: Append the `docker` job**

Run:
```bash
cat >> .github/workflows/ci.yml <<'EOF'

  docker:
    name: docker build
    runs-on: ubuntu-24.04
    timeout-minutes: 25
    steps:
      - uses: actions/checkout@v4

      - uses: docker/setup-buildx-action@v3

      - name: Build backend image (not pushed)
        uses: docker/build-push-action@v6
        with:
          context: backend
          load: true
          push: false
          tags: dailytaiyari-backend:ci
          cache-from: type=gha
          cache-to: type=gha,mode=max

      - name: Smoke test the image (Django boots, no secrets baked in)
        run: |
          docker run --rm --entrypoint python dailytaiyari-backend:ci manage.py check
          docker run --rm --entrypoint sh dailytaiyari-backend:ci -c 'test ! -e /app/.env'
EOF
```

- [ ] **Step 2: If Docker is available locally, build and smoke-test the same way**

Run:
```bash
docker build -t dailytaiyari-backend:ci backend
docker run --rm --entrypoint python dailytaiyari-backend:ci manage.py check
```
Expected: build succeeds; the check prints `System check identified no issues (0 silenced).` If Docker is not installed, skip this step; Task 7 proves it on GitHub.

- [ ] **Step 3: Validate YAML and commit**

```bash
.venv/Scripts/python.exe -c "import yaml; d=yaml.safe_load(open('.github/workflows/ci.yml')); print(list(d['jobs']))"
git add .github/workflows/ci.yml
git commit -m "ci: build and smoke-test the backend Docker image

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```
Expected output of the first command: `['backend', 'frontend', 'docker']`.

---

### Task 6: Secret-scan job

**Files:**
- Modify: `.github/workflows/ci.yml` (append a job)

- [ ] **Step 1: Append the `secret-scan` job**

It scans only the commits the PR adds (not the whole history), so pre-existing findings in old history cannot block unrelated PRs. The base branch name is passed through `env`, not interpolated into the shell.

Run:
```bash
cat >> .github/workflows/ci.yml <<'EOF'

  secret-scan:
    name: secret scan
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-24.04
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Install gitleaks
        run: |
          V=8.18.4
          curl -sSfL "https://github.com/gitleaks/gitleaks/releases/download/v${V}/gitleaks_${V}_linux_x64.tar.gz" | tar -xz gitleaks
          ./gitleaks version

      - name: Scan the commits this PR adds
        env:
          BASE_REF: ${{ github.base_ref }}
        run: ./gitleaks detect --source . --log-opts "origin/${BASE_REF}..HEAD" --redact --no-banner --verbose
EOF
```

- [ ] **Step 2: Validate YAML and the final job list**

Run:
```bash
.venv/Scripts/python.exe -c "import yaml; d=yaml.safe_load(open('.github/workflows/ci.yml')); print(list(d['jobs'])); assert set(d['jobs'])=={'backend','frontend','docker','secret-scan'}"
```
Expected: `['backend', 'frontend', 'docker', 'secret-scan']` and no assertion error.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: secret scan (gitleaks) over the commits a PR adds

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Prove it on GitHub — **STOP: needs the owner's explicit approval to push and open a PR**

Pushing a branch and opening a PR is outward-facing on the org's repo. Ask first.

**Files:** none

- [ ] **Step 1: Owner approves the push**

Show the owner `git log --oneline origin/main..HEAD` (expect 6 commits: the guardian fix, hygiene, and one each for the backend, frontend, docker and secret-scan jobs) and wait for a yes.

- [ ] **Step 2: Push and open the PR**

Run:
```bash
git push -u origin ci/phase0-gates
gh pr create --base main --head ci/phase0-gates --title "ci: PR gates (backend tests, migrations, frontends, docker, secret scan)" --body "$(cat <<'EOF'
## What
First CI for the repo. Adds `.github/workflows/ci.yml` with four gates, fixes the one failing test on `main`, and closes two hygiene gaps (`.gitignore`, `backend/.dockerignore`).

## Gates
- backend: Postgres 16 service, `manage.py check`, `makemigrations --check --dry-run`, `manage.py test`
- frontend: build exam-frontend, superadmin-frontend, landing-page
- docker: build and smoke-test the backend image (not pushed)
- secret scan: gitleaks over this PR's commits

## Test plan
- [ ] All four jobs green on this PR
- [ ] Backend job reports 334 tests passing (4 ffmpeg tests included)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Watch the run**

Run: `gh pr checks --watch`
Expected: `backend`, `frontend (exam-frontend)`, `frontend (superadmin-frontend)`, `frontend (landing-page)`, `docker build`, `secret scan` all pass.

- [ ] **Step 4: Triage anything red — do not skip tests to get green**

- If the 4 `RunWithProgressTests` fail on Linux: open the log, find the ffmpeg error (likely a missing `libx264` or a timing assumption), and fix the cause (package or test) in a new commit.
- If `docker build` fails on `COPY`/`.dockerignore`: read the error, fix `backend/.dockerignore`.
- If `secret scan` flags a finding: it is real until proven otherwise. Verify, then rotate or remove; only add an allowlist entry for a verified false positive.
- Report the final test count and run time to the owner.

---

### Task 8: Make the gates required on `main` — **STOP: needs the owner's explicit approval**

Branch protection is a repository setting. `PUT` branch protection **replaces** existing rules, so read first.

**Files:** none

- [ ] **Step 1: Read the current protection (read-only)**

Run: `gh api repos/dailytaiyari-lms/dailytaiyari.ai/branches/main/protection`
Expected: either a JSON object (existing rules; keep them in the next step) or `404 Branch not protected`.

- [ ] **Step 2: Owner approves; apply**

If unprotected, run (otherwise merge the existing settings into this payload first):
```bash
gh api -X PUT repos/dailytaiyari-lms/dailytaiyari.ai/branches/main/protection --input - <<'EOF'
{
  "required_status_checks": {
    "strict": false,
    "contexts": [
      "backend",
      "frontend (exam-frontend)",
      "frontend (superadmin-frontend)",
      "frontend (landing-page)",
      "docker build",
      "secret scan"
    ]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": null,
  "restrictions": null
}
EOF
```
`enforce_admins: false` leaves the owner able to merge in an emergency.

- [ ] **Step 3: Verify**

Run: `gh api repos/dailytaiyari-lms/dailytaiyari.ai/branches/main/protection/required_status_checks --jq '.contexts'`
Expected: the six check names above.

---

### Task 9: Record the results in project knowledge

The knowledge folder lives untracked in the owner's main checkout (`c:\Users\uparp\Desktop\dailytaiyari\project-knowledge`), not in this worktree.

**Files:**
- Modify: `project-knowledge/infra/uat-cicd-design.md` (§9 constraint and §15 open items)
- Modify: `project-knowledge/infra/cicd-readiness.md` (note that CI now exists)
- Modify: `project-knowledge/known-issues.md` (guardian-email bug fixed)

- [ ] **Step 1: Update the design spec**

In `uat-cicd-design.md` §9, replace the sentence beginning "Constraint to verify while planning: `exam-frontend/inject-meta.mjs` ..." with: "Verified: `exam-frontend/inject-meta.mjs` never fails the build when the API is unreachable (it logs a warning and keeps default meta tags), so staging builds do not depend on the API being awake; social-preview tags just fall back to defaults. SWA Free limits (apps per subscription, custom domains per app) still to be confirmed."
In §15, replace "Whether `python manage.py test` is green on `main` today is unverified; phase 0 starts with that." with the measured result: "Baseline measured 2026-11-14: 334 tests; 1 real failure (guardian email, fixed in Phase 0) and 4 ffmpeg errors that only occur on Windows; Phase 0 CI confirms on Linux."

- [ ] **Step 2: Update `cicd-readiness.md` and `known-issues.md`**

Add one dated line to each: CI exists as `.github/workflows/ci.yml` with the six checks (once merged and Task 8 applied); the stale-guardian-response bug in `users/views.py` is fixed by the Phase 0 PR. Use the real PR number once known.

- [ ] **Step 3: No commit**

These files are untracked in the owner's checkout; leave them there and tell the owner they are updated.

---

## Self-review against the spec (§6 `ci.yml`, §14 Phase 0)

- Backend tests on a Postgres service container -> Task 3. `makemigrations --check` incl. conflicting leaves -> Task 3. Three frontend builds -> Task 4. `docker build` -> Task 5. Secret scan -> Task 6. Dependency audit as non-blocking report -> Task 3 last step.
- `.gitignore` covering `data_dump/`, `.env*`, `*.bak*` (§12 item 8) -> Task 2.
- "Baseline test run, fix whatever CI exposes" -> Tasks 0, 1, 7.
- Not in this plan on purpose: `build.yml` (image push needs the registry, Phase 1/2), `uat-up/down/ttl`, Azure OIDC, compose/nginx/entrypoint changes, shadow-tenant commands. These belong to the Phase 1/2 plans.
- ESLint is not a gate: both frontends define `lint` with `--max-warnings 0`, and no lint results exist for `main`. Adding it is a follow-up once the owner decides whether to fix existing warnings.
- Names used consistently: job names `backend`, `frontend (<app>)`, `docker build`, `secret scan` match the required-check contexts in Task 8.
