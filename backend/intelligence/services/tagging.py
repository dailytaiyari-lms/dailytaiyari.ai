"""LLM item tagging: concepts, difficulty prior and cognitive type for items
the generators didn't (or couldn't) tag — hand-typed questions, pre-existing
banks, multi-subject mock tests, and items edited into staleness.

Cost shape:
- items are batched 12 per completion, on the tenant's cheap ``tagging_model``
  when one is configured;
- every result is cached by (content hash, prompt version, model), so a
  duplicated question — common across mock papers — never pays twice;
- sweeps are budget-gated with the same monthly check as the generators.
"""
import json
import logging

from chatbot import resolver
from chatbot.models import AIUsageRecord
from coursegen.generation import GenerationError, _call, _Meter, resolve_for_admin, extract_json

from intelligence.models import AITaggingResult
from intelligence.versions import TAGGER_PROMPT_VERSION
from intelligence.services.itemtags import content_hash_for, set_item_tags

logger = logging.getLogger(__name__)

BATCH_SIZE = 12
MAX_CANDIDATE_CONCEPTS = 150
MAX_TOPICS = 120

TAG_SYSTEM = """
You are an assessment metadata expert for an Indian online learning platform.
You will receive a syllabus context and a list of assessment questions.
For each question, identify:

- "concepts": 1-4 short concept names the question actually tests, most
  central first. STRONGLY prefer a name from CANDIDATE CONCEPTS when one fits;
  invent a new name only when nothing listed fits.
- "topic": the single best-matching topic name from the TOPICS list ("" if none fits).
- "difficulty": "easy" | "medium" | "hard" for the stated audience.
- "cognitive_type": "recall" (remembering a fact/definition),
  "application" (applying one concept), or "multi_concept" (solving genuinely
  requires combining two or more concepts — then list each in "concepts").

Return ONE JSON object, no markdown fences, no commentary:
{"items": [{"id": "<id exactly as given>", "concepts": ["..."], "topic": "...",
            "difficulty": "...", "cognitive_type": "..."}]}
Include every question id you were given exactly once.
""".strip()


def _resolve_tagging_model(tenant):
    ai_settings = resolver.get_ai_settings(tenant)
    override = (ai_settings.tagging_model or '').strip()
    resolved = resolve_for_admin(tenant, model=override or None, max_tokens=4000)
    if override and resolved.source == AIUsageRecord.SOURCE_TENANT:
        # resolve_for_admin only honours the model override on the platform
        # path; for a tenant's own key the config model wins, so re-point it.
        resolved.model = override
    return resolved


def _model_ref(resolved):
    return f'{resolved.provider}:{resolved.model}'


def _item_payload(item_id, item):
    from quiz.models import MockTestItem

    if isinstance(item, MockTestItem):
        item_type = item.item_type
        options = [str(o.get('text') or '') for o in (item.options or [])]
    else:
        item_type = item.question_type
        options = list(item.options.order_by('order').values_list('option_text', flat=True))
    return {
        'id': str(item_id),
        'type': item_type,
        'question': (item.question_text or '')[:2000],
        'options': [o[:300] for o in options[:8]],
    }


def _context_block(subject_names, topics, candidates):
    lines = ['SYLLABUS SUBJECT(S): ' + ', '.join(subject_names)]
    if topics:
        lines.append('TOPICS:')
        lines.extend(f'- {name}' for name in topics[:MAX_TOPICS])
    if candidates:
        lines.append('CANDIDATE CONCEPTS (prefer these names):')
        lines.extend(f'- {name}' for name in candidates[:MAX_CANDIDATE_CONCEPTS])
    return '\n'.join(lines)


def _cached_result(tenant, content_hash, model_ref):
    row = AITaggingResult.objects.filter(
        tenant=tenant, content_hash=content_hash,
        prompt_version=TAGGER_PROMPT_VERSION, model_ref=model_ref,
    ).first()
    return row.result if row else None


def _store_result(tenant, content_hash, model_ref, result):
    AITaggingResult.objects.get_or_create(
        tenant=tenant, content_hash=content_hash,
        prompt_version=TAGGER_PROMPT_VERSION, model_ref=model_ref,
        defaults={'result': result},
    )


def _candidate_concepts(tenant, subjects):
    from intelligence.models import Concept

    return list(
        Concept.objects.filter(tenant=tenant, subject__in=subjects, status='active')
        .order_by('-created_at')
        .values_list('name', flat=True)[:MAX_CANDIDATE_CONCEPTS]
    )


def _apply_result(item, result, *, subject, topics_by_name, tagger_version,
                  allow_difficulty):
    """Write one item's tag payload through set_item_tags. Returns True on success."""
    topic = topics_by_name.get((result.get('topic') or '').strip().casefold())
    resolved_subject = subject or (topic.subject if topic else None)
    if resolved_subject is None:
        # Without a subject there is no concept namespace — leave for a later
        # sweep once the item (or its test's course) can pin one down.
        return False
    set_item_tags(
        item,
        concept_labels=[c for c in (result.get('concepts') or []) if isinstance(c, str)][:4],
        subject=resolved_subject,
        topic=topic,
        source='llm_tagger',
        difficulty=(result.get('difficulty') if allow_difficulty else None),
        cognitive_type=result.get('cognitive_type'),
        tagger_version=tagger_version,
    )
    return True


