"""Notifications & announcements API URLs (mounted at /api/v1/notifications/)."""
from django.urls import path

from .views import (
    AnnouncementListCreateView,
    BirthdayCelebrationView,
    EmailTemplateDetailView,
    EmailTemplateListView,
    MarkAllReadView,
    MarkReadView,
    NotificationListView,
    UnreadCountView,
)

urlpatterns = [
    # --- Student/admin: their own notifications ---
    path('', NotificationListView.as_view(), name='notification-list'),
    path('unread-count/', UnreadCountView.as_view(), name='notification-unread-count'),
    path('birthday/', BirthdayCelebrationView.as_view(), name='notification-birthday'),
    path('mark-all-read/', MarkAllReadView.as_view(), name='notification-mark-all-read'),
    path('<uuid:pk>/read/', MarkReadView.as_view(), name='notification-mark-read'),

    # --- Tenant-admin: announcements ---
    path('announcements/', AnnouncementListCreateView.as_view(), name='announcement-list-create'),

    # --- Tenant-admin: editable email templates ---
    path('email-templates/', EmailTemplateListView.as_view(), name='email-template-list'),
    path('email-templates/<str:template_type>/', EmailTemplateDetailView.as_view(), name='email-template-detail'),
]
