"""URL patterns for the Notebooks app."""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .admin_views import (
    AdminNotebookDatasetViewSet, AdminNotebookSubmissionViewSet,
    AdminNotebookViewSet, NotebookMetaView,
)
from .views import NotebookViewSet

router = DefaultRouter()
router.register(r'notebooks', NotebookViewSet, basename='notebook')

admin_router = DefaultRouter()
admin_router.register(r'notebooks', AdminNotebookViewSet, basename='admin-notebook')
admin_router.register(r'datasets', AdminNotebookDatasetViewSet, basename='admin-notebook-dataset')
admin_router.register(r'submissions', AdminNotebookSubmissionViewSet,
                      basename='admin-notebook-submission')

urlpatterns = [
    path('meta/', NotebookMetaView.as_view(), name='notebook-meta'),
    path('admin/', include(admin_router.urls)),
    path('', include(router.urls)),
]
