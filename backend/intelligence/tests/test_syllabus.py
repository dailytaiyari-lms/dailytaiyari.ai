"""Exam-tree instantiation, subtopic Concepts, tree versions, packs, contexts."""
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase

from core.models import Tenant
from exams.models import Course, Subject, Topic
from intelligence.models import Concept, CourseSyllabus, SkillPack, SyllabusNode
from intelligence.services import syllabus, taxonomy
from intelligence.tests.taxonomy_fixtures import mini_tags, mini_tree, sync_mini_vocabulary

FRICTION = 'mini.physics.mechanics.laws_of_motion.friction'
NEWTON = 'mini.physics.mechanics.laws_of_motion.newtons_laws'
LAWS = 'mini.physics.mechanics.laws_of_motion'


def patched_tree(tree=None):
    validated = taxonomy.validate_exam_tree(tree or mini_tree())
    return patch('intelligence.services.syllabus.load_exam_tree', return_value=validated)


class SyllabusTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create(name='Tree Academy', is_active=True)
        cls.course = Course.objects.create(
            tenant=cls.tenant, name='Mini Prep', code='tree-mini', course_type='competitive',
        )
        cls.subject = Subject.objects.create(
            tenant=cls.tenant, course=cls.course, name='Physics', code='physics',
        )
        cls.laws = Topic.objects.create(
            tenant=cls.tenant, subject=cls.subject, name='Laws of Motion', code='laws-of-motion',
        )
        cls.optics = Topic.objects.create(
            tenant=cls.tenant, subject=cls.subject, name='Optics', code='optics',
        )

    def instantiate(self, tree=None):
        with patched_tree(tree):
            return syllabus.instantiate_exam_tree(self.course, 'mini', {'physics': self.subject})

    def test_instantiate_creates_nodes_links_topics_and_concepts(self):
        old = Concept.objects.create(
            tenant=self.tenant, subject=self.subject, name='Friction', slug='friction', source='llm_tagger',
        )
        summary = self.instantiate()
        self.assertEqual(summary['created'], 6)  # 1 sub-subject + 2 topics + 3 subtopics
        laws_node = SyllabusNode.objects.get(subject=self.subject, key=LAWS)
        self.assertEqual(laws_node.course_topic, self.laws)
        self.assertEqual(laws_node.level, 'topic')
        self.assertEqual(summary['unmatched_topics'], ['Physics: Optics'])
        subtopics = SyllabusNode.objects.filter(subject=self.subject, level='subtopic')
        self.assertEqual(subtopics.count(), 3)
        self.assertTrue(all(node.concept and node.concept.source == 'syllabus' for node in subtopics))
        friction = SyllabusNode.objects.get(subject=self.subject, key=FRICTION)
        self.assertIn(self.laws, friction.concept.topics.all())
        old.refresh_from_db()
        self.assertEqual((old.status, old.merged_into_id), ('merged', friction.concept_id))
        self.assertEqual(summary['merged_concepts'], 1)
        record = CourseSyllabus.objects.get(course=self.course)
        self.assertEqual(record.exam_tree, 'mini')
        self.assertEqual(record.audience, 'Mini Exam aspirants')
        self.assertEqual(record.subject_map, {str(self.subject.id): 'physics'})

    def test_rerun_updates_by_key_and_archives_missing_nodes(self):
        self.instantiate()
        friction_concept = SyllabusNode.objects.get(key=FRICTION).concept_id
        changed = mini_tree()
        laws = changed['subjects'][0]['children'][0]['children'][0]
        laws['children'] = [{'key': 'friction', 'label': 'Friction and Drag', 'weightage': 1.0}]
        summary = self.instantiate(changed)
        self.assertEqual(summary['created'], 0)
        self.assertEqual(summary['archived'], 1)
        self.assertEqual(SyllabusNode.objects.get(key=NEWTON).status, 'archived')
        friction = SyllabusNode.objects.get(key=FRICTION)
        self.assertEqual(friction.name, 'Friction and Drag')
        self.assertEqual(friction.concept_id, friction_concept)  # same Concept, renamed
        self.assertEqual(friction.concept.name, 'Friction and Drag')

    def test_tree_version_tracks_content(self):
        self.instantiate()
        before = syllabus.compute_tree_version(self.subject)
        self.assertEqual(len(before), 16)
        self.assertEqual(before, syllabus.compute_tree_version(self.subject))
        SyllabusNode.objects.filter(key=FRICTION).update(name='Kinetic friction')
        self.assertNotEqual(before, syllabus.compute_tree_version(self.subject))

    def test_unknown_tree_subject_is_rejected(self):
        with patched_tree(), self.assertRaises(taxonomy.TaxonomyError):
            syllabus.instantiate_exam_tree(self.course, 'mini', {'biology': self.subject})

    def test_packs_for_subject(self):
        sync_mini_vocabulary()
        SkillPack.objects.create(key='programming', label='Programming', applies_to=['python', 'dsa'])
        SkillPack.objects.create(key='ai_ml', label='AI', applies_to=['ai'])
        self.assertEqual([p.key for p in syllabus.packs_for_subject(self.subject)], ['physics'])
        python = Subject.objects.create(tenant=self.tenant, course=self.course, name='Python Programming', code='py')
        chai = Subject.objects.create(tenant=self.tenant, course=self.course, name='Chai Lessons', code='chai')
        self.assertEqual([p.key for p in syllabus.packs_for_subject(python)], ['programming'])
        self.assertEqual(syllabus.packs_for_subject(chai), [])
        CourseSyllabus.objects.create(tenant=self.tenant, course=self.course,
                                      skill_packs={str(chai.id): ['ai_ml']})
        self.assertEqual([p.key for p in syllabus.packs_for_subject(chai)], ['ai_ml'])

    def test_tagging_context_shape(self):
        sync_mini_vocabulary()
        self.instantiate()
        with patched_tree():
            context = syllabus.tagging_context(self.subject)
        self.assertEqual(context['exam_label'], 'Mini Exam')
        self.assertEqual(context['audience'], 'Mini Exam aspirants')
        self.assertEqual(context['subject'], 'Physics')
        self.assertEqual(context['review_threshold'], 0.6)
        self.assertEqual(context['taxonomy_version'], '1')
        self.assertEqual(context['tree_version'], syllabus.compute_tree_version(self.subject))
        self.assertEqual([t['key'] for t in context['topics']], [LAWS])  # gravitation is out of syllabus
        topic = context['topics'][0]
        self.assertEqual(topic['group'], 'Mechanics')
        self.assertEqual(topic['course_topic_id'], str(self.laws.id))
        self.assertEqual([s['key'] for s in topic['subtopics']], [FRICTION, NEWTON])
        self.assertEqual({s['key'] for s in context['skills']}, {'formula_application', 'free_body_diagram'})
        self.assertEqual(len(context['thinking_levels']), 5)
        self.assertEqual([f['key'] for f in context['special_formats']], ['statement_pair'])

    def test_map_course_to_exam_command(self):
        out = StringIO()
        with patched_tree():
            call_command('map_course_to_exam', '--course', str(self.course.id), '--exam', 'mini',
                         '--subject-map', f'physics={self.subject.id}', stdout=out)
        self.assertIn('created 6', out.getvalue())
        self.assertIn('Physics: Optics', out.getvalue())
        other = Subject.objects.create(
            tenant=self.tenant,
            course=Course.objects.create(tenant=self.tenant, name='X', code='tree-x', course_type='skill'),
            name='Other', code='other',
        )
        with patched_tree(), self.assertRaises(CommandError):
            call_command('map_course_to_exam', '--course', str(self.course.id), '--exam', 'mini',
                         '--subject-map', f'physics={other.id}', stdout=StringIO())
        with self.assertRaises(CommandError):
            call_command('map_course_to_exam', '--course', 'not-a-uuid', '--exam', 'mini',
                         '--subject-map', f'physics={self.subject.id}', stdout=StringIO())


class ContextFromTreeTests(SimpleTestCase):
    def test_yaml_context_matches_the_db_shape(self):
        tags = taxonomy.validate_tags(mini_tags())
        tree = taxonomy.validate_exam_tree(mini_tree())
        context = syllabus.context_from_tree(tree, 'physics', tags)
        self.assertEqual(context['exam_label'], 'Mini Exam')
        self.assertEqual(context['subject'], 'Physics')
        self.assertEqual([t['key'] for t in context['topics']], [LAWS])
        self.assertIsNone(context['topics'][0]['course_topic_id'])
        self.assertEqual({s['key'] for s in context['skills']}, {'formula_application', 'free_body_diagram'})
        self.assertEqual(context['taxonomy_version'], '1')
        self.assertEqual(len(context['tree_version']), 16)
        self.assertEqual(set(context['skills'][0]), {'key', 'label', 'definition', 'pack'})
        with self.assertRaises(taxonomy.TaxonomyError):
            syllabus.context_from_tree(tree, 'biology', tags)
