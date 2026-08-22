# Birthday Greetings

Automated, tenant-branded birthday wishes for students — an in-app celebration
moment plus an optional branded email — and a daily digest for admins. Because a
birthday reaches *everyone* on the roll, including people who drifted away, it
doubles as a warm, non-salesy re-engagement channel for past students.

---

## What a student sees

On the morning of their birthday (or the first time they open the app that day)
the student gets:

1. A **full-screen celebration** — confetti, floating balloons and a greeting
   card headed with the institution's logo and name
   (`components/common/BirthdayCelebration.jsx`). It plays **once**: dismissing
   marks the underlying notification read.
2. A **notification in the bell**, which stays there for the rest of the day.
3. Optionally, a **branded HTML email** using the tenant's logo, name and theme
   accent colour.

Past students — anyone with no active, approved enrolment — get a warmer variant
that invites them back, and its call-to-action points at `/courses` instead of
`/dashboard`.

## What an admin sees

One **daily digest** notification listing everyone celebrating today
(`🎂 3 birthdays today — Riya, Arjun and 1 more`), deep-linking to the student
list so they can follow up personally. Optionally the same digest by email, sent
to the tenant's notification address.

---

## Turning it on and off

**Admin dashboard → Settings → Advanced.** Every switch is per-tenant and stored
on `Tenant.advanced_settings` (a JSON map; missing keys fall back to the default
declared in `Tenant.ADVANCED_SETTING_CHOICES`).

| Key | Default | Effect |
|---|---|---|
| `birthday_greetings` | on | Master switch. Off = nothing is sent at all. |
| `birthday_email_student` | on | Also email the student their wish. |
| `birthday_include_past_students` | on | Include students with no active enrolment. |
| `birthday_notify_admins` | on | In-app daily digest for admins. |
| `birthday_email_admins` | off | Email the digest to `Tenant.notification_email`. |

The sub-switches are inert while the master switch is off (the UI greys them
out). Adding a new advanced switch is a one-line addition to
`ADVANCED_SETTING_CHOICES` — the settings UI is driven by the API response, so no
frontend change is needed.

## Rewording the emails

**Settings → Email & Notifications** exposes three editable templates alongside
the enrolment ones:

| Type | Placeholders |
|---|---|
| `birthday_student` | `student_name`, `first_name`, `tenant_name`, `age` |
| `birthday_past_student` | `student_name`, `first_name`, `tenant_name`, `age` |
| `birthday_digest` | `tenant_name`, `count`, `names`, `date` |

Overrides live in `TenantEmailTemplate`; any blank part falls back to the
packaged default in `notifications/email_templates.py`. The rendered body is
wrapped by `emails.celebration_body_html()` — a table-based, Outlook-safe
greeting card — and then by the standard branded `emails/base_email.html`, which
supplies the logo header and footer.

---

## Where the birthday comes from

`StudentProfile.date_of_birth` — already editable by the student
(**Profile → Personal**) and by an admin (**Students → Edit**). Students with no
date of birth are simply never greeted, so the feature needs no backfill.

Only accounts with `role='student'`, `is_active=True` and `is_suspended=False`
are considered. Faculty and admins are not greeted.

A **29 February** birthday is celebrated on 28 February in non-leap years so
those students aren't skipped three years out of four.

---

## How delivery is scheduled

There are two triggers, and running both is safe:

1. **Management command** (preferred — greetings land early in the morning):

   ```bash
   python manage.py send_birthday_greetings
   ```

   Suggested cron entry on the VM:

   ```
   30 3 * * * cd /srv/dailytaiyari/backend && docker compose exec -T web \
       python manage.py send_birthday_greetings >> /var/log/birthday.log 2>&1
   ```

   Useful flags: `--dry-run` (report only), `--date YYYY-MM-DD`,
   `--tenant <id|subdomain|name>`, `--force` (ignore the tenant's
   `birthday_greetings` switch — suspension and billing freezes are still
   honoured).

2. **Request-time self-healing trigger.** The endpoints the app already polls
   (`/notifications/unread-count/` and `/notifications/birthday/`) call
   `birthdays.maybe_run_for_tenant()`, which fires the sweep the first time a
   tenant is seen on a new day. This means the feature works with **no scheduler
   configured at all** — cron only makes the greeting earlier. Cost is bounded
   by a per-process memo: at most one extra DB round-trip per worker, per
   tenant, per day. The fan-out never runs on the request thread: with
   `NOTIFICATIONS_ASYNC=True` it goes to Celery
   (`notifications.run_tenant_birthday_sweep`), otherwise to a short-lived
   background thread that closes its DB connections when done.

A `notifications.send_birthday_greetings` Celery task also exists for
deployments that add a beat scheduler.

### Idempotency

Two guards, so the sweep can run as often as you like:

* `BirthdayGreetingLog` — unique on `(user, year)`. Created in the same
  transaction as the in-app notification, so it doubles as the lock: a duplicate
  key means someone else already wished this person this year, and a failure
  can never mark a student greeted without a greeting. One failing recipient is
  logged and skipped without aborting the rest of the batch.
* `BirthdayDispatchRun` — unique on `(tenant, run_date)`. Claimed atomically so
  concurrent web workers can't both start a sweep, and only marked
  `completed_at` once the sweep finishes. A claim left in flight (crashed worker,
  lost Celery task) is retried by the next trigger after `STALE_CLAIM_AFTER`
  (30 minutes), so a partial failure never silently costs a student their
  greeting for the year.

---

## Code map

| Concern | Location |
|---|---|
| Sweep, audience resolution, delivery | `backend/notifications/birthdays.py` |
| Tracking tables | `BirthdayGreetingLog`, `BirthdayDispatchRun` in `backend/notifications/models.py` |
| Notification types | `Notification.TYPE_BIRTHDAY`, `TYPE_BIRTHDAY_DIGEST` |
| Email defaults & placeholders | `backend/notifications/email_templates.py` |
| Greeting-card email wrapper | `emails.celebration_body_html()` |
| API | `GET /api/v1/notifications/birthday/` |
| Cron entry point | `backend/notifications/management/commands/send_birthday_greetings.py` |
| Tenant switches | `Tenant.ADVANCED_SETTING_CHOICES` / `Tenant.advanced_settings` |
| Celebration UI | `frontend/exam-frontend/src/components/common/BirthdayCelebration.jsx` |
| Advanced settings UI | `frontend/exam-frontend/src/components/admin/AdvancedSettings.jsx` |
