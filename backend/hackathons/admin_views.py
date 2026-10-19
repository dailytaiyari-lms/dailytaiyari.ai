"""
Tenant-admin hackathon management API.

Covers the whole admin journey: author the event, build its rounds and their
questions, watch registrations come in, review and grade submissions, decide who
advances (by cut-off, top-N or by hand), broadcast updates, and finally declare
winners. Every write is tenant-scoped through ``_tenant()``.
"""
import csv
import logging
import mimetypes
import os
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponse
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from core.permissions import IsTenantAdmin

from . import grading, notify
from .admin_serializers import (
    AdminAnnouncementSerializer,
    AdminHackathonSerializer,
    AdminParticipationDetailSerializer,
    AdminParticipationSerializer,
    AdminRegistrationSerializer,
    AdminStageDetailSerializer,
    AdminStageItemSerializer,
    AdminStageSerializer,
    GradeParticipationSerializer,
    QualifySerializer,
    WinnerDeclarationSerializer,
)
from .models import (
    Hackathon,
    HackathonRegistration,
    HackathonStage,
    HackathonStageItem,
    StageParticipation,
    StageSubmissionFile,
)

logger = logging.getLogger(__name__)


class HackathonsPagination(PageNumberPagination):
    page_size = 100
    page_size_query_param = 'page_size'
    max_page_size = 1000


class TenantScopedAdminViewSet(viewsets.ModelViewSet):
    permission_classes = [IsTenantAdmin]
    pagination_class = HackathonsPagination
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def _tenant(self):
        return getattr(self.request, 'tenant', None)


