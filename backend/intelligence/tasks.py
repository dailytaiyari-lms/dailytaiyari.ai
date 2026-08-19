"""Celery tasks for the learner-intelligence layer.

Two kinds of work, on two queues:
- LLM work (tagging) runs on ``aigen`` beside the course/mock builders, with
  its own generous time limits;
- statistical work (learner state, item stats) is cheap and runs on the
  default queue. All of it is recompute-from-events, so redelivery or a
  double-enqueue is harmless.
"""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Learner state + item stats (default queue — cheap, statistical)
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(name='intelligence.update_learner_state', max_retries=0)
def update_learner_state_for_attempt(kind, attempt_id):
    """Recompute the concept states an attempt touched. Idempotent."""
    from .services import state

    try:
        return state.update_for_attempt(kind, attempt_id)
    except Exception:  # noqa: BLE001 — the nightly refresh catches up
        logger.exception('intelligence.update_learner_state failed for %s %s', kind, attempt_id)
        return 0


@shared_task(name='intelligence.refresh_learner_state', time_limit=1800)
def refresh_learner_state():
    """Nightly: re-decay stale states and catch up on any missed enqueues.

    Two sweeps:
    - states not recomputed in 24h get fresh retention/mastery decay;
    - attempts finalized in the last 48h whose enqueue may have been lost
      (broker blip) are re-processed — a no-op when nothing was missed.
    """
    from datetime import timedelta

    from django.utils import timezone

    from .models import LearnerConceptState
    from .services import state

    refreshed = 0
    cutoff = timezone.now() - timedelta(hours=24)
    stale = (
        LearnerConceptState.objects.filter(computed_at__lt=cutoff, effective_evidence__gt=0)
        .select_related('student__user', 'concept')[:5000]
    )
    for row in stale:
        state.recompute_state(row.student, row.concept)
        refreshed += 1

    caught_up = 0
    recent = timezone.now() - timedelta(hours=48)
    from .models import LearningEvent

    pairs = (
        LearningEvent.objects.filter(created_at__gte=recent)
        .values_list('attempt_kind', 'attempt_id').distinct()
    )
    for kind, attempt_id in pairs:
        if kind in ('quiz', 'mock') and attempt_id:
            caught_up += state.update_for_attempt(kind, attempt_id)

    logger.info('intelligence.refresh_learner_state: %d refreshed, %d catch-up concepts',
                refreshed, caught_up)
    return refreshed


@shared_task(name='intelligence.recompute_item_stats', time_limit=1800)
def recompute_item_stats():
    """Nightly: rebuild empirical item statistics from the event log."""
    from .services import itemstats

    count = itemstats.recompute_all()
    logger.info('intelligence.recompute_item_stats: %d item(s)', count)
    return count


# ─────────────────────────────────────────────────────────────────────────────
# Practice recommendations (default queue — pure tag algebra)
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(name='intelligence.recompute_recommendations', max_retries=0)
def recompute_recommendations(student_id, course_id=None):
    """Refresh a student's suggested practice sets (one course or all)."""
    from exams.models import Course
    from users.models import CourseEnrollment, StudentProfile

    from . import recommendation

    student = StudentProfile.objects.filter(id=student_id).select_related('user').first()
    if student is None:
        return 0
    if course_id:
        courses = list(Course.objects.filter(id=course_id))
    else:
        courses = list(Course.objects.filter(
            id__in=CourseEnrollment.objects.filter(
                student=student, status='approved',
            ).values_list('course_id', flat=True),
            status='active',
        ))
    built = 0
    for course in courses:
        try:
            built += len(recommendation.refresh_recommendations(student, course))
        except Exception:
            logger.exception('intelligence.recompute_recommendations failed for %s/%s',
                             student_id, course.id)
    return built


# ─────────────────────────────────────────────────────────────────────────────
# AI subjective grading (queue: aigen)
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(
    name='intelligence.grade_subjective', bind=True, max_retries=0,
    queue='aigen', soft_time_limit=1500, time_limit=1560,
)
def grade_subjective_answers(self, attempt_id):
    """AI-grade the pending subjective answers of one mock attempt."""
    from quiz.models import MockTestAttempt

    from .services import grading

    attempt = (
        MockTestAttempt.objects.filter(id=attempt_id)
        .select_related('student__user', 'mock_test').first()
    )
    if attempt is None:
        logger.warning('intelligence.grade_subjective: attempt %s not found', attempt_id)
        return None
    counts = grading.grade_attempt(attempt)
    logger.info('intelligence.grade_subjective %s: %s', attempt_id, counts)
    return counts


