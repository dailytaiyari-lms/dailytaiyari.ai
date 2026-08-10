"""Celery tasks for the notebooks app.

`grade_notebook_submission` re-executes a submitted notebook in the sandboxed
runner off the web request thread. Notebook grading is far heavier than a
coding submission (a submission can train a model), so the async path is the
intended default: the view returns a queued submission immediately with the
browser's provisional score, and the client polls for the authoritative result.
"""
import logging

from celery import shared_task

from . import services
from .models import NotebookSubmission

logger = logging.getLogger(__name__)


@shared_task(
    name='notebooks.grade_submission', bind=True, max_retries=0,
    queue='notebooks',
    # Notebook grading is long-running (a submission may train a model), so it
    # gets its own queue/worker and much higher limits than the coding judge.
    # Must exceed services.HTTP_TIMEOUT_S plus the runner's own grace period.
    soft_time_limit=280, time_limit=300,
)
def grade_notebook_submission(self, submission_id):
    """Grade a queued submission in place. Idempotent-safe to re-run."""
    from . import grading

    # Atomically claim the job: only a still-'queued' row transitions to
    # 'running'. If another worker/redelivery already claimed or finished it,
    # skip -- this prevents duplicate grading (and duplicate XP) on redelivery.
    claimed = NotebookSubmission.objects.filter(
        id=submission_id, status=NotebookSubmission.STATUS_QUEUED,
    ).update(status=NotebookSubmission.STATUS_RUNNING)
    if not claimed:
        logger.info('grade_notebook_submission: %s already claimed/terminal, skipping', submission_id)
        return None

    try:
        submission = NotebookSubmission.objects.select_related(
            'notebook', 'student',
        ).get(id=submission_id)
    except NotebookSubmission.DoesNotExist:
        logger.warning('grade_notebook_submission: submission %s not found', submission_id)
        return None

    try:
        grading.finalize_submission(submission)
    except services.EngineError as exc:
        # finalize_submission already marked the submission status='error' with
        # a user-facing message; the poll endpoint surfaces it. Don't retry --
        # re-running untrusted code on a flaky engine isn't worth the churn.
        logger.error('grade_notebook_submission engine error for %s: %s', submission_id, exc)
    except Exception as exc:  # noqa: BLE001 - never leave a submission stuck 'running'
        logger.exception('grade_notebook_submission failed for %s: %s', submission_id, exc)
        NotebookSubmission.objects.filter(id=submission_id).update(
            status=NotebookSubmission.STATUS_ERROR,
            execution_error='Grading failed unexpectedly. Please try submitting again.',
        )

    return str(submission_id)
