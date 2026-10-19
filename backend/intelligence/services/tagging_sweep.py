"""The tagging sweep: v2 for subjects with a syllabus tree, v1 for the rest.

DB shell around the pure core in ``tagging_v2``: it picks items, builds their
payloads and the subject context, caches each stage's reply per item content,
and writes ItemTagging / ItemSkillTag / ConceptLink rows.
"""
import logging
from collections import defaultdict

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from intelligence.models import AITaggingResult, ItemSkillTag, ItemTagging, SyllabusNode, TagDefinition
from intelligence.services import tagging as tagging_v1
from intelligence.services.itemtags import content_hash_for, replace_links
from intelligence.services.llm import tenant_tagging_call
from intelligence.services import taxonomy
from intelligence.services.syllabus import ensure_node_concept, tagging_context
from intelligence.services.tagging_v2 import cognitive_projection, tag_payloads
from intelligence.versions import TAGGER_V2_PROMPT_VERSION

logger = logging.getLogger(__name__)

LINK_VERSION_CHARS = 60  # ConceptLink.tagger_version max_length


class DbCache:
    """AITaggingResult-backed cache: one row per (content, stage, versions, model)."""

    def __init__(self, tenant, context, model_ref, hashes):
        self.tenant = tenant
        self.context = context
        self.model_ref = model_ref
        self.hashes = hashes

    def _key(self, stage, payload_id):
        return {
            'tenant': self.tenant,
            'content_hash': self.hashes[payload_id],
            'prompt_version': TAGGER_V2_PROMPT_VERSION,
            'taxonomy_version': self.context['taxonomy_version'],
            'tree_version': self.context['tree_version'],
            'stage': stage,
            'model_ref': self.model_ref,
        }

    def get(self, stage, payload_id):
        row = AITaggingResult.objects.filter(**self._key(stage, payload_id)).first()
        return row.result if row else None

    def put(self, stage, payload_id, entry):
        AITaggingResult.objects.get_or_create(**self._key(stage, payload_id), defaults={'result': entry})


def _arm(item):
    from quiz.models import MockTestItem

    return 'mock_item' if isinstance(item, MockTestItem) else 'question'


def item_payload(item):
    """Tagger payload for a bank Question or MockTestItem (answer as text)."""
    if _arm(item) == 'mock_item':
        options = [str(option.get('text') or '') for option in item.options or []]
        correct = [str(option.get('text') or '') for option in item.options or [] if option.get('is_correct')]
        fallback = str(item.numerical_answer) if item.numerical_answer is not None else ''
        item_type = item.item_type
    else:
        rows = list(item.options.order_by('order'))
        options = [row.option_text for row in rows]
        correct = [row.option_text for row in rows if row.is_correct]
        fallback = (str(item.numerical_answer) if item.numerical_answer is not None
                    else (item.correct_answer or ''))
        item_type = item.question_type
    return {
        'id': str(item.id),
        'type': item_type,
        'question': item.question_text or '',
        'options': options,
        'answer': ' | '.join(correct) or fallback,
    }


def _is_current(item, tagging, context):
    return (
        tagging is not None
        and item.tagging_status == 'tagged'
        and tagging.taxonomy_version == context['taxonomy_version']
        and tagging.tree_version == context['tree_version']
    )


def _replace_skill_tags(item, arm, skills):
    ItemSkillTag.objects.filter(**{arm: item}, source='llm_tagger').delete()
    manual = set(ItemSkillTag.objects.filter(**{arm: item}).values_list('skill__key', flat=True))
    definitions = {
        row.key: row for row in TagDefinition.objects.filter(
            kind=TagDefinition.KIND_SKILL, key__in=[skill['key'] for skill in skills])
    }
    ItemSkillTag.objects.bulk_create([
        ItemSkillTag(tenant=item.tenant, skill=definitions[skill['key']], role=skill['role'],
                     reason=skill['reason'], source='llm_tagger', **{arm: item})
        for skill in skills if skill['key'] in definitions and skill['key'] not in manual
    ])


