"""Sandboxed notebook grading runner.

A tiny stdlib-only HTTP service that executes an untrusted student notebook and
then runs autograder tests against the resulting namespace. It is the
authoritative grader: the browser's Pyodide score is provisional only.

Contract — POST /execute
    {
      "notebook": {...nbformat v4...},
      "tests": [{"id","name","source","points"}],
      "files": [{"filename","content_b64"}],
      "packages": ["numpy", ...],          # advisory; preinstalled in the image
      "time_limit_ms": 30000,
      "memory_limit_mb": 512
    }
->  {
      "execution_error": "",
      "results": [{"id","name","passed","points","max_points","error"}],
      "stdout": "..."
    }

Isolation (defense in depth — the container is also network-isolated, non-root,
CPU/memory/pids capped, and has no credentials or mounted app code):
  * every request runs in a *fresh forked subprocess*, so student code cannot
    persist state, monkeypatch the server, or affect the next submission;
  * the subprocess sets RLIMIT_AS / RLIMIT_CPU / RLIMIT_FSIZE / RLIMIT_NPROC and
    is hard-killed on wall-clock timeout;
  * it chdirs into a per-request temp directory that is deleted afterwards, so
    students can only write to their own scratch space;
  * matplotlib is forced to the headless Agg backend before any user code runs.
"""
import base64
import contextlib
import io
import json
import multiprocessing
import os
import resource
import shutil
import signal
import sys
import tempfile
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get('NBRUNNER_PORT', '2100'))
# Absolute ceilings, independent of whatever the caller asks for.
MAX_TIMEOUT_S = 180
MAX_MEMORY_MB = 2048
MAX_REQUEST_BYTES = 64 * 1024 * 1024
MAX_STDOUT_CHARS = 20_000
MAX_ERROR_CHARS = 4_000
# Cap on output written to the scratch directory (bytes).
MAX_FILE_SIZE = 128 * 1024 * 1024


def _source_to_text(source):
    if isinstance(source, list):
        return ''.join(str(part) for part in source)
    return '' if source is None else str(source)


def _user_traceback(prefix):
    """Format the current exception showing only the *user's* frames.

    Keeps the runner's own file out of student-visible output (both to avoid
    confusing noise and to not disclose the grader's internals).
    """
    exc_type, exc, tb = sys.exc_info()
    frames = [
        f for f in traceback.extract_tb(tb)
        if f.filename.startswith('<cell ') or f.filename.startswith('<test ')
    ]
    lines = [prefix] if prefix else []
    if frames:
        lines.extend(line.rstrip('\n') for line in traceback.format_list(frames[-5:]))
    lines.extend(
        line.rstrip('\n') for line in traceback.format_exception_only(exc_type, exc)
    )
    return '\n'.join(lines)


def _apply_limits(memory_mb, cpu_seconds):
    """Apply POSIX resource limits to the current (child) process."""
    mem_bytes = int(memory_mb) * 1024 * 1024
    for limit, value in (
        (resource.RLIMIT_AS, mem_bytes),
        (resource.RLIMIT_DATA, mem_bytes),
        (resource.RLIMIT_CPU, int(cpu_seconds)),
        (resource.RLIMIT_FSIZE, MAX_FILE_SIZE),
        (resource.RLIMIT_CORE, 0),
    ):
        try:
            soft, hard = resource.getrlimit(limit)
            ceiling = value if hard == resource.RLIM_INFINITY else min(value, hard)
            resource.setrlimit(limit, (ceiling, ceiling))
        except (ValueError, OSError):
            pass
    # Cap process/thread creation so a fork bomb can't escape the pids_limit.
    try:
        resource.setrlimit(resource.RLIMIT_NPROC, (256, 256))
    except (ValueError, OSError):
        pass


