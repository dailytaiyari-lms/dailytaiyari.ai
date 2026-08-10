"""What a topic already has, for the focused single-topic studio.

Two consumers, one source of truth:

* the **API** shows the admin what is already on the topic before they generate,
  so "add more" is an informed choice rather than a guess;
* the **prompt** gets the same picture in prose, so the model can write material
  that complements what exists instead of repeating it.
"""
from __future__ import annotations

from assignments.models import Assignment
from coding.models import CodingProblem
from content.models import Content
from notebooks.models import Notebook
from quiz.models import Quiz

from .notehtml import html_to_plain_text


def topic_material(topic):
    """A compact inventory of everything already attached to ``topic``."""
    notes = [
        {
            'id': str(item.id),
            'title': item.title,
            'status': item.status,
            'content_type': item.content_type,
            'estimated_time_minutes': item.estimated_time_minutes,
        }
        for item in Content.objects.filter(topic=topic).order_by('order', 'created_at')
    ]
    quizzes = [
        {
            'id': str(item.id),
            'title': item.title,
            'status': item.status,
            'question_count': item.questions.count(),
            'total_attempts': item.total_attempts,
            # Attempted quizzes are never overwritten — surface that up front so
            # the admin isn't surprised by a "(new)" quiz appearing.
            'locked': item.total_attempts > 0,
        }
        for item in Quiz.objects.filter(topic=topic).order_by('created_at')
    ]
    assignments = [
        {
            'id': str(item.id),
            'title': item.title,
            'status': item.status,
            'submission_type': item.submission_type,
            'max_marks': item.max_marks,
            'locked': item.submissions.exists(),
        }
        for item in Assignment.objects.filter(topic=topic).order_by('order', 'created_at')
    ]
    coding = [
        {
            'id': str(item.id),
            'title': item.title,
            'status': item.status,
            'difficulty': item.difficulty,
            'test_case_count': item.test_cases.count(),
            'locked': item.submissions.exists(),
        }
        for item in CodingProblem.objects.filter(topic=topic).order_by('order', 'created_at')
    ]
    notebooks = [
        {
            'id': str(item.id),
            'title': item.title,
            'status': item.status,
            'difficulty': item.difficulty,
            'total_points': item.total_points(),
            'locked': item.submissions.exists(),
        }
        for item in Notebook.objects.filter(topic=topic).order_by('order', '-created_at')
    ]

    return {
        'topic_id': str(topic.id),
        'topic_name': topic.name,
        'notes': notes,
        'quizzes': quizzes,
        'assignments': assignments,
        'coding_problems': coding,
        'notebooks': notebooks,
        'counts': {
            'notes': len(notes),
            'quizzes': len(quizzes),
            'questions': sum(q['question_count'] for q in quizzes),
            'assignments': len(assignments),
            'coding_problems': len(coding),
            'notebooks': len(notebooks),
        },
    }


def existing_material_text(topics, *, limit_per_topic=6):
    """The same inventory as prose, for the generation prompt.

    Titles alone are not enough to avoid repetition, so a note also contributes
    the opening of its text — that is what tells the model which ground is
    already covered.
    """
    lines = []
    for topic in topics:
        topic_id = topic.get('id')
        if not topic_id:
            continue
        entries = []

        for note in Content.objects.filter(topic_id=topic_id).order_by('order')[:limit_per_topic]:
            excerpt = html_to_plain_text(note.content_html, limit=400)
            entries.append(
                f'  - Reading: "{note.title}"' + (f' — covers: {excerpt}' if excerpt else '')
            )
        for quiz in Quiz.objects.filter(topic_id=topic_id).order_by('created_at')[:limit_per_topic]:
            concepts = sorted({
                tag
                for question in quiz.questions.all()[:30]
                for tag in (question.tags or [])
                if tag
            })
            entries.append(
                f'  - Quiz: "{quiz.title}" ({quiz.questions.count()} questions)'
                + (f' — already tests: {", ".join(concepts[:12])}' if concepts else '')
            )
        for assignment in Assignment.objects.filter(
            topic_id=topic_id
        ).order_by('order')[:limit_per_topic]:
            entries.append(f'  - Assignment: "{assignment.title}"')
        for problem in CodingProblem.objects.filter(
            topic_id=topic_id
        ).order_by('order')[:limit_per_topic]:
            entries.append(f'  - Coding problem: "{problem.title}" ({problem.difficulty})')
        for notebook in Notebook.objects.filter(
            topic_id=topic_id
        ).order_by('order')[:limit_per_topic]:
            entries.append(f'  - Python notebook: "{notebook.title}" ({notebook.difficulty})')

        if entries:
            lines.append(f'Topic "{topic.get("name")}":')
            lines.extend(entries)

    return '\n'.join(lines)
