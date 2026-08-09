"""
Chatbot models for AI doubt solver.
"""
import uuid

from django.db import models
from core.models import TimeStampedModel
from exams.models import Topic, Subject

# Anti-farming caps for AI-generated quizzes (lean economy).
AI_QUIZ_XP_CAP_PER_ATTEMPT = 25
AI_QUIZ_XP_DAILY_CAP = 75

# Labels a model (or an older client) may send as a "topic" that carry no
# diagnostic value — they tell the student nothing about what to revise, so we
# refuse to record them as concepts.
GENERIC_TOPIC_LABELS = {
    'quiz', 'quizzes', 'practice', 'practice quiz', 'practice quizzes',
    'practice questions', 'ai quiz', 'ai generated quiz', 'ai-generated quiz',
    'general', 'general quiz', 'general knowledge', 'misc', 'miscellaneous',
    'mcq', 'mcqs', 'test', 'mock test', 'questions', 'revision', 'topic',
    'untitled', 'n/a', 'na', 'none', 'other', 'others',
}


def normalize_topic_label(value):
    """Clean a model-supplied topic label, or return '' when it is useless.

    Trims markdown/punctuation noise, collapses whitespace and drops generic
    labels such as "Practice Quiz" so mastery tracking only ever accumulates
    against real concept names.
    """
    if not value or not isinstance(value, str):
        return ''
    label = value.replace('*', '').replace('#', '').strip()
    label = ' '.join(label.split())
    label = label.strip(' .:-–—"\'')
    if not label or len(label) < 2:
        return ''
    if label.casefold() in GENERIC_TOPIC_LABELS:
        return ''
    return label[:200]


class ChatSession(TimeStampedModel):
    """
    A chat session with the AI doubt solver.
    """
    student = models.ForeignKey(
        'users.StudentProfile',
        on_delete=models.CASCADE,
        related_name='chat_sessions'
    )
    
    # Context
    title = models.CharField(max_length=200, blank=True)
    # The enrolled course this conversation is scoped to. When set, the AI is
    # given that course's syllabus + the student's progress/mistakes so it can
    # answer "what's pending?", "where did I go wrong?" style questions.
    course = models.ForeignKey(
        'exams.Course',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='chat_sessions'
    )
    topic = models.ForeignKey(
        Topic,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='chat_sessions'
    )
    subject = models.ForeignKey(
        Subject,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='chat_sessions'
    )
    
    # Status
    is_active = models.BooleanField(default=True)
    
    # Stats
    message_count = models.PositiveIntegerField(default=0)
    
    # Feedback
    was_helpful = models.BooleanField(null=True, blank=True)
    rating = models.PositiveIntegerField(null=True, blank=True)  # 1-5

    class Meta:
        verbose_name = 'Chat Session'
        verbose_name_plural = 'Chat Sessions'
        ordering = ['-updated_at']

    def __str__(self):
        return f"Chat: {self.student.user.email} - {self.title or 'Untitled'}"


class ChatMessage(TimeStampedModel):
    """
    Individual message in a chat session.
    """
    ROLE_CHOICES = [
        ('user', 'User'),
        ('assistant', 'Assistant'),
        ('system', 'System'),
    ]

    session = models.ForeignKey(
        ChatSession,
        on_delete=models.CASCADE,
        related_name='messages'
    )
    
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    content = models.TextField()
    
    # For image/file uploads
    image = models.ImageField(upload_to='chat_images/', blank=True, null=True)
    
    # AI response metadata
    model_used = models.CharField(max_length=50, blank=True)
    tokens_used = models.PositiveIntegerField(default=0)
    response_time_ms = models.PositiveIntegerField(default=0)
    
    # Feedback
    is_helpful = models.BooleanField(null=True, blank=True)

    class Meta:
        verbose_name = 'Chat Message'
        verbose_name_plural = 'Chat Messages'
        ordering = ['created_at']

    def __str__(self):
        return f"{self.role}: {self.content[:50]}..."


