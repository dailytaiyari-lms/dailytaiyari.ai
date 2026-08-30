"""
Hackathon models.

A tenant admin authors a ``Hackathon`` — a standalone, fully self-contained
competition that lives outside the course tree and gets its own dedicated,
full-page experience on the student app.

Shape of the domain
-------------------
``Hackathon``
    The event itself: branding (thumbnail/banner), rich description, timeline
    (registration window + event window), prizes, eligibility and the toggles
    an admin controls (e.g. whether the public registration count is shown).

``HackathonStage``
    An ordered round. Every stage is one of four kinds:

    * ``quiz``       – auto-graded MCQ / multi-select / numerical / subjective
                       items authored inline (``HackathonStageItem``).
    * ``coding``     – inline coding items judged against test cases by the
                       shared Piston runner (``coding.services``).
    * ``lab``        – an existing ``notebooks.Notebook`` linked into the round;
                       the notebook app owns authoring + grading, we only read
                       the student's best score back.
    * ``submission`` – free-form deliverables (zip / pdf / video / links)
                       reviewed manually by the admin.

    Progression between stages is controlled by ``qualification_mode``:
    ``cutoff`` (score >= cutoff), ``top_n`` (highest N scorers) or ``manual``
    (the admin ticks the qualifiers). Whoever is not qualified sees a clear
    "you did not advance" state instead of the next round.

``HackathonRegistration``
    A student's entry into the event. Registration requires login; browsing
    does not.

``StageParticipation``
    One row per (registration, stage). It is the single source of truth for a
    participant's state in a round: attempt window, score, qualification
    decision and reviewer feedback.

Everything is tenant-scoped and every write path is idempotent where a student
could reasonably retry.
"""
import uuid

from django.db import models
from django.utils import timezone

from core.models import OrderedModel, TimeStampedModel


def default_submission_types():
    return ['pdf', 'zip', 'mp4', 'png', 'jpg']


