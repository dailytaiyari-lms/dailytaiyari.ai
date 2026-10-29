"""Celery tasks for the learner-intelligence layer.

Two kinds of work, on two queues:
- LLM work (tagging) runs on ``aigen`` beside the course/mock builders, with
  its own generous time limits;
- statistical work (learner state, diagnosis, item stats, recommendations)
  runs on its own ``intelligence`` queue and worker, so a burst of submits
  or a 30-minute nightly job never holds up the default queue (coding judge,
  notifications). All of it is recompute-from-events, so redelivery or a
  double-enqueue is harmless.
"""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Learner state + item stats (queue: intelligence — statistical)
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(name='intelligence.update_learner_state', max_retries=0, queue='intelligence')
def update_learner_state_for_attempt(kind, attempt_id):
    """Recompute the concept states an attempt touched. Idempotent."""
    from .services import state

    try:
        return state.update_for_attempt(kind, attempt_id)
    except Exception:  # noqa: BLE001 — the nightly refresh catches up
        logger.exception('intelligence.update_learner_state failed for %s %s', kind, attempt_id)
        return 0


@shared_task(name='intelligence.diagnose_and_update_state', max_retries=0, queue='intelligence')
def diagnose_and_update_state(kind, attempt_id):
    """Diagnose an attempt's responses, then recompute the states it touched.

    Ordered on purpose: state reads diagnosis weights. A diagnosis failure
    never blocks the state update (weights fall back to 1.0) and the nightly
    sweep retries it.
    """
    from .services import diagnose, state

    try:
        diagnose.diagnose_attempt(kind, attempt_id)
    except Exception:  # noqa: BLE001
        logger.exception('intelligence.diagnose failed for %s %s', kind, attempt_id)
    if kind not in ('quiz', 'mock'):
        return 0
    try:
        return state.update_for_attempt(kind, attempt_id)
    except Exception:  # noqa: BLE001 — the nightly refresh catches up
        logger.exception('intelligence.update_learner_state failed for %s %s', kind, attempt_id)
        return 0


@shared_task(name='intelligence.refresh_learner_state', time_limit=1800, queue='intelligence')
def refresh_learner_state():
    """Nightly: re-decay stale states and catch up on any missed enqueues.

    Two sweeps:
    - states not recomputed in 24h get fresh retention/mastery decay;
    - attempts finalized in the last 48h whose enqueue may have been lost
      (broker blip) are re-processed — a no-op when nothing was missed.
    """
    from datetime import timedelta

    from django.utils import timezone

    from .api import enabled_tenant_ids
    from .models import LearnerConceptState
    from .services import state

    # Only tenants with the learning layer on: backfilled events of a tenant
    # that has not opted in must stay inert.
    enabled = enabled_tenant_ids()
    refreshed = 0
    cutoff = timezone.now() - timedelta(hours=24)
    stale = (
        LearnerConceptState.objects.filter(
            computed_at__lt=cutoff, effective_evidence__gt=0,
            student__user__tenant_id__in=enabled,
        )
        .select_related('student__user', 'concept')[:5000]
    )
    for row in stale:
        state.recompute_state(row.student, row.concept)
        refreshed += 1

    caught_up = 0
    recent = timezone.now() - timedelta(hours=48)
    from .models import LearningEvent, ResponseDiagnosis
    from .services import diagnose
    from .versions import CLASSIFIER_VERSION

    pairs = list(
        LearningEvent.objects.filter(created_at__gte=recent, tenant_id__in=enabled)
        .values_list('attempt_kind', 'attempt_id').distinct()
    )
    for kind, attempt_id in pairs:
        if not attempt_id:
            continue
        current = ResponseDiagnosis.objects.filter(
            attempt_kind=kind, attempt_id=attempt_id, classifier_version=CLASSIFIER_VERSION,
        ).exists()
        if not current:
            try:
                diagnose.diagnose_attempt(kind, attempt_id)
            except Exception:  # noqa: BLE001
                logger.exception('nightly diagnose failed for %s %s', kind, attempt_id)
        if kind in ('quiz', 'mock'):
            try:
                caught_up += state.update_for_attempt(kind, attempt_id)
            except Exception:  # noqa: BLE001 — one bad attempt must not stop the sweep
                logger.exception('nightly state update failed for %s %s', kind, attempt_id)

    logger.info('intelligence.refresh_learner_state: %d refreshed, %d catch-up concepts',
                refreshed, caught_up)
    return refreshed


