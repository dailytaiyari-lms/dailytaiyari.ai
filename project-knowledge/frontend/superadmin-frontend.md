# superadmin-frontend (platform Super Admin console)

Source of truth: branch `main`, directory `frontend/superadmin-frontend/` (paths below are repo-relative). Verified from code unless marked "unverified".

## 1. Purpose and audience
- Standalone SPA for the **platform operator** (Django superuser, `is_superuser=True`, tenant-less account). NOT for tenant admins/faculty/students.
- Capabilities: platform overview/stats, tenant CRUD + per-tenant plan/quota/feature-lock/suspension/allowed-origins, cross-tenant user management, "Support Inbox" (marketing leads), platform announcements, platform-supplied LLM accounts + usage + per-tenant AI allocation, audit log.
- Backend enforces access on every endpoint via `core.permissions.IsSuperAdmin` (`backend/core/permissions.py`). The frontend gate is only `isAuthenticated` in the persisted store (no role check client-side).
- `index.html` has `<meta name="robots" content="noindex, nofollow">`.

## 2. Stack and versions (package.json / package-lock.json)
- Vite ^5 (lock: 5.4.21), React ^18.2 (lock: 18.3.1), react-router-dom ^6.22, zustand ^4.5 (persist middleware), axios ^1.6, Tailwind ^3.4 (+ postcss/autoprefixer), recharts ^2.15, lucide-react ^0.563, react-hot-toast, date-fns ^3, clsx.
- Plain JavaScript/JSX (no TypeScript). `"type": "module"`. `engines.node: ">=20.x"`. Package name `dailytaiyari-superadmin`.
- Font: Outfit via Google Fonts `<link>` in `index.html`. Brand color scale in `tailwind.config.js` (`brand-50..700`, indigo-ish).
- Lockfile: `package-lock.json` (lockfileVersion 3, npm). No yarn/pnpm lock.

## 3. Scripts
`dev` = `vite` (port **3100**), `build` = `vite build` (-> `dist/`), `preview` = `vite preview`, `lint` = `eslint src --ext js,jsx --report-unused-disable-directives --max-warnings 0`.
- Vite alias `@` -> `/src` (declared in `vite.config.js`; code actually uses relative imports).
- Dev proxy: `/api` -> `http://localhost:8000` (`changeOrigin: true`). Backend must have `localhost` in `ALLOWED_HOSTS`.

## 4. Build / deploy config
- `netlify.toml`: `command = "npm run build"`, `publish = "dist"`, `NODE_VERSION = "20"`, SPA fallback redirect `/* -> /index.html` (200).
- `vercel.json`: SPA rewrite `/(.*) -> /index.html` only (no build settings; Vercel auto-detects Vite). Both files exist; which host is actually used in prod is **unverified** (README says "static site, see netlify.toml").
- No `.nvmrc`, no Dockerfile, no GitHub workflows in repo (`.github/` only has `skills/*`). No CI exists for this app.
- Project root for deploy = `frontend/superadmin-frontend` (package.json lives there).

## 5. Environment variables (names only)
- `VITE_API_URL` (build-time, inlined by Vite). Optional. Default when unset: `/api/v1` (relative; works only with the Vite dev proxy or a host rewrite). **Production builds MUST set it** to the absolute API base including `/api/v1` (example in `.env.example`: the production API host + `/api/v1`), otherwise requests go to the static host's own `/api/v1/...` and the SPA fallback returns index.html (netlify.toml has NO `/api` proxy rule).
- No other env vars. `.env`/`.env.local` are gitignored; `.env.example` is committed.

