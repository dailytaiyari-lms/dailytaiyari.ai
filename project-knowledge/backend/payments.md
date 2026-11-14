# payments

Source: branch `main`.

- **Purpose**: Pay-to-enrol for paid courses. A tenant connects its OWN payment gateway (Razorpay, Cashfree or PayU); students check out, the order is confirmed by browser return and/or provider webhook, and an approved `CourseEnrollment` is granted. Also a tenant-admin sales dashboard with refunds and access revoke/restore. Coupons (from `marketing`) discount the charge server-side.
- **Mount**: `/api/v1/payments/` (backend/dailytaiyari/urls.py). Webhook + PayU callback are in `TENANT_EXEMPT_PATHS` (backend/core/middleware.py): `/api/v1/payments/webhook/`, `/api/v1/payments/payu/callback/`.
- No platform-level payment keys: gateway credentials are per tenant and stored in the DB (`core.PaymentGateway`), not env vars.

## Key models
- `payments.PaymentOrder` (backend/payments/models.py; own UUID pk, NOT TimeStampedModel): `tenant` (required), `student`, `course`, `enrollment` (SET_NULL), `provider` razorpay/cashfree/payu, `provider_order_id` (indexed; Razorpay order id / Cashfree order_id / PayU `txnid`), `provider_payment_id`, `amount` (charged), `currency`, `coupon` FK, `original_amount`, `discount_amount`, `status` created/paid/failed/cancelled/refunded, `is_test_mode`, refund fields (`provider_refund_id`, `refund_amount`, `refund_reason`, `refunded_at`, `refunded_by`). Indexes (provider, provider_order_id), (tenant, status). No unique constraint on `(provider, provider_order_id)`.
- `core.PaymentGateway` (backend/core/models.py): `tenant`, `provider`, `key_id` (Razorpay key id / Cashfree app id / PayU merchant key — plaintext), `key_secret_encrypted` (Razorpay key secret / Cashfree secret / PayU salt), `webhook_secret_encrypted` (falls back to key secret when empty), `is_active`, `is_test_mode`. UniqueConstraint `(tenant, provider)`: a tenant may store all three providers but only one `is_active` (enforced in `PaymentGatewayView.put`). `is_configured` = key_id and secret present.
- Encryption: `core/encryption.py` Fernet; key from env `FIELD_ENCRYPTION_KEY`, else derived from `SECRET_KEY` (prod must set it; rotating SECRET_KEY otherwise silently turns every stored secret into '' on decrypt). Secrets are write-only in the API (`has_secret`/`has_webhook_secret` flags).
- Related tenant flags on `core.Tenant`: `request_enrollment_free`, `request_enrollment_paid`; `Tenant.enroll_mode_for(course)` returns `request` | `self` | `payment` (payment only when paid course AND `request_enrollment_paid=False` AND active configured gateway). `users/views.py` (~line 663) refuses plain enrol with `code: payment_required` in payment mode.

