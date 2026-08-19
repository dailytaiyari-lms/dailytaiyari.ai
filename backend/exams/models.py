"""
Course models - Structure for IIT JEE and NEET competitive exams.
"""
from django.db import models
from core.models import TimeStampedModel, OrderedModel


class Course(TimeStampedModel):
    """
    Represents an course category (e.g., NEET, IIT JEE, CBSE Class 10).
    Every course must belong to a tenant.
    """
    COURSE_TYPES = [
        ('competitive', 'Competitive Course'),
        ('board', 'Board Course'),
        ('entrance', 'Entrance Course'),
        ('government', 'Government Job Course'),
        ('skill', 'Skill Development'),
    ]
    
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('coming_soon', 'Coming Soon'),
        ('inactive', 'Inactive'),
    ]

    # Selectable certificate designs a student receives on 100% completion.
    CERTIFICATE_TEMPLATES = [
        ('classic', 'Classic — navy & gold, ornate border'),
        ('modern', 'Modern — bold color blocks'),
        ('elegant', 'Elegant — cream & gold, refined'),
        ('minimal', 'Minimal — clean & monochrome'),
    ]

    tenant = models.ForeignKey(
        'core.Tenant',
        on_delete=models.CASCADE,
        related_name='courses',
    )
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50, unique=True)  # e.g., 'neet', 'jee-main'
    description = models.TextField(blank=True)
    course_type = models.CharField(max_length=20, choices=COURSE_TYPES)
    
    # Visual
    icon = models.ImageField(upload_to='course_icons/', blank=True, null=True)
    thumbnail = models.ImageField(upload_to='course_thumbnails/', blank=True, null=True)
    color = models.CharField(max_length=7, default='#3B82F6')  # Hex color
    
    # Metadata
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    is_featured = models.BooleanField(default=False)
    
    # Course details
    duration_minutes = models.PositiveIntegerField(null=True, blank=True)
    total_marks = models.PositiveIntegerField(null=True, blank=True)
    negative_marking = models.BooleanField(default=False)
    negative_marking_ratio = models.DecimalField(
        max_digits=3, decimal_places=2, 
        default=0.25,
        help_text="e.g., 0.25 means 1/4 negative marking"
    )
    
    # Statistics (denormalized for performance)
    total_students = models.PositiveIntegerField(default=0)
    total_questions = models.PositiveIntegerField(default=0)

    # ── Pricing ────────────────────────────────────────────────────────────
    # Payment gateway is not wired yet; for now both free and paid courses
    # simply create an enrollment request that an admin approves.
    PRICING_TYPES = [
        ('free', 'Free'),
        ('paid', 'Paid'),
    ]
    pricing_type = models.CharField(max_length=10, choices=PRICING_TYPES, default='free')
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    # Optional higher "list" price, shown struck-through to convey a discount.
    original_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=3, default='INR')

    # ── Marketing / details page content ───────────────────────────────────
    subtitle = models.CharField(max_length=255, blank=True, default='')
    # "What you will get" bullet points — a list of short strings.
    highlights = models.JSONField(default=list, blank=True)
    refund_policy = models.TextField(blank=True, default='')

    # ── Certificate of completion ──────────────────────────────────────────
    # When enabled, a student who reaches 100% completion can download a
    # certificate rendered from the chosen template (with tenant logo + name).
    certificate_enabled = models.BooleanField(default=False)
    certificate_template = models.CharField(
        max_length=20, choices=CERTIFICATE_TEMPLATES, default='classic'
    )

    # ── Sequential chapter progression ─────────────────────────────────────
    # When enabled, within each subject a chapter stays locked for a student
    # until every preceding chapter (that has content) is fully completed.
    sequential_chapter_unlock = models.BooleanField(
        default=False,
        help_text=(
            "If enabled, students must finish each chapter before the next one "
            "in the same subject unlocks."
        ),
    )

    # Instructors assigned by a tenant admin. Assigned instructors can edit the
    # course content (chapters, topics, quizzes, etc.) but cannot manage the
    # instructor list themselves — that stays admin-only.
    instructors = models.ManyToManyField(
        'users.User',
        related_name='instructing_courses',
        blank=True,
        limit_choices_to={'role': 'instructor'},
    )

    class Meta:
        verbose_name = 'Course'
        verbose_name_plural = 'Courses'
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def is_free(self):
        return self.pricing_type == 'free' or not self.price

    @property
    def discount_percent(self):
        """Percentage off vs. original_price, if a valid discount exists."""
        try:
            if self.original_price and self.price and self.original_price > self.price:
                return round((float(self.original_price) - float(self.price)) / float(self.original_price) * 100, 2)
        except (TypeError, ValueError):
            pass
        return 0



