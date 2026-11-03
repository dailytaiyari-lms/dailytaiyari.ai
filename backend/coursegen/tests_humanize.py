"""Tests for the humanizer hook. The service itself is stubbed at the HTTP layer."""
from unittest.mock import Mock, patch

import requests
from django.test import SimpleTestCase, override_settings

from coursegen.humanize import humanize_draft

URL = 'http://humanizer:8100'


def service_response(text):
    return Mock(
        status_code=200,
        raise_for_status=Mock(),
        json=Mock(return_value={
            'text': f'H: {text}', 'sentences_total': 1, 'sentences_rewritten': 1,
        }),
    )


def fake_post(_url, json, timeout):
    return service_response(json['text'])


def content_draft():
    return {'topics': [{
        'topic_name': 'Variables',
        'note': {
            'title': 'Variables',
            'blocks': [
                {'type': 'lead', 'text': 'Lead text.'},
                {'type': 'heading', 'text': 'A heading', 'level': 3},
                {'type': 'paragraph', 'text': 'Paragraph text.'},
                {'type': 'bullets', 'items': ['Bullet one.', 'Bullet two.']},
                {'type': 'numbers', 'items': ['Step one.']},
                {'type': 'code', 'text': 'x = 1', 'language': 'python'},
                {'type': 'callout', 'variant': 'tip', 'title': 'A title', 'text': 'Callout text.'},
                {'type': 'table', 'headers': ['Head'], 'rows': [['Cell']]},
                {'type': 'quote', 'text': 'Quote text.', 'attribution': 'Someone'},
                {'type': 'divider'},
            ],
            'html': '<p>old</p>',
            'estimated_time_minutes': 3,
            'include': True,
        },
        'quiz': {'questions': [{'question_text': 'Q?', 'explanation': 'Because.'}]},
        'assignments': [{'title': 'A', 'instructions': [{'type': 'paragraph', 'text': 'Do it.'}]}],
        'coding_problems': [{'title': 'C', 'statement': [{'type': 'paragraph', 'text': 'Solve.'}]}],
    }]}


def outline_draft():
    return {
        'course': {'name': 'Python', 'subtitle': 'Sub', 'description': 'Course text.',
                   'highlights': ['Highlight.']},
        'subjects': [{
            'name': 'Core', 'description': 'Subject text.',
            'chapters': [{
                'name': 'Basics', 'description': 'Chapter text.',
                'topics': [{'name': 'Loops', 'summary': 'Topic text.',
                            'objectives': ['Objective.']}],
            }],
        }],
    }


def meta_draft():
    return {'course': {
        'subtitle': 'Sub',
        'description': 'Plain description.',
        'description_blocks': [
            {'type': 'heading', 'text': 'A heading', 'level': 3},
            {'type': 'paragraph', 'text': 'Block text.'},
        ],
        'description_html': '<p>old</p>',
        'highlights': ['Highlight.'],
        'refund_policy': 'Refund text.',
    }}


