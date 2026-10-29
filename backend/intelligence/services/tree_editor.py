"""Teacher edits to a course's syllabus tree (spec 2B §5.2).

Course topics are read-only: their names and order come from the course.
Sub-subjects and subtopics can be added, renamed and archived; topics move
between sub-subjects; any node takes a weightage; suggested (``proposed``)
subtopics are accepted explicitly or by editing; two subtopics merge.
Add, rename, archive and merge change the subject's tree version, so the
next tagging run re-tags the affected items.
"""
import uuid
from collections import defaultdict

from django.db import transaction
from django.utils import timezone

from intelligence.models import CourseSyllabus, ItemTagging, SkillPack, SyllabusNode
from intelligence.services.course_tree import _slug, _subject_code, _unique_key
from intelligence.services.normalize import merge_concept
from intelligence.services.syllabus import (
    compute_tree_version, ensure_node_concept, exam_tree_options, packs_for_subject,
)

LIVE = ('active', 'proposed')
WEIGHT_TOLERANCE = 0.01


class EditError(ValueError):
    """A refused edit; the message is shown to the teacher as is."""


def as_uuid(value):
    """``value`` as a UUID string, or None when it is not one.

    Ids from request bodies and query strings go through this before any
    ``filter(id=...)``: a malformed id raises ValidationError inside the ORM,
    which would be a 500 instead of a 400.
    """
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        return None


def _clean_name(value):
    name = ' '.join(str(value or '').split())[:300]
    if not name:
        raise EditError('A name is required.')
    return name


# ── Payload ──────────────────────────────────────────────────────────────────

def _node_payload(node, children):
    return {
        'id': str(node.id),
        'key': node.key,
        'level': node.level,
        'name': node.name,
        'description': node.description,
        'weightage': node.weightage,
        'status': node.status,
        'source': node.source,
        'in_syllabus': node.in_syllabus,
        'course_topic_id': str(node.course_topic_id) if node.course_topic_id else None,
        'children': [_node_payload(child, children) for child in children.get(node.id, [])],
    }


def tree_payload(course):
    """Everything the Syllabus tab shows except job history."""
    record = CourseSyllabus.objects.filter(course=course).first()
    explicit = (record.skill_packs or {}) if record else {}
    subjects = []
    for subject in course.subjects.all().order_by('order', 'name'):
        nodes = list(
            SyllabusNode.objects.filter(subject=subject).exclude(status='archived')
            .order_by('order', 'name')
        )
        children = defaultdict(list)
        for node in nodes:
            children[node.parent_id].append(node)
        subjects.append({
            'id': str(subject.id),
            'name': subject.name,
            'has_tree': any(node.level == 'topic' for node in nodes),
            'tree_version': compute_tree_version(subject) if nodes else '',
            'proposed': sum(1 for node in nodes if node.status == 'proposed'),
            'packs': [pack.key for pack in packs_for_subject(subject)],
            'explicit_packs': str(subject.id) in explicit,
            'nodes': [_node_payload(node, children) for node in children.get(None, [])],
        })
    if record and record.exam_tree:
        kind = 'exam'
    elif any(subject['has_tree'] for subject in subjects):
        kind = 'custom'
    else:
        kind = 'none'
    return {
        'course': {'id': str(course.id), 'name': course.name, 'course_type': course.course_type},
        'kind': kind,
        'exam_tree': record.exam_tree if record else '',
        'subject_map': (record.subject_map or {}) if record else {},
        'subjects': subjects,
        'skill_packs_available': [
            {'key': pack.key, 'label': pack.label}
            for pack in SkillPack.objects.filter(active=True).order_by('key')
        ],
        'exam_trees': exam_tree_options(),
    }


# ── Edits ────────────────────────────────────────────────────────────────────

def add_node(subject, *, level, name, parent=None, description=''):
    """Add a subtopic (under a topic) or a sub-subject (top level)."""
    name = _clean_name(name)
    used = set(SyllabusNode.objects.filter(subject=subject).values_list('key', flat=True))
    if level == 'subtopic':
        if (parent is None or parent.subject_id != subject.id or parent.level != 'topic'
                or parent.status == 'archived'):
            raise EditError('A subtopic goes under a topic of this subject.')
        key = _unique_key(f'{parent.key}.{_slug(name)}', used)
    elif level == 'sub_subject':
        if parent is not None:
            raise EditError('A sub-subject sits at the top of the subject.')
        sibling = (SyllabusNode.objects.filter(subject=subject, level='sub_subject')
                   .order_by('order').first())
        prefix = sibling.key.rsplit('.', 1)[0] if sibling else f'course.{_subject_code(subject)}.group'
        key = _unique_key(f'{prefix}.{_slug(name)}', used)
    else:
        raise EditError('Topics come from the course itself. Add the topic to the course instead.')
    order = SyllabusNode.objects.filter(subject=subject, parent=parent, level=level).count()
    node = SyllabusNode.objects.create(
        tenant=subject.tenant, subject=subject, parent=parent, level=level, key=key,
        name=name, description=str(description or '').strip()[:2000],
        source='manual', status='active', order=order,
    )
    if level == 'subtopic':
        ensure_node_concept(node)
    return node


def weight_warnings(node):
    """A note when weighted siblings don't add up to 1 (never blocks the edit)."""
    siblings = SyllabusNode.objects.filter(
        subject=node.subject, parent=node.parent, level=node.level, status__in=LIVE)
    weights = [sibling.weightage for sibling in siblings]
    if not any(weights):
        return []
    total = sum(weights)
    if abs(total - 1) <= WEIGHT_TOLERANCE:
        return []
    where = node.parent.name if node.parent_id else node.subject.name
    return [f'Weightages under "{where}" add up to {total:.2f}, not 1.']


