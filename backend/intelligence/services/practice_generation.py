"""Novel practice-question generation for thin pools.

When the recommendation engine diagnoses a gap but the tagged pool has too
few healthy questions, it requests generation here. Generated items become
real bank Questions (tagged at birth, provenance in GeneratedItem) so they
are reusable for the next student with the same gap — generation happens
once per gap, not once per student.

Guardrails: per-tenant daily caps on jobs and items, a 30-day cooldown per
deficit signature, budget gating, and a strict normalizer that drops (never
repairs) malformed items. Empirically bad items are later excluded by the
recommendation pool filters and retirable from the insights page.
"""
import json
import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from chatbot.models import AIUsageRecord
from coursegen.generation import (
    GenerationError, _call, _check_budget, _Meter, extract_json, resolve_for_admin,
)

from intelligence.models import GeneratedItem, PracticeGenerationJob
from intelligence.services.itemtags import set_item_tags
from intelligence.services.normalize import normalize_concept_label

logger = logging.getLogger(__name__)

ITEMS_PER_JOB = 8
MAX_JOBS_PER_TENANT_PER_DAY = 20
MAX_ITEMS_PER_TENANT_PER_DAY = 160
SIGNATURE_COOLDOWN_DAYS = 30

GENERATE_SYSTEM = """
You write practice questions for an Indian online learning platform.
Generate multiple-choice questions targeting one specific learning gap.

QUALITY RULES:
- Exactly 4 options, exactly one correct.
- Every distractor must correspond to a specific, common mistake a student
  actually makes — never filler. When a misconception is stated below, at
  least one distractor must embody exactly that misconception.
- Never "All of the above" / "None of the above". Vary the correct position.
- Every question needs an explanation covering why the right answer is right
  AND what mistake each distractor represents.
- Stay strictly inside the stated concepts and difficulty.

Return ONE JSON object, no markdown fences:
{"items": [{"question_text": "...",
            "options": [{"text": "...", "is_correct": true}, ...],
            "explanation": "...",
            "difficulty": "easy|medium|hard",
            "concepts": ["primary concept", "secondary (only if truly tested)"],
            "cognitive_type": "recall|application|multi_concept",
            "misconception_targeted": "the mistake a distractor embodies, or \\"\\""}]}
""".strip()


def _today_start():
    return timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)


def request_generation(course, deficit, *, have=0):
    """Queue a generation job for a diagnosed gap, unless a cap says no.

    Called by the recommendation engine when a pool is thin. Returns the job
    or None. Never raises — a refused generation just means the deficit waits.
    """
    tenant = course.tenant
    jobs_today = PracticeGenerationJob.objects.filter(
        tenant=tenant, created_at__gte=_today_start(),
    ).count()
    if jobs_today >= MAX_JOBS_PER_TENANT_PER_DAY:
        logger.info('practicegen: daily job cap reached for tenant %s', tenant.id)
        return None

    items_today = GeneratedItem.objects.filter(
        tenant=tenant, created_at__gte=_today_start(),
    ).count()
    if items_today >= MAX_ITEMS_PER_TENANT_PER_DAY:
        logger.info('practicegen: daily item cap reached for tenant %s', tenant.id)
        return None

    cooldown = timezone.now() - timedelta(days=SIGNATURE_COOLDOWN_DAYS)
    if PracticeGenerationJob.objects.filter(
        tenant=tenant, deficit_signature=deficit['signature'], created_at__gte=cooldown,
    ).exclude(status=PracticeGenerationJob.STATUS_FAILED).exists():
        return None  # already generated (or generating) for this exact gap

    concept = deficit.get('concept')
    job = PracticeGenerationJob.objects.create(
        tenant=tenant,
        course=course,
        deficit_kind=deficit['kind'],
        deficit_signature=deficit['signature'],
        options={
            'count': ITEMS_PER_JOB,
            'have': have,
            'slots': deficit.get('slots', {}),
        },
    )
    if concept is not None:
        job.target_concepts.add(concept)

    try:
        from intelligence.tasks import run_practice_generation
        run_practice_generation.delay(str(job.id))
    except Exception:
        logger.exception('practicegen: failed to enqueue job %s', job.id)
    return job


