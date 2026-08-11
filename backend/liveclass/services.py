"""Live-class service layer — Zoom meeting lifecycle + attendance reconciliation.

Everything that talks to Zoom or mutates attendance lives here so views, the
webhook receiver and Celery tasks share one implementation (and one set of
matching rules).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone as dt_timezone

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from users.models import CourseEnrollment

from .models import LiveClass, LiveClassAttendance, LiveClassRegistrant
from .zoom import ZoomClient, ZoomError

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------- setup
def get_zoom_client(tenant):
    """Return a :class:`ZoomClient` for ``tenant``, or ``None`` when not connected."""
    integration = getattr(tenant, 'zoom', None)
    if not integration or not integration.is_active or not integration.is_configured:
        return None
    return ZoomClient(integration)


def zoom_settings(tenant):
    return getattr(tenant, 'zoom', None)


def attendance_threshold(tenant):
    integration = zoom_settings(tenant)
    return getattr(integration, 'attendance_threshold_percent', 60) or 60


# ------------------------------------------------------------------ meetings
def sync_zoom_meeting(live_class, *, create_if_missing=True):
    """Create or update the Zoom meeting backing ``live_class``.

    Returns ``(ok, error_message)``. Never raises: a Zoom outage must not stop
    an admin from saving the class — the class is simply left unlinked and can
    be retried from the UI.
    """
    if live_class.provider != LiveClass.PROVIDER_ZOOM:
        return True, ''

    client = get_zoom_client(live_class.tenant)
    if client is None:
        return False, ('Zoom is not connected for this academy. Add your Zoom '
                       'credentials in Settings → Integrations, or paste a Zoom '
                       'link manually.')

    integration = zoom_settings(live_class.tenant)
    with_registration = bool(integration and integration.use_registration)

    try:
        if live_class.zoom_meeting_id:
            data = client.update_meeting(
                live_class.zoom_meeting_id,
                topic=live_class.title,
                start_time=live_class.scheduled_start,
                duration=live_class.duration_minutes,
                agenda=live_class.description,
                with_registration=with_registration,
            )
        elif create_if_missing:
            data = client.create_meeting(
                topic=live_class.title,
                start_time=live_class.scheduled_start,
                duration=live_class.duration_minutes,
                agenda=live_class.description,
                with_registration=with_registration,
            )
        else:
            return True, ''
    except ZoomError as exc:
        logger.warning('Zoom meeting sync failed for live class %s: %s', live_class.pk, exc)
        return False, str(exc)

    _apply_meeting_payload(live_class, data, with_registration)
    return True, ''


def _apply_meeting_payload(live_class, data, with_registration):
    live_class.zoom_meeting_id = str(data.get('id') or live_class.zoom_meeting_id or '')
    live_class.zoom_start_url = data.get('start_url') or live_class.zoom_start_url
    live_class.zoom_passcode = data.get('password') or ''
    live_class.zoom_registration_enabled = with_registration
    join_url = data.get('join_url')
    if join_url:
        live_class.meeting_url = join_url
    live_class.save(update_fields=[
        'zoom_meeting_id', 'zoom_start_url', 'zoom_passcode',
        'zoom_registration_enabled', 'meeting_url', 'updated_at',
    ])


def delete_zoom_meeting(live_class):
    """Best-effort removal of the Zoom meeting when a class is deleted."""
    if not live_class.zoom_linked:
        return
    client = get_zoom_client(live_class.tenant)
    if client is None:
        return
    try:
        client.delete_meeting(live_class.zoom_meeting_id)
    except ZoomError as exc:
        logger.info('Could not delete Zoom meeting %s: %s', live_class.zoom_meeting_id, exc)


# --------------------------------------------------------------- registrants
def join_url_for_student(live_class, student):
    """The link this student should open, registering them with Zoom if needed.

    Falls back to the generic meeting URL whenever registration is off, Zoom is
    unreachable, or the plan does not allow registration — a student must never
    be blocked from joining because of a reporting feature.
    """
    if not live_class.zoom_linked or not live_class.zoom_registration_enabled:
        return live_class.meeting_url

    existing = LiveClassRegistrant.objects.filter(
        live_class=live_class, student=student
    ).first()
    if existing and existing.join_url:
        return existing.join_url

    client = get_zoom_client(live_class.tenant)
    user = getattr(student, 'user', None)
    email = getattr(user, 'email', '') or ''
    if client is None or not email:
        return live_class.meeting_url

    try:
        data = client.add_registrant(
            live_class.zoom_meeting_id,
            email=email,
            first_name=getattr(user, 'first_name', '') or email.split('@')[0],
            last_name=getattr(user, 'last_name', '') or '',
        )
    except ZoomError as exc:
        logger.info('Zoom registration failed for %s on class %s: %s',
                    email, live_class.pk, exc)
        return live_class.meeting_url

    join_url = data.get('join_url') or live_class.meeting_url
    LiveClassRegistrant.objects.update_or_create(
        live_class=live_class, student=student,
        defaults={
            'email': email,
            'zoom_registrant_id': str(data.get('registrant_id') or ''),
            'join_url': join_url,
        },
    )
    return join_url


# --------------------------------------------------------------- attendance
def record_portal_join(live_class, student):
    """Log that a student opened the class from inside DailyTaiyari.

    This is the only attendance signal available for Google Meet classes and on
    free Zoom plans, so it always runs — Zoom data later overwrites the duration
    on the same row when it arrives.
    """
    row, created = LiveClassAttendance.objects.get_or_create(
        live_class=live_class, student=student,
        defaults={
            'display_name': _student_name(student),
            'email': _student_email(student),
            'source': LiveClassAttendance.SOURCE_PORTAL,
            'first_joined_at': timezone.now(),
            'join_count': 1,
        },
    )
    if not created:
        updates = ['join_count', 'updated_at']
        row.join_count = (row.join_count or 0) + 1
        if not row.first_joined_at:
            row.first_joined_at = timezone.now()
            updates.append('first_joined_at')
        row.save(update_fields=updates)
    return row


def _student_name(student):
    user = getattr(student, 'user', None)
    if not user:
        return ''
    return (user.full_name or user.email or '').strip()


def _student_email(student):
    user = getattr(student, 'user', None)
    return (getattr(user, 'email', '') or '').strip()


def enrolled_students(live_class):
    """Approved, active students of the class's course."""
    from users.models import StudentProfile
    student_ids = CourseEnrollment.objects.filter(
        course_id=live_class.course_id, status='approved', is_active=True,
    ).values_list('student_id', flat=True)
    return StudentProfile.objects.filter(id__in=student_ids).select_related('user')


