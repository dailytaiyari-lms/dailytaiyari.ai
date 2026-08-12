"""
Views for user authentication and profile management.
"""
import logging

from rest_framework import status, generics, permissions, filters
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework_simplejwt.views import TokenObtainPairView
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db import transaction

from .models import StudentProfile, CourseEnrollment
from .serializers import (
    CustomTokenObtainPairSerializer,
    UserRegistrationSerializer,
    UserSerializer,
    StudentProfileSerializer,
    CourseEnrollmentSerializer,
    AdminEnrollmentRequestSerializer,
    AdminStudentCreateSerializer,
    AdminAssignCourseSerializer,
    OnboardingSerializer,
    EmailOTPRequestSerializer,
    EmailOTPVerifySerializer,
    PasswordResetConfirmSerializer,
    PasswordChangeSerializer,
)
from .emails import create_and_send_otp, verify_otp, can_resend, generate_temp_password
from exams.models import Course
from core.permissions import IsTenantAdmin
from core.views import TenantAwareViewSet, TenantAwareReadOnlyViewSet


User = get_user_model()

logger = logging.getLogger(__name__)


class StudentRecordsPagination(PageNumberPagination):
    """
    Pagination for the tenant admin student-records view.

    Defaults to a high page size so admins can search/filter/export across
    the whole institution, while still allowing an explicit ?page_size=
    override (capped) for clients that want true pagination.
    """
    page_size = 100
    page_size_query_param = 'page_size'
    max_page_size = 5000


class CustomTokenObtainPairView(TokenObtainPairView):
    """Custom JWT token view with extra user data."""
    serializer_class = CustomTokenObtainPairSerializer


