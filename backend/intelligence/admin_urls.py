"""Tenant-admin intelligence routes, mounted at /api/v1/tenant-admin/intelligence/."""
from django.urls import path

from .admin_views import CoursePracticeConfigView, TaggingRunView

urlpatterns = [
    path('tagging/run/', TaggingRunView.as_view(), name='intelligence-tagging-run'),
    path('courses/<uuid:course_id>/practice-config/', CoursePracticeConfigView.as_view(),
         name='intelligence-practice-config'),
]
