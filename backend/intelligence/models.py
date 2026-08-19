"""Learner Intelligence foundation models.

Three layers, kept strictly separate:

- Observation:  ``LearningEvent`` — append-only facts about graded responses.
- Inference:    ``LearnerConceptState`` / ``ItemStats`` — always *recomputed*
                from events (never incrementally mutated), so every job is
                idempotent and an algorithm change is a recompute, not a
                migration.
- Semantics:    ``Concept`` / ``ConceptAlias`` / ``ConceptLink`` — what an
                item measures, populated by generators and the LLM tagger.

Other apps must not import these models directly; they go through
``intelligence.api`` so the dependency surface stays one file wide.
"""
from django.db import models
from django.db.models import Q

from core.models import TimeStampedModel
from exams.models import Subject, Topic

from .versions import EVENT_SCHEMA_VERSION, ONTOLOGY_VERSION, STATE_MODEL_VERSION


class Concept(TimeStampedModel):
    """A nameable unit of understanding, finer-grained than a Topic.

    Concepts are namespaced per subject per tenant. ``scope`` reserves room
    for a future platform-owned (cross-tenant) concept bank; today everything
    is tenant-scoped and ``tenant`` is always set for scope='tenant'.
    """

    SCOPE_TENANT = 'tenant'
    SCOPE_GLOBAL = 'global'
    SCOPE_CHOICES = [
        (SCOPE_TENANT, 'Tenant'),
        (SCOPE_GLOBAL, 'Global'),
    ]

    SOURCE_CHOICES = [
        ('manual', 'Manual'),
        ('llm_tagger', 'LLM tagger'),
        ('mockgen', 'Mock test builder'),
        ('coursegen', 'Course builder'),
        ('backfill', 'Backfill'),
    ]

    STATUS_CHOICES = [
        ('active', 'Active'),
        ('merged', 'Merged into another concept'),
        ('archived', 'Archived'),
    ]

    scope = models.CharField(max_length=10, choices=SCOPE_CHOICES, default=SCOPE_TENANT)
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='concepts')
    name = models.CharField(max_length=200)
    slug = models.CharField(max_length=220, db_index=True)
    description = models.TextField(blank=True)

    # Loose curriculum anchoring — filled by the tagger and by generator
    # provenance; a concept may map to zero or many topics.
    topics = models.ManyToManyField(Topic, blank=True, related_name='concepts')

    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='manual')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='active')
    merged_into = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='merge_sources',
    )
    ontology_version = models.CharField(max_length=20, default=ONTOLOGY_VERSION)

    class Meta:
        verbose_name = 'Concept'
        verbose_name_plural = 'Concepts'
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'subject', 'slug'], name='uniq_concept_per_subject',
            ),
        ]

    def __str__(self):
        return f'{self.subject.name} — {self.name}'


class ConceptAlias(TimeStampedModel):
    """Every raw label ever resolved, so resolution is a two-index lookup.

    Merging concepts is just re-pointing aliases at the canonical concept.
    ``subject`` is a denormalized copy of ``concept.subject`` so uniqueness
    can be enforced per subject.
    """

    concept = models.ForeignKey(Concept, on_delete=models.CASCADE, related_name='aliases')
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='concept_aliases')
    raw_label = models.CharField(max_length=200)
    alias_slug = models.CharField(max_length=220)

    class Meta:
        verbose_name = 'Concept Alias'
        verbose_name_plural = 'Concept Aliases'
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'subject', 'alias_slug'], name='uniq_concept_alias',
            ),
        ]

    def __str__(self):
        return f'{self.raw_label} → {self.concept_id}'


class ConceptLink(TimeStampedModel):
    """Connects a Concept to exactly one assessment item (bank or inline).

    Two nullable FKs with an XOR constraint rather than a GenericForeignKey,
    so joins stay plain SQL and the DB enforces integrity. The quiz app keeps
    no reference to this model — consumers query ``item.concept_links``.
    """

    SOURCE_CHOICES = [
        ('llm_tagger', 'LLM tagger'),
        ('generator', 'Generator'),
        ('manual', 'Manual'),
        ('backfill', 'Backfill'),
    ]

    concept = models.ForeignKey(Concept, on_delete=models.CASCADE, related_name='links')
    question = models.ForeignKey(
        'quiz.Question', on_delete=models.CASCADE, null=True, blank=True,
        related_name='concept_links',
    )
    mock_item = models.ForeignKey(
        'quiz.MockTestItem', on_delete=models.CASCADE, null=True, blank=True,
        related_name='concept_links',
    )

    # Primary concept carries weight 1.0; secondary concepts 0.5 by convention.
    weight = models.FloatField(default=1.0)
    is_primary = models.BooleanField(default=False)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='llm_tagger')
    # "{TAGGER_PROMPT_VERSION}:{provider:model}" for llm links, blank otherwise.
    tagger_version = models.CharField(max_length=60, blank=True, default='')

    class Meta:
        verbose_name = 'Concept Link'
        verbose_name_plural = 'Concept Links'
        constraints = [
            models.CheckConstraint(
                name='conceptlink_exactly_one_item',
                check=(
                    (Q(question__isnull=False) & Q(mock_item__isnull=True))
                    | (Q(question__isnull=True) & Q(mock_item__isnull=False))
                ),
            ),
            models.UniqueConstraint(
                fields=['concept', 'question'],
                condition=Q(question__isnull=False),
                name='uniq_conceptlink_question',
            ),
            models.UniqueConstraint(
                fields=['concept', 'mock_item'],
                condition=Q(mock_item__isnull=False),
                name='uniq_conceptlink_mock_item',
            ),
        ]

    def __str__(self):
        target = self.question_id or self.mock_item_id
        return f'{self.concept_id} ↔ {target}'


