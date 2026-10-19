from rest_framework import viewsets
from rest_framework.exceptions import PermissionDenied

class TenantAwareViewSet(viewsets.ModelViewSet):
    """
    A base viewset for multi-tenant applications.
    Ensures that queries are filtered by request.tenant and
    new objects have the tenant automatically assigned.
    """
    
    def get_queryset(self):
        """
        Filter the queryset to only return items belonging to the current tenant.
        """
        queryset = super().get_queryset()
        
        # If no tenant is available in the request, return empty queryset to prevent data leaks
        if not hasattr(self.request, 'tenant') or not self.request.tenant:
            return queryset.none()
            
        return queryset.filter(tenant=self.request.tenant)

    def perform_create(self, serializer):
        """
        Automatically save the tenant to the newly created instance.
        """
        if not hasattr(self.request, 'tenant') or not self.request.tenant:
            raise PermissionDenied("A valid Tenant is required to perform this action.")
            
        serializer.save(tenant=self.request.tenant)

class TenantAwareReadOnlyViewSet(viewsets.ReadOnlyModelViewSet):
    """
    A base viewset for multi-tenant applications (Read Only).
    Ensures that queries are filtered by request.tenant.
    """
    
    def get_queryset(self):
        """
        Filter the queryset to only return items belonging to the current tenant.
        """
        queryset = super().get_queryset()
        
        # If no tenant is available in the request, return empty queryset to prevent data leaks
        if not hasattr(self.request, 'tenant') or not self.request.tenant:
            return queryset.none()
            
        return queryset.filter(tenant=self.request.tenant)

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions, status
from .models import Tenant

class TenantDetailView(APIView):
    """
    Unauthenticated endpoint for the frontend to fetch Tenant branding details.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request, pk=None):
        if not pk:
            return Response({"error": "Tenant ID is required"}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            tenant = Tenant.objects.get(id=pk, is_active=True)
            _frozen, _freeze_msg, _freeze_code = tenant.access_block()
            return Response({
                "id": str(tenant.id),
                "name": tenant.name,
                "tagline": tenant.tagline,
                "subdomain": tenant.subdomain,
                "logo": request.build_absolute_uri(tenant.logo.url) if tenant.logo else None,
                "favicon": request.build_absolute_uri(tenant.favicon.url) if tenant.favicon else None,
                "theme": tenant.theme or Tenant.DEFAULT_THEME,
                "show_name": tenant.show_name,
                "auth_panel": tenant.auth_panel or {},
                "features": tenant.get_features(),
                "feature_labels": tenant.get_feature_labels(),
                "is_suspended": tenant.is_suspended,
                "suspension_message": tenant.suspension_message,
                "is_frozen": _frozen,
                "freeze_message": _freeze_msg,
                "freeze_code": _freeze_code,
                "request_enrollment_free": tenant.request_enrollment_free,
                "request_enrollment_paid": tenant.request_enrollment_paid,
                "payment_gateway": _public_payment_gateway(tenant),
                "promo_banner": _public_promo_banner(tenant),
                "announcements": _public_announcements(tenant),
            })
        except Tenant.DoesNotExist:
            return Response({"error": "Tenant not found"}, status=status.HTTP_404_NOT_FOUND)


def _public_promo_banner(tenant):
    """The current live promo banner for this tenant, or None."""
    from marketing.models import PromoBanner
    from marketing.serializers import PublicPromoBannerSerializer

    banner = (
        PromoBanner.objects.filter(tenant=tenant, is_active=True)
        .select_related('coupon')
        .order_by('-updated_at')
        .first()
    )
    if banner is None or not banner.is_live():
        return None
    return PublicPromoBannerSerializer(banner).data


def _public_announcements(tenant):
    """Live platform announcements (global + tenant-scoped) for the app banner."""
    from .models import PlatformAnnouncement

    live = PlatformAnnouncement.live_for_tenant(tenant)
    return [
        {
            'id': str(a.id),
            'title': a.title,
            'body': a.body,
            'level': a.level,
            'scope': 'global' if a.target_tenant_id is None else 'tenant',
            'starts_at': a.starts_at.isoformat() if a.starts_at else None,
            'ends_at': a.ends_at.isoformat() if a.ends_at else None,
        }
        for a in live
    ]


def _public_payment_gateway(tenant):
    """Safe, secret-free payment gateway summary for the public tenant config."""
    gateway = tenant.active_payment_gateway
    if not gateway or not gateway.is_configured:
        return None
    return {
        "provider": gateway.provider,
        "is_test_mode": gateway.is_test_mode,
    }



# ---------------------------------------------------------------------------
# Platform-owned (non-tenant) public endpoints — marketing site leads.
# ---------------------------------------------------------------------------
import logging

from rest_framework import generics
from rest_framework.throttling import ScopedRateThrottle

from .models import DemoBooking, ContactMessage, JobApplication
from .serializers import (
    DemoBookingSerializer,
    ContactMessageSerializer,
    JobApplicationSerializer,
)
from . import emails

logger = logging.getLogger(__name__)


class DemoBookingCreateView(generics.CreateAPIView):
    """Public 'Book a Demo' endpoint. Not tenant-scoped."""
    queryset = DemoBooking.objects.all()
    serializer_class = DemoBookingSerializer
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'platform_lead'

    def perform_create(self, serializer):
        booking = serializer.save()
        try:
            emails.send_demo_booking_notification(booking)
        except Exception:  # noqa: BLE001 - never fail the write on a mail error
            logger.exception('Failed to send demo booking notification email')


class ContactMessageCreateView(generics.CreateAPIView):
    """Public 'Talk to us' endpoint. Not tenant-scoped."""
    queryset = ContactMessage.objects.all()
    serializer_class = ContactMessageSerializer
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'platform_lead'

    def perform_create(self, serializer):
        contact = serializer.save()
        try:
            emails.send_contact_message_notification(contact)
        except Exception:  # noqa: BLE001 - never fail the write on a mail error
            logger.exception('Failed to send contact message notification email')


class JobApplicationCreateView(generics.CreateAPIView):
    """Public careers 'Apply' endpoint. Not tenant-scoped."""
    queryset = JobApplication.objects.all()
    serializer_class = JobApplicationSerializer
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'platform_lead'

    def perform_create(self, serializer):
        application = serializer.save()
        try:
            emails.send_job_application_notification(application)
        except Exception:  # noqa: BLE001 - never fail the write on a mail error
            logger.exception('Failed to send job application notification email')
