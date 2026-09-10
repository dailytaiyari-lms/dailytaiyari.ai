"""
Code-execution service.

Thin, swappable interface over a code-execution engine (currently self-hosted
Piston). All engine-specific details live behind `run_code`; the rest of the
app only talks to `execute_submission` / `run_samples`. To move the engine to a
separate host later, only PISTON_URL (env) changes -- no app code changes.

Security note: the engine sandboxes each run (network disabled, process/memory/
output caps, timeouts). We additionally pass explicit per-run limits here.
"""
import logging
from concurrent.futures import ThreadPoolExecutor

import requests
from django.conf import settings

from .languages import LANGUAGES

logger = logging.getLogger(__name__)

# Hard ceilings applied regardless of per-problem config (defense in depth).
MAX_RUN_TIMEOUT_MS = 10_000
MAX_MEMORY_MB = 512
# Wall-clock timeout for the HTTP call to the engine (generous vs run_timeout).
HTTP_TIMEOUT_S = 20
# Default number of test cases to execute concurrently when settings is absent.
DEFAULT_JUDGE_PARALLELISM = 4


class EngineError(Exception):
    """Raised when the execution engine is unreachable or misbehaves."""


def _engine_url():
    return getattr(settings, 'PISTON_URL', 'http://piston:2000').rstrip('/')


def run_code(*, language, source, stdin='', time_limit_ms=3000, memory_limit_mb=256):
    """Execute a single program against one stdin. Returns a normalized dict.

    Raises EngineError on transport/engine failures (never leaks internals).
    """
    lang = LANGUAGES.get(language)
    if not lang:
        raise EngineError(f'Unsupported language: {language}')

    run_timeout = min(int(time_limit_ms or 3000), MAX_RUN_TIMEOUT_MS)
    mem_mb = min(int(memory_limit_mb or 256), MAX_MEMORY_MB)
    mem_bytes = mem_mb * 1024 * 1024

    payload = {
        'language': lang['piston_language'],
        'version': lang['piston_version'],
        'files': [{'name': lang['filename'], 'content': source}],
        'stdin': stdin or '',
        'compile_timeout': 10_000,
        'run_timeout': run_timeout,
        'compile_memory_limit': mem_bytes,
        'run_memory_limit': mem_bytes,
    }

    try:
        resp = requests.post(
            f'{_engine_url()}/api/v2/execute',
            json=payload,
            timeout=HTTP_TIMEOUT_S,
        )
    except requests.RequestException as exc:
        logger.error('Piston request failed: %s', exc)
        raise EngineError('Code execution service is unavailable. Please try again.')

    if resp.status_code != 200:
        logger.error('Piston non-200: %s %s', resp.status_code, resp.text[:300])
        raise EngineError('Code execution failed. Please try again.')

    data = resp.json()
    compile_stage = data.get('compile') or {}
    run_stage = data.get('run') or {}

    compile_ok = compile_stage.get('code', 0) in (0, None)
    compile_output = (compile_stage.get('stderr') or '') + (compile_stage.get('stdout') or '')

    return {
        'compile_ok': compile_ok,
        'compile_output': compile_output.strip(),
        'stdout': run_stage.get('stdout', '') or '',
        'stderr': run_stage.get('stderr', '') or '',
        'exit_code': run_stage.get('code'),
        'signal': run_stage.get('signal'),
        # Piston status: RE/SG/TO/OL/EL/XX or null on success.
        'status': run_stage.get('status'),
        'wall_time_ms': run_stage.get('wall_time'),
        'cpu_time_ms': run_stage.get('cpu_time'),
    }


def _normalize(text):
    """Judge-style normalization: strip trailing spaces per line + trailing blank lines."""
    if text is None:
        return ''
    lines = [ln.rstrip() for ln in text.replace('\r\n', '\n').split('\n')]
    while lines and lines[-1] == '':
        lines.pop()
    return '\n'.join(lines)


def _verdict_for(result, expected):
    """Map an engine result + expected output to a per-test verdict string."""
    status = result.get('status')
    if not result.get('compile_ok'):
        return 'compile_error'
    if status == 'TO':
        return 'time_limit'
    if status in ('OL', 'EL'):
        return 'output_limit'
    if status == 'SG' or result.get('signal'):
        return 'runtime_error'
    if status in ('RE', 'XX') or (result.get('exit_code') not in (0, None)):
        return 'runtime_error'
    if _normalize(result.get('stdout')) == _normalize(expected):
        return 'passed'
    return 'wrong_answer'