class LearningEvent(TimeStampedModel):
    """Append-only observation: one graded response to one item.

    Concept ids are deliberately NOT stored here — state recompute joins
    through ConceptLink at compute time, so events recorded before an item
    was tagged automatically gain concepts once tagging runs.

    A regrade appends a superseding row (``event_kind='regraded'``) instead of
    mutating; consumers take the latest event per source answer.
    """

    SOURCE_QUIZ_ANSWER = 'quiz_answer'
    SOURCE_MOCK_BANK_ANSWER = 'mock_bank_answer'
    SOURCE_MOCK_ITEM_ANSWER = 'mock_item_answer'
    SOURCE_PRACTICE_ANSWER = 'practice_answer'
    SOURCE_CHOICES = [
        (SOURCE_QUIZ_ANSWER, 'Quiz answer (bank question)'),
        (SOURCE_MOCK_BANK_ANSWER, 'Mock test answer (bank question)'),
        (SOURCE_MOCK_ITEM_ANSWER, 'Mock test answer (inline item)'),
        (SOURCE_PRACTICE_ANSWER, 'Practice set answer'),
    ]

    KIND_CHOICES = [
        ('graded', 'Graded'),
        ('regraded', 'Regraded'),
    ]

    student = models.ForeignKey(
        'users.StudentProfile', on_delete=models.CASCADE, related_name='learning_events',
    )
    source_type = models.CharField(max_length=20, choices=SOURCE_CHOICES)
    event_kind = models.CharField(max_length=10, choices=KIND_CHOICES, default='graded')

    # Source rows. SET_NULL so history survives deletion of the source.
    answer = models.ForeignKey(
        'quiz.Answer', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='learning_events',
    )
    item_answer = models.ForeignKey(
        'quiz.MockTestAnswer', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='learning_events',
    )
    question = models.ForeignKey(
        'quiz.Question', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='learning_events',
    )
    mock_item = models.ForeignKey(
        'quiz.MockTestItem', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='learning_events',
    )

    # The owning attempt. No FK — two possible target models; batch jobs join
    # by id when they need attempt-level data (e.g. discrimination).
    attempt_kind = models.CharField(max_length=10, blank=True, default='')  # 'quiz' | 'mock' | 'practice'
    attempt_id = models.UUIDField(null=True, blank=True)

    # Snapshots that survive item deletion.
    topic = models.ForeignKey(
        Topic, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    subject = models.ForeignKey(
        Subject, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )

    occurred_at = models.DateTimeField(db_index=True)
    is_correct = models.BooleanField(default=False)
    # marks_obtained / max_marks clamped to [0, 1] — the mastery signal, which
    # also carries partial credit for subjective/coding items.
    score_fraction = models.FloatField(default=0.0)
    marks_obtained = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    max_marks = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    time_taken_seconds = models.PositiveIntegerField(default=0)

    # Just enough of the response for distractor analysis without joining back:
    # {"selected": [1]} | {"numerical": "3.14"} | {"needs_manual": true}
    response_digest = models.JSONField(default=dict, blank=True)

    # "{source_type}:{answer_id}:{grade_marker}" — grade_marker is 0 for the
    # initial grade and int(graded_at.timestamp()) for a manual regrade.
    dedup_key = models.CharField(max_length=120, unique=True)
    schema_version = models.CharField(max_length=10, default=EVENT_SCHEMA_VERSION)

    class Meta:
        verbose_name = 'Learning Event'
        verbose_name_plural = 'Learning Events'
        indexes = [
            models.Index(fields=['student', 'occurred_at']),
            models.Index(fields=['tenant', 'occurred_at']),
        ]

    def __str__(self):
        return f'{self.source_type} {self.dedup_key}'


class LearnerConceptState(TimeStampedModel):
    """Inferred state of one student on one concept.

    Fully recomputed from LearningEvents by ``services.state`` — no field here
    is ever incremented in place.
    """

    CONFIDENCE_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
    ]

    student = models.ForeignKey(
        'users.StudentProfile', on_delete=models.CASCADE, related_name='concept_states',
    )
    concept = models.ForeignKey(Concept, on_delete=models.CASCADE, related_name='learner_states')

    # Recency-decayed, prior-smoothed probability-like estimate in [0, 1].
    mastery = models.FloatField(default=0.0)
    evidence_count = models.PositiveIntegerField(default=0)
    effective_evidence = models.FloatField(default=0.0)  # decay-weighted count
    confidence = models.CharField(max_length=10, choices=CONFIDENCE_CHOICES, default='low')

    first_seen_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    # Spacing model: memory stability in days and predicted recall now.
    stability_days = models.FloatField(default=1.0)
    retention = models.FloatField(default=0.0)
    correct_streak = models.PositiveIntegerField(default=0)

    # Transfer split: single-concept vs multi-concept item performance
    # (windowed, decay-weighted correct mass over attempts).
    single_attempts = models.PositiveIntegerField(default=0)
    single_correct_w = models.FloatField(default=0.0)
    multi_attempts = models.PositiveIntegerField(default=0)
    multi_correct_w = models.FloatField(default=0.0)
    transfer_gap = models.FloatField(null=True, blank=True)

    # {"<item_ref>:<option_idx>": count} for wrong MCQ picks on this concept.
    misconception_counts = models.JSONField(default=dict, blank=True)

    # Computed pattern flags, e.g. ["weak_transfer", "fading_retention"].
    flags = models.JSONField(default=list, blank=True)

    model_version = models.CharField(max_length=10, default=STATE_MODEL_VERSION)
    computed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Learner Concept State'
        verbose_name_plural = 'Learner Concept States'
        constraints = [
            models.UniqueConstraint(
                fields=['student', 'concept'], name='uniq_learner_concept_state',
            ),
        ]
        indexes = [
            models.Index(fields=['tenant', 'concept']),
        ]

    def __str__(self):
        return f'{self.student_id} × {self.concept_id}: {self.mastery:.2f}'