class Hackathon(TimeStampedModel):
    """A standalone competition with its own dedicated public page."""

    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('published', 'Published'),
        ('completed', 'Completed'),
        ('archived', 'Archived'),
    ]
    MODE_CHOICES = [
        ('online', 'Online'),
        ('offline', 'On-site'),
        ('hybrid', 'Hybrid'),
    ]
    DIFFICULTY_CHOICES = [
        ('beginner', 'Beginner'),
        ('intermediate', 'Intermediate'),
        ('advanced', 'Advanced'),
        ('all', 'All levels'),
    ]

    # Required tenant (overrides the nullable FK on TimeStampedModel).
    tenant = models.ForeignKey(
        'core.Tenant', on_delete=models.CASCADE, related_name='hackathons',
        help_text='Required: every hackathon belongs to a tenant.',
    )

    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=280, blank=True, db_index=True)
    tagline = models.CharField(max_length=300, blank=True)

    thumbnail = models.ImageField(upload_to='hackathons/thumbnails/', blank=True, null=True)
    banner = models.ImageField(upload_to='hackathons/banners/', blank=True, null=True)
    theme_color = models.CharField(max_length=20, blank=True, default='')

    # Rich HTML authored in the admin editor.
    description = models.TextField(blank=True)
    rules = models.TextField(blank=True)
    prizes_description = models.TextField(blank=True)
    eligibility = models.TextField(blank=True)
    # [{"question": str, "answer": str}]
    faqs = models.JSONField(default=list, blank=True)
    # ["AI/ML", "Web", ...]
    tags = models.JSONField(default=list, blank=True)

    mode = models.CharField(max_length=20, choices=MODE_CHOICES, default='online')
    location = models.CharField(max_length=255, blank=True)
    difficulty = models.CharField(max_length=20, choices=DIFFICULTY_CHOICES, default='all')

    organizer_name = models.CharField(max_length=255, blank=True)
    contact_email = models.EmailField(blank=True)

    prize_pool = models.PositiveIntegerField(null=True, blank=True)
    prize_currency = models.CharField(max_length=10, default='INR', blank=True)

    # Timeline. `registration_deadline` is the hard cut-off for new entries.
    registration_opens_at = models.DateTimeField(null=True, blank=True)
    registration_deadline = models.DateTimeField(null=True, blank=True)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)

    max_participants = models.PositiveIntegerField(
        null=True, blank=True, help_text='Leave blank for unlimited seats.',
    )

    # Admin toggles surfaced on the public page.
    show_registration_count = models.BooleanField(
        default=True, help_text='Show the live registered-participant count publicly.',
    )
    show_leaderboard = models.BooleanField(
        default=True, help_text='Let participants see the stage leaderboard.',
    )
    email_notifications = models.BooleanField(
        default=True, help_text='Email registered participants on key events.',
    )

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')

    results_announced = models.BooleanField(default=False)
    results_announced_at = models.DateTimeField(null=True, blank=True)

    # Courses an admin recommends to help a student prepare.
    related_courses = models.ManyToManyField(
        'exams.Course', related_name='related_hackathons', blank=True,
    )

    created_by = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='created_hackathons',
    )
    views_count = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'Hackathon'
        verbose_name_plural = 'Hackathons'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant', 'status', '-created_at']),
            models.Index(fields=['tenant', 'slug']),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            from django.utils.text import slugify
            base = slugify(self.title)[:240] or 'hackathon'
            self.slug = f'{base}-{uuid.uuid4().hex[:6]}'
        super().save(*args, **kwargs)

    # -- Derived state ----------------------------------------------------
    @property
    def is_published(self):
        return self.status in ('published', 'completed')

    @property
    def registration_open(self):
        """Whether new registrations are currently accepted."""
        if self.status != 'published':
            return False
        now = timezone.now()
        if self.registration_opens_at and now < self.registration_opens_at:
            return False
        if self.registration_deadline and now > self.registration_deadline:
            return False
        if self.max_participants is not None:
            if self.registrations.filter(status='registered').count() >= self.max_participants:
                return False
        return True

    @property
    def registration_state(self):
        """A single label the UI can render without re-deriving the rules."""
        if self.status == 'draft':
            return 'not_open'
        if self.status in ('completed', 'archived'):
            return 'closed'
        now = timezone.now()
        if self.registration_opens_at and now < self.registration_opens_at:
            return 'opening_soon'
        if self.registration_deadline and now > self.registration_deadline:
            return 'closed'
        if self.max_participants is not None:
            if self.registrations.filter(status='registered').count() >= self.max_participants:
                return 'full'
        return 'open'

    @property
    def has_started(self):
        return bool(self.starts_at and timezone.now() >= self.starts_at)

    @property
    def has_ended(self):
        return bool(self.ends_at and timezone.now() > self.ends_at)