@transaction.atomic
def write_result(item, result, context, nodes, tagger_version, *, subject, allow_difficulty):
    """Persist one TagResult. Returns the ItemTagging, or None when locked."""
    arm = _arm(item)
    tagging = ItemTagging.objects.filter(**{arm: item}).first()
    if tagging is not None and tagging.source == 'manual':
        return None
    was_untagged = not item.tagging_status

    primary = nodes.get(result.primary_subtopic)
    secondaries = [nodes[key] for key in result.secondary_subtopics if key in nodes] if primary else []
    concepts = [ensure_node_concept(node) for node in ([primary, *secondaries] if primary else [])]
    replace_links(item, concepts, source='llm_tagger', tagger_version=tagger_version[:LINK_VERSION_CHARS])

    if tagging is None:
        tagging = ItemTagging(tenant=item.tenant, **{arm: item})
    tagging.primary_node = primary
    tagging.thinking_level = result.thinking_level
    tagging.special_format = result.special_format
    tagging.difficulty_prior = result.difficulty
    tagging.est_solve_seconds = result.est_solve_seconds
    tagging.confidence = result.confidence
    tagging.review_status = ItemTagging.REVIEW_NEEDED if result.needs_review else ItemTagging.REVIEW_AUTO
    tagging.review_reasons = result.review_reasons
    tagging.proposed_subtopic = result.proposed_subtopic
    tagging.source = 'llm_tagger'
    tagging.tagger_version = tagger_version[:120]
    tagging.taxonomy_version = context['taxonomy_version']
    tagging.tree_version = context['tree_version']
    tagging.raw = result.raw
    tagging.save()
    tagging.secondary_nodes.set(secondaries)
    _replace_skill_tags(item, arm, result.skills)

    update_fields = ['content_hash', 'tagging_status', 'tagged_at', 'updated_at']
    item.content_hash = content_hash_for(item)
    item.tagging_status = 'tagged'
    item.tagged_at = timezone.now()
    projection = cognitive_projection(result.thinking_level)
    if projection:
        item.cognitive_type = projection
        update_fields.append('cognitive_type')
    if allow_difficulty and was_untagged and result.difficulty:
        item.difficulty = result.difficulty
        update_fields.append('difficulty')
    if item.topic_id is None and primary is not None and primary.parent and primary.parent.course_topic_id:
        item.topic_id = primary.parent.course_topic_id
        update_fields.append('topic')
    if arm == 'mock_item' and item.subject_id is None:
        item.subject = subject
        update_fields.append('subject')
    item.save(update_fields=list(dict.fromkeys(update_fields)))
    return tagging


def _tag_group(tenant, subject, context, items, call, *, arm):
    nodes = {
        node.key: node for node in
        SyllabusNode.objects.filter(subject=subject, status='active').select_related('parent', 'concept')
    }
    hints = {topic['course_topic_id']: topic['key'] for topic in context['topics'] if topic['course_topic_id']}
    by_id, hashes, payloads = {}, {}, []
    for item in items:
        payload = item_payload(item)
        payload['topic_hint'] = hints.get(str(item.topic_id), '') if item.topic_id else ''
        payloads.append(payload)
        by_id[payload['id']] = item
        hashes[payload['id']] = content_hash_for(item)
    results = tag_payloads(context, payloads, call=call,
                           cache=DbCache(tenant, context, call.model_ref, hashes))
    tagger_version = f'{TAGGER_V2_PROMPT_VERSION}:{call.model_ref}'
    written = 0
    for result in results:
        if result.error == 'no_topic':
            # Locate found no valid topic: a result (needs review), not a retry.
            result.error = ''
            result.review_reasons = ['invalid_key']
            result.needs_review = True
        if result.error:
            logger.info('tagging v2: %s %s not tagged (%s)', arm, result.id, result.error)
            continue
        if write_result(by_id[result.id], result, context, nodes, tagger_version,
                        subject=subject, allow_difficulty=(arm == 'mock_item')):
            written += 1
    return written


def _mock_item_subject(item):
    if item.subject_id:
        return item.subject
    if item.topic_id:
        return item.topic.subject
    test = item.mock_test
    courses = list(test.courses.all()) or ([test.course] if test.course_id else [])
    subjects = [subject for course in courses for subject in course.subjects.all()]
    return subjects[0] if len(subjects) == 1 else None


