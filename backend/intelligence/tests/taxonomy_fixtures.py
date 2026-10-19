"""Small vocabulary + exam tree shared by the tagging v2 tests."""
import copy

MINI_TAGS = {
    'version': 1,
    'review_confidence_threshold': 0.6,
    'thinking_levels': [
        {'key': 'recall', 'label': 'Recall', 'definition': 'Remember a fact or formula.'},
        {'key': 'conceptual', 'label': 'Conceptual', 'definition': 'Explain or predict qualitatively.'},
        {'key': 'single_application', 'label': 'Single application', 'definition': 'Apply one concept.'},
        {'key': 'multi_concept', 'label': 'Multi-concept', 'definition': 'Combine two or more subtopics.'},
        {'key': 'analytical', 'label': 'Analytical', 'definition': 'Needs insight or a built approach.'},
    ],
    'special_formats': [
        {'key': 'statement_pair', 'label': 'Two statements', 'definition': 'Judge Statement I and II.'},
    ],
    'skills': {
        'universal': [
            {'key': 'formula_application', 'label': 'Formula application', 'definition': 'Use a formula.'},
        ],
        'packs': [
            {'key': 'physics', 'label': 'Physics', 'applies_to': ['physics'],
             'skills': [{'key': 'free_body_diagram', 'label': 'Free-body diagram',
                         'definition': 'Draw and resolve the forces.'}]},
        ],
    },
}

MINI_TREE = {
    'key': 'mini',
    'label': 'Mini Exam',
    'audience': 'Mini Exam aspirants',
    'version': 1,
    'subjects': [{
        'key': 'physics', 'label': 'Physics', 'aliases': ['phy'], 'weightage': 1.0,
        'children': [{
            'key': 'mechanics', 'label': 'Mechanics', 'weightage': 1.0,
            'children': [
                {'key': 'laws_of_motion', 'label': 'Laws of Motion', 'weightage': 0.6,
                 'aliases': ['laws-of-motion'],
                 'children': [
                     {'key': 'friction', 'label': 'Friction', 'weightage': 0.5},
                     {'key': 'newtons_laws', 'label': "Newton's Laws", 'weightage': 0.5},
                 ]},
                {'key': 'gravitation', 'label': 'Gravitation', 'weightage': 0.4, 'in_syllabus': False,
                 'children': [{'key': 'orbits', 'label': 'Orbits'}]},
            ],
        }],
    }],
}


def mini_tags():
    return copy.deepcopy(MINI_TAGS)


def mini_tree():
    return copy.deepcopy(MINI_TREE)


def sync_mini_vocabulary():
    """Load MINI_TAGS into the database; returns the TaxonomyRelease."""
    from intelligence.services import taxonomy

    return taxonomy.sync_vocabulary(taxonomy.validate_tags(mini_tags()), 'mini-sha')['release']
