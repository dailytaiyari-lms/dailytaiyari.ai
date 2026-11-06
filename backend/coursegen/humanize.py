"""Send a draft's prose through the optional humanizer service.

The service lives in the top-level ``humanizer/`` folder and owns the model. This
module only decides which draft fields are prose, posts them, and writes back what
returns. Any failure keeps the generated text, so a job never fails because of it.
"""
from __future__ import annotations

import logging
import time

import requests
from django.conf import settings

from .notehtml import estimate_reading_minutes, render_blocks

logger = logging.getLogger(__name__)

# These mirror the limits in schema.py, so a longer rewrite can't be clipped later.
NOTE_TEXT_LIMIT = 4000
LIST_ITEM_LIMIT = 500
TOPIC_SUMMARY_LIMIT = 800
SECTION_DESCRIPTION_LIMIT = 1500
OUTLINE_DESCRIPTION_LIMIT = 4000
META_DESCRIPTION_LIMIT = 6000

CONNECT_TIMEOUT_S = 5

_PROSE_BLOCKS = ('lead', 'paragraph', 'callout', 'quote')
_LIST_BLOCKS = ('bullets', 'numbers')


def _block_fields(blocks):
    for block in blocks or []:
        kind = block.get('type')
        if kind in _PROSE_BLOCKS:
            yield block, 'text', NOTE_TEXT_LIMIT
        elif kind in _LIST_BLOCKS:
            items = block.get('items') or []
            for index in range(len(items)):
                yield items, index, LIST_ITEM_LIMIT


def _outline_fields(draft):
    yield draft.get('course') or {}, 'description', OUTLINE_DESCRIPTION_LIMIT
    for subject in draft.get('subjects') or []:
        yield subject, 'description', SECTION_DESCRIPTION_LIMIT
        for chapter in subject.get('chapters') or []:
            yield chapter, 'description', SECTION_DESCRIPTION_LIMIT
            for topic in chapter.get('topics') or []:
                yield topic, 'summary', TOPIC_SUMMARY_LIMIT


def _content_fields(draft):
    for topic in draft.get('topics') or []:
        yield from _block_fields((topic.get('note') or {}).get('blocks'))


def _meta_fields(draft):
    course = draft.get('course') or {}
    yield course, 'description', META_DESCRIPTION_LIMIT
    yield from _block_fields(course.get('description_blocks'))


_FIELDS = {'outline': _outline_fields, 'content': _content_fields, 'meta': _meta_fields}


def _text_at(container, key):
    if isinstance(container, dict):
        return container.get(key)
    return container[key]


def _post(url, text):
    response = requests.post(
        f'{url.rstrip("/")}/humanize',
        json={'text': text},
        timeout=(CONNECT_TIMEOUT_S, settings.HUMANIZER_READ_TIMEOUT_S),
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get('text'), str):
        raise ValueError('unexpected humanizer response')
    return (
        payload['text'],
        int(payload.get('sentences_total') or 0),
        int(payload.get('sentences_rewritten') or 0),
    )


def _rerender(kind, draft):
    if kind == 'content':
        for topic in draft.get('topics') or []:
            note = topic.get('note') or {}
            if note.get('blocks'):
                note['html'] = render_blocks(note['blocks'])
                note['estimated_time_minutes'] = estimate_reading_minutes(note['blocks'])
    elif kind == 'meta':
        course = draft.get('course') or {}
        if course.get('description_blocks'):
            course['description_html'] = render_blocks(course['description_blocks'])


def humanize_draft(kind, draft, *, previous=None, time_budget_s):
    """Rewrite ``draft``'s prose in place and return it; see the module docstring."""
    url = settings.HUMANIZER_URL
    fields = _FIELDS.get(kind)
    if not url or fields is None:
        return draft

    already_done = set()
    if previous:
        already_done = {_text_at(c, k) for c, k, _limit in fields(previous)}

    deadline = time.monotonic() + time_budget_s
    total = rewritten = skipped = succeeded = 0
    unreachable = False

    for container, key, limit in fields(draft):
        text = _text_at(container, key)
        if not text or text in already_done:
            continue
        if unreachable or time.monotonic() >= deadline:
            skipped += 1
            continue
        try:
            rewrite, sentences_total, sentences_rewritten = _post(url, text)
        except (requests.RequestException, ValueError, TypeError) as exc:
            logger.warning('humanizer: keeping generated text (%s)', exc)
            unreachable = True
            skipped += 1
            continue

        succeeded += 1
        total += sentences_total
        if len(rewrite) > limit:
            skipped += 1
            continue
        container[key] = rewrite
        rewritten += sentences_rewritten

    if unreachable and not succeeded:
        status = 'failed'
    elif skipped:
        status = 'partial'
    else:
        status = 'complete'

    _rerender(kind, draft)
    draft['humanizer'] = {
        'status': status,
        'sentences_total': total,
        'sentences_rewritten': rewritten,
        'fields_skipped': skipped,
    }
    logger.info('humanizer: %s draft %s', kind, draft['humanizer'])
    return draft
