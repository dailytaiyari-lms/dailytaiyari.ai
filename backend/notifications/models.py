"""Notification & Announcement models.

- ``Notification`` is one row per recipient per event. It powers the in-app
  bell/badge (unread count) and the notifications page. Rows are tenant-scoped
  and always belong to exactly one user.
- ``Announcement`` is an admin-authored broadcast. Creating one fans out into
  many ``Notification`` rows (and optionally emails) via the service layer.
"""
import uuid

from django.conf import settings
from django.db import models


class Notification(models.Model):
    """A single in-app notification delivered to one user."""

    # Stable type identifiers. The frontend maps these to an icon/accent.
    TYPE_ENROLLMENT_REQUEST = 'enrollment_request'
    TYPE_ENROLLMENT_APPROVED = 'enrollment_approved'
    TYPE_ENROLLMENT_REJECTED = 'enrollment_rejected'
    TYPE_ANNOUNCEMENT = 'announcement'
    TYPE_AI_ALLOWANCE = 'ai_allowance'
    TYPE_ACCOUNT_CREATED = 'account_created'
    TYPE_COURSE_ASSIGNED = 'course_assigned'
    TYPE_CHOICES = [
        (TYPE_ENROLLMENT_REQUEST, 'Enrollment request'),
        (TYPE_ENROLLMENT_APPROVED, 'Enrollment approved'),
        (TYPE_ENROLLMENT_REJECTED, 'Enrollment rejected'),
        (TYPE_ANNOUNCEMENT, 'Announcement'),
        (TYPE_AI_ALLOWANCE, 'AI allowance'),
        (TYPE_ACCOUNT_CREATED, 'Account created'),
        (TYPE_COURSE_ASSIGNED, 'Course assigned'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        'core.Tenant', on_delete=models.CASCADE, related_name='notifications',
        null=True, blank=True,
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='notifications',
    )
    type = models.CharField(max_length=40, choices=TYPE_CHOICES)
    title = models.CharField(max_length=255)
    body = models.TextField(blank=True, default='')
    # Frontend-relative link the notification deep-links to when clicked
    # (e.g. '/admin-dashboard?tab=enrollments' or '/profile').
    link = models.CharField(max_length=500, blank=True, default='')
    # Arbitrary structured payload (enrollment_id, course_id, announcement_id...).
    data = models.JSONField(default=dict, blank=True)

    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            # Powers the badge count + the "unread first" listing efficiently.
            models.Index(fields=['recipient', 'is_read', '-created_at']),
        ]

    def __str__(self):
        return f'{self.get_type_display()} → {self.recipient_id}'


class Announcement(models.Model):
    """An admin-authored broadcast to everyone or to selected courses."""

    AUDIENCE_ALL = 'all'
    AUDIENCE_COURSES = 'courses'
    AUDIENCE_CHOICES = [
        (AUDIENCE_ALL, 'Everyone'),
        (AUDIENCE_COURSES, 'Selected courses'),
    ]

    STATUS_SENDING = 'sending'
    STATUS_SENT = 'sent'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_SENDING, 'Sending'),
        (STATUS_SENT, 'Sent'),
        (STATUS_FAILED, 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        'core.Tenant', on_delete=models.CASCADE, related_name='tenant_announcements',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='authored_announcements',
    )
    title = models.CharField(max_length=255)
    body = models.TextField()

    audience = models.CharField(max_length=20, choices=AUDIENCE_CHOICES, default=AUDIENCE_ALL)
    # Only meaningful when audience == 'courses'.
    courses = models.ManyToManyField('exams.Course', blank=True, related_name='announcements')

    send_email = models.BooleanField(default=True)
    send_in_app = models.BooleanField(default=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_SENDING)
    recipients_count = models.PositiveIntegerField(default=0)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.title} ({self.tenant_id})'


class TenantEmailTemplate(models.Model):
    """A tenant's override of a lifecycle email's subject / heading / body.

    Only the templatable enrollment emails are stored here (announcement
    content is authored per-send). A missing row — or any blank part — means
    "use the packaged default" (see ``notifications.email_templates``). Bodies
    are plain text with ``{placeholder}`` tokens.
    """

    TYPE_CHOICES = [
        ('enrollment_request', 'New enrollment request (to admins)'),
        ('enrollment_approved', 'Enrollment approved (to student)'),
        ('enrollment_rejected', 'Enrollment declined (to student)'),
        ('account_created', 'Account created by admin (to student)'),
        ('course_assigned', 'Course assigned by admin (to student)'),
        ('credentials_reset', 'Password reset by admin (to student)'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        'core.Tenant', on_delete=models.CASCADE, related_name='email_templates',
    )
    type = models.CharField(max_length=40, choices=TYPE_CHOICES)
    subject = models.CharField(max_length=500, blank=True, default='')
    heading = models.CharField(max_length=255, blank=True, default='')
    body = models.TextField(blank=True, default='')

    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('tenant', 'type')]
        ordering = ['type']

    def __str__(self):
        return f'{self.get_type_display()} ({self.tenant_id})'