class RegisterView(generics.CreateAPIView):
    """User registration endpoint."""
    queryset = User.objects.all()
    permission_classes = [permissions.AllowAny]
    serializer_class = UserRegistrationSerializer

    def create(self, request, *args, **kwargs):
        if not hasattr(request, 'tenant') or not request.tenant:
            return Response(
                {'error': 'A valid Tenant is required to register.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not request.tenant.can_add('students'):
            return Response(
                {'error': 'This academy has reached its student capacity. '
                          'Please contact the DailyTaiyari team.',
                 'code': 'quota_exceeded'},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save(tenant=request.tenant)

        # Kick off email verification.
        try:
            create_and_send_otp(user, purpose='email_verification')
        except Exception:
            # Don't fail registration if the mail transport hiccups; the
            # user can request a fresh code via the resend endpoint.
            pass

        return Response({
            'message': 'Registration successful. Please check your email for a verification code.',
            'requires_email_verification': True,
            'user': UserSerializer(user).data
        }, status=status.HTTP_201_CREATED)


class VerifyEmailView(APIView):
    """Verify a user's email using the OTP sent to their inbox."""
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            return Response({'error': 'A valid Tenant is required.'},
                            status=status.HTTP_400_BAD_REQUEST)

        serializer = EmailOTPVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']
        code = serializer.validated_data['code']

        try:
            user = User.objects.get(email=email, tenant=tenant)
        except User.DoesNotExist:
            return Response({'error': 'Invalid code.'},
                            status=status.HTTP_400_BAD_REQUEST)

        if user.is_email_verified:
            return Response({'message': 'Email already verified.'})

        ok, error = verify_otp(user, code, purpose='email_verification')
        if not ok:
            return Response({'error': error}, status=status.HTTP_400_BAD_REQUEST)

        user.is_email_verified = True
        user.email_verified_at = timezone.now()
        user.save(update_fields=['is_email_verified', 'email_verified_at'])

        return Response({
            'message': 'Email verified successfully.',
            'user': UserSerializer(user).data,
        })


class ResendOTPView(APIView):
    """Re-send an email verification code (rate-limited)."""
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            return Response({'error': 'A valid Tenant is required.'},
                            status=status.HTTP_400_BAD_REQUEST)

        serializer = EmailOTPRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']

        # Generic response regardless of whether the user exists, so this
        # endpoint can't be used to enumerate registered emails.
        generic = Response({
            'message': 'If an unverified account exists for that email, a new code has been sent.'
        })

        try:
            user = User.objects.get(email=email, tenant=tenant)
        except User.DoesNotExist:
            return generic

        if user.is_email_verified:
            return generic
        if not can_resend(user, purpose='email_verification'):
            return Response(
                {'error': 'Please wait a moment before requesting another code.'},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        try:
            create_and_send_otp(user, purpose='email_verification')
        except Exception:
            return Response(
                {'error': 'Could not send the verification email. Please try again shortly.'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return generic


class PasswordResetRequestView(APIView):
    """Send a password-reset code to a registered email (rate-limited)."""
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            return Response({'error': 'A valid Tenant is required.'},
                            status=status.HTTP_400_BAD_REQUEST)

        serializer = EmailOTPRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']

        generic = Response({
            'message': 'If an account exists for that email, a reset code has been sent.'
        })

        try:
            user = User.objects.get(email=email, tenant=tenant)
        except User.DoesNotExist:
            return generic

        if not can_resend(user, purpose='password_reset'):
            return Response(
                {'error': 'Please wait a moment before requesting another code.'},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        try:
            create_and_send_otp(user, purpose='password_reset')
        except Exception:
            return Response(
                {'error': 'Could not send the reset email. Please try again shortly.'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return generic


class PasswordResetConfirmView(APIView):
    """Verify a reset code and set a new password."""
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            return Response({'error': 'A valid Tenant is required.'},
                            status=status.HTTP_400_BAD_REQUEST)

        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']
        code = serializer.validated_data['code']
        new_password = serializer.validated_data['new_password']

        try:
            user = User.objects.get(email=email, tenant=tenant)
        except User.DoesNotExist:
            return Response({'error': 'Invalid code.'},
                            status=status.HTTP_400_BAD_REQUEST)

        ok, error = verify_otp(user, code, purpose='password_reset')
        if not ok:
            return Response({'error': error}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(new_password)
        # A successful reset also proves ownership of the mailbox.
        if not user.is_email_verified:
            user.is_email_verified = True
            user.email_verified_at = timezone.now()
            user.save(update_fields=['password', 'is_email_verified', 'email_verified_at'])
        else:
            user.save(update_fields=['password'])

        return Response({'message': 'Password reset successful. You can now sign in.'})


class PasswordChangeView(APIView):
    """Change the password for the authenticated user."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = PasswordChangeSerializer(
            data=request.data, context={'request': request}
        )
        serializer.is_valid(raise_exception=True)

        user = request.user
        user.set_password(serializer.validated_data['new_password'])
        user.save(update_fields=['password'])

        return Response({'message': 'Password changed successfully.'})


class ProfileView(generics.RetrieveUpdateAPIView):
    """Get and update user profile."""
    serializer_class = StudentProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user.profile


class UserView(generics.RetrieveUpdateAPIView):
    """Get and update user data."""
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user


class OnboardingView(APIView):
    """Complete user onboarding — saves study goals only.

    Course selection/enrollment is intentionally NOT part of onboarding.
    After onboarding, students request enrollment from the Courses tab
    (creating a pending CourseEnrollment that an admin approves).
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = OnboardingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user = request.user
        profile = user.profile

        # Update profile goals
        profile.target_year = data.get('target_year')
        profile.daily_study_goal_minutes = data['daily_study_goal_minutes']
        profile.preferred_study_time = data['preferred_study_time']
        profile.save()

        # Mark user as onboarded
        user.is_onboarded = True
        user.onboarded_at = timezone.now()
        user.save()

        return Response({
            'message': 'Onboarding completed successfully',
            'profile': StudentProfileSerializer(profile).data
        })


class CourseEnrollmentListView(generics.ListCreateAPIView):
    """List enrollment requests and request enrollment in an course (pending admin approval)."""
    serializer_class = CourseEnrollmentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return CourseEnrollment.objects.filter(
            student=self.request.user.profile
        ).select_related('course').order_by('-created_at')

    def create(self, request, *args, **kwargs):
        student = request.user.profile
        course_id = request.data.get('course')
        tenant = getattr(request, 'tenant', None)

        from exams.models import Course
        course = Course.objects.filter(id=course_id, tenant=tenant).first() if course_id else None
        if course is None:
            return Response(
                {'course': ['Course not found.']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Resolve how this student may join the course given the tenant's flags.
        mode = tenant.enroll_mode_for(course) if tenant else 'request'
        if mode == 'payment':
            # Paid, pay-to-enrol: the client must go through the payment flow.
            return Response(
                {'detail': 'This course requires payment to enrol.',
                 'code': 'payment_required'},
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )
        # 'self' → auto-approve (free course, request flow disabled); else pending.
        target_status = 'approved' if mode == 'self' else 'pending'

        existing = CourseEnrollment.objects.filter(student=student, course=course).first()
        if existing:
            if existing.status == 'rejected':
                # Allow re-request after rejection: reopen (or self-enrol).
                existing.status = target_status
                existing.is_active = True
                existing.rejection_reason = ''
                existing.reviewed_at = timezone.now() if target_status == 'approved' else None
                existing.reviewed_by = None
                existing.save()
                if target_status == 'pending':
                    self._notify_enrollment_requested(existing)
                return Response(self.get_serializer(existing).data, status=status.HTTP_200_OK)
            return Response(
                {'course': ['You have already requested or are enrolled in this course.']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        enrollment = CourseEnrollment.objects.create(
            student=student, course=course, status=target_status, is_active=True,
            reviewed_at=timezone.now() if target_status == 'approved' else None,
        )
        if target_status == 'pending':
            self._notify_enrollment_requested(enrollment)
        return Response(self.get_serializer(enrollment).data, status=status.HTTP_201_CREATED)

    @staticmethod
    def _notify_enrollment_requested(enrollment):
        """Alert tenant admins about a new pending request (best-effort)."""
        try:
            from notifications import services as notification_services
            notification_services.on_enrollment_requested(enrollment)
        except Exception:  # noqa: BLE001 - never block enrolment on a notify error
            logger.exception('Failed to notify admins of enrollment request %s', enrollment.id)

    def perform_create(self, serializer):
        serializer.save(student=self.request.user.profile, status='pending', is_active=True)


class CourseEnrollmentDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Manage individual course enrollment."""
    serializer_class = CourseEnrollmentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return CourseEnrollment.objects.filter(student=self.request.user.profile)


class TenantStudentViewSet(TenantAwareViewSet):
    """
    Manage student profiles for the current tenant.
    Only accessible by tenant admins.
    """
    queryset = StudentProfile.objects.all()
    serializer_class = StudentProfileSerializer
    permission_classes = [permissions.IsAuthenticated, IsTenantAdmin]
    pagination_class = StudentRecordsPagination
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = [
        'user__email', 'user__first_name', 'user__last_name', 'user__phone',
        'school', 'coaching', 'city', 'state',
    ]
    ordering_fields = [
        'user__first_name', 'user__email', 'total_xp', 'current_level',
        'total_questions_attempted', 'created_at',
    ]
    ordering = ['user__first_name']

    def get_queryset(self):
        tenant = self.request.tenant
        qs = StudentProfile.objects.filter(user__tenant=tenant).select_related('user').prefetch_related('enrollments__course')

        # Optional explicit filters (used by the admin dashboard).
        role = self.request.query_params.get('role')
        if role:
            qs = qs.filter(user__role=role)

        status_param = self.request.query_params.get('status')
        if status_param == 'active':
            qs = qs.filter(user__is_suspended=False)
        elif status_param == 'suspended':
            qs = qs.filter(user__is_suspended=True)

        # Filter by any course the student is enrolled in (non-rejected).
        # unique_together(student, course) means one enrollment per pair, so the
        # exclude below targets exactly the matched course's enrollment.
        course = self.request.query_params.get('course') or self.request.query_params.get('primary_course')
        if course:
            qs = qs.filter(
                enrollments__course_id=course,
            ).exclude(
                enrollments__course_id=course,
                enrollments__status='rejected',
            ).distinct()

        return qs

    def get_serializer_class(self):
        if self.action == 'create':
            return AdminStudentCreateSerializer
        return super().get_serializer_class()

    @staticmethod
    def _assign_courses(profile, courses, admin_user, notify_student=True):
        """Enrol ``profile`` in each course, approving immediately.

        Existing enrollments are upgraded to approved (covers pending requests
        and previously rejected ones). Returns the list of enrollments that were
        newly granted access, so callers only email about real changes.
        """
        granted = []
        for course in courses:
            enrollment, created = CourseEnrollment.objects.get_or_create(
                student=profile, course=course,
                defaults={
                    'status': 'approved',
                    'is_active': True,
                    'reviewed_at': timezone.now(),
                    'reviewed_by': admin_user,
                },
            )
            if created:
                granted.append(enrollment)
                continue
            if enrollment.status != 'approved' or not enrollment.is_active:
                enrollment.status = 'approved'
                enrollment.is_active = True
                enrollment.rejection_reason = ''
                enrollment.reviewed_at = timezone.now()
                enrollment.reviewed_by = admin_user
                enrollment.save()
                granted.append(enrollment)
        if notify_student:
            from notifications import services as notification_services
            for enrollment in granted:
                try:
                    notification_services.on_course_assigned(enrollment)
                except Exception:  # noqa: BLE001 - never fail the enrolment
                    logger.exception('Failed to notify student of course assignment %s', enrollment.id)
        return granted

    def create(self, request, *args, **kwargs):
        """Create a student (or faculty) account with a generated password.

        The password is generated server-side, emailed to the user, and never
        returned to the admin unless the email could not be delivered.
        """
        tenant = getattr(request, 'tenant', None)
        if tenant is None:
            return Response(
                {'detail': 'A valid Tenant is required to perform this action.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = AdminStudentCreateSerializer(
            data=request.data, context={'request': request, 'tenant': tenant},
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        role = data.get('role') or 'student'
        quota_resource = 'students' if role == 'student' else None
        if quota_resource and not tenant.can_add(quota_resource):
            limit = tenant.quota_limits().get(quota_resource)
            return Response(
                {'detail': f'Student limit reached for your plan ({limit}). '
                           'Upgrade your plan to add more students.',
                 'code': 'quota_exceeded'},
                status=status.HTTP_403_FORBIDDEN,
            )

        courses = list(Course.objects.filter(id__in=data.get('course_ids') or [], tenant=tenant))
        temp_password = generate_temp_password()

        with transaction.atomic():
            user = User.objects.create_user(
                email=data['email'],
                tenant=tenant,
                password=temp_password,
                first_name=data['first_name'],
                last_name=data.get('last_name') or '',
                phone=data.get('phone') or '',
                role=role,
                # Admin-provisioned accounts are trusted: skip the OTP wall so
                # the student can sign in with the emailed credentials directly.
                is_email_verified=True,
                email_verified_at=timezone.now(),
            )
            # The post_save signal creates the profile.
            profile = StudentProfile.objects.get(user=user)
            profile_updates = serializer.profile_updates()
            if profile_updates:
                for field, value in profile_updates.items():
                    setattr(profile, field, value)
                profile.save(update_fields=list(profile_updates.keys()) + ['updated_at'])

            # Courses are assigned inside the transaction, but the assignment
            # email is suppressed — the welcome email already lists them.
            self._assign_courses(profile, courses, request.user, notify_student=False)

        email_sent = False
        if data.get('send_email', True):
            try:
                from notifications import services as notification_services
                email_sent = notification_services.on_student_account_created(
                    user, temp_password, courses=courses,
                )
            except Exception:  # noqa: BLE001 - account creation must still succeed
                logger.exception('Failed to send welcome email to %s', user.email)

        profile.refresh_from_db()
        payload = StudentProfileSerializer(profile).data
        payload['email_sent'] = email_sent
        # Surface the password only when the admin can't rely on the email.
        if not email_sent:
            payload['temporary_password'] = temp_password
        return Response(payload, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='assign-courses')
    def assign_courses(self, request, pk=None):
        """Enrol an existing student in one or more courses and notify them."""
        profile = self.get_object()
        tenant = request.tenant
        serializer = AdminAssignCourseSerializer(
            data=request.data, context={'request': request, 'tenant': tenant},
        )
        serializer.is_valid(raise_exception=True)

        courses = list(Course.objects.filter(
            id__in=serializer.validated_data['course_ids'], tenant=tenant,
        ))
        send_email = serializer.validated_data.get('send_email', True)

        with transaction.atomic():
            granted = self._assign_courses(profile, courses, request.user, notify_student=False)

        if send_email:
            from notifications import services as notification_services
            for enrollment in granted:
                try:
                    notification_services.on_course_assigned(enrollment)
                except Exception:  # noqa: BLE001
                    logger.exception('Failed to notify student of course assignment %s', enrollment.id)

        profile.refresh_from_db()
        return Response({
            'assigned': [
                {'course_id': str(e.course_id), 'course_name': e.course.name}
                for e in granted
            ],
            'already_enrolled': [
                str(c.id) for c in courses
                if all(str(c.id) != str(e.course_id) for e in granted)
            ],
            'student': StudentProfileSerializer(profile).data,
        })

    @action(detail=True, methods=['post'], url_path='remove-course')
    def remove_course(self, request, pk=None):
        """Remove a student's enrollment in a course (no email is sent)."""
        profile = self.get_object()
        course_id = request.data.get('course_id')
        if not course_id:
            return Response({'course_id': ['This field is required.']},
                            status=status.HTTP_400_BAD_REQUEST)
        deleted, _ = CourseEnrollment.objects.filter(
            student=profile, course_id=course_id, course__tenant=request.tenant,
        ).delete()
        if not deleted:
            return Response({'detail': 'Enrollment not found.'},
                            status=status.HTTP_404_NOT_FOUND)
        profile.refresh_from_db()
        return Response(StudentProfileSerializer(profile).data)

    @action(detail=True, methods=['post'], url_path='reset-password')
    def reset_password(self, request, pk=None):
        """Issue a fresh temporary password and email it to the user."""
        profile = self.get_object()
        user = profile.user
        # Resetting a peer admin's password would hand over their account, so
        # admin accounts can only be reset by their own owner.
        if user.role == 'admin' and user != request.user:
            return Response(
                {'detail': "You cannot reset another admin's password."},
                status=status.HTTP_403_FORBIDDEN,
            )
        temp_password = generate_temp_password()
        user.set_password(temp_password)
        user.save(update_fields=['password'])

        email_sent = False
        try:
            from notifications import services as notification_services
            email_sent = notification_services.on_credentials_reset(
                user, temp_password,
            )
        except Exception:  # noqa: BLE001
            logger.exception('Failed to email new password to %s', user.email)

        payload = {'email_sent': email_sent}
        if not email_sent:
            payload['temporary_password'] = temp_password
        return Response(payload)

    @action(detail=True, methods=['post'])
    def reset_progress(self, request, pk=None):
        """Reset all progress for a student."""
        profile = self.get_object()
        
        with transaction.atomic():
            # Reset profile counters
            profile.total_xp = 0
            profile.current_level = 1
            profile.total_questions_attempted = 0
            profile.total_correct_answers = 0
            profile.total_study_time_minutes = 0
            profile.save()
            
            # Delete related analytics data
            profile.daily_activities.all().delete()
            profile.topic_masteries.all().delete()
            profile.subject_performances.all().delete()
            profile.streaks.all().delete()
            profile.weekly_reports.all().delete()
            profile.study_sessions.all().delete()
            
            # Note: Quiz attempts and Mock attempts are NOT deleted by default 
            # to preserve audit logs, but their derived analytics are cleared.
            
        return Response({'status': 'progress reset successful'})

    @action(detail=True, methods=['post'])
    def toggle_status(self, request, pk=None):
        """Toggle user active status."""
        profile = self.get_object()
        user = profile.user
        
        # Prevent admins from deactivating themselves via this endpoint 
        # (though they could via other means, this is a safety check)
        if user == request.user:
            return Response(
                {'error': 'You cannot deactivate your own account'},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        user.is_suspended = not user.is_suspended
        user.save(update_fields=['is_suspended'])
        
        return Response({
            'status': 'status toggled',
            'is_active': user.is_active,
            'is_suspended': user.is_suspended
        })

class TenantEnrollmentRequestViewSet(TenantAwareViewSet):
    """
    Tenant admins review and approve/reject student course enrollment requests.
    """
    serializer_class = AdminEnrollmentRequestSerializer
    permission_classes = [permissions.IsAuthenticated, IsTenantAdmin]
    http_method_names = ['get', 'post', 'head', 'options']

    def get_queryset(self):
        tenant = self.request.tenant
        qs = CourseEnrollment.objects.filter(
            student__user__tenant=tenant
        ).select_related('student__user', 'course', 'reviewed_by').order_by('-created_at')
        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        enrollment = self.get_object()
        enrollment.status = 'approved'
        enrollment.is_active = True
        enrollment.rejection_reason = ''
        enrollment.reviewed_at = timezone.now()
        enrollment.reviewed_by = request.user
        enrollment.save()
        try:
            from notifications import services as notification_services
            notification_services.on_enrollment_approved(enrollment)
        except Exception:  # noqa: BLE001
            logger.exception('Failed to notify student of approval for %s', enrollment.id)
        return Response(self.get_serializer(enrollment).data)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        enrollment = self.get_object()
        enrollment.status = 'rejected'
        enrollment.is_active = False
        enrollment.rejection_reason = request.data.get('reason', '')
        enrollment.reviewed_at = timezone.now()
        enrollment.reviewed_by = request.user
        enrollment.save()
        try:
            from notifications import services as notification_services
            notification_services.on_enrollment_rejected(enrollment)
        except Exception:  # noqa: BLE001
            logger.exception('Failed to notify student of rejection for %s', enrollment.id)
        return Response(self.get_serializer(enrollment).data)
