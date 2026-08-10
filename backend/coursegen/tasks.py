"""Celery tasks for the AI Course Builder.

A content job makes several sequential LLM calls (one batch of topics at a
time), so it routinely outlives a sane HTTP timeout. Running it on the worker
lets the studio return a job id immediately and poll ``GET /jobs/{id}/`` until
the draft is ready — the same contract the notebook generator uses.

Nothing here writes to the course tables: the task only ever fills in the job's
``draft``. Applying stays an explicit, admin-confirmed request.
"""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    name='coursegen.generate', bind=True, max_retries=0,
    # Its own queue: authoring is long-form and I/O-bound, so it must not sit
    # head-of-line in front of quick coding-submission grading on the default
    # queue. Limits are far above the project-wide defaults for the same reason.
    queue='aigen',
    soft_time_limit=1500, time_limit=1560,
)
def run_generation_job(self, job_id, mode='generate', instruction='', topics=None):
    """Generate or refine a course draft off the request thread.

    ``mode`` is 'generate' (fresh draft, or a retry of a failed job) or 'refine'
    (revise the existing preview draft using ``instruction``). ``topics`` is the
    already-resolved topic snapshot for content jobs, passed through so the
    worker does not have to re-authorize the caller's course scope.
    """
    from . import generation
    from .models import CourseGenerationJob

    # Claim atomically so a broker redelivery can never run the same job twice.
    # A refine starts from the reviewable draft; a generate/retry from a job
    # that is queued or has already failed.
    if mode == 'refine':
        allowed = [CourseGenerationJob.STATUS_PREVIEW]
    else:
        allowed = [CourseGenerationJob.STATUS_PENDING, CourseGenerationJob.STATUS_FAILED]

    claimed = CourseGenerationJob.objects.filter(
        id=job_id, status__in=allowed,
    ).update(status=CourseGenerationJob.STATUS_GENERATING)
    if not claimed:
        logger.info('coursegen.generate: %s not in a runnable state, skipping', job_id)
        return None

    try:
        job = CourseGenerationJob.objects.select_related('tenant', 'course').get(id=job_id)
    except CourseGenerationJob.DoesNotExist:
        logger.warning('coursegen.generate: job %s not found', job_id)
        return None

    try:
        if mode == 'refine':
            generation.apply_refinement(job, instruction or '')
        else:
            generation.run_job(job, topics=topics or [])
    except generation.GenerationError as exc:
        # run_job / apply_refinement already recorded a user-facing error and
        # the right terminal status.
        logger.info('coursegen.generate %s reported: %s', job_id, exc)
    except Exception as exc:  # noqa: BLE001 - never leave a job stuck 'generating'
        logger.exception('coursegen.generate failed for %s: %s', job_id, exc)
        CourseGenerationJob.objects.filter(id=job_id).update(
            status=CourseGenerationJob.STATUS_FAILED,
            error='Generation failed unexpectedly. Please try again.',
        )
    return str(job_id)