def _check_archivable(node):
    if node.level == 'topic':
        raise EditError('Topics come from the course. Remove the topic from the course instead.')
    if node.level == 'sub_subject' and SyllabusNode.objects.filter(
            parent=node, status__in=LIVE).exists():
        raise EditError('Move its topics to another sub-subject first.')


def update_node(node, data):
    """Apply one PATCH (name, description, parent, weightage, status).

    Returns weightage warnings. Editing a suggestion accepts it.
    """
    if node.status == 'archived':
        raise EditError('This node is archived.')
    fields = set()
    if 'name' in data or 'description' in data:
        if node.level == 'topic':
            raise EditError('Topic names come from the course.')
        if 'name' in data:
            node.name = _clean_name(data['name'])
            fields.add('name')
        if 'description' in data:
            node.description = str(data['description'] or '').strip()[:2000]
            fields.add('description')
    if 'parent' in data:
        if node.level != 'topic':
            raise EditError('Only topics move between sub-subjects.')
        parent_id = as_uuid(data['parent'])
        target = (SyllabusNode.objects.filter(
            id=parent_id, subject=node.subject, level='sub_subject', status__in=LIVE).first()
            if parent_id else None)
        if target is None:
            raise EditError('Pick a sub-subject of this subject.')
        node.parent = target
        fields.add('parent')
    if 'weightage' in data:
        try:
            weight = float(data['weightage'])
        except (TypeError, ValueError):
            raise EditError('Weightage is a number from 0 to 1.') from None
        if not 0 <= weight <= 1:
            raise EditError('Weightage is a number from 0 to 1.')
        node.weightage = weight
        fields.add('weightage')
    if 'status' in data:
        if data['status'] == 'active':
            node.status = 'active'
        elif data['status'] == 'archived':
            _check_archivable(node)
            node.status = 'archived'
        else:
            raise EditError('Status is "active" or "archived".')
        fields.add('status')
    if not fields:
        raise EditError('Nothing to change.')
    if node.status == 'proposed' and fields & {'name', 'description', 'weightage'}:
        node.status = 'active'
        fields.add('status')
    node.save(update_fields=[*fields, 'updated_at'])
    if node.level == 'subtopic' and node.status != 'archived':
        ensure_node_concept(node)  # keeps the Concept's name in step
    return weight_warnings(node)


@transaction.atomic
def merge_nodes(source, target):
    """Merge subtopic ``source`` into ``target`` and archive ``source``.

    The target keeps its Concept: ``merge_concept`` moves ConceptLinks and
    aliases and drops the source's learner states (callers queue a
    recompute of the target concept). ItemTagging primary and secondary
    nodes move from source to target. Skill tags are per item: untouched.
    """
    if source.id == target.id:
        raise EditError('Pick a different subtopic to merge into.')
    if source.level != 'subtopic' or target.level != 'subtopic':
        raise EditError('Only subtopics can be merged.')
    if source.subject_id != target.subject_id:
        raise EditError('Both subtopics must be in the same subject.')
    if source.status == 'archived' or target.status == 'archived':
        raise EditError('Archived subtopics cannot be merged.')
    target_concept = ensure_node_concept(target)
    if source.concept_id and source.concept_id != target_concept.id:
        merge_concept(source.concept, target_concept)

    primary_moved = ItemTagging.objects.filter(primary_node=source).update(
        primary_node=target, updated_at=timezone.now())
    secondary_moved = 0
    for tagging in ItemTagging.objects.filter(secondary_nodes=source):
        tagging.secondary_nodes.remove(source)
        if tagging.primary_node_id != target.id:
            tagging.secondary_nodes.add(target)
        secondary_moved += 1
    for tagging in ItemTagging.objects.filter(primary_node=target, secondary_nodes=target):
        tagging.secondary_nodes.remove(target)

    source.status = 'archived'
    source.save(update_fields=['status', 'updated_at'])
    if target.status == 'proposed':
        target.status = 'active'
        target.save(update_fields=['status', 'updated_at'])
    return {'primary_moved': primary_moved, 'secondary_moved': secondary_moved,
            'concept_id': str(target_concept.id)}


def set_skill_packs(course, packs):
    """Explicit skill packs per subject: ``{subject_id: [pack_key, …]}``.

    Unknown pack keys are dropped; an empty list removes the subject's
    explicit choice (it falls back to name matching).
    """
    if not isinstance(packs, dict):
        raise EditError('Send packs as {subject_id: [pack keys]}.')
    subject_ids = {str(sid) for sid in course.subjects.values_list('id', flat=True)}
    active = set(SkillPack.objects.filter(active=True).values_list('key', flat=True))
    record, _ = CourseSyllabus.objects.get_or_create(course=course, defaults={'tenant': course.tenant})
    current = dict(record.skill_packs or {})
    for subject_id, keys in packs.items():
        if str(subject_id) not in subject_ids:
            raise EditError('That subject is not in this course.')
        cleaned = [key for key in (keys if isinstance(keys, list) else []) if key in active]
        if cleaned:
            current[str(subject_id)] = cleaned
        else:
            current.pop(str(subject_id), None)
    record.skill_packs = current
    record.save(update_fields=['skill_packs', 'updated_at'])
    return current
