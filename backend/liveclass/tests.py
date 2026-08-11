"""Tests for Zoom-backed live classes and attendance.

The parts worth pinning down are the ones a silent regression would corrupt:
webhook signature verification (a bad check accepts forged attendance),
participant→student matching, and the duration/status maths.
"""
import hashlib
import hmac
import json

from django.test import TestCase
from django.utils import timezone

from core.models import Tenant, ZoomIntegration
from exams.models import Course, Subject, Topic
from users.models import User, StudentProfile, CourseEnrollment

from .models import LiveClass, LiveClassAttendance, LiveClassRegistrant
from .services import handle_participant_joined, handle_participant_left, ensure_absent_rows
from .zoom import (
    is_valid_plain_token, verify_webhook_signature, webhook_validation_response,
)

WEBHOOK_PATH = '/api/v1/live-classes/zoom/webhook/'
SECRET = 'test-secret-token'


def tenant_webhook_path(tenant):
    return f'/api/v1/live-classes/zoom/webhook/{tenant.id}/'


def sign(secret, timestamp, body):
    message = f'v0:{timestamp}:{body}'
    digest = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return f'v0={digest}'


class ZoomSignatureTests(TestCase):
    def test_valid_signature_accepted(self):
        body = '{"event":"meeting.started"}'
        ts = '1700000000'
        headers = {'x-zm-signature': sign(SECRET, ts, body), 'x-zm-request-timestamp': ts}
        self.assertTrue(verify_webhook_signature(SECRET, headers, body.encode()))

    def test_wrong_secret_rejected(self):
        body = '{"event":"meeting.started"}'
        ts = '1700000000'
        headers = {'x-zm-signature': sign('other', ts, body), 'x-zm-request-timestamp': ts}
        self.assertFalse(verify_webhook_signature(SECRET, headers, body.encode()))

    def test_missing_headers_rejected(self):
        self.assertFalse(verify_webhook_signature(SECRET, {}, b'{}'))

    def test_no_secret_rejected(self):
        ts = '1700000000'
        headers = {'x-zm-signature': sign('', ts, '{}'), 'x-zm-request-timestamp': ts}
        self.assertFalse(verify_webhook_signature('', headers, b'{}'))

    def test_url_validation_response(self):
        out = webhook_validation_response(SECRET, 'abc')
        expected = hmac.new(SECRET.encode(), b'abc', hashlib.sha256).hexdigest()
        self.assertEqual(out, {'plainToken': 'abc', 'encryptedToken': expected})

    def test_signing_payload_is_not_a_valid_plain_token(self):
        # The challenge HMACs caller-supplied input with the same secret that
        # signs events. If a 'v0:<ts>:<body>' payload were accepted, the reply
        # would *be* a valid x-zm-signature for a forged event.
        body = '{"event":"meeting.participant_joined"}'
        self.assertFalse(is_valid_plain_token(f'v0:1700000000:{body}'))
        self.assertFalse(is_valid_plain_token('a' * 129))
        self.assertFalse(is_valid_plain_token(''))
        self.assertTrue(is_valid_plain_token('kIdN2_5rSY-jkjSDaP-t3w'))
        with self.assertRaises(ValueError):
            webhook_validation_response(SECRET, f'v0:1700000000:{body}')


class AttendanceBaseTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create(name='Zoom Academy', subdomain='zoomacademy')
        cls.zoom = ZoomIntegration.objects.create(
            tenant=cls.tenant, account_id='acc', client_id='cid',
            is_active=True, attendance_threshold_percent=60,
        )
        cls.zoom.client_secret = 'secret'
        cls.zoom.webhook_secret_token = SECRET
        cls.zoom.save()

        cls.course = Course.objects.create(
            tenant=cls.tenant, name='Python', code='py-zoom', course_type='other',
        )
        cls.subject = Subject.objects.create(name='Basics', code='basics', course=cls.course)
        cls.topic = Topic.objects.create(name='Loops', code='loops', subject=cls.subject)

        cls.live_class = LiveClass.objects.create(
            tenant=cls.tenant, course=cls.course, subject=cls.subject, topic=cls.topic,
            title='Live: Loops', provider=LiveClass.PROVIDER_ZOOM,
            zoom_meeting_id='9988776655', zoom_registration_enabled=True,
            scheduled_start=timezone.now() - timezone.timedelta(hours=2),
            duration_minutes=60, status='published',
        )

        cls.student = cls._make_student(cls, 'asha@example.com', 'Asha', 'Rao')
        cls.other = cls._make_student(cls, 'vik@example.com', 'Vik', 'Sen')

    def _make_student(self, email, first, last):
        user = User.objects.create_user(
            email=email, password='pw12345!', tenant=self.tenant,
            first_name=first, last_name=last,
        )
        # A post-save signal already creates the profile for new users.
        profile, _ = StudentProfile.objects.get_or_create(user=user)
        CourseEnrollment.objects.create(
            student=profile, course=self.course, status='approved', is_active=True,
        )
        return profile