class ItemStats(TimeStampedModel):
    """Batch-recomputed empirical statistics for one item (bank or inline).

    Kept separate from the content rows so nightly recomputes never contend
    with student submits, and both item models get identical treatment.
    """

    question = models.OneToOneField(
        'quiz.Question', on_delete=models.CASCADE, null=True, blank=True,
        related_name='item_stats',
    )
    mock_item = models.OneToOneField(
        'quiz.MockTestItem', on_delete=models.CASCADE, null=True, blank=True,
        related_name='item_stats',
    )

    attempts_count = models.PositiveIntegerField(default=0)
    correct_count = models.PositiveIntegerField(default=0)
    p_value = models.FloatField(null=True, blank=True)  # observed % correct in [0,1]
    avg_time_seconds = models.FloatField(null=True, blank=True)

    # {option_idx: count}, correct option included — the distractor table.
    option_distribution = models.JSONField(default=dict, blank=True)

    # Point-biserial vs the attempt's overall percentage; null until n >= 30.
    discrimination = models.FloatField(null=True, blank=True)

    predicted_difficulty = models.CharField(max_length=20, blank=True, default='')
    observed_difficulty = models.CharField(max_length=20, blank=True, default='')
    difficulty_divergence = models.BooleanField(default=False)

    stats_version = models.CharField(max_length=10, default='1')
    computed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Item Stats'
        verbose_name_plural = 'Item Stats'
        constraints = [
            models.CheckConstraint(
                name='itemstats_exactly_one_item',
                check=(
                    (Q(question__isnull=False) & Q(mock_item__isnull=True))
                    | (Q(question__isnull=True) & Q(mock_item__isnull=False))
                ),
            ),
        ]

    def __str__(self):
        target = self.question_id or self.mock_item_id
        return f'stats for {target} (n={self.attempts_count})'


class AITaggingResult(TimeStampedModel):
    """Cache of one item's LLM tag payload, keyed by content + versions.

    Identical items across mock tests (same content hash) skip the LLM
    entirely; a prompt or model change naturally misses the cache.
    """

    content_hash = models.CharField(max_length=64)
    prompt_version = models.CharField(max_length=20)
    ontology_version = models.CharField(max_length=20, default=ONTOLOGY_VERSION)
    model_ref = models.CharField(max_length=240)  # "provider:model"
    # One item's raw payload: {"concepts": [...], "difficulty": ..., "cognitive_type": ...}
    result = models.JSONField(default=dict)

    class Meta:
        verbose_name = 'AI Tagging Result'
        verbose_name_plural = 'AI Tagging Results'
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'content_hash', 'prompt_version', 'model_ref'],
                name='uniq_tagging_cache_entry',
            ),
        ]

    def __str__(self):
        return f'{self.content_hash[:12]} @ {self.model_ref}'
