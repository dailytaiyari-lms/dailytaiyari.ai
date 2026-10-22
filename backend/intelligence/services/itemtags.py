"""Applying intelligence metadata (concepts, difficulty, cognitive type) to items.

Shared by the generators (mockgen/coursegen tag at creation, source
='generator') and the LLM tagging sweep (source='llm_tagger'). Manual links
are never touched by either.
"""
import hashlib
import json

from django.utils import timezone

from .normalize import resolve_concept

SECONDARY_WEIGHT = 0.5


def mock_item_hash(row):
    """Semantic content hash for a MockTestItem row."""
    payload = {
        'type': row.item_type,
        'text': (row.question_text or '').strip(),
        'options': [
            [str(option.get('text') or '').strip(), bool(option.get('is_correct'))]
            for option in row.options or []
        ],
        'numerical': str(row.numerical_answer) if row.numerical_answer is not None else None,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def question_hash(question):
    """Semantic content hash for a bank Question row."""
    payload = {
        'type': question.question_type,
        'text': (question.question_text or '').strip(),
        'options': [
            [option.option_text.strip(), option.is_correct]
            for option in question.options.order_by('order')
        ],
        'correct': (question.correct_answer or '').strip(),
        'numerical': str(question.numerical_answer) if question.numerical_answer is not None else None,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def content_hash_for(item):
    from quiz.models import MockTestItem

    return mock_item_hash(item) if isinstance(item, MockTestItem) else question_hash(item)


def replace_links(item, concepts, *, source, tagger_version=''):
    """Replace ``item``'s concept links of one source with ``concepts``.

    ``concepts`` is an ordered list of Concept rows, most central first.
    Links from other sources (especially 'manual') are preserved; a concept
    already linked by another source is not duplicated.
    """
    from quiz.models import MockTestItem

    from intelligence.models import ConceptLink

    arm = 'mock_item' if isinstance(item, MockTestItem) else 'question'
    item.concept_links.filter(source=source).delete()
    kept = set(item.concept_links.values_list('concept_id', flat=True))

    links = []
    for position, concept in enumerate(concepts):
        if concept is None or concept.id in kept:
            continue
        kept.add(concept.id)
        links.append(ConceptLink(
            tenant=item.tenant,
            concept=concept,
            weight=1.0 if position == 0 else SECONDARY_WEIGHT,
            is_primary=position == 0,
            source=source,
            tagger_version=tagger_version,
            **{arm: item},
        ))
    if links:
        ConceptLink.objects.bulk_create(links)
    return links


def set_item_tags(item, *, concept_labels, subject, topic=None, source,
                  difficulty=None, cognitive_type=None, tagger_version='',
                  overwrite_difficulty=False):
    """Resolve labels and stamp full intelligence metadata onto one item.

    ``subject`` is required for concept resolution (concepts are namespaced
    per subject); callers that cannot determine a subject should skip concept
    tagging entirely and leave the item for the tagging sweep.

    Difficulty is only written when the item is still untagged (or
    ``overwrite_difficulty``), so an author's explicit choice survives.
    """
    was_untagged = not item.tagging_status

    concepts = []
    for label in concept_labels or []:
        concept = resolve_concept(item.tenant, subject, label, source=source, topic=topic)
        if concept and concept.id not in {c.id for c in concepts}:
            concepts.append(concept)

    replace_links(item, concepts, source=source, tagger_version=tagger_version)

    update_fields = ['content_hash', 'tagging_status', 'tagged_at', 'updated_at']
    item.content_hash = content_hash_for(item)
    item.tagging_status = 'tagged'
    item.tagged_at = timezone.now()

    if difficulty in ('easy', 'medium', 'hard') and (overwrite_difficulty or was_untagged):
        item.difficulty = difficulty
        update_fields.append('difficulty')
    if cognitive_type in ('recall', 'application', 'multi_concept'):
        item.cognitive_type = cognitive_type
        update_fields.append('cognitive_type')

    if hasattr(item, 'subject_id') and getattr(item, 'subject_id', None) is None and subject is not None:
        item.subject = subject
        update_fields.append('subject')
    if hasattr(item, 'topic_id') and getattr(item, 'topic_id', None) is None:
        anchor = topic or (concepts[0].topics.first() if concepts else None)
        if anchor is not None:
            item.topic = anchor
            update_fields.append('topic')

    item.save(update_fields=list(dict.fromkeys(update_fields)))
    return concepts


def mark_stale_if_changed(item):
    """Flip a tagged item to 'stale' when its semantic content has changed."""
    if not item.content_hash:
        return False
    new_hash = content_hash_for(item)
    if new_hash != item.content_hash and item.tagging_status == 'tagged':
        item.tagging_status = 'stale'
        item.save(update_fields=['tagging_status', 'updated_at'])
        return True
    return False
