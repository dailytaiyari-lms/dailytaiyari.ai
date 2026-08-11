# Live Classes & Zoom Integration

DailyTaiyari live classes are authored under a **Topic** (alongside content,
quizzes, assignments and coding problems) and support two providers:

| Provider | How it works | Attendance |
|---|---|---|
| `gmeet` | Instructor pastes a Google Meet link. | Portal join clicks only |
| `zoom` | We create the meeting on the academy's own Zoom account via API. | Full: per-student durations, present/partial/absent, CSV export |

In-house live streaming (`in_house`) is a placeholder and is rejected by the
authoring serializer until it ships.

---

## 1. Connecting Zoom (per tenant)

Each academy connects **its own** Zoom account, so meetings are hosted by them,
recordings stay in their cloud, and reports come from their plan. Credentials are
stored on `core.ZoomIntegration` (one per tenant) and encrypted at rest with
`core.encryption` — the API never returns them, only `has_*` booleans.

**Admin → Settings → Integrations → Zoom**

1. In [marketplace.zoom.us](https://marketplace.zoom.us) → **Develop → Build App →
   Server-to-Server OAuth**, create an app.
2. Copy **Account ID**, **Client ID** and **Client Secret** into the form.
3. Add these scopes to the Zoom app:
   - `meeting:write:admin`, `meeting:read:admin`
   - `report:read:admin` (participant reports)
   - `user:read:admin` (host lookup / "Test connection")
4. Under **Feature → Event Subscriptions**, add the webhook URL shown in the form
   (`https://<your-api>/api/v1/live-classes/zoom/webhook/`) and subscribe to:
   - `meeting.started`, `meeting.ended`
   - `meeting.participant_joined`, `meeting.participant_left`
   Paste the app's **Secret Token** into "Webhook Secret Token".
5. Hit **Test connection**, then turn on **Use Zoom for live classes**.

### Plan requirements

| Feature | Needs |
|---|---|
| Creating meetings | Any plan |
| Personal join links (registration) | Licensed (paid) plan |
| Participant reports (`/report`) | Pro or higher |

On a Basic account meetings still work; attendance degrades to webhook-derived
durations plus portal join clicks. The settings screen warns about this after a
successful "Test connection" (Zoom user `type == 1` means Basic).

### Settings

| Field | Meaning |
|---|---|
| `host_email` | Zoom user meetings are created under. Blank = account owner (`me`). |
| `use_registration` | Register each enrolled student so they get a personal join link. |
| `pull_reports` | Reconcile against Zoom's participant report after a class ends. |
| `attendance_threshold_percent` | Share of the class needed to count as *present* (default 60). |

---

## 2. Scheduling a Zoom class

**Course Manager → Topic → Live tab → Add live class → Platform: Zoom**

The admin fills in title, start time and duration only. On save the backend calls
Zoom and stores `zoom_meeting_id`, the student `meeting_url`, the host-only
`zoom_start_url` and the passcode.

A Zoom failure **never fails the save** — the class is stored, and the response
carries `zoom_error` which the UI surfaces. The admin can then either retry
("Create on Zoom", `POST .../zoom-sync/`) or paste a Zoom link manually.

Editing a class pushes topic/time/duration back to Zoom; deleting it removes the
meeting from Zoom first.

The **Start** button fetches `GET .../host-link/` on demand — the host start URL
is deliberately kept out of list payloads because opening it starts the meeting.

---

## 3. How attendance is captured

Three signals are reconciled onto one `LiveClassAttendance` row per person:

| Source | When | What it gives |
|---|---|---|
| `portal` | Student clicks Join in DailyTaiyari | Proof of intent; the only signal for Google Meet |
| `webhook` | `participant_joined` / `participant_left` | Live "in call now" + running duration |
| `report` | After the meeting ends | Authoritative durations; overwrites the computed values |

### Matching a Zoom participant to a student

In descending order of confidence:

1. **Zoom registrant id** — set when the student got a personal join link. Exact.
2. **Registrant email**, then the student's account email (case-insensitive).
3. **Exact display name**, and only when it is unambiguous among enrolled students.

Unmatched participants are kept as **guests** (`student = NULL`) rather than
dropped, so an admin can always see who was in the room.

This is why registration matters: without it, a student who renames themselves in
Zoom cannot be matched reliably.

### Student join flow

Students call `POST /api/v1/live-classes/classes/<id>/join/` instead of opening
the link directly. The backend lazily registers them with Zoom, returns their
personal `join_url`, and records the click. For registered meetings the shared
`meeting_url` is **blanked out** of the student list payload so nobody can join
unregistered and break matching.

### Status derivation

```
duration == 0                    → absent
duration >= threshold% of class  → present
otherwise                        → partial
```

An admin can override any row (present/absent + note). Overridden rows are
pinned: later syncs leave their status alone (`is_manual_override`).

Once a class has ended, `ensure_absent_rows()` materialises an absent row for
every enrolled student who never appeared, so the register is the full roster.

---

## 4. Reconciliation & reliability

Zoom does not publish its participant report the instant a meeting ends, so:

1. The `meeting.ended` webhook attempts a sync immediately (often too early).
2. Opening the admin attendance drawer **lazily re-syncs** if the last sync
   predates the meeting end. This is what makes it work with no worker running.
3. `POST .../attendance/sync/` is the manual "Sync" button.
4. Optional backstop for missed webhooks:

```bash
python manage.py sync_live_attendance --hours 24
```

or the Celery tasks `liveclass.sync_attendance` / `liveclass.sync_recent_attendance`.

The report source falls back through `/report/meetings/…` →
`/metrics/meetings/…` → `/past_meetings/…`, so a lower plan degrades instead of
erroring. When none are available the failure is stored on
`LiveClass.attendance_sync_error` and shown in the drawer.

---

## 5. Webhook security

`/api/v1/live-classes/zoom/webhook/` is in `TENANT_EXEMPT_PATHS` (Zoom cannot
send `X-Tenant-ID`) and takes no auth, so it is protected by signature instead:

- Zoom signs `v0:<timestamp>:<raw body>` with the app's Secret Token.
- We resolve the tenant from `payload.object.id` (the meeting id), then verify
  `x-zm-signature` against **that tenant's** token with `hmac.compare_digest`.
- Unknown meetings are acked with `200` so Zoom stops retrying.
- Handler exceptions are logged, never raised — a 500 would make Zoom retry a
  poisoned event for hours.
- `endpoint.url_validation` is answered before any signature check (that is the
  challenge that establishes the endpoint).

---

## 6. API reference

### Student

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/live-classes/classes/?topic=<id>` | Published classes for an enrolled topic |
| `POST` | `/api/v1/live-classes/classes/<id>/join/` | Get the personal join link + record the join |

### Admin / instructor

| Method | Path | Purpose |
|---|---|---|
| `GET/POST` | `/api/v1/live-classes/admin/classes/` | List / create (creates the Zoom meeting) |
| `PATCH/DELETE` | `/api/v1/live-classes/admin/classes/<id>/` | Update / delete (syncs to Zoom) |
| `POST` | `…/<id>/zoom-sync/` | Retry creating the Zoom meeting |
| `GET` | `…/<id>/host-link/` | Host start URL |
| `GET` | `…/<id>/attendance/` | Register + summary (lazily syncs) |
| `POST` | `…/<id>/attendance/sync/` | Force a Zoom report pull |
| `PATCH` | `…/<id>/attendance/<row_id>/` | Override a row |
| `GET` | `…/<id>/attendance/export/` | CSV download |

### Tenant admin

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/tenant-admin/zoom/` | Connection + webhook URL |
| `PUT` | `/api/v1/tenant-admin/zoom/` | Save credentials/settings (blank secret = keep) |
| `POST` | `/api/v1/tenant-admin/zoom/` | Test connection |
| `DELETE` | `/api/v1/tenant-admin/zoom/` | Disconnect |

---

## 7. Code map

| File | Responsibility |
|---|---|
| `backend/core/models.py` → `ZoomIntegration` | Per-tenant encrypted credentials |
| `backend/liveclass/zoom.py` | Zoom REST client, token cache, signature helpers |
| `backend/liveclass/services.py` | Meeting lifecycle, registration, matching, reconciliation |
| `backend/liveclass/webhooks.py` | Zoom event receiver |
| `backend/liveclass/admin_views.py` | Authoring + attendance API + CSV |
| `backend/liveclass/tests.py` | Signature, matching and duration tests |
| `frontend/…/pages/CourseManager.jsx` | Scheduling modal + attendance drawer |
| `frontend/…/pages/AdminDashboard.jsx` → `IntegrationSettings` | Zoom settings screen |
| `frontend/…/pages/StudyTopicContent.jsx` | Student join flow |
