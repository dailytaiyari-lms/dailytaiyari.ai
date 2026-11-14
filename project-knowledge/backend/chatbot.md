# chatbot

Source of truth: `main` branch (production). Paths are repo-relative.

- **Purpose**
  - Student-facing AI Doubt Solver (course-aware chat, streaming, saved answers, FAQs, AI-generated practice quizzes with XP).
  - Also the platform's **shared LLM layer**: provider abstraction (`providers.py`), per-request provider/budget resolution (`resolver.py`), usage metering (`AIUsageRecord`), tenant "bring your own key" admin API, and the super-admin "platform LLM fleet" (platform-owned keys lent to tenants with token/dollar ceilings). `coursegen`, `notebooks.aigen`, `mockgen`, `hackathons` all call into it.
  - The app has no Celery tasks and no management commands.

## Key models (`backend/chatbot/models.py`)
All inherit `core.models.TimeStampedModel` (UUID pk, nullable `tenant` FK with `related_name='+'`, `created_at`, `updated_at`) unless noted.

| Model | Purpose / notable fields |
|---|---|
| `ChatSession` | One conversation. `student` FK StudentProfile (CASCADE), optional `course`/`topic`/`subject` (SET_NULL), `title`, `is_active`, `message_count`, `was_helpful`, `rating` (1-5). |
| `ChatMessage` | `session`, `role` (user/assistant/system), `content`, `image` (ImageField `chat_images/`), `model_used` (<=50 chars), `tokens_used`, `response_time_ms`, `is_helpful`. Special `model_used` values: `unavailable`, `error` (canned fallback replies). |
| `SavedResponse` | Bookmarked assistant message. `unique_together (student, message)`. |
| `FrequentQuestion` | Admin-curated FAQ (question/answer, topic/subject, views/helpful counters). Public read. |
| `AIQuizAttempt` | A quiz generated in chat and attempted. `questions_data` JSON (client-supplied incl. `correct_option`), totals, `percentage`, `xp_earned`, `completed_at`. `calculate_results()` / `calculate_xp()` (5 XP/question scaled by accuracy + bonus 10/5/2 at 100/80/60%). Constants `AI_QUIZ_XP_CAP_PER_ATTEMPT=25`, `AI_QUIZ_XP_DAILY_CAP=75`. |
| `AIQuizQuestion` | Per-question row (`question_index`, `topic` concept label, `options` JSON, `correct_option`, `user_answer`, `is_correct`, `explanation`). |
| `AILearningStats` | One-to-one per student: totals, streaks, `topic_performance` JSON `{topic: {attempted, correct, quizzes}}`, perfect/80% counters. `update_from_attempt()` folds a quiz in. |
| `AIProviderConfig` | **Tenant BYO-key** config. UUID pk, `tenant` (NOT NULL here, `related_name='ai_providers'`), `provider` (choice), `api_key_encrypted`, `base_url`, `model`, `api_version` (Azure, default `2024-10-21`), `temperature` (0.7), `max_tokens` (2000), `is_active`, last-test fields. **UniqueConstraint (tenant, provider)** `uniq_tenant_ai_provider`. Many rows per tenant, exactly one `is_active` (enforced in the admin view, not by a DB constraint). `.api_key` property encrypts/decrypts via `core.encryption`. `is_configured`, `effective_base_url`, `effective_model` helpers. |
| `AISettings` | Per-tenant behaviour (row created lazily by `resolver.get_ai_settings`): `is_enabled` (master switch), `student_daily_message_limit` (default 50, 0=unlimited), `monthly_token_budget` (0=unlimited; applies to tenant-key spend only), `allow_quiz_generation`, `allow_course_context`, `custom_instructions` (<=2000 chars, appended to every system prompt). |
| `AIUsageRecord` | One metered LLM call. `student`/`session` (SET_NULL), `source` (`tenant` \| `platform`), `provider`, `model` string, `platform_model` FK (SET_NULL), `feature` (`chat`,`quiz`,`coursegen`,`notebookgen`,`mockgen`,`hackathongen`,`other`), prompt/completion/total tokens, `estimated_cost_usd` Decimal(10,6), `response_time_ms`, `was_successful`, `error_message` (500 chars). Indexes: (tenant,created_at), (tenant,source,created_at), (source,created_at). |
| `PlatformAIProvider` | **Platform-owned** LLM account (super admin only): `name`, `provider`, encrypted key, `base_url`, `api_version`, `is_enabled`, `notes`, `sort_order`, last-test fields. Never exposed to tenants. Not tenant-scoped. |
| `PlatformAIModel` | A model served by a platform provider: `model_name` (sent verbatim), `label`, `description`, `input_cost_per_million` / `output_cost_per_million` (USD, editable at runtime = price table), `max_output_tokens` (4000), `is_enabled`. UniqueConstraint (provider, model_name). `is_usable` = model+provider enabled and provider configured. |
| `TenantAIAllocation` | One-to-one per tenant: super-admin half (`is_enabled` default **False**, `granted_models` M2M, `default_model`, `monthly_token_limit`, `monthly_cost_limit_usd`, 0 = unlimited on that axis, `notify_at_percent` default 80) and tenant-admin half (`tenant_enabled_models` M2M narrowing, `tenant_default_model`). `last_notified_period` ('YYYY-MM') + `last_notified_percent` de-dupe warnings. Methods `usable_models()`, `selectable_models()` (tenant narrowing can never empty the set), `effective_model()` (tenant default > platform default > first). |

