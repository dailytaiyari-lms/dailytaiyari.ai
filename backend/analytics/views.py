"""
Views for Analytics app.
"""
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.utils import timezone
from datetime import timedelta

from .models import TopicMastery, SubjectPerformance, DailyActivity, Streak, WeeklyReport, StudySession
from .serializers import (
    TopicMasterySerializer, SubjectPerformanceSerializer,
    DailyActivitySerializer, StreakSerializer, WeeklyReportSerializer,
    DashboardStatsSerializer, PerformanceChartSerializer
)
from .services import AnalyticsService
from gamification.services import GamificationService
from core.views import TenantAwareReadOnlyViewSet
from core.permissions import IsTenantAdmin



class DashboardView(APIView):
    """
    Get comprehensive dashboard statistics.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        student = request.user.profile
        course_id = request.query_params.get('course_id')
        
        stats = AnalyticsService.get_dashboard_stats(student, course_id)
        serializer = DashboardStatsSerializer(stats)
        
        return Response(serializer.data)


class TopicMasteryViewSet(TenantAwareReadOnlyViewSet):
    """
    ViewSet for topic mastery data.
    """
    serializer_class = TopicMasterySerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return TopicMastery.objects.filter(
            student=self.request.user.profile
        ).select_related('topic', 'topic__subject')

    @action(detail=False, methods=['get'])
    def weak_topics(self, request):
        """Get topics that need revision."""
        topics = self.get_queryset().filter(
            mastery_level__lte=2
        ).order_by('mastery_level', '-last_attempted')[:10]
        
        return Response(TopicMasterySerializer(topics, many=True).data)

    @action(detail=False, methods=['get'])
    def strong_topics(self, request):
        """Get mastered topics."""
        topics = self.get_queryset().filter(
            mastery_level__gte=4
        ).order_by('-mastery_level', '-mastery_score')[:10]
        
        return Response(TopicMasterySerializer(topics, many=True).data)

    @action(detail=False, methods=['get'])
    def by_subject(self, request):
        """Get topic mastery grouped by subject."""
        subject_id = request.query_params.get('subject_id')
        if not subject_id:
            return Response(
                {'error': 'subject_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        topics = self.get_queryset().filter(
            topic__subject_id=subject_id
        ).order_by('topic__order')
        
        return Response(TopicMasterySerializer(topics, many=True).data)


class SubjectPerformanceViewSet(TenantAwareReadOnlyViewSet):
    """
    ViewSet for subject performance data.
    """
    serializer_class = SubjectPerformanceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return SubjectPerformance.objects.filter(
            student=self.request.user.profile
        ).select_related('subject', 'course')

    @action(detail=False, methods=['get'])
    def by_course(self, request):
        """Get performance for all subjects in an course."""
        course_id = request.query_params.get('course_id')
        if not course_id:
            return Response(
                {'error': 'course_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        performances = self.get_queryset().filter(course_id=course_id)
        return Response(SubjectPerformanceSerializer(performances, many=True).data)


class DailyActivityViewSet(TenantAwareReadOnlyViewSet):
    """
    ViewSet for daily activity data.
    """
    serializer_class = DailyActivitySerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return DailyActivity.objects.filter(
            student=self.request.user.profile
        ).order_by('-date')

    @action(detail=False, methods=['get'])
    def today(self, request):
        """Get today's activity."""
        today = timezone.now().date()
        activity = self.get_queryset().filter(date=today).first()
        
        if not activity:
            return Response({
                'date': str(today),
                'study_time_minutes': 0,
                'questions_attempted': 0,
                'questions_correct': 0,
                'accuracy': 0,
                'daily_goal_met': False
            })
        
        return Response(DailyActivitySerializer(activity).data)

    @action(detail=False, methods=['get'])
    def weekly(self, request):
        """Get last 7 days activity."""
        week_ago = timezone.now().date() - timedelta(days=7)
        activities = self.get_queryset().filter(date__gte=week_ago)
        
        return Response(DailyActivitySerializer(activities, many=True).data)

    @action(detail=False, methods=['get'])
    def chart_data(self, request):
        """Get data for performance charts."""
        days = int(request.query_params.get('days', 7))
        start_date = timezone.now().date() - timedelta(days=days)
        
        activities = self.get_queryset().filter(
            date__gte=start_date
        ).order_by('date')
        
        labels = []
        accuracy = []
        questions = []
        study_time = []
        
        for activity in activities:
            labels.append(activity.date.strftime('%b %d'))
            accuracy.append(
                round(activity.questions_correct / activity.questions_attempted * 100, 2)
                if activity.questions_attempted > 0 else 0
            )
            questions.append(activity.questions_attempted)
            study_time.append(activity.study_time_minutes)
        
        return Response({
            'labels': labels,
            'accuracy': accuracy,
            'questions': questions,
            'study_time': study_time
        })


