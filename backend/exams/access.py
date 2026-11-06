from django.db.models import Q


def has_approved_course_enrollment(user, course_id):
    """Whether a student currently has usable access to a course."""
    if not user or not user.is_authenticated:
        return False
    profile = getattr(user, 'profile', None)
    if profile is None:
        return False
    return profile.enrollments.filter(
        course_id=course_id,
        status='approved',
        is_active=True,
    ).exists()


def can_access_course(user, course):
    """Whether a user may open enrolled-only study surfaces for a course."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or getattr(user, 'role', None) == 'admin':
        return True
    if getattr(user, 'role', None) == 'instructor':
        return course.instructors.filter(pk=user.pk).exists()
    return has_approved_course_enrollment(user, course.id)


def visible_courses_for_request(queryset, request):
    """Apply the shared public/enrolled visibility rule to a Course queryset."""
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return queryset.filter(is_hidden=False)

    if user.is_superuser or getattr(user, 'role', None) == 'admin':
        return queryset

    if getattr(user, 'role', None) == 'instructor':
        return queryset.filter(Q(is_hidden=False) | Q(instructors=user)).distinct()

    return queryset.filter(
        Q(is_hidden=False)
        | Q(
            enrollments__student__user=user,
            enrollments__status='approved',
            enrollments__is_active=True,
        )
    ).distinct()
