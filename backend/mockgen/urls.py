"""URL patterns for the AI Mock Test Builder (mounted at /api/v1/tenant-admin/mock-ai/)."""
from django.urls import path

from .views import (
    CourseSyllabusView,
    JobApplyView,
    JobDetailView,
    JobDiscardView,
    JobListCreateView,
    JobRefineView,
    JobRegenerateView,
    MockTestSnapshotView,
    StudioOptionsView,
    studio_health,
)

urlpatterns = [
    path('options/', StudioOptionsView.as_view(), name='mockgen-options'),
    path('health/', studio_health, name='mockgen-health'),
    path(
        'courses/<uuid:course_id>/syllabus/',
        CourseSyllabusView.as_view(), name='mockgen-course-syllabus',
    ),
    path(
        'mock-tests/<uuid:mock_test_id>/snapshot/',
        MockTestSnapshotView.as_view(), name='mockgen-mock-snapshot',
    ),
    path('jobs/', JobListCreateView.as_view(), name='mockgen-jobs'),
    path('jobs/<uuid:job_id>/', JobDetailView.as_view(), name='mockgen-job-detail'),
    path('jobs/<uuid:job_id>/refine/', JobRefineView.as_view(), name='mockgen-job-refine'),
    path(
        'jobs/<uuid:job_id>/regenerate/',
        JobRegenerateView.as_view(), name='mockgen-job-regenerate',
    ),
    path('jobs/<uuid:job_id>/apply/', JobApplyView.as_view(), name='mockgen-job-apply'),
    path('jobs/<uuid:job_id>/discard/', JobDiscardView.as_view(), name='mockgen-job-discard'),
]
