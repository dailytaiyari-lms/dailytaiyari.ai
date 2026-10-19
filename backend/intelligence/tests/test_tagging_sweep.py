"""Tagging sweep: payloads, cache, writes, manual lock, v1 fallback."""
import json
import re
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from core.models import Tenant
from coursegen.generation import GenerationError
from exams.models import Course, Subject, Topic
from intelligence.models import AITaggingResult, ConceptLink, ItemSkillTag, ItemTagging, SyllabusNode
from intelligence.services import llm, syllabus, tagging, tagging_sweep, taxonomy
from intelligence.services.tagging_v2 import LOCATE_MARKER
from intelligence.tests.taxonomy_fixtures import mini_tree, sync_mini_vocabulary
from quiz.models import MockTest, MockTestItem, Question, QuestionOption

LAWS = 'mini.physics.mechanics.laws_of_motion'
FRICTION = f'{LAWS}.friction'
NEWTON = f'{LAWS}.newtons_laws'


def patched_tree():
    return patch('intelligence.services.syllabus.load_exam_tree',
                 return_value=taxonomy.validate_exam_tree(mini_tree()))


def tag_entry(**overrides):
    entry = {'primary_subtopic': FRICTION, 'secondary_subtopics': [NEWTON],
             'thinking_level': 'single_application',
             'skills': [{'key': 'free_body_diagram', 'role': 'core', 'reason': 'forces'},
                        {'key': 'formula_application', 'role': 'supporting', 'reason': 'mu N'}],
             'special_format': '', 'difficulty': 'hard', 'est_solve_seconds': 75,
             'proposed_subtopic': '', 'confidence': 0.9}
    entry.update(overrides)
    return entry


class FakeCall:
    model_ref = 'fake:tagger'

    def __init__(self, locate=None, tag=None):
        self.locate, self.tag = locate or {}, tag or {}
        self.calls = []

    def __call__(self, system, user):
        stage = 'locate' if LOCATE_MARKER in system else 'tag'
        self.calls.append(stage)
        ids = re.findall(r'"id": "([^"]+)"', user)
        table = self.locate if stage == 'locate' else self.tag
        return json.dumps({'items': [dict(table[i], id=i) for i in ids if i in table]})


class SweepTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create(name='Sweep Academy', is_active=True)
        cls.course = Course.objects.create(
            tenant=cls.tenant, name='Mini Prep', code='sweep-mini', course_type='competitive',
        )
        cls.subject = Subject.objects.create(
            tenant=cls.tenant, course=cls.course, name='Physics', code='physics',
        )
        cls.laws = Topic.objects.create(
            tenant=cls.tenant, subject=cls.subject, name='Laws of Motion', code='laws-of-motion',
        )
        sync_mini_vocabulary()
        with patched_tree():
            syllabus.instantiate_exam_tree(cls.course, 'mini', {'physics': cls.subject})
        cls.question = Question.objects.create(
            tenant=cls.tenant, subject=cls.subject, topic=cls.laws, question_type='mcq',
            question_text='A 2 kg block on a rough floor (mu = 0.5)…', correct_answer='1',
        )
        for order, (text, correct) in enumerate([('5 N', False), ('10 N', True)]):
            QuestionOption.objects.create(tenant=cls.tenant, question=cls.question, option_text=text,
                                          is_correct=correct, order=order)

    def run_v2(self, call):
        with patched_tree():
            return tagging_sweep.tag_v2_for_tenant(self.tenant, {self.subject.id}, call, limit=50)

    def test_payload_for_bank_question(self):
        payload = tagging_sweep.item_payload(self.question)
        self.assertEqual(payload, {
            'id': str(self.question.id), 'type': 'mcq',
            'question': 'A 2 kg block on a rough floor (mu = 0.5)…',
            'options': ['5 N', '10 N'], 'answer': '10 N',
        })

    def test_bank_question_is_tagged_anchored(self):
        call = FakeCall(tag={str(self.question.id): tag_entry()})
        self.assertEqual(self.run_v2(call), 1)
        self.assertEqual(call.calls, ['tag'])  # topic known → no locate stage
        self.question.refresh_from_db()
        tagging_row = ItemTagging.objects.get(question=self.question)
        self.assertEqual(tagging_row.primary_node.key, FRICTION)
        self.assertEqual([n.key for n in tagging_row.secondary_nodes.all()], [NEWTON])
        self.assertEqual(tagging_row.thinking_level, 'single_application')
        self.assertEqual(tagging_row.difficulty_prior, 'hard')
        self.assertEqual(tagging_row.est_solve_seconds, 75)
        self.assertEqual(tagging_row.review_status, 'auto')
        self.assertEqual(tagging_row.taxonomy_version, '1')
        self.assertEqual(tagging_row.tree_version, syllabus.compute_tree_version(self.subject))
        self.assertEqual(tagging_row.tagger_version, '2:fake:tagger')
        # Bank difficulty is authored and never overwritten.
        self.assertEqual(self.question.difficulty, 'medium')
        self.assertEqual(self.question.cognitive_type, 'application')
        self.assertEqual(self.question.tagging_status, 'tagged')
        links = {link.concept_id: link for link in ConceptLink.objects.filter(question=self.question)}
        friction = SyllabusNode.objects.get(key=FRICTION).concept_id
        newton = SyllabusNode.objects.get(key=NEWTON).concept_id
        self.assertEqual((links[friction].weight, links[friction].is_primary), (1.0, True))
        self.assertEqual(links[newton].weight, 0.5)
        roles = dict(ItemSkillTag.objects.filter(question=self.question).values_list('skill__key', 'role'))
        self.assertEqual(roles, {'free_body_diagram': 'core', 'formula_application': 'supporting'})

    def test_current_items_are_skipped_and_stale_items_hit_the_cache(self):
        self.run_v2(FakeCall(tag={str(self.question.id): tag_entry()}))
        idle = FakeCall()
        self.assertEqual(self.run_v2(idle), 0)
        self.assertEqual(idle.calls, [])
        Question.objects.filter(id=self.question.id).update(tagging_status='stale')
        cached = FakeCall()
        self.assertEqual(self.run_v2(cached), 1)
        self.assertEqual(cached.calls, [])  # same content → cached reply

    def test_malformed_cached_reply_is_replaced_not_raised(self):
        self.run_v2(FakeCall(tag={str(self.question.id): tag_entry()}))
        AITaggingResult.objects.filter(stage='tag').update(result=['not', 'an', 'entry'])
        Question.objects.filter(id=self.question.id).update(tagging_status='stale')
        fresh = FakeCall(tag={str(self.question.id): tag_entry()})
        self.assertEqual(self.run_v2(fresh), 1)
        self.assertEqual(fresh.calls, ['tag'])
        self.assertIsInstance(AITaggingResult.objects.get(stage='tag').result, dict)

    def test_malformed_fresh_reply_is_not_cached(self):
        self.run_v2(FakeCall(tag={str(self.question.id): tag_entry(thinking_level=['recall'])}))
        tagging_row = ItemTagging.objects.get(question=self.question)
        self.assertIn('invalid_key', tagging_row.review_reasons)  # coerced, not raised
        Question.objects.filter(id=self.question.id).update(tagging_status='stale')
        with patch('intelligence.services.tagging_v2._apply_tag', side_effect=TypeError('boom')):
            AITaggingResult.objects.all().delete()
            self.assertEqual(self.run_v2(FakeCall(tag={str(self.question.id): tag_entry()})), 0)
        self.assertFalse(AITaggingResult.objects.filter(stage='tag').exists())

    def test_manual_tags_are_never_overwritten(self):
        ItemTagging.objects.create(tenant=self.tenant, question=self.question, source='manual',
                                   thinking_level='recall')
        call = FakeCall(tag={str(self.question.id): tag_entry()})
        self.assertEqual(self.run_v2(call), 0)
        self.assertEqual(call.calls, [])
        self.assertEqual(ItemTagging.objects.get(question=self.question).thinking_level, 'recall')

    def test_failed_reply_leaves_the_item_untagged(self):
        self.assertEqual(self.run_v2(FakeCall()), 0)
        self.assertFalse(ItemTagging.objects.filter(question=self.question).exists())
        self.question.refresh_from_db()
        self.assertEqual(self.question.tagging_status, '')

    def test_mock_item_runs_blind_and_gets_topic_subject_difficulty(self):
        mock_test = MockTest.objects.create(tenant=self.tenant, title='Paper', duration_minutes=60,
                                            total_marks=4)
        mock_test.courses.set([self.course])
        item = MockTestItem.objects.create(
            tenant=self.tenant, mock_test=mock_test, item_type='mcq', question_text='Friction on a slope…',
            options=[{'text': '1', 'is_correct': True}, {'text': '2', 'is_correct': False}], marks=4,
        )
        call = FakeCall(locate={str(item.id): {'topic_key': LAWS, 'confidence': 0.9}},
                        tag={str(item.id): tag_entry(),
                             str(self.question.id): tag_entry()})
        self.assertEqual(self.run_v2(call), 2)
        self.assertIn('locate', call.calls)
        item.refresh_from_db()
        self.assertEqual((item.topic_id, item.subject_id), (self.laws.id, self.subject.id))
        self.assertEqual(item.difficulty, 'hard')  # untagged mock item: model difficulty applies

    def test_run_sweep_sends_untreed_subjects_to_v1(self):
        chemistry = Subject.objects.create(tenant=self.tenant, course=self.course, name='Chemistry',
                                           code='chemistry')
        call = FakeCall(tag={str(self.question.id): tag_entry()})
        with patched_tree(), patch.object(tagging_sweep.tagging_v1, 'run_tagging_for_tenant',
                                          return_value=3) as v1:
            result = tagging_sweep.run_sweep(self.tenant, limit=50, call=call)
        self.assertEqual(result, {'v2': 1, 'v1': 3})
        kwargs = v1.call_args.kwargs
        self.assertEqual(set(kwargs['exclude_subject_ids']), {self.subject.id})
        self.assertFalse(kwargs['check_budget'])
        self.assertNotIn(chemistry.id, set(kwargs['exclude_subject_ids']))

    def test_v1_selection_excludes_treed_subjects(self):
        self.assertIn(self.question, tagging.untagged_questions(self.tenant))
        self.assertNotIn(self.question,
                         tagging.untagged_questions(self.tenant, exclude_subject_ids={self.subject.id}))

    def test_tag_items_command_accepts_a_platform_model(self):
        call = FakeCall(tag={str(self.question.id): tag_entry()})
        out = StringIO()
        with patched_tree(), patch('intelligence.management.commands.tag_items.platform_call',
                                   return_value=call):
            call_command('tag_items', '--tenant', str(self.tenant.id), '--model', 'gpt-6-luna', stdout=out)
        self.assertIn('v2: 1', out.getvalue())

    def _blind_item(self):
        mock_test = MockTest.objects.create(tenant=self.tenant, title='Blind', duration_minutes=60,
                                            total_marks=4)
        mock_test.courses.set([self.course])
        return MockTestItem.objects.create(
            tenant=self.tenant, mock_test=mock_test, item_type='mcq', question_text='Unplaceable…',
            options=[{'text': '1', 'is_correct': True}, {'text': '2', 'is_correct': False}], marks=4,
        )

    def test_v2_owned_mock_items_are_never_handed_to_v1(self):
        item = self._blind_item()  # no subject, no topic; single-subject treed course
        self.run_v2(FakeCall())  # v2 gets no reply for it
        q = tagging_sweep.v2_mock_item_filter(self.tenant, {self.subject.id})
        self.assertIn(item, tagging.untagged_mock_items(self.tenant))
        self.assertNotIn(item, tagging.untagged_mock_items(self.tenant, exclude_mock_q=q))

    def test_run_sweep_passes_the_mock_filter_to_v1(self):
        item = self._blind_item()
        with patched_tree(), patch.object(tagging_sweep.tagging_v1, 'run_tagging_for_tenant',
                                          return_value=0) as v1:
            tagging_sweep.run_sweep(self.tenant, limit=50, call=FakeCall())
        q = v1.call_args.kwargs['exclude_mock_q']
        self.assertIsNotNone(q)
        self.assertNotIn(item, tagging.untagged_mock_items(self.tenant, exclude_mock_q=q))

    def test_no_topic_is_a_review_result_and_not_retried(self):
        item = self._blind_item()
        call = FakeCall(locate={str(item.id): {'topic_key': 'mini.physics.nope', 'confidence': 0.9}})
        self.run_v2(call)
        row = ItemTagging.objects.get(mock_item=item)
        self.assertEqual(row.review_status, 'needs_review')
        self.assertEqual(row.review_reasons, ['invalid_key'])
        self.assertIsNone(row.primary_node)
        self.assertFalse(ConceptLink.objects.filter(mock_item=item).exists())
        item.refresh_from_db()
        self.assertEqual(item.tagging_status, 'tagged')
        again = FakeCall()
        self.run_v2(again)
        self.assertNotIn('locate', again.calls)  # the blind item is not re-located
        self.assertEqual(ItemTagging.objects.filter(mock_item=item).count(), 1)


    def test_tree_change_retags_current_items(self):
        self.run_v2(FakeCall(tag={str(self.question.id): tag_entry()}))
        old = ItemTagging.objects.get(question=self.question).tree_version
        SyllabusNode.objects.filter(key=FRICTION).update(name='Kinetic friction')
        call = FakeCall(tag={str(self.question.id): tag_entry()})
        self.assertEqual(self.run_v2(call), 1)
        self.assertNotEqual(call.calls, [])
        new = ItemTagging.objects.get(question=self.question).tree_version
        self.assertNotEqual(new, old)
        self.assertEqual(new, syllabus.compute_tree_version(self.subject))

    def test_no_topic_item_is_retried_after_a_tree_change(self):
        item = self._blind_item()
        self.run_v2(FakeCall(locate={str(item.id): {'topic_key': 'mini.physics.nope', 'confidence': 0.9}}))
        SyllabusNode.objects.filter(key=FRICTION).update(name='Kinetic friction')
        again = FakeCall(locate={str(item.id): {'topic_key': LAWS, 'confidence': 0.9}},
                         tag={str(item.id): tag_entry()})
        self.run_v2(again)
        self.assertIn('locate', again.calls)
        row = ItemTagging.objects.get(mock_item=item)
        self.assertEqual(row.primary_node.key, FRICTION)

class LlmTests(TestCase):
    def test_unknown_platform_model_raises(self):
        with self.assertRaises(GenerationError):
            llm.platform_call('no-such-model')

    def test_metered_call_records_latency_per_call(self):
        metered = llm.MeteredCall(type('R', (), {'provider': 'p', 'model': 'm'})(), None)

        def fake(resolved, system, user, meter, tenant, feature=None):
            meter.elapsed_ms += 40
            return 'text'

        with patch('intelligence.services.llm._call', side_effect=fake):
            self.assertEqual(metered('s', 'u'), 'text')
            self.assertEqual(metered('s', 'u'), 'text')
        self.assertEqual(metered.latencies_ms, [40, 40])
        self.assertEqual(metered.model_ref, 'p:m')
