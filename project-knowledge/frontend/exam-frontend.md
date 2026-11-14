# exam-frontend (main student / instructor / tenant-admin SPA)

Source of truth: branch `main` (production export), `frontend/exam-frontend/`. Everything below was read from that code
(paths are repo-relative, `frontend/exam-frontend/...`). "unverified" = inferred, not proven from code. This is NOT the
`landing-page/` (marketing) or `superadmin-frontend/` (platform operator) app. The older `frontend/` dir on the intelligence branch is stale.

## 1. Stack, scripts, build pipeline

- Vite 5.4 + React 18.2 (plain JS/JSX, NO TypeScript), react-router-dom 6, Tailwind 3.4 (+ postcss/autoprefixer), MUI 5 + emotion
  (declared deps but ZERO imports in src; the UI is Tailwind + lucide-react), framer-motion 11, Zustand 4.5, @tanstack/react-query 5,
  axios 1.6, react-hot-toast, recharts 2, date-fns 3, react-markdown 9 + remark-gfm/remark-math + rehype-katex + katex 0.16,
  @monaco-editor/react + monaco-editor 0.55 (full ESM bundle), react-pdf 9.2 (pdfjs-dist 4.8.69 is transitive only), hls.js, jspdf,
  dompurify, canvas-confetti, react-confetti, react-easy-crop, react-circular-progressbar, clsx, lucide-react.
- Scripts (`package.json`): `dev` = `vite` (port 3000, proxies `/api` -> `http://localhost:8000`); `build` = `vite build && node scripts/inject-meta.mjs`;
  `preview`; `lint` = `eslint src --ext js,jsx --report-unused-disable-directives --max-warnings 0`.
- `vite.config.js`: only `@vitejs/plugin-react`, dev proxy, alias `@` -> `/src` (alias is effectively unused; code uses relative imports). No `manualChunks`, no env-mode files.
- Node: `.nvmrc` = `20`; `engines.node >=20.x`; `netlify.toml` sets `NODE_VERSION=20`.
- Hosting config: `netlify.toml` (`npm run build`, publish `dist`, SPA fallback `/* -> /index.html` 200) and `vercel.json` (SPA rewrite). Both are SPA fallbacks only, no headers/CSP.
- `tailwind.config.js`: `darkMode: 'class'`; `primary-*` and `accent-*` palettes come from CSS variables (`rgb(var(--color-primary-500) / <alpha-value>)`);
  `success/warning/error/surface` are static. Fonts: Outfit (Google Fonts `<link>` in index.html), "Clash Display"/JetBrains Mono are referenced in config but never loaded.
- `src/styles/index.css`: Tailwind layers + CSS vars (default Sunrise theme) + component classes `.btn .btn-primary/-secondary/-accent/-success/-ghost/-icon .card .card-hover .card-gradient .input .badge(-primary/-success/-warning/-error)`. Reuse these instead of raw Tailwind.

### Build-time tenant baking (IMPORTANT)
- One deployment per tenant. `VITE_TENANT_ID` (UUID) and `VITE_API_URL` (e.g. `https://api.../api/v1`) are inlined by Vite at build time (`import.meta.env`).
  Changing tenant = different env + rebuild. There is NO hostname/subdomain -> tenant resolution at runtime (grep for `hostname`/`location.host` finds nothing).
  Each tenant domain is a separate Netlify (or Vercel) site built from the same code with its own env vars. Backend also keeps per-tenant allowed frontend origins (CORS) - see backend docs.
