"""Tree editor operations (spec 2B §5.2)."""
from intelligence.models import (
    ConceptLink, CourseSyllabus, ItemTagging, LearnerConceptState, SyllabusNode,
)
from intelligence.services import syllabus, tree_editor
from intelligence.services.tree_editor import EditError
from intelligence.tests.syllabus_fixtures import SyllabusTestCase


class PayloadTests(SyllabusTestCase):
    def test_tree_payload_nests_and_skips_archived(self):
        payload = tree_editor.tree_payload(self.course)
        self.assertEqual(payload['kind'], 'exam')
        self.assertEqual(payload['exam_tree'], 'mini')
        subject = payload['subjects'][0]
        self.assertTrue(subject['has_tree'])
        mechanics = subject['nodes'][0]
        self.assertEqual(mechanics['level'], 'sub_subject')
        laws = next(n for n in mechanics['children'] if n['key'] == self.laws_node.key)
        self.assertEqual([c['name'] for c in laws['children']], ['Friction', "Newton's Laws"])
        self.assertIn('exam_trees', payload)

    def test_custom_course_without_tree(self):
        payload = tree_editor.tree_payload(self.custom)
        self.assertEqual(payload['kind'], 'none')
        self.assertFalse(payload['subjects'][0]['has_tree'])


class AddAndUpdateTests(SyllabusTestCase):
    def test_add_subtopic_gets_key_and_concept(self):
        node = tree_editor.add_node(self.physics, level='subtopic', name='Static friction',
                                    parent=self.laws_node)
        self.assertEqual(node.key, f'{self.laws_node.key}.static_friction')
        self.assertEqual(node.source, 'manual')
        self.assertIsNotNone(node.concept_id)

    def test_add_topic_is_refused(self):
        with self.assertRaises(EditError):
            tree_editor.add_node(self.physics, level='topic', name='Optics', parent=self.mechanics)

    def test_add_sub_subject_uses_sibling_prefix(self):
        node = tree_editor.add_node(self.physics, level='sub_subject', name='Modern Physics')
        self.assertEqual(node.key, 'mini.physics.modern_physics')

    def test_rename_changes_tree_version_and_concept(self):
        before = syllabus.compute_tree_version(self.physics)
        tree_editor.update_node(self.friction, {'name': 'Kinetic friction'})
        self.friction.refresh_from_db()
        self.assertEqual(self.friction.concept.name, 'Kinetic friction')
        self.assertNotEqual(syllabus.compute_tree_version(self.physics), before)

    def test_topic_rename_is_refused(self):
        with self.assertRaises(EditError):
            tree_editor.update_node(self.laws_node, {'name': 'Newton'})

    def test_move_topic_to_another_sub_subject(self):
        target = tree_editor.add_node(self.physics, level='sub_subject', name='Dynamics')
        tree_editor.update_node(self.laws_node, {'parent': str(target.id)})
        self.laws_node.refresh_from_db()
        self.assertEqual(self.laws_node.parent_id, target.id)
        with self.assertRaises(EditError):
            tree_editor.update_node(self.friction, {'parent': str(target.id)})

    def test_weightage_warning_when_siblings_do_not_sum_to_one(self):
        self.assertEqual(tree_editor.update_node(self.friction, {'weightage': 0.5}), [])
        warnings = tree_editor.update_node(self.friction, {'weightage': 0.7})
        self.assertEqual(len(warnings), 1)
        self.assertIn('1.20', warnings[0])
        with self.assertRaises(EditError):
            tree_editor.update_node(self.friction, {'weightage': 2})

    def test_editing_a_suggestion_accepts_it(self):
        self.friction.status = 'proposed'
        self.friction.save()
        tree_editor.update_node(self.friction, {'name': 'Friction forces'})
        self.friction.refresh_from_db()
        self.assertEqual(self.friction.status, 'active')

    def test_accept_and_archive(self):
        self.friction.status = 'proposed'
        self.friction.save()
        tree_editor.update_node(self.friction, {'status': 'active'})
        tree_editor.update_node(self.friction, {'status': 'archived'})
        self.friction.refresh_from_db()
        self.assertEqual(self.friction.status, 'archived')
        with self.assertRaises(EditError):
            tree_editor.update_node(self.mechanics, {'status': 'archived'})  # has live topics


class MergeTests(SyllabusTestCase):
    def test_merge_moves_links_taggings_and_archives_source(self):
        question = self.question('A block slides…')
        other = self.question('A rope pulls…')
        friction_concept = syllabus.ensure_node_concept(self.friction)
        newton_concept = syllabus.ensure_node_concept(self.newton)
        ConceptLink.objects.create(tenant=self.tenant, concept=friction_concept, question=question,
                                   is_primary=True, source='llm_tagger')
        primary = ItemTagging.objects.create(tenant=self.tenant, question=question,
                                             primary_node=self.friction)
        secondary = ItemTagging.objects.create(tenant=self.tenant, question=other,
                                               primary_node=self.newton)
        secondary.secondary_nodes.add(self.friction)

        summary = tree_editor.merge_nodes(self.friction, self.newton)

        self.assertEqual(summary['primary_moved'], 1)
        self.assertEqual(summary['secondary_moved'], 1)
        self.friction.refresh_from_db()
        self.assertEqual(self.friction.status, 'archived')
        primary.refresh_from_db()
        self.assertEqual(primary.primary_node_id, self.newton.id)
        self.assertEqual(list(secondary.secondary_nodes.all()), [])  # target is already primary
        self.assertEqual(ConceptLink.objects.get(question=question).concept_id, newton_concept.id)
        friction_concept.refresh_from_db()
        self.assertEqual(friction_concept.status, 'merged')
        self.assertFalse(LearnerConceptState.objects.filter(concept=friction_concept).exists())

    def test_merge_needs_two_live_subtopics_of_one_subject(self):
        with self.assertRaises(EditError):
            tree_editor.merge_nodes(self.friction, self.friction)
        with self.assertRaises(EditError):
            tree_editor.merge_nodes(self.friction, self.laws_node)


class SkillPackTests(SyllabusTestCase):
    def test_set_skill_packs(self):
        tree_editor.set_skill_packs(self.course, {str(self.physics.id): ['physics', 'nope']})
        self.assertEqual(CourseSyllabus.objects.get(course=self.course).skill_packs,
                         {str(self.physics.id): ['physics']})
        with self.assertRaises(EditError):
            tree_editor.set_skill_packs(self.course, {str(self.arrays.id): ['physics']})
