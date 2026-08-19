"""
Quiz models - Questions, Quizzes, Mock Tests, and Attempts.
"""
from django.db import models
from core.models import TimeStampedModel, OrderedModel
from exams.models import Topic, Subject, Course
import uuid


class Question(TimeStampedModel):
    """
    Question bank model supporting multiple question types.
    """
    QUESTION_TYPES = [
        ('mcq', 'Multiple Choice (Single)'),
        ('mcq_multi', 'Multiple Choice (Multiple)'),
        ('true_false', 'True/False'),
        ('numerical', 'Numerical'),
        ('fill_blank', 'Fill in the Blank'),
        ('match', 'Match the Following'),
    ]
    
    DIFFICULTY_CHOICES = [
        ('easy', 'Easy'),
        ('medium', 'Medium'),
        ('hard', 'Hard'),
    ]
    
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('review', 'Under Review'),
        ('published', 'Published'),
        ('archived', 'Archived'),
    ]

    # Question content
    question_text = models.TextField()
    question_html = models.TextField(blank=True)  # Rich text with formulas
    question_image = models.ImageField(upload_to='questions/', blank=True, null=True)
    
    # Type and metadata
    question_type = models.CharField(max_length=20, choices=QUESTION_TYPES, default='mcq')
    difficulty = models.CharField(max_length=20, choices=DIFFICULTY_CHOICES, default='medium')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    
    # Relationships
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name='questions')
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='questions')
    courses = models.ManyToManyField(Course, related_name='questions')
    
    # Answer
    correct_answer = models.CharField(max_length=500)  # Option index or value
    explanation = models.TextField(blank=True)
    explanation_image = models.ImageField(upload_to='explanations/', blank=True, null=True)
    
    # For numerical questions
    numerical_answer = models.DecimalField(max_digits=20, decimal_places=10, null=True, blank=True)
    numerical_tolerance = models.DecimalField(max_digits=10, decimal_places=5, default=0.01)
    
    # Scoring
    marks = models.DecimalField(max_digits=5, decimal_places=2, default=1.0)
    negative_marks = models.DecimalField(max_digits=5, decimal_places=2, default=0.25)
    
    # Statistics (updated periodically)
    times_attempted = models.PositiveIntegerField(default=0)
    times_correct = models.PositiveIntegerField(default=0)
    average_time_seconds = models.PositiveIntegerField(default=0)
    
    # Source
    source = models.CharField(max_length=200, blank=True)  # e.g., "NEET 2023"
    year = models.PositiveIntegerField(null=True, blank=True)
    
    # Tags for filtering (legacy concept storage — the intelligence app's
    # ConceptLink is the canonical item↔concept mapping)
    tags = models.JSONField(default=list, blank=True)

    # Intelligence metadata (see intelligence app; '' = untagged)
    COGNITIVE_TYPES = [
        ('recall', 'Recall'),
        ('application', 'Application'),
        ('multi_concept', 'Multi-concept / transfer'),
    ]
    cognitive_type = models.CharField(
        max_length=30, choices=COGNITIVE_TYPES, blank=True, default='',
    )
    # sha256 over the semantic content; a mismatch after an edit marks the
    # item 'stale' so the tagging sweep re-tags it.
    content_hash = models.CharField(max_length=64, blank=True, default='')
    TAGGING_STATUS_CHOICES = [
        ('', 'Untagged'),
        ('tagged', 'Tagged'),
        ('stale', 'Stale'),
    ]
    tagging_status = models.CharField(
        max_length=10, choices=TAGGING_STATUS_CHOICES, blank=True, default='',
    )
    tagged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Question'
        verbose_name_plural = 'Questions'
        indexes = [
            models.Index(fields=['topic', 'difficulty']),
            models.Index(fields=['subject', 'status']),
        ]

    def __str__(self):
        return f"Q{self.id}: {self.question_text[:50]}..."

    @property
    def accuracy_rate(self):
        if self.times_attempted == 0:
            return 0
        return round((self.times_correct / self.times_attempted) * 100, 2)


class QuestionOption(OrderedModel):
    """
    Options for MCQ questions.
    """
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='options')
    option_text = models.TextField()
    option_image = models.ImageField(upload_to='options/', blank=True, null=True)
    is_correct = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'Question Option'
        verbose_name_plural = 'Question Options'

    def __str__(self):
        return f"Option {self.order}: {self.option_text[:30]}..."


