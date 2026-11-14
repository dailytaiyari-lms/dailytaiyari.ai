# landing-page (DailyTaiyari marketing site, Next.js)

Source of truth: branch `main`. **Next.js project root for deploy = `frontend/landing-page/main/`** (NOT `frontend/landing-page/`). `frontend/landing-page/` contains only the `main/` folder; `package.json`, `package-lock.json`, `next.config.ts`, `netlify.toml`, `tsconfig.json`, `eslint.config.mjs`, `src/`, `public/` are all inside `main/`. Set the Netlify/Vercel "base directory"/"root directory" to `frontend/landing-page/main`. Paths below are repo-relative. Verified from code unless marked "unverified".

## 1. Purpose and audience
- Public B2B marketing site "DailyTaiyari for Institutes" selling the white-label AI LMS to coaching institutes, schools, colleges, creators. Canonical host hardcoded as `https://business.dailytaiyari.in` (layout, sitemap, robots, JSON-LD).
- Conversion goals: "Book a demo", "Talk to us"/contact, careers applications. All three post to the backend platform lead endpoints (not tenant-scoped).
- It is NOT the tenant-facing branded landing page (that is `/api/v1/landing/` served to tenant frontends via `backend/core/landing_urls.py`; this app never calls it).

## 2. Stack and versions
- Next.js **16.2.6** (App Router, `src/app`), React **19.2.4**, TypeScript ^5 (`strict: true`), Tailwind CSS **v4** (`@tailwindcss/postcss`, config via `@theme inline` in `src/app/globals.css`, no tailwind.config), framer-motion ^12.40, lucide-react ^1.16, ESLint ^9 flat config with `eslint-config-next` 16.2.6 (core-web-vitals + typescript).
- `package.json` name is `"exam"` (template leftover, harmless). `next.config.ts` is empty (`nextConfig = {}`): no images config, redirects, headers, or output mode.
- Fonts: `next/font/google` Outfit (`--font-outfit`) and JetBrains Mono (`--font-mono`) - fetched at **build time** from Google (build needs outbound network).
- Path alias `@/*` -> `./src/*`. Lockfile: `package-lock.json` v3 (npm). Next 16 requires Node >=20.9.0 (from lockfile engines). No `.nvmrc`, no `engines` field.
- **AGENTS.md / CLAUDE.md** (`CLAUDE.md` is just `@AGENTS.md`): says "This is NOT the Next.js you know ... Read the relevant guide in `node_modules/next/dist/docs/` before writing any code." Agents must consult those bundled docs (after `npm ci`) before touching Next APIs; Next 16 has breaking changes vs. older training data.
- Dead/unused components (not imported by any page): `components/institutes/Hero.tsx`, `Sections.tsx`, `ProductTour.tsx`, `LeadCTAButtons.tsx` (only used by Sections). Home page uses `components/creators/*` + `institutes/{Pricing,FAQ,InstituteFooter,JsonLd,LeadDialogs}`.

## 3. Scripts
`dev` = `next dev` (port 3000; backend CORS default allows `http://localhost:3000`), `build` = `next build`, `start` = `next start`, `lint` = `eslint` (flat config; ignores `.next/**`, `out/**`, `build/**`, `next-env.d.ts`).

## 4. Build / deploy config
- `netlify.toml`: `command = "npm run build"`, `publish = ".next"`, `NODE_VERSION = "20"`, `[[plugins]] package = "@netlify/plugin-nextjs"` (plugin is not in package.json; Netlify installs it from the toml). So the intended host appears to be **Netlify with the Next runtime plugin** (SSR/ISR-capable). `.gitignore` also ignores `.vercel`, README is the create-next-app template mentioning Vercel; actual production host: unverified.
- No vercel.json, Dockerfile, GitHub workflows (`.github/` has only `skills/*`).
- Rendering: every route is prerenderable static HTML (no `fetch` at request time, no route handlers, no `generateStaticParams`, no `force-dynamic`). `sitemap.ts`, `robots.ts` and `opengraph-image.tsx` (ImageResponse 1200x630) are metadata routes. `next build` should output all pages as static (not verified by running a build).
- Because nothing needs a server at runtime, deployment could be a plain static host, but netlify.toml is configured for the Next plugin; don't change `publish` without changing the plugin setup.

