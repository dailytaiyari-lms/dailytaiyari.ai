"""Student-facing intelligence routes, mounted at /api/v1/intelligence/."""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import MasteryView, MyAttemptDiagnosisView, MyProgressView, PracticeRefreshView, PracticeSetViewSet, SelfReportView, TimelineSyncView

router = DefaultRouter()
router.register(r'practice/sets', PracticeSetViewSet, basename='practice-sets')

urlpatterns = [
    path('', include(router.urls)),
    path('practice/refresh/', PracticeRefreshView.as_view(), name='practice-refresh'),
    path('mastery/', MasteryView.as_view(), name='intelligence-mastery'),
    path('timeline/', TimelineSyncView.as_view(), name='intelligence-timeline'),
    path('self-report/', SelfReportView.as_view(), name='intelligence-self-report'),
    path('my/progress/', MyProgressView.as_view(), name='intelligence-my-progress'),
    path('my/attempts/<str:kind>/<uuid:attempt_id>/diagnosis/', MyAttemptDiagnosisView.as_view(),
         name='intelligence-my-attempt-diagnosis'),
]
