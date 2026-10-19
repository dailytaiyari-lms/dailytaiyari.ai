"""HLS (HTTP Live Streaming) packaging for uploaded lecture videos.

A progressive MP4 is one file at one bitrate. Even with the index up front the
browser must pull that single stream at whatever bitrate it was encoded at, so
a 1080p lecture stays painful on a weak connection.

HLS instead cuts the lecture into a few seconds of video per segment and offers
several quality ladders side by side. The player downloads one small segment to
start — a second or two of data regardless of how long the lecture is — and
keeps fetching the next segments while the current one plays, stepping up or
down the ladder as the viewer's bandwidth changes.
"""
import json
import logging
import mimetypes
import os
import posixpath
import subprocess

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from .ffmpeg_utils import run_with_progress

logger = logging.getLogger(__name__)

FFMPEG = os.environ.get('FFMPEG_BINARY', 'ffmpeg')
FFPROBE = os.environ.get('FFPROBE_BINARY', 'ffprobe')

TRANSCODE_TIMEOUT_SECONDS = int(os.environ.get('VIDEO_TRANSCODE_TIMEOUT', str(6 * 3600)))
SEGMENT_SECONDS = int(os.environ.get('VIDEO_HLS_SEGMENT_SECONDS', '4'))
# veryfast keeps a two hour lecture within a sensible wall clock on a modest VM
# while costing only a little size compared with slower presets.
PRESET = os.environ.get('VIDEO_HLS_PRESET', 'veryfast')

# name, height, video kbps, max kbps, buffer kbps, audio kbps
LADDER = [
    ('360p', 360, 700, 800, 1200, 96),
    ('480p', 480, 1300, 1450, 2100, 128),
    ('720p', 720, 2600, 2900, 4200, 128),
    ('1080p', 1080, 5000, 5500, 7500, 192),
]

# Python does not know these out of the box, and Safari refuses a playlist that
# is served as application/octet-stream.
mimetypes.add_type('application/vnd.apple.mpegurl', '.m3u8')
mimetypes.add_type('video/mp2t', '.ts')


def probe_streams(path):
    """Return ``(height, has_audio)`` for the first video stream."""
    try:
        out = subprocess.run(
            [FFPROBE, '-v', 'error', '-show_entries',
             'stream=codec_type,height', '-of', 'json', path],
            capture_output=True, text=True, timeout=180, check=True,
        )
        streams = json.loads(out.stdout).get('streams', [])
    except (subprocess.SubprocessError, ValueError, OSError):
        logger.warning('Could not probe streams for %s', path, exc_info=True)
        return None, True

    height = next((s.get('height') for s in streams
                   if s.get('codec_type') == 'video' and s.get('height')), None)
    has_audio = any(s.get('codec_type') == 'audio' for s in streams)
    return height, has_audio


def ladder_for(height):
    """The rungs worth producing for a source of the given height.

    Never upscale — encoding a 480p lecture at 1080p costs bandwidth and buys
    nothing. Always keep at least the lowest rung so there is something to fall
    back to on a bad connection.
    """
    if not height:
        return [rung for rung in LADDER if rung[1] <= 720]
    usable = [rung for rung in LADDER if rung[1] <= height]
    return usable or [LADDER[0]]


