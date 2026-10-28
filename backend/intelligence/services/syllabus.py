"""Syllabus trees in the database (decision D5).

- Exam trees (YAML) are *instantiated* per course subject, keyed by their
  full dotted keys, so analytics compare across tenants by key.
- Every subtopic node owns one Concept: mastery keeps living at the leaves.
- ``tagging_context`` / ``context_from_tree`` produce the plain-data context
  the v2 tagger consumes (see services/tagging_v2.py).
"""
import hashlib
import json
import re

from django.db import transaction
from django.db.models import Q
from django.utils.text import slugify

from intelligence.services.normalize import concept_slug, merge_concept
from intelligence.services.taxonomy import (
    DEFAULT_REVIEW_THRESHOLD, TaxonomyError, current_release, flatten_tree, load_exam_tree,
)


def norm(text):
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', (text or '').casefold()).split())


def pack_matches(applies_to, names):
    """True when any ``applies_to`` term occurs as whole words in any name."""
    haystacks = [f' {norm(name)} ' for name in names if norm(name)]
    return any(f' {norm(term)} ' in haystack for term in applies_to if norm(term) for haystack in haystacks)


def _node_concept_slug(key):
    slug = slugify(key.replace('.', ' '))
    if len(slug) > 220:
        slug = f'{slug[:200]}-{hashlib.sha1(key.encode()).hexdigest()[:12]}'
    return slug


def ensure_node_concept(node):
    """Give a subtopic node its own Concept (created once, renamed on re-sync)."""
    from intelligence.models import Concept

    if node.concept_id:
        concept = node.concept
        if concept.name != node.name[:200]:
            concept.name = node.name[:200]
            concept.save(update_fields=['name', 'updated_at'])
        return concept
    concept, _ = Concept.objects.get_or_create(
        tenant=node.tenant, subject=node.subject, slug=_node_concept_slug(node.key),
        defaults={'name': node.name[:200], 'source': 'syllabus'},
    )
    node.concept = concept
    node.save(update_fields=['concept', 'updated_at'])
    anchor = node.parent.course_topic if node.parent_id else None
    if anchor is not None:
        concept.topics.add(anchor)
    return concept


def compute_tree_version(subject):
    """Hash of the subject's live tree; part of the tagging cache key."""
    from intelligence.models import SyllabusNode

    rows = list(
        SyllabusNode.objects.filter(subject=subject).exclude(status='archived').order_by('key')
        .values_list('key', 'name', 'description', 'level', 'in_syllabus')
    )
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode('utf-8')).hexdigest()[:16]


def _link_course_topics(subject, nodes, aliases, unmatched):
    from exams.models import Topic

    topics = list(Topic.objects.filter(subject=subject).order_by('order', 'name'))
    by_name = {}
    for topic in topics:
        by_name.setdefault(norm(topic.name), topic)
        by_name.setdefault(norm(topic.code), topic)
    linked_ids, linked = set(), 0
    for key, node in nodes.items():
        if node.level != 'topic':
            continue
        candidates = [node.name, key.rsplit('.', 1)[-1], *aliases.get(key, [])]
        match = next((by_name[norm(c)] for c in candidates if norm(c) in by_name), None)
        if match is None:
            continue
        if node.course_topic_id != match.id:
            node.course_topic = match
            node.save(update_fields=['course_topic', 'updated_at'])
        linked_ids.add(match.id)
        linked += 1
    unmatched.extend(f'{subject.name}: {topic.name}' for topic in topics if topic.id not in linked_ids)
    return linked


def _merge_existing_concepts(subject, summary):
    """Fold pre-tree flat Concepts into tree subtopics with the same name."""
    from intelligence.models import Concept, SyllabusNode

    by_slug = {}
    owned = set()
    for node in SyllabusNode.objects.filter(subject=subject, level='subtopic', status='active'):
        if node.concept_id:
            owned.add(node.concept_id)
            by_slug.setdefault(concept_slug(node.name), []).append(node)
    for concept in Concept.objects.filter(subject=subject, status='active').exclude(id__in=owned):
        matches = by_slug.get(concept.slug) or by_slug.get(concept_slug(concept.name)) or []
        if len(matches) == 1:
            merge_concept(concept, matches[0].concept)
            summary['merged_concepts'] += 1
        elif len(matches) > 1:
            summary['ambiguous_concepts'].append(f'{subject.name}: {concept.name}')


