# Question Tagging v2 — Design (Learning Layer, sub-project 2)

**Status:** draft for review, 2026-10-19.
**Builds on:** the decisions in
[`2026-10-19-question-tagging-decisions.md`](2026-10-19-question-tagging-decisions.md)
(D1–D10). This spec does not repeat them. Where it settles one of that
file's "still to decide" points, or changes a decision, it says so under
**Decided here**.
**Replaces:** the flat, open-vocabulary tagger in
`backend/intelligence/services/tagging.py`.

## 1. Scope and delivery

Sub-project 2 is delivered as two plans. Each one ships working software on
its own.

| Plan | Delivers | Test track |
|---|---|---|
| **2A — Taxonomy, trees, tagger v2, evaluation** | Tag config (YAML) and sync; syllabus trees (JEE Main, plus course-built trees); the two-stage tagger with confidence; the JEE lab importer; `evaluate_tagger` | Tagging accuracy on Track A (JEE question bank) and Track B (real courses) |
| **2B — Tag-powered analytics** | Roll-ups and skill/thinking-level states; teacher review queue and tree editing; generators emitting v2 tags; synthetic students run end to end; solve-time estimate fed into diagnosis | Diagnosis, mastery and recommendations against synthetic ground truth |

This spec covers both plans. Plan 2A is written and built first. The model
is `gpt-6-luna` on the Azure UAT experiment resource; other models are
scored by the same `evaluate_tagger` once they are deployed.

## 2. Data model

All new models live in the `intelligence` app. They inherit
`TimeStampedModel`: UUID primary key, nullable `tenant`, and timestamps. Other
apps keep reaching them only through `intelligence.api`.

### 2.1 Tag vocabulary (platform-wide, `tenant = NULL`)

- **`TaxonomyRelease`**
  - Fields: `version`, `file_sha256`, `synced_at`.
  - One row per `sync_taxonomy` run that changed anything. The current
    version is the newest row.
- **`SkillPack`**
  - Fields: `key`, `label`, `applies_to` (JSON list of subject names or
    aliases, matched case-insensitively against `Subject.name` and
    `Subject.code`), `active`.
- **`TagDefinition`**
  - Fields: `kind` (`thinking_level` · `skill` · `special_format`), `key`,
    `label`, `definition`, `pack` (FK `SkillPack`, null for universal skills
    and for non-skill kinds), `active`, `order`.
  - Unique on (`kind`, `key`).
  - Difficulty (`easy`/`medium`/`hard`) and the structural formats stay as
    code choices. They are not editable vocabulary.

### 2.2 Syllabus trees

- **`SyllabusNode`**, tenant-scoped. Fields:
  - `subject` (FK `exams.Subject`, CASCADE); `parent` (self FK, null at the
    top); `level`: `sub_subject` · `topic` · `subtopic`.
  - `key`: stable within the subject.
    - Exam-tree nodes carry the tree's dotted key, e.g.
      `jee_main.physics.mechanics.laws_of_motion.friction`.
    - Course-built nodes use `course.<subject-code>.<slug path>`.
  - `name`, `description`.
  - `weightage`: float, a share within the parent. Siblings sum to 1 when
    known; all 0 means unweighted.
  - `in_syllabus` (bool, default true).
  - `source`: `exam_tree` · `course` · `llm_proposed` · `manual`.
  - `status`: `active` · `proposed` · `archived`.
  - `course_topic`: FK `exams.Topic`, null, SET_NULL. Maps a course Topic
    onto a `topic`-level node.
  - `concept`: OneToOne `Concept`, null, SET_NULL. Every `subtopic` node owns
    exactly one Concept.
  - Unique on (`tenant`, `subject`, `key`).
