from django.contrib import admin

from .models import (
    Hackathon,
    HackathonAnnouncement,
    HackathonGenerationJob,
    HackathonRegistration,
    HackathonStage,
    HackathonStageItem,
    StageItemAnswer,
    StageParticipation,
    StageSubmission,
    StageSubmissionFile,
)


class HackathonStageInline(admin.TabularInline):
    model = HackathonStage
    extra = 0
    fields = ('order', 'title', 'stage_type', 'status', 'starts_at', 'ends_at',
              'qualification_mode', 'results_published')
    ordering = ('order',)
    show_change_link = True


@admin.register(Hackathon)
class HackathonAdmin(admin.ModelAdmin):
    list_display = ('title', 'status', 'mode', 'starts_at', 'registration_deadline',
                    'results_announced', 'tenant')
    list_filter = ('status', 'mode', 'difficulty', 'results_announced', 'tenant')
    search_fields = ('title', 'tagline', 'organizer_name')
    filter_horizontal = ('related_courses',)
    readonly_fields = ('slug', 'views_count', 'created_at', 'updated_at')
    inlines = [HackathonStageInline]


class HackathonStageItemInline(admin.TabularInline):
    model = HackathonStageItem
    extra = 0
    fields = ('order', 'item_type', 'title', 'marks', 'negative_marks')
    ordering = ('order',)
    show_change_link = True


@admin.register(HackathonStage)
class HackathonStageAdmin(admin.ModelAdmin):
    list_display = ('title', 'hackathon', 'order', 'stage_type', 'status',
                    'qualification_mode', 'results_published')
    list_filter = ('stage_type', 'status', 'qualification_mode', 'results_published')
    search_fields = ('title', 'hackathon__title')
    inlines = [HackathonStageItemInline]


@admin.register(HackathonStageItem)
class HackathonStageItemAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'stage', 'item_type', 'order', 'marks')
    list_filter = ('item_type',)
    search_fields = ('title', 'question_text', 'stage__title')


class StageParticipationInline(admin.TabularInline):
    model = StageParticipation
    extra = 0
    fields = ('stage', 'status', 'qualification', 'score', 'max_score', 'rank')
    readonly_fields = fields
    can_delete = False


@admin.register(HackathonRegistration)
class HackathonRegistrationAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'email', 'hackathon', 'status', 'total_score',
                    'final_rank', 'is_winner', 'registered_at')
    list_filter = ('status', 'is_winner', 'hackathon')
    search_fields = ('full_name', 'email', 'institution', 'hackathon__title')
    inlines = [StageParticipationInline]


@admin.register(StageParticipation)
class StageParticipationAdmin(admin.ModelAdmin):
    list_display = ('registration', 'stage', 'status', 'qualification', 'score',
                    'needs_manual_grading', 'rank')
    list_filter = ('status', 'qualification', 'needs_manual_grading')
    search_fields = ('registration__full_name', 'registration__email', 'stage__title')


@admin.register(StageItemAnswer)
class StageItemAnswerAdmin(admin.ModelAdmin):
    list_display = ('participation', 'item', 'is_correct', 'marks_obtained',
                    'needs_manual_grading')
    list_filter = ('is_correct', 'needs_manual_grading', 'is_auto_graded')


class StageSubmissionFileInline(admin.TabularInline):
    model = StageSubmissionFile
    extra = 0


@admin.register(StageSubmission)
class StageSubmissionAdmin(admin.ModelAdmin):
    list_display = ('participation', 'title', 'submitted_at', 'is_late')
    list_filter = ('is_late',)
    inlines = [StageSubmissionFileInline]


@admin.register(HackathonAnnouncement)
class HackathonAnnouncementAdmin(admin.ModelAdmin):
    list_display = ('title', 'hackathon', 'audience', 'sent_at', 'recipients_count')
    list_filter = ('audience', 'send_email')
    search_fields = ('title', 'hackathon__title')


@admin.register(HackathonGenerationJob)
class HackathonGenerationJobAdmin(admin.ModelAdmin):
    list_display = ('kind', 'status', 'hackathon', 'model', 'total_tokens', 'created_at')
    list_filter = ('kind', 'status', 'provider')
    readonly_fields = ('draft', 'revisions', 'applied_summary')
