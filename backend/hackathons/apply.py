"""The only module that writes an AI draft into the hackathon tables.

Every write is a single transaction and needs an explicit admin confirmation
upstream (:class:`hackathons.ai_views.JobApplyView`). Nothing is destructive by
default: applying a stage plan appends rounds, applying questions appends items,
and applying an event brief creates a hackathon in ``draft`` status which the
admin still has to publish.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import Hackathon, HackathonStage, HackathonStageItem

logger = logging.getLogger(__name__)


class ApplyError(Exception):
    """A draft could not be written — always with a message fit for an admin."""


def _selected(entries, selection, bucket):
    """Honour the reviewer's tick-boxes; no selection means "everything included"."""
    keys = (selection or {}).get(bucket)
    if keys is None:
        return [entry for entry in entries if entry.get('include', True)]
    wanted = {str(key) for key in keys}
    return [entry for entry in entries if str(entry.get('key')) in wanted]


def _dec(value, default='0'):
    try:
        return Decimal(str(value if value is not None else default))
    except Exception:  # noqa: BLE001
        return Decimal(default)


def _create_stage(hackathon, data, order):
    stage = HackathonStage.objects.create(
        tenant=hackathon.tenant,
        hackathon=hackathon,
        order=order,
        title=data.get('title') or f'Round {order + 1}',
        description=data.get('description') or '',
        instructions=data.get('instructions') or '',
        stage_type=data.get('stage_type') or 'quiz',
        duration_minutes=data.get('duration_minutes') or 0,
        max_score=_dec(data.get('max_score'), '100'),
        qualification_mode=data.get('qualification_mode') or 'manual',
        cutoff_score=(
            _dec(data['cutoff_score']) if data.get('cutoff_score') is not None else None
        ),
        top_n=data.get('top_n') or None,
        submission_instructions=data.get('submission_instructions') or '',
        allowed_file_types=data.get('allowed_file_types') or [],
        require_repo_url=bool(data.get('require_repo_url')),
        require_demo_url=bool(data.get('require_demo_url')),
        require_video_url=bool(data.get('require_video_url')),
        status='draft',
    )
    return stage


def _create_item(stage, data, order):
    return HackathonStageItem(
        tenant=stage.hackathon.tenant,
        stage=stage,
        order=order,
        item_type=data.get('item_type') or 'mcq',
        title=data.get('title') or '',
        question_text=data.get('question_text') or '',
        explanation=data.get('explanation') or '',
        difficulty=data.get('difficulty') or '',
        marks=_dec(data.get('marks'), '1'),
        negative_marks=_dec(data.get('negative_marks'), '0'),
        options=data.get('options') or [],
        numerical_answer=(
            _dec(data['numerical_answer'])
            if data.get('numerical_answer') is not None else None
        ),
        numerical_tolerance=_dec(data.get('numerical_tolerance'), '0.01'),
        max_words=data.get('max_words') or None,
        rubric=data.get('rubric') or '',
        model_answer=data.get('model_answer') or '',
        allowed_languages=data.get('allowed_languages') or [],
        starter_code=data.get('starter_code') or {},
        time_limit_ms=data.get('time_limit_ms') or 3000,
        memory_limit_mb=data.get('memory_limit_mb') or 256,
        coding_test_cases=data.get('coding_test_cases') or [],
    )


@transaction.atomic
def apply_draft(job, *, user, selection=None):
    """Write ``job.draft`` and mark the job applied. Returns a summary dict."""
    draft = job.draft or {}
    if not draft:
        raise ApplyError('This job has no draft to apply.')

    kind = draft.get('kind') or job.kind
    if kind == 'event':
        summary = _apply_event(job, draft, selection, user)
    elif kind == 'stages':
        summary = _apply_stages(job, draft, selection)
    elif kind == 'stage_content':
        summary = _apply_items(job, draft, selection)
    else:
        raise ApplyError(f'Unknown draft type "{kind}".')

    job.status = 'applied'
    job.applied_at = timezone.now()
    job.applied_by = user
    job.applied_summary = summary
    job.log('applied', summary.get('message', ''))
    job.save(update_fields=[
        'status', 'applied_at', 'applied_by', 'applied_summary', 'revisions', 'updated_at',
    ])
    return summary


def _apply_event(job, draft, selection, user):
    data = draft.get('hackathon') or {}
    if not data.get('title'):
        raise ApplyError('The draft has no hackathon title.')

    hackathon = job.hackathon
    if hackathon is None:
        hackathon = Hackathon(tenant=job.tenant, created_by=user)
    for field in (
        'title', 'tagline', 'description', 'rules', 'prizes_description',
        'eligibility', 'difficulty', 'mode', 'theme_color',
    ):
        if data.get(field):
            setattr(hackathon, field, data[field])
    if data.get('faqs'):
        hackathon.faqs = data['faqs']
    if data.get('tags'):
        hackathon.tags = data['tags']
    if not hackathon.status:
        hackathon.status = 'draft'
    hackathon.save()
    job.hackathon = hackathon

    stages = _selected(draft.get('stages') or [], selection, 'stages')
    created = _write_stages(hackathon, stages)
    return {
        'hackathon_id': str(hackathon.id),
        'hackathon_title': hackathon.title,
        'stages_created': len(created),
        'message': (
            f'Created "{hackathon.title}"'
            + (f' with {len(created)} round(s)' if created else '')
            + '. It is saved as a draft — review and publish when ready.'
        ),
    }


def _apply_stages(job, draft, selection):
    hackathon = job.hackathon
    if hackathon is None:
        raise ApplyError('This job has no hackathon to add rounds to.')
    stages = _selected(draft.get('stages') or [], selection, 'stages')
    if not stages:
        raise ApplyError('No rounds were selected.')
    created = _write_stages(hackathon, stages)
    return {
        'hackathon_id': str(hackathon.id),
        'stages_created': len(created),
        'stage_ids': [str(stage.id) for stage in created],
        'message': f'Added {len(created)} round(s) to "{hackathon.title}".',
    }


def _write_stages(hackathon, stages):
    last = hackathon.stages.order_by('-order').first()
    next_order = (last.order + 1) if last else 0
    created = []
    for offset, data in enumerate(stages):
        created.append(_create_stage(hackathon, data, next_order + offset))
    return created


def _apply_items(job, draft, selection):
    stage = job.stage
    if stage is None:
        raise ApplyError('This job has no round to add questions to.')
    items = _selected(draft.get('items') or [], selection, 'items')
    if not items:
        raise ApplyError('No questions were selected.')

    last = stage.items.order_by('-order').first()
    next_order = (last.order + 1) if last else 0
    rows = [
        _create_item(stage, data, next_order + offset)
        for offset, data in enumerate(items)
    ]
    HackathonStageItem.objects.bulk_create(rows)

    # Keep the round's headline score honest once its questions exist.
    computed = stage.computed_max_score()
    if computed and stage.stage_type in ('quiz', 'coding'):
        stage.max_score = computed
        stage.save(update_fields=['max_score', 'updated_at'])

    return {
        'stage_id': str(stage.id),
        'stage_title': stage.title,
        'items_created': len(rows),
        'max_score': float(stage.max_score),
        'message': f'Added {len(rows)} question(s) to "{stage.title}".',
    }
