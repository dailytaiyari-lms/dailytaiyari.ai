"""Tenant-admin endpoints for the AI Hackathon Studio.

The contract the whole screen is built on: **generation and writing are two
separate calls.** ``POST /jobs/`` only ever produces a draft for review;
``POST /jobs/{id}/apply/`` is the single endpoint that touches the hackathon
tables, and it refuses anything that is not an explicitly confirmed,
still-in-preview draft.
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

from . import generation
from .ai_serializers import (
    AIJobListSerializer,
    AIJobSerializer,
    ApplySerializer,
    DraftUpdateSerializer,
    GenerateSerializer,
    RefineSerializer,
)
from .apply import ApplyError, apply_draft
from .models import Hackathon, HackathonGenerationJob, HackathonStage
from .schema import (
    FILE_TYPES,
    ITEM_TYPES,
    MAX_ITEMS_PER_REQUEST,
    MAX_ITEMS_PER_STAGE,
    MAX_STAGES,
    STAGE_TYPES,
)

logger = logging.getLogger(__name__)

OPEN_STATUSES = ('pending', 'generating', 'preview')

ITEM_TYPE_LABELS = {
    'mcq': 'MCQ (single answer)',
    'mcq_multi': 'MCQ (multiple answers)',
    'numerical': 'Numerical',
    'subjective': 'Subjective (written)',
    'coding': 'Coding',
}
STAGE_TYPE_LABELS = {
    'quiz': 'Quiz round',
    'coding': 'Coding round',
    'lab': 'Hands-on lab',
    'submission': 'Project submission',
}


def _async_enabled():
    return bool(getattr(settings, 'HACKATHONGEN_ASYNC',
                        getattr(settings, 'COURSEGEN_ASYNC', True)))


def _enqueue(job, *, mode='generate', instruction=''):
    """Run a generation in the background, falling back to inline if Celery is down.

    Returns True when the work was queued (the studio should poll the job),
    False when it had to run inline (the job is already terminal).
    """
    if _async_enabled():
        # Flip to "queued" *before* handing the job over, otherwise a refine
        # would answer while the job still reads ``preview`` and the studio,
        # seeing a settled job, would stop polling and show the stale draft.
        job.status = 'pending'
        job.error = ''
        job.save(update_fields=['status', 'error', 'updated_at'])
        try:
            from .tasks import run_generation_job
            run_generation_job.delay(str(job.id), mode, instruction)
            return True
        except Exception as exc:  # broker down -> never block the admin
            logger.warning('hackathongen: async enqueue failed (%s); running inline.', exc)

    if mode == 'refine':
        try:
            generation.apply_refinement(job, instruction)
        except generation.GenerationError:
            pass  # the job is back in preview with a user-facing error
    else:
        generation.run_job(job)
    return False


class _StudioView(APIView):
    """Shared tenant scoping for every hackathon-studio endpoint."""

    permission_classes = [IsAuthenticated, IsTenantAdmin]

    @property
    def tenant(self):
        return getattr(self.request, 'tenant', None)

    def get_hackathon(self, hackathon_id):
        if not hackathon_id:
            return None
        return get_object_or_404(
            Hackathon.objects.filter(tenant=self.tenant), id=hackathon_id,
        )

    def get_stage(self, stage_id):
        if not stage_id:
            return None
        return get_object_or_404(
            HackathonStage.objects.filter(hackathon__tenant=self.tenant)
            .select_related('hackathon'),
            id=stage_id,
        )

    def jobs(self):
        return (
            HackathonGenerationJob.objects
            .filter(tenant=self.tenant)
            .select_related('hackathon', 'stage', 'created_by')
        )


class StudioOptionsView(_StudioView):
    """Everything the studio needs to render its composer in one call."""

    def get(self, request):
        tenant = self.tenant
        models = generation.available_models(tenant)
        settings_obj = resolver.get_ai_settings(tenant)

        hackathons = [
            {'id': str(h.id), 'title': h.title, 'status': h.status,
             'stages': h.stages.count()}
            for h in Hackathon.objects.filter(tenant=tenant).order_by('-created_at')[:100]
        ]

        return Response({
            'is_ready': bool(models) and settings_obj.is_enabled,
            'ai_enabled': settings_obj.is_enabled,
            'async_generation': _async_enabled(),
            'providers': models,
            'hackathons': hackathons,
            'kinds': [
                {'id': key, 'label': label}
                for key, label in HackathonGenerationJob.KIND_CHOICES
            ],
            'item_types': [
                {'id': key, 'label': ITEM_TYPE_LABELS.get(key, key)} for key in ITEM_TYPES
            ],
            'stage_types': [
                {'id': key, 'label': STAGE_TYPE_LABELS.get(key, key)} for key in STAGE_TYPES
            ],
            'coding_languages': [
                {'id': key, 'label': label} for key, label in language_choices()
            ],
            'file_types': list(FILE_TYPES),
            'limits': {
                'max_items_per_request': MAX_ITEMS_PER_REQUEST,
                'max_items_per_stage': MAX_ITEMS_PER_STAGE,
                'max_stages': MAX_STAGES,
            },
            'defaults': {
                'stage_count': 3,
                'difficulty': 'all_levels',
                'mode': 'online',
                'language': 'English',
                'include_stages': True,
                'blueprint': [
                    {'item_type': 'mcq', 'count': 10, 'marks': 4, 'negative_marks': 1},
                ],
            },
            'not_ready_reason': (
                '' if models else
                'Connect an AI provider under Admin → AI Features to use the '
                'hackathon studio.'
            ),
        })


class StagesForHackathonView(_StudioView):
    """The rounds of one hackathon, so the studio can target one for content."""

    def get(self, request, hackathon_id):
        hackathon = self.get_hackathon(hackathon_id)
        return Response({
            'hackathon': {'id': str(hackathon.id), 'title': hackathon.title},
            'stages': [
                {'id': str(stage.id), 'title': stage.title, 'order': stage.order,
                 'stage_type': stage.stage_type, 'status': stage.status,
                 'items_count': stage.items.count(), 'max_score': float(stage.max_score)}
                for stage in hackathon.stages.all().order_by('order', 'created_at')
            ],
        })


class JobPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class JobListCreateView(_StudioView):
    """``GET`` recent jobs; ``POST`` starts a generation and returns the job."""

    def get(self, request):
        queryset = self.jobs()
        for param, field in (('hackathon', 'hackathon_id'), ('stage', 'stage_id'),
                             ('kind', 'kind')):
            value = request.query_params.get(param)
            if value:
                queryset = queryset.filter(**{field: value})

        raw_status = request.query_params.get('status')
        if raw_status == 'open':
            queryset = queryset.filter(status__in=OPEN_STATUSES)
        elif raw_status == 'running':
            queryset = queryset.filter(status__in=('pending', 'generating'))
        elif raw_status:
            wanted = [value.strip() for value in raw_status.split(',') if value.strip()]
            if wanted:
                queryset = queryset.filter(status__in=wanted)

        paginator = JobPagination()
        page = paginator.paginate_queryset(queryset.order_by('-created_at'), request, view=self)
        return paginator.get_paginated_response(AIJobListSerializer(page, many=True).data)

    def post(self, request):
        serializer = GenerateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        stage = self.get_stage(data.get('stage'))
        hackathon = self.get_hackathon(data.get('hackathon'))
        if stage is not None and hackathon is None:
            hackathon = stage.hackathon

        job = HackathonGenerationJob.objects.create(
            tenant=self.tenant,
            created_by=request.user,
            hackathon=hackathon,
            stage=stage,
            kind=data.get('kind') or 'event',
            prompt=data['prompt'],
            options=data['options'],
            provider=(data.get('provider') or '').strip(),
            model=(data.get('model') or '').strip(),
        )

        queued = _enqueue(job, mode='generate')
        job.refresh_from_db()
        payload = AIJobSerializer(job).data
        if queued:
            return Response(payload, status=status.HTTP_202_ACCEPTED)
        if job.status == 'failed':
            return Response(payload, status=status.HTTP_502_BAD_GATEWAY)
        return Response(payload, status=status.HTTP_201_CREATED)


class JobDetailView(_StudioView):
    """``GET`` the draft, ``PATCH`` an admin's edits, ``DELETE`` the job."""

    def get_job(self, job_id):
        return get_object_or_404(self.jobs(), id=job_id)

    def get(self, request, job_id):
        return Response(AIJobSerializer(self.get_job(job_id)).data)

    def patch(self, request, job_id):
        job = self.get_job(job_id)
        if not job.can_apply:
            return Response(
                {'detail': 'This draft can no longer be edited.'},
                status=status.HTTP_409_CONFLICT,
            )
        serializer = DraftUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.update(job, serializer.validated_data)
        return Response(AIJobSerializer(job).data)

    def delete(self, request, job_id):
        self.get_job(job_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class JobRefineView(_StudioView):
    """Ask the model to revise the draft. Still does not write anything."""

    def post(self, request, job_id):
        job = get_object_or_404(self.jobs(), id=job_id)
        if not job.can_apply:
            return Response(
                {'detail': 'Only a draft awaiting review can be refined.'},
                status=status.HTTP_409_CONFLICT,
            )
        serializer = RefineSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        queued = _enqueue(
            job, mode='refine', instruction=serializer.validated_data['instruction'],
        )
        job.refresh_from_db()
        payload = AIJobSerializer(job).data
        if queued:
            return Response(payload, status=status.HTTP_202_ACCEPTED)
        if job.error and job.status == 'preview':
            return Response({**payload, 'draft_preserved': True},
                            status=status.HTTP_502_BAD_GATEWAY)
        return Response(payload)


class JobRegenerateView(_StudioView):
    """Retry a job, reusing its original prompt and options."""

    def post(self, request, job_id):
        job = get_object_or_404(self.jobs(), id=job_id)
        if job.status not in HackathonGenerationJob.RUNNABLE_STATUSES:
            return Response(
                {'detail': 'This job can no longer be regenerated.'},
                status=status.HTTP_409_CONFLICT,
            )
        job.status = 'pending'
        job.error = ''
        job.save(update_fields=['status', 'error', 'updated_at'])

        queued = _enqueue(job, mode='generate')
        job.refresh_from_db()
        payload = AIJobSerializer(job).data
        if queued:
            return Response(payload, status=status.HTTP_202_ACCEPTED)
        if job.status == 'failed':
            return Response(payload, status=status.HTTP_502_BAD_GATEWAY)
        return Response(payload)


class JobApplyView(_StudioView):
    """The one endpoint that writes. Requires an explicit confirmation."""

    def post(self, request, job_id):
        job = get_object_or_404(self.jobs(), id=job_id)
        if not job.can_apply:
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
            logger.exception('hackathongen: apply failed for job %s', job.id)
            return Response(
                {'detail': f'Could not save this draft: {str(exc)[:200]}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        job.refresh_from_db()
        return Response({'job': AIJobSerializer(job).data, 'summary': summary})


class JobDiscardView(_StudioView):
    """Throw a draft away without writing anything."""

    def post(self, request, job_id):
        job = get_object_or_404(self.jobs(), id=job_id)
        if job.status == 'applied':
            return Response(
                {'detail': 'An applied draft cannot be discarded.'},
                status=status.HTTP_409_CONFLICT,
            )
        job.status = 'discarded'
        job.log('discarded')
        job.save(update_fields=['status', 'revisions', 'updated_at'])
        return Response(AIJobSerializer(job).data)


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsTenantAdmin])
def studio_health(request):
    """Cheap readiness probe used to gate the "Generate with AI" buttons."""
    tenant = getattr(request, 'tenant', None)
    models = generation.available_models(tenant) if tenant else []
    return Response({'is_ready': bool(models), 'provider_count': len(models)})
