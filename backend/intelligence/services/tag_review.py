"""The tag review queue (spec 2B §5.3).

Accept keeps the tagger's tags. Edit saves a teacher's tags as ``manual``:
ItemTagging, ConceptLinks and ItemSkillTags all carry source ``manual``, so
the tagger never overwrites them. Re-tag sends the item back to the tagger.
Add to tree turns a proposed subtopic into a real node and assigns it.
"""
from django.db import transaction
from django.utils import timezone

from intelligence.models import ConceptLink, ItemSkillTag, ItemTagging, SyllabusNode, TagDefinition
from intelligence.services.itemtags import content_hash_for, replace_links
from intelligence.services.normalize import concept_slug
from intelligence.services.syllabus import ensure_node_concept, packs_for_subject
from intelligence.services.tagging_v2 import cognitive_projection
from intelligence.services.tree_editor import as_uuid

REVIEW_REASONS = ('low_confidence', 'invalid_key', 'proposed_subtopic', 'stage_disagreement')
DIFFICULTIES = ('easy', 'medium', 'hard')
SOLVE_SECONDS = (10, 1800)
LIVE = ('active', 'proposed')
REASON_CHARS = 200


class ReviewError(ValueError):
    """A refused review action; the message is shown to the teacher."""


def item_of(tagging):
    return tagging.question or tagging.mock_item


def _arm(tagging):
    return 'question' if tagging.question_id else 'mock_item'


def subject_of(tagging):
    from intelligence.services.tagging_sweep import _mock_item_subject

    item = item_of(tagging)
    if item is None:
        return None
    return item.subject if tagging.question_id else _mock_item_subject(item)


def course_of(tagging):
    subject = subject_of(tagging)
    return subject.course if subject else None


def _node_brief(node):
    if node is None:
        return None
    return {'id': str(node.id), 'name': node.name, 'status': node.status,
            'topic': node.parent.name if node.parent_id else ''}


def row_payload(tagging):
    """One review row: the question and every tag the tagger gave it."""
    item = item_of(tagging)
    arm = _arm(tagging)
    skills = (ItemSkillTag.objects.filter(**{arm: item}).select_related('skill')
              .order_by('-role', 'skill__key'))
    topic = getattr(item, 'topic', None)
    return {
        'id': str(tagging.id),
        'item_kind': 'bank' if arm == 'question' else 'item',
        'item_id': str(item.id),
        'question_text': (item.question_text or '')[:400],
        'topic': topic.name if topic else '',
        'primary': _node_brief(tagging.primary_node),
        'secondary': [_node_brief(node) for node in tagging.secondary_nodes.select_related('parent')],
        'thinking_level': tagging.thinking_level,
        'skills': [
            {'key': tag.skill.key, 'label': tag.skill.label, 'role': tag.role,
             'reason': tag.reason, 'source': tag.source}
            for tag in skills
        ],
        'special_format': tagging.special_format,
        'difficulty_prior': tagging.difficulty_prior,
        'est_solve_seconds': tagging.est_solve_seconds,
        'confidence': tagging.confidence,
        'review_status': tagging.review_status,
        'review_reasons': tagging.review_reasons,
        'proposed_subtopic': tagging.proposed_subtopic,
        'source': tagging.source,
    }


def edit_choices(subject):
    """The tree and vocabulary an edit may choose from, for one subject."""
    nodes = list(SyllabusNode.objects.filter(subject=subject, status__in=LIVE).order_by('order', 'name'))
    topics = [
        {'id': str(topic.id), 'name': topic.name,
         'subtopics': [{'id': str(child.id), 'name': child.name, 'status': child.status}
                       for child in nodes if child.parent_id == topic.id and child.level == 'subtopic']}
        for topic in nodes if topic.level == 'topic'
    ]

    def vocabulary(kind, packs=None):
        rows = TagDefinition.objects.filter(kind=kind, active=True)
        if kind == TagDefinition.KIND_SKILL:
            from django.db.models import Q
            rows = rows.filter(Q(pack__isnull=True) | Q(pack__in=packs or []))
        return [{'key': row.key, 'label': row.label} for row in rows.order_by('order', 'key')]

    return {
        'topics': topics,
        'thinking_levels': vocabulary(TagDefinition.KIND_THINKING),
        'skills': vocabulary(TagDefinition.KIND_SKILL, packs_for_subject(subject)),
        'special_formats': vocabulary(TagDefinition.KIND_FORMAT),
    }