def ensure_absent_rows(live_class):
    """Materialise an 'absent' row for every enrolled student without one.

    Runs after a class ends so the admin's attendance table is a full roster
    (present + absent) rather than only the people who showed up.
    """
    existing = set(
        LiveClassAttendance.objects.filter(live_class=live_class)
        .exclude(student__isnull=True)
        .values_list('student_id', flat=True)
    )
    missing = [s for s in enrolled_students(live_class) if s.id not in existing]
    if not missing:
        return 0
    LiveClassAttendance.objects.bulk_create([
        LiveClassAttendance(
            live_class=live_class, student=s,
            display_name=_student_name(s), email=_student_email(s),
            status=LiveClassAttendance.STATUS_ABSENT,
            source=LiveClassAttendance.SOURCE_REPORT,
        ) for s in missing
    ], ignore_conflicts=True)
    return len(missing)


def _match_student(live_class, *, registrant_id='', email='', name=''):
    """Map a Zoom participant back to one of our students.

    Order of confidence: Zoom registrant id → registrant email → the student's
    account email → an exact display-name match among enrolled students.
    """
    if registrant_id:
        reg = LiveClassRegistrant.objects.filter(
            live_class=live_class, zoom_registrant_id=str(registrant_id)
        ).select_related('student').first()
        if reg:
            return reg.student

    email = (email or '').strip().lower()
    if email:
        reg = LiveClassRegistrant.objects.filter(
            live_class=live_class, email__iexact=email
        ).select_related('student').first()
        if reg:
            return reg.student
        match = enrolled_students(live_class).filter(user__email__iexact=email).first()
        if match:
            return match

    name = (name or '').strip()
    if name:
        candidates = [
            s for s in enrolled_students(live_class)
            if _student_name(s).lower() == name.lower()
        ]
        # Only trust a name when it is unambiguous.
        if len(candidates) == 1:
            return candidates[0]
    return None


def _attendance_row(live_class, *, student, email, name, participant_uuid, registrant_id):
    """Find or create the row a Zoom participant belongs to."""
    if student is not None:
        row, _ = LiveClassAttendance.objects.get_or_create(
            live_class=live_class, student=student,
            defaults={'display_name': name, 'email': email},
        )
        return row

    # Guest: de-duplicate on Zoom's identity, then email, then display name.
    qs = LiveClassAttendance.objects.filter(live_class=live_class, student__isnull=True)
    row = None
    if participant_uuid:
        row = qs.filter(zoom_participant_uuid=participant_uuid).first()
    if row is None and registrant_id:
        row = qs.filter(zoom_registrant_id=str(registrant_id)).first()
    if row is None and email:
        row = qs.filter(email__iexact=email).first()
    if row is None and name:
        row = qs.filter(display_name__iexact=name).first()
    if row is None:
        row = LiveClassAttendance.objects.create(
            live_class=live_class, student=None,
            display_name=name, email=email,
            zoom_participant_uuid=participant_uuid or '',
            zoom_registrant_id=str(registrant_id or ''),
        )
    return row


