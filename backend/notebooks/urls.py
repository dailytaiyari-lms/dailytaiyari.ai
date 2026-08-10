"""URL patterns for the Notebooks app."""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .admin_views import (
    AdminNotebookDatasetViewSet, AdminNotebookSubmissionViewSet,
    AdminNotebookViewSet, NotebookMetaView,
)
from .aigen.views import (
    JobApplyView, JobDetailView, JobDiscardView, JobListCreateView,
    JobRefineView, JobRegenerateView, OptionsView,
)
from .views import NotebookViewSet

router = DefaultRouter()
router.register(r'notebooks', NotebookViewSet, basename='notebook')

admin_router = DefaultRouter()
admin_router.register(r'notebooks', AdminNotebookViewSet, basename='admin-notebook')
admin_router.register(r'datasets', AdminNotebookDatasetViewSet, basename='admin-notebook-dataset')
admin_router.register(r'submissions', AdminNotebookSubmissionViewSet,
                      basename='admin-notebook-submission')

# AI Notebook Builder ("Notebook Studio"): generation runs in the background and
# the client polls the job. Writing a real notebook only happens on apply/.
generate_patterns = [
    path('options/', OptionsView.as_view(), name='notebookgen-options'),
    path('jobs/', JobListCreateView.as_view(), name='notebookgen-jobs'),
    path('jobs/<uuid:job_id>/', JobDetailView.as_view(), name='notebookgen-job-detail'),
    path('jobs/<uuid:job_id>/refine/', JobRefineView.as_view(), name='notebookgen-job-refine'),
    path('jobs/<uuid:job_id>/regenerate/', JobRegenerateView.as_view(), name='notebookgen-job-regenerate'),
    path('jobs/<uuid:job_id>/apply/', JobApplyView.as_view(), name='notebookgen-job-apply'),
    path('jobs/<uuid:job_id>/discard/', JobDiscardView.as_view(), name='notebookgen-job-discard'),
]

urlpatterns = [
    path('meta/', NotebookMetaView.as_view(), name='notebook-meta'),
    path('admin/generate/', include(generate_patterns)),
    path('admin/', include(admin_router.urls)),
    path('', include(router.urls)),
]
