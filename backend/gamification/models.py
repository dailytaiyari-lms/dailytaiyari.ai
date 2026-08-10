"""
Gamification models - XP, Badges, Achievements, Leaderboards.
"""
from django.db import models
from core.models import TimeStampedModel
from exams.models import Course


class Badge(TimeStampedModel):
    """
    Achievement badges that students can earn.
    """
    BADGE_CATEGORIES = [
        ('streak', 'Streak Badges'),
        ('quiz', 'Quiz Badges'),
        ('mastery', 'Mastery Badges'),
        ('milestone', 'Milestone Badges'),
        ('special', 'Special Badges'),
    ]
    
    RARITY_CHOICES = [
        ('common', 'Common'),
        ('uncommon', 'Uncommon'),
        ('rare', 'Rare'),
        ('epic', 'Epic'),
        ('legendary', 'Legendary'),
    ]

    name = models.CharField(max_length=100)
    description = models.TextField()
    category = models.CharField(max_length=20, choices=BADGE_CATEGORIES)
    rarity = models.CharField(max_length=20, choices=RARITY_CHOICES, default='common')
    
    # Visual
    icon = models.CharField(max_length=50)  # Icon name or emoji
    color = models.CharField(max_length=7, default='#FFD700')  # Hex color
    image = models.ImageField(upload_to='badges/', blank=True, null=True)
    
    # Requirements (JSON for flexibility)
    requirements = models.JSONField(default=dict)
    # Example: {"streak_days": 7} or {"quizzes_completed": 10}
    
    # Reward
    xp_reward = models.PositiveIntegerField(default=0)
    
    # Status
    is_active = models.BooleanField(default=True)
    is_secret = models.BooleanField(default=False)  # Hidden until earned

    class Meta:
        verbose_name = 'Badge'
        verbose_name_plural = 'Badges'

    def __str__(self):
        return f"{self.name} ({self.rarity})"


class StudentBadge(TimeStampedModel):
    """
    Badges earned by students.
    """
    student = models.ForeignKey(
        'users.StudentProfile', 
        on_delete=models.CASCADE, 
        related_name='badges'
    )
    badge = models.ForeignKey(Badge, on_delete=models.CASCADE, related_name='earned_by')
    
    # When earned
    earned_at = models.DateTimeField(auto_now_add=True)
    
    # Progress (for partial completion tracking)
    progress = models.JSONField(default=dict)
    is_complete = models.BooleanField(default=True)

    class Meta:
        unique_together = ['student', 'badge']
        verbose_name = 'Student Badge'
        verbose_name_plural = 'Student Badges'

    def __str__(self):
        return f"{self.student.user.email} - {self.badge.name}"


class XPTransaction(TimeStampedModel):
    """
    Records all XP earned/spent.
    """
    TRANSACTION_TYPES = [
        ('quiz_complete', 'Quiz Completed'),
        ('mock_complete', 'Mock Test Completed'),
        ('content_complete', 'Content Completed'),
        ('ai_quiz', 'AI Quiz Completed'),
        ('coding_solved', 'Coding Problem Solved'),
        ('assignment_graded', 'Assignment Graded'),
        ('notebook_graded', 'Notebook Completed'),
        ('daily_goal', 'Daily Goal Met'),
        ('streak_bonus', 'Streak Bonus'),
        ('badge_earned', 'Badge Earned'),
        ('level_up', 'Level Up Bonus'),
        ('referral', 'Referral Bonus'),
        ('challenge_win', 'Challenge Won'),
        ('community', 'Community Activity'),
        ('manual', 'Manual Adjustment'),
    ]

    student = models.ForeignKey(
        'users.StudentProfile', 
        on_delete=models.CASCADE, 
        related_name='xp_transactions'
    )
    
    transaction_type = models.CharField(max_length=30, choices=TRANSACTION_TYPES)
    xp_amount = models.IntegerField()  # Can be negative for deductions
    
    # Reference
    description = models.CharField(max_length=200, blank=True)
    reference_id = models.UUIDField(null=True, blank=True)  # Quiz/MockTest/Badge ID
    
    # Balance tracking
    balance_after = models.PositiveIntegerField()

    class Meta:
        verbose_name = 'XP Transaction'
        verbose_name_plural = 'XP Transactions'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.student.user.email}: {self.xp_amount:+d} XP ({self.transaction_type})"


