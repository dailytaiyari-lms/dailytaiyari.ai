---
name: manage-tenants
description: How to create DailyTaiyari tenants, provision tenant admin accounts, whitelist a tenant's frontend origin, and move or copy a course (with its full content graph) between tenants. Use whenever onboarding a new academy/tenant or relocating/duplicating a course across tenants — as opposed to small field backfills (populate-data) or authoring new course material from scratch (create-course).
---

# Manage Tenants (DailyTaiyari)

Runbook for tenant-level operations on production:

1. **Create a tenant** (a new academy/institute).
2. **Provision a tenant admin** account.
3. **Whitelist a tenant's frontend origin** (CORS) — data only, no deploy.
4. **Move a course** from one tenant to another (reassign its whole graph).
5. **Copy a course** into another tenant (deep clone with new keys).

Like `populate-data`, every data change is a small, **idempotent** Python
script piped into the Django shell in the `web` container on the VM (production
Postgres is only reachable from the VM). Reuse the connection setup and the
`dt_ssh` helper from the **deploy-backend** skill (`$DT_SSH_KEY`, `$DT_VM_USER`,
`$DT_VM_HOST`, `$DT_APP_DIR`). **This guide contains no secrets** — never commit
keys, hosts, tenant IDs, or passwords.

> **When NOT to use this skill:**
> - Patching field values in bulk (pricing, descriptions, flags) → **populate-data**.
> - Authoring a full curriculum + notes + quizzes → **create-course**.
> - Changing a model field / adding a column → a **migration** (code → PR → **deploy-backend**).

---

## The one thing you must understand first

**Tenant scoping is enforced per-row, per-model — not by walking the course FK.**

`core.models.TimeStampedModel` (and `OrderedModel`, which subclasses it) defines
a `tenant` FK, so **almost every content row carries its own `tenant` column**:
`Course`, `Subject`, `Topic`, `Chapter`, `Question`, `QuestionOption`, `Quiz`,
`Assignment`, etc. The read APIs (`TenantAwareReadOnlyViewSet` in
`core/views.py`) filter each queryset with `.filter(tenant=request.tenant)`.

**Consequence:** moving *only* `Course.tenant` to a new tenant would surface the
course card but **none** of its subjects, topics, questions or quizzes — they'd
still be filtered out under the old tenant. A correct move/copy must touch the
**entire authored-content graph**, not just the `Course` row.

### The authored-content graph (proven, in dependency order)

For a course `c`, these are every tenant-bearing model and the ORM path from the
course. This exact list was used to move the Electric Vehicles course (481 rows):

| Model (`app.Model`)              | Filter from course `c`                         |
|----------------------------------|------------------------------------------------|
| `exams.Course`                   | `pk=c.pk`                                       |
| `exams.Subject`                  | `course=c`                                      |
| `exams.Topic`                    | `subject__course=c`                             |
| `exams.Chapter`                  | `subject__course=c`                             |
| `exams.ChapterTopic`             | `chapter__subject__course=c`                    |
| `exams.TopicCourseRelevance`     | `course=c`                                      |
| `quiz.Question`                  | `subject__course=c`                             |
| `quiz.QuestionOption`            | `question__subject__course=c`                   |
| `quiz.Quiz`                      | `course=c`                                      |
| `quiz.QuizQuestion`              | `quiz__course=c`                                |
| `quiz.MockTest`                  | `course=c`                                      |
| `quiz.MockTestQuestion`          | `mock_test__course=c`                           |
| `quiz.MockTestItem`              | `mock_test__course=c`                           |
| `coding.CodingProblem`           | `course=c`                                      |
| `coding.TestCase`                | `problem__course=c`                             |
| `assignments.Assignment`         | `course=c`                                      |