class Subject(OrderedModel):
    """
    Subjects within an course (e.g., Physics, Chemistry for NEET).
    Each subject is linked to one and only one course.
    """
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50)
    description = models.TextField(blank=True)
    
    # Visual
    icon = models.CharField(max_length=50, blank=True)  # Icon name
    color = models.CharField(max_length=7, default='#10B981')
    
    # Course relationship: one subject belongs to one course
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name='subjects',
    )
    
    # Importance for course
    weightage = models.DecimalField(
        max_digits=5, decimal_places=2, 
        default=0,
        help_text="Percentage weightage in the course"
    )
    
    # Statistics
    total_topics = models.PositiveIntegerField(default=0)
    total_questions = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'Subject'
        verbose_name_plural = 'Subjects'
        unique_together = [['code', 'course']]

    def __str__(self):
        return self.name


class Topic(OrderedModel):
    """
    Topics within a subject (e.g., "Laws of Motion" in Physics).
    """
    DIFFICULTY_CHOICES = [
        ('easy', 'Easy'),
        ('medium', 'Medium'),
        ('hard', 'Hard'),
    ]
    
    IMPORTANCE_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('critical', 'Critical'),
    ]

    name = models.CharField(max_length=300)
    code = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    
    # Hierarchy
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='topics')
    parent_topic = models.ForeignKey(
        'self', 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True,
        related_name='subtopics'
    )
    
    # Metadata
    difficulty = models.CharField(max_length=20, choices=DIFFICULTY_CHOICES, default='medium')
    importance = models.CharField(max_length=20, choices=IMPORTANCE_CHOICES, default='medium')
    
    # Course-specific importance (which courses is this topic important for)
    courses = models.ManyToManyField(Course, through='TopicCourseRelevance', related_name='topics')
    
    # Study time estimate
    estimated_study_hours = models.DecimalField(max_digits=4, decimal_places=1, default=1.0)

    # Learning objectives, e.g. ["Solve one-step linear equations", ...].
    # Populated by the AI course builder (which already generates them) and
    # editable by admins.
    objectives = models.JSONField(default=list, blank=True)

    # Statistics
    total_questions = models.PositiveIntegerField(default=0)
    total_content = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'Topic'
        verbose_name_plural = 'Topics'

    def __str__(self):
        return f"{self.subject.name} - {self.name}"


class TopicCourseRelevance(TimeStampedModel):
    """
    Tracks the relevance of a topic to specific exams.
    Allows different importance levels for the same topic across exams.
    """
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE)
    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    
    # Course-specific importance
    importance = models.CharField(
        max_length=20, 
        choices=Topic.IMPORTANCE_CHOICES, 
        default='medium'
    )
    average_questions = models.PositiveIntegerField(
        default=0,
        help_text="Average questions from this topic in the course"
    )
    marks_weightage = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    class Meta:
        unique_together = ['topic', 'course']
        verbose_name = 'Topic Course Relevance'
        verbose_name_plural = 'Topic Course Relevances'

    def __str__(self):
        return f"{self.topic.name} - {self.course.name}"


class Chapter(OrderedModel):
    """
    Chapters organize topics into a learning sequence.
    Study flow: Course → Subject → Chapter → Topic → (Content + Quizzes).
    """
    name = models.CharField(max_length=300)
    code = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    
    # Relationships
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='chapters')
    topics = models.ManyToManyField(
        Topic,
        through='ChapterTopic',
        through_fields=('chapter', 'topic'),
        related_name='chapters',
        blank=True,
    )
    
    # For board courses (e.g., CBSE) or syllabus grouping (e.g., class_11, algebra)
    grade = models.CharField(max_length=20, blank=True)
    book_reference = models.CharField(max_length=200, blank=True)
    
    # Study estimate
    estimated_hours = models.DecimalField(max_digits=4, decimal_places=1, default=2.0)

    class Meta:
        verbose_name = 'Chapter'
        verbose_name_plural = 'Chapters'
        ordering = ['order', 'name']

    def __str__(self):
        return f"{self.subject.name} - {self.name}"


class ChapterTopic(OrderedModel):
    """
    Through model: ordering of topics within a chapter.
    Enables Study flow: Chapter → Topics (ordered) → each topic has Content + Quizzes.
    """
    chapter = models.ForeignKey(Chapter, on_delete=models.CASCADE, related_name='chapter_topics')
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name='chapter_topics')

    class Meta:
        unique_together = [['chapter', 'topic']]
        verbose_name = 'Chapter Topic'
        verbose_name_plural = 'Chapter Topics'
        ordering = ['chapter', 'order']

    def __str__(self):
        return f"{self.chapter.name} → {self.topic.name}"

