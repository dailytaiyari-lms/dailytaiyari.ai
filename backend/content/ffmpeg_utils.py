"""Running ffmpeg while reporting how far along it is.

Re-encoding a two-hour lecture takes many minutes, and without feedback the
admin screen cannot tell "working" apart from "stuck". ffmpeg will describe its
own progress on a pipe, so we read that and convert it into a percentage of the
clip's known duration.
"""
import logging
import subprocess

logger = logging.getLogger(__name__)


def _parse_progress_line(line):
    """Return elapsed output seconds from a `-progress` line, or None."""
    key, _, value = line.partition('=')
    key = key.strip()
    value = value.strip()
    if not value or value == 'N/A':
        return None
    # ffmpeg reports microseconds as out_time_us (older builds: out_time_ms,
    # which despite the name is also microseconds).
    if key in ('out_time_us', 'out_time_ms'):
        try:
            return int(value) / 1_000_000
        except ValueError:
            return None
    if key == 'out_time':
        # HH:MM:SS.ffffff
        parts = value.split(':')
        try:
            hours, minutes, seconds = (float(p) for p in parts)
        except ValueError:
            return None
        return hours * 3600 + minutes * 60 + seconds
    return None


def run_with_progress(cmd, total_seconds, on_progress, timeout, min_step=2):
    """Run an ffmpeg command, calling ``on_progress(percent)`` as it advances.

    ``cmd`` must be a plain ffmpeg argument list; the progress flags are added
    here. ``on_progress`` is throttled to whole-percent steps of at least
    ``min_step`` so a long encode cannot flood the database with writes.

    Falls back silently to a plain run when the duration is unknown — progress
    is a convenience, and a missing percentage must never fail an encode.
    """
    if not total_seconds or total_seconds <= 0 or on_progress is None:
        subprocess.run(cmd, capture_output=True, text=True,
                       timeout=timeout, check=True)
        return

    # `-progress pipe:1` writes machine-readable key=value lines to stdout;
    # `-nostats` silences the human-readable bar that would interleave with it.
    full = [cmd[0], '-progress', 'pipe:1', '-nostats'] + list(cmd[1:])

    proc = subprocess.Popen(
        full, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    last_reported = -min_step
    try:
        for line in proc.stdout:
            elapsed = _parse_progress_line(line)
            if elapsed is None:
                continue
            percent = int(min(99, max(0, elapsed / total_seconds * 100)))
            if percent - last_reported >= min_step:
                last_reported = percent
                try:
                    on_progress(percent)
                except Exception:  # never let reporting break the encode
                    logger.exception('progress callback failed')
        stderr = proc.stderr.read()
        proc.wait(timeout=timeout)
    except BaseException:
        proc.kill()
        proc.wait()
        raise

    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, full, stderr=stderr)