## API (backend/payments/urls.py)
Student (`IsAuthenticated`, tenant from `X-Tenant-ID`):
- `POST orders/` `CreateOrderView`: body `course`, optional `return_url`, `coupon_code`. Checks course in tenant, not hidden, not already approved-enrolled, `enroll_mode_for == 'payment'`, active gateway. Coupon validated server-side (`marketing.services.validate_coupon`). If final charge <= 0: creates a `coupon-<hex>` order and calls `mark_order_paid` immediately (`free: true`). Else `client.create_order(...)` and returns `{order, checkout}` (checkout payload differs per provider: Razorpay key_id/order_id/amount; Cashfree payment_session_id; PayU form `action_url`+`params` with SHA-512 request hash).
- `POST orders/<uuid>/verify/` `VerifyOrderView`: loads order by (id, tenant, student); verifies browser-return payload via `client.verify_return`; on ok `mark_order_paid`; returns `{status:'paid'|'pending', enrolled}` (pending -> 202).
Public/provider (no auth, csrf_exempt):
- `POST webhook/<provider>/` `WebhookView` (razorpay | cashfree | payu): parses body, finds order by (provider, provider_order_id), uses the ORDER's tenant's active gateway to verify the signature (400 on bad signature, 200 "Ignored" for unknown order/no gateway), then `mark_order_paid` if event is a paid event.
- `GET|POST payu/callback/` `PayUCallbackView`: PayU surl/furl browser POST; verifies reverse hash, grants enrolment, 302-redirects to `udf1` (the `return_url`) + `?payment=success|failed`.
Tenant admin (`IsAuthenticated + IsTenantAdmin`, backend/payments/admin_views.py): `admin/sales/orders/` (paginated, filters status/provider/course/date_from/date_to/search), `admin/sales/summary/`, `admin/sales/orders/<id>/refund/` (provider refund API then status=refunded + enrolment `rejected`/inactive; optional partial `amount`), `admin/sales/orders/<id>/revoke/` (revoke or `restore:true`).
Gateway management is in core: `/api/v1/tenant-admin/payment-gateway/` (`PaymentGatewayView`, GET/PUT/DELETE per provider). Public tenant endpoint `/api/v1/tenant/<id>/` exposes a sanitised `payment_gateway` blob (`core.views._public_payment_gateway`).

## Business logic
- `backend/payments/providers.py`: thin `requests` clients (no SDKs) with a uniform interface `create_order / verify_return / verify_webhook / parse_webhook / is_order_paid / refund`; `get_client(gateway)`.
  - Razorpay: base `https://api.razorpay.com/v1`; amount in paise; return signature = HMAC-SHA256(key_secret, `order_id|payment_id`); webhook = HMAC-SHA256(webhook_secret, raw body) in `X-Razorpay-Signature`; paid events `payment.captured`, `order.paid`.
  - Cashfree: sandbox `https://sandbox.cashfree.com/pg` vs prod `https://api.cashfree.com/pg` chosen by `is_test_mode`; API version `2023-08-01`; `verify_return` has no client signature -> calls `is_order_paid` (status API); webhook sig = base64(HMAC-SHA256(secret_key, ts+body)) from `x-webhook-signature`/`x-webhook-timestamp` (requires a stored webhook secret to be non-empty even though it signs with the secret key). Fallback placeholder customer email/phone used when missing.
  - PayU: test `test.payu.in` vs live `secure.payu.in`; `key_id`=Merchant Key, `key_secret`=Salt; request hash `key|txnid|amount|productinfo|firstname|email|udf1..udf5||||||salt`; response/webhook reverse hash with SHA-512 (`additionalCharges` prefix supported); `txnid` = order UUID without dashes (25 chars); `is_order_paid` via `postservice.php` `verify_payment`; refund via `cancel_refund_transaction`.
- `backend/payments/services.mark_order_paid`: atomic `select_for_update`; get-or-create `CourseEnrollment` (approved, active) and repair state; sets order paid + enrollment link; records coupon redemption via `marketing.services.record_redemption` (best-effort, swallowed errors). Idempotent for client-return + webhook racing.
- No Celery tasks, signals or management commands in this app. Confirmation emails/notifications are NOT sent from here.

