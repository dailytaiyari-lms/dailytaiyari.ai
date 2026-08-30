"""
Job Portal models.

A tenant admin authors a ``Job`` that is either:

* ``internal`` – the full hiring pipeline is managed inside the platform.
  Students apply with a resume (PDF) + cover letter and the admin moves each
  application through stages (applied → under review → shortlisted → interview
  → offer → hired/rejected), leaving notes. Every change is recorded as an
  ``ApplicationEvent`` so the admin has a complete audit trail.

* ``external`` – the job lives on an external site (``external_url``). When a
  student clicks "Apply" we record the click as an *applied externally*
  application and tell them to finish the process on the external site.
"""
from django.db import models
from django.utils import timezone

from core.models import TimeStampedModel


class Job(TimeStampedModel):
    JOB_TYPES = [
        ('internal', 'Internal Hiring'),
        ('external', 'External Posting'),
    ]
    CATEGORY_CHOICES = [
        ('job', 'Job'),
        ('internship', 'Internship'),
    ]
    EMPLOYMENT_TYPES = [
        ('full_time', 'Full-time'),
        ('part_time', 'Part-time'),
        ('internship', 'Internship'),
        ('contract', 'Contract'),
        ('temporary', 'Temporary'),
    ]
    WORK_MODES = [
        ('onsite', 'On-site'),
        ('remote', 'Remote'),
        ('hybrid', 'Hybrid'),
    ]
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('published', 'Published'),
        ('closed', 'Closed'),
        ('archived', 'Archived'),
    ]

    # Number of distinct student "this is closed" reports that auto-archives an
    # opening so only genuinely active jobs stay on the board.
    REPORT_ARCHIVE_THRESHOLD = 3

    # Required tenant (overrides the nullable FK on TimeStampedModel): no job
    # exists outside a tenant.
    tenant = models.ForeignKey(
        'core.Tenant', on_delete=models.CASCADE, related_name='jobs',
        help_text='Required: every job belongs to a tenant.',
    )

    title = models.CharField(max_length=255)
    job_type = models.CharField(max_length=20, choices=JOB_TYPES, default='internal')
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='job')

    department = models.CharField(max_length=150, blank=True)
    location = models.CharField(max_length=200, blank=True)
    work_mode = models.CharField(max_length=20, choices=WORK_MODES, default='onsite')
    employment_type = models.CharField(max_length=20, choices=EMPLOYMENT_TYPES, default='full_time')

    experience_min = models.PositiveSmallIntegerField(null=True, blank=True)
    experience_max = models.PositiveSmallIntegerField(null=True, blank=True)

    salary_min = models.PositiveIntegerField(null=True, blank=True)
    salary_max = models.PositiveIntegerField(null=True, blank=True)
    salary_currency = models.CharField(max_length=10, default='INR', blank=True)
    salary_period = models.CharField(max_length=20, default='year', blank=True)

    # Rich HTML description + requirements (same editor used across the app).
    description = models.TextField(blank=True)
    requirements = models.TextField(blank=True)

    # External postings link out to another site.
    external_url = models.URLField(max_length=1000, blank=True)

    openings = models.PositiveIntegerField(default=1)
    deadline = models.DateTimeField(null=True, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')

    created_by = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='created_jobs',
    )

    # Courses an admin recommends to help a student upskill for this opening.
    # Surfaced as course tiles on the job/internship detail page.
    related_courses = models.ManyToManyField(
        'exams.Course', related_name='related_jobs', blank=True,
    )

    views_count = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'Job'
        verbose_name_plural = 'Jobs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant', 'status', '-created_at']),
            models.Index(fields=['tenant', 'job_type']),
            models.Index(fields=['tenant', 'category']),
        ]

    def __str__(self):
        return self.title

    @property
    def is_external(self):
        return self.job_type == 'external'

    @property
    def is_open(self):
        """Whether the job currently accepts applications."""
        if self.status != 'published':
            return False
        if self.deadline and timezone.now() > self.deadline:
            return False
        return True


