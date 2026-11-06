"""
Views for Content app.
"""
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from django.utils import timezone
from django.db.models import Q
from django.http import FileResponse, Http404

from .models import Content, ContentProgress, StudyPlan, StudyPlanItem
from .serializers import (
    ContentSerializer, ContentDetailSerializer,
    ContentProgressSerializer, StudyPlanSerializer,
    StudyPlanItemSerializer, DailyStudyPlanSerializer
)
from .services import StudyPlanService
from core.views import TenantAwareViewSet, TenantAwareReadOnlyViewSet


class ContentViewSet(TenantAwareReadOnlyViewSet):
    """
    ViewSet for content operations.
    """
    lookup_value_regex = '[0-9a-f-]{36}'
    queryset = Content.objects.filter(status='published')
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['topic', 'subject', 'content_type', 'difficulty', 'is_free']
    search_fields = ['title', 'description']
    ordering_fields = ['order', 'views_count', 'created_at']

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return ContentDetailSerializer
        return ContentSerializer

    def get_queryset(self):
        tenant = getattr(self.request, 'tenant', None)
        if tenant is None:
            return self.queryset.none()
        queryset = self.queryset.filter(subject__course__tenant=tenant)
        user = self.request.user

        if user.is_superuser or getattr(user, 'role', None) == 'admin':
            return queryset

        if getattr(user, 'role', None) == 'instructor':
            return queryset.filter(subject__course__in=user.instructing_courses.all())

        # Scope to every course the student is actively enrolled in, not just
        # their primary course, so multi-course students can open content from
        # any of their enrolled courses. A student with no approved active
        # enrollment must receive an empty queryset, never all tenant content.
        student = getattr(user, 'profile', None)
        if student is None:
            return queryset.none()
        enrolled_course_ids = student.enrollments.filter(
            status='approved', is_active=True
        ).values_list('course_id', flat=True)
        return queryset.filter(courses__in=enrolled_course_ids).distinct()

    def retrieve(self, request, *args, **kwargs):
        """Increment view count on retrieve."""
        instance = self.get_object()
        instance.views_count += 1
        instance.save(update_fields=['views_count'])
        return super().retrieve(request, *args, **kwargs)

    @action(detail=True, methods=['get'], url_path='pdf')
    def pdf(self, request, *args, **kwargs):
        """
        Stream the PDF bytes inline for in-app reading.

        The raw blob URL is never exposed to the client; the file is proxied
        through this authenticated endpoint and served with an inline
        Content-Disposition so it is rendered rather than downloaded.
        """
        content = self.get_object()
        if content.content_type != 'pdf' or not content.pdf_file:
            raise Http404('No PDF available for this content.')
        try:
            fh = content.pdf_file.open('rb')
        except Exception:
            raise Http404('PDF file not found.')
        response = FileResponse(fh, content_type='application/pdf')
        response['Content-Disposition'] = 'inline; filename="document.pdf"'
        response['X-Content-Type-Options'] = 'nosniff'
        response['Cache-Control'] = 'private, no-store'
        return response

    @action(detail=False, methods=['get'])
    def by_topic(self, request):
        """Get content grouped by topic."""
        topic_id = request.query_params.get('topic_id')
        if not topic_id:
            return Response(
                {'error': 'topic_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        contents = self.get_queryset().filter(topic_id=topic_id)
        serializer = self.get_serializer(contents, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def recommended(self, request):
        """Get recommended content based on user's progress."""
        student = request.user.profile
        
        # Get weak topics from analytics
        from analytics.models import TopicMastery
        weak_topics = TopicMastery.objects.filter(
            student=student,
            mastery_level__lte=2  # Beginner or Developing
        ).values_list('topic_id', flat=True)[:5]
        
        contents = self.get_queryset().filter(
            Q(topic_id__in=weak_topics) | Q(is_free=True)
        ).order_by('-created_at')[:10]
        
        serializer = self.get_serializer(contents, many=True)
        return Response(serializer.data)


class ContentProgressViewSet(TenantAwareViewSet):
    """
    ViewSet for content progress tracking.
    """
    serializer_class = ContentProgressSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['content', 'is_completed', 'is_bookmarked']

    def get_queryset(self):
        return ContentProgress.objects.filter(
            student=self.request.user.profile
        ).select_related(
            'content', 'content__topic', 'content__subject'
        ).order_by('-updated_at')

    def create(self, request, *args, **kwargs):
        content_id = request.data.get('content')
        if not content_id:
            return Response(
                {'content': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        student = request.user.profile
        progress, created = ContentProgress.objects.get_or_create(
            student=student,
            content_id=content_id,
            defaults={
                'tenant': getattr(request, 'tenant', None),
                'progress_percentage': request.data.get('progress_percentage', 0),
            },
        )
        if not created:
            for field in ('progress_percentage', 'video_position_seconds', 'time_spent_minutes'):
                if field in request.data:
                    setattr(progress, field, request.data[field])
            progress.save()
        serializer = self.get_serializer(progress)
        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    def perform_create(self, serializer):
        serializer.save(student=self.request.user.profile, tenant=getattr(self.request, 'tenant', None))

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        """Mark content as completed and award XP."""
        from gamification.services import GamificationService
        from analytics.services import AnalyticsService
        
        progress = self.get_object()
        student = request.user.profile
        
        # Check if already completed (don't award XP twice)
        if progress.is_completed:
            response_data = ContentProgressSerializer(progress).data
            response_data['xp_earned'] = 0
            return Response(response_data)
        
        progress.is_completed = True
        progress.completed_at = timezone.now()
        progress.progress_percentage = 100
        if request.data.get('time_spent_minutes'):
            progress.time_spent_minutes = int(request.data['time_spent_minutes'])
        progress.save()
        
        # XP per content, by type (lean: notes/revision/formula 5, video/interactive 8, pdf 6)
        content = progress.content
        content_xp_map = {
            'notes': 5,
            'revision': 5,
            'formula': 5,
            'video': 8,
            'interactive': 8,
            'pdf': 6,
        }
        xp_amount = content_xp_map.get(content.content_type, 5)
        
        # Award XP
        GamificationService.award_xp(
            student,
            xp_amount,
            'content_complete',
            f'Completed: {content.title}',
            str(content.id)
        )
        
        # Update daily activity
        study_minutes = progress.time_spent_minutes or content.estimated_time_minutes or 5
        AnalyticsService.update_daily_activity(
            student,
            study_time_minutes=study_minutes,
            notes_read=1 if content.content_type in ['notes', 'pdf'] else 0,
        )
        
        # Update profile study time
        student.total_study_time_minutes += study_minutes
        student.save(update_fields=['total_study_time_minutes'])
        
        response_data = ContentProgressSerializer(progress).data
        response_data['xp_earned'] = xp_amount
        
        return Response(response_data)

    @action(detail=True, methods=['post'])
    def toggle_bookmark(self, request, pk=None):
        """Toggle bookmark status."""
        progress = self.get_object()
        progress.is_bookmarked = not progress.is_bookmarked
        progress.save()
        
        # Update content bookmark count
        content = progress.content
        if progress.is_bookmarked:
            content.bookmarks_count += 1
        else:
            content.bookmarks_count = max(0, content.bookmarks_count - 1)
        content.save(update_fields=['bookmarks_count'])
        
        return Response(ContentProgressSerializer(progress).data)


class StudyPlanViewSet(TenantAwareViewSet):
    """
    ViewSet for study plan operations.
    """
    serializer_class = StudyPlanSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return StudyPlan.objects.filter(student=self.request.user.profile)

    @staticmethod
    def _resolve_course_id(student, requested_course_id=None):
        """Resolve a usable course for the student's study plan.

        Order: explicitly requested -> first approved/active enrollment.
        Returns None if the student has no usable course.
        """
        if requested_course_id and student.enrollments.filter(
            course_id=requested_course_id, status='approved', is_active=True
        ).exists():
            return requested_course_id
        enrollment = student.enrollments.filter(
            status='approved', is_active=True
        ).order_by('created_at').first()
        return enrollment.course_id if enrollment else requested_course_id

    @action(detail=False, methods=['get'])
    def today(self, request):
        """Get today's study plan."""
        student = request.user.profile
        today = timezone.now().date()
        requested = request.query_params.get('course_id')
        course_id = self._resolve_course_id(student, requested)

        if not course_id:
            return Response({
                'items': [],
                'no_course': True,
                'detail': 'Enroll in an course to get a personalised study plan.',
            })

        plan, created = StudyPlan.objects.get_or_create(
            student=student,
            course_id=course_id,
            date=today,
            defaults={
                'target_study_minutes': student.daily_study_goal_minutes,
                'target_questions': 20
            }
        )
        
        # Generate items if new plan
        if created or plan.items.count() == 0:
            StudyPlanService.generate_daily_items(plan)
        
        return Response(StudyPlanSerializer(plan).data)

    @action(detail=False, methods=['post'])
    def generate(self, request):
        """Generate a new study plan."""
        serializer = DailyStudyPlanSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        student = request.user.profile
        today = timezone.now().date()
        course_id = self._resolve_course_id(student, serializer.validated_data.get('course_id'))

        if not course_id:
            return Response(
                {'detail': 'Enroll in an course before creating a study plan.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        plan, created = StudyPlan.objects.get_or_create(
            student=student,
            course_id=course_id,
            date=today,
            defaults={
                'target_study_minutes': serializer.validated_data['target_minutes']
            }
        )
        
        # Regenerate items
        plan.items.all().delete()
        StudyPlanService.generate_daily_items(
            plan,
            include_revision=serializer.validated_data['include_revision'],
            focus_weak_topics=serializer.validated_data['focus_weak_topics']
        )
        
        return Response(StudyPlanSerializer(plan).data)


class StudyPlanItemViewSet(TenantAwareViewSet):
    """
    ViewSet for individual study plan items.
    """
    serializer_class = StudyPlanItemSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return StudyPlanItem.objects.filter(
            study_plan__student=self.request.user.profile
        )

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        """Start working on an item."""
        item = self.get_object()
        item.status = 'in_progress'
        item.save()
        return Response(StudyPlanItemSerializer(item).data)

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        """Mark item as completed."""
        item = self.get_object()
        actual_minutes = request.data.get('actual_minutes', item.estimated_minutes)
        
        item.status = 'completed'
        item.completed_at = timezone.now()
        item.actual_minutes = actual_minutes
        item.save()
        
        # Update study plan
        plan = item.study_plan
        plan.actual_study_minutes += actual_minutes
        if item.item_type == 'quiz':
            plan.actual_questions += request.data.get('questions_count', 0)
        plan.save()
        
        # Check if plan is complete
        if not plan.items.exclude(status='completed').exists():
            plan.is_completed = True
            plan.completed_at = timezone.now()
            plan.save()
        
        return Response(StudyPlanItemSerializer(item).data)

    @action(detail=True, methods=['post'])
    def skip(self, request, pk=None):
        """Skip an item."""
        item = self.get_object()
        item.status = 'skipped'
        item.save()
        return Response(StudyPlanItemSerializer(item).data)