## 5. Environment variables (names only)
- `NEXT_PUBLIC_API_URL` - the only one (`src/lib/leads.ts`). Optional; trailing slash stripped. Fallback hardcoded to the production API base (`https://api.dailytaiyari.in/api/v1`). Inlined at **build time** (NEXT_PUBLIC_), so changing it needs a rebuild. Staging/preview deploys that forget it will POST real leads to production API.
- No build-time secrets required. No other `process.env` usage in `src/`.

## 6. Routes / pages
| Route | File | Type | Notes |
|---|---|---|---|
| `/` | `src/app/page.tsx` | static; server component composing client components | sections in order: CreatorNav, CreatorHero, PlatformsMarquee, ImpactStats, StudentExperience, CreatorConsole, CourseShowcase, HowItWorks, TestimonialsMarquee, Audience, Pricing, FAQ, FinalCTA, InstituteFooter, LeadDialogs, plus JSON-LD |
| `/careers` | `app/careers/page.tsx` -> `institutes/CareersContent.tsx` (client; jobs from `careersData.ts`) | static + client form | per-job apply modal -> job-applications endpoint |
| `/privacy`, `/terms`, `/refund-policy`, `/cookie-policy` | `app/<x>/page.tsx` using `LegalShell` | static content | privacy page "updated 10 July 2026" text hardcoded |
| `/sitemap.xml`, `/robots.txt`, `/opengraph-image` | `sitemap.ts`, `robots.ts`, `opengraph-image.tsx` | generated | |
In-page anchors that exist on `/`: `#features`, `#how`, `#audience` (CreatorSections), `#pricing`, `#faq`. `#tour`, `#grow`, `#demo` exist only in the dead `institutes/*` components, so they are **dead anchors** even though `sitemap.ts` lists `/#tour` and `/#grow` and `InstituteFooter` links `#grow` and `#demo`. Footer/nav hash links are bare `#x`, so on `/careers` and legal pages they won't scroll to the home sections.

## 7. API calls and lead flow
All in `src/lib/leads.ts` via plain `fetch` (no axios). **No auth header and NO `X-Tenant-ID` header** - these endpoints are tenant-exempt (`/api/v1/platform/` in `TENANT_EXEMPT_PATHS`, `backend/core/middleware.py`). Body is JSON, always prefixed with `source: "landing"` (overridden by payload `source`).
| Function | POST | Payload fields | Triggered from |
|---|---|---|---|
| `submitDemoBooking` | `/platform/demo-bookings/` | name, email, phone, organization, organization_type (creator/coaching/school/college/edtech/other), message, source | LeadDialogs kind `demo` |
| `submitContactMessage` | `/platform/contact-messages/` | name, email, subject, message (required), source | LeadDialogs kind `contact` |
| `submitJobApplication` | `/platform/job-applications/` | name, email, phone, position, experience, portfolio_url, cover_letter, source `careers-<jobId>` | CareersContent |
- Dialog mechanism: any component calls `openLeadDialog(kind, ctx?)` which dispatches a `window` CustomEvent `dt:open-lead`; `LeadDialogs` (mounted once on `/`) listens. **`LeadDialogs` is only mounted on `/`**, so `openLeadDialog` from nav on `/careers` or legal pages (InstituteNav has "Book demo" button calling it) does nothing there (no listener) - unverified in browser, but code shows the listener only in `LeadDialogs`, rendered only in `app/page.tsx`.
- Pricing buttons pass context `{plan, source:"Pricing page"}`: source becomes `landing-pricing-page`, message gets a prefixed "SALES LEAD - interested in the X plan" line, contact subject becomes `[Sales] <plan> plan - ...`. Enterprise opens contact; Starter/Growth open demo. Prices (INR per student/month) are hardcoded in `Pricing.tsx`.
- Backend (`backend/core/views.py`): `DemoBookingCreateView`, `ContactMessageCreateView`, `JobApplicationCreateView` - `AllowAny`, `authentication_classes=[]`, `throttle_classes=[ScopedRateThrottle]`, `throttle_scope='platform_lead'`. Rate `platform_lead: 20/hour` in `REST_FRAMEWORK.DEFAULT_THROTTLE_RATES` (`backend/dailytaiyari/settings.py`). Per DRF scoped throttle semantics the key is scope+client IP, so the **20/hour budget is shared across all three endpoints per IP** (e.g. an office NAT could 429 a legitimate lead). Client shows the first error string from the JSON body; a 429 body is `{"detail": "..."}` so the user sees DRF's throttle message.
- Backend then persists `DemoBooking`/`ContactMessage`/`JobApplication` and emails the team (`core/emails.py`; mail failure is swallowed so the lead is still saved). Super admins triage them in superadmin-frontend `/support`.
- CORS: backend allows regex `^https://([a-z0-9-]+\.)?dailytaiyari\.(in|ai)$` plus `http://localhost:3000` default. Netlify preview URLs (`*.netlify.app`) are NOT allowed, so form posts from deploy previews fail CORS unless added (the hardcoded list only has specific tenant Netlify hosts).
- No analytics, cookies, or third-party scripts found in `src/`.

