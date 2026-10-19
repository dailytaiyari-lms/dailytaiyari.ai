import { useCallback, useEffect, useRef } from 'react'
import { timelineService } from '../services/timelineService'

/**
 * Records a raw per-question interaction timeline for one attempt and syncs
 * it to the server. Raw events only — every interpretation (active time,
 * guesses, slips…) happens server-side in intelligence/services/timeline.py.
 *
 * Event tuples: [t_ms, code, key, value?] — e/l enter/leave a question,
 * h/s tab hidden/shown, a answer set (value = digest), c answer cleared.
 * Never throws and never blocks the attempt: network/5xx failures retry next
 * tick; a 4xx (the server will never accept this session) stops syncing it.
 *
 * Budget: the server rejects >5000 events or a body >256 KB, so the hook
 * counts events and an estimate of their serialized size and drops anything
 * past MAX_EVENTS / MAX_EVENT_BYTES (answers and clears included), marking the
 * session `truncated`. The server then treats items that were answered but
 * never seen in the timeline as having no timing.
 */
const SYNC_MS = 30000
const MAX_EVENTS = 5000
const MAX_EVENT_BYTES = 200000  // leaves headroom for the envelope under the 256 KB cap
const COALESCE_MS = 1500        // rapid re-answers (toggling) collapse
const TYPING_COALESCE_MS = 10000 // free-text / code keystrokes collapse harder
const KEEPALIVE_LIMIT = 60000   // fetch keepalive bodies must stay small
const FINAL_WAIT_MS = 4000      // the pre-submit flush never holds the attempt longer than this

const typingKind = (digest) =>
  (digest && typeof digest === 'object') ? (('txt' in digest) ? 'txt' : (('code' in digest) ? 'code' : null)) : null

