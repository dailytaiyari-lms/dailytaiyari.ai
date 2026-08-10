from django.contrib import admin

from .models import (
    Notebook, NotebookCompletion, NotebookDataset, NotebookDraft,
    NotebookGenerationJob, NotebookSubmission, NotebookTest,
)


class NotebookTestInline(admin.TabularInline):
    model = NotebookTest
    extra = 0


class NotebookDatasetInline(admin.TabularInline):
    model = NotebookDataset
    extra = 0


@admin.register(Notebook)
class NotebookAdmin(admin.ModelAdmin):
    list_display = ['title', 'course', 'topic', 'difficulty', 'status', 'max_marks', 'due_at']
    list_filter = ['status', 'difficulty', 'is_timed', 'course']
    search_fields = ['title']
    inlines = [NotebookTestInline, NotebookDatasetInline]


@admin.register(NotebookSubmission)
class NotebookSubmissionAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'notebook', 'student', 'attempt_number', 'status',
        'passed_points', 'total_points', 'marks', 'submitted_at',
    ]
    list_filter = ['status', 'is_late']
    search_fields = ['notebook__title']
    readonly_fields = ['results', 'provisional_results', 'notebook_json', 'submitted_at']


@admin.register(NotebookCompletion)
class NotebookCompletionAdmin(admin.ModelAdmin):
    list_display = [
        'notebook', 'student', 'best_passed_points', 'best_total_points',
        'attempts_used', 'is_complete', 'completed_at',
    ]
    list_filter = ['is_complete']
    search_fields = ['notebook__title']


@admin.register(NotebookDraft)
class NotebookDraftAdmin(admin.ModelAdmin):
    list_display = ['notebook', 'student', 'time_spent_seconds', 'updated_at']
    search_fields = ['notebook__title']
    readonly_fields = ['notebook_json']


@admin.register(NotebookGenerationJob)
class NotebookGenerationJobAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'topic', 'status', 'provider', 'model', 'total_tokens',
        'created_by', 'created_at',
    ]
    list_filter = ['status', 'kind']
    search_fields = ['prompt', 'topic__name', 'course__name']
    readonly_fields = ['draft', 'revisions', 'applied_summary', 'created_at', 'updated_at']
