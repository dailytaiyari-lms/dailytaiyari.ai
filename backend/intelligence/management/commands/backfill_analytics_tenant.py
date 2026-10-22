"""Fill the historically-NULL tenant column on analytics rollup tables.

The analytics services now set tenant on every create; this one-off brings
old rows in line so tenant-scoped queries and indexes work. Re-runnable.
"""
from django.core.management.base import BaseCommand

from analytics.models import (
    DailyActivity, Streak, StudySession, SubjectPerformance, TopicMastery, WeeklyReport,
)

MODELS = [TopicMastery, SubjectPerformance, DailyActivity, Streak, WeeklyReport, StudySession]


class Command(BaseCommand):
    help = 'Backfill tenant on analytics rows from student.user.tenant (idempotent).'

    def handle(self, *args, **options):
        for model in MODELS:
            updated = 0
            queryset = model.objects.filter(tenant__isnull=True).select_related('student__user')
            for row in queryset.iterator(chunk_size=1000):
                tenant = row.student.user.tenant
                if tenant is None:
                    continue
                row.tenant = tenant
                row.save(update_fields=['tenant'])
                updated += 1
            self.stdout.write(f'{model.__name__}: {updated} rows backfilled')
        self.stdout.write(self.style.SUCCESS('Analytics tenant backfill done.'))