class SavedResponse(TimeStampedModel):
    """
    Saved/bookmarked AI responses for later reference.
    """
    student = models.ForeignKey(
        'users.StudentProfile',
        on_delete=models.CASCADE,
        related_name='saved_responses'
    )
    message = models.ForeignKey(
        ChatMessage,
        on_delete=models.CASCADE,
        related_name='saves'
    )
    
    # Organization
    title = models.CharField(max_length=200, blank=True)
    topic = models.ForeignKey(
        Topic,
        on_delete=models.SET_NULL,
        null=True, blank=True
    )
    
    # Notes
    personal_notes = models.TextField(blank=True)

    class Meta:
        verbose_name = 'Saved Response'
        verbose_name_plural = 'Saved Responses'
        unique_together = ['student', 'message']

    def __str__(self):
        return f"Saved: {self.title or self.message.content[:30]}..."


class FrequentQuestion(TimeStampedModel):
    """
    Frequently asked questions with pre-generated answers.
    """
    question = models.TextField()
    answer = models.TextField()
    
    # Context
    topic = models.ForeignKey(
        Topic,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='faqs'
    )
    subject = models.ForeignKey(
        Subject,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='faqs'
    )
    
    # Stats
    views_count = models.PositiveIntegerField(default=0)
    helpful_count = models.PositiveIntegerField(default=0)
    
    # Status
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Frequent Question'
        verbose_name_plural = 'Frequent Questions'

    def __str__(self):
        return self.question[:50]


class AIQuizAttempt(TimeStampedModel):
    """
    Tracks quizzes generated and attempted through the AI chatbot.
    """
    student = models.ForeignKey(
        'users.StudentProfile',
        on_delete=models.CASCADE,
        related_name='ai_quiz_attempts'
    )
    session = models.ForeignKey(
        ChatSession,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='quiz_attempts'
    )
    
    # Quiz content (stored as JSON)
    quiz_topic = models.CharField(max_length=200, blank=True)
    quiz_subject = models.CharField(max_length=100, blank=True)
    questions_data = models.JSONField(default=list)  # Store all questions with options
    
    # Results
    total_questions = models.PositiveIntegerField(default=0)
    correct_answers = models.PositiveIntegerField(default=0)
    wrong_answers = models.PositiveIntegerField(default=0)
    percentage = models.FloatField(default=0)
    
    # XP awarded
    xp_earned = models.PositiveIntegerField(default=0)
    
    # Time tracking
    time_taken_seconds = models.PositiveIntegerField(default=0)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'AI Quiz Attempt'
        verbose_name_plural = 'AI Quiz Attempts'
        ordering = ['-created_at']

    def __str__(self):
        return f"AI Quiz: {self.student.user.email} - {self.quiz_topic or 'General'} ({self.percentage}%)"
    
    def calculate_results(self):
        """Calculate quiz results from answers."""
        if not self.questions_data:
            return
        
        correct = 0
        for q in self.questions_data:
            if q.get('user_answer') == q.get('correct_option'):
                correct += 1
        
        self.total_questions = len(self.questions_data)
        self.correct_answers = correct
        self.wrong_answers = self.total_questions - correct
        self.percentage = (correct / self.total_questions * 100) if self.total_questions > 0 else 0
    
    def calculate_xp(self):
        """
        Calculate XP based on performance.

        Base: 5 XP/question scaled by accuracy, plus an accuracy bonus
        (100% -> +10, >=80% -> +5, >=60% -> +2), capped per attempt so a
        single AI quiz cannot award an unbounded amount of XP.
        """
        if self.total_questions == 0:
            self.xp_earned = 0
            return 0
        base_xp = self.total_questions * 5
        xp = int(base_xp * (self.percentage / 100))
        if self.percentage >= 100:
            xp += 10
        elif self.percentage >= 80:
            xp += 5
        elif self.percentage >= 60:
            xp += 2
        self.xp_earned = min(xp, AI_QUIZ_XP_CAP_PER_ATTEMPT)
        return self.xp_earned


class AIQuizQuestion(TimeStampedModel):
    """
    Individual question record for AI quiz attempts (for detailed analytics).
    """
    attempt = models.ForeignKey(
        AIQuizAttempt,
        on_delete=models.CASCADE,
        related_name='questions'
    )
    
    # Question data
    question_index = models.PositiveIntegerField(default=0)
    question_text = models.TextField()
    # The concept this question tests (e.g. "Free Body Diagrams"). Drives the
    # per-concept mastery breakdown on the AI Learning page.
    topic = models.CharField(max_length=200, blank=True)
    options = models.JSONField(default=list)  # List of option strings
    correct_option = models.PositiveIntegerField(default=0)  # Index of correct option
    
    # User's answer
    user_answer = models.IntegerField(null=True, blank=True)  # Index of selected option
    is_correct = models.BooleanField(default=False)
    
    # Explanation
    explanation = models.TextField(blank=True)
    
    # Time spent on this question
    time_spent_seconds = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'AI Quiz Question'
        verbose_name_plural = 'AI Quiz Questions'
        ordering = ['attempt', 'question_index']

    def __str__(self):
        status = "✓" if self.is_correct else "✗"
        return f"Q{self.question_index + 1} {status}: {self.question_text[:50]}..."


