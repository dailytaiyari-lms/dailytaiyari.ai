"""Tests that OTP emails carry the sending tenant's branding.

These codes were the last tenant-facing email still hardcoding the platform
name, so the assertions here are deliberately about *branding*, not delivery.
"""
from django.core import mail
from django.test import TestCase, override_settings

from core.models import Tenant
from users.emails import create_and_send_otp
from users.models import User


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    DEFAULT_FROM_EMAIL='DoNotReply@dailytaiyari.in',
)
class OTPEmailBrandingTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name='CodeMinors', theme='indigo')
        self.user = User.objects.create_user(
            email='student@codeminors.in', tenant=self.tenant,
            password='pass12345', first_name='Sam',
        )

    def _send(self, purpose='email_verification'):
        mail.outbox = []
        create_and_send_otp(self.user, purpose=purpose)
        self.assertEqual(len(mail.outbox), 1)
        return mail.outbox[0]

    def test_verification_email_uses_tenant_name_not_platform_name(self):
        msg = self._send()
        self.assertEqual(msg.subject, 'Your CodeMinors verification code')
        self.assertNotIn('DailyTaiyari', msg.subject)
        self.assertNotIn('DailyTaiyari', msg.body)

    def test_password_reset_email_uses_tenant_name(self):
        msg = self._send(purpose='password_reset')
        self.assertEqual(msg.subject, 'Your CodeMinors password reset code')
        self.assertNotIn('DailyTaiyari', msg.body)

    def test_sender_shows_tenant_display_name_on_platform_domain(self):
        msg = self._send()
        # Only the display name is tenant-specific; the mailbox must stay on
        # the verified sending domain or Azure will reject the message.
        self.assertEqual(msg.from_email, 'CodeMinors <DoNotReply@dailytaiyari.in>')

    def test_email_is_html_branded_and_carries_the_code(self):
        msg = self._send()
        self.assertEqual(len(msg.alternatives), 1)
        html, mimetype = msg.alternatives[0]
        self.assertEqual(mimetype, 'text/html')
        # Tenant name in the branded header, accent from the tenant theme.
        self.assertIn('CodeMinors', html)
        self.assertIn('#4f46e5', html)
        # The six-digit code must appear in both parts.
        code = next(t for t in msg.body.split() if t.isdigit() and len(t) == 6)
        self.assertIn(code, html)

    def test_falls_back_to_platform_name_when_user_has_no_tenant(self):
        self.user.tenant = None
        self.user.save(update_fields=['tenant'])
        msg = self._send()
        self.assertEqual(msg.subject, 'Your DailyTaiyari verification code')