@transaction.atomic
def handle_participant_joined(live_class, payload):
    """Apply a Zoom ``meeting.participant_joined`` event."""
    participant = payload.get('participant') or {}
    email = (participant.get('email') or '').strip()
    name = (participant.get('user_name') or '').strip()
    registrant_id = participant.get('registrant_id') or ''
    participant_uuid = participant.get('participant_uuid') or participant.get('id') or ''
    joined_at = _parse_zoom_time(participant.get('join_time')) or timezone.now()

    student = _match_student(
        live_class, registrant_id=registrant_id, email=email, name=name
    )
    row = _attendance_row(
        live_class, student=student, email=email, name=name,
        participant_uuid=participant_uuid, registrant_id=registrant_id,
    )
    row.display_name = row.display_name or name
    row.email = row.email or email
    row.zoom_participant_uuid = participant_uuid or row.zoom_participant_uuid
    row.zoom_registrant_id = str(registrant_id or row.zoom_registrant_id or '')
    if not row.first_joined_at or joined_at < row.first_joined_at:
        row.first_joined_at = joined_at
    row.join_count = (row.join_count or 0) + 1
    row.is_currently_in_call = True
    # Only upgrade the source: a later report is more authoritative than a webhook.
    if row.source != LiveClassAttendance.SOURCE_REPORT:
        row.source = LiveClassAttendance.SOURCE_WEBHOOK
    row.save()
    return row


