"""Notebook models.

A Notebook is authored by a tenant admin under a Topic (mirroring Assignment,
Quiz and CodingProblem placement). It carries a template notebook document
(nbformat v4 JSON) that each student gets their own editable copy of.

Execution happens client-side in Pyodide (CPython compiled to WebAssembly), so
students can experiment freely — including classical ML training with numpy,
pandas and scikit-learn — with no server compute. "Run" is unguarded
experimentation; "Submit" scores the notebook against NotebookTests.

Scoring is two-stage:
  * a provisional score computed in the browser for instant feedback, and
  * an authoritative score produced by re-executing the submitted notebook in
    a sandboxed server-side runner (see services.py / tasks.py).
The authoritative score always wins; the provisional one is display-only.
"""
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils import timezone

from core.models import OrderedModel, TimeStampedModel
from exams.models import Topic, Subject, Course

from .nbformat_utils import DEFAULT_PACKAGES, empty_notebook

# Datasets an admin can attach for students to load from the notebook filesystem.
DATASET_FILE_EXTENSIONS = ['csv', 'tsv', 'json', 'txt', 'xlsx', 'xls', 'parquet', 'npy', 'npz', 'zip']


class Notebook(OrderedModel):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('published', 'Published'),
        ('archived', 'Archived'),
    ]
    DIFFICULTY_CHOICES = [
        ('easy', 'Easy'),
        ('medium', 'Medium'),
        ('hard', 'Hard'),
    ]
    # How much automatic feedback a student gets in the browser at submit time.
    #   none     -> no instant score; wait for the server result
    #   visible  -> run only non-hidden tests in the browser (default: hidden
    #               test sources never reach the client, so they can't be read)
    #   all      -> run every test in the browser for a full instant score
    #               (faster feedback, but hidden test code is exposed)
    PROVISIONAL_NONE = 'none'
    PROVISIONAL_VISIBLE = 'visible'
    PROVISIONAL_ALL = 'all'
    PROVISIONAL_CHOICES = [
        (PROVISIONAL_NONE, 'No instant score'),
        (PROVISIONAL_VISIBLE, 'Instant score from visible tests only'),
        (PROVISIONAL_ALL, 'Instant score from all tests (reveals hidden tests)'),
    ]

    tenant = models.ForeignKey(
        'core.Tenant', on_delete=models.CASCADE, related_name='notebooks',
        help_text='Required: no notebook without tenant.',
    )
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='notebooks')
    subject = models.ForeignKey(
        Subject, on_delete=models.SET_NULL, null=True, blank=True, related_name='notebooks',
    )
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name='notebooks')

    title = models.CharField(max_length=500)
    # Rich description / brief shown above the notebook (HTML, like notes).
    description = models.TextField(blank=True)
    difficulty = models.CharField(max_length=10, choices=DIFFICULTY_CHOICES, default='easy')

    # The starter notebook every student begins from (nbformat v4 JSON).
    template_json = models.JSONField(default=empty_notebook, blank=True)

    # Python packages preloaded into the kernel before the first run. Must be
    # available to Pyodide (prebuilt wheel or pure-Python from PyPI).
    packages = models.JSONField(default=list, blank=True)

    # Wall-clock cap for a single cell execution, applied in both the browser
    # kernel and the server-side grading runner.
    time_limit_ms = models.PositiveIntegerField(default=30_000)
    memory_limit_mb = models.PositiveIntegerField(default=512)

    max_marks = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    estimated_time_minutes = models.PositiveIntegerField(default=30)

    # Timing: timeless when is_timed is False (due_at ignored).
    is_timed = models.BooleanField(default=False)
    due_at = models.DateTimeField(null=True, blank=True)

    # Resubmission policy. When allow_resubmission is False a student gets one
    # attempt. When True, max_attempts caps the total (null/0 = unlimited).
    allow_resubmission = models.BooleanField(default=True)
    max_attempts = models.PositiveIntegerField(null=True, blank=True)

    provisional_grading = models.CharField(
        max_length=10, choices=PROVISIONAL_CHOICES, default=PROVISIONAL_VISIBLE,
    )
    # Whether students may see per-test feedback after submitting.
    show_results_to_students = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Notebook'
        verbose_name_plural = 'Notebooks'
        ordering = ['order', '-created_at']
        indexes = [
            models.Index(fields=['topic', 'status']),
            models.Index(fields=['course', 'status']),
        ]

    def __str__(self):
        return self.title

    @property
    def is_open(self):
        """Whether submissions are currently accepted."""
        if self.status != 'published':
            return False
        if self.is_timed and self.due_at:
            return timezone.now() <= self.due_at
        return True

    @property
    def is_past_due(self):
        return bool(self.is_timed and self.due_at and timezone.now() > self.due_at)

    def normalized_packages(self):
        pkgs = [str(p).strip() for p in (self.packages or []) if str(p).strip()]
        return pkgs or list(DEFAULT_PACKAGES)

    @property
    def attempt_limit(self):
        """Max attempts allowed, or None for unlimited."""
        if not self.allow_resubmission:
            return 1
        return self.max_attempts or None

    def attempts_remaining(self, used):
        limit = self.attempt_limit
        if limit is None:
            return None
        return max(limit - (used or 0), 0)

    def total_points(self):
        return sum(t.points for t in self.tests.all()) or 0


