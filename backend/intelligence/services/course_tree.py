"""Course-built syllabus trees for custom courses (spec §4.2, decision D5).

Topic level = the course's own Topics. Sub-subjects: one implicit group for
small subjects, else one LLM grouping call. Subtopics: existing Concepts
first (so mastery history carries over), then LLM proposals for what is
missing. Only question text — never student data — is sent to the model.
"""
import json

from django.db import transaction

from coursegen.generation import GenerationError, extract_json
from intelligence.services.normalize import concept_slug
from intelligence.services.syllabus import ensure_node_concept, norm

GROUP_THRESHOLD = 6
MAX_GROUPS = 8
MAX_PROPOSALS = 10
MAX_STEMS = 15
STEM_CHARS = 300
SLUG_CHARS = 60

GROUP_MARKER = 'syllabus organiser'
SUBTOPIC_MARKER = 'subtopic planner'
PACK_MARKER = 'skill-pack chooser'

GROUP_SYSTEM = f"""
You are a {GROUP_MARKER}. Group the TOPICS of one course subject into 2 to {MAX_GROUPS}
sub-subjects: coherent areas a teacher would name. Every topic id must appear in
exactly one group. Short group names (1-4 words).
Return ONE JSON object, no markdown fences: {{"groups": [{{"name": "...", "topic_ids": ["..."]}}]}}
""".strip()

SUBTOPIC_SYSTEM = f"""
You are a {SUBTOPIC_MARKER}. Break one course topic into subtopics: the distinct,
separately testable ideas a question could target. EXISTING subtopics are kept;
add only the missing ones (0 to {MAX_PROPOSALS}). Short names (2-6 words), no numbering.
Return ONE JSON object, no markdown fences: {{"subtopics": [{{"name": "...", "description": "<one line>"}}]}}
""".strip()

PACK_SYSTEM = f"""
You are a {PACK_MARKER}. For each subject, pick the skill packs whose skills its
questions exercise. Use only the pack keys listed; a subject may get none.
Return ONE JSON object, no markdown fences: {{"subjects": [{{"id": "...", "packs": ["..."]}}]}}
""".strip()


class _Rollback(Exception):
    pass


def _slug(text):
    return (norm(text).replace(' ', '_')[:SLUG_CHARS].strip('_')) or 'x'


def _ask_json(call, system, payload, summary):
    summary['llm_calls'] += 1
    try:
        return extract_json(call(system, json.dumps(payload, ensure_ascii=False)))
    except GenerationError:
        return None


def _unique_key(base, used):
    key, suffix = base, 2
    while key in used:
        key, suffix = f'{base}_{suffix}', suffix + 1
    used.add(key)
    return key


def _group_topics(subject, topics, call, summary):
    """[(group name, [topics])] — implicit group, LLM grouping, or fallback."""
    if len(topics) <= GROUP_THRESHOLD:
        return [(None, topics)]
    payload = {'subject': subject.name,
               'topics': [{'id': str(topic.id), 'name': topic.name} for topic in topics]}
    reply = _ask_json(call, GROUP_SYSTEM, payload, summary)
    by_id = {str(topic.id): topic for topic in topics}
    groups, placed = [], set()
    for raw in (reply or {}).get('groups') or []:
        if not isinstance(raw, dict) or len(groups) >= MAX_GROUPS:
            continue
        name = str(raw.get('name') or '').strip()[:300]
        members = [by_id[tid] for tid in raw.get('topic_ids') or []
                   if isinstance(tid, str) and tid in by_id and tid not in placed]
        if not name or not members:
            continue
        placed.update(str(topic.id) for topic in members)
        groups.append((name, members))
    if not groups:
        return [(None, topics)]
    rest = [topic for topic in topics if str(topic.id) not in placed]
    if rest:
        groups.append(('Other', rest))
    return groups


def _subject_code(subject):
    return _slug(subject.code or subject.name)