class StreakViewSet(TenantAwareReadOnlyViewSet):
    """
    ViewSet for streak data.
    """
    serializer_class = StreakSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Streak.objects.filter(
            student=self.request.user.profile
        ).select_related('course')

    @action(detail=False, methods=['get'])
    def current(self, request):
        """Get current active streak."""
        course_id = request.query_params.get('course_id')
        streak = self.get_queryset().filter(course_id=course_id).first()
        
        if not streak:
            return Response({
                'current_streak': 0,
                'longest_streak': 0,
                'total_active_days': 0
            })
        
        return Response(StreakSerializer(streak).data)


class WeeklyReportViewSet(TenantAwareReadOnlyViewSet):
    """
    ViewSet for weekly reports.
    """
    serializer_class = WeeklyReportSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return WeeklyReport.objects.filter(
            student=self.request.user.profile
        ).order_by('-week_start')

    @action(detail=False, methods=['get'])
    def latest(self, request):
        """Get the latest weekly report for the current week."""
        from datetime import timedelta
        
        today = timezone.now().date()
        current_week_start = today - timedelta(days=today.weekday())
        
        # Check if we have a report for the current week
        current_week_report = self.get_queryset().filter(
            week_start=current_week_start
        ).first()
        
        if current_week_report:
            # Update the report with fresh data (in case activity happened since report was created)
            report = AnalyticsService.update_weekly_report(current_week_report)
        else:
            # Generate new report for current week
            report = AnalyticsService.generate_weekly_report(request.user.profile)
        
        return Response(WeeklyReportSerializer(report).data)

    @action(detail=False, methods=['post'])
    def generate(self, request):
        """Generate a new weekly report."""
        report = AnalyticsService.generate_weekly_report(request.user.profile)
        return Response(WeeklyReportSerializer(report).data)