class AILearningStats(TimeStampedModel):
    """
    Aggregated AI learning statistics for a student.
    Updated after each AI quiz attempt.
    """
    student = models.OneToOneField(
        'users.StudentProfile',
        on_delete=models.CASCADE,
        related_name='ai_learning_stats'
    )
    
    # Overall stats
    total_quizzes_attempted = models.PositiveIntegerField(default=0)
    total_questions_attempted = models.PositiveIntegerField(default=0)
    total_correct_answers = models.PositiveIntegerField(default=0)
    total_xp_earned = models.PositiveIntegerField(default=0)
    
    # Averages
    average_accuracy = models.FloatField(default=0)
    average_time_per_question = models.FloatField(default=0)  # in seconds
    
    # Streaks
    current_quiz_streak = models.PositiveIntegerField(default=0)
    longest_quiz_streak = models.PositiveIntegerField(default=0)
    last_quiz_date = models.DateField(null=True, blank=True)
    
    # Topic mastery (JSON: {"topic_name": {"attempted": X, "correct": Y}})
    topic_performance = models.JSONField(default=dict)
    
    # Achievements
    perfect_quizzes = models.PositiveIntegerField(default=0)  # 100% score
    quizzes_above_80 = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'AI Learning Stats'
        verbose_name_plural = 'AI Learning Stats'

    def __str__(self):
        return f"AI Stats: {self.student.user.email} - {self.total_xp_earned} XP"
    
    def update_from_attempt(self, attempt):
        """Update stats from a new quiz attempt."""
        self.total_quizzes_attempted += 1
        self.total_questions_attempted += attempt.total_questions
        self.total_correct_answers += attempt.correct_answers
        self.total_xp_earned += attempt.xp_earned
        
        # Update averages
        if self.total_questions_attempted > 0:
            self.average_accuracy = (self.total_correct_answers / self.total_questions_attempted) * 100
        
        # Update topic performance.
        # Questions carry the concept they test, so a single quiz can improve
        # (or expose) several concepts at once. Fall back to the quiz-level
        # topic for questions the model did not tag.
        fallback_topic = normalize_topic_label(attempt.quiz_topic)
        per_topic = {}
        for question in attempt.questions.all():
            topic = normalize_topic_label(question.topic) or fallback_topic
            if not topic:
                continue
            bucket = per_topic.setdefault(topic, {'attempted': 0, 'correct': 0})
            bucket['attempted'] += 1
            bucket['correct'] += 1 if question.is_correct else 0

        if not per_topic and fallback_topic:
            per_topic[fallback_topic] = {
                'attempted': attempt.total_questions,
                'correct': attempt.correct_answers,
            }

        for topic, counts in per_topic.items():
            entry = self.topic_performance.setdefault(
                topic, {'attempted': 0, 'correct': 0, 'quizzes': 0}
            )
            entry['attempted'] = entry.get('attempted', 0) + counts['attempted']
            entry['correct'] = entry.get('correct', 0) + counts['correct']
            entry['quizzes'] = entry.get('quizzes', 0) + 1
        
        # Update achievements
        if attempt.percentage == 100:
            self.perfect_quizzes += 1
        if attempt.percentage >= 80:
            self.quizzes_above_80 += 1
        
        # Update streak
        from django.utils import timezone
        today = timezone.now().date()
        if self.last_quiz_date:
            if (today - self.last_quiz_date).days == 1:
                self.current_quiz_streak += 1
            elif (today - self.last_quiz_date).days > 1:
                self.current_quiz_streak = 1
        else:
            self.current_quiz_streak = 1
        
        if self.current_quiz_streak > self.longest_quiz_streak:
            self.longest_quiz_streak = self.current_quiz_streak
        
        self.last_quiz_date = today
        self.save()



