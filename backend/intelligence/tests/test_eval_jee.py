"""eval_jee helpers and the JEE Main tree draft (pure; no DB, no dataset file)."""
import json

from django.test import SimpleTestCase

from intelligence.services import eval_jee, taxonomy


def row(**overrides):
    base = {
        'question_id': 'q1', 'subject': 'physics', 'chapter': 'laws-of-motion',
        'topic': 'friction-force', 'question': '<p>A block of mass $$m$$ rests…</p>',
        'options': json.dumps([{'identifier': 'A', 'content': '1 N'}, {'identifier': 'B', 'content': '2 N'}]),
        'correct_option': json.dumps(['B']), 'answer': None, 'explanation': '<p>Because…</p>',
        'question_type': 'mcq', 'paper_id': 'jee-main-2023-online-1st-february-morning-shift',
    }
    base.update(overrides)
    return base


class HelperTests(SimpleTestCase):
    def test_keys_and_labels(self):
        self.assertEqual(eval_jee.node_key('calculation-of-standard-deviation,-variance'),
                         'calculation_of_standard_deviation_variance')
        self.assertEqual(eval_jee.node_key('3d-geometry'), '3d_geometry')
        self.assertEqual(eval_jee.slug_label('3d-geometry'), '3D Geometry')
        self.assertEqual(eval_jee.slug_label('ac-circuits-and-power-in-ac-circuits'),
                         'AC Circuits and Power in AC Circuits')
        self.assertEqual(eval_jee.slug_label('calculation-of-mean,-median'), 'Calculation of Mean, Median')

    def test_paper_year_and_html(self):
        self.assertEqual(eval_jee.paper_year('aieee-2005'), 2005)
        self.assertEqual(eval_jee.paper_year('weird'), 0)
        self.assertEqual(eval_jee.strip_html('<p>x &lt; $$y$$</p>\n<p>z</p>'), 'x < $$y$$ z')

    def test_options_and_answers(self):
        self.assertEqual(eval_jee.parse_options(row()), [{'id': 'A', 'text': '1 N'}, {'id': 'B', 'text': '2 N'}])
        self.assertEqual(eval_jee.correct_ids(row()), ['B'])
        self.assertEqual(eval_jee.parse_options(row(options='not json')), [])

    def test_usable_pool_rules(self):
        self.assertTrue(eval_jee.is_usable(row()))
        self.assertFalse(eval_jee.is_usable(row(paper_id='jee-main-2019-online-9th-january')))
        self.assertFalse(eval_jee.is_usable(row(question='<img src="https://x/a.png">')))
        self.assertFalse(eval_jee.is_usable(row(question_type='subjective')))
        self.assertFalse(eval_jee.is_usable(row(question_type='integer', answer='')))
        self.assertTrue(eval_jee.is_usable(row(question_type='integer', answer='4', options='[]',
                                               correct_option='[]')))
        self.assertFalse(eval_jee.is_usable(row(), out_of_syllabus=frozenset({'laws_of_motion'})))

    def test_payload(self):
        payload = eval_jee.row_to_payload(row())
        self.assertEqual(payload, {
            'id': 'q1', 'type': 'mcq', 'question': 'A block of mass $$m$$ rests…',
            'options': ['1 N', '2 N'], 'answer': '2 N',
        })
        integer = eval_jee.row_to_payload(row(question_type='integer', answer='4', options='[]'))
        self.assertEqual((integer['type'], integer['answer']), ('numerical', '4'))


class StratifiedSampleTests(SimpleTestCase):
    def test_sample_is_deterministic_and_spread(self):
        rows = [row(question_id=f'p{i}', chapter=['laws-of-motion', 'gravitation'][i % 2]) for i in range(10)]
        rows += [row(question_id=f'c{i}', subject='chemistry', chapter='hydrocarbons') for i in range(10)]
        first = eval_jee.stratified_sample(rows, 6, seed=7)
        self.assertEqual([r['question_id'] for r in first],
                         [r['question_id'] for r in eval_jee.stratified_sample(rows, 6, seed=7)])
        self.assertEqual(len(first), 6)
        self.assertEqual(sum(1 for r in first if r['subject'] == 'physics'), 3)
        physics_chapters = {r['chapter'] for r in first if r['subject'] == 'physics'}
        self.assertEqual(physics_chapters, {'laws-of-motion', 'gravitation'})


