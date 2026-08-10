import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * React binding for the Pyodide kernel worker.
 *
 * The worker owns all Python state, so "Stop" is implemented by terminating
 * the worker outright (Pyodide is synchronous WASM — there is no way to
 * interrupt a running cell from inside). A fresh worker is spun up immediately
 * so the student can carry on; they just lose their in-memory variables, which
 * is exactly what "Restart kernel" means in Jupyter.
 *
 * Busy state is tracked with an explicit count of in-flight executions. It was
 * previously inferred from "are any promises still pending", so a single
 * unresolved message left the notebook stuck on "Running" for the whole
 * session — and made submitting hang.
 */
export const KERNEL_IDLE = 'idle'
export const KERNEL_LOADING = 'loading'
export const KERNEL_READY = 'ready'
export const KERNEL_BUSY = 'busy'

const createWorker = () =>
  new Worker(new URL('../workers/pyodideKernel.worker.js', import.meta.url), {
    type: 'classic',
  })

export default function usePyodideKernel({ packages = [], files = [] } = {}) {
  const workerRef = useRef(null)
  const pendingRef = useRef(new Map())
  const seqRef = useRef(0)
  const execRef = useRef(0)
  const filesRef = useRef(files)
  const packagesRef = useRef(packages)
  const stateRef = useRef(KERNEL_IDLE)

  const [state, setState] = useState(KERNEL_IDLE)
  const [status, setStatus] = useState('')
  const [warnings, setWarnings] = useState([])
  const [runningCellId, setRunningCellId] = useState(null)

  filesRef.current = files
  packagesRef.current = packages

  const moveTo = useCallback((next) => {
    stateRef.current = next
    setState(next)
  }, [])

  const rejectAll = useCallback((reason) => {
    pendingRef.current.forEach(({ reject }) => reject(new Error(reason)))
    pendingRef.current.clear()
    execRef.current = 0
  }, [])

  /** An execution finished: drop back to ready once nothing is left running. */
  const finishExec = useCallback(() => {
    execRef.current = Math.max(0, execRef.current - 1)
    if (execRef.current === 0) {
      setRunningCellId(null)
      if (stateRef.current === KERNEL_BUSY) moveTo(KERNEL_READY)
    }
  }, [moveTo])

  const attach = useCallback((worker) => {
    worker.onmessage = (event) => {
      const msg = event.data || {}
      if (msg.type === 'status') {
        if (msg.phase === 'warning') {
          setWarnings((prev) => (prev.includes(msg.detail) ? prev : [...prev, msg.detail]))
        } else {
          setStatus(msg.detail || '')
        }
        return
      }
      if (msg.type === 'stream') {
        pendingRef.current.get(msg.id)?.onStream?.(msg)
        return
      }

      const entry = msg.id ? pendingRef.current.get(msg.id) : null
      if (entry) pendingRef.current.delete(msg.id)

      if (msg.type === 'ready') {
        setStatus('')
        entry?.resolve({ ready: true })
        if (entry?.isExec) finishExec()
        else if (stateRef.current !== KERNEL_BUSY) moveTo(KERNEL_READY)
        return
      }
      if (msg.type === 'result' || msg.type === 'tests') {
        entry?.resolve(msg)
        finishExec()
        return
      }
      if (msg.type === 'fatal') {
        if (entry) entry.reject(new Error(msg.error))
        else setWarnings((prev) => [...prev, msg.error])
        finishExec()
      }
    }
    worker.onerror = (err) => {
      rejectAll(err?.message || 'The Python kernel crashed.')
      moveTo(KERNEL_IDLE)
    }
  }, [finishExec, moveTo, rejectAll])

  const ensureWorker = useCallback(() => {
    if (workerRef.current) return workerRef.current
    const worker = createWorker()
    attach(worker)
    workerRef.current = worker
    return worker
  }, [attach])

  const send = useCallback((payload, { onStream, isExec = false } = {}) => {
    const worker = ensureWorker()
    const id = `m${++seqRef.current}`
    if (isExec) execRef.current += 1
    return new Promise((resolve, reject) => {
      pendingRef.current.set(id, { resolve, reject, onStream, isExec })
      worker.postMessage({ ...payload, id, packages: packagesRef.current })
    })
  }, [ensureWorker])

  /** Boot the kernel and stage the notebook's dataset files. */
  const boot = useCallback(async () => {
    if (stateRef.current === KERNEL_READY || stateRef.current === KERNEL_LOADING) return
    moveTo(KERNEL_LOADING)
    try {
      await send({ type: 'init', files: filesRef.current })
      moveTo(KERNEL_READY)
    } catch (err) {
      moveTo(KERNEL_IDLE)
      setWarnings((prev) => [...prev, err.message])
    }
  }, [moveTo, send])

  const runCell = useCallback((cellId, code, { onStream } = {}) => {
    moveTo(KERNEL_BUSY)
    setRunningCellId(cellId)
    return send({ type: 'run', code }, { onStream, isExec: true })
  }, [moveTo, send])

  const runTests = useCallback((tests) => {
    moveTo(KERNEL_BUSY)
    return send({ type: 'runTests', tests }, { isExec: true })
  }, [moveTo, send])

  /** Hard-stop: terminate the worker (the only way to kill running WASM). */
  const stop = useCallback(() => {
    if (workerRef.current) {
      workerRef.current.terminate()
      workerRef.current = null
    }
    rejectAll('Execution stopped.')
    setRunningCellId(null)
    moveTo(KERNEL_IDLE)
    setStatus('')
  }, [moveTo, rejectAll])

  /** Restart: clear the namespace but keep the (already downloaded) runtime. */
  const restart = useCallback(async () => {
    if (!workerRef.current) return boot()
    moveTo(KERNEL_BUSY)
    try {
      await send({ type: 'reset' })
      await send({ type: 'init', files: filesRef.current })
      setRunningCellId(null)
      moveTo(KERNEL_READY)
    } catch {
      stop()
    }
    return undefined
  }, [boot, moveTo, send, stop])

  useEffect(() => () => {
    workerRef.current?.terminate()
    workerRef.current = null
  }, [])

  return {
    state,
    status,
    warnings,
    runningCellId,
    isReady: state === KERNEL_READY,
    isBusy: state === KERNEL_BUSY,
    isLoading: state === KERNEL_LOADING,
    boot,
    runCell,
    runTests,
    stop,
    restart,
    dismissWarnings: () => setWarnings([]),
  }
}
