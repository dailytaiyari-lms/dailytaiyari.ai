"""Tenant-admin / instructor endpoints (/api/v1/tenant-admin/intelligence/).

Every read here is a thin serialization over the foundation tables — no new
computation pipelines live in the product layer.
"""
from collections import Counter, defaultdict
from datetime import timedelta

from django.db.models import Avg, Count, F, Max, Min, Q
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import IsTenantAdmin
from exams.models import Course

from . import visibility_config as VC
from .access import (
    assessment_course_ids, assessment_in_scope, can_manage_course, can_view_student,
    diagnosis_scope_q, teachable_course_ids,
)
from .models import (
    Concept, CoursePracticeConfig, GeneratedItem, ItemStats, LearnerConceptState,
    PracticeGenerationJob, PracticeSet, ResponseDiagnosis,
)
from .recommendation import practice_config_for
from .serializers import MasteryRowSerializer, PracticeSetSerializer
from .services import visibility


class IsTenantAdminOrInstructor(permissions.BasePermission):
    """Teacher-visible surfaces: tenant admins and faculty both see them."""

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user and user.is_authenticated
            and getattr(user, 'role', '') in ('admin', 'instructor')
        )


class TeacherDiagnosisPermission(permissions.BasePermission):
    """The tenant must have the diagnosis teacher view on (which needs
    Answer Diagnosis; ``get_features`` folds that in)."""

    message = 'The diagnosis teacher view is not enabled for this academy.'

    def has_permission(self, request, view):
        tenant = getattr(request, 'tenant', None)
        return bool(tenant and tenant.get_features().get('diagnosis_teacher_view'))


TEACHER_DIAGNOSIS = [
    permissions.IsAuthenticated, IsTenantAdminOrInstructor, TeacherDiagnosisPermission,
]
LABEL_DISPLAY = dict(ResponseDiagnosis.LABEL_CHOICES)


def _load_assessment(request, kind, assessment_id):
    from quiz.models import MockTest, Quiz

    model = {'quiz': Quiz, 'mock': MockTest}.get(kind)
    if model is None:
        return None
    return model.objects.filter(id=assessment_id, tenant=request.tenant).first()


def _finished_attempt_ids(kind, assessment, limit):
    """Ids of the newest ``limit`` finished attempts on an assessment."""
    from quiz.models import MockTestAttempt, QuizAttempt

    if kind == 'quiz':
        attempts = QuizAttempt.objects.filter(quiz=assessment)
    else:
        attempts = MockTestAttempt.objects.filter(mock_test=assessment)
    # nulls_last: on Postgres a plain '-completed_at' puts abandoned attempts
    # with no completed_at first and can crowd real ones out of the cap.
    return list(
        attempts.exclude(status='in_progress')
        .order_by(F('completed_at').desc(nulls_last=True))
        .values_list('id', flat=True)[:limit]
    )


def _assessment_items(kind, assessment):
    """[(item_key, question_text)] in paper order: bank questions, then a
    mock's inline items."""
    from quiz.models import MockTestItem, MockTestQuestion

    # QuizQuestion / MockTestQuestion declare their own Meta and so have no
    # default ordering: order explicitly, or Postgres returns any order.
    if kind == 'quiz':
        rows = [(f'bank:{qq.question_id}', qq.question.question_text)
                for qq in assessment.quizquestion_set.select_related('question')
                .order_by('order', 'created_at')]
    else:
        rows = [(f'bank:{mtq.question_id}', mtq.question.question_text)
                for mtq in MockTestQuestion.objects.filter(mock_test=assessment)
                .select_related('question').order_by('section', 'order', 'created_at')]
        rows += [(f'item:{item.id}', item.question_text)
                 for item in MockTestItem.objects.filter(mock_test=assessment)]
    return [(key, (text or '')[:200]) for key, text in rows]


def _item_key(question_id, mock_item_id):
    return f'bank:{question_id}' if question_id else f'item:{mock_item_id}'


def _course_or_404(request, course_id):
    return Course.objects.filter(id=course_id, tenant=request.tenant).first()


