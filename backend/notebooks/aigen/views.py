"""Tenant-admin endpoints for the AI Notebook Builder.

The contract mirrors the Course Builder: **generation and writing are two
separate calls.** ``POST /jobs/`` only ever produces a draft (in the
background); ``POST /jobs/{id}/apply/`` is the single endpoint that creates a
real Notebook, and only from an explicitly confirmed, still-in-preview draft.

Because a graded notebook is a long LLM call, generation runs on the
``notebooks`` Celery queue and the client polls ``GET /jobs/{id}/``. If the
broker is unreachable the call falls back to running inline so the feature keeps
working without Celery.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from chatbot import resolver
from core.permissions import IsCourseEditor
from exams.models import Course, Topic

from ..models import NotebookGenerationJob
from . import generation
from .apply import ApplyError, apply_draft
from .serializers import (
    ApplySerializer,
    GenerateSerializer,
    NotebookGenerationJobListSerializer,
    NotebookGenerationJobSerializer,
    RefineSerializer,
)

logger = logging.getLogger(__name__)


class _StudioView(APIView):
    """Shared tenant + course scoping for every notebook-studio endpoint."""

    permission_classes = [IsAuthenticated, IsCourseEditor]

    @property
    def tenant(self):
        return getattr(self.request, 'tenant', None)

    def editable_courses(self):
        queryset = Course.objects.filter(tenant=self.tenant)
        if getattr(self.request.user, 'role', None) == 'instructor':
            queryset = queryset.filter(
                id__in=self.request.user.instructing_courses.values_list('id', flat=True)
            )
        return queryset

    def jobs(self):
        queryset = NotebookGenerationJob.objects.filter(tenant=self.tenant)
        if getattr(self.request.user, 'role', None) == 'instructor':
            queryset = queryset.filter(course__in=self.editable_courses())
        return queryset.select_related('course', 'subject', 'topic', 'created_by', 'notebook')


def _enqueue(job, *, mode='generate', instruction=''):
    """Run generation in the background, falling back to inline if Celery is down.

    Returns True when the work was queued (client should poll), False when it ran
    inline (the job is already terminal).
    """
    if getattr(settings, 'NOTEBOOKS_GEN_ASYNC', True):
        try:
            from ..tasks import run_generation_job
            run_generation_job.delay(str(job.id), mode, instruction)
            return True
        except Exception as exc:  # broker down -> never block the admin
            logger.warning('notebookgen: async enqueue failed (%s); running inline.', exc)

    if mode == 'refine':
        try:
            generation.apply_refinement(job, instruction)
        except generation.GenerationError:
            pass  # job already restored to preview with an error message
    else:
        generation.run_job(job)
    return False


class JobPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class OptionsView(_StudioView):
    """Everything the notebook studio needs to render its composer."""

    def get(self, request):
        tenant = self.tenant
        models = generation.available_models(tenant)
        settings_obj = resolver.get_ai_settings(tenant)
        return Response({
            'is_ready': bool(models) and settings_obj.is_enabled,
            'ai_enabled': settings_obj.is_enabled,
            'providers': models,
            'async_generation': bool(getattr(settings, 'NOTEBOOKS_GEN_ASYNC', True)),
            'difficulties': ['easy', 'medium', 'hard'],
        })


class JobListCreateView(_StudioView):
    """``GET`` recent jobs; ``POST`` starts a generation (returns immediately)."""

    def get(self, request):
        queryset = self.jobs()
        for field in ('course', 'topic', 'status'):
            value = request.query_params.get(field)
            if value:
                queryset = queryset.filter(**{field if field == 'status' else f'{field}_id': value})
        paginator = JobPagination()
        page = paginator.paginate_queryset(queryset.order_by('-created_at'), request, view=self)
        return paginator.get_paginated_response(
            NotebookGenerationJobListSerializer(page, many=True).data
        )

    def post(self, request):
        serializer = GenerateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        course = get_object_or_404(self.editable_courses(), id=data['course'])
        topic = get_object_or_404(
            Topic.objects.filter(subject__course=course).select_related('subject'),
            id=data['topic'],
        )

        job = NotebookGenerationJob.objects.create(
            tenant=self.tenant,
            created_by=request.user,
            course=course,
            subject=topic.subject,
            topic=topic,
            kind=NotebookGenerationJob.KIND_NOTEBOOK,
            prompt=data['prompt'],
            options=data.get('options') or {},
            provider=(data.get('provider') or '').strip(),
            model=(data.get('model') or '').strip(),
        )

        queued = _enqueue(job, mode='generate')
        job.refresh_from_db()
        payload = NotebookGenerationJobSerializer(job).data
        if queued:
            return Response(payload, status=status.HTTP_202_ACCEPTED)
        if job.status == NotebookGenerationJob.STATUS_FAILED:
            return Response(payload, status=status.HTTP_502_BAD_GATEWAY)
        return Response(payload, status=status.HTTP_201_CREATED)


class JobDetailView(_StudioView):
    """``GET`` (poll) the job, ``DELETE`` it."""

    def get_job(self, job_id):
        return get_object_or_404(self.jobs(), id=job_id)

    def get(self, request, job_id):
        return Response(NotebookGenerationJobSerializer(self.get_job(job_id)).data)

    def delete(self, request, job_id):
        self.get_job(job_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class JobRefineView(_StudioView):
    """"Modify with AI" — revise the reviewable draft in the background."""

    def post(self, request, job_id):
        job = get_object_or_404(self.jobs(), id=job_id)
        if not job.is_reviewable:
            return Response(
                {'detail': 'Only a draft awaiting review can be modified.'},
                status=status.HTTP_409_CONFLICT,
            )
        serializer = RefineSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instruction = serializer.validated_data['instruction']

        queued = _enqueue(job, mode='refine', instruction=instruction)
        job.refresh_from_db()
        payload = NotebookGenerationJobSerializer(job).data
        if queued:
            return Response(payload, status=status.HTTP_202_ACCEPTED)
        if job.error and job.status == NotebookGenerationJob.STATUS_PREVIEW:
            # Inline refine failed but preserved the previous draft.
            return Response(
                {**payload, 'draft_preserved': True},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(payload)


class JobRegenerateView(_StudioView):
    """Retry a failed job (or start a fresh attempt) in the background."""

    def post(self, request, job_id):
        job = get_object_or_404(self.jobs(), id=job_id)
        if job.status not in (
            NotebookGenerationJob.STATUS_FAILED, NotebookGenerationJob.STATUS_PENDING,
        ):
            return Response(
                {'detail': 'Only a failed job can be regenerated.'},
                status=status.HTTP_409_CONFLICT,
            )
        # Reset to pending so the background claim is unambiguous.
        job.status = NotebookGenerationJob.STATUS_PENDING
        job.error = ''
        job.save(update_fields=['status', 'error', 'updated_at'])

        queued = _enqueue(job, mode='generate')
        job.refresh_from_db()
        payload = NotebookGenerationJobSerializer(job).data
        if queued:
            return Response(payload, status=status.HTTP_202_ACCEPTED)
        if job.status == NotebookGenerationJob.STATUS_FAILED:
            return Response(payload, status=status.HTTP_502_BAD_GATEWAY)
        return Response(payload)


class JobApplyView(_StudioView):
    """The one endpoint that writes. Creates the real Notebook + tests."""

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
            summary = apply_draft(job, user=request.user)
        except ApplyError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:  # noqa: BLE001 - the transaction already rolled back
            logger.exception('notebookgen: apply failed for job %s', job.id)
            return Response(
                {'detail': f'Could not save this notebook: {str(exc)[:200]}'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({
            'job': NotebookGenerationJobSerializer(job).data,
            'summary': summary,
        })


class JobDiscardView(_StudioView):
    """Throw a draft away without writing anything."""

    def post(self, request, job_id):
        job = get_object_or_404(self.jobs(), id=job_id)
        if job.status == NotebookGenerationJob.STATUS_APPLIED:
            return Response(
                {'detail': 'An applied draft cannot be discarded.'},
                status=status.HTTP_409_CONFLICT,
            )
        job.status = NotebookGenerationJob.STATUS_DISCARDED
        job.record_revision('discarded')
        job.save(update_fields=['status', 'revisions', 'updated_at'])
        return Response(NotebookGenerationJobSerializer(job).data)
