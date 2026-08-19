"""Tenant-admin intelligence routes, mounted at /api/v1/tenant-admin/intelligence/."""
from django.urls import path

from .admin_views import (
    AssessmentReportView, CoursePracticeConfigView, GeneratedItemsView,
    GenerationJobsView, OverviewView, StudentDiagnosisView, TaggingRunView,
)

urlpatterns = [
    path('overview/', OverviewView.as_view(), name='intelligence-overview'),
    path('assessments/<str:kind>/<uuid:assessment_id>/report/',
         AssessmentReportView.as_view(), name='intelligence-assessment-report'),
    path('students/<uuid:student_id>/diagnosis/', StudentDiagnosisView.as_view(),
         name='intelligence-student-diagnosis'),
    path('generated-items/', GeneratedItemsView.as_view(), name='intelligence-generated-items'),
    path('generation-jobs/', GenerationJobsView.as_view(), name='intelligence-generation-jobs'),
    path('tagging/run/', TaggingRunView.as_view(), name='intelligence-tagging-run'),
    path('courses/<uuid:course_id>/practice-config/', CoursePracticeConfigView.as_view(),
         name='intelligence-practice-config'),
]