def accept(tagging):
    tagging.review_status = ItemTagging.REVIEW_DONE
    tagging.save(update_fields=['review_status', 'updated_at'])
    return tagging


def bulk_accept(queryset):
    return queryset.filter(review_status=ItemTagging.REVIEW_NEEDED).update(
        review_status=ItemTagging.REVIEW_DONE, updated_at=timezone.now())


def _subtopic(subject, node_id):
    node_id = as_uuid(node_id)
    node = SyllabusNode.objects.filter(
        id=node_id, subject=subject, level='subtopic', status__in=LIVE).first() if node_id else None
    if node is None:
        raise ReviewError('Pick a subtopic from this subject\'s tree.')
    return node


def _clean(tagging, data, subject, require_thinking):
    if not isinstance(data, dict):
        raise ReviewError('Send the tags as an object.')
    choices = edit_choices(subject)
    primary = _subtopic(subject, data.get('primary'))
    secondary = []
    for node_id in data.get('secondary') or []:
        node = _subtopic(subject, node_id)
        if node.id != primary.id and node not in secondary:
            secondary.append(node)
    thinking = str(data.get('thinking_level') or '')
    if thinking not in {row['key'] for row in choices['thinking_levels']} and (thinking or require_thinking):
        raise ReviewError('Pick a thinking level.')
    skill_keys = {row['key'] for row in choices['skills']}
    skills, seen = [], set()
    for raw in data.get('skills') or []:
        key = raw.get('key') if isinstance(raw, dict) else None
        if key not in skill_keys:
            raise ReviewError('Pick skills from the list for this subject.')
        if key in seen:
            continue
        seen.add(key)
        skills.append({'key': key, 'role': 'core' if raw.get('role') == 'core' else 'supporting',
                       'reason': str(raw.get('reason') or '')[:REASON_CHARS]})
    special = str(data.get('special_format') or '')
    if special and special not in {row['key'] for row in choices['special_formats']}:
        raise ReviewError('Unknown special format.')
    difficulty = str(data.get('difficulty_prior') or '')
    if difficulty and difficulty not in DIFFICULTIES:
        raise ReviewError('Difficulty is easy, medium or hard.')
    seconds = data.get('est_solve_seconds')
    if seconds in (None, ''):
        seconds = None
    else:
        try:
            seconds = min(SOLVE_SECONDS[1], max(SOLVE_SECONDS[0], int(seconds)))
        except (TypeError, ValueError):
            raise ReviewError('Solve time is a number of seconds.') from None
    return primary, secondary, thinking, skills, special, difficulty, seconds