class NotebookDataset(OrderedModel):
    """A file mounted into the notebook filesystem before execution.

    Students read it with the exact ``filename`` (e.g. ``pd.read_csv('data.csv')``)
    both in the browser kernel and in the server-side grading runner, so paths
    behave identically in either environment.
    """
    notebook = models.ForeignKey(Notebook, on_delete=models.CASCADE, related_name='datasets')
    # Path the file is written to inside the kernel's working directory.
    filename = models.CharField(max_length=255)
    file = models.FileField(
        upload_to='notebook_datasets/',
        validators=[FileExtensionValidator(DATASET_FILE_EXTENSIONS)],
    )
    description = models.CharField(max_length=500, blank=True)

    class Meta:
        verbose_name = 'Notebook Dataset'
        verbose_name_plural = 'Notebook Datasets'
        ordering = ['order', 'created_at']
        constraints = [
            models.UniqueConstraint(fields=['notebook', 'filename'], name='uniq_notebook_dataset_filename'),
        ]

    def __str__(self):
        return f'{self.filename} ({self.notebook_id})'


class NotebookTest(OrderedModel):
    """An autograder check run against a student's executed notebook.

    ``source`` is Python executed in the same kernel namespace as the student's
    notebook after all cells have run, so it can inspect their variables and
    functions. It passes when it completes without raising (``assert`` is the
    natural idiom); any exception fails it and the message is the feedback.
    """
    notebook = models.ForeignKey(Notebook, on_delete=models.CASCADE, related_name='tests')
    # Optional link to the answer cell this test grades (cell metadata grade_id).
    grade_id = models.CharField(max_length=100, blank=True)
    name = models.CharField(max_length=300)
    source = models.TextField(blank=True)
    points = models.PositiveIntegerField(default=1)
    # Hidden tests are the real grade; visible ones let students self-check on Run.
    is_hidden = models.BooleanField(default=True)
    # Shown to the student when the test fails (instead of the raw traceback).
    failure_hint = models.CharField(max_length=500, blank=True)

    class Meta:
        verbose_name = 'Notebook Test'
        verbose_name_plural = 'Notebook Tests'
        ordering = ['order', 'created_at']

    def __str__(self):
        return f'{self.name} ({"hidden" if self.is_hidden else "visible"})'


class NotebookDraft(TimeStampedModel):
    """Autosaved work-in-progress so a student never loses experiments.

    Exactly one draft per (notebook, student); overwritten by debounced saves
    from the client. Independent of submissions — the draft survives submitting.
    """
    notebook = models.ForeignKey(Notebook, on_delete=models.CASCADE, related_name='drafts')
    student = models.ForeignKey(
        'users.StudentProfile', on_delete=models.CASCADE, related_name='notebook_drafts',
    )
    notebook_json = models.JSONField(default=empty_notebook, blank=True)
    # Total seconds the student has had the notebook open (rough engagement metric).
    time_spent_seconds = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'Notebook Draft'
        verbose_name_plural = 'Notebook Drafts'
        constraints = [
            models.UniqueConstraint(fields=['notebook', 'student'], name='uniq_notebook_student_draft'),
        ]

    def __str__(self):
        return f'draft {self.student_id} → {self.notebook_id}'


