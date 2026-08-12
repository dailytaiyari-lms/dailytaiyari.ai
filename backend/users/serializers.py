"""
Serializers for User authentication and profile management.
"""
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth import get_user_model
from .models import StudentProfile, CourseEnrollment

User = get_user_model()


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Custom JWT token serializer with additional user data."""
    
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        # Add custom claims
        token['email'] = user.email
        token['name'] = user.full_name
        token['is_onboarded'] = user.is_onboarded
        token['is_suspended'] = user.is_suspended
        return token

    def validate(self, attrs):
        # The standard validate calls authenticate() which will fail 
        # because the email is no longer globally unique for the default backend.
        # We handle tenant-scoping here.
        email = attrs.get('email')
        password = attrs.get('password')
        tenant = getattr(self.context['request'], 'tenant', None)

        if not tenant:
            raise serializers.ValidationError('Tenant context is missing.')

        try:
            user = User.objects.get(email=email, tenant=tenant)
        except User.DoesNotExist:
            user = None

        if user and user.check_password(password):
            if not user.is_active:
                raise serializers.ValidationError('User account is disabled.')
            # A suspended or billing-frozen tenant is frozen for everyone,
            # including its admins.
            blocked, message, _code = tenant.access_block()
            if blocked:
                raise serializers.ValidationError(message)
            # NOTE: Unverified and suspended users are allowed to authenticate.
            # The frontend gates the app behind a "verify your email" screen for
            # unverified users, and blurs it behind a modal for suspended users.
            # Suspended users are additionally blocked from data APIs by
            # core.middleware.BlockSuspendedUsersMiddleware.
            self.user = user
            refresh = self.get_token(user)
            data = {
                'refresh': str(refresh),
                'access': str(refresh.access_token),
                'user': UserSerializer(user).data
            }
            return data
        
        raise serializers.ValidationError('No active account found with the given credentials')



class UserRegistrationSerializer(serializers.ModelSerializer):
    """Serializer for user registration."""
    password = serializers.CharField(write_only=True, min_length=8)
    password_confirm = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ['email', 'first_name', 'last_name', 'phone', 'password', 'password_confirm']

    def validate_email(self, value):
        """Reject duplicate emails within the tenant with a clean 400 instead of
        letting the DB unique constraint raise a 500."""
        request = self.context.get('request')
        tenant = getattr(request, 'tenant', None)
        qs = User.objects.filter(email__iexact=value)
        if tenant is not None:
            qs = qs.filter(tenant=tenant)
        if qs.exists():
            raise serializers.ValidationError(
                'An account with this email already exists. Please sign in instead.'
            )
        return value

    def validate(self, attrs):
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({'password_confirm': 'Passwords do not match'})
        return attrs

    def create(self, validated_data):
        from django.db import IntegrityError
        password = validated_data.pop('password')
        validated_data.pop('password_confirm')
        tenant = validated_data.pop('tenant')
        try:
            user = User.objects.create_user(password=password, tenant=tenant, **validated_data)
        except IntegrityError:
            # Safety net for a race between validate_email and insert.
            raise serializers.ValidationError(
                {'email': ['An account with this email already exists. Please sign in instead.']}
            )
        return user


class EmailOTPRequestSerializer(serializers.Serializer):
    """Request (or re-request) an email verification code for an address."""
    email = serializers.EmailField()


class EmailOTPVerifySerializer(serializers.Serializer):
    """Verify an email address with a 6-digit code."""
    email = serializers.EmailField()
    code = serializers.CharField(min_length=4, max_length=8)


class PasswordResetConfirmSerializer(serializers.Serializer):
    """Reset a password using the emailed OTP."""
    email = serializers.EmailField()
    code = serializers.CharField(min_length=4, max_length=8)
    new_password = serializers.CharField(min_length=8, write_only=True)


class PasswordChangeSerializer(serializers.Serializer):
    """Change the password for an authenticated user."""
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(min_length=8, write_only=True)

    def validate_old_password(self, value):
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError('Current password is incorrect.')
        return value

    def validate(self, attrs):
        if attrs['old_password'] == attrs['new_password']:
            raise serializers.ValidationError(
                {'new_password': 'New password must be different from the current password.'}
            )
        return attrs



class UserSerializer(serializers.ModelSerializer):
    """Serializer for user data."""
    full_name = serializers.ReadOnlyField()
    
    class Meta:
        model = User
        fields = [
            'id', 'email', 'first_name', 'last_name', 'full_name', 'role', 'is_active', 'is_suspended',
            'is_email_verified',
            'phone', 'avatar', 'is_onboarded', 'preferred_language',
            'notification_enabled', 'dark_mode', 'created_at', 'last_active'
        ]

        read_only_fields = ['id', 'email', 'created_at', 'last_active', 'is_email_verified']


class StudentProfileSerializer(serializers.ModelSerializer):
    """Serializer for student profile."""
    user = UserSerializer(required=False)

    overall_accuracy = serializers.ReadOnlyField()
    xp_for_next_level = serializers.ReadOnlyField()
    enrolled_course_ids = serializers.SerializerMethodField()
    enrolled_courses = serializers.SerializerMethodField()

    def get_enrolled_course_ids(self, obj):
        """All courses the student is enrolled in (excluding rejected requests).

        Lets the admin roster filter by any course a student is associated with.
        """
        return [
            str(e.course_id)
            for e in obj.enrollments.all()
            if e.status != 'rejected'
        ]

    def get_enrolled_courses(self, obj):
        """Course id/name/status for every non-rejected enrollment.

        All of a student's courses are treated at the same level; this is the
        single source of truth for which courses a student belongs to.
        """
        return [
            {'id': str(e.course_id), 'name': e.course.name, 'status': e.status}
            for e in obj.enrollments.all()
            if e.status != 'rejected'
        ]

    # Handle nullable fields that may receive empty strings from frontend
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    target_year = serializers.IntegerField(required=False, allow_null=True)

    class Meta:
        model = StudentProfile
        fields = [
            'id', 'user', 
            # Personal info
            'date_of_birth', 'bio', 'instagram_handle', 'parent_phone',
            # Academic info
            'grade', 'school', 'coaching', 'board', 'medium', 'target_year',
            # Location
            'city', 'state',
            # Course info
            'enrolled_course_ids', 'enrolled_courses',
            # Study preferences
            'daily_study_goal_minutes', 'preferred_study_time', 
            # Stats
            'total_xp', 'current_level', 
            'total_questions_attempted', 'total_correct_answers',
            'total_study_time_minutes', 'overall_accuracy', 'xp_for_next_level',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'total_xp', 'current_level', 
            'total_questions_attempted', 'total_correct_answers',
            'total_study_time_minutes', 'created_at', 'updated_at'
        ]

    
    def to_internal_value(self, data):
        # Copy immutable QueryDicts (multipart/form-data) so we can normalize values
        if hasattr(data, '_mutable'):
            data = data.copy()
        # Convert empty strings to None for nullable fields
        if 'date_of_birth' in data and data['date_of_birth'] == '':
            data['date_of_birth'] = None
        if 'target_year' in data and data['target_year'] == '':
            data['target_year'] = None
        return super().to_internal_value(data)

    def update(self, instance, validated_data):
        user_data = validated_data.pop('user', None)
        if user_data:
            user_serializer = UserSerializer(instance.user, data=user_data, partial=True)
            user_serializer.is_valid(raise_exception=True)
            user_serializer.save()
        
        return super().update(instance, validated_data)




class CourseEnrollmentSerializer(serializers.ModelSerializer):
    """Serializer for course enrollment."""
    course_name = serializers.CharField(source='course.name', read_only=True)
    course_code = serializers.CharField(source='course.code', read_only=True)

    class Meta:
        model = CourseEnrollment
        fields = [
            'id', 'course', 'course_name', 'course_code', 'is_active', 'status',
            'rejection_reason', 'reviewed_at', 'enrolled_at', 'course_xp',
            'course_rank', 'target_score', 'target_rank'
        ]
        read_only_fields = [
            'id', 'enrolled_at', 'course_xp', 'course_rank', 'status',
            'rejection_reason', 'reviewed_at'
        ]


class AdminStudentCreateSerializer(serializers.Serializer):
    """Validate the payload a tenant admin submits to create a student account.

    The password is never supplied by the admin — it is generated server-side
    and emailed to the student — so this serializer only accepts identity,
    profile and course-assignment fields.
    """
    email = serializers.EmailField()
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default='')
    phone = serializers.CharField(max_length=15, required=False, allow_blank=True, default='')
    role = serializers.ChoiceField(
        choices=['student', 'instructor'], required=False, default='student',
    )
    course_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, default=list,
    )
    send_email = serializers.BooleanField(required=False, default=True)

    # Optional profile fields, mirroring StudentProfile.
    grade = serializers.CharField(max_length=20, required=False, allow_blank=True, default='')
    school = serializers.CharField(max_length=200, required=False, allow_blank=True, default='')
    coaching = serializers.CharField(max_length=200, required=False, allow_blank=True, default='')
    board = serializers.CharField(max_length=20, required=False, allow_blank=True, default='')
    medium = serializers.CharField(max_length=20, required=False, allow_blank=True, default='')
    city = serializers.CharField(max_length=100, required=False, allow_blank=True, default='')
    state = serializers.CharField(max_length=100, required=False, allow_blank=True, default='')
    parent_phone = serializers.CharField(max_length=15, required=False, allow_blank=True, default='')
    target_year = serializers.IntegerField(required=False, allow_null=True, default=None)

    PROFILE_FIELDS = [
        'grade', 'school', 'coaching', 'board', 'medium', 'city', 'state',
        'parent_phone', 'target_year',
    ]

    def validate_email(self, value):
        value = value.strip().lower()
        tenant = self.context.get('tenant')
        qs = User.objects.filter(email__iexact=value)
        if tenant is not None:
            qs = qs.filter(tenant=tenant)
        if qs.exists():
            raise serializers.ValidationError(
                'A user with this email already exists in your institution.'
            )
        return value

    def validate_course_ids(self, value):
        """Restrict assignment to courses owned by the admin's own tenant."""
        if not value:
            return []
        tenant = self.context.get('tenant')
        from exams.models import Course
        courses = list(Course.objects.filter(id__in=value, tenant=tenant))
        found = {str(c.id) for c in courses}
        missing = [str(v) for v in value if str(v) not in found]
        if missing:
            raise serializers.ValidationError(
                f"Course(s) not found in this institution: {', '.join(missing)}"
            )
        return [c.id for c in courses]

    def profile_updates(self):
        """Non-blank profile field values from the validated payload."""
        data = self.validated_data
        updates = {}
        for field in self.PROFILE_FIELDS:
            value = data.get(field)
            if value not in (None, ''):
                updates[field] = value
        return updates