- Env vars used: `VITE_TENANT_ID` (api.js, tenantStore.js, inject-meta), `VITE_API_URL` (api.js default `'/api/v1'`, chatService streaming, AdminDashboard line ~3656, inject-meta),
  `VITE_SITE_URL` (inject-meta only; falls back to Netlify's `URL`). No `.env*` file is committed. If `VITE_TENANT_ID` is missing, `api.js` sends no `X-Tenant-ID` (backend answers 403 for everything) and `tenantStore` sets `error: 'Tenant ID not configured'`.
- `scripts/inject-meta.mjs` (runs after `vite build`): Node `fetch` of `${VITE_API_URL}/tenant/${VITE_TENANT_ID}/` (public endpoint) during the Netlify build, then rewrites the
  `<!-- social-meta:start --> ... <!-- social-meta:end -->` block in `dist/index.html` with `<title>`, description, og:*, twitter:* using tenant `name`, `tagline`, `logo||favicon`, og:url = `VITE_SITE_URL||URL`.
  Reason: WhatsApp/Facebook crawlers do not run JS. It NEVER fails the build: missing env, API unreachable, missing file or markers -> `console.warn` and keeps the default "DailyTaiyari - Ace Your Exams" tags.
  So the build host must be able to reach the API for per-tenant previews. Needs Node >=18 global `fetch`.
- Runtime branding (separate from the build-time block): `tenantStore.fetchTenantConfig` sets `document.title`, favicon `<link>` and the colour theme.

## 2. Directory map (`src/`, 221 files, ~62k lines)

- `main.jsx` - React 18 root, `QueryClientProvider` (defaults: `staleTime` 5 min, `retry` 1), `BrowserRouter`, react-hot-toast `<Toaster>` (top-right). `App.jsx` - all routes + route guards.
- `pages/` (63 files incl. `auth/`) - route components. Giants: `AdminDashboard.jsx` (4083 lines, holds ~25 inline sub-components: StudentManagement, PerformanceReports, EnrollmentRequests, SalesDashboard, Overview, TenantSettings, IntegrationSettings, PaymentSettings...), `CourseManager.jsx` (2223), `HackathonParticipants.jsx` (1063), `Profile.jsx` (902), `AIDoubtSolver.jsx` (893).
- `components/layout/` - `MainLayout` (student shell: Sidebar, Header, MobileNav, PromoBanner, AnnouncementBanner, StudyTimer widget, BirthdayCelebration), `AdminLayout`+`AdminSidebar`, `AuthLayout`, `SuspensionOverlay`, `VerificationGate` (email OTP), `ExistingStudentConsentNotice` (guardian/compliance), `NotificationBell`, `XPChip`, `StreakChip`.
- `components/admin/` - tenant-admin builders: `ContentBuilder`, `CourseBuilder`, `builderShared` (shared inputs, `NotesTextarea` markdown+image paste upload), `LandingBuilder`, `MarketingPromotions`, `Announcements`, `EmailSettings`, `RegistrationSettings`, `AdvancedSettings`, `AIFeatures`, `IncludedModels`, `AICourseStudio` (+`aiStudio/`), `mockAi/` (AI mock-test studio), `hackathon/`, `hackathonAi/`.
- `components/{notebook,coding,content,chat,community,hackathons,jobs,certificate,landing,auth,course,profile,common}/` - feature components (see section 7).
- `services/` (27 files) - API layer (section 5). `context/` - Zustand stores (section 6). `hooks/` - `usePyodideKernel`, `useGenerationJob` (poll AI jobs), `useTopicAiJobs`, `useVoiceDictation` (Web Speech with MediaRecorder fallback -> backend transcribe).
- `config/` - `themes.js` (tenant colour themes + `applyTheme`), `authPanel.js` (login panel defaults), `bannerThemes.js`, `landingSections.js`. `utils/` - `xp.js` (XP transaction metadata), `html.js` (`stripHtml`). `workers/pyodideKernel.worker.js`. `styles/index.css`.

## 3. Routing (`src/App.jsx`)

Roles seen in code: `student`, `instructor`, `admin` (tenant admin). Platform superadmin lives in the other app. Role is read as `user?.role || profile?.user?.role`.
There is NO `React.lazy` for pages: every page is statically imported (only CodeEditor and PdfReader/FileDownloadCard are lazy). Guards:
- `ProtectedRoute` - must be authenticated and onboarded (else `/login`, `/onboarding`).
- `AppShell` - student shell (`MainLayout`) rendered for ANYONE incl. anonymous; authed-not-onboarded -> `/onboarding`.
- `LoginGate` (`components/auth/LoginGate.jsx`) - page content blurred behind a login/register card for anonymous visitors (this is the main "auth required" guard inside AppShell, not a redirect).
- `AdminRoute` - role `admin` only (else `/dashboard`). `EditorRoute` - `admin` or `instructor` (backend scopes instructors to assigned courses).
- `PublicRoute` - redirects logged-in+onboarded users to `/dashboard` (login/register/verify/forgot/reset).
- `FeatureRoute feature="x"` - redirects to `/dashboard` if `tenantStore.isFeatureEnabled(x)` is false (default true).
- `*` -> `RootRedirect` (`/dashboard` if authed else `/`). `/` -> `RootRoute` shows tenant `LandingPage` (admin preview `/?preview=1`).

### Auth / public (AuthLayout, no app shell)
`/login` Login, `/register` Register, `/verify-email` VerifyEmail, `/forgot-password`, `/reset-password` (all PublicRoute); `/onboarding` Onboarding; `/guardian-consent/:token` GuardianConsent (public).
Standalone public: `/` LandingPage, `/refund-policy` `/privacy-policy` `/terms` -> `LegalPage slug=...`, `/hackathons/:hackathonId` HackathonDetail (full-bleed, readable by anyone).

### Student shell (AppShell + MainLayout); feature flag in brackets
| Path | Page | Guard |
|---|---|---|
| `/dashboard` | Dashboard | LoginGate |
| `/courses`, `/courses/:courseId` | Courses, CourseDetail (enrol, coupons, Razorpay/Cashfree/PayU checkout, community preview) | public, [courses] |
| `/study`, `/study/course/:courseId`, `/study/:subjectId`, `/study/chapter/:chapterId`, `/study/chapter/:chapterId/topic/:topicId` | Study, StudyCourse (certificate button), StudyChapters, StudyChapterTopics, StudyTopicContent (content/quiz/assignment/coding/lab/live-class items per topic) | LoginGate [study] |
| `/topic/:topicId`, `/content/:contentId`, `/revision` | TopicView, ContentViewer (video/PDF/notes/file), Revision (bookmarks) | LoginGate [study] |
| `/assignment/:assignmentId` | AssignmentView | LoginGate |
| `/coding/:problemId` | CodingProblem (Monaco + run/submit via Piston backend) | LoginGate |
| `/notebooks/:notebookId` | NotebookPage (Pyodide lab) | LoginGate |
| `/quiz`, `/quiz/:quizId`, `/quiz/review/:attemptId` | Quiz, QuizAttempt (fullscreen proctoring events), QuizReview | LoginGate [quiz] |
| `/mock-test`, `/mock-test/live/:testId`, `/mock-test/live-review/:attemptId` | MockTest list, RichMockAttempt, RichMockReview (current "rich" mock flow) | LoginGate [mock_tests] |
| `/mock-test/:testId`, `/mock-test/review/:attemptId` | MockTestAttempt, MockTestReview (LEGACY flow; still the one `/pyp` uses) | LoginGate [mock_tests] |
| `/pyp` | PreviousYearPapers | LoginGate [pyq] |
| `/analytics`, `/leaderboard` | Analytics, Leaderboard | LoginGate [analytics]/[leaderboard] |
| `/profile`, `/notifications`, `/xp` | Profile, Notifications, XPHistory | LoginGate |
| `/doubt-solver` and `/ai-doubt-solver` (alias), `/ai-learning`, `/ai-quiz-review/:attemptId` | AIDoubtSolver (chat, streaming), AILearning, AIQuizReview | LoginGate [ai] |
| `/community`, `/community/:id` | Community, CommunityPost | LoginGate [community] |
| `/jobs`, `/jobs/:jobId` | Jobs, JobDetail (browse public, apply needs login) | [jobs] |
| `/hackathons` | Hackathons list | [hackathons] |
Outside the shell: `/hackathons/:hackathonId/rounds/:stageId` HackathonStage (ProtectedRoute).

### Instructor/creator routes (inside AppShell; `LoginGate` + `EditorRoute`, admin or instructor)
`/courses/:courseId/manage` CourseManager (topic-level content, quizzes, assignments, coding, labs, live classes, instructors, thumbnail),
`.../manage/assignments/:assignmentId` AssignmentGrading and `.../submissions/:submissionId` SubmissionReview,
`.../manage/coding/:problemId` CodingGrading and `.../submissions/:submissionId` CodingSubmissionReview,
`.../manage/notebooks/:notebookId/edit` NotebookBuilder, `.../manage/notebooks/:notebookId` NotebookGrading, `.../submissions/:submissionId` NotebookSubmissionReview.
Instructors find courses via `Courses` page (`manageableCourses` query); the Header "Switch to Admin View" button shows only for `role === 'admin'`.

### Tenant admin (AdminLayout; `ProtectedRoute` + `AdminRoute`; no feature gating)
`/admin-dashboard` AdminDashboard - single page with `?tab=` (default overview): `overview, students, enrollments, sales, marketing, announcements, performance (Reports), content (CourseBuilder), ai-studio (AICourseStudio), landing, ai (AIFeatures), settings` (settings sub-tabs: general, payments, integrations (Zoom), email, advanced, registration). `AdminSidebar.ADMIN_NAV_ITEMS` mixes `tab` items and `path` items.
`/admin-dashboard/content/:courseId` CourseManager.
`/admin/jobs`, `/admin/jobs/:jobId` (JobApplicants), `/admin/jobs/:jobId/applications/:applicationId` (JobApplicationReview) - JobManager.
`/admin/mock-tests` MockTestManager, `/admin/mock-tests/ai` AIMockStudioPage, `/admin/mock-tests/grading`, `/admin/mock-tests/:testId/submissions`, `/admin/mock-tests/:testId/submissions/:attemptId`, `/admin/mock-tests/:testId` MockTestBuilder.
`/admin/hackathons`, `/admin/hackathons/ai`, `/admin/hackathons/:hackathonId` (HackathonBuilder), `.../participants`.
Note: the order of `/admin/mock-tests/ai`, `/grading` before `/:testId` matters (react-router v6 ranks static above dynamic anyway).

### Feature -> where it lives (quick finder)
Certificates: `components/certificate/*` (SVG templates -> PNG/PDF client-side via jspdf; button in StudyCourse; `certificateService`). Payments: `paymentService` (loads provider SDK lazily; PayU = auto-submitted form redirect) used only in CourseDetail. Live classes (Zoom): student join in StudyTopicContent via `liveClassService`; admin CRUD/attendance in CourseManager `LiveClassSection` via `contentBuilderService`. Marketing: `PromoBanner` (tenant.promo_banner), coupons (`marketingService`), admin `MarketingPromotions`. Notifications: `NotificationBell` (polls unread-count), `Notifications` page, admin `Announcements`, `AnnouncementBanner` (tenant.announcements, dismissal in localStorage), `BirthdayCelebration`. Gamification: `XPChip`, `StreakChip`, XPHistory, Leaderboard, `utils/xp.js`. Study timer: `components/common/StudyTimer.jsx` (floating widget; localStorage UI prefs + `/analytics/study-timer/`). Community: `components/community/*`. Landing page builder/renderer: `components/landing/*`, `config/landingSections.js`, `LandingBuilder`. NO teacher "learning insights"/intelligence pages exist on main (they are on the intelligence branch only).

## 4. Auth & tenancy

- `services/api.js` exports default `api` (axios, baseURL `VITE_API_URL || '/api/v1'`, default header `X-Tenant-ID: VITE_TENANT_ID`) and `tenantApi` (identical config, used only for the public `/tenant/<id>/`). Also exports `API_BASE_URL`, `TENANT_ID` for raw-fetch callers.
- Request interceptor: reads `localStorage['auth-storage']` (Zustand persist JSON), adds `Authorization: Bearer <state.tokens.access>`. No try/catch around `JSON.parse`.
- Response interceptor: (a) `403` with `data.code === 'account_suspended'` -> `authStore.markSuspended()` (session kept, `SuspensionOverlay` blocks UI); (b) `401` once (`_retry`) -> POST refresh token, retry; on failure wipes `auth-storage` and hard-redirects to `/login`.
- **Latent bug**: the refresh call uses bare `axios.post(`${API_BASE_URL}/auth/refresh/`)` WITHOUT `X-Tenant-ID`; backend `TenantMiddleware` only exempts a fixed path list and `/api/v1/auth/refresh/` is not on it, so the refresh would 403 and force logout. Masked because SimpleJWT access lifetime is 365 days (refresh 730 d) in backend settings.py. Also the interceptor writes the new access token to localStorage but not into the in-memory Zustand state (rehydrates on reload). `authStore.refreshToken()` (uses `api`, so it has the header) is unused.
- Streaming (`chatService.sendMessageStream`, `POST /chatbot/sessions/<id>/send_message_stream/`, NDJSON lines `{content}` / `{done}`) uses raw `fetch` and manually adds `X-Tenant-ID` + Bearer. Any new raw fetch/axios call MUST add `X-Tenant-ID` itself (backend returns 403 without it, except tenant-exempt paths such as `/tenant/`, `/certificates/verify/`).
- Tenant is also enforced server-side: backend binds `X-Tenant-ID` to the caller's own tenant (403 `tenant_mismatch`), and suspended/frozen tenants reject authed calls (auth bootstrap paths excepted).
- `authStore` (persist key `auth-storage`, partialised to `user, profile, tokens{access,refresh}, isAuthenticated, isOnboarded`): `login` (`/auth/login/`; `email_not_verified` code -> `needsVerification`), `register` (no auto-login; email OTP via `/auth/verify-email/`, `/auth/resend-otp/`), `requestPasswordReset/resetPassword` (`/auth/password/forgot|reset/`), `changePassword`, `completeOnboarding` (`/auth/onboarding/`), `fetchProfile`/`updateProfile` (`/auth/profile/`; FormData for avatar), `logout` (local only, no API call, React Query cache NOT cleared), `markSuspended`.
  Tokens live in localStorage (XSS-exposed, accepted tradeoff). `MainLayout`/`AdminLayout` call `fetchProfile()` on mount.
- Gates always mounted in `App`: `SuspensionOverlay` (`user.is_suspended`), `VerificationGate` (`!user.is_email_verified`, OTP modal), `ExistingStudentConsentNotice` (`/auth/compliance-status/`, driven by `tenant.registration_schema.guardian_consent.enabled`).
- **Feature flags**: `tenantStore` (not persisted; `{tenant, isLoading, error}`) loads `GET /tenant/<VITE_TENANT_ID>/` once in `App` (full-screen spinner only first time; later `fetchTenantConfig()` refreshes are silent, called after admin saves). Public payload keys consumed: `name, tagline, logo, favicon, theme, show_name, auth_panel, features, feature_labels, registration_schema, promo_banner, announcements` (backend also sends `is_suspended, is_frozen, freeze_message, freeze_code, request_enrollment_free/paid, payment_gateway, subdomain` - `is_frozen`/`freeze_*` are NOT consumed anywhere in the UI per grep).
  `FEATURE_KEYS` (must mirror backend `Tenant.FEATURE_CHOICES`): `courses, study, quiz, mock_tests, pyq, community, analytics, leaderboard, ai, jobs, hackathons`. `isFeatureEnabled(key)` is TRUE unless `features[key]` is explicitly false (default-on, so a missing key never hides things). Backend resolves `features` = super-admin `feature_locks` over tenant `features`. Gating happens in 3 places: `FeatureRoute` in App.jsx, `Sidebar`/`MobileNav` item filters (`feature` prop), and ad-hoc checks (e.g. community preview in CourseDetail). Admin routes are not feature-gated. Only these 11 keys exist on main; any new key must be added to `FEATURE_KEYS`, `DEFAULT_FEATURE_LABELS` and backend `FEATURE_CHOICES`.
  `featureLabel(key, fallback)` / `useFeatureLabel(key, fallback)` return the tenant's renamed label (`feature_labels`) else fallback else platform default; nav items flagged `renamable` use it.
- **Theming**: `config/themes.js` `THEMES` (`sunrise` default, `ocean`, `emerald`, `violet`, ...; keys must match backend `Tenant.THEME_CHOICES`); `applyTheme(key)` writes `--color-primary-*`/`--color-accent-*` "R G B" CSS vars on `:root`. Always style with `primary-*`/`accent-*` Tailwind classes, never hard-coded orange. A few leftovers hard-code `#f97316` (Razorpay `theme.color`, `theme-color` meta). `show_name===false` => logo-only branding in sidebars. Auth-page marketing panel: `resolveAuthPanel(tenant.auth_panel)` over `DEFAULT_AUTH_PANEL`.
- **Dark mode**: `appStore.darkMode` (persist key `app-preferences`, only `darkMode` persisted); toggles `dark` class on `<html>` and re-applies on rehydrate. Use `dark:` variants. `appStore` also holds sidebar/mobile-menu state; its `notifications`, `activeQuiz`, `selectedExam`, `globalLoading` slices look unused (unverified).

## 5. API service layer (`src/services/*.js`)

Convention: plain modules exporting an object of async fns (`export const xService = { ... }`) that `return response.data` (a few export bare functions: `paymentService`, `courseAiService` default export). All go through `api`. Base is `/api/v1` + prefix. Prefixes map to `backend/dailytaiyari/urls.py`:
| Service | Backend prefix (app) |
|---|---|
| `courseService` | `/courses/` (exams: catalog, `study/*`), `/auth/enrollments/` |
| `contentService` | `/content/` (content, progress, study-plans) |
| `contentBuilderService` | admin CRUD: `/courses/admin/*`, `/content/admin/*`, `/quiz/admin/*`, `/assignments/admin/*`, `/coding/admin/*`, `/live-classes/admin/*` |
| `quizService` | `/quiz/` (quizzes, attempts, mock-tests, mock-attempts, pyp, reports, proctoring_event) |
| `mockTestBuilderService` | `/quiz/admin/mock-tests|mock-items/*` + rich attempt calls `/quiz/mock-tests/<id>/start_rich|save_rich|submit_rich|run_item|paper` |
| `assignmentService`, `codingService` | `/assignments/`, `/coding/` (problems, run, submit, meta) |
| `notebookService` | `/notebooks/` (student `notebooks/...`, admin `admin/...`, `admin/generate/jobs` AI) |
| `analyticsService` | `/analytics/` (+ `/courses/explorer/`) |
| `gamificationService` | `/gamification/` |
| `chatService` | `/chatbot/` (sessions, messages, faq, saved, ai-quizzes, workspace; streaming via fetch) |
| `communityService` | `/community/` |
| `jobService` | `/jobs/` (+ `/jobs/admin/*`) |
| `hackathonService` / `hackathonAdminService` | `/hackathons/` / `/hackathons/admin/*` and AI `/tenant-admin/hackathon-ai/` |
| `liveClassService` | `/live-classes/classes/` |
| `certificateService` | `/certificates/` |
| `paymentService` | `/payments/orders/` (+ `/payments/admin/sales/*` via tenantAdminService) |
| `marketingService` | `/marketing/` (coupons validate, admin banners/coupons) |
| `notificationService` | `/notifications/` (incl. email-templates, announcements, birthday) |
| `landingService` / `landingAdminService` | `/landing/` / `/tenant-admin/landing/` |
| `tenantAdminService` | `/tenant-admin/` (settings, email-domain, payment-gateway, zoom), `/auth/tenant-students/`, `/auth/enrollment-requests/`, `/payments/admin/sales/` |
| `aiAdminService` | `/tenant-admin/ai/` (providers, included-models, usage, settings) |
| `courseAiService` / `mockAiService` | `/tenant-admin/course-ai/` / `/tenant-admin/mock-ai/` (jobs: create, poll, refine, regenerate, apply, discard) |
Auth endpoints are called from `authStore` (`/auth/*`), tenant from `tenantStore`. A few components call `api` directly (`PdfReader`/`FileDownloadCard` blob GETs, `ExistingStudentConsentNotice`, hackathon file downloads, GuardianConsent). Error handling: code reads `error.response.data.{detail|error|code|<field>[0]}` ad hoc; no shared error normaliser.
AI generation jobs pattern: POST returns a job immediately, `hooks/useGenerationJob` polls every 2.5 s up to 360 polls (~15 min) until status `preview|failed` (running = `pending|generating`); backend needs the `celery-aiworker` running or jobs sit "queued" forever.

## 6. State management

- Zustand stores (`src/context/`): `authStore` (persisted), `tenantStore` (memory), `appStore` (persisted `darkMode` only). No other global stores; feature state is local `useState` or React Query.
- React Query v5 everywhere for server state (~330 `invalidateQueries/useQueryClient` usages). Defaults in main.jsx. Query keys are inline arrays and INCONSISTENT in style: camelCase for student features (`['studyCourses']`, `['dashboardStats']`, `['enrollments']`, `['chatSessions']`, `['weakTopics']`, `['tenantStudents']`, `['availableCourses']`), kebab for admin/builders (`['cb-courses']`, `['cb-subjects', courseId]`, `['admin-mock-test', id]`, `['admin-jobs']`, `['coursegen-jobs']`, `['mockgen-jobs']`, `['hackathon', id]`, `['hackathon-stage', id, stageId]`). No key factory; when you mutate, grep for the key string and invalidate all sites by hand (the same key is often duplicated across pages, e.g. `['studyCourses']` x9, `['cb-courses']` x9).
- Small localStorage conveniences (not stores): `study:lastCourseId` (Dashboard/Quiz/MockTest/StudyCourse), VideoPlayer prefs, StudyTimer position/mode, dismissed banners/announcements.

## 7. Shared components & heavy-library patterns

- Layout/UX: `LoginGate`, `common/Loading`, `StatCard`, `ProgressRing`, `StreakFire`, `LeaderboardRow`, `SearchableSelect`, `ImageCropper` (react-easy-crop), `TopicMasteryChip`, `course/CourseThumbnail`, `admin/builderShared` (form fields, `NotesTextarea` with inline image upload to `/content/admin/upload-image/`), `common/RichMarkdownEditor` (write/preview over NotesTextarea + MathRenderer).
- Markdown + math: `components/chat/MathRenderer.jsx` = react-markdown + remark-gfm + remark-math + rehype-katex (+ `katex.min.css`); it pre-converts `\[..\]`, `\(..\)` and bracketed-LaTeX to `$$`/`$`. Use it for any student-visible rich text (questions, explanations, AI answers). `chat/quizParser.js` + `ChatQuiz` parse AI-emitted quizzes in chat.
- HTML rendering: ~20 `dangerouslySetInnerHTML` sites; sanitised with DOMPurify only in `hackathonShared`, `JobContent`, `notebook/CellOutput`, `CodingProblem`. Course descriptions/legal/landing/mock content/certificates/EmailSettings/DraftPreview render without DOMPurify (content is authored by tenant admins; treat as XSS surface). `utils/html.js stripHtml` for previews.
- Video: `content/VideoPlayer.jsx` custom player (hls.js for HLS, native file, YouTube/Vimeo/Drive iframe via `resolveVideo`, speed/skip/PiP, prefs in localStorage). Backend video pipeline status shown in CourseManager (`VideoPipelineBadge`, `reprocess_video`).
- PDF: `content/PdfReader.jsx` (lazy) = react-pdf; worker via `new URL('pdfjs-dist/build/pdf.worker.min.mjs', import.meta.url)` (relies on transitive `pdfjs-dist`); bytes fetched through authenticated `api` (`/content/<id>/pdf/`) as blob, no download toolbar, context menu disabled.
- Monaco: `coding/CodeEditor.jsx` (lazy) self-hosts Monaco: imports full `monaco-editor` + `editor.worker?worker` and `loader.config({monaco})`; only the base editor worker (no TS/JSON workers; python/cpp/java highlight is Monarch). Languages: python | cpp | java. Biggest chunk in the build.
- Notebooks/labs: `components/notebook/*` + `pages/NotebookPage|NotebookBuilder`. Student code runs client-side in Pyodide: `hooks/usePyodideKernel` spawns `workers/pyodideKernel.worker.js` (classic worker, `new Worker(new URL(...), {type:'classic'})`) which loads Pyodide `v0.28.3` from `cdn.jsdelivr.net/pyodide/...` at runtime (needs CDN access / CSP allowance; numpy, pandas, scipy, scikit-learn, matplotlib). Protocol messages: `init/run/runTests/reset` -> `status/ready/stream/result/tests/fatal`. Kernel states idle/loading/ready/busy. Final grading is server-side (`nbrunner` + `notebooks` Celery queue); `LabSubmitFlow` handles submit. Cell roles (`answer`, `readonly`, ...) in `notebookDoc.js`; `NotebookEditor` handles dataset fetch (`fetch(dataset.url)`). `.ipynb` import via admin endpoint. See wiki `notebooks-labs.md`.
- Certificates: SVG templates (`CertificateTemplates.jsx`) rasterised to PNG then jspdf; tenant logo fetched as data URL first (`certificateDownload.js`, needs CORS on blob storage).
- Charts: recharts (Analytics, AILearning). Confetti: canvas-confetti/react-confetti. Icons: lucide-react (MUI icons unused).
- Other: `StudyTimer` floating widget; `hooks/useVoiceDictation` (en-IN default); quiz proctoring in `QuizAttempt` (fullscreen/visibility violations -> `POST /quiz/quizzes/<id>/proctoring_event/`).

## 8. Testing, lint, CI

- NO tests: no `*.test.*`/`*.spec.*`, no vitest/jest/playwright deps, no test script.
- ESLint: `npm run lint` is declared (eslint 8.56 + react + react-hooks plugins installed) but NO ESLint config exists in the exported tree (no `.eslintrc*`, no `eslintConfig` in package.json, no `eslint.config.js`), so lint errors out with "couldn't find a configuration file" (verified by file search of the export; could exist untracked locally). `--max-warnings 0` would be very strict for this codebase. Do not gate CI on lint without first adding a config. Source has inline `/* eslint-env worker */` comments only.
- No frontend CI workflow in the repo (`.github/` on main only has `skills/`); build/deploy is done by Netlify git integration (wiki: frontend and landing "deploy automatically via Netlify"). Branches: `main` = pre-prod, `production` = prod (wiki `branching-strategy.md`/`deployment.md`).
- No TypeScript, no `tsc`/type check; the only compile-time gate is `vite build`. A reasonable CI gate = `npm ci && npm run build` (with no `VITE_TENANT_ID`/`VITE_API_URL`, inject-meta just warns and the build still succeeds).
- Lockfile: `package-lock.json` lockfileVersion 3. It contains platform binaries ONLY for `@rollup/rollup-darwin-x64`, `@rollup/rollup-linux-x64-gnu` and `@esbuild/darwin-x64` (generated on an Intel Mac). `package.json` therefore pins `optionalDependencies: {"@rollup/rollup-linux-x64-gnu": "4.57.1"}` so Linux x64 builds (Netlify, GitHub ubuntu runners) work. Consequences: `npm ci` on Windows/Apple-silicon/arm64 may miss the native rollup/esbuild binary (the classic npm optional-deps bug: fix = `npm install` locally or delete lock+node_modules); `@esbuild/linux-x64` is not in the lockfile (unverified whether esbuild's installer fallback fetches it; builds on Netlify evidently work). Keep rollup optional pin in sync with the `rollup` version in the lock (both 4.57.1) when upgrading vite.
- Bundle-size / build-time risks: no code-splitting beyond Monaco/PdfReader; all ~63 pages + MUI/emotion + recharts + framer-motion + katex + jspdf + hls.js are in the main chunk graph (index chunk likely multi-MB; unverified, not built). Monaco full import is heavy. Pyodide is NOT bundled (CDN). Build memory: if CI OOMs use `NODE_OPTIONS=--max-old-space-size=4096` (unverified need).

## 9. Gotchas / tech debt

- Per-tenant build model: every tenant = separate site + env; adding tenant requires a new Netlify site with `VITE_TENANT_ID`, `VITE_API_URL`, optionally `VITE_SITE_URL`, plus backend allowed-origin for the new domain. A wrong/missing tenant id yields a spinner->unbranded app with every API call 403.
- Refresh-token path missing `X-Tenant-ID` (section 4). `logout()` doesn't clear React Query cache or call backend; a different user logging in on the same tab can see cached data until refetch (cache lives in memory, is reset on page reload; the 401 failure path does `window.location.href`, which resets it).
- Two parallel mock-test flows (legacy `MockTestAttempt/Review` for PYP, "rich" `RichMockAttempt/Review` for tenant mocks); two aliases for AI Doubt Solver; StudyChapters (`/study/:subjectId`) vs `/study/course/:courseId`.
- Huge page files (AdminDashboard 4k lines, CourseManager 2.2k) with inline sub-components and inline modal/field helpers re-declared in several files (`StatCard` exists in both `common/` and AdminDashboard).
- `dangerouslySetInnerHTML` without DOMPurify in many places; tokens in localStorage.
- `@mui/*` and `@emotion/*` are dependencies but have ZERO imports in `src/` (verified), the `@` alias is also unused, and `recharts` is only imported by AILearning/Analytics, `jspdf` only by certificateDownload, `hls.js` only by VideoPlayer. Safe to drop MUI/emotion to cut install time.
- Direct `window.location.href = '/login'` hard navigations (api.js, Profile) bypass the router. Tenant `is_frozen` payload is ignored by the UI. No `console.log` calls (only console.error/warn); no error boundary component anywhere (a render error blanks the app).
- Query-key naming inconsistency (section 6); services mostly return `response.data` but some pages call `api` directly.
- Intelligence-layer features (feat/intelligence-foundation) are not in this export; do not assume `tenant.features` has opt-in keys here.