# ─────────────────────────────────────────────────────────────────────────────
# Generation (runs on the aigen worker)
# ─────────────────────────────────────────────────────────────────────────────

def _difficulty_for(deficit_kind, slots):
    if deficit_kind == 'low_mastery':
        return 'easy' if (slots.get('pct') or 50) < 35 else 'medium'
    if deficit_kind == 'transfer_gap':
        return 'medium'
    return 'medium'


def _cognitive_for(deficit_kind):
    return 'multi_concept' if deficit_kind == 'transfer_gap' else 'application'


def _gap_description(job):
    slots = (job.options or {}).get('slots', {})
    kind = job.deficit_kind
    concept_names = [c.name for c in job.target_concepts.all()]
    lines = [f'CONCEPTS TO TEST: {", ".join(concept_names) or "see below"}']
    if kind == 'low_mastery':
        lines.append('GAP: the student group scores poorly on this concept — '
                     'build understanding from the target difficulty up.')
    elif kind == 'retention':
        lines.append('GAP: previously learned but fading — write refresh questions '
                     'that require actual recall, not recognition.')
    elif kind == 'misconception':
        lines.append('GAP: students repeatedly pick the same wrong answer. '
                     'Each question must expose and correct that mistake.')
    elif kind == 'transfer_gap':
        lines.append('GAP: students handle these concepts in isolation but fail '
                     'when they must be combined. EVERY question must genuinely '
                     'require combining the listed concepts (cognitive_type '
                     '"multi_concept").')
    lines.append(f'DIFFICULTY: {_difficulty_for(kind, slots)}')
    lines.append(f'COUNT: {(job.options or {}).get("count", ITEMS_PER_JOB)}')
    return '\n'.join(lines)


def _syllabus_context(job):
    course = job.course
    subjects = list(course.subjects.all()[:6])
    lines = [f'COURSE: {course.name}']
    for concept in job.target_concepts.select_related('subject'):
        lines.append(f'- Concept "{concept.name}" (subject: {concept.subject.name})')
        if concept.description:
            lines.append(f'  {concept.description[:300]}')
        for topic in concept.topics.all()[:5]:
            if topic.description:
                lines.append(f'  Topic {topic.name}: {topic.description[:200]}')
            else:
                lines.append(f'  Topic {topic.name}')
    if not job.target_concepts.exists():
        for subject in subjects:
            lines.append(f'- Subject: {subject.name}')
    return '\n'.join(lines[:60])


def _existing_stems(job):
    """Normalized stems of questions already linked to the target concepts."""
    from quiz.models import Question

    stems = set()
    concept_ids = list(job.target_concepts.values_list('id', flat=True))
    if not concept_ids:
        return stems
    texts = Question.objects.filter(
        concept_links__concept_id__in=concept_ids,
    ).values_list('question_text', flat=True)[:500]
    for text in texts:
        stems.add(' '.join((text or '').split()).casefold())
    return stems


def normalize_generated_items(raw_items, *, existing_stems):
    """Strict normalization: drop, never repair. Returns clean item dicts."""
    items = []
    seen = set(existing_stems)
    for raw in raw_items or []:
        if not isinstance(raw, dict):
            continue
        text = str(raw.get('question_text') or '').strip()
        stem = ' '.join(text.split()).casefold()
        if len(text) < 15 or stem in seen:
            continue
        options = raw.get('options')
        if not isinstance(options, list) or len(options) != 4:
            continue
        cleaned_options = []
        correct_count = 0
        for option in options:
            if not isinstance(option, dict):
                break
            option_text = str(option.get('text') or '').strip()
            if not option_text:
                break
            is_correct = bool(option.get('is_correct'))
            correct_count += int(is_correct)
            cleaned_options.append({'text': option_text[:600], 'is_correct': is_correct})
        if len(cleaned_options) != 4 or correct_count != 1:
            continue
        explanation = str(raw.get('explanation') or '').strip()
        if not explanation:
            continue
        concepts = [
            label for label in (raw.get('concepts') or [])
            if isinstance(label, str) and normalize_concept_label(label)
        ][:4]
        if not concepts:
            continue
        difficulty = raw.get('difficulty')
        cognitive = raw.get('cognitive_type')
        items.append({
            'question_text': text[:4000],
            'options': cleaned_options,
            'explanation': explanation[:4000],
            'difficulty': difficulty if difficulty in ('easy', 'medium', 'hard') else 'medium',
            'concepts': concepts,
            'cognitive_type': cognitive if cognitive in ('recall', 'application', 'multi_concept') else 'application',
            'misconception_targeted': str(raw.get('misconception_targeted') or '')[:300],
        })
        seen.add(stem)
    return items


