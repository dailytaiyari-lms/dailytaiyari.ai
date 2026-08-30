from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .admin_views import (
    AdminHackathonViewSet,
    AdminParticipationViewSet,
    AdminStageItemViewSet,
    AdminStageViewSet,
    AdminSubmissionFileViewSet,
)
from .views import HackathonViewSet

router = DefaultRouter()
router.register(r'', HackathonViewSet, basename='hackathon')

admin_router = DefaultRouter()
admin_router.register(r'hackathons', AdminHackathonViewSet, basename='admin-hackathon')
admin_router.register(r'stages', AdminStageViewSet, basename='admin-hackathon-stage')
admin_router.register(r'items', AdminStageItemViewSet, basename='admin-hackathon-item')
admin_router.register(
    r'participations', AdminParticipationViewSet, basename='admin-hackathon-participation',
)
admin_router.register(
    r'submission-files', AdminSubmissionFileViewSet,
    basename='admin-hackathon-submission-file',
)

urlpatterns = [
    # /api/v1/hackathons/admin/...
    path('admin/', include(admin_router.urls)),
    # /api/v1/hackathons/...
    path('', include(router.urls)),
]
