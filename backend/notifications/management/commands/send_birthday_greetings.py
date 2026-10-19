"""Deliver today's birthday greetings.

Safe to run repeatedly — a student is never wished twice in the same year. Meant
for a daily cron entry, e.g.::

    30 3 * * * python manage.py send_birthday_greetings

The app also self-heals: if this command never runs, the first notification poll
of the day triggers the same sweep. Cron simply makes the greeting land early in
the morning rather than whenever the first user opens the app.
"""
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.models import Tenant
from notifications import birthdays


class Command(BaseCommand):
    help = "Send birthday greetings to students celebrating today."

    def add_arguments(self, parser):
        parser.add_argument(
            '--date', help='Run for a specific date (YYYY-MM-DD) instead of today.',
        )
        parser.add_argument(
            '--tenant', help='Limit the sweep to one tenant (id, subdomain or name).',
        )
        parser.add_argument(
            '--force', action='store_true',
            help='Ignore the tenant\'s "birthday greetings" setting.',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report who would be greeted without sending anything.',
        )

    def handle(self, *args, **options):
        today = timezone.localdate()
        if options.get('date'):
            try:
                today = datetime.strptime(options['date'], '%Y-%m-%d').date()
            except ValueError:
                raise CommandError('--date must be in YYYY-MM-DD format.')

        tenants = Tenant.objects.filter(is_active=True)
        selector = options.get('tenant')
        if selector:
            from django.db.models import Q
            filters = Q(subdomain__iexact=selector) | Q(name__iexact=selector)
            try:
                import uuid
                filters |= Q(id=uuid.UUID(selector))
            except (ValueError, AttributeError):
                pass
            tenants = tenants.filter(filters)
            if not tenants.exists():
                raise CommandError(f'No active tenant matched "{selector}".')

        dry_run = options.get('dry_run', False)
        summaries = birthdays.run_sweep(
            today, tenants=tenants, force=options.get('force', False),
            dry_run=dry_run,
        )

        total = 0
        for summary in summaries:
            greeted = summary['greeted']
            total += len(greeted)
            if not summary['enabled']:
                self.stdout.write(
                    f'- {summary["tenant"]}: birthday greetings disabled, skipped.'
                )
                continue
            if not greeted:
                self.stdout.write(f'- {summary["tenant"]}: no birthdays today.')
                continue
            self.stdout.write(self.style.SUCCESS(
                f'- {summary["tenant"]}: {len(greeted)} greeted'
                + (f', {summary["skipped"]} skipped' if summary['skipped'] else '')
            ))
            for person in greeted:
                tag = ' (past student)' if person['is_past_student'] else ''
                self.stdout.write(f'    · {person["name"]}{tag}')

        verb = 'would be greeted' if dry_run else 'greeted'
        self.stdout.write(self.style.SUCCESS(
            f'{today.isoformat()}: {total} student(s) {verb}.'
        ))
