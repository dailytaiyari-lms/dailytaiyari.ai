"""Writes an *approved* draft into the real course tables.

Nothing here runs until an admin has seen the preview and confirmed. Guarantees:

* **Atomic** — one transaction per apply; a partial course never exists.
* **Idempotent by code** — every row is matched on its natural key
  (``(course, code)``, ``(subject, code)``, ``(topic, content_type)``…) and
  updated in place, so re-applying a draft after an edit tops up rather than
  duplicates.
* **Non-destructive** — existing quizzes that already have student attempts are
  left alone; the generated quiz is added alongside instead of replacing them.
* **Tenant-safe** — every created row carries the tenant of the acting admin,
  and nothing is written outside the course that was confirmed.
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from assignments.models import Assignment
from coding.models import CodingProblem, TestCase
from content.models import Content
from exams.models import Chapter, ChapterTopic, Course, Subject, Topic
from quiz.models import Question, QuestionOption, Quiz, QuizQuestion

from .notehtml import blocks_to_plain_text, render_blocks

logger = logging.getLogger(__name__)


def _tag_question(question, question_data, topic):
    """Concept-link a generated bank question (fail-safe — never fails apply)."""
    from intelligence.services.itemtags import set_item_tags

    label = question_data.get('concept')
    try:
        set_item_tags(
            question,
            concept_labels=[label] if label else [],
            subject=topic.subject,
            topic=topic,
            source='generator',
            difficulty=question_data.get('difficulty'),
            overwrite_difficulty=True,
        )
    except Exception:
        logger.exception('coursegen: failed to tag question %s at apply', question.id)


class ApplyError(Exception):
    """The draft cannot be written (bad references, quota, nothing selected)."""


def _keep(selection, key):
    """Read one bucket of the admin's tick-boxes.

    The distinction that matters: a *missing* key means "the admin didn't narrow
    this level, write it all", while a key that is present but empty means "the
    admin unticked everything here, write none of it". Collapsing the two would
    turn an empty selection into a full write — the exact opposite of what the
    admin asked for.
    """
    if not isinstance(selection, dict) or key not in selection:
        return None
    values = selection.get(key)
    if not isinstance(values, (list, tuple, set)):
        return None
    return {str(value) for value in values}


def _unique_course_code(base, tenant):
    """``Course.code`` is unique platform-wide, so disambiguate before saving."""
    code = slugify(base or '') or 'course'
    code = code[:50]
    candidate = code
    suffix = 2
    while Course.objects.filter(code=candidate).exists():
        tail = f'-{suffix}'
        candidate = f'{code[:50 - len(tail)]}{tail}'
        suffix += 1
    return candidate


def _unique_content_slug(title, instance=None):
    base = slugify(title or '') or 'content'
    base = base[:400]
    slug = base
    index = 1
    queryset = Content.objects.all()
    if instance is not None:
        queryset = queryset.exclude(pk=instance.pk)
    while queryset.filter(slug=slug).exists():
        index += 1
        slug = f'{base}-{index}'
    return slug


# ─────────────────────────────────────────────────────────────────────────────
# Outline
# ─────────────────────────────────────────────────────────────────────────────

@transaction.atomic
def apply_outline(job, *, selection=None):
    """Create/extend the course tree described by ``job.draft``.

    ``selection`` optionally narrows what is written to
    ``{'subjects': [code, …], 'chapters': [code, …], 'topics': [code, …]}`` —
    the codes the admin left ticked in the preview.
    """
    draft = job.draft or {}
    tenant = job.tenant
    course_data = draft.get('course') or {}
    subjects_data = draft.get('subjects') or []
    if not subjects_data:
        raise ApplyError('This draft has no subjects to create.')

    selection = selection or {}
    keep_subjects = _keep(selection, 'subjects')
    keep_chapters = _keep(selection, 'chapters')
    keep_topics = _keep(selection, 'topics')

    if keep_subjects == set() or keep_chapters == set() or keep_topics == set():
        raise ApplyError('Nothing was selected to apply.')

    created = {
        'course': None, 'subjects': 0, 'chapters': 0, 'topics': 0,
        'subjects_updated': 0, 'chapters_updated': 0, 'topics_updated': 0,
    }

    course = job.course
    if course is None:
        if tenant is not None and not tenant.can_add('courses'):
            raise ApplyError(
                'This academy has reached its course limit. Contact the '
                'DailyTaiyari team to add more.'
            )
        course = Course.objects.create(
            tenant=tenant,
            name=course_data.get('name') or 'Untitled course',
            code=_unique_course_code(course_data.get('code') or course_data.get('name'), tenant),
            description=course_data.get('description') or '',
            subtitle=course_data.get('subtitle') or '',
            course_type=course_data.get('course_type') or 'skill',
            highlights=course_data.get('highlights') or [],
            # A generated course starts hidden: the admin publishes it once they
            # are happy with the material inside.
            status='coming_soon',
        )
        created['course'] = str(course.id)
        job.course = course

    for subject_index, subject_data in enumerate(subjects_data):
        if keep_subjects is not None and subject_data.get('code') not in keep_subjects:
            continue
        subject, subject_created = Subject.objects.get_or_create(
            course=course,
            code=subject_data.get('code') or slugify(subject_data.get('name') or 'module'),
            defaults={
                'tenant': tenant,
                'name': subject_data.get('name') or 'Module',
                'description': subject_data.get('description') or '',
                'weightage': subject_data.get('weightage') or 0,
                'order': subject_data.get('order', subject_index),
            },
        )
        if subject_created:
            created['subjects'] += 1
        else:
            # Existing subject: only fill blanks, never clobber admin edits.
            changed = []
            if not subject.description and subject_data.get('description'):
                subject.description = subject_data['description']
                changed.append('description')
            if changed:
                subject.save(update_fields=changed)
                created['subjects_updated'] += 1

        for chapter_index, chapter_data in enumerate(subject_data.get('chapters') or []):
            if keep_chapters is not None and chapter_data.get('code') not in keep_chapters:
                continue
            chapter, chapter_created = Chapter.objects.get_or_create(
                subject=subject,
                code=chapter_data.get('code') or slugify(chapter_data.get('name') or 'chapter'),
                defaults={
                    'tenant': tenant,
                    'name': chapter_data.get('name') or 'Chapter',
                    'description': chapter_data.get('description') or '',
                    'estimated_hours': chapter_data.get('estimated_hours') or 2.0,
                    'order': chapter_data.get('order', chapter_index),
                },
            )
            if chapter_created:
                created['chapters'] += 1
            elif not chapter.description and chapter_data.get('description'):
                chapter.description = chapter_data['description']
                chapter.save(update_fields=['description'])
                created['chapters_updated'] += 1

            for topic_index, topic_data in enumerate(chapter_data.get('topics') or []):
                if keep_topics is not None and topic_data.get('code') not in keep_topics:
                    continue
                topic, topic_created = Topic.objects.get_or_create(
                    subject=subject,
                    code=topic_data.get('code') or slugify(topic_data.get('name') or 'topic'),
                    defaults={
                        'tenant': tenant,
                        'name': topic_data.get('name') or 'Topic',
                        'description': topic_data.get('summary') or '',
                        'difficulty': topic_data.get('difficulty') or 'medium',
                        'importance': topic_data.get('importance') or 'medium',
                        'estimated_study_hours': topic_data.get('estimated_study_hours') or 1.0,
                        'order': topic_data.get('order', topic_index),
                        'objectives': topic_data.get('objectives') or [],
                    },
                )
                if topic_created:
                    created['topics'] += 1
                else:
                    updates = []
                    if not topic.description and topic_data.get('summary'):
                        topic.description = topic_data['summary']
                        updates.append('description')
                    # Objectives were generated and validated but historically
                    # dropped on apply — persist them (without clobbering any
                    # an admin has already curated).
                    if not topic.objectives and topic_data.get('objectives'):
                        topic.objectives = topic_data['objectives']
                        updates.append('objectives')
                    if updates:
                        topic.save(update_fields=updates)
                        created['topics_updated'] += 1

                ChapterTopic.objects.get_or_create(
                    chapter=chapter,
                    topic=topic,
                    defaults={'tenant': tenant, 'order': topic_data.get('order', topic_index)},
                )

    if not any((created['subjects'], created['chapters'], created['topics'], created['course'])):
        raise ApplyError('Nothing new to create — every item in this draft already exists.')

    created['course_id'] = str(course.id)
    created['course_name'] = course.name
    return created


# ─────────────────────────────────────────────────────────────────────────────
# Topic content
# ─────────────────────────────────────────────────────────────────────────────

@transaction.atomic
def apply_content(job, *, selection=None):
    """Write the notes and quizzes in ``job.draft`` onto their topics."""
    draft = job.draft or {}
    tenant = job.tenant
    course = job.course
    if course is None:
        raise ApplyError('This draft is not linked to a course.')

    entries = draft.get('topics') or []
    if not entries:
        raise ApplyError('This draft has no material to apply.')

    keep = _keep(selection, 'topics')
    options = job.options or {}
    publish = bool(options.get('publish_immediately'))
    status = 'published' if publish else 'draft'
    quiz_status = 'published' if publish else 'draft'
    # 'replace' updates the topic's existing material in place; 'add' always
    # creates new rows so the admin can stack extra material on a topic that is
    # already written.
    mode = 'add' if (options.get('mode') or 'replace') == 'add' else 'replace'

    summary = {
        'notes_created': 0, 'notes_updated': 0,
        'quizzes_created': 0, 'quizzes_updated': 0,
        'questions_created': 0,
        'assignments_created': 0, 'assignments_updated': 0,
        'coding_created': 0, 'coding_updated': 0, 'test_cases_created': 0,
        'skipped': [],
        'content_ids': [], 'quiz_ids': [], 'assignment_ids': [], 'coding_ids': [],
    }

    topic_ids = [entry.get('topic_id') for entry in entries if entry.get('topic_id')]
    topics_by_id = {
        str(topic.id): topic
        for topic in Topic.objects.filter(
            id__in=topic_ids, subject__course=course
        ).select_related('subject')
    }

    for entry in entries:
        topic_id = str(entry.get('topic_id') or '')
        if keep is not None and topic_id not in keep:
            continue
        topic = topics_by_id.get(topic_id)
        if topic is None:
            summary['skipped'].append({
                'topic': entry.get('topic_name') or 'Unknown topic',
                'reason': 'The topic no longer exists in this course.',
            })
            continue

        note = entry.get('note') or {}
        if note.get('include') and note.get('blocks'):
            _apply_note(tenant, course, topic, note, status, summary, mode)

        quiz = entry.get('quiz') or {}
        if quiz.get('include') and quiz.get('questions'):
            _apply_quiz(tenant, course, topic, quiz, quiz_status, summary, mode)

        for assignment in entry.get('assignments') or []:
            if assignment.get('include'):
                _apply_assignment(tenant, course, topic, assignment, status, summary, mode)

        for problem in entry.get('coding_problems') or []:
            if problem.get('include'):
                _apply_coding_problem(tenant, course, topic, problem, status, summary, mode)

    if not any(
        summary[key] for key in (
            'notes_created', 'notes_updated', 'quizzes_created', 'quizzes_updated',
            'assignments_created', 'assignments_updated',
            'coding_created', 'coding_updated',
        )
    ):
        raise ApplyError('Nothing was selected to apply.')

    summary['course_id'] = str(course.id)
    return summary


def _apply_note(tenant, course, topic, note, status, summary, mode='replace'):
    """Create or replace the AI reading note for ``topic``.

    In ``replace`` mode matching is by ``(topic, content_type='notes')`` so a
    regenerated note updates the existing reading rather than stacking a second
    one. In ``add`` mode a new reading is always created alongside.
    """
    blocks = note.get('blocks') or []
    # Re-render server-side: never trust HTML that came back through the client.
    html = render_blocks(blocks)
    title = (note.get('title') or topic.name)[:500]
    description = blocks_to_plain_text(blocks, limit=400)

    existing = None
    if mode == 'replace':
        existing = (
            Content.objects.filter(topic=topic, content_type='notes')
            .order_by('order').first()
        )
    if existing is not None:
        existing.title = title
        existing.description = description
        existing.content_html = html
        existing.subject = topic.subject
        existing.material_kind = 'study'
        existing.difficulty = note.get('difficulty') or 'intermediate'
        existing.estimated_time_minutes = note.get('estimated_time_minutes') or 10
        existing.status = status
        if not existing.slug:
            existing.slug = _unique_content_slug(title, existing)
        existing.save()
        existing.courses.add(course)
        summary['notes_updated'] += 1
        summary['content_ids'].append(str(existing.id))
        return

    content = Content.objects.create(
        tenant=tenant,
        topic=topic,
        subject=topic.subject,
        title=title,
        slug=_unique_content_slug(title),
        description=description,
        content_type='notes',
        material_kind='study',
        content_html=html,
        difficulty=note.get('difficulty') or 'intermediate',
        estimated_time_minutes=note.get('estimated_time_minutes') or 10,
        status=status,
        is_free=True,
        order=Content.objects.filter(topic=topic).count(),
    )
    content.courses.add(course)
    summary['notes_created'] += 1
    summary['content_ids'].append(str(content.id))


def _apply_quiz(tenant, course, topic, quiz_data, status, summary, mode='replace'):
    """Create or refresh the AI practice quiz for ``topic``.

    A quiz that students have already attempted is never rewritten — the new
    questions go into a fresh quiz instead, so attempt history stays intact.
    In ``add`` mode nothing is ever reused: the quiz is always a new one.
    """
    title = (quiz_data.get('title') or f'{topic.name} Quiz')[:300]
    existing = (
        Quiz.objects.filter(topic=topic, course=course, quiz_type='topic')
        .order_by('created_at')
        .first()
    )
    reuse = mode == 'replace' and existing is not None and existing.total_attempts == 0

    if reuse:
        quiz = existing
        quiz.title = title
        quiz.duration_minutes = quiz_data.get('duration_minutes') or 10
        quiz.status = status
        quiz.subject = topic.subject
        quiz.save()
        # Clearing the link rows (not the questions) keeps any question that is
        # shared with another quiz alive.
        QuizQuestion.objects.filter(quiz=quiz).delete()
        summary['quizzes_updated'] += 1
    else:
        quiz = Quiz.objects.create(
            tenant=tenant,
            course=course,
            subject=topic.subject,
            topic=topic,
            title=title if existing is None else f'{title} (new)',
            description='',
            quiz_type='topic',
            status=status,
            duration_minutes=quiz_data.get('duration_minutes') or 10,
            is_free=True,
        )
        summary['quizzes_created'] += 1

    total_marks = 0
    for index, question_data in enumerate(quiz_data.get('questions') or []):
        options = question_data.get('options') or []
        correct = question_data.get('correct_option', 0)
        if len(options) < 2 or not 0 <= correct < len(options):
            continue
        question = Question.objects.create(
            tenant=tenant,
            topic=topic,
            subject=topic.subject,
            question_text=question_data.get('question_text') or '',
            question_type='mcq',
            difficulty=question_data.get('difficulty') or 'medium',
            status=status,
            # The player compares against the option index as a string.
            correct_answer=str(correct),
            explanation=question_data.get('explanation') or '',
            tags=[t for t in [question_data.get('concept')] if t],
            marks=1,
        )
        question.courses.set([course])
        for option_index, option_text in enumerate(options):
            QuestionOption.objects.create(
                tenant=tenant,
                question=question,
                option_text=option_text,
                is_correct=(option_index == correct),
                order=option_index,
            )
        _tag_question(question, question_data, topic)
        QuizQuestion.objects.create(tenant=tenant, quiz=quiz, question=question, order=index)
        summary['questions_created'] += 1
        total_marks += 1

    quiz.total_marks = total_marks
    quiz.save(update_fields=['total_marks'])
    summary['quiz_ids'].append(str(quiz.id))


def _apply_assignment(tenant, course, topic, data, status, summary, mode='replace'):
    """Create or refresh one generated assignment on ``topic``.

    In ``replace`` mode an assignment with the same title is updated in place so
    a regeneration tops it up instead of duplicating it. An assignment that
    students have already submitted to is never rewritten — the new version is
    filed alongside it, so submissions and grades stay attached to what was
    actually set.
    """
    title = (data.get('title') or f'{topic.name} Assignment')[:500]
    instructions = render_blocks(data.get('instructions') or [])

    existing = None
    if mode == 'replace':
        existing = (
            Assignment.objects.filter(topic=topic, course=course, title__iexact=title)
            .order_by('created_at').first()
        )
        if existing is not None and existing.submissions.exists():
            existing = None
            title = f'{title} (new)'[:500]

    if existing is not None:
        existing.instructions = instructions
        existing.submission_type = data.get('submission_type') or 'either'
        existing.max_marks = data.get('max_marks') or None
        existing.subject = topic.subject
        existing.status = status
        existing.save()
        summary['assignments_updated'] += 1
        summary['assignment_ids'].append(str(existing.id))
        return

    assignment = Assignment.objects.create(
        tenant=tenant,
        course=course,
        subject=topic.subject,
        topic=topic,
        title=title,
        instructions=instructions,
        submission_type=data.get('submission_type') or 'either',
        max_marks=data.get('max_marks') or None,
        is_timed=False,
        status=status,
        order=Assignment.objects.filter(topic=topic).count(),
    )
    summary['assignments_created'] += 1
    summary['assignment_ids'].append(str(assignment.id))


def _apply_coding_problem(tenant, course, topic, data, status, summary, mode='replace'):
    """Create or refresh one generated coding problem and its test cases.

    A problem students have already submitted against is never rewritten, for
    the same reason as assignments. When a problem *is* reused its test cases
    are replaced wholesale — a half-old, half-new suite would grade nonsense.
    """
    title = (data.get('title') or f'{topic.name} Problem')[:500]
    statement = render_blocks(data.get('statement') or [])

    existing = None
    if mode == 'replace':
        existing = (
            CodingProblem.objects.filter(topic=topic, course=course, title__iexact=title)
            .order_by('created_at').first()
        )
        if existing is not None and existing.submissions.exists():
            existing = None
            title = f'{title} (new)'[:500]

    fields = {
        'statement': statement,
        'difficulty': data.get('difficulty') or 'easy',
        'allowed_languages': data.get('allowed_languages') or ['python'],
        'starter_code': data.get('starter_code') or {},
        'time_limit_ms': data.get('time_limit_ms') or 3000,
        'memory_limit_mb': data.get('memory_limit_mb') or 256,
        'max_marks': data.get('max_marks') or None,
        'status': status,
    }

    if existing is not None:
        for field, value in fields.items():
            setattr(existing, field, value)
        existing.subject = topic.subject
        existing.save()
        existing.test_cases.all().delete()
        problem = existing
        summary['coding_updated'] += 1
    else:
        problem = CodingProblem.objects.create(
            tenant=tenant,
            course=course,
            subject=topic.subject,
            topic=topic,
            title=title,
            solve_mode='in_app',
            order=CodingProblem.objects.filter(topic=topic).count(),
            **fields,
        )
        summary['coding_created'] += 1

    for index, case in enumerate(data.get('test_cases') or []):
        TestCase.objects.create(
            problem=problem,
            stdin=case.get('stdin') or '',
            expected_output=case.get('expected_output') or '',
            is_sample=bool(case.get('is_sample')),
            points=case.get('points') or 1,
            explanation=(case.get('explanation') or '')[:500],
            order=index,
        )
        summary['test_cases_created'] += 1

    summary['coding_ids'].append(str(problem.id))


# ─────────────────────────────────────────────────────────────────────────────
# Course meta
# ─────────────────────────────────────────────────────────────────────────────

@transaction.atomic
def apply_meta(job, *, selection=None):
    """Write the approved marketing copy onto the course."""
    course = job.course
    if course is None:
        raise ApplyError('This draft is not linked to a course.')

    data = (job.draft or {}).get('course') or {}
    fields = _keep(selection, 'fields')
    changed = []

    def maybe(field, value):
        if value in (None, '', []):
            return
        if fields is not None and field not in fields:
            return
        setattr(course, field, value)
        changed.append(field)

    maybe('subtitle', data.get('subtitle'))
    # The detail page renders HTML when the model gave us structured blocks.
    maybe('description', data.get('description_html') or data.get('description'))
    maybe('highlights', data.get('highlights'))
    maybe('refund_policy', data.get('refund_policy'))

    if not changed:
        raise ApplyError('Nothing was selected to apply.')

    course.save(update_fields=changed)
    return {'course_id': str(course.id), 'fields_updated': changed}


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

APPLIERS = {
    'outline': apply_outline,
    'content': apply_content,
    'meta': apply_meta,
}


def apply_draft(job, *, user, selection=None):
    """Apply ``job``'s draft after confirmation, and seal the job.

    The caller is responsible for checking ``job.is_reviewable`` and that the
    admin explicitly confirmed; this function performs the write and records the
    audit trail.
    """
    applier = APPLIERS.get(job.kind)
    if applier is None:
        raise ApplyError('This draft cannot be applied.')

    summary = applier(job, selection=selection)

    job.status = job.STATUS_APPLIED
    job.applied_at = timezone.now()
    job.applied_by = user
    job.applied_summary = summary
    job.record_revision('applied', str(summary))
    job.save()
    return summary
