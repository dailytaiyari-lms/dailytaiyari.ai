"""Student-facing hackathon serializers.

These never expose authoring internals (correct answers, rubrics, hidden test
cases, admin notes). The admin equivalents live in ``admin_serializers.py``.
"""
from rest_framework import serializers

from .models import (
    Hackathon,
    HackathonRegistration,
    HackathonStage,
    StageParticipation,
    StageSubmission,
    StageSubmissionFile,
)


class HackathonListSerializer(serializers.ModelSerializer):
    """Compact card payload for the public listing grid."""

    thumbnail_url = serializers.SerializerMethodField()
    registration_count = serializers.SerializerMethodField()
    registration_state = serializers.CharField(read_only=True)
    stages_count = serializers.SerializerMethodField()
    is_registered = serializers.SerializerMethodField()

    class Meta:
        model = Hackathon
        fields = [
            'id', 'title', 'slug', 'tagline', 'thumbnail_url', 'theme_color',
            'tags', 'mode', 'location', 'difficulty', 'organizer_name',
            'prize_pool', 'prize_currency', 'registration_opens_at',
            'registration_deadline', 'starts_at', 'ends_at', 'status',
            'registration_state', 'registration_count', 'show_registration_count',
            'stages_count', 'is_registered', 'results_announced', 'created_at',
        ]

    def get_thumbnail_url(self, obj):
        return obj.thumbnail.url if obj.thumbnail else None

    def get_registration_count(self, obj):
        """Hidden entirely when the admin turned the counter off."""
        if not obj.show_registration_count:
            return None
        cached = getattr(obj, 'registrations_total', None)
        if cached is not None:
            return cached
        return obj.registrations.filter(status='registered').count()

    def get_stages_count(self, obj):
        cached = getattr(obj, 'published_stages_total', None)
        if cached is not None:
            return cached
        return obj.stages.filter(status__in=['published', 'completed']).count()

    def get_is_registered(self, obj):
        return str(obj.id) in (self.context.get('registered_ids') or set())


class PublicStageSerializer(serializers.ModelSerializer):
    """A round as an anonymous visitor sees it — timeline and shape only."""

    timing_state = serializers.CharField(read_only=True)
    items_count = serializers.SerializerMethodField()
    total_marks = serializers.SerializerMethodField()

    class Meta:
        model = HackathonStage
        fields = [
            'id', 'order', 'title', 'description', 'stage_type', 'status',
            'starts_at', 'ends_at', 'duration_minutes', 'timing_state',
            'items_count', 'total_marks', 'qualification_mode',
            'results_published', 'max_score',
        ]

    def get_items_count(self, obj):
        if obj.stage_type in ('quiz', 'coding'):
            return obj.items.count()
        return None

    def get_total_marks(self, obj):
        return float(obj.computed_max_score() or 0)


class MyParticipationSerializer(serializers.ModelSerializer):
    """The participant's own state in a round."""

    stage_id = serializers.CharField(source='stage.id', read_only=True)
    stage_title = serializers.CharField(source='stage.title', read_only=True)
    score = serializers.SerializerMethodField()
    percentage = serializers.FloatField(read_only=True)
    results_visible = serializers.SerializerMethodField()

    class Meta:
        model = StageParticipation
        fields = [
            'id', 'stage_id', 'stage_title', 'status', 'qualification',
            'attempt_number', 'started_at', 'submitted_at', 'score',
            'max_score', 'percentage', 'rank', 'feedback', 'results_visible',
        ]

    def get_results_visible(self, obj):
        return bool(obj.stage.results_published)

    def get_score(self, obj):
        # Scores stay hidden until the admin publishes the round's results.
        if not obj.stage.results_published:
            return None
        return float(obj.effective_score)


class MyRegistrationSerializer(serializers.ModelSerializer):
    participations = MyParticipationSerializer(many=True, read_only=True)

    class Meta:
        model = HackathonRegistration
        fields = [
            'id', 'status', 'full_name', 'email', 'phone', 'institution',
            'year_of_study', 'skills', 'github_url', 'linkedin_url',
            'portfolio_url', 'motivation', 'registered_at', 'total_score',
            'final_rank', 'is_winner', 'winner_title', 'prize', 'participations',
        ]
        read_only_fields = [
            'status', 'registered_at', 'total_score', 'final_rank',
            'is_winner', 'winner_title', 'prize',
        ]