@transaction.atomic
def save_manual(tagging, data, *, require_thinking=True):
    """Save a teacher's tags and lock them against the tagger."""
    subject = subject_of(tagging)
    if subject is None:
        raise ReviewError('This question has no subject, so it has no tree to tag against.')
    primary, secondary, thinking, skills, special, difficulty, seconds = _clean(
        tagging, data, subject, require_thinking)
    item = item_of(tagging)
    arm = _arm(tagging)

    concepts = [ensure_node_concept(node) for node in [primary, *secondary]]
    replace_links(item, [], source='llm_tagger')
    replace_links(item, concepts, source='manual')

    ItemSkillTag.objects.filter(**{arm: item}).delete()
    definitions = {row.key: row for row in TagDefinition.objects.filter(
        kind=TagDefinition.KIND_SKILL, key__in=[skill['key'] for skill in skills])}
    ItemSkillTag.objects.bulk_create([
        ItemSkillTag(tenant=item.tenant, skill=definitions[skill['key']], role=skill['role'],
                     reason=skill['reason'], source='manual', **{arm: item})
        for skill in skills
    ])

    tagging.primary_node = primary
    tagging.thinking_level = thinking
    tagging.special_format = special
    tagging.difficulty_prior = difficulty
    tagging.est_solve_seconds = seconds
    tagging.review_status = ItemTagging.REVIEW_DONE
    tagging.review_reasons = []
    tagging.proposed_subtopic = ''
    tagging.source = 'manual'
    tagging.save()
    tagging.secondary_nodes.set(secondary)

    update_fields = ['content_hash', 'tagging_status', 'tagged_at', 'updated_at']
    item.content_hash = content_hash_for(item)
    item.tagging_status = 'tagged'
    item.tagged_at = timezone.now()
    projection = cognitive_projection(thinking)
    if projection:
        item.cognitive_type = projection
        update_fields.append('cognitive_type')
    item.save(update_fields=update_fields)
    return tagging


def mark_for_retag(tagging):
    """Hand the item back to the tagger: unlock it and mark it stale."""
    item = item_of(tagging)
    if tagging.source == 'manual':
        tagging.source = 'llm_tagger'
        tagging.save(update_fields=['source', 'updated_at'])
        # The teacher's links and skills become tagger rows, so the re-tag
        # replaces them instead of sitting beside the new primary link.
        ConceptLink.objects.filter(**{_arm(tagging): item}, source='manual').update(source='llm_tagger')
        ItemSkillTag.objects.filter(**{_arm(tagging): item}, source='manual').update(source='llm_tagger')
    item.tagging_status = 'stale'
    item.save(update_fields=['tagging_status', 'updated_at'])
    return item


def _topic_for(tagging, subject):
    key = (tagging.raw or {}).get('topic_key')
    if key:
        node = SyllabusNode.objects.filter(subject=subject, key=key, level='topic', status__in=LIVE).first()
        if node:
            return node
    item = item_of(tagging)
    if getattr(item, 'topic_id', None):
        return SyllabusNode.objects.filter(
            subject=subject, level='topic', course_topic_id=item.topic_id, status__in=LIVE).first()
    return None


@transaction.atomic
def add_to_tree(tagging, topic_node=None):
    """Create the proposed subtopic under the item's topic and assign it."""
    from intelligence.services.tree_editor import EditError, add_node

    name = ' '.join((tagging.proposed_subtopic or '').split())
    if not name:
        raise ReviewError('This question has no proposed subtopic.')
    subject = subject_of(tagging)
    if subject is None:
        raise ReviewError('This question has no subject.')
    topic = topic_node or _topic_for(tagging, subject)
    if topic is None or topic.subject_id != subject.id or topic.level != 'topic':
        raise ReviewError('Pick the topic the new subtopic belongs to.')
    slug = concept_slug(name)
    node = next((child for child in SyllabusNode.objects.filter(
        parent=topic, level='subtopic', status__in=LIVE) if concept_slug(child.name) == slug), None)
    if node is None:
        try:
            node = add_node(subject, level='subtopic', name=name, parent=topic)
        except EditError as exc:
            raise ReviewError(str(exc)) from exc
    arm = _arm(tagging)
    save_manual(tagging, {
        'primary': str(node.id),
        'secondary': [str(n.id) for n in tagging.secondary_nodes.filter(status__in=LIVE)],
        'thinking_level': tagging.thinking_level,
        'skills': [{'key': tag.skill.key, 'role': tag.role, 'reason': tag.reason}
                   for tag in ItemSkillTag.objects.filter(**{arm: item_of(tagging)}).select_related('skill')],
        'special_format': tagging.special_format,
        'difficulty_prior': tagging.difficulty_prior,
        'est_solve_seconds': tagging.est_solve_seconds,
    }, require_thinking=False)
    return node
