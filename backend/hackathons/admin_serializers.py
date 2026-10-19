"""Admin-facing hackathon serializers (tenant admin portal)."""
from rest_framework import serializers

from core.serializer_fields import Base64ImageField

from .models import (
    Hackathon,
    HackathonAnnouncement,
    HackathonGenerationJob,
    HackathonStage,
    HackathonStageItem,
    HackathonRegistration,
    StageItemAnswer,
    StageParticipation,
    StageSubmission,
    StageSubmissionFile,
)


class AdminHackathonSerializer(serializers.ModelSerializer):
    thumbnail = Base64ImageField(required=False, allow_null=True)
    banner = Base64ImageField(required=False, allow_null=True)
    thumbnail_url = serializers.SerializerMethodField()
    banner_url = serializers.SerializerMethodField()

    registrations_count = serializers.SerializerMethodField()
    stages_count = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    related_course_ids = serializers.ListField(
        child=serializers.UUIDField(), write_only=True, required=False,
    )
    related_courses = serializers.SerializerMethodField()
    registration_state = serializers.CharField(read_only=True)

    class Meta:
        model = Hackathon
        fields = [
            'id', 'title', 'slug', 'tagline', 'thumbnail', 'banner',
            'thumbnail_url', 'banner_url', 'theme_color', 'description',
            'rules', 'prizes_description', 'eligibility', 'faqs', 'tags',
            'mode', 'location', 'difficulty', 'organizer_name', 'contact_email',
            'prize_pool', 'prize_currency', 'registration_opens_at',
            'registration_deadline', 'starts_at', 'ends_at', 'max_participants',
            'show_registration_count', 'show_leaderboard', 'email_notifications',
            'status', 'results_announced', 'results_announced_at',
            'registration_state', 'registrations_count', 'stages_count',
            'related_courses', 'related_course_ids', 'created_by_name',
            'views_count', 'created_at', 'updated_at',
        ]
        read_only_fields = ['slug', 'results_announced', 'results_announced_at',
                            'views_count', 'created_at', 'updated_at']

    def get_thumbnail_url(self, obj):
        return obj.thumbnail.url if obj.thumbnail else None

    def get_banner_url(self, obj):
        return obj.banner.url if obj.banner else None

    def get_registrations_count(self, obj):
        return obj.registrations.filter(status='registered').count()

    def get_stages_count(self, obj):
        return obj.stages.count()

    def get_created_by_name(self, obj):
        return getattr(obj.created_by, 'full_name', '') if obj.created_by else ''

    def get_related_courses(self, obj):
        return [{'id': str(c.id), 'name': c.name} for c in obj.related_courses.all()]

    def _apply_courses(self, instance, course_ids):
        from exams.models import Course
        courses = Course.objects.filter(
            id__in=course_ids, tenant=instance.tenant,
        )
        instance.related_courses.set(courses)

    def create(self, validated_data):
        course_ids = validated_data.pop('related_course_ids', None)
        instance = super().create(validated_data)
        if course_ids is not None:
            self._apply_courses(instance, course_ids)
        return instance

    def update(self, instance, validated_data):
        course_ids = validated_data.pop('related_course_ids', None)
        instance = super().update(instance, validated_data)
        if course_ids is not None:
            self._apply_courses(instance, course_ids)
        return instance


