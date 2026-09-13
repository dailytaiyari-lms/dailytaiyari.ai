"""
Background media processing for uploaded lecture videos.

Most tools export MP4s with the ``moov`` atom (the index the player needs to
know where every frame lives) written *after* the media data. A browser cannot
render a single frame until it has that index, so it keeps downloading until it
finds it — for a two hour lecture that means waiting on hundreds of megabytes
before playback starts.

Remuxing with ``-movflags +faststart`` moves the index to the front of the file.
It is a stream copy, so there is no re-encode and no quality loss; the file is
simply rewritten with its atoms reordered. Playback then starts as soon as the
first chunk arrives, and seeking works off byte ranges.
"""
import json
import logging
import os
import shutil
import subprocess
import tempfile

from celery import shared_task
from django.core.files import File
from django.db import transaction

logger = logging.getLogger(__name__)

FFMPEG = os.environ.get('FFMPEG_BINARY', 'ffmpeg')
FFPROBE = os.environ.get('FFPROBE_BINARY', 'ffprobe')

# Long lectures are big; give ffmpeg room but never hang a worker forever.
REMUX_TIMEOUT_SECONDS = int(os.environ.get('VIDEO_REMUX_TIMEOUT', '3600'))
PROBE_TIMEOUT_SECONDS = 120


def _iter_top_level_atoms(path, limit=25):
    """Yield the top-level atom types of an MP4, in file order."""
    with open(path, 'rb') as fh:
        for _ in range(limit):
            header = fh.read(8)
            if len(header) < 8:
                return
            size = int.from_bytes(header[:4], 'big')
            atom = header[4:8].decode('latin-1', errors='replace')
            yield atom
            if size == 1:
                # 64-bit size follows the type.
                ext = fh.read(8)
                if len(ext) < 8:
                    return
                size = int.from_bytes(ext, 'big')
                if size < 16:
                    return
                fh.seek(size - 16, os.SEEK_CUR)
            elif size == 0:
                # Extends to EOF — nothing meaningful after this.
                return
            elif size < 8:
                return
            else:
                fh.seek(size - 8, os.SEEK_CUR)


def is_faststart(path):
    """True when the ``moov`` index precedes the media data."""
    try:
        for atom in _iter_top_level_atoms(path):
            if atom == 'moov':
                return True
            if atom == 'mdat':
                return False
    except OSError:
        logger.warning('Could not inspect atoms for %s', path, exc_info=True)
    return False


def probe_duration_seconds(path):
    """Duration in seconds via ffprobe, or None when it cannot be determined."""
    try:
        out = subprocess.run(
            [FFPROBE, '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'json', path],
            capture_output=True, text=True, timeout=PROBE_TIMEOUT_SECONDS, check=True,
        )
        value = json.loads(out.stdout).get('format', {}).get('duration')
        return float(value) if value else None
    except (subprocess.SubprocessError, ValueError, KeyError, OSError):
        logger.warning('ffprobe failed for %s', path, exc_info=True)
        return None


def remux_faststart(src_path, dst_path):
    """Stream-copy ``src_path`` into ``dst_path`` with the index up front."""
    subprocess.run(
        [FFMPEG, '-v', 'error', '-y', '-i', src_path,
         '-c', 'copy', '-map', '0', '-movflags', '+faststart', dst_path],
        capture_output=True, text=True, timeout=REMUX_TIMEOUT_SECONDS, check=True,
    )


@shared_task(
    name='content.optimize_video',
    bind=True,
    max_retries=2,
    default_retry_delay=120,
    acks_late=True,
    # The project-wide limit is tuned for short grading jobs; a two hour remux
    # needs far longer, so override it here rather than globally.
    soft_time_limit=REMUX_TIMEOUT_SECONDS + 120,
    time_limit=REMUX_TIMEOUT_SECONDS + 300,
)
def optimize_content_video(self, content_id):
    """Make an uploaded lecture video start playing immediately.

    Downloads the upload, records its real duration, and — when the index is at
    the back — rewrites it with ``+faststart`` and swaps the stored file. Never
    raises into the caller: a failure leaves the original file playable, just
    slower to start.
    """
    from content.models import Content

    try:
        content = Content.objects.get(pk=content_id)
    except Content.DoesNotExist:
        return 'content-missing'

    if not content.video_file:
        return 'no-video'

    source_name = content.video_file.name
    Content.objects.filter(pk=content_id).update(video_status='processing')

    workdir = tempfile.mkdtemp(prefix='dt-video-')
    local_src = os.path.join(workdir, 'source.mp4')
    local_out = os.path.join(workdir, 'faststart.mp4')

    try:
        with content.video_file.open('rb') as remote, open(local_src, 'wb') as local:
            shutil.copyfileobj(remote, local, length=8 * 1024 * 1024)

        duration = probe_duration_seconds(local_src)
        fields = {}
        if duration:
            fields['video_duration_seconds'] = int(round(duration))
            fields['video_duration_minutes'] = max(1, int(round(duration / 60)))

        if is_faststart(local_src):
            fields['video_status'] = 'ready'
            Content.objects.filter(pk=content_id).update(**fields)
            return 'already-faststart'

        remux_faststart(local_src, local_out)

        # Save under a fresh name so anyone mid-playback keeps a working URL,
        # then drop the original.
        base = os.path.basename(source_name)
        stem, _ = os.path.splitext(base)
        with open(local_out, 'rb') as fh:
            content.video_file.save(f'{stem}-faststart.mp4', File(fh), save=False)

        fields['video_status'] = 'ready'
        fields['video_file'] = content.video_file.name
        Content.objects.filter(pk=content_id).update(**fields)

        try:
            content.video_file.storage.delete(source_name)
        except Exception:
            logger.warning('Could not delete original video %s', source_name, exc_info=True)

        return 'remuxed'

    except subprocess.TimeoutExpired:
        Content.objects.filter(pk=content_id).update(video_status='failed')
        logger.error('Video remux timed out for content %s', content_id)
        return 'timeout'
    except FileNotFoundError:
        # ffmpeg/ffprobe not installed — leave the upload usable and say so.
        Content.objects.filter(pk=content_id).update(video_status='failed')
        logger.error('ffmpeg is not available; skipping optimisation for %s', content_id)
        return 'ffmpeg-missing'
    except Exception as exc:
        Content.objects.filter(pk=content_id).update(video_status='failed')
        logger.exception('Video optimisation failed for content %s', content_id)
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            return 'failed'
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def enqueue_video_optimization(content):
    """Queue optimisation for a content row once its transaction commits."""
    from django.conf import settings

    if not getattr(settings, 'VIDEO_OPTIMIZATION_ENABLED', True):
        return
    if not content.pk or not content.video_file:
        return

    content_id = content.pk

    def _dispatch():
        try:
            # retry=False so a dead broker fails immediately instead of blocking
            # the request thread that just finished the upload.
            optimize_content_video.apply_async(
                args=[content_id], queue='media', retry=False, ignore_result=True,
            )
        except Exception:
            # Broker down — the upload still plays, just without the speed-up.
            logger.warning('Could not queue video optimisation for %s', content_id, exc_info=True)

    transaction.on_commit(_dispatch)