@shared_task(name='intelligence.grading_sweep', queue='aigen', time_limit=300)
def grading_sweep():
    """Every 15 min: re-enqueue attempts whose AI grading never ran/finished.

    Covers worker crashes and enqueue failures. Only attempts from tenants
    with ai_grading enabled, finalized in the last 7 days, that still have
    a pending subjective answer the AI has not looked at.
    """
    from datetime import timedelta

    from django.utils import timezone

    from quiz.models import MockTestAttempt

    from .hooks import _feature_enabled

    recent = timezone.now() - timedelta(days=7)
    attempts = (
        MockTestAttempt.objects.filter(
            grading_status='pending_manual',
            completed_at__gte=recent,
            item_answers__needs_manual_grading=True,
            item_answers__ai_confidence__isnull=True,
            item_answers__item__item_type='subjective',
        )
        .select_related('student__user__tenant')
        .distinct()[:200]
    )
    queued = 0
    for attempt in attempts:
        if _feature_enabled(attempt.student.user.tenant, 'ai_grading'):
            grade_subjective_answers.delay(str(attempt.id))
            queued += 1
    if queued:
        logger.info('intelligence.grading_sweep: %d attempt(s) queued', queued)
    return queued


# ─────────────────────────────────────────────────────────────────────────────
# Practice question generation (queue: aigen)
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(
    name='intelligence.practice_generation', bind=True, max_retries=0,
    queue='aigen', soft_time_limit=1500, time_limit=1560,
)
def run_practice_generation(self, job_id):
    """Generate novel practice questions for one diagnosed gap."""
    from .models import PracticeGenerationJob
    from .services import practice_generation

    claimed = PracticeGenerationJob.objects.filter(
        id=job_id, status=PracticeGenerationJob.STATUS_PENDING,
    ).update(status=PracticeGenerationJob.STATUS_GENERATING)
    if not claimed:
        logger.info('intelligence.practice_generation: %s not runnable, skipping', job_id)
        return None

    job = (
        PracticeGenerationJob.objects.filter(id=job_id)
        .select_related('tenant', 'course').first()
    )
    if job is None:
        return None
    try:
        practice_generation.run_job(job)
    except practice_generation.GenerationError as exc:
        PracticeGenerationJob.objects.filter(id=job_id).update(
            status=PracticeGenerationJob.STATUS_FAILED, error=str(exc)[:1000],
        )
        logger.info('intelligence.practice_generation %s reported: %s', job_id, exc)
    except Exception:  # noqa: BLE001 — never leave a job stuck 'generating'
        logger.exception('intelligence.practice_generation failed for %s', job_id)
        PracticeGenerationJob.objects.filter(id=job_id).update(
            status=PracticeGenerationJob.STATUS_FAILED,
            error='Generation failed unexpectedly.',
        )
    return str(job_id)


# ─────────────────────────────────────────────────────────────────────────────
# LLM tagging (queue: aigen)
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(
    name='intelligence.tag_items', bind=True, max_retries=0,
    queue='aigen', soft_time_limit=1500, time_limit=1560,
)
def tag_items_for_tenant(self, tenant_id, limit=200):
    """One budget-gated tagging pass for one tenant."""
    from core.models import Tenant

    from .services import tagging

    tenant = Tenant.objects.filter(id=tenant_id).first()
    if tenant is None:
        logger.warning('intelligence.tag_items: tenant %s not found', tenant_id)
        return 0
    try:
        return tagging.run_tagging_for_tenant(tenant, limit=limit)
    except Exception as exc:  # noqa: BLE001 — a failed sweep just waits for the next one
        logger.warning('intelligence.tag_items: tenant %s failed: %s', tenant_id, exc)
        return 0


@shared_task(name='intelligence.tagging_sweep', queue='aigen', time_limit=300)
def tagging_sweep():
    """Weekly: enqueue a tagging pass for every tenant with untagged items."""
    from core.models import Tenant
    from quiz.models import MockTestItem, Question

    tenant_ids = set(
        Question.objects.filter(tagging_status__in=['', 'stale'], tenant__isnull=False)
        .values_list('tenant_id', flat=True).distinct()
    ) | set(
        MockTestItem.objects.filter(tagging_status__in=['', 'stale'], tenant__isnull=False)
        .values_list('tenant_id', flat=True).distinct()
    )
    active = set(Tenant.objects.filter(id__in=tenant_ids, is_active=True)
                 .values_list('id', flat=True))
    for tenant_id in active:
        tag_items_for_tenant.delay(str(tenant_id))
    logger.info('intelligence.tagging_sweep: %d tenant(s) queued', len(active))
    return len(active)
