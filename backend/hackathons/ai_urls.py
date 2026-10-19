"""URL patterns for the AI Hackathon Studio (mounted at /api/v1/tenant-admin/hackathon-ai/)."""
from django.urls import path

from .ai_views import (
    JobApplyView,
    JobDetailView,
    JobDiscardView,
    JobListCreateView,
    JobRefineView,
    JobRegenerateView,
    StagesForHackathonView,
    StudioOptionsView,
    studio_health,
)

urlpatterns = [
    path('options/', StudioOptionsView.as_view(), name='hackathonai-options'),
    path('health/', studio_health, name='hackathonai-health'),
    path(
        'hackathons/<uuid:hackathon_id>/stages/',
        StagesForHackathonView.as_view(), name='hackathonai-stages',
    ),
    path('jobs/', JobListCreateView.as_view(), name='hackathonai-jobs'),
    path('jobs/<uuid:job_id>/', JobDetailView.as_view(), name='hackathonai-job-detail'),
    path('jobs/<uuid:job_id>/refine/', JobRefineView.as_view(), name='hackathonai-job-refine'),
    path(
        'jobs/<uuid:job_id>/regenerate/',
        JobRegenerateView.as_view(), name='hackathonai-job-regenerate',
    ),
    path('jobs/<uuid:job_id>/apply/', JobApplyView.as_view(), name='hackathonai-job-apply'),
    path(
        'jobs/<uuid:job_id>/discard/',
        JobDiscardView.as_view(), name='hackathonai-job-discard',
    ),
]
