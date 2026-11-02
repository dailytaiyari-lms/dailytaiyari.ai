"""
URL patterns for user authentication and profile.
"""
from django.urls import path, include

from rest_framework_simplejwt.views import TokenRefreshView
from .views import (
    CustomTokenObtainPairView,
    RegisterView,
    VerifyEmailView,
    ResendOTPView,
    GuardianConsentView,
    GuardianConsentStatusView,
    ResendGuardianConsentView,
    ExistingStudentComplianceView,
    PasswordResetRequestView,
    PasswordResetConfirmView,
    PasswordChangeView,
    ProfileView,
    UserView,
    OnboardingView,
    CourseEnrollmentListView,
    CourseEnrollmentDetailView,
    TenantStudentViewSet,
    TenantEnrollmentRequestViewSet,
)
from rest_framework.routers import DefaultRouter

router = DefaultRouter()
router.register(r'tenant-students', TenantStudentViewSet, basename='tenant-students')
router.register(r'enrollment-requests', TenantEnrollmentRequestViewSet, basename='enrollment-requests')


urlpatterns = [
    # Authentication
    path('login/', CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('register/', RegisterView.as_view(), name='register'),
    path('verify-email/', VerifyEmailView.as_view(), name='verify-email'),
    path('resend-otp/', ResendOTPView.as_view(), name='resend-otp'),
    path('guardian-consent/status/', GuardianConsentStatusView.as_view(), name='guardian-consent-status'),
    path('guardian-consent/resend/', ResendGuardianConsentView.as_view(), name='guardian-consent-resend'),
    path('guardian-consent/<str:token>/', GuardianConsentView.as_view(), name='guardian-consent'),
    path('compliance-status/', ExistingStudentComplianceView.as_view(), name='compliance-status'),
    path('password/forgot/', PasswordResetRequestView.as_view(), name='password-forgot'),
    path('password/reset/', PasswordResetConfirmView.as_view(), name='password-reset'),
    path('password/change/', PasswordChangeView.as_view(), name='password-change'),
    
    # User & Profile
    path('user/', UserView.as_view(), name='user'),
    path('profile/', ProfileView.as_view(), name='profile'),
    path('onboarding/', OnboardingView.as_view(), name='onboarding'),
    
    # Course Enrollments
    path('enrollments/', CourseEnrollmentListView.as_view(), name='enrollment-list'),
    path('enrollments/<uuid:pk>/', CourseEnrollmentDetailView.as_view(), name='enrollment-detail'),

    # Tenant Management
    path('', include(router.urls)),
]
