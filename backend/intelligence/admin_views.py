"""Tenant-admin / instructor endpoints (/api/v1/tenant-admin/intelligence/).

Every read here is a thin serialization over the foundation tables — no new
computation pipelines live in the product layer.
"""
from django.db.models import Avg, Count, Q
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from exams.models import Course

from .models import (
    Concept, CoursePracticeConfig, GeneratedItem, ItemStats, LearnerConceptState,
    PracticeGenerationJob, PracticeSet,
)
from .recommendation import practice_config_for
from .serializers import MasteryRowSerializer, PracticeSetSerializer


class IsTenantAdminOrInstructor(permissions.BasePermission):
    """Teacher-visible surfaces: tenant admins and faculty both see them."""

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user and user.is_authenticated
            and getattr(user, 'role', '') in ('admin', 'instructor')
        )


def _course_or_404(request, course_id):
    return Course.objects.filter(id=course_id, tenant=request.tenant).first()


class TaggingRunView(APIView):
    """On-demand tagging pass for this tenant (queued on the AI worker)."""

    permission_classes = [permissions.IsAuthenticated, IsTenantAdminOrInstructor]

    def post(self, request):
        from .tasks import tag_items_for_tenant

        tenant = getattr(request, 'tenant', None)
        if tenant is None:
            return Response({'error': 'Tenant required.'}, status=status.HTTP_400_BAD_REQUEST)
        tag_items_for_tenant.delay(str(tenant.id))
        return Response({'queued': True})


class OverviewView(APIView):
    """InsightsHome tiles for one course."""

    permission_classes = [permissions.IsAuthenticated, IsTenantAdminOrInstructor]

    def get(self, request):
        course = _course_or_404(request, request.query_params.get('course'))
        if course is None:
            return Response({'error': 'Course not found.'}, status=status.HTTP_404_NOT_FOUND)

        # Class concept mastery (only concepts with real evidence).
        concept_rows = (
            LearnerConceptState.objects.filter(
                concept__subject__course=course, evidence_count__gte=3,
            )
            .values('concept_id', 'concept__name', 'concept__subject__name')
            .annotate(avg_mastery=Avg('mastery'), students=Count('student_id', distinct=True))
            .order_by('avg_mastery')[:30]
        )

        month_ago = timezone.now() - timezone.timedelta(days=30)
        sets = PracticeSet.objects.filter(course=course, created_at__gte=month_ago)
        deficit_counts = dict(
            sets.filter(status__in=['suggested', 'in_progress'])
            .values_list('deficit_kind').annotate(n=Count('id'))
        )

        flagged_items = ItemStats.objects.filter(
            Q(question__courses=course) | Q(mock_item__mock_test__courses=course)
            | Q(mock_item__mock_test__course=course),
            difficulty_divergence=True,
        ).count()

        generated = GeneratedItem.objects.filter(question__courses=course)
        return Response({
            'course': {'id': str(course.id), 'name': course.name},
            'config': CoursePracticeConfigView._payload(practice_config_for(course)),
            'concepts': [
                {
                    'concept_id': str(row['concept_id']),
                    'name': row['concept__name'],
                    'subject': row['concept__subject__name'],
                    'avg_mastery': round(row['avg_mastery'] or 0, 3),
                    'students': row['students'],
                }
                for row in concept_rows
            ],
            'deficit_counts': deficit_counts,
            'practice_adoption': {
                'suggested': sets.count(),
                'completed': sets.filter(status='completed').count(),
                'dismissed': sets.filter(status='dismissed').count(),
            },
            'flagged_items': flagged_items,
            'generated_pool': {
                'active': generated.filter(retired_at__isnull=True).count(),
                'retired': generated.filter(retired_at__isnull=False).count(),
            },
        })