class StudyTimerView(APIView):
    """
    Real-time study timer tracking.
    Handles starting, updating, and pausing study sessions.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        """Get current study session state."""
        student = request.user.profile
        today = timezone.now().date()
        
        session, created = StudySession.objects.get_or_create(
            student=student,
            date=today,
            defaults={
                'goal_seconds': student.daily_study_goal_minutes * 60,
                'tenant': student.user.tenant,
            }
        )

        return Response({
            'date': str(session.date),
            'total_seconds_today': session.total_seconds_today,
            'goal_seconds': session.goal_seconds,
            'remaining_seconds': session.remaining_seconds,
            'progress_percentage': round(session.progress_percentage, 2),
            'goal_achieved': session.goal_achieved,
            'goal_achieved_at': session.goal_achieved_at.isoformat() if session.goal_achieved_at else None,
            'exceeded_goal': session.exceeded_goal,
            'is_active': session.is_active,
            'goal_minutes': session.goal_seconds // 60,
            'total_minutes_today': session.total_seconds_today // 60,
        })

    def post(self, request):
        """Start or resume a study session."""
        student = request.user.profile
        today = timezone.now().date()
        
        session, created = StudySession.objects.get_or_create(
            student=student,
            date=today,
            defaults={
                'goal_seconds': student.daily_study_goal_minutes * 60,
                'tenant': student.user.tenant,
            }
        )

        session.is_active = True
        session.session_started_at = timezone.now()
        session.last_heartbeat = timezone.now()
        session.save()
        
        return Response({
            'message': 'Session started',
            'total_seconds_today': session.total_seconds_today,
            'goal_seconds': session.goal_seconds,
            'remaining_seconds': session.remaining_seconds,
            'progress_percentage': round(session.progress_percentage, 2),
        })

    def put(self, request):
        """
        Update study session with elapsed time (heartbeat).
        Called periodically while user is active on the site.
        """
        student = request.user.profile
        today = timezone.now().date()
        
        elapsed_seconds = request.data.get('elapsed_seconds', 0)
        
        try:
            session = StudySession.objects.get(student=student, date=today)
        except StudySession.DoesNotExist:
            return Response(
                {'error': 'No active session found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Update session
        previous_total = session.total_seconds_today
        session.total_seconds_today += elapsed_seconds
        session.last_heartbeat = timezone.now()
        
        # Check if goal was just achieved
        goal_just_achieved = False
        xp_awarded = 0
        streak_updated = False
        
        if not session.goal_achieved and session.total_seconds_today >= session.goal_seconds:
            session.goal_achieved = True
            session.goal_achieved_at = timezone.now()
            goal_just_achieved = True
            
            # Award XP for achieving daily goal: 25 base + streak bonus (3/day, max +25)
            if not session.goal_xp_awarded:
                # Update streak first so the bonus reflects today's achievement
                AnalyticsService.update_streak(student, today, None)
                streak_updated = True

                from analytics.models import Streak
                streak_obj = Streak.objects.filter(student=student).order_by('-current_streak').first()
                current_streak = streak_obj.current_streak if streak_obj else 0
                streak_bonus = min(25, current_streak * 3)
                xp_awarded = 25 + streak_bonus

                GamificationService.award_xp(
                    student,
                    xp_awarded,
                    'daily_goal',
                    f'Achieved daily study goal of {session.goal_seconds // 60} minutes'
                    + (f' (+{streak_bonus} streak bonus)' if streak_bonus else ''),
                    str(session.id),
                    update_daily_activity=True
                )
                session.goal_xp_awarded = True

                # Mark daily activity goal as met
                DailyActivity.objects.filter(
                    student=student,
                    date=today
                ).update(daily_goal_met=True)
        
        session.save()
        
        # Also update DailyActivity study_time
        AnalyticsService.update_daily_activity(
            student,
            study_time_minutes=elapsed_seconds // 60 if elapsed_seconds >= 60 else 0
        )
        
        return Response({
            'total_seconds_today': session.total_seconds_today,
            'goal_seconds': session.goal_seconds,
            'remaining_seconds': session.remaining_seconds,
            'progress_percentage': round(session.progress_percentage, 2),
            'goal_achieved': session.goal_achieved,
            'goal_just_achieved': goal_just_achieved,
            'exceeded_goal': session.exceeded_goal,
            'xp_awarded': xp_awarded,
            'streak_updated': streak_updated,
        })

    def delete(self, request):
        """Pause/stop the study session."""
        student = request.user.profile
        today = timezone.now().date()
        
        try:
            session = StudySession.objects.get(student=student, date=today)
            session.is_active = False
            session.save()
            
            return Response({
                'message': 'Session paused',
                'total_seconds_today': session.total_seconds_today,
            })
        except StudySession.DoesNotExist:
            return Response({'message': 'No active session'})


class StudyGoalView(APIView):
    """
    Manage user's daily study goal.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        """Get current study goal settings."""
        student = request.user.profile
        return Response({
            'daily_study_goal_minutes': student.daily_study_goal_minutes,
        })

    def put(self, request):
        """Update study goal."""
        student = request.user.profile
        new_goal = request.data.get('daily_study_goal_minutes')
        
        if not new_goal or new_goal < 5:
            return Response(
                {'error': 'Goal must be at least 5 minutes'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if new_goal > 480:  # Max 8 hours
            return Response(
                {'error': 'Goal cannot exceed 8 hours'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        student.daily_study_goal_minutes = new_goal
        student.save(update_fields=['daily_study_goal_minutes'])
        
        # Update today's session if exists
        today = timezone.now().date()
        StudySession.objects.filter(
            student=student,
            date=today
        ).update(goal_seconds=new_goal * 60)
        
        return Response({
            'message': 'Goal updated',
            'daily_study_goal_minutes': new_goal,
        })


class TenantAdminStatsView(APIView):
    """
    Get aggregated statistics for the entire tenant.
    Only accessible by tenant admins.
    """
    permission_classes = [permissions.IsAuthenticated, IsTenantAdmin]

    def get(self, request):
        if not request.tenant:
            return Response(
                {'error': 'Tenant context is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            period_days = int(request.query_params.get('days', 30))
        except (TypeError, ValueError):
            period_days = 30

        stats = AnalyticsService.get_tenant_admin_stats(request.tenant, period_days=period_days)
        return Response(stats)


class TenantSubjectStatsView(APIView):
    """
    Get subject-wise performance for the tenant.
    """
    permission_classes = [permissions.IsAuthenticated, IsTenantAdmin]

    def get(self, request):
        if not request.tenant:
            return Response(
                {'error': 'Tenant context is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        stats = AnalyticsService.get_tenant_subject_performance(request.tenant)
        return Response(stats)


class TenantLeaderboardView(APIView):
    """
    Get top students leaderboard for the tenant.
    """
    permission_classes = [permissions.IsAuthenticated, IsTenantAdmin]

    def get(self, request):
        if not request.tenant:
            return Response(
                {'error': 'Tenant context is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        limit = int(request.query_params.get('limit', 10))
        stats = AnalyticsService.get_tenant_leaderboard(request.tenant, limit=limit)
        return Response(stats)