@transaction.atomic
def _apply_items(job, items):
    """Write normalized items as published bank Questions with provenance."""
    from quiz.models import Question, QuestionOption

    tenant = job.tenant
    course = job.course
    # Anchor subject/topic from the primary target concept.
    concept = job.target_concepts.select_related('subject').first()
    subject = concept.subject if concept else course.subjects.first()
    topic = concept.topics.first() if concept else None
    if subject is None:
        raise GenerationError('Course has no subject to attach questions to.')
    if topic is None:
        topic = subject.topics.first()
    if topic is None:
        raise GenerationError('Subject has no topic to attach questions to.')

    created = []
    for item in items:
        correct_index = next(
            i for i, option in enumerate(item['options']) if option['is_correct']
        )
        question = Question.objects.create(
            tenant=tenant,
            topic=topic,
            subject=subject,
            question_text=item['question_text'],
            question_type='mcq',
            difficulty=item['difficulty'],
            status='published',
            correct_answer=str(correct_index),
            explanation=item['explanation'],
            source='AI Practice',
            marks=1,
        )
        question.courses.set([course])
        for order, option in enumerate(item['options']):
            QuestionOption.objects.create(
                tenant=tenant, question=question,
                option_text=option['text'], is_correct=option['is_correct'], order=order,
            )
        set_item_tags(
            question,
            concept_labels=item['concepts'],
            subject=subject,
            topic=topic,
            source='generator',
            difficulty=item['difficulty'],
            cognitive_type=item['cognitive_type'],
            overwrite_difficulty=True,
        )
        GeneratedItem.objects.create(
            tenant=tenant,
            question=question,
            job=job,
            deficit_kind=job.deficit_kind,
            deficit_signature=job.deficit_signature,
            target_misconception=item['misconception_targeted'],
        )
        created.append(str(question.id))
    return created


def run_job(job):
    """Generate, normalize and (auto-)apply one job. Raises GenerationError."""
    tenant = job.tenant
    _check_budget(tenant)
    resolved = resolve_for_admin(tenant, max_tokens=8000)
    meter = _Meter()

    user = f'{_syllabus_context(job)}\n\n{_gap_description(job)}'
    content = _call(resolved, GENERATE_SYSTEM, user, meter, tenant,
                    feature=AIUsageRecord.FEATURE_PRACTICEGEN)
    parsed = extract_json(content)
    items = normalize_generated_items(
        parsed.get('items'), existing_stems=_existing_stems(job),
    )

    job.provider = resolved.provider
    job.model = resolved.model
    job.total_tokens = meter.usage.total_tokens
    job.generation_ms = meter.elapsed_ms
    job.draft = {'items': items, 'raw_count': len(parsed.get('items') or [])}

    if not items:
        job.status = PracticeGenerationJob.STATUS_FAILED
        job.error = 'No item survived normalization.'
        job.save()
        return job

    if job.auto_apply:
        created = _apply_items(job, items)
        job.status = PracticeGenerationJob.STATUS_APPLIED
        job.applied_at = timezone.now()
        job.applied_summary = {'created': len(created), 'question_ids': created}
    else:
        job.status = PracticeGenerationJob.STATUS_PREVIEW
    job.save()
    return job
