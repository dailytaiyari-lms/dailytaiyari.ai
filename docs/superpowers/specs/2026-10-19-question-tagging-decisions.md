# Question Tagging v2 — Agreed Decisions (Learning Layer, sub-project 2)

**Status:** decisions agreed in design discussion, 2026-10-19. A full spec
and plan follow after sub-project 1 (response diagnosis) is under way.
**Replaces:** the flat, open-vocabulary tagger in
`backend/intelligence/services/tagging.py`.

## Why

The current tagger is exam-blind. "JEE" never reaches the prompt, and
"difficulty for the stated audience" has no audience. Its concepts are a flat
list per subject that grows from LLM-invented names. Only spelling variants
merge, and concepts older than the 150-name candidate window drift into
duplicates. It records no confidence, has no review path and no evaluation,
so the model choice is a guess. Its question nature is only 3 values.

## D1 — Every question is tagged on these levels

| Level | Values | Source |
|---|---|---|
| Syllabus location | primary subtopic + any secondary subtopics. Subject → sub-subject → topic is derived from the tree. | LLM, choosing from the course's tree |
| Difficulty | `easy` · `medium` · `hard`, at the **exam's** level | LLM prior; observed difficulty (`ItemStats`) takes over once there is enough data |
| Format | the structural type (MCQ single/multi, numerical/integer, match, true/false, fill-blank, short answer, long answer, coding) **plus** detected special formats (assertion–reason, paragraph-based, matrix-match) | structure first; LLM only for the special formats; short vs long from word limit or marks, else LLM |
| Thinking level | **exactly one** (D2) | LLM |
| Skills | **every applicable skill, no cap** (D3), each `core` or `supporting`, each with a one-line reason | LLM |
| Estimated solve time | seconds, never shown to users | LLM. Replaces the diagnosis default usual-time table until `ItemStats` has real timings. |
| Confidence | per question | LLM. Low confidence → teacher review queue. |

## D2 — Thinking level (exactly one: the highest the question demands)

| Key | Definition |
|---|---|
| `recall` | Remember a fact, definition, formula, unit or name |
| `conceptual` | Explain or predict qualitatively; no calculation needed |
| `single_application` | Apply one concept or formula in a standard way |
| `multi_concept` | Must combine two or more subtopics to reach the answer |
| `analytical` | Unusual problem; needs insight, a trick, or building the approach |

`recall` and `multi_concept` keep today's `cognitive_type` keys, so
`services/state.py` (the transfer split) keeps working. A data migration maps
`application` → `single_application`.

## D3 — Skills (all that apply; core = weight 1.0, supporting = 0.5)

There is no limit on the number of skills per question. The core/supporting
weighting keeps a wrong answer on a six-skill question from counting fully
against all six.

- **Universal:** `formula_application`, `numerical_computation`,
  `algebraic_manipulation`, `derivation`, `graph_interpretation`,
  `diagram_interpretation`, `data_analysis`, `units_dimensions`,
  `approximation`, `case_analysis`, `spatial_visualization`,
  `statement_evaluation`, `passage_comprehension`.
- **Physics pack:** `free_body_diagram`, `conservation_law_choice`,
  `vector_resolution`, `sign_convention`.
- **Chemistry pack:** `reaction_mechanism`, `named_reaction_reagent`,
  `nomenclature`, `stoichiometry`, `periodic_trend_reasoning`.
- **Maths pack:** `calculus_technique`, `counting_combinatorics`,
  `coordinate_setup`, `inequality_reasoning`, `pattern_recognition`.
- **Biology pack (NEET, later):** `classification`, `process_sequencing`.

The lists are accepted "for now" and must stay easy to change (D4).

## D4 — Every list is editable config, not code

- The source of truth is `backend/intelligence/taxonomy/tags.yaml`, versioned
  in git. It holds `version`, `difficulty`, `formats`, `thinking_levels`, and
  `skills` (`universal` + `packs`, each pack naming the course subjects it
  applies to, matched by name or alias). Every entry has a stable `key`, a
  `label`, a `definition` (what the LLM tags against) and an `active` flag.
- `manage.py sync_taxonomy` validates the file (unique keys, non-empty
  definitions, packs pointing at real subjects) and loads it into the
  database. The tagger reads only from the database.
- Effect of each kind of edit:

  | Edit | Effect |
  |---|---|
  | Change a label | Display only, nothing re-tags. Keys never change. |
  | Add a tag | Run `sync_taxonomy --retag` for the affected subjects. The taxonomy `version` is part of the tagging cache key. |
  | Change a definition's meaning | Bump `version`, then re-tag. |
  | Remove a tag | Set `active: false`. History is kept; the tag is no longer offered or shown. |

- An admin editing UI can come later, on the same tables.

## D5 — Where syllabus trees come from: hybrid

