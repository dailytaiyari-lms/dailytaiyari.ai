"""Helpers for the local-only ``eval_jee`` JEE Main question bank (D10, Track A).

The dataset (Hugging Face ``kartikjain42/eval_jee``: 10,809 JEE Main/AIEEE
previous-year questions with human chapter/topic labels) has no licence. It is
read from ``data_dumps/jee_eval/`` only — never committed, never loaded
outside a local lab tenant. Nothing in this module touches the database.
"""
import html
import json
import random
import re
from collections import Counter, defaultdict

POOL_MIN_YEAR = 2021
TYPE_MAP = {'mcq': 'mcq', 'mcqm': 'mcq_multi', 'integer': 'numerical'}
IMAGE_RE = re.compile(r'<img|!\[|\.(png|jpe?g|gif|svg|webp)\b', re.I)
TAG_RE = re.compile(r'<[^>]+>')
SMALL_WORDS = {'a', 'an', 'and', 'as', 'at', 'by', 'for', 'in', 'of', 'on', 'or', 'the', 'to', 'with'}
ACRONYMS = {
    'ac', 'dc', 'emf', 'lcr', 'lc', 'lr', 'rc', 'shm', 'em', 'ph', 'vsepr', 'iupac', 'dna', 'rna',
    'gcd', 'lcm', 'ap', 'gp', 'hp', 'am', 'gm', 'hm', 'vbt', 'cft', 'sn1', 'sn2', 'rms',
}

SUBJECT_LABELS = {'physics': 'Physics', 'chemistry': 'Chemistry', 'maths': 'Mathematics'}
SUBJECT_ALIASES = {'physics': ['phy'], 'chemistry': ['chem'], 'maths': ['mathematics', 'math']}
# Dataset slug → corrected slug, for chapters and topics. Tree keys are
# permanent cross-tenant identifiers, so misspellings and truncations in the
# dataset's labels are fixed here; the original slug stays in the node's
# ``aliases``, so ``tree_key_index`` (and the gold files) still map dataset rows.
SLUG_FIXES = {
    # chapters
    'trigonometric-ratio-and-identites': 'trigonometric-ratios-and-identities',
    # topics
    'mediun-and-angle-bisector': 'median-and-angle-bisector',
    'interestitial-voids': 'interstitial-voids',
    'existance-of-limits': 'existence-of-limits',
    'limits-of-algebric-function': 'limits-of-algebraic-function',
    'newton-lebnitz-rule-of-differentiation': 'newton-leibnitz-rule-of-differentiation',
    "real-gas-and-van-der-wall's-equation": 'real-gas-and-van-der-waals-equation',
    'van-der-walls-forces': 'van-der-waals-forces',
    "pressure,-density,-pascal's-law-and-archimede's-principle":
        "pressure,-density,-pascal's-law-and-archimedes'-principle",
    'classical-defininition-of-probability': 'classical-definition-of-probability',
    'stress-strain-curve,-thermal-stress-and-elastic-pe':
        'stress-strain-curve,-thermal-stress-and-elastic-potential-energy',
    'relative-lowering-of-vapour-pressure-and-roult’s-law':
        'relative-lowering-of-vapour-pressure-and-raoult’s-law',
    "warner's-theory-and-valence-bond-theory": "werner's-theory-and-valence-bond-theory",
    'dearrangement': 'derangement',
    'physiochemical-trends-in-alkali-metals': 'physicochemical-trends-in-alkali-metals',
    'physiochemical-trends-in-alkaline-earth-metals': 'physicochemical-trends-in-alkaline-earth-metals',
}

# Display labels where slug_label() gets it wrong, keyed by the dataset slug.
CHAPTER_LABEL_OVERRIDES = {
    'trigonometric-ratio-and-identites': 'Trigonometric Ratios and Identities',
    'magnetics': 'Magnetic Effects of Current',
    's-block-elements': 's-Block Elements',
    'p-block-elements': 'p-Block Elements',
    'd-and-f-block-elements': 'd- and f-Block Elements',
}
SUBTOPIC_LABEL_OVERRIDES = {
    'refraction,-tir-and-prism': 'Refraction, TIR and Prism',
    'ph,-buffer-and-indicators': 'pH, Buffer and Indicators',
    'relative-lowering-of-vapour-pressure-and-roult’s-law': 'Relative Lowering of Vapour Pressure and Raoult’s Law',
    'crystal-field-theory-(cft)': 'Crystal Field Theory (CFT)',
    'arithmetic-progression-(a.p)': 'Arithmetic Progression (AP)',
    'geometric-progression-(g.p)': 'Geometric Progression (GP)',
    'harmonic-progression-(h.p)': 'Harmonic Progression (HP)',
    "warner's-theory-and-valence-bond-theory": "Werner's Theory and Valence Bond Theory",
    "real-gas-and-van-der-wall's-equation": 'Real Gas and Van der Waals Equation',
    'van-der-walls-forces': 'Van der Waals Forces',
}

