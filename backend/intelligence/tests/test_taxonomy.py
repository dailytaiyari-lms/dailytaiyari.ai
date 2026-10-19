"""Taxonomy YAML: validation, flattening, vocabulary sync, the sync command."""
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase

from core.models import Tenant
from exams.models import Course, Subject, Topic
from intelligence.models import SkillPack, TagDefinition, TaxonomyRelease
from intelligence.services import taxonomy
from intelligence.services.taxonomy import TaxonomyError
from intelligence.tests.taxonomy_fixtures import mini_tags, mini_tree
from quiz.models import Question


def _entry(entries, key):
    return next(entry for entry in entries if entry['key'] == key)


class ValidateTagsTests(SimpleTestCase):
    def test_valid_vocabulary_is_normalized(self):
        tags = taxonomy.validate_tags(mini_tags())
        self.assertEqual(tags['version'], '1')
        self.assertEqual(tags['review_confidence_threshold'], 0.6)
        self.assertEqual(tags['thinking_levels'][0]['key'], 'recall')
        self.assertEqual(tags['packs'][0]['applies_to'], ['physics'])
        self.assertTrue(tags['packs'][0]['skills'][0]['active'])

    def test_every_problem_is_reported_at_once(self):
        data = mini_tags()
        data['review_confidence_threshold'] = 1.5
        _entry(data['thinking_levels'], 'single_application')['definition'] = ''
        data['skills']['packs'][0]['skills'].append(
            {'key': 'formula_application', 'label': 'Dup', 'definition': 'x'})
        data['skills']['packs'][0]['applies_to'] = []
        with self.assertRaises(TaxonomyError) as ctx:
            taxonomy.validate_tags(data)
        joined = ' | '.join(ctx.exception.errors)
        self.assertIn('review_confidence_threshold', joined)
        self.assertIn('thinking_levels.single_application: definition is required', joined)
        self.assertIn('skills.packs.physics.skills.formula_application: duplicate key', joined)
        self.assertIn('applies_to must list at least one subject name', joined)

    def test_bad_key_is_rejected(self):
        data = mini_tags()
        data['special_formats'][0]['key'] = 'Statement Pair'
        with self.assertRaises(TaxonomyError):
            taxonomy.validate_tags(data)


class ExamTreeTests(SimpleTestCase):
    def test_valid_tree_flattens_with_full_keys(self):
        flat = taxonomy.flatten_tree(taxonomy.validate_exam_tree(mini_tree()))
        self.assertEqual(flat[0]['key'], 'mini.physics')
        self.assertEqual(flat[0]['level'], 'subject')
        friction = next(node for node in flat if node['local_key'] == 'friction')
        self.assertEqual(friction['key'], 'mini.physics.mechanics.laws_of_motion.friction')
        self.assertEqual(friction['level'], 'subtopic')
        self.assertEqual(friction['parent_key'], 'mini.physics.mechanics.laws_of_motion')
        self.assertEqual(friction['subject'], 'physics')
        orbits = next(node for node in flat if node['local_key'] == 'orbits')
        self.assertFalse(orbits['in_syllabus'])  # inherited from its out-of-syllabus topic

    def test_sibling_weights_must_sum_to_one(self):
        data = mini_tree()
        data['subjects'][0]['children'][0]['children'][0]['weightage'] = 0.9
        with self.assertRaises(TaxonomyError) as ctx:
            taxonomy.validate_exam_tree(data)
        self.assertIn('weightages sum to 1.300', ' '.join(ctx.exception.errors))

    def test_depth_is_enforced(self):
        data = mini_tree()
        laws = data['subjects'][0]['children'][0]['children'][0]
        laws['children'][0]['children'] = [{'key': 'too_deep', 'label': 'Too deep'}]
        with self.assertRaises(TaxonomyError) as ctx:
            taxonomy.validate_exam_tree(data)
        self.assertIn('subtopics cannot have children', ' '.join(ctx.exception.errors))

        data = mini_tree()
        data['subjects'][0]['children'][0]['children'][1]['children'] = []
        with self.assertRaises(TaxonomyError) as ctx:
            taxonomy.validate_exam_tree(data)
        self.assertIn('needs a non-empty list of subtopic nodes', ' '.join(ctx.exception.errors))


class SyncVocabularyTests(TestCase):
    def test_upsert_deactivate_and_release(self):
        tags = taxonomy.validate_tags(mini_tags())
        summary = taxonomy.sync_vocabulary(tags, 'sha-1')
        self.assertEqual(summary['release'].sequence, 1)
        self.assertEqual(TagDefinition.objects.filter(kind='skill', active=True).count(), 2)
        self.assertEqual(TagDefinition.objects.get(key='free_body_diagram').pack.key, 'physics')

        # The same file again: nothing new to release.
        self.assertIsNone(taxonomy.sync_vocabulary(tags, 'sha-1')['release'])

        # A key removed from the file is deactivated, never deleted.
        data = mini_tags()
        data['skills']['packs'] = []
        summary = taxonomy.sync_vocabulary(taxonomy.validate_tags(data), 'sha-2')
        self.assertEqual(summary['deactivated'], 1)
        self.assertFalse(TagDefinition.objects.get(key='free_body_diagram').active)
        self.assertFalse(SkillPack.objects.get(key='physics').active)
        self.assertEqual(summary['release'].sequence, 2)
        self.assertEqual(taxonomy.current_release().file_sha256, 'sha-2')


class SyncCommandTests(TestCase):
    def test_check_validates_shipped_files_and_writes_nothing(self):
        out = StringIO()
        call_command('sync_taxonomy', '--check', stdout=out)
        self.assertIn('tags.yaml v', out.getvalue())
        self.assertFalse(TagDefinition.objects.exists())

    def test_sync_loads_the_shipped_vocabulary(self):
        call_command('sync_taxonomy', stdout=StringIO())
        self.assertTrue(TagDefinition.objects.filter(kind='thinking_level', key='analytical').exists())
        self.assertTrue(TagDefinition.objects.filter(
            kind='skill', key='code_tracing', pack__key='programming').exists())
        self.assertTrue(TagDefinition.objects.filter(
            kind='skill', key='pattern_recognition', pack__isnull=True).exists())
        self.assertEqual(TaxonomyRelease.objects.count(), 1)

    def test_retag_subjects_marks_tagged_items_stale(self):
        tenant = Tenant.objects.create(name='Retag Academy', is_active=True)
        course = Course.objects.create(tenant=tenant, name='C', code='retag-c', course_type='skill')
        subject = Subject.objects.create(tenant=tenant, course=course, name='Python', code='python')
        topic = Topic.objects.create(tenant=tenant, subject=subject, name='Loops', code='loops')
        question = Question.objects.create(
            tenant=tenant, subject=subject, topic=topic, question_text='What prints?',
            question_type='mcq', correct_answer='0', tagging_status='tagged',
        )
        call_command('sync_taxonomy', '--retag-subjects', str(subject.id), stdout=StringIO())
        question.refresh_from_db()
        self.assertEqual(question.tagging_status, 'stale')

    def test_bad_subject_id_is_a_command_error(self):
        with self.assertRaises(CommandError):
            call_command('sync_taxonomy', '--retag-subjects', 'not-a-uuid', stdout=StringIO())
