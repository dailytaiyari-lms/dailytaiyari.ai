"""Notebook execution service.

Thin, swappable interface over the notebook grading engine (a small, network-
isolated Python container — see ``deploy/nbrunner/``). All engine-specific
details live behind ``execute_notebook``; the rest of the app only talks to
``grade_notebook``. Mirrors ``coding/services.py`` so the engine can be moved
to a separate host later by changing only NBRUNNER_URL.

Security note: the runner executes untrusted student code. It runs as a
non-root user on an internal-only Docker network with no published ports, with
per-request CPU/memory/wall-clock caps enforced inside the container and hard
resource caps on the container itself.
"""
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

# Hard ceilings applied regardless of per-notebook config (defense in depth).
MAX_RUN_TIMEOUT_MS = 120_000
MAX_MEMORY_MB = 2048
# Wall-clock timeout for the HTTP call (generous vs the in-runner timeout, so
# the runner's own timeout fires first and we get structured results back).
HTTP_TIMEOUT_S = 180
# Cap on how much dataset content we ship to the runner per request.
MAX_DATASET_BYTES = 25 * 1024 * 1024


class EngineError(Exception):
    """Raised when the execution engine is unreachable or misbehaves."""


def _engine_url():
    return getattr(settings, 'NBRUNNER_URL', 'http://nbrunner:2100').rstrip('/')


def is_enabled():
    return bool(getattr(settings, 'NOTEBOOKS_SERVER_GRADING', False))


def _dataset_payload(notebook):
    """Read the notebook's datasets into an inline payload for the runner.

    Files are sent by value rather than by URL so the runner needs no network
    and no storage credentials.
    """
    import base64

    files = []
    budget = MAX_DATASET_BYTES
    for dataset in notebook.datasets.all().order_by('order', 'created_at'):
        if not dataset.file:
            continue
        try:
            with dataset.file.open('rb') as fh:
                content = fh.read(budget + 1)
        except Exception as exc:  # noqa: BLE001 - a missing file must not kill grading
            logger.warning('Notebook dataset %s unreadable: %s', dataset.id, exc)
            continue
        if len(content) > budget:
            logger.warning(
                'Notebook %s datasets exceed %s bytes; truncating the set.',
                notebook.id, MAX_DATASET_BYTES,
            )
            break
        budget -= len(content)
        files.append({
            'filename': dataset.filename,
            'content_b64': base64.b64encode(content).decode('ascii'),
        })
    return files


def execute_notebook(*, notebook_json, tests, datasets=None, packages=None,
                     time_limit_ms=30_000, memory_limit_mb=512):
    """Execute a notebook then run each test in its namespace.

    Returns the runner's normalized response:
        {
          "execution_error": str,
          "results": [{"id","name","passed","points","max_points","error"}...],
          "stdout": str,
        }
    Raises EngineError on transport/engine failures (never leaks internals).
    """
    payload = {
        'notebook': notebook_json,
        'tests': tests,
        'files': datasets or [],
        'packages': packages or [],
        'time_limit_ms': min(int(time_limit_ms or 30_000), MAX_RUN_TIMEOUT_MS),
        'memory_limit_mb': min(int(memory_limit_mb or 512), MAX_MEMORY_MB),
    }

    try:
        resp = requests.post(
            f'{_engine_url()}/execute', json=payload, timeout=HTTP_TIMEOUT_S,
        )
    except requests.RequestException as exc:
        logger.error('nbrunner request failed: %s', exc)
        raise EngineError('Notebook grading service is unavailable. Please try again.')

    if resp.status_code != 200:
        logger.error('nbrunner non-200: %s %s', resp.status_code, resp.text[:300])
        raise EngineError('Notebook grading failed. Please try again.')

    try:
        data = resp.json()
    except ValueError as exc:
        logger.error('nbrunner returned non-JSON: %s', exc)
        raise EngineError('Notebook grading failed. Please try again.')

    return {
        'execution_error': str(data.get('execution_error') or ''),
        'results': data.get('results') or [],
        'stdout': str(data.get('stdout') or '')[:20_000],
    }


def grade_notebook(notebook, notebook_json):
    """Run every test for `notebook` against `notebook_json`; return an outcome.

    Outcome shape mirrors coding.services.run_against_cases:
        {results, passed_count, total_count, passed_points, total_points,
         execution_error}
    """
    tests = list(notebook.tests.all().order_by('order', 'created_at'))
    if not tests:
        return {
            'results': [], 'passed_count': 0, 'total_count': 0,
            'passed_points': 0, 'total_points': 0, 'execution_error': '',
        }

    engine_response = execute_notebook(
        notebook_json=notebook_json,
        tests=[
            {'id': str(t.id), 'name': t.name, 'source': t.source, 'points': t.points}
            for t in tests
        ],
        datasets=_dataset_payload(notebook),
        packages=notebook.normalized_packages(),
        time_limit_ms=notebook.time_limit_ms,
        memory_limit_mb=notebook.memory_limit_mb,
    )

    by_id = {r.get('id'): r for r in engine_response['results'] if isinstance(r, dict)}
    results = []
    passed_count = 0
    passed_points = 0
    total_points = 0
    for index, test in enumerate(tests):
        raw = by_id.get(str(test.id)) or {}
        passed = bool(raw.get('passed'))
        awarded = test.points if passed else 0
        total_points += test.points
        passed_count += 1 if passed else 0
        passed_points += awarded
        error = str(raw.get('error') or '')
        if not passed and test.failure_hint:
            error = test.failure_hint
        results.append({
            'index': index,
            'id': str(test.id),
            'name': test.name,
            'grade_id': test.grade_id,
            'is_hidden': test.is_hidden,
            'passed': passed,
            'points': awarded,
            'max_points': test.points,
            'error': error[:2000],
        })

    return {
        'results': results,
        'passed_count': passed_count,
        'total_count': len(tests),
        'passed_points': passed_points,
        'total_points': total_points,
        'execution_error': engine_response['execution_error'][:5000],
    }
