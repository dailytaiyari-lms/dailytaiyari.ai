import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * React binding for the Pyodide kernel worker.
 *
 * The worker owns all Python state, so "Stop" is implemented by terminating
 * the worker outright (Pyodide is synchronous WASM — there is no way to
 * interrupt a running cell from inside). A fresh worker is spun up immediately
 * so the student can carry on; they just lose their in-memory variables, which
 * is exactly what "Restart kernel" means in Jupyter.
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
  const filesRef = useRef(files)
  const packagesRef = useRef(packages)

  const [state, setState] = useState(KERNEL_IDLE)
  const [status, setStatus] = useState('')
  const [warnings, setWarnings] = useState([])
  const [runningCellId, setRunningCellId] = useState(null)

  filesRef.current = files
  packagesRef.current = packages

  const rejectAll = useCallback((reason) => {
    pendingRef.current.forEach(({ reject }) => reject(new Error(reason)))
    pendingRef.current.clear()
  }, [])

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
        const handler = pendingRef.current.get(msg.id)
        handler?.onStream?.(msg)
        return
      }
      if (msg.type === 'ready') {
        setState(KERNEL_READY)
        setStatus('')
        const entry = pendingRef.current.get(msg.id)
        if (entry) {
          pendingRef.current.delete(msg.id)
          entry.resolve({ ready: true })
        }
        return
      }
      if (msg.type === 'result' || msg.type === 'tests') {
        const entry = pendingRef.current.get(msg.id)
        if (entry) {
          pendingRef.current.delete(msg.id)
          entry.resolve(msg)
        }
        if (!pendingRef.current.size) setState(KERNEL_READY)
        return
      }
      if (msg.type === 'fatal') {
        const entry = pendingRef.current.get(msg.id)
        if (entry) {
          pendingRef.current.delete(msg.id)
          entry.reject(new Error(msg.error))
        } else {
          setWarnings((prev) => [...prev, msg.error])
        }
        if (!pendingRef.current.size) setState(KERNEL_READY)
      }
    }
    worker.onerror = (err) => {
      rejectAll(err?.message || 'The Python kernel crashed.')
      setState(KERNEL_IDLE)
    }
  }, [rejectAll])

  const ensureWorker = useCallback(() => {
    if (workerRef.current) return workerRef.current
    const worker = createWorker()
    attach(worker)
    workerRef.current = worker
    return worker
  }, [attach])

  const send = useCallback((payload, { onStream } = {}) => {
    const worker = ensureWorker()
    const id = `m${++seqRef.current}`
    return new Promise((resolve, reject) => {
      pendingRef.current.set(id, { resolve, reject, onStream })
      worker.postMessage({ ...payload, id, packages: packagesRef.current })
    })
  }, [ensureWorker])

  /** Boot the kernel and stage the notebook's dataset files. */
  const boot = useCallback(async () => {
    if (state === KERNEL_READY || state === KERNEL_LOADING) return
    setState(KERNEL_LOADING)
    try {
      await send({ type: 'init', files: filesRef.current })
      setState(KERNEL_READY)
    } catch (err) {
      setState(KERNEL_IDLE)
      setWarnings((prev) => [...prev, err.message])
    }
  }, [send, state])

  const runCell = useCallback(async (cellId, code, { onStream } = {}) => {
    setState(KERNEL_BUSY)
    setRunningCellId(cellId)
    try {
      return await send({ type: 'run', code }, { onStream })
    } finally {
      setRunningCellId(null)
    }
  }, [send])

  const runTests = useCallback(async (tests) => {
    setState(KERNEL_BUSY)
    try {
      return await send({ type: 'runTests', tests })
    } finally {
      setRunningCellId(null)
    }
  }, [send])

  /** Hard-stop: terminate the worker (the only way to kill running WASM). */
  const stop = useCallback(() => {
    if (workerRef.current) {
      workerRef.current.terminate()
      workerRef.current = null
    }
    rejectAll('Execution stopped.')
    setRunningCellId(null)
    setState(KERNEL_IDLE)
    setStatus('')
  }, [rejectAll])

  /** Restart: clear the namespace but keep the (already downloaded) runtime. */
  const restart = useCallback(async () => {
    if (!workerRef.current) return
    setState(KERNEL_BUSY)
    try {
      await send({ type: 'reset' })
      await send({ type: 'init', files: filesRef.current })
      setState(KERNEL_READY)
    } catch {
      stop()
    }
  }, [send, stop])

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