@transaction.atomic
def handle_participant_left(live_class, payload):
    """Apply a Zoom ``meeting.participant_left`` event, accumulating duration."""
    participant = payload.get('participant') or {}
    email = (participant.get('email') or '').strip()
    name = (participant.get('user_name') or '').strip()
    registrant_id = participant.get('registrant_id') or ''
    participant_uuid = participant.get('participant_uuid') or participant.get('id') or ''
    left_at = _parse_zoom_time(participant.get('leave_time')) or timezone.now()

    student = _match_student(
        live_class, registrant_id=registrant_id, email=email, name=name
    )
    row = _attendance_row(
        live_class, student=student, email=email, name=name,
        participant_uuid=participant_uuid, registrant_id=registrant_id,
    )
    # Accumulate this stint. The report sync later replaces the total with
    # Zoom's own figure, so drift from missed events is self-healing.
    anchor = row.last_left_at or row.first_joined_at
    if anchor and left_at > anchor:
        minutes = int((left_at - anchor).total_seconds() // 60)
        row.duration_minutes = (row.duration_minutes or 0) + max(minutes, 0)
    row.last_left_at = left_at
    row.is_currently_in_call = False
    if row.source != LiveClassAttendance.SOURCE_REPORT:
        row.source = LiveClassAttendance.SOURCE_WEBHOOK
    row.recompute_status(attendance_threshold(live_class.tenant))
    row.save()
    return row


def sync_attendance_from_zoom(live_class, *, force=False):
    """Pull the authoritative participant report and overwrite computed data.

    Returns ``(ok, message)``. Safe to call repeatedly — it is idempotent.
    """
    if not live_class.zoom_linked:
        return False, 'This class is not linked to a Zoom meeting.'
    client = get_zoom_client(live_class.tenant)
    if client is None:
        return False, 'Zoom is not connected for this academy.'
    if not force and live_class.live_status == 'upcoming':
        return False, 'This class has not started yet.'

    integration = zoom_settings(live_class.tenant)
    if integration and not integration.pull_reports and not force:
        return False, 'Zoom report syncing is turned off for this academy.'

    # Prefer the specific occurrence UUID when we have one (recurring meetings
    # reuse the numeric id across occurrences).
    meeting_ref = live_class.zoom_meeting_uuid or live_class.zoom_meeting_id
    try:
        participants = client.get_participants(_encode_uuid(meeting_ref))
    except ZoomError as exc:
        live_class.attendance_sync_error = str(exc)
        live_class.save(update_fields=['attendance_sync_error', 'updated_at'])
        return False, str(exc)

    threshold = attendance_threshold(live_class.tenant)
    seen = {}
    with transaction.atomic():
        for p in participants:
            email = (p.get('user_email') or p.get('email') or '').strip()
            name = (p.get('name') or p.get('user_name') or '').strip()
            registrant_id = p.get('registrant_id') or ''
            participant_uuid = p.get('participant_uuid') or p.get('id') or ''
            duration_seconds = int(p.get('duration') or 0)
            join_time = _parse_zoom_time(p.get('join_time'))
            leave_time = _parse_zoom_time(p.get('leave_time'))

            student = _match_student(
                live_class, registrant_id=registrant_id, email=email, name=name
            )
            row = _attendance_row(
                live_class, student=student, email=email, name=name,
                participant_uuid=participant_uuid, registrant_id=registrant_id,
            )
            key = row.pk
            # The report lists one entry per stint; sum them per person.
            agg = seen.setdefault(key, {'seconds': 0, 'join': None, 'leave': None, 'count': 0})
            agg['seconds'] += duration_seconds
            agg['count'] += 1
            if join_time and (agg['join'] is None or join_time < agg['join']):
                agg['join'] = join_time
            if leave_time and (agg['leave'] is None or leave_time > agg['leave']):
                agg['leave'] = leave_time

            row.display_name = row.display_name or name
            row.email = row.email or email
            row.zoom_registrant_id = str(registrant_id or row.zoom_registrant_id or '')
            row.zoom_participant_uuid = participant_uuid or row.zoom_participant_uuid
            row.source = LiveClassAttendance.SOURCE_REPORT
            row.duration_minutes = int(round(agg['seconds'] / 60))
            row.join_count = agg['count']
            row.first_joined_at = agg['join'] or row.first_joined_at
            row.last_left_at = agg['leave'] or row.last_left_at
            row.is_currently_in_call = False
            row.recompute_status(threshold)
            row.save()

        ensure_absent_rows(live_class)
        # Anyone who never appeared in the report is absent (unless an admin
        # said otherwise, or they only have a portal-click record we keep).
        LiveClassAttendance.objects.filter(
            live_class=live_class, is_manual_override=False, duration_minutes=0,
        ).exclude(pk__in=seen.keys()).update(
            status=LiveClassAttendance.STATUS_ABSENT, is_currently_in_call=False,
        )

        live_class.attendance_synced_at = timezone.now()
        live_class.attendance_sync_error = ''
        live_class.save(update_fields=[
            'attendance_synced_at', 'attendance_sync_error', 'updated_at',
        ])

    return True, f'Synced {len(seen)} participant(s) from Zoom.'


def attendance_summary(live_class):
    """Counts used by the admin attendance header."""
    rows = LiveClassAttendance.objects.filter(live_class=live_class)
    enrolled = enrolled_students(live_class).count()
    present = rows.filter(status=LiveClassAttendance.STATUS_PRESENT).count()
    partial = rows.filter(status=LiveClassAttendance.STATUS_PARTIAL).count()
    guests = rows.filter(student__isnull=True).exclude(
        status=LiveClassAttendance.STATUS_ABSENT
    ).count()
    attended = rows.filter(
        Q(status=LiveClassAttendance.STATUS_PRESENT)
        | Q(status=LiveClassAttendance.STATUS_PARTIAL)
    ).exclude(student__isnull=True).count()
    return {
        'enrolled': enrolled,
        'attended': attended,
        'present': present,
        'partial': partial,
        'absent': max(enrolled - attended, 0),
        'guests': guests,
        'in_call_now': rows.filter(is_currently_in_call=True).count(),
        'attendance_rate': int(round(attended * 100 / enrolled)) if enrolled else 0,
        'synced_at': live_class.attendance_synced_at,
        'sync_error': live_class.attendance_sync_error,
    }


# ------------------------------------------------------------------ helpers
def _parse_zoom_time(value):
    """Parse Zoom's ``2024-01-01T10:00:00Z`` timestamps into aware datetimes."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (ValueError, TypeError):
        return None
    if timezone.is_naive(dt):
        dt = dt.replace(tzinfo=dt_timezone.utc)
    return dt


def _encode_uuid(meeting_ref):
    """Double-URL-encode meeting UUIDs that need it.

    Zoom requires UUIDs containing ``/`` or starting with ``//`` to be double
    encoded when used as a path segment. Plain numeric ids pass through.
    """
    ref = str(meeting_ref or '')
    if ref.isdigit():
        return ref
    if ref.startswith('/') or '//' in ref:
        from urllib.parse import quote
        return quote(quote(ref, safe=''), safe='')
    return ref
