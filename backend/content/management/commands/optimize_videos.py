"""
Backfill faststart optimisation for lecture videos uploaded before the
pipeline existed.

    python manage.py optimize_videos --dry-run
    python manage.py optimize_videos --all
    python manage.py optimize_videos --content-id 42
    python manage.py optimize_videos --sync      # run inline, no Celery
    python manage.py optimize_videos --hls-only  # only (re)build HLS ladders
"""
from django.core.management.base import BaseCommand

from content.models import Content
from content.tasks import optimize_content_video, package_content_hls


class Command(BaseCommand):
    help = 'Queue faststart optimisation for uploaded lecture videos.'

    def add_arguments(self, parser):
        parser.add_argument('--all', action='store_true',
                            help='Include videos already marked ready.')
        parser.add_argument('--content-id', default=None,
                            help='Only this content row (UUID).')
        parser.add_argument('--dry-run', action='store_true',
                            help='List what would be processed and exit.')
        parser.add_argument('--sync', action='store_true',
                            help='Process inline instead of queueing to Celery.')
        parser.add_argument('--hls-only', action='store_true',
                            help='Skip the remux and only build HLS ladders.')
        parser.add_argument('--status', action='store_true',
                            help='Report pipeline health and exit without queueing.')

    def handle(self, *args, **options):
        if options['status']:
            self.report_status()
            return

        qs = Content.objects.exclude(video_file='').exclude(video_file__isnull=True)

        if options['content_id']:
            qs = qs.filter(pk=options['content_id'])
        elif options['hls_only']:
            qs = qs.exclude(hls_status='ready')
        elif not options['all']:
            qs = qs.exclude(video_status='ready')

        task = package_content_hls if options['hls_only'] else optimize_content_video

        total = qs.count()
        if not total:
            self.stdout.write(self.style.WARNING('No videos to process.'))
            return

        self.stdout.write(f'{total} video(s) to process.')

        for content in qs.only('id', 'title', 'video_file', 'video_status', 'hls_status').iterator():
            label = f'#{content.pk} {content.title[:60]}'
            state = content.hls_status if options['hls_only'] else content.video_status
            if options['dry_run']:
                self.stdout.write(f'  would process {label} [{state or "new"}]')
                continue

            if options['sync']:
                result = task(content.pk)
                self.stdout.write(f'  {label}: {result}')
            else:
                task.apply_async(args=[content.pk], queue='media')
                self.stdout.write(f'  queued {label}')

        if not options['dry_run']:
            self.stdout.write(self.style.SUCCESS('Done.'))

    def report_status(self):
        """Explain why videos may still be unprocessed.

        Optimisation runs in a Celery worker, so an upload stays broken when
        ffmpeg is missing from the image, the `media` queue has no worker, or
        the feature flag is off. Each of those is invisible from the app, so
        check them explicitly rather than guessing.
        """
        import shutil
        import subprocess
        from django.conf import settings
        from content.tasks import FFMPEG, FFPROBE

        self.stdout.write(self.style.MIGRATE_HEADING('Tooling'))
        for label, binary in (('ffmpeg', FFMPEG), ('ffprobe', FFPROBE)):
            path = shutil.which(binary)
            if path:
                self.stdout.write(f'  {label}: {path}')
            else:
                self.stdout.write(self.style.ERROR(
                    f'  {label}: NOT FOUND — rebuild the image; nothing can be processed'))

        self.stdout.write(self.style.MIGRATE_HEADING('Settings'))
        for flag in ('VIDEO_OPTIMIZATION_ENABLED', 'VIDEO_HLS_ENABLED'):
            value = getattr(settings, flag, True)
            style = self.style.SUCCESS if value else self.style.WARNING
            self.stdout.write('  ' + style(f'{flag} = {value}'))

        self.stdout.write(self.style.MIGRATE_HEADING('Workers on the "media" queue'))
        try:
            from dailytaiyari.celery import app as celery_app
            pong = celery_app.control.ping(timeout=3)
            if not pong:
                self.stdout.write(self.style.ERROR(
                    '  no Celery workers responded — start celery-mediaworker'))
            else:
                for entry in pong:
                    for name in entry:
                        self.stdout.write(f'  {name}')
                active = celery_app.control.inspect(timeout=3).active_queues() or {}
                serving = [w for w, qs in active.items()
                           if any(q.get('name') == 'media' for q in qs)]
                if serving:
                    self.stdout.write(self.style.SUCCESS(
                        f'  serving "media": {", ".join(serving)}'))
                else:
                    self.stdout.write(self.style.ERROR(
                        '  NO worker consumes the "media" queue — tasks will queue forever'))
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f'  could not reach the broker: {exc}'))

        self.stdout.write(self.style.MIGRATE_HEADING('Videos'))
        qs = Content.objects.exclude(video_file='').exclude(video_file__isnull=True)
        total = qs.count()
        self.stdout.write(f'  {total} content row(s) with an uploaded video')
        for field in ('video_status', 'hls_status'):
            counts = {}
            for value in qs.values_list(field, flat=True):
                counts[value or 'unprocessed'] = counts.get(value or 'unprocessed', 0) + 1
            summary = ', '.join(f'{k}={v}' for k, v in sorted(counts.items())) or 'none'
            self.stdout.write(f'  {field}: {summary}')

        stuck = qs.exclude(video_status='ready')[:10]
        if stuck:
            self.stdout.write(self.style.WARNING('  not ready yet:'))
            for c in stuck:
                self.stdout.write(f'    {c.pk}  {c.title[:50]}  [{c.video_status or "unprocessed"}]')
            self.stdout.write('  fix with: manage.py optimize_videos --all')