@override_settings(HUMANIZER_URL=URL, HUMANIZER_READ_TIMEOUT_S=120)
class HumanizeDraftTests(SimpleTestCase):
    def run_draft(self, kind, draft, **kwargs):
        kwargs.setdefault('time_budget_s', 600)
        with patch('coursegen.humanize.requests.post', side_effect=fake_post) as post:
            result = humanize_draft(kind, draft, **kwargs)
        return result, post

    def test_content_changes_only_prose_blocks(self):
        result, post = self.run_draft('content', content_draft())
        topic = result['topics'][0]
        blocks = topic['note']['blocks']

        self.assertEqual(blocks[0]['text'], 'H: Lead text.')
        self.assertEqual(blocks[1]['text'], 'A heading')
        self.assertEqual(blocks[2]['text'], 'H: Paragraph text.')
        self.assertEqual(blocks[3]['items'], ['H: Bullet one.', 'H: Bullet two.'])
        self.assertEqual(blocks[4]['items'], ['H: Step one.'])
        self.assertEqual(blocks[5]['text'], 'x = 1')
        self.assertEqual(blocks[6]['text'], 'H: Callout text.')
        self.assertEqual(blocks[6]['title'], 'A title')
        self.assertEqual(blocks[7]['rows'], [['Cell']])
        self.assertEqual(blocks[8]['text'], 'H: Quote text.')
        self.assertEqual(blocks[8]['attribution'], 'Someone')

        self.assertEqual(topic['quiz']['questions'][0]['explanation'], 'Because.')
        self.assertEqual(topic['assignments'][0]['instructions'][0]['text'], 'Do it.')
        self.assertEqual(topic['coding_problems'][0]['statement'][0]['text'], 'Solve.')
        self.assertEqual(post.call_count, 7)

    def test_content_html_and_reading_time_are_rerendered(self):
        draft = content_draft()
        draft['topics'][0]['note']['blocks'][2]['text'] = ' '.join(['word'] * 1000) + '.'
        result, _post = self.run_draft('content', draft)
        note = result['topics'][0]['note']

        self.assertIn('H: Lead text.', note['html'])
        self.assertNotIn('<p>old</p>', note['html'])
        self.assertEqual(note['estimated_time_minutes'], 5)

    def test_outline_changes_descriptions_and_summaries_only(self):
        result, post = self.run_draft('outline', outline_draft())

        self.assertEqual(result['course']['description'], 'H: Course text.')
        self.assertEqual(result['course']['subtitle'], 'Sub')
        self.assertEqual(result['course']['highlights'], ['Highlight.'])
        subject = result['subjects'][0]
        self.assertEqual(subject['description'], 'H: Subject text.')
        chapter = subject['chapters'][0]
        self.assertEqual(chapter['description'], 'H: Chapter text.')
        self.assertEqual(chapter['name'], 'Basics')
        self.assertEqual(chapter['topics'][0]['summary'], 'H: Topic text.')
        self.assertEqual(chapter['topics'][0]['objectives'], ['Objective.'])
        self.assertEqual(post.call_count, 4)

    def test_meta_changes_description_and_rerenders_html(self):
        result, _post = self.run_draft('meta', meta_draft())
        course = result['course']

        self.assertEqual(course['description'], 'H: Plain description.')
        self.assertEqual(course['description_blocks'][0]['text'], 'A heading')
        self.assertEqual(course['description_blocks'][1]['text'], 'H: Block text.')
        self.assertIn('H: Block text.', course['description_html'])
        self.assertEqual(course['refund_policy'], 'Refund text.')
        self.assertEqual(course['highlights'], ['Highlight.'])

    def test_report_counts_sentences(self):
        result, _post = self.run_draft('outline', outline_draft())
        self.assertEqual(result['humanizer'], {
            'status': 'complete', 'sentences_total': 4,
            'sentences_rewritten': 4, 'fields_skipped': 0,
        })

    def test_rewrite_over_the_field_limit_keeps_the_original(self):
        draft = outline_draft()
        original = 'x' * 799
        draft['subjects'][0]['chapters'][0]['topics'][0]['summary'] = original
        result, _post = self.run_draft('outline', draft)

        topic = result['subjects'][0]['chapters'][0]['topics'][0]
        self.assertEqual(topic['summary'], original)
        self.assertEqual(result['humanizer']['status'], 'partial')
        self.assertEqual(result['humanizer']['fields_skipped'], 1)
        self.assertEqual(result['humanizer']['sentences_rewritten'], 3)

    def test_unchanged_text_from_the_previous_draft_is_not_sent(self):
        previous = outline_draft()
        draft = outline_draft()
        draft['subjects'][0]['description'] = 'A new subject text.'
        result, post = self.run_draft('outline', draft, previous=previous)

        self.assertEqual(post.call_count, 1)
        self.assertEqual(result['subjects'][0]['description'], 'H: A new subject text.')
        self.assertEqual(result['course']['description'], 'Course text.')
        self.assertEqual(result['humanizer']['status'], 'complete')

    def test_service_failure_keeps_text_and_stops_calling(self):
        for error in (requests.ConnectionError('down'), requests.Timeout('slow')):
            with self.subTest(error=error):
                with patch('coursegen.humanize.requests.post', side_effect=error) as post:
                    result = humanize_draft('outline', outline_draft(), time_budget_s=600)

                self.assertEqual(post.call_count, 1)
                self.assertEqual(result['course']['description'], 'Course text.')
                self.assertEqual(result['humanizer']['status'], 'failed')
                self.assertEqual(result['humanizer']['fields_skipped'], 4)

    def test_non_200_response_keeps_text(self):
        bad = Mock(raise_for_status=Mock(side_effect=requests.HTTPError('503')))
        with patch('coursegen.humanize.requests.post', return_value=bad) as post:
            result = humanize_draft('outline', outline_draft(), time_budget_s=600)

        self.assertEqual(post.call_count, 1)
        self.assertEqual(result['course']['description'], 'Course text.')
        self.assertEqual(result['humanizer']['status'], 'failed')

    def test_malformed_response_keeps_text(self):
        bad = Mock(raise_for_status=Mock(), json=Mock(return_value=['not', 'a', 'dict']))
        with patch('coursegen.humanize.requests.post', return_value=bad):
            result = humanize_draft('outline', outline_draft(), time_budget_s=600)

        self.assertEqual(result['course']['description'], 'Course text.')
        self.assertEqual(result['humanizer']['status'], 'failed')

    def test_failure_after_some_success_is_partial(self):
        responses = [service_response('Course text.'), requests.ConnectionError('down')]
        with patch('coursegen.humanize.requests.post', side_effect=responses):
            result = humanize_draft('outline', outline_draft(), time_budget_s=600)

        self.assertEqual(result['course']['description'], 'H: Course text.')
        self.assertEqual(result['subjects'][0]['description'], 'Subject text.')
        self.assertEqual(result['humanizer']['status'], 'partial')
        self.assertEqual(result['humanizer']['fields_skipped'], 3)

    def test_spent_budget_makes_no_calls(self):
        result, post = self.run_draft('outline', outline_draft(), time_budget_s=0)

        post.assert_not_called()
        self.assertEqual(result['course']['description'], 'Course text.')
        self.assertEqual(result['humanizer']['status'], 'partial')
        self.assertEqual(result['humanizer']['fields_skipped'], 4)

    def test_budget_running_out_mid_draft_stops_calls(self):
        clock = iter([0, 1])
        with patch('coursegen.humanize.time.monotonic', side_effect=lambda: next(clock, 700)), \
                patch('coursegen.humanize.requests.post', side_effect=fake_post) as post:
            result = humanize_draft('outline', outline_draft(), time_budget_s=600)

        self.assertEqual(post.call_count, 1)
        self.assertEqual(result['humanizer']['fields_skipped'], 3)


class HumanizeDisabledTests(SimpleTestCase):
    @override_settings(HUMANIZER_URL='')
    def test_empty_url_makes_no_call_and_changes_nothing(self):
        draft = outline_draft()
        with patch('coursegen.humanize.requests.post') as post:
            result = humanize_draft('outline', draft, time_budget_s=600)

        post.assert_not_called()
        self.assertEqual(result, outline_draft())

    @override_settings(HUMANIZER_URL=URL)
    def test_unknown_kind_changes_nothing(self):
        with patch('coursegen.humanize.requests.post') as post:
            result = humanize_draft('other', {'a': 1}, time_budget_s=600)

        post.assert_not_called()
        self.assertEqual(result, {'a': 1})