def _ensure_groups(subject, topics, call, summary, used):
    """Create sub-subject + topic nodes for topics not yet in the tree."""
    from intelligence.models import SyllabusNode

    existing = {node.course_topic_id: node for node in
                SyllabusNode.objects.filter(subject=subject, level='topic').exclude(status='archived')}
    new_topics = [topic for topic in topics if topic.id not in existing]
    if not new_topics:
        return existing
    code = _subject_code(subject)
    first_group = (SyllabusNode.objects.filter(subject=subject, level='sub_subject')
                   .exclude(status='archived').order_by('order').first())
    if first_group is not None:
        plan = [(first_group, new_topics)]
    else:
        plan = []
        for order, (name, members) in enumerate(_group_topics(subject, new_topics, call, summary)):
            key = (f'course.{code}.all' if name is None
                   else _unique_key(f'course.{code}.group.{_slug(name)}', used))
            group = SyllabusNode.objects.create(
                tenant=subject.tenant, subject=subject, level='sub_subject', key=key,
                name=(subject.name if name is None else name)[:300], source='course', order=order,
            )
            summary['sub_subjects_created'] += 1
            plan.append((group, members))
    for group, members in plan:
        for topic in members:
            key = _unique_key(f'course.{code}.{_slug(topic.code or topic.name)}', used)
            existing[topic.id] = SyllabusNode.objects.create(
                tenant=subject.tenant, subject=subject, parent=group, level='topic', key=key,
                name=topic.name[:300], description=(topic.description or '')[:2000],
                course_topic=topic, source='course', order=topic.order,
            )
            summary['topics_created'] += 1
    return existing


def _seed_subtopics(subject, topic_nodes, topics, summary, used):
    from intelligence.models import Concept, SyllabusNode

    owned = set(SyllabusNode.objects.filter(subject=subject, concept__isnull=False)
                .values_list('concept_id', flat=True))
    for topic in topics:  # topic order decides where a shared concept lands
        node = topic_nodes[topic.id]
        for concept in Concept.objects.filter(subject=subject, status='active', topics=topic).order_by('name'):
            if concept.id in owned:
                continue
            SyllabusNode.objects.create(
                tenant=subject.tenant, subject=subject, parent=node, level='subtopic',
                key=_unique_key(f'{node.key}.{_slug(concept.name)}', used), name=concept.name[:300],
                source='course', concept=concept,
            )
            owned.add(concept.id)
            summary['seeded_subtopics'] += 1
        for child in topic.subtopics.all().order_by('order', 'name'):
            if SyllabusNode.objects.filter(subject=subject, level='subtopic', course_topic=child).exists():
                continue
            child_node = SyllabusNode.objects.create(
                tenant=subject.tenant, subject=subject, parent=node, level='subtopic',
                key=_unique_key(f'{node.key}.{_slug(child.name)}', used), name=child.name[:300],
                description=(child.description or '')[:2000], source='course', course_topic=child,
            )
            ensure_node_concept(child_node)
            summary['seeded_subtopics'] += 1


