"""
Backfill faststart optimisation for lecture videos uploaded before the
pipeline existed.

    python manage.py optimize_videos --dry-run
    python manage.py optimize_videos --all
    python manage.py optimize_videos --content-id 42
    python manage.py optimize_videos --sync      # run inline, no Celery
"""
from django.core.management.base import BaseCommand

from content.models import Content
from content.tasks import optimize_content_video


class Command(BaseCommand):
    help = 'Queue faststart optimisation for uploaded lecture videos.'

    def add_arguments(self, parser):
        parser.add_argument('--all', action='store_true',
                            help='Include videos already marked ready.')
        parser.add_argument('--content-id', type=int, default=None,
                            help='Only this content row.')
        parser.add_argument('--dry-run', action='store_true',
                            help='List what would be processed and exit.')
        parser.add_argument('--sync', action='store_true',
                            help='Process inline instead of queueing to Celery.')

    def handle(self, *args, **options):
        qs = Content.objects.exclude(video_file='').exclude(video_file__isnull=True)

        if options['content_id']:
            qs = qs.filter(pk=options['content_id'])
        elif not options['all']:
            qs = qs.exclude(video_status='ready')

        total = qs.count()
        if not total:
            self.stdout.write(self.style.WARNING('No videos to process.'))
            return

        self.stdout.write(f'{total} video(s) to process.')

        for content in qs.only('id', 'title', 'video_file', 'video_status').iterator():
            label = f'#{content.pk} {content.title[:60]}'
            if options['dry_run']:
                self.stdout.write(f'  would process {label} [{content.video_status or "new"}]')
                continue

            if options['sync']:
                result = optimize_content_video(content.pk)
                self.stdout.write(f'  {label}: {result}')
            else:
                optimize_content_video.apply_async(args=[content.pk], queue='media')
                self.stdout.write(f'  queued {label}')

        if not options['dry_run']:
            self.stdout.write(self.style.SUCCESS('Done.'))