## 6. Routes (src/App.jsx, BrowserRouter)
| Path | Page file | Notes |
|---|---|---|
| `/login` | `src/pages/Login.jsx` | redirects to `/` if already authenticated |
| `/` | `pages/Dashboard.jsx` | stats + tenant charts (recharts via `components/charts.jsx`) |
| `/tenants` | `pages/Tenants.jsx` | list/search, create modal (name, subdomain, tagline, theme from 10 themes), plan charts |
| `/tenants/:id` | `pages/TenantDetail.jsx` | edit branding/subdomain/theme, active/suspended + message, plan/billing/trial/period-end, caps (max_students/courses/admins), allowed origins (textarea, one per line), tri-state feature locks (tenant/on/off), custom email domains toggle, usage bars, last 8 audit entries, embeds `components/TenantAIAllocationCard.jsx` |
| `/users` | `pages/Users.jsx` | cross-tenant users; filters search/tenant/role/status; row actions suspend/unsuspend/verify/reset_password |
| `/support` | `pages/Support.jsx` | "Support Inbox" = marketing leads (demo/contact/job); filter type+status; set status + internal notes |
| `/announcements` | `pages/Announcements.jsx` | CRUD; level, target_tenant (blank = all), is_active, starts_at/ends_at |
| `/ai` | `pages/AIPlatform.jsx` | tabs: "Accounts & models" (providers/models/test) and "Usage & cost" (days window) |
| `/audit` | `pages/AuditLog.jsx` | audit trail |
| `*` | - | `Navigate` to `/` |
All routes except `/login` are wrapped in `ProtectedRoute` + `Layout` (sidebar nav, `src/components/Layout.jsx`).

## 7. API layer
- `src/services/api.js`: axios instance, `baseURL = VITE_API_URL || '/api/v1'`, JSON content-type.
- **Auth header**: request interceptor reads `localStorage['superadmin-auth']` (zustand persist key; shape `{state:{user,tokens:{access,refresh},isAuthenticated}}`) and sets `Authorization: Bearer <access>`.
- **Tenant header: NEVER sent.** All calls are under `/api/v1/superadmin/`, which is in `TENANT_EXEMPT_PATHS` in `backend/core/middleware.py`. Do not add `X-Tenant-ID` here.
- 401 handling: one retry; POSTs `${API_BASE_URL}/auth/refresh/` with a bare `axios` call, stores new `access`, replays request. On any failure: clears `superadmin-auth`, hard-redirects `window.location.href='/login'`.
- Store (`src/store/authStore.js`): `login(email,password)` -> `svc.login` -> `{user, access, refresh}`; `logout()` only clears state (no server call/blacklist). Errors surface `non_field_errors[0]` / `detail`.

Endpoints (all in `src/services/superadminService.js`; backend routes in `backend/core/superadmin_urls.py`, mounted at `api/v1/superadmin/` in `backend/dailytaiyari/urls.py`):
| Method | Path (under /api/v1/superadmin/) | Used by |
|---|---|---|
| POST | `auth/login/` (AllowAny, no auth classes) | Login |
| GET | `auth/me/` | `fetchMe` defined but **unused** |
| GET | `stats/` | Dashboard |
| GET/POST | `tenants/` (`?search=&is_active=`; frontend passes `page_size`) | Tenants, Dashboard, Users/Announcements dropdowns |
| GET/PATCH | `tenants/{uuid}/` | TenantDetail |
| GET | `audit-logs/` (`?tenant=`) | AuditLog, TenantDetail |
| GET | `users/` (`search,tenant,role,status`) | Users |
| POST | `users/{uuid}/action/` body `{action: suspend\|unsuspend\|verify\|reset_password}` | Users |
| GET | `leads/` (`type=demo\|contact\|job`, `status=new\|contacted\|closed`) -> `{results,total,counts}` | Support |
| PATCH | `leads/{type}/{uuid}/` (status, internal_notes) | Support |
| GET/POST, PATCH/DELETE | `announcements/`, `announcements/{uuid}/` | Announcements |
| GET/POST | `ai/providers/`; PATCH/DELETE `ai/providers/{id}/` | AIPlatform |
| POST | `ai/providers/{id}/test/` body `{model}` | AIPlatform |
| POST | `ai/providers/{id}/models/`; PATCH/DELETE `ai/models/{id}/` | AIPlatform |
| GET | `ai/usage/?days=` | AIPlatform usage tab |
| GET/PUT | `tenants/{uuid}/ai-allocation/` | TenantAIAllocationCard |
AI views are in `backend/chatbot/platform_views.py`; provider API keys are write-only (responses carry only a masked hint).

