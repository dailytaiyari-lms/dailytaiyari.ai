"""Tenant-admin intelligence routes, mounted at /api/v1/tenant-admin/intelligence/."""
from django.urls import include, path

from .admin_views import (
    AssessmentBehaviourView, AssessmentReportView, CourseBehaviourView, StudentAnswersView, CoursePracticeConfigView, GeneratedItemsView,
    DiagnosisCalibrationView, GenerationJobsView, OverviewView, StudentDiagnosisView, TaggingRunView,
    CourseHeatmapView, StudentProgressView,
)

urlpatterns = [
    path('overview/', OverviewView.as_view(), name='intelligence-overview'),
    path('assessments/<str:kind>/<uuid:assessment_id>/report/',
         AssessmentReportView.as_view(), name='intelligence-assessment-report'),
    path('assessments/<str:kind>/<uuid:assessment_id>/behaviour/',
         AssessmentBehaviourView.as_view(), name='intelligence-assessment-behaviour'),
    path('students/<uuid:student_id>/answers/', StudentAnswersView.as_view(),
         name='intelligence-student-answers'),
    path('students/<uuid:student_id>/diagnosis/', StudentDiagnosisView.as_view(),
         name='intelligence-student-diagnosis'),
    path('generated-items/', GeneratedItemsView.as_view(), name='intelligence-generated-items'),
    path('generation-jobs/', GenerationJobsView.as_view(), name='intelligence-generation-jobs'),
    path('tagging/run/', TaggingRunView.as_view(), name='intelligence-tagging-run'),
    path('courses/<uuid:course_id>/practice-config/', CoursePracticeConfigView.as_view(),
         name='intelligence-practice-config'),
    path('courses/<uuid:course_id>/behaviour/', CourseBehaviourView.as_view(),
         name='intelligence-course-behaviour'),
    path('diagnosis/calibration/', DiagnosisCalibrationView.as_view(),
         name='intelligence-diagnosis-calibration'),
    path('students/<uuid:student_id>/progress/', StudentProgressView.as_view(),
         name='intelligence-student-progress'),
    path('courses/<uuid:course_id>/heatmap/', CourseHeatmapView.as_view(),
         name='intelligence-course-heatmap'),
    path('syllabus/', include('intelligence.syllabus_urls')),
]