Migrations: 0001-0011. 0008 is a data migration seeding `TenantAIAllocation` from legacy `Tenant.ai_platform_monthly_tokens` (reversible: pushes limits back). 0009-0011 only widen `AIUsageRecord.feature` choices (no schema risk). Migration 0004 adds the `tenant` FK to the original models.

## API
URL prefixes from `backend/dailytaiyari/urls.py`:

**Student: `/api/v1/chatbot/`** (`backend/chatbot/urls.py`, DRF router; all `IsAuthenticated` except FAQ = `AllowAny`)
- `GET workspace/` (`AIWorkspaceView`): enrolled courses, tailored `starter_prompts`, `is_available`/`unavailable_reason`/`model_label`.
- `sessions/` `ChatSessionViewSet`: CRUD + actions `set_course`, `send_message` (JSON reply), `send_message_stream` (newline-delimited JSON over `text/event-stream`, `X-Accel-Buffering: no`), `close`, `rate`. Filters: topic, subject, course, is_active; search title.
- `messages/` read-only + `mark_helpful`, `save`. `saved/` CRUD of `SavedResponse`. `faq/` read-only + `mark_helpful`, `suggestions`.
- `ai-quizzes/` `AIQuizAttemptViewSet`: `submit` (creates attempt + question rows, awards XP, updates stats/daily activity/badges), `review`, `stats`, `by_topic`, `wrong_questions`. It is a full `ModelViewSet`, so default create/update/delete routes also exist (see gotchas).

**Tenant admin: `/api/v1/tenant-admin/ai/`** (`backend/chatbot/admin_urls.py`; `IsAuthenticated` + `core.permissions.IsTenantAdmin` = role `admin`)
- `providers/` GET (providers, `catalog`, settings, usage-ready flag, `included` platform allowance), PUT (create/update one provider by `provider` key; activating one deactivates the rest in a transaction), DELETE `?provider=`.
- `providers/test/` POST: sends a "ping" prompt (accepts inline `api_key` so credentials can be verified before saving; records result on the stored row).
- `settings/` GET/PATCH `AISettings`. `usage/` GET (`?days=1..365`, default 30; by-model breakdown, failures count). `included-models/` GET/PUT (tenant narrows/chooses default among models the platform granted; validates ids against the grant).

**Super admin: `/api/v1/superadmin/ai/`** (routes live in `backend/core/superadmin_urls.py`, views in `backend/chatbot/platform_views.py`; `IsSuperAdmin` = `is_superuser`, tenant-exempt path)
- `providers/` (list/create), `providers/<uuid>/` (PATCH/DELETE), `providers/<uuid>/test/`, `providers/<uuid>/models/` (POST), `models/<uuid>/` (PATCH/DELETE), `usage/` (platform-source spend by tenant/model/feature). Tenant grants: `tenants/<uuid>/ai-allocation/` (`TenantAIAllocationView`, GET/PUT; PUT resets the warning de-dupe fields so a top-up re-arms notices). All mutations are written to the super-admin audit trail via `core.superadmin_views._record_action`.