class HackathonStage(OrderedModel):
    """One ordered round of a hackathon."""

    STAGE_TYPES = [
        ('quiz', 'Quiz / MCQ Round'),
        ('coding', 'Coding Round'),
        ('lab', 'Lab / Notebook Round'),
        ('submission', 'Project Submission'),
    ]
    QUALIFICATION_MODES = [
        ('manual', 'Admin picks qualifiers'),
        ('cutoff', 'Score cut-off'),
        ('top_n', 'Top N scorers'),
        ('all', 'Everyone advances'),
    ]
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('published', 'Published'),
        ('completed', 'Completed'),
    ]

    hackathon = models.ForeignKey(
        Hackathon, on_delete=models.CASCADE, related_name='stages',
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    instructions = models.TextField(blank=True)
    stage_type = models.CharField(max_length=20, choices=STAGE_TYPES, default='quiz')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')

    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)

    # Quiz / coding rounds only. 0 = untimed.
    duration_minutes = models.PositiveIntegerField(default=0)
    shuffle_items = models.BooleanField(default=False)
    max_attempts = models.PositiveIntegerField(default=1)

    # Lab rounds link an existing authored notebook rather than duplicating it.
    notebook = models.ForeignKey(
        'notebooks.Notebook', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='hackathon_stages',
    )

    # Submission rounds.
    submission_instructions = models.TextField(blank=True)
    allowed_file_types = models.JSONField(default=default_submission_types, blank=True)
    max_file_mb = models.PositiveIntegerField(default=50)
    max_files = models.PositiveIntegerField(default=3)
    require_repo_url = models.BooleanField(default=False)
    require_demo_url = models.BooleanField(default=False)
    require_video_url = models.BooleanField(default=False)
    allow_resubmission = models.BooleanField(default=True)

    # Progression.
    max_score = models.DecimalField(max_digits=8, decimal_places=2, default=100)
    qualification_mode = models.CharField(
        max_length=20, choices=QUALIFICATION_MODES, default='manual',
    )
    cutoff_score = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    top_n = models.PositiveIntegerField(null=True, blank=True)
    results_published = models.BooleanField(
        default=False,
        help_text='Once published, participants can see their result and whether they advanced.',
    )
    results_published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Hackathon Stage'
        verbose_name_plural = 'Hackathon Stages'
        ordering = ['order', 'created_at']
        indexes = [
            models.Index(fields=['hackathon', 'order']),
        ]

    def __str__(self):
        return f'{self.title} ({self.hackathon_id})'

    @property
    def is_open(self):
        """Whether the round currently accepts attempts/submissions."""
        if self.status != 'published':
            return False
        now = timezone.now()
        if self.starts_at and now < self.starts_at:
            return False
        if self.ends_at and now > self.ends_at:
            return False
        return True

    @property
    def timing_state(self):
        if self.status == 'draft':
            return 'not_open'
        if self.status == 'completed':
            return 'ended'
        now = timezone.now()
        if self.starts_at and now < self.starts_at:
            return 'upcoming'
        if self.ends_at and now > self.ends_at:
            return 'ended'
        return 'live'

    @property
    def is_auto_graded(self):
        return self.stage_type in ('quiz', 'coding', 'lab')

    def computed_max_score(self):
        """Total marks derived from the round's items, falling back to max_score."""
        if self.stage_type in ('quiz', 'coding'):
            total = self.items.aggregate(t=models.Sum('marks'))['t']
            if total:
                return total
        return self.max_score


class HackathonStageItem(OrderedModel):
    """A self-contained question authored inline in a quiz or coding round.

    Mirrors ``quiz.MockTestItem`` so the shared grading semantics (negative
    marking, Piston-judged coding, manual subjective review) behave identically
    to the rest of the platform.
    """

    ITEM_TYPES = [
        ('mcq', 'Multiple Choice (Single)'),
        ('mcq_multi', 'Multiple Choice (Multiple)'),
        ('numerical', 'Numerical'),
        ('subjective', 'Subjective'),
        ('coding', 'Coding'),
    ]

    stage = models.ForeignKey(
        HackathonStage, on_delete=models.CASCADE, related_name='items',
    )
    item_type = models.CharField(max_length=20, choices=ITEM_TYPES, default='mcq')

    title = models.CharField(max_length=255, blank=True)
    question_text = models.TextField(blank=True)
    question_html = models.TextField(blank=True, help_text='Optional rich-text/HTML statement.')
    question_image = models.ImageField(upload_to='hackathon_items/', blank=True, null=True)
    explanation = models.TextField(blank=True)
    difficulty = models.CharField(max_length=20, blank=True, default='')

    marks = models.DecimalField(max_digits=6, decimal_places=2, default=1)
    negative_marks = models.DecimalField(max_digits=6, decimal_places=2, default=0)

    # MCQ / MCQ-multi: [{"text": str, "image": url|null, "is_correct": bool}]
    options = models.JSONField(default=list, blank=True)

    # Numerical
    numerical_answer = models.DecimalField(max_digits=20, decimal_places=10, null=True, blank=True)
    numerical_tolerance = models.DecimalField(max_digits=10, decimal_places=5, default=0.01)

    # Subjective (manually graded)
    max_words = models.PositiveIntegerField(null=True, blank=True)
    rubric = models.TextField(blank=True, help_text='Grading guidance shown to admins only.')
    model_answer = models.TextField(blank=True, help_text='Reference answer shown to admins only.')

    # Coding (auto-graded via Piston)
    allowed_languages = models.JSONField(default=list, blank=True)
    starter_code = models.JSONField(default=dict, blank=True)
    time_limit_ms = models.PositiveIntegerField(default=3000)
    memory_limit_mb = models.PositiveIntegerField(default=256)
    # [{"stdin": str, "expected_output": str, "points": int, "is_sample": bool, "explanation": str}]
    coding_test_cases = models.JSONField(default=list, blank=True)

    class Meta:
        verbose_name = 'Hackathon Stage Item'
        verbose_name_plural = 'Hackathon Stage Items'
        ordering = ['order', 'created_at']
        indexes = [
            models.Index(fields=['stage', 'order']),
        ]

    def __str__(self):
        return f'{self.get_item_type_display()} ({self.stage_id})'

    @property
    def is_auto_gradable(self):
        return self.item_type in ('mcq', 'mcq_multi', 'numerical', 'coding')

    @property
    def correct_option_indices(self):
        return [i for i, opt in enumerate(self.options or []) if opt.get('is_correct')]