class AssessmentReportView(APIView):
    """Per-assessment intelligence report: item quality + concept performance."""

    permission_classes = [permissions.IsAuthenticated, IsTenantAdminOrInstructor]

    def get(self, request, kind, assessment_id):
        from quiz.models import MockTest, Quiz

        if kind == 'mock':
            assessment = MockTest.objects.filter(id=assessment_id, tenant=request.tenant).first()
        elif kind == 'quiz':
            assessment = Quiz.objects.filter(id=assessment_id, tenant=request.tenant).first()
        else:
            assessment = None
        if assessment is None:
            return Response({'error': 'Assessment not found.'}, status=status.HTTP_404_NOT_FOUND)

        items = self._items(kind, assessment)
        concept_perf = {}
        rows = []
        for item, stats in items:
            links = list(item.concept_links.select_related('concept'))
            concepts = [link.concept.name for link in links]
            row = {
                'item_id': str(item.id),
                'question_text': (item.question_text or '')[:200],
                'item_type': getattr(item, 'item_type', getattr(item, 'question_type', '')),
                'difficulty': getattr(item, 'difficulty', ''),
                'cognitive_type': getattr(item, 'cognitive_type', ''),
                'concepts': concepts,
                'stats': None,
            }
            if stats:
                row['stats'] = {
                    'attempts': stats.attempts_count,
                    'p_value': stats.p_value,
                    'observed_difficulty': stats.observed_difficulty,
                    'difficulty_divergence': stats.difficulty_divergence,
                    'discrimination': stats.discrimination,
                    'avg_time_seconds': stats.avg_time_seconds,
                    'option_distribution': stats.option_distribution,
                }
                for link in links:
                    bucket = concept_perf.setdefault(
                        link.concept.name, {'attempts': 0, 'correct': 0},
                    )
                    bucket['attempts'] += stats.attempts_count
                    bucket['correct'] += stats.correct_count
            rows.append(row)

        tested_concepts = {name for row in rows for name in row['concepts']}
        untested = list(
            Concept.objects.filter(
                subject__course__in=self._courses(kind, assessment), status='active',
            )
            .exclude(name__in=tested_concepts)
            .values_list('name', flat=True)[:40]
        )

        return Response({
            'assessment': {'id': str(assessment.id), 'title': assessment.title, 'kind': kind},
            'items': rows,
            'concept_performance': [
                {
                    'concept': name,
                    'attempts': data['attempts'],
                    'accuracy': round(data['correct'] / data['attempts'], 3) if data['attempts'] else None,
                }
                for name, data in sorted(concept_perf.items())
            ],
            'untested_concepts': untested,
        })

    @staticmethod
    def _items(kind, assessment):
        if kind == 'mock':
            items = assessment.items.prefetch_related('concept_links__concept')
        else:
            items = [
                qq.question
                for qq in assessment.quizquestion_set.select_related('question')
            ]
        result = []
        for item in items:
            try:
                stats = item.item_stats
            except Exception:
                stats = None
            result.append((item, stats))
        return result

    @staticmethod
    def _courses(kind, assessment):
        if kind == 'quiz':
            return [assessment.course] if assessment.course_id else []
        courses = list(assessment.courses.all())
        if not courses and assessment.course_id:
            courses = [assessment.course]
        return courses


class StudentDiagnosisView(APIView):
    """One student's concept map, deficits and suggestion audit trail."""

    permission_classes = [permissions.IsAuthenticated, IsTenantAdminOrInstructor]

    def get(self, request, student_id):
        from users.models import StudentProfile

        student = StudentProfile.objects.filter(
            id=student_id, user__tenant=request.tenant,
        ).select_related('user').first()
        if student is None:
            return Response({'error': 'Student not found.'}, status=status.HTTP_404_NOT_FOUND)

        states = (
            LearnerConceptState.objects.filter(student=student)
            .select_related('concept__subject')
            .order_by('mastery')
        )
        course_id = request.query_params.get('course')
        if course_id:
            states = states.filter(concept__subject__course_id=course_id)

        sets = (
            PracticeSet.objects.filter(student=student)
            .select_related('course').prefetch_related('target_concepts', 'items')
            .order_by('-created_at')[:30]
        )
        return Response({
            'student': {
                'id': str(student.id),
                'name': (getattr(student.user, 'full_name', '') or student.user.email),
                'email': student.user.email,
            },
            'concepts': MasteryRowSerializer(states[:200], many=True).data,
            'practice_history': PracticeSetSerializer(sets, many=True).data,
        })


