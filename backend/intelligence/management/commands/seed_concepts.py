"""Harvest existing free-text concept labels into canonical Concept rows.

Sources:
- ``Question.tags`` — coursegen has stored a single concept string there
- ``chatbot.AIQuizQuestion.topic`` — the AI-quiz per-question concept label

Idempotent: resolution goes through the same alias funnel as everything else.
"""
from django.core.management.base import BaseCommand

from intelligence.services.itemtags import set_item_tags
from intelligence.services.normalize import resolve_concept
from quiz.models import Question


class Command(BaseCommand):
    help = 'Seed Concepts (and links) from legacy free-text labels. Idempotent.'

    def add_arguments(self, parser):
        parser.add_argument('--tenant', help='Tenant id to seed (default: all).')

    def handle(self, *args, **options):
        questions = (
            Question.objects.exclude(tags=[])
            .filter(tenant__isnull=False, tagging_status='')
            .select_related('subject', 'topic')
        )
        if options.get('tenant'):
            questions = questions.filter(tenant_id=options['tenant'])

        linked = 0
        for question in questions.iterator(chunk_size=500):
            labels = [t for t in question.tags if isinstance(t, str) and t.strip()][:4]
            if not labels:
                continue
            set_item_tags(
                question,
                concept_labels=labels,
                subject=question.subject,
                topic=question.topic,
                source='backfill',
            )
            linked += 1
        self.stdout.write(f'{linked} bank questions concept-linked from tags')

        # AI-quiz labels become concepts (no item link — those questions live
        # in JSON), so the tagger's candidate lists know the tenant's ideas.
        try:
            from chatbot.models import AIQuizQuestion
        except ImportError:
            AIQuizQuestion = None
        seeded = 0
        if AIQuizQuestion is not None:
            rows = (
                AIQuizQuestion.objects.exclude(topic='')
                .filter(attempt__session__course__isnull=False)
                .select_related('attempt__session__course')
            )
            if options.get('tenant'):
                rows = rows.filter(tenant_id=options['tenant'])
            for row in rows.iterator(chunk_size=500):
                course = row.attempt.session.course
                subject = course.subjects.first() if course else None
                if subject is None:
                    continue
                if resolve_concept(row.tenant, subject, row.topic, source='backfill'):
                    seeded += 1
        self.stdout.write(self.style.SUCCESS(
            f'Concept seeding done ({seeded} AI-quiz labels resolved).'
        ))
