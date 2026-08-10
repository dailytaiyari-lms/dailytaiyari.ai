"""Turn an approved notebook draft into real Notebook + NotebookTest rows.

The only module in the AI Notebook Builder that writes to the notebook tables,
and only from an explicitly confirmed, still-in-``preview`` job. Idempotent:
re-applying the same job updates its notebook in place (matched by the job's
linked notebook, or by tenant+topic+title) instead of creating duplicates, and
rebuilds the tests to match the draft.
"""
from django.db import transaction
from django.utils import timezone

from ..models import Notebook, NotebookGenerationJob, NotebookTest
from .schema import draft_to_template


class ApplyError(Exception):
    """A draft could not be written (bad state or empty payload)."""


@transaction.atomic
def apply_draft(job, *, user, selection=None):
    """Create/update the notebook described by ``job.draft`` and its tests."""
    draft = job.draft or {}
    cells = draft.get('cells') or []
    if not cells:
        raise ApplyError('This draft has no cells to apply.')

    template = draft_to_template(draft)
    packages = draft.get('packages') or []
    title = (draft.get('title') or 'Untitled notebook').strip()
    status = 'published' if (job.options or {}).get('publish', True) else 'draft'

    fields = dict(
        course=job.course,
        subject=job.subject,
        template_json=template,
        description=draft.get('description') or '',
        difficulty=draft.get('difficulty') or 'easy',
        packages=packages,
        max_marks=draft.get('max_marks') or None,
        estimated_time_minutes=draft.get('estimated_time_minutes') or 30,
        status=status,
    )

    notebook = job.notebook
    if notebook is None:
        notebook = Notebook.objects.filter(
            tenant=job.tenant, topic=job.topic, title=title,
        ).first()

    created = notebook is None
    if created:
        notebook = Notebook.objects.create(
            tenant=job.tenant, topic=job.topic, title=title, **fields,
        )
    else:
        notebook.title = title
        for key, value in fields.items():
            setattr(notebook, key, value)
        notebook.save()

    # Rebuild tests to match the draft exactly (match by name within notebook).
    kept = set()
    for order, test in enumerate(draft.get('tests') or []):
        name = (test.get('name') or 'Check')[:300]
        kept.add(name)
        NotebookTest.objects.update_or_create(
            notebook=notebook, name=name,
            defaults=dict(
                grade_id=test.get('grade_id') or '',
                source=test.get('source') or '',
                points=int(test.get('points') or 1),
                is_hidden=bool(test.get('is_hidden', True)),
                failure_hint=(test.get('failure_hint') or '')[:500],
                order=order,
            ),
        )
    notebook.tests.exclude(name__in=kept).delete()

    summary = {
        'notebook_id': str(notebook.id),
        'created': created,
        'title': notebook.title,
        'cells': len(template.get('cells') or []),
        'tests': notebook.tests.count(),
        'total_points': notebook.total_points(),
        'status': notebook.status,
    }

    job.notebook = notebook
    job.status = NotebookGenerationJob.STATUS_APPLIED
    job.applied_at = timezone.now()
    job.applied_by = user
    job.applied_summary = summary
    job.record_revision('applied', notebook.title)
    job.save()
    return summary
