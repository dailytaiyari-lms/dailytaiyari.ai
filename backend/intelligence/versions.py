"""Version constants stamped onto stored inference so it can be recomputed.

Bump a version when its algorithm/prompt/ontology semantics change, then re-run
the matching recompute command — state is always derived from events, never
migrated in place.
"""

# LearningEvent row shape.
EVENT_SCHEMA_VERSION = '1'

# LearnerConceptState algorithm (services/state.py).
STATE_MODEL_VERSION = '2'

# ItemStats computation (services/itemstats.py).
ITEM_STATS_VERSION = '1'

# LLM item-tagging prompt (services/tagging.py). Part of the cache key: a new
# prompt invalidates cached tag results.
TAGGER_PROMPT_VERSION = '1'

# Concept ontology conventions (normalization rules, generic-label policy).
ONTOLOGY_VERSION = '1'

# Response diagnosis rules + thresholds (services/diagnosis.py,
# diagnosis_config.py). Bump, then run ``recompute_diagnoses``.
CLASSIFIER_VERSION = '1'

# Tagger v2 prompts (services/tagging_v2.py). Part of the v2 cache key; v1's
# TAGGER_PROMPT_VERSION stays as is while v1 still tags subjects with no tree.
TAGGER_V2_PROMPT_VERSION = '2'

# Skill / thinking-level facet algorithm (services/facets.py, the facet
# weights in progress_config.py). Bump, then run ``recompute_learner_state``.
FACET_MODEL_VERSION = '1'
