"""Tenant-admin endpoints for the AI Course Builder ("Course Studio").

The contract the whole screen is built on: **generation and writing are two
separate calls.** ``POST /jobs/`` only ever produces a draft for review;
``POST /jobs/{id}/apply/`` is the single endpoint that touches course tables and
it refuses anything that is not an explicitly confirmed, still-in-preview draft.

Everything is scoped to the tenant resolved by ``TenantMiddleware`` and to the
courses the caller is allowed to edit (admins: all; instructors: assigned only).
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

from assignments.models import Assignment
from chatbot import resolver
from coding.languages import language_choices
from coding.models import CodingProblem
from content.models import Content
from core.permissions import IsCourseEditor
from exams.models import Course, Topic
from notebooks.models import Notebook
from quiz.models import Quiz

from . import generation
from .apply import ApplyError, apply_draft
from .material import topic_material
from .models import CourseGenerationJob
from .prompts import MATERIAL_TYPES
from .schema import (
    MAX_ASSIGNMENTS_PER_TOPIC,
    MAX_CODING_PROBLEMS_PER_TOPIC,
    MAX_QUESTIONS_PER_QUIZ,
    MAX_TOPICS_PER_CONTENT_JOB,
)
from .serializers import (
    ApplySerializer,
    CourseGenerationJobListSerializer,
    CourseGenerationJobSerializer,
    DraftUpdateSerializer,
    GenerateSerializer,
    RefineSerializer,
)

logger = logging.getLogger(__name__)


def _enqueue(job, *, mode='generate', instruction='', topics=None):
    """Run a generation in the background, falling back to inline if Celery is down.

    Returns True when the work was queued (the client should poll the job),
    False when it had to run inline (the job is already terminal).
    """
    if getattr(settings, 'COURSEGEN_ASYNC', True):
        try:
            from .tasks import run_generation_job
            run_generation_job.delay(str(job.id), mode, instruction, topics or [])
            return True
        except Exception as exc:  # broker down -> never block the admin
            logger.warning('coursegen: async enqueue failed (%s); running inline.', exc)

    if mode == 'refine':
        try:
            generation.apply_refinement(job, instruction)
        except generation.GenerationError:
            pass  # the job is back in preview with a user-facing error
    else:
        generation.run_job(job, topics=topics or [])
    return False


class _StudioView(APIView):
    """Shared tenant + course scoping for every studio endpoint."""

    permission_classes = [IsAuthenticated, IsCourseEditor]

    @property
    def tenant(self):
        return getattr(self.request, 'tenant', None)

    def editable_courses(self):
        """Courses this caller may build in."""
        queryset = Course.objects.filter(tenant=self.tenant)
        if getattr(self.request.user, 'role', None) == 'instructor':
            queryset = queryset.filter(
                id__in=self.request.user.instructing_courses.values_list('id', flat=True)
            )
        return queryset

    def get_course(self, course_id):
        if not course_id:
            return None
        return get_object_or_404(self.editable_courses(), id=course_id)

    def jobs(self):
        queryset = CourseGenerationJob.objects.filter(tenant=self.tenant)
        if getattr(self.request.user, 'role', None) == 'instructor':
            # An instructor sees their own jobs and jobs on their courses, never
            # another instructor's draft for a course they cannot edit.
            queryset = queryset.filter(
                course__in=self.editable_courses()
            ) | queryset.filter(created_by=self.request.user, course__isnull=True)
        return queryset.select_related('course', 'created_by').distinct()

    def can_create_courses(self):
        return getattr(self.request.user, 'role', None) == 'admin'


class StudioOptionsView(_StudioView):
    """Everything the studio needs to render its composer in one call."""

    def get(self, request):
        tenant = self.tenant
        models = generation.available_models(tenant)
        settings_obj = resolver.get_ai_settings(tenant)

        courses = [
            {'id': str(c.id), 'name': c.name, 'code': c.code, 'status': c.status}
            for c in self.editable_courses().order_by('name')
        ]

        return Response({
            'is_ready': bool(models) and settings_obj.is_enabled,
            'ai_enabled': settings_obj.is_enabled,
            'async_generation': bool(getattr(settings, 'COURSEGEN_ASYNC', True)),
            'providers': models,
            'courses': courses,
            'can_create_courses': self.can_create_courses(),
            'limits': {
                'max_topics_per_content_job': MAX_TOPICS_PER_CONTENT_JOB,
                'max_questions_per_quiz': MAX_QUESTIONS_PER_QUIZ,
                'max_assignments_per_topic': MAX_ASSIGNMENTS_PER_TOPIC,
                'max_coding_problems_per_topic': MAX_CODING_PROBLEMS_PER_TOPIC,
            },
            'materials': [
                {'id': 'notes', 'label': 'Reading notes'},
                {'id': 'quiz', 'label': 'Practice quiz'},
                {'id': 'assignment', 'label': 'Assignment'},
                {'id': 'coding', 'label': 'Coding problem'},
            ],
            'coding_languages': [
                {'id': key, 'label': label} for key, label in language_choices()
            ],
            'defaults': {
                'chapters_per_subject': 5,
                'topics_per_chapter': 4,
                'questions_per_quiz': 5,
                'assignments_per_topic': 1,
                'coding_problems_per_topic': 1,
                'coding_languages': ['python'],
                'materials': ['notes', 'quiz'],
                'mode': 'replace',
                'depth': 'standard',
                'language': 'English',
                'publish_immediately': False,
            },
            'kinds': [
                {'id': k, 'label': label}
                for k, label in CourseGenerationJob.KIND_CHOICES
            ],
            'not_ready_reason': (
                '' if models else
                'Connect an AI provider under Admin → AI Features to use the course studio.'
            ),
        })


class CourseTreeView(_StudioView):
    """The course's tree, annotated with what already has material.

    Powers the topic picker: an admin can see at a glance which topics are still
    empty before asking the AI to write for them.
    """

    def get(self, request, course_id):
        course = self.get_course(course_id)

        topics_with_notes = set(
            Content.objects.filter(
                topic__subject__course=course, content_type='notes'
            ).values_list('topic_id', flat=True)
        )
        topics_with_quiz = set(
            Quiz.objects.filter(course=course).exclude(topic=None).values_list('topic_id', flat=True)
        )
        topics_with_assignment = set(
            Assignment.objects.filter(course=course).values_list('topic_id', flat=True)
        )
        topics_with_coding = set(
            CodingProblem.objects.filter(course=course).values_list('topic_id', flat=True)
        )
        topics_with_notebook = set(
            Notebook.objects.filter(course=course).values_list('topic_id', flat=True)
        )

        subjects = []
        for subject in course.subjects.all().order_by('order', 'name'):
            chapters = []
            for chapter in subject.chapters.all().order_by('order', 'name'):
                links = (
                    chapter.chapter_topics.select_related('topic').order_by('order')
                )
                chapters.append({
                    'id': str(chapter.id),
                    'name': chapter.name,
                    'code': chapter.code,
                    'topics': [
                        {
                            'id': str(link.topic.id),
                            'name': link.topic.name,
                            'code': link.topic.code,
                            'summary': link.topic.description or '',
                            'difficulty': link.topic.difficulty,
                            'has_notes': link.topic.id in topics_with_notes,
                            'has_quiz': link.topic.id in topics_with_quiz,
                            'has_assignment': link.topic.id in topics_with_assignment,
                            'has_coding': link.topic.id in topics_with_coding,
                            'has_notebook': link.topic.id in topics_with_notebook,
                        }
                        for link in links
                    ],
                })
            subjects.append({
                'id': str(subject.id),
                'name': subject.name,
                'code': subject.code,
                'chapters': chapters,
            })

        return Response({
            'course': {
                'id': str(course.id),
                'name': course.name,
                'code': course.code,
                'status': course.status,
                'description': course.description,
                'subtitle': course.subtitle,
                'highlights': course.highlights or [],
            },
            'subjects': subjects,
        })


class TopicMaterialView(_StudioView):
    """What one topic already has — the entry point for the focused studio.

    The admin opens a topic, sees its existing readings, quizzes, assignments
    and coding problems, and only then decides whether to add to them or replace
    them. Nothing here writes.
    """

    def get(self, request, course_id, topic_id):
        course = self.get_course(course_id)
        topic = get_object_or_404(Topic, id=topic_id, subject__course=course)
        payload = topic_material(topic)
        payload['course'] = {'id': str(course.id), 'name': course.name}
        payload['topic'] = {
            'id': str(topic.id),
            'name': topic.name,
            'code': topic.code,
            'summary': topic.description or '',
            'difficulty': topic.difficulty,
            'subject_name': topic.subject.name if topic.subject_id else '',
        }
        return Response(payload)


class JobPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class JobListCreateView(_StudioView):
    """``GET`` recent jobs; ``POST`` runs a generation and returns the draft."""

    def get(self, request):
        queryset = self.jobs()
        course_id = request.query_params.get('course')
        if course_id:
            queryset = queryset.filter(course_id=course_id)
        kind = request.query_params.get('kind')
        if kind:
            queryset = queryset.filter(kind=kind)
        job_status = request.query_params.get('status')
        if job_status:
            queryset = queryset.filter(status=job_status)

        paginator = JobPagination()
        page = paginator.paginate_queryset(queryset.order_by('-created_at'), request, view=self)
        return paginator.get_paginated_response(
            CourseGenerationJobListSerializer(page, many=True).data
        )

    def post(self, request):
        serializer = GenerateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        course = self.get_course(data.get('course'))
        kind = data['kind']

        if kind == CourseGenerationJob.KIND_OUTLINE and course is None and not self.can_create_courses():
            return Response(
                {'detail': 'Only admins can create new courses. Pick an existing course to extend.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        job = CourseGenerationJob.objects.create(
            tenant=self.tenant,
            created_by=request.user,
            course=course,
            kind=kind,
            prompt=data['prompt'],
            input_mode=data.get('input_mode') or CourseGenerationJob.INPUT_TEXT,
            options=data.get('options') or {},
            provider=(data.get('provider') or '').strip(),
            model=(data.get('model') or '').strip(),
        )

        topics = []
        if kind == CourseGenerationJob.KIND_CONTENT:
            topics = self._resolve_topics(course, data.get('topic_ids') or [])
            if not topics:
                job.delete()
                return Response(
                    {'topic_ids': ['None of those topics belong to this course.']},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            # Remember the resolved topics so a regenerate can re-run the job
            # without re-authorising the caller's course scope.
            job.options = {**(job.options or {}), 'topics_snapshot': topics}
            job.save(update_fields=['options', 'updated_at'])

        queued = _enqueue(job, mode='generate', topics=topics)

        payload = CourseGenerationJobSerializer(job).data
        if queued:
            return Response(payload, status=status.HTTP_202_ACCEPTED)
        if job.status == CourseGenerationJob.STATUS_FAILED:
            return Response(payload, status=status.HTTP_502_BAD_GATEWAY)
        return Response(payload, status=status.HTTP_201_CREATED)

    @staticmethod
    def _resolve_topics(course, topic_ids):
        """Load the requested topics, in the order the admin picked them."""
        from exams.models import Topic

        found = {
            str(topic.id): topic
            for topic in Topic.objects.filter(
                id__in=topic_ids, subject__course=course
            ).select_related('subject')
        }
        ordered = []
        for topic_id in topic_ids:
            topic = found.get(str(topic_id))
            if topic is None:
                continue
            ordered.append({
                'id': str(topic.id),
                'name': topic.name,
                'code': topic.code,
                'summary': topic.description or '',
                'subject_name': topic.subject.name,
            })
        return ordered


class JobDetailView(_StudioView):
    """``GET`` the draft, ``PATCH`` an admin's edits, ``DELETE`` the job."""

    def get_job(self, job_id):
        return get_object_or_404(self.jobs(), id=job_id)

    def get(self, request, job_id):
        return Response(CourseGenerationJobSerializer(self.get_job(job_id)).data)

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
        return Response(CourseGenerationJobSerializer(job).data)

    def delete(self, request, job_id):
        job = self.get_job(job_id)
        job.delete()
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
        instruction = serializer.validated_data['instruction']

        queued = _enqueue(job, mode='refine', instruction=instruction)
        job.refresh_from_db()
        payload = CourseGenerationJobSerializer(job).data
        if queued:
            return Response(payload, status=status.HTTP_202_ACCEPTED)
        if job.error and job.status == CourseGenerationJob.STATUS_PREVIEW:
            # The refine failed inline but the previous draft survived.
            return Response(
                {**payload, 'draft_preserved': True},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(payload)


class JobRegenerateView(_StudioView):
    """Retry a failed job. Reuses the original prompt, options and topics."""

    def post(self, request, job_id):
        job = get_object_or_404(self.jobs(), id=job_id)
        if job.status not in (
            CourseGenerationJob.STATUS_FAILED, CourseGenerationJob.STATUS_PENDING,
        ):
            return Response(
                {'detail': 'Only a failed job can be regenerated.'},
                status=status.HTTP_409_CONFLICT,
            )
        # Reset first so the background claim is unambiguous.
        job.status = CourseGenerationJob.STATUS_PENDING
        job.error = ''
        job.save(update_fields=['status', 'error', 'updated_at'])

        topics = (job.options or {}).get('topics_snapshot') or []
        queued = _enqueue(job, mode='generate', topics=topics)
        job.refresh_from_db()
        payload = CourseGenerationJobSerializer(job).data
        if queued:
            return Response(payload, status=status.HTTP_202_ACCEPTED)
        if job.status == CourseGenerationJob.STATUS_FAILED:
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

        if (job.kind == CourseGenerationJob.KIND_OUTLINE
                and job.course is None and not self.can_create_courses()):
            return Response(
                {'detail': 'Only admins can create new courses.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            summary = apply_draft(
                job, user=request.user, selection=serializer.validated_data.get('selection') or {}
            )
        except ApplyError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:  # noqa: BLE001 - the transaction already rolled back
            logger.exception('coursegen: apply failed for job %s', job.id)
            return Response(
                {'detail': f'Could not save this draft: {str(exc)[:200]}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({
            'job': CourseGenerationJobSerializer(job).data,
            'summary': summary,
        })


class JobDiscardView(_StudioView):
    """Throw a draft away without writing anything."""

    def post(self, request, job_id):
        job = get_object_or_404(self.jobs(), id=job_id)
        if job.status == CourseGenerationJob.STATUS_APPLIED:
            return Response(
                {'detail': 'An applied draft cannot be discarded.'},
                status=status.HTTP_409_CONFLICT,
            )
        job.status = CourseGenerationJob.STATUS_DISCARDED
        job.record_revision('discarded')
        job.save(update_fields=['status', 'revisions', 'updated_at'])
        return Response(CourseGenerationJobSerializer(job).data)


class TranscribeView(_StudioView):
    """Server-side speech-to-text, for browsers without the Web Speech API.

    The studio dictates in-browser wherever possible (free, instant, private).
    This is the fallback: it forwards the recording to the tenant's own
    OpenAI-compatible provider, so no audio ever reaches a third party the
    academy has not already chosen.
    """

    def post(self, request):
        audio = request.FILES.get('audio')
        if audio is None:
            return Response(
                {'audio': ['Record something first.']}, status=status.HTTP_400_BAD_REQUEST
            )
        if audio.size > 25 * 1024 * 1024:
            return Response(
                {'audio': ['That recording is too long — keep it under 25 MB.']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            text = transcribe_audio(
                self.tenant,
                audio,
                provider=request.data.get('provider'),
                language=request.data.get('language') or '',
            )
        except generation.GenerationError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'text': text})


def transcribe_audio(tenant, audio, *, provider=None, language=''):
    """Transcribe ``audio`` through an OpenAI-compatible ``/audio/transcriptions``."""
    import requests

    from chatbot.models import AIProviderConfig
    from chatbot.providers import CONNECT_TIMEOUT, READ_TIMEOUT

    resolved = generation.resolve_for_admin(tenant, provider=provider)
    supported = {
        AIProviderConfig.PROVIDER_OPENAI,
        AIProviderConfig.PROVIDER_GROQ,
        AIProviderConfig.PROVIDER_CUSTOM,
    }
    if resolved.provider not in supported:
        raise generation.GenerationError(
            'Voice transcription needs an OpenAI- or Groq-compatible provider. '
            'Dictation still works directly in Chrome, Edge and Safari.'
        )

    base = (resolved.base_url or 'https://api.openai.com/v1').rstrip('/')
    model = (
        'whisper-large-v3-turbo'
        if resolved.provider == AIProviderConfig.PROVIDER_GROQ
        else 'whisper-1'
    )
    data = {'model': model}
    if language:
        data['language'] = language[:5]

    try:
        response = requests.post(
            f'{base}/audio/transcriptions',
            headers={'Authorization': f'Bearer {resolved.api_key}'},
            files={'file': (audio.name or 'speech.webm', audio.file, audio.content_type)},
            data=data,
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
        )
    except requests.RequestException as exc:
        raise generation.GenerationError(f'Could not reach the transcription service: {exc}')

    if response.status_code >= 400:
        try:
            detail = response.json().get('error', {}).get('message') or response.text
        except ValueError:
            detail = response.text
        raise generation.GenerationError(f'Transcription failed: {detail[:200]}')

    try:
        return (response.json().get('text') or '').strip()
    except ValueError:
        return response.text.strip()


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsCourseEditor])
def studio_health(request):
    """Cheap readiness probe used to gate the studio's entry buttons."""
    tenant = getattr(request, 'tenant', None)
    models = generation.available_models(tenant) if tenant else []
    return Response({
        'is_ready': bool(models),
        'provider_count': len(models),
    })