## 8. Static vs dynamic
- Static: all copy, pricing, FAQs (`faqData.ts`), careers (`careersData.ts`), legal text, JSON-LD (`institutes/JsonLd.tsx`, Organization + WebSite + SoftwareApplication + FAQ from `faqData`), OG image.
- Dynamic (client-side only): lead/careers form submissions, dialog state, Typewriter/Marquee/framer-motion animations. Many components are `"use client"`. Dark-mode classes (`dark:`) are used throughout.

## 9. SEO/meta (`src/app/layout.tsx`)
- `metadataBase` = `https://business.dailytaiyari.in`; title default + template `%s | DailyTaiyari`; long keyword list; canonical `/`; OpenGraph (website, en_IN) + Twitter `summary_large_image`; robots index/follow with googleBot large previews; `/careers` and legal pages set own title/description/canonical.
- `robots.ts` allows all and points to sitemap; `sitemap.ts` lists `/`, hash URLs (low value, includes dead anchors), `/careers`, 4 legal pages.
- Contact emails hardcoded: `hello@dailytaiyari.in`, `careers@dailytaiyari.in`. Footer social links are `href="#"` placeholders. JSON-LD `sameAs` is empty.

## 10. Tests / lint status
- No tests, no test runner.
- Lint: `eslint.config.mjs` present and valid for ESLint 9 + eslint-config-next 16 (`npm run lint` is runnable; not executed here, so pass/fail unverified).
- Type check: only via `next build` (tsconfig `strict`, `noEmit`); no standalone `tsc` script (could use `npx tsc --noEmit`).

## 11. CI-relevant findings
- Node 20.x (>=20.9 required by Next 16.2.6); Netlify pins `NODE_VERSION=20`. Use `actions/setup-node` 20 with `cache: npm` and `cache-dependency-path: frontend/landing-page/main/package-lock.json`.
- Run everything with `working-directory: frontend/landing-page/main`: `npm ci`, `npm run lint`, `npm run build`.
- Build needs: outbound internet for Google Fonts (`next/font/google`); no secrets; `NEXT_PUBLIC_API_URL` optional (default points at production API). `next-env.d.ts` and `.next/` are gitignored; `.env*` is gitignored (no `.env.example` exists).
- Landing-page project root nesting: path filters for CI should be `frontend/landing-page/**`.
- No existing CI in repo; no preview-protection against posting to prod API (see env var note).

## 12. Gotchas
1. Deploy root is `frontend/landing-page/main/` (nested). Pointing the host at `frontend/landing-page/` finds no package.json.
2. Follow AGENTS.md: read `node_modules/next/dist/docs/` before using Next APIs (Next 16, React 19, Tailwind 4 - e.g. no `tailwind.config.js`, theme tokens `primary-*`, `accent-*`, `surface-*`, `success-*` defined in `globals.css`).
3. Lead dialogs only work on `/` (listener lives in `LeadDialogs`); `InstituteNav`/`LegalShell` pages call `openLeadDialog` with no listener mounted.
4. Dead anchors and dead components listed in sections 2 and 6; edit `creators/*` for the live homepage, not `institutes/Hero|Sections|ProductTour`.
5. Shared 20/hour/IP lead throttle across demo+contact+job endpoints.
6. `NEXT_PUBLIC_API_URL` default is production; local dev without the var posts real leads to prod unless overridden (point it at `http://localhost:8000/api/v1`; backend CORS default already allows localhost:3000).
7. Domain strings hardcoded in 4 places (layout.tsx, sitemap.ts, robots.ts, JsonLd.tsx); change all together when the canonical host changes.
8. Backend `landing_urls.py` (`/api/v1/landing/`, requires `X-Tenant-ID`) belongs to the tenant-site feature, unrelated to this app.