def _forbidden():
    return Response({'error': 'Not in your courses.'}, status=status.HTTP_403_FORBIDDEN)


class TaggingRunView(APIView):
    """On-demand tagging pass for this tenant (queued on the AI worker)."""

    permission_classes = [permissions.IsAuthenticated, IsTenantAdminOrInstructor]

    def post(self, request):
        from .api import intelligence_enabled
        from .tasks import tag_items_for_tenant

        tenant = getattr(request, 'tenant', None)
        if tenant is None:
            return Response({'error': 'Tenant required.'}, status=status.HTTP_400_BAD_REQUEST)
        if not intelligence_enabled(tenant):
            # The task would be a no-op anyway; say so instead of "queued".
            return Response({'queued': False, 'reason': 'learning_layer_disabled'})
        tag_items_for_tenant.delay(str(tenant.id))
        return Response({'queued': True})


class OverviewView(APIView):
    """InsightsHome tiles for one course."""

    permission_classes = [permissions.IsAuthenticated, IsTenantAdminOrInstructor]

    def get(self, request):
        course = _course_or_404(request, request.query_params.get('course'))
        if course is None:
            return Response({'error': 'Course not found.'}, status=status.HTTP_404_NOT_FOUND)
        if not can_manage_course(request.user, course):
            return _forbidden()

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
        if not assessment_in_scope(request.user, kind, assessment):
            return _forbidden()

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
        return list(Course.objects.filter(id__in=assessment_course_ids(kind, assessment)))


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
        if not can_view_student(request.user, student):
            return _forbidden()

        states = (
            LearnerConceptState.objects.filter(student=student)
            .select_related('concept__subject')
            .order_by('mastery')
        )
        course_id = request.query_params.get('course')
        if course_id:
            if (request.user.role != 'admin'
                    and not any(str(c) == course_id for c in teachable_course_ids(request.user))):
                return _forbidden()
            states = states.filter(concept__subject__course_id=course_id)
        elif request.user.role != 'admin':
            states = states.filter(
                concept__subject__course_id__in=teachable_course_ids(request.user))

        sets = PracticeSet.objects.filter(student=student)
        if request.user.role != 'admin':
            sets = sets.filter(course_id__in=teachable_course_ids(request.user))
        sets = (
            sets.select_related('course').prefetch_related('target_concepts', 'items')
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


class AssessmentBehaviourView(APIView):
    """Per-question answer behaviour for one quiz or mock (spec 2B §4.1.1)."""

    permission_classes = TEACHER_DIAGNOSIS

    def get(self, request, kind, assessment_id):
        assessment = _load_assessment(request, kind, assessment_id)
        if assessment is None:
            return Response({'error': 'Assessment not found.'}, status=status.HTTP_404_NOT_FOUND)
        if not assessment_in_scope(request.user, kind, assessment):
            return _forbidden()

        attempt_ids = _finished_attempt_ids(kind, assessment, VC.BEHAVIOUR_MAX_ATTEMPTS)
        grouped = defaultdict(list)
        for question_id, mock_item_id, label, metrics, report in (
            ResponseDiagnosis.objects.filter(attempt_kind=kind, attempt_id__in=attempt_ids)
            .values_list('question_id', 'mock_item_id', 'final_label', 'metrics', 'self_report')
            .iterator()
        ):
            grouped[_item_key(question_id, mock_item_id)].append((label, metrics or {}, report))

        items = []
        for key, text in _assessment_items(kind, assessment):
            rows = grouped.get(key, [])
            distribution = visibility.label_distribution([label for label, _m, _r in rows])
            items.append({
                'item_key': key,
                'question_text': text,
                'distribution': distribution,
                'median_active_s': visibility.median([m.get('active_s') for _l, m, _r in rows]),
                'usual_s': visibility.median([m.get('usual_s') for _l, m, _r in rows]),
                'self_reports': sum(1 for _l, _m, report in rows if report),
                'flags': visibility.question_flags(distribution),
            })
        return Response({
            'assessment': {'id': str(assessment.id), 'title': assessment.title, 'kind': kind},
            'labels': list(visibility.LABELS),
            'answers': sum(item['distribution']['total'] for item in items),
            'flagged': sum(1 for item in items if item['flags']),
            'items': items,
        })


def _attempt_titles(pairs):
    """{(kind, attempt_id): (title, completed_at)} for quiz/mock/practice attempts."""
    from quiz.models import MockTestAttempt, QuizAttempt

    ids = defaultdict(list)
    for kind, attempt_id in pairs:
        ids[kind].append(attempt_id)
    titles = {}
    for attempt in QuizAttempt.objects.filter(id__in=ids['quiz']).select_related('quiz'):
        titles[('quiz', attempt.id)] = (attempt.quiz.title, attempt.completed_at)
    for attempt in MockTestAttempt.objects.filter(id__in=ids['mock']).select_related('mock_test'):
        titles[('mock', attempt.id)] = (attempt.mock_test.title, attempt.completed_at)
    for practice_set in PracticeSet.objects.filter(id__in=ids['practice']):
        titles[('practice', practice_set.id)] = ('Practice set', practice_set.completed_at)
    return titles


def _answer_rows(student, pairs):
    """Diagnosis rows of the given attempts, as dicts, grouped per attempt."""
    if not pairs:
        return {}
    match = Q()
    for kind, attempt_id in pairs:
        match |= Q(attempt_kind=kind, attempt_id=attempt_id)
    grouped = defaultdict(list)
    rows = (
        ResponseDiagnosis.objects.filter(student=student).filter(match)
        .select_related('question__topic', 'mock_item__topic')
        .order_by('created_at', 'id')
    )
    for row in rows:
        item = row.question or row.mock_item
        topic = getattr(item, 'topic', None) if item else None
        grouped[(row.attempt_kind, row.attempt_id)].append({
            'id': str(row.id),
            'item_key': _item_key(row.question_id, row.mock_item_id),
            'question_text': ((item.question_text if item else '') or '')[:200],
            'topic': topic.name if topic else None,
            'label': row.final_label,
            'label_display': LABEL_DISPLAY.get(row.final_label, row.final_label),
            'confidence': row.confidence,
            'is_correct': row.is_correct,
            'answered': row.answered,
            'active_s': (row.metrics or {}).get('active_s'),
            'metrics': row.metrics or {},
            'evidence': visibility.describe_evidence(row.evidence, row.metrics),
            'self_report': row.self_report,
        })
    return grouped


class StudentAnswersView(APIView):
    """One student's diagnosed answers, newest attempt first, with patterns
    over the newest attempts (spec 2B §4.1.2)."""

    permission_classes = TEACHER_DIAGNOSIS

    def get(self, request, student_id):
        from users.models import StudentProfile

        student = StudentProfile.objects.filter(
            id=student_id, user__tenant=request.tenant,
        ).select_related('user').first()
        if student is None:
            return Response({'error': 'Student not found.'}, status=status.HTTP_404_NOT_FOUND)
        if not can_view_student(request.user, student):
            return _forbidden()

        try:
            page = max(1, int(request.query_params.get('page', 1)))
        except (TypeError, ValueError):
            page = 1
        attempts = (
            ResponseDiagnosis.objects.filter(student=student)
            .filter(diagnosis_scope_q(request.user, student))
            .values('attempt_kind', 'attempt_id')
            .annotate(first_seen=Min('created_at'), last_computed=Max('computed_at'))
            # Rows written in one burst can share a created_at, and the
            # database clock can be coarse, so break ties on when the
            # diagnosis was computed (later = newer), then on the id.
            .order_by('-first_seen', F('last_computed').desc(nulls_last=True), 'attempt_id')
        )
        total = attempts.count()
        size = VC.ANSWERS_PAGE_SIZE
        pages = max(1, -(-total // size))
        page = min(page, pages)
        page_pairs = [(a['attempt_kind'], a['attempt_id'])
                      for a in attempts[(page - 1) * size:page * size]]
        rows = _answer_rows(student, page_pairs)
        titles = _attempt_titles(page_pairs)

        patterns = []
        if page == 1:
            window = page_pairs[:VC.PATTERN_ATTEMPTS]
            patterns = visibility.detect_patterns(
                [{'answers': rows.get(pair, [])} for pair in window])

        payload = []
        for pair in page_pairs:
            title, completed_at = titles.get(pair, ('Deleted attempt', None))
            payload.append({
                'attempt_kind': pair[0],
                'attempt_id': str(pair[1]),
                'title': title,
                'completed_at': completed_at.isoformat() if completed_at else None,
                'answers': [
                    {key: value for key, value in answer.items() if key != 'metrics'}
                    for answer in rows.get(pair, [])
                ],
            })
        return Response({
            'student': {
                'id': str(student.id),
                'name': getattr(student.user, 'full_name', '') or student.user.email,
            },
            'page': page,
            'pages': pages,
            'total_attempts': total,
            'patterns': patterns,
            'attempts': payload,
        })


class CourseBehaviourView(APIView):
    """Answer-behaviour tile for one course (spec 2B §4.1.3): guess, slip and
    time-pressure rates over the last 28 days, a weekly trend, and the
    students most worth checking."""

    permission_classes = TEACHER_DIAGNOSIS

    def get(self, request, course_id):
        from quiz.models import MockTestAttempt, QuizAttempt
        from users.models import StudentProfile

        course = _course_or_404(request, course_id)
        if course is None:
            return Response({'error': 'Course not found.'}, status=status.HTTP_404_NOT_FOUND)
        if not can_manage_course(request.user, course):
            return _forbidden()

        now = timezone.now()
        since = now - timedelta(days=VC.COURSE_TILE_DAYS)
        completed = {}     # (kind, attempt_id) → completed_at
        assessments = {}   # (kind, assessment_id) → (title, latest completed_at)

        def collect(kind, rows):
            for attempt_id, done, assessment_id, title in rows:
                completed[(kind, attempt_id)] = done
                if assessment_id is None:
                    continue
                key = (kind, assessment_id)
                if key not in assessments or assessments[key][1] < done:
                    assessments[key] = (title, done)

        collect('quiz', QuizAttempt.objects.filter(
            quiz__course=course, completed_at__gte=since,
        ).values_list('id', 'completed_at', 'quiz_id', 'quiz__title'))
        collect('mock', MockTestAttempt.objects.filter(
            Q(mock_test__course=course) | Q(mock_test__courses=course),
            completed_at__gte=since,
        ).distinct().values_list('id', 'completed_at', 'mock_test_id', 'mock_test__title'))
        collect('practice', [
            (row_id, done, None, '')
            for row_id, done in PracticeSet.objects.filter(
                course=course, completed_at__gte=since,
            ).values_list('id', 'completed_at')
        ])

        ids_by_kind = defaultdict(list)
        for kind, attempt_id in completed:
            ids_by_kind[kind].append(attempt_id)
        match = Q(pk__in=[])
        for kind, ids in ids_by_kind.items():
            match |= Q(attempt_kind=kind, attempt_id__in=ids)
        rows = list(
            ResponseDiagnosis.objects.filter(tenant=request.tenant).filter(match)
            .values_list('attempt_kind', 'attempt_id', 'student_id', 'final_label')
        )

        weeks = [[] for _ in range(VC.COURSE_TILE_WEEKS)]
        per_student = defaultdict(list)
        for kind, attempt_id, student_id, label in rows:
            per_student[student_id].append(label)
            age_days = (now - completed[(kind, attempt_id)]).days
            index = VC.COURSE_TILE_WEEKS - 1 - min(age_days // 7, VC.COURSE_TILE_WEEKS - 1)
            weeks[index].append(label)

        trend = []
        for index, labels in enumerate(weeks):
            start = now - timedelta(days=7 * (VC.COURSE_TILE_WEEKS - index))
            trend.append({'week_start': start.date().isoformat(),
                          **visibility.behaviour_rates(labels)})

        check = visibility.students_to_check(per_student)
        names = {
            profile.id: (getattr(profile.user, 'full_name', '') or profile.user.email)
            for profile in StudentProfile.objects.filter(
                id__in=[row['student_id'] for row in check]).select_related('user')
        }
        recent = sorted(assessments.items(), key=lambda pair: pair[1][1], reverse=True)
        return Response({
            'course': {'id': str(course.id), 'name': course.name},
            'days': VC.COURSE_TILE_DAYS,
            'rates': visibility.behaviour_rates([row[3] for row in rows]),
            'trend': trend,
            'students_to_check': [
                {**row, 'student_id': str(row['student_id']), 'name': names.get(row['student_id'], '')}
                for row in check
            ],
            'recent_assessments': [
                {'kind': kind, 'id': str(assessment_id), 'title': title,
                 'completed_at': done.isoformat()}
                for (kind, assessment_id), (title, done) in recent[:VC.RECENT_ASSESSMENTS]
            ],
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
        if request.user.role != 'admin':
            rows = rows.filter(question__courses__id__in=teachable_course_ids(request.user)).distinct()
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
        if request.user.role != 'admin' and not row.question.courses.filter(
                id__in=teachable_course_ids(request.user)).exists():
            return _forbidden()
        row.retired_at = timezone.now()
        row.save(update_fields=['retired_at', 'updated_at'])
        row.question.status = 'archived'
        row.question.save(update_fields=['status', 'updated_at'])
        return Response({'retired': True})


class GenerationJobsView(APIView):
    """Observability for practice-generation jobs."""

    permission_classes = [permissions.IsAuthenticated, IsTenantAdminOrInstructor]

    def get(self, request):
        jobs = PracticeGenerationJob.objects.filter(tenant=request.tenant)
        if request.user.role != 'admin':
            jobs = jobs.filter(course_id__in=teachable_course_ids(request.user))
        jobs = jobs.select_related('course').order_by('-created_at')[:100]
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
        if not can_manage_course(request.user, course):
            return _forbidden()
        config = practice_config_for(course)
        return Response(self._payload(config))

    def patch(self, request, course_id):
        course = _course_or_404(request, course_id)
        if course is None:
            return Response({'error': 'Course not found.'}, status=status.HTTP_404_NOT_FOUND)
        if not can_manage_course(request.user, course):
            return _forbidden()
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


class DiagnosisCalibrationView(APIView):
    """How well response-diagnosis labels match what students say happened.

    Label distribution, classifier-label × self-report confusion, per-label
    agreement, and how much of the data had a timeline / trusted usual time.
    Admin only. Also reports the thresholds and classifier version in use.
    """

    permission_classes = [permissions.IsAuthenticated, IsTenantAdmin]

    def get(self, request):
        from .diagnosis_config import SELF_REPORT_LABEL, THRESHOLDS
        from .versions import CLASSIFIER_VERSION

        try:
            days = max(1, min(365, int(request.query_params.get('days', 30))))
        except ValueError:
            days = 30
        since = timezone.now() - timedelta(days=days)
        rows = ResponseDiagnosis.objects.filter(
            tenant=request.tenant, computed_at__gte=since,
        ).values_list('label', 'self_report', 'has_timeline', 'metrics')

        labels = Counter()
        confusion = defaultdict(Counter)
        total = with_timeline = stats_usual = 0
        for label, report, has_timeline, metrics in rows.iterator():
            total += 1
            labels[label] += 1
            with_timeline += 1 if has_timeline else 0
            stats_usual += 1 if (metrics or {}).get('usual_source') == 'stats' else 0
            if report:
                confusion[label][report] += 1

        agreement = {
            label: round(
                sum(n for rep, n in reports.items() if SELF_REPORT_LABEL.get(rep) == label)
                / sum(reports.values()), 3)
            for label, reports in confusion.items()
        }
        return Response({
            'days': days, 'total': total, 'with_timeline': with_timeline,
            'stats_usual': stats_usual, 'labels': dict(labels),
            'confusion': {label: dict(reports) for label, reports in confusion.items()},
            'agreement': agreement,
            'thresholds': THRESHOLDS,
            'classifier_version': CLASSIFIER_VERSION,
        })