# ─────────────────────────────────────────────────────────────────────────────
# Bring-your-own-LLM configuration (tenant admin → "AI Features")
# ─────────────────────────────────────────────────────────────────────────────

class AIProviderConfig(models.Model):
    """A tenant's LLM provider credentials for the AI Doubt Solver.

    A tenant may store several providers but exactly one is ``is_active`` — that
    is the one used to answer students. API keys are encrypted at rest via
    :mod:`core.encryption` and are never serialized back to API clients.

    Every supported provider except Anthropic speaks the OpenAI chat-completions
    protocol, so they share one client path and only differ by ``base_url``:

    * ``openai``            — api.openai.com
    * ``azure_openai``      — an Azure OpenAI deployment
    * ``gemini``            — Google's OpenAI-compatible endpoint
    * ``anthropic``         — Claude (native Messages API)
    * ``groq``              — free/fast hosting of open-source models
    * ``openrouter``        — includes several ``:free`` open-source models
    * ``together``          — open-source model hosting
    * ``ollama``            — self-hosted open models (fully free, your server)
    * ``custom``            — any other OpenAI-compatible endpoint (vLLM, LM Studio…)
    """

    PROVIDER_OPENAI = 'openai'
    PROVIDER_AZURE = 'azure_openai'
    PROVIDER_GEMINI = 'gemini'
    PROVIDER_ANTHROPIC = 'anthropic'
    PROVIDER_GROQ = 'groq'
    PROVIDER_OPENROUTER = 'openrouter'
    PROVIDER_TOGETHER = 'together'
    PROVIDER_OLLAMA = 'ollama'
    PROVIDER_CUSTOM = 'custom'

    PROVIDER_CHOICES = [
        (PROVIDER_OPENAI, 'OpenAI'),
        (PROVIDER_AZURE, 'Azure OpenAI'),
        (PROVIDER_GEMINI, 'Google Gemini'),
        (PROVIDER_ANTHROPIC, 'Anthropic Claude'),
        (PROVIDER_GROQ, 'Groq (open-source models)'),
        (PROVIDER_OPENROUTER, 'OpenRouter (free open-source models)'),
        (PROVIDER_TOGETHER, 'Together AI (open-source models)'),
        (PROVIDER_OLLAMA, 'Self-hosted Ollama'),
        (PROVIDER_CUSTOM, 'Custom OpenAI-compatible endpoint'),
    ]

    # Default endpoint per provider. ``None`` means "the SDK default" (OpenAI)
    # or "the admin must supply one" (Azure / Ollama / custom).
    DEFAULT_BASE_URLS = {
        PROVIDER_OPENAI: '',
        PROVIDER_GEMINI: 'https://generativelanguage.googleapis.com/v1beta/openai/',
        PROVIDER_GROQ: 'https://api.groq.com/openai/v1',
        PROVIDER_OPENROUTER: 'https://openrouter.ai/api/v1',
        PROVIDER_TOGETHER: 'https://api.together.xyz/v1',
        PROVIDER_OLLAMA: 'http://localhost:11434/v1',
        PROVIDER_ANTHROPIC: 'https://api.anthropic.com',
    }

    # A sensible default model so a tenant only has to paste a key.
    DEFAULT_MODELS = {
        PROVIDER_OPENAI: 'gpt-4o-mini',
        PROVIDER_AZURE: '',  # = the deployment name, tenant-specific
        PROVIDER_GEMINI: 'gemini-2.0-flash',
        PROVIDER_ANTHROPIC: 'claude-3-5-haiku-latest',
        PROVIDER_GROQ: 'llama-3.3-70b-versatile',
        PROVIDER_OPENROUTER: 'meta-llama/llama-3.3-70b-instruct:free',
        PROVIDER_TOGETHER: 'meta-llama/Llama-3.3-70B-Instruct-Turbo-Free',
        PROVIDER_OLLAMA: 'llama3.1',
        PROVIDER_CUSTOM: '',
    }

    # Providers that do not need an API key (self-hosted, open weights).
    KEYLESS_PROVIDERS = {PROVIDER_OLLAMA, PROVIDER_CUSTOM}

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        'core.Tenant', on_delete=models.CASCADE, related_name='ai_providers'
    )
    provider = models.CharField(max_length=32, choices=PROVIDER_CHOICES)

    api_key_encrypted = models.TextField(blank=True, default='')
    # Endpoint override. Required for Azure ("https://<res>.openai.azure.com"),
    # Ollama and custom endpoints; defaulted for the rest.
    base_url = models.CharField(max_length=500, blank=True, default='')
    # Model name, or the *deployment name* for Azure OpenAI.
    model = models.CharField(max_length=200, blank=True, default='')
    # Azure only — the REST API version of the deployment.
    api_version = models.CharField(max_length=50, blank=True, default='2024-10-21')

    # Generation controls, exposed to the admin so they can trade cost/quality.
    temperature = models.FloatField(default=0.7)
    max_tokens = models.PositiveIntegerField(default=2000)

    is_active = models.BooleanField(default=False)

    # Result of the last "Test connection" run, surfaced in the admin UI.
    last_tested_at = models.DateTimeField(null=True, blank=True)
    last_test_ok = models.BooleanField(null=True, blank=True)
    last_test_error = models.CharField(max_length=500, blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'AI Provider Config'
        verbose_name_plural = 'AI Provider Configs'
        ordering = ['provider']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'provider'], name='uniq_tenant_ai_provider'
            ),
        ]

    def __str__(self):
        return f'{self.tenant.name} — {self.get_provider_display()}'

    @property
    def api_key(self):
        """Decrypted API key (empty string when not set)."""
        from core.encryption import decrypt
        return decrypt(self.api_key_encrypted)

    @api_key.setter
    def api_key(self, raw):
        from core.encryption import encrypt
        self.api_key_encrypted = encrypt(raw or '')

    @property
    def effective_base_url(self):
        return self.base_url or self.DEFAULT_BASE_URLS.get(self.provider, '')

    @property
    def effective_model(self):
        return self.model or self.DEFAULT_MODELS.get(self.provider, '')

    @property
    def is_configured(self):
        """True once everything needed to actually call the provider is present."""
        if not self.effective_model:
            return False
        if self.provider in self.KEYLESS_PROVIDERS:
            return bool(self.effective_base_url)
        if self.provider == self.PROVIDER_AZURE:
            return bool(self.api_key_encrypted and self.base_url)
        return bool(self.api_key_encrypted)


