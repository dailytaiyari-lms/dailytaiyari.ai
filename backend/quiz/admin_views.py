"""
Admin CRUD views for the Quiz Builder.

Tenant-scoped, tenant-admin only. Quizzes scope via ``course__tenant`` and
Questions via ``subject__course__tenant`` (legacy rows may have a null tenant).
"""
from django.db.models import Case, When

from exams.admin_views import TenantAdminModelViewSet

from .models import Quiz, Question, QuizQuestion
from .admin_serializers import AdminQuizSerializer, AdminQuestionSerializer


class AdminQuizViewSet(TenantAdminModelViewSet):
    queryset = Quiz.objects.select_related('course', 'subject', 'topic').all()
    serializer_class = AdminQuizSerializer
    search_fields = ['title']
    ordering_fields = ['created_at', 'title']
    ordering = ['-created_at']
    filterset_fields = ['course', 'subject', 'topic', 'quiz_type', 'status']
    tenant_lookup = 'course__tenant'
    course_lookup = 'course'


class AdminQuestionViewSet(TenantAdminModelViewSet):
    queryset = Question.objects.select_related('topic', 'subject').prefetch_related('options').all()
    serializer_class = AdminQuestionSerializer
    search_fields = ['question_text']
    ordering_fields = ['created_at']
    ordering = ['created_at']
    filterset_fields = ['topic', 'subject', 'difficulty', 'status', 'question_type']
    tenant_lookup = 'subject__course__tenant'
    course_lookup = 'subject__course'

    def get_queryset(self):
        qs = super().get_queryset()
        quiz_id = self.request.query_params.get('quiz')
        if quiz_id:
            ordered_ids = list(
                QuizQuestion.objects.filter(quiz_id=quiz_id)
                .order_by('order')
                .values_list('question_id', flat=True)
            )
            if not ordered_ids:
                return qs.none()
            # Preserve the quiz's question order (IN does not guarantee order),
            # and stop the OrderingFilter default from re-sorting by created_at.
            self.ordering = None
            preserved = Case(*[When(id=pk, then=pos) for pos, pk in enumerate(ordered_ids)])
            qs = qs.filter(id__in=ordered_ids).order_by(preserved)
        return qs

    def perform_destroy(self, instance):
        QuizQuestion.objects.filter(question=instance).delete()
        instance.delete()


# ---------------------------------------------------------------------------
# Rich Mock Test builder (Phase 2)
# ---------------------------------------------------------------------------
from decimal import Decimal

from django.utils import timezone

from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError, NotFound
from django_filters.rest_framework import DjangoFilterBackend

from core.permissions import IsTenantAdmin
from exams.admin_views import BuilderPagination
from .models import MockTest, MockTestItem, MockTestQuestion, Question, MockTestAttempt, MockTestAnswer
from .admin_serializers import (
    AdminMockTestSerializer, AdminMockTestItemSerializer,
    AdminMockTestQuestionSerializer,
)


def recompute_mock_total(mock_test):
    """Recompute and persist ``total_marks`` = inline items + linked bank questions."""
    items_total = sum((i.marks for i in mock_test.items.all()), Decimal('0'))
    bank_total = sum(
        (mtq.effective_marks for mtq in
         MockTestQuestion.objects.filter(mock_test=mock_test).select_related('question')),
        Decimal('0'),
    )
    mock_test.total_marks = items_total + bank_total
    mock_test.save(update_fields=['total_marks', 'updated_at'])
    return mock_test.total_marks


