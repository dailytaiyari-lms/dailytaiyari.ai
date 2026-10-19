import logging

from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import IsTenantAdmin

from . import birthdays, services
from .email_templates import (
    DEFAULT_EMAIL_TEMPLATES,
    TEMPLATE_META,
    TEMPLATE_TYPES,
    get_template_parts,
    render_email,
)
from .models import Announcement, Notification, TenantEmailTemplate
from .serializers import (
    AnnouncementCreateSerializer,
    AnnouncementSerializer,
    EmailTemplateUpdateSerializer,
    NotificationSerializer,
)

logger = logging.getLogger(__name__)


class NotificationPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


def _unread_count(user):
    return Notification.objects.filter(recipient=user, is_read=False).count()


def _trigger_birthday_sweep(request):
    """Fire the tenant's daily birthday sweep the first time it's seen today.

    Hung off the endpoints the app already polls so greetings are delivered on
    the day even with no cron/beat scheduler configured. Cheap: a per-process
    memo means at most one DB round-trip per worker per tenant per day, and it
    never raises.
    """
    tenant = getattr(request, 'tenant', None)
    if tenant is None:
        return
    try:
        birthdays.maybe_run_for_tenant(tenant)
    except Exception:  # noqa: BLE001 - never break a notification poll
        logger.exception('Birthday sweep trigger failed')


class NotificationListView(generics.ListAPIView):
    """Current user's notifications (newest first) + unread count."""
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = NotificationPagination

    def get_queryset(self):
        qs = Notification.objects.filter(recipient=self.request.user)
        if self.request.query_params.get('unread') in ('1', 'true', 'True'):
            qs = qs.filter(is_read=False)
        type_filter = self.request.query_params.get('type')
        if type_filter:
            qs = qs.filter(type__in=[t for t in type_filter.split(',') if t])
        return qs

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        if isinstance(response.data, dict):
            response.data['unread_count'] = _unread_count(request.user)
        return response


class UnreadCountView(APIView):
    """Lightweight endpoint the bell polls for the badge count."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        _trigger_birthday_sweep(request)
        return Response({'unread_count': _unread_count(request.user)})


class BirthdayCelebrationView(APIView):
    """The pending birthday celebration for the current user, if any.

    Returns the unread birthday notification created today so the frontend can
    play its full-screen confetti moment exactly once. Dismissing it is just
    marking the notification read through the normal endpoint.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        _trigger_birthday_sweep(request)
        notification = Notification.objects.filter(
            recipient=request.user,
            type=Notification.TYPE_BIRTHDAY,
            is_read=False,
            created_at__date=timezone.localdate(),
        ).first()
        if notification is None:
            return Response({'celebration': None})
        data = notification.data or {}
        return Response({
            'celebration': {
                'id': str(notification.id),
                'title': notification.title,
                'body': notification.body,
                'link': notification.link,
                'first_name': data.get('first_name', ''),
                'age': data.get('age'),
                'tenant_name': data.get('tenant_name', ''),
                'is_past_student': bool(data.get('is_past_student')),
            },
        })


class MarkReadView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        updated = Notification.objects.filter(
            id=pk, recipient=request.user, is_read=False,
        ).update(is_read=True, read_at=timezone.now())
        return Response({'updated': updated, 'unread_count': _unread_count(request.user)})


class MarkAllReadView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        updated = Notification.objects.filter(
            recipient=request.user, is_read=False,
        ).update(is_read=True, read_at=timezone.now())
        return Response({'updated': updated, 'unread_count': 0})