def run_against_cases(*, language, source, cases, time_limit_ms, memory_limit_mb, reveal_io):
    """Run source against a list of test cases.

    `cases` is an iterable of objects with .stdin, .expected_output, .points,
    .is_sample, .id, .order. `reveal_io` controls whether stdin/expected/stdout
    are included in the returned per-test detail (True for samples/run, False
    for hidden graded cases so answers never leak to the client).

    Test cases are executed with a bounded thread pool (CODE_JUDGE_PARALLELISM,
    default 1 = sequential). Concurrency is opt-in because Piston's run_timeout
    is wall-clock: parallel runs only stay correct when Piston has that many
    dedicated cores, otherwise CPU contention inflates wall time into spurious
    TIME_LIMIT verdicts. Ordering, scoring, and compile-error semantics are
    preserved regardless of the parallelism level.

    Returns dict: {results[], passed_count, total_count, passed_points,
    total_points, compile_error(bool), compile_output(str)}.
    """
    cases = list(cases)

    def _execute(case):
        return run_code(
            language=language,
            source=source,
            stdin=getattr(case, 'stdin', '') or '',
            time_limit_ms=time_limit_ms,
            memory_limit_mb=memory_limit_mb,
        )

    # Execute cases, filling engine_results in input order. A `None` slot marks a
    # case that was short-circuited after a compile failure (see below) and is
    # reported as a compile_error without being run.
    engine_results = [None] * len(cases)
    if cases:
        # Probe with the first case. Compilation is input-independent, so if the
        # source fails to compile here the whole submission fails -- skip running
        # the remaining cases instead of recompiling the broken source N times.
        engine_results[0] = _execute(cases[0])
        if engine_results[0].get('compile_ok') and len(cases) > 1:
            parallelism = getattr(settings, 'CODE_JUDGE_PARALLELISM', DEFAULT_JUDGE_PARALLELISM)
            # Concurrency only helps with a multi-core Piston; see the setting's
            # docs. map() preserves order and re-raises EngineError to the caller.
            max_workers = max(1, min(int(parallelism or 1), len(cases) - 1))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                for offset, res in enumerate(executor.map(_execute, cases[1:]), start=1):
                    engine_results[offset] = res

    results = []
    passed_count = 0
    passed_points = 0
    total_points = 0
    compile_error = False
    compile_output = ''

    for idx, case in enumerate(cases):
        points = int(getattr(case, 'points', 1) or 0)
        total_points += points

        res = engine_results[idx]
        if res is None:
            # Short-circuited: an earlier case failed to compile.
            results.append({
                'index': idx,
                'is_sample': bool(getattr(case, 'is_sample', False)),
                'verdict': 'compile_error',
                'points': 0,
                'max_points': points,
            })
            continue

        verdict = _verdict_for(res, getattr(case, 'expected_output', '') or '')

        # Compilation is input-independent: a compile failure means the whole
        # submission fails to compile. Record it once for the outcome.
        if verdict == 'compile_error' and not compile_error:
            compile_error = True
            compile_output = res.get('compile_output', '')

        awarded = points if verdict == 'passed' else 0
        if verdict == 'passed':
            passed_count += 1
            passed_points += awarded

        detail = {
            'index': idx,
            'is_sample': bool(getattr(case, 'is_sample', False)),
            'verdict': verdict,
            'points': awarded,
            'max_points': points,
            'time_ms': res.get('wall_time_ms'),
        }
        if reveal_io or getattr(case, 'is_sample', False):
            detail.update({
                'stdin': getattr(case, 'stdin', '') or '',
                'expected_output': getattr(case, 'expected_output', '') or '',
                'stdout': res.get('stdout', ''),
                'stderr': res.get('stderr', ''),
            })
        results.append(detail)

    return {
        'results': results,
        'passed_count': passed_count,
        'total_count': len(results),
        'passed_points': passed_points,
        'total_points': total_points,
        'compile_error': compile_error,
        'compile_output': compile_output,
    }


def engine_health():
    """Check the engine is reachable AND has every runtime we advertise.

    Reachability alone is not enough: Piston starts with an empty package store,
    and in that state it happily serves /api/v2/runtimes (returning `[]`) while
    failing every execute call. Treating that as healthy is what let a
    runtime-less engine 503 every submission unnoticed, so a missing runtime is
    reported as unhealthy here.

    Returns {'ok': bool, 'runtimes': [...], 'missing': [...]} or
    {'ok': False, 'error': str} when the engine cannot be reached.
    """
    try:
        resp = requests.get(f'{_engine_url()}/api/v2/runtimes', timeout=5)
        resp.raise_for_status()
        installed = {
            (r.get('language'), r.get('version'))
            for r in resp.json()
        }
    except (requests.RequestException, ValueError) as exc:
        return {'ok': False, 'error': str(exc)}

    missing = sorted(
        f"{cfg['piston_language']} {cfg['piston_version']}"
        for cfg in LANGUAGES.values()
        if (cfg['piston_language'], cfg['piston_version']) not in installed
    )
    return {
        'ok': not missing,
        'runtimes': sorted(f'{lang} {ver}' for lang, ver in installed if lang),
        'missing': missing,
    }
