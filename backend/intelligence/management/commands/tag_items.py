"""Run the LLM tagging pass from the CLI (budget-gated, cached, batched).

Useful for the initial backfill after seed_concepts, or to catch up a single
tenant without waiting for the weekly sweep.
"""
from django.core.management.base import BaseCommand, CommandError

from core.models import Tenant
from intelligence.services import tagging


class Command(BaseCommand):
    help = 'Tag untagged/stale items with concepts/difficulty/cognitive type via LLM.'

    def add_arguments(self, parser):
        parser.add_argument('--tenant', help='Tenant id (default: every active tenant).')
        parser.add_argument('--limit', type=int, default=200,
                            help='Max items per kind per tenant in this pass.')

    def handle(self, *args, **options):
        if options.get('tenant'):
            tenants = list(Tenant.objects.filter(id=options['tenant']))
            if not tenants:
                raise CommandError('Tenant not found.')
        else:
            tenants = list(Tenant.objects.filter(is_active=True))

        total = 0
        for tenant in tenants:
            try:
                tagged = tagging.run_tagging_for_tenant(tenant, limit=options['limit'])
            except Exception as exc:  # noqa: BLE001 — budget/provider errors are per-tenant
                self.stderr.write(f'{tenant.name}: {exc}')
                continue
            total += tagged
            self.stdout.write(f'{tenant.name}: {tagged} item(s) tagged')
        self.stdout.write(self.style.SUCCESS(f'Done — {total} item(s) tagged.'))
