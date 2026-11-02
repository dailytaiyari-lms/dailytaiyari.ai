"""
User models for DailyTaiyari platform.
Custom User model with StudentProfile for IIT JEE & NEET course preparation.
"""
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from core.models import TimeStampedModel
import uuid


class UserManager(BaseUserManager):
    """Custom user manager for email-based authentication."""
    
    def create_user(self, email, tenant=None, password=None, **extra_fields):
        if not email:
            raise ValueError('Email is required')
        # Only require tenant for non-superuser/non-staff if needed, 
        # but generally, we want to allow the model to handle the nullability.

        email = self.normalize_email(email)
        user = self.model(email=email, tenant=tenant, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user


    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        
        # Superusers can be tenant-less
        return self.create_user(email, tenant=None, password=password, **extra_fields)



class User(AbstractUser):
    """
    Custom User model with email as the primary identifier.
    """
    # NOTE: the stored value 'instructor' is intentionally kept for backwards
    # compatibility — it is what lives in the DB and is checked throughout the
    # backend/frontend permission logic (e.g. `role == 'instructor'`) and the
    # Course.instructors relation. Only the human-readable label is "Faculty".
    # Do NOT rename the stored value without a data migration + coordinated
    # frontend rollout, or auth/permissions will silently break.
    ROLE_CHOICES = [
        ('student', 'Student'),
        ('instructor', 'Faculty'),
        ('admin', 'Admin'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey('core.Tenant', on_delete=models.CASCADE, related_name='users', null=True, blank=True)

    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='student')
    is_suspended = models.BooleanField(default=False)
    is_email_verified = models.BooleanField(default=False)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    guardian_consent_required = models.BooleanField(default=False)
    guardian_consent_granted_at = models.DateTimeField(null=True, blank=True)
    username = None  # Remove username field
    email = models.EmailField()

    phone = models.CharField(max_length=15, blank=True, null=True)
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)
    
    # Onboarding status
    is_onboarded = models.BooleanField(default=False)
    onboarded_at = models.DateTimeField(null=True, blank=True)
    
    # Preferences
    preferred_language = models.CharField(max_length=10, default='en')
    notification_enabled = models.BooleanField(default=True)
    dark_mode = models.BooleanField(default=False)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_active = models.DateTimeField(auto_now=True)
    
    objects = UserManager()
    
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['first_name', 'last_name']

    class Meta:
        verbose_name = 'User'
        verbose_name_plural = 'Users'
        unique_together = ['email', 'tenant']


    def __str__(self):
        return self.email

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()


class EmailOTP(TimeStampedModel):
    """
    One-time password issued to verify a user's email address.

    Codes are stored hashed (never in plaintext), expire after a short
    window, and are single-use with a capped number of verify attempts.
    """
    PURPOSE_CHOICES = [
        ('email_verification', 'Email Verification'),
        ('password_reset', 'Password Reset'),
    ]

    MAX_ATTEMPTS = 5
    EXPIRY_MINUTES = 10
    RESEND_COOLDOWN_SECONDS = 60

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='email_otps')
    code_hash = models.CharField(max_length=128)
    purpose = models.CharField(max_length=32, choices=PURPOSE_CHOICES, default='email_verification')
    attempts = models.PositiveSmallIntegerField(default=0)
    is_used = models.BooleanField(default=False)
    expires_at = models.DateTimeField()

    class Meta:
        indexes = [
            models.Index(fields=['user', 'purpose', 'is_used']),
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f"OTP({self.purpose}) for {self.user.email}"

    def is_expired(self):
        from django.utils import timezone
        return timezone.now() >= self.expires_at

    def is_valid(self):
        return (
            not self.is_used
            and not self.is_expired()
            and self.attempts < self.MAX_ATTEMPTS
        )


class StudentProfile(TimeStampedModel):
    """
    Extended profile for students preparing for IIT JEE & NEET.
    One profile per user, linked to their target course.
    """
    
    GRADE_CHOICES = [
        ('6', 'Class 6'),
        ('7', 'Class 7'),
        ('8', 'Class 8'),
        ('9', 'Class 9'),
        ('10', 'Class 10'),
        ('11', 'Class 11'),
        ('12', 'Class 12'),
        ('graduate', 'Graduate'),
        ('other', 'Other'),
    ]
    
    BOARD_CHOICES = [
        ('cbse', 'CBSE'),
        ('icse', 'ICSE'),
        ('state', 'State Board'),
        ('ib', 'IB'),
        ('igcse', 'IGCSE'),
        ('other', 'Other'),
    ]
    
    MEDIUM_CHOICES = [
        ('english', 'English'),
        ('hindi', 'Hindi'),
        ('bilingual', 'Bilingual'),
        ('other', 'Other'),
    ]

    GENDER_CHOICES = [
        ('female', 'Female'),
        ('male', 'Male'),
        ('non_binary', 'Non-binary'),
        ('prefer_not_to_say', 'Prefer not to say'),
        ('other', 'Other'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    
    # Personal info
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=32, choices=GENDER_CHOICES, blank=True)
    bio = models.TextField(max_length=500, blank=True)
    instagram_handle = models.CharField(max_length=100, blank=True)
    parent_phone = models.CharField(max_length=15, blank=True)
    
    # Academic info
    grade = models.CharField(max_length=20, choices=GRADE_CHOICES, blank=True)
    school = models.CharField(max_length=200, blank=True)
    coaching = models.CharField(max_length=200, blank=True)
    stream = models.CharField(max_length=100, blank=True)
    board = models.CharField(max_length=20, choices=BOARD_CHOICES, blank=True)
    medium = models.CharField(max_length=20, choices=MEDIUM_CHOICES, default='english')
    target_year = models.PositiveIntegerField(null=True, blank=True)
    
    # Location
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    admission_number = models.CharField(max_length=100, blank=True)
    batch_section = models.CharField(max_length=100, blank=True)
    
    # Study preferences
    daily_study_goal_minutes = models.PositiveIntegerField(default=60)
    preferred_study_time = models.CharField(
        max_length=20,
        choices=[
            ('morning', 'Morning (6AM-12PM)'),
            ('afternoon', 'Afternoon (12PM-6PM)'),
            ('evening', 'Evening (6PM-10PM)'),
            ('night', 'Night (10PM-6AM)'),
        ],
        default='evening'
    )
    
    # Overall stats (denormalized for quick access)
    total_xp = models.PositiveIntegerField(default=0)
    current_level = models.PositiveIntegerField(default=1)
    total_questions_attempted = models.PositiveIntegerField(default=0)
    total_correct_answers = models.PositiveIntegerField(default=0)
    total_study_time_minutes = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'Student Profile'
        verbose_name_plural = 'Student Profiles'

    def __str__(self):
        return f"Profile: {self.user.email}"

    @property
    def overall_accuracy(self):
        if self.total_questions_attempted == 0:
            return 0
        return round((self.total_correct_answers / self.total_questions_attempted) * 100, 2)

    def add_xp(self, xp_amount):
        """Add XP and check for level up."""
        self.total_xp += xp_amount
        new_level = self.calculate_level()
        if new_level > self.current_level:
            self.current_level = new_level
        self.save()
        return self.current_level

    def calculate_level(self):
        """Calculate level based on XP. Each level requires more XP."""
        xp = self.total_xp
        level = 1
        required_xp = 100
        while xp >= required_xp:
            xp -= required_xp
            level += 1
            required_xp = int(required_xp * 1.5)  # Each level needs 50% more XP
        return level

    @property
    def xp_for_next_level(self):
        """Calculate XP needed for next level."""
        level = 1
        required_xp = 100
        total_required = 100
        while level < self.current_level:
            level += 1
            required_xp = int(required_xp * 1.5)
            total_required += required_xp
        return total_required - self.total_xp


class GuardianConsent(TimeStampedModel):
    """Tenant-branded parental approval for an underage student account."""

    STATUS_PENDING = 'pending'
    STATUS_GRANTED = 'granted'
    STATUS_WITHDRAWN = 'withdrawn'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_GRANTED, 'Granted'),
        (STATUS_WITHDRAWN, 'Withdrawn'),
    ]

    # Declared explicitly (rather than relying on TimeStampedModel's abstract
    # field) because consent lookup and token validation are tenant-scoped.
    tenant = models.ForeignKey(
        'core.Tenant', on_delete=models.CASCADE, null=True, blank=True,
        related_name='+',
    )
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name='guardian_consent'
    )
    guardian_name = models.CharField(max_length=200)
    guardian_email = models.EmailField()
    guardian_phone = models.CharField(max_length=15, blank=True)
    relationship = models.CharField(max_length=50)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING
    )
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    email_verified_at = models.DateTimeField(null=True, blank=True)
    granted_at = models.DateTimeField(null=True, blank=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    consent_version = models.CharField(max_length=50, default='1.0')
    consent_text_hash = models.CharField(max_length=64, blank=True)
    verification_method = models.CharField(
        max_length=50, default='verified_email_declaration'
    )

    class Meta:
        ordering = ['-created_at']

    def is_expired(self):
        from django.utils import timezone
        return timezone.now() >= self.expires_at

    def __str__(self):
        return f'Guardian consent for {self.user.email}: {self.status}'


class CourseEnrollment(TimeStampedModel):
    """
    Tracks which courses a student is preparing for.
    Allows multiple course preparations simultaneously.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name='enrollments')
    course = models.ForeignKey('exams.Course', on_delete=models.CASCADE, related_name='enrollments')
    
    # Status
    is_active = models.BooleanField(default=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    enrolled_at = models.DateTimeField(auto_now_add=True)

    # Approval workflow
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='reviewed_enrollments'
    )
    rejection_reason = models.CharField(max_length=255, blank=True, default='')
    
    # Course-specific stats
    course_xp = models.PositiveIntegerField(default=0)
    course_rank = models.PositiveIntegerField(null=True, blank=True)
    
    # Target
    target_score = models.PositiveIntegerField(null=True, blank=True)
    target_rank = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        unique_together = ['student', 'course']
        verbose_name = 'Course Enrollment'
        verbose_name_plural = 'Course Enrollments'

    def __str__(self):
        return f"{self.student.user.email} - {self.course.name}"
