"""Tenant-admin endpoints for the AI Mock Test Builder ("Mock Studio").

The contract the whole screen is built on: **generation and writing are two
separate calls.** ``POST /jobs/`` only ever produces a draft paper for review;
``POST /jobs/{id}/apply/`` is the single endpoint that touches the mock-test
tables and it refuses anything that is not an explicitly confirmed,
still-in-preview draft.

Everything is scoped to the tenant resolved by ``TenantMiddleware``.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from chatbot import resolver
from coding.languages import language_choices
from core.permissions import IsTenantAdmin
from exams.models import Course
from quiz.models import MockTest, MockTestItem

from . import generation
from .apply import ApplyError, apply_draft, draft_from_mock_test
from .models import MockTestGenerationJob
from .schema import (
    ITEM_TYPES,
    MAX_ITEMS_PER_REQUEST,
    MAX_ITEMS_PER_TEST,
    MAX_SECTIONS,
)
from .serializers import (
    ApplySerializer,
    DraftUpdateSerializer,
    GenerateSerializer,
    MockJobListSerializer,
    MockJobSerializer,
    RefineSerializer,
)

logger = logging.getLogger(__name__)

# Statuses that still want the admin's attention: queued, being written, or
# waiting to be reviewed. Everything else is done with.
OPEN_STATUSES = (
    MockTestGenerationJob.STATUS_PENDING,
    MockTestGenerationJob.STATUS_GENERATING,
    MockTestGenerationJob.STATUS_PREVIEW,
)

ITEM_TYPE_LABELS = {
    'mcq': 'MCQ (single answer)',
    'mcq_multi': 'MCQ (multiple answers)',
    'numerical': 'Numerical',
    'subjective': 'Subjective (written)',
    'coding': 'Coding',
}


def _async_enabled():
    return bool(getattr(settings, 'MOCKGEN_ASYNC', getattr(settings, 'COURSEGEN_ASYNC', True)))


def _enqueue(job, *, mode='generate', instruction=''):
    """Run a generation in the background, falling back to inline if Celery is down.

    Returns True when the work was queued (the client should poll the job),
    False when it had to run inline (the job is already terminal).
    """
    if _async_enabled():
        # Flip to "queued" *before* handing the job over, otherwise a refine
        # would answer while the job still reads ``preview`` and the studio,
        # seeing a settled job, would stop polling and show the stale draft.
        job.status = MockTestGenerationJob.STATUS_PENDING
        job.error = ''
        job.save(update_fields=['status', 'error', 'updated_at'])
        try:
            from .tasks import run_generation_job
            run_generation_job.delay(str(job.id), mode, instruction)
            return True
        except Exception as exc:  # broker down -> never block the admin
            logger.warning('mockgen: async enqueue failed (%s); running inline.', exc)

    if mode == 'refine':
        try:
            generation.apply_refinement(job, instruction)
        except generation.GenerationError:
            pass  # the job is back in preview with a user-facing error
    else:
        generation.run_job(job)
    return False


class _StudioView(APIView):
    """Shared tenant scoping for every mock-studio endpoint."""

    permission_classes = [IsAuthenticated, IsTenantAdmin]

    @property
    def tenant(self):
        return getattr(self.request, 'tenant', None)

    def mock_tests(self):
        return MockTest.objects.filter(tenant=self.tenant)

    def get_mock_test(self, mock_test_id):
        if not mock_test_id:
            return None
        return get_object_or_404(self.mock_tests(), id=mock_test_id)

    def get_course(self, course_id):
        if not course_id:
            return None
        return get_object_or_404(Course.objects.filter(tenant=self.tenant), id=course_id)

    def jobs(self):
        return (
            MockTestGenerationJob.objects
            .filter(tenant=self.tenant)
            .select_related('mock_test', 'course', 'created_by')
        )


class StudioOptionsView(_StudioView):
    """Everything the studio needs to render its composer in one call."""

    def get(self, request):
        tenant = self.tenant
        models = generation.available_models(tenant)
        settings_obj = resolver.get_ai_settings(tenant)

        courses = [
            {'id': str(course.id), 'name': course.name, 'code': course.code}
            for course in Course.objects.filter(tenant=tenant).order_by('name')
        ]

        return Response({
            'is_ready': bool(models) and settings_obj.is_enabled,
            'ai_enabled': settings_obj.is_enabled,
            'async_generation': _async_enabled(),
            'providers': models,
            'courses': courses,
            'item_types': [
                {'id': key, 'label': ITEM_TYPE_LABELS.get(key, key)} for key in ITEM_TYPES
            ],
            'coding_languages': [
                {'id': key, 'label': label} for key, label in language_choices()
            ],
            'limits': {
                'max_items_per_request': MAX_ITEMS_PER_REQUEST,
                'max_items_per_test': MAX_ITEMS_PER_TEST,
                'max_sections': MAX_SECTIONS,
            },
            'defaults': {
                'duration_minutes': 60,
                'difficulty': 'mixed',
                'language': 'English',
                'negative_marking': True,
                'publish_immediately': False,
                'apply_mode': 'replace',
                'blueprint': [
                    {'item_type': 'mcq', 'count': 10, 'marks': 4, 'negative_marks': 1,
                     'difficulty': 'mixed', 'section': 0},
                ],
                'sections': [{'name': 'Section 1', 'description': ''}],
                'coding_languages': ['python'],
            },
            'kinds': [
                {'id': key, 'label': label}
                for key, label in MockTestGenerationJob.KIND_CHOICES
            ],
            'not_ready_reason': (
                '' if models else
                'Connect an AI provider under Admin → AI Features to use the mock studio.'
            ),
        })


class CourseSyllabusView(_StudioView):
    """A course's subject → chapter → topic tree, for grounding a paper."""

    def get(self, request, course_id):
        course = self.get_course(course_id)
        subjects = []
        for subject in course.subjects.all().order_by('order', 'name'):
            chapters = []
            for chapter in subject.chapters.all().order_by('order', 'name'):
                links = chapter.chapter_topics.select_related('topic').order_by('order')
                chapters.append({
                    'id': str(chapter.id),
                    'name': chapter.name,
                    'topics': [
                        {
                            'id': str(link.topic.id),
                            'name': link.topic.name,
                            'difficulty': link.topic.difficulty,
                        }
                        for link in links
                    ],
                })
            subjects.append({
                'id': str(subject.id),
                'name': subject.name,
                'chapters': chapters,
            })
        return Response({
            'course': {'id': str(course.id), 'name': course.name},
            'subjects': subjects,
        })


