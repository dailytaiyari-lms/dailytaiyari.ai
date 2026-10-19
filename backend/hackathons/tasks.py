"""Celery tasks for the AI Hackathon Studio.

A full event brief, or a batch of coding problems, routinely outlives a sane HTTP
timeout — so generation runs on the worker and the studio polls
``GET /jobs/{id}/`` until the draft is ready, the same contract the course and
mock-test builders use.

Nothing here writes to the hackathon tables: the task only fills in the job's
``draft``. Applying stays an explicit, admin-confirmed request.
"""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    name='hackathons.generate', bind=True, max_retries=0,
    # Shares the authoring queue with the other builders: long-form, I/O-bound,
    # and must not sit in front of quick submission grading on the default queue.
    queue='aigen', soft_time_limit=1500, time_limit=1560,
)
def run_generation_job(self, job_id, mode='generate', instruction=''):
    from . import generation
    from .models import HackathonGenerationJob

    # Claim atomically so a broker redelivery can never run the same job twice.
    claimed = HackathonGenerationJob.objects.filter(
        id=job_id, status__in=HackathonGenerationJob.RUNNABLE_STATUSES,
    ).update(status='generating')
    if not claimed:
        logger.info('hackathons.generate: %s not in a runnable state, skipping', job_id)
        return None

    try:
        job = HackathonGenerationJob.objects.select_related(
            'tenant', 'hackathon', 'stage', 'stage__hackathon',
        ).get(id=job_id)
    except HackathonGenerationJob.DoesNotExist:
        logger.warning('hackathons.generate: job %s not found', job_id)
        return None

    try:
        if mode == 'refine':
            generation.apply_refinement(job, instruction or '')
        else:
            generation.run_job(job)
    except generation.GenerationError as exc:
        # run_job / apply_refinement already stored a user-facing error and the
        # right terminal status.
        logger.info('hackathons.generate %s reported: %s', job_id, exc)
    except Exception as exc:  # noqa: BLE001 - never leave a job stuck 'generating'
        logger.exception('hackathons.generate failed for %s: %s', job_id, exc)
        HackathonGenerationJob.objects.filter(id=job_id).update(
            status='failed',
            error='Generation failed unexpectedly. Please try again.',
        )
    return str(job_id)
