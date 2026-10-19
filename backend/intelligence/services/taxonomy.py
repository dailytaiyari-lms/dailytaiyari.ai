"""Tag vocabulary and exam syllabus trees: YAML config → validated data → DB.

The YAML files under ``intelligence/taxonomy/`` are the source of truth
(decision D4). Validation runs before any write and reports every problem at
once. Nothing is ever deleted: a key that disappears from the file is
deactivated, so existing tags keep their meaning.
"""
import hashlib
import re
import uuid

import yaml
from django.db import transaction
from django.db.models import Max

KEY_RE = re.compile(r'^[a-z0-9][a-z0-9_]*$')
TREE_LEVELS = ('subject', 'sub_subject', 'topic', 'subtopic')
WEIGHT_TOLERANCE = 0.02
DEFAULT_REVIEW_THRESHOLD = 0.6


class TaxonomyError(ValueError):
    """Invalid taxonomy YAML; ``errors`` lists every problem found."""

    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__('; '.join(self.errors))


def read_yaml(path):
    """(parsed data, sha256 of the file text)."""
    with open(path, encoding='utf-8') as handle:
        text = handle.read()
    return yaml.safe_load(text) or {}, hashlib.sha256(text.encode('utf-8')).hexdigest()


def _text(value):
    return str(value if value is not None else '').strip()


def _entries(raw, where, errors, seen=None):
    """Validate a list of {key, label, definition[, active]} entries."""
    seen = set() if seen is None else seen
    if not isinstance(raw, list):
        errors.append(f'{where}: must be a list')
        return []
    clean = []
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            errors.append(f'{where}[{index}]: must be a mapping')
            continue
        key = entry.get('key')
        if not isinstance(key, str) or not KEY_RE.match(key):
            errors.append(f'{where}[{index}]: key {key!r} must be lower_snake_case')
            continue
        if key in seen:
            errors.append(f'{where}.{key}: duplicate key')
            continue
        seen.add(key)
        for field in ('label', 'definition'):
            if not _text(entry.get(field)):
                errors.append(f'{where}.{key}: {field} is required')
        clean.append({
            'key': key,
            'label': _text(entry.get('label')),
            'definition': _text(entry.get('definition')),
            'active': entry.get('active', True) is not False,
        })
    return clean


def validate_tags(data):
    """Validate parsed tags.yaml. Returns the normalized vocabulary or raises."""
    if not isinstance(data, dict):
        raise TaxonomyError(['tags.yaml: the top level must be a mapping'])
    errors = []
    if not _text(data.get('version')):
        errors.append('version is required')
    threshold = data.get('review_confidence_threshold', DEFAULT_REVIEW_THRESHOLD)
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0 < threshold < 1:
        errors.append('review_confidence_threshold must be a number between 0 and 1')
        threshold = DEFAULT_REVIEW_THRESHOLD
    thinking = _entries(data.get('thinking_levels') or [], 'thinking_levels', errors)
    if not thinking:
        errors.append('thinking_levels must not be empty')
    formats = _entries(data.get('special_formats') or [], 'special_formats', errors)

    skills = data.get('skills') or {}
    if not isinstance(skills, dict):
        errors.append('skills: must be a mapping with universal and packs')
        skills = {}
    skill_keys = set()  # unique across universal and every pack
    universal = _entries(skills.get('universal') or [], 'skills.universal', errors, skill_keys)
    packs, pack_keys = [], set()
    for index, pack in enumerate(skills.get('packs') or []):
        where = f'skills.packs[{index}]'
        if not isinstance(pack, dict):
            errors.append(f'{where}: must be a mapping')
            continue
        key = pack.get('key')
        if not isinstance(key, str) or not KEY_RE.match(key) or key in pack_keys:
            errors.append(f'{where}: key {key!r} must be unique lower_snake_case')
            continue
        pack_keys.add(key)
        applies_to = [_text(name) for name in pack.get('applies_to') or [] if _text(name)]
        if not applies_to:
            errors.append(f'skills.packs.{key}: applies_to must list at least one subject name')
        if not _text(pack.get('label')):
            errors.append(f'skills.packs.{key}: label is required')
        packs.append({
            'key': key,
            'label': _text(pack.get('label')),
            'applies_to': applies_to,
            'active': pack.get('active', True) is not False,
            'skills': _entries(pack.get('skills') or [], f'skills.packs.{key}.skills', errors, skill_keys),
        })
    if errors:
        raise TaxonomyError(errors)
    return {
        'version': _text(data.get('version')),
        'review_confidence_threshold': float(threshold),
        'thinking_levels': thinking,
        'special_formats': formats,
        'universal_skills': universal,
        'packs': packs,
    }


