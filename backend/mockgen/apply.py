"""Writes an *approved* mock-test draft into the real quiz tables.

Nothing here runs until an admin has seen the preview and confirmed. Guarantees:

* **Atomic** — one transaction per apply; a half-written paper never exists.
* **Selective** — only the questions the admin left ticked are written.
* **Non-destructive by default** — a *modify* apply in ``append`` mode adds to
  the paper; even in ``replace`` mode it refuses to delete questions that
  students have already answered, because that would orphan their marks.
* **Tenant-safe** — every row carries the tenant of the acting admin, and
  nothing is written outside the mock test that was confirmed.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from quiz.admin_views import recompute_mock_total
from quiz.models import MockTest, MockTestAnswer, MockTestItem

from .models import MockTestGenerationJob

logger = logging.getLogger(__name__)


class ApplyError(Exception):
    """The draft cannot be written (nothing selected, paper gone, bad state)."""


def _keep(selection):
    """The item keys the admin left ticked.

    A *missing* key means "the admin didn't narrow this, write it all"; a key
    that is present but empty means "everything was unticked, write none of it".
    Collapsing the two would turn an empty selection into a full write — the
    exact opposite of what the admin asked for.
    """
    if not isinstance(selection, dict) or 'items' not in selection:
        return None
    values = selection.get('items')
    if not isinstance(values, (list, tuple, set)):
        return None
    return {str(value) for value in values}


def _selected_items(draft, selection):
    keep = _keep(selection)
    items = [
        item for item in (draft or {}).get('items') or []
        if item.get('include', True)
    ]
    if keep is not None:
        items = [item for item in items if str(item.get('key')) in keep]
    return items


def _decimal(value, default='0'):
    try:
        return Decimal(str(round(float(value), 2)))
    except (TypeError, ValueError):
        return Decimal(default)


def _item_fields(item, *, section_offset=0):
    """Map one draft question onto :class:`quiz.models.MockTestItem` columns."""
    item_type = item.get('item_type') or 'mcq'
    fields = {
        'item_type': item_type,
        'section': int(item.get('section') or 0) + section_offset,
        'question_text': item.get('question_text') or '',
        'question_html': '',
        'explanation': item.get('explanation') or '',
        'marks': _decimal(item.get('marks'), '1'),
        'negative_marks': _decimal(item.get('negative_marks')),
        # Reset every type-specific column, so an item whose type changed during
        # a refine can never keep a stale answer from its previous shape.
        'options': [],
        'numerical_answer': None,
        'numerical_tolerance': Decimal('0.01'),
        'max_words': None,
        'rubric': '',
        'model_answer': '',
        'allowed_languages': [],
        'starter_code': {},
        'coding_test_cases': [],
        'time_limit_ms': 3000,
        'memory_limit_mb': 256,
    }

    if item_type in ('mcq', 'mcq_multi'):
        fields['options'] = [
            {'text': option.get('text') or '', 'image': None,
             'is_correct': bool(option.get('is_correct'))}
            for option in item.get('options') or []
        ]
    elif item_type == 'numerical':
        fields['numerical_answer'] = _decimal(item.get('numerical_answer'))
        fields['numerical_tolerance'] = _decimal(item.get('numerical_tolerance'), '0.01')
    elif item_type == 'subjective':
        fields['max_words'] = item.get('max_words') or None
        fields['rubric'] = item.get('rubric') or ''
        fields['model_answer'] = item.get('model_answer') or ''
    elif item_type == 'coding':
        fields['allowed_languages'] = item.get('allowed_languages') or ['python']
        fields['starter_code'] = item.get('starter_code') or {}
        fields['coding_test_cases'] = item.get('coding_test_cases') or []
        fields['time_limit_ms'] = int(item.get('time_limit_ms') or 3000)
        fields['memory_limit_mb'] = int(item.get('memory_limit_mb') or 256)

    return fields


def _sections_payload(draft, items):
    """``MockTest.sections`` — the section list, annotated with what landed in it."""
    sections = (draft or {}).get('sections') or []
    counts = {}
    marks = {}
    for item in items:
        index = int(item.get('section') or 0)
        counts[index] = counts.get(index, 0) + 1
        marks[index] = marks.get(index, 0) + float(item.get('marks') or 0)
    payload = []
    for index, section in enumerate(sections):
        payload.append({
            'index': index,
            'name': section.get('name') or f'Section {index + 1}',
            'description': section.get('description') or '',
            'questions_count': counts.get(index, 0),
            'marks': round(marks.get(index, 0), 2),
        })
    return payload


def _test_fields(draft, *, publish):
    test = (draft or {}).get('test') or {}
    fields = {
        'title': (test.get('title') or 'Untitled Mock Test')[:300],
        'description': test.get('description') or '',
        'duration_minutes': int(test.get('duration_minutes') or 60),
        'negative_marking': bool(test.get('negative_marking', True)),
        'is_free': bool(test.get('is_free', False)),
        'result_visibility': test.get('result_visibility') or 'immediate',
        'fullscreen_required': bool(test.get('fullscreen_required', True)),
        'max_attempts': int(test.get('max_attempts') or 1),
    }
    if publish:
        fields['status'] = 'published'
    return fields


# ─────────────────────────────────────────────────────────────────────────────
# Apply
# ─────────────────────────────────────────────────────────────────────────────

@transaction.atomic
def apply_draft(job, *, user=None, selection=None):
    """Write ``job.draft`` into a real mock test and mark the job applied."""
    if not job.is_reviewable:
        raise ApplyError('Only a draft awaiting review can be saved.')

    items = _selected_items(job.draft, selection or {})
    if not items:
        raise ApplyError('Nothing was selected to save.')

    options = job.options or {}
    publish = bool(options.get('publish_immediately'))

    if job.kind == MockTestGenerationJob.KIND_MODIFY:
        summary = _apply_modification(job, items, publish=publish, options=options)
    else:
        summary = _apply_new_paper(job, items, publish=publish)

    job.status = MockTestGenerationJob.STATUS_APPLIED
    job.applied_at = timezone.now()
    job.applied_by = user
    job.applied_summary = summary
    job.record_revision('applied', summary.get('title', ''))
    job.save()
    return summary


def _apply_new_paper(job, items, *, publish):
    tenant = job.tenant
    fields = _test_fields(job.draft, publish=publish)

    mock_test = MockTest.objects.create(
        tenant=tenant,
        total_marks=Decimal('0'),
        sections=_sections_payload(job.draft, items),
        status='published' if publish else 'draft',
        **{key: value for key, value in fields.items() if key != 'status'},
    )

    # Only courses the acting admin may actually build in, resolved against this
    # tenant so a stale id from the composer can never link another academy's
    # course into the paper.
    course_ids = [str(value) for value in (job.options or {}).get('course_ids') or []]
    if job.course_id and str(job.course_id) not in course_ids:
        course_ids.append(str(job.course_id))
    if course_ids:
        from exams.models import Course

        mock_test.courses.set(Course.objects.filter(id__in=course_ids, tenant=tenant))

    created = _write_items(mock_test, items, tenant=tenant, start_order=0)
    recompute_mock_total(mock_test)

    job.mock_test = mock_test
    return {
        'mock_test': str(mock_test.id),
        'title': mock_test.title,
        'created': created,
        'updated': 0,
        'removed': 0,
        'total_marks': float(mock_test.total_marks),
        'mode': 'created',
    }


def _apply_modification(job, items, *, publish, options):
    mock_test = job.mock_test
    if mock_test is None:
        raise ApplyError('The mock test this draft belongs to no longer exists.')

    mode = options.get('apply_mode') or 'replace'
    tenant = job.tenant or mock_test.tenant

    existing = {
        str(item.id): item
        for item in MockTestItem.objects.filter(mock_test=mock_test)
    }
    # Draft keys are stable across a refine, and a draft built from a saved
    # paper uses each row's id as its key — so a key that matches an existing
    # row means "update this question in place".
    answered_ids = set(
        MockTestAnswer.objects.filter(item__mock_test=mock_test)
        .values_list('item_id', flat=True)
    )
    answered_ids = {str(value) for value in answered_ids}

    created = updated = 0
    seen = set()
    order = 0
    for item in items:
        key = str(item.get('key') or '')
        fields = _item_fields(item)
        target = existing.get(key)
        if target is not None:
            seen.add(key)
            for name, value in fields.items():
                setattr(target, name, value)
            target.order = order
            target.save()
            updated += 1
        else:
            MockTestItem.objects.create(
                mock_test=mock_test, tenant=tenant, order=order, **fields
            )
            created += 1
        order += 1

    removed = 0
    if mode == 'replace':
        # A question a student has already answered is never deleted: their
        # marks reference it, and losing it would silently rewrite history.
        stale = [
            item_id for item_id in existing
            if item_id not in seen and item_id not in answered_ids
        ]
        if stale:
            removed, _ = MockTestItem.objects.filter(id__in=stale).delete()
            removed = len(stale)
        skipped = [item_id for item_id in existing if item_id not in seen and item_id in answered_ids]
        if skipped:
            logger.info(
                'mockgen: kept %d already-answered item(s) on mock test %s',
                len(skipped), mock_test.id,
            )

    if publish:
        mock_test.status = 'published'
    for name, value in _test_fields(job.draft, publish=publish).items():
        if name == 'status':
            continue
        setattr(mock_test, name, value)
    mock_test.sections = _sections_payload(job.draft, items)
    mock_test.save()
    recompute_mock_total(mock_test)

    return {
        'mock_test': str(mock_test.id),
        'title': mock_test.title,
        'created': created,
        'updated': updated,
        'removed': removed,
        'total_marks': float(mock_test.total_marks),
        'mode': mode,
    }


def _write_items(mock_test, items, *, tenant, start_order=0):
    for index, item in enumerate(items):
        MockTestItem.objects.create(
            mock_test=mock_test, tenant=tenant, order=start_order + index,
            **_item_fields(item),
        )
    return len(items)


# ─────────────────────────────────────────────────────────────────────────────
# The other direction: a saved paper as a draft
# ─────────────────────────────────────────────────────────────────────────────

def draft_from_mock_test(mock_test):
    """Render a saved mock test in the draft shape.

    This is what makes "Modify with AI" work on *any* paper, including one that
    was typed by hand: the model is handed the same JSON it would have produced
    itself. Each item's key is its database id, so applying the revision updates
    the original rows instead of duplicating them.
    """
    sections = []
    for index, section in enumerate(mock_test.sections or []):
        if isinstance(section, dict):
            sections.append({
                'index': index,
                'name': section.get('name') or f'Section {index + 1}',
                'description': section.get('description') or '',
            })

    items = []
    rows = MockTestItem.objects.filter(mock_test=mock_test).order_by('section', 'order')
    for order, row in enumerate(rows):
        item = {
            'key': str(row.id),
            'item_type': row.item_type,
            'section': row.section,
            'question_text': row.question_text or '',
            'explanation': row.explanation or '',
            'marks': float(row.marks),
            'negative_marks': float(row.negative_marks),
            'difficulty': 'medium',
            'concept': '',
            'options': [],
            'order': order,
            'include': True,
        }
        if row.item_type in ('mcq', 'mcq_multi'):
            item['options'] = [
                {'text': option.get('text') or '', 'is_correct': bool(option.get('is_correct'))}
                for option in row.options or []
            ]
        elif row.item_type == 'numerical':
            item['numerical_answer'] = float(row.numerical_answer or 0)
            item['numerical_tolerance'] = float(row.numerical_tolerance or 0.01)
        elif row.item_type == 'subjective':
            item['max_words'] = row.max_words
            item['rubric'] = row.rubric or ''
            item['model_answer'] = row.model_answer or ''
        elif row.item_type == 'coding':
            item['allowed_languages'] = row.allowed_languages or ['python']
            item['starter_code'] = row.starter_code or {}
            item['coding_test_cases'] = row.coding_test_cases or []
            item['time_limit_ms'] = row.time_limit_ms
            item['memory_limit_mb'] = row.memory_limit_mb
        items.append(item)

    if not sections and items:
        sections = [{'index': 0, 'name': 'Section 1', 'description': ''}]

    from .schema import mock_stats

    return {
        'test': {
            'title': mock_test.title,
            'description': mock_test.description or '',
            'duration_minutes': mock_test.duration_minutes,
            'negative_marking': bool(mock_test.negative_marking),
            'is_free': bool(mock_test.is_free),
            'result_visibility': mock_test.result_visibility,
            'fullscreen_required': bool(mock_test.fullscreen_required),
            'max_attempts': mock_test.max_attempts,
        },
        'sections': sections,
        'items': items,
        'stats': mock_stats(items, sections),
    }