class JobApplication(TimeStampedModel):
    """A student's application to a job.

    For internal jobs ``stage`` walks the hiring pipeline. For external jobs the
    application is a lightweight record that the student clicked through
    (``is_external=True``, ``stage='applied_external'``).
    """

    # Active pipeline stages, in board order, for internal jobs.
    PIPELINE_STAGES = [
        'applied', 'under_review', 'shortlisted', 'interview', 'offer', 'hired',
    ]

    STAGE_CHOICES = [
        ('applied', 'Applied'),
        ('under_review', 'Under Review'),
        ('shortlisted', 'Shortlisted'),
        ('interview', 'Interview'),
        ('offer', 'Offer'),
        ('hired', 'Hired'),
        ('rejected', 'Rejected'),
        ('withdrawn', 'Withdrawn'),
        ('applied_external', 'Applied Externally'),
    ]

    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name='applications')
    applicant = models.ForeignKey(
        'users.StudentProfile', on_delete=models.CASCADE, related_name='job_applications',
    )

    # Contact snapshot captured at apply time.
    full_name = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)

    resume = models.FileField(upload_to='jobs/resumes/', null=True, blank=True)
    cover_letter = models.TextField(blank=True)
    portfolio_url = models.URLField(max_length=1000, blank=True)
    linkedin_url = models.URLField(max_length=1000, blank=True)

    stage = models.CharField(max_length=30, choices=STAGE_CHOICES, default='applied')
    is_external = models.BooleanField(default=False)
    applied_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = 'Job Application'
        verbose_name_plural = 'Job Applications'
        unique_together = ['job', 'applicant']
        ordering = ['-applied_at']
        indexes = [
            models.Index(fields=['job', 'stage']),
        ]

    def __str__(self):
        return f'{self.full_name or self.applicant_id} → {self.job.title}'

    @property
    def is_active(self):
        return self.stage not in ('rejected', 'withdrawn', 'applied_external')


class JobReport(TimeStampedModel):
    """A student's report that an opening is no longer active.

    Once ``Job.REPORT_ARCHIVE_THRESHOLD`` distinct students report the same job,
    it is auto-archived so only genuinely active openings remain on the board.
    """

    REASON_CHOICES = [
        ('closed', 'Position closed / filled'),
        ('expired', 'Link expired or unavailable'),
        ('other', 'Other'),
    ]

    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name='reports')
    reporter = models.ForeignKey(
        'users.StudentProfile', on_delete=models.CASCADE, related_name='job_reports',
    )
    reason = models.CharField(max_length=20, choices=REASON_CHOICES, default='closed')
    note = models.TextField(blank=True)

    class Meta:
        verbose_name = 'Job Report'
        verbose_name_plural = 'Job Reports'
        unique_together = ['job', 'reporter']
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['job']),
        ]

    def __str__(self):
        return f'report on {self.job_id} by {self.reporter_id}'


class ApplicationEvent(TimeStampedModel):
    """Audit trail entry for an application: a stage change or an admin note."""

    EVENT_TYPES = [
        ('applied', 'Applied'),
        ('stage_change', 'Stage Change'),
        ('note', 'Note'),
    ]

    application = models.ForeignKey(
        JobApplication, on_delete=models.CASCADE, related_name='events',
    )
    event_type = models.CharField(max_length=20, choices=EVENT_TYPES, default='note')
    from_stage = models.CharField(max_length=30, blank=True)
    to_stage = models.CharField(max_length=30, blank=True)
    note = models.TextField(blank=True)
    created_by = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='job_application_events',
    )

    class Meta:
        verbose_name = 'Application Event'
        verbose_name_plural = 'Application Events'
        ordering = ['created_at']

    def __str__(self):
        return f'{self.event_type} on {self.application_id}'