class AdminStageItemSerializer(serializers.ModelSerializer):
    question_image = Base64ImageField(required=False, allow_null=True)
    question_image_url = serializers.SerializerMethodField()

    class Meta:
        model = HackathonStageItem
        fields = [
            'id', 'stage', 'item_type', 'order', 'title', 'question_text',
            'question_html', 'question_image', 'question_image_url',
            'explanation', 'difficulty', 'marks', 'negative_marks', 'options',
            'numerical_answer', 'numerical_tolerance', 'max_words', 'rubric',
            'model_answer', 'allowed_languages', 'starter_code', 'time_limit_ms',
            'memory_limit_mb', 'coding_test_cases', 'created_at',
        ]
        read_only_fields = ['created_at']

    def get_question_image_url(self, obj):
        return obj.question_image.url if obj.question_image else None

    def validate(self, attrs):
        item_type = attrs.get('item_type') or getattr(self.instance, 'item_type', 'mcq')
        options = attrs.get('options', getattr(self.instance, 'options', None)) or []
        if item_type in ('mcq', 'mcq_multi'):
            if len(options) < 2:
                raise serializers.ValidationError(
                    {'options': 'Add at least two options.'})
            if not any(o.get('is_correct') for o in options):
                raise serializers.ValidationError(
                    {'options': 'Mark at least one option as correct.'})
            if item_type == 'mcq' and sum(1 for o in options if o.get('is_correct')) > 1:
                raise serializers.ValidationError(
                    {'options': 'A single-choice question can only have one correct option.'})
        if item_type == 'numerical':
            answer = attrs.get('numerical_answer',
                               getattr(self.instance, 'numerical_answer', None))
            if answer is None:
                raise serializers.ValidationError(
                    {'numerical_answer': 'Provide the correct numeric answer.'})
        if item_type == 'coding':
            cases = attrs.get('coding_test_cases',
                              getattr(self.instance, 'coding_test_cases', None)) or []
            if not cases:
                raise serializers.ValidationError(
                    {'coding_test_cases': 'Add at least one test case.'})
            langs = attrs.get('allowed_languages',
                              getattr(self.instance, 'allowed_languages', None)) or []
            if not langs:
                raise serializers.ValidationError(
                    {'allowed_languages': 'Pick at least one language.'})
        return attrs


class AdminStageSerializer(serializers.ModelSerializer):
    items_count = serializers.SerializerMethodField()
    total_marks = serializers.SerializerMethodField()
    stats = serializers.SerializerMethodField()
    notebook_title = serializers.SerializerMethodField()
    timing_state = serializers.CharField(read_only=True)

    class Meta:
        model = HackathonStage
        fields = [
            'id', 'hackathon', 'order', 'title', 'description', 'instructions',
            'stage_type', 'status', 'starts_at', 'ends_at', 'duration_minutes',
            'shuffle_items', 'max_attempts', 'notebook', 'notebook_title',
            'submission_instructions', 'allowed_file_types', 'max_file_mb',
            'max_files', 'require_repo_url', 'require_demo_url',
            'require_video_url', 'allow_resubmission', 'max_score',
            'qualification_mode', 'cutoff_score', 'top_n', 'results_published',
            'results_published_at', 'timing_state', 'items_count', 'total_marks',
            'stats', 'created_at', 'updated_at',
        ]
        read_only_fields = ['hackathon', 'results_published_at',
                            'created_at', 'updated_at']

    def get_items_count(self, obj):
        return obj.items.count()

    def get_total_marks(self, obj):
        return float(obj.computed_max_score() or 0)

    def get_notebook_title(self, obj):
        return getattr(obj.notebook, 'title', '') if obj.notebook_id else ''

    def get_stats(self, obj):
        if not self.context.get('with_stats'):
            return None
        from .grading import stage_stats
        return stage_stats(obj)

    def validate(self, attrs):
        mode = attrs.get('qualification_mode') or getattr(
            self.instance, 'qualification_mode', 'manual')
        if mode == 'cutoff':
            cutoff = attrs.get('cutoff_score', getattr(self.instance, 'cutoff_score', None))
            if cutoff is None:
                raise serializers.ValidationError(
                    {'cutoff_score': 'Set the qualifying score for a cut-off round.'})
        if mode == 'top_n':
            top_n = attrs.get('top_n', getattr(self.instance, 'top_n', None))
            if not top_n:
                raise serializers.ValidationError(
                    {'top_n': 'Set how many participants advance.'})
        stage_type = attrs.get('stage_type') or getattr(self.instance, 'stage_type', 'quiz')
        if stage_type == 'lab':
            notebook = attrs.get('notebook', getattr(self.instance, 'notebook', None))
            status = attrs.get('status') or getattr(self.instance, 'status', 'draft')
            if status == 'published' and not notebook:
                raise serializers.ValidationError(
                    {'notebook': 'Pick the lab notebook before publishing this round.'})
        return attrs


