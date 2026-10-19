"""Tests for the video optimisation pipeline's ffmpeg plumbing.

These cover the failure modes that cost us a production incident: a task that
outlives its Celery budget is killed, and because the video tasks use
``acks_late`` the broker redelivers it and the encode restarts from zero — for
ever. Every guard that keeps a run bounded is therefore worth a test.

The ffmpeg-backed cases are skipped where ffmpeg is unavailable, so the suite
still passes on a bare CI image.
"""
import shutil
import subprocess
import time
import unittest

from django.test import SimpleTestCase

from .ffmpeg_utils import _parse_progress_line, run_with_progress
from .tasks import (
    REMUX_TIMEOUT_SECONDS,
    TRANSCODE_TIMEOUT_SECONDS,
    needs_transcode,
    optimize_content_video,
)

HAS_FFMPEG = bool(shutil.which('ffmpeg'))
requires_ffmpeg = unittest.skipUnless(HAS_FFMPEG, 'ffmpeg not installed')

# A source ffmpeg can synthesise, so the tests need no binary fixtures.
LAVFI_SRC = ['-f', 'lavfi', '-i', 'testsrc=size=320x180:rate=25', '-t', '4']


class ParseProgressLineTests(SimpleTestCase):
    """``-progress`` output is parsed into elapsed seconds."""

    def test_out_time_ms_is_microseconds(self):
        # Despite the name, ffmpeg writes microseconds here. Reading it as
        # milliseconds would report 1000x the real position and peg progress
        # at 99% immediately.
        self.assertEqual(_parse_progress_line('out_time_ms=5000000'), 5.0)

    def test_timestamp_form(self):
        self.assertEqual(_parse_progress_line('out_time=00:01:02.500000'), 62.5)

    def test_unparseable_lines_are_ignored(self):
        for line in ('out_time=N/A', 'out_time_ms=N/A', 'frame=120', ''):
            self.assertIsNone(_parse_progress_line(line), line)


class TaskBudgetTests(SimpleTestCase):
    """The Celery budget must cover the slowest path the task can take."""

    def test_time_limit_covers_a_full_transcode(self):
        # The task may remux (fast) or re-encode (hours). Sizing the limit on
        # the remux lets a legitimate transcode be killed mid-flight.
        self.assertGreater(optimize_content_video.soft_time_limit,
                           TRANSCODE_TIMEOUT_SECONDS)
        self.assertGreater(optimize_content_video.time_limit,
                           optimize_content_video.soft_time_limit)

    def test_transcode_budget_exceeds_remux_budget(self):
        self.assertGreater(TRANSCODE_TIMEOUT_SECONDS, REMUX_TIMEOUT_SECONDS)

    def test_broker_redelivery_outlasts_the_hard_limit(self):
        # Redelivery must only ever fire for a genuinely dead worker. If the
        # visibility timeout expires first, a healthy long encode is handed to
        # a second worker that duplicates the work and resets the row.
        from django.conf import settings

        visibility = settings.CELERY_BROKER_TRANSPORT_OPTIONS['visibility_timeout']
        self.assertGreater(visibility, optimize_content_video.time_limit)


@requires_ffmpeg
class RunWithProgressTests(SimpleTestCase):
    """``run_with_progress`` must report progress and stay bounded."""

    def _encode(self, dst, *extra, preset='ultrafast'):
        return ['ffmpeg', '-v', 'error', '-y'] + list(LAVFI_SRC) + [
            '-c:v', 'libx264', '-preset', preset, *extra, dst,
        ]

    def test_progress_is_monotonic_and_never_reaches_100(self):
        seen = []
        with self.settings():
            run_with_progress(self._encode('/dev/null', '-f', 'mp4'),
                              4, seen.append, 120)
        self.assertTrue(seen, 'no progress was reported')
        self.assertEqual(seen, sorted(seen))
        # 100% belongs to the caller, after the upload — not to ffmpeg exiting.
        self.assertLessEqual(max(seen), 99)

    def test_timeout_is_enforced_while_ffmpeg_is_still_running(self):
        # The regression this guards: waiting for the timeout only *after*
        # draining stdout means a slow encode is never interrupted, so the
        # worker blocks until Celery kills it and the broker redelivers.
        started = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            run_with_progress(
                ['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi',
                 '-i', 'testsrc=size=1920x1080:rate=25', '-t', '600',
                 '-c:v', 'libx264', '-preset', 'veryslow', '-f', 'mp4',
                 '/dev/null'],
                600, lambda pct: None, 3,
            )
        # Bounded by the budget, not by the encode finishing.
        self.assertLess(time.monotonic() - started, 60)

    def test_a_chatty_command_does_not_deadlock(self):
        # ffmpeg blocks once the stderr pipe buffer (~64KB) fills. Reading
        # stderr only after stdout is drained therefore hangs on any source
        # that logs per frame, which is exactly when we need the error text.
        run_with_progress(
            ['ffmpeg', '-v', 'debug', '-y'] + LAVFI_SRC +
            ['-c:v', 'libx264', '-preset', 'ultrafast', '-f', 'mp4', '/dev/null'],
            4, lambda pct: None, 120,
        )

    def test_failure_raises_with_stderr_attached(self):
        with self.assertRaises(subprocess.CalledProcessError) as ctx:
            run_with_progress(
                ['ffmpeg', '-v', 'error', '-y', '-i', '/nonexistent.mp4',
                 '-f', 'mp4', '/dev/null'],
                4, lambda pct: None, 60,
            )
        # Without the message the operator cannot tell a bad upload from a
        # broken worker.
        self.assertTrue((ctx.exception.stderr or '').strip())

    def test_unknown_duration_falls_back_to_a_plain_run(self):
        # Progress is a convenience; a missing duration must not fail a job.
        run_with_progress(self._encode('/dev/null', '-f', 'mp4'), None, None, 60)


@requires_ffmpeg
class NeedsTranscodeTests(SimpleTestCase):
    """Only the streams a browser cannot decode should force a re-encode."""

    def _make(self, path, vcodec, acodec):
        subprocess.run(
            ['ffmpeg', '-v', 'error', '-y'] + LAVFI_SRC +
            ['-f', 'lavfi', '-i', 'sine=frequency=440', '-t', '4',
             '-c:v', vcodec, '-c:a', acodec, path],
            check=True, capture_output=True,
        )

    def setUp(self):
        import tempfile

        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_browser_friendly_media_is_left_alone(self):
        path = f'{self.tmp}/ok.mp4'
        self._make(path, 'libx264', 'aac')
        self.assertEqual(needs_transcode(path), (False, False))

    def test_audio_only_mismatch_spares_the_picture(self):
        # Re-encoding H.264 video just because the audio is Opus turns a
        # two-minute job into an hours-long one.
        path = f'{self.tmp}/opus.mkv'
        self._make(path, 'libx264', 'libopus')
        self.assertEqual(needs_transcode(path), (False, True))

    def test_undecodable_video_is_flagged(self):
        path = f'{self.tmp}/vp9.webm'
        self._make(path, 'libvpx-vp9', 'libopus')
        video_bad, _ = needs_transcode(path)
        self.assertTrue(video_bad)

    def test_an_unreadable_file_does_not_claim_a_transcode(self):
        # Probing failures must fail safe: a remux is cheap and reversible,
        # an unnecessary multi-hour re-encode is neither.
        self.assertEqual(needs_transcode(f'{self.tmp}/missing.mp4'), (False, False))
