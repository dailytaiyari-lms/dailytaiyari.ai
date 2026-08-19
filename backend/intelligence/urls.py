"""Student-facing intelligence routes, mounted at /api/v1/intelligence/."""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import MasteryView, PracticeRefreshView, PracticeSetViewSet

router = DefaultRouter()
router.register(r'practice/sets', PracticeSetViewSet, basename='practice-sets')

urlpatterns = [
    path('', include(router.urls)),
    path('practice/refresh/', PracticeRefreshView.as_view(), name='practice-refresh'),
    path('mastery/', MasteryView.as_view(), name='intelligence-mastery'),
]
