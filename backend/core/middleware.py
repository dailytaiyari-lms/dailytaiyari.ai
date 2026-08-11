import logging
import uuid

from django.utils.deprecation import MiddlewareMixin
from django.http import JsonResponse
from core.models import Tenant

logger = logging.getLogger(__name__)

_USER_CACHE_ATTR = '_resolved_api_user'


def resolve_request_user(request):
    """The authenticated user for an API request, or ``None``.

    Middleware runs before DRF, so ``request.user`` is still anonymous for
    token-authenticated calls. We decode the JWT here and cache the result on
    the request so the tenant and suspension checks don't each pay for it.
    """
    if hasattr(request, _USER_CACHE_ATTR):
        return getattr(request, _USER_CACHE_ATTR)

    user = None

    # Session auth (Django admin, browsable API) is already resolved upstream.
    session_user = getattr(request, 'user', None)
    if session_user is not None and getattr(session_user, 'is_authenticated', False):
        user = session_user
    else:
        from rest_framework_simplejwt.authentication import JWTAuthentication

        try:
            result = JWTAuthentication().authenticate(request)
        except Exception:
            # Invalid/expired/malformed token — let the normal auth flow answer.
            result = None
        if result is not None:
            user, _token = result

    setattr(request, _USER_CACHE_ATTR, user)
    return user

# Paths that don't require a tenant header
TENANT_EXEMPT_PATHS = [
    '/admin/',
    '/api/v1/tenant/',
    '/api/v1/platform/',
    '/api/v1/superadmin/',
    '/api/v1/certificates/verify/',
    '/api/v1/payments/webhook/',
    '/api/v1/payments/payu/callback/',
    '/api/v1/live-classes/zoom/webhook/',
    '/api/docs/',
    '/api/redoc/',
    '/static/',
    '/media/',
]

# Auth-bootstrap paths a user of a suspended tenant may still reach so the
# frontend can authenticate enough to render the suspension overlay (and the
# login view can return a clear "suspended" message). Everything else is frozen.
TENANT_SUSPENSION_BYPASS_PATHS = [
    '/api/v1/auth/login/',
    '/api/v1/auth/refresh/',
    '/api/v1/auth/logout/',
    '/api/v1/auth/profile/',
]

class TenantMiddleware(MiddlewareMixin):
    """Resolve and enforce the tenant for every API request.

    All API requests must carry a valid ``X-Tenant-ID`` header (except the
    whitelisted paths above), *and* the authenticated caller must belong to
    that tenant. Validating only that the tenant exists is not enough — the
    header is client-supplied, so without the ownership check it is a
    self-service cross-tenant access grant.
    """
    def process_request(self, request):
        # Check if this path is exempt from tenant requirement
        for path in TENANT_EXEMPT_PATHS:
            if request.path.startswith(path):
                request.tenant = None
                return None

        tenant_id = request.headers.get('X-Tenant-ID')

        if not tenant_id:
            return JsonResponse(
                {'error': 'X-Tenant-ID header is required.'},
                status=403
            )

        try:
            valid_uuid = uuid.UUID(tenant_id)
            tenant = Tenant.objects.filter(id=valid_uuid, is_active=True).first()
        except ValueError:
            return JsonResponse(
                {'error': 'Invalid Tenant ID format.'},
                status=403
            )

        if not tenant:
            return JsonResponse(
                {'error': 'Tenant not found or inactive.'},
                status=403
            )

        request.tenant = tenant

        # The header alone proves nothing: anyone can send any tenant's UUID.
        # Bind it to the caller's own account, or a logged-in user of tenant A
        # could read and write tenant B's data simply by editing one header.
        mismatch = self._tenant_mismatch(request, tenant)
        if mismatch is not None:
            return mismatch

        # A suspended or billing-frozen tenant stays active (so its public
        # config + notice still load) but is frozen: every authenticated API
        # call is rejected. Auth-bootstrap paths are allowed through so the
        # login flow can surface a clear message and the frontend can render
        # its overlay.
        blocked, message, code = tenant.access_block()
        if blocked and not self._is_suspension_bypass(request.path):
            return JsonResponse(
                {
                    'detail': message,
                    'code': code,
                },
                status=403,
            )

    @staticmethod
    def _tenant_mismatch(request, tenant):
        """403 when the caller does not belong to the tenant they asked for.

        Anonymous requests are left alone — public endpoints (registration, the
        course catalogue, landing config) legitimately have no user to check.
        Django superusers are platform operators and are tenant-less by design,
        so they are exempt; every other account is pinned to its own tenant.
        """
        user = resolve_request_user(request)
        if user is None or getattr(user, 'is_superuser', False):
            return None

        user_tenant_id = getattr(user, 'tenant_id', None)
        if user_tenant_id is None or user_tenant_id == tenant.id:
            return None

        logger.warning(
            'Tenant mismatch: user %s (tenant %s) requested tenant %s on %s',
            getattr(user, 'id', '?'),
            user_tenant_id,
            tenant.id,
            request.path,
        )
        return JsonResponse(
            {
                'detail': 'You do not have access to this tenant.',
                'code': 'tenant_mismatch',
            },
            status=403,
        )

    @staticmethod
    def _is_suspension_bypass(path):
        return any(path.startswith(p) for p in TENANT_SUSPENSION_BYPASS_PATHS)



# Auth/bootstrap endpoints a suspended user must still be able to reach so the
# frontend can authenticate, refresh tokens, verify email, and load its profile
# (which surfaces is_suspended to drive the blocking overlay).
SUSPENSION_EXEMPT_PATHS = [
    '/api/v1/auth/login/',
    '/api/v1/auth/register/',
    '/api/v1/auth/refresh/',
    '/api/v1/auth/logout/',
    '/api/v1/auth/verify-email/',
    '/api/v1/auth/resend-otp/',
    '/api/v1/auth/password/',
    '/api/v1/auth/profile/',
]


class BlockSuspendedUsersMiddleware:
    """Reject API requests from suspended accounts.

    Defense-in-depth: individual DRF views set their own permission_classes,
    which override any default permission. Enforcing suspension here guarantees
    every /api/ endpoint (except auth/bootstrap paths) rejects a suspended user,
    regardless of the view's permissions.

    Returns HTTP 403 with code 'account_suspended' (not 401) so the frontend
    keeps the session, avoids a refresh/logout loop, and shows the blocking
    overlay instead.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        if path.startswith('/api/') and not self._is_exempt(path):
            user = resolve_request_user(request)
            if user is not None and getattr(user, 'is_suspended', False):
                return JsonResponse(
                    {
                        'detail': 'Your account has been suspended by your administrator.',
                        'code': 'account_suspended',
                    },
                    status=403,
                )
        return self.get_response(request)

    @staticmethod
    def _is_exempt(path):
        return any(path.startswith(p) for p in SUSPENSION_EXEMPT_PATHS)
