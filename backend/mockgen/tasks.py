"""Celery tasks for the AI Mock Test Builder.

A paper is written in several sequential LLM calls (one batch of questions at a
time), so a full-length mock routinely outlives a sane HTTP timeout. Running it
on the worker lets the studio return a job id immediately and poll
``GET /jobs/{id}/`` until the draft is ready — the same contract the course
builder and notebook generator use.

Nothing here writes to the mock-test tables: the task only ever fills in the
job's ``draft``. Applying stays an explicit, admin-confirmed request.
"""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    name='mockgen.generate', bind=True, max_retries=0,
    # Shares the authoring queue with the course builder: both are long-form and
    # I/O-bound, and must not sit head-of-line in front of quick coding-submission
    # grading on the default queue.
    queue='aigen',
    soft_time_limit=1500, time_limit=1560,
)
def run_generation_job(self, job_id, mode='generate', instruction=''):
    """Generate or refine a mock-test draft off the request thread."""
    from . import generation
    from .models import MockTestGenerationJob

    # Claim atomically so a broker redelivery can never run the same job twice.
    # Every queued job is left in ``pending`` by the view, whatever the mode —
    # a refine included, so the studio keeps polling instead of settling on the
    # draft it is about to replace.
    allowed = [MockTestGenerationJob.STATUS_PENDING, MockTestGenerationJob.STATUS_FAILED]

    claimed = MockTestGenerationJob.objects.filter(
        id=job_id, status__in=allowed,
    ).update(status=MockTestGenerationJob.STATUS_GENERATING)
    if not claimed:
        logger.info('mockgen.generate: %s not in a runnable state, skipping', job_id)
        return None

    try:
        job = MockTestGenerationJob.objects.select_related(
            'tenant', 'mock_test', 'course',
        ).get(id=job_id)
    except MockTestGenerationJob.DoesNotExist:
        logger.warning('mockgen.generate: job %s not found', job_id)
        return None

    try:
        if mode == 'refine':
            generation.apply_refinement(job, instruction or '')
        else:
            generation.run_job(job)
    except generation.GenerationError as exc:
        # run_job / apply_refinement already recorded a user-facing error and
        # the right terminal status.
        logger.info('mockgen.generate %s reported: %s', job_id, exc)
    except Exception as exc:  # noqa: BLE001 - never leave a job stuck 'generating'
        logger.exception('mockgen.generate failed for %s: %s', job_id, exc)
        MockTestGenerationJob.objects.filter(id=job_id).update(
            status=MockTestGenerationJob.STATUS_FAILED,
            error='Generation failed unexpectedly. Please try again.',
        )
    return str(job_id)
