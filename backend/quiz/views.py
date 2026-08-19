"""
Views for Quiz app.
"""
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter
from django.utils import timezone
from django.db.models import Q, Count, F

from .models import (
    Question, Quiz, QuizQuestion, MockTest, MockTestQuestion, QuizAttempt, MockTestAttempt, Answer, QuestionReport,
    MockTestItem, MockTestAnswer,
)
from .serializers import (
    QuestionSerializer, QuestionWithAnswerSerializer,
    QuizSerializer, QuizDetailSerializer,
    MockTestSerializer, MockTestDetailSerializer,
    PreviousYearPaperSerializer, PreviousYearPaperDetailSerializer,
    QuizAttemptSerializer, QuizAttemptSummarySerializer,
    MockTestAttemptSerializer, MockTestAttemptSummarySerializer,
    AnswerSubmitSerializer, QuizStartSerializer, QuizSubmitSerializer,
    QuizAttemptReviewSerializer, MockTestAttemptReviewSerializer,
    QuestionReportSerializer, QuestionReportCreateSerializer
)
from core.utils import calculate_xp_for_quiz
from analytics.services import AnalyticsService
from gamification.services import GamificationService
from core.views import TenantAwareViewSet, TenantAwareReadOnlyViewSet
from intelligence import api as intelligence_api
from intelligence import hooks as intelligence_hooks


class QuizSubmitThrottle(UserRateThrottle):
    """Throttle for quiz/mock test submissions."""
    rate = '3000/hour'


def _get_student_course_ids(request):
    """
    Return the IDs of every *active* course the student may access.

    Access to quizzes / questions / mock tests is scoped to a student's
    approved, active enrollments whose course is itself ``active`` — not just
    their primary course — so multi-course students can open items from any
    enrolled course (e.g. a Python quiz while their primary course is Class XI),
    while quizzes from ``inactive`` / ``coming_soon`` courses stay hidden.

    Return values are deliberately three-valued:
      * ``None``  -> the user isn't a student (e.g. staff / no profile); the
        queryset is left tenant-scoped only.
      * ``[]``    -> a student with no accessible courses; callers must scope
        the queryset down to nothing course-specific (NOT leave it open).
      * ``[...]`` -> the concrete list of accessible course IDs.

    Callers must therefore test ``if course_ids is not None`` and never a plain
    truthiness check, otherwise a student with zero accessible courses would
    incorrectly see every quiz in the tenant.
    """
    if not request.user.is_authenticated:
        return None
    try:
        profile = request.user.profile
    except Exception:
        return None
    return list(
        profile.enrollments.filter(
            status='approved', is_active=True, course__status='active'
        ).values_list('course_id', flat=True)
    )


class QuestionViewSet(TenantAwareReadOnlyViewSet):
    """
    ViewSet for questions.
    """
    queryset = Question.objects.filter(status='published')
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ['topic', 'subject', 'difficulty', 'question_type']
    search_fields = ['question_text']

    def get_serializer_class(self):
        # Only show answers for review purposes
        if self.action == 'retrieve' and self.request.query_params.get('with_answer'):
            return QuestionWithAnswerSerializer
        return QuestionSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        # Scope to every active course the student may access.
        course_ids = _get_student_course_ids(self.request)
        if course_ids is not None:
            queryset = queryset.filter(courses__in=course_ids).distinct()
        return queryset

    @action(detail=False, methods=['get'])
    def by_topic(self, request):
        """Get questions by topic."""
        topic_id = request.query_params.get('topic_id')
        limit = int(request.query_params.get('limit', 10))
        difficulty = request.query_params.get('difficulty')
        
        questions = self.get_queryset().filter(topic_id=topic_id)
        if difficulty:
            questions = questions.filter(difficulty=difficulty)
        
        questions = questions.order_by('?')[:limit]
        serializer = self.get_serializer(questions, many=True)
        return Response(serializer.data)


