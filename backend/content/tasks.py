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
import posixpath
import shutil
import subprocess
import tempfile
import uuid

from celery import shared_task
from django.core.files import File
from django.db import transaction

from .ffmpeg_utils import run_with_progress

logger = logging.getLogger(__name__)

FFMPEG = os.environ.get('FFMPEG_BINARY', 'ffmpeg')
FFPROBE = os.environ.get('FFPROBE_BINARY', 'ffprobe')

# Long lectures are big; give ffmpeg room but never hang a worker forever.
REMUX_TIMEOUT_SECONDS = int(os.environ.get('VIDEO_REMUX_TIMEOUT', '3600'))
PROBE_TIMEOUT_SECONDS = 120
# A re-encode is far slower than a stream copy, so it gets its own budget.
TRANSCODE_TIMEOUT_SECONDS = int(os.environ.get('VIDEO_TRANSCODE_TIMEOUT', str(6 * 3600)))
TRANSCODE_PRESET = os.environ.get('VIDEO_HLS_PRESET', 'veryfast')

# Codecs every current browser can decode inside an MP4. Anything else plays
# for some students and not others, so it is re-encoded rather than copied.
BROWSER_VIDEO_CODECS = {'h264'}
BROWSER_AUDIO_CODECS = {'aac', 'mp3'}


def _iter_top_level_atoms(path, limit=25):
    """Yield ``(atom_type, payload_offset, payload_size)`` in file order."""
    with open(path, 'rb') as fh:
        for _ in range(limit):
            start = fh.tell()
            header = fh.read(8)
            if len(header) < 8:
                return
            size = int.from_bytes(header[:4], 'big')
            atom = header[4:8].decode('latin-1', errors='replace')
            header_len = 8
            if size == 1:
                # 64-bit size follows the type.
                ext = fh.read(8)
                if len(ext) < 8:
                    return
                size = int.from_bytes(ext, 'big')
                header_len = 16
                if size < header_len:
                    return
            elif size == 0:
                # Extends to EOF — nothing meaningful after this.
                yield atom, start + header_len, None
                return
            elif size < 8:
                return

            yield atom, start + header_len, size - header_len
            fh.seek(start + size)


def _has_movie_extends(path, offset, size):
    """True when a ``moov`` box contains ``mvex`` — the fMP4 marker.

    ``mvex`` announces that the real samples live in later fragments, so the
    movie header carries no sample table and usually a zero duration.
    """
    if not size or size > 32 * 1024 * 1024:
        return False
    try:
        with open(path, 'rb') as fh:
            fh.seek(offset)
            return b'mvex' in fh.read(size)
    except OSError:
        return False


def inspect_mp4(path):
    """Return ``(faststart, fragmented)`` for an MP4.

    ``faststart`` means the ``moov`` index precedes the media data.

    ``fragmented`` means the file is an fMP4: a stub ``moov`` followed by many
    ``moof``/``mdat`` fragment pairs. Those are built for live streaming, and a
    browser handed one over plain HTTP reports a nonsense duration (the movie
    header declares zero, so players guess from the first fragment) and cannot
    seek, because there is no sample table mapping a timestamp to a byte offset
    — every seek restarts the file. Such a file is technically "faststart" yet
    still needs remuxing, so the two answers have to be separate.
    """
    faststart = False
    fragmented = False
    seen_media = False
    try:
        for atom, offset, size in _iter_top_level_atoms(path):
            if atom == 'moof':
                fragmented = True
                break
            if atom == 'moov':
                if _has_movie_extends(path, offset, size):
                    fragmented = True
                    if not seen_media:
                        faststart = True
                    break
                if not seen_media:
                    faststart = True
            elif atom == 'mdat':
                seen_media = True
                if faststart:
                    # Index up front and no fragment header before the media.
                    break
    except OSError:
        logger.warning('Could not inspect atoms for %s', path, exc_info=True)
        return False, False
    return faststart, fragmented


def is_faststart(path):
    """True when the file already starts instantly and can be seeked."""
    faststart, fragmented = inspect_mp4(path)
    return faststart and not fragmented


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


def probe_codecs(path):
    """Return ``(video_codec, audio_codec)``; either may be ``None``."""
    try:
        out = subprocess.run(
            [FFPROBE, '-v', 'error', '-show_entries', 'stream=codec_type,codec_name',
             '-of', 'json', path],
            capture_output=True, text=True, timeout=PROBE_TIMEOUT_SECONDS, check=True,
        )
        streams = json.loads(out.stdout).get('streams', [])
    except (subprocess.SubprocessError, ValueError, OSError):
        logger.warning('Could not probe codecs for %s', path, exc_info=True)
        return None, None

    video = next((s.get('codec_name') for s in streams if s.get('codec_type') == 'video'), None)
    audio = next((s.get('codec_name') for s in streams if s.get('codec_type') == 'audio'), None)
    return video, audio