# Sub-subject grouping of the dataset's chapters (dataset `chapter` = tree
# topic, dataset `topic` = tree subtopic). Every dataset chapter must appear
# exactly once; draft_jee_main_tree fails on an unassigned chapter.
JEE_MAIN_GROUPS = {
    'physics': [
        ('mechanics', 'Mechanics', [
            'units-and-measurements', 'vector-algebra', 'motion-in-a-straight-line',
            'motion-in-a-plane', 'laws-of-motion', 'circular-motion', 'work-power-and-energy',
            'center-of-mass', 'rotational-motion', 'gravitation', 'properties-of-matter',
        ]),
        ('thermal_physics', 'Thermal Physics', ['heat-and-thermodynamics']),
        ('oscillations_waves', 'Oscillations and Waves', ['simple-harmonic-motion', 'waves']),
        ('electrodynamics', 'Electrodynamics', [
            'electrostatics', 'capacitor', 'current-electricity', 'magnetics',
            'magnetic-properties-of-matter', 'electromagnetic-induction', 'alternating-current',
            'electromagnetic-waves',
        ]),
        ('optics', 'Optics', ['geometrical-optics', 'wave-optics']),
        ('modern_physics', 'Modern Physics', [
            'dual-nature-of-radiation', 'atoms-and-nuclei', 'electronic-devices',
            'communication-systems',
        ]),
    ],
    'chemistry': [
        ('physical_chemistry', 'Physical Chemistry', [
            'some-basic-concepts-of-chemistry', 'structure-of-atom', 'gaseous-state',
            'thermodynamics', 'chemical-equilibrium', 'ionic-equilibrium', 'redox-reactions',
            'solutions', 'electrochemistry', 'chemical-kinetics-and-nuclear-chemistry',
            'solid-state', 'surface-chemistry',
        ]),
        ('inorganic_chemistry', 'Inorganic Chemistry', [
            'periodic-table-and-periodicity', 'chemical-bonding-and-molecular-structure',
            'hydrogen', 's-block-elements', 'p-block-elements', 'd-and-f-block-elements',
            'coordination-compounds', 'isolation-of-elements', 'environmental-chemistry',
        ]),
        ('organic_chemistry', 'Organic Chemistry', [
            'basics-of-organic-chemistry', 'hydrocarbons', 'haloalkanes-and-haloarenes',
            'alcohols-phenols-and-ethers', 'aldehydes-ketones-and-carboxylic-acids',
            'compounds-containing-nitrogen', 'biomolecules', 'polymers',
            'chemistry-in-everyday-life', 'practical-organic-chemistry',
        ]),
    ],
    'maths': [
        ('algebra', 'Algebra', [
            'sets-and-relations', 'complex-numbers', 'quadratic-equation-and-inequalities',
            'sequences-and-series', 'binomial-theorem', 'permutations-and-combinations',
            'matrices-and-determinants', 'mathematical-induction', 'mathematical-reasoning',
            'logarithm',
        ]),
        ('trigonometry', 'Trigonometry', [
            'trigonometric-ratio-and-identites', 'trigonometric-functions-and-equations',
            'inverse-trigonometric-functions', 'properties-of-triangle', 'height-and-distance',
        ]),
        ('coordinate_geometry', 'Coordinate Geometry', [
            'straight-lines-and-pair-of-straight-lines', 'circle', 'parabola', 'ellipse', 'hyperbola',
        ]),
        ('calculus', 'Calculus', [
            'functions', 'limits-continuity-and-differentiability', 'differentiation',
            'application-of-derivatives', 'indefinite-integrals', 'definite-integration',
            'area-under-the-curves', 'differential-equations',
        ]),
        ('vectors_3d', 'Vectors and 3D Geometry', ['vector-algebra', '3d-geometry']),
        ('statistics_probability', 'Statistics and Probability', ['statistics', 'probability']),
    ],
}

# Chapters removed from the NTA JEE Main syllabus (2024 revision). The
# dataset agrees: each has ~0 questions in 2024 papers. Checked by hand
# against the NTA syllabus PDF during the tree review.
JEE_MAIN_OUT_OF_SYLLABUS = frozenset({
    'communication-systems',
    'gaseous-state', 'solid-state', 'surface-chemistry', 'hydrogen', 's-block-elements',
    'isolation-of-elements', 'environmental-chemistry', 'polymers', 'chemistry-in-everyday-life',
    'mathematical-induction', 'mathematical-reasoning', 'height-and-distance',
})

TREE_AUDIENCE = 'JEE Main (Paper 1, B.E./B.Tech) aspirants, Class 11–12 level'


