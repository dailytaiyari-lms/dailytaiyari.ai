"""Tests for provider response and timeout handling.

These cover the failure modes seen in production: an aggregator answering
HTTP 200 with no ``choices`` (which crashed with "'NoneType' object is not
subscriptable"), a model so slow the web request outlives gunicorn, and the
newer OpenAI/Azure reasoning models rejecting ``max_tokens``.
"""
from types import SimpleNamespace
from unittest.mock import patch

import requests
from django.test import SimpleTestCase, override_settings

from . import providers as providers_mod
from .providers import (
    AIProviderError,
    ResolvedProvider,
    _normalise_error,
    _openai_content,
    _openai_create,
    _openai_stream,
    _token_param_for,
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


class _FakeCompletions:
    """Records the kwargs of each call and raises whatever is queued."""

    def __init__(self, errors=None):
        self.calls = []
        self.errors = list(errors or [])

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.errors:
            err = self.errors.pop(0)
            if err is not None:
                raise err
        return _response(choices=[_choice('ok')])


class _FakeClient:
    def __init__(self, errors=None):
        self.completions = _FakeCompletions(errors)
        self.chat = SimpleNamespace(completions=self.completions)


UNSUPPORTED = (
    "Error code: 400 - {'error': {'message': \"Unsupported parameter: "
    "'max_tokens' is not supported with this model. Use "
    "'max_completion_tokens' instead.\", 'type': 'invalid_request_error'}}"
)


class TokenParameterTests(SimpleTestCase):
    """Newer reasoning models need ``max_completion_tokens``, older ones don't."""

    def setUp(self):
        providers_mod._TOKEN_PARAM_OVERRIDES.clear()
        self.addCleanup(providers_mod._TOKEN_PARAM_OVERRIDES.clear)

    def test_classic_models_keep_max_tokens(self):
        for name in ('gpt-4o', 'gpt-4o-mini', 'llama3.1', 'claude-3-5-sonnet'):
            rp = ResolvedProvider(provider='openai', model=name)
            self.assertEqual(_token_param_for(rp), 'max_tokens', name)

    def test_reasoning_families_are_detected_by_name(self):
        for name in ('gpt-5.1', 'GPT-5', 'o1-preview', 'o3-mini',
                     'openai/gpt-5.1', 'openai/o4-mini'):
            rp = ResolvedProvider(provider='openai', model=name)
            self.assertEqual(_token_param_for(rp), 'max_completion_tokens', name)

    def test_azure_deployment_alias_is_learned_from_the_error(self):
        """An Azure deployment can be named anything, so the name tells us
        nothing — the provider's own 400 has to teach us."""
        rp = ResolvedProvider(provider='azure_openai', model='my-deployment',
                              max_tokens=1234)
        self.assertEqual(_token_param_for(rp), 'max_tokens')

        client = _FakeClient(errors=[Exception(UNSUPPORTED)])
        _openai_create(client, rp, {'model': rp.model, 'messages': []})

        first, second = client.completions.calls
        self.assertEqual(first.get('max_tokens'), 1234)
        self.assertNotIn('max_completion_tokens', first)
        self.assertEqual(second.get('max_completion_tokens'), 1234)
        self.assertNotIn('max_tokens', second)

    def test_the_correction_is_remembered_so_we_pay_it_once(self):
        rp = ResolvedProvider(provider='azure_openai', model='my-deployment',
                              max_tokens=50)
        first = _FakeClient(errors=[Exception(UNSUPPORTED)])
        _openai_create(first, rp, {'model': rp.model, 'messages': []})
        self.assertEqual(len(first.completions.calls), 2)

        second = _FakeClient()
        _openai_create(second, rp, {'model': rp.model, 'messages': []})
        self.assertEqual(len(second.completions.calls), 1)
        self.assertEqual(second.completions.calls[0].get('max_completion_tokens'), 50)

    def test_a_reasoning_model_that_wants_the_old_name_is_corrected_too(self):
        rp = ResolvedProvider(provider='openai', model='gpt-5-legacy-proxy',
                              max_tokens=7)
        err = Exception("Unsupported parameter: 'max_completion_tokens' is not "
                        "supported. Use 'max_tokens' instead.")
        client = _FakeClient(errors=[err])
        _openai_create(client, rp, {'model': rp.model, 'messages': []})

        first, second = client.completions.calls
        self.assertEqual(first.get('max_completion_tokens'), 7)
        self.assertEqual(second.get('max_tokens'), 7)

    def test_unrelated_errors_are_not_retried(self):
        rp = ResolvedProvider(provider='openai', model='gpt-4o')
        client = _FakeClient(errors=[Exception('Error code: 401 - invalid api key')])
        with self.assertRaises(Exception) as ctx:
            _openai_create(client, rp, {'model': rp.model, 'messages': []})
        self.assertIn('401', str(ctx.exception))
        self.assertEqual(len(client.completions.calls), 1)

    def test_a_rate_limit_naming_max_tokens_is_not_mistaken_for_the_swap(self):
        """429 bodies often mention token limits; that must not flip the param."""
        rp = ResolvedProvider(provider='openai', model='gpt-4o')
        err = Exception('Error code: 429 - Rate limit reached for max_tokens '
                        'per minute. Please retry later.')
        client = _FakeClient(errors=[err])
        with self.assertRaises(Exception):
            _openai_create(client, rp, {'model': rp.model, 'messages': []})
        self.assertEqual(len(client.completions.calls), 1)
        self.assertEqual(_token_param_for(rp), 'max_tokens')