> **Student-generated data is deliberately excluded** from this graph:
> `CourseEnrollment` (users), `QuizAttempt`/`Answer` (quiz),
> `AssignmentSubmission`, `CodingSubmission`. These reference students who belong
> to the *source* tenant, so moving them creates cross-tenant references. Leave
> them in place unless the requester explicitly asks to move or delete them —
> and surface that decision, don't assume it.

---

## Golden rules

1. **Idempotent.** Use `get_or_create` for tenants/users; match courses by the
   stable `code`; only reassign rows whose `tenant` isn't already the target.
   Re-running must reach the same end state.
2. **Whole-graph, in a transaction.** Reassign/clone the full table above inside
   one `transaction.atomic()` so a failure rolls back cleanly.
3. **Codes are unique.** `Course.code` is **globally unique**; `Subject.code`,
   `Topic.code`, `Chapter.code` are unique within their parent scope. A **move**
   keeps codes as-is; a **copy** must assign a new course code or it will
   `IntegrityError`.
4. **Every row needs `tenant`.** When creating/cloning, always set `tenant=`.
5. **Print a summary** (counts per model) so a green run visibly proves what it did.
6. **Dry-run first.** Wrap writes in a `DRY_RUN` flag and roll back to preview.

---

## Recipe 1 — Create a tenant

`core.models.Tenant`: `name`, `subdomain` (unique, nullable), `tagline`,
`features` (JSON; missing keys default to enabled), `is_active`.

```python
# create_tenant.py — idempotent
from core.models import Tenant

NAME = "Tesla EV Academy"
SUBDOMAIN = "tesla-ev"   # unique; keep it slug-safe

tenant, created = Tenant.objects.get_or_create(
    name=NAME,
    defaults={"subdomain": SUBDOMAIN, "is_active": True},
)
print(f"Tenant {'CREATED' if created else 'exists'}: {tenant.name} id={tenant.id} subdomain={tenant.subdomain}")
```

Run it:
```bash
dt_ssh "cd $DT_APP_DIR/backend && sudo docker compose exec -T web python manage.py shell" \
  < create_tenant.py 2>&1 | grep -vE 'objects imported'
```

The frontend sends the tenant UUID as the `X-Tenant-ID` header on every API
call, so note the printed `id`.

---

## Recipe 2 — Provision a tenant admin

A tenant admin is simply `users.User` with `role='admin'` scoped to the tenant
(`core/permissions.py:IsTenantAdmin` only checks `user.role == 'admin'`). Users
are unique on `('email', 'tenant')`, so the same email can exist under multiple
tenants.

```python
# create_tenant_admin.py — idempotent
from django.utils import timezone
from core.models import Tenant
from users.models import User

EMAIL = "director@teslaevacademy.com"
PASSWORD = "<generate-a-strong-one>"   # never hard-code a real password into the repo
TENANT_NAME = "Tesla EV Academy"

tenant = Tenant.objects.filter(name=TENANT_NAME).first()
assert tenant, "tenant not found"

user, created = User.objects.get_or_create(
    email=EMAIL, tenant=tenant,
    defaults={"role": "admin", "first_name": "Tesla EV", "last_name": "Director"},
)
user.role = "admin"
user.is_active = True
user.is_email_verified = True          # skip the OTP gate for a provisioned admin
if not user.email_verified_at:
    user.email_verified_at = timezone.now()
user.set_password(PASSWORD)
user.save()
print(f"Admin {'CREATED' if created else 'UPDATED'}: {user.email} role={user.role} tenant={user.tenant.name}")
```

