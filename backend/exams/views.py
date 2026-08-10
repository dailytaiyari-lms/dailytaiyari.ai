"""
Views for Courses app.
"""
from rest_framework import viewsets, permissions, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Count, Q, Avg, Sum, F, Value, DecimalField
from django.db.models.functions import Coalesce

from .models import Course, Subject, Topic, Chapter
from .serializers import (
    CourseSerializer, CourseListSerializer, CourseDetailSerializer,
    SubjectSerializer, SubjectDetailSerializer,
    TopicSerializer, TopicDetailSerializer,
    ChapterSerializer, ChapterDetailSerializer
)
from core.views import TenantAwareReadOnlyViewSet


def _enrolled_course_ids(request):
    """
    IDs of every course the student is actively enrolled in (approved + active).

    Scoping subjects/topics to all enrolled courses — not just the primary
    course — lets multi-course students open subjects/topics from any enrolled
    course (e.g. Python while primary is Class XI). Returns None for
    non-students so the queryset stays tenant-scoped only.
    """
    if not request.user.is_authenticated:
        return None
    try:
        profile = request.user.profile
    except Exception:
        return None
    ids = list(
        profile.enrollments.filter(
            status='approved', is_active=True
        ).values_list('course_id', flat=True)
    )
    return ids or None


def _chapter_completion_counts(student, topic_ids):
    """
    Total vs. completed learnable items for a chapter's set of topics.

    Mirrors the per-chapter progress computation used in ``StudyChaptersView``
    (published content + quizzes + assignments + coding + labs). Returns a
    ``(total, completed)`` tuple. Used to decide sequential-unlock locking.
    """
    from content.models import Content, ContentProgress
    from quiz.models import Quiz, QuizAttempt
    from assignments.models import Assignment, AssignmentSubmission
    from coding.models import CodingProblem, CodingSubmission
    from notebooks.models import Notebook, NotebookCompletion

    if not topic_ids:
        return 0, 0

    content_count = Content.objects.filter(
        topic_id__in=topic_ids, status='published'
    ).count()
    content_done = ContentProgress.objects.filter(
        student=student, content__topic_id__in=topic_ids,
        content__status='published', is_completed=True,
    ).count()
    quiz_count = Quiz.objects.filter(
        topic_id__in=topic_ids, status='published',
    ).count()
    quiz_done = QuizAttempt.objects.filter(
        student=student, quiz__topic_id__in=topic_ids, status='completed',
    ).values('quiz').distinct().count()
    assignment_total = Assignment.objects.filter(
        topic_id__in=topic_ids, status='published',
    ).count()
    assignment_done = AssignmentSubmission.objects.filter(
        student=student, assignment__topic_id__in=topic_ids,
        assignment__status='published',
    ).values('assignment').distinct().count()
    coding_total = CodingProblem.objects.filter(
        topic_id__in=topic_ids, status='published',
    ).count()
    coding_done = CodingSubmission.objects.filter(
        student=student, problem__topic_id__in=topic_ids,
        problem__status='published', total_count__gt=0,
        passed_count=F('total_count'),
    ).values('problem').distinct().count()
    lab_total = Notebook.objects.filter(
        topic_id__in=topic_ids, status='published',
    ).count()
    lab_done = NotebookCompletion.objects.filter(
        student=student, notebook__topic_id__in=topic_ids,
        notebook__status='published', is_complete=True,
    ).count()

    total = content_count + quiz_count + assignment_total + coding_total + lab_total
    done = content_done + quiz_done + assignment_done + coding_done + lab_done
    return total, done


def _chapter_blocks_next(total, done):
    """A chapter blocks subsequent chapters only if it has unfinished items."""
    return total > 0 and done < total