class GeneratedItemsView(APIView):
    """Provenance list for AI-generated practice questions (review surface)."""

    permission_classes = [permissions.IsAuthenticated, IsTenantAdminOrInstructor]

    def get(self, request):
        rows = (
            GeneratedItem.objects.filter(tenant=request.tenant)
            .select_related('question')
            .order_by('-created_at')
        )
        course_id = request.query_params.get('course')
        if course_id:
            rows = rows.filter(question__courses__id=course_id)
        payload = []
        for row in rows[:200]:
            stats = None
            try:
                stats = row.question.item_stats
            except Exception:
                stats = None
            payload.append({
                'id': str(row.id),
                'question_id': str(row.question_id),
                'question_text': row.question.question_text[:200],
                'deficit_kind': row.deficit_kind,
                'target_misconception': row.target_misconception,
                'times_served': row.times_served,
                'times_answered': row.times_answered,
                'retired_at': row.retired_at.isoformat() if row.retired_at else None,
                'p_value': stats.p_value if stats else None,
                'discrimination': stats.discrimination if stats else None,
                'flagged': bool(stats.difficulty_divergence) if stats else False,
                'created_at': row.created_at.isoformat(),
            })
        return Response(payload)

    def post(self, request):
        """Retire a generated item: archived from the pool, history preserved."""
        row = GeneratedItem.objects.filter(
            id=request.data.get('id'), tenant=request.tenant,
        ).select_related('question').first()
        if row is None:
            return Response({'error': 'Item not found.'}, status=status.HTTP_404_NOT_FOUND)
        row.retired_at = timezone.now()
        row.save(update_fields=['retired_at', 'updated_at'])
        row.question.status = 'archived'
        row.question.save(update_fields=['status', 'updated_at'])
        return Response({'retired': True})


class GenerationJobsView(APIView):
    """Observability for practice-generation jobs."""

    permission_classes = [permissions.IsAuthenticated, IsTenantAdminOrInstructor]

    def get(self, request):
        jobs = (
            PracticeGenerationJob.objects.filter(tenant=request.tenant)
            .select_related('course').order_by('-created_at')[:100]
        )
        return Response([
            {
                'id': str(job.id),
                'course': job.course.name if job.course_id else '',
                'deficit_kind': job.deficit_kind,
                'deficit_signature': job.deficit_signature,
                'status': job.status,
                'error': job.error,
                'total_tokens': job.total_tokens,
                'applied_summary': job.applied_summary,
                'created_at': job.created_at.isoformat(),
            }
            for job in jobs
        ])


class CoursePracticeConfigView(APIView):
    """Per-course practice toggle + knobs (the teacher's off switch)."""

    permission_classes = [permissions.IsAuthenticated, IsTenantAdminOrInstructor]

    def get(self, request, course_id):
        course = _course_or_404(request, course_id)
        if course is None:
            return Response({'error': 'Course not found.'}, status=status.HTTP_404_NOT_FOUND)
        config = practice_config_for(course)
        return Response(self._payload(config))

    def patch(self, request, course_id):
        course = _course_or_404(request, course_id)
        if course is None:
            return Response({'error': 'Course not found.'}, status=status.HTTP_404_NOT_FOUND)
        config = practice_config_for(course)
        for field in ('practice_enabled', 'generation_enabled'):
            if field in request.data:
                setattr(config, field, bool(request.data[field]))
        for field in ('max_active_sets', 'daily_xp_set_cap'):
            if field in request.data:
                try:
                    setattr(config, field, max(0, int(request.data[field])))
                except (TypeError, ValueError):
                    pass
        config.save()
        return Response(self._payload(config))

    @staticmethod
    def _payload(config: CoursePracticeConfig):
        return {
            'course': str(config.course_id),
            'practice_enabled': config.practice_enabled,
            'generation_enabled': config.generation_enabled,
            'max_active_sets': config.max_active_sets,
            'daily_xp_set_cap': config.daily_xp_set_cap,
        }
