"""Version constants stamped onto stored inference so it can be recomputed.

Bump a version when its algorithm/prompt/ontology semantics change, then re-run
the matching recompute command — state is always derived from events, never
migrated in place.
"""

# LearningEvent row shape.
EVENT_SCHEMA_VERSION = '1'

# LearnerConceptState algorithm (services/state.py).
STATE_MODEL_VERSION = '1'

# ItemStats computation (services/itemstats.py).
ITEM_STATS_VERSION = '1'

# LLM item-tagging prompt (services/tagging.py). Part of the cache key: a new
# prompt invalidates cached tag results.
TAGGER_PROMPT_VERSION = '1'

# Concept ontology conventions (normalization rules, generic-label policy).
ONTOLOGY_VERSION = '1'