class AdminHackathonViewSet(TenantScopedAdminViewSet):
    """Full CRUD over hackathons plus the event-level operations."""

    serializer_class = AdminHackathonSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['title', 'tagline', 'organizer_name']
    ordering_fields = ['created_at', 'title', 'status', 'starts_at', 'registration_deadline']
    ordering = ['-created_at']
    filterset_fields = ['status', 'mode', 'difficulty']

    def get_queryset(self):
        tenant = self._tenant()
        if not tenant:
            return Hackathon.objects.none()
        return (
            Hackathon.objects.filter(tenant=tenant)
            .prefetch_related('related_courses')
            .annotate(
                registrations_total=Count(
                    'registrations', filter=Q(registrations__status='registered'),
                    distinct=True,
                ),
            )
        )

    def perform_create(self, serializer):
        tenant = self._tenant()
        if not tenant:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('A valid tenant is required.')
        serializer.save(tenant=tenant, created_by=self.request.user)

    # -- stages -----------------------------------------------------------
    @action(detail=True, methods=['get', 'post'])
    def stages(self, request, pk=None):
        hackathon = self.get_object()
        if request.method == 'GET':
            qs = hackathon.stages.all().order_by('order', 'created_at')
            return Response(
                AdminStageSerializer(
                    qs, many=True, context={'request': request, 'with_stats': True},
                ).data
            )

        serializer = AdminStageSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        last = hackathon.stages.order_by('-order').first()
        serializer.save(
            tenant=hackathon.tenant,
            hackathon=hackathon,
            order=(last.order + 1) if last else 0,
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='stages/reorder')
    def reorder_stages(self, request, pk=None):
        hackathon = self.get_object()
        ids = request.data.get('ids') or []
        stages = {str(s.id): s for s in hackathon.stages.all()}
        updated = []
        for index, sid in enumerate(ids):
            stage = stages.get(str(sid))
            if stage and stage.order != index:
                stage.order = index
                updated.append(stage)
        if updated:
            HackathonStage.objects.bulk_update(updated, ['order'])
        qs = hackathon.stages.all().order_by('order', 'created_at')
        return Response(AdminStageSerializer(qs, many=True).data)

    # -- registrations ----------------------------------------------------
    @action(detail=True, methods=['get'])
    def registrations(self, request, pk=None):
        hackathon = self.get_object()
        qs = (
            hackathon.registrations
            .select_related('participant__user')
            .prefetch_related('participations')
            .order_by('-registered_at')
        )
        search = (request.query_params.get('search') or '').strip()
        if search:
            qs = qs.filter(
                Q(full_name__icontains=search)
                | Q(email__icontains=search)
                | Q(institution__icontains=search)
            )
        state = request.query_params.get('status')
        if state in dict(HackathonRegistration.STATUS_CHOICES):
            qs = qs.filter(status=state)

        return Response({
            'hackathon': {'id': str(hackathon.id), 'title': hackathon.title},
            'total': qs.count(),
            'counts': {
                'registered': hackathon.registrations.filter(status='registered').count(),
                'withdrawn': hackathon.registrations.filter(status='withdrawn').count(),
                'disqualified': hackathon.registrations.filter(status='disqualified').count(),
            },
            'registrations': AdminRegistrationSerializer(qs, many=True).data,
        })

    @action(detail=True, methods=['get'], url_path='registrations/export')
    def export_registrations(self, request, pk=None):
        hackathon = self.get_object()
        response = HttpResponse(content_type='text/csv')
        slug = hackathon.slug or 'hackathon'
        response['Content-Disposition'] = f'attachment; filename="{slug}-registrations.csv"'
        writer = csv.writer(response)
        writer.writerow([
            'Name', 'Email', 'Phone', 'Institution', 'Year', 'Skills',
            'GitHub', 'LinkedIn', 'Portfolio', 'Status', 'Registered at',
            'Total score', 'Final rank', 'Winner',
        ])
        for r in hackathon.registrations.select_related('participant__user'):
            writer.writerow([
                r.full_name, r.email, r.phone, r.institution, r.year_of_study,
                ', '.join(r.skills or []), r.github_url, r.linkedin_url,
                r.portfolio_url, r.status,
                r.registered_at.strftime('%Y-%m-%d %H:%M') if r.registered_at else '',
                r.total_score, r.final_rank or '', 'Yes' if r.is_winner else '',
            ])
        return response

    @action(detail=True, methods=['patch'], url_path=r'registrations/(?P<reg_id>[^/.]+)')
    def update_registration(self, request, pk=None, reg_id=None):
        hackathon = self.get_object()
        registration = hackathon.registrations.filter(id=reg_id).first()
        if not registration:
            raise Http404('Registration not found.')
        for field in ('status', 'admin_notes', 'winner_title', 'prize'):
            if field in request.data:
                setattr(registration, field, request.data[field])
        registration.save()
        return Response(AdminRegistrationSerializer(registration).data)

    # -- results ----------------------------------------------------------
    @action(detail=True, methods=['get'])
    def overview(self, request, pk=None):
        """Everything the admin dashboard header needs in one call."""
        hackathon = self.get_object()
        registrations = hackathon.registrations.filter(status='registered')
        stages = list(hackathon.stages.all().order_by('order', 'created_at'))
        return Response({
            'registrations_total': registrations.count(),
            'withdrawn': hackathon.registrations.filter(status='withdrawn').count(),
            'views': hackathon.views_count,
            'stages_total': len(stages),
            'stages_published': sum(1 for s in stages if s.status == 'published'),
            'pending_review': StageParticipation.objects.filter(
                stage__hackathon=hackathon, needs_manual_grading=True,
            ).count(),
            'results_announced': hackathon.results_announced,
            'winners': hackathon.registrations.filter(is_winner=True).count(),
            'stages': [
                {'id': str(s.id), 'title': s.title, 'order': s.order,
                 'stage_type': s.stage_type, 'status': s.status,
                 'results_published': s.results_published,
                 **grading.stage_stats(s)}
                for s in stages
            ],
        })

    @action(detail=True, methods=['post'], url_path='declare-winners')
    def declare_winners(self, request, pk=None):
        hackathon = self.get_object()
        serializer = WinnerDeclarationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        grading.recompute_totals(hackathon)

        with transaction.atomic():
            hackathon.registrations.update(is_winner=False, winner_title='', prize='')
            winners = []
            for entry in data['winners']:
                registration = hackathon.registrations.filter(
                    id=entry['registration_id'],
                ).first()
                if not registration:
                    continue
                registration.is_winner = True
                registration.final_rank = entry['rank']
                registration.winner_title = entry.get('title') or f"Rank {entry['rank']}"
                registration.prize = entry.get('prize') or ''
                registration.save(update_fields=[
                    'is_winner', 'final_rank', 'winner_title', 'prize', 'updated_at',
                ])
                winners.append(registration)

            if data.get('announce'):
                hackathon.results_announced = True
                hackathon.results_announced_at = timezone.now()
                hackathon.status = 'completed'
                hackathon.save(update_fields=[
                    'results_announced', 'results_announced_at', 'status', 'updated_at',
                ])

        if data.get('announce'):
            notify.on_winners_declared(hackathon, winners)
            if data.get('notify_all'):
                others = hackathon.registrations.filter(
                    status='registered',
                ).exclude(id__in=[w.id for w in winners]).select_related(
                    'participant__user',
                )
                notify.on_results_announced(hackathon, others)

        return Response({
            'winners': AdminRegistrationSerializer(winners, many=True).data,
            'results_announced': hackathon.results_announced,
        })

    @action(detail=True, methods=['get', 'post'])
    def announcements(self, request, pk=None):
        hackathon = self.get_object()
        if request.method == 'GET':
            qs = hackathon.announcements.all()
            return Response(AdminAnnouncementSerializer(qs, many=True).data)

        serializer = AdminAnnouncementSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        announcement = serializer.save(
            tenant=hackathon.tenant, hackathon=hackathon, created_by=request.user,
        )

        recipients = self._announcement_recipients(hackathon, announcement)
        count = notify.send_announcement(announcement, recipients) or 0
        announcement.sent_at = timezone.now()
        announcement.recipients_count = count
        announcement.save(update_fields=['sent_at', 'recipients_count', 'updated_at'])
        return Response(
            AdminAnnouncementSerializer(announcement).data,
            status=status.HTTP_201_CREATED,
        )

    @staticmethod
    def _announcement_recipients(hackathon, announcement):
        qs = hackathon.registrations.filter(status='registered').select_related(
            'participant__user',
        )
        if announcement.audience == 'winners':
            return list(qs.filter(is_winner=True))
        if announcement.audience == 'qualified' and announcement.stage_id:
            ids = StageParticipation.objects.filter(
                stage_id=announcement.stage_id, qualification='qualified',
            ).values_list('registration_id', flat=True)
            return list(qs.filter(id__in=ids))
        if announcement.audience == 'active':
            last_decided = (
                HackathonStage.objects
                .filter(hackathon=hackathon, results_published=True)
                .order_by('-order').first()
            )
            if last_decided:
                ids = StageParticipation.objects.filter(
                    stage=last_decided, qualification='qualified',
                ).values_list('registration_id', flat=True)
                return list(qs.filter(id__in=ids))
        return list(qs)