class AdminStageDetailSerializer(AdminStageSerializer):
    items = AdminStageItemSerializer(many=True, read_only=True)

    class Meta(AdminStageSerializer.Meta):
        fields = AdminStageSerializer.Meta.fields + ['items']


class AdminSubmissionFileSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = StageSubmissionFile
        fields = ['id', 'url', 'download_url', 'original_name', 'size_bytes',
                  'label', 'created_at']

    def get_url(self, obj):
        return obj.file.url if obj.file else None

    def get_download_url(self, obj):
        return f'/api/v1/hackathons/admin/submission-files/{obj.id}/download/'


class AdminSubmissionSerializer(serializers.ModelSerializer):
    files = AdminSubmissionFileSerializer(many=True, read_only=True)

    class Meta:
        model = StageSubmission
        fields = ['id', 'title', 'summary', 'repo_url', 'demo_url', 'video_url',
                  'submitted_at', 'is_late', 'files']


class AdminItemAnswerSerializer(serializers.ModelSerializer):
    item = AdminStageItemSerializer(read_only=True)

    class Meta:
        model = StageItemAnswer
        fields = [
            'id', 'item', 'selected_options', 'numerical_answer', 'answer_text',
            'code', 'language', 'coding_results', 'passed_count', 'total_count',
            'is_correct', 'is_auto_graded', 'needs_manual_grading',
            'marks_obtained', 'max_marks', 'feedback',
        ]
        read_only_fields = ['item', 'is_auto_graded', 'passed_count', 'total_count']


class AdminParticipationSerializer(serializers.ModelSerializer):
    participant_name = serializers.SerializerMethodField()
    participant_email = serializers.SerializerMethodField()
    institution = serializers.CharField(source='registration.institution', read_only=True)
    registration_id = serializers.CharField(source='registration.id', read_only=True)
    effective_score = serializers.SerializerMethodField()
    percentage = serializers.FloatField(read_only=True)
    has_submission = serializers.SerializerMethodField()

    class Meta:
        model = StageParticipation
        fields = [
            'id', 'registration_id', 'participant_name', 'participant_email',
            'institution', 'status', 'qualification', 'attempt_number',
            'started_at', 'submitted_at', 'evaluated_at', 'score', 'auto_score',
            'override_score', 'effective_score', 'max_score', 'percentage',
            'needs_manual_grading', 'rank', 'feedback', 'has_submission',
        ]
        read_only_fields = ['score', 'auto_score', 'max_score', 'attempt_number']

    def get_participant_name(self, obj):
        return obj.registration.full_name or ''

    def get_participant_email(self, obj):
        return obj.registration.email or ''

    def get_effective_score(self, obj):
        return float(obj.effective_score)

    def get_has_submission(self, obj):
        return hasattr(obj, 'submission')


class AdminParticipationDetailSerializer(AdminParticipationSerializer):
    answers = AdminItemAnswerSerializer(many=True, read_only=True)
    submission = AdminSubmissionSerializer(read_only=True)
    stage_type = serializers.CharField(source='stage.stage_type', read_only=True)
    stage_title = serializers.CharField(source='stage.title', read_only=True)

    class Meta(AdminParticipationSerializer.Meta):
        fields = AdminParticipationSerializer.Meta.fields + [
            'answers', 'submission', 'stage_type', 'stage_title',
        ]