class AISettings(TimeStampedModel):
    """Per-tenant AI behaviour and spend guardrails.

    One row per tenant, created lazily. ``student_daily_message_limit`` and
    ``monthly_token_budget`` are the tenant's own guardrails on their own key;
    the platform-key allowance is granted separately by the super admin via
    :pyattr:`core.Tenant.ai_platform_monthly_tokens`.
    """

    # Master switch — lets an admin pause the AI without deleting credentials.
    is_enabled = models.BooleanField(default=True)

    # 0 = unlimited.
    student_daily_message_limit = models.PositiveIntegerField(default=50)
    monthly_token_budget = models.PositiveIntegerField(default=0)

    # Feature toggles inside the assistant.
    allow_quiz_generation = models.BooleanField(default=True)
    allow_course_context = models.BooleanField(default=True)

    # Appended to the built-in system prompt — tone, syllabus notes, language.
    custom_instructions = models.TextField(blank=True, default='')

    class Meta:
        verbose_name = 'AI Settings'
        verbose_name_plural = 'AI Settings'

    def __str__(self):
        return f'AI settings — {self.tenant.name if self.tenant else "unassigned"}'


class AIUsageRecord(TimeStampedModel):
    """One metered LLM call, used for cost reporting and quota enforcement.

    ``source`` distinguishes calls billed to the tenant's own key from calls
    that fell back to the platform key (which cost the platform owner money and
    are therefore capped by the super-admin grant).
    """

    SOURCE_TENANT = 'tenant'
    SOURCE_PLATFORM = 'platform'
    SOURCE_CHOICES = [
        (SOURCE_TENANT, "Tenant's own key"),
        (SOURCE_PLATFORM, 'Platform key (granted)'),
    ]

    student = models.ForeignKey(
        'users.StudentProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='ai_usage_records',
    )
    session = models.ForeignKey(
        ChatSession,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='usage_records',
    )
    source = models.CharField(max_length=16, choices=SOURCE_CHOICES, default=SOURCE_TENANT)
    provider = models.CharField(max_length=32, blank=True, default='')
    model = models.CharField(max_length=200, blank=True, default='')

    # Which platform model was billed, when the call was ours to pay for. Kept
    # as a nullable FK *alongside* the plain ``model`` string so the historical
    # record survives the model row being deleted.
    platform_model = models.ForeignKey(
        'PlatformAIModel', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='usage_records',
    )
    # Which part of the product spent the money. Without this a platform owner
    # cannot tell an expensive course generation from a cheap student question.
    FEATURE_CHAT = 'chat'
    FEATURE_QUIZ = 'quiz'
    FEATURE_COURSEGEN = 'coursegen'
    FEATURE_OTHER = 'other'
    FEATURE_CHOICES = [
        (FEATURE_CHAT, 'Doubt solver'),
        (FEATURE_QUIZ, 'AI quiz'),
        (FEATURE_COURSEGEN, 'Course builder'),
        (FEATURE_OTHER, 'Other'),
    ]
    feature = models.CharField(max_length=20, choices=FEATURE_CHOICES, default=FEATURE_CHAT)

    prompt_tokens = models.PositiveIntegerField(default=0)
    completion_tokens = models.PositiveIntegerField(default=0)
    total_tokens = models.PositiveIntegerField(default=0)

    # Best-effort USD estimate from a static price table; 0 when unknown/free.
    estimated_cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)

    response_time_ms = models.PositiveIntegerField(default=0)
    was_successful = models.BooleanField(default=True)
    error_message = models.CharField(max_length=500, blank=True, default='')

    class Meta:
        verbose_name = 'AI Usage Record'
        verbose_name_plural = 'AI Usage Records'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant', 'created_at']),
            models.Index(fields=['tenant', 'source', 'created_at']),
            # Powers the platform-wide "who is costing us money" report.
            models.Index(fields=['source', 'created_at']),
        ]

    def __str__(self):
        return f'{self.provider}/{self.model} — {self.total_tokens} tokens'


