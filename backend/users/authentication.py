from rest_framework_simplejwt.authentication import JWTAuthentication


class RegistrationAwareJWTAuthentication(JWTAuthentication):
    """JWT authentication retained for compatibility; consent is reminder-only."""
