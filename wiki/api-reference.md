# API Reference

## Authentication

All API requests (except exempt paths) require the `X-Tenant-ID` header.

```
X-Tenant-ID: 405223b1-7738-4b01-b405-9cbfecdd63a1
```

Authenticated endpoints also require:
```
Authorization: Bearer <access_token>
```

---

## Tenant Endpoints

### GET `/api/v1/tenant/<uuid:id>/`

Fetch tenant branding details. **No authentication required.**

**Response (200):**
```json
{
  "id": "405223b1-7738-4b01-b405-9cbfecdd63a1",
  "name": "Test Academy",
  "subdomain": "test",
  "logo": "http://localhost:8000/media/tenant_logos/logo.png"
}
```

**Response (404):**
```json
{
  "error": "Tenant not found"
}
```

---

## Auth Endpoints

### POST `/api/v1/auth/register/`

Register a new user. The user is automatically assigned to the tenant from `X-Tenant-ID`.

**Headers:**
```
X-Tenant-ID: <uuid>
```

**Request Body:**
```json
{
  "email": "student@example.com",
  "password": "securepass123",
  "password_confirm": "securepass123",
  "first_name": "John",
  "last_name": "Doe",
  "phone": "+919876543210"
}
```

**Response (201):**
```json
{
  "message": "Registration successful",
  "user": {
    "id": "...",
    "email": "student@example.com",
    "first_name": "John",
    "last_name": "Doe"
  }
}
```

**Response (400) — No tenant:**
```json
{
  "error": "A valid Tenant is required to register."
}
```

### POST `/api/v1/auth/login/`

Obtain JWT tokens.

**Request Body:**
```json
{
  "email": "student@example.com",
  "password": "securepass123"
}
```

**Response (200):**
```json
{
  "access": "<jwt_access_token>",
  "refresh": "<jwt_refresh_token>",
  "user": { ... }
}
```

### POST `/api/v1/auth/refresh/`

Refresh an expired access token.

**Request Body:**
```json
{
  "refresh": "<jwt_refresh_token>"
}
```

---

## Exam Endpoints

All exam endpoints are **read-only** and tenant-filtered.

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/v1/exams/exams/` | List exams |
| GET | `/api/v1/exams/exams/<id>/` | Get exam detail |
| GET | `/api/v1/exams/subjects/` | List subjects |
| GET | `/api/v1/exams/topics/` | List topics |
| GET | `/api/v1/exams/chapters/` | List chapters |

---

## Quiz Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/v1/quiz/questions/` | List published questions |
| GET | `/api/v1/quiz/questions/by_topic/` | Get questions by topic |
| GET | `/api/v1/quiz/quizzes/` | List published quizzes |
| GET | `/api/v1/quiz/quizzes/<id>/` | Get quiz detail with questions |
| POST | `/api/v1/quiz/quizzes/<id>/start/` | Start a quiz attempt |
| POST | `/api/v1/quiz/quizzes/<id>/submit/` | Submit quiz answers |
| GET | `/api/v1/quiz/mock-tests/` | List mock tests |
| GET | `/api/v1/quiz/mock-tests/<id>/` | Get mock test detail |
| GET | `/api/v1/quiz/quiz-attempts/` | List user's quiz attempts |
| GET | `/api/v1/quiz/quiz-attempts/<id>/review/` | Review completed attempt |
| POST | `/api/v1/quiz/question-reports/` | Report a question issue |

---

## Analytics Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/v1/analytics/dashboard/` | Get dashboard stats |
| GET | `/api/v1/analytics/topic-mastery/` | Get topic mastery data |
| GET | `/api/v1/analytics/topic-mastery/weak_topics/` | Get weak topics |
| GET | `/api/v1/analytics/subject-performance/` | Get subject performance |
| GET | `/api/v1/analytics/daily-activity/today/` | Get today's activity |
| GET | `/api/v1/analytics/daily-activity/weekly/` | Get last 7 days |
| GET | `/api/v1/analytics/streaks/current/` | Get current streak |
| GET | `/api/v1/analytics/weekly-reports/latest/` | Get latest weekly report |
| GET | `/api/v1/analytics/study-timer/` | Get study timer state |
| POST | `/api/v1/analytics/study-timer/` | Start study session |
| PUT | `/api/v1/analytics/study-timer/` | Update with heartbeat |

---