class AdminStageViewSet(TenantScopedAdminViewSet):
    """CRUD for rounds plus grading + progression actions."""

    serializer_class = AdminStageSerializer

    def get_queryset(self):
        tenant = self._tenant()
        if not tenant:
            return HackathonStage.objects.none()
        qs = HackathonStage.objects.filter(hackathon__tenant=tenant).select_related(
            'hackathon', 'notebook',
        )
        hackathon_id = self.request.query_params.get('hackathon')
        if hackathon_id:
            qs = qs.filter(hackathon_id=hackathon_id)
        return qs.order_by('order', 'created_at')

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return AdminStageDetailSerializer
        return AdminStageSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['with_stats'] = self.action in ('retrieve', 'list')
        return context

    def perform_update(self, serializer):
        previous_status = serializer.instance.status
        stage = serializer.save()
        # Publishing a round for the first time notifies whoever can enter it.
        if previous_status != 'published' and stage.status == 'published':
            self._open_round(stage)

    def _open_round(self, stage):
        prev = grading.previous_stage(stage)
        if prev is None:
            registrations = list(
                stage.hackathon.registrations.filter(status='registered')
                .select_related('participant__user')
            )
        else:
            ids = StageParticipation.objects.filter(
                stage=prev, qualification='qualified',
            ).values_list('registration_id', flat=True)
            registrations = list(
                HackathonRegistration.objects.filter(id__in=ids)
                .select_related('participant__user')
            )
        grading.open_next_stage(stage, registrations)
        notify.on_stage_opened(stage, registrations)

    # -- items ------------------------------------------------------------
    @action(detail=True, methods=['get', 'post'])
    def items(self, request, pk=None):
        stage = self.get_object()
        if request.method == 'GET':
            qs = stage.items.all().order_by('order', 'created_at')
            return Response(AdminStageItemSerializer(qs, many=True).data)

        payload = dict(request.data)
        payload.pop('stage', None)
        serializer = AdminStageItemSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        last = stage.items.order_by('-order').first()
        serializer.save(
            tenant=stage.hackathon.tenant,
            stage=stage,
            order=(last.order + 1) if last else 0,
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='items/reorder')
    def reorder_items(self, request, pk=None):
        stage = self.get_object()
        ids = request.data.get('ids') or []
        items = {str(i.id): i for i in stage.items.all()}
        updated = []
        for index, iid in enumerate(ids):
            item = items.get(str(iid))
            if item and item.order != index:
                item.order = index
                updated.append(item)
        if updated:
            HackathonStageItem.objects.bulk_update(updated, ['order'])
        qs = stage.items.all().order_by('order', 'created_at')
        return Response(AdminStageItemSerializer(qs, many=True).data)

    # -- participants -----------------------------------------------------
    @action(detail=True, methods=['get'])
    def participants(self, request, pk=None):
        stage = self.get_object()
        qs = (
            stage.participations
            .select_related('registration', 'registration__participant__user')
            .order_by('-score', 'submitted_at')
        )
        state = request.query_params.get('status')
        if state:
            qs = qs.filter(status=state)
        qualification = request.query_params.get('qualification')
        if qualification:
            qs = qs.filter(qualification=qualification)
        search = (request.query_params.get('search') or '').strip()
        if search:
            qs = qs.filter(
                Q(registration__full_name__icontains=search)
                | Q(registration__email__icontains=search)
            )
        return Response({
            'stage': AdminStageSerializer(
                stage, context={'request': request, 'with_stats': True},
            ).data,
            'stats': grading.stage_stats(stage),
            'suggested_qualifiers': [
                str(i) for i in grading.compute_qualifiers(stage)
            ],
            'participants': AdminParticipationSerializer(qs, many=True).data,
        })

    @action(detail=True, methods=['post'])
    def qualify(self, request, pk=None):
        """Decide who advances — by the stage rule or by an explicit pick."""
        stage = self.get_object()
        serializer = QualifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        pending = stage.participations.filter(needs_manual_grading=True).count()
        if pending and not request.data.get('force'):
            return Response(
                {'error': f'{pending} submission(s) still need review. '
                          'Grade them first, or resend with force=true.',
                 'code': 'pending_review', 'pending': pending},
                status=status.HTTP_400_BAD_REQUEST,
            )

        qualified_ids = (
            data.get('participation_ids') if data['mode'] == 'manual' else None
        )
        result = grading.apply_qualification(
            stage,
            qualified_ids=qualified_ids,
            publish_results=data['publish_results'],
            actor=request.user,
        )

        if data['notify'] and data['publish_results']:
            notify.on_stage_results(
                stage,
                result.pop('qualified_participations', []),
                result.pop('rejected_participations', []),
            )
        result.pop('qualified_participations', None)
        result.pop('rejected_participations', None)

        grading.recompute_totals(stage.hackathon)
        return Response(result)

    @action(detail=True, methods=['post'], url_path='publish-results')
    def publish_results(self, request, pk=None):
        """Make scores visible without deciding qualification yet."""
        stage = self.get_object()
        if not stage.results_published:
            stage.results_published = True
            stage.results_published_at = timezone.now()
            stage.save(update_fields=[
                'results_published', 'results_published_at', 'updated_at',
            ])
        return Response(AdminStageSerializer(stage).data)

    @action(detail=True, methods=['get'])
    def leaderboard(self, request, pk=None):
        stage = self.get_object()
        return Response({'entries': grading.leaderboard(stage.hackathon, stage=stage)})