const newSessionId = () =>
  (typeof crypto !== 'undefined' && crypto.randomUUID)
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`

export default function useResponseTimeline({ attemptKind, attemptId, parentId, currentKey, active }) {
  const enabled = Boolean(active && (attemptId || parentId))
  const targetRef = useRef({})
  targetRef.current = { attemptKind, attemptId, parentId, enabled }

  const sessionRef = useRef(null)     // { id, t0, events, bytes, truncated, dirty, dead }
  const inflightRef = useRef(Promise.resolve()) // tail of the serialized sync chain
  const currentRef = useRef(null)     // key on screen
  const visibleSinceRef = useRef(null) // perf time the current visible stretch began
  const activeMsRef = useRef({})      // key → visible ms so far

  const now = () => performance.now()

  const session = () => {
    if (!sessionRef.current) {
      sessionRef.current = { id: newSessionId(), t0: now(), events: [], bytes: 0, truncated: false, dirty: false, dead: false }
    }
    return sessionRef.current
  }

  const push = useCallback((code, key = null, value) => {
    const s = session()
    const t = Math.round(now() - s.t0)
    const last = s.events[s.events.length - 1]
    if (code === 'a' && last && last[1] === 'a' && last[2] === key) {
      const kind = typingKind(value)
      const windowMs = (kind && kind === typingKind(last[3])) ? TYPING_COALESCE_MS : COALESCE_MS
      if (t - last[0] < windowMs) {
        const before = JSON.stringify(last).length
        const delta = JSON.stringify([t, last[1], last[2], value]).length - before
        if (s.bytes + delta > MAX_EVENT_BYTES) {
          // the rewrite would outgrow the budget: keep the old digest, flag it
          if (!s.truncated) {
            s.truncated = true
            s.dirty = true
          }
          return
        }
        last[0] = t
        last[3] = value
        s.bytes += delta
        s.dirty = true
        return
      }
    }
    const event = value === undefined ? [t, code, key] : [t, code, key, value]
    const size = JSON.stringify(event).length + 1
    if (s.events.length >= MAX_EVENTS || s.bytes + size > MAX_EVENT_BYTES) {
      if (!s.truncated) {
        s.truncated = true
        s.dirty = true // let the truncated flag reach the server once
      }
      return
    }
    s.events.push(event)
    s.bytes += size
    s.dirty = true
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const pauseClock = () => {
    const key = currentRef.current
    if (key && visibleSinceRef.current != null) {
      activeMsRef.current[key] = (activeMsRef.current[key] || 0) + (now() - visibleSinceRef.current)
    }
    visibleSinceRef.current = null
  }

  const resumeClock = () => {
    if (currentRef.current && !document.hidden) visibleSinceRef.current = now()
  }

  const payload = () => {
    const s = sessionRef.current
    const { attemptKind: kind, attemptId: id, parentId: parent } = targetRef.current
    return {
      attempt_kind: kind,
      ...(id ? { attempt_id: id } : { parent_id: parent }),
      session_id: s.id,
      elapsed_ms: Math.round(now() - s.t0),
      truncated: s.truncated,
      events: s.events,
    }
  }

  // Only network errors, 5xx, 401 (token refresh) and 429 can succeed later.
  const syncFailed = (s, error) => {
    const status = error?.response?.status
    if (!error?.response || status >= 500 || status === 401 || status === 429) s.dirty = true
    else s.dead = true // 400/403/404/409/413…: this session will never be accepted
  }

  // Syncs run one at a time, each building its payload when it starts, so an
  // older snapshot can never land after a newer one and an awaited flush()
  // sends the latest state after any in-flight sync.
  // flush({ final: true }) is the pre-submit call: it sends even when nothing
  // is dirty (time passing never marks the session dirty, and the server needs
  // the final elapsed_ms to credit the last reading time) and resolves after at
  // most FINAL_WAIT_MS so a stalled request can never hold up the submit; the
  // sync itself keeps running.
  const flush = useCallback((options) => {
    const final = Boolean(options && options.final)
    const run = async () => {
      const s = sessionRef.current
      if (!targetRef.current.enabled || !s || s.dead || (!final && !s.dirty)) return
      s.dirty = false
      try {
        await timelineService.sync(payload())
      } catch (error) {
        syncFailed(s, error)
      }
    }
    // then(run, run): a rejected earlier link can never poison the chain.
    const next = inflightRef.current.then(run, run)
    inflightRef.current = next
    if (!final) return next
    return new Promise((resolve) => {
      const timer = setTimeout(resolve, FINAL_WAIT_MS)
      next.then(() => { clearTimeout(timer); resolve() }, () => { clearTimeout(timer); resolve() })
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const flushOnHide = () => {
    const s = sessionRef.current
    if (!targetRef.current.enabled || !s || s.dead || !s.dirty) return
    const json = JSON.stringify(payload())
    if (json.length < KEEPALIVE_LIMIT) {
      s.dirty = false
      timelineService.syncOnUnload(json) // fire-and-forget keepalive fetch
    } else {
      flush()
    }
  }

  // Enter/leave as the question on screen changes (or the hook switches off).
  useEffect(() => {
    const next = enabled ? currentKey || null : null
    if (next === currentRef.current) return
    if (currentRef.current) {
      pauseClock()
      push('l', currentRef.current)
    }
    currentRef.current = next
    if (next) {
      push('e', next)
      resumeClock()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, currentKey, push])

  // Tab visibility, periodic sync and unmount.
  useEffect(() => {
    if (!enabled) return undefined
    const onVisibility = () => {
      if (document.hidden) {
        pauseClock()
        push('h')
        flushOnHide()
      } else {
        push('s')
        resumeClock()
      }
    }
    document.addEventListener('visibilitychange', onVisibility)
    const timer = setInterval(() => { flush() }, SYNC_MS)
    return () => {
      document.removeEventListener('visibilitychange', onVisibility)
      clearInterval(timer)
      if (currentRef.current) {
        pauseClock()
        push('l', currentRef.current)
        currentRef.current = null
      }
      flushOnHide()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, push, flush])

  const recordAnswer = useCallback((key, digest) => {
    // The server rejects the whole session if an 'a' event lacks a dict digest.
    if (!digest || typeof digest !== 'object' || Array.isArray(digest)) return
    if (targetRef.current.enabled && key) push('a', key, digest)
  }, [push])

  const clearAnswer = useCallback((key) => {
    if (targetRef.current.enabled && key) push('c', key)
  }, [push])

  const activeSeconds = useCallback((key) => {
    let ms = activeMsRef.current[key] || 0
    if (key === currentRef.current && visibleSinceRef.current != null) ms += now() - visibleSinceRef.current
    return ms / 1000
  }, [])

  return { recordAnswer, clearAnswer, activeSeconds, flush }
}
