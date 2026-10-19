"""Tagger v2 core: prompts, two stages, validation, confidence, review rule."""
import json
import re

from django.test import SimpleTestCase

from coursegen.generation import GenerationError
from intelligence.services import tagging_v2
from intelligence.services.tagging_v2 import LOCATE_MARKER, TAG_MARKER

LAWS = 'mini.physics.mechanics.laws_of_motion'
WORK = 'mini.physics.mechanics.work_energy'
FRICTION = f'{LAWS}.friction'
NEWTON = f'{LAWS}.newtons_laws'
POWER = f'{WORK}.power'


def context(**overrides):
    base = {
        'exam_label': 'Mini Exam', 'audience': 'Mini Exam aspirants', 'subject': 'Physics',
        'review_threshold': 0.6, 'taxonomy_version': '1', 'tree_version': 'abc',
        'topics': [
            {'key': LAWS, 'label': 'Laws of Motion', 'description': '', 'group': 'Mechanics',
             'course_topic_id': None,
             'subtopics': [{'key': FRICTION, 'label': 'Friction', 'description': ''},
                           {'key': NEWTON, 'label': "Newton's Laws", 'description': ''}]},
            {'key': WORK, 'label': 'Work and Energy', 'description': '', 'group': 'Mechanics',
             'course_topic_id': None,
             'subtopics': [{'key': POWER, 'label': 'Power', 'description': ''}]},
        ],
        'thinking_levels': [{'key': k, 'label': k, 'definition': k} for k in
                            ('recall', 'conceptual', 'single_application', 'multi_concept', 'analytical')],
        'special_formats': [{'key': 'statement_pair', 'label': 'Two statements', 'definition': 'I and II'}],
        'skills': [{'key': 'formula_application', 'label': 'F', 'definition': 'f', 'pack': ''},
                   {'key': 'free_body_diagram', 'label': 'FBD', 'definition': 'fbd', 'pack': 'physics'}],
    }
    base.update(overrides)
    return base


def payload(pid, hint='', question='A block on a rough incline…'):
    return {'id': pid, 'type': 'mcq', 'question': question, 'options': ['1 N', '2 N'],
            'answer': '2 N', 'topic_hint': hint}


def tag_entry(**overrides):
    entry = {'primary_subtopic': FRICTION, 'secondary_subtopics': [NEWTON],
             'thinking_level': 'multi_concept',
             'skills': [{'key': 'free_body_diagram', 'role': 'core', 'reason': 'forces on the block'},
                        {'key': 'formula_application', 'role': 'supporting', 'reason': 'mu N'}],
             'special_format': '', 'difficulty': 'medium', 'est_solve_seconds': 90,
             'proposed_subtopic': '', 'confidence': 0.9}
    entry.update(overrides)
    return entry


class FakeCall:
    """Answers each stage from per-id tables; records prompts."""

    def __init__(self, locate=None, tag=None, fail=None):
        self.locate, self.tag, self.fail = locate or {}, tag or {}, fail
        self.calls = []

    def __call__(self, system, user):
        stage = 'locate' if LOCATE_MARKER in system else 'tag'
        self.calls.append((stage, system, user))
        if self.fail == stage:
            raise GenerationError('provider down')
        ids = re.findall(r'"id": "([^"]+)"', user)
        table = self.locate if stage == 'locate' else self.tag
        return json.dumps({'items': [dict(table[i], id=i) for i in ids if i in table]})


class DictCache:
    def __init__(self):
        self.store = {}

    def get(self, stage, payload_id):
        return self.store.get((stage, payload_id))

    def put(self, stage, payload_id, entry):
        self.store[(stage, payload_id)] = entry