class AdminRegistrationSerializer(serializers.ModelSerializer):
    participant_name = serializers.SerializerMethodField()
    participant_email = serializers.SerializerMethodField()
    avatar = serializers.SerializerMethodField()
    stage_summary = serializers.SerializerMethodField()

    class Meta:
        model = HackathonRegistration
        fields = [
            'id', 'participant_name', 'participant_email', 'avatar', 'full_name',
            'email', 'phone', 'institution', 'year_of_study', 'skills',
            'github_url', 'linkedin_url', 'portfolio_url', 'motivation',
            'status', 'registered_at', 'total_score', 'final_rank', 'is_winner',
            'winner_title', 'prize', 'admin_notes', 'stage_summary',
        ]
        read_only_fields = ['registered_at', 'total_score']

    def get_participant_name(self, obj):
        return obj.full_name or getattr(obj.participant.user, 'full_name', '')

    def get_participant_email(self, obj):
        return obj.email or getattr(obj.participant.user, 'email', '')

    def get_avatar(self, obj):
        avatar = getattr(obj.participant.user, 'avatar', None)
        return avatar.url if avatar else None

    def get_stage_summary(self, obj):
        return [
            {
                'stage_id': str(p.stage_id),
                'status': p.status,
                'qualification': p.qualification,
                'score': float(p.effective_score),
                'max_score': float(p.max_score or 0),
            }
            for p in obj.participations.all()
        ]


class AdminAnnouncementSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = HackathonAnnouncement
        fields = ['id', 'hackathon', 'stage', 'title', 'body', 'audience',
                  'send_email', 'sent_at', 'recipients_count',
                  'created_by_name', 'created_at']
        read_only_fields = ['hackathon', 'sent_at', 'recipients_count', 'created_at']

    def get_created_by_name(self, obj):
        return getattr(obj.created_by, 'full_name', '') if obj.created_by else ''


class WinnerDeclarationSerializer(serializers.Serializer):
    """Payload for ``POST /admin/hackathons/{id}/declare-winners/``."""

    class _Winner(serializers.Serializer):
        registration_id = serializers.UUIDField()
        rank = serializers.IntegerField(min_value=1)
        title = serializers.CharField(max_length=150, required=False, allow_blank=True)
        prize = serializers.CharField(max_length=255, required=False, allow_blank=True)

    winners = _Winner(many=True)
    announce = serializers.BooleanField(default=True)
    notify_all = serializers.BooleanField(default=True)


class QualifySerializer(serializers.Serializer):
    """Payload for ``POST /admin/stages/{id}/qualify/``."""

    mode = serializers.ChoiceField(
        choices=['auto', 'manual'], default='auto',
        help_text="'auto' applies the stage rule; 'manual' uses participation_ids.",
    )
    participation_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_empty=True,
    )
    publish_results = serializers.BooleanField(default=True)
    notify = serializers.BooleanField(default=True)


class GradeParticipationSerializer(serializers.Serializer):
    """Payload for manually scoring a participation."""

    override_score = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, allow_null=True,
    )
    feedback = serializers.CharField(required=False, allow_blank=True)
    answer_marks = serializers.DictField(
        child=serializers.DecimalField(max_digits=8, decimal_places=2),
        required=False,
        help_text='{answer_id: marks} for subjective answers.',
    )
    answer_feedback = serializers.DictField(
        child=serializers.CharField(allow_blank=True), required=False,
    )


class AdminGenerationJobSerializer(serializers.ModelSerializer):
    summary = serializers.SerializerMethodField()
    can_apply = serializers.BooleanField(read_only=True)
    is_running = serializers.BooleanField(read_only=True)

    class Meta:
        model = HackathonGenerationJob
        fields = [
            'id', 'hackathon', 'stage', 'kind', 'prompt', 'options', 'provider',
            'model', 'status', 'draft', 'revisions', 'error', 'summary',
            'can_apply', 'is_running', 'prompt_tokens', 'completion_tokens',
            'total_tokens', 'estimated_cost_usd', 'generation_ms', 'applied_at',
            'applied_summary', 'created_at',
        ]
        read_only_fields = fields
