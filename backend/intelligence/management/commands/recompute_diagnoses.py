"""Re-run response diagnosis over finished attempts (after a classifier or
threshold change — bump CLASSIFIER_VERSION first). Idempotent."""
from datetime import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone

from intelligence.models import LearningEvent
from intelligence.services import diagnose


class Command(BaseCommand):
    help = 'Recompute ResponseDiagnosis rows for attempts with learning events.'

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
        attempts = rows = 0
        for kind, attempt_id in pairs.iterator():
            rows += diagnose.diagnose_attempt(kind, attempt_id)
            attempts += 1
        self.stdout.write(self.style.SUCCESS(
            f'Diagnosed {attempts} attempt(s), {rows} response row(s).'))