class CourseViewSet(TenantAwareReadOnlyViewSet):
    """
    ViewSet for course operations.

    list: Get all active courses
    retrieve: Get course details with subjects
    subjects: Get all subjects for an course
    """
    queryset = Course.objects.filter(status='active')
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['course_type', 'is_featured']
    search_fields = ['name', 'code']

    def get_serializer_class(self):
        if self.action == 'list':
            return CourseListSerializer
        return CourseDetailSerializer

    @action(detail=True, methods=['get'])
    def subjects(self, request, pk=None):
        """Get all subjects for an course."""
        course = self.get_object()
        subjects = course.subjects.all()
        serializer = SubjectSerializer(subjects, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def topics(self, request, pk=None):
        """Get all topics for an course."""
        course = self.get_object()
        topics = Topic.objects.filter(courses=course)
        serializer = TopicSerializer(topics, many=True)
        return Response(serializer.data)


class SubjectViewSet(TenantAwareReadOnlyViewSet):
    """
    ViewSet for subject operations.
    """
    queryset = Subject.objects.all()
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['courses']
    search_fields = ['name', 'code']

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return SubjectDetailSerializer
        return SubjectSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.user.is_authenticated and not self.request.query_params.get('courses'):
            course_ids = _enrolled_course_ids(self.request)
            if course_ids:
                queryset = queryset.filter(course__in=course_ids)
        return queryset

    @action(detail=True, methods=['get'])
    def topics(self, request, pk=None):
        """Get all topics for a subject."""
        subject = self.get_object()
        topics = subject.topics.filter(parent_topic__isnull=True)
        serializer = TopicDetailSerializer(topics, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def chapters(self, request, pk=None):
        """Get all chapters for a subject."""
        subject = self.get_object()
        chapters = subject.chapters.all()
        serializer = ChapterSerializer(chapters, many=True)
        return Response(serializer.data)


class TopicViewSet(TenantAwareReadOnlyViewSet):
    """
    ViewSet for topic operations.
    """
    queryset = Topic.objects.all()
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['subject', 'difficulty', 'importance', 'parent_topic']
    search_fields = ['name', 'code']

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return TopicDetailSerializer
        return TopicSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.user.is_authenticated and not self.request.query_params.get('subject'):
            course_ids = _enrolled_course_ids(self.request)
            if course_ids:
                queryset = queryset.filter(subject__course__in=course_ids)
        return queryset

    @action(detail=True, methods=['get'])
    def subtopics(self, request, pk=None):
        """Get subtopics of a topic."""
        topic = self.get_object()
        subtopics = topic.subtopics.all()
        serializer = TopicSerializer(subtopics, many=True)
        return Response(serializer.data)


class ChapterViewSet(TenantAwareReadOnlyViewSet):
    """
    ViewSet for chapter operations.
    """
    queryset = Chapter.objects.all()
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['subject', 'grade']
    search_fields = ['name', 'code']

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return ChapterDetailSerializer
        return ChapterSerializer


class TenantContentExplorerView(APIView):
    """
    Hierarchical content explorer for Tenant Admins.
    Returns all active courses -> subjects -> chapters.
    """
    permission_classes = [permissions.IsAuthenticated] # Role check handled in frontend for now, or add IsTenantAdmin

    def get(self, request):
        if request.user.role != 'admin' and not request.user.is_superuser:
            return Response({"detail": "Permission denied"}, status=status.HTTP_403_FORBIDDEN)
            
        from .serializers import CourseContentExplorerSerializer
        courses = Course.objects.filter(status='active').prefetch_related(
            'subjects',
            'subjects__chapters',
            'subjects__quizzes',
            'mock_tests',
            'quizzes'
        ).order_by('name')
        
        serializer = CourseContentExplorerSerializer(courses, many=True)
        return Response(serializer.data)


# ──────────────────────────────────────────────────────────────────────────────
# Courses available for enrollment (dropdown / list) — not tenant-strict so list is never empty
# ──────────────────────────────────────────────────────────────────────────────

class AvailableCoursesForEnrollmentView(APIView):
    """
    Return active courses for the enrollment dropdown / public catalog. Course
    must belong to the request tenant. Public so anonymous visitors can browse
    the course catalog before signing up.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        qs = Course.objects.filter(status='active').order_by('name')
        if hasattr(request, 'tenant') and request.tenant:
            qs = qs.filter(tenant=request.tenant)
        qs = qs.prefetch_related('instructors')
        courses = list(qs)
        result = [
            {
                'id': str(e.id),
                'name': e.name,
                'code': e.code,
                'color': getattr(e, 'color', None) or '#3B82F6',
                'is_featured': getattr(e, 'is_featured', False),
                'course_type': getattr(e, 'course_type', '') or '',
                'description': getattr(e, 'description', '') or '',
                'thumbnail': (
                    e.thumbnail.url if getattr(e, 'thumbnail', None)
                    else (e.icon.url if getattr(e, 'icon', None) else None)
                ),
                'instructors': [
                    {'id': str(u.id), 'name': u.full_name or u.first_name or u.email}
                    for u in e.instructors.all()
                ],
                'pricing_type': e.pricing_type,
                'price': str(e.price),
                'original_price': str(e.original_price) if e.original_price is not None else None,
                'currency': e.currency,
                'is_free': e.is_free,
                'discount_percent': e.discount_percent,
                'subtitle': e.subtitle or '',
                'certificate_enabled': bool(getattr(e, 'certificate_enabled', False)),
                'enroll_mode': (
                    request.tenant.enroll_mode_for(e)
                    if getattr(request, 'tenant', None) else 'request'
                ),
            }
            for e in courses
        ]
        return Response(result)


# ──────────────────────────────────────────────────────────────────────────────
# Study Flow API — courses → subjects → chapters → content with progress
# ──────────────────────────────────────────────────────────────────────────────

class StudyCoursesView(APIView):
    """
    Return the user's enrolled courses for the Study tab.
    Only approved + active courses are usable; pending requests are returned
    separately so the UI can show them as awaiting admin approval.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from users.models import CourseEnrollment

        student = request.user.profile
        enrolled = CourseEnrollment.objects.filter(
            student=student
        ).exclude(status='rejected').select_related('course').order_by('enrolled_at')

        approved = []
        pending = []
        for e in enrolled:
            if not e.course or e.course.status != 'active':
                continue
            item = {
                'id': str(e.course.id),
                'name': e.course.name,
                'code': e.course.code,
                'color': getattr(e.course, 'color', None) or '#3B82F6',
                'is_featured': getattr(e.course, 'is_featured', False),
                'course_type': getattr(e.course, 'course_type', '') or '',
                'description': getattr(e.course, 'description', '') or '',
                'thumbnail': (
                    e.course.thumbnail.url if getattr(e.course, 'thumbnail', None)
                    else (e.course.icon.url if getattr(e.course, 'icon', None) else None)
                ),
                'enrollment_status': e.status,
            }
            if e.status == 'approved':
                approved.append(item)
            elif e.status == 'pending':
                pending.append(item)

        return Response({'courses': approved, 'pending': pending})


class StudySubjectsView(APIView):
    """
    Return subjects for the selected course with completion progress.
    Flow: Study tab → select course → this list of subjects.
    Query params: course_id (optional) — if omitted, uses the student's first
    approved enrollment.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from content.models import Content, ContentProgress
        from quiz.models import Quiz, QuizAttempt
        from assignments.models import Assignment, AssignmentSubmission
        from coding.models import CodingProblem, CodingSubmission
        from notebooks.models import Notebook, NotebookCompletion

        student = request.user.profile
        course_id = request.query_params.get('course_id')
        if course_id:
            try:
                course = Course.objects.get(pk=course_id, status='active')
            except Course.DoesNotExist:
                return Response({'error': 'Course not found'}, status=404)
        else:
            enrollment = student.enrollments.filter(
                status='approved', is_active=True, course__status='active'
            ).order_by('created_at').first()
            course = enrollment.course if enrollment else None
        if not course:
            return Response([])

        # Block access unless the student has an approved enrollment for this course
        from users.models import CourseEnrollment
        if not CourseEnrollment.objects.filter(
            student=student, course=course, status='approved'
        ).exists():
            return Response(
                {'error': 'Enrollment pending admin approval'}, status=403
            )

        reading_types = ['notes', 'pdf', 'revision', 'formula']

        subjects = Subject.objects.filter(course=course).order_by('order')
        result = []
        for subj in subjects:
            subj_topic_ids = list(subj.topics.values_list('id', flat=True))

            reading_total = Content.objects.filter(
                subject=subj, status='published',
                content_type__in=reading_types,
            ).count()
            reading_done = ContentProgress.objects.filter(
                student=student,
                content__subject=subj,
                content__status='published',
                content__content_type__in=reading_types,
                is_completed=True,
            ).count()

            video_total = Content.objects.filter(
                subject=subj, status='published', content_type='video',
            ).count()
            video_done = ContentProgress.objects.filter(
                student=student,
                content__subject=subj,
                content__status='published',
                content__content_type='video',
                is_completed=True,
            ).count()

            quiz_count = Quiz.objects.filter(
                subject=subj, course=course, status='published'
            ).count()
            quiz_done = QuizAttempt.objects.filter(
                student=student,
                quiz__subject=subj,
                quiz__course=course,
                quiz__status='published',
                status='completed',
            ).values('quiz').distinct().count()

            assignment_total = Assignment.objects.filter(
                topic_id__in=subj_topic_ids, status='published',
            ).count()
            assignment_done = AssignmentSubmission.objects.filter(
                student=student,
                assignment__topic_id__in=subj_topic_ids,
                assignment__status='published',
            ).values('assignment').distinct().count()

            coding_total = CodingProblem.objects.filter(
                topic_id__in=subj_topic_ids, status='published',
            ).count()
            coding_done = CodingSubmission.objects.filter(
                student=student,
                problem__topic_id__in=subj_topic_ids,
                problem__status='published',
                total_count__gt=0,
                passed_count=F('total_count'),
            ).values('problem').distinct().count()

            lab_total = Notebook.objects.filter(
                topic_id__in=subj_topic_ids, status='published',
            ).count()
            lab_done = NotebookCompletion.objects.filter(
                student=student,
                notebook__topic_id__in=subj_topic_ids,
                notebook__status='published',
                is_complete=True,
            ).count()

            content_count = reading_total + video_total
            content_done = reading_done + video_done

            total_content = (
                content_count + quiz_count + assignment_total + coding_total + lab_total
            )
            completed_content = (
                content_done + quiz_done + assignment_done + coding_done + lab_done
            )
            progress = (
                round((completed_content / total_content) * 100)
                if total_content > 0 else 0
            )

            chapters = subj.chapters.all().order_by('order')
            chapter_count = chapters.count()
            topic_count = subj.topics.count()

            result.append({
                'id': str(subj.id),
                'name': subj.name,
                'code': subj.code,
                'icon': subj.icon,
                'color': subj.color,
                'weightage': float(subj.weightage),
                'total_topics': topic_count,
                'total_chapters': chapter_count,
                'total_content': total_content,
                'completed_content': completed_content,
                'progress': progress,
                'reading': {'total': reading_total, 'completed': reading_done},
                'videos': {'total': video_total, 'completed': video_done},
                'quizzes': {'total': quiz_count, 'attempted': quiz_done},
                'assignments': {'total': assignment_total, 'completed': assignment_done},
                'coding': {'total': coding_total, 'completed': coding_done},
                'labs': {'total': lab_total, 'completed': lab_done},
            })

        return Response(result)


class StudyChaptersView(APIView):
    """
    Return chapters for a subject with ordered topics in each chapter.
    Flow: Subject → Chapters → each chapter has topics (ordered).
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, subject_id):
        from content.models import Content, ContentProgress
        from quiz.models import Quiz, QuizAttempt
        from assignments.models import Assignment, AssignmentSubmission
        from coding.models import CodingProblem, CodingSubmission
        from notebooks.models import Notebook, NotebookCompletion

        student = request.user.profile
        try:
            subject = Subject.objects.select_related('course').get(pk=subject_id)
        except Subject.DoesNotExist:
            return Response({'error': 'Subject not found'}, status=404)

        sequential = bool(getattr(subject.course, 'sequential_chapter_unlock', False))
        chapters = subject.chapters.all().order_by('order').prefetch_related(
            'chapter_topics__topic'
        )
        result = []
        for ch in chapters:
            # Ordered topics via ChapterTopic (prefetched)
            chapter_topic_qs = ch.chapter_topics.select_related('topic').order_by('order')
            topic_ids = []
            topic_list = []
            for ct in chapter_topic_qs:
                topic_ids.append(ct.topic_id)
                topic_list.append({
                    'id': str(ct.topic.id),
                    'name': ct.topic.name,
                    'code': ct.topic.code,
                    'order': ct.order,
                })

            content_count = Content.objects.filter(
                topic_id__in=topic_ids, status='published'
            ).count()
            content_done = ContentProgress.objects.filter(
                student=student,
                content__topic_id__in=topic_ids,
                content__status='published',
                is_completed=True,
            ).count()
            quiz_count = Quiz.objects.filter(
                topic_id__in=topic_ids, status='published',
            ).count()
            quiz_done = QuizAttempt.objects.filter(
                student=student,
                quiz__topic_id__in=topic_ids,
                status='completed',
            ).values('quiz').distinct().count()

            reading_total = Content.objects.filter(
                topic_id__in=topic_ids, status='published',
                content_type__in=['notes', 'pdf', 'revision', 'formula'],
            ).count()
            reading_done = ContentProgress.objects.filter(
                student=student,
                content__topic_id__in=topic_ids,
                content__status='published',
                content__content_type__in=['notes', 'pdf', 'revision', 'formula'],
                is_completed=True,
            ).count()

            video_total = Content.objects.filter(
                topic_id__in=topic_ids, status='published',
                content_type='video',
            ).count()
            video_done = ContentProgress.objects.filter(
                student=student,
                content__topic_id__in=topic_ids,
                content__status='published',
                content__content_type='video',
                is_completed=True,
            ).count()

            quiz_total = Quiz.objects.filter(
                topic_id__in=topic_ids, status='published',
            ).count()
            quiz_attempted = QuizAttempt.objects.filter(
                student=student,
                quiz__topic_id__in=topic_ids,
                status='completed',
            ).values('quiz').distinct().count()

            assignment_total = Assignment.objects.filter(
                topic_id__in=topic_ids, status='published',
            ).count()
            assignment_done = AssignmentSubmission.objects.filter(
                student=student,
                assignment__topic_id__in=topic_ids,
                assignment__status='published',
            ).values('assignment').distinct().count()

            coding_total = CodingProblem.objects.filter(
                topic_id__in=topic_ids, status='published',
            ).count()
            coding_done = CodingSubmission.objects.filter(
                student=student,
                problem__topic_id__in=topic_ids,
                problem__status='published',
                total_count__gt=0,
                passed_count=F('total_count'),
            ).values('problem').distinct().count()

            lab_total = Notebook.objects.filter(
                topic_id__in=topic_ids, status='published',
            ).count()
            lab_done = NotebookCompletion.objects.filter(
                student=student,
                notebook__topic_id__in=topic_ids,
                notebook__status='published',
                is_complete=True,
            ).count()

            total_content = (
                content_count + quiz_count + assignment_total + coding_total + lab_total
            )
            completed_content = (
                content_done + quiz_done + assignment_done + coding_done + lab_done
            )

            progress = (
                round((completed_content / total_content) * 100)
                if total_content > 0 else 0
            )

            result.append({
                'id': str(ch.id),
                'name': ch.name,
                'code': ch.code,
                'description': ch.description,
                'estimated_hours': float(ch.estimated_hours),
                'topics_count': len(topic_ids),
                'topics': topic_list,
                'order': ch.order,
                'progress': progress,
                'is_completed': total_content > 0 and completed_content >= total_content,
                'is_locked': False,
                'reading': {'total': reading_total, 'completed': reading_done},
                'videos': {'total': video_total, 'completed': video_done},
                'quizzes': {'total': quiz_total, 'attempted': quiz_attempted},
                'assignments': {'total': assignment_total, 'completed': assignment_done},
                'coding': {'total': coding_total, 'completed': coding_done},
                'labs': {'total': lab_total, 'completed': lab_done},
                '_blocks_next': _chapter_blocks_next(total_content, completed_content),
            })

        # Sequential unlock: a chapter stays locked until every preceding
        # chapter (that has content) is fully completed.
        if sequential:
            unlocked = True
            for item in result:
                item['is_locked'] = not unlocked
                if item.pop('_blocks_next'):
                    unlocked = False
        else:
            for item in result:
                item.pop('_blocks_next', None)

        return Response({
            'subject': {
                'id': str(subject.id),
                'name': subject.name,
                'code': subject.code,
                'color': subject.color,
            },
            'sequential_unlock': sequential,
            'chapters': result,
        })


class StudyChapterDetailView(APIView):
    """
    Return chapter detail with topics; each topic has reading materials and quizzes.
    Flow: Chapter → Topics → each topic has reading (content) + quizzes.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, chapter_id):
        from content.models import Content, ContentProgress
        from quiz.models import Quiz, QuizAttempt
        from assignments.models import Assignment, AssignmentSubmission
        from coding.models import CodingProblem, CodingSubmission
        from notebooks.models import Notebook, NotebookCompletion

        student = request.user.profile
        try:
            chapter = Chapter.objects.select_related('subject', 'subject__course').prefetch_related(
                'chapter_topics__topic'
            ).get(pk=chapter_id)
        except Chapter.DoesNotExist:
            return Response({'error': 'Chapter not found'}, status=404)

        # Sequential unlock: when a preceding chapter in the same subject is not
        # yet fully completed, this chapter is "locked". We no longer hard-block
        # the request (that hid the chapter's topics entirely). Instead we return
        # the topic list as usual but flag it as locked, so the UI can preview the
        # contents, show a lock indicator, and prevent entering a topic.
        locked = False
        locked_by = None
        if getattr(chapter.subject.course, 'sequential_chapter_unlock', False):
            preceding = chapter.subject.chapters.filter(
                order__lt=chapter.order
            ).order_by('order').prefetch_related('chapter_topics')
            for prev in preceding:
                if prev.id == chapter.id:
                    continue
                prev_topic_ids = [ct.topic_id for ct in prev.chapter_topics.all()]
                total, done = _chapter_completion_counts(student, prev_topic_ids)
                if _chapter_blocks_next(total, done):
                    locked = True
                    locked_by = {
                        'id': str(prev.id),
                        'name': prev.name,
                        'subject_id': str(chapter.subject_id),
                    }
                    break

        def _chapter_dict():
            return {
                'id': str(chapter.id),
                'name': chapter.name,
                'code': chapter.code,
                'description': chapter.description,
                'subject_name': chapter.subject.name,
                'subject_id': str(chapter.subject.id),
                'course_id': str(chapter.subject.course_id),
                'course_name': chapter.subject.course.name,
                'estimated_hours': float(chapter.estimated_hours),
                'locked': locked,
                'locked_by': locked_by,
            }

        # Ordered topics in this chapter
        chapter_topics = list(
            chapter.chapter_topics.select_related('topic').order_by('order')
        )
        topic_ids = [ct.topic_id for ct in chapter_topics]

        if not topic_ids:
            return Response({
                'chapter': _chapter_dict(),
                'topics': [],
            })

        contents = Content.objects.filter(
            topic_id__in=topic_ids, status='published'
        ).order_by('topic_id', 'order')
        progress_map = {
            cp.content_id: cp
            for cp in ContentProgress.objects.filter(
                student=student, content__in=contents
            )
        }
        quizzes = Quiz.objects.filter(
            topic_id__in=topic_ids, status='published'
        ).prefetch_related('questions')
        attempt_map = {}
        for qa in QuizAttempt.objects.filter(
            student=student, quiz__in=quizzes, status='completed'
        ).order_by('-completed_at'):
            if qa.quiz_id not in attempt_map:
                attempt_map[qa.quiz_id] = []
            attempt_map[qa.quiz_id].append({
                'id': str(qa.id),
                'percentage': float(qa.percentage),
                'correct_answers': qa.correct_answers,
                'total_questions': qa.total_questions,
                'completed_at': qa.completed_at.isoformat() if qa.completed_at else None,
            })

        # Build per-topic: reading (notes, revision, pdf, formula) + videos + quizzes
        content_by_topic = {}
        for c in contents:
            tid = str(c.topic_id)
            if tid not in content_by_topic:
                content_by_topic[tid] = {'reading': [], 'videos': []}
            cp = progress_map.get(c.id)
            item = {
                'id': str(c.id),
                'title': c.title,
                'content_type': c.content_type,
                'material_kind': c.material_kind,
                'order': c.order,
                'estimated_time_minutes': c.estimated_time_minutes,
                'video_duration_minutes': c.video_duration_minutes,
                'difficulty': c.difficulty,
                'is_free': c.is_free,
                'views_count': c.views_count,
                'is_completed': cp.is_completed if cp else False,
                'progress_percentage': cp.progress_percentage if cp else 0,
                'video_position_seconds': cp.video_position_seconds if cp else 0,
                'is_bookmarked': cp.is_bookmarked if cp else False,
            }
            if c.content_type == 'video':
                content_by_topic[tid]['videos'].append(item)
            else:
                content_by_topic[tid]['reading'].append(item)

        quiz_by_topic = {}
        for q in quizzes:
            tid = str(q.topic_id) if q.topic_id else None
            if tid not in quiz_by_topic:
                quiz_by_topic[tid] = []
            attempts = attempt_map.get(q.id, [])
            best = max((a['percentage'] for a in attempts), default=0) if attempts else 0
            quiz_by_topic[tid].append({
                'id': str(q.id),
                'title': q.title,
                'quiz_type': q.quiz_type,
                'duration_minutes': q.duration_minutes,
                'total_questions': q.questions.count(),
                'is_free': q.is_free,
                'attempts_count': len(attempts),
                'best_score': best,
                'last_attempt': attempts[0] if attempts else None,
            })

        assignments = Assignment.objects.filter(
            topic_id__in=topic_ids, status='published'
        ).order_by('topic_id', 'order')
        submission_map = {
            s.assignment_id: s
            for s in AssignmentSubmission.objects.filter(
                student=student, assignment__in=assignments
            )
        }
        assignment_by_topic = {}
        for a in assignments:
            tid = str(a.topic_id)
            if tid not in assignment_by_topic:
                assignment_by_topic[tid] = []
            sub = submission_map.get(a.id)
            assignment_by_topic[tid].append({
                'id': str(a.id),
                'title': a.title,
                'submission_type': a.submission_type,
                'is_timed': a.is_timed,
                'due_at': a.due_at.isoformat() if a.due_at else None,
                'max_marks': a.max_marks,
                'is_open': a.is_open,
                'is_completed': sub is not None,
                'submission_status': sub.status if sub else None,
            })

        coding_problems = CodingProblem.objects.filter(
            topic_id__in=topic_ids, status='published'
        ).order_by('topic_id', 'order')
        coding_sub_map = {}
        for cs in CodingSubmission.objects.filter(
            student=student, problem__in=coding_problems
        ):
            info = coding_sub_map.setdefault(
                cs.problem_id, {'attempts': 0, 'solved': False}
            )
            info['attempts'] += 1
            if cs.total_count > 0 and cs.passed_count == cs.total_count:
                info['solved'] = True
        coding_by_topic = {}
        for p in coding_problems:
            tid = str(p.topic_id)
            info = coding_sub_map.get(p.id, {'attempts': 0, 'solved': False})
            coding_by_topic.setdefault(tid, []).append({
                'id': str(p.id),
                'title': p.title,
                'difficulty': p.difficulty,
                'max_marks': p.max_marks,
                'attempts_count': info['attempts'],
                'is_completed': info['solved'],
            })

        labs = Notebook.objects.filter(
            topic_id__in=topic_ids, status='published'
        ).order_by('topic_id', 'order')
        lab_completion_map = {
            nc.notebook_id: nc
            for nc in NotebookCompletion.objects.filter(
                student=student, notebook__in=labs,
            )
        }
        lab_by_topic = {}
        for nb in labs:
            tid = str(nb.topic_id)
            done = lab_completion_map.get(nb.id)
            lab_by_topic.setdefault(tid, []).append({
                'id': str(nb.id),
                'title': nb.title,
                'difficulty': nb.difficulty,
                'max_marks': nb.max_marks,
                'estimated_time_minutes': nb.estimated_time_minutes,
                'attempts_count': done.attempts_used if done else 0,
                'is_completed': bool(done and done.is_complete),
            })

        topics_payload = []
        for ct in chapter_topics:
            t = ct.topic
            tid = str(t.id)
            topics_payload.append({
                'topic': {
                    'id': tid,
                    'name': t.name,
                    'code': t.code,
                    'order': ct.order,
                    'difficulty': t.difficulty,
                    'importance': t.importance,
                    'estimated_study_hours': float(t.estimated_study_hours),
                },
                'reading': content_by_topic.get(tid, {}).get('reading', []),
                'videos': content_by_topic.get(tid, {}).get('videos', []),
                'quizzes': quiz_by_topic.get(tid, []),
                'assignments': assignment_by_topic.get(tid, []),
                'coding': coding_by_topic.get(tid, []),
                'labs': lab_by_topic.get(tid, []),
            })

        return Response({
            'chapter': _chapter_dict(),
            'topics': topics_payload,
        })


class StudyLeaderboardView(APIView):
    """Scoped leaderboard at subject, chapter, or quiz level."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from analytics.models import DailyActivity
        from users.models import StudentProfile

        tenant = getattr(request, 'tenant', None)
        if not tenant:
            return Response([])

        scope = request.query_params.get('scope', 'subject')
        scope_id = request.query_params.get('scope_id')
        student = request.user.profile

        if scope == 'quiz' and scope_id:
            return self._quiz_leaderboard(tenant, student, scope_id)

        if scope == 'course' and scope_id:
            return self._course_leaderboard(tenant, student, scope_id)

        if scope == 'subject' and scope_id:
            topic_ids = Topic.objects.filter(subject_id=scope_id).values_list('id', flat=True)
        elif scope == 'chapter' and scope_id:
            try:
                ch = Chapter.objects.get(pk=scope_id)
            except Chapter.DoesNotExist:
                return Response([])
            topic_ids = ch.chapter_topics.values_list('topic_id', flat=True)
        else:
            return Response([])

        from quiz.models import QuizAttempt
        from content.models import ContentProgress
        from content.models import Content
        from quiz.models import Quiz
        from gamification.models import XPTransaction

        quiz_qs = (
            QuizAttempt.objects.filter(
                quiz__topic_id__in=topic_ids,
                status='completed',
                student__user__tenant=tenant,
            )
            .values('student')
            .annotate(
                total_correct=Sum('correct_answers'),
                total_attempted=Sum('total_questions'),
                avg_accuracy=Avg('percentage'),
            )
        )
        
        # Collect base stats per student
        student_stats = {}
        for entry in quiz_qs:
            sid = entry['student']
            student_stats[sid] = {
                'total_xp': 0,
                'avg_accuracy': entry['avg_accuracy'],
            }
            
        # Get reference_ids for XPTransactions: content uses content.id; quiz_complete uses attempt.id (not quiz.id)
        content_ids = list(Content.objects.filter(topic_id__in=topic_ids).values_list('id', flat=True))
        quiz_attempt_ids = list(
            QuizAttempt.objects.filter(
                quiz__topic_id__in=topic_ids,
                status='completed',
                student__user__tenant=tenant,
            ).values_list('id', flat=True)
        )
        all_refs = content_ids + quiz_attempt_ids
        
        xp_qs = XPTransaction.objects.filter(
            reference_id__in=all_refs,
            student__user__tenant=tenant,
        ).values('student').annotate(
            total_earned=Sum('xp_amount')
        )
        
        for xp_entry in xp_qs:
            sid = xp_entry['student']
            if sid not in student_stats:
                student_stats[sid] = {
                    'total_xp': 0,
                    'avg_accuracy': 0,
                }
            student_stats[sid]['total_xp'] += xp_entry['total_earned'] or 0

        # Sort by XP descending, keep top 20
        sorted_students = sorted(
            [(sid, stats) for sid, stats in student_stats.items() if stats['total_xp'] > 0],
            key=lambda x: x[1]['total_xp'],
            reverse=True
        )[:20]

        profiles = {
            str(p.id): p
            for p in StudentProfile.objects.select_related('user').filter(
                id__in=[sid for sid, stats in sorted_students],
                user__tenant=tenant,
            )
        }

        entries = []
        rank = 1
        for sid, stats in sorted_students:
            p = profiles.get(str(sid))
            if not p:
                continue
            entries.append({
                'rank': rank,
                'student_name': p.user.full_name,
                'role': p.user.role,
                'avatar': p.user.avatar.url if p.user.avatar else None,
                'total_xp': stats['total_xp'],
                'accuracy': round(float(stats['avg_accuracy'] or 0), 1),
                'is_current_user': p.id == student.id,
            })
            rank += 1



        return Response(entries)

    def _quiz_leaderboard(self, tenant, student, quiz_id):
        """Rank students by their best completed attempt on a single quiz."""
        from quiz.models import QuizAttempt

        attempts = (
            QuizAttempt.objects.filter(
                quiz_id=quiz_id,
                status='completed',
                student__user__tenant=tenant,
            )
            .select_related('student__user')
        )

        # Keep each student's best attempt: highest percentage, then fastest.
        best = {}
        for a in attempts:
            cur = best.get(a.student_id)
            score = (float(a.percentage or 0), -(a.time_taken_seconds or 0))
            if cur is None or score > cur[0]:
                best[a.student_id] = (score, a)

        ranked = sorted(
            (a for _score, a in best.values()),
            key=lambda a: (
                -float(a.percentage or 0),
                a.time_taken_seconds or 0,
            ),
        )[:20]

        entries = []
        for rank, a in enumerate(ranked, start=1):
            p = a.student
            entries.append({
                'rank': rank,
                'student_name': p.user.full_name,
                'role': p.user.role,
                'avatar': p.user.avatar.url if p.user.avatar else None,
                'total_xp': a.xp_earned or 0,
                'xp_earned': a.xp_earned or 0,
                'accuracy': round(float(a.percentage or 0), 1),
                'marks_obtained': float(a.marks_obtained or 0),
                'total_marks': float(a.total_marks or 0),
                'time_taken_seconds': a.time_taken_seconds or 0,
                'is_current_user': p.id == student.id,
            })

        return Response(entries)

    def _course_leaderboard(self, tenant, student, course_id):
        """Rank enrolled students by their overall completion percentage in a course."""
        from content.models import Content, ContentProgress
        from quiz.models import Quiz, QuizAttempt
        from assignments.models import Assignment, AssignmentSubmission
        from coding.models import CodingProblem, CodingSubmission
        from notebooks.models import Notebook, NotebookCompletion
        from users.models import CourseEnrollment, StudentProfile

        try:
            course = Course.objects.get(pk=course_id)
        except Course.DoesNotExist:
            return Response([])

        content_types = ['notes', 'pdf', 'revision', 'formula', 'video']
        topic_ids = list(Topic.objects.filter(subject__course=course).values_list('id', flat=True))

        # Fixed denominator: every published item across the course.
        content_total = Content.objects.filter(
            subject__course=course, status='published', content_type__in=content_types,
        ).count()
        quiz_total = Quiz.objects.filter(course=course, status='published').count()
        assignment_total = Assignment.objects.filter(
            topic_id__in=topic_ids, status='published',
        ).count()
        coding_total = CodingProblem.objects.filter(
            topic_id__in=topic_ids, status='published',
        ).count()
        lab_total = Notebook.objects.filter(
            topic_id__in=topic_ids, status='published',
        ).count()
        grand_total = (
            content_total + quiz_total + assignment_total + coding_total + lab_total
        )
        if grand_total == 0:
            return Response([])

        # Per-student completed counts (distinct items) via grouped aggregates.
        completed = {}

        def _accumulate(qs):
            for row in qs:
                sid = row['student']
                completed[sid] = completed.get(sid, 0) + (row['c'] or 0)

        _accumulate(
            ContentProgress.objects.filter(
                content__subject__course=course,
                content__status='published',
                content__content_type__in=content_types,
                is_completed=True,
                student__user__tenant=tenant,
            ).values('student').annotate(c=Count('content', distinct=True))
        )
        _accumulate(
            QuizAttempt.objects.filter(
                quiz__course=course, quiz__status='published', status='completed',
                student__user__tenant=tenant,
            ).values('student').annotate(c=Count('quiz', distinct=True))
        )
        _accumulate(
            AssignmentSubmission.objects.filter(
                assignment__topic_id__in=topic_ids, assignment__status='published',
                student__user__tenant=tenant,
            ).values('student').annotate(c=Count('assignment', distinct=True))
        )
        _accumulate(
            CodingSubmission.objects.filter(
                problem__topic_id__in=topic_ids, problem__status='published',
                total_count__gt=0, passed_count=F('total_count'),
                student__user__tenant=tenant,
            ).values('student').annotate(c=Count('problem', distinct=True))
        )
        _accumulate(
            NotebookCompletion.objects.filter(
                notebook__topic_id__in=topic_ids, notebook__status='published',
                is_complete=True, student__user__tenant=tenant,
            ).values('student').annotate(c=Count('notebook', distinct=True))
        )

        # Only rank students actively enrolled in this course.
        enrolled_ids = set(
            str(sid) for sid in CourseEnrollment.objects.filter(
                course=course, status='approved',
            ).values_list('student_id', flat=True)
        )

        ranked = sorted(
            (
                (str(sid), done) for sid, done in completed.items()
                if str(sid) in enrolled_ids and done > 0
            ),
            key=lambda x: x[1],
            reverse=True,
        )[:20]

        profiles = {
            str(p.id): p
            for p in StudentProfile.objects.select_related('user').filter(
                id__in=[sid for sid, _ in ranked], user__tenant=tenant,
            )
        }

        entries = []
        rank = 1
        for sid, done in ranked:
            p = profiles.get(sid)
            if not p:
                continue
            entries.append({
                'rank': rank,
                'student_name': p.user.full_name,
                'role': p.user.role,
                'avatar': p.user.avatar.url if p.user.avatar else None,
                'completion': round((done / grand_total) * 100),
                'completed_content': done,
                'total_content': grand_total,
                'is_current_user': p.id == student.id,
            })
            rank += 1

        return Response(entries)