class DraftTreeTests(SimpleTestCase):
    def test_unknown_chapter_is_an_error(self):
        with self.assertRaises(ValueError) as ctx:
            eval_jee.draft_jee_main_tree([row(chapter='brand-new-chapter')])
        self.assertIn('physics/brand-new-chapter', str(ctx.exception))

    def test_draft_validates_and_weighs_recent_questions(self):
        rows = [
            row(question_id='1', topic='friction-force'),
            row(question_id='2', topic='friction-force'),
            row(question_id='3', topic='newtons-laws'),
            row(question_id='4', chapter='gravitation', topic='orbits'),
            row(question_id='5', chapter='communication-systems', topic='modulation'),
            row(question_id='6', topic='old-topic', paper_id='aieee-2004'),
        ]
        tree, warnings = eval_jee.draft_jee_main_tree(rows)
        taxonomy.validate_exam_tree(tree)  # raises if invalid
        self.assertTrue(any(w.startswith('physics/') for w in warnings))
        flat = {node['key']: node for node in taxonomy.flatten_tree(taxonomy.validate_exam_tree(tree))}
        laws = flat['jee_main.physics.mechanics.laws_of_motion']
        self.assertEqual(laws['label'], 'Laws of Motion')
        self.assertAlmostEqual(laws['weightage'], round(3 / 4, 4))  # 3 of 4 recent mechanics rows
        self.assertAlmostEqual(flat['jee_main.physics.mechanics.laws_of_motion.friction_force']['weightage'],
                               round(2 / 3, 4))
        self.assertEqual(flat['jee_main.physics.mechanics.laws_of_motion.old_topic']['weightage'], 0.0)
        comms = flat['jee_main.physics.modern_physics.communication_systems']
        self.assertFalse(comms['in_syllabus'])
        self.assertEqual(comms['weightage'], 0.0)
        index = eval_jee.tree_key_index(taxonomy.validate_exam_tree(tree))
        self.assertEqual(index[('physics', 'laws-of-motion')], 'jee_main.physics.mechanics.laws_of_motion')
        self.assertEqual(index[('physics', 'laws-of-motion', 'newtons-laws')],
                         'jee_main.physics.mechanics.laws_of_motion.newtons_laws')
        self.assertIn('communication_systems', eval_jee.out_of_syllabus_chapters(taxonomy.validate_exam_tree(tree)))


    def test_misspelt_slugs_get_corrected_keys_and_keep_the_dataset_alias(self):
        rows = [
            row(question_id='1', chapter='properties-of-matter',
                topic='stress-strain-curve,-thermal-stress-and-elastic-pe'),
            row(question_id='2', subject='maths', chapter='trigonometric-ratio-and-identites',
                topic='trigonometric-ratio-of-standard-angles'),
            row(question_id='3', subject='maths', chapter='limits-continuity-and-differentiability',
                topic='existance-of-limits'),
        ]
        tree = taxonomy.validate_exam_tree(eval_jee.draft_jee_main_tree(rows)[0])
        flat = {node['key']: node for node in taxonomy.flatten_tree(tree)}
        elastic = ('jee_main.physics.mechanics.properties_of_matter.'
                   'stress_strain_curve_thermal_stress_and_elastic_potential_energy')
        self.assertEqual(flat[elastic]['label'], 'Stress Strain Curve, Thermal Stress and Elastic Potential Energy')
        self.assertEqual(flat[elastic]['aliases'], ['stress-strain-curve,-thermal-stress-and-elastic-pe'])
        trig = 'jee_main.maths.trigonometry.trigonometric_ratios_and_identities'
        self.assertEqual(flat[trig]['label'], 'Trigonometric Ratios and Identities')
        self.assertEqual(flat[trig]['aliases'], ['trigonometric-ratio-and-identites'])
        limits = 'jee_main.maths.calculus.limits_continuity_and_differentiability.existence_of_limits'
        self.assertEqual(flat[limits]['label'], 'Existence of Limits')
        index = eval_jee.tree_key_index(tree)
        self.assertEqual(index[('physics', 'properties-of-matter',
                                'stress-strain-curve,-thermal-stress-and-elastic-pe')], elastic)
        self.assertEqual(index[('maths', 'trigonometric-ratio-and-identites')], trig)
        self.assertEqual(index[('maths', 'limits-continuity-and-differentiability', 'existance-of-limits')],
                         limits)

    def test_fixed_chapter_still_matches_the_out_of_syllabus_set(self):
        excluded = frozenset({'trigonometric_ratios_and_identities'})
        self.assertFalse(eval_jee.is_usable(row(subject='maths', chapter='trigonometric-ratio-and-identites'),
                                            out_of_syllabus=excluded))


class ShippedTreeTests(SimpleTestCase):
    def test_shipped_jee_main_tree(self):
        tree = taxonomy.load_exam_tree('jee_main')
        flat = taxonomy.flatten_tree(tree)
        topics = [node for node in flat if node['level'] == 'topic']
        self.assertEqual([s['key'] for s in tree['subjects']], ['physics', 'chemistry', 'maths'])
        self.assertEqual(len(topics), 91)
        self.assertEqual(sum(1 for node in topics if not node['in_syllabus']), 13)