- **`CourseSyllabus`**, tenant-scoped. Fields:
  - `course`: OneToOne `exams.Course`.
  - `exam_tree`: `''` (custom course) or a tree key such as `jee_main`.
  - `audience`: free text sent to the tagger, e.g. "JEE Main aspirants
    (Class 11–12)".
  - `subject_map`: JSON `{subject_id: tree_subject_key}`.
  - `skill_packs`: JSON `{subject_id: [pack_key, …]}`. This is an explicit
    choice for subjects whose names match no pack, which is common in
    custom courses (e.g. "Arrays & Hashing" → `programming`).
    - A subject listed here uses exactly these packs.
    - A subject not listed falls back to `SkillPack.applies_to` name
      matching.
    - `build_course_tree --packs programming` fills it for every subject of
      the course. Without the flag, one LLM call picks packs per subject
      from the pack labels.
  - `tree_version`: a hash of the active node keys, names and definitions
    per subject. It is part of the tagging cache key.

**Decided here (data model):** a separate `SyllabusNode` tree whose
subtopic leaves own a `Concept`. The alternative, giving `Concept` itself
tree levels, was rejected:
- **Mastery stays at the leaves.** `LearnerConceptState`, alias resolution,
  merging and recommendations keep working unchanged at subtopic level.
- **Roll-ups are computed, not stored as evidence.** Topic, sub-subject and
  subject figures come from the tree and are never recorded as evidence of
  their own.

**Decided here (platform versus tenant trees):** exam trees live in YAML,
which is the platform's source of truth. They are *instantiated* per tenant
when a course is mapped to an exam, keeping the tree's keys. Cross-tenant
analytics compare by `key`. This avoids platform-scoped rows that tenant
foreign keys cannot reference. Re-syncing a tree updates names, definitions
and weights by key. It never deletes a node; a node dropped from the YAML
becomes `archived`.

### 2.3 Item tags

The existing per-item fields stay: `difficulty`, `cognitive_type`,
`content_hash`, `tagging_status` and `topic`. So do the `ConceptLink` rows.
Two tables are added.

- **`ItemTagging`**: one per item. It uses an XOR `question` / `mock_item`
  pair, the same pattern and constraints as `ConceptLink`. Fields:
  - `primary_node` (FK `SyllabusNode`, SET_NULL) and `secondary_nodes` (M2M).
  - `thinking_level` (a key) and `special_format` (a key, or `''`).
  - `difficulty_prior` (the model's value, always stored, even when the item
    keeps an authored difficulty).
  - `est_solve_seconds`.
  - `confidence` (0–1).
  - `review_status`: `auto` · `needs_review` · `reviewed`.
  - `review_reasons` (JSON list): `low_confidence` · `invalid_key` ·
    `proposed_subtopic` · `stage_disagreement`.
  - `proposed_subtopic` (text): the model's suggestion when no subtopic fits.
  - `source`: `llm_tagger` · `generator` · `manual`.
  - `tagger_version`, `taxonomy_version`, `tree_version`, and `raw`
    (the model payload, for audit).
- **`ItemSkillTag`**: the same XOR item pair. Fields: `skill` (FK
  `TagDefinition`, PROTECT), `role` (`core` · `supporting`), `reason`
  (≤ 200 chars) and `source`. Unique on (item, skill).

**Writes stay compatible with what already reads the tags:**
- Primary and secondary subtopics become `ConceptLink` rows through
  `replace_links`: weight 1.0 for the primary subtopic, 0.5 for secondaries,
  source `llm_tagger`.
- `item.topic` is filled from `primary_node`'s topic-level ancestor
  `course_topic`, but only when it is empty.
- `item.cognitive_type` stays a three-value compatibility projection of the
  thinking level: `recall` → `recall`, `multi_concept` → `multi_concept`,
  anything else → `application`.

**Decided here (changes D2):** D2 planned to migrate
`cognitive_type='application'` to `single_application`. Instead, the full
five-value thinking level lives only on `ItemTagging`, and `cognitive_type`
keeps its three quiz-app choices. This keeps the quiz app, mockgen,
practice generation and `state.py` untouched. D2's goal, keeping the
transfer split working, is met either way.