class Quiz(TimeStampedModel):
    """
    Quiz model - can be topic-wise, subject-wise, or custom.
    """
    QUIZ_TYPES = [
        ('topic', 'Topic Quiz'),
        ('subject', 'Subject Quiz'),
        ('chapter', 'Chapter Quiz'),
        ('daily', 'Daily Challenge'),
        ('custom', 'Custom Quiz'),
        ('pyq', 'Previous Year Questions'),
    ]
    
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('published', 'Published'),
        ('archived', 'Archived'),
    ]

    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    quiz_type = models.CharField(max_length=20, choices=QUIZ_TYPES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    
    # Relationships
    tenant = models.ForeignKey(
        'core.Tenant',
        on_delete=models.CASCADE,
        related_name='quizzes',
        help_text='Required: no quiz without tenant.',
    )
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='quizzes')
    subject = models.ForeignKey(Subject, on_delete=models.SET_NULL, null=True, blank=True, related_name='quizzes')
    topic = models.ForeignKey(Topic, on_delete=models.SET_NULL, null=True, blank=True, related_name='quizzes')
    
    # Questions
    questions = models.ManyToManyField(Question, through='QuizQuestion', related_name='quizzes')
    
    # Settings
    duration_minutes = models.PositiveIntegerField(default=15)
    total_marks = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    passing_marks = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    
    # Rules
    shuffle_questions = models.BooleanField(default=True)
    shuffle_options = models.BooleanField(default=True)
    show_answer_after_each = models.BooleanField(default=False)
    allow_skip = models.BooleanField(default=True)
    
    # Visibility
    is_free = models.BooleanField(default=True)
    is_daily_challenge = models.BooleanField(default=False)
    challenge_date = models.DateField(null=True, blank=True)
    
    # Statistics
    total_attempts = models.PositiveIntegerField(default=0)
    average_score = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    class Meta:
        verbose_name = 'Quiz'
        verbose_name_plural = 'Quizzes'

    def __str__(self):
        return self.title

    @property
    def questions_count(self):
        return self.questions.count()


class QuizQuestion(OrderedModel):
    """
    Through model for Quiz-Question relationship with ordering.
    """
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE)
    question = models.ForeignKey(Question, on_delete=models.CASCADE)

    class Meta:
        unique_together = ['quiz', 'question']
        verbose_name = 'Quiz Question'
        verbose_name_plural = 'Quiz Questions'


