"""Course-built syllabus trees: grouping, concept seeding, proposals, packs."""
import json
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from core.models import Tenant
from coursegen.generation import GenerationError
from exams.models import Course, Subject, Topic
from intelligence.models import Concept, CourseSyllabus, SkillPack, SyllabusNode
from intelligence.services import course_tree
from intelligence.services.course_tree import GROUP_MARKER, PACK_MARKER, SUBTOPIC_MARKER
from quiz.models import Question


class FakeCall:
    model_ref = 'fake:builder'

    def __init__(self, groups=None, subtopics=None, packs=None, fail=()):
        self.groups, self.subtopics, self.packs = groups, subtopics or {}, packs
        self.fail = set(fail)
        self.calls = []

    def __call__(self, system, user):
        if GROUP_MARKER in system:
            kind = 'group'
        elif SUBTOPIC_MARKER in system:
            kind = 'subtopic'
        else:
            kind = 'pack'
        self.calls.append((kind, user))
        if kind in self.fail:
            raise GenerationError('down')
        if kind == 'group':
            return json.dumps({'groups': self.groups or []})
        if kind == 'pack':
            return json.dumps({'subjects': self.packs or []})
        topic = json.loads(user)['topic']
        return json.dumps({'subtopics': [{'name': n, 'description': ''} for n in self.subtopics.get(topic, [])]})


class CourseTreeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create(name='Skill Academy', is_active=True)
        cls.course = Course.objects.create(
            tenant=cls.tenant, name='DSA Sheet', code='tree-dsa', course_type='skill',
        )
        cls.subject = Subject.objects.create(
            tenant=cls.tenant, course=cls.course, name='Arrays & Hashing', code='arrays',
        )
        cls.two_sum = Topic.objects.create(
            tenant=cls.tenant, subject=cls.subject, name='Two Sum Patterns', code='two-sum', order=0,
        )
        cls.prefix = Topic.objects.create(
            tenant=cls.tenant, subject=cls.subject, name='Prefix Sums', code='prefix-sums', order=1,
        )
        cls.hash_concept = Concept.objects.create(
            tenant=cls.tenant, subject=cls.subject, name='Hash map lookup', slug='hash-map-lookup',
        )
        cls.hash_concept.topics.add(cls.two_sum, cls.prefix)
        cls.orphan = Concept.objects.create(
            tenant=cls.tenant, subject=cls.subject, name='Sliding window', slug='sliding-window',
        )
        Question.objects.create(tenant=cls.tenant, subject=cls.subject, topic=cls.two_sum,
                                question_type='mcq', question_text='Find two numbers that sum to k…',
                                correct_answer='0')
        SkillPack.objects.create(key='programming', label='Programming', applies_to=['python'])
        SkillPack.objects.create(key='aptitude', label='Aptitude', applies_to=['aptitude'])

    def test_small_subject_gets_an_implicit_group_seeds_and_proposals(self):
        call = FakeCall(
            subtopics={'Two Sum Patterns': ['Hash map lookup', 'Sorted two pointers', 'sorted two-pointer'],
                       'Prefix Sums': ['Sliding window', 'Range sum queries']},
            packs=[{'id': str(self.subject.id), 'packs': ['programming', 'astrology']}],
        )
        summary = course_tree.build_course_tree(self.course, call=call)
        self.assertEqual([kind for kind, _ in call.calls].count('group'), 0)  # ≤ 6 topics
        group = SyllabusNode.objects.get(subject=self.subject, level='sub_subject')
        self.assertEqual((group.key, group.name), ('course.arrays.all', 'Arrays & Hashing'))
        two_sum = SyllabusNode.objects.get(subject=self.subject, level='topic', course_topic=self.two_sum)
        self.assertEqual(two_sum.key, 'course.arrays.two_sum')
        self.assertEqual(two_sum.parent, group)
        # The concept linked to both topics is seeded once, under the first topic.
        seeded = SyllabusNode.objects.get(concept=self.hash_concept)
        self.assertEqual((seeded.parent, seeded.source), (two_sum, 'course'))
        names = sorted(SyllabusNode.objects.filter(parent=two_sum).values_list('name', flat=True))
        self.assertEqual(names, ['Hash map lookup', 'Sorted two pointers'])  # duplicate dropped
        # The unowned "Sliding window" concept is adopted, not duplicated.
        sliding = SyllabusNode.objects.get(name='Sliding window')
        self.assertEqual(sliding.concept, self.orphan)
        self.assertEqual(Concept.objects.filter(subject=self.subject, slug='sliding-window').count(), 1)
        self.assertEqual(SyllabusNode.objects.get(name='Range sum queries').source, 'llm_proposed')
        self.assertEqual(summary['seeded_subtopics'], 1)
        self.assertEqual(summary['proposed_subtopics'], 3)
        self.assertEqual(summary['packs'], {'Arrays & Hashing': ['programming']})  # unknown pack dropped
        record = CourseSyllabus.objects.get(course=self.course)
        self.assertEqual(record.skill_packs, {str(self.subject.id): ['programming']})
        self.assertEqual(record.exam_tree, '')
        # The proposal prompt saw real question stems (text only).
        subtopic_users = [json.loads(user) for kind, user in call.calls if kind == 'subtopic']
        self.assertIn('Find two numbers that sum to k…', subtopic_users[0]['sample_questions'])

    def test_rerun_is_idempotent(self):
        call = FakeCall(subtopics={'Two Sum Patterns': ['Sorted two pointers'],
                                   'Prefix Sums': ['Range sum queries']})
        course_tree.build_course_tree(self.course, call=call, packs=['programming'])
        count = SyllabusNode.objects.filter(subject=self.subject).count()
        again = FakeCall(subtopics={'Two Sum Patterns': ['Brand new idea']})
        summary = course_tree.build_course_tree(self.course, call=again, packs=['programming'])
        self.assertEqual(SyllabusNode.objects.filter(subject=self.subject).count(), count)
        self.assertEqual([kind for kind, _ in again.calls], [])  # every topic already has subtopics
        self.assertEqual(summary['topics_created'], 0)

    def test_large_subject_is_grouped_and_failures_degrade(self):
        for index in range(5):
            Topic.objects.create(tenant=self.tenant, subject=self.subject, name=f'Topic {index}',
                                 code=f't{index}', order=10 + index)
        topics = Topic.objects.filter(subject=self.subject)
        call = FakeCall(groups=[
            {'name': 'Hashing', 'topic_ids': [str(self.two_sum.id), str(self.prefix.id)]},
            {'name': 'Misc', 'topic_ids': [str(t.id) for t in topics if t.code.startswith('t')][:3]},
        ], fail={'subtopic', 'pack'})
        course_tree.build_course_tree(self.course, call=call)
        groups = dict(SyllabusNode.objects.filter(subject=self.subject, level='sub_subject')
                      .values_list('name', 'key'))
        self.assertEqual(set(groups), {'Hashing', 'Misc', 'Other'})  # 2 topics left out → Other
        self.assertEqual(groups['Hashing'], 'course.arrays.group.hashing')
        prefix = SyllabusNode.objects.get(course_topic=self.prefix)
        self.assertEqual(prefix.parent.name, 'Hashing')
        record = CourseSyllabus.objects.get(course=self.course)
        self.assertEqual(record.skill_packs, {})  # pack call failed → name matching applies

    def test_dry_run_writes_nothing(self):
        summary = course_tree.build_course_tree(self.course, call=FakeCall(), dry_run=True)
        self.assertTrue(summary['dry_run'])
        self.assertGreater(summary['topics_created'], 0)
        self.assertFalse(SyllabusNode.objects.exists())
        self.assertFalse(CourseSyllabus.objects.exists())

    def test_command_with_explicit_packs(self):
        out = StringIO()
        with patch('intelligence.management.commands.build_course_tree.platform_call',
                   return_value=FakeCall()):
            call_command('build_course_tree', '--course', str(self.course.id), '--model', 'gpt-6-luna',
                         '--packs', 'programming', stdout=out)
        self.assertIn('topics created: 2', out.getvalue())
        self.assertEqual(CourseSyllabus.objects.get(course=self.course).skill_packs,
                         {str(self.subject.id): ['programming']})