## Gamification Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/v1/gamification/badges/` | List badges |
| GET | `/api/v1/gamification/student-badges/` | List earned badges |
| GET | `/api/v1/gamification/xp-transactions/` | XP history |
| GET | `/api/v1/gamification/xp-transactions/summary/` | XP summary |
| GET | `/api/v1/gamification/leaderboard/` | Get leaderboard |
| GET | `/api/v1/gamification/challenges/active/` | Active challenges |

---

## Community Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/v1/community/posts/` | List posts |
| POST | `/api/v1/community/posts/` | Create post |
| POST | `/api/v1/community/posts/<id>/like/` | Toggle like |
| POST | `/api/v1/community/posts/<id>/vote_poll/` | Vote on poll |
| GET | `/api/v1/community/comments/?post=<id>` | List comments |
| POST | `/api/v1/community/comments/` | Create comment |

---

## Chatbot Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/v1/chatbot/sessions/` | List chat sessions |
| POST | `/api/v1/chatbot/sessions/` | Create new session |
| POST | `/api/v1/chatbot/sessions/<id>/send_message/` | Send message |
| POST | `/api/v1/chatbot/sessions/<id>/send_message_stream/` | Send with streaming |
| GET | `/api/v1/chatbot/faqs/` | List FAQs |
| POST | `/api/v1/chatbot/ai-quizzes/submit/` | Submit AI quiz |

---

## Lab (Notebook) Endpoints

Gradeable Python notebooks. Surfaced to users as **"Labs"**; the API path stays
`notebooks`. Full details in [notebooks-labs.md](./notebooks-labs.md).

### Student

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/v1/notebooks/` | Labs across the student's enrolled courses |
| GET | `/api/v1/notebooks/<id>/` | Lab detail + attempt state + best result |
| GET/PUT/DELETE | `/api/v1/notebooks/<id>/draft/` | Autosaved work-in-progress |
| POST | `/api/v1/notebooks/<id>/submit/` | Submit for grading |
| GET | `/api/v1/notebooks/<id>/submissions/<sub_id>/` | Poll submission status |
| GET | `/api/v1/notebooks/<id>/my-submissions/` | Attempt history |

Submission is **asynchronous by default**: `submit/` returns a submission with
`status: "queued"` and the client polls the status endpoint until it reads
`graded` (or `failed`).

```json
{
  "id": "…",
  "status": "graded",
  "attempt_number": 2,
  "passed_count": 4,
  "total_count": 5,
  "passed_points": 8,
  "total_points": 10,
  "marks": "16.00",
  "is_late": false,
  "results": [
    { "name": "returns the sum", "passed": true, "points": 2 },
    { "name": "handles negatives", "passed": false, "points": 2,
      "failure_hint": "Check the sign handling" }
  ]
}
```

Lab detail includes the attempt policy so the client never reimplements it:
`can_submit`, `allow_resubmission`, `max_attempts`, `attempts_used`,
`attempts_remaining`, `is_past_due`, `hidden_test_count`, `my_best`,
`is_complete`.

### Author / admin

| Method | Endpoint | Description |
|---|---|---|
| — | `/api/v1/notebooks/admin/notebooks/` | Lab CRUD (incl. tests) |
| — | `/api/v1/notebooks/admin/datasets/` | Dataset management |
| — | `/api/v1/notebooks/admin/submissions/` | Review, override marks, feedback |
| GET | `/api/v1/notebooks/meta/` | Available packages, limits, defaults |

### AI lab generation

Always a background job — poll it, then `apply/` to write a real lab.

| Method | Endpoint | Description |
|---|---|---|
| GET/POST | `/api/v1/notebooks/admin/generate/jobs/` | List / start a job |
| GET | `/api/v1/notebooks/admin/generate/jobs/<id>/` | Poll status + draft |
| POST | `/api/v1/notebooks/admin/generate/jobs/<id>/refine/` | Modify the draft |
| POST | `/api/v1/notebooks/admin/generate/jobs/<id>/regenerate/` | Retry |
| POST | `/api/v1/notebooks/admin/generate/jobs/<id>/apply/` | Persist as a lab |
| POST | `/api/v1/notebooks/admin/generate/jobs/<id>/discard/` | Discard the draft |

---

## Error Responses

### 403 — Tenant Required
```json
{
  "error": "X-Tenant-ID header is required."
}
```

### 403 — Invalid Tenant
```json
{
  "error": "Tenant not found or inactive."
}
```

### 401 — Unauthorized
```json
{
  "detail": "Authentication credentials were not provided."
}
```