def _tree_level(raw, depth, path, errors):
    level = TREE_LEVELS[depth]
    if not isinstance(raw, list) or not raw:
        errors.append(f'{path}: needs a non-empty list of {level} nodes')
        return []
    clean, seen, weights = [], set(), []
    for index, node in enumerate(raw):
        if not isinstance(node, dict):
            errors.append(f'{path}[{index}]: must be a mapping')
            continue
        key = node.get('key')
        if not isinstance(key, str) or not KEY_RE.match(key):
            errors.append(f'{path}[{index}]: key {key!r} must be lower_snake_case')
            continue
        if key in seen:
            errors.append(f'{path}.{key}: duplicate key')
            continue
        seen.add(key)
        if not _text(node.get('label')):
            errors.append(f'{path}.{key}: label is required')
        weight = node.get('weightage', 0)
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or weight < 0:
            errors.append(f'{path}.{key}: weightage must be a number >= 0')
            weight = 0
        weights.append(float(weight))
        entry = {
            'key': key,
            'label': _text(node.get('label')),
            'description': _text(node.get('description')),
            'weightage': float(weight),
            'in_syllabus': node.get('in_syllabus', True) is not False,
            'aliases': [_text(alias) for alias in node.get('aliases') or [] if _text(alias)],
        }
        if depth + 1 < len(TREE_LEVELS):
            entry['children'] = _tree_level(node.get('children'), depth + 1, f'{path}.{key}', errors)
        elif node.get('children'):
            errors.append(f'{path}.{key}: subtopics cannot have children')
        clean.append(entry)
    total = sum(weights)
    if total and abs(total - 1.0) > WEIGHT_TOLERANCE:
        errors.append(f'{path}: {level} weightages sum to {total:.3f}; expected 1 (or all 0)')
    return clean


def validate_exam_tree(data):
    """Validate a parsed exam tree YAML. Returns the normalized tree or raises."""
    if not isinstance(data, dict):
        raise TaxonomyError(['exam tree: the top level must be a mapping'])
    errors = []
    key = data.get('key')
    if not isinstance(key, str) or not KEY_RE.match(key):
        errors.append(f'key {key!r} must be lower_snake_case')
        key = '?'
    for field in ('label', 'audience', 'version'):
        if not _text(data.get(field)):
            errors.append(f'{field} is required')
    subjects = _tree_level(data.get('subjects'), 0, key, errors)
    if errors:
        raise TaxonomyError(errors)
    return {
        'key': key,
        'label': _text(data.get('label')),
        'audience': _text(data.get('audience')),
        'version': _text(data.get('version')),
        'subjects': subjects,
    }


def flatten_tree(tree):
    """Every node of a validated tree in pre-order, with full dotted keys.

    ``in_syllabus`` is inherited: a node under an out-of-syllabus parent is
    out of syllabus too.
    """
    flat = []

    def walk(nodes, depth, parent_key, subject_key, parent_in_syllabus):
        for order, node in enumerate(nodes):
            key = f'{parent_key}.{node["key"]}'
            subject = subject_key or node['key']
            in_syllabus = parent_in_syllabus and node['in_syllabus']
            flat.append({
                'key': key,
                'local_key': node['key'],
                'level': TREE_LEVELS[depth],
                'parent_key': parent_key,
                'subject': subject,
                'label': node['label'],
                'description': node['description'],
                'weightage': node['weightage'],
                'in_syllabus': in_syllabus,
                'aliases': node['aliases'],
                'order': order,
            })
            walk(node.get('children') or [], depth + 1, key, subject, in_syllabus)

    walk(tree['subjects'], 0, tree['key'], None, True)
    return flat


def load_tags(path=None):
    """(validated vocabulary, sha256) from tags.yaml."""
    from intelligence.taxonomy import TAGS_FILE

    data, sha = read_yaml(path or TAGS_FILE)
    return validate_tags(data), sha