@transaction.atomic
def instantiate_exam_tree(course, exam_key, subject_map, *, audience=None):
    """Upsert an exam tree's nodes under each mapped course subject.

    ``subject_map`` is ``{tree_subject_key: exams.Subject}``. Updates by key,
    never deletes: nodes missing from the tree become 'archived'.
    """
    from intelligence.models import CourseSyllabus, SyllabusNode

    tree = load_exam_tree(exam_key)
    flat = flatten_tree(tree)
    tree_subjects = {node['subject'] for node in flat}
    unknown = sorted(set(subject_map) - tree_subjects)
    if unknown:
        raise TaxonomyError([f'{exam_key} has no subject {key!r}' for key in unknown])

    record, _ = CourseSyllabus.objects.get_or_create(course=course, defaults={'tenant': course.tenant})
    record.exam_tree = exam_key
    record.audience = (audience or tree['audience'])[:200]
    record.subject_map = {str(subject.id): key for key, subject in subject_map.items()}
    record.save()

    summary = {'created': 0, 'updated': 0, 'archived': 0, 'linked_topics': 0,
               'unmatched_topics': [], 'merged_concepts': 0, 'ambiguous_concepts': []}
    for tree_subject, subject in subject_map.items():
        entries = [node for node in flat if node['subject'] == tree_subject and node['level'] != 'subject']
        nodes = {}
        for entry in entries:  # pre-order: parents before children
            node, created = SyllabusNode.objects.update_or_create(
                tenant=course.tenant, subject=subject, key=entry['key'],
                defaults={
                    'parent': nodes.get(entry['parent_key']),
                    'level': entry['level'],
                    'name': entry['label'][:300],
                    'description': entry['description'],
                    'weightage': entry['weightage'],
                    'in_syllabus': entry['in_syllabus'],
                    'source': 'exam_tree',
                    'status': 'active',
                    'order': entry['order'],
                },
            )
            nodes[entry['key']] = node
            summary['created' if created else 'updated'] += 1
        summary['archived'] += (
            SyllabusNode.objects.filter(subject=subject, source='exam_tree')
            .exclude(key__in=list(nodes)).exclude(status='archived').update(status='archived')
        )
        aliases = {entry['key']: entry['aliases'] for entry in entries}
        summary['linked_topics'] += _link_course_topics(subject, nodes, aliases, summary['unmatched_topics'])
        for node in nodes.values():
            if node.level == 'subtopic':
                node.refresh_from_db(fields=['course_topic', 'concept'])
                ensure_node_concept(node)
        _merge_existing_concepts(subject, summary)
    return summary


def packs_for_subject(subject):
    """Explicit CourseSyllabus packs, else whole-word name matching."""
    from intelligence.models import CourseSyllabus, SkillPack

    active = {pack.key: pack for pack in SkillPack.objects.filter(active=True).order_by('key')}
    record = CourseSyllabus.objects.filter(course_id=subject.course_id).first()
    if record and str(subject.id) in (record.skill_packs or {}):
        return [active[key] for key in record.skill_packs[str(subject.id)] if key in active]
    names = [subject.name, subject.code]
    if record and record.subject_map.get(str(subject.id)):
        names.append(record.subject_map[str(subject.id)])
    return [pack for pack in active.values() if pack_matches(pack.applies_to, names)]


def _definitions(kind, packs=None):
    from intelligence.models import TagDefinition

    rows = TagDefinition.objects.filter(kind=kind, active=True).select_related('pack')
    if kind == TagDefinition.KIND_SKILL:
        rows = rows.filter(Q(pack__isnull=True) | Q(pack__in=packs or []))
        return [{'key': r.key, 'label': r.label, 'definition': r.definition,
                 'pack': r.pack.key if r.pack_id else ''} for r in rows]
    return [{'key': r.key, 'label': r.label, 'definition': r.definition} for r in rows]


def _exam_label(exam_key):
    try:
        return load_exam_tree(exam_key)['label']
    except TaxonomyError:
        return exam_key