**Manual lock:** an item whose `ItemTagging.source == 'manual'` is never
re-tagged. Its `ConceptLink` rows with source `manual` are already preserved
by `replace_links`.

## 3. Taxonomy config

### 3.1 `tags.yaml`

Path: `backend/intelligence/taxonomy/tags.yaml`. Shape:

```yaml
version: 1
thinking_levels:
  - {key: recall, label: Recall, definition: "Remember a fact, definition, formula, unit or name."}
  # … the five D2 levels
special_formats:
  - {key: assertion_reason, label: Assertion–reason, definition: "…"}
  - {key: statement_pair,   label: Two statements,   definition: "Statement I / Statement II, judge each."}
  - {key: match_list,       label: Match the lists,  definition: "List-I to List-II matching."}
  - {key: paragraph,        label: Paragraph-based,  definition: "…"}
  - {key: matrix_match,     label: Matrix match,     definition: "…"}
skills:
  universal:
    - {key: formula_application, label: Formula application, definition: "…"}
    # … the D3 universal list
  packs:
    - key: physics
      label: Physics
      applies_to: [physics]
      skills: [{key: free_body_diagram, …}, …]
    # chemistry, maths, biology, plus the D10 programming, aptitude and ai_ml packs
```

- `statement_pair` and `match_list` are added to D1's special formats. The
  JEE Main bank has 263 and 163 of them respectively, and they are the
  forms JEE Main actually uses.
- Each entry may set `active: false`.
- The D10 Track B packs are included as proposed. Changing them later is an
  edit to this file plus `sync_taxonomy`.

### 3.2 Exam trees

Path: `backend/intelligence/taxonomy/exams/<exam>.yaml`. Shape:

```yaml
key: jee_main
label: JEE Main
audience: "JEE Main (Paper 1) aspirants, Class 11–12 level"
version: 1
subjects:
  - key: physics
    label: Physics
    aliases: [phy]
    weightage: 0.333
    children:                       # sub_subject
      - key: mechanics
        label: Mechanics
        weightage: 0.31
        children:                   # topic
          - key: laws_of_motion
            label: Laws of Motion
            weightage: 0.12
            children:               # subtopic
              - {key: friction, label: Friction, weightage: 0.3}
```

### 3.3 `manage.py sync_taxonomy`

- **Validation** (fails before any write):
  - unique keys per kind and per tree level;
  - non-empty `label` and `definition` for vocabulary entries;
  - pack `applies_to` non-empty;
  - tree depth exactly subject → sub_subject → topic → subtopic;
  - sibling weightages sum to 1 ± 0.02, or are all 0.
- **Load:** upserts by key. Entries missing from the file become
  `active=false`; nothing is deleted. A `TaxonomyRelease` row is written
  when the file hash changes.
- **Flags:**
  - `--check`: validate only. The test suite runs this on the shipped files.
  - `--retag-subjects <ids>`: marks those subjects' items `stale`.
- **Tree instantiation is separate:** `map_course_to_exam --course <id>
  --exam jee_main --subject-map physics=<subject_id>,…` creates or updates
  `CourseSyllabus`, then upserts the subject's nodes from the YAML.
  - A course Topic is linked to a node's `course_topic` when its name
    matches the node label or an alias. The command lists Topics it could
    not match, and they stay unmapped.

## 4. Building the trees

### 4.1 JEE Main tree (Track A)

`manage.py draft_exam_tree --from-eval-jee <jsonl> --out
intelligence/taxonomy/exams/jee_main.yaml` is a **dev-only** command.

- **Levels:**

  | Dataset field | Tree level | Count |
  |---|---|---|
  | subject | subject | 3 |
  | `chapter` | topic | 91 |
  | `topic` | subtopic | 460 |

  Slugs are turned into readable labels, e.g. `laws-of-motion` → "Laws of
  Motion".
