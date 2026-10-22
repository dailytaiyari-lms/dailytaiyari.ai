"""Concept label normalization and resolution.

Free-text concept labels arrive from three generators (mockgen, coursegen,
the LLM tagger) and from humans. This module is the single funnel that turns
a raw label into a canonical ``Concept`` row, so the same idea never exists
twice under trivially different spellings. No LLM is ever called here.
"""
from django.utils.text import slugify

# Labels that carry no diagnostic value (mirrors chatbot.GENERIC_TOPIC_LABELS,
# which stays in place for the AI-quiz flow; this is the superset used for
# concept resolution).
GENERIC_LABELS = {
    'quiz', 'quizzes', 'practice', 'practice quiz', 'practice quizzes',
    'practice questions', 'ai quiz', 'ai generated quiz', 'ai-generated quiz',
    'general', 'general quiz', 'general knowledge', 'misc', 'miscellaneous',
    'mcq', 'mcqs', 'test', 'mock test', 'questions', 'revision', 'topic',
    'untitled', 'n/a', 'na', 'none', 'other', 'others', 'concept', 'concepts',
    'basics', 'fundamentals', 'introduction', 'overview',
}

# Leading noise phrases stripped before slugging.
_STRIP_PREFIXES = ('introduction to ', 'intro to ', 'basics of ', 'the ')


def normalize_concept_label(value):
    """Clean a raw concept label, or return '' when it is useless."""
    if not value or not isinstance(value, str):
        return ''
    label = value.replace('*', '').replace('#', '').replace('`', '').strip()
    label = ' '.join(label.split())
    label = label.strip(' .:-–—"\'')
    if not label or len(label) < 2:
        return ''
    if label.casefold() in GENERIC_LABELS:
        return ''
    return label[:200]


def _light_singular(word):
    """Conservative singularization: only a plain trailing 's'.

    Leaves 'gas', 'lens', 'analysis', 'calculus' etc. alone by requiring
    length > 3 and skipping -ss/-us/-is endings.
    """
    if len(word) > 3 and word.endswith('s') and not word.endswith(('ss', 'us', 'is')):
        return word[:-1]
    return word


def concept_slug(label):
    """Deterministic slug for a normalized label ('' when not slugworthy)."""
    label = normalize_concept_label(label)
    if not label:
        return ''
    lowered = label.casefold()
    for prefix in _STRIP_PREFIXES:
        if lowered.startswith(prefix) and len(lowered) > len(prefix) + 2:
            lowered = lowered[len(prefix):]
            break
    words = [_light_singular(w) for w in lowered.split()]
    return slugify(' '.join(words))[:220]


def _follow_merge_chain(concept, _seen=None):
    """Resolve to the canonical concept through any merge chain."""
    seen = _seen or set()
    while concept.merged_into_id and concept.status == 'merged' and concept.id not in seen:
        seen.add(concept.id)
        concept = concept.merged_into
    return concept


def resolve_concept(tenant, subject, raw_label, *, source='manual', topic=None):
    """Resolve (or create) the canonical Concept for a raw label.

    Returns None for generic/empty labels. Always leaves an alias row behind
    so the next resolution of the same raw string is a pure index lookup.
    """
    from intelligence.models import Concept, ConceptAlias

    label = normalize_concept_label(raw_label)
    slug = concept_slug(raw_label)
    if not label or not slug:
        return None

    concept = Concept.objects.filter(tenant=tenant, subject=subject, slug=slug).first()
    if concept is None:
        alias = (
            ConceptAlias.objects
            .filter(tenant=tenant, subject=subject, alias_slug=slug)
            .select_related('concept')
            .first()
        )
        if alias:
            concept = _follow_merge_chain(alias.concept)

    if concept is None:
        concept = Concept.objects.create(
            tenant=tenant, subject=subject, name=label, slug=slug, source=source,
        )
    else:
        concept = _follow_merge_chain(concept)

    # Record the raw spelling as an alias (idempotent).
    ConceptAlias.objects.get_or_create(
        tenant=tenant, subject=subject, alias_slug=slug,
        defaults={'concept': concept, 'raw_label': label},
    )

    if topic is not None and not concept.topics.filter(id=topic.id).exists():
        concept.topics.add(topic)

    return concept


def merge_concept(loser, winner):
    """Merge ``loser`` into ``winner``: re-point links and aliases, mark merged.

    Callers are responsible for recomputing affected learner states afterwards
    (``recompute_learner_state`` command).
    """
    from intelligence.models import ConceptLink, LearnerConceptState

    if loser.id == winner.id:
        return winner

    # Re-point links, dropping ones that would collide with an existing link.
    for link in ConceptLink.objects.filter(concept=loser):
        exists = ConceptLink.objects.filter(
            concept=winner, question=link.question, mock_item=link.mock_item,
        ).exists()
        if exists:
            link.delete()
        else:
            link.concept = winner
            link.save(update_fields=['concept'])

    loser.aliases.update(concept=winner)
    LearnerConceptState.objects.filter(concept=loser).delete()

    loser.status = 'merged'
    loser.merged_into = winner
    loser.save(update_fields=['status', 'merged_into'])
    return winner


def concepts_for(item):
    """List of (concept, weight, is_primary) for a Question or MockTestItem."""
    return [
        (link.concept, link.weight, link.is_primary)
        for link in item.concept_links.select_related('concept')
    ]