class NotebookSubmission(TimeStampedModel):
    """One graded attempt at a notebook."""
    STATUS_QUEUED = 'queued'
    STATUS_RUNNING = 'running'
    STATUS_GRADED = 'graded'
    STATUS_ERROR = 'error'
    STATUS_CHOICES = [
        (STATUS_QUEUED, 'Queued'),
        (STATUS_RUNNING, 'Running'),
        (STATUS_GRADED, 'Graded'),
        (STATUS_ERROR, 'Engine error'),
    ]

    notebook = models.ForeignKey(Notebook, on_delete=models.CASCADE, related_name='submissions')
    student = models.ForeignKey(
        'users.StudentProfile', on_delete=models.CASCADE, related_name='notebook_submissions',
    )
    attempt_number = models.PositiveIntegerField(default=1)

    # The student's notebook exactly as submitted (merged against the template
    # so locked setup cells can't be tampered with).
    notebook_json = models.JSONField(default=empty_notebook)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_QUEUED)
    # Per-test verdicts from the authoritative server-side run.
    results = models.JSONField(default=list, blank=True)
    # Notebook-level execution error (e.g. a cell raised before tests could run).
    execution_error = models.TextField(blank=True)

    passed_count = models.PositiveIntegerField(default=0)
    total_count = models.PositiveIntegerField(default=0)
    passed_points = models.PositiveIntegerField(default=0)
    total_points = models.PositiveIntegerField(default=0)
    # Authoritative marks scaled to notebook.max_marks (if set).
    marks = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)

    # Instant in-browser score, kept for transparency and for spotting
    # divergence between the two environments. Never used for the final grade.
    provisional_passed_points = models.PositiveIntegerField(default=0)
    provisional_total_points = models.PositiveIntegerField(default=0)
    provisional_results = models.JSONField(default=list, blank=True)

    is_late = models.BooleanField(default=False)
    submitted_at = models.DateTimeField(default=timezone.now)
    graded_at = models.DateTimeField(null=True, blank=True)

    # Manual override by an admin/instructor; when set it supersedes `marks`.
    override_marks = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    feedback = models.TextField(blank=True)
    graded_by = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='graded_notebook_submissions',
    )

    class Meta:
        verbose_name = 'Notebook Submission'
        verbose_name_plural = 'Notebook Submissions'
        ordering = ['-submitted_at']
        constraints = [
            models.UniqueConstraint(
                fields=['notebook', 'student', 'attempt_number'],
                name='uniq_notebook_student_attempt',
            ),
        ]
        indexes = [
            models.Index(fields=['notebook', 'student'], name='nb_submission_ns_idx'),
            models.Index(fields=['status'], name='nb_submission_status_idx'),
        ]

    def __str__(self):
        return f'{self.student_id} → {self.notebook_id} (attempt {self.attempt_number})'

    @property
    def all_passed(self):
        return self.total_count > 0 and self.passed_count == self.total_count

    @property
    def final_marks(self):
        """Marks the student is actually credited with (override wins)."""
        return self.override_marks if self.override_marks is not None else self.marks

    @property
    def score_percent(self):
        if not self.total_points:
            return 0
        return round(100 * self.passed_points / self.total_points)


class NotebookCompletion(TimeStampedModel):
    """One row per (notebook, student) recording their best result.

    Written after every authoritative grading pass; keeps the study/progress
    views cheap (no aggregation over submissions) and mirrors
    CodingProblemCompletion.
    """
    tenant = models.ForeignKey(
        'core.Tenant', on_delete=models.CASCADE, related_name='notebook_completions',
    )
    notebook = models.ForeignKey(Notebook, on_delete=models.CASCADE, related_name='completions')
    student = models.ForeignKey(
        'users.StudentProfile', on_delete=models.CASCADE, related_name='notebook_completions',
    )
    best_submission = models.ForeignKey(
        NotebookSubmission, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    best_passed_points = models.PositiveIntegerField(default=0)
    best_total_points = models.PositiveIntegerField(default=0)
    best_marks = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    attempts_used = models.PositiveIntegerField(default=0)
    is_complete = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Notebook Completion'
        verbose_name_plural = 'Notebook Completions'
        constraints = [
            models.UniqueConstraint(fields=['notebook', 'student'], name='uniq_notebook_student_completion'),
        ]
        indexes = [
            models.Index(fields=['notebook', 'student'], name='nb_completion_ns_idx'),
        ]

    def __str__(self):
        return f'{self.student_id} → {self.notebook_id} ({self.best_passed_points}/{self.best_total_points})'