def _propose_subtopics(subject, node, topic, call, summary, used, before):
    """LLM proposals for one topic — only on the run that first plans it."""
    from intelligence.models import Concept, SyllabusNode
    from quiz.models import Question

    existing = list(SyllabusNode.objects.filter(parent=node, level='subtopic').exclude(status='archived'))
    if any(child.id in before for child in existing):
        return  # this topic was planned in an earlier run
    seen = {concept_slug(child.name) for child in existing}
    stems = list(Question.objects.filter(topic=topic).exclude(status='archived')
                 .order_by('created_at').values_list('question_text', flat=True)[:MAX_STEMS])
    payload = {
        'subject': subject.name, 'topic': topic.name, 'objectives': topic.objectives or [],
        'existing_subtopics': [child.name for child in existing],
        'sample_questions': [(stem or '')[:STEM_CHARS] for stem in stems],
    }
    reply = _ask_json(call, SUBTOPIC_SYSTEM, payload, summary)
    for raw in ((reply or {}).get('subtopics') or [])[:MAX_PROPOSALS]:
        if not isinstance(raw, dict):
            continue
        name = ' '.join(str(raw.get('name') or '').split())[:300]
        slug = concept_slug(name)
        if not slug or slug in seen:
            continue
        seen.add(slug)
        adopt = (Concept.objects.filter(subject=subject, status='active', slug=slug)
                 .exclude(syllabus_node__isnull=False).first())
        child = SyllabusNode.objects.create(
            tenant=subject.tenant, subject=subject, parent=node, level='subtopic',
            key=_unique_key(f'{node.key}.{_slug(name)}', used), name=name,
            description=str(raw.get('description') or '').strip()[:2000],
            source='llm_proposed', concept=adopt,
        )
        if adopt is None:
            ensure_node_concept(child)
        else:
            adopt.topics.add(topic)
        summary['proposed_subtopics'] += 1


def _choose_packs(subjects, call, summary):
    from intelligence.models import SkillPack

    packs = {pack.key: pack.label for pack in SkillPack.objects.filter(active=True)}
    payload = {'packs': [{'key': key, 'label': label} for key, label in sorted(packs.items())],
               'subjects': [{'id': str(subject.id), 'name': subject.name} for subject in subjects]}
    reply = _ask_json(call, PACK_SYSTEM, payload, summary)
    chosen = {}
    for raw in (reply or {}).get('subjects') or []:
        if isinstance(raw, dict) and isinstance(raw.get('packs'), list):
            chosen[str(raw.get('id'))] = [key for key in raw['packs'] if key in packs]
    return chosen


def _build(course, call, packs, summary):
    from exams.models import Topic
    from intelligence.models import CourseSyllabus, SkillPack, SyllabusNode

    record, _ = CourseSyllabus.objects.get_or_create(
        course=course, defaults={
            'tenant': course.tenant,
            'audience': f'Learners of "{course.name}" ({course.get_course_type_display()})'[:200],
        })
    subjects = list(course.subjects.all().order_by('order', 'name'))
    for subject in subjects:
        summary['subjects'] += 1
        used = set(SyllabusNode.objects.filter(subject=subject).values_list('key', flat=True))
        before = set(SyllabusNode.objects.filter(subject=subject, level='subtopic').values_list('id', flat=True))
        topics = list(Topic.objects.filter(subject=subject, parent_topic__isnull=True).order_by('order', 'name'))
        topic_nodes = _ensure_groups(subject, topics, call, summary, used)
        topics = [topic for topic in topics if topic.id in topic_nodes]
        _seed_subtopics(subject, topic_nodes, topics, summary, used)
        for topic in topics:
            _propose_subtopics(subject, topic_nodes[topic.id], topic, call, summary, used, before)

    if packs is not None:
        active = set(SkillPack.objects.filter(active=True).values_list('key', flat=True))
        chosen = {str(subject.id): [key for key in packs if key in active] for subject in subjects}
    else:
        chosen = _choose_packs(subjects, call, summary) if subjects else {}
    record.skill_packs = {sid: keys for sid, keys in chosen.items() if keys}
    record.save()
    names = {str(subject.id): subject.name for subject in subjects}
    summary['packs'] = {names[sid]: keys for sid, keys in record.skill_packs.items() if sid in names}


def build_course_tree(course, *, call, packs=None, dry_run=False):
    """Build or extend the syllabus tree of every subject in ``course``."""
    summary = {'subjects': 0, 'sub_subjects_created': 0, 'topics_created': 0, 'seeded_subtopics': 0,
               'proposed_subtopics': 0, 'llm_calls': 0, 'packs': {}, 'dry_run': dry_run}
    try:
        with transaction.atomic():
            _build(course, call, packs, summary)
            if dry_run:
                raise _Rollback
    except _Rollback:
        pass
    return summary
