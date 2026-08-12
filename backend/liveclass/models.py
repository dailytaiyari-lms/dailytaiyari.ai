"""
Live-class models.

A LiveClass is authored under a Topic (mirrors CodingProblem/Assignment/Quiz
placement). It represents a scheduled live session students can join.

Two providers are live today:

* ``gmeet``  -- the instructor pastes a Google Meet link students join through.
* ``zoom``   -- the meeting is created on the academy's own Zoom account through
  the API, each enrolled student gets a personal (registered) join link, and
  attendance is captured from Zoom webhooks + the post-class participant report.

In-house live streaming (going live from inside the portal with the creator's
own device) is planned and is surfaced as "coming soon" -- it is intentionally
not selectable yet, enforced both in the serializer and the UI.
"""
from django.db import models
from django.utils import timezone

from core.models import OrderedModel, TimeStampedModel
from exams.models import Topic, Subject, Course


class LiveClass(OrderedModel):
    PROVIDER_GMEET = 'gmeet'
    PROVIDER_ZOOM = 'zoom'
    PROVIDER_IN_HOUSE = 'in_house'
    PROVIDER_CHOICES = [
        (PROVIDER_GMEET, 'Google Meet'),
        (PROVIDER_ZOOM, 'Zoom'),
        (PROVIDER_IN_HOUSE, 'In-house Live'),
    ]
    # Providers the instructor may actually pick right now. Others are
    # "coming soon" and rejected by the authoring serializer.
    ENABLED_PROVIDERS = {PROVIDER_GMEET, PROVIDER_ZOOM}

    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('published', 'Published'),
        ('archived', 'Archived'),
    ]

    tenant = models.ForeignKey(
        'core.Tenant', on_delete=models.CASCADE, related_name='live_classes',
        help_text='Required: no live class without tenant.',
    )
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='live_classes')
    subject = models.ForeignKey(
        Subject, on_delete=models.SET_NULL, null=True, blank=True, related_name='live_classes',
    )
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name='live_classes')

    title = models.CharField(max_length=500)
    # Rich description (HTML / Markdown) shown to students before they join.
    description = models.TextField(blank=True)

    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES, default=PROVIDER_GMEET)
    # Google Meet (or other provider) join link.
    meeting_url = models.URLField(blank=True)

    # Schedule. duration is used to derive whether the class is live/ended.
    scheduled_start = models.DateTimeField(null=True, blank=True)
    duration_minutes = models.PositiveIntegerField(default=60)

    host_name = models.CharField(max_length=200, blank=True)

    # --- Zoom-specific ----------------------------------------------------
    # Numeric Zoom meeting id (kept as text: it is long and may be padded).
    zoom_meeting_id = models.CharField(max_length=64, blank=True, default='', db_index=True)
    # UUID of the *occurrence*, sent by webhooks and needed by the report API
    # for recurring/restarted meetings. Updated whenever a meeting starts.
    zoom_meeting_uuid = models.CharField(max_length=128, blank=True, default='')
    # Host-only launch link. Never exposed to students.
    zoom_start_url = models.TextField(blank=True, default='')
    zoom_passcode = models.CharField(max_length=64, blank=True, default='')
    # Whether this meeting was created with registration on (each student then
    # gets a personal join link and attendance maps exactly to a student).
    zoom_registration_enabled = models.BooleanField(default=False)
    # Actual occurrence window reported by Zoom, used for attendance maths.
    zoom_started_at = models.DateTimeField(null=True, blank=True)
    zoom_ended_at = models.DateTimeField(null=True, blank=True)
    # Last time attendance was reconciled against Zoom's participant report.
    attendance_synced_at = models.DateTimeField(null=True, blank=True)
    attendance_sync_error = models.TextField(blank=True, default='')

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')

    class Meta:
        verbose_name = 'Live Class'
        verbose_name_plural = 'Live Classes'
        ordering = ['order', '-created_at']
        indexes = [
            models.Index(fields=['topic', 'status']),
            models.Index(fields=['course', 'status']),
        ]

    def __str__(self):
        return self.title

    @property
    def is_published(self):
        return self.status == 'published'

    @property
    def scheduled_end(self):
        if not self.scheduled_start:
            return None
        return self.scheduled_start + timezone.timedelta(minutes=self.duration_minutes or 0)

    @property
    def live_status(self):
        """Derived lifecycle state: 'upcoming', 'live', or 'ended'.

        Falls back to 'upcoming' when no start time has been set yet.
        """
        start = self.scheduled_start
        if not start:
            return 'upcoming'
        now = timezone.now()
        if now < start:
            return 'upcoming'
        if now <= self.scheduled_end:
            return 'live'
        return 'ended'

    @property
    def is_zoom(self):
        return self.provider == self.PROVIDER_ZOOM

    @property
    def zoom_linked(self):
        """True when this class is backed by a real Zoom meeting."""
        return bool(self.is_zoom and self.zoom_meeting_id)

    @property
    def supports_attendance(self):
        """Whether an attendance report can be produced for this class."""
        return self.zoom_linked


