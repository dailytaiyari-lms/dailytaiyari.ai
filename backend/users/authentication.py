from rest_framework.exceptions import PermissionDenied
from rest_framework_simplejwt.authentication import JWTAuthentication


class RegistrationAwareJWTAuthentication(JWTAuthentication):
    """Block protected APIs while mandatory guardian approval is pending."""

    EXEMPT_PREFIXES = (
        '/api/v1/auth/login/',
        '/api/v1/auth/refresh/',
        '/api/v1/auth/verify-email/',
        '/api/v1/auth/resend-otp/',
        '/api/v1/auth/guardian-consent/',
        '/api/v1/auth/compliance-status/',
        '/api/v1/auth/password/',
        '/api/v1/auth/user/',
        '/api/v1/auth/profile/',
    )

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None
        user, token = result
        if (
            user.guardian_consent_required
            and not user.guardian_consent_granted_at
            and not any(request.path.startswith(path) for path in self.EXEMPT_PREFIXES)
        ):
            raise PermissionDenied({
                'detail': 'Parent or guardian approval is required.',
                'code': 'guardian_consent_required',
            })
        return user, token