## AI provider layer (detail)

### Supported providers (`AIProviderConfig.PROVIDER_CHOICES`)
| key | protocol | default base URL | default model |
|---|---|---|---|
| `openai` | OpenAI SDK | SDK default (api.openai.com) | `gpt-4o-mini` |
| `azure_openai` | `AzureOpenAI` SDK, needs resource endpoint + `api_version`; model = *deployment name* | none (required) | none |
| `gemini` | OpenAI-compatible endpoint | `https://generativelanguage.googleapis.com/v1beta/openai/` | `gemini-2.0-flash` |
| `anthropic` | **Native Messages API over plain `requests`** (header `anthropic-version: 2023-06-01`), no SDK | `https://api.anthropic.com` | `claude-3-5-haiku-latest` |
| `groq` | OpenAI-compatible | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile` |
| `openrouter` | OpenAI-compatible | `https://openrouter.ai/api/v1` | `meta-llama/llama-3.3-70b-instruct:free` |
| `together` | OpenAI-compatible | `https://api.together.xyz/v1` | `meta-llama/Llama-3.3-70B-Instruct-Turbo-Free` |
| `ollama` | OpenAI-compatible, keyless | `http://localhost:11434/v1` | `llama3.1` |
| `custom` | any OpenAI-compatible (vLLM, LM Studio, LiteLLM), keyless | none (required) | none |

Keyless providers = `ollama`, `custom` (need `base_url` only). Model dropdown suggestions + provider docs links/blurbs are server-side in `admin_views._catalog()` (adding a provider = backend-only change + a `PROVIDER_CHOICES` entry; `coursegen.generation._model_suggestions` reuses it).