def read_rows(path):
    with open(path, encoding='utf-8') as handle:
        return [json.loads(line) for line in handle if line.strip()]


def node_key(slug):
    """'calculation-of-standard-deviation,-variance' → 'calculation_of_standard_deviation_variance'."""
    return re.sub(r'[^a-z0-9]+', '_', (slug or '').casefold()).strip('_')


def fixed_slug(slug):
    """The dataset slug with SLUG_FIXES applied."""
    return SLUG_FIXES.get(slug, slug)


def chapter_key(slug):
    """Tree key for a dataset chapter slug (after SLUG_FIXES)."""
    return node_key(fixed_slug(slug))


def slug_label(slug):
    """'ac-circuits-and-power-in-ac-circuits' → 'AC Circuits and Power in AC Circuits'."""
    words = (slug or '').replace(',-', ', ').replace('-', ' ').split()
    out = []
    for index, word in enumerate(words):
        bare, comma = (word[:-1], ',') if word.endswith(',') else (word, '')
        if bare in ACRONYMS or re.fullmatch(r'\d+d', bare):
            bare = bare.upper()
        elif index and bare in SMALL_WORDS:
            pass
        else:
            bare = bare[:1].upper() + bare[1:]
        out.append(bare + comma)
    return ' '.join(out)


def paper_year(paper_id):
    match = re.search(r'(20\d\d)', paper_id or '')
    return int(match.group(1)) if match else 0


def has_image(row):
    return bool(IMAGE_RE.search((row.get('question') or '') + (row.get('options') or '')))


def strip_html(text):
    """Tags out, entities decoded, whitespace collapsed; LaTeX is kept."""
    return ' '.join(html.unescape(TAG_RE.sub(' ', text or '')).split())


def parse_options(row):
    try:
        options = json.loads(row.get('options') or '[]')
    except (TypeError, ValueError):
        return []
    if not isinstance(options, list):
        return []
    return [
        {'id': str(option.get('identifier') or ''), 'text': strip_html(str(option.get('content') or ''))}
        for option in options if isinstance(option, dict)
    ]


def correct_ids(row):
    try:
        value = json.loads(row.get('correct_option') or '[]')
    except (TypeError, ValueError):
        return []
    return [str(item) for item in value] if isinstance(value, list) else []


def is_usable(row, out_of_syllabus=frozenset()):
    """Text-only, 2021+, a known type, in syllabus, with an answer."""
    if row.get('question_type') not in TYPE_MAP or row.get('subject') not in SUBJECT_LABELS:
        return False
    if paper_year(row.get('paper_id')) < POOL_MIN_YEAR or has_image(row):
        return False
    if chapter_key(row.get('chapter')) in out_of_syllabus:
        return False
    if row['question_type'] == 'integer':
        return str(row.get('answer') or '').strip() != ''
    ids = {option['id'] for option in parse_options(row)}
    return len(ids) >= 2 and bool(correct_ids(row)) and set(correct_ids(row)) <= ids


def row_to_payload(row):
    """The tagger payload for one dataset row (answer as text)."""
    options = parse_options(row)
    if row.get('question_type') == 'integer':
        answer = str(row.get('answer') or '').strip()
    else:
        wanted = set(correct_ids(row))
        answer = ' | '.join(option['text'] for option in options if option['id'] in wanted)
    return {
        'id': str(row['question_id']),
        'type': TYPE_MAP.get(row.get('question_type'), ''),
        'question': strip_html(row.get('question')),
        'options': [option['text'] for option in options],
        'answer': answer,
    }


def stratified_sample(rows, n, seed):
    """Deterministic sample: equal share per subject, round-robin over chapters."""
    rng = random.Random(seed)
    by_subject = defaultdict(lambda: defaultdict(list))
    for item in sorted(rows, key=lambda r: str(r['question_id'])):
        by_subject[item['subject']][item['chapter']].append(item)
    subjects = sorted(by_subject)
    if not subjects or n <= 0:
        return []
    picked = []
    for position, subject in enumerate(subjects):
        quota = n // len(subjects) + (1 if position < n % len(subjects) else 0)
        chapters = by_subject[subject]
        for bucket in chapters.values():
            rng.shuffle(bucket)
        order = sorted(chapters)
        cursor = {chapter: 0 for chapter in order}
        taken = []
        while len(taken) < quota and any(cursor[c] < len(chapters[c]) for c in order):
            for chapter in order:
                if len(taken) >= quota:
                    break
                if cursor[chapter] < len(chapters[chapter]):
                    taken.append(chapters[chapter][cursor[chapter]])
                    cursor[chapter] += 1
        picked.extend(taken)
    return picked


def _share(part, whole):
    return round(part / whole, 4) if whole else 0.0


