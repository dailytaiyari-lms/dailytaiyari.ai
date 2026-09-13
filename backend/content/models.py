"""
Content models for study materials - Notes, Videos, PDFs.
"""
from django.db import models
from core.models import TimeStampedModel, OrderedModel
from exams.models import Topic, Subject, Course


class Content(OrderedModel):
    """
    Base model for all study content.
    Can be notes, video, pdf, or interactive content.
    """
    CONTENT_TYPES = [
        ('notes', 'Notes'),
        ('video', 'Video'),
        ('pdf', 'PDF'),
        ('interactive', 'Interactive'),
        ('revision', 'Revision Notes'),
        ('formula', 'Formula Sheet'),
    ]
    
    DIFFICULTY_CHOICES = [
        ('beginner', 'Beginner'),
        ('intermediate', 'Intermediate'),
        ('advanced', 'Advanced'),
    ]
    
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('published', 'Published'),
        ('archived', 'Archived'),
    ]

    MATERIAL_KIND_CHOICES = [
        ('study', 'Study material'),
        ('practice', 'Practice questions'),
    ]

    VIDEO_STATUS_CHOICES = [
        ('pending', 'Pending optimisation'),
        ('processing', 'Optimising'),
        ('ready', 'Ready to stream'),
        ('failed', 'Optimisation failed'),
    ]

    title = models.CharField(max_length=500)
    slug = models.SlugField(max_length=500, unique=True)
    description = models.TextField(blank=True)
    content_type = models.CharField(max_length=20, choices=CONTENT_TYPES)
    # For reading material (notes/pdf): distinguishes study material from practice questions
    material_kind = models.CharField(max_length=20, choices=MATERIAL_KIND_CHOICES, default='study')
    
    # Relationships
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name='contents')
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='contents')
    courses = models.ManyToManyField(Course, related_name='contents')
    
    # Content data
    content_html = models.TextField(blank=True)  # For notes
    video_url = models.URLField(blank=True)  # For videos (YouTube, Vimeo, Google Drive, OneDrive)
    video_file = models.FileField(upload_to='content_videos/', blank=True, null=True)  # Uploaded video on blob
    # Streaming readiness of `video_file`. An MP4 whose `moov` index sits at the
    # end of the file forces the browser to download almost all of it before the
    # first frame renders, which is painful for long lectures. We remux uploads
    # so the index sits up front; this tracks that pipeline.
    video_status = models.CharField(
        max_length=20, choices=VIDEO_STATUS_CHOICES, blank=True, default=''
    )
    video_duration_minutes = models.PositiveIntegerField(null=True, blank=True)
    video_duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    # Storage path of the HLS master playlist produced from `video_file`. HLS
    # cuts the lecture into a few seconds per segment at several bitrates, so
    # playback starts after one small segment and the quality adapts to the
    # viewer's bandwidth instead of forcing one fixed bitrate on everyone.
    hls_playlist = models.CharField(max_length=500, blank=True, default='')
    hls_status = models.CharField(
        max_length=20, choices=VIDEO_STATUS_CHOICES, blank=True, default=''
    )
    pdf_file = models.FileField(upload_to='content_pdfs/', blank=True, null=True)
    thumbnail = models.ImageField(upload_to='content_thumbnails/', blank=True, null=True)
    
    # Metadata
    difficulty = models.CharField(max_length=20, choices=DIFFICULTY_CHOICES, default='intermediate')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    is_free = models.BooleanField(default=False)
    is_premium = models.BooleanField(default=False)
    
    # Reading/viewing time
    estimated_time_minutes = models.PositiveIntegerField(default=10)
    
    # Statistics
    views_count = models.PositiveIntegerField(default=0)
    likes_count = models.PositiveIntegerField(default=0)
    bookmarks_count = models.PositiveIntegerField(default=0)
    
    # Author
    author_name = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = 'Content'
        verbose_name_plural = 'Contents'
        indexes = [
            models.Index(fields=['topic', 'content_type']),
            models.Index(fields=['subject', 'status']),
        ]

    def __str__(self):
        return f"{self.title} ({self.content_type})"


class ContentProgress(TimeStampedModel):
    """
    Tracks student progress on content items.
    """
    student = models.ForeignKey(
        'users.StudentProfile', 
        on_delete=models.CASCADE, 
        related_name='content_progress'
    )
    content = models.ForeignKey(Content, on_delete=models.CASCADE, related_name='progress')
    
    # Progress tracking
    is_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    progress_percentage = models.PositiveIntegerField(default=0)
    
    # For videos
    video_position_seconds = models.PositiveIntegerField(default=0)
    
    # Time spent
    time_spent_minutes = models.PositiveIntegerField(default=0)
    
    # Engagement
    is_bookmarked = models.BooleanField(default=False)
    is_liked = models.BooleanField(default=False)
    
    # Notes
    personal_notes = models.TextField(blank=True)

    class Meta:
        unique_together = ['student', 'content']
        verbose_name = 'Content Progress'
        verbose_name_plural = 'Content Progress'

    def __str__(self):
        return f"{self.student.user.email} - {self.content.title}"


class StudyPlan(TimeStampedModel):
    """
    Daily study plan for students.
    Generated based on their goals, progress, and weak areas.
    """
    student = models.ForeignKey(
        'users.StudentProfile', 
        on_delete=models.CASCADE, 
        related_name='study_plans'
    )
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='study_plans')
    
    # Plan details
    date = models.DateField()
    is_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    # Goals
    target_study_minutes = models.PositiveIntegerField(default=60)
    actual_study_minutes = models.PositiveIntegerField(default=0)
    target_questions = models.PositiveIntegerField(default=20)
    actual_questions = models.PositiveIntegerField(default=0)
    
    # XP
    xp_earned = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ['student', 'course', 'date']
        verbose_name = 'Study Plan'
        verbose_name_plural = 'Study Plans'
        ordering = ['-date']

    def __str__(self):
        return f"{self.student.user.email} - {self.date}"


class StudyPlanItem(OrderedModel):
    """
    Individual items in a study plan.
    """
    ITEM_TYPES = [
        ('content', 'Study Content'),
        ('quiz', 'Practice Quiz'),
        ('revision', 'Revision'),
        ('mock', 'Mock Test'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('skipped', 'Skipped'),
    ]

    study_plan = models.ForeignKey(StudyPlan, on_delete=models.CASCADE, related_name='items')
    
    # Item details
    item_type = models.CharField(max_length=20, choices=ITEM_TYPES)
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    
    # References
    content = models.ForeignKey(Content, on_delete=models.SET_NULL, null=True, blank=True)
    topic = models.ForeignKey(Topic, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    completed_at = models.DateTimeField(null=True, blank=True)
    
    # Time
    estimated_minutes = models.PositiveIntegerField(default=15)
    actual_minutes = models.PositiveIntegerField(default=0)
    
    # Priority
    is_priority = models.BooleanField(default=False)
    is_revision = models.BooleanField(default=False)  # Weak topic revision

    class Meta:
        verbose_name = 'Study Plan Item'
        verbose_name_plural = 'Study Plan Items'

    def __str__(self):
        return f"{self.study_plan.date} - {self.title}"

