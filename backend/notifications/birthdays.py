"""Automated birthday greetings.

A tenant that has birthday greetings enabled (Settings → Advanced) wishes every
student celebrating a birthday today with:

* a celebratory **in-app notification** the frontend turns into a full-screen
  confetti moment, and
* an optional **branded email** carrying the tenant's logo and name.

Former students — anyone with no active, approved enrolment — get a warmer,
re-engagement flavoured variant of the same wish, which is a natural, non-salesy
reason to get back in touch. Admins optionally receive a single daily digest
(in-app and/or email) of everyone celebrating, so they can follow up personally.

Delivery is driven by :func:`run_sweep`, which is safe to call as often as you
like:

* ``python manage.py send_birthday_greetings`` (cron / manual), and
* :func:`maybe_run_for_tenant`, a request-time trigger that fires the sweep the
  first time a tenant is seen on a new day, so greetings go out even with no
  scheduler configured.

Idempotency is enforced at two levels: ``BirthdayDispatchRun`` claims the
tenant/date pair atomically, and ``BirthdayGreetingLog`` guarantees a user is
never wished twice in the same calendar year.
"""
import logging
import threading
from datetime import date, timedelta

from django.conf import settings as django_settings
from django.db import IntegrityError, transaction
from django.db import connections as db_connections
from django.db.models import F, Q
from django.utils import timezone

from . import emails
from .email_templates import (
    TYPE_BIRTHDAY_DIGEST,
    TYPE_BIRTHDAY_PAST_STUDENT,
    TYPE_BIRTHDAY_STUDENT,
    render_email,
)
from .models import BirthdayDispatchRun, BirthdayGreetingLog, Notification

logger = logging.getLogger(__name__)

#: Advanced-settings keys that drive this feature.
SETTING_ENABLED = 'birthday_greetings'
SETTING_EMAIL_STUDENT = 'birthday_email_student'
SETTING_INCLUDE_PAST = 'birthday_include_past_students'
SETTING_NOTIFY_ADMINS = 'birthday_notify_admins'
SETTING_EMAIL_ADMINS = 'birthday_email_admins'

#: Per-process memo of the last date each tenant's sweep was attempted. Keeps
#: the request-time trigger down to a single DB round-trip per worker per day.
_last_attempt = {}

#: How long a claimed-but-unfinished sweep is left alone before another worker
#: is allowed to retry it.
STALE_CLAIM_AFTER = timedelta(minutes=30)


# ---------------------------------------------------------------------------
# Audience resolution
# ---------------------------------------------------------------------------
def _birthday_filters(today):
    """(month, day) pairs that count as "birthday today".

    A 29 February birthday is celebrated on 28 February in non-leap years so
    those students are not skipped three years out of four.
    """
    pairs = [(today.month, today.day)]
    if today.month == 2 and today.day == 28:
        try:
            date(today.year, 2, 29)
        except ValueError:
            pairs.append((2, 29))
    return pairs


def celebrants(tenant, today):
    """Students of ``tenant`` whose birthday falls on ``today``.

    Suspended, deactivated and profile-less accounts are excluded. Faculty and
    admins are not included — this is a student-facing celebration.
    """
    from django.db.models import Exists, OuterRef, Q
    from users.models import User, CourseEnrollment

    condition = Q()
    for month, day in _birthday_filters(today):
        condition |= Q(profile__date_of_birth__month=month,
                       profile__date_of_birth__day=day)

    active_enrollment = CourseEnrollment.objects.filter(
        student=OuterRef('profile'), status='approved', is_active=True,
    )

    return (
        User.objects
        .filter(condition, tenant=tenant, role='student',
                is_active=True, is_suspended=False)
        .exclude(profile__date_of_birth__isnull=True)
        .select_related('profile')
        .annotate(has_active_enrollment=Exists(active_enrollment))
        .order_by('first_name', 'email')
    )


