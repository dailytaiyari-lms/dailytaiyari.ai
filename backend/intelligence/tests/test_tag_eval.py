"""Tagger evaluation: metrics, threshold suggestion, gold files, the command."""
import json
import tempfile
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase

from chatbot.providers import Usage
from intelligence.services import eval_jee, tag_eval, taxonomy
from intelligence.services.tagging_v2 import LOCATE_MARKER, TagResult

T1, T2 = 'x.physics.m.t1', 'x.physics.m.t2'
S1, S2, S3 = f'{T1}.s1', f'{T1}.s2', f'{T2}.s3'


def gold_rows():
    return [
        {'id': 'a', 'gold': {'topic': T1, 'subtopic': S1, 'thinking_level': 'recall', 'skills': ['x', 'y'],
                             'core_skills': ['x'], 'difficulty': 'easy', 'special_format': ''}},
        {'id': 'b', 'gold': {'topic': T1, 'subtopic': S2, 'thinking_level': 'analytical', 'skills': ['x'],
                             'core_skills': [], 'difficulty': 'hard', 'special_format': 'statement_pair'}},
        {'id': 'c', 'gold': {'topic': T2, 'subtopic': S3}},
    ]


def results():
    return [
        TagResult(id='a', topic_key=T1, primary_subtopic=S1, thinking_level='recall',
                  skills=[{'key': 'x', 'role': 'core', 'reason': ''}, {'key': 'z', 'role': 'supporting', 'reason': ''}],
                  difficulty='medium', confidence=0.95, review_reasons=[], needs_review=False),
        TagResult(id='b', topic_key=T2, primary_subtopic=S3, secondary_subtopics=[S2],
                  thinking_level='multi_concept', skills=[{'key': 'x', 'role': 'core', 'reason': ''}],
                  special_format='statement_pair', difficulty='hard', confidence=0.55,
                  review_reasons=['low_confidence'], needs_review=True),
    ]


class ScoreTests(SimpleTestCase):
    def test_metrics_match_hand_computation(self):
        m = tag_eval.score(gold_rows(), results(), mode='blind')
        self.assertEqual(m['n'], 3)
        self.assertEqual(m['error_rate'], 0.3333)  # 'c' is missing
        self.assertEqual(m['needs_review_rate'], 0.6667)
        self.assertEqual(m['invalid_key_rate'], 0.0)
        self.assertEqual(m['topic_accuracy'], 0.3333)
        self.assertEqual((m['subtopic_exact'], m['subtopic_hit']), (0.3333, 0.6667))
        self.assertEqual(m['thinking_accuracy'], 0.5)
        self.assertEqual(m['thinking_confusion'], {'recall': {'recall': 1}, 'analytical': {'multi_concept': 1}})
        self.assertEqual(m['skills'], {'precision': 0.6667, 'recall': 0.6667, 'f1': 0.6667})
        self.assertEqual(m['core_skills'], {'precision': 0.5, 'recall': 1.0, 'f1': 0.6667})
        self.assertEqual((m['difficulty_accuracy'], m['difficulty_within_one']), (0.5, 1.0))
        self.assertEqual(m['special_formats'], {'statement_pair': {'precision': 1.0, 'recall': 1.0, 'f1': 1.0}})
        self.assertEqual(m['calibration'], [{'from': 0.5, 'n': 1, 'subtopic_exact': 0.0},
                                            {'from': 0.9, 'n': 1, 'subtopic_exact': 1.0}])
        self.assertEqual(m['suggested_threshold'], 0.6)

    def test_anchored_mode_has_no_topic_accuracy(self):
        self.assertNotIn('topic_accuracy', tag_eval.score(gold_rows(), results(), mode='anchored'))

    def test_percentile_and_markdown(self):
        self.assertEqual(tag_eval.percentile([30, 10, 20, 40], 50), 20)
        self.assertEqual(tag_eval.percentile([30, 10, 20, 40], 95), 40)
        self.assertIsNone(tag_eval.percentile([], 50))
        report = {'gold': 'g.jsonl', 'mode': 'blind',
                  'models': {'gpt-6-luna': {**tag_eval.score(gold_rows(), results(), mode='blind'),
                                            'tokens_per_question': 120.0, 'cost_per_1000_usd': 0.0}}}
        text = tag_eval.render_markdown(report)
        self.assertIn('| Metric | gpt-6-luna |', text)
        self.assertIn('| Subtopic hit | 0.667 |', text)
        self.assertIn('| Tokens / question | 120.0 |', text)


