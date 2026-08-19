"""
URL configuration for DailyTaiyari project.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi

# API Documentation Schema
schema_view = get_schema_view(
    openapi.Info(
        title="DailyTaiyari API",
        default_version='v1',
        description="API for DailyTaiyari - India's Premier Course Preparation Platform",
        terms_of_service="https://dailytaiyari.ai/terms/",
        contact=openapi.Contact(email="support@dailytaiyari.ai"),
        license=openapi.License(name="Proprietary"),
    ),
    public=True,
    permission_classes=[permissions.AllowAny],
)

urlpatterns = [
    # Admin
    path('admin/', admin.site.urls),
    
    # API v1 endpoints
    path('api/v1/tenant/<uuid:pk>/', __import__('core.views').views.TenantDetailView.as_view(), name='tenant-detail'),
    path('api/v1/platform/', include('core.urls')),
    path('api/v1/superadmin/', include('core.superadmin_urls')),
    path('api/v1/landing/', include('core.landing_urls')),
    path('api/v1/tenant-admin/', include('core.admin_urls')),
    path('api/v1/tenant-admin/ai/', include('chatbot.admin_urls')),
    path('api/v1/tenant-admin/course-ai/', include('coursegen.urls')),
    path('api/v1/tenant-admin/mock-ai/', include('mockgen.urls')),
    path('api/v1/auth/', include('users.urls')),
    path('api/v1/courses/', include('exams.urls')),
    path('api/v1/content/', include('content.urls')),
    path('api/v1/quiz/', include('quiz.urls')),
    path('api/v1/analytics/', include('analytics.urls')),
    path('api/v1/gamification/', include('gamification.urls')),
    path('api/v1/chatbot/', include('chatbot.urls')),
    path('api/v1/community/', include('community.urls')),
    path('api/v1/assignments/', include('assignments.urls')),
    path('api/v1/coding/', include('coding.urls')),
    path('api/v1/live-classes/', include('liveclass.urls')),
    path('api/v1/jobs/', include('jobs.urls')),
    path('api/v1/certificates/', include('certificates.urls')),
    path('api/v1/payments/', include('payments.urls')),
    path('api/v1/marketing/', include('marketing.urls')),
    path('api/v1/notifications/', include('notifications.urls')),
    path('api/v1/notebooks/', include('notebooks.urls')),
    path('api/v1/intelligence/', include('intelligence.urls')),
    path('api/v1/tenant-admin/intelligence/', include('intelligence.admin_urls')),
    
    # API Documentation
    path('api/docs/', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),
    path('api/redoc/', schema_view.with_ui('redoc', cache_timeout=0), name='schema-redoc'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