class HackathonRegistration(TimeStampedModel):
    """A student's entry into a hackathon."""

    STATUS_CHOICES = [
        ('registered', 'Registered'),
        ('withdrawn', 'Withdrawn'),
        ('disqualified', 'Disqualified'),
    ]

    hackathon = models.ForeignKey(
        Hackathon, on_delete=models.CASCADE, related_name='registrations',
    )
    participant = models.ForeignKey(
        'users.StudentProfile', on_delete=models.CASCADE,
        related_name='hackathon_registrations',
    )

    # Contact + profile snapshot captured at registration time.
    full_name = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    institution = models.CharField(max_length=255, blank=True)
    year_of_study = models.CharField(max_length=50, blank=True)
    # ["Python", "React"]
    skills = models.JSONField(default=list, blank=True)
    github_url = models.URLField(max_length=1000, blank=True)
    linkedin_url = models.URLField(max_length=1000, blank=True)
    portfolio_url = models.URLField(max_length=1000, blank=True)
    motivation = models.TextField(blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='registered')
    registered_at = models.DateTimeField(default=timezone.now)

    # Final standings, set when the admin declares winners.
    total_score = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    final_rank = models.PositiveIntegerField(null=True, blank=True)
    is_winner = models.BooleanField(default=False)
    winner_title = models.CharField(max_length=150, blank=True)
    prize = models.CharField(max_length=255, blank=True)

    admin_notes = models.TextField(blank=True)

    class Meta:
        verbose_name = 'Hackathon Registration'
        verbose_name_plural = 'Hackathon Registrations'
        unique_together = ['hackathon', 'participant']
        ordering = ['-registered_at']
        indexes = [
            models.Index(fields=['hackathon', 'status']),
            models.Index(fields=['hackathon', 'is_winner']),
        ]

    def __str__(self):
        return f'{self.full_name or self.participant_id} → {self.hackathon_id}'

    @property
    def is_active(self):
        return self.status == 'registered'


