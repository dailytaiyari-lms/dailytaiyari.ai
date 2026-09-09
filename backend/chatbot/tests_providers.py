"""Tests for provider response and timeout handling.

These cover the two failure modes seen in production: an aggregator answering
HTTP 200 with no ``choices`` (which crashed with "'NoneType' object is not
subscriptable"), and a model so slow the web request outlives gunicorn.
"""
from types import SimpleNamespace
from unittest.mock import patch

import requests
from django.test import SimpleTestCase, override_settings

from .providers import (
    AIProviderError,
    ResolvedProvider,
    _normalise_error,
    _openai_content,
    _openai_stream,
    complete,
    read_timeout,
)


def _response(choices=None, error=None, usage=None):
    """A stand-in for the SDK's ChatCompletion, including pydantic extras."""
    resp = SimpleNamespace(choices=choices, usage=usage)
    if error is not None:
        resp.model_extra = {'error': error}
    return resp


def _choice(content=None, finish_reason=None):
    return SimpleNamespace(
        message=SimpleNamespace(content=content), finish_reason=finish_reason,
    )


class OpenAIContentTests(SimpleTestCase):
    """``_openai_content`` must never raise a raw Python error."""

    def test_choices_none_raises_readable_error(self):
        # The exact production shape: OpenRouter 200 with choices=None.
        with self.assertRaises(AIProviderError) as ctx:
            _openai_content(_response(choices=None))
        message = str(ctx.exception)
        self.assertIn('empty response', message)
        self.assertNotIn('NoneType', message)

    def test_choices_empty_list_raises_readable_error(self):
        with self.assertRaises(AIProviderError):
            _openai_content(_response(choices=[]))

    def test_error_body_is_surfaced_to_the_admin(self):
        resp = _response(
            choices=None,
            error={'message': 'Rate limit exceeded', 'code': 429},
        )
        with self.assertRaises(AIProviderError) as ctx:
            _openai_content(resp)
        self.assertIn('Rate limit exceeded', str(ctx.exception))
        self.assertIn('429', str(ctx.exception))

    def test_openrouter_nested_upstream_text_is_surfaced(self):
        resp = _response(
            choices=None,
            error={'metadata': {'raw': 'upstream provider is overloaded'}},
        )
        with self.assertRaises(AIProviderError) as ctx:
            _openai_content(resp)
        self.assertIn('overloaded', str(ctx.exception))

    def test_truncated_choice_explains_the_output_limit(self):
        resp = _response(choices=[_choice(content='', finish_reason='length')])
        with self.assertRaises(AIProviderError) as ctx:
            _openai_content(resp)
        self.assertIn('output limit', str(ctx.exception))

    def test_content_filter_is_explained(self):
        resp = _response(choices=[_choice(content=None, finish_reason='content_filter')])
        with self.assertRaises(AIProviderError) as ctx:
            _openai_content(resp)
        self.assertIn('safety filter', str(ctx.exception))

    def test_normal_response_returns_content(self):
        resp = _response(choices=[_choice(content='Hello there')])
        self.assertEqual(_openai_content(resp), 'Hello there')

    def test_message_none_does_not_crash(self):
        resp = _response(choices=[SimpleNamespace(message=None, finish_reason='stop')])
        self.assertEqual(_openai_content(resp), '')


class StreamTests(SimpleTestCase):
    """An empty stream is a failure, not a blank answer."""

    def _run(self, chunks):
        rp = ResolvedProvider(provider='openai', model='m')
        with patch('chatbot.providers._openai_client') as client:
            client.return_value.chat.completions.create.return_value = iter(chunks)
            return list(_openai_stream(rp, []))

    def test_stream_with_no_tokens_raises(self):
        with self.assertRaises(AIProviderError) as ctx:
            self._run([SimpleNamespace(choices=[], usage=None)])
        self.assertIn('empty response', str(ctx.exception))

    def test_stream_error_chunk_is_surfaced(self):
        chunk = SimpleNamespace(
            choices=[], usage=None, model_extra={'error': {'message': 'quota exhausted'}},
        )
        with self.assertRaises(AIProviderError) as ctx:
            self._run([chunk])
        self.assertIn('quota exhausted', str(ctx.exception))

    def test_stream_with_tokens_yields_normally(self):
        chunk = SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content='hi'))], usage=None,
        )
        out = self._run([chunk])
        self.assertEqual(out[0][0], 'hi')
        # Final yield always carries usage.
        self.assertEqual(out[-1][0], '')


class TimeoutTests(SimpleTestCase):
    def test_web_timeout_stays_below_gunicorn_timeout(self):
        """The whole point of the change: gunicorn must not kill us first."""
        import importlib.util
        import pathlib

        path = pathlib.Path(__file__).resolve().parent.parent / 'gunicorn.conf.py'
        spec = importlib.util.spec_from_file_location('gunicorn_conf', path)
        conf = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(conf)

        from django.conf import settings
        self.assertLess(settings.AI_READ_TIMEOUT, conf.timeout)

    @override_settings(AI_READ_TIMEOUT=90, AI_READ_TIMEOUT_BACKGROUND=600)
    def test_background_context_gets_the_longer_timeout(self):
        with patch('chatbot.providers.in_background_worker', return_value=True):
            self.assertEqual(read_timeout(), 600)
        with patch('chatbot.providers.in_background_worker', return_value=False):
            self.assertEqual(read_timeout(), 90)

    def test_timeout_error_names_the_model_and_suggests_a_fix(self):
        rp = ResolvedProvider(provider='openrouter', model='nvidia/slow-model:free')
        err = _normalise_error(rp, requests.exceptions.Timeout('timed out'))
        self.assertIn('nvidia/slow-model:free', str(err))
        self.assertIn('faster model', str(err))

    def test_sdk_timeout_class_is_recognised_by_name(self):
        class APITimeoutError(Exception):
            pass

        rp = ResolvedProvider(provider='openai', model='gpt-4o')
        err = _normalise_error(rp, APITimeoutError('request timed out'))
        self.assertIn('did not respond', str(err))

    def test_non_timeout_errors_pass_through(self):
        rp = ResolvedProvider(provider='openai', model='gpt-4o')
        err = _normalise_error(rp, ValueError('something else'))
        self.assertIn('something else', str(err))

    def test_complete_wraps_a_timeout_rather_than_leaking_it(self):
        rp = ResolvedProvider(provider='openai', model='gpt-4o')
        with patch('chatbot.providers._openai_complete',
                   side_effect=requests.exceptions.Timeout('timed out')):
            with self.assertRaises(AIProviderError):
                complete(rp, [])