def dataset_rows():
    rows = []
    for index in range(6):
        rows.append({
            'question_id': f'q{index}', 'subject': 'physics',
            'chapter': ['laws-of-motion', 'gravitation'][index % 2],
            'topic': ['friction-force', 'orbits'][index % 2],
            'question': f'<p>Question {index}</p>',
            'options': json.dumps([{'identifier': 'A', 'content': '1'}, {'identifier': 'B', 'content': '2'}]),
            'correct_option': json.dumps(['A']), 'answer': None, 'explanation': '',
            'question_type': 'mcq', 'paper_id': 'jee-main-2023-online-1st-february-morning-shift',
        })
    return rows


class FakeMeteredCall:
    model_ref = 'fake:eval'

    def __init__(self, rows):
        self.rows = {row['id']: row for row in rows}
        self.meter = SimpleNamespace(usage=Usage(100, 50, 150), elapsed_ms=0)
        self.latencies_ms = [120, 80]

    def cost_usd(self):
        return 0.0

    def __call__(self, system, user):
        ids = [i for i in self.rows if f'"id": "{i}"' in user]
        if LOCATE_MARKER in system:
            items = [{'id': i, 'topic_key': self.rows[i]['gold']['topic'], 'confidence': 0.9} for i in ids]
        else:
            items = [{'id': i, 'primary_subtopic': self.rows[i]['gold']['subtopic'], 'thinking_level': 'recall',
                      'skills': [], 'confidence': 0.9} for i in ids]
        return json.dumps({'items': items})


class GoldAndEvaluateCommandTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dumps = Path(self.tmp.name) / 'data_dumps'
        self.dumps.mkdir()
        self.source = self.dumps / 'eval_jee.jsonl'
        self.source.write_text('\n'.join(json.dumps(r) for r in dataset_rows()), encoding='utf-8')
        tree, _ = eval_jee.draft_jee_main_tree(dataset_rows())
        self.tree = taxonomy.validate_exam_tree(tree)

    def tearDown(self):
        self.tmp.cleanup()

    def patch_tree(self, module):
        return patch(f'intelligence.management.commands.{module}.load_exam_tree', return_value=self.tree)

    def test_make_gold_from_eval_jee(self):
        out = self.dumps / 'gold.jsonl'
        with self.patch_tree('make_gold'):
            call_command('make_gold', '--eval-jee', str(self.source), '--out', str(out), '--n', '4',
                         '--seed', '7', stdout=StringIO())
        rows = eval_jee.read_rows(out)
        self.assertEqual(len(rows), 4)
        first = rows[0]
        self.assertEqual(set(first), {'id', 'subject', 'type', 'question', 'options', 'answer',
                                      'topic_hint', 'gold', 'source'})
        self.assertTrue(first['gold']['subtopic'].startswith(first['gold']['topic'] + '.'))
        self.assertEqual(first['topic_hint'], first['gold']['topic'])

    def test_gold_must_go_under_data_dumps(self):
        with self.patch_tree('make_gold'), self.assertRaises(CommandError):
            call_command('make_gold', '--eval-jee', str(self.source),
                         '--out', str(Path(self.tmp.name) / 'gold.jsonl'), stdout=StringIO())

    def test_evaluate_tagger_blind_and_anchored(self):
        gold = self.dumps / 'gold.jsonl'
        with self.patch_tree('make_gold'):
            call_command('make_gold', '--eval-jee', str(self.source), '--out', str(gold), '--n', '4',
                         stdout=StringIO())
        rows = eval_jee.read_rows(gold)
        report_path = self.dumps / 'report.json'
        out = StringIO()
        with self.patch_tree('evaluate_tagger'), patch(
                'intelligence.management.commands.evaluate_tagger.platform_call',
                return_value=FakeMeteredCall(rows)):
            call_command('evaluate_tagger', '--gold', str(gold), '--models', 'gpt-6-luna', '--mode', 'blind',
                         '--exam', 'jee_main', '--out', str(report_path), stdout=out)
        self.assertIn('| Topic accuracy (blind) | 1.000 |', out.getvalue())
        saved = json.loads(report_path.read_text(encoding='utf-8'))
        self.assertEqual(saved['report']['models']['gpt-6-luna']['subtopic_exact'], 1.0)
        self.assertEqual(len(saved['items']['gpt-6-luna']), 4)
        self.assertNotIn('question', saved['items']['gpt-6-luna'][0])  # ids and keys only
        with self.patch_tree('evaluate_tagger'), patch(
                'intelligence.management.commands.evaluate_tagger.platform_call',
                return_value=FakeMeteredCall(rows)):
            call_command('evaluate_tagger', '--gold', str(gold), '--models', 'gpt-6-luna',
                         '--mode', 'anchored', '--exam', 'jee_main', stdout=(anchored := StringIO()))
        self.assertNotIn('Topic accuracy (blind) | 1', anchored.getvalue())
        self.assertIn('| Subtopic exact | 1.000 |', anchored.getvalue())