class StageParticipation(TimeStampedModel):
    """A participant's state in one round — attempt, score and qualification."""

    STATUS_CHOICES = [
        ('locked', 'Locked'),            # did not qualify for this round
        ('pending', 'Not started'),
        ('in_progress', 'In progress'),
        ('submitted', 'Submitted'),
        ('evaluated', 'Evaluated'),
    ]
    QUALIFICATION_CHOICES = [
        ('undecided', 'Undecided'),
        ('qualified', 'Qualified'),
        ('not_qualified', 'Not qualified'),
    ]

    stage = models.ForeignKey(
        HackathonStage, on_delete=models.CASCADE, related_name='participations',
    )
    registration = models.ForeignKey(
        HackathonRegistration, on_delete=models.CASCADE, related_name='participations',
    )

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    qualification = models.CharField(
        max_length=20, choices=QUALIFICATION_CHOICES, default='undecided',
    )

    attempt_number = models.PositiveIntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    evaluated_at = models.DateTimeField(null=True, blank=True)

    score = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    max_score = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    auto_score = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    override_score = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text='Admin override; wins over the computed score when set.',
    )
    needs_manual_grading = models.BooleanField(default=False)

    rank = models.PositiveIntegerField(null=True, blank=True)
    feedback = models.TextField(blank=True)
    evaluated_by = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='hackathon_evaluations',
    )

    class Meta:
        verbose_name = 'Stage Participation'
        verbose_name_plural = 'Stage Participations'
        unique_together = ['stage', 'registration']
        ordering = ['-score', 'submitted_at']
        indexes = [
            models.Index(fields=['stage', 'qualification']),
            models.Index(fields=['stage', '-score']),
        ]

    def __str__(self):
        return f'{self.registration_id} @ {self.stage_id}'

    @property
    def effective_score(self):
        return self.override_score if self.override_score is not None else self.score

    @property
    def percentage(self):
        total = float(self.max_score or 0)
        if total <= 0:
            return 0.0
        return round((float(self.effective_score) / total) * 100, 2)


class StageItemAnswer(TimeStampedModel):
    """A participant's answer to one inline item in a quiz/coding round."""

    participation = models.ForeignKey(
        StageParticipation, on_delete=models.CASCADE, related_name='answers',
    )
    item = models.ForeignKey(
        HackathonStageItem, on_delete=models.CASCADE, related_name='answers',
    )

    selected_options = models.JSONField(default=list, blank=True)
    numerical_answer = models.DecimalField(
        max_digits=20, decimal_places=10, null=True, blank=True,
    )
    answer_text = models.TextField(blank=True)
    code = models.TextField(blank=True)
    language = models.CharField(max_length=30, blank=True)

    coding_results = models.JSONField(default=list, blank=True)
    passed_count = models.PositiveIntegerField(default=0)
    total_count = models.PositiveIntegerField(default=0)

    is_correct = models.BooleanField(default=False)
    is_auto_graded = models.BooleanField(default=False)
    needs_manual_grading = models.BooleanField(default=False)
    marks_obtained = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    max_marks = models.DecimalField(max_digits=8, decimal_places=2, default=0)

    feedback = models.TextField(blank=True)
    graded_by = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='hackathon_graded_answers',
    )

    class Meta:
        verbose_name = 'Stage Item Answer'
        verbose_name_plural = 'Stage Item Answers'
        unique_together = ['participation', 'item']
        ordering = ['item__order']

    def __str__(self):
        return f'answer {self.item_id} ({self.participation_id})'


class StageSubmission(TimeStampedModel):
    """A participant's deliverable for a ``submission`` round."""

    participation = models.OneToOneField(
        StageParticipation, on_delete=models.CASCADE, related_name='submission',
    )
    title = models.CharField(max_length=255, blank=True)
    summary = models.TextField(blank=True)
    repo_url = models.URLField(max_length=1000, blank=True)
    demo_url = models.URLField(max_length=1000, blank=True)
    video_url = models.URLField(max_length=1000, blank=True)
    submitted_at = models.DateTimeField(default=timezone.now)
    is_late = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'Stage Submission'
        verbose_name_plural = 'Stage Submissions'
        ordering = ['-submitted_at']

    def __str__(self):
        return f'submission ({self.participation_id})'


class StageSubmissionFile(TimeStampedModel):
    """One uploaded artefact attached to a ``StageSubmission``."""

    submission = models.ForeignKey(
        StageSubmission, on_delete=models.CASCADE, related_name='files',
    )
    file = models.FileField(upload_to='hackathons/submissions/')
    original_name = models.CharField(max_length=255, blank=True)
    size_bytes = models.PositiveBigIntegerField(default=0)
    label = models.CharField(max_length=150, blank=True)

    class Meta:
        verbose_name = 'Stage Submission File'
        verbose_name_plural = 'Stage Submission Files'
        ordering = ['created_at']

    def __str__(self):
        return self.original_name or str(self.file)