def needs_transcode(path):
    """True when the media has to be re-encoded rather than just repackaged.

    Rewriting the container cannot change what is inside it. A lecture encoded
    as AV1, VP9 or HEVC plays in some browsers and shows nothing at all in
    others — Safari and iOS in particular — so those have to be re-encoded to
    H.264/AAC, which every current browser can decode.
    """
    video, audio = probe_codecs(path)
    if video and video not in BROWSER_VIDEO_CODECS:
        return True
    if audio and audio not in BROWSER_AUDIO_CODECS:
        return True
    return False


def _report_progress(content_id, field, percent):
    """Record encode progress without letting a write failure kill the job."""
    from content.models import Content

    try:
        Content.objects.filter(pk=content_id).update(**{field: percent})
    except Exception:
        logger.exception('could not record %s for content %s', field, content_id)


def remux_faststart(src_path, dst_path):
    """Stream-copy ``src_path`` into ``dst_path`` with the index up front."""
    subprocess.run(
        [FFMPEG, '-v', 'error', '-y', '-i', src_path,
         '-c', 'copy', '-map', '0', '-movflags', '+faststart', dst_path],
        capture_output=True, text=True, timeout=REMUX_TIMEOUT_SECONDS, check=True,
    )


def transcode_h264(src_path, dst_path, total_seconds=None, on_progress=None):
    """Re-encode to H.264/AAC so every browser can play the result.

    Capped at 1080p: the fallback MP4 only has to be universally playable, and
    letting a 4K source through would cost hours of CPU for a size almost no
    student watches. The adaptive ladder handles quality separately.
    """
    run_with_progress(
        [FFMPEG, '-v', 'error', '-y', '-i', src_path,
         '-map', '0:v:0', '-map', '0:a:0?',
         '-vf', "scale='min(1920,iw)':-2",
         '-c:v', 'libx264', '-preset', TRANSCODE_PRESET, '-crf', '23',
         '-pix_fmt', 'yuv420p',
         '-c:a', 'aac', '-b:a', '128k', '-ac', '2',
         '-movflags', '+faststart', dst_path],
        total_seconds, on_progress, TRANSCODE_TIMEOUT_SECONDS,
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
    """Make an uploaded lecture video start playing immediately and seek.

    Downloads the upload and records its real duration, then repairs whichever
    problem the file has: a trailing index or fragmentation is fixed by a cheap
    stream copy, while a codec browsers cannot all decode needs a real
    re-encode. Never raises into the caller: a failure leaves the original file
    in place.
    """
    from content.models import Content

    try:
        content = Content.objects.get(pk=content_id)
    except Content.DoesNotExist:
        return 'content-missing'

    if not content.video_file:
        return 'no-video'

    source_name = content.video_file.name
    Content.objects.filter(pk=content_id).update(
        video_status='processing', video_progress=0,
    )

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

        faststart, fragmented = inspect_mp4(local_src)
        transcode = needs_transcode(local_src)

        if faststart and not fragmented and not transcode:
            fields['video_status'] = 'ready'
            fields['video_progress'] = 100
            Content.objects.filter(pk=content_id).update(**fields)
            enqueue_hls_packaging(content_id)
            return 'already-faststart'

        if transcode:
            # The container is fine but the codec is not universally playable,
            # so repackaging would not help — the picture has to be re-encoded.
            # That is slow enough to be worth reporting on.
            transcode_h264(
                local_src, local_out, duration,
                lambda pct: _report_progress(content_id, 'video_progress', pct),
            )
            outcome = 'transcoded'
        else:
            remux_faststart(local_src, local_out)
            outcome = 'defragmented' if fragmented else 'remuxed'

        # Save under a fresh name so anyone mid-playback keeps a working URL,
        # then drop the original.
        base = os.path.basename(source_name)
        stem, _ = os.path.splitext(base)
        with open(local_out, 'rb') as fh:
            content.video_file.save(f'{stem}-faststart.mp4', File(fh), save=False)

        # A re-encode changes the duration slightly and the source duration may
        # have been unreadable, so trust the file we actually publish.
        out_duration = probe_duration_seconds(local_out)
        if out_duration:
            fields['video_duration_seconds'] = int(round(out_duration))
            fields['video_duration_minutes'] = max(1, int(round(out_duration / 60)))

        fields['video_status'] = 'ready'
        fields['video_progress'] = 100
        fields['video_file'] = content.video_file.name
        Content.objects.filter(pk=content_id).update(**fields)

        try:
            content.video_file.storage.delete(source_name)
        except Exception:
            logger.warning('Could not delete original video %s', source_name, exc_info=True)

        enqueue_hls_packaging(content_id)
        return outcome

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


def dispatch_video_optimization(content_id):
    """Send a content to the media queue. Returns False if the broker refused.

    Callers that a human is waiting on need to know whether the job was really
    accepted, rather than discovering days later that nothing ran.
    """
    try:
        # retry=False so a dead broker fails immediately instead of blocking
        # the request thread that just finished the upload.
        optimize_content_video.apply_async(
            args=[content_id], queue='media', retry=False, ignore_result=True,
        )
        return True
    except Exception:
        # Broker down — the upload still plays, just without the speed-up.
        logger.warning('Could not queue video optimisation for %s', content_id, exc_info=True)
        return False


def enqueue_video_optimization(content):
    """Queue optimisation for a content row once its transaction commits."""
    from django.conf import settings

    if not getattr(settings, 'VIDEO_OPTIMIZATION_ENABLED', True):
        return
    if not content.pk or not content.video_file:
        return

    content_id = content.pk

    transaction.on_commit(lambda: dispatch_video_optimization(content_id))


HLS_TIMEOUT_SECONDS = int(os.environ.get('VIDEO_TRANSCODE_TIMEOUT', str(6 * 3600)))


@shared_task(
    name='content.package_video_hls',
    bind=True,
    max_retries=1,
    default_retry_delay=300,
    acks_late=True,
    soft_time_limit=HLS_TIMEOUT_SECONDS + 300,
    time_limit=HLS_TIMEOUT_SECONDS + 600,
)
def package_content_hls(self, content_id):
    """Publish an adaptive-bitrate HLS ladder for a content's video.

    Runs after the faststart remux, so the lecture is already watchable while
    this is grinding away. When it finishes the player switches to HLS and
    starts on a small segment instead of a big progressive stream.
    """
    from content.models import Content
    from content import hls

    try:
        content = Content.objects.get(pk=content_id)
    except Content.DoesNotExist:
        return 'content-missing'

    if not content.video_file:
        return 'no-video'

    Content.objects.filter(pk=content_id).update(
        hls_status='processing', hls_progress=0,
    )
    previous = content.hls_playlist
    prefix = f'content_hls/{content_id}'
    workdir = tempfile.mkdtemp(prefix='dt-hls-')
    local_src = os.path.join(workdir, 'source.mp4')
    outdir = os.path.join(workdir, 'out')
    os.makedirs(outdir, exist_ok=True)

    try:
        with content.video_file.open('rb') as remote, open(local_src, 'wb') as local:
            shutil.copyfileobj(remote, local, length=8 * 1024 * 1024)

        rungs = hls.package(
            local_src, outdir,
            content.video_duration_seconds or probe_duration_seconds(local_src),
            lambda pct: _report_progress(content_id, 'hls_progress', pct),
        )

        # Publish under a fresh generation so viewers mid-playback keep the old
        # tree working; the previous generation is removed afterwards.
        generation = posixpath.join(prefix, uuid.uuid4().hex[:8])
        master = hls.upload(outdir, generation)
        if not master:
            raise RuntimeError('HLS packaging produced no master playlist')

        Content.objects.filter(pk=content_id).update(
            hls_playlist=master, hls_status='ready', hls_progress=100,
        )

        if previous:
            old_generation = posixpath.dirname(previous)
            if old_generation and old_generation != generation:
                hls.delete_tree(old_generation)

        return f'packaged:{",".join(r[0] for r in rungs)}'

    except subprocess.TimeoutExpired:
        Content.objects.filter(pk=content_id).update(hls_status='failed')
        logger.error('HLS packaging timed out for content %s', content_id)
        return 'timeout'
    except FileNotFoundError:
        Content.objects.filter(pk=content_id).update(hls_status='failed')
        logger.error('ffmpeg is not available; skipping HLS for %s', content_id)
        return 'ffmpeg-missing'
    except Exception as exc:
        Content.objects.filter(pk=content_id).update(hls_status='failed')
        logger.exception('HLS packaging failed for content %s', content_id)
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            return 'failed'
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def enqueue_hls_packaging(content_id):
    """Queue HLS packaging, tolerating a broker that is not reachable."""
    from django.conf import settings
    from content.models import Content

    if not getattr(settings, 'VIDEO_HLS_ENABLED', True):
        return
    Content.objects.filter(pk=content_id).update(hls_status='pending')
    try:
        package_content_hls.apply_async(
            args=[content_id], queue='media', retry=False, ignore_result=True,
        )
    except Exception:
        logger.warning('Could not queue HLS packaging for %s', content_id, exc_info=True)