class LiveClassRegistrant(TimeStampedModel):
    """A student registered with Zoom for one live class.

    Registration is what makes attendance exact: Zoom hands back a personal
    ``join_url`` per registrant and echoes the ``registrant_id`` in participant
    events/reports, so a participant maps to exactly one student instead of
    being guessed from a free-text display name.
    """

    live_class = models.ForeignKey(
        LiveClass, on_delete=models.CASCADE, related_name='registrants'
    )
    student = models.ForeignKey(
        'users.StudentProfile', on_delete=models.CASCADE, related_name='live_class_registrations'
    )
    # Email actually sent to Zoom (kept even if the user later changes theirs,
    # because Zoom's report will echo the original).
    email = models.EmailField()
    zoom_registrant_id = models.CharField(max_length=128, blank=True, default='', db_index=True)
    # Personal join link issued by Zoom for this student.
    join_url = models.TextField(blank=True, default='')

    class Meta:
        verbose_name = 'Live Class Registrant'
        verbose_name_plural = 'Live Class Registrants'
        constraints = [
            models.UniqueConstraint(
                fields=['live_class', 'student'], name='uniq_liveclass_student_registrant'
            ),
        ]
        indexes = [models.Index(fields=['live_class', 'email'])]

    def __str__(self):
        return f'{self.email} → {self.live_class.title}'


class LiveClassAttendance(TimeStampedModel):
    """One person's presence in one live class.

    Rows are created from three sources and reconciled onto the same record:

    * ``portal``  — the student clicked "Join" inside DailyTaiyari (works for
      Google Meet too, and is the only signal available on a free Zoom plan).
    * ``webhook`` — Zoom ``participant_joined`` / ``participant_left`` events,
      giving live in-class presence.
    * ``report``  — the authoritative post-class Zoom participant report, which
      overwrites the computed duration once available.

    ``student`` is null for guests Zoom saw but we could not map to an enrolled
    student; those are still shown to the admin so nothing is silently dropped.
    """

    SOURCE_PORTAL = 'portal'
    SOURCE_WEBHOOK = 'webhook'
    SOURCE_REPORT = 'report'
    SOURCE_MANUAL = 'manual'
    SOURCE_CHOICES = [
        (SOURCE_PORTAL, 'Portal join'),
        (SOURCE_WEBHOOK, 'Zoom webhook'),
        (SOURCE_REPORT, 'Zoom report'),
        (SOURCE_MANUAL, 'Marked by admin'),
    ]

    STATUS_PRESENT = 'present'
    STATUS_PARTIAL = 'partial'
    STATUS_ABSENT = 'absent'
    STATUS_CHOICES = [
        (STATUS_PRESENT, 'Present'),
        (STATUS_PARTIAL, 'Partial'),
        (STATUS_ABSENT, 'Absent'),
    ]

    live_class = models.ForeignKey(
        LiveClass, on_delete=models.CASCADE, related_name='attendance'
    )
    student = models.ForeignKey(
        'users.StudentProfile', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='live_class_attendance',
    )

    # What Zoom (or the portal) knew about this participant.
    display_name = models.CharField(max_length=255, blank=True, default='')
    email = models.EmailField(blank=True, default='')
    # Zoom's per-session participant identity, used to de-duplicate rejoins.
    zoom_participant_uuid = models.CharField(max_length=128, blank=True, default='')
    zoom_registrant_id = models.CharField(max_length=128, blank=True, default='')

    first_joined_at = models.DateTimeField(null=True, blank=True)
    last_left_at = models.DateTimeField(null=True, blank=True)
    # Total time in the meeting across rejoins.
    duration_minutes = models.PositiveIntegerField(default=0)
    # How many separate times they entered the meeting.
    join_count = models.PositiveIntegerField(default=0)
    # True between a join and its matching leave event (drives the live view).
    is_currently_in_call = models.BooleanField(default=False)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ABSENT)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default=SOURCE_PORTAL)
    # Set when an admin overrides the computed status; sync then leaves it alone.
    is_manual_override = models.BooleanField(default=False)
    notes = models.CharField(max_length=500, blank=True, default='')

    class Meta:
        verbose_name = 'Live Class Attendance'
        verbose_name_plural = 'Live Class Attendance'
        ordering = ['-duration_minutes', 'display_name']
        constraints = [
            # One row per student per class. Guest rows (student=NULL) are not
            # covered by this and are de-duplicated on the Zoom identity instead.
            models.UniqueConstraint(
                fields=['live_class', 'student'],
                condition=models.Q(student__isnull=False),
                name='uniq_liveclass_student_attendance',
            ),
        ]
        indexes = [
            models.Index(fields=['live_class', 'status']),
            models.Index(fields=['live_class', 'email']),
        ]

    def __str__(self):
        who = self.student_id or self.email or self.display_name
        return f'{who} @ {self.live_class_id}'

    @property
    def attendance_percent(self):
        """Share of the scheduled class this person was present for (0-100)."""
        planned = self.live_class.duration_minutes or 0
        if not planned:
            return 0
        return min(int(round(self.duration_minutes * 100 / planned)), 100)

    def recompute_status(self, threshold_percent=60):
        """Derive present/partial/absent from the recorded duration.

        Respects an admin's manual override.
        """
        if self.is_manual_override:
            return self.status
        if self.duration_minutes <= 0:
            self.status = self.STATUS_ABSENT
        elif self.attendance_percent >= threshold_percent:
            self.status = self.STATUS_PRESENT
        else:
            self.status = self.STATUS_PARTIAL
        return self.status