class AdminMockTestViewSet(viewsets.ModelViewSet):
    """Admin-only CRUD for rich mock tests (tenant-scoped)."""
    permission_classes = [IsTenantAdmin]
    serializer_class = AdminMockTestSerializer
    pagination_class = BuilderPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['title', 'description']
    ordering_fields = ['created_at', 'title', 'status']
    ordering = ['-created_at']
    filterset_fields = ['status', 'is_pyp', 'is_free', 'result_visibility']
    queryset = MockTest.objects.all().prefetch_related('items', 'courses')

    def _tenant(self):
        return getattr(self.request, 'tenant', None)

    def get_queryset(self):
        tenant = self._tenant()
        if not tenant:
            return MockTest.objects.none()
        return super().get_queryset().filter(tenant=tenant)

    def perform_create(self, serializer):
        extra = {'tenant': self._tenant()}
        if serializer.validated_data.get('total_marks') is None:
            extra['total_marks'] = Decimal('0')
        serializer.save(**extra)

    # --- bank-question linking -------------------------------------------

    @action(detail=True, methods=['get'])
    def bank_questions(self, request, pk=None):
        mock_test = self.get_object()
        mtqs = (MockTestQuestion.objects.filter(mock_test=mock_test)
                .select_related('question').order_by('section', 'order'))
        return Response(AdminMockTestQuestionSerializer(mtqs, many=True).data)

    @action(detail=True, methods=['post'])
    def add_bank_questions(self, request, pk=None):
        mock_test = self.get_object()
        tenant = self._tenant()
        ids = request.data.get('question_ids', [])
        if not isinstance(ids, list) or not ids:
            raise ValidationError({'question_ids': 'Provide a non-empty list of question ids.'})
        section = request.data.get('section', 0)
        marks_override = request.data.get('marks_override')
        neg_override = request.data.get('negative_marks_override')
        # Only questions in this tenant (via subject->course) or already tenant-linked.
        valid = Question.objects.filter(id__in=ids).filter(
            subject__course__tenant=tenant
        )
        valid_ids = {str(q.id) for q in valid}
        base_order = MockTestQuestion.objects.filter(mock_test=mock_test).count()
        created = 0
        for qid in ids:
            if str(qid) not in valid_ids:
                continue
            if MockTestQuestion.objects.filter(mock_test=mock_test, question_id=qid).exists():
                continue
            MockTestQuestion.objects.create(
                mock_test=mock_test, question_id=qid, section=section,
                order=base_order + created,
                marks_override=marks_override, negative_marks_override=neg_override,
                tenant=tenant,
            )
            created += 1
        recompute_mock_total(mock_test)
        return Response({'added': created}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def remove_bank_question(self, request, pk=None):
        mock_test = self.get_object()
        qid = request.data.get('question_id')
        if not qid:
            raise ValidationError({'question_id': 'Required.'})
        deleted, _ = MockTestQuestion.objects.filter(
            mock_test=mock_test, question_id=qid).delete()
        recompute_mock_total(mock_test)
        return Response({'removed': deleted})

    @action(detail=True, methods=['post'])
    def recompute_marks(self, request, pk=None):
        mock_test = self.get_object()
        total = recompute_mock_total(mock_test)
        return Response({'total_marks': float(total)})

    # --- manual grading (Phase 5) ----------------------------------------

    def _attempt_grading_payload(self, attempt):
        """Serialize an attempt with its inline answers for the grading UI."""
        u = getattr(attempt.student, 'user', None)
        answers = []
        for ans in (attempt.item_answers.select_related('item')
                    .order_by('item__section', 'item__order')):
            item = ans.item
            answers.append({
                'answer_id': str(ans.id),
                'item_id': str(item.id),
                'item_type': item.item_type,
                'section': item.section,
                'order': item.order,
                'question_text': item.question_text,
                'question_html': item.question_html or '',
                'explanation': item.explanation or '',
                'max_marks': float(ans.max_marks or item.marks),
                'max_words': item.max_words,
                # Student response (only the field relevant to item_type is used).
                'selected_options': ans.selected_options or [],
                'numerical_answer': float(ans.numerical_answer) if ans.numerical_answer is not None else None,
                'answer_text': ans.answer_text,
                'code': ans.code,
                'language': ans.language,
                'coding_results': ans.coding_results,
                'passed_count': ans.passed_count,
                'total_count': ans.total_count,
                # Correct-answer reference (admin-only) for review display.
                'options': item.options or [],
                'correct_option_indices': list(item.correct_option_indices or []),
                'numerical_correct': float(item.numerical_answer) if item.numerical_answer is not None else None,
                'numerical_tolerance': float(item.numerical_tolerance) if item.numerical_tolerance is not None else None,
                'model_answer': item.model_answer or '',
                'rubric': item.rubric or '',
                'marks_obtained': float(ans.marks_obtained),
                'is_correct': ans.is_correct,
                'feedback': ans.feedback,
                'needs_manual_grading': ans.needs_manual_grading,
                'is_auto_graded': ans.is_auto_graded,
                'graded_at': ans.graded_at.isoformat() if ans.graded_at else None,
            })
        return {
            'attempt_id': str(attempt.id),
            'student_name': (getattr(u, 'full_name', '') or (u.email if u else '')).strip() if u else '',
            'student_email': u.email if u else '',
            'mock_test_id': str(attempt.mock_test_id),
            'mock_test_title': attempt.mock_test.title,
            'total_marks': float(attempt.mock_test.total_marks),
            'marks_obtained': float(attempt.marks_obtained),
            'percentage': float(attempt.percentage),
            'grading_status': attempt.grading_status,
            'completed_at': attempt.completed_at.isoformat() if attempt.completed_at else None,
            'pending_count': attempt.item_answers.filter(needs_manual_grading=True).count(),
            'answers': answers,
        }

    @action(detail=False, methods=['get'], url_path='pending-grading')
    def pending_grading(self, request):
        """List completed attempts (this tenant) awaiting manual grading."""
        tenant = self._tenant()
        qs = (MockTestAttempt.objects.filter(
                mock_test__tenant=tenant, status='completed',
                grading_status='pending_manual')
              .select_related('student__user', 'mock_test')
              .order_by('completed_at'))
        mock_id = request.query_params.get('mock_test')
        if mock_id:
            qs = qs.filter(mock_test_id=mock_id)
        out = []
        for a in qs:
            u = getattr(a.student, 'user', None)
            out.append({
                'attempt_id': str(a.id),
                'student_name': (getattr(u, 'full_name', '') or (u.email if u else '')).strip() if u else '',
                'student_email': u.email if u else '',
                'mock_test_id': str(a.mock_test_id),
                'mock_test_title': a.mock_test.title,
                'completed_at': a.completed_at.isoformat() if a.completed_at else None,
                'pending_count': a.item_answers.filter(needs_manual_grading=True).count(),
            })
        return Response(out)

    @action(detail=True, methods=['get'], url_path='submissions')
    def submissions(self, request, pk=None):
        """All completed attempts for one mock test, plus summary counts.

        Mirrors the assignment/coding submissions views: eligible-student count,
        submitted/graded/pending breakdown, average score, and a per-attempt
        list the admin can drill into for review + grading.
        """
        mock_test = self.get_object()
        attempts = (MockTestAttempt.objects.filter(
                        mock_test=mock_test, status='completed')
                    .select_related('student__user')
                    .prefetch_related('item_answers')
                    .order_by('-completed_at'))

        rows, graded, pending, score_sum = [], 0, 0, 0.0
        for a in attempts:
            u = getattr(a.student, 'user', None)
            pending_count = a.item_answers.filter(needs_manual_grading=True).count()
            is_graded = a.grading_status == 'graded' or (
                a.grading_status == 'auto_graded' and pending_count == 0)
            if pending_count > 0:
                pending += 1
            else:
                graded += 1
            score_sum += float(a.percentage)
            rows.append({
                'attempt_id': str(a.id),
                'student_name': (getattr(u, 'full_name', '') or (u.email if u else '')).strip() if u else '',
                'student_email': u.email if u else '',
                'marks_obtained': float(a.marks_obtained),
                'total_marks': float(mock_test.total_marks),
                'percentage': float(a.percentage),
                'grading_status': a.grading_status,
                'pending_count': pending_count,
                'is_fully_graded': pending_count == 0,
                'completed_at': a.completed_at.isoformat() if a.completed_at else None,
                'time_taken_seconds': a.time_taken_seconds,
            })

        # Eligible students: enrolled (approved+active) in any linked/legacy
        # course, or every student in the tenant when the test is open to all.
        from users.models import StudentProfile, CourseEnrollment
        course_ids = list(mock_test.courses.values_list('id', flat=True))
        if mock_test.course_id:
            course_ids.append(mock_test.course_id)
        if course_ids:
            eligible = (CourseEnrollment.objects.filter(
                            course_id__in=course_ids, status='approved', is_active=True)
                        .values('student_id').distinct().count())
        else:
            eligible = StudentProfile.objects.filter(
                user__tenant=mock_test.tenant_id, user__role='student').count()

        submitted = len(rows)
        avg_score = round(score_sum / submitted, 2) if submitted else 0.0
        return Response({
            'mock_test': {
                'id': str(mock_test.id),
                'title': mock_test.title,
                'status': mock_test.status,
                'total_marks': float(mock_test.total_marks),
                'duration_minutes': mock_test.duration_minutes,
                'result_visibility': mock_test.result_visibility,
                'results_released': mock_test.results_released,
            },
            'counts': {
                'eligible': eligible,
                'submitted': submitted,
                'graded': graded,
                'pending': pending,
            },
            'average_score': avg_score,
            'attempts': rows,
        })

    @action(detail=False, methods=['get'], url_path='attempts/(?P<attempt_id>[^/.]+)')
    def attempt_detail(self, request, attempt_id=None):
        """Full grading view for a single attempt."""
        tenant = self._tenant()
        attempt = (MockTestAttempt.objects.filter(id=attempt_id, mock_test__tenant=tenant)
                   .select_related('student__user', 'mock_test').first())
        if not attempt:
            raise NotFound('Attempt not found.')
        return Response(self._attempt_grading_payload(attempt))

    @action(detail=False, methods=['post'], url_path='grade-answer')
    def grade_answer(self, request):
        """Set marks + feedback on one inline answer (marks it manually graded)."""
        tenant = self._tenant()
        answer_id = request.data.get('answer_id')
        ans = (MockTestAnswer.objects.filter(id=answer_id, attempt__mock_test__tenant=tenant)
               .select_related('item', 'attempt__mock_test').first())
        if not ans:
            raise NotFound('Answer not found.')
        try:
            marks = Decimal(str(request.data.get('marks')))
        except (TypeError, ValueError):
            raise ValidationError({'marks': 'A numeric marks value is required.'})
        max_marks = Decimal(str(ans.max_marks or ans.item.marks))
        if marks < 0 or marks > max_marks:
            raise ValidationError({'marks': f'Marks must be between 0 and {max_marks}.'})
        ans.marks_obtained = marks
        ans.feedback = request.data.get('feedback', '') or ''
        ans.is_correct = marks >= max_marks and max_marks > 0
        ans.needs_manual_grading = False
        ans.is_auto_graded = False
        ans.graded_by = request.user
        ans.graded_at = timezone.now()
        ans.save(update_fields=[
            'marks_obtained', 'feedback', 'is_correct', 'needs_manual_grading',
            'is_auto_graded', 'graded_by', 'graded_at', 'updated_at',
        ])
        from .mock_grading import recompute_attempt
        attempt = ans.attempt
        recompute_attempt(attempt)
        attempt.save(update_fields=[
            'marks_obtained', 'attempted_questions', 'correct_answers',
            'wrong_answers', 'percentage', 'updated_at',
        ])

        # Superseding learning event for the intelligence layer (fail-safe)
        from intelligence import api as intelligence_api
        intelligence_api.record_regrade_event(ans)

        return Response({
            'answer_id': str(ans.id),
            'marks_obtained': float(ans.marks_obtained),
            'attempt_marks': float(attempt.marks_obtained),
            'attempt_percentage': float(attempt.percentage),
            'pending_count': attempt.item_answers.filter(needs_manual_grading=True).count(),
        })

    @action(detail=False, methods=['post'], url_path='finalize-attempt')
    def finalize_attempt(self, request):
        """Finalize a fully-graded attempt: mark graded + award deferred XP."""
        tenant = self._tenant()
        attempt = (MockTestAttempt.objects.filter(
                    id=request.data.get('attempt_id'), mock_test__tenant=tenant)
                   .select_related('student__user', 'mock_test').first())
        if not attempt:
            raise NotFound('Attempt not found.')
        remaining = attempt.item_answers.filter(needs_manual_grading=True).count()
        if remaining:
            raise ValidationError(
                {'error': f'{remaining} answer(s) still need grading before finalizing.'})

        from .mock_grading import recompute_attempt
        recompute_attempt(attempt)
        attempt.grading_status = 'graded'
        attempt.save(update_fields=[
            'marks_obtained', 'attempted_questions', 'correct_answers',
            'wrong_answers', 'percentage', 'grading_status', 'updated_at',
        ])

        # Safety-net event emission (idempotent — no-op if submit already
        # recorded these answers and grade_answer recorded the regrades).
        from intelligence import api as intelligence_api
        intelligence_api.record_attempt_events(attempt)

        # Award XP once (deferred from submit for manual-grading attempts).
        awarded = 0
        from gamification.models import XPTransaction
        already = XPTransaction.objects.filter(
            student=attempt.student, transaction_type='mock_complete',
            reference_id=attempt.id,
        ).exists()
        if not already and attempt.xp_earned == 0:
            from gamification.services import GamificationService
            from core.utils import calculate_xp_for_quiz
            awarded = calculate_xp_for_quiz(
                float(attempt.percentage), attempt.total_questions, is_daily_challenge=False
            ) * 2
            attempt.xp_earned = awarded
            attempt.save(update_fields=['xp_earned'])
            GamificationService.award_xp(
                attempt.student, awarded, 'mock_complete',
                f'Completed mock test: {attempt.mock_test.title}', str(attempt.id),
            )
        return Response({
            'attempt_id': str(attempt.id),
            'grading_status': attempt.grading_status,
            'marks_obtained': float(attempt.marks_obtained),
            'percentage': float(attempt.percentage),
            'xp_awarded': awarded,
        })


class AdminMockTestItemViewSet(viewsets.ModelViewSet):
    """Admin-only CRUD for inline mock-test items. Filter by ``?mock_test=<id>``."""
    permission_classes = [IsTenantAdmin]
    serializer_class = AdminMockTestItemSerializer
    pagination_class = BuilderPagination
    queryset = MockTestItem.objects.all()

    def _tenant(self):
        return getattr(self.request, 'tenant', None)

    def get_queryset(self):
        tenant = self._tenant()
        if not tenant:
            return MockTestItem.objects.none()
        qs = MockTestItem.objects.filter(mock_test__tenant=tenant)
        mock_test_id = self.request.query_params.get('mock_test')
        if mock_test_id:
            qs = qs.filter(mock_test_id=mock_test_id)
        return qs.order_by('section', 'order')

    def _resolve_mock_test(self, serializer):
        mock_test = serializer.validated_data.get('mock_test')
        if mock_test is None or mock_test.tenant_id != self._tenant().id:
            raise ValidationError({'mock_test': 'Mock test not found for this tenant.'})
        return mock_test

    def perform_create(self, serializer):
        mock_test = self._resolve_mock_test(serializer)
        if not serializer.validated_data.get('order'):
            serializer.validated_data['order'] = MockTestItem.objects.filter(
                mock_test=mock_test).count()
        item = serializer.save(tenant=self._tenant())
        recompute_mock_total(item.mock_test)

    def perform_update(self, serializer):
        item = serializer.save()
        recompute_mock_total(item.mock_test)

    def perform_destroy(self, instance):
        mock_test = instance.mock_test
        instance.delete()
        recompute_mock_total(mock_test)

    @action(detail=False, methods=['post'])
    def reorder(self, request):
        """Body: {"order": [item_id, ...]}. Reorders items within the tenant."""
        ids = request.data.get('order', [])
        qs = self.get_queryset()
        lookup = {str(obj.id): obj for obj in qs.filter(id__in=ids)}
        updated = []
        for index, obj_id in enumerate(ids):
            obj = lookup.get(str(obj_id))
            if obj is not None:
                obj.order = index
                updated.append(obj)
        if updated:
            MockTestItem.objects.bulk_update(updated, ['order'])
        return Response({'updated': len(updated)})
