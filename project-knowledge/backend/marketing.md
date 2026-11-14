# marketing

Source: branch `main`.

- **Purpose**: Tenant promotions: discount **coupons** (validated at checkout and re-validated server-side by `payments`) and a sitewide **promo banner** shown in the app header. NOTE: despite the brief, there is **no leads model in this app**. Marketing-site leads (demo bookings, contact messages, career applications) live in `core` (`core.PlatformLead` -> `DemoBooking`, `ContactMessage`, `JobApplication`; public endpoints under `/api/v1/platform/` via `core/urls.py`, superadmin views `/api/v1/superadmin/leads/`).
- **Mount**: `/api/v1/marketing/` (backend/dailytaiyari/urls.py).
- Tenant feature flags: none for marketing (not in `Tenant.FEATURE_CHOICES`).

## Key models (backend/marketing/models.py; plain `models.Model`, UUID pk, `tenant` FK required, NOT TimeStampedModel)
| Model | Notes |
|---|---|
| `Coupon` | `code` (upper-cased on save), **UniqueConstraint `uniq_coupon_code_per_tenant (tenant, code)`**, `discount_type` percent/flat, `discount_value`, `max_discount_amount` (cap for percent), `min_order_amount`, `applies_to_all` or `courses` M2M, `starts_at`/`ends_at`, `usage_limit` (total, null=unlimited), `per_user_limit` (0=unlimited, default 1), `times_redeemed`, `is_active`. Helpers `is_live()`, `is_expired/is_scheduled/is_exhausted`, `compute_discount(amount)` (Decimal ROUND_HALF_UP, never > amount). |
| `CouponRedemption` | `coupon`, `student`, `course`, `order`->`payments.PaymentOrder` (SET_NULL), `original/discount/final_amount`, `currency`. Written once per paid order (idempotent per `(coupon, order)`). |
| `PromoBanner` | `title`, `message`, `cta_label`, `cta_url`, optional `coupon` FK, `theme` sunset/ocean/forest/royal/midnight/custom (+`bg_color`/`text_color` for custom), `dismissible`, `is_active`, `starts_at`/`ends_at`. |
Migration: only `0001_initial`.

## API (backend/marketing/urls.py)
- Student: `POST coupons/validate/` (`IsAuthenticated`; body `code`, `course` UUID) -> `{valid, code, discount_type, discount_value, original_amount, discount_amount, final_amount, currency}` or 400 `{valid:false, detail}`. Hidden/other-tenant course -> 404.
- Tenant admin (`IsAuthenticated + IsTenantAdmin`, role admin only), all tenant-scoped via `request.tenant`: `admin/coupons/` (list/create), `admin/coupons/<uuid>/` (retrieve/update/delete), `admin/coupons/course-options/` (paid courses picker), `admin/coupons/<uuid>/redemptions/`, `admin/banners/`, `admin/banners/<uuid>/`. Course/coupon pickers are re-scoped to the tenant in the views (`_ScopedCourseFieldMixin`, banner `coupon` queryset).
- Public banner delivery is NOT in this app's URLs: `core.views._public_promo_banner` embeds the newest `is_active` + live banner in the public `GET /api/v1/tenant/<id>/` payload (`PublicPromoBannerSerializer`: exposes `coupon_code` only if the coupon `is_live()`).

## Business logic (backend/marketing/services.py)
- `validate_coupon(tenant, code, course, student)` -> quote dict or raises `CouponError(message)`: checks existence (case-insensitive within tenant), active, scheduled, expired, exhausted, course applicability, course price > 0, `min_order_amount`, per-user limit (counts `CouponRedemption`), then computes discount/final.
- `record_redemption(...)` (atomic; bumps `times_redeemed` with `F()`); called from `payments.services.mark_order_paid` (best-effort, exceptions swallowed).
- No Celery, signals, or management commands.

## Integrations / settings / env
None.

## Cross-app dependencies
Imports `exams.Course`, `core.permissions.IsTenantAdmin`, FK to `core.Tenant`, `users.StudentProfile`, `payments.PaymentOrder`. Called by `payments/views.py` (`validate_coupon` in `CreateOrderView`), `payments/services.py` (`record_redemption`), `core/views.py` (banner). Frontend: `frontend/exam-frontend/src/services/marketingService.js`.

## Tests
None in backend/marketing.

## Gotchas / risks
- **Usage limits are not race-safe**: `validate_coupon` checks `is_exhausted` / per-user count at order creation, but redemption (and the `times_redeemed` increment) is only recorded when the order is **paid**; many concurrent checkouts can all pass validation, so `usage_limit`/`per_user_limit` can be exceeded. Unpaid/abandoned orders consume nothing.
- Coupon `courses` / `applies_to_all` is evaluated against `course.price` only; no currency check.
- `AdminCouponSerializer` validates discount_value in `validate`; the model's `clean()` is not invoked by DRF.
- Deleting a coupon cascades its `CouponRedemption` rows (FK CASCADE) — loses sales attribution; banners just null the FK.
- `PromoBanner.cta_url` is a free-form string (not URL-validated) rendered in the app header — open-redirect/`javascript:` handling is a frontend concern (unverified).
- Admin banner `is_active` is separate from `starts_at/ends_at`; only the first (newest) active banner is shown.
- Validation endpoint reveals coupon state differences ("expired", "exhausted", "not active yet") to any authenticated student -> code enumeration possible (no rate limiting in this app).

## Key files
- backend/marketing/models.py — Coupon, CouponRedemption, PromoBanner
- backend/marketing/services.py — validate_coupon, record_redemption
- backend/marketing/views.py — student coupon validation
- backend/marketing/admin_views.py, admin_serializers.py — tenant-admin CRUD
- backend/marketing/serializers.py — public banner + validate-request serializers
- backend/core/views.py (`_public_promo_banner`) — banner delivery
- backend/payments/views.py, services.py — consumers