### `backend/chatbot/providers.py`
- `ResolvedProvider` dataclass decouples the call path from DB rows: `from_config(AIProviderConfig, source)` and `from_platform_model(PlatformAIModel, ...)`. Fields: provider, api_key, base_url, model, api_version, temperature, max_tokens, `source` (`tenant`/`platform`), `platform_model`, `extra_headers`.
- Public API: `complete(rp, messages) -> (content, Usage, elapsed_ms)`, `stream(rp, messages)` yields `(delta, None)` and a final `('', Usage)`, `test_connection(rp) -> (ok, message)` (probe uses `max_tokens=256` so reasoning models don't return empty), `estimate_cost_usd(model, usage, platform_model=None)`. All raise `AIProviderError` (admin-safe message, <=300 chars).
- OpenAI SDK clients are built per call with `max_retries=1`. Azure uses `AzureOpenAI`. API key `'not-needed'` is substituted for keyless providers.
- **Token-param negotiation**: model names matching `^(o[1-9]|gpt-5)` (optionally after `/`) get `max_completion_tokens`, everything else `max_tokens`; if the provider's 400 names the other param, it retries once and caches the correction in a process-global dict `_TOKEN_PARAM_OVERRIDES` (per-process, lost on restart).
- Streaming asks for `stream_options.include_usage`, falling back to a plain stream if rejected. A stream with zero tokens raises `AIProviderError` (not a blank success). HTTP-200 bodies with `error` / empty `choices` (OpenRouter style) are surfaced as readable errors; `finish_reason` `length`/`content_filter` have specific messages.
- No Anthropic-specific features (no prompt caching, tools, vision); messages are flattened to system + user/assistant turns.

### Timeouts
- `CONNECT_TIMEOUT = 10`s. `READ_TIMEOUT = settings.AI_READ_TIMEOUT` (default **90**s) for web requests; `BACKGROUND_READ_TIMEOUT = settings.AI_READ_TIMEOUT_BACKGROUND` (default **600**s) when running inside a Celery task. Detected at call time by `in_background_worker()` via `celery.current_task.request.id` (so the same code path picks the right timeout).
- Invariant (asserted in `tests_providers.py`): web read timeout must stay **below** `gunicorn.conf.py` `timeout = 120`, otherwise gunicorn kills the worker before the provider error is shown. nginx `proxy_read_timeout` is 300s.
- The OpenAI SDK `timeout` is per-request read timeout; the Anthropic `requests` call uses `(connect, read)`. A provider that trickles tokens can therefore exceed the nominal read timeout.

### Key configuration: tenant vs platform
- **Tenant keys**: stored per tenant in `AIProviderConfig.api_key_encrypted`, Fernet-encrypted by `backend/core/encryption.py`. Key derived from `settings.FIELD_ENCRYPTION_KEY` if set, else from `SECRET_KEY` (SHA-256). **If `SECRET_KEY` rotates and `FIELD_ENCRYPTION_KEY` was never set, every stored key silently decrypts to `''`** (decrypt swallows errors) and every provider shows as unconfigured.
- Keys are write-only in serializers (`api_key` write_only, `has_api_key` boolean). Super-admin serializer exposes only a masked hint (first 3 + last 4 chars).
- **Platform keys**: `PlatformAIProvider` rows (encrypted the same way), granted to tenants through `TenantAIAllocation`.
- **Legacy fallback**: `settings.OPENAI_API_KEY` (env) + `settings.AI_PLATFORM_MODEL` (default `gpt-4o-mini`, hard-coded `max_tokens=1500`) — only used when an allocation is `is_enabled` but has **no granted models** (state every tenant migrated from the old `ai_platform_monthly_tokens` grant lands in).

### Resolution order (`resolver.resolve(tenant, student)`)
1. Tenant `is_enabled` in `AISettings`, else `AIUnavailable(reason='disabled')`.
2. Student daily cap: count of successful `AIUsageRecord` rows for that student in the **trailing 24h** (rolling window, not calendar day). Applies to all sources.
3. Tenant's active + `is_configured` `AIProviderConfig` -> source `tenant`; enforce `monthly_token_budget` (tenant-source tokens since month start) -> `tenant_budget`.
4. Else platform: `platform_available()` -> `TenantAIAllocation` must be enabled, not exhausted (token OR cost ceiling, whichever first), with a usable model -> source `platform`.
5. Else legacy env key (only when reason `no_models`).
6. Else `AIUnavailable` with reason one of `not_configured`, `platform_exhausted`, `platform_unavailable` (granted models later disabled; deliberately does NOT fall back to another account), `no_tenant`.
- Reasons are returned to the frontend (`unavailable_reason`) so the UI can branch.

### Cost tracking
- `resolver.record_usage(...)` writes `AIUsageRecord` (never raises; swallows all exceptions and returns None, so metering failure = silent under-counting). Called by chat, coursegen, notebook gen, mockgen, hackathon gen.
- Cost estimate: if a `PlatformAIModel` is attached its admin-maintained per-million prices win (0/0 -> cost 0); otherwise a static substring table `_PRICE_PER_MILLION` in `providers.py` (gpt-4o, gpt-4o-mini, gpt-4.1*, o4-mini, gemini-2.0-flash/2.5-flash/2.5-pro, claude-3-5-haiku, claude-3-7-sonnet, claude-sonnet-4, llama-3.3-70b); `:free` suffix and unknown models = 0. Lookup is first-substring-match in dict insertion order (`if name in model.lower()`), and `gpt-4o` / `gpt-4.1` are listed before their `-mini`/`-nano` variants, so (from reading the code) `gpt-4o-mini`, `gpt-4.1-mini` and `gpt-4.1-nano` are priced as the larger sibling (over-estimate ~16x for gpt-4o-mini). The `-mini` entries are effectively dead.
- Streaming usage missing -> approximated as chars/4 (both in chat and generation).
- `allocation_status()` returns tokens/cost used vs limits plus worst-axis `percent_used`; `maybe_warn_allowance()` fires `notifications.services.on_ai_allowance_warning` at most twice per month (threshold, then 100%). Tenant-facing payloads strip dollar fields (`cost_*`); tenants see tokens/percent only.
- `usage_summary(tenant, days)` feeds the admin usage panel; super-admin report groups platform-source spend by tenant, model, feature.

## Business logic
- `backend/chatbot/services.py` `ChatService`: `create_session`, `add_message`, `get_session_history(limit=60)` (newest 60, re-ordered oldest-first), `process_question` (non-stream), `process_question_streaming` (generator of NDJSON chunks; terminal object has `done: true`, `success`, `full_content`, `message_id`, `reason` on failure).
- **Chat memory** = last `HISTORY_TURNS = 30` user/assistant messages of the session are replayed on every request, plus a freshly built system prompt (`build_system_prompt`): base tutor rules (LaTeX `$..$`/`$$..$$` math, strict quiz output format with `Quiz Topic:` / `Answer:` / `Topic:` / `Explanation:` lines parsed by the frontend) + optional `NO_QUIZ_CLAUSE` (when `allow_quiz_generation` False) + subject/topic context + course context block (when session has a course and `allow_course_context`) + tenant `custom_instructions`. No long-term memory beyond the session; no summarisation.
- **Tenant for billing** is derived from the student's user (`tenant_of_student`), never from the stored `session.tenant` (which came from a client header).
- Course context (`course_context.py`): `enrolled_courses`/`enrolled_course_or_none` (approved + active enrollment + `course.status == 'active'` + same tenant), snapshot of syllabus/progress/weak topics, `starter_prompts`. `work_context.py` adds recent wrong answers, assignment status, coding failures (reads `quiz`, `assignments`, `coding`, `content` models). Context is re-validated at send time, so revoked enrollments stop leaking course data. Both are capped to a few hundred tokens and re-sent every message.
- Quiz submit (`AIQuizAttemptViewSet.submit`): trusts client-provided `correct_option`/`user_answer`; XP clamped per attempt (25) and per day (75, summed from `gamification.XPTransaction` type `ai_quiz`), then `GamificationService.award_xp`, `AILearningStats.update_from_attempt`, `AnalyticsService.update_daily_activity`, `check_and_award_badges`. Topic labels normalised by `normalize_topic_label` (drops generic labels like "Practice Quiz").
- Failure UX: provider/availability errors are stored as an assistant message built from `UNAVAILABLE_TEMPLATE`, with `model_used='unavailable'|'error'` and `success: false`; the HTTP status is still 200.
- No Celery tasks, signals, or management commands in this app.

## Integrations / settings / env vars
- Env/settings: `OPENAI_API_KEY` (legacy platform fallback), `AI_PLATFORM_MODEL`, `AI_READ_TIMEOUT` (90), `AI_READ_TIMEOUT_BACKGROUND` (600), `FIELD_ENCRYPTION_KEY`, `SECRET_KEY`. Docker compose passes `OPENAI_API_KEY` to all app containers. `openai` and `cryptography` Python packages; `requests` for Anthropic.
- Outbound network: whatever `base_url`/provider each tenant or platform account configures. Images uploaded in chat go to default media storage (`STORAGE_BACKEND` azure/s3/local).
- Notifications: `notifications.services.on_ai_allowance_warning` (admin notification + deep link `/admin-dashboard?tab=ai`).

## Cross-app dependencies
- Imports: `core` (TimeStampedModel, Tenant, `encryption`, permissions, `TenantAwareViewSet`, superadmin audit), `exams` (Topic, Subject, Course), `users` (StudentProfile, CourseEnrollment), `gamification`, `analytics`, `notifications`, `content`/`quiz`/`assignments`/`coding` (via `work_context`/`course_context`).
- Imported by: `coursegen` (generation, views, apply of providers), `notebooks.aigen`, `mockgen`, `hackathons` (ai views + generation), `core/superadmin_urls.py` + `core/superadmin_serializers.py` (tenant AI summary), `notifications`, `gamification/tests.py`.
- Middleware: `TenantMiddleware` requires `X-Tenant-ID` and rejects mismatch with the caller's tenant; `chatbot/tenancy.py::request_tenant` re-derives the tenant from the user as defence in depth (superusers act on the header).

## Tests
- `backend/chatbot/tests.py` (~480 lines): platform AI economy: resolution order, token/cost ceilings, tenant isolation of usage, platform price attribution, exhaustion warnings (once per threshold/month, top-up reopens), super-admin API (keys never returned, key preserved on update, grants, default must be granted), tenant "included models" API (no pricing exposed, cannot enable ungranted model, revoked models don't wedge panel), course-builder grant boundary, legacy env-key fallback. **No tests for the chat endpoints, streaming, quiz submit, course context.**
- `backend/chatbot/tests_providers.py`: `_openai_content` error shapes (None/empty choices, OpenRouter nested errors, `length`, `content_filter`), stream failure modes, timeout invariants (web < gunicorn; background longer; timeout error wording), `max_tokens` vs `max_completion_tokens` negotiation and caching. LLMs are never actually called (fakes/mocks).

## Gotchas / tech debt / risks
- **SSRF surface**: tenant admins can set arbitrary `base_url` (any provider key accepts an override; `ollama`/`custom`/`azure` require it) and the backend (web or worker) will POST to it with no allow/deny validation (`admin_serializers.py` only checks presence). The `providers/test/` endpoint echoes upstream error text (<=300 chars). Same for `coursegen` `TranscribeView`, which posts audio to `<base_url>/audio/transcriptions`. Internal hosts (db, redis, piston, nbrunner, cloud metadata) are reachable from the backend network.
- **Cost table bug**: substring lookup over a dict (see Cost tracking) — `gpt-4o-mini` / `gpt-4.1-mini` / `gpt-4.1-nano` are priced as the bigger sibling since `gpt-4o` / `gpt-4.1` appear earlier. Affects only tenant-source estimates (platform models use their own prices) and `CourseGenerationJob.estimated_cost_usd` (which always uses the built-in table, never platform prices).
- Tenant-budget and student-limit checks happen once per request before the call; concurrent requests can overshoot. Platform ceiling is checked at resolve time, not per call; long coursegen jobs can exceed it by one job.
- The `AISettings.student_daily_message_limit` window is a rolling 24h and counts only `was_successful=True` rows; failed calls are free.
- Uploaded chat `image` is saved on the message but **never sent to the model** (text-only prompts). `ChatSession`/`SavedResponse` viewsets override `get_queryset` to filter by student, so the `TenantAwareViewSet` tenant filter is bypassed (isolation relies on student ownership). `AIQuizAttempt`/`AIQuizQuestion`/`AILearningStats` rows created by `submit` have `tenant = NULL` (tenant not set). `AIQuizAttemptViewSet` is a full `ModelViewSet`: standard POST/PATCH/DELETE are reachable by students; read-only fields protect xp/totals but `questions_data` is writable.
- XP farming: quiz correctness is client-asserted (`correct_option` sent by browser); mitigated only by the 25/attempt and 75/day caps.
- `_TOKEN_PARAM_OVERRIDES` is per-process; first call after each restart may pay one extra failed request.
- `record_usage` swallows all exceptions: DB failures mean uncounted spend.
- Default `SECRET_KEY` and `DEBUG=True` in `dailytaiyari/settings.py` are insecure defaults; with no `FIELD_ENCRYPTION_KEY` the key-encryption key derives from `SECRET_KEY`.
- JWT access token lifetime is 365 days (settings), relevant because the AI endpoints spend money.
- Provider failure still returns HTTP 200 with `success: false` (frontend must read the flag). Hard-coded English prompts; language handled only through `custom_instructions`.
- `chatbot` admin (`admin.py`) registers only the original models + AIProviderConfig/AISettings/AIUsageRecord; Platform* and TenantAIAllocation are managed via the super-admin API only. Django admin shows `AIProviderConfig` with the encrypted blob field.

## Key files
- `backend/chatbot/models.py` - all models and provider catalogue constants.
- `backend/chatbot/providers.py` - unified LLM client, timeouts, cost estimation.
- `backend/chatbot/resolver.py` - provider selection, quotas, allocation status, metering, warnings.
- `backend/chatbot/services.py` - prompt assembly, chat processing (sync + streaming).
- `backend/chatbot/course_context.py`, `backend/chatbot/work_context.py` - course/progress/mistake context for prompts.
- `backend/chatbot/views.py`, `backend/chatbot/serializers.py`, `backend/chatbot/urls.py` - student API.
- `backend/chatbot/admin_views.py`, `admin_serializers.py`, `admin_urls.py` - tenant-admin AI Features API + provider catalogue.
- `backend/chatbot/platform_views.py`, `platform_serializers.py` - super-admin LLM fleet/allocations/usage (routed in `backend/core/superadmin_urls.py`).
- `backend/chatbot/tenancy.py` - user-derived tenant resolution.
- `backend/core/encryption.py` - Fernet field encryption used for API keys.
- `backend/dailytaiyari/settings.py` (AI_*, OPENAI_API_KEY, FIELD_ENCRYPTION_KEY) and `backend/gunicorn.conf.py` (timeout 120).