def _tag_batch(tenant, items_by_id, *, subject, subjects, topics_by_name, allow_difficulty):
    """Tag one batch of items (dict id → item). Returns count tagged."""
    if not items_by_id:
        return 0

    resolved = _resolve_tagging_model(tenant)
    model_ref = _model_ref(resolved)
    tagger_version = f'{TAGGER_PROMPT_VERSION}:{model_ref}'

    tagged = 0
    pending = {}
    hashes = {}
    for item_id, item in items_by_id.items():
        content_hash = content_hash_for(item)
        hashes[item_id] = content_hash
        cached = _cached_result(tenant, content_hash, model_ref)
        if cached is not None:
            if _apply_result(item, cached, subject=subject, topics_by_name=topics_by_name,
                             tagger_version=tagger_version, allow_difficulty=allow_difficulty):
                tagged += 1
            continue
        pending[item_id] = item

    if not pending:
        return tagged

    meter = _Meter()
    topic_names = sorted({name for name in topics_by_name}, key=str)
    context = _context_block(
        [s.name for s in subjects],
        [topics_by_name[name].name for name in topic_names],
        _candidate_concepts(tenant, subjects),
    )
    payload = {'questions': [_item_payload(iid, item) for iid, item in pending.items()]}
    user = f'{context}\n\nQUESTIONS:\n{json.dumps(payload, ensure_ascii=False)}'

    content = _call(resolved, TAG_SYSTEM, user, meter, tenant,
                    feature=AIUsageRecord.FEATURE_ITEMTAG)
    parsed = extract_json(content)

    for entry in parsed.get('items') or []:
        if not isinstance(entry, dict):
            continue
        item = pending.get(str(entry.get('id')))
        if item is None:
            continue
        if _apply_result(item, entry, subject=subject, topics_by_name=topics_by_name,
                         tagger_version=tagger_version, allow_difficulty=allow_difficulty):
            _store_result(tenant, hashes[str(entry.get('id'))], model_ref, entry)
            tagged += 1
    return tagged


def _topics_by_name(subjects):
    from exams.models import Topic

    topics = Topic.objects.filter(subject__in=subjects).select_related('subject')
    return {topic.name.strip().casefold(): topic for topic in topics}


def tag_questions(tenant, questions):
    """Tag untagged/stale bank Questions (subject always known). Returns count."""
    tagged = 0
    by_subject = {}
    for question in questions:
        by_subject.setdefault(question.subject, []).append(question)
    for subject, group in by_subject.items():
        topics_by_name = _topics_by_name([subject])
        for start in range(0, len(group), BATCH_SIZE):
            batch = {str(q.id): q for q in group[start:start + BATCH_SIZE]}
            tagged += _tag_batch(
                tenant, batch, subject=subject, subjects=[subject],
                topics_by_name=topics_by_name,
                # Bank difficulty is always authored — never overwrite it.
                allow_difficulty=False,
            )
    return tagged


def tag_mock_items(tenant, items):
    """Tag untagged/stale MockTestItems. Subject is inferred per item from the
    LLM-chosen topic within the owning test's course. Returns count."""
    tagged = 0
    by_test = {}
    for item in items:
        by_test.setdefault(item.mock_test, []).append(item)
    for mock_test, group in by_test.items():
        # Rich mocks link courses via the M2M; legacy/PYP mocks use the FK.
        courses = list(mock_test.courses.all()) or (
            [mock_test.course] if mock_test.course_id else []
        )
        subjects = [subject for course in courses for subject in course.subjects.all()]
        if not subjects:
            logger.info('tagging: mock test %s has no course/subjects; skipped', mock_test.id)
            continue
        topics_by_name = _topics_by_name(subjects)
        default_subject = subjects[0] if len(subjects) == 1 else None
        for start in range(0, len(group), BATCH_SIZE):
            batch = {str(i.id): i for i in group[start:start + BATCH_SIZE]}
            tagged += _tag_batch(
                tenant, batch, subject=default_subject, subjects=subjects,
                topics_by_name=topics_by_name, allow_difficulty=True,
            )
    return tagged


def untagged_questions(tenant, limit=None):
    from quiz.models import Question

    qs = Question.objects.filter(
        tenant=tenant, tagging_status__in=['', 'stale'],
    ).exclude(status='archived').select_related('subject', 'topic').order_by('created_at')
    return list(qs[:limit] if limit else qs)


def untagged_mock_items(tenant, limit=None):
    from quiz.models import MockTestItem

    qs = MockTestItem.objects.filter(
        tenant=tenant, tagging_status__in=['', 'stale'],
    ).select_related('mock_test__course', 'subject', 'topic').order_by('created_at')
    return list(qs[:limit] if limit else qs)


def run_tagging_for_tenant(tenant, *, limit=200):
    """Budget-gated tagging pass over a tenant's untagged/stale items."""
    from coursegen.generation import _check_budget

    _check_budget(tenant)
    questions = untagged_questions(tenant, limit=limit)
    items = untagged_mock_items(tenant, limit=limit)
    tagged = tag_questions(tenant, questions) + tag_mock_items(tenant, items)
    logger.info('tagging: tenant %s — %d item(s) tagged', tenant.id, tagged)
    return tagged