def is_past_student(user):
    """True when the user has no active, approved enrolment right now.

    Covers both lapsed students (enrolment deactivated) and people who signed up
    but never got approved into a course — for either, a birthday wish is a
    natural re-engagement moment rather than a routine greeting.
    """
    annotated = getattr(user, 'has_active_enrollment', None)
    if annotated is not None:
        return not annotated
    profile = getattr(user, 'profile', None)
    if profile is None:
        return True
    return not profile.enrollments.filter(status='approved', is_active=True).exists()


def _first_name(user):
    return (user.first_name or '').strip() or (user.full_name or '').split(' ')[0] \
        or (user.email or '').split('@')[0]


def _age_turning(profile, today):
    """Age the student turns today, or ``None`` when the year is unusable."""
    dob = getattr(profile, 'date_of_birth', None)
    if not dob or not dob.year:
        return None
    age = today.year - dob.year
    return age if 0 < age < 120 else None


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------
def _greeting_copy(user, tenant, past_student, age):
    """In-app title/body for one celebrant."""
    tenant_name = getattr(tenant, 'name', '') or 'DailyTaiyari'
    first_name = _first_name(user)
    title = f'Happy Birthday, {first_name}! 🎂'
    if past_student:
        body = (
            f'Everyone at {tenant_name} is wishing you a wonderful day. '
            "You'll always be part of the family — come say hello whenever "
            "you're ready to pick up where you left off."
        )
    else:
        body = (
            f'{tenant_name} is celebrating you today. Thank you for the '
            'curiosity and effort you bring every day — have a brilliant one!'
        )
    if age:
        body = f'Turning {age} today! ' + body
    return title, body


def _greet(user, tenant, today, *, send_email, past_student=None):
    """Deliver one birthday greeting. Returns a summary dict, or None if skipped.

    The ``BirthdayGreetingLog`` row is created first and doubles as the lock: a
    duplicate key means someone else already wished this user this year. The
    in-app notification shares that transaction so a failure can never leave a
    student marked as greeted without a greeting.
    """
    profile = getattr(user, 'profile', None)
    if past_student is None:
        past_student = is_past_student(user)
    age = _age_turning(profile, today)
    tenant_name = getattr(tenant, 'name', '') or 'DailyTaiyari'
    title, body = _greeting_copy(user, tenant, past_student, age)

    try:
        with transaction.atomic():
            log = BirthdayGreetingLog.objects.create(
                tenant=tenant, user=user, year=today.year,
                is_past_student=past_student,
            )
            Notification.objects.create(
                recipient=user, tenant=tenant, type=Notification.TYPE_BIRTHDAY,
                title=title, body=body,
                link='/courses' if past_student else '/dashboard',
                data={
                    'first_name': _first_name(user),
                    'full_name': user.full_name or user.email,
                    'tenant_name': tenant_name,
                    'age': age,
                    'is_past_student': past_student,
                    'celebrate': True,
                },
            )
    except IntegrityError:
        return None  # Already greeted this year.

    emailed = False
    if send_email and user.email:
        from . import services

        template = TYPE_BIRTHDAY_PAST_STUDENT if past_student else TYPE_BIRTHDAY_STUDENT
        subject, heading, body_html = render_email(
            tenant, template,
            {
                'student_name': user.full_name or user.email,
                'first_name': _first_name(user),
                'tenant_name': tenant_name,
                'age': str(age) if age else '',
            },
        )
        banner = f'Turning {age} today!' if age else 'Happy Birthday!'
        services._dispatch_email(
            tenant, user.email,
            subject=subject,
            heading=heading,
            body_html=emails.celebration_body_html(
                tenant, body_html, badge='🎂', banner_text=banner,
            ),
            cta_text='Explore what’s new' if past_student else 'Open my dashboard',
            cta_url=emails.tenant_link(tenant, '/courses' if past_student else '/dashboard'),
            preheader=f'{tenant_name} is wishing you a very happy birthday.',
        )
        emailed = True
        BirthdayGreetingLog.objects.filter(pk=log.pk).update(emailed=True)

    return {
        'user_id': str(user.id),
        'name': user.full_name or user.email,
        'email': user.email,
        'age': age,
        'is_past_student': past_student,
        'emailed': emailed,
    }


