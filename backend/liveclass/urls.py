"""URL patterns for the Live Class app."""
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import LiveClassViewSet
from .admin_views import AdminLiveClassViewSet
from .webhooks import ZoomWebhookView

router = DefaultRouter()
router.register(r'classes', LiveClassViewSet, basename='live-class')

admin_router = DefaultRouter()
admin_router.register(r'classes', AdminLiveClassViewSet, basename='admin-live-class')

urlpatterns = [
    # Zoom posts here with no auth and no tenant header (see TENANT_EXEMPT_PATHS).
    # The tenant-scoped form is what the settings screen hands out; the bare one
    # is kept so Zoom apps configured before scoping keep delivering events.
    path('zoom/webhook/<uuid:tenant_id>/', ZoomWebhookView.as_view(),
         name='zoom-webhook-tenant'),
    path('zoom/webhook/', ZoomWebhookView.as_view(), name='zoom-webhook'),
    path('admin/', include(admin_router.urls)),
    path('', include(router.urls)),
]