def _grade(payload, conn):
    """Child-process entry point: execute the notebook, then run the tests."""
    workdir = tempfile.mkdtemp(prefix='nb-')
    outcome = {'execution_error': '', 'results': [], 'stdout': ''}
    try:
        memory_mb = min(int(payload.get('memory_limit_mb') or 512), MAX_MEMORY_MB)
        timeout_s = min(
            max(int(payload.get('time_limit_ms') or 30_000) // 1000, 1), MAX_TIMEOUT_S,
        )
        os.chdir(workdir)

        for item in payload.get('files') or []:
            name = os.path.basename(str(item.get('filename') or '')).strip()
            if not name or name.startswith('.'):
                continue
            try:
                with open(os.path.join(workdir, name), 'wb') as fh:
                    fh.write(base64.b64decode(item.get('content_b64') or ''))
            except (ValueError, OSError):
                continue

        # Limits go on *after* dataset staging so writing them can't trip
        # RLIMIT_FSIZE accounting against the student's budget.
        _apply_limits(memory_mb, timeout_s)

        namespace = {'__name__': '__main__', '__builtins__': __builtins__}
        stdout = io.StringIO()

        preamble = (
            'import matplotlib\n'
            'matplotlib.use("Agg")\n'
            'import warnings\n'
            'warnings.filterwarnings("ignore")\n'
        )
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stdout):
            try:
                exec(compile(preamble, '<preamble>', 'exec'), namespace)  # noqa: S102
            except Exception:  # noqa: BLE001 - matplotlib may be absent; harmless
                pass

            cells = (payload.get('notebook') or {}).get('cells') or []
            code_index = 0
            for cell in cells:
                if not isinstance(cell, dict) or cell.get('cell_type') != 'code':
                    continue
                code_index += 1
                source = _source_to_text(cell.get('source'))
                if not source.strip():
                    continue
                try:
                    exec(compile(source, f'<cell {code_index}>', 'exec'), namespace)  # noqa: S102
                except SystemExit:
                    continue
                except BaseException:  # noqa: BLE001 - report, then stop executing
                    outcome['execution_error'] = _user_traceback(
                        f'Cell {code_index} raised an error:'
                    )[:MAX_ERROR_CHARS]
                    break

            # Tests still run after an execution error: some may not depend on
            # the failing cell, so the student keeps any points they earned.
            for test in payload.get('tests') or []:
                entry = {
                    'id': test.get('id'),
                    'name': test.get('name') or '',
                    'passed': False,
                    'points': 0,
                    'max_points': int(test.get('points') or 0),
                    'error': '',
                }
                source = _source_to_text(test.get('source'))
                if not source.strip():
                    entry['passed'] = True
                    entry['points'] = entry['max_points']
                    outcome['results'].append(entry)
                    continue
                try:
                    exec(compile(source, f'<test {entry["name"]}>', 'exec'), namespace)  # noqa: S102
                except AssertionError as exc:
                    entry['error'] = (str(exc) or 'Assertion failed.')[:MAX_ERROR_CHARS]
                except BaseException as exc:  # noqa: BLE001
                    entry['error'] = f'{type(exc).__name__}: {exc}'[:MAX_ERROR_CHARS]
                else:
                    entry['passed'] = True
                    entry['points'] = entry['max_points']
                outcome['results'].append(entry)

        outcome['stdout'] = stdout.getvalue()[:MAX_STDOUT_CHARS]
    except MemoryError:
        outcome['execution_error'] = 'The notebook ran out of memory.'
    except BaseException:  # noqa: BLE001
        outcome['execution_error'] = _user_traceback(
            'The notebook could not be executed.'
        )[:MAX_ERROR_CHARS]
    finally:
        with contextlib.suppress(OSError):
            os.chdir('/')
        shutil.rmtree(workdir, ignore_errors=True)
        with contextlib.suppress(Exception):
            conn.send(outcome)
        with contextlib.suppress(Exception):
            conn.close()


def run_request(payload):
    """Run one grading request in an isolated subprocess with a hard timeout."""
    timeout_s = min(
        max(int(payload.get('time_limit_ms') or 30_000) // 1000, 1), MAX_TIMEOUT_S,
    )
    # Grace on top of the in-child CPU limit so CPU-bound code hits RLIMIT_CPU
    # first (clean error) and only truly stuck code hits the wall-clock kill.
    wall_timeout = timeout_s + 15

    ctx = multiprocessing.get_context('fork')
    parent_conn, child_conn = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=_grade, args=(payload, child_conn), daemon=True)
    proc.start()
    child_conn.close()

    result = None
    if parent_conn.poll(wall_timeout):
        try:
            result = parent_conn.recv()
        except EOFError:
            result = None
    with contextlib.suppress(Exception):
        parent_conn.close()

    if proc.is_alive():
        proc.terminate()
        proc.join(3)
        if proc.is_alive():
            with contextlib.suppress(OSError):
                os.kill(proc.pid, signal.SIGKILL)
            proc.join(2)

    if result is None:
        tests = payload.get('tests') or []
        return {
            'execution_error': (
                f'The notebook took longer than {timeout_s}s to run and was stopped. '
                'Reduce the work done at the top level (smaller data, fewer '
                'iterations) and submit again.'
            ),
            'results': [
                {
                    'id': t.get('id'), 'name': t.get('name') or '', 'passed': False,
                    'points': 0, 'max_points': int(t.get('points') or 0),
                    'error': 'Not run: the notebook timed out.',
                }
                for t in tests
            ],
            'stdout': '',
        }
    return result


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'nbrunner'

    def _send(self, code, body):
        raw = json.dumps(body).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path.rstrip('/') in ('/health', ''):
            self._send(200, {'status': 'ok'})
        else:
            self._send(404, {'error': 'not found'})

    def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path.rstrip('/') != '/execute':
            self._send(404, {'error': 'not found'})
            return
        try:
            length = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_REQUEST_BYTES:
            self._send(413, {'error': 'request too large'})
            return
        try:
            payload = json.loads(self.rfile.read(length) or b'{}')
        except ValueError:
            self._send(400, {'error': 'invalid JSON'})
            return
        if not isinstance(payload, dict):
            self._send(400, {'error': 'invalid payload'})
            return
        try:
            self._send(200, run_request(payload))
        except Exception:  # noqa: BLE001 - never take the server down
            traceback.print_exc()
            self._send(500, {'error': 'runner failure'})

    def log_message(self, fmt, *args):
        sys.stderr.write('nbrunner %s\n' % (fmt % args))


def main():
    server = ThreadingHTTPServer(('0.0.0.0', PORT), Handler)
    server.daemon_threads = True
    sys.stderr.write(f'nbrunner listening on :{PORT}\n')
    server.serve_forever()


if __name__ == '__main__':
    main()