def _notify_admins(tenant, today, greeted):
    """Send admins the daily digest (in-app and/or email) of today's birthdays."""
    from . import services

    notify_in_app = tenant.advanced_setting(SETTING_NOTIFY_ADMINS)
    send_email = tenant.advanced_setting(SETTING_EMAIL_ADMINS)
    if not greeted or not (notify_in_app or send_email):
        return

    admins = list(services._tenant_admins(tenant))
    if not admins:
        return

    names = [g['name'] for g in greeted]
    preview = ', '.join(names[:3])
    if len(names) > 3:
        preview += f' and {len(names) - 3} more'
    count = len(names)
    title = (
        f'🎂 {count} birthday today' if count == 1
        else f'🎂 {count} birthdays today'
    )
    body = f'{preview} — wish them a happy birthday!'
    admin_link = '/admin-dashboard?tab=students'

    if notify_in_app:
        Notification.objects.bulk_create([
            Notification(
                recipient=admin, tenant=tenant,
                type=Notification.TYPE_BIRTHDAY_DIGEST,
                title=title, body=body, link=admin_link,
                data={
                    'date': today.isoformat(),
                    'count': count,
                    'celebrants': [
                        {'name': g['name'], 'is_past_student': g['is_past_student']}
                        for g in greeted
                    ],
                },
            )
            for admin in admins
        ])

    if send_email:
        recipients = services._admin_email_recipients(tenant, admins)
        if recipients:
            listed = '\n'.join(
                f'• {g["name"]}' + (' (past student)' if g['is_past_student'] else '')
                for g in greeted
            )
            subject, heading, body_html = render_email(
                tenant, TYPE_BIRTHDAY_DIGEST,
                {
                    'tenant_name': getattr(tenant, 'name', '') or 'DailyTaiyari',
                    'count': str(count),
                    'names': listed,
                    'date': today.strftime('%d %B %Y'),
                },
            )
            services._dispatch_email(
                tenant, recipients,
                subject=subject,
                heading=heading,
                body_html=emails.celebration_body_html(
                    tenant, body_html, badge='🎉',
                    banner_text=f'{count} to celebrate today',
                ),
                cta_text='Open student list',
                cta_url=emails.tenant_link(tenant, admin_link),
                preheader=body,
            )


# ---------------------------------------------------------------------------
# Sweeps
# ---------------------------------------------------------------------------
def tenant_is_eligible(tenant):
    """True when ``tenant`` should have birthday greetings delivered."""
    if tenant is None or not tenant.is_active or tenant.is_suspended:
        return False
    if getattr(tenant, 'is_billing_frozen', False):
        return False
    return tenant.advanced_setting(SETTING_ENABLED)


def run_for_tenant(tenant, today=None, *, force=False, dry_run=False):
    """Deliver one tenant's birthday greetings for ``today``.

    Returns a summary dict. Never raises — a failure to celebrate must not break
    the request or cron job that triggered it.
    """
    today = today or timezone.localdate()
    summary = {'tenant': getattr(tenant, 'name', ''), 'date': today.isoformat(),
               'greeted': [], 'skipped': 0, 'enabled': True}

    try:
        if tenant is None or not tenant.is_active or tenant.is_suspended:
            summary['enabled'] = False
            return summary
        if getattr(tenant, 'is_billing_frozen', False):
            summary['enabled'] = False
            return summary
        if not force and not tenant.advanced_setting(SETTING_ENABLED):
            summary['enabled'] = False
            return summary

        include_past = tenant.advanced_setting(SETTING_INCLUDE_PAST)
        email_students = tenant.advanced_setting(SETTING_EMAIL_STUDENT)

        greeted = []
        for user in celebrants(tenant, today):
            past_student = is_past_student(user)
            if past_student and not include_past:
                summary['skipped'] += 1
                continue
            if dry_run:
                greeted.append({
                    'user_id': str(user.id),
                    'name': user.full_name or user.email,
                    'email': user.email,
                    'age': _age_turning(getattr(user, 'profile', None), today),
                    'is_past_student': past_student,
                    'emailed': False,
                })
                continue
            try:
                result = _greet(user, tenant, today, send_email=email_students,
                                past_student=past_student)
            except Exception:  # noqa: BLE001 - one bad record must not stop the rest
                logger.exception('Birthday greeting failed for user %s', user.id)
                summary['skipped'] += 1
                continue
            if result is None:
                summary['skipped'] += 1
            else:
                greeted.append(result)

        summary['greeted'] = greeted
        if not dry_run:
            # Record the run so the request-time trigger doesn't repeat a sweep
            # that cron (or another worker) already completed today.
            run, _ = BirthdayDispatchRun.objects.get_or_create(
                tenant=tenant, run_date=today,
            )
            BirthdayDispatchRun.objects.filter(pk=run.pk).update(
                greeted_count=run.greeted_count + len(greeted),
                completed_at=timezone.now(),
            )
            if greeted:
                _notify_admins(tenant, today, greeted)
    except Exception:  # noqa: BLE001 - greetings must never break the caller
        logger.exception('Birthday sweep failed for tenant %s',
                         getattr(tenant, 'id', None))
    return summary