- **Exam courses:** the platform ships trees for JEE Main, JEE Advanced and
  NEET in `taxonomy/exams/<exam>.yaml`, at subject → sub-subject → topic →
  subtopic, with exam weightage per node.
  - Each tree is drafted once by the LLM from the official syllabus and
    reviewed by a person, then synced like D4.
  - A course mapped to an exam tags against that fixed tree, so analytics are
    consistent and comparable across tenants.
  - The tagger proposes concepts outside the tree for review; it never
    silently creates them.
- **Custom courses:** the tree is built from the course's own Subjects and
  Topics. The LLM proposes sub-subjects and subtopics when the course is
  generated, and the teacher can edit them.
- The existing course `Chapter` model is the course's teaching structure, not
  the syllabus, so it is not reused as the sub-subject level. Course topics
  are *mapped* onto tree nodes.

## D6 — How tagging runs

- The generators (mockgen, coursegen, practice generation) emit the full D1
  tag set as they create questions.
- The sweep tags everything else in two stages: first pick the topic from
  the tree, then the subtopics and remaining tags within that topic. This
  keeps prompts small on JEE-sized trees.
- Cache key: content hash + prompt version + taxonomy version + model.
- Teacher edits are locked (`source='manual'`, never overwritten by the
  tagger) and become evaluation data.

## D7 — What the analytics gain

- Subtopic mastery (the existing engine) rolls up to topic, sub-subject and
  subject, weighted by exam weightage.
- New per-student, per-subject **skill** and **thinking-level** states use
  the same recompute-from-events engine. Core skills weigh 1.0, supporting
  0.5.

## D8 — Choosing the tagging model

- `manage.py evaluate_tagger --gold <file> --models a,b,c` scores each model
  against a hand-tagged gold set (target: about 200 JEE questions) on every
  D1 level, plus cost per 1,000 questions.
- Candidates: an open/self-hosted model, a GPT mini-class model, and Claude
  Haiku, all through the existing per-tenant `tagging_model` resolution.

## D9 — Sequencing

1. Sub-project 1 (response diagnosis) runs first. It doesn't depend on the
   new tags, and its usual-time statistics need weeks of real timing data.
2. Then this sub-project's full spec and plan.
3. Then one small follow-up in diagnosis: prefer the item's
   estimated solve time over `DEFAULT_USUAL_S` while `ItemStats` is thin.

## D10 — Two test tracks (decided 2026-10-19)

A production copy audit found that real content is mostly skill and
programming courses:

| Course | Questions |
|---|---|
| DSA sheet | 210 |
| Aptitude | 156 |
| Pygame | 155 |
| Python, AI/ML | (several courses) |
| Class XI PCM (board) | 129 |
| "JEE Mains" | 0 |

All 1,260 bank questions are single-answer MCQs, 664 have no tags, and
`TopicCourseRelevance` is empty. So tagging is built and tested on two
separate tracks.

**Track A — JEE, on generated dummy data.**
- A dev-only, seeded generator builds a synthetic tenant, a JEE Main course
  mapped to the shipped tree, and questions across every JEE format:
  - single and multi-correct;
  - integer/numerical;
  - assertion–reason;
  - paragraph-based;
  - matrix-match.
- Each question is generated *with* its intended tags, so the output doubles
  as a gold set. It is biased towards easy cases, because the same model
  family writes and tags it. A hand-checked subset guards against that.
- Synthetic students with known per-concept ability and scripted behaviour
  (guessing, slipping, running out of time) give end-to-end ground truth for
  tagging, diagnosis labels, mastery and recommendations.

**Track B — existing courses, against the production copy.**
- Separate instrumentation for the course-built trees that real courses need:
  - LLM-proposed sub-subjects and subtopics on top of their existing 86
    subjects and 532 topics;
  - skill packs for programming, aptitude and AI/ML content (proposed below,
    not yet approved).
- Tested against `dt_prod_work`. The gold set is a hand-verified sample of
  real questions from the largest courses.
- Production AI provider keys are blanked in `dt_prod_work`. LLM runs need a
  dedicated local key.

**Proposed skill packs for Track B (pending approval):**

| Pack | Skills |
|---|---|
| Programming | `code_tracing`, `debugging`, `syntax_recall`, `algorithm_design`, `complexity_analysis`, `data_structure_choice`, `edge_case_reasoning`, `api_library_usage` |
| Aptitude | `quantitative_shortcut`, `logical_deduction`, `verbal_reasoning`, `data_sufficiency` (with the universal `numerical_computation`, `data_analysis` and `pattern_recognition`) |
| AI/ML | `model_selection`, `metric_interpretation`, `data_preprocessing`, `prompt_design` |

## Still to decide in the full spec

- Data model: whether tree nodes are a new `SyllabusNode` table with
  subtopics linked to `Concept` rows, or `Concept` itself gains tree levels.
  Also how platform-scoped (cross-tenant) nodes coexist with tenant-scoped
  `Concept.subject` foreign keys.
- Who hand-tags the gold set, and its exact size.
- The review-queue UI and its confidence threshold.
- Migration of existing flat concepts onto the trees for exam-mapped courses.