def draft_jee_main_tree(rows):
    """Build the jee_main tree (``validate_exam_tree`` input) from dataset rows.

    Weightage is each node's share of 2021+ questions within its parent;
    out-of-syllabus chapters (and their subtopics) weigh 0. Returns
    ``(tree, warnings)``; raises ValueError for chapters missing from
    JEE_MAIN_GROUPS.
    """
    chapters = defaultdict(lambda: defaultdict(set))
    recent = Counter()
    for item in rows:
        subject, chapter, topic = item.get('subject'), item.get('chapter'), item.get('topic')
        if subject not in JEE_MAIN_GROUPS or not chapter or not topic:
            continue
        chapters[subject][chapter].add(topic)
        if paper_year(item.get('paper_id')) >= POOL_MIN_YEAR:
            recent[(subject, chapter, topic)] += 1

    grouped = {s: {c for _, _, slugs in groups for c in slugs} for s, groups in JEE_MAIN_GROUPS.items()}
    missing = sorted(f'{s}/{c}' for s in chapters for c in chapters[s] if c not in grouped[s])
    if missing:
        raise ValueError('chapters missing from JEE_MAIN_GROUPS: ' + ', '.join(missing))
    warnings = sorted(f'{s}/{c}' for s in grouped for c in grouped[s] if c not in chapters.get(s, {}))

    def counted(subject, chapter, topic=None):
        if chapter in JEE_MAIN_OUT_OF_SYLLABUS:
            return 0
        if topic is not None:
            return recent[(subject, chapter, topic)]
        return sum(n for (s, c, _), n in recent.items() if s == subject and c == chapter)

    subjects = []
    for subject, groups in JEE_MAIN_GROUPS.items():
        present_by_group = [(key, label, [c for c in slugs if c in chapters.get(subject, {})])
                            for key, label, slugs in groups]
        subject_total = sum(counted(subject, c) for _, _, present in present_by_group for c in present)
        group_nodes = []
        for group_key, group_label, present in present_by_group:
            if not present:
                continue
            group_total = sum(counted(subject, c) for c in present)
            topic_nodes = []
            for chapter in present:
                chapter_total = counted(subject, chapter)
                children, used = [], set()
                for topic in sorted(chapters[subject][chapter]):
                    base = node_key(fixed_slug(topic))
                    key, suffix = base, 2
                    while key in used:  # two slugs that normalise to one key
                        key, suffix = f'{base}_{suffix}', suffix + 1
                    used.add(key)
                    children.append({
                        'key': key,
                        'label': SUBTOPIC_LABEL_OVERRIDES.get(topic) or slug_label(fixed_slug(topic)),
                        'weightage': _share(counted(subject, chapter, topic), chapter_total),
                        'aliases': [topic],  # the dataset slug, even when the key was fixed
                    })
                topic_nodes.append({
                    'key': chapter_key(chapter),
                    'label': CHAPTER_LABEL_OVERRIDES.get(chapter) or slug_label(fixed_slug(chapter)),
                    'weightage': _share(chapter_total, group_total),
                    'in_syllabus': chapter not in JEE_MAIN_OUT_OF_SYLLABUS,
                    'aliases': [chapter],
                    'children': children,
                })
            group_nodes.append({
                'key': group_key, 'label': group_label,
                'weightage': _share(group_total, subject_total), 'children': topic_nodes,
            })
        if group_nodes:
            subjects.append({
                'key': subject, 'label': SUBJECT_LABELS[subject], 'aliases': SUBJECT_ALIASES[subject],
                'weightage': 0.0, 'children': group_nodes,
            })
    for subject_node in subjects:
        subject_node['weightage'] = _share(1, len(subjects))
    tree = {
        'key': 'jee_main', 'label': 'JEE Main', 'audience': TREE_AUDIENCE, 'version': 1,
        'subjects': subjects,
    }
    return tree, warnings


def tree_key_index(tree):
    """Map dataset slugs to full tree keys, via each node's slug alias.

    ``(subject, chapter_slug) → topic key`` and
    ``(subject, chapter_slug, topic_slug) → subtopic key``.
    """
    index = {}
    for subject in tree['subjects']:
        for group in subject['children']:
            for topic in group['children']:
                topic_key = f'{tree["key"]}.{subject["key"]}.{group["key"]}.{topic["key"]}'
                for chapter_slug in topic['aliases'] or [topic['key']]:
                    index[(subject['key'], chapter_slug)] = topic_key
                    for subtopic in topic['children']:
                        for topic_slug in subtopic['aliases'] or [subtopic['key']]:
                            index[(subject['key'], chapter_slug, topic_slug)] = f'{topic_key}.{subtopic["key"]}'
    return index


def out_of_syllabus_chapters(tree):
    """Local keys of topic-level nodes marked out of syllabus."""
    return frozenset(
        topic['key']
        for subject in tree['subjects'] for group in subject['children'] for topic in group['children']
        if not topic['in_syllabus']
    )
