"""
Student-facing hackathon API.

Browsing is public (anonymous visitors get the full event page); everything
that writes — registering, attempting a round, submitting a project — requires
a logged-in student. Round access is gated by ``grading.is_eligible_for`` so a
participant can never reach a round they did not qualify for, even by URL.
"""
import logging
import mimetypes
import os
from decimal import Decimal, InvalidOperation

from django.db.models import Count, Q
from django.http import FileResponse, Http404
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from . import grading, notify
from .models import (
    Hackathon,
    HackathonRegistration,
    HackathonStageItem,
    StageItemAnswer,
    StageParticipation,
    StageSubmission,
    StageSubmissionFile,
)
from .serializers import (
    HackathonDetailSerializer,
    HackathonListSerializer,
    MyRegistrationSerializer,
    MyRegistrationWithHackathonSerializer,
    RegisterSerializer,
    StageSubmissionSerializer,
)

logger = logging.getLogger(__name__)

PUBLIC_ACTIONS = {'list', 'retrieve', 'winners', 'stage_public'}


class HackathonViewSet(viewsets.ReadOnlyModelViewSet):
    """Public browsing + the participant's own journey through an event."""

    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_permissions(self):
        if self.action in PUBLIC_ACTIONS:
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]

    # -- helpers ----------------------------------------------------------
    def _tenant(self):
        return getattr(self.request, 'tenant', None)

    def _student(self):
        user = self.request.user
        if not user or not user.is_authenticated:
            return None
        return getattr(user, 'profile', None)

    def _registration(self, hackathon, *, active_only=False):
        student = self._student()
        if not student:
            return None
        qs = HackathonRegistration.objects.filter(
            hackathon=hackathon, participant=student,
        )
        if active_only:
            qs = qs.filter(status='registered')
        return qs.first()

    def get_queryset(self):
        tenant = self._tenant()
        if not tenant:
            return Hackathon.objects.none()
        qs = Hackathon.objects.filter(
            tenant=tenant, status__in=['published', 'completed'],
        ).prefetch_related('related_courses')
        return qs

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return HackathonDetailSerializer
        return HackathonListSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        student = self._student()
        if student and self.action == 'list':
            context['registered_ids'] = set(
                str(x) for x in HackathonRegistration.objects.filter(
                    participant=student, status='registered',
                ).values_list('hackathon_id', flat=True)
            )
        return context

    # -- browsing ---------------------------------------------------------
    def list(self, request, *args, **kwargs):
        qs = self.get_queryset().annotate(
            registrations_total=Count(
                'registrations', filter=Q(registrations__status='registered'),
                distinct=True,
            ),
            published_stages_total=Count(
                'stages', filter=Q(stages__status__in=['published', 'completed']),
                distinct=True,
            ),
        )

        search = (request.query_params.get('search') or '').strip()
        if search:
            qs = qs.filter(
                Q(title__icontains=search)
                | Q(tagline__icontains=search)
                | Q(organizer_name__icontains=search)
            )
        mode = request.query_params.get('mode')
        if mode in dict(Hackathon.MODE_CHOICES):
            qs = qs.filter(mode=mode)
        difficulty = request.query_params.get('difficulty')
        if difficulty in dict(Hackathon.DIFFICULTY_CHOICES):
            qs = qs.filter(difficulty=difficulty)

        # `state` lets the listing show Live / Upcoming / Past tabs cheaply.
        state = request.query_params.get('state')
        now = timezone.now()
        if state == 'live':
            qs = qs.filter(
                Q(starts_at__lte=now) | Q(starts_at__isnull=True),
            ).filter(Q(ends_at__gte=now) | Q(ends_at__isnull=True))
        elif state == 'upcoming':
            qs = qs.filter(starts_at__gt=now)
        elif state == 'past':
            qs = qs.filter(ends_at__lt=now)

        qs = qs.order_by('-starts_at', '-created_at')
        page = self.paginate_queryset(qs)
        serializer = self.get_serializer(page if page is not None else qs, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        hackathon = self.get_object()
        Hackathon.objects.filter(pk=hackathon.pk).update(
            views_count=hackathon.views_count + 1,
        )
        registration = self._registration(hackathon)
        context = self.get_serializer_context()
        context['my_registration'] = registration
        return Response(
            HackathonDetailSerializer(hackathon, context=context).data
        )

    @action(detail=True, methods=['get'])
    def winners(self, request, pk=None):
        hackathon = self.get_object()
        if not hackathon.results_announced:
            return Response({'announced': False, 'winners': []})
        from .serializers import WinnerSerializer
        qs = hackathon.registrations.filter(is_winner=True).select_related(
            'participant__user',
        ).order_by('final_rank')
        return Response({
            'announced': True,
            'announced_at': hackathon.results_announced_at,
            'winners': WinnerSerializer(qs, many=True).data,
        })

    @action(detail=True, methods=['get'])
    def leaderboard(self, request, pk=None):
        hackathon = self.get_object()
        if not hackathon.show_leaderboard:
            return Response({'enabled': False, 'entries': []})
        stage_id = request.query_params.get('stage_id')
        stage = None
        if stage_id:
            stage = hackathon.stages.filter(id=stage_id, results_published=True).first()
            if not stage:
                return Response({'enabled': True, 'entries': []})
        return Response({
            'enabled': True,
            'stage_id': stage_id if stage else None,
            'entries': grading.leaderboard(hackathon, stage=stage),
        })

    # -- registration -----------------------------------------------------
    @action(detail=True, methods=['post'])
    def register(self, request, pk=None):
        hackathon = self.get_object()
        student = self._student()
        if not student:
            return Response(
                {'error': 'Only student accounts can register for a hackathon.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        existing = HackathonRegistration.objects.filter(
            hackathon=hackathon, participant=student,
        ).first()
        if existing and existing.status == 'registered':
            return Response(
                MyRegistrationSerializer(existing).data, status=status.HTTP_200_OK,
            )
        if existing and existing.status == 'disqualified':
            return Response(
                {'error': 'You are not eligible to register for this hackathon.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        state = hackathon.registration_state
        if state != 'open':
            messages = {
                'not_open': 'Registrations have not opened yet.',
                'opening_soon': 'Registrations have not opened yet.',
                'closed': 'Registrations for this hackathon are closed.',
                'full': 'All seats for this hackathon are taken.',
            }
            return Response(
                {'error': messages.get(state, 'Registrations are closed.'),
                 'registration_state': state},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if existing:  # re-registering after a withdrawal
            for field, value in data.items():
                setattr(existing, field, value)
            existing.status = 'registered'
            existing.registered_at = timezone.now()
            existing.save()
            registration = existing
        else:
            registration = HackathonRegistration.objects.create(
                tenant=hackathon.tenant,
                hackathon=hackathon,
                participant=student,
                status='registered',
                **data,
            )

        # Seed the first round so the participant lands somewhere concrete.
        first_stage = hackathon.stages.filter(
            status='published',
        ).order_by('order', 'created_at').first()
        if first_stage:
            grading.get_or_create_participation(first_stage, registration)

        notify.on_registered(registration)
        return Response(
            MyRegistrationSerializer(registration).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['post'])
    def withdraw(self, request, pk=None):
        hackathon = self.get_object()
        registration = self._registration(hackathon, active_only=True)
        if not registration:
            return Response({'error': 'You are not registered for this hackathon.'},
                            status=status.HTTP_404_NOT_FOUND)
        registration.status = 'withdrawn'
        registration.save(update_fields=['status', 'updated_at'])
        return Response({'status': 'withdrawn'})

    @action(detail=False, methods=['get'], url_path='my-registrations')
    def my_registrations(self, request):
        student = self._student()
        if not student:
            return Response([])
        qs = (
            HackathonRegistration.objects
            .filter(participant=student, hackathon__tenant=self._tenant())
            .select_related('hackathon')
            .prefetch_related('participations__stage')
            .order_by('-registered_at')
        )
        return Response(MyRegistrationWithHackathonSerializer(qs, many=True).data)

    @action(detail=True, methods=['get'], url_path='my-progress')
    def my_progress(self, request, pk=None):
        """Everything the participant needs to know about their journey."""
        hackathon = self.get_object()
        registration = self._registration(hackathon, active_only=True)
        if not registration:
            return Response({'registered': False, 'stages': []})

        stages = list(
            hackathon.stages.filter(status__in=['published', 'completed'])
            .order_by('order', 'created_at')
        )
        by_stage = {
            p.stage_id: p for p in StageParticipation.objects.filter(
                registration=registration, stage__in=stages,
            )
        }

        payload = []
        for stage in stages:
            participation = by_stage.get(stage.id)
            eligible = grading.is_eligible_for(stage, registration)
            entry = {
                'stage_id': str(stage.id),
                'title': stage.title,
                'stage_type': stage.stage_type,
                'order': stage.order,
                'timing_state': stage.timing_state,
                'starts_at': stage.starts_at,
                'ends_at': stage.ends_at,
                'is_open': stage.is_open,
                'eligible': eligible,
                'results_published': stage.results_published,
                'status': participation.status if participation else (
                    'pending' if eligible else 'locked'
                ),
                'qualification': participation.qualification if participation else 'undecided',
                'attempt_number': participation.attempt_number if participation else 0,
                'score': None,
                'max_score': float(stage.computed_max_score() or 0),
                'rank': participation.rank if participation else None,
                'feedback': participation.feedback if participation else '',
            }
            if participation and stage.results_published:
                entry['score'] = float(participation.effective_score)
            payload.append(entry)

        return Response({
            'registered': True,
            'registration': MyRegistrationSerializer(registration).data,
            'stages': payload,
        })

    # -- rounds -----------------------------------------------------------
    def _stage_and_participation(self, hackathon, stage_id, *, require_open=False):
        """Resolve (stage, registration, participation) or raise a DRF Response.

        Returns a tuple ``(ok, payload)``. When ``ok`` is False, ``payload`` is
        a ready-to-return ``Response``.
        """
        stage = hackathon.stages.filter(
            id=stage_id, status__in=['published', 'completed'],
        ).first()
        if not stage:
            return False, Response({'error': 'Round not found.'},
                                   status=status.HTTP_404_NOT_FOUND)

        registration = self._registration(hackathon, active_only=True)
        if not registration:
            return False, Response(
                {'error': 'Register for this hackathon to take part.',
                 'code': 'not_registered'},
                status=status.HTTP_403_FORBIDDEN,
            )

        if not grading.is_eligible_for(stage, registration):
            prev = grading.previous_stage(stage)
            prev_participation = StageParticipation.objects.filter(
                stage=prev, registration=registration,
            ).first() if prev else None
            reason = 'not_qualified' if (
                prev_participation and prev_participation.qualification == 'not_qualified'
            ) else 'awaiting_results'
            return False, Response(
                {'error': 'You have not qualified for this round.',
                 'code': reason,
                 'previous_stage': str(prev.id) if prev else None},
                status=status.HTTP_403_FORBIDDEN,
            )

        participation = grading.get_or_create_participation(stage, registration)
        if require_open and not stage.is_open:
            return False, Response(
                {'error': 'This round is not open right now.',
                 'code': stage.timing_state},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return True, (stage, registration, participation)

    @action(detail=True, methods=['get'], url_path=r'stages/(?P<stage_id>[^/.]+)')
    def stage_detail(self, request, pk=None, stage_id=None):
        """The round's brief + the participant's state + (if live) the paper."""
        hackathon = self.get_object()
        ok, payload = self._stage_and_participation(hackathon, stage_id)
        if not ok:
            return payload
        stage, registration, participation = payload

        data = {
            'id': str(stage.id),
            'title': stage.title,
            'description': stage.description,
            'instructions': stage.instructions,
            'stage_type': stage.stage_type,
            'order': stage.order,
            'starts_at': stage.starts_at,
            'ends_at': stage.ends_at,
            'duration_minutes': stage.duration_minutes,
            'max_attempts': stage.max_attempts,
            'timing_state': stage.timing_state,
            'is_open': stage.is_open,
            'max_score': float(stage.computed_max_score() or 0),
            'results_published': stage.results_published,
            'hackathon': {'id': str(hackathon.id), 'title': hackathon.title},
            'participation': {
                'id': str(participation.id),
                'status': participation.status,
                'qualification': participation.qualification,
                'attempt_number': participation.attempt_number,
                'started_at': participation.started_at,
                'submitted_at': participation.submitted_at,
                'score': (float(participation.effective_score)
                          if stage.results_published else None),
                'max_score': float(participation.max_score or 0),
                'rank': participation.rank,
                'feedback': participation.feedback if stage.results_published else '',
            },
        }

        if stage.stage_type in ('quiz', 'coding'):
            reveal = bool(stage.results_published)
            data['items'] = grading.build_paper(stage, reveal_answers=reveal)
            if reveal:
                data['my_answers'] = [
                    {
                        'item_id': str(a.item_id),
                        'selected_options': a.selected_options,
                        'numerical_answer': (float(a.numerical_answer)
                                             if a.numerical_answer is not None else None),
                        'answer_text': a.answer_text,
                        'code': a.code,
                        'language': a.language,
                        'is_correct': a.is_correct,
                        'marks_obtained': float(a.marks_obtained),
                        'max_marks': float(a.max_marks),
                        'feedback': a.feedback,
                        'passed_count': a.passed_count,
                        'total_count': a.total_count,
                    }
                    for a in participation.answers.select_related('item')
                ]
        elif stage.stage_type == 'lab':
            data['notebook'] = (
                {'id': str(stage.notebook_id), 'title': stage.notebook.title}
                if stage.notebook_id else None
            )
        elif stage.stage_type == 'submission':
            data.update({
                'submission_instructions': stage.submission_instructions,
                'allowed_file_types': stage.allowed_file_types or [],
                'max_file_mb': stage.max_file_mb,
                'max_files': stage.max_files,
                'require_repo_url': stage.require_repo_url,
                'require_demo_url': stage.require_demo_url,
                'require_video_url': stage.require_video_url,
                'allow_resubmission': stage.allow_resubmission,
            })
            submission = getattr(participation, 'submission', None)
            data['my_submission'] = (
                StageSubmissionSerializer(submission).data if submission else None
            )

        return Response(data)

    @action(detail=True, methods=['post'], url_path=r'stages/(?P<stage_id>[^/.]+)/start')
    def stage_start(self, request, pk=None, stage_id=None):
        """Begin (or resume) an attempt. Idempotent within an attempt."""
        hackathon = self.get_object()
        ok, payload = self._stage_and_participation(
            hackathon, stage_id, require_open=True,
        )
        if not ok:
            return payload
        stage, _registration, participation = payload

        if participation.status in ('submitted', 'evaluated'):
            if participation.attempt_number >= stage.max_attempts:
                return Response(
                    {'error': 'You have used all your attempts for this round.',
                     'code': 'attempts_exhausted'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            participation.answers.all().delete()

        if participation.status != 'in_progress':
            participation.status = 'in_progress'
            participation.attempt_number += 1
            participation.started_at = timezone.now()
            participation.submitted_at = None
            participation.max_score = Decimal(str(stage.computed_max_score() or 0))
            participation.save(update_fields=[
                'status', 'attempt_number', 'started_at', 'submitted_at',
                'max_score', 'updated_at',
            ])

        return Response({
            'participation_id': str(participation.id),
            'status': participation.status,
            'attempt_number': participation.attempt_number,
            'started_at': participation.started_at,
            'duration_minutes': stage.duration_minutes,
            'ends_at': stage.ends_at,
            'items': grading.build_paper(stage),
        })

    @action(detail=True, methods=['post'], url_path=r'stages/(?P<stage_id>[^/.]+)/run')
    def stage_run(self, request, pk=None, stage_id=None):
        """Run code against the visible sample cases. Nothing is stored."""
        hackathon = self.get_object()
        ok, payload = self._stage_and_participation(
            hackathon, stage_id, require_open=True,
        )
        if not ok:
            return payload
        stage, _registration, _participation = payload

        item = HackathonStageItem.objects.filter(
            stage=stage, id=request.data.get('item_id'), item_type='coding',
        ).first()
        if not item:
            return Response({'error': 'Coding problem not found.'},
                            status=status.HTTP_404_NOT_FOUND)

        language = request.data.get('language') or ''
        source = request.data.get('source_code') or ''
        if not source.strip():
            return Response({'error': 'Write some code first.'},
                            status=status.HTTP_400_BAD_REQUEST)
        if item.allowed_languages and language not in item.allowed_languages:
            return Response({'error': 'That language is not allowed here.'},
                            status=status.HTTP_400_BAD_REQUEST)

        stdin = request.data.get('stdin')
        try:
            from coding.services import EngineError
            result = grading.run_samples(
                item, language=language, source=source, stdin=stdin,
            )
        except EngineError as exc:
            return Response({'error': str(exc)},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response(result)

    @action(detail=True, methods=['post'], url_path=r'stages/(?P<stage_id>[^/.]+)/submit')
    def stage_submit(self, request, pk=None, stage_id=None):
        """Submit a quiz/coding round. Auto-grades everything it can."""
        hackathon = self.get_object()
        ok, payload = self._stage_and_participation(
            hackathon, stage_id, require_open=True,
        )
        if not ok:
            return payload
        stage, _registration, participation = payload

        if stage.stage_type not in ('quiz', 'coding'):
            return Response({'error': 'This round is not answered with a paper.'},
                            status=status.HTTP_400_BAD_REQUEST)
        if participation.status not in ('in_progress',):
            return Response({'error': 'Start the round before submitting.',
                             'code': 'not_started'},
                            status=status.HTTP_400_BAD_REQUEST)

        answers = request.data.get('answers') or []
        items = {str(i.id): i for i in stage.items.all()}

        participation.answers.all().delete()
        for raw in answers:
            item = items.get(str(raw.get('item_id')))
            if not item:
                continue
            numerical = raw.get('numerical_answer')
            try:
                numerical = Decimal(str(numerical)) if numerical not in (None, '') else None
            except (InvalidOperation, ValueError):
                numerical = None
            answer = StageItemAnswer(
                tenant=hackathon.tenant,
                participation=participation,
                item=item,
                selected_options=raw.get('selected_options') or [],
                numerical_answer=numerical,
                answer_text=(raw.get('answer_text') or '')[:20000],
                code=(raw.get('code') or '')[:100000],
                language=raw.get('language') or '',
            )
            grading.grade_answer(item, answer)
            answer.save()

        participation.submitted_at = timezone.now()
        participation.save(update_fields=['submitted_at', 'updated_at'])
        grading.recompute_participation(participation)

        return Response({
            'status': participation.status,
            'submitted_at': participation.submitted_at,
            'results_published': stage.results_published,
            'score': (float(participation.effective_score)
                      if stage.results_published else None),
            'max_score': float(participation.max_score or 0),
            'message': (
                'Submitted. Results will be published by the organisers.'
                if not stage.results_published else 'Submitted.'
            ),
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'],
            url_path=r'stages/(?P<stage_id>[^/.]+)/submit-project',
            parser_classes=[MultiPartParser, FormParser, JSONParser])
    def stage_submit_project(self, request, pk=None, stage_id=None):
        """Submit deliverables (files + links) for a ``submission`` round."""
        hackathon = self.get_object()
        ok, payload = self._stage_and_participation(
            hackathon, stage_id, require_open=True,
        )
        if not ok:
            return payload
        stage, _registration, participation = payload

        if stage.stage_type != 'submission':
            return Response({'error': 'This round does not take project submissions.'},
                            status=status.HTTP_400_BAD_REQUEST)

        submission = getattr(participation, 'submission', None)
        if submission and not stage.allow_resubmission:
            return Response({'error': 'You have already submitted for this round.'},
                            status=status.HTTP_400_BAD_REQUEST)

        repo_url = (request.data.get('repo_url') or '').strip()
        demo_url = (request.data.get('demo_url') or '').strip()
        video_url = (request.data.get('video_url') or '').strip()
        for required, value, label in (
            (stage.require_repo_url, repo_url, 'repository URL'),
            (stage.require_demo_url, demo_url, 'demo URL'),
            (stage.require_video_url, video_url, 'video URL'),
        ):
            if required and not value:
                return Response({'error': f'A {label} is required for this round.'},
                                status=status.HTTP_400_BAD_REQUEST)

        files = request.FILES.getlist('files') or (
            [request.FILES['file']] if 'file' in request.FILES else []
        )
        if len(files) > stage.max_files:
            return Response(
                {'error': f'You can upload at most {stage.max_files} file(s).'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        allowed = [str(x).lower().lstrip('.') for x in (stage.allowed_file_types or [])]
        limit_bytes = int(stage.max_file_mb or 50) * 1024 * 1024
        for f in files:
            ext = os.path.splitext(f.name)[1].lower().lstrip('.')
            if allowed and ext not in allowed:
                return Response(
                    {'error': f'"{f.name}" is not an accepted file type. '
                              f'Allowed: {", ".join(allowed)}.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if f.size > limit_bytes:
                return Response(
                    {'error': f'"{f.name}" is larger than {stage.max_file_mb} MB.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        if not files and not (repo_url or demo_url or video_url
                              or (request.data.get('summary') or '').strip()):
            return Response({'error': 'Attach a file or share a link before submitting.'},
                            status=status.HTTP_400_BAD_REQUEST)

        now = timezone.now()
        is_late = bool(stage.ends_at and now > stage.ends_at)
        if submission is None:
            submission = StageSubmission(
                tenant=hackathon.tenant, participation=participation,
            )
        submission.title = (request.data.get('title') or '')[:255]
        submission.summary = (request.data.get('summary') or '')[:20000]
        submission.repo_url = repo_url
        submission.demo_url = demo_url
        submission.video_url = video_url
        submission.submitted_at = now
        submission.is_late = is_late
        submission.save()

        if files:
            submission.files.all().delete()
            for f in files:
                StageSubmissionFile.objects.create(
                    tenant=hackathon.tenant,
                    submission=submission,
                    file=f,
                    original_name=f.name[:255],
                    size_bytes=f.size or 0,
                )

        participation.status = 'submitted'
        participation.submitted_at = now
        participation.needs_manual_grading = True
        participation.max_score = Decimal(str(stage.computed_max_score() or 0))
        participation.save(update_fields=[
            'status', 'submitted_at', 'needs_manual_grading', 'max_score', 'updated_at',
        ])

        return Response(
            {'submission': StageSubmissionSerializer(submission).data,
             'status': participation.status},
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=['post'],
            url_path=r'stages/(?P<stage_id>[^/.]+)/sync-lab')
    def stage_sync_lab(self, request, pk=None, stage_id=None):
        """Pull the participant's latest notebook score into a lab round."""
        hackathon = self.get_object()
        ok, payload = self._stage_and_participation(hackathon, stage_id)
        if not ok:
            return payload
        stage, _registration, participation = payload
        if stage.stage_type != 'lab':
            return Response({'error': 'This round is not a lab.'},
                            status=status.HTTP_400_BAD_REQUEST)
        grading.sync_lab_score(participation)
        return Response({
            'status': participation.status,
            'score': (float(participation.effective_score)
                      if stage.results_published else None),
            'max_score': float(participation.max_score or 0),
        })

    @action(detail=True, methods=['get'],
            url_path=r'submission-files/(?P<file_id>[^/.]+)/download')
    def download_submission_file(self, request, pk=None, file_id=None):
        """Let a participant re-download their own uploaded artefact."""
        hackathon = self.get_object()
        student = self._student()
        if not student:
            raise Http404
        record = StageSubmissionFile.objects.filter(
            id=file_id,
            submission__participation__registration__participant=student,
            submission__participation__stage__hackathon=hackathon,
        ).first()
        if not record or not record.file:
            raise Http404('File not found.')
        return _stream(record)


def _stream(record):
    try:
        fh = record.file.open('rb')
    except Exception:
        raise Http404('File not found.')
    name = record.original_name or os.path.basename(record.file.name)
    content_type = mimetypes.guess_type(name)[0] or 'application/octet-stream'
    response = FileResponse(fh, content_type=content_type)
    response['Content-Disposition'] = f'attachment; filename="{name}"'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'private, no-store'
    return response