def run_sweep(today=None, *, tenants=None, force=False, dry_run=False):
    """Run the birthday sweep across every eligible tenant."""
    from core.models import Tenant

    today = today or timezone.localdate()
    if tenants is None:
        tenants = Tenant.objects.filter(is_active=True)
    return [
        run_for_tenant(tenant, today, force=force, dry_run=dry_run)
        for tenant in tenants
    ]


def maybe_run_for_tenant(tenant):
    """Request-time trigger: run today's sweep once per tenant per day.

    Called from the notification endpoints the app polls, so greetings are
    delivered on schedule even when no cron/beat scheduler is configured. The
    per-process memo keeps this to at most one DB round-trip per worker per day,
    and ``BirthdayDispatchRun`` makes the claim atomic across workers. A claim
    that never completes (worker crash, broker loss) is retried after
    ``STALE_CLAIM_AFTER`` instead of silently losing the day.
    """
    if not tenant_is_eligible(tenant):
        return False

    today = timezone.localdate()
    if _last_attempt.get(tenant.id) == today:
        return False
    _last_attempt[tenant.id] = today

    try:
        if not _claim_run(tenant, today):
            return False
        # Never fan out inline on a user's request: queue it on a worker when
        # one is available, otherwise run it on a background thread so the
        # poll returns immediately and can't time out mid-batch.
        if getattr(django_settings, 'NOTIFICATIONS_ASYNC', False):
            try:
                from .tasks import run_tenant_birthday_sweep_task
                run_tenant_birthday_sweep_task.delay(str(tenant.id), today.isoformat())
                return True
            except Exception:  # noqa: BLE001 - broker down, fall back to a thread
                logger.exception('Async birthday sweep dispatch failed; running in-process')
        _run_in_background(tenant, today)
        return True
    except Exception:  # noqa: BLE001
        logger.exception('Lazy birthday trigger failed for tenant %s', tenant.id)
        return False


def _claim_run(tenant, today):
    """Atomically claim today's sweep for ``tenant``. False if someone else has it."""
    run, created = BirthdayDispatchRun.objects.get_or_create(
        tenant=tenant, run_date=today,
        defaults={'attempts': 1, 'last_attempt_at': timezone.now()},
    )
    if created:
        return True
    if run.completed_at is not None:
        return False

    # An in-flight claim is respected until it goes stale, then retried.
    cutoff = timezone.now() - STALE_CLAIM_AFTER
    claimed = (
        BirthdayDispatchRun.objects
        .filter(pk=run.pk, completed_at__isnull=True)
        .filter(Q(last_attempt_at__isnull=True) | Q(last_attempt_at__lt=cutoff))
        .update(last_attempt_at=timezone.now(), attempts=F('attempts') + 1)
    )
    return bool(claimed)


def _run_in_background(tenant, today):
    """Run the sweep off the request thread, closing its DB connections after."""
    def _worker():
        try:
            run_for_tenant(tenant, today)
        finally:
            db_connections.close_all()

    threading.Thread(
        target=_worker, name=f'birthday-sweep-{tenant.id}', daemon=True,
    ).start()