class LeaderboardEntry(TimeStampedModel):
    """
    Leaderboard entries for different timeframes and exams.
    """
    PERIOD_CHOICES = [
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
        ('all_time', 'All Time'),
    ]

    student = models.ForeignKey(
        'users.StudentProfile', 
        on_delete=models.CASCADE, 
        related_name='leaderboard_entries'
    )
    course = models.ForeignKey(
        Course, 
        on_delete=models.CASCADE, 
        related_name='leaderboard_entries',
        null=True, blank=True  # null = global leaderboard
    )
    
    period = models.CharField(max_length=20, choices=PERIOD_CHOICES)
    period_start = models.DateField()
    period_end = models.DateField()
    
    # Metrics
    xp_earned = models.PositiveIntegerField(default=0)
    questions_answered = models.PositiveIntegerField(default=0)
    accuracy = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    study_time_minutes = models.PositiveIntegerField(default=0)
    
    # Ranking
    rank = models.PositiveIntegerField()
    previous_rank = models.PositiveIntegerField(null=True, blank=True)
    rank_change = models.IntegerField(default=0)

    class Meta:
        unique_together = ['student', 'course', 'period', 'period_start']
        verbose_name = 'Leaderboard Entry'
        verbose_name_plural = 'Leaderboard Entries'
        indexes = [
            models.Index(fields=['period', 'course', 'rank']),
            models.Index(fields=['period_start', 'period_end']),
        ]

    def __str__(self):
        return f"{self.student.user.email} - Rank {self.rank} ({self.period})"


class Challenge(TimeStampedModel):
    """
    Special challenges for extra XP and badges.
    """
    CHALLENGE_TYPES = [
        ('daily', 'Daily Challenge'),
        ('weekly', 'Weekly Challenge'),
        ('event', 'Special Event'),
        ('competition', 'Competition'),
    ]
    
    STATUS_CHOICES = [
        ('upcoming', 'Upcoming'),
        ('active', 'Active'),
        ('ended', 'Ended'),
    ]

    title = models.CharField(max_length=200)
    description = models.TextField()
    challenge_type = models.CharField(max_length=20, choices=CHALLENGE_TYPES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='upcoming')
    
    # Target course (optional)
    course = models.ForeignKey(
        Course, 
        on_delete=models.CASCADE, 
        related_name='challenges',
        null=True, blank=True
    )
    
    # Timing
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    
    # Goals
    goal = models.JSONField(default=dict)
    # Example: {"questions": 50, "accuracy": 80}
    
    # Rewards
    xp_reward = models.PositiveIntegerField(default=100)
    badge_reward = models.ForeignKey(
        Badge, 
        on_delete=models.SET_NULL, 
        null=True, blank=True,
        related_name='challenges'
    )
    
    # Stats
    participants = models.PositiveIntegerField(default=0)
    completers = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'Challenge'
        verbose_name_plural = 'Challenges'

    def __str__(self):
        return self.title


class ChallengeParticipation(TimeStampedModel):
    """
    Student participation in challenges.
    """
    student = models.ForeignKey(
        'users.StudentProfile', 
        on_delete=models.CASCADE, 
        related_name='challenge_participations'
    )
    challenge = models.ForeignKey(
        Challenge, 
        on_delete=models.CASCADE, 
        related_name='participations'
    )
    
    # Progress
    progress = models.JSONField(default=dict)
    is_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    # Rewards claimed
    xp_claimed = models.PositiveIntegerField(default=0)
    badge_claimed = models.BooleanField(default=False)
    
    # Ranking (for competitions)
    final_rank = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        unique_together = ['student', 'challenge']
        verbose_name = 'Challenge Participation'
        verbose_name_plural = 'Challenge Participations'

    def __str__(self):
        return f"{self.student.user.email} - {self.challenge.title}"