# ─────────────────────────────────────────────────────────────────────────────
# Platform-supplied LLMs (super admin → "AI Platform")
# ─────────────────────────────────────────────────────────────────────────────
#
# Bring-your-own-key (above) assumes a technical tenant admin who can obtain an
# OpenAI key. Most academy owners cannot. So the platform also sells/gifts its
# own models: the super admin registers credentials once here, grants a set of
# models to a tenant, and that tenant's AI works immediately with no key of its
# own. Tenant keys always win when present — the platform only pays when the
# tenant has nothing of their own.


class PlatformAIProvider(models.Model):
    """LLM credentials owned by the platform, not by any tenant.

    Deliberately separate from :class:`AIProviderConfig`: these keys are the
    platform owner's, are never exposed to a tenant admin, and are billed to the
    platform. Several may exist at once (e.g. OpenAI for quality, Groq for cheap
    bulk work) and each exposes its own set of :class:`PlatformAIModel` rows.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Operator-facing label, e.g. "OpenAI (production)". Distinguishes two
    # accounts with the same underlying provider.
    name = models.CharField(max_length=120)
    provider = models.CharField(max_length=32, choices=AIProviderConfig.PROVIDER_CHOICES)

    api_key_encrypted = models.TextField(blank=True, default='')
    base_url = models.CharField(max_length=500, blank=True, default='')
    api_version = models.CharField(max_length=50, blank=True, default='2024-10-21')

    # Master switch. Turning this off instantly stops every tenant relying on
    # this account, without deleting the grants.
    is_enabled = models.BooleanField(default=True)
    notes = models.TextField(blank=True, default='')
    sort_order = models.PositiveIntegerField(default=0)

    last_tested_at = models.DateTimeField(null=True, blank=True)
    last_test_ok = models.BooleanField(null=True, blank=True)
    last_test_error = models.CharField(max_length=500, blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Platform AI Provider'
        verbose_name_plural = 'Platform AI Providers'
        ordering = ['sort_order', 'name']

    def __str__(self):
        return self.name or self.get_provider_display()

    @property
    def api_key(self):
        from core.encryption import decrypt
        return decrypt(self.api_key_encrypted)

    @api_key.setter
    def api_key(self, raw):
        from core.encryption import encrypt
        self.api_key_encrypted = encrypt(raw or '')

    @property
    def effective_base_url(self):
        return self.base_url or AIProviderConfig.DEFAULT_BASE_URLS.get(self.provider, '')

    @property
    def is_configured(self):
        if self.provider in AIProviderConfig.KEYLESS_PROVIDERS:
            return bool(self.effective_base_url)
        if self.provider == AIProviderConfig.PROVIDER_AZURE:
            return bool(self.api_key_encrypted and self.base_url)
        return bool(self.api_key_encrypted)


class PlatformAIModel(models.Model):
    """One model a platform provider serves, with the price we pay for it.

    Prices live here rather than in a code table so the super admin can correct
    them the day a vendor changes pricing, without a deploy. They drive both the
    per-tenant cost report and the cost ceiling enforced in the resolver.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.ForeignKey(
        PlatformAIProvider, on_delete=models.CASCADE, related_name='models'
    )
    # What the vendor calls it — sent verbatim on the wire.
    model_name = models.CharField(max_length=200)
    # What a tenant admin sees, e.g. "Fast — good for most questions".
    label = models.CharField(max_length=120, blank=True, default='')
    description = models.CharField(max_length=300, blank=True, default='')

    # USD per 1,000,000 tokens. 0 is meaningful: self-hosted and ':free' models
    # genuinely cost nothing.
    input_cost_per_million = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    output_cost_per_million = models.DecimalField(max_digits=10, decimal_places=4, default=0)

    max_output_tokens = models.PositiveIntegerField(default=4000)
    is_enabled = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Platform AI Model'
        verbose_name_plural = 'Platform AI Models'
        ordering = ['sort_order', 'model_name']
        constraints = [
            models.UniqueConstraint(
                fields=['provider', 'model_name'], name='uniq_platform_provider_model'
            ),
        ]

    def __str__(self):
        return f'{self.provider.name} — {self.model_name}'

    @property
    def display_label(self):
        return self.label or self.model_name

    @property
    def is_usable(self):
        """Both the model and the account behind it must be live and complete."""
        return bool(
            self.is_enabled
            and self.provider.is_enabled
            and self.provider.is_configured
        )