Generate the password locally (don't invent it in the script), e.g.
`python3 -c "import secrets,string; a=string.ascii_letters+string.digits; print('TeslaEV-'+''.join(secrets.choice(a) for _ in range(14)))"`,
pass it in via an env var if you prefer, and hand it to the requester
out-of-band with a "rotate on first login" note. Login requires the tenant's
`X-Tenant-ID`.

---

## Recipe 3 — Whitelist a tenant's frontend origin (CORS)

Per-tenant frontends hosted off the `dailytaiyari.in` / `.ai` domains (e.g. a
Vercel or Netlify deploy) are **not** covered by `CORS_ALLOWED_ORIGIN_REGEXES`.

This is now **self-serve data, not a code change**. `core/signals.py` hooks
corsheaders' `check_request_enabled` and allows any origin listed in some active
tenant's `Tenant.allowed_origins` JSON field. So there is **no settings edit, no
commit, and no deploy or restart** — just write the row:

```python
# add_tenant_origin.py — idempotent
from core.models import Tenant

ORIGIN = "https://<tenant-app>.vercel.app"   # exact, no trailing slash
tenant = Tenant.objects.filter(name="Tesla EV Academy").first()
assert tenant, "tenant not found"

origins = list(tenant.allowed_origins or [])
if ORIGIN not in origins:
    origins.append(ORIGIN)
    tenant.allowed_origins = origins
    tenant.save(update_fields=["allowed_origins"])   # post_save busts the cache
print(f"{tenant.name} origins -> {tenant.allowed_origins}")
```

Whitelist the **specific** origin, not a broad `*.vercel.app` pattern. Copy it
verbatim (watch for subdomain typos — matching is exact after stripping a
trailing slash). The tenant must be `is_active=True` or its origins are ignored.

> **Gotcha — the change is NOT instant in production.** The origin set is cached
> under `tenant_allowed_origins` for 300s, and the default cache is
> **`LocMemCache`, which is per-process**. Saving from `manage.py shell` (or from
> one gunicorn worker) only clears *that* process's copy, so other workers keep
> serving the stale set for up to 5 minutes. A preflight that fails immediately
> after the write is expected — retry for ~5 min before concluding it's broken.
> Confirm the data side independently with
> `python -c` / shell: `from core import signals; signals._all_allowed_origins()`.

Verify the preflight:
```bash
curl -s -i -X OPTIONS "$DT_API_URL/api/v1/courses/" \
  -H "Origin: https://<tenant-app>.vercel.app" \
  -H "Access-Control-Request-Method: GET" \
  -H "Access-Control-Request-Headers: x-tenant-id" 2>&1 \
  | grep -iE "HTTP/|access-control-allow-origin|access-control-allow-cred"
```
Expect `200` and `access-control-allow-origin` echoing your origin.

---

## Recipe 4 — Move a course between tenants

Reassign `tenant` across the whole graph. This is the exact, proven script:

```python
# move_course.py — idempotent; moves authored content only (not student data)
import os
from django.db import transaction
from core.models import Tenant
from exams.models import Course, Subject, Topic, Chapter, ChapterTopic, TopicCourseRelevance
from quiz.models import Quiz, QuizQuestion, Question, QuestionOption, MockTest, MockTestQuestion, MockTestItem
from coding.models import CodingProblem, TestCase
from assignments.models import Assignment

DRY_RUN = os.environ.get("DRY_RUN") == "1"
COURSE_CODE = "electric-vehicles"
DEST_TENANT_NAME = "Tesla EV Academy"

course = Course.objects.filter(code=COURSE_CODE).first()
assert course, f"course {COURSE_CODE!r} not found"
dest = Tenant.objects.filter(name=DEST_TENANT_NAME).first()
assert dest, "destination tenant not found"
src = course.tenant

graph = [
    ("course",              Course.objects.filter(pk=course.pk)),
    ("subjects",            Subject.objects.filter(course=course)),
    ("topics",              Topic.objects.filter(subject__course=course)),
    ("chapters",            Chapter.objects.filter(subject__course=course)),
    ("chapter_topics",      ChapterTopic.objects.filter(chapter__subject__course=course)),
    ("topic_course_relev",  TopicCourseRelevance.objects.filter(course=course)),
    ("questions",           Question.objects.filter(subject__course=course)),
    ("question_options",    QuestionOption.objects.filter(question__subject__course=course)),
    ("quizzes",             Quiz.objects.filter(course=course)),
    ("quiz_questions",      QuizQuestion.objects.filter(quiz__course=course)),
    ("mock_tests",          MockTest.objects.filter(course=course)),
    ("mock_test_questions", MockTestQuestion.objects.filter(mock_test__course=course)),
    ("mock_test_items",     MockTestItem.objects.filter(mock_test__course=course)),
    ("coding_problems",     CodingProblem.objects.filter(course=course)),
    ("test_cases",          TestCase.objects.filter(problem__course=course)),
    ("assignments",         Assignment.objects.filter(course=course)),
]

summary, total = [], 0
with transaction.atomic():
    for label, qs in graph:
        to_move = qs.exclude(tenant=dest)
        n = to_move.count()
        if n and not DRY_RUN:
            to_move.update(tenant=dest)
        summary.append((label, n)); total += n
    if DRY_RUN:
        transaction.set_rollback(True)

print(("DRY-RUN " if DRY_RUN else "") + f"Move [{course.code}] {src.name} -> {dest.name}")
for label, n in summary:
    print(f"  {label:22s} moved={n}")
print(f"Total rows reassigned: {total}")
```

Dry-run, read the plan, then run for real:
```bash
# preview (rolls back)
dt_ssh "cd $DT_APP_DIR/backend && sudo docker compose exec -T -e DRY_RUN=1 web python manage.py shell" \
  < move_course.py 2>&1 | grep -vE 'objects imported'
# commit
dt_ssh "cd $DT_APP_DIR/backend && sudo docker compose exec -T web python manage.py shell" \
  < move_course.py 2>&1 | grep -vE 'objects imported'
```

> **Gotcha:** a `Tenant.objects.get_or_create(...)` placed *before* the atomic
> block is **not** rolled back by the dry-run — so a dry-run can leave the new
> tenant created. That's harmless (idempotent), but don't be surprised when the
> real run reports the tenant "exists".

---

## Recipe 5 — Copy a course into another tenant (deep clone)

A copy duplicates the whole graph with **new primary keys** under the
destination tenant, leaving the original intact. Use it to seed a new tenant
from an existing course.

**Extra gotchas beyond a move:**
- **Give the new course a new, unique `code`** (`Course.code` is globally
  unique). Subject/Topic/Chapter codes are unique only within their parent, so
  they can stay the same in the copied subtree.
- **Clone in dependency order and remap FKs** via old-id → new-object maps.
- **Reset each row for insert:** set `pk=None`, `id=None` (a fresh `uuid4` is
  generated on save), `tenant=dest`, and repoint every FK to its cloned parent.
- **Skip student data** (attempts, submissions, enrollments) — a fresh tenant
  starts empty.

```python
# copy_course.py — clones a course graph into another tenant. DRY_RUN supported.
import os
from django.db import transaction
from core.models import Tenant
from exams.models import Course, Subject, Topic, Chapter, ChapterTopic
from quiz.models import Quiz, QuizQuestion, Question, QuestionOption
from assignments.models import Assignment

DRY_RUN = os.environ.get("DRY_RUN") == "1"
SRC_CODE   = "electric-vehicles"
DEST_TENANT = "Tesla EV Academy"
NEW_CODE   = "electric-vehicles-tesla"   # MUST be globally unique

src = Course.objects.get(code=SRC_CODE)
dest = Tenant.objects.get(name=DEST_TENANT)
assert not Course.objects.filter(code=NEW_CODE).exists(), "NEW_CODE already used"

def clone(obj, **overrides):
    obj.pk = None; obj.id = None; obj._state.adding = True
    obj.tenant = dest
    for k, v in overrides.items():
        setattr(obj, k, v)
    if not DRY_RUN:
        obj.save()
    return obj

subj_map, topic_map, chap_map, q_map, quiz_map = {}, {}, {}, {}, {}
with transaction.atomic():
    new_course = clone(Course.objects.get(pk=src.pk), code=NEW_CODE)

    for s in Subject.objects.filter(course=src):
        subj_map[s.pk] = clone(Subject.objects.get(pk=s.pk), course=new_course)
    # self-FK: order by parent so parents are cloned before children
    for t in Topic.objects.filter(subject__course=src).order_by("parent_topic_id"):
        src_t = Topic.objects.get(pk=t.pk)
        topic_map[t.pk] = clone(src_t, subject=subj_map[src_t.subject_id],
                                parent_topic=topic_map.get(src_t.parent_topic_id))
    for ch in Chapter.objects.filter(subject__course=src):
        src_ch = Chapter.objects.get(pk=ch.pk)
        chap_map[ch.pk] = clone(src_ch, subject=subj_map[src_ch.subject_id])
    for ct in ChapterTopic.objects.filter(chapter__subject__course=src):
        src_ct = ChapterTopic.objects.get(pk=ct.pk)
        clone(src_ct, chapter=chap_map[src_ct.chapter_id], topic=topic_map[src_ct.topic_id])
    for qn in Question.objects.filter(subject__course=src):
        src_q = Question.objects.get(pk=qn.pk)
        q_map[qn.pk] = clone(src_q, subject=subj_map[src_q.subject_id],
                             topic=topic_map[src_q.topic_id])
    for opt in QuestionOption.objects.filter(question__subject__course=src):
        src_o = QuestionOption.objects.get(pk=opt.pk)
        clone(src_o, question=q_map[src_o.question_id])
    for qz in Quiz.objects.filter(course=src):
        src_qz = Quiz.objects.get(pk=qz.pk)
        quiz_map[qz.pk] = clone(src_qz, course=new_course,
                                subject=subj_map.get(src_qz.subject_id),
                                topic=topic_map.get(src_qz.topic_id))
    for qq in QuizQuestion.objects.filter(quiz__course=src):
        src_qq = QuizQuestion.objects.get(pk=qq.pk)
        clone(src_qq, quiz=quiz_map[src_qq.quiz_id], question=q_map[src_qq.question_id])
    for a in Assignment.objects.filter(course=src):
        src_a = Assignment.objects.get(pk=a.pk)
        clone(src_a, course=new_course,
              subject=subj_map.get(src_a.subject_id), topic=topic_map.get(src_a.topic_id))
    if DRY_RUN:
        transaction.set_rollback(True)

print(("DRY-RUN " if DRY_RUN else "") + f"Copied {SRC_CODE} -> {NEW_CODE} into {dest.name}")
```

This mirrors the move graph; extend it for the `MockTest`/`CodingProblem`
subtrees if the source course has them (they were empty for the EV course).
**Always dry-run first** and eyeball the counts against the source before
committing.

---

## Verify (any recipe)

```bash
# Course now served under the destination tenant, with its content:
curl -s -H "X-Tenant-ID: $DEST_TENANT_ID" "$DT_API_URL/api/v1/courses/" | head -c 400
# And (for a move) gone from the source tenant's list.
curl -s -H "X-Tenant-ID: $SRC_TENANT_ID"  "$DT_API_URL/api/v1/courses/" | head -c 400
```

A quick shell re-count is the strongest proof — for the target tenant, confirm
`subjects/questions/quizzes on new tenant == total` for the course.

## Guardrails

- **Never `.delete()` broadly.** Moving/copying never deletes; if asked to
  "replace", prefer deactivating (`is_active=False` / `status='inactive'`) over
  destroying rows with student history.
- **One course, one tenant at a time.** Filter by `code` / tenant so you never
  touch a neighbouring academy's data.
- **No local DB.** Validate with `python3 -m py_compile`; all execution is on the
  VM via `dt_ssh`.
- **Keep the scripts** under the session `files/` folder so the next tenant op
  starts from a proven template.
- Never commit the SSH key, host, tenant IDs, or admin passwords.
