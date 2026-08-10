"""Shared grading logic for notebook submissions.

`finalize_submission` grades a *queued* NotebookSubmission in place: it
re-executes the student's notebook in the sandboxed runner, scores it against
the notebook's tests, persists the result, refreshes the student's completion
record and — on the first pass — awards XP. Used by both the synchronous path
(NOTEBOOKS_JUDGE_ASYNC=False) and the Celery task, so scoring and XP semantics
are identical either way.
"""
import logging
from decimal import Decimal

from django.utils import timezone

from . import services
from .models import NotebookCompletion

logger = logging.getLogger(__name__)

# A notebook counts as "complete" (and earns XP) at this share of the points.
PASS_RATIO = 0.6


def _marks_for(notebook, passed_points, total_points):
    if not notebook.max_marks:
        return None
    if total_points <= 0:
        return Decimal('0.00')
    return (
        Decimal(notebook.max_marks) * Decimal(passed_points) / Decimal(total_points)
    ).quantize(Decimal('0.01'))


def award_completion_xp(student, notebook, marks):
    """Award notebook XP once per notebook (idempotent). Returns XP given."""
    from gamification.models import XPTransaction
    from gamification.services import GamificationService
    from core.utils import calculate_xp_for_assignment

    already_awarded = XPTransaction.objects.filter(
        student=student, transaction_type='notebook_graded', reference_id=notebook.id,
    ).exists()
    if already_awarded:
        return 0
    xp_awarded = calculate_xp_for_assignment(marks, notebook.max_marks)
    GamificationService.award_xp(
        student,
        xp_awarded,
        'notebook_graded',
        f'Completed notebook: {notebook.title}',
        str(notebook.id),
    )
    return xp_awarded


def refresh_completion(submission):
    """Recompute the student's best-result record for this notebook.

    Returns the XP awarded (0 unless this pass newly completed the notebook).
    """
    from .models import NotebookSubmission

    notebook = submission.notebook
    student = submission.student

    graded = list(NotebookSubmission.objects.filter(
        notebook=notebook, student=student, status=NotebookSubmission.STATUS_GRADED,
    ))
    attempts_used = NotebookSubmission.objects.filter(
        notebook=notebook, student=student,
    ).count()

    best = None
    for candidate in graded:
        if best is None or candidate.passed_points > best.passed_points:
            best = candidate
    if best is None:
        best = submission

    total_points = best.total_points or 0
    is_complete = bool(total_points) and best.passed_points >= PASS_RATIO * total_points
    completion, _ = NotebookCompletion.objects.update_or_create(
        notebook=notebook, student=student,
        defaults={
            'tenant': notebook.tenant,
            'best_submission': best,
            'best_passed_points': best.passed_points,
            'best_total_points': total_points,
            'best_marks': best.marks,
            'attempts_used': attempts_used,
            'is_complete': is_complete,
        },
    )
    if is_complete and completion.completed_at is None:
        completion.completed_at = timezone.now()
        completion.save(update_fields=['completed_at', 'updated_at'])

    if not is_complete:
        return 0
    return award_completion_xp(student, notebook, best.marks)


def finalize_submission(submission):
    """Grade `submission` in place against all tests and persist the result.

    Returns the XP awarded. On an engine failure the submission is marked
    status='error' with a user-facing message and services.EngineError is
    re-raised so the caller can decide how to surface it.
    """
    from .models import NotebookSubmission

    notebook = submission.notebook

    if not notebook.tests.exists():
        # A notebook with no autograder tests is a pure exercise: record it as
        # submitted-and-graded with zero points so admins can still review and
        # manually award marks.
        submission.status = NotebookSubmission.STATUS_GRADED
        submission.results = []
        submission.passed_count = 0
        submission.total_count = 0
        submission.passed_points = 0
        submission.total_points = 0
        submission.marks = None
        submission.graded_at = timezone.now()
        submission.save()
        refresh_completion(submission)
        return 0

    try:
        outcome = services.grade_notebook(notebook, submission.notebook_json)
    except services.EngineError as exc:
        submission.status = NotebookSubmission.STATUS_ERROR
        submission.execution_error = str(exc)
        submission.save(update_fields=['status', 'execution_error', 'updated_at'])
        raise

    submission.status = NotebookSubmission.STATUS_GRADED
    submission.results = outcome['results']
    submission.execution_error = outcome['execution_error']
    submission.passed_count = outcome['passed_count']
    submission.total_count = outcome['total_count']
    submission.passed_points = outcome['passed_points']
    submission.total_points = outcome['total_points']
    submission.marks = _marks_for(notebook, outcome['passed_points'], outcome['total_points'])
    submission.graded_at = timezone.now()
    submission.save()

    return refresh_completion(submission)


def apply_provisional(submission, provisional_results):
    """Store the browser's instant score on a freshly-created submission.

    Display-only: it never influences `marks`. Points are re-derived from the
    notebook's own test rows so a tampered client payload can't inflate them.
    """
    tests = {str(t.id): t for t in submission.notebook.tests.all()}
    cleaned = []
    passed_points = 0
    total_points = 0
    for raw in provisional_results or []:
        if not isinstance(raw, dict):
            continue
        test = tests.get(str(raw.get('id')))
        if not test:
            continue
        passed = bool(raw.get('passed'))
        total_points += test.points
        awarded = test.points if passed else 0
        passed_points += awarded
        cleaned.append({
            'id': str(test.id),
            'name': test.name,
            'grade_id': test.grade_id,
            'is_hidden': test.is_hidden,
            'passed': passed,
            'points': awarded,
            'max_points': test.points,
            'error': str(raw.get('error') or '')[:2000],
        })

    submission.provisional_results = cleaned
    submission.provisional_passed_points = passed_points
    submission.provisional_total_points = total_points
    submission.save(update_fields=[
        'provisional_results', 'provisional_passed_points',
        'provisional_total_points', 'updated_at',
    ])
    return cleaned
