"""
Email + OTP helpers for user email verification.

Sending goes through Django's standard email framework (``send_mail``),
so the underlying transport is controlled entirely by ``EMAIL_BACKEND`` in
settings. In production this is Azure Communication Services Email; in
development it falls back to the console backend so no real mail is sent.
"""
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import make_password, check_password
from django.core.mail import send_mail
from django.utils import timezone

from .models import EmailOTP


def _generate_code(num_digits: int = 6) -> str:
    """Return a cryptographically-random zero-padded numeric OTP."""
    upper = 10 ** num_digits
    return str(secrets.randbelow(upper)).zfill(num_digits)


# Ambiguous glyphs (0/O, 1/l/I) are excluded so a password read off an email
# can be retyped without confusion. '&' is excluded too: it would render as
# '&amp;' in the plain-text part of the HTML email.
_PASSWORD_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789'
_PASSWORD_SYMBOLS = '@#$%*'


def generate_temp_password(length: int = 12) -> str:
    """Return a readable, cryptographically-random temporary password.

    Guarantees at least one uppercase, one lowercase, one digit and one symbol
    so the value always satisfies common password policies.
    """
    length = max(length, 8)
    required = [
        secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ'),
        secrets.choice('abcdefghijkmnopqrstuvwxyz'),
        secrets.choice('23456789'),
        secrets.choice(_PASSWORD_SYMBOLS),
    ]
    rest = [secrets.choice(_PASSWORD_ALPHABET) for _ in range(length - len(required))]
    chars = required + rest
    # Fisher-Yates shuffle with a CSPRNG (random.shuffle is not crypto-safe).
    for i in range(len(chars) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        chars[i], chars[j] = chars[j], chars[i]
    return ''.join(chars)


def can_resend(user, purpose: str = 'email_verification') -> bool:
    """Enforce a per-user cooldown between OTP sends."""
    latest = (
        EmailOTP.objects
        .filter(user=user, purpose=purpose)
        .order_by('-created_at')
        .first()
    )
    if not latest:
        return True
    cooldown = timedelta(seconds=EmailOTP.RESEND_COOLDOWN_SECONDS)
    return timezone.now() >= latest.created_at + cooldown


def create_and_send_otp(user, purpose: str = 'email_verification') -> EmailOTP:
    """
    Invalidate any outstanding OTPs, mint a fresh one, email it, and
    return the created ``EmailOTP`` record.
    """
    # Invalidate previous unused codes so only the newest one works.
    EmailOTP.objects.filter(
        user=user, purpose=purpose, is_used=False
    ).update(is_used=True)

    code = _generate_code()
    otp = EmailOTP.objects.create(
        user=user,
        tenant=user.tenant,
        code_hash=make_password(code),
        purpose=purpose,
        expires_at=timezone.now() + timedelta(minutes=EmailOTP.EXPIRY_MINUTES),
    )

    _send_otp_email(user, code, purpose)
    return otp


def verify_otp(user, code: str, purpose: str = 'email_verification'):
    """
    Validate ``code`` against the newest usable OTP for ``user``.

    Returns ``(ok: bool, error: str | None)``.
    """
    otp = (
        EmailOTP.objects
        .filter(user=user, purpose=purpose, is_used=False)
        .order_by('-created_at')
        .first()
    )

    if otp is None:
        return False, 'No verification code found. Please request a new one.'
    if otp.is_expired():
        return False, 'This code has expired. Please request a new one.'
    if otp.attempts >= EmailOTP.MAX_ATTEMPTS:
        return False, 'Too many attempts. Please request a new code.'

    if not check_password(code, otp.code_hash):
        otp.attempts += 1
        otp.save(update_fields=['attempts', 'updated_at'])
        remaining = EmailOTP.MAX_ATTEMPTS - otp.attempts
        return False, f'Invalid code. {remaining} attempt(s) remaining.'

    otp.is_used = True
    otp.save(update_fields=['is_used', 'updated_at'])
    return True, None


def _send_otp_email(user, code: str, purpose: str) -> None:
    minutes = EmailOTP.EXPIRY_MINUTES
    greeting = f"Hi {user.first_name or 'there'},"
    signature = "— The DailyTaiyari Team"

    if purpose == 'password_reset':
        subject = 'Your DailyTaiyari password reset code'
        intro = 'We received a request to reset your DailyTaiyari password. Your code is:'
        footer = "If you didn't request a password reset, you can safely ignore this email."
    else:
        subject = 'Your DailyTaiyari verification code'
        intro = 'Your DailyTaiyari email verification code is:'
        footer = "If you didn't request this, you can safely ignore this email."

    message = (
        f"{greeting}\n\n"
        f"{intro}\n\n"
        f"    {code}\n\n"
        f"This code expires in {minutes} minutes. {footer}\n\n"
        f"{signature}"
    )
    send_mail(
        subject=subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )
