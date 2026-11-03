from django.utils import timezone

from .models import GuardianConsent


def guardian_consent_state(user, *, mask_email=False):
    """Return the current tenant guardian-consent state for a student."""
    tenant = user.tenant
    if (
        not tenant
        or user.role != 'student'
        or not tenant.get_registration_settings()['guardian_consent']['enabled']
    ):
        return {'status': 'not_required', 'eligible': False}

    profile = getattr(user, 'profile', None)
    if not profile or not profile.date_of_birth:
        return {'status': 'date_of_birth_required', 'eligible': None}

    today = timezone.localdate()
    dob = profile.date_of_birth
    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    if age >= 18:
        return {'status': 'not_required', 'eligible': False}

    consent = getattr(user, 'guardian_consent', None)
    if not consent:
        return {'status': 'guardian_details_required', 'eligible': True}

    guardian_email = consent.guardian_email
    if mask_email and '@' in guardian_email:
        local, domain = guardian_email.split('@', 1)
        guardian_email = f"{local[:1]}***@{domain}"

    details = {
        'eligible': True,
        'guardian_name': consent.guardian_name,
        'guardian_email': guardian_email,
        'guardian_phone': consent.guardian_phone,
        'guardian_relationship': consent.relationship,
        'requested_at': consent.created_at,
        'updated_at': consent.updated_at,
        'expires_at': consent.expires_at,
        'granted_at': consent.granted_at,
    }
    if (
        consent.status == GuardianConsent.STATUS_GRANTED
        and user.guardian_consent_granted_at
    ):
        return {'status': 'compliant', **details}
    return {'status': 'guardian_approval_pending', **details}