class AdminStageItemViewSet(TenantScopedAdminViewSet):
    """Edit or remove a single question. Creation happens on the stage."""

    serializer_class = AdminStageItemSerializer
    http_method_names = ['get', 'patch', 'put', 'delete', 'head', 'options']

    def get_queryset(self):
        tenant = self._tenant()
        if not tenant:
            return HackathonStageItem.objects.none()
        return HackathonStageItem.objects.filter(
            stage__hackathon__tenant=tenant,
        ).select_related('stage')


class AdminParticipationViewSet(viewsets.ReadOnlyModelViewSet):

    permission_classes = [IsTenantAdmin]
    pagination_class = HackathonsPagination
    serializer_class = AdminParticipationDetailSerializer

    def _tenant(self):
        return getattr(self.request, 'tenant', None)

    def get_queryset(self):
        tenant = self._tenant()
        if not tenant:
            return StageParticipation.objects.none()
        return (
            StageParticipation.objects
            .filter(stage__hackathon__tenant=tenant)
            .select_related('stage', 'registration', 'registration__participant__user')
            .prefetch_related('answers__item', 'submission__files')
        )

    @action(detail=True, methods=['post'])
    def grade(self, request, pk=None):
        """Apply manual marks / feedback and re-total the round."""
        participation = self.get_object()
        serializer = GradeParticipationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        answer_marks = data.get('answer_marks') or {}
        answer_feedback = data.get('answer_feedback') or {}
        if answer_marks or answer_feedback:
            answers = {
                str(a.id): a for a in participation.answers.select_related('item')
            }
            touched = []
            for answer_id, marks in answer_marks.items():
                answer = answers.get(str(answer_id))
                if not answer:
                    continue
                answer.marks_obtained = min(
                    Decimal(str(marks)), Decimal(str(answer.max_marks or marks)),
                )
                answer.needs_manual_grading = False
                answer.is_correct = answer.marks_obtained > 0
                answer.graded_by = request.user
                touched.append(answer)
            for answer_id, feedback in answer_feedback.items():
                answer = answers.get(str(answer_id))
                if answer:
                    answer.feedback = feedback
                    if answer not in touched:
                        touched.append(answer)
            for answer in touched:
                answer.save(update_fields=[
                    'marks_obtained', 'needs_manual_grading', 'is_correct',
                    'graded_by', 'feedback', 'updated_at',
                ])
            grading.recompute_participation(participation)

        if 'override_score' in data:
            participation.override_score = data['override_score']
        if 'feedback' in data:
            participation.feedback = data['feedback']
        participation.needs_manual_grading = participation.answers.filter(
            needs_manual_grading=True,
        ).exists()
        participation.status = 'evaluated'
        participation.evaluated_at = timezone.now()
        participation.evaluated_by = request.user
        participation.save(update_fields=[
            'override_score', 'feedback', 'needs_manual_grading', 'status',
            'evaluated_at', 'evaluated_by', 'updated_at',
        ])
        return Response(
            AdminParticipationDetailSerializer(
                participation, context={'request': request},
            ).data
        )