class ParticipantMatchingTests(AttendanceBaseTestCase):
    def test_matched_by_registrant_id(self):
        LiveClassRegistrant.objects.create(
            live_class=self.live_class, student=self.student,
            email='asha@example.com', zoom_registrant_id='REG123',
        )
        row = handle_participant_joined(self.live_class, {
            'participant': {'registrant_id': 'REG123', 'user_name': 'Totally Different Name'},
        })
        self.assertEqual(row.student_id, self.student.id)

    def test_matched_by_account_email(self):
        row = handle_participant_joined(self.live_class, {
            'participant': {'email': 'ASHA@example.com', 'user_name': 'asha'},
        })
        self.assertEqual(row.student_id, self.student.id)

    def test_matched_by_exact_display_name(self):
        row = handle_participant_joined(self.live_class, {
            'participant': {'user_name': 'Asha Rao'},
        })
        self.assertEqual(row.student_id, self.student.id)

    def test_unknown_participant_kept_as_guest(self):
        row = handle_participant_joined(self.live_class, {
            'participant': {'user_name': 'Random Guest', 'email': 'guest@nowhere.test'},
        })
        self.assertIsNone(row.student_id)
        self.assertEqual(row.display_name, 'Random Guest')


class AttendanceDurationTests(AttendanceBaseTestCase):
    def test_join_then_leave_accumulates_and_marks_present(self):
        start = timezone.now() - timezone.timedelta(minutes=50)
        handle_participant_joined(self.live_class, {
            'participant': {'email': 'asha@example.com', 'join_time': start.isoformat()},
        })
        handle_participant_left(self.live_class, {
            'participant': {
                'email': 'asha@example.com',
                'leave_time': (start + timezone.timedelta(minutes=45)).isoformat(),
            },
        })
        row = LiveClassAttendance.objects.get(live_class=self.live_class, student=self.student)
        self.assertEqual(row.duration_minutes, 45)
        # 45 of 60 minutes = 75% ≥ 60% threshold.
        self.assertEqual(row.status, LiveClassAttendance.STATUS_PRESENT)
        self.assertFalse(row.is_currently_in_call)

    def test_short_visit_is_partial(self):
        start = timezone.now() - timezone.timedelta(minutes=50)
        handle_participant_joined(self.live_class, {
            'participant': {'email': 'asha@example.com', 'join_time': start.isoformat()},
        })
        handle_participant_left(self.live_class, {
            'participant': {
                'email': 'asha@example.com',
                'leave_time': (start + timezone.timedelta(minutes=10)).isoformat(),
            },
        })
        row = LiveClassAttendance.objects.get(live_class=self.live_class, student=self.student)
        self.assertEqual(row.status, LiveClassAttendance.STATUS_PARTIAL)

    def test_rejoin_sums_both_stints(self):
        base = timezone.now() - timezone.timedelta(minutes=60)
        for offset, length in ((0, 20), (30, 20)):
            join = base + timezone.timedelta(minutes=offset)
            handle_participant_joined(self.live_class, {
                'participant': {'email': 'asha@example.com', 'join_time': join.isoformat()},
            })
            handle_participant_left(self.live_class, {
                'participant': {
                    'email': 'asha@example.com',
                    'leave_time': (join + timezone.timedelta(minutes=length)).isoformat(),
                },
            })
        row = LiveClassAttendance.objects.get(live_class=self.live_class, student=self.student)
        self.assertEqual(row.join_count, 2)
        # 20 minutes, then 10 idle + 20 present measured from the previous leave.
        self.assertGreaterEqual(row.duration_minutes, 40)

    def test_manual_override_survives_recompute(self):
        row = LiveClassAttendance.objects.create(
            live_class=self.live_class, student=self.student,
            duration_minutes=0, status=LiveClassAttendance.STATUS_PRESENT,
            is_manual_override=True,
        )
        row.recompute_status(60)
        self.assertEqual(row.status, LiveClassAttendance.STATUS_PRESENT)

    def test_ensure_absent_rows_fills_the_roster(self):
        handle_participant_joined(self.live_class, {
            'participant': {'email': 'asha@example.com'},
        })
        created = ensure_absent_rows(self.live_class)
        self.assertEqual(created, 1)
        absent = LiveClassAttendance.objects.get(
            live_class=self.live_class, student=self.other
        )
        self.assertEqual(absent.status, LiveClassAttendance.STATUS_ABSENT)