def build_command(src, outdir, rungs, has_audio):
    """ffmpeg invocation producing every rung plus a master playlist."""
    count = len(rungs)
    split = f'[0:v]split={count}' + ''.join(f'[v{i}]' for i in range(count))
    scales = ';'.join(
        # -2 keeps the aspect ratio and rounds the width to an even number,
        # which h264 requires.
        f'[v{i}]scale=-2:{rung[1]}[v{i}out]' for i, rung in enumerate(rungs)
    )

    cmd = [FFMPEG, '-v', 'error', '-y', '-i', src,
           '-filter_complex', f'{split};{scales}']

    for i, (_name, _h, vkbps, maxk, bufk, akbps) in enumerate(rungs):
        cmd += [
            '-map', f'[v{i}out]',
            f'-c:v:{i}', 'libx264', '-preset', PRESET,
            f'-b:v:{i}', f'{vkbps}k',
            f'-maxrate:v:{i}', f'{maxk}k',
            f'-bufsize:v:{i}', f'{bufk}k',
        ]
        if has_audio:
            cmd += ['-map', 'a:0', f'-c:a:{i}', 'aac', f'-b:a:{i}', f'{akbps}k', '-ac', '2']

    # Segments can only be cut on a keyframe, so pin one every segment boundary
    # across every rung. Without this the ladders are not aligned and the player
    # cannot switch quality mid-stream.
    cmd += [
        '-force_key_frames', f'expr:gte(t,n_forced*{SEGMENT_SECONDS})',
        '-sc_threshold', '0',
        '-pix_fmt', 'yuv420p',
        '-f', 'hls',
        '-hls_time', str(SEGMENT_SECONDS),
        '-hls_playlist_type', 'vod',
        '-hls_flags', 'independent_segments',
        '-hls_segment_type', 'mpegts',
        '-hls_segment_filename', os.path.join(outdir, 'v%v', 'seg_%05d.ts'),
        '-master_pl_name', 'master.m3u8',
        '-var_stream_map',
        ' '.join(
            f'v:{i},a:{i},name:{rung[0]}' if has_audio else f'v:{i},name:{rung[0]}'
            for i, rung in enumerate(rungs)
        ),
        os.path.join(outdir, 'v%v', 'index.m3u8'),
    ]
    return cmd


def package(src_path, outdir, total_seconds=None, on_progress=None):
    """Transcode ``src_path`` into an HLS ladder inside ``outdir``."""
    height, has_audio = probe_streams(src_path)
    rungs = ladder_for(height)
    # `%v` in the output paths expands to the rung name from var_stream_map.
    for rung in rungs:
        os.makedirs(os.path.join(outdir, f'v{rung[0]}'), exist_ok=True)

    run_with_progress(
        build_command(src_path, outdir, rungs, has_audio),
        total_seconds, on_progress, TRANSCODE_TIMEOUT_SECONDS,
    )
    return rungs


def upload(outdir, prefix, storage=None):
    """Push the packaged tree to storage; return the master playlist's name.

    Segments are uploaded before the playlists that reference them so a player
    can never fetch a playlist pointing at a segment that is not there yet.
    """
    storage = storage or default_storage
    master_name = None
    playlists = []

    for root, _dirs, files in os.walk(outdir):
        rel_dir = os.path.relpath(root, outdir)
        for filename in sorted(files):
            rel = filename if rel_dir == '.' else posixpath.join(*rel_dir.split(os.sep), filename)
            target = posixpath.join(prefix, rel)
            if filename.endswith('.m3u8'):
                playlists.append((os.path.join(root, filename), target, filename))
                continue
            _save(storage, os.path.join(root, filename), target)

    for local, target, filename in playlists:
        saved = _save(storage, local, target)
        if filename == 'master.m3u8':
            master_name = saved

    return master_name


def _save(storage, local_path, target):
    # Overwrite rather than let the backend append a suffix: playlists point at
    # their segments by relative name, so the names have to be exactly these.
    if storage.exists(target):
        try:
            storage.delete(target)
        except Exception:
            logger.warning('Could not replace %s', target, exc_info=True)
    with open(local_path, 'rb') as fh:
        return storage.save(target, ContentFile(fh.read()))


def delete_tree(prefix, storage=None):
    """Best-effort removal of a previously published HLS tree."""
    storage = storage or default_storage
    try:
        dirs, files = storage.listdir(prefix)
    except Exception:
        return
    for name in files:
        try:
            storage.delete(posixpath.join(prefix, name))
        except Exception:
            logger.warning('Could not delete %s/%s', prefix, name, exc_info=True)
    for name in dirs:
        delete_tree(posixpath.join(prefix, name), storage=storage)