- **Sub-subjects** come from a fixed, committed grouping:
  - Physics: Mechanics, Thermal Physics, Oscillations & Waves,
    Electrodynamics, Optics, Modern Physics, Experimental Skills;
  - Chemistry: Physical, Inorganic, Organic;
  - Maths: Algebra, Trigonometry, Coordinate Geometry, Calculus,
    Vectors & 3D, Statistics & Probability.

  The command fails if any chapter is unassigned.
- **Weightage:** each node's share of 2021–2024 questions within its parent.
- **`in_syllabus`:** set to false for chapters outside the current NTA JEE
  Main syllabus, e.g. mathematical reasoning, removed in 2024. The list is
  committed in the command, checked by hand against the NTA syllabus PDF.
- **The YAML is committed.** It contains syllabus names and weights only,
  no question content. After the draft, a person reviews it (labels, merged
  duplicates, the grouping) and then runs `sync_taxonomy --check`.

### 4.2 Course-built trees (Track B)

`manage.py build_course_tree --course <id> [--dry-run]` builds a tree for
each Subject of a custom course:

- **Topic level:** one node per course Topic. `course_topic` is set and the
  source is `course`.
- **Sub-subject level:**
  - If the subject has 6 or fewer topics, one implicit sub-subject named
    after the subject.
  - Otherwise, one LLM call groups the topic names into 2–8 sub-subjects.
- **Subtopic level:**
  - **Seeded from existing Concepts first.** Each active Concept linked to
    the topic (`Concept.topics`) becomes a subtopic node that **owns that
    Concept**, so `LearnerConceptState` history carries over.
  - Then one LLM call per topic proposes the missing subtopics. Its inputs
    are the topic name, its objectives, the seeded subtopic names and up to
    15 question stems from the topic: question text only, never student
    data. A proposal that duplicates a seeded name (by slug or alias) is
    dropped.
  - Proposed nodes are created `active` with source `llm_proposed`, so
    tagging works at once. Teachers edit or archive them later (2B).
- **Weightage:** stays 0 (unweighted) unless a teacher sets it.
- **Concepts with no topic** stay as they are. They are still valid tagging
  targets through the existing concept path until a teacher places them.

**Decided here (flat concept migration):**
- **Custom courses:** existing Concepts become subtopic nodes, as above.
- **Exam-mapped courses:** existing Concepts are matched to tree subtopics
  by slug or alias. A match merges into the tree subtopic's Concept with
  the existing `merged_into` machinery. Anything unmatched is left alone and
  listed in the command output. (No production course is exam-mapped today.)

## 5. Tagger v2

### 5.1 Pure core, thin shell

`intelligence/services/tagging_v2.py` splits into two layers:

- **`tag_payloads(context, payloads, *, call) -> list[TagResult]`** is pure:
  - inputs: the context, plain dicts and a completion callable;
  - it builds prompts, parses and validates replies, and computes the
    confidence and review reasons;
  - no database access. `evaluate_tagger` runs it on gold items with no
    database writes.
- **`run_tagging_for_tenant`** is the shell: it selects items, builds the
  context from the database, checks the cache, calls the core and writes
  the results.

The context includes the exam or course label, the audience, the subject
tree (keys, labels, definitions), the skill definitions for the subject
(universal plus matching packs), the thinking levels and the special
formats.

### 5.2 Two stages

| Stage | When | Prompt carries | Model returns per question |
|---|---|---|---|
| 1 — locate | Item has no topic (mock items, blind evaluation) | the subject's topic-level nodes (key, label, parent sub-subject) | `topic_key`, `also_topic_keys` (0–2), `confidence` |
| 2 — tag | Always. Grouped by topic, so each prompt carries one topic's subtopics. | the topic's subtopics, plus the subtopics of any `also_topic_keys`; skill, thinking-level and special-format definitions; difficulty rubric "for {audience}" | `primary_subtopic_key`, `secondary_subtopic_keys` (any number), `thinking_level`, `skills: [{key, role, reason}]` (all that apply, no cap), `special_format`, `difficulty`, `est_solve_seconds`, `proposed_subtopic`, `confidence` |

