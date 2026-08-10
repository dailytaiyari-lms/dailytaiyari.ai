import { useCallback, useEffect, useRef, useState } from 'react'

/* ===========================================================================
 * useGenerationJob — drive a background AI generation job from the client.
 *
 * Both AI job families (the course studio and the notebook generator) expose
 * the same contract: `start` returns a job, the job sits in `pending` /
 * `generating` while a Celery worker writes the draft, and `getJob` is polled
 * until it settles on `preview` (ready to review) or `failed`.
 *
 * Authoring runs can take minutes, so this deliberately never races a request
 * timeout: the POST returns immediately and everything after that is polling.
 * ========================================================================= */

const RUNNING_STATUSES = new Set(['pending', 'generating'])
const DEFAULT_INTERVAL = 2500
// Give up after ~15 min rather than polling a dead job forever.
const MAX_POLLS = 360

export const isJobRunning = (job) => !!job && RUNNING_STATUSES.has(job.status)

/**
 * @param {(jobId: string) => Promise<object>} fetchJob  Loads the latest job.
 * @param {{ interval?: number, onSettled?: (job) => void }} opts
 */
const useGenerationJob = (fetchJob, { interval = DEFAULT_INTERVAL, onSettled } = {}) => {
    const [job, setJob] = useState(null)
    const [error, setError] = useState('')
    const [busy, setBusy] = useState(false)

    const timerRef = useRef(null)
    const pollsRef = useRef(0)
    const mountedRef = useRef(true)
    // Keep the callbacks in refs so changing them never restarts a poll loop.
    const fetchRef = useRef(fetchJob)
    const settledRef = useRef(onSettled)
    fetchRef.current = fetchJob
    settledRef.current = onSettled

    const stop = useCallback(() => {
        if (timerRef.current) {
            clearInterval(timerRef.current)
            timerRef.current = null
        }
    }, [])

    useEffect(() => () => { mountedRef.current = false; stop() }, [stop])

    const poll = useCallback((jobId) => {
        stop()
        pollsRef.current = 0
        timerRef.current = setInterval(async () => {
            pollsRef.current += 1
            if (pollsRef.current > MAX_POLLS) {
                stop()
                if (mountedRef.current) {
                    setError('This is taking unusually long. Try regenerating.')
                }
                return
            }
            try {
                const fresh = await fetchRef.current(jobId)
                if (!mountedRef.current) return
                setJob(fresh)
                if (!isJobRunning(fresh)) {
                    stop()
                    setBusy(false)
                    if (fresh.status === 'failed') setError(fresh.error || 'Generation failed.')
                    settledRef.current?.(fresh)
                }
            } catch {
                // A transient 5xx/offline blip must not kill a long run.
            }
        }, interval)
    }, [interval, stop])

    /**
     * Kick off (or resume) a job. `request` is any call that returns a job —
     * generate, refine or regenerate.
     */
    const run = useCallback(async (request) => {
        setBusy(true)
        setError('')
        try {
            const next = await request()
            if (!mountedRef.current) return next
            setJob(next)
            if (isJobRunning(next)) {
                poll(next.id)
            } else {
                setBusy(false)
                if (next.status === 'failed') setError(next.error || 'Generation failed.')
                settledRef.current?.(next)
            }
            return next
        } catch (err) {
            if (mountedRef.current) {
                setBusy(false)
                const data = err?.response?.data
                setError(
                    data?.detail
                    || data?.error
                    || (Array.isArray(data?.prompt) ? data.prompt[0] : data?.prompt)
                    || 'Generation failed. Try again, or add more detail to your brief.',
                )
            }
            return null
        }
    }, [poll])

    const reset = useCallback(() => {
        stop()
        setJob(null)
        setError('')
        setBusy(false)
    }, [stop])

    return {
        job,
        setJob,
        error,
        setError,
        // `busy` stays true for the whole run — the request *and* the polling.
        busy: busy || isJobRunning(job),
        run,
        reset,
        stop,
    }
}

export default useGenerationJob