class TenantAIAllocation(models.Model):
    """What one tenant may use from the platform's own LLMs, and how much.

    Entirely super-admin owned. Which models sit behind a tenant's AI is our
    operational concern, not theirs: an academy owner is told "AI is included"
    and nothing more, so we stay free to add, retire or reprice models without
    ever touching a tenant's settings. A tenant that wants a specific model
    connects its own key, which always takes precedence.

    Several models can be granted at once; the extras act as a failover chain
    rather than a menu.
    """

    tenant = models.OneToOneField(
        'core.Tenant', on_delete=models.CASCADE, related_name='ai_allocation'
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    is_enabled = models.BooleanField(default=False)
    granted_models = models.ManyToManyField(
        PlatformAIModel, blank=True, related_name='granted_to_tenants'
    )
    default_model = models.ForeignKey(
        PlatformAIModel, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='default_for_tenants',
    )
    # 0 means unlimited on that axis. Whichever is hit first stops the tenant.
    monthly_token_limit = models.PositiveIntegerField(default=0)
    monthly_cost_limit_usd = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # ── Exhaustion warnings ─────────────────────────────────────────────────
    # Warn once when usage crosses this percentage, then again at 100%.
    notify_at_percent = models.PositiveIntegerField(default=80)
    # 'YYYY-MM' of the last warning, so each month warns afresh but never spams.
    last_notified_period = models.CharField(max_length=7, blank=True, default='')
    last_notified_percent = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'Tenant AI Allocation'
        verbose_name_plural = 'Tenant AI Allocations'

    def __str__(self):
        return f'AI allocation — {self.tenant.name}'

    def usable_models(self):
        """Granted models that are actually callable right now.

        Filters out models whose provider the super admin has since disabled or
        whose credentials were removed, so a stale grant can never 500 a chat.
        """
        return [m for m in self.granted_models.select_related('provider') if m.is_usable]

    def candidate_models(self):
        """The failover chain: preferred model first, then the rest in order.

        Granting several models buys resilience, not choice — if the first one
        errors or rate-limits mid-request we quietly try the next, and the
        student never learns that anything went wrong.
        """
        models_ = self.usable_models()
        if not models_:
            return []
        models_.sort(key=lambda m: (m.provider.sort_order, m.sort_order, m.model_name))
        preferred = self.default_model_id
        if preferred and any(m.id == preferred for m in models_):
            models_.sort(key=lambda m: m.id != preferred)
        return models_

    def effective_model(self):
        """The model a request should start with."""
        chain = self.candidate_models()
        return chain[0] if chain else None