- **Bank questions start at stage 2.** They always have a `topic` (it is
  required). If that topic maps to no node, the shell runs stage 1 for the
  question.
- **Batching:** 12 questions per call in both stages, the same as today.
  The structural type from the item is sent, so the model does not guess it.
- **Special-format hint:** a regex pre-filter flags likely
  `statement_pair` and `match_list` items ("Statement I", "List-I",
  "Assertion (A)") as a hint in the payload. The model decides.
- **Answer key:** the prompt includes the correct answer, since tagging is
  a teacher-side job. It is truncated with the stem (2,000 chars) and
  options (300 chars each).

### 5.3 Validation and confidence

- **Keys are checked against the context.** An unknown subtopic, skill,
  level or format key is dropped and adds `invalid_key`. If the primary
  subtopic is invalid, the item gets no location and `needs_review`.
- **Range checks:**
  - `est_solve_seconds` is clamped to 10–1,800.
  - `difficulty` outside the three values becomes null.
  - Skills beyond the context are dropped.
  - `role` defaults to `supporting`.
- **Confidence** is the model's stated confidence, multiplied by 0.8 when
  stage 1 named a topic other than the one stage 2's primary subtopic sits
  under (`stage_disagreement`).
- **Review rule:** `needs_review` when confidence is below the threshold,
  when any review reason is present, or when there is a
  `proposed_subtopic`.

**Decided here (review threshold):** the threshold lives in `tags.yaml`
(`review_confidence_threshold`, default 0.6). After the first evaluation it
is reset from the calibration table (§6.3): it becomes the lowest
confidence bucket whose subtopic accuracy is at least 80%.

### 5.4 Cache, versions, budget

- **Cache key:** `AITaggingResult` gains `stage`, `taxonomy_version` and
  `tree_version`. Its unique key becomes (tenant, content_hash,
  prompt_version, taxonomy_version, tree_version, stage, model_ref).
- **Prompt version:** `TAGGER_PROMPT_VERSION` becomes `'2'`.
- **Which items the sweep picks:** items with no `ItemTagging`, or with
  `tagging_status = 'stale'`, or whose `ItemTagging` versions are older
  than current. Manual items are excluded.
- **Budget:** the existing `_check_budget` monthly gate and `AIUsageRecord`
  metering (feature `item_tagging`) are unchanged.
- **Old tagger:** v1 stays importable until 2B, for the generators'
  `set_item_tags` path, but the nightly sweep calls v2 only.

## 6. Evaluation

### 6.1 Gold files (JSONL, one item per line)

```json
{"id": "…", "subject": "physics", "question": "…", "options": ["…"], "type": "mcq",
 "answer": "…", "topic_hint": "laws_of_motion",
 "gold": {"topic": "…", "subtopic": "…", "thinking_level": "…",
          "skills": ["…"], "core_skills": ["…"], "difficulty": "…", "special_format": "…"}}
```

Every `gold` field is optional, and an item is scored only on the fields it
has. A gold file is plain data. It is never committed when it holds licensed
or production text.

**Decided here (gold sets: who and how many):**

- **Track A, location:** `make_gold --eval-jee <jsonl> --n 300 --seed 7`.
  - A deterministic, stratified sample: 100 per subject, spread across
    chapters.
  - Drawn from 2021–2024, text-only, in-syllabus questions.
  - Gold `topic` and `subtopic` come straight from the dataset's
    human-assigned chapter and topic, so no hand labelling is needed.
- **Track A, the other levels:** a 60-question subset (20 per subject) with
  thinking level, skills, difficulty and special format.
  - I (Claude) draft these labels by reading each question, without running
    the tagger. You, or a teacher you name, then spot-check them.
  - This is a different model family from `gpt-6-luna`, and the human check
    is the guard on it.
- **Track B:** 120 questions from the four largest real courses (DSA sheet,
  aptitude, Pygame, Class XI PCM).
  - Labelling is done locally from the production copy, in the same way.
  - Location gold is the course Topic the question already sits in, plus the
    subtopic I draft.
  - The file stays in `data_dumps/` because it contains production text.