class MockTest(TimeStampedModel):
    """
    Full-length mock test simulating actual course.
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('published', 'Published'),
        ('archived', 'Archived'),
    ]

    RESULT_VISIBILITY_CHOICES = [
        ('immediate', 'Show results on submission'),
        ('on_release', 'Hide results until released by admin'),
    ]

    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    tenant = models.ForeignKey(
        'core.Tenant',
        on_delete=models.CASCADE,
        related_name='mock_tests',
        help_text='Required: no mock test or PYP without tenant.',
    )
    # Legacy single-course link (kept for existing PYP/competitive mocks).
    course = models.ForeignKey(
        Course, on_delete=models.CASCADE, related_name='mock_tests',
        null=True, blank=True,
    )
    # Access control for rich mock tests. If any courses are linked, only their
    # approved+active enrolled students may attempt. If empty (and no legacy
    # `course`), every registered student in the tenant may attempt.
    courses = models.ManyToManyField(
        Course, related_name='linked_mock_tests', blank=True,
        help_text='Courses whose enrolled students can attempt. Empty = all registered students in the tenant.',
    )
    
    # Sections (for courses with multiple subjects)
    sections = models.JSONField(default=list)  # [{subject_id, questions_count, marks}]
    
    # Questions
    questions = models.ManyToManyField(Question, through='MockTestQuestion', related_name='mock_tests')
    
    # Settings (from course defaults)
    duration_minutes = models.PositiveIntegerField()
    total_marks = models.DecimalField(max_digits=6, decimal_places=2)
    negative_marking = models.BooleanField(default=True)
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    is_free = models.BooleanField(default=False)

    # Result visibility: show immediately on submit, or hide until admin releases.
    result_visibility = models.CharField(
        max_length=20, choices=RESULT_VISIBILITY_CHOICES, default='immediate',
    )
    results_released = models.BooleanField(
        default=False,
        help_text='When result_visibility=on_release, results become visible to students once this is True.',
    )
    # Last moment a student is allowed to START the test (independent of duration).
    start_deadline = models.DateTimeField(null=True, blank=True)
    # Force fullscreen during the attempt for a distraction-free experience.
    fullscreen_required = models.BooleanField(default=True)
    # Maximum number of attempts a student may make. Default 1 (no re-attempts).
    max_attempts = models.PositiveIntegerField(
        default=1,
        help_text='Total attempts allowed per student. 1 = no re-attempts (default).',
    )
    
    # Previous Year Paper fields
    is_pyp = models.BooleanField(default=False, help_text='Is this a Previous Year Paper?')
    pyp_year = models.PositiveIntegerField(null=True, blank=True, help_text='e.g., 2024')
    pyp_shift = models.CharField(max_length=50, blank=True, help_text='e.g., Shift 1, Shift 2')
    pyp_session = models.CharField(max_length=100, blank=True, help_text='e.g., January, April')
    pyp_date = models.DateField(null=True, blank=True, help_text='Actual course date')
    
    # Scheduling
    available_from = models.DateTimeField(null=True, blank=True)
    available_until = models.DateTimeField(null=True, blank=True)
    
    # Statistics
    total_attempts = models.PositiveIntegerField(default=0)
    average_score = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    highest_score = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    class Meta:
        verbose_name = 'Mock Test'
        verbose_name_plural = 'Mock Tests'

    def __str__(self):
        return self.title


class MockTestQuestion(OrderedModel):
    """
    Through model for MockTest-Question with section info.
    Supports per-mock-test marks override (so different courses can use 
    different marking schemes for the same question).
    """
    mock_test = models.ForeignKey(MockTest, on_delete=models.CASCADE)
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    section = models.PositiveIntegerField(default=0)  # Section index
    marks_override = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        help_text='Override marks for this question in this mock test (null = use question default)'
    )
    negative_marks_override = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        help_text='Override negative marks for this question in this mock test (null = use question default)'
    )

    class Meta:
        unique_together = ['mock_test', 'question']
    
    @property
    def effective_marks(self):
        """Get marks for this question in this mock test context."""
        return self.marks_override if self.marks_override is not None else self.question.marks
    
    @property
    def effective_negative_marks(self):
        """Get negative marks for this question in this mock test context."""
        return self.negative_marks_override if self.negative_marks_override is not None else self.question.negative_marks


class MockTestItem(OrderedModel):
    """
    A self-contained question authored inline in a rich mock test.

    Unlike MockTestQuestion (which references the shared Question bank and only
    covers MCQ/numerical), a MockTestItem can be any of the four supported
    types, including subjective and coding, and carries all of its own content
    so the mock-test builder is fully self-contained.
    """
    ITEM_TYPES = [
        ('mcq', 'Multiple Choice (Single)'),
        ('mcq_multi', 'Multiple Choice (Multiple)'),
        ('numerical', 'Numerical'),
        ('subjective', 'Subjective'),
        ('coding', 'Coding'),
    ]

    mock_test = models.ForeignKey(MockTest, on_delete=models.CASCADE, related_name='items')
    item_type = models.CharField(max_length=20, choices=ITEM_TYPES, default='mcq')
    section = models.PositiveIntegerField(default=0)

    # Common content
    question_text = models.TextField(blank=True)
    question_html = models.TextField(blank=True, help_text='Optional rich-text/HTML statement.')
    question_image = models.ImageField(upload_to='mock_items/', blank=True, null=True)
    explanation = models.TextField(blank=True)
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

    # Curriculum anchoring + intelligence metadata. Unlike bank Questions these
    # are optional: hand-typed items start untagged and the tagging sweep
    # fills them in. Concepts live in intelligence.ConceptLink.
    topic = models.ForeignKey(
        Topic, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='mock_items',
    )
    subject = models.ForeignKey(
        Subject, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='mock_items',
    )
    difficulty = models.CharField(
        max_length=20, choices=Question.DIFFICULTY_CHOICES, default='medium',
    )
    cognitive_type = models.CharField(
        max_length=30, choices=Question.COGNITIVE_TYPES, blank=True, default='',
    )
    content_hash = models.CharField(max_length=64, blank=True, default='')
    tagging_status = models.CharField(
        max_length=10, choices=Question.TAGGING_STATUS_CHOICES, blank=True, default='',
    )
    tagged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['section', 'order']
        verbose_name = 'Mock Test Item'
        verbose_name_plural = 'Mock Test Items'
        indexes = [
            models.Index(fields=['topic', 'difficulty']),
        ]

    def __str__(self):
        return f'{self.get_item_type_display()} item ({self.mock_test_id})'

    @property
    def is_auto_gradable(self):
        return self.item_type in ('mcq', 'mcq_multi', 'numerical', 'coding')

    @property
    def correct_option_indices(self):
        """Indices of options flagged is_correct (for MCQ types)."""
        return [i for i, opt in enumerate(self.options or []) if opt.get('is_correct')]


class QuizAttempt(TimeStampedModel):
    """
    Records a student's quiz attempt.
    """
    STATUS_CHOICES = [
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('abandoned', 'Abandoned'),
        ('timed_out', 'Timed Out'),
    ]

    student = models.ForeignKey(
        'users.StudentProfile', 
        on_delete=models.CASCADE, 
        related_name='quiz_attempts'
    )
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name='attempts')
    
    # Timing
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    time_taken_seconds = models.PositiveIntegerField(default=0)
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='in_progress')
    
    # Results
    total_questions = models.PositiveIntegerField(default=0)
    attempted_questions = models.PositiveIntegerField(default=0)
    correct_answers = models.PositiveIntegerField(default=0)
    wrong_answers = models.PositiveIntegerField(default=0)
    skipped_questions = models.PositiveIntegerField(default=0)
    
    # Scoring
    marks_obtained = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    total_marks = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    
    # XP earned
    xp_earned = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'Quiz Attempt'
        verbose_name_plural = 'Quiz Attempts'
        ordering = ['-started_at']

    def __str__(self):
        return f"{self.student.user.email} - {self.quiz.title}"

    def calculate_results(self):
        """Calculate and update results from answers."""
        answers = self.answers.all()
        self.total_questions = self.quiz.questions.count()
        self.attempted_questions = answers.count()
        self.correct_answers = answers.filter(is_correct=True).count()
        self.wrong_answers = answers.filter(is_correct=False).count()
        self.skipped_questions = self.total_questions - self.attempted_questions
        
        # Calculate marks using answer.marks_obtained (set by check_answer)
        # This correctly handles +marks for correct, -negative_marks for wrong
        marks = sum(a.marks_obtained for a in answers)
        self.marks_obtained = marks  # Can be negative in competitive courses
        self.total_marks = sum(q.marks for q in self.quiz.questions.all())
        
        if self.total_marks > 0:
            self.percentage = max(0, (self.marks_obtained / self.total_marks) * 100)
        else:
            self.percentage = 0
        
        self.save()


class MockTestAttempt(TimeStampedModel):
    """
    Records a student's mock test attempt.
    """
    STATUS_CHOICES = [
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('abandoned', 'Abandoned'),
        ('timed_out', 'Timed Out'),
    ]

    student = models.ForeignKey(
        'users.StudentProfile', 
        on_delete=models.CASCADE, 
        related_name='mock_test_attempts'
    )
    mock_test = models.ForeignKey(MockTest, on_delete=models.CASCADE, related_name='attempts')
    
    # Timing
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    time_taken_seconds = models.PositiveIntegerField(default=0)
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='in_progress')
    
    # Results
    total_questions = models.PositiveIntegerField(default=0)
    attempted_questions = models.PositiveIntegerField(default=0)
    correct_answers = models.PositiveIntegerField(default=0)
    wrong_answers = models.PositiveIntegerField(default=0)
    
    # Scoring
    marks_obtained = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    total_marks = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    
    # Section-wise results
    section_results = models.JSONField(default=dict)  # {section_id: {attempted, correct, marks}}
    
    # Rank (calculated after submission)
    rank = models.PositiveIntegerField(null=True, blank=True)
    percentile = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    # Grading lifecycle. Rich mock tests with subjective items stay
    # 'pending_manual' until an admin grades every subjective answer.
    GRADING_STATUS_CHOICES = [
        ('auto_graded', 'Auto-graded'),
        ('pending_manual', 'Pending manual grading'),
        ('graded', 'Fully graded'),
    ]
    grading_status = models.CharField(
        max_length=20, choices=GRADING_STATUS_CHOICES, default='auto_graded',
    )
    
    # XP
    xp_earned = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'Mock Test Attempt'
        verbose_name_plural = 'Mock Test Attempts'
        ordering = ['-started_at']

    def __str__(self):
        return f"{self.student.user.email} - {self.mock_test.title}"


class MockTestAnswer(TimeStampedModel):
    """
    A student's response to a single inline MockTestItem.

    (Reused bank questions are still recorded via the shared `Answer` model,
    which already links to MockTestAttempt. This model covers the inline items,
    including subjective + coding, and carries both auto-grade and manual-grade
    fields.)
    """
    attempt = models.ForeignKey(
        MockTestAttempt, on_delete=models.CASCADE, related_name='item_answers',
    )
    item = models.ForeignKey(
        MockTestItem, on_delete=models.CASCADE, related_name='answers',
    )

    # Responses (only the relevant field is used per item_type)
    selected_options = models.JSONField(default=list, blank=True)  # option indices for MCQ types
    numerical_answer = models.DecimalField(max_digits=20, decimal_places=10, null=True, blank=True)
    answer_text = models.TextField(blank=True)  # subjective
    code = models.TextField(blank=True)          # coding
    language = models.CharField(max_length=20, blank=True)

    # Coding auto-grade detail
    coding_results = models.JSONField(default=list, blank=True)
    passed_count = models.PositiveIntegerField(default=0)
    total_count = models.PositiveIntegerField(default=0)

    # Grading
    is_correct = models.BooleanField(default=False)
    is_auto_graded = models.BooleanField(default=False)
    needs_manual_grading = models.BooleanField(default=False)
    marks_obtained = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    max_marks = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    feedback = models.TextField(blank=True)
    graded_by = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='graded_mock_answers',
    )
    graded_at = models.DateTimeField(null=True, blank=True)

    # Meta
    time_taken_seconds = models.PositiveIntegerField(default=0)
    is_marked_for_review = models.BooleanField(default=False)

    class Meta:
        unique_together = ['attempt', 'item']
        verbose_name = 'Mock Test Answer'
        verbose_name_plural = 'Mock Test Answers'

    def __str__(self):
        return f'Answer to item {self.item_id} (attempt {self.attempt_id})'


class Answer(TimeStampedModel):
    """
    Individual answer in a quiz/mock test attempt.
    """
    # Can be linked to either quiz or mock test attempt
    quiz_attempt = models.ForeignKey(
        QuizAttempt, 
        on_delete=models.CASCADE, 
        related_name='answers',
        null=True, blank=True
    )
    mock_test_attempt = models.ForeignKey(
        MockTestAttempt, 
        on_delete=models.CASCADE, 
        related_name='answers',
        null=True, blank=True
    )
    
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='answers')
    
    # Answer data
    selected_option = models.CharField(max_length=500, blank=True)  # Option index or value
    answer_text = models.TextField(blank=True)  # For fill-in-blank
    numerical_answer = models.DecimalField(max_digits=20, decimal_places=10, null=True, blank=True)
    
    # Result
    is_correct = models.BooleanField(default=False)
    marks_obtained = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    
    # Timing
    time_taken_seconds = models.PositiveIntegerField(default=0)
    
    # Status
    is_marked_for_review = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'Answer'
        verbose_name_plural = 'Answers'

    def __str__(self):
        return f"Answer to Q{self.question_id}"

    def check_answer(self, marks_override=None, negative_marks_override=None):
        """
        Check if the answer is correct and calculate marks.
        
        Args:
            marks_override: Override marks for correct answer (for mock test per-question schemes)
            negative_marks_override: Override negative marks (for mock test per-question schemes)
        """
        question = self.question
        effective_marks = marks_override if marks_override is not None else question.marks
        effective_negative = negative_marks_override if negative_marks_override is not None else question.negative_marks
        
        if question.question_type in ['mcq', 'true_false']:
            self.is_correct = self.selected_option == question.correct_answer
        elif question.question_type == 'numerical':
            if self.numerical_answer is not None and question.numerical_answer is not None:
                diff = abs(self.numerical_answer - question.numerical_answer)
                self.is_correct = diff <= question.numerical_tolerance
        elif question.question_type == 'fill_blank':
            self.is_correct = self.answer_text.strip().lower() == question.correct_answer.strip().lower()
        
        if self.is_correct:
            self.marks_obtained = effective_marks
        else:
            self.marks_obtained = -effective_negative
        
        self.save()
        return self.is_correct


class QuestionReport(TimeStampedModel):
    """
    Model for reporting problems with questions.
    """
    REPORT_TYPES = [
        ('wrong_answer', 'Wrong Answer/Solution'),
        ('unclear_question', 'Unclear Question'),
        ('wrong_options', 'Wrong/Missing Options'),
        ('formatting_issue', 'Formatting Issue'),
        ('typo', 'Typo/Spelling Error'),
        ('wrong_topic', 'Wrong Topic/Subject'),
        ('duplicate', 'Duplicate Question'),
        ('outdated', 'Outdated Information'),
        ('other', 'Other'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('reviewing', 'Under Review'),
        ('resolved', 'Resolved'),
        ('dismissed', 'Dismissed'),
    ]
    
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='reports')
    reported_by = models.ForeignKey(
        'users.StudentProfile',
        on_delete=models.CASCADE,
        related_name='question_reports'
    )
    
    report_type = models.CharField(max_length=30, choices=REPORT_TYPES)
    description = models.TextField()
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    admin_response = models.TextField(blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        'users.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='resolved_reports'
    )
    
    class Meta:
        verbose_name = 'Question Report'
        verbose_name_plural = 'Question Reports'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Report on Q{self.question_id} by {self.reported_by}"

