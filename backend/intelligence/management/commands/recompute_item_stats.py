"""Recompute empirical ItemStats from the event log (same job the nightly
Beat task runs, on demand)."""
from django.core.management.base import BaseCommand

from core.models import Tenant
from intelligence.services import itemstats


class Command(BaseCommand):
    help = 'Recompute per-item empirical statistics from LearningEvents.'

    def add_arguments(self, parser):
        parser.add_argument('--tenant', help='Tenant id (default: all).')

    def handle(self, *args, **options):
        tenant = None
        if options.get('tenant'):
            tenant = Tenant.objects.filter(id=options['tenant']).first()
            if tenant is None:
                self.stderr.write('Tenant not found.')
                return
        count = itemstats.recompute_all(tenant=tenant)
        self.stdout.write(self.style.SUCCESS(f'{count} item stats recomputed.'))
