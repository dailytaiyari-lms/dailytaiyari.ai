from django.contrib import admin

from .models import MockTestGenerationJob


@admin.register(MockTestGenerationJob)
class MockTestGenerationJobAdmin(admin.ModelAdmin):
    list_display = (
        'kind', 'status', 'tenant', 'mock_test', 'model', 'total_tokens', 'created_at',
    )
    list_filter = ('kind', 'status', 'provider')
    search_fields = ('prompt', 'mock_test__title', 'model')
    readonly_fields = (
        'draft', 'revisions', 'applied_summary', 'prompt_tokens',
        'completion_tokens', 'total_tokens', 'estimated_cost_usd', 'generation_ms',
    )
    date_hierarchy = 'created_at'