### 6.2 `manage.py evaluate_tagger`

Usage: `evaluate_tagger --gold <file> --models <ref,…> --mode blind|anchored
[--limit N] [--out report.json]`.

- **Modes:**
  - **anchored:** sends `topic_hint` and starts at stage 2, which is the
    path bank questions take in production.
  - **blind:** withholds the hint and runs both stages, the mock-item path.
- **Model references** are platform models by `model_name`. Today that is
  `gpt-6-luna`.
- **Tree context:** the tagging context comes from the tree YAML directly
  (exam track) or from a course's `SyllabusNode` rows (`--course <id>`).
- **Database:** no database writes, apart from `AIUsageRecord` metering.

### 6.3 Metrics (per model and mode)

| Level | Metric |
|---|---|
| Topic (blind only) | accuracy |
| Subtopic | primary exact accuracy; "hit" accuracy (gold subtopic is primary or secondary) |
| Thinking level | accuracy; confusion matrix |
| Skills | micro precision, recall and F1 over all skills; separately over gold core skills |
| Difficulty | accuracy; ± one-step agreement |
| Special format | precision and recall per format |
| Calibration | subtopic accuracy per confidence bucket (0.1 wide); sets the review threshold |
| Health | invalid-key rate, parse-failure rate, `needs_review` rate |
| Cost | tokens per question, latency p50 and p95, and cost per 1,000 questions from `PlatformAIModel` prices (reads $0 until prices are filled in) |

The report is printed as a markdown table and written as JSON. Runs are
reproducible: fixed seed and order, with the model temperature at the
deployment default (`gpt-6-luna` accepts only that).

**Targets (Track A, anchored):** subtopic hit ≥ 85%, thinking level ≥ 70%,
skills micro-F1 ≥ 0.6, and parse failures under 1%. These are first-pass
bars, revisited after the first run. Because the model may have memorised
these papers, Track B results are read alongside.

## 7. JEE lab tenant (Track A data in the app)

`manage.py import_eval_jee --file <jsonl> --tenant lab-jee [--limit N]` is a
**dev-only** command.

- **Refusals:** it refuses unless all three hold:
  - `DEBUG` is true;
  - the tenant slug starts with `lab-`;
  - the default database is local: SQLite, or `HOST` is one of `localhost`,
    `127.0.0.1` or `::1`.
- **What it creates:**
  - a tenant "JEE Lab" and a course "JEE Main (Lab)" (`code=lab-jee-main`,
    `course_type='competitive'`);
  - Physics, Chemistry and Maths subjects;
  - Topics for the in-syllabus tree topics;
  - `CourseSyllabus` mapped to `jee_main`.
- **Questions:** one bank `Question` per pooled item.
  - Type mapping: `mcq` → `mcq`, `mcqm` → `mcq_multi`, `integer` →
    `numerical`.
  - Options, correct answer, explanation (HTML kept) and the chapter's
    Topic are copied.
  - Difficulty stays at the model default, `medium`.
  - `tags=['eval_jee', <paper_id>]`.
- **What is not stored:** the dataset's subtopic label is never put in the
  database, so the tagger cannot see it. The gold lives only in the gold file.
