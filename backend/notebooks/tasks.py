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


@shared_task(
    name='notebooks.generate', bind=True, max_retries=0,
    queue='notebooks',
    # Generating a full graded notebook is a long-form LLM call; give it the
    # same generous limits as grading so it never trips the default worker's.
    soft_time_limit=280, time_limit=300,
)
def run_generation_job(self, job_id, mode='generate', instruction=''):
    """Run an AI notebook generation/refinement off the request thread.

    ``mode`` is 'generate' (a fresh draft or a retry of a failed job) or
    'refine' (revise the existing preview draft with ``instruction``). The job
    is claimed atomically so a broker redelivery can't run it twice.
    """
    from .aigen import generation
    from .models import NotebookGenerationJob

    # Only a job that is genuinely waiting to run may transition to 'generating'.
    # For a refine we accept 'preview' (there is a draft to revise); for a
    # generate/retry we accept 'pending' or 'failed'.
    if mode == 'refine':
        allowed = [NotebookGenerationJob.STATUS_PREVIEW]
    else:
        allowed = [NotebookGenerationJob.STATUS_PENDING, NotebookGenerationJob.STATUS_FAILED]

    claimed = NotebookGenerationJob.objects.filter(
        id=job_id, status__in=allowed,
    ).update(status=NotebookGenerationJob.STATUS_GENERATING)
    if not claimed:
        logger.info('run_generation_job: %s not in a runnable state, skipping', job_id)
        return None

    try:
        job = NotebookGenerationJob.objects.select_related(
            'tenant', 'course', 'subject', 'topic', 'notebook',
        ).get(id=job_id)
    except NotebookGenerationJob.DoesNotExist:
        logger.warning('run_generation_job: job %s not found', job_id)
        return None

    try:
        if mode == 'refine':
            generation.apply_refinement(job, instruction or '')
        else:
            generation.run_job(job)
    except generation.GenerationError as exc:
        # run_job/apply_refinement already stored a user-facing error and the
        # appropriate terminal status; nothing more to do.
        logger.info('run_generation_job %s reported: %s', job_id, exc)
    except Exception as exc:  # noqa: BLE001 - never leave a job stuck 'generating'
        logger.exception('run_generation_job failed for %s: %s', job_id, exc)
        NotebookGenerationJob.objects.filter(id=job_id).update(
            status=NotebookGenerationJob.STATUS_FAILED,
            error='Generation failed unexpectedly. Please try again.',
        )
    return str(job_id)
