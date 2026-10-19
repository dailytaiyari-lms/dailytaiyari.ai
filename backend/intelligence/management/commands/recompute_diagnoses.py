"""Re-run response diagnosis over finished attempts (after a classifier or
threshold change — bump CLASSIFIER_VERSION first), then refresh the learner
state of each quiz/mock attempt so the new labels reach mastery. Idempotent;
one failing attempt is reported and skipped."""
from datetime import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone

from intelligence.models import LearningEvent
from intelligence.services import diagnose, state


class Command(BaseCommand):
    help = ('Recompute ResponseDiagnosis rows for attempts with learning events, '
            'and refresh learner state for quiz/mock attempts.')

    def add_arguments(self, parser):
        parser.add_argument('--tenant', help='Only this tenant id.')
        parser.add_argument('--since', help='Only attempts with events on/after YYYY-MM-DD.')

    def handle(self, *args, **options):
        events = LearningEvent.objects.exclude(attempt_id=None)
        if options.get('tenant'):
            events = events.filter(tenant_id=options['tenant'])
        if options.get('since'):
            since = timezone.make_aware(datetime.strptime(options['since'], '%Y-%m-%d'))
            events = events.filter(occurred_at__gte=since)
        pairs = events.values_list('attempt_kind', 'attempt_id').distinct()
        attempts = rows = failures = 0
        for kind, attempt_id in pairs.iterator():
            try:
                rows += diagnose.diagnose_attempt(kind, attempt_id)
                if kind in ('quiz', 'mock'):
                    state.update_for_attempt(kind, attempt_id)
                attempts += 1
            except Exception as exc:  # noqa: BLE001 — keep going
                failures += 1
                self.stderr.write(f'Failed {kind} {attempt_id}: {exc}')
        self.stdout.write(self.style.SUCCESS(
            f'Diagnosed {attempts} attempt(s), {rows} response row(s), {failures} failure(s).'))