class ZoomWebhookEndpointTests(AttendanceBaseTestCase):
    def _post(self, body_dict, secret=SECRET):
        body = json.dumps(body_dict)
        ts = '1700000000'
        return self.client.post(
            WEBHOOK_PATH, data=body, content_type='application/json',
            headers={
                'x-zm-signature': sign(secret, ts, body),
                'x-zm-request-timestamp': ts,
            },
        )

    def test_url_validation_challenge_on_tenant_scoped_url(self):
        resp = self.client.post(
            tenant_webhook_path(self.tenant),
            data=json.dumps({
                'event': 'endpoint.url_validation',
                'payload': {'plainToken': 'xyz'},
            }),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['plainToken'], 'xyz')
        self.assertEqual(
            resp.json()['encryptedToken'],
            hmac.new(SECRET.encode(), b'xyz', hashlib.sha256).hexdigest(),
        )

    def _challenge(self, path, plain):
        return self.client.post(
            path,
            data=json.dumps({
                'event': 'endpoint.url_validation',
                'payload': {'plainToken': plain},
            }),
            content_type='application/json',
        )

    def test_unscoped_url_validation_needs_an_open_window(self):
        # Without an explicitly opened window the legacy URL must not hand out
        # an HMAC computed with some arbitrary tenant's secret.
        ZoomIntegration.objects.filter(pk=self.zoom.pk).update(
            webhook_validation_until=None
        )
        self.assertEqual(self._challenge(WEBHOOK_PATH, 'xyz').status_code, 400)

        self.zoom.refresh_from_db()
        self.zoom.open_webhook_validation()
        self.assertEqual(self._challenge(WEBHOOK_PATH, 'xyz').status_code, 200)

        ZoomIntegration.objects.filter(pk=self.zoom.pk).update(
            webhook_validation_until=timezone.now() - timezone.timedelta(minutes=1)
        )
        self.assertEqual(self._challenge(WEBHOOK_PATH, 'xyz').status_code, 400)

    def test_validation_cannot_be_used_to_forge_a_signature(self):
        """The challenge must never sign a 'v0:<ts>:<body>' payload."""
        ts = '1700000000'
        body = json.dumps({
            'event': 'meeting.participant_joined',
            'payload': {'object': {'id': '9988776655',
                                   'participant': {'email': 'asha@example.com'}}},
        })
        resp = self._challenge(tenant_webhook_path(self.tenant), f'v0:{ts}:{body}')
        self.assertEqual(resp.status_code, 400)
        self.assertNotIn('encryptedToken', resp.json())

        # …and the forged event that HMAC would have authenticated is rejected.
        forged = self.client.post(
            WEBHOOK_PATH, data=body, content_type='application/json',
            headers={'x-zm-signature': 'v0=deadbeef', 'x-zm-request-timestamp': ts},
        )
        self.assertEqual(forged.status_code, 401)
        self.assertFalse(LiveClassAttendance.objects.exists())

    def test_scoped_url_ignores_another_tenants_meeting(self):
        other = Tenant.objects.create(name='Other', subdomain='other-zoom')
        body = json.dumps({
            'event': 'meeting.started',
            'payload': {'object': {'id': '9988776655', 'uuid': 'zzz=='}},
        })
        ts = '1700000000'
        resp = self.client.post(
            tenant_webhook_path(other), data=body, content_type='application/json',
            headers={'x-zm-signature': sign(SECRET, ts, body),
                     'x-zm-request-timestamp': ts},
        )
        self.assertEqual(resp.status_code, 200)
        self.live_class.refresh_from_db()
        self.assertNotEqual(self.live_class.zoom_meeting_uuid, 'zzz==')

    def test_forged_signature_rejected(self):
        resp = self._post({
            'event': 'meeting.participant_joined',
            'payload': {'object': {'id': '9988776655',
                                   'participant': {'email': 'asha@example.com'}}},
        }, secret='wrong-secret')
        self.assertEqual(resp.status_code, 401)
        self.assertFalse(LiveClassAttendance.objects.exists())

    def test_valid_participant_joined_recorded(self):
        resp = self._post({
            'event': 'meeting.participant_joined',
            'payload': {'object': {'id': '9988776655',
                                   'participant': {'email': 'asha@example.com'}}},
        })
        self.assertEqual(resp.status_code, 200)
        row = LiveClassAttendance.objects.get(live_class=self.live_class)
        self.assertEqual(row.student_id, self.student.id)
        self.assertTrue(row.is_currently_in_call)

    def test_unknown_meeting_is_acked(self):
        resp = self._post({
            'event': 'meeting.participant_joined',
            'payload': {'object': {'id': '0000000000', 'participant': {}}},
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(LiveClassAttendance.objects.exists())

    def test_webhook_needs_no_tenant_header(self):
        # TenantMiddleware must let Zoom through: it cannot send X-Tenant-ID.
        resp = self._post({
            'event': 'meeting.started',
            'payload': {'object': {'id': '9988776655', 'uuid': 'abc=='}},
        })
        self.assertEqual(resp.status_code, 200)
        self.live_class.refresh_from_db()
        self.assertEqual(self.live_class.zoom_meeting_uuid, 'abc==')


class StudentSerializerTests(AttendanceBaseTestCase):
    def test_registered_zoom_link_is_hidden_from_list(self):
        from .serializers import LiveClassSerializer

        self.live_class.meeting_url = 'https://zoom.us/j/9988776655'
        self.live_class.save()
        data = LiveClassSerializer(self.live_class).data
        self.assertTrue(data['requires_join_request'])
        # The shared link would let a student join unregistered and break
        # attendance matching, so it must not be handed out.
        self.assertEqual(data['meeting_url'], '')
