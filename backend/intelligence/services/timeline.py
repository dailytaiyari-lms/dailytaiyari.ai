"""Raw interaction timelines → per-question timing facts (pure reduction).

The browser records only raw events (``hooks/useResponseTimeline.js``); every
interpretation happens here so it is versioned and testable. Event tuples are
``[t_ms, code, key, value?]`` with ``t_ms`` relative to the session start:

    e / l   enter / leave a question       h / s   tab hidden / shown
    a       answer set (value = digest)    c       answer cleared

Digests: ``{"sel": [1, 3]}``, ``{"num": "3.14"}``, ``{"txt": 120}``,
``{"code": 480}``.
"""
import logging
import math
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

MAX_EVENTS = 5000
CODES = {'e', 'l', 'h', 's', 'a', 'c'}
KEYED_CODES = {'e', 'l', 'a', 'c'}
MAX_KEY_LENGTH = 80


class TimelineError(ValueError):
    """Malformed payload — rejected whole, never partially stored."""


@dataclass
class KeyTimeline:
    """What one question's timeline says. ``*_at_s`` are seconds relative to
    the timing window start; durations are seconds.

    ``final_answer_at_s`` is the time of the last answer change, set or clear
    (a trailing clear counts)."""
    active_s: float = 0.0
    hidden_s: float = 0.0
    visits: int = 0
    first_enter_at_s: float | None = None
    first_answer_active_s: float | None = None
    final_answer_at_s: float | None = None
    answers: list = field(default_factory=list)  # [(at_s, digest | None)]; None = cleared


def _valid_number(value):
    """A real, finite, non-negative number (huge ints overflow float: invalid)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def clean_events(events):
    """Validate a session's events; return (t_ms, code, key, value) sorted by t."""
    if not isinstance(events, list):
        raise TimelineError('events must be a list')
    if len(events) > MAX_EVENTS:
        raise TimelineError(f'at most {MAX_EVENTS} events per session')
    cleaned = []
    for index, raw in enumerate(events):
        if not isinstance(raw, (list, tuple)) or len(raw) < 2:
            raise TimelineError(f'event {index} is not a tuple')
        t, code = raw[0], raw[1]
        key = raw[2] if len(raw) > 2 else None
        value = raw[3] if len(raw) > 3 else None
        if not _valid_number(t):
            raise TimelineError(f'event {index} has a bad time')
        if code not in CODES:
            raise TimelineError(f'event {index} has an unknown code')
        if code in KEYED_CODES and (
                not isinstance(key, str) or not key or len(key) > MAX_KEY_LENGTH):
            raise TimelineError(f'event {index} needs a question key')
        if value is not None and not isinstance(value, dict):
            raise TimelineError(f'event {index} has a bad value')
        if code == 'a' and value is None:
            raise TimelineError(f'event {index} is an answer without a digest')
        cleaned.append((float(t), code, key, value))
    cleaned.sort(key=lambda event: event[0])  # stable: equal times keep order
    return cleaned


def _offset_s(session):
    """Session start in seconds, or None when the stored session is corrupt."""
    if not isinstance(session, dict):
        return None
    raw = session.get('offset_ms')
    if raw is None:
        return 0.0
    if not _valid_number(raw):
        return None
    return float(raw) / 1000.0


def _valid_sessions(sessions):
    """[(offset_s, session)] for sessions with a usable offset, in offset order."""
    valid = []
    for session in (sessions.values() if isinstance(sessions, dict) else ()):
        offset = _offset_s(session)
        if offset is None:
            logger.warning('timeline: skipping a corrupt stored session')
            continue
        valid.append((offset, session))
    valid.sort(key=lambda pair: pair[0])
    return valid


def window_start_s(sessions, clock):
    """Where the timing window starts, in seconds after the attempt anchor.

    Server-timed attempts run from ``started_at`` itself; client-timed and
    untimed ones from their earliest session (a client-timed row only ever
    keeps one session — see timeline_sync).
    """
    if clock == 'server':
        return 0.0
    valid = _valid_sessions(sessions)
    return valid[0][0] if valid else 0.0


def _fold_session(events, base_s, out, known_keys, end_ms=None):
    """Fold one session's cleaned events into ``out`` (key → KeyTimeline).
    ``base_s`` is this session's start relative to the window start. A visit
    still open at the end closes at ``max(last event, end_ms)`` — the final
    pre-submit snapshot has an ``e`` but no ``l`` for the question on screen."""
    current = None        # key on screen
    entered = None        # t (ms) the current visit began
    visit_hidden = 0.0    # hidden ms already closed inside this visit
    hidden_since = None   # t (ms) the tab went hidden; None while visible

    def line(key):
        return out.setdefault(key, KeyTimeline())

    def open_hidden(t):
        return (t - max(hidden_since, entered)) if hidden_since is not None else 0.0

    def close(t):
        nonlocal current, entered, visit_hidden
        if current is None:
            return
        duration = max(0.0, t - entered)
        hidden = min(max(0.0, visit_hidden + open_hidden(t)), duration)
        kt = line(current)
        kt.active_s += (duration - hidden) / 1000.0
        kt.hidden_s += hidden / 1000.0
        current, entered, visit_hidden = None, None, 0.0

    def active_so_far(key, t):
        total = line(key).active_s
        if current == key:
            total += max(0.0, (t - entered) - visit_hidden - open_hidden(t)) / 1000.0
        return total

    last_t = 0.0
    for t, code, key, value in events:
        last_t = t
        if key is not None and known_keys is not None and key not in known_keys:
            if code == 'e':
                close(t)  # an unknown question still ends the previous visit
            continue
        at_s = base_s + t / 1000.0
        if code == 'e':
            close(t)
            current, entered, visit_hidden = key, t, 0.0
            kt = line(key)
            kt.visits += 1
            if kt.first_enter_at_s is None or at_s < kt.first_enter_at_s:
                kt.first_enter_at_s = at_s
        elif code == 'l':
            if key == current:
                close(t)
        elif code == 'h':
            if hidden_since is None:
                hidden_since = t
        elif code == 's':
            if hidden_since is not None:
                if current is not None:
                    visit_hidden += t - max(hidden_since, entered)
                hidden_since = None
        else:  # 'a' / 'c'
            kt = line(key)
            if code == 'a' and kt.first_answer_active_s is None:
                kt.first_answer_active_s = active_so_far(key, t)
            kt.answers.append((at_s, value if code == 'a' else None))
            if kt.final_answer_at_s is None or at_s > kt.final_answer_at_s:
                kt.final_answer_at_s = at_s
    close(max(last_t, end_ms) if _valid_number(end_ms) else last_t)


def reduce_sessions(sessions, *, clock, known_keys=None):
    """key → KeyTimeline across every session, times relative to the window.

    A stored session that no longer validates is skipped (logged), so one
    corrupt session never hides the others.
    """
    out = {}
    start = window_start_s(sessions, clock)
    for offset, session in _valid_sessions(sessions):
        try:
            events = clean_events(session.get('events') or [])
        except TimelineError:
            logger.warning('timeline: skipping a corrupt stored session')
            continue
        _fold_session(events, offset - start, out, known_keys,
                      end_ms=session.get('elapsed_ms'))
    for kt in out.values():
        kt.answers.sort(key=lambda answer: answer[0])  # stable: ties keep order
    return out