def shipped_exam_keys():
    from intelligence.taxonomy import EXAMS_DIR

    return sorted(path.stem for path in EXAMS_DIR.glob('*.yaml'))


def load_exam_tree(exam_key):
    """The validated tree from ``taxonomy/exams/<exam_key>.yaml``."""
    from intelligence.taxonomy import EXAMS_DIR

    if not isinstance(exam_key, str) or not KEY_RE.match(exam_key):
        raise TaxonomyError([f'unknown exam tree {exam_key!r}'])
    path = EXAMS_DIR / f'{exam_key}.yaml'
    if not path.exists():
        raise TaxonomyError([f'no exam tree file for {exam_key!r}'])
    data, _ = read_yaml(path)
    tree = validate_exam_tree(data)
    if tree['key'] != exam_key:
        raise TaxonomyError([f'{path.name}: key {tree["key"]!r} does not match the file name'])
    return tree


def current_release():
    from intelligence.models import TaxonomyRelease

    return TaxonomyRelease.objects.order_by('-sequence').first()


@transaction.atomic
def sync_vocabulary(tags, file_sha256):
    """Upsert a validated vocabulary. Never deletes; missing keys deactivate."""
    from intelligence.models import SkillPack, TagDefinition, TaxonomyRelease

    summary = {'upserted': 0, 'deactivated': 0, 'release': None}
    kept = {
        TagDefinition.KIND_THINKING: set(),
        TagDefinition.KIND_FORMAT: set(),
        TagDefinition.KIND_SKILL: set(),
    }

    def upsert(kind, entry, order, pack=None):
        TagDefinition.objects.update_or_create(
            kind=kind, key=entry['key'],
            defaults={
                'tenant': None, 'label': entry['label'], 'definition': entry['definition'],
                'active': entry['active'], 'pack': pack, 'order': order,
            },
        )
        kept[kind].add(entry['key'])
        summary['upserted'] += 1

    for order, entry in enumerate(tags['thinking_levels']):
        upsert(TagDefinition.KIND_THINKING, entry, order)
    for order, entry in enumerate(tags['special_formats']):
        upsert(TagDefinition.KIND_FORMAT, entry, order)
    for order, entry in enumerate(tags['universal_skills']):
        upsert(TagDefinition.KIND_SKILL, entry, order)
    pack_keys = set()
    for pack_index, pack in enumerate(tags['packs'], start=1):
        pack_row, _ = SkillPack.objects.update_or_create(
            key=pack['key'],
            defaults={
                'tenant': None, 'label': pack['label'],
                'applies_to': pack['applies_to'], 'active': pack['active'],
            },
        )
        pack_keys.add(pack['key'])
        for order, entry in enumerate(pack['skills']):
            upsert(TagDefinition.KIND_SKILL, entry, pack_index * 1000 + order, pack=pack_row)

    for kind, keys in kept.items():
        summary['deactivated'] += (
            TagDefinition.objects.filter(kind=kind, active=True).exclude(key__in=keys)
            .update(active=False)
        )
    SkillPack.objects.filter(active=True).exclude(key__in=pack_keys).update(active=False)

    latest = current_release()
    if latest is None or latest.file_sha256 != file_sha256:
        sequence = (TaxonomyRelease.objects.aggregate(top=Max('sequence'))['top'] or 0) + 1
        summary['release'] = TaxonomyRelease.objects.create(
            tenant=None, sequence=sequence, version=tags['version'], file_sha256=file_sha256,
            review_confidence_threshold=tags['review_confidence_threshold'],
        )
    return summary


def mark_subjects_stale(subject_ids):
    """Flip tagged items of these subjects to 'stale' so the sweep re-tags them."""
    from quiz.models import MockTestItem, Question

    ids = []
    for raw in subject_ids:
        try:
            ids.append(uuid.UUID(str(raw)))
        except ValueError as exc:
            raise TaxonomyError([f'not a subject id: {raw!r}']) from exc
    marked = Question.objects.filter(subject_id__in=ids, tagging_status='tagged').update(
        tagging_status='stale')
    marked += MockTestItem.objects.filter(subject_id__in=ids, tagging_status='tagged').update(
        tagging_status='stale')
    return marked
