"""Roster-wide course completion, computed in a fixed number of queries.

``certificates.services.compute_course_progress`` is authoritative but costs
~10 queries per (student, course) pair — fine for one certificate check, far
too slow for an admin roster where every student may sit in several courses.

``bulk_course_progress`` answers the same question for a whole tenant using
grouped aggregates: four queries for the per-course denominators and four for
the per-(student, course) numerators, regardless of roster size. The item
definitions deliberately mirror ``compute_course_progress`` so the percentage
an admin sees matches the one that unlocks the student's certificate.
"""
from collections import defaultdict

from django.db.models import Count, F

READING_TYPES = ['notes', 'pdf', 'revision', 'formula']
COUNTED_CONTENT_TYPES = READING_TYPES + ['video']


def _totals_by_course(course_ids):
    """Published item counts per course id."""
    from assignments.models import Assignment
    from coding.models import CodingProblem
    from content.models import Content
    from quiz.models import Quiz

    totals = defaultdict(int)

    rows = (
        Content.objects
        .filter(subject__course_id__in=course_ids, status='published',
                content_type__in=COUNTED_CONTENT_TYPES)
        .values('subject__course_id')
        .annotate(n=Count('id'))
    )
    for row in rows:
        totals[row['subject__course_id']] += row['n']

    rows = (
        Quiz.objects
        .filter(course_id__in=course_ids, status='published')
        .values('course_id')
        .annotate(n=Count('id'))
    )
    for row in rows:
        totals[row['course_id']] += row['n']

    # Assignments and coding problems are attributed through their topic's
    # subject (matching compute_course_progress), not their own course FK,
    # so an item filed under another course's topic isn't double counted.
    rows = (
        Assignment.objects
        .filter(topic__subject__course_id__in=course_ids, status='published')
        .values('topic__subject__course_id')
        .annotate(n=Count('id'))
    )
    for row in rows:
        totals[row['topic__subject__course_id']] += row['n']

    rows = (
        CodingProblem.objects
        .filter(topic__subject__course_id__in=course_ids, status='published')
        .values('topic__subject__course_id')
        .annotate(n=Count('id'))
    )
    for row in rows:
        totals[row['topic__subject__course_id']] += row['n']

    return totals


def _completed_by_student_course(student_ids, course_ids):
    """Completed item counts keyed by ``(student_id, course_id)``."""
    from assignments.models import AssignmentSubmission
    from coding.models import CodingSubmission
    from content.models import ContentProgress
    from quiz.models import QuizAttempt

    done = defaultdict(int)

    rows = (
        ContentProgress.objects
        .filter(student_id__in=student_ids,
                content__subject__course_id__in=course_ids,
                content__status='published',
                content__content_type__in=COUNTED_CONTENT_TYPES,
                is_completed=True)
        .values('student_id', 'content__subject__course_id')
        .annotate(n=Count('content_id', distinct=True))
    )
    for row in rows:
        done[(row['student_id'], row['content__subject__course_id'])] += row['n']

    rows = (
        QuizAttempt.objects
        .filter(student_id__in=student_ids, quiz__course_id__in=course_ids,
                quiz__status='published', status='completed')
        .values('student_id', 'quiz__course_id')
        .annotate(n=Count('quiz_id', distinct=True))
    )
    for row in rows:
        done[(row['student_id'], row['quiz__course_id'])] += row['n']

    rows = (
        AssignmentSubmission.objects
        .filter(student_id__in=student_ids,
                assignment__topic__subject__course_id__in=course_ids,
                assignment__status='published')
        .values('student_id', 'assignment__topic__subject__course_id')
        .annotate(n=Count('assignment_id', distinct=True))
    )
    for row in rows:
        done[(row['student_id'], row['assignment__topic__subject__course_id'])] += row['n']

    rows = (
        CodingSubmission.objects
        .filter(student_id__in=student_ids,
                problem__topic__subject__course_id__in=course_ids,
                problem__status='published',
                total_count__gt=0, passed_count=F('total_count'))
        .values('student_id', 'problem__topic__subject__course_id')
        .annotate(n=Count('problem_id', distinct=True))
    )
    for row in rows:
        done[(row['student_id'], row['problem__topic__subject__course_id'])] += row['n']

    return done


def bulk_course_progress(enrollments):
    """Completion percentages for many enrollments at once.

    ``enrollments`` is any iterable of ``CourseEnrollment`` rows (already
    filtered to the caller's tenant). Returns::

        {student_id: [{'course_id', 'course_name', 'completed', 'total',
                       'percent', 'status'}, ...]}

    Courses with no published items report 0% with ``total = 0`` so the client
    can distinguish "nothing to do yet" from "nothing done yet".
    """
    enrollments = list(enrollments)
    if not enrollments:
        return {}

    student_ids = {e.student_id for e in enrollments}
    course_ids = {e.course_id for e in enrollments}

    totals = _totals_by_course(course_ids)
    done = _completed_by_student_course(student_ids, course_ids)

    result = defaultdict(list)
    for enrollment in enrollments:
        total = totals.get(enrollment.course_id, 0)
        completed = min(done.get((enrollment.student_id, enrollment.course_id), 0), total)
        result[enrollment.student_id].append({
            'course_id': str(enrollment.course_id),
            'course_name': enrollment.course.name,
            'completed': completed,
            'total': total,
            'percent': round((completed / total) * 100) if total else 0,
            'status': enrollment.status,
        })

    for rows in result.values():
        rows.sort(key=lambda r: (-r['percent'], r['course_name']))
    return result