## Integrations / settings / env vars
- Env: `FIELD_ENCRYPTION_KEY`, `SECRET_KEY`, `FRONTEND_URL` (PayU redirect fallback), `ALLOWED_HOSTS`. `SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO','https')` is set so `request.build_absolute_uri` yields https behind nginx (nginx passes `X-Forwarded-Proto` and `Host`).
- External: Razorpay / Cashfree / PayU REST APIs (credentials per tenant in DB). Frontend loads provider SDKs from their CDNs (`frontend/exam-frontend/src/services/paymentService.js`; PayU is a hosted-page form POST).
- **Callback/webhook URLs that must match the deployed API hostname** (configure in each tenant's provider dashboard):
  - `https://<api-host>/api/v1/payments/webhook/razorpay/` (+ webhook secret entered in the tenant gateway settings; events payment.captured / order.paid)
  - `https://<api-host>/api/v1/payments/webhook/cashfree/`
  - `https://<api-host>/api/v1/payments/webhook/payu/` (server-to-server)
  - PayU surl/furl = `https://<api-host>/api/v1/payments/payu/callback/` — built per request by `build_absolute_uri`, so it follows the Host header the request arrived with.

## Cross-app dependencies
Imports: `core.PaymentGateway/Tenant`, `exams.Course`, `users.CourseEnrollment/StudentProfile`, `marketing.Coupon` (FK + services). Called by: `marketing.models.CouponRedemption.order` FK, `core.views.TenantDetailView` (public gateway info), `users/views.py` (payment_required gate), `exams/serializers.py` (`enroll_mode`).

## Tests
**None** in backend/payments (no test file; no other test references `PaymentOrder`/`mark_order_paid`). Signature/verification code is untested.

## Gotchas / risks (verified by reading code)
- **Cross-order verification gap (high)**: `VerifyOrderView` loads order B but never checks that the verified provider order id equals `order.provider_order_id`. Razorpay `verify_return` takes `razorpay_order_id` from the client payload; PayU takes `txnid`; Cashfree takes `order_id` (all client-supplied, `setdefault` only fills them when absent). A student who has one genuinely paid cheap order (or a heavily coupon-discounted one) can replay its valid signature/payment against a different, unpaid, expensive order of theirs and get that enrolment. Fix: assert returned order id/txnid == `order.provider_order_id` (and amount == `order.amount`).
- **Open redirect on PayU callback**: failure paths (`txnid` missing, order unknown, gateway missing, hash invalid) redirect to the unverified `udf1` query/form value; also `return_url` in `CreateOrderView` is taken from the client without allow-list validation. Only the success path's `udf1` is hash-covered.
- `mark_order_paid` does not guard against `refunded`/`cancelled`/`failed` orders: a replayed/late "paid" webhook can flip a refunded order back to `paid` and re-grant enrolment. Webhooks carry no timestamp/replay protection and amounts are never compared to `order.amount`.
- Webhook/refund resolve the gateway via `tenant.active_payment_gateway` (webhook) vs `PaymentGateway.filter(tenant, provider=order.provider)` (refund); if the tenant switches active provider after an order is created, webhooks for old orders fail signature (400) and `verify` uses the NEW provider's client on an OLD order.
- Failed/cancelled orders never get transitioned: only `created` -> `paid`/`refunded`; abandoned checkouts stay `created` forever.
- Partial refund still revokes access entirely and sets status `refunded`.
- Free (100% coupon) path creates an order with provider_order_id `coupon-<hex>` under the active provider.
- `PaymentGateway` docstring says "one gateway per tenant" but the DB constraint is per (tenant, provider).
- Cashfree create_order falls back to placeholder customer email/phone; PayU falls back to `student@example.com` and a dummy phone when missing.
- Razorpay `verify_return` accepts `signature` from client but secret is the tenant key secret (fine); decrypt failure returns '' so a mis-keyed deployment makes every signature check fail silently rather than error.
- `SalesSummaryView` hard-codes `currency: 'INR'`.

## Key files
- backend/payments/views.py — create order, verify, webhook, PayU callback
- backend/payments/providers.py — Razorpay/Cashfree/PayU clients, hashing, refunds
- backend/payments/services.py — `mark_order_paid`, coupon redemption hook
- backend/payments/admin_views.py — sales dashboard, refund, revoke/restore
- backend/payments/models.py, serializers.py, admin_serializers.py, urls.py
- backend/core/models.py (`PaymentGateway`, `Tenant.enroll_mode_for`, `active_payment_gateway`), backend/core/admin_views.py (`PaymentGatewayView`), backend/core/admin_serializers.py (`PaymentGatewaySerializer`), backend/core/encryption.py
- backend/core/middleware.py — `TENANT_EXEMPT_PATHS`
- frontend/exam-frontend/src/services/paymentService.js — client checkout/verify
