import { useCallback, useEffect, useRef } from 'react'
import { timelineService } from '../services/timelineService'

/**
 * Records a raw per-question interaction timeline for one attempt and syncs
 * it to the server. Raw events only — every interpretation (active time,
 * guesses, slips…) happens server-side in intelligence/services/timeline.py.
 *
 * Event tuples: [t_ms, code, key, value?] — e/l enter/leave a question,
 * h/s tab hidden/shown, a answer set (value = digest), c answer cleared.
 * Never throws and never blocks the attempt: sync failures retry next tick.
 */
const SYNC_MS = 30000
const MAX_EVENTS = 5000
const COALESCE_MS = 1500        // rapid re-answers (typing, toggling) collapse
const KEEPALIVE_LIMIT = 60000   // fetch keepalive bodies must stay small

const newSessionId = () =>
  (typeof crypto !== 'undefined' && crypto.randomUUID)
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`

export default function useResponseTimeline({ attemptKind, attemptId, parentId, currentKey, active }) {
  const enabled = Boolean(active && (attemptId || parentId))
  const targetRef = useRef({})
  targetRef.current = { attemptKind, attemptId, parentId, enabled }

  const sessionRef = useRef(null)     // { id, t0, events, truncated, dirty }
  const currentRef = useRef(null)     // key on screen
  const visibleSinceRef = useRef(null) // perf time the current visible stretch began
  const activeMsRef = useRef({})      // key → visible ms so far

  const now = () => performance.now()

  const session = () => {
    if (!sessionRef.current) {
      sessionRef.current = { id: newSessionId(), t0: now(), events: [], truncated: false, dirty: false }
    }
    return sessionRef.current
  }

  const push = useCallback((code, key = null, value) => {
    const s = session()
    const t = Math.round(now() - s.t0)
    const last = s.events[s.events.length - 1]
    if (code === 'a' && last && last[1] === 'a' && last[2] === key && t - last[0] < COALESCE_MS) {
      last[0] = t
      last[3] = value
      s.dirty = true
      return
    }
    if (s.events.length >= MAX_EVENTS && code !== 'a' && code !== 'c') {
      s.truncated = true
      return
    }
    s.events.push(value === undefined ? [t, code, key] : [t, code, key, value])
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

  const flush = useCallback(async () => {
    const s = sessionRef.current
    if (!targetRef.current.enabled || !s || !s.dirty) return
    s.dirty = false
    try {
      await timelineService.sync(payload())
    } catch {
      s.dirty = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const flushOnHide = () => {
    const s = sessionRef.current
    if (!targetRef.current.enabled || !s || !s.dirty) return
    const body = payload()
    s.dirty = false
    if (JSON.stringify(body).length < KEEPALIVE_LIMIT) {
      timelineService.syncOnUnload(body)
    } else {
      timelineService.sync(body).catch(() => { s.dirty = true })
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