class AdminAssignCourseSerializer(serializers.Serializer):
    """Validate an admin's request to enrol a student in one or more courses."""
    course_ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=False)
    send_email = serializers.BooleanField(required=False, default=True)

    def validate_course_ids(self, value):
        tenant = self.context.get('tenant')
        from exams.models import Course
        courses = list(Course.objects.filter(id__in=value, tenant=tenant))
        found = {str(c.id) for c in courses}
        missing = [str(v) for v in value if str(v) not in found]
        if missing:
            raise serializers.ValidationError(
                f"Course(s) not found in this institution: {', '.join(missing)}"
            )
        return [c.id for c in courses]


class AdminEnrollmentRequestSerializer(serializers.ModelSerializer):
    """Serializer for tenant admins to review enrollment requests."""
    course_name = serializers.CharField(source='course.name', read_only=True)
    course_code = serializers.CharField(source='course.code', read_only=True)
    student_name = serializers.CharField(source='student.user.full_name', read_only=True)
    student_email = serializers.CharField(source='student.user.email', read_only=True)
    reviewed_by_email = serializers.CharField(source='reviewed_by.email', read_only=True)

    class Meta:
        model = CourseEnrollment
        fields = [
            'id', 'course', 'course_name', 'course_code', 'student_name', 'student_email',
            'status', 'rejection_reason', 'reviewed_at', 'reviewed_by_email', 'created_at'
        ]
        read_only_fields = fields


class OnboardingSerializer(serializers.Serializer):
    """Serializer for student onboarding — goals only (no course selection)."""
    target_year = serializers.IntegerField(required=False)
    daily_study_goal_minutes = serializers.IntegerField(default=60)
    preferred_study_time = serializers.ChoiceField(
        choices=['morning', 'afternoon', 'evening', 'night'],
        default='evening'
    )