class AdminSubmissionFileViewSet(viewsets.GenericViewSet):
    """Streams a participant's uploaded artefact to a reviewing admin."""

    permission_classes = [IsTenantAdmin]

    def get_queryset(self):
        tenant = getattr(self.request, 'tenant', None)
        if not tenant:
            return StageSubmissionFile.objects.none()
        return StageSubmissionFile.objects.filter(
            submission__participation__stage__hackathon__tenant=tenant,
        )

    @action(detail=True, methods=['get'])
    def download(self, request, pk=None):
        record = self.get_queryset().filter(id=pk).first()
        if not record or not record.file:
            raise Http404('File not found.')
        try:
            fh = record.file.open('rb')
        except Exception:
            raise Http404('File not found.')
        name = record.original_name or os.path.basename(record.file.name)
        content_type = mimetypes.guess_type(name)[0] or 'application/octet-stream'
        response = FileResponse(fh, content_type=content_type)
        disposition = 'inline' if content_type in (
            'application/pdf', 'video/mp4', 'image/png', 'image/jpeg',
        ) else 'attachment'
        response['Content-Disposition'] = f'{disposition}; filename="{name}"'
        response['X-Content-Type-Options'] = 'nosniff'
        response['Cache-Control'] = 'private, no-store'
        return response
