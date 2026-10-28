"""Who may see which students and courses in the learning layer (spec 2B §3.2).

- Students see only themselves; their endpoints never take a student id.
- Faculty (``role='instructor'``) see the courses they are assigned to
  (``Course.instructors``) and the students with an approved enrollment in
  one of them.
- Admins see every course and student in their tenant.

Every teacher-facing intelligence view goes through these helpers, so the
rule lives in one place.
"""
from django.db.models import Q

from exams.models import Course

STAFF_ROLES = ('admin', 'instructor')


def _role(user):
    return getattr(user, 'role', '') if user is not None else ''


def teachable_course_ids(user):
    """Ids of the courses ``user`` may see, as a set (empty for students)."""
    role = _role(user)
    if role not in STAFF_ROLES or not getattr(user, 'tenant_id', None):
        return set()
    courses = Course.objects.filter(tenant_id=user.tenant_id)
    if role != 'admin':
        courses = courses.filter(instructors=user)
    return set(courses.values_list('id', flat=True))


def can_manage_course(user, course):
    """Admins: any course in their tenant. Faculty: their assigned courses."""
    role = _role(user)
    if course is None or role not in STAFF_ROLES:
        return False
    if course.tenant_id != getattr(user, 'tenant_id', None):
        return False
    if role == 'admin':
        return True
    return course.instructors.filter(id=user.id).exists()


def can_view_student(user, student):
    """Admins: any student in their tenant. Faculty: students with an
    approved enrollment in one of their courses."""
    from users.models import CourseEnrollment

    role = _role(user)
    if student is None or role not in STAFF_ROLES:
        return False
    if student.user.tenant_id != getattr(user, 'tenant_id', None):
        return False
    if role == 'admin':
        return True
    return CourseEnrollment.objects.filter(
        student=student, status='approved', course__instructors=user,
    ).exists()


def assessment_course_ids(kind, assessment):
    """The courses a quiz or mock belongs to (a mock can have several, or none)."""
    if kind == 'quiz':
        return [assessment.course_id] if assessment.course_id else []
    # The legacy FK and the M2M both mean "belongs to": take the union.
    ids = list(assessment.courses.values_list('id', flat=True))
    if assessment.course_id and assessment.course_id not in ids:
        ids.append(assessment.course_id)
    return ids


def assessment_in_scope(user, kind, assessment):
    """Admins see every assessment. Faculty see those linked to one of their
    courses; a mock linked to no course is open to the whole tenant, so it is
    admin-only."""
    if _role(user) == 'admin':
        return True
    return bool(set(assessment_course_ids(kind, assessment)) & teachable_course_ids(user))


def diagnosis_scope_q(user, student):
    """A ``Q`` over ResponseDiagnosis limiting ``student``'s rows to the
    attempts ``user`` may see: everything for admins; for faculty, quizzes,
    mocks and practice sets that belong to one of their courses."""
    from quiz.models import MockTestAttempt, QuizAttempt

    from intelligence.models import PracticeSet

    if _role(user) == 'admin':
        return Q()
    ids = teachable_course_ids(user)
    quiz_ids = QuizAttempt.objects.filter(
        student=student, quiz__course_id__in=ids).values('id')
    mock_ids = MockTestAttempt.objects.filter(student=student).filter(
        Q(mock_test__course_id__in=ids) | Q(mock_test__courses__id__in=ids)).values('id')
    practice_ids = PracticeSet.objects.filter(
        student=student, course_id__in=ids).values('id')
    return (
        Q(attempt_kind='quiz', attempt_id__in=quiz_ids)
        | Q(attempt_kind='mock', attempt_id__in=mock_ids)
        | Q(attempt_kind='practice', attempt_id__in=practice_ids)
    )