class MockTestSnapshotView(_StudioView):
    """A saved paper rendered as a draft — what "Modify with AI" starts from.

    Deliberately available for *every* mock test, not only generated ones: a
    hand-typed paper produces exactly the same JSON, which is what lets the AI
    edit it.
    """

    def get(self, request, mock_test_id):
        mock_test = self.get_mock_test(mock_test_id)
        draft = draft_from_mock_test(mock_test)
        return Response({
            'mock_test': {
                'id': str(mock_test.id),
                'title': mock_test.title,
                'status': mock_test.status,
                'total_attempts': mock_test.total_attempts,
                'items_count': MockTestItem.objects.filter(mock_test=mock_test).count(),
            },
            'draft': draft,
        })


class JobPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class JobListCreateView(_StudioView):
    """``GET`` recent jobs; ``POST`` starts a generation and returns the job."""

    def get(self, request):
        queryset = self.jobs()

        mock_test_id = request.query_params.get('mock_test')
        if mock_test_id:
            queryset = queryset.filter(mock_test_id=mock_test_id)
        kind = request.query_params.get('kind')
        if kind:
            queryset = queryset.filter(kind=kind)

        raw_status = request.query_params.get('status')
        if raw_status == 'open':
            queryset = queryset.filter(status__in=OPEN_STATUSES)
        elif raw_status == 'running':
            queryset = queryset.filter(status__in=MockTestGenerationJob.RUNNING_STATUSES)
        elif raw_status:
            wanted = [value.strip() for value in raw_status.split(',') if value.strip()]
            if wanted:
                queryset = queryset.filter(status__in=wanted)

        paginator = JobPagination()
        page = paginator.paginate_queryset(queryset.order_by('-created_at'), request, view=self)
        return paginator.get_paginated_response(MockJobListSerializer(page, many=True).data)

    def post(self, request):
        serializer = GenerateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        mock_test = self.get_mock_test(data.get('mock_test'))
        course = self.get_course(data.get('course'))
        kind = data.get('kind') or MockTestGenerationJob.KIND_CREATE

        options = dict(data.get('options') or {})
        # Course links are the admin's choice, but they are written by the apply
        # step — so keep only ids that really belong to this tenant.
        course_ids = [str(value) for value in options.get('course_ids') or []]
        if course_ids:
            options['course_ids'] = [
                str(value) for value in Course.objects
                .filter(id__in=course_ids, tenant=self.tenant)
                .values_list('id', flat=True)
            ]

        job = MockTestGenerationJob.objects.create(
            tenant=self.tenant,
            created_by=request.user,
            mock_test=mock_test,
            course=course,
            kind=kind,
            prompt=data['prompt'],
            input_mode=data.get('input_mode') or MockTestGenerationJob.INPUT_TEXT,
            options=options,
            provider=(data.get('provider') or '').strip(),
            model=(data.get('model') or '').strip(),
        )

        queued = _enqueue(job, mode='generate')
        job.refresh_from_db()
        payload = MockJobSerializer(job).data
        if queued:
            return Response(payload, status=status.HTTP_202_ACCEPTED)
        if job.status == MockTestGenerationJob.STATUS_FAILED:
            return Response(payload, status=status.HTTP_502_BAD_GATEWAY)
        return Response(payload, status=status.HTTP_201_CREATED)


