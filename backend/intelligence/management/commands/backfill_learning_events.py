"""Backfill LearningEvents from historical quiz/mock attempts.

Fully re-runnable: emission is deduped on ``LearningEvent.dedup_key``, so a
second run creates nothing new. Run per tenant or across all tenants.
"""
from django.core.management.base import BaseCommand
from django.db.models import Q

from intelligence.services import events as event_service
from quiz.models import MockTestAnswer, MockTestAttempt, QuizAttempt

FINISHED = ('completed', 'timed_out')


class Command(BaseCommand):
    help = 'Backfill LearningEvents from historical completed attempts (idempotent).'

    def add_arguments(self, parser):
        parser.add_argument('--tenant', help='Tenant id to backfill (default: all).')
        parser.add_argument('--since', help='Only attempts completed on/after this date (YYYY-MM-DD).')
        parser.add_argument('--batch-size', type=int, default=500)

    def handle(self, *args, **options):
        tenant_id = options.get('tenant')
        since = options.get('since')
        batch_size = options['batch_size']

        quiz_attempts = QuizAttempt.objects.filter(status__in=FINISHED)
        mock_attempts = MockTestAttempt.objects.filter(status__in=FINISHED)
        if tenant_id:
            quiz_attempts = quiz_attempts.filter(student__user__tenant_id=tenant_id)
            mock_attempts = mock_attempts.filter(student__user__tenant_id=tenant_id)
        if since:
            quiz_attempts = quiz_attempts.filter(completed_at__date__gte=since)
            mock_attempts = mock_attempts.filter(completed_at__date__gte=since)

        total_events = 0
        total_attempts = 0
        for queryset in (quiz_attempts, mock_attempts):
            for attempt in queryset.order_by('pk').iterator(chunk_size=batch_size):
                total_events += event_service.record_attempt_events(attempt)
                total_attempts += 1
                if total_attempts % batch_size == 0:
                    self.stdout.write(f'  … {total_attempts} attempts, {total_events} events built')

        # Superseding events for answers that were manually graded before the
        # event log existed.
        graded = MockTestAnswer.objects.filter(
            Q(graded_at__isnull=False),
            attempt__status__in=FINISHED,
        ).select_related('attempt__student__user', 'item__topic', 'item__subject')
        if tenant_id:
            graded = graded.filter(attempt__student__user__tenant_id=tenant_id)
        regrades = 0
        for item_answer in graded.order_by('pk').iterator(chunk_size=batch_size):
            if event_service.record_regrade_event(item_answer):
                regrades += 1

        self.stdout.write(self.style.SUCCESS(
            f'Backfill done: {total_attempts} attempts scanned, '
            f'{total_events} events built, {regrades} regrade events built '
            f'(duplicates ignored by dedup_key).'
        ))