class HackathonAnnouncement(TimeStampedModel):
    """An admin broadcast to participants (in-app + optional email)."""

    AUDIENCE_CHOICES = [
        ('all', 'All registered participants'),
        ('active', 'Still-in-the-running participants'),
        ('qualified', 'Qualified for a specific stage'),
        ('winners', 'Winners only'),
    ]

    hackathon = models.ForeignKey(
        Hackathon, on_delete=models.CASCADE, related_name='announcements',
    )
    stage = models.ForeignKey(
        HackathonStage, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='announcements',
    )
    title = models.CharField(max_length=255)
    body = models.TextField(blank=True)
    audience = models.CharField(max_length=20, choices=AUDIENCE_CHOICES, default='all')
    send_email = models.BooleanField(default=True)

    sent_at = models.DateTimeField(null=True, blank=True)
    recipients_count = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='hackathon_announcements',
    )

    class Meta:
        verbose_name = 'Hackathon Announcement'
        verbose_name_plural = 'Hackathon Announcements'
        ordering = ['-created_at']

    def __str__(self):
        return self.title


class HackathonGenerationJob(TimeStampedModel):
    """An AI-assisted hackathon/stage generation run, reviewed before it is applied.

    Mirrors ``coursegen.CourseGenerationJob`` — same strictly-forward status
    machine, same "nothing is written until the admin confirms" guarantee.
    """

    KIND_CHOICES = [
        ('event', 'Hackathon brief + timeline'),
        ('stages', 'Stage plan'),
        ('stage_content', 'Questions / problems for one stage'),
    ]
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('generating', 'Generating'),
        ('preview', 'Ready for review'),
        ('applied', 'Applied'),
        ('failed', 'Failed'),
        ('discarded', 'Discarded'),
    ]
    RUNNABLE_STATUSES = ('pending', 'preview', 'failed')

    hackathon = models.ForeignKey(
        Hackathon, on_delete=models.CASCADE, null=True, blank=True,
        related_name='generation_jobs',
    )
    stage = models.ForeignKey(
        HackathonStage, on_delete=models.CASCADE, null=True, blank=True,
        related_name='generation_jobs',
    )

    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default='event')
    prompt = models.TextField(blank=True)
    options = models.JSONField(default=dict, blank=True)

    provider = models.CharField(max_length=50, blank=True)
    model = models.CharField(max_length=200, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    draft = models.JSONField(default=dict, blank=True)
    revisions = models.JSONField(default=list, blank=True)
    error = models.TextField(blank=True)

    prompt_tokens = models.PositiveIntegerField(default=0)
    completion_tokens = models.PositiveIntegerField(default=0)
    total_tokens = models.PositiveIntegerField(default=0)
    estimated_cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    generation_ms = models.PositiveIntegerField(default=0)

    applied_at = models.DateTimeField(null=True, blank=True)
    applied_by = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='applied_hackathon_jobs',
    )
    applied_summary = models.JSONField(default=dict, blank=True)

    created_by = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='hackathon_generation_jobs',
    )

    class Meta:
        verbose_name = 'Hackathon Generation Job'
        verbose_name_plural = 'Hackathon Generation Jobs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant', 'status', '-created_at']),
        ]

    def __str__(self):
        return f'{self.kind} job ({self.status})'

    @property
    def is_running(self):
        return self.status in ('pending', 'generating')

    @property
    def can_apply(self):
        return self.status == 'preview' and bool(self.draft)

    def log(self, action, detail=''):
        entries = list(self.revisions or [])
        entries.append({
            'action': action,
            'detail': detail,
            'at': timezone.now().isoformat(),
        })
        self.revisions = entries[-25:]