@shared_task(name='intelligence.recompute_item_stats', time_limit=1800, queue='intelligence')
def recompute_item_stats():
    """Nightly: rebuild empirical item statistics from the event log.

    Only for tenants with the learning layer on, so backfilled events of a
    tenant that has not opted in never produce ItemStats rows.
    """
    from core.models import Tenant

    from .api import enabled_tenant_ids
    from .services import itemstats

    count = 0
    for tenant in Tenant.objects.filter(id__in=enabled_tenant_ids()):
        count += itemstats.recompute_all(tenant=tenant)
    logger.info('intelligence.recompute_item_stats: %d item(s)', count)
    return count


# ─────────────────────────────────────────────────────────────────────────────
# Practice recommendations (queue: intelligence — pure tag algebra)
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(name='intelligence.recompute_recommendations', max_retries=0, queue='intelligence')
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
    """One budget-gated tagging pass for one tenant.

    A no-op (0) for a tenant without the learning layer, so neither the weekly
    sweep nor the admin "run tagging" button spends its AI budget.
    """
    from core.models import Tenant

    from .api import intelligence_enabled
    from .services import tagging_sweep

    tenant = Tenant.objects.filter(id=tenant_id).first()
    if tenant is None:
        logger.warning('intelligence.tag_items: tenant %s not found', tenant_id)
        return 0
    if not intelligence_enabled(tenant):
        logger.info('intelligence.tag_items: tenant %s has no learning feature on, skipping',
                    tenant_id)
        return 0
    try:
        result = tagging_sweep.run_sweep(tenant, limit=limit)
        return result['v2'] + result['v1']
    except Exception as exc:  # noqa: BLE001 — a failed sweep just waits for the next one
        logger.warning('intelligence.tag_items: tenant %s failed: %s', tenant_id, exc)
        return 0


@shared_task(name='intelligence.tagging_sweep', queue='aigen', time_limit=300)
def tagging_sweep():
    """Weekly: enqueue a tagging pass for every enabled tenant with untagged items or a syllabus tree.

    Only tenants with the learning layer on (see ``api.intelligence_enabled``)
    are considered; the rest are never tagged and never spend AI budget.
    Treed tenants are always enqueued, so v2 work starts after a tree is created
    or edited even when every item is already v1-tagged; ``run_sweep`` selects
    precisely, so an idle pass is cheap.
    """
    from core.models import Tenant
    from quiz.models import MockTestItem, Question

    from .api import intelligence_enabled
    from .models import SyllabusNode

    tenant_ids = set(
        SyllabusNode.objects.filter(status='active', tenant__isnull=False)
        .values_list('tenant_id', flat=True).distinct()
    ) | set(
        Question.objects.filter(tagging_status__in=['', 'stale'], tenant__isnull=False)
        .values_list('tenant_id', flat=True).distinct()
    ) | set(
        MockTestItem.objects.filter(tagging_status__in=['', 'stale'], tenant__isnull=False)
        .values_list('tenant_id', flat=True).distinct()
    )
    active = {
        tenant.id for tenant in Tenant.objects.filter(id__in=tenant_ids, is_active=True)
        if intelligence_enabled(tenant)
    }
    for tenant_id in active:
        tag_items_for_tenant.delay(str(tenant_id))
    logger.info('intelligence.tagging_sweep: %d tenant(s) queued', len(active))
    return len(active)



# ─────────────────────────────────────────────────────────────────────────────
# Syllabus tools (queue: aigen) — spec 2B §5
# ─────────────────────────────────────────────────────────────────────────────

TAGGING_RUN_LIMIT = 500


def _claim(model, job_id):
    """queued → running, atomically. None when already claimed or gone."""
    from django.utils import timezone

    claimed = model.objects.filter(id=job_id, status=model.STATUS_QUEUED).update(
        status=model.STATUS_RUNNING, started_at=timezone.now())
    if not claimed:
        return None
    return model.objects.filter(id=job_id).select_related('tenant', 'course').first()


def _finish(job, *, status, summary=None, error='', call=None):
    from django.utils import timezone

    job.status = status
    job.summary = summary if summary is not None else job.summary
    job.error = error[:1000]
    if call is not None:
        try:
            job.tokens = call.meter.usage.total_tokens
            job.cost_usd = call.cost_usd()
        except Exception:  # noqa: BLE001 — metering must never fail the job
            logger.exception('syllabus job %s: metering failed', job.id)
    job.finished_at = timezone.now()
    job.save()