class MyRegistrationWithHackathonSerializer(MyRegistrationSerializer):
    hackathon = HackathonListSerializer(read_only=True)

    class Meta(MyRegistrationSerializer.Meta):
        fields = MyRegistrationSerializer.Meta.fields + ['hackathon']


class WinnerSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    avatar = serializers.SerializerMethodField()

    class Meta:
        model = HackathonRegistration
        fields = ['id', 'name', 'avatar', 'final_rank', 'winner_title',
                  'prize', 'total_score', 'institution']

    def get_name(self, obj):
        return obj.full_name or getattr(obj.participant.user, 'full_name', '') or 'Participant'

    def get_avatar(self, obj):
        avatar = getattr(obj.participant.user, 'avatar', None)
        return avatar.url if avatar else None


class HackathonDetailSerializer(HackathonListSerializer):
    """Full public page payload."""

    banner_url = serializers.SerializerMethodField()
    stages = serializers.SerializerMethodField()
    related_courses = serializers.SerializerMethodField()
    winners = serializers.SerializerMethodField()
    my_registration = serializers.SerializerMethodField()

    class Meta(HackathonListSerializer.Meta):
        fields = HackathonListSerializer.Meta.fields + [
            'banner_url', 'description', 'rules', 'prizes_description',
            'eligibility', 'faqs', 'contact_email', 'max_participants',
            'show_leaderboard', 'stages', 'related_courses', 'winners',
            'my_registration', 'views_count', 'results_announced_at',
        ]

    def get_banner_url(self, obj):
        return obj.banner.url if obj.banner else None

    def get_stages(self, obj):
        stages = obj.stages.filter(status__in=['published', 'completed']).order_by(
            'order', 'created_at',
        )
        return PublicStageSerializer(stages, many=True, context=self.context).data

    def get_related_courses(self, obj):
        return [
            {
                'id': str(c.id),
                'name': c.name,
                'thumbnail': c.thumbnail.url if getattr(c, 'thumbnail', None) else None,
            }
            for c in obj.related_courses.all()[:8]
        ]

    def get_winners(self, obj):
        if not obj.results_announced:
            return []
        qs = obj.registrations.filter(is_winner=True).select_related(
            'participant__user',
        ).order_by('final_rank')
        return WinnerSerializer(qs, many=True, context=self.context).data

    def get_my_registration(self, obj):
        registration = self.context.get('my_registration')
        if not registration:
            return None
        return MyRegistrationSerializer(registration, context=self.context).data


class RegisterSerializer(serializers.Serializer):
    """Validated payload for ``POST /hackathons/{id}/register/``."""

    full_name = serializers.CharField(max_length=255)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True)
    institution = serializers.CharField(max_length=255, required=False, allow_blank=True)
    year_of_study = serializers.CharField(max_length=50, required=False, allow_blank=True)
    skills = serializers.ListField(
        child=serializers.CharField(max_length=60), required=False, allow_empty=True,
    )
    github_url = serializers.URLField(required=False, allow_blank=True)
    linkedin_url = serializers.URLField(required=False, allow_blank=True)
    portfolio_url = serializers.URLField(required=False, allow_blank=True)
    motivation = serializers.CharField(required=False, allow_blank=True)


class SubmissionFileSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = StageSubmissionFile
        fields = ['id', 'url', 'original_name', 'size_bytes', 'label', 'created_at']

    def get_url(self, obj):
        return obj.file.url if obj.file else None


class StageSubmissionSerializer(serializers.ModelSerializer):
    files = SubmissionFileSerializer(many=True, read_only=True)

    class Meta:
        model = StageSubmission
        fields = [
            'id', 'title', 'summary', 'repo_url', 'demo_url', 'video_url',
            'submitted_at', 'is_late', 'files',
        ]