# ---------------------------------------------------------------------------
# Admin: announcements
# ---------------------------------------------------------------------------
class AnnouncementListCreateView(generics.ListCreateAPIView):
    """Tenant admins list past announcements and broadcast new ones."""
    permission_classes = [permissions.IsAuthenticated, IsTenantAdmin]
    pagination_class = NotificationPagination

    def get_serializer_class(self):
        return AnnouncementCreateSerializer if self.request.method == 'POST' else AnnouncementSerializer

    def get_queryset(self):
        return Announcement.objects.filter(
            tenant=self.request.tenant,
        ).prefetch_related('courses').select_related('created_by')

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        announcement = serializer.save()
        # Fan out (async when configured, inline otherwise).
        services.dispatch_announcement(announcement)
        return Response(
            AnnouncementSerializer(announcement).data,
            status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# Admin: editable email templates
# ---------------------------------------------------------------------------
def _sample_context(template_type, tenant):
    """Placeholder values used to render a live preview of a template."""
    tenant_name = getattr(tenant, 'name', '') or 'Your Institute'
    return {
        'student_name': 'Jane Doe',
        'first_name': 'Jane',
        'student_email': 'jane.doe@example.com',
        'course_name': 'Sample Course 101',
        'reason': 'Reason: Incomplete profile',
        'tenant_name': tenant_name,
        'age': '18',
        'count': '3',
        'names': '• Jane Doe\n• Arjun Mehta\n• Riya Sharma (past student)',
        'date': timezone.localdate().strftime('%d %B %Y'),
    }


def _template_payload(tenant, template_type):
    """Serialise a template's effective + default parts and its metadata."""
    subject, heading, body = get_template_parts(tenant, template_type)
    default = DEFAULT_EMAIL_TEMPLATES.get(template_type, {})
    meta = TEMPLATE_META.get(template_type, {})
    is_custom = TenantEmailTemplate.objects.filter(
        tenant=tenant, type=template_type,
    ).exists()
    prev_subject, prev_heading, prev_body_html = render_email(
        tenant, template_type, _sample_context(template_type, tenant),
    )
    return {
        'type': template_type,
        'label': meta.get('label', template_type),
        'description': meta.get('description', ''),
        'placeholders': meta.get('placeholders', []),
        'subject': subject,
        'heading': heading,
        'body': body,
        'default_subject': default.get('subject', ''),
        'default_heading': default.get('heading', ''),
        'default_body': default.get('body', ''),
        'is_custom': is_custom,
        'preview': {
            'subject': prev_subject,
            'heading': prev_heading,
            'body_html': prev_body_html,
        },
    }


class EmailTemplateListView(APIView):
    """List every templatable email with its effective + default parts."""
    permission_classes = [permissions.IsAuthenticated, IsTenantAdmin]

    def get(self, request):
        tenant = request.tenant
        return Response({
            'templates': [_template_payload(tenant, t) for t in TEMPLATE_TYPES],
        })


class EmailTemplateDetailView(APIView):
    """Retrieve, upsert (PUT) or reset (DELETE) a single email template."""
    permission_classes = [permissions.IsAuthenticated, IsTenantAdmin]

    def _validate_type(self, template_type):
        return template_type in TEMPLATE_TYPES

    def get(self, request, template_type):
        if not self._validate_type(template_type):
            return Response({'detail': 'Unknown template type.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(_template_payload(request.tenant, template_type))

    def put(self, request, template_type):
        if not self._validate_type(template_type):
            return Response({'detail': 'Unknown template type.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = EmailTemplateUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        tenant = request.tenant

        subject = (data.get('subject') or '').strip()
        heading = (data.get('heading') or '').strip()
        body = data.get('body') or ''

        # If every part is blank the override is meaningless — reset instead.
        if not subject and not heading and not body.strip():
            TenantEmailTemplate.objects.filter(tenant=tenant, type=template_type).delete()
        else:
            TenantEmailTemplate.objects.update_or_create(
                tenant=tenant, type=template_type,
                defaults={'subject': subject, 'heading': heading, 'body': body},
            )
        return Response(_template_payload(tenant, template_type))

    def delete(self, request, template_type):
        if not self._validate_type(template_type):
            return Response({'detail': 'Unknown template type.'}, status=status.HTTP_404_NOT_FOUND)
        TenantEmailTemplate.objects.filter(
            tenant=request.tenant, type=template_type,
        ).delete()
        return Response(_template_payload(request.tenant, template_type))
