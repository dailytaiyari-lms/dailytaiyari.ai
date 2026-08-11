"""Reconcile Zoom attendance for recently-ended live classes.

Intended as a cron backstop for missed webhooks:

    python manage.py sync_live_attendance --hours 24
"""
from django.core.management.base import BaseCommand

from liveclass.tasks import sync_recent_attendance_task


class Command(BaseCommand):
    help = 'Pull Zoom attendance reports for live classes that ended recently.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--hours', type=int, default=24,
            help='How far back to look for ended classes (default: 24).',
        )

    def handle(self, *args, **options):
        count = sync_recent_attendance_task(hours=options['hours'])
        self.stdout.write(self.style.SUCCESS(f'Synced attendance for {count} class(es).'))