def _run_syllabus_job(model, job_id, work, label):
    """Shared worker shell: claim, gate, budget, run, record."""
    from coursegen.generation import GenerationError, _check_budget

    from .services import llm

    job = _claim(model, job_id)
    if job is None:
        logger.info('%s: %s not runnable, skipping', label, job_id)
        return None
    call = None
    try:
        if not job.tenant.get_features().get('syllabus_tools'):
            raise GenerationError('Syllabus & tagging tools are turned off for this academy.')
        _check_budget(job.tenant)
        call = llm.tenant_tagging_call(job.tenant)
        summary = work(job, call)
        _finish(job, status=model.STATUS_DONE, summary=summary, call=call)
    except GenerationError as exc:
        _finish(job, status=model.STATUS_FAILED, error=str(exc), call=call)
    except Exception:  # noqa: BLE001 — never leave a job 'running'
        logger.exception('%s failed for %s', label, job_id)
        _finish(job, status=model.STATUS_FAILED, error='The run failed unexpectedly.', call=call)
    return str(job_id)


@shared_task(
    name='intelligence.build_course_tree', bind=True, max_retries=0,
    queue='aigen', soft_time_limit=1500, time_limit=1560,
)
def run_tree_build(self, job_id):
    """Build or extend a custom course's syllabus tree (one TreeBuildJob)."""
    from .models import TreeBuildJob
    from .services import course_tree

    def work(job, call):
        packs = job.options.get('packs') if isinstance(job.options, dict) else None
        return course_tree.build_course_tree(job.course, call=call, packs=packs)

    return _run_syllabus_job(TreeBuildJob, job_id, work, 'intelligence.build_course_tree')


@shared_task(
    name='intelligence.tagging_run', bind=True, max_retries=0,
    queue='aigen', soft_time_limit=1500, time_limit=1560,
)
def run_tagging_run(self, run_id):
    """Tag a course's not-current items with tagger v2 (one TaggingRun)."""
    from coursegen.generation import GenerationError

    from .models import SyllabusNode, TaggingRun
    from .services import tagging_sweep, taxonomy

    def work(run, call):
        subject_ids = set(
            SyllabusNode.objects.filter(subject__course=run.course, level='topic', status='active')
            .values_list('subject_id', flat=True))
        if not subject_ids:
            raise GenerationError('Build or map a syllabus tree for this course first.')
        if taxonomy.current_release() is None:
            raise GenerationError('No tag vocabulary is loaded. Run manage.py sync_taxonomy.')
        # Seeded: tag_v2_for_tenant leaves this empty when there is nothing to tag.
        stats = {'tagged': 0, 'needs_review': 0, 'failed': 0, 'locked': 0}
        tagging_sweep.tag_v2_for_tenant(
            run.tenant, subject_ids, call, limit=TAGGING_RUN_LIMIT, stats=stats)
        return stats

    return _run_syllabus_job(TaggingRun, run_id, work, 'intelligence.tagging_run')


@shared_task(
    name='intelligence.retag_item', max_retries=0,
    queue='aigen', soft_time_limit=280, time_limit=300,
)
def retag_item(kind, item_id):
    """Re-tag one bank question ('bank') or mock item ('item') now."""
    from coursegen.generation import GenerationError, _check_budget
    from quiz.models import MockTestItem, Question

    from .services import llm, tagging_sweep

    model = {'bank': Question, 'item': MockTestItem}.get(kind)
    item = model.objects.filter(id=item_id).select_related('tenant').first() if model else None
    if item is None or not item.tenant.get_features().get('syllabus_tools'):
        return 0
    try:
        _check_budget(item.tenant)
        return tagging_sweep.tag_one_item(item, llm.tenant_tagging_call(item.tenant))
    except GenerationError as exc:
        logger.info('intelligence.retag_item %s %s: %s', kind, item_id, exc)
        return 0
    except Exception:  # noqa: BLE001 — the item stays stale; the weekly sweep retries
        logger.exception('intelligence.retag_item failed for %s %s', kind, item_id)
        return 0


@shared_task(name='intelligence.recompute_concept_states', max_retries=0, queue='intelligence')
def recompute_concept_states(concept_id):
    """Recompute every learner state on one concept (after a subtopic merge)."""
    from django.db.models import Q

    from users.models import StudentProfile

    from .models import Concept, ConceptLink, LearningEvent
    from .services import state

    concept = Concept.objects.filter(id=concept_id).first()
    if concept is None:
        return 0
    links = ConceptLink.objects.filter(concept=concept)
    question_ids = [qid for qid in links.values_list('question_id', flat=True) if qid]
    item_ids = [mid for mid in links.values_list('mock_item_id', flat=True) if mid]
    student_ids = (
        LearningEvent.objects.filter(Q(question_id__in=question_ids) | Q(mock_item_id__in=item_ids))
        .values_list('student_id', flat=True).distinct()
    )
    done = 0
    for student in StudentProfile.objects.filter(id__in=list(student_ids)):
        state.recompute_state(student, concept)
        done += 1
    return done