def _single_subject_test_ids(tenant, subject_ids):
    """Mock tests whose courses have exactly one subject, and it is in ``subject_ids``."""
    from quiz.models import MockTest

    ids = []
    for test in (MockTest.objects.filter(tenant=tenant).select_related('course')
                 .prefetch_related('courses__subjects')):
        courses = list(test.courses.all()) or ([test.course] if test.course_id else [])
        subjects = [subject for course in courses for subject in course.subjects.all()]
        if len(subjects) == 1 and subjects[0].id in subject_ids:
            ids.append(test.id)
    return ids


def v2_mock_item_filter(tenant, subject_ids):
    """Q selecting the mock items the v2 sweep owns (v1 must skip these)."""
    subject_ids = set(subject_ids)
    return (
        Q(subject_id__in=subject_ids)
        | Q(subject__isnull=True, topic__subject_id__in=subject_ids)
        | Q(subject__isnull=True, topic__isnull=True,
            mock_test_id__in=_single_subject_test_ids(tenant, subject_ids))
    )


def _candidate_q():
    release = taxonomy.current_release()
    version = release.version if release else ''
    return (Q(tagging__isnull=True) | Q(tagging_status__in=['', 'stale'])
            | ~Q(tagging__taxonomy_version=version))


def tag_v2_for_tenant(tenant, subject_ids, call, *, limit=200):
    """Tag up to ``limit`` not-current items of these (treed) subjects."""
    from quiz.models import MockTestItem, Question

    subject_ids = set(subject_ids)
    contexts, subjects = {}, {}
    picked = defaultdict(list)
    candidates = _candidate_q()

    def context_for(subject):
        if subject.id not in contexts:
            contexts[subject.id] = tagging_context(subject)
        return contexts[subject.id]

    def take(arm, item, subject, tagging):
        if _is_current(item, tagging, context_for(subject)):
            return False
        picked[(arm, subject.id)].append(item)
        subjects[subject.id] = subject
        return True

    taken = 0
    questions = (
        Question.objects.filter(tenant=tenant, subject_id__in=subject_ids).exclude(status='archived')
        .exclude(tagging__source='manual').filter(candidates)
        .select_related('subject__course', 'topic', 'tagging').order_by('created_at')
    )
    for question in questions.iterator():
        if taken >= limit:
            break
        taken += take('question', question, question.subject, getattr(question, 'tagging', None))

    items = (
        MockTestItem.objects.filter(tenant=tenant).filter(v2_mock_item_filter(tenant, subject_ids))
        .exclude(tagging__source='manual').filter(candidates)
        .select_related('mock_test__course', 'subject__course', 'topic__subject__course', 'tagging')
        .prefetch_related('mock_test__courses__subjects')
        .order_by('created_at')
    )
    for item in items:
        if taken >= limit:
            break
        subject = _mock_item_subject(item)
        if subject is None or subject.id not in subject_ids:
            continue
        taken += take('mock_item', item, subject, getattr(item, 'tagging', None))

    tagged = 0
    for (arm, subject_id), group in picked.items():
        subject = subjects[subject_id]
        tagged += _tag_group(tenant, subject, context_for(subject), group, call, arm=arm)
    return tagged


def run_sweep(tenant, *, limit=200, call=None):
    """Budget-gated pass: v2 where a syllabus tree exists, v1 everywhere else."""
    from coursegen.generation import _check_budget

    _check_budget(tenant)
    treed = set(
        SyllabusNode.objects.filter(tenant=tenant, level='topic', status='active')
        .values_list('subject_id', flat=True)
    )
    v2 = tag_v2_for_tenant(tenant, treed, call or tenant_tagging_call(tenant), limit=limit) if treed else 0
    v1 = tagging_v1.run_tagging_for_tenant(
        tenant, limit=limit, exclude_subject_ids=treed, check_budget=False,
        exclude_mock_q=v2_mock_item_filter(tenant, treed) if treed else None,
    )
    logger.info('tagging sweep: tenant %s — v2 %d, v1 %d item(s)', tenant.id, v2, v1)
    return {'v2': v2, 'v1': v1}
