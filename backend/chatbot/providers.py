"""Unified LLM client for every supported provider.

The platform is "bring your own key": each tenant configures an
:class:`~chatbot.models.AIProviderConfig` and every AI answer is produced through
that provider. Almost all supported providers (OpenAI, Azure OpenAI, Gemini's
compatibility endpoint, Groq, OpenRouter, Together, Ollama, any vLLM/LM Studio
server) speak the OpenAI chat-completions protocol, so they share a single code
path and differ only by ``base_url``/auth. Anthropic uses its native Messages
API and is implemented over plain HTTP so no extra dependency is required.

Everything here is provider-agnostic in and out:

* :func:`complete` → ``{'content', 'model', 'prompt_tokens', ...}``
* :func:`stream`   → yields ``(delta_text, usage_or_none)`` and finally the usage

Callers should go through :mod:`chatbot.resolver`, which picks the right config
for a tenant and meters the result.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field

import requests
from django.conf import settings

from .models import AIProviderConfig

logger = logging.getLogger(__name__)

# Network guard rails. Streaming answers can legitimately take a while, but a
# hung provider must never pin a worker forever.
CONNECT_TIMEOUT = 10

# The web timeout MUST stay below gunicorn's ``timeout`` (see gunicorn.conf.py).
# If the provider is allowed to run as long as gunicorn waits, gunicorn kills the
# worker first and the caller gets a dead connection instead of a readable "the
# model took too long" message. Some free/large models genuinely take ~100s for
# even a short reply, so this fires in practice.
READ_TIMEOUT = getattr(settings, 'AI_READ_TIMEOUT', 90)

# Celery tasks are not bound by gunicorn, so long-form generation (a course
# outline, a full mock paper, a hackathon brief) may wait far longer.
BACKGROUND_READ_TIMEOUT = getattr(settings, 'AI_READ_TIMEOUT_BACKGROUND', 600)


def in_background_worker():
    """True when the current call runs inside a Celery task, not a web request.

    Timeouts differ by an order of magnitude between the two, and threading a
    flag through every generation module would touch a dozen call sites for no
    behavioural gain, so the context is detected once here.
    """
    try:
        from celery import current_task
    except ImportError:  # pragma: no cover - celery is pinned
        return False
    request = getattr(current_task, 'request', None)
    return getattr(request, 'id', None) is not None


def read_timeout():
    """Seconds to wait for a provider response in the current context."""
    return BACKGROUND_READ_TIMEOUT if in_background_worker() else READ_TIMEOUT


class AIProviderError(RuntimeError):
    """Raised when a provider call fails in a way worth showing an admin."""


@dataclass
class ResolvedProvider:
    """A ready-to-call provider, decoupled from the DB row it came from.

    Using a plain dataclass means the platform fallback (which has no
    ``AIProviderConfig`` row) and a tenant's own config share one call path.
    """

    provider: str
    api_key: str = ''
    base_url: str = ''
    model: str = ''
    api_version: str = '2024-10-21'
    temperature: float = 0.7
    max_tokens: int = 2000
    # 'tenant' or 'platform' — only used for metering/reporting.
    source: str = 'tenant'
    extra_headers: dict = field(default_factory=dict)
    # The PlatformAIModel row behind this call, when the platform is paying.
    # Carried so metering can attribute cost at the exact price we're charged.
    platform_model: object = None

    @classmethod
    def from_platform_model(cls, platform_model, *, max_tokens=None, temperature=0.7):
        """Build a callable provider from a super-admin-registered model."""
        account = platform_model.provider
        return cls(
            provider=account.provider,
            api_key=account.api_key,
            base_url=account.effective_base_url,
            model=platform_model.model_name,
            api_version=account.api_version or '2024-10-21',
            temperature=temperature,
            max_tokens=max_tokens or platform_model.max_output_tokens or 2000,
            source='platform',
            platform_model=platform_model,
        )

    @classmethod
    def from_config(cls, config: AIProviderConfig, source: str = 'tenant') -> 'ResolvedProvider':
        return cls(
            provider=config.provider,
            api_key=config.api_key,
            base_url=config.effective_base_url,
            model=config.effective_model,
            api_version=config.api_version or '2024-10-21',
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            source=source,
        )


@dataclass
class Usage:
    """Token accounting for one call (zeros when a provider omits it)."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    @classmethod
    def from_openai(cls, usage) -> 'Usage':
        if not usage:
            return cls()
        prompt = getattr(usage, 'prompt_tokens', 0) or 0
        completion = getattr(usage, 'completion_tokens', 0) or 0
        return cls(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=(getattr(usage, 'total_tokens', 0) or 0) or (prompt + completion),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Cost estimation
# ─────────────────────────────────────────────────────────────────────────────

# USD per 1M tokens (input, output). Deliberately coarse — it exists so admins
# see a ballpark spend, not an invoice. Unknown models fall back to 0 (which is
# also correct for self-hosted and ``:free`` models).
_PRICE_PER_MILLION = {
    'gpt-4o': (2.50, 10.00),
    'gpt-4o-mini': (0.15, 0.60),
    'gpt-4.1': (2.00, 8.00),
    'gpt-4.1-mini': (0.40, 1.60),
    'gpt-4.1-nano': (0.10, 0.40),
    'o4-mini': (1.10, 4.40),
    'gemini-2.0-flash': (0.10, 0.40),
    'gemini-2.5-flash': (0.30, 2.50),
    'gemini-2.5-pro': (1.25, 10.00),
    'claude-3-5-haiku': (0.80, 4.00),
    'claude-3-7-sonnet': (3.00, 15.00),
    'claude-sonnet-4': (3.00, 15.00),
    'llama-3.3-70b': (0.59, 0.79),
}


def estimate_cost_usd(model: str, usage: Usage, platform_model=None) -> float:
    """Best-effort USD estimate for one call; 0 when the model isn't priced.

    ``platform_model`` is a :class:`~chatbot.models.PlatformAIModel` whose prices
    the super admin maintains. When present it wins over the built-in table,
    because it is the number the platform is actually invoiced.
    """
    if not usage.total_tokens:
        return 0.0
    if platform_model is not None:
        inp = float(platform_model.input_cost_per_million or 0)
        out = float(platform_model.output_cost_per_million or 0)
        if inp or out:
            return round(
                (usage.prompt_tokens * inp + usage.completion_tokens * out) / 1_000_000, 6
            )
        return 0.0
    if not model:
        return 0.0
    key = model.lower()
    if key.endswith(':free'):
        return 0.0
    for name, (inp, out) in _PRICE_PER_MILLION.items():
        if name in key:
            return round(
                (usage.prompt_tokens * inp + usage.completion_tokens * out) / 1_000_000, 6
            )
    return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# OpenAI-compatible path
# ─────────────────────────────────────────────────────────────────────────────

def _openai_client(rp: ResolvedProvider):
    """Build an OpenAI SDK client pointed at whichever endpoint ``rp`` names."""
    try:
        from openai import AzureOpenAI, OpenAI
    except ImportError as exc:  # pragma: no cover - dependency is pinned
        raise AIProviderError('The openai package is not installed on the server.') from exc

    if rp.provider == AIProviderConfig.PROVIDER_AZURE:
        if not rp.base_url:
            raise AIProviderError('Azure OpenAI needs the resource endpoint URL.')
        return AzureOpenAI(
            api_key=rp.api_key,
            azure_endpoint=rp.base_url.rstrip('/'),
            api_version=rp.api_version,
            timeout=read_timeout(),
            max_retries=1,
        )

    kwargs = {
        # Self-hosted servers usually ignore the key but the SDK requires one.
        'api_key': rp.api_key or 'not-needed',
        'timeout': read_timeout(),
        'max_retries': 1,
    }
    if rp.base_url:
        kwargs['base_url'] = rp.base_url
    if rp.extra_headers:
        kwargs['default_headers'] = rp.extra_headers
    return OpenAI(**kwargs)


def _error_detail(payload):
    """Human-readable message from a provider's ``error`` field, if any."""
    if payload is None:
        return ''
    if isinstance(payload, dict):
        message = payload.get('message') or ''
        code = payload.get('code') or ''
        meta = payload.get('metadata') or {}
        # OpenRouter nests the upstream provider's own text under metadata.
        if not message and isinstance(meta, dict):
            message = meta.get('raw') or ''
        if message and code:
            return f'{message} (code {code})'
        return str(message or code or '')
    message = getattr(payload, 'message', '') or ''
    code = getattr(payload, 'code', '') or ''
    if message and code:
        return f'{message} (code {code})'
    return str(message or code or '')


def _response_error(response):
    """The ``error`` object on an OpenAI-shaped response, wherever it landed.

    Aggregators return HTTP 200 with a bare ``{"error": {...}}`` body. The SDK
    parses that into a ChatCompletion whose declared fields are all empty, so
    the error is only reachable via the pydantic extras.
    """
    err = getattr(response, 'error', None)
    if err is None:
        extra = getattr(response, 'model_extra', None)
        if isinstance(extra, dict):
            err = extra.get('error')
    return err


def _openai_content(response):
    """Text of the first choice, or a clear :class:`AIProviderError`.

    A provider that fronts other vendors (OpenRouter especially) can answer
    HTTP 200 with **no choices at all** when the upstream model is rate
    limited, overloaded or moderated. Indexing ``choices[0]`` then raised
    ``'NoneType' object is not subscriptable``, which was stored verbatim on
    the usage record and shown to tenant admins.
    """
    choices = getattr(response, 'choices', None)
    if not choices:
        detail = _error_detail(_response_error(response))
        if detail:
            raise AIProviderError(f'The AI provider rejected the request: {detail[:300]}')
        raise AIProviderError(
            'The AI provider returned an empty response. This usually means the '
            'model was rate limited or temporarily overloaded — try again, or '
            'pick a different model.'
        )

    choice = choices[0]
    message = getattr(choice, 'message', None)
    content = getattr(message, 'content', None) if message is not None else None
    if content:
        return content

    # A choice with no text still carries the reason it stopped, which is far
    # more actionable than an empty answer.
    reason = getattr(choice, 'finish_reason', '') or ''
    if reason == 'length':
        raise AIProviderError(
            'The model hit its output limit before producing any text. Raise '
            'the max tokens for this provider, or use a shorter prompt.'
        )
    if reason == 'content_filter':
        raise AIProviderError(
            "The model's safety filter blocked this response. Rephrase the "
            'request and try again.'
        )
    detail = _error_detail(_response_error(response))
    if detail:
        raise AIProviderError(f'The AI provider rejected the request: {detail[:300]}')
    return ''


def _openai_complete(rp: ResolvedProvider, messages):
    client = _openai_client(rp)
    response = client.chat.completions.create(
        model=rp.model,
        messages=messages,
        max_tokens=rp.max_tokens,
        temperature=rp.temperature,
    )
    return _openai_content(response), Usage.from_openai(response.usage)


def _openai_stream(rp: ResolvedProvider, messages):
    client = _openai_client(rp)
    kwargs = {
        'model': rp.model,
        'messages': messages,
        'max_tokens': rp.max_tokens,
        'temperature': rp.temperature,
        'stream': True,
    }
    # Ask for usage in the final chunk where the provider supports it; servers
    # that reject the option (some self-hosted ones) are retried without it.
    try:
        stream = client.chat.completions.create(stream_options={'include_usage': True}, **kwargs)
    except Exception:  # noqa: BLE001 - fall back to a plain stream
        stream = client.chat.completions.create(**kwargs)

    usage = Usage()
    produced = False
    stream_error = ''
    for chunk in stream:
        if getattr(chunk, 'usage', None):
            usage = Usage.from_openai(chunk.usage)
        # An error can arrive mid-stream instead of as a failed request.
        detail = _error_detail(_response_error(chunk))
        if detail:
            stream_error = detail
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        text = getattr(delta, 'content', None)
        if text:
            produced = True
            yield text, None

    # A stream that ends without a single token is a failure, not a blank
    # answer: surfacing it stops the UI showing an empty bubble as success.
    if not produced:
        if stream_error:
            raise AIProviderError(
                f'The AI provider rejected the request: {stream_error[:300]}'
            )
        raise AIProviderError(
            'The AI provider returned an empty response. This usually means the '
            'model was rate limited or temporarily overloaded — try again, or '
            'pick a different model.'
        )
    yield '', usage


# ─────────────────────────────────────────────────────────────────────────────
# Anthropic path (native Messages API over HTTP)
# ─────────────────────────────────────────────────────────────────────────────

def _anthropic_payload(rp: ResolvedProvider, messages):
    """Split OpenAI-style messages into Anthropic's system + turns shape."""
    system_parts = [m['content'] for m in messages if m['role'] == 'system']
    turns = [
        {'role': 'assistant' if m['role'] == 'assistant' else 'user', 'content': m['content']}
        for m in messages
        if m['role'] in ('user', 'assistant')
    ]
    payload = {
        'model': rp.model,
        'max_tokens': rp.max_tokens,
        'temperature': rp.temperature,
        'messages': turns,
    }
    if system_parts:
        payload['system'] = '\n\n'.join(system_parts)
    return payload


def _anthropic_headers(rp: ResolvedProvider):
    return {
        'x-api-key': rp.api_key,
        'anthropic-version': '2023-06-01',
        'content-type': 'application/json',
    }


def _anthropic_url(rp: ResolvedProvider):
    base = (rp.base_url or 'https://api.anthropic.com').rstrip('/')
    return f'{base}/v1/messages'


def _raise_for_http(response):
    if response.status_code >= 400:
        try:
            detail = response.json().get('error', {}).get('message') or response.text
        except ValueError:
            detail = response.text
        raise AIProviderError(f'Provider returned {response.status_code}: {detail[:300]}')


def _anthropic_complete(rp: ResolvedProvider, messages):
    response = requests.post(
        _anthropic_url(rp),
        headers=_anthropic_headers(rp),
        json=_anthropic_payload(rp, messages),
        timeout=(CONNECT_TIMEOUT, read_timeout()),
    )
    _raise_for_http(response)
    data = response.json()
    text = ''.join(block.get('text', '') for block in data.get('content', []))
    raw = data.get('usage') or {}
    usage = Usage(
        prompt_tokens=raw.get('input_tokens', 0),
        completion_tokens=raw.get('output_tokens', 0),
        total_tokens=raw.get('input_tokens', 0) + raw.get('output_tokens', 0),
    )
    return text, usage


def _anthropic_stream(rp: ResolvedProvider, messages):
    payload = {**_anthropic_payload(rp, messages), 'stream': True}
    with requests.post(
        _anthropic_url(rp),
        headers=_anthropic_headers(rp),
        json=payload,
        stream=True,
        timeout=(CONNECT_TIMEOUT, read_timeout()),
    ) as response:
        _raise_for_http(response)
        usage = Usage()
        for line in response.iter_lines(decode_unicode=True):
            if not line or not line.startswith('data:'):
                continue
            raw = line[5:].strip()
            if not raw or raw == '[DONE]':
                continue
            try:
                event = json.loads(raw)
            except ValueError:
                continue
            etype = event.get('type')
            if etype == 'content_block_delta':
                text = (event.get('delta') or {}).get('text')
                if text:
                    yield text, None
            elif etype == 'message_start':
                started = ((event.get('message') or {}).get('usage')) or {}
                usage.prompt_tokens = started.get('input_tokens', 0)
            elif etype == 'message_delta':
                usage.completion_tokens = (event.get('usage') or {}).get('output_tokens', 0)
        usage.total_tokens = usage.prompt_tokens + usage.completion_tokens
        yield '', usage


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def _normalise_error(rp: ResolvedProvider, exc: Exception) -> AIProviderError:
    """Turn any SDK/HTTP exception into a message worth showing an admin."""
    if isinstance(exc, requests.exceptions.Timeout) or 'timeout' in type(exc).__name__.lower():
        waited = read_timeout()
        return AIProviderError(
            f'The model "{rp.model}" did not respond within {waited}s. Large '
            'free-tier models are often this slow — pick a faster model, or '
            'connect your own provider key.'
        )
    return AIProviderError(str(exc)[:300])


def complete(rp: ResolvedProvider, messages):
    """Run a non-streaming completion.

    Returns ``(content, usage, elapsed_ms)``. Raises :class:`AIProviderError`
    with a message safe to surface to a tenant admin.
    """
    started = time.time()
    try:
        if rp.provider == AIProviderConfig.PROVIDER_ANTHROPIC:
            content, usage = _anthropic_complete(rp, messages)
        else:
            content, usage = _openai_complete(rp, messages)
    except AIProviderError:
        raise
    except Exception as exc:  # noqa: BLE001 - normalise every SDK's errors
        logger.warning('AI provider %s failed: %s', rp.provider, exc)
        raise _normalise_error(rp, exc) from exc
    return content, usage, int((time.time() - started) * 1000)


def stream(rp: ResolvedProvider, messages):
    """Stream a completion, yielding ``(delta_text, usage_or_none)``.

    The final yield always carries the usage (possibly all zeros) and an empty
    delta, so callers can meter the call once the stream drains.
    """
    try:
        generator = (
            _anthropic_stream(rp, messages)
            if rp.provider == AIProviderConfig.PROVIDER_ANTHROPIC
            else _openai_stream(rp, messages)
        )
        for delta, usage in generator:
            yield delta, usage
    except AIProviderError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning('AI provider %s stream failed: %s', rp.provider, exc)
        raise _normalise_error(rp, exc) from exc


def test_connection(rp: ResolvedProvider):
    """Send a tiny prompt to verify credentials. Returns ``(ok, message)``."""
    probe = ResolvedProvider(
        provider=rp.provider,
        api_key=rp.api_key,
        base_url=rp.base_url,
        model=rp.model,
        api_version=rp.api_version,
        temperature=0,
        max_tokens=16,
        source=rp.source,
    )
    messages = [
        {'role': 'system', 'content': 'Reply with the single word: ok'},
        {'role': 'user', 'content': 'ping'},
    ]
    try:
        content, _usage, elapsed = complete(probe, messages)
    except AIProviderError as exc:
        return False, str(exc)
    if not content.strip():
        return False, 'The provider responded but returned no text.'
    return True, f'Connected in {elapsed} ms — model replied "{content.strip()[:40]}".'
