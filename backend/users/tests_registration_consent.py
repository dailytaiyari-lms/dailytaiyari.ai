from datetime import date, timedelta
from types import SimpleNamespace

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import Tenant
from notifications.emails import tenant_link
from users.models import GuardianConsent, User
from users.serializers import UserRegistrationSerializer
from users.views import (
    _existing_student_compliance,
    _issue_guardian_consent,
)


class RegistrationSettingsTests(TestCase):
    def test_defaults_preserve_phone_only(self):
        tenant = Tenant.objects.create(name='Example Academy')
        settings = tenant.get_registration_settings()
        self.assertTrue(settings['fields']['phone']['enabled'])
        self.assertFalse(settings['fields']['date_of_birth']['enabled'])
        self.assertFalse(settings['guardian_consent']['enabled'])

    def test_guardian_consent_forces_required_date_of_birth(self):
        tenant = Tenant.objects.create(
            name='Example Academy',
            registration_settings={'guardian_consent': {'enabled': True}},
        )
        settings = tenant.get_registration_settings()
        self.assertTrue(settings['fields']['date_of_birth']['enabled'])
        self.assertTrue(settings['fields']['date_of_birth']['required'])


class UnderageRegistrationTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            name='Example Academy',
            registration_settings={'guardian_consent': {'enabled': True}},
        )
        self.request = SimpleNamespace(tenant=self.tenant)

    def payload(self):
        today = timezone.localdate()
        return {
            'first_name': 'Aarav',
            'last_name': 'Student',
            'email': 'aarav@example.com',
            'password': 'secure-pass-123',
            'password_confirm': 'secure-pass-123',
            'date_of_birth': date(today.year - 12, 1, 1),
        }

    def test_guardian_details_are_required_for_underage_student(self):
        serializer = UserRegistrationSerializer(
            data=self.payload(), context={'request': self.request}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn('guardian_email', serializer.errors)

    def test_underage_student_is_marked_pending_guardian_consent(self):
        payload = {
            **self.payload(),
            'guardian_name': 'Parent Name',
            'guardian_email': 'parent@example.com',
            'guardian_relationship': 'parent',
        }
        serializer = UserRegistrationSerializer(
            data=payload, context={'request': self.request}
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        user = serializer.save(tenant=self.tenant)
        self.assertTrue(user.guardian_consent_required)
        self.assertIsNone(user.guardian_consent_granted_at)
        self.assertEqual(user.profile.date_of_birth, payload['date_of_birth'])

    def test_guardian_consent_expiry(self):
        payload = {
            **self.payload(),
            'guardian_name': 'Parent Name',
            'guardian_email': 'parent@example.com',
            'guardian_relationship': 'parent',
        }
        serializer = UserRegistrationSerializer(
            data=payload, context={'request': self.request}
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        user = serializer.save(tenant=self.tenant)
        consent = GuardianConsent.objects.create(
            tenant=self.tenant,
            user=user,
            guardian_name='Parent Name',
            guardian_email='parent@example.com',
            relationship='parent',
            token_hash='a' * 64,
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        self.assertTrue(consent.is_expired())


class ExistingStudentComplianceTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            name='Example Academy',
            registration_settings={'guardian_consent': {'enabled': True}},
        )
        self.user = User.objects.create_user(
            email='existing@example.com',
            tenant=self.tenant,
            password='secure-pass-123',
            first_name='Existing',
        )

    def test_missing_dob_requires_age_confirmation(self):
        self.assertEqual(
            _existing_student_compliance(self.user)['status'],
            'date_of_birth_required',
        )

    def test_existing_adult_does_not_require_guardian_consent(self):
        today = timezone.localdate()
        self.user.profile.date_of_birth = date(today.year - 20, 1, 1)
        self.user.profile.save(update_fields=['date_of_birth', 'updated_at'])
        self.assertEqual(
            _existing_student_compliance(self.user)['status'],
            'not_required',
        )

    def test_existing_minor_receives_reminder_without_account_block(self):
        today = timezone.localdate()
        self.user.profile.date_of_birth = date(today.year - 12, 1, 1)
        self.user.profile.save(update_fields=['date_of_birth', 'updated_at'])
        self.assertEqual(
            _existing_student_compliance(self.user)['status'],
            'guardian_details_required',
        )
        self.assertFalse(self.user.guardian_consent_required)


class GuardianApprovalEmailTests(TestCase):
    def test_first_party_request_origin_builds_absolute_link(self):
        tenant = Tenant.objects.create(name='Example Academy')
        request = SimpleNamespace(
            headers={'Origin': 'https://academy.dailytaiyari.in'}
        )
        self.assertEqual(
            tenant_link(tenant, '/guardian-consent/token', request=request),
            'https://academy.dailytaiyari.in/guardian-consent/token',
        )

    def test_configured_external_origin_builds_absolute_link(self):
        tenant = Tenant.objects.create(
            name='Example Academy',
            allowed_origins=['https://academy.example.com'],
        )
        request = SimpleNamespace(
            headers={'Origin': 'https://academy.example.com'}
        )
        self.assertEqual(
            tenant_link(tenant, '/guardian-consent/token', request=request),
            'https://academy.example.com/guardian-consent/token',
        )

    def test_untrusted_request_origin_falls_back_to_configured_origin(self):
        tenant = Tenant.objects.create(
            name='Example Academy',
            allowed_origins=['https://academy.example.com'],
        )
        request = SimpleNamespace(headers={'Origin': 'https://attacker.example'})
        self.assertEqual(
            tenant_link(tenant, '/guardian-consent/token', request=request),
            'https://academy.example.com/guardian-consent/token',
        )

    def test_missing_absolute_origin_does_not_create_consent_request(self):
        tenant = Tenant.objects.create(name='Example Academy')
        user = User.objects.create_user(
            email='student@example.com',
            tenant=tenant,
            password='secure-pass-123',
        )
        with self.assertRaises(ValueError):
            _issue_guardian_consent(user, {
                'guardian_name': 'Parent',
                'guardian_email': 'parent@example.com',
                'guardian_phone': '',
                'guardian_relationship': 'parent',
            })
        self.assertFalse(GuardianConsent.objects.filter(user=user).exists())

    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        DEFAULT_FROM_EMAIL='DoNotReply@dailytaiyari.in',
    )
    def test_platform_named_tenant_uses_neutral_guardian_email_brand(self):
        tenant = Tenant.objects.create(
            name='DailyTaiyari',
            allowed_origins=['https://academy.example.com'],
        )
        user = User.objects.create_user(
            email='student@example.com',
            tenant=tenant,
            password='secure-pass-123',
            first_name='Aarav',
        )
        request = SimpleNamespace(
            headers={'Origin': 'https://academy.example.com'}
        )
        sent = _issue_guardian_consent(user, {
            'guardian_name': 'Parent',
            'guardian_email': 'parent@example.com',
            'guardian_phone': '',
            'guardian_relationship': 'parent',
        }, request=request)
        self.assertTrue(sent)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        html_body = message.alternatives[0][0]
        self.assertNotIn('DailyTaiyari', message.subject)
        self.assertNotIn('DailyTaiyari', message.body)
        self.assertNotIn('DailyTaiyari', html_body)
        self.assertIn(
            'https://academy.example.com/guardian-consent/',
            message.body,
        )
        self.assertIn(
            'https://academy.example.com/guardian-consent/',
            html_body,
        )