def tagging_context(subject):
    """The v2 tagger context for one subject, built from the database."""
    from intelligence.models import CourseSyllabus, SyllabusNode, TagDefinition

    course = subject.course
    record = CourseSyllabus.objects.filter(course=course).first()
    nodes = list(
        SyllabusNode.objects.filter(subject=subject, status__in=('active', 'proposed'), in_syllabus=True)
        .order_by('order', 'name')
    )
    by_id = {node.id: node for node in nodes}
    topics = []
    for node in nodes:
        if node.level != 'topic':
            continue
        parent = by_id.get(node.parent_id)
        topics.append({
            'key': node.key,
            'label': node.name,
            'description': node.description,
            'group': parent.name if parent else '',
            'course_topic_id': str(node.course_topic_id) if node.course_topic_id else None,
            'subtopics': [
                {'key': child.key, 'label': child.name, 'description': child.description}
                for child in nodes if child.parent_id == node.id and child.level == 'subtopic'
            ],
        })
    release = current_release()
    exam_label = _exam_label(record.exam_tree) if record and record.exam_tree else course.name
    audience = (record.audience if record and record.audience
                else f'Learners of the course "{course.name}"')
    return {
        'exam_label': exam_label,
        'audience': audience,
        'subject': subject.name,
        'review_threshold': release.review_confidence_threshold if release else DEFAULT_REVIEW_THRESHOLD,
        'taxonomy_version': release.version if release else '',
        'tree_version': compute_tree_version(subject),
        'topics': topics,
        'thinking_levels': _definitions(TagDefinition.KIND_THINKING),
        'special_formats': _definitions(TagDefinition.KIND_FORMAT),
        'skills': _definitions(TagDefinition.KIND_SKILL, packs_for_subject(subject)),
    }


def _plain(entry, pack=None):
    out = {'key': entry['key'], 'label': entry['label'], 'definition': entry['definition']}
    if pack is not None:
        out['pack'] = pack
    return out


def context_from_tree(tree, subject_key, tags):
    """The same context shape, straight from a validated tree + vocabulary (no DB)."""
    flat = [node for node in flatten_tree(tree) if node['subject'] == subject_key]
    subject = next((node for node in flat if node['level'] == 'subject'), None)
    if subject is None:
        raise TaxonomyError([f'{tree["key"]} has no subject {subject_key!r}'])
    groups = {node['key']: node['label'] for node in flat if node['level'] == 'sub_subject'}
    topics = []
    for node in flat:
        if node['level'] != 'topic' or not node['in_syllabus']:
            continue
        topics.append({
            'key': node['key'],
            'label': node['label'],
            'description': node['description'],
            'group': groups.get(node['parent_key'], ''),
            'course_topic_id': None,
            'subtopics': [
                {'key': child['key'], 'label': child['label'], 'description': child['description']}
                for child in flat if child['parent_key'] == node['key'] and child['in_syllabus']
            ],
        })
    names = [subject_key, subject['label'], *subject['aliases']]
    packs = [pack for pack in tags['packs'] if pack['active'] and pack_matches(pack['applies_to'], names)]
    rows = [(node['key'], node['label'], node['description'], node['level'], node['in_syllabus'])
            for node in sorted(flat, key=lambda n: n['key'])]
    return {
        'exam_label': tree['label'],
        'audience': tree['audience'],
        'subject': subject['label'],
        'review_threshold': tags['review_confidence_threshold'],
        'taxonomy_version': tags['version'],
        'tree_version': hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode('utf-8')).hexdigest()[:16],
        'topics': topics,
        'thinking_levels': [_plain(e) for e in tags['thinking_levels'] if e['active']],
        'special_formats': [_plain(e) for e in tags['special_formats'] if e['active']],
        'skills': [_plain(e, '') for e in tags['universal_skills'] if e['active']]
                  + [_plain(e, pack['key']) for pack in packs for e in pack['skills'] if e['active']],
    }


def exam_tree_options():
    """Shipped exam trees and their subjects, for the "Use an exam syllabus" form."""
    from intelligence.services.taxonomy import shipped_exam_keys

    options = []
    for key in shipped_exam_keys():
        try:
            tree = load_exam_tree(key)
        except TaxonomyError:
            continue
        options.append({
            'key': key,
            'label': tree['label'],
            'subjects': [{'key': node['subject'], 'label': node['label']}
                         for node in flatten_tree(tree) if node['level'] == 'subject'],
        })
    return options
