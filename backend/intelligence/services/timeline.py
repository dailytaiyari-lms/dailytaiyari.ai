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
    the timing window start; durations are seconds."""
    active_s: float = 0.0
    hidden_s: float = 0.0
    visits: int = 0
    first_enter_at_s: float | None = None
    first_answer_active_s: float | None = None
    final_answer_at_s: float | None = None
    answers: list = field(default_factory=list)  # [(at_s, digest | None)]; None = cleared


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
        if isinstance(t, bool) or not isinstance(t, (int, float)) or t < 0:
            raise TimelineError(f'event {index} has a bad time')
        if code not in CODES:
            raise TimelineError(f'event {index} has an unknown code')
        if code in KEYED_CODES and (
                not isinstance(key, str) or not key or len(key) > MAX_KEY_LENGTH):
            raise TimelineError(f'event {index} needs a question key')
        if value is not None and not isinstance(value, dict):
            raise TimelineError(f'event {index} has a bad value')
        cleaned.append((float(t), code, key, value))
    cleaned.sort(key=lambda event: event[0])  # stable: equal times keep order
    return cleaned


def _offset_s(session):
    return float(session.get('offset_ms') or 0) / 1000.0


def window_start_s(sessions, clock):
    """Where the timing window starts, in seconds after the attempt anchor.

    Server-timed attempts run from ``started_at`` itself; client-timed and
    untimed ones from their earliest session (a client-timed row only ever
    keeps one session — see timeline_sync).
    """
    if clock == 'server' or not sessions:
        return 0.0
    return min(_offset_s(session) for session in sessions.values())


def _fold_session(events, base_s, out, known_keys):
    """Fold one session's cleaned events into ``out`` (key → KeyTimeline).
    ``base_s`` is this session's start relative to the window start."""
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
    close(last_t)


def reduce_sessions(sessions, *, clock, known_keys=None):
    """key → KeyTimeline across every session, times relative to the window.

    A stored session that no longer validates is skipped (logged), so one
    corrupt session never hides the others.
    """
    out = {}
    start = window_start_s(sessions, clock)
    for session in sorted((sessions or {}).values(), key=_offset_s):
        try:
            events = clean_events(session.get('events') or [])
        except TimelineError:
            logger.warning('timeline: skipping a corrupt stored session')
            continue
        _fold_session(events, _offset_s(session) - start, out, known_keys)
    return out