class JobDetailView(_StudioView):
    """``GET`` the draft, ``PATCH`` an admin's edits, ``DELETE`` the job."""

    def get_job(self, job_id):
        return get_object_or_404(self.jobs(), id=job_id)

    def get(self, request, job_id):
        return Response(MockJobSerializer(self.get_job(job_id)).data)

    def patch(self, request, job_id):
        job = self.get_job(job_id)
        if not job.is_reviewable:
            return Response(
                {'detail': 'This draft can no longer be edited.'},
                status=status.HTTP_409_CONFLICT,
            )
        serializer = DraftUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.update(job, serializer.validated_data)
        return Response(MockJobSerializer(job).data)

    def delete(self, request, job_id):
        self.get_job(job_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class JobRefineView(_StudioView):
    """Ask the model to revise the draft. Still does not write anything."""

    def post(self, request, job_id):
        job = get_object_or_404(self.jobs(), id=job_id)
        if not job.is_reviewable:
            return Response(
                {'detail': 'Only a draft awaiting review can be refined.'},
                status=status.HTTP_409_CONFLICT,
            )
        serializer = RefineSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        queued = _enqueue(job, mode='refine', instruction=serializer.validated_data['instruction'])
        job.refresh_from_db()
        payload = MockJobSerializer(job).data
        if queued:
            return Response(payload, status=status.HTTP_202_ACCEPTED)
        if job.error and job.status == MockTestGenerationJob.STATUS_PREVIEW:
            # The refine failed inline but the previous draft survived.
            return Response({**payload, 'draft_preserved': True},
                            status=status.HTTP_502_BAD_GATEWAY)
        return Response(payload)


class JobRegenerateView(_StudioView):
    """Retry a job. Reuses the original prompt and blueprint."""

    def post(self, request, job_id):
        job = get_object_or_404(self.jobs(), id=job_id)
        if job.status not in (
            MockTestGenerationJob.STATUS_FAILED,
            MockTestGenerationJob.STATUS_PENDING,
            MockTestGenerationJob.STATUS_PREVIEW,
        ):
            return Response(
                {'detail': 'This job can no longer be regenerated.'},
                status=status.HTTP_409_CONFLICT,
            )
        # Reset first so the background claim is unambiguous.
        job.status = MockTestGenerationJob.STATUS_PENDING
        job.error = ''
        job.save(update_fields=['status', 'error', 'updated_at'])

        queued = _enqueue(job, mode='generate')
        job.refresh_from_db()
        payload = MockJobSerializer(job).data
        if queued:
            return Response(payload, status=status.HTTP_202_ACCEPTED)
        if job.status == MockTestGenerationJob.STATUS_FAILED:
            return Response(payload, status=status.HTTP_502_BAD_GATEWAY)
        return Response(payload)


class JobApplyView(_StudioView):
    """The one endpoint that writes. Requires an explicit confirmation."""

    def post(self, request, job_id):
        job = get_object_or_404(self.jobs(), id=job_id)
        if not job.is_reviewable:
            return Response(
                {'detail': f'This draft was already {job.get_status_display().lower()}.'},
                status=status.HTTP_409_CONFLICT,
            )

        serializer = ApplySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            summary = apply_draft(
                job, user=request.user,
                selection=serializer.validated_data.get('selection') or {},
            )
        except ApplyError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:  # noqa: BLE001 - the transaction already rolled back
            logger.exception('mockgen: apply failed for job %s', job.id)
            return Response(
                {'detail': f'Could not save this paper: {str(exc)[:200]}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({'job': MockJobSerializer(job).data, 'summary': summary})


class JobDiscardView(_StudioView):
    """Throw a draft away without writing anything."""

    def post(self, request, job_id):
        job = get_object_or_404(self.jobs(), id=job_id)
        if job.status == MockTestGenerationJob.STATUS_APPLIED:
            return Response(
                {'detail': 'An applied draft cannot be discarded.'},
                status=status.HTTP_409_CONFLICT,
            )
        job.status = MockTestGenerationJob.STATUS_DISCARDED
        job.record_revision('discarded')
        job.save(update_fields=['status', 'revisions', 'updated_at'])
        return Response(MockJobSerializer(job).data)


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsTenantAdmin])
def studio_health(request):
    """Cheap readiness probe used to gate the "Generate with AI" buttons."""
    tenant = getattr(request, 'tenant', None)
    models = generation.available_models(tenant) if tenant else []
    return Response({'is_ready': bool(models), 'provider_count': len(models)})
