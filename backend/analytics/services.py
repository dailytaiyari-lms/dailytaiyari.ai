"""
Analytics service layer for complex calculations.
"""
from django.db import transaction
from django.db.models import Sum, Avg, Count, F, Q
from django.utils import timezone
from datetime import timedelta
from .models import TopicMastery, SubjectPerformance, DailyActivity, Streak, WeeklyReport, StudySession


class AnalyticsService:
    """
    Service class for analytics calculations and updates.
    """
    
    @staticmethod
    def update_topic_mastery_from_attempt(quiz_attempt):
        """
        Update topic mastery after a quiz attempt.
        """
        from quiz.models import Answer
        
        student = quiz_attempt.student
        answers = quiz_attempt.answers.select_related('question__topic')
        
        # Group answers by topic
        topic_stats = {}
        for answer in answers:
            question = getattr(answer, 'question', None)
            if not question:
                continue
            topic = getattr(question, 'topic', None)
            if not topic:
                continue
            if topic.id not in topic_stats:
                topic_stats[topic.id] = {'correct': 0, 'total': 0, 'time': 0}
            topic_stats[topic.id]['total'] += 1
            if answer.is_correct:
                topic_stats[topic.id]['correct'] += 1
            topic_stats[topic.id]['time'] += answer.time_taken_seconds
        
        # Update mastery for each topic
        for topic_id, stats in topic_stats.items():
            mastery, created = TopicMastery.objects.get_or_create(
                student=student,
                topic_id=topic_id,
                defaults={'tenant': student.user.tenant},
            )
            avg_time = stats['time'] // stats['total'] if stats['total'] > 0 else 0
            mastery.update_mastery(stats['correct'], stats['total'], avg_time)
    
    @staticmethod
    def update_mock_test_analytics(mock_attempt):
        """
        Update analytics after mock test completion.
        """
        student = mock_attempt.student
        
        # Update topic mastery
        AnalyticsService.update_topic_mastery_from_attempt(mock_attempt)
        
        # Update subject performance
        from quiz.models import Answer
        answers = mock_attempt.answers.select_related('question__subject')
        
        subject_stats = {}
        for answer in answers:
            subject = answer.question.subject
            if subject.id not in subject_stats:
                subject_stats[subject.id] = {'correct': 0, 'total': 0}
            
            subject_stats[subject.id]['total'] += 1
            if answer.is_correct:
                subject_stats[subject.id]['correct'] += 1
        
        for subject_id, stats in subject_stats.items():
            perf, created = SubjectPerformance.objects.get_or_create(
                student=student,
                subject_id=subject_id,
                course=mock_attempt.mock_test.course,
                defaults={'tenant': student.user.tenant},
            )
            perf.total_questions += stats['total']
            perf.correct_answers += stats['correct']
            if perf.total_questions > 0:
                perf.accuracy = (perf.correct_answers / perf.total_questions) * 100
            perf.save()
    
    @staticmethod
    def update_daily_activity(student, **kwargs):
        """
        Update daily activity record.

        Wrapped in a transaction with a row lock so concurrent updates
        (e.g. quiz submit + study heartbeat) accumulate instead of clobbering.
        """
        today = timezone.now().date()
        with transaction.atomic():
            DailyActivity.objects.get_or_create(
                student=student, date=today,
                defaults={'tenant': student.user.tenant},
            )
            activity = DailyActivity.objects.select_for_update().get(
                student=student, date=today
            )

            for field, value in kwargs.items():
                if hasattr(activity, field):
                    current_value = getattr(activity, field)
                    if isinstance(current_value, int):
                        setattr(activity, field, current_value + value)
                    else:
                        setattr(activity, field, value)

            # Check if daily goal met
            if activity.study_time_minutes >= student.daily_study_goal_minutes:
                activity.daily_goal_met = True

            activity.save()

        # Update streak
        AnalyticsService.update_streak(student, today)

        return activity
    
    @staticmethod
    def update_streak(student, activity_date, course=None):
        """
        Update study streak.
        """
        streak, created = Streak.objects.get_or_create(
            student=student,
            course=course,
            defaults={'tenant': student.user.tenant},
        )
        streak.update_streak(activity_date)
        return streak
    
    @staticmethod
    def get_dashboard_stats(student, course=None):
        """
        Get comprehensive dashboard statistics.
        """
        today = timezone.now().date()
        week_ago = today - timedelta(days=7)
        
        # Get streak
        streak = Streak.objects.filter(student=student, course=course).first()
        current_streak = streak.current_streak if streak else 0
        
        # Today's activity (for questions, accuracy)
        today_activity = DailyActivity.objects.filter(
            student=student,
            date=today
        ).first()
        
        # Today's study session (for real-time time tracking)
        today_session = StudySession.objects.filter(
            student=student,
            date=today
        ).first()
        
        # Calculate study time from StudySession (in minutes)
        today_study_time = (today_session.total_seconds_today // 60) if today_session else 0
        
        # Calculate goal progress from StudySession
        if today_session:
            goal_progress = min(100, today_session.progress_percentage)
            goal_met = today_session.goal_achieved
        else:
            goal_progress = 0
            goal_met = False
        
        # Weekly stats
        weekly_activities = DailyActivity.objects.filter(
            student=student,
            date__gte=week_ago
        ).aggregate(
            total_time=Sum('study_time_minutes'),
            total_questions=Sum('questions_attempted'),
            total_correct=Sum('questions_correct'),
            total_xp=Sum('xp_earned'),
            days_active=Count('id')
        )
        
        # Weekly study time from StudySession (more accurate)
        weekly_sessions = StudySession.objects.filter(
            student=student,
            date__gte=week_ago
        ).aggregate(
            total_seconds=Sum('total_seconds_today')
        )
        weekly_study_time = (weekly_sessions['total_seconds'] or 0) // 60
        
        # Topic mastery summary
        mastery_summary = TopicMastery.objects.filter(student=student).aggregate(
            total_topics=Count('id'),
            mastered_topics=Count('id', filter=Q(mastery_level__gte=4)),
            weak_topics=Count('id', filter=Q(mastery_level__lte=2)),
            level_1=Count('id', filter=Q(mastery_level=1)),
            level_2=Count('id', filter=Q(mastery_level=2)),
            level_3=Count('id', filter=Q(mastery_level=3)),
            level_4=Count('id', filter=Q(mastery_level=4)),
            level_5=Count('id', filter=Q(mastery_level=5)),
        )
        
        # Get weak topics for revision
        weak_topics = TopicMastery.objects.filter(
            student=student,
            mastery_level__lte=2
        ).select_related('topic').order_by('mastery_level')[:5]
        
        return {
            'current_streak': current_streak,
            'longest_streak': streak.longest_streak if streak else 0,
            'today': {
                'study_time': today_study_time,
                'questions': today_activity.questions_attempted if today_activity else 0,
                'accuracy': (today_activity.questions_correct / today_activity.questions_attempted * 100) 
                           if today_activity and today_activity.questions_attempted > 0 else 0,
                'goal_progress': goal_progress,
                'goal_met': goal_met
            },
            'weekly': {
                'study_time': weekly_study_time,
                'questions': weekly_activities['total_questions'] or 0,
                'accuracy': (weekly_activities['total_correct'] / weekly_activities['total_questions'] * 100)
                           if weekly_activities['total_questions'] else 0,
                'xp_earned': weekly_activities['total_xp'] or 0,
                'days_active': weekly_activities['days_active'] or 0
            },
            'mastery': {
                'total_topics': mastery_summary['total_topics'] or 0,
                'mastered': mastery_summary['mastered_topics'] or 0,
                'weak': mastery_summary['weak_topics'] or 0,
                'distribution': {
                    'beginner': mastery_summary['level_1'] or 0,
                    'developing': mastery_summary['level_2'] or 0,
                    'proficient': mastery_summary['level_3'] or 0,
                    'expert': mastery_summary['level_4'] or 0,
                    'master': mastery_summary['level_5'] or 0,
                },
                'weak_topics': [
                    {'id': str(tm.topic.id), 'name': tm.topic.name, 'level': tm.mastery_level}
                    for tm in weak_topics
                ]
            },
            'profile': {
                'total_xp': student.total_xp,
                'level': student.current_level,
                'xp_for_next_level': student.xp_for_next_level,
                'overall_accuracy': student.overall_accuracy,
                'total_questions': student.total_questions_attempted,
                'total_correct': student.total_correct_answers,
                'total_study_time': student.total_study_time_minutes
            }
        }
    
    @staticmethod
    def generate_weekly_report(student):
        """
        Generate weekly performance report.
        """
        today = timezone.now().date()
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)
        
        # Check if report already exists
        existing = WeeklyReport.objects.filter(
            student=student,
            week_start=week_start
        ).first()
        
        if existing:
            return AnalyticsService.update_weekly_report(existing)
        
        # Get daily activities for the week
        activities = DailyActivity.objects.filter(
            student=student,
            date__gte=week_start,
            date__lte=week_end
        )
        
        # Aggregate stats
        stats = activities.aggregate(
            questions=Sum('questions_attempted'),
            correct=Sum('questions_correct'),
            xp=Sum('xp_earned'),
            days=Count('id'),
            goals=Count('id', filter=Q(daily_goal_met=True))
        )
        
        # Get study time from StudySession (more accurate real-time tracking)
        study_sessions = StudySession.objects.filter(
            student=student,
            date__gte=week_start,
            date__lte=week_end
        ).aggregate(
            total_seconds=Sum('total_seconds_today')
        )
        total_study_minutes = (study_sessions['total_seconds'] or 0) // 60
        
        # Get weak topics
        weak = TopicMastery.objects.filter(
            student=student,
            mastery_level__lte=2
        ).values_list('topic_id', flat=True)[:10]
        
        # Create report
        report = WeeklyReport.objects.create(
            student=student,
            tenant=student.user.tenant,
            week_start=week_start,
            week_end=week_end,
            total_study_minutes=total_study_minutes,
            questions_attempted=stats['questions'] or 0,
            questions_correct=stats['correct'] or 0,
            accuracy=(stats['correct'] / stats['questions'] * 100) if stats['questions'] else 0,
            days_active=stats['days'] or 0,
            goals_met=stats['goals'] or 0,
            xp_earned=stats['xp'] or 0,
            weak_topics=list(map(str, weak))
        )
        
        return report
    
    @staticmethod
    def update_weekly_report(report):
        """
        Update an existing weekly report with fresh data.
        Used to ensure the report reflects the latest activity.
        """
        student = report.student
        week_start = report.week_start
        week_end = report.week_end
        
        # Get daily activities for the week
        activities = DailyActivity.objects.filter(
            student=student,
            date__gte=week_start,
            date__lte=week_end
        )
        
        # Aggregate stats
        stats = activities.aggregate(
            questions=Sum('questions_attempted'),
            correct=Sum('questions_correct'),
            xp=Sum('xp_earned'),
            days=Count('id'),
            goals=Count('id', filter=Q(daily_goal_met=True))
        )
        
        # Get study time from StudySession (more accurate real-time tracking)
        study_sessions = StudySession.objects.filter(
            student=student,
            date__gte=week_start,
            date__lte=week_end
        ).aggregate(
            total_seconds=Sum('total_seconds_today')
        )
        total_study_minutes = (study_sessions['total_seconds'] or 0) // 60
        
        # Get weak topics
        weak = TopicMastery.objects.filter(
            student=student,
            mastery_level__lte=2
        ).values_list('topic_id', flat=True)[:10]
        
        # Update report with fresh data
        report.total_study_minutes = total_study_minutes
        report.questions_attempted = stats['questions'] or 0
        report.questions_correct = stats['correct'] or 0
        report.accuracy = (stats['correct'] / stats['questions'] * 100) if stats['questions'] else 0
        report.days_active = stats['days'] or 0
        report.goals_met = stats['goals'] or 0
        report.xp_earned = stats['xp'] or 0
        report.weak_topics = list(map(str, weak))
        report.save()
        
        return report

    @staticmethod
    def get_tenant_admin_stats(tenant, period_days=30):
        """
        Get aggregated statistics for all students in a tenant.

        ``period_days`` controls the growth window (e.g. 7, 30, 90) used for
        new-signup counts, active-user counts and the activity trend chart.
        Growth metrics compare the selected window against the immediately
        preceding window of the same length.
        """
        from users.models import StudentProfile
        from django.db.models import Count, Avg, Sum

        # Sanitise the requested window.
        try:
            period_days = int(period_days)
        except (TypeError, ValueError):
            period_days = 30
        period_days = max(1, min(period_days, 365))

        now = timezone.now()
        today = now.date()
        window_start = now - timedelta(days=period_days)
        prev_window_start = now - timedelta(days=period_days * 2)

        def _pct_change(current, previous):
            """Percent change vs previous period (None when no baseline)."""
            if previous:
                return round(((current - previous) / previous) * 100, 1)
            if current:
                return None  # growth from zero baseline is undefined
            return 0.0

        # Base queryset for students in this tenant
        students = StudentProfile.objects.filter(user__tenant=tenant)
        total_students = students.count()

        # New signups within the selected window vs the previous window.
        new_signups = students.filter(user__date_joined__gte=window_start).count()
        prev_new_signups = students.filter(
            user__date_joined__gte=prev_window_start,
            user__date_joined__lt=window_start,
        ).count()
        signup_change_pct = _pct_change(new_signups, prev_new_signups)

        # Active students within the selected window vs the previous window.
        active_in_period = DailyActivity.objects.filter(
            student__user__tenant=tenant,
            date__gte=window_start.date(),
        ).values('student').distinct().count()
        prev_active_in_period = DailyActivity.objects.filter(
            student__user__tenant=tenant,
            date__gte=prev_window_start.date(),
            date__lt=window_start.date(),
        ).values('student').distinct().count()
        active_change_pct = _pct_change(active_in_period, prev_active_in_period)

        growth = {
            'period_days': period_days,
            'new_signups': new_signups,
            'prev_new_signups': prev_new_signups,
            'signup_change_pct': signup_change_pct,
            'active_in_period': active_in_period,
            'prev_active_in_period': prev_active_in_period,
            'active_change_pct': active_change_pct,
            'total_students_start': max(total_students - new_signups, 0),
        }

        if total_students == 0:
            return {
                'total_students': 0,
                'active_today': 0,
                'avg_accuracy': 0,
                'total_xp': 0,
                'level_distribution': {},
                'activity_trend': [],
                'growth': growth,
            }

        # Active today (activity in last 24h)
        active_today = DailyActivity.objects.filter(
            student__user__tenant=tenant,
            date=today
        ).values('student').distinct().count()

        # Overall performance
        # Total XP from all students
        total_xp = students.aggregate(total=Sum('total_xp'))['total'] or 0
        
        # Avg accuracy only from students who have attempted questions
        performance = students.filter(total_questions_attempted__gt=0).aggregate(
            avg_accuracy=Avg(F('total_correct_answers') * 100.0 / F('total_questions_attempted'))
        )
        avg_accuracy = performance['avg_accuracy'] or 0

        # Level distribution
        level_dist = students.values('current_level').annotate(count=Count('id')).order_by('current_level')
        level_distribution = {str(item['current_level']): item['count'] for item in level_dist}

        # Activity trend (over the selected window)
        trend_start = window_start.date()
        trend_data = DailyActivity.objects.filter(
            student__user__tenant=tenant,
            date__gte=trend_start
        ).values('date').annotate(
            active_users=Count('student', distinct=True),
            total_questions=Sum('questions_attempted'),
            total_time=Sum('study_time_minutes')
        ).order_by('date')

        activity_trend = [
            {
                'date': item['date'].strftime('%Y-%m-%d'),
                'active_users': item['active_users'],
                'total_questions': item['total_questions'],
                'total_time': item['total_time']
            }
            for item in trend_data
        ]

        return {
            'total_students': total_students,
            'active_today': active_today,
            'avg_accuracy': round(avg_accuracy, 2),
            'total_xp': total_xp,
            'level_distribution': level_distribution,
            'activity_trend': activity_trend,
            'growth': growth,
        }

    @staticmethod
    def get_tenant_subject_performance(tenant):
        """
        Get aggregated performance data per subject for the tenant.
        """
        from django.db.models import Avg, Count
        
        # Aggregate stats from SubjectPerformance for students in this tenant
        stats = SubjectPerformance.objects.filter(
            student__user__tenant=tenant
        ).values(
            'subject__name'
        ).annotate(
            avg_accuracy=Avg('accuracy'),
            total_students=Count('student', distinct=True),
            avg_study_minutes=Avg('total_study_minutes')
        ).order_by('-avg_accuracy')
        
        return [
            {
                'subject': item['subject__name'],
                'accuracy': round(item['avg_accuracy'] or 0, 2),
                'student_count': item['total_students'],
                'avg_study_minutes': round(item['avg_study_minutes'] or 0, 1)
            }
            for item in stats
        ]

    @staticmethod
    def get_tenant_leaderboard(tenant, limit=10):
        """
        Get top performing students in the tenant.
        """
        from users.models import StudentProfile
        
        top_students = StudentProfile.objects.filter(
            user__tenant=tenant
        ).select_related('user').order_by('-total_xp')[:limit]
        
        return [
            {
                'id': str(student.id),
                'name': student.user.full_name,
                'avatar': student.user.avatar.url if student.user.avatar else None,
                'xp': student.total_xp,
                'level': student.current_level,
                'accuracy': student.overall_accuracy
            }
            for student in top_students
        ]