## 8. How leads flow (this app is the READ side)
Marketing site (landing-page) POSTs to `/api/v1/platform/{demo-bookings,contact-messages,job-applications}/` -> models `DemoBooking`/`ContactMessage`/`JobApplication` (abstract `PlatformLead`, statuses new/contacted/closed, `internal_notes`, `source`) in `backend/core/models.py`. Super admin reads/updates them via `leads/` above. Throttle `platform_lead` = 20/hour (details in landing-page.md). The Support page is the only UI for these; email notifications are sent by the backend (`core/emails.py`, failures swallowed).

## 9. Static vs dynamic
Fully client-rendered SPA; everything dynamic from the API after login. No SSR, no static data except theme/plan label constants. Session lives in localStorage (key `superadmin-auth`).

## 10. SEO/meta
`noindex, nofollow`, `theme-color #4f46e5`, title "DailyTaiyari - Super Admin". No sitemap/robots.txt.

## 11. Tests / lint status
- **No tests** (no test runner, no `*.test.*`).
- **`npm run lint` will fail**: script invokes ESLint 8 (`eslint ^8.56`) but there is NO `.eslintrc*`/`eslint.config.*`/`eslintConfig` in package.json (verified by file listing; not executed). Do not add `npm run lint` to CI without first adding a config. `eslint-plugin-react`/`-react-hooks` are installed but unused.
- Build is the only real gate: `npm ci && npm run build`.

## 12. CI-relevant findings
- Node: Netlify pins 20; engines `>=20.x`; Vite 5 needs >=18. Use Node 20 in CI.
- Install: `npm ci` (lockfile v3 present).
- Build: `npm run build` -> `dist/`. Needs `VITE_API_URL` set at build time for prod correctness (build succeeds without it, silently wrong at runtime).
- No existing workflows, no Docker.

## 13. Gotchas
1. **Pagination ignored**: backend uses DRF default `PageNumberPagination`, `PAGE_SIZE=20` (`backend/dailytaiyari/settings.py`), with no `page_size` query param configured, so the frontend's `page_size: 200` is ignored. Pages read only `data.results` and never follow `next`: tenants (Dashboard charts, dropdowns), users, audit logs are effectively capped at 20 rows once exceeded. (Leads endpoint returns its own `{results,total,counts}` with a `limit`.)
2. **Refresh token flow is broken by design**: `/api/v1/auth/refresh/` is NOT tenant-exempt, and this app sends no `X-Tenant-ID`, so `TenantMiddleware` returns 403 -> catch -> logout. Also the client stores only the new `access` (ignores rotated `refresh`; backend has `ROTATE_REFRESH_TOKENS` + `BLACKLIST_AFTER_ROTATION`). Mostly masked because `ACCESS_TOKEN_LIFETIME` is 365 days; effective behavior on expiry = forced re-login.
3. Because access tokens last a year and logout does not blacklist, a stolen localStorage token stays valid.
4. Login path `superadmin/auth/login/` is distinct from tenant `auth/login/`; tenant users get rejected server-side.
5. CORS: backend allows `*.dailytaiyari.in/.ai` by regex plus a hardcoded list (`CORS_ALLOWED_ORIGINS` in settings.py). A new deploy host (e.g. a Netlify default URL) must be added to backend CORS config or all calls fail. Actual prod host of this app: unverified.
6. `window.location.href = '/login'` on auth failure (full reload), relies on SPA rewrite being present on the host.
7. Tenant theme list in `Tenants.jsx` (`THEMES`) is hardcoded; keep in sync with backend theme choices.
8. Feature locks: `feature_locks` map; UI mode `tenant` = key absent, `on` = true, `off` = false (`locksToModes`/inverse in TenantDetail.jsx). `available_features` and `available_plans` (with `defaults`) come from the tenant detail payload, not hardcoded.