class TagPayloadsTests(SimpleTestCase):
    def test_anchored_item_skips_stage_one(self):
        call = FakeCall(tag={'q1': tag_entry()})
        [result] = tagging_v2.tag_payloads(context(), [payload('q1', hint=LAWS)], call=call)
        self.assertEqual([stage for stage, _, _ in call.calls], ['tag'])
        self.assertEqual(result.topic_key, LAWS)
        self.assertEqual(result.primary_subtopic, FRICTION)
        self.assertEqual(result.secondary_subtopics, [NEWTON])
        self.assertEqual(result.thinking_level, 'multi_concept')
        self.assertEqual([s['key'] for s in result.skills], ['free_body_diagram', 'formula_application'])
        self.assertEqual(result.skills[0]['role'], 'core')
        self.assertEqual((result.difficulty, result.est_solve_seconds), ('medium', 90))
        self.assertFalse(result.needs_review)
        self.assertEqual(result.review_reasons, [])
        self.assertEqual(result.error, '')
        # Exam-aware prompt: audience and exam label reach the model.
        self.assertIn('Mini Exam aspirants', call.calls[0][1])
        self.assertIn(FRICTION, call.calls[0][2])
        self.assertNotIn(POWER, call.calls[0][2])  # only the anchored topic's subtopics

    def test_blind_item_runs_both_stages_and_includes_also_topics(self):
        call = FakeCall(
            locate={'q1': {'topic_key': LAWS, 'also_topic_keys': [WORK], 'confidence': 0.8}},
            tag={'q1': tag_entry(secondary_subtopics=[POWER])},
        )
        [result] = tagging_v2.tag_payloads(context(), [payload('q1')], call=call)
        self.assertEqual([stage for stage, _, _ in call.calls], ['locate', 'tag'])
        self.assertIn(POWER, call.calls[1][2])
        self.assertEqual(result.secondary_subtopics, [POWER])
        self.assertFalse(result.needs_review)

    def test_stage_disagreement_lowers_confidence(self):
        call = FakeCall(
            locate={'q1': {'topic_key': WORK, 'also_topic_keys': [LAWS], 'confidence': 0.9}},
            tag={'q1': tag_entry(confidence=0.7, secondary_subtopics=[])},
        )
        [result] = tagging_v2.tag_payloads(context(), [payload('q1')], call=call)
        self.assertEqual(result.topic_key, LAWS)  # follows the primary subtopic
        self.assertAlmostEqual(result.confidence, 0.56)
        self.assertEqual(result.review_reasons, ['low_confidence', 'stage_disagreement'])
        self.assertTrue(result.needs_review)

    def test_invalid_keys_are_dropped_and_flagged(self):
        call = FakeCall(tag={'q1': tag_entry(
            secondary_subtopics=['made.up.key', NEWTON],
            thinking_level='genius',
            skills=[{'key': 'telepathy'}, 'formula_application', {'key': 'formula_application'}],
            special_format='riddle', difficulty='brutal', est_solve_seconds=99999,
        )})
        [result] = tagging_v2.tag_payloads(context(), [payload('q1', hint=LAWS)], call=call)
        self.assertEqual(result.secondary_subtopics, [NEWTON])
        self.assertEqual(result.thinking_level, '')
        self.assertEqual(result.skills, [{'key': 'formula_application', 'role': 'supporting', 'reason': ''}])
        self.assertEqual((result.special_format, result.difficulty), ('', ''))
        self.assertEqual(result.est_solve_seconds, 1800)
        self.assertEqual(result.review_reasons, ['invalid_key'])

    def test_unknown_primary_or_proposal_needs_review(self):
        call = FakeCall(tag={
            'q1': tag_entry(primary_subtopic='nope'),
            'q2': tag_entry(primary_subtopic='', proposed_subtopic='Pseudo forces'),
        })
        results = tagging_v2.tag_payloads(
            context(), [payload('q1', hint=LAWS), payload('q2', hint=LAWS)], call=call)
        self.assertEqual((results[0].primary_subtopic, results[0].secondary_subtopics), ('', []))
        self.assertIn('invalid_key', results[0].review_reasons)
        self.assertEqual(results[1].proposed_subtopic, 'Pseudo forces')
        self.assertEqual(results[1].review_reasons, ['proposed_subtopic'])

    def test_missing_items_and_failed_calls_are_errors_not_tags(self):
        call = FakeCall(tag={'q1': tag_entry()})
        results = tagging_v2.tag_payloads(
            context(), [payload('q1', hint=LAWS), payload('q2', hint=LAWS)], call=call)
        self.assertEqual(results[1].error, 'missing_from_reply')
        failing = FakeCall(fail='tag')
        [result] = tagging_v2.tag_payloads(context(), [payload('q1', hint=LAWS)], call=failing)
        self.assertTrue(result.error.startswith('call_failed'))
        blind_fail = FakeCall(locate={'q1': {'topic_key': 'nope', 'confidence': 0.9}})
        [result] = tagging_v2.tag_payloads(context(), [payload('q1')], call=blind_fail)
        self.assertEqual(result.error, 'no_topic')
        self.assertEqual(len(blind_fail.calls), 1)

    def test_batches_of_twelve_grouped_by_topic(self):
        payloads = [payload(f'q{i}', hint=LAWS) for i in range(13)] + [payload('w1', hint=WORK)]
        entries = {p['id']: tag_entry(secondary_subtopics=[]) for p in payloads}
        entries['w1'] = tag_entry(primary_subtopic=POWER, secondary_subtopics=[])
        call = FakeCall(tag=entries)
        results = tagging_v2.tag_payloads(context(), payloads, call=call)
        self.assertEqual(len(call.calls), 3)  # 12 + 1 laws, 1 work
        self.assertEqual([r.id for r in results], [p['id'] for p in payloads])
        self.assertEqual(results[-1].primary_subtopic, POWER)

    def test_cache_hits_skip_the_model(self):
        cache = DictCache()
        first = FakeCall(locate={'q1': {'topic_key': LAWS, 'confidence': 0.9}}, tag={'q1': tag_entry()})
        tagging_v2.tag_payloads(context(), [payload('q1')], call=first, cache=cache)
        second = FakeCall()
        [result] = tagging_v2.tag_payloads(context(), [payload('q1')], call=second, cache=cache)
        self.assertEqual(second.calls, [])
        self.assertEqual(result.primary_subtopic, FRICTION)

    def test_format_hint_reaches_the_prompt(self):
        call = FakeCall(tag={'q1': tag_entry(special_format='statement_pair')})
        text = 'Given below are two statements: Statement I: … Statement II: … Choose.'
        [result] = tagging_v2.tag_payloads(context(), [payload('q1', hint=LAWS, question=text)], call=call)
        self.assertIn('"format_hint": "statement_pair"', call.calls[0][2])
        self.assertEqual(result.special_format, 'statement_pair')
        self.assertEqual(tagging_v2.format_hint('List-I … List-II'), 'match_list')
        self.assertEqual(tagging_v2.format_hint('plain question'), '')

    def test_empty_tree_marks_every_item(self):
        [result] = tagging_v2.tag_payloads(context(topics=[]), [payload('q1')], call=FakeCall())
        self.assertEqual(result.error, 'no_tree')

    def test_cognitive_projection(self):
        self.assertEqual(tagging_v2.cognitive_projection('recall'), 'recall')
        self.assertEqual(tagging_v2.cognitive_projection('multi_concept'), 'multi_concept')
        self.assertEqual(tagging_v2.cognitive_projection('analytical'), 'application')
        self.assertEqual(tagging_v2.cognitive_projection(''), '')