class QuizViewSet(TenantAwareReadOnlyViewSet):
    """
    ViewSet for quiz operations.
    """
    queryset = Quiz.objects.filter(status='published')
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ['course', 'subject', 'topic', 'quiz_type', 'is_free', 'is_daily_challenge']
    search_fields = ['title', 'description']

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return QuizDetailSerializer
        return QuizSerializer
    
    def get_queryset(self):
        queryset = super().get_queryset()
        request = self.request
        
        # Keep daily challenges out of the regular quiz listing; they are
        # surfaced through the dedicated daily_challenge endpoint/banner.
        if self.action == 'list' and 'is_daily_challenge' not in request.query_params:
            queryset = queryset.filter(is_daily_challenge=False)
        
        # Scope to the student's accessible (enrolled + active) courses. Always
        # applied — even when an explicit `course` filter is supplied — so a
        # student can never widen visibility to a course they aren't enrolled
        # in (or an inactive course) by passing `?course=`. `None` means the
        # viewer isn't a student (staff), so leave it tenant-scoped only; `[]`
        # means a student with no accessible courses, who must see no quizzes.
        course_ids = _get_student_course_ids(request)
        if course_ids is not None:
            queryset = queryset.filter(course_id__in=course_ids)
        
        # Filter by attempted status
        attempted_filter = request.query_params.get('attempted')
        if attempted_filter is not None and request.user.is_authenticated:
            profile = request.user.profile
            attempted_quiz_ids = QuizAttempt.objects.filter(
                student=profile,
                status='completed'
            ).values_list('quiz_id', flat=True).distinct()
            
            if attempted_filter.lower() == 'true':
                queryset = queryset.filter(id__in=attempted_quiz_ids)
            elif attempted_filter.lower() == 'false':
                queryset = queryset.exclude(id__in=attempted_quiz_ids)
        
        # Filter by difficulty
        difficulty = request.query_params.get('difficulty')
        if difficulty:
            # Filter quizzes that have questions with this difficulty
            queryset = queryset.filter(questions__difficulty=difficulty).distinct()
        
        return queryset

    @action(detail=False, methods=['get'])
    def filter_options(self, request):
        """Get available filter options for quizzes (scoped to student's course)."""
        from exams.models import Subject, Topic, Course
        
        # Scope to the student's accessible (enrolled + active) courses
        course_ids = _get_student_course_ids(request)
        quiz_qs = Quiz.objects.filter(status='published')
        if course_ids is not None:
            quiz_qs = quiz_qs.filter(course__in=course_ids)
        
        # Get subjects that have quizzes for this course
        subjects_with_quizzes = Subject.objects.filter(
            quizzes__in=quiz_qs
        ).distinct().values('id', 'name', 'course_id')
        
        # Get topics that have quizzes for this course
        topics_with_quizzes = Topic.objects.filter(
            quizzes__in=quiz_qs
        ).distinct().values('id', 'name', 'subject_id', 'subject__name', 'subject__course_id')
        
        # Get courses that have quizzes
        courses_with_quizzes = Course.objects.filter(
            quizzes__status='published'
        ).distinct().annotate(short_name=F('code')).values('id', 'name', 'short_name')
        
        # Get quiz type counts (scoped to course)
        quiz_types = quiz_qs.values('quiz_type').annotate(
            count=Count('id')
        )
        
        # Get attempted/non-attempted counts for the user (scoped to course)
        attempted_count = 0
        non_attempted_count = 0
        if request.user.is_authenticated:
            profile = request.user.profile
            attempted_quiz_ids = QuizAttempt.objects.filter(
                student=profile,
                status='completed',
                quiz__in=quiz_qs
            ).values_list('quiz_id', flat=True).distinct()
            
            total_quizzes = quiz_qs.count()
            attempted_count = len(set(attempted_quiz_ids))
            non_attempted_count = total_quizzes - attempted_count
        
        topics_list = [
            {'id': t['id'], 'name': t['name'], 'subject_id': t['subject_id'],
             'subject__name': t['subject__name'], 'course_id': t['subject__course_id']}
            for t in topics_with_quizzes
        ]
        return Response({
            'subjects': list(subjects_with_quizzes),
            'topics': topics_list,
            'courses': list(courses_with_quizzes),
            'quiz_types': [
                {'value': 'topic', 'label': 'Topic Quiz', 'count': next((qt['count'] for qt in quiz_types if qt['quiz_type'] == 'topic'), 0)},
                {'value': 'subject', 'label': 'Subject Quiz', 'count': next((qt['count'] for qt in quiz_types if qt['quiz_type'] == 'subject'), 0)},
                {'value': 'mixed', 'label': 'Mixed Quiz', 'count': next((qt['count'] for qt in quiz_types if qt['quiz_type'] == 'mixed'), 0)},
                {'value': 'pyq', 'label': 'Previous Year Questions', 'count': next((qt['count'] for qt in quiz_types if qt['quiz_type'] == 'pyq'), 0)},
                {'value': 'daily', 'label': 'Daily Challenge', 'count': next((qt['count'] for qt in quiz_types if qt['quiz_type'] == 'daily'), 0)},
            ],
            'difficulties': [
                {'value': 'easy', 'label': 'Easy'},
                {'value': 'medium', 'label': 'Medium'},
                {'value': 'hard', 'label': 'Hard'},
            ],
            'attempt_status': {
                'attempted': attempted_count,
                'not_attempted': non_attempted_count,
            }
        })

    @action(detail=False, methods=['get'])
    def daily_challenge(self, request):
        """Get today's daily challenge, auto-generating one if needed.

        A fresh challenge of ~10 questions is built per course per day. The
        question set rotates daily (deterministic, so every student on the same
        course gets the same challenge for the day).
        """
        today = timezone.now().date()
        student = getattr(request.user, 'profile', None)

        # Resolve a usable course, restricted to the student's *accessible*
        # (enrolled + active) courses so a daily challenge is never surfaced for
        # an inactive course or one the student isn't enrolled in.
        accessible_ids = set(_get_student_course_ids(request) or [])
        requested = request.query_params.get('course_id')
        course_id = None
        if requested and str(requested) in {str(c) for c in accessible_ids}:
            course_id = requested
        if not course_id and accessible_ids and student:
            enr = student.enrollments.filter(
                status='approved', is_active=True, course__status='active'
            ).order_by('created_at').first()
            course_id = enr.course_id if enr else None

        # 1. Existing challenge for today (scoped to course when known)
        existing = self.get_queryset().filter(is_daily_challenge=True, challenge_date=today)
        if course_id:
            existing = existing.filter(course_id=course_id)
        quiz = existing.first()

        # 2. Auto-generate today's challenge from the course question pool
        if not quiz and course_id and getattr(request, 'tenant', None):
            quiz = self._build_daily_challenge(request.tenant, course_id, today)

        # 3. Fallback: most recent challenge available
        if not quiz:
            fallback = self.get_queryset().filter(is_daily_challenge=True)
            if course_id:
                fallback = fallback.filter(course_id=course_id)
            quiz = fallback.order_by('-challenge_date').first()

        if not quiz:
            return Response(
                {'error': 'No daily challenge available yet. Please check back later!'},
                status=status.HTTP_404_NOT_FOUND
            )

        return Response(QuizDetailSerializer(quiz, context={'request': request}).data)

    def _build_daily_challenge(self, tenant, course_id, today, size=10):
        """Create (idempotently) a daily challenge quiz for an course/date."""
        from exams.models import Course

        question_ids = list(
            Question.objects.filter(
                courses__id=course_id, status='published'
            ).order_by('id').values_list('id', flat=True)
        )
        if not question_ids:
            return None

        # Deterministic daily rotation through the pool.
        total = len(question_ids)
        offset = today.toordinal() % total
        rotated = question_ids[offset:] + question_ids[:offset]
        picked = rotated[:min(size, total)]

        course = Course.objects.filter(id=course_id).first()
        title = f"Daily Challenge — {today.strftime('%b %d, %Y')}"
        quiz, created = Quiz.objects.get_or_create(
            course_id=course_id, is_daily_challenge=True, challenge_date=today,
            defaults={
                'tenant': tenant, 'title': title, 'quiz_type': 'daily',
                'status': 'published', 'is_free': True,
                'description': f"Today's mixed challenge for {course.name if course else 'your course'}.",
                'duration_minutes': max(5, len(picked) * 1),
                'total_marks': len(picked), 'shuffle_questions': True,
            }
        )
        if created or quiz.questions.count() == 0:
            QuizQuestion.objects.filter(quiz=quiz).delete()
            for order, qid in enumerate(picked):
                QuizQuestion.objects.create(quiz=quiz, question_id=qid, order=order)
        return quiz

    @action(detail=True, methods=['get'])
    def my_attempts(self, request, pk=None):
        """Get all attempts for this quiz by the current user."""
        quiz = self.get_object()
        student = request.user.profile
        
        attempts = QuizAttempt.objects.filter(
            student=student,
            quiz=quiz
        ).order_by('-started_at')
        
        return Response(QuizAttemptSummarySerializer(attempts, many=True).data)

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        """Start a quiz attempt."""
        quiz = self.get_object()
        student = request.user.profile
        
        # Check for existing in-progress attempt
        existing = QuizAttempt.objects.filter(
            student=student,
            quiz=quiz,
            status='in_progress'
        ).first()
        
        if existing:
            return Response(
                QuizAttemptSerializer(existing).data,
                status=status.HTTP_200_OK
            )
        
        # Create new attempt
        attempt = QuizAttempt.objects.create(
            student=student,
            quiz=quiz,
            total_questions=quiz.questions.count()
        )
        
        return Response(
            QuizAttemptSerializer(attempt).data,
            status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=['post'], throttle_classes=[QuizSubmitThrottle])
    def submit(self, request, pk=None):
        """Submit quiz answers."""
        quiz = self.get_object()
        student = request.user.profile
        
        serializer = QuizSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Get or create attempt
        attempt = QuizAttempt.objects.filter(
            student=student,
            quiz=quiz,
            status='in_progress'
        ).first()
        
        if not attempt:
            attempt = QuizAttempt.objects.create(
                student=student,
                quiz=quiz,
                total_questions=quiz.questions.count()
            )
        
        # Process answers
        for answer_data in serializer.validated_data['answers']:
            try:
                question = Question.objects.get(id=answer_data['question_id'])
                answer, created = Answer.objects.get_or_create(
                    quiz_attempt=attempt,
                    question=question,
                    defaults={
                        'selected_option': answer_data.get('selected_option', ''),
                        'answer_text': answer_data.get('answer_text', ''),
                        'numerical_answer': answer_data.get('numerical_answer'),
                        'time_taken_seconds': answer_data.get('time_taken_seconds', 0),
                        'is_marked_for_review': answer_data.get('is_marked_for_review', False)
                    }
                )
                if not created:
                    answer.selected_option = answer_data.get('selected_option', '')
                    answer.answer_text = answer_data.get('answer_text', '')
                    answer.numerical_answer = answer_data.get('numerical_answer')
                    answer.time_taken_seconds = answer_data.get('time_taken_seconds', 0)
                    answer.save()
                
                answer.check_answer()
                
                # Update question statistics
                question.times_attempted += 1
                if answer.is_correct:
                    question.times_correct += 1
                question.save(update_fields=['times_attempted', 'times_correct'])
                
            except Question.DoesNotExist:
                continue
        
        # Calculate results
        attempt.status = 'completed'
        attempt.completed_at = timezone.now()
        attempt.time_taken_seconds = serializer.validated_data['time_taken_seconds']
        attempt.calculate_results()
        
        # XP only on first completion (re-attempts earn 0 XP)
        already_completed = QuizAttempt.objects.filter(
            student=student, quiz=quiz, status='completed'
        ).exclude(id=attempt.id).exists()
        if already_completed:
            xp = 0
        else:
            accuracy = attempt.percentage
            xp = calculate_xp_for_quiz(
                accuracy,
                attempt.total_questions,
                quiz.is_daily_challenge
            )
        attempt.xp_earned = xp
        attempt.save()
        
        # Update student profile
        student.total_questions_attempted += attempt.attempted_questions
        student.total_correct_answers += attempt.correct_answers
        student.save()
        
        # Award XP only on first completion
        if xp > 0:
            GamificationService.award_xp(
                student,
                xp,
                'quiz_complete',
                f'Completed quiz: {quiz.title}',
                str(attempt.id)
            )
        
        # Update daily activity (convert time_taken_seconds to minutes)
        study_minutes = max(1, attempt.time_taken_seconds // 60)  # At least 1 minute
        AnalyticsService.update_daily_activity(
            student,
            study_time_minutes=study_minutes,
            questions_attempted=attempt.attempted_questions,
            questions_correct=attempt.correct_answers,
            quizzes_completed=1 if xp > 0 else 0,
            xp_earned=xp
        )
        
        # Also update profile study time
        student.total_study_time_minutes += study_minutes
        student.save(update_fields=['total_study_time_minutes'])

        # Update topic mastery
        AnalyticsService.update_topic_mastery_from_attempt(attempt)

        # Record learning events for the intelligence layer (fail-safe)
        intelligence_api.record_attempt_events(attempt)
        intelligence_hooks.on_attempt_graded(attempt, course=quiz.course)
        
        # Build badge context for accurate badge awarding
        badge_context = {
            'perfect_quiz': attempt.percentage == 100,
            'speed_quiz': attempt.time_taken_seconds < (quiz.duration_minutes * 60 / 2) if quiz.duration_minutes > 0 else False,
            'early_study': timezone.now().hour < 6,
            'night_study': timezone.now().hour >= 22,
            'weekend_study': timezone.now().weekday() >= 5,
        }
        
        # Check for new badges with context
        GamificationService.check_and_award_badges(student, context=badge_context)
        
        # Update quiz statistics
        quiz.total_attempts += 1
        quiz.save(update_fields=['total_attempts'])

        # Return full attempt data; on serialization error return summary or minimal payload so client never gets 500
        try:
            return Response(QuizAttemptSerializer(attempt).data)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.exception(
                "Quiz submit: full serialization failed (attempt_id=%s), returning fallback: %s",
                attempt.id, e
            )
            try:
                return Response(
                    QuizAttemptSummarySerializer(attempt).data,
                    status=status.HTTP_200_OK
                )
            except Exception as e2:
                logger.exception("Quiz submit: summary serialization also failed: %s", e2)
                return Response(
                    {
                        'id': str(attempt.id),
                        'quiz': str(attempt.quiz_id),
                        'quiz_title': attempt.quiz.title,
                        'status': attempt.status,
                        'xp_earned': int(attempt.xp_earned),
                        'percentage': float(attempt.percentage) if attempt.percentage is not None else 0,
                        'marks_obtained': float(attempt.marks_obtained) if attempt.marks_obtained is not None else 0,
                        'total_marks': float(attempt.total_marks) if attempt.total_marks is not None else 0,
                        'correct_answers': attempt.correct_answers,
                        'wrong_answers': attempt.wrong_answers,
                        'completed_at': attempt.completed_at.isoformat() if attempt.completed_at else None,
                        'answers': [],
                    },
                    status=status.HTTP_200_OK
                )
    
    @action(detail=True, methods=['get'])
    def leaderboard(self, request, pk=None):
        """Get leaderboard for a specific quiz (tenant-scoped)."""
        quiz = self.get_object()
        tenant = getattr(request, 'tenant', None)
        
        # Get best attempt per student (highest marks), only for current tenant's students
        from django.db.models import Max, Min, F
        
        qs = QuizAttempt.objects.filter(
            quiz=quiz,
            status='completed',
        )
        if tenant:
            qs = qs.filter(student__user__tenant=tenant)
        attempts = qs.order_by('-marks_obtained', 'time_taken_seconds')
        
        # Deduplicate: keep best attempt per student
        seen_students = set()
        leaderboard = []
        for attempt in attempts[:200]:  # Check up to 200 attempts
            if attempt.student_id in seen_students:
                continue
            seen_students.add(attempt.student_id)
            leaderboard.append({
                'rank': len(leaderboard) + 1,
                'student_name': attempt.student.user.full_name or attempt.student.user.username,
                'marks_obtained': float(attempt.marks_obtained),
                'total_marks': float(attempt.total_marks),
                'percentage': float(attempt.percentage),
                'correct_answers': attempt.correct_answers,
                'wrong_answers': attempt.wrong_answers,
                'time_taken_seconds': attempt.time_taken_seconds,
                'completed_at': attempt.completed_at.isoformat() if attempt.completed_at else None,
                'is_current_user': attempt.student == request.user.profile,
            })
            if len(leaderboard) >= 50:
                break
        
        # Find current user's rank
        user_rank = None
        for entry in leaderboard:
            if entry['is_current_user']:
                user_rank = entry['rank']
                break
        
        return Response({
            'quiz_title': quiz.title,
            'total_marks': float(quiz.total_marks),
            'leaderboard': leaderboard,
            'user_rank': user_rank,
            'total_participants': len(seen_students),
        })


class MockTestViewSet(TenantAwareReadOnlyViewSet):
    """
    ViewSet for mock test operations.
    """
    queryset = MockTest.objects.filter(status='published', is_pyp=False)
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter]
    # NOTE: `course` is handled manually in get_queryset so it matches both the
    # legacy `course` FK and the rich `courses` M2M. Keeping it in
    # filterset_fields would let DjangoFilterBackend re-filter on the legacy FK
    # only, hiding rich mock tests (course=None) whenever a course is selected.
    filterset_fields = ['is_free']
    search_fields = ['title', 'description']

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return MockTestDetailSerializer
        return MockTestSerializer
    
    def get_queryset(self):
        queryset = super().get_queryset()
        request = self.request

        from .mock_grading import accessible_mock_tests_q

        # Scope to mock tests this student may attempt. Access covers: linked
        # `courses` (M2M), legacy `course`, or fully-open tests (no course links)
        # for any student in the tenant. Non-enrolled viewers (e.g. staff) stay
        # tenant-scoped only.
        course_ids = _get_student_course_ids(request)
        if course_ids is not None:
            queryset = queryset.filter(accessible_mock_tests_q(course_ids)).distinct()

        # Optional course filter from the UI. Match the selected course against
        # BOTH the legacy `course` FK and the rich `courses` M2M, and always keep
        # fully-open tests (no course links) visible regardless of the selection.
        course_param = request.query_params.get('course')
        if course_param:
            queryset = queryset.filter(
                Q(course_id=course_param)
                | Q(courses__id=course_param)
                | (Q(course__isnull=True) & Q(courses__isnull=True))
            ).distinct()
        
        # Filter by attempted status
        attempted_filter = request.query_params.get('attempted')
        if attempted_filter is not None and request.user.is_authenticated:
            profile = request.user.profile
            attempted_test_ids = MockTestAttempt.objects.filter(
                student=profile,
                status='completed'
            ).values_list('mock_test_id', flat=True).distinct()
            
            if attempted_filter.lower() == 'true':
                queryset = queryset.filter(id__in=attempted_test_ids)
            elif attempted_filter.lower() == 'false':
                queryset = queryset.exclude(id__in=attempted_test_ids)
        
        return queryset

    @action(detail=False, methods=['get'])
    def filter_options(self, request):
        """Get available filter options for mock tests (scoped to student's course)."""
        from exams.models import Course
        
        # Scope to the student's accessible courses (legacy FK or rich M2M).
        course_ids = _get_student_course_ids(request)
        test_qs = MockTest.objects.filter(status='published')
        if course_ids is not None:
            test_qs = test_qs.filter(
                Q(course__in=course_ids) | Q(courses__in=course_ids)
            ).distinct()
        
        # Courses that have published mock tests, via the legacy `course` FK OR
        # the rich `courses` M2M, so rich mock tests surface as filter chips too.
        courses_with_tests = Course.objects.filter(
            Q(mock_tests__status='published') | Q(linked_mock_tests__status='published')
        ).distinct().annotate(short_name=F('code')).values('id', 'name', 'short_name')
        
        # Get attempted/non-attempted counts for the user (scoped to course)
        attempted_count = 0
        non_attempted_count = 0
        if request.user.is_authenticated:
            profile = request.user.profile
            attempted_test_ids = MockTestAttempt.objects.filter(
                student=profile,
                status='completed',
                mock_test__in=test_qs
            ).values_list('mock_test_id', flat=True).distinct()
            
            total_tests = test_qs.count()
            attempted_count = len(set(attempted_test_ids))
            non_attempted_count = total_tests - attempted_count
        
        return Response({
            'courses': list(courses_with_tests),
            'attempt_status': {
                'attempted': attempted_count,
                'not_attempted': non_attempted_count,
            }
        })

    @action(detail=True, methods=['get'])
    def my_attempts(self, request, pk=None):
        """Get all attempts for this mock test by the current user."""
        mock_test = self.get_object()
        student = request.user.profile
        
        attempts = MockTestAttempt.objects.filter(
            student=student,
            mock_test=mock_test
        ).order_by('-started_at')
        
        return Response(MockTestAttemptSummarySerializer(attempts, many=True).data)

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        """Start a mock test attempt."""
        mock_test = self.get_object()
        student = request.user.profile
        
        # Check for existing attempt
        existing = MockTestAttempt.objects.filter(
            student=student,
            mock_test=mock_test,
            status='in_progress'
        ).first()
        
        if existing:
            return Response(
                MockTestAttemptSerializer(existing).data,
                status=status.HTTP_200_OK
            )
        
        attempt = MockTestAttempt.objects.create(
            student=student,
            mock_test=mock_test,
            total_questions=mock_test.questions.count()
        )
        
        return Response(
            MockTestAttemptSerializer(attempt).data,
            status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=['post'], throttle_classes=[QuizSubmitThrottle])
    def submit(self, request, pk=None):
        """Submit mock test answers."""
        mock_test = self.get_object()
        student = request.user.profile
        
        serializer = QuizSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        attempt = MockTestAttempt.objects.filter(
            student=student,
            mock_test=mock_test,
            status='in_progress'
        ).first()
        
        if not attempt:
            return Response(
                {'error': 'No active attempt found'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Build a map of question -> MockTestQuestion for marks overrides
        mtq_map = {}
        for mtq in MockTestQuestion.objects.filter(mock_test=mock_test).select_related('question'):
            mtq_map[str(mtq.question_id)] = mtq
        
        # Process answers (similar to quiz)
        for answer_data in serializer.validated_data['answers']:
            try:
                question = Question.objects.get(id=answer_data['question_id'])
                answer, created = Answer.objects.get_or_create(
                    mock_test_attempt=attempt,
                    question=question,
                    defaults={
                        'selected_option': answer_data.get('selected_option', ''),
                        'time_taken_seconds': answer_data.get('time_taken_seconds', 0),
                    }
                )
                if not created:
                    answer.selected_option = answer_data.get('selected_option', '')
                    answer.time_taken_seconds = answer_data.get('time_taken_seconds', 0)
                    answer.save()
                
                # Use per-mock-test marks overrides if available
                mtq = mtq_map.get(str(question.id))
                if mtq and (mtq.marks_override is not None or mtq.negative_marks_override is not None):
                    answer.check_answer(
                        marks_override=mtq.marks_override,
                        negative_marks_override=mtq.negative_marks_override
                    )
                else:
                    answer.check_answer()
                
                # Update question statistics
                question.times_attempted += 1
                if answer.is_correct:
                    question.times_correct += 1
                question.save(update_fields=['times_attempted', 'times_correct'])
            except Question.DoesNotExist:
                continue
        
        # Calculate results
        answers = attempt.answers.all()
        attempt.total_questions = mock_test.questions.count()
        attempt.attempted_questions = answers.count()
        attempt.correct_answers = answers.filter(is_correct=True).count()
        attempt.wrong_answers = answers.filter(is_correct=False).count()
        
        # Use marks_obtained from check_answer (handles +marks/-negative_marks)
        marks = sum(a.marks_obtained for a in answers)
        attempt.marks_obtained = marks  # Can be negative in competitive courses
        
        # Use effective total marks from MockTestQuestion (accounts for overrides)
        actual_total = sum(float(mtq.effective_marks) for mtq in mtq_map.values())
        if actual_total > 0:
            attempt.percentage = max(0, (float(marks) / actual_total) * 100)
        else:
            attempt.percentage = 0
        
        attempt.status = 'completed'
        attempt.completed_at = timezone.now()
        attempt.time_taken_seconds = serializer.validated_data['time_taken_seconds']
        attempt.save()
        
        # XP only on first completion (re-attempts earn 0 XP)
        already_completed = MockTestAttempt.objects.filter(
            student=student, mock_test=mock_test, status='completed'
        ).exclude(id=attempt.id).exists()
        if already_completed:
            xp = 0
        else:
            # Base quiz formula is capped at 100; mock tests pay double (effective max 200).
            xp = calculate_xp_for_quiz(
                attempt.percentage,
                attempt.total_questions,
                is_daily_challenge=False
            ) * 2
        attempt.xp_earned = xp
        attempt.save(update_fields=['xp_earned'])
        
        # Update student profile
        student.total_questions_attempted += attempt.attempted_questions
        student.total_correct_answers += attempt.correct_answers
        student.save()
        
        # Award XP only on first completion
        if xp > 0:
            GamificationService.award_xp(
                student,
                xp,
                'mock_complete',
                f'Completed mock test: {mock_test.title}',
                str(attempt.id)
            )
        
        # Update daily activity (convert time_taken_seconds to minutes)
        study_minutes = max(1, attempt.time_taken_seconds // 60)  # At least 1 minute
        AnalyticsService.update_daily_activity(
            student,
            study_time_minutes=study_minutes,
            questions_attempted=attempt.attempted_questions,
            questions_correct=attempt.correct_answers,
            mock_tests_completed=1 if xp > 0 else 0,
            xp_earned=xp
        )
        
        # Also update profile study time
        student.total_study_time_minutes += study_minutes
        student.save(update_fields=['total_study_time_minutes'])
        
        # Update topic mastery and subject performance
        AnalyticsService.update_mock_test_analytics(attempt)

        # Record learning events for the intelligence layer (fail-safe)
        intelligence_api.record_attempt_events(attempt)
        intelligence_hooks.on_attempt_graded(attempt, course=mock_test.course)

        # Build badge context for accurate badge awarding
        badge_context = {
            'perfect_quiz': attempt.percentage == 100,
            'speed_quiz': attempt.time_taken_seconds < (mock_test.duration_minutes * 60 / 2) if mock_test.duration_minutes > 0 else False,
            'early_study': timezone.now().hour < 6,
            'night_study': timezone.now().hour >= 22,
            'weekend_study': timezone.now().weekday() >= 5,
        }
        
        # Check for new badges with context
        GamificationService.check_and_award_badges(student, context=badge_context)
        
        # Update mock test stats
        mock_test.total_attempts += 1
        if attempt.marks_obtained > mock_test.highest_score:
            mock_test.highest_score = attempt.marks_obtained
        mock_test.save()
        
        return Response(MockTestAttemptSerializer(attempt).data)
    
    @action(detail=True, methods=['get'])
    def leaderboard(self, request, pk=None):
        """Get leaderboard for a specific mock test (tenant-scoped)."""
        mock_test = self.get_object()
        tenant = getattr(request, 'tenant', None)
        
        qs = MockTestAttempt.objects.filter(
            mock_test=mock_test,
            status='completed',
        )
        if tenant:
            qs = qs.filter(student__user__tenant=tenant)
        attempts = qs.order_by('-marks_obtained', 'time_taken_seconds')
        
        # Deduplicate: keep best attempt per student
        seen_students = set()
        leaderboard = []
        for attempt in attempts[:200]:
            if attempt.student_id in seen_students:
                continue
            seen_students.add(attempt.student_id)
            leaderboard.append({
                'rank': len(leaderboard) + 1,
                'student_name': attempt.student.user.full_name or attempt.student.user.username,
                'marks_obtained': float(attempt.marks_obtained),
                'total_marks': float(mock_test.total_marks),
                'percentage': float(attempt.percentage),
                'correct_answers': attempt.correct_answers,
                'wrong_answers': attempt.wrong_answers,
                'time_taken_seconds': attempt.time_taken_seconds,
                'completed_at': attempt.completed_at.isoformat() if attempt.completed_at else None,
                'is_current_user': attempt.student == request.user.profile,
            })
            if len(leaderboard) >= 50:
                break
        
        user_rank = None
        for entry in leaderboard:
            if entry['is_current_user']:
                user_rank = entry['rank']
                break
        
        return Response({
            'mock_test_title': mock_test.title,
            'total_marks': float(mock_test.total_marks),
            'leaderboard': leaderboard,
            'user_rank': user_rank,
            'total_participants': len(seen_students),
        })

    # ------------------------------------------------------------------
    # Rich mock test flow (Phase 3): merged bank + inline items, autograde
    # for MCQ / numerical / coding, manual grading for subjective.
    # ------------------------------------------------------------------

    def _rich_access_or_403(self, mock_test, request):
        from .mock_grading import student_can_access
        course_ids = _get_student_course_ids(request)
        if course_ids is None:
            course_ids = []
        if not student_can_access(mock_test, course_ids):
            return Response(
                {'error': 'You are not eligible to attempt this test.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        return None

    # -- timing / persistence helpers for the server-authoritative timer -----

    def _attempt_timing(self, mock_test, attempt):
        """Server-authoritative timing for an in-progress attempt.

        The clock is anchored to ``attempt.started_at`` (stored in the DB), so
        closing the tab never pauses it. Returns server ``now``, the absolute
        ``expires_at``, whole ``seconds_remaining`` and whether it has expired.
        """
        now = timezone.now()
        expires_at = attempt.started_at + timezone.timedelta(
            minutes=mock_test.duration_minutes or 0)
        remaining = int((expires_at - now).total_seconds())
        return {
            'server_now': now.isoformat(),
            'started_at': attempt.started_at.isoformat(),
            'expires_at': expires_at.isoformat(),
            'seconds_remaining': max(0, remaining),
            'expired': remaining <= 0,
        }

    def _saved_answers(self, attempt):
        """Previously-saved answers, keyed to match the attempt UI (`kind:ref`).

        Lets a resumed attempt restore what the student had entered before the
        tab was closed.
        """
        out = {}
        for a in attempt.answers.select_related('question').all():
            key = f'bank:{a.question_id}'
            entry = {'is_marked_for_review': a.is_marked_for_review}
            if a.numerical_answer is not None:
                entry['numerical_answer'] = float(a.numerical_answer)
            if a.selected_option:
                entry['selected'] = [a.selected_option]
            out[key] = entry
        for a in attempt.item_answers.select_related('item').all():
            key = f'item:{a.item_id}'
            entry = {'is_marked_for_review': a.is_marked_for_review}
            if a.selected_options:
                entry['selected'] = list(a.selected_options)
            if a.numerical_answer is not None:
                entry['numerical_answer'] = float(a.numerical_answer)
            if a.answer_text:
                entry['answer_text'] = a.answer_text
            if a.code:
                entry['code'] = a.code
            if a.language:
                entry['language'] = a.language
            out[key] = entry
        return out

    def _upsert_rich_answers(self, attempt, mock_test, tenant,
                             bank_answers, item_answers, grade):
        """Persist submitted answers. When ``grade`` is False (autosave) the
        answers are stored raw without any grading (never runs code)."""
        from .mock_grading import grade_item_answer
        mtq_map = {
            str(mtq.question_id): mtq
            for mtq in MockTestQuestion.objects.filter(mock_test=mock_test).select_related('question')
        }
        for a in bank_answers or []:
            mtq = mtq_map.get(str(a.get('question_id')))
            if not mtq:
                continue
            answer, _ = Answer.objects.get_or_create(
                mock_test_attempt=attempt, question=mtq.question,
                defaults={'tenant': tenant},
            )
            answer.selected_option = a.get('selected_option', '') or ''
            answer.numerical_answer = a.get('numerical_answer')
            answer.answer_text = a.get('answer_text', '') or ''
            answer.time_taken_seconds = int(a.get('time_taken_seconds', 0) or 0)
            answer.is_marked_for_review = bool(a.get('is_marked_for_review', False))
            if grade:
                answer.check_answer(
                    marks_override=mtq.marks_override,
                    negative_marks_override=mtq.negative_marks_override,
                )
            else:
                answer.save()

        item_map = {
            str(it.id): it
            for it in MockTestItem.objects.filter(mock_test=mock_test)
        }
        for a in item_answers or []:
            item = item_map.get(str(a.get('item_id')))
            if not item:
                continue
            ans, _ = MockTestAnswer.objects.get_or_create(
                attempt=attempt, item=item, defaults={'tenant': tenant},
            )
            ans.selected_options = a.get('selected_options', []) or []
            ans.numerical_answer = a.get('numerical_answer')
            ans.answer_text = a.get('answer_text', '') or ''
            ans.code = a.get('code', '') or ''
            ans.language = a.get('language', '') or ''
            ans.time_taken_seconds = int(a.get('time_taken_seconds', 0) or 0)
            ans.is_marked_for_review = bool(a.get('is_marked_for_review', False))
            if grade:
                grade_item_answer(item, ans)
            ans.save()

    def _finalize_rich_attempt(self, attempt, mock_test, student, timed_out=False):
        """Grade every saved answer, aggregate results and complete the attempt.

        Used by both explicit submission and server-side auto-submit when the
        timer expires (e.g. the student never returned to the tab). Idempotent
        via the attempt's ``in_progress`` guard at the call sites.
        """
        from decimal import Decimal
        from .mock_grading import grade_item_answer

        # (Re)grade any answers that were only autosaved (stored ungraded).
        mtq_map = {
            str(mtq.question_id): mtq
            for mtq in MockTestQuestion.objects.filter(mock_test=mock_test).select_related('question')
        }
        for answer in attempt.answers.select_related('question').all():
            mtq = mtq_map.get(str(answer.question_id))
            if mtq:
                answer.check_answer(
                    marks_override=mtq.marks_override,
                    negative_marks_override=mtq.negative_marks_override,
                )
        for ans in attempt.item_answers.select_related('item').all():
            grade_item_answer(ans.item, ans)
            ans.save()

        bank_qs = attempt.answers.all()
        item_qs = attempt.item_answers.all()
        bank_marks = sum((x.marks_obtained for x in bank_qs), Decimal('0'))
        item_marks = sum((x.marks_obtained for x in item_qs), Decimal('0'))
        attempt.marks_obtained = bank_marks + item_marks
        attempt.attempted_questions = bank_qs.count() + item_qs.count()
        attempt.correct_answers = (
            bank_qs.filter(is_correct=True).count() + item_qs.filter(is_correct=True).count()
        )
        attempt.wrong_answers = (
            bank_qs.filter(is_correct=False).count()
            + item_qs.filter(is_correct=False, needs_manual_grading=False).count()
        )
        total = float(mock_test.total_marks) or 0
        attempt.percentage = max(0, (float(attempt.marks_obtained) / total) * 100) if total > 0 else 0

        pending_manual = item_qs.filter(needs_manual_grading=True).exists()
        attempt.grading_status = 'pending_manual' if pending_manual else 'auto_graded'
        attempt.status = 'timed_out' if timed_out else 'completed'
        attempt.completed_at = timezone.now()
        elapsed = int((attempt.completed_at - attempt.started_at).total_seconds())
        cap = (mock_test.duration_minutes or 0) * 60
        attempt.time_taken_seconds = min(elapsed, cap) if cap else elapsed
        attempt.save()

        from .mock_grading import award_completion_xp
        awarded_xp = award_completion_xp(attempt) if not pending_manual else 0

        mock_test.total_attempts += 1
        if attempt.marks_obtained > mock_test.highest_score:
            mock_test.highest_score = attempt.marks_obtained
        mock_test.save(update_fields=['total_attempts', 'highest_score'])

        # One explicit analytics update per finalization (signals were removed
        # because they fired on every save of a completed attempt). Also covers
        # timed-out attempts, which the old signal skipped.
        AnalyticsService.update_mock_test_analytics(attempt)

        # Record learning events for the intelligence layer (fail-safe)
        intelligence_api.record_attempt_events(attempt)
        intelligence_hooks.on_attempt_graded(
            attempt, course=mock_test.course or mock_test.courses.first(),
        )

        # AI grading of pending subjective answers (opt-in per tenant; no-op
        # otherwise). Runs async — the attempt stays pending_manual meanwhile.
        if pending_manual:
            intelligence_hooks.maybe_enqueue_ai_grading(attempt)

        results_visible = (
            mock_test.result_visibility == 'immediate' and not pending_manual
        ) or mock_test.results_released

        return {
            'attempt': MockTestAttemptSerializer(attempt).data,
            'grading_status': attempt.grading_status,
            'results_visible': results_visible,
            'pending_manual': pending_manual,
            'timed_out': timed_out,
        }

    @action(detail=True, methods=['get'])
    def paper(self, request, pk=None):
        """Merged, ordered question paper for the rich attempt UI (no answers)."""
        from .mock_grading import build_paper
        mock_test = self.get_object()
        denied = self._rich_access_or_403(mock_test, request)
        if denied:
            return denied
        student = request.user.profile
        active = MockTestAttempt.objects.filter(
            student=student, mock_test=mock_test, status='in_progress'
        ).first()
        attempts_used = MockTestAttempt.objects.filter(
            student=student, mock_test=mock_test,
            status__in=['completed', 'timed_out'],
        ).count()
        max_attempts = mock_test.max_attempts or 1
        timing = self._attempt_timing(mock_test, active) if active else None
        return Response({
            'mock_test': {
                'id': str(mock_test.id),
                'title': mock_test.title,
                'description': mock_test.description,
                'duration_minutes': mock_test.duration_minutes,
                'total_marks': float(mock_test.total_marks),
                'negative_marking': mock_test.negative_marking,
                'fullscreen_required': mock_test.fullscreen_required,
                'result_visibility': mock_test.result_visibility,
                'start_deadline': mock_test.start_deadline.isoformat() if mock_test.start_deadline else None,
                'max_attempts': max_attempts,
                'sections': mock_test.sections,
            },
            'questions': build_paper(mock_test),
            'active_attempt_id': str(active.id) if active else None,
            'server_now': timezone.now().isoformat(),
            'attempts_used': attempts_used,
            'attempts_remaining': max(0, max_attempts - attempts_used),
            'can_start': attempts_used < max_attempts,
            'timing': timing,
        })

    @action(detail=True, methods=['post'])
    def start_rich(self, request, pk=None):
        """Start (or resume) a rich mock test attempt after access + deadline checks."""
        from .mock_grading import build_paper
        mock_test = self.get_object()
        denied = self._rich_access_or_403(mock_test, request)
        if denied:
            return denied
        student = request.user.profile

        existing = MockTestAttempt.objects.filter(
            student=student, mock_test=mock_test, status='in_progress'
        ).first()
        if existing:
            timing = self._attempt_timing(mock_test, existing)
            # Timer runs on the server clock, so a tab left closed past the
            # deadline is auto-submitted here on return rather than resumed.
            if timing['expired']:
                result = self._finalize_rich_attempt(
                    existing, mock_test, student, timed_out=True)
                return Response({
                    'expired': True,
                    'attempt_id': str(existing.id),
                    **result,
                })
            return Response({
                'attempt': MockTestAttemptSerializer(existing).data,
                'questions': build_paper(mock_test),
                'saved_answers': self._saved_answers(existing),
                'timing': timing,
                'resumed': True,
            })

        # Fresh start: enforce the per-student attempt cap.
        attempts_used = MockTestAttempt.objects.filter(
            student=student, mock_test=mock_test,
            status__in=['completed', 'timed_out'],
        ).count()
        max_attempts = mock_test.max_attempts or 1
        if attempts_used >= max_attempts:
            return Response(
                {'error': 'You have used all allowed attempts for this test.',
                 'attempts_used': attempts_used, 'max_attempts': max_attempts},
                status=status.HTTP_403_FORBIDDEN,
            )

        if mock_test.start_deadline and timezone.now() > mock_test.start_deadline:
            return Response(
                {'error': 'The window to start this test has closed.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        bank_count = MockTestQuestion.objects.filter(mock_test=mock_test).count()
        item_count = MockTestItem.objects.filter(mock_test=mock_test).count()
        attempt = MockTestAttempt.objects.create(
            student=student,
            mock_test=mock_test,
            total_questions=bank_count + item_count,
            total_marks=mock_test.total_marks,
            tenant=getattr(request, 'tenant', None),
        )
        return Response({
            'attempt': MockTestAttemptSerializer(attempt).data,
            'questions': build_paper(mock_test),
            'saved_answers': {},
            'timing': self._attempt_timing(mock_test, attempt),
            'resumed': False,
        }, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def save_rich(self, request, pk=None):
        """Autosave in-progress answers (no grading) so a resume can restore them."""
        mock_test = self.get_object()
        denied = self._rich_access_or_403(mock_test, request)
        if denied:
            return denied
        student = request.user.profile
        attempt = MockTestAttempt.objects.filter(
            student=student, mock_test=mock_test, status='in_progress'
        ).first()
        if not attempt:
            return Response({'error': 'No active attempt found'},
                            status=status.HTTP_400_BAD_REQUEST)
        timing = self._attempt_timing(mock_test, attempt)
        if timing['expired']:
            result = self._finalize_rich_attempt(
                attempt, mock_test, student, timed_out=True)
            return Response({'expired': True, 'attempt_id': str(attempt.id), **result})
        self._upsert_rich_answers(
            attempt, mock_test, getattr(request, 'tenant', None),
            request.data.get('bank_answers', []),
            request.data.get('item_answers', []),
            grade=False,
        )
        return Response({'saved': True, 'timing': timing})

    @action(detail=True, methods=['post'], throttle_classes=[QuizSubmitThrottle])
    def submit_rich(self, request, pk=None):
        """Submit a rich attempt: grade bank + inline answers; flag subjective."""
        mock_test = self.get_object()
        denied = self._rich_access_or_403(mock_test, request)
        if denied:
            return denied
        student = request.user.profile

        attempt = MockTestAttempt.objects.filter(
            student=student, mock_test=mock_test, status='in_progress'
        ).first()
        if not attempt:
            return Response({'error': 'No active attempt found'},
                            status=status.HTTP_400_BAD_REQUEST)

        tenant = getattr(request, 'tenant', None)
        # Persist and grade the final answers, then finalize. Time is computed
        # server-side from started_at (never trusts the client clock).
        self._upsert_rich_answers(
            attempt, mock_test, tenant,
            request.data.get('bank_answers', []),
            request.data.get('item_answers', []),
            grade=True,
        )
        timing = self._attempt_timing(mock_test, attempt)
        result = self._finalize_rich_attempt(
            attempt, mock_test, student, timed_out=timing['expired'])
        return Response(result)

    @action(detail=True, methods=['post'], throttle_classes=[QuizSubmitThrottle])
    def run_item(self, request, pk=None):
        """Run a coding item's SAMPLE cases against submitted code (ungraded)."""
        from types import SimpleNamespace
        from django.conf import settings
        mock_test = self.get_object()
        denied = self._rich_access_or_403(mock_test, request)
        if denied:
            return denied
        if not getattr(settings, 'CODING_ENABLED', True):
            return Response({'error': 'Coding execution is disabled.'},
                            status=status.HTTP_400_BAD_REQUEST)
        item = MockTestItem.objects.filter(
            mock_test=mock_test, id=request.data.get('item_id'), item_type='coding'
        ).first()
        if not item:
            return Response({'error': 'Coding item not found.'},
                            status=status.HTTP_400_BAD_REQUEST)
        code = request.data.get('code', '') or ''
        language = request.data.get('language', '') or ''
        if not code or not language:
            return Response({'error': 'code and language are required.'},
                            status=status.HTTP_400_BAD_REQUEST)
        samples = [
            SimpleNamespace(
                stdin=c.get('stdin', ''), expected_output=c.get('expected_output', ''),
                points=int(c.get('points', 1) or 1), is_sample=True, id=i, order=i,
            )
            for i, c in enumerate(item.coding_test_cases or []) if c.get('is_sample')
        ]
        if not samples:
            return Response({'results': [], 'passed_count': 0, 'total_count': 0})
        try:
            from coding.services import run_against_cases, EngineError
            result = run_against_cases(
                language=language, source=code, cases=samples,
                time_limit_ms=item.time_limit_ms, memory_limit_mb=item.memory_limit_mb,
                reveal_io=True,
            )
        except EngineError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response(result)

    @action(detail=False, methods=['post'],
            url_path='attempts/(?P<attempt_id>[^/.]+)/request-regrade')
    def request_regrade(self, request, attempt_id=None):
        """Dispute an AI-graded subjective answer: return it to the human queue.

        Once per answer. The AI's suggestion and feedback are kept for the
        grader's context; the attempt drops back to pending_manual so the
        existing grading flow picks it up.
        """
        import uuid as uuid_module

        from django.db import transaction

        attempt = MockTestAttempt.objects.filter(
            id=attempt_id, student=request.user.profile,
        ).first()
        if not attempt:
            return Response({'error': 'Attempt not found.'}, status=status.HTTP_404_NOT_FOUND)
        try:
            answer_id = uuid_module.UUID(str(request.data.get('answer_id')))
        except (TypeError, ValueError):
            return Response({'error': 'A valid answer_id is required.'},
                            status=status.HTTP_400_BAD_REQUEST)
        answer = attempt.item_answers.filter(
            id=answer_id, item__item_type='subjective',
        ).first()
        if not answer:
            return Response({'error': 'Answer not found.'}, status=status.HTTP_404_NOT_FOUND)
        # ai_graded implies the answer is not already pending; disputed answers
        # have ai_graded=False, so this also enforces once-per-answer.
        if not answer.ai_graded:
            return Response(
                {'error': 'Only AI-graded answers can be sent for re-checking.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Withdraw the disputed marks until a human decides; the AI suggestion
        # stays on ai_suggested_marks/ai_feedback for the grader's context.
        # Note the deliberate tradeoff: the attempt returns to pending_manual
        # (that is what the admin grading queue lists), which also withholds
        # the result view until the re-check — same semantics as any other
        # pending-manual attempt.
        from .mock_grading import recompute_attempt

        with transaction.atomic():
            answer.needs_manual_grading = True
            answer.ai_graded = False
            answer.marks_obtained = 0
            answer.is_correct = False
            answer.save(update_fields=[
                'needs_manual_grading', 'ai_graded', 'marks_obtained', 'is_correct',
                'updated_at',
            ])
            recompute_attempt(attempt)
            attempt.grading_status = 'pending_manual'
            attempt.save(update_fields=[
                'marks_obtained', 'attempted_questions', 'correct_answers',
                'wrong_answers', 'percentage', 'grading_status', 'updated_at',
            ])
        return Response({'status': 'requested'})

    @action(detail=False, methods=['get'], url_path='attempts/(?P<attempt_id>[^/.]+)/review')
    def rich_review(self, request, attempt_id=None):
        """Per-question review for the owning student, gated by result visibility."""
        from .mock_grading import build_review, results_visible_for
        attempt = MockTestAttempt.objects.filter(
            id=attempt_id, student=request.user.profile
        ).select_related('mock_test').first()
        if not attempt:
            return Response({'error': 'Attempt not found.'}, status=status.HTTP_404_NOT_FOUND)

        mt = attempt.mock_test
        visible = results_visible_for(attempt)
        base = {
            'attempt_id': str(attempt.id),
            'mock_test_id': str(mt.id),
            'mock_test_title': mt.title,
            'grading_status': attempt.grading_status,
            'results_visible': visible,
        }
        if not visible:
            base['message'] = (
                'Your attempt is awaiting grading.'
                if attempt.grading_status == 'pending_manual'
                else 'Results will be released by your faculty.'
            )
            return Response(base)

        base.update({
            'marks_obtained': float(attempt.marks_obtained),
            'total_marks': float(mt.total_marks),
            'percentage': float(attempt.percentage),
            'correct_answers': attempt.correct_answers,
            'wrong_answers': attempt.wrong_answers,
            'time_taken_seconds': attempt.time_taken_seconds,
            'xp_earned': attempt.xp_earned,
            'questions': build_review(attempt),
        })
        return Response(base)


class PreviousYearPaperViewSet(MockTestViewSet):
    """
    ViewSet for Previous Year Papers.
    Extends MockTestViewSet (inherits start, submit, review, leaderboard)
    but filters to only PYP papers.
    """
    queryset = MockTest.objects.filter(status='published', is_pyp=True)

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return PreviousYearPaperDetailSerializer
        return PreviousYearPaperSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filter by year
        year = self.request.query_params.get('year')
        if year:
            queryset = queryset.filter(pyp_year=year)
        
        # Filter by session
        session = self.request.query_params.get('session')
        if session:
            queryset = queryset.filter(pyp_session__icontains=session)
        
        return queryset.order_by('-pyp_year', 'pyp_session', 'pyp_shift')

    @action(detail=False, methods=['get'])
    def by_year(self, request):
        """
        Get PYPs grouped by year for the listing page.
        Returns: {years: [{year, papers: [{...}]}]}
        """
        queryset = self.get_queryset()
        
        # Get distinct years
        years = queryset.values_list('pyp_year', flat=True).distinct().order_by('-pyp_year')
        
        result = []
        for year in years:
            if year is None:
                continue
            papers = queryset.filter(pyp_year=year)
            serializer = PreviousYearPaperSerializer(
                papers, many=True, context={'request': request}
            )
            result.append({
                'year': year,
                'count': papers.count(),
                'papers': serializer.data,
            })
        
        return Response({'years': result})

    @action(detail=False, methods=['get'])
    def filter_options(self, request):
        """Get filter options for PYPs."""
        queryset = self.get_queryset()
        
        years = list(
            queryset.values_list('pyp_year', flat=True)
            .distinct().order_by('-pyp_year')
        )
        sessions = list(
            queryset.exclude(pyp_session='')
            .values_list('pyp_session', flat=True)
            .distinct().order_by('pyp_session')
        )
        
        return Response({
            'years': [y for y in years if y is not None],
            'sessions': sessions,
        })



class QuizAttemptViewSet(TenantAwareReadOnlyViewSet):
    """
    ViewSet for viewing quiz attempts.
    """
    serializer_class = QuizAttemptSummarySerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return QuizAttempt.objects.filter(
            student=self.request.user.profile
        ).order_by('-started_at')

    def retrieve(self, request, *args, **kwargs):
        """Get attempt with full answers for review."""
        instance = self.get_object()
        # Only show answers if attempt is completed
        if instance.status == 'completed':
            serializer = QuizAttemptSerializer(instance)
        else:
            serializer = QuizAttemptSummarySerializer(instance)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def recent(self, request):
        """Get recent quiz attempts."""
        attempts = self.get_queryset().filter(status='completed')[:10]
        return Response(QuizAttemptSummarySerializer(attempts, many=True).data)

    @action(detail=True, methods=['get'])
    def review(self, request, pk=None):
        """Get detailed review with all questions (including unanswered)."""
        attempt = self.get_object()
        
        if attempt.status != 'completed':
            return Response(
                {'error': 'Can only review completed attempts'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Use the new review serializer that includes all questions
        return Response(QuizAttemptReviewSerializer(attempt).data)


class MockTestAttemptViewSet(TenantAwareReadOnlyViewSet):
    """
    ViewSet for viewing mock test attempts.
    """
    serializer_class = MockTestAttemptSummarySerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return MockTestAttempt.objects.filter(
            student=self.request.user.profile
        ).order_by('-started_at')

    def retrieve(self, request, *args, **kwargs):
        """Get attempt with full answers for review."""
        instance = self.get_object()
        # Only show answers if attempt is completed
        if instance.status == 'completed':
            serializer = MockTestAttemptSerializer(instance)
        else:
            serializer = MockTestAttemptSummarySerializer(instance)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def recent(self, request):
        """Get recent mock test attempts."""
        attempts = self.get_queryset().filter(status='completed')[:10]
        return Response(MockTestAttemptSummarySerializer(attempts, many=True).data)

    @action(detail=True, methods=['get'])
    def review(self, request, pk=None):
        """Get detailed review with all questions (including unanswered)."""
        attempt = self.get_object()
        
        if attempt.status != 'completed':
            return Response(
                {'error': 'Can only review completed attempts'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Use the new review serializer that includes all questions
        return Response(MockTestAttemptReviewSerializer(attempt).data)


class QuestionReportViewSet(TenantAwareViewSet):
    """
    ViewSet for reporting problems with questions.
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        return QuestionReport.objects.filter(reported_by=self.request.user.profile)
    
    def get_serializer_class(self):
        if self.action == 'create':
            return QuestionReportCreateSerializer
        return QuestionReportSerializer
    
    def create(self, request, *args, **kwargs):
        """Create a new question report."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Check if user has already reported this question
        existing_report = QuestionReport.objects.filter(
            question=serializer.validated_data['question'],
            reported_by=request.user.profile,
            status__in=['pending', 'reviewing']
        ).first()
        
        if existing_report:
            return Response(
                {'error': 'You have already reported this question. Your report is being reviewed.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        self.perform_create(serializer)
        return Response(
            {'message': 'Thank you for your report. We will review it shortly.'},
            status=status.HTTP_201_CREATED
        )
    
    @action(detail=False, methods=['get'])
    def my_reports(self, request):
        """Get user's question reports."""
        reports = self.get_queryset().order_by('-created_at')[:20]
        return Response(QuestionReportSerializer(reports, many=True).data)