- **Idempotent:** keyed by `question_id` in `tags`.
- **Licence rules (from D10):** the data file is never committed, and the
  lab tenant is never created outside a local database. The command and a
  small hand-written fixture (6 made-up questions in the dataset's shape)
  are committed for tests.

## 8. Plan 2B — tag-powered analytics

This section sets direction only. It is fixed in detail when plan 2B is
written.

- **Roll-ups:** subtopic mastery is aggregated up to topic, sub-subject and
  subject, weighted by evidence × weightage and computed on read (an API and
  service, no stored rows). This feeds the weak/strong topic split (idea 20).
- **Skill and thinking-level states:** a new `LearnerFacetState` (student,
  subject, kind, key) is recomputed from `LearningEvent` with the same decay
  and diagnosis weights as `state.py`. Core skills count 1.0, supporting
  skills 0.5. New version constant: `FACET_MODEL_VERSION`.
- **Review queue (teacher-facing):**
  - The tenant-admin page lists `needs_review` items with their reasons.
  - Accept, edit or reject. An edit sets `source='manual'` and becomes
    gold data.
  - Proposed subtopics can be accepted into the tree.
- **Tree editor for custom courses:** rename, merge, archive and add
  subtopics, and set weightage.
- **Generators:** mockgen, coursegen and practice generation emit the full
  v2 set through the same validation as §5.3. `set_item_tags` v1 is retired.
- **Synthetic students:**
  - `manage.py simulate_learners --tenant lab-jee --students 200 --seed 7`.
    Each student has a planted ability per subtopic (a 1PL model, with item
    difficulty from `difficulty_prior`), a few planted weak and strong
    subtopics, and a behaviour profile: guess rate, slip rate, speed factor
    and tendency to run out of time.
  - It writes real quiz attempts, answers, raw timelines in the `/timeline/`
    event format, and some self-reports. Then it runs the real pipeline:
    events, `diagnose_attempt`, state and recommendations.
  - Scored against the planted truth:
    - diagnosis label confusion (scripted guess, slip and time pressure
      against the classifier labels);
    - Spearman correlation of mastery with true ability;
    - recall of the planted weak and strong subtopics;
    - recommendation hit rate on planted weak subtopics.
- **Diagnosis follow-up (D9.3):** `usual_seconds` prefers
  `ItemTagging.est_solve_seconds` over `DEFAULT_USUAL_S` while `ItemStats`
  has too little timing data.

## 9. Data handling rules

- **Production copy:**
  - Only question text, options and answer keys may be sent to the Azure
    UAT deployment.
  - No student data, names, emails or answers leave the machine.
  - Reports on it print aggregates only.
- **The `eval_jee` dataset:**
  - local only: `data_dumps/jee_eval/`, excluded from git;
  - never committed, never loaded into production or UAT;
  - the importer guards against that (§7).
- **Production AI keys:** never used. They stay blanked in `dt_prod_work`.
  The experiment model is the "Azure OpenAI (UAT)" platform provider.

## 10. Testing

- **Unit tests (pure):**
  - prompt building and reply parsing;
  - key validation;
  - the confidence and review rule;
  - the compatibility projection to `cognitive_type`;
  - evaluation metrics (hand-computed expectations);
  - YAML validation, both failing and passing cases.
- **Database tests:**
  - `sync_taxonomy` upsert, archive and no-delete;
  - `map_course_to_exam` topic linking;
  - `build_course_tree` seeding from existing Concepts and dropping
    duplicate proposals;
  - the tagger shell: cache hits, manual lock, writes to `ItemTagging`,
    `ItemSkillTag`, `ConceptLink` and `item.topic`, and stale re-tagging;
  - the importer on the made-up fixture, including its refusal guards.
- **LLM calls** are faked in tests by patching the completion callable, as
  `test_tagging.py` does today.
- **`sync_taxonomy --check`** runs on the shipped `tags.yaml` and
  `exams/jee_main.yaml` as a test.
- **Live runs, manual, recorded in the plan's final task:**
  - `evaluate_tagger` on the Track A gold, both modes;
  - the Track B gold against `dt_prod_work`;
  - the report saved under `data_dumps/`, with the summary numbers copied
    into the wiki.

## 11. Out of scope

- JEE Advanced and NEET trees. They use the same YAML shape and are added
  later. JEEBench is the candidate source for JEE Advanced formats.
- Questions with images. The 1,602 `eval_jee` items with images are
  excluded until there is image or OCR support.
- Tagging content types other than assessment items (videos, notes).
- An admin UI for editing `tags.yaml`. YAML plus `sync_taxonomy` is the
  editing path for now (D4).
