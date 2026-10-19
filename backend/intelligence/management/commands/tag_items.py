"""Run the tagging sweep from the CLI (budget-gated, cached, batched).

v2 tags every subject that has a syllabus tree; v1 tags the rest.
``--model`` runs v2 on a platform model instead of the tenant's tagging model
(experiments: e.g. ``--model gpt-6-luna``).
"""
from django.core.management.base import BaseCommand, CommandError

from core.models import Tenant
from intelligence.services import tagging_sweep
from intelligence.services.llm import platform_call


class Command(BaseCommand):
    help = 'Tag untagged/stale items (v2 where a syllabus tree exists, v1 elsewhere).'

    def add_arguments(self, parser):
        parser.add_argument('--tenant', help='Tenant id (default: every active tenant).')
        parser.add_argument('--limit', type=int, default=200,
                            help='Item cap per tenant for this pass: v2 shares one cap across questions '
                                 'and mock items; v1 applies it to each kind separately.')
        parser.add_argument('--model', default=None,
                            help='Platform model name to use for v2 (default: tenant tagging model).')

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
                call = platform_call(options['model'], tenant) if options['model'] else None
                result = tagging_sweep.run_sweep(tenant, limit=options['limit'], call=call)
            except Exception as exc:  # noqa: BLE001 — budget/provider errors are per-tenant
                self.stderr.write(f'{tenant.name}: {exc}')
                continue
            total += result['v2'] + result['v1']
            self.stdout.write(f'{tenant.name}: v2: {result["v2"]}, v1: {result["v1"]} item(s) tagged')
        self.stdout.write(self.style.SUCCESS(f'Done — {total} item(s) tagged.'))
