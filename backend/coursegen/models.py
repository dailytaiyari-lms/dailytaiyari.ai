"""AI Course Builder — the draft that sits between a prompt and the database.

The whole feature is built around one rule: **the AI never writes to the course
tables.** A generation run only ever produces a :class:`CourseGenerationJob`
holding a JSON ``draft``. An admin reads that draft in a preview, optionally
refines or hand-edits it, and only an explicit "apply" call (with
``confirm=true``) turns it into real Course / Subject / Chapter / Topic /
Content / Quiz rows.

Statuses move strictly forward::

    pending → generating → preview → applied
                        ↘ failed        ↘ discarded

``preview`` is the only status an apply is accepted from, so a draft can never
be written twice.
"""
from django.db import models

from core.models import TimeStampedModel


class CourseGenerationJob(TimeStampedModel):
    """One AI generation request plus the draft it produced."""

    # ── What the admin asked for ────────────────────────────────────────────
    KIND_OUTLINE = 'outline'
    KIND_CONTENT = 'content'
    KIND_META = 'meta'

    KIND_CHOICES = [
        (KIND_OUTLINE, 'Course outline (subjects, chapters, topics)'),
        (KIND_CONTENT, 'Topic material (notes, quiz, assignments, coding)'),
        (KIND_META, 'Course description & marketing copy'),
    ]

    STATUS_PENDING = 'pending'
    STATUS_GENERATING = 'generating'
    STATUS_PREVIEW = 'preview'
    STATUS_APPLIED = 'applied'
    STATUS_FAILED = 'failed'
    STATUS_DISCARDED = 'discarded'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_GENERATING, 'Generating'),
        (STATUS_PREVIEW, 'Awaiting review'),
        (STATUS_APPLIED, 'Applied'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_DISCARDED, 'Discarded'),
    ]

    # Statuses a background run may legitimately be started from. Anything else
    # is either already running or terminal, so the worker must not claim it.
    RUNNABLE_STATUSES = (STATUS_PENDING, STATUS_PREVIEW, STATUS_FAILED)

    INPUT_TEXT = 'text'
    INPUT_VOICE = 'voice'
    INPUT_CHOICES = [(INPUT_TEXT, 'Typed'), (INPUT_VOICE, 'Dictated')]

    created_by = models.ForeignKey(
        'users.User',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='course_generation_jobs',
    )
    # Set for content/meta jobs, and for outline jobs that extend an existing
    # course. Null for an outline that will create a brand-new course.
    course = models.ForeignKey(
        'exams.Course',
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='generation_jobs',
    )

    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default=KIND_OUTLINE)
    prompt = models.TextField(blank=True, default='')
    input_mode = models.CharField(max_length=10, choices=INPUT_CHOICES, default=INPUT_TEXT)

    # Generation knobs the admin picked (topics per chapter, quiz size, tone,
    # language, target scope such as which chapter/topics to write for…).
    options = models.JSONField(default=dict, blank=True)

    # ── Which model produced it ─────────────────────────────────────────────
    # Free-form on purpose: the admin may pick any provider they have configured
    # under "AI Features", and any model that provider serves.
    provider = models.CharField(max_length=32, blank=True, default='')
    model = models.CharField(max_length=200, blank=True, default='')

    # ── Result ──────────────────────────────────────────────────────────────
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    # The reviewable payload. Shape depends on ``kind`` — see coursegen.schema.
    draft = models.JSONField(default=dict, blank=True)
    # Every refine/edit is appended here so an admin can see how the draft moved.
    revisions = models.JSONField(default=list, blank=True)
    error = models.TextField(blank=True, default='')

    prompt_tokens = models.PositiveIntegerField(default=0)
    completion_tokens = models.PositiveIntegerField(default=0)
    total_tokens = models.PositiveIntegerField(default=0)
    estimated_cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    generation_ms = models.PositiveIntegerField(default=0)

    # ── Confirmation trail ──────────────────────────────────────────────────
    applied_at = models.DateTimeField(null=True, blank=True)
    applied_by = models.ForeignKey(
        'users.User',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='applied_course_generation_jobs',
    )
    # What the apply actually wrote: {'courses': 1, 'topics': 12, ...} plus the
    # ids created, so an admin can trace or undo by hand.
    applied_summary = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = 'Course Generation Job'
        verbose_name_plural = 'Course Generation Jobs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['course', 'kind']),
        ]

    def __str__(self):
        return f'{self.get_kind_display()} — {self.status}'

    @property
    def is_reviewable(self):
        return self.status == self.STATUS_PREVIEW

    @property
    def is_running(self):
        """True while a background worker is (or is about to be) on this job.

        The studio polls until this flips false, so ``pending`` counts as running:
        the job is queued but the worker has not claimed it yet.
        """
        return self.status in (self.STATUS_PENDING, self.STATUS_GENERATING)

    def record_revision(self, action, detail=''):
        """Append an audit entry describing how the draft changed."""
        from django.utils import timezone

        entries = list(self.revisions or [])
        entries.append({
            'action': action,
            'detail': (detail or '')[:1000],
            'at': timezone.now().isoformat(),
        })
        # Keep the trail bounded — it is an aid, not an archive.
        self.revisions = entries[-25:]
