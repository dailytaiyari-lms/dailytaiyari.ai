import { useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState, forwardRef } from 'react'
import {
  Play, FastForward, RotateCcw, Square, Loader2, Plus, Download, Database,
  CircleDot, AlertTriangle,
} from 'lucide-react'
import NotebookCell from './NotebookCell'
import usePyodideKernel, { KERNEL_IDLE } from '../../hooks/usePyodideKernel'
import {
  ROLE_ANSWER, ROLE_EDITABLE, cellRole, downloadNotebook, makeCell,
  sourceToText, withKeys,
} from './notebookDoc'

/**
 * The interactive notebook surface.
 *
 * Owns the Pyodide kernel and the working document. The parent supplies the
 * initial document and receives every change (for autosave / submit) via
 * `onChange`. Structural editing (add/delete/move cells) is enabled for
 * authors via `canEditStructure`.
 */
const NotebookEditor = forwardRef(({
  document: initialDocument,
  datasets = [],
  packages = [],
  onChange,
  onKernelReady,
  canEditStructure = false,
  headerExtra = null,
  autoBoot = true,
}, ref) => {
  const [doc, setDoc] = useState(() => withKeys(initialDocument))
  const [editingMarkdown, setEditingMarkdown] = useState(null)
  const [liveOutput, setLiveOutput] = useState('')
  const [runningIndex, setRunningIndex] = useState(null)
  const [runningAll, setRunningAll] = useState(false)
  const [datasetFiles, setDatasetFiles] = useState([])
  const [datasetError, setDatasetError] = useState('')
  const docRef = useRef(doc)
  const abortRunAll = useRef(false)

  docRef.current = doc

  // Reset the working copy when the parent swaps in a different document
  // (e.g. the student resets to the template, or an admin loads a submission).
  const documentKey = initialDocument
  useEffect(() => {
    setDoc(withKeys(initialDocument))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [documentKey])

  const kernel = usePyodideKernel({ packages, files: datasetFiles })

  // Fetch the notebook's datasets and hand the bytes to the kernel worker,
  // which writes them into the Pyodide filesystem under their exact filenames.
  useEffect(() => {
    let cancelled = false
    if (!datasets.length) {
      setDatasetFiles([])
      return undefined
    }
    ;(async () => {
      const loaded = []
      for (const dataset of datasets) {
        if (!dataset.url) continue
        try {
          const res = await fetch(dataset.url)
          if (!res.ok) throw new Error(`HTTP ${res.status}`)
          loaded.push({ filename: dataset.filename, bytes: await res.arrayBuffer() })
        } catch (err) {
          if (!cancelled) {
            setDatasetError(
              `Could not download "${dataset.filename}". Reload the page to try again.`,
            )
          }
        }
      }
      if (!cancelled) setDatasetFiles(loaded)
    })()
    return () => { cancelled = true }
  }, [datasets])

  useEffect(() => {
    if (autoBoot && kernel.state === KERNEL_IDLE) kernel.boot()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoBoot, kernel.state])

  useEffect(() => {
    if (kernel.isReady) onKernelReady?.()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kernel.isReady])

  const update = useCallback((updater) => {
    setDoc((prev) => {
      const next = typeof updater === 'function' ? updater(prev) : updater
      docRef.current = next
      onChange?.(next)
      return next
    })
  }, [onChange])

  const setCellSource = useCallback((index, value) => {
    update((prev) => {
      const cells = [...prev.cells]
      cells[index] = { ...cells[index], source: value }
      return { ...prev, cells }
    })
  }, [update])

  const applyResult = useCallback((index, result) => {
    update((prev) => {
      const cells = [...prev.cells]
      if (!cells[index]) return prev
      cells[index] = {
        ...cells[index],
        outputs: result.outputs || [],
        execution_count: result.execution_count ?? null,
      }
      return { ...prev, cells }
    })
  }, [update])

  const runCellAt = useCallback(async (index) => {
    const cell = docRef.current.cells[index]
    if (!cell || cell.cell_type !== 'code') return { error: null }
    setRunningIndex(index)
    setLiveOutput('')
    try {
      const result = await kernel.runCell(
        cell.__key,
        sourceToText(cell.source),
        { onStream: (msg) => setLiveOutput((prev) => prev + msg.text) },
      )
      applyResult(index, result)
      return result
    } catch (err) {
      applyResult(index, {
        outputs: [{ output_type: 'error', traceback: err.message }],
        execution_count: null,
      })
      return { error: err.message }
    } finally {
      setRunningIndex(null)
      setLiveOutput('')
    }
  }, [applyResult, kernel])

  const runAll = useCallback(async () => {
    abortRunAll.current = false
    setRunningAll(true)
    try {
      const indexes = docRef.current.cells
        .map((cell, index) => (cell.cell_type === 'code' ? index : -1))
        .filter((index) => index >= 0)
      for (const index of indexes) {
        if (abortRunAll.current) break
        // Stop at the first failure, like "Run all" in Jupyter — continuing past
        // a NameError just produces a cascade of confusing errors.
        const result = await runCellAt(index)
        if (result?.error) break
      }
    } finally {
      setRunningAll(false)
    }
  }, [runCellAt])

  const stop = useCallback(() => {
    abortRunAll.current = true
    kernel.stop()
    setRunningIndex(null)
    setLiveOutput('')
  }, [kernel])

  const restart = useCallback(async () => {
    abortRunAll.current = true
    update((prev) => ({
      ...prev,
      cells: prev.cells.map((cell) =>
        cell.cell_type === 'code'
          ? { ...cell, outputs: [], execution_count: null }
          : cell,
      ),
    }))
    if (kernel.state === KERNEL_IDLE) await kernel.boot()
    else await kernel.restart()
  }, [kernel, update])

  /** Run tests in the browser kernel — used for self-check and the provisional score. */
  const runTests = useCallback(async (tests) => {
    if (!tests?.length) return []
    const runnable = tests.filter((t) => t.source)
    if (!runnable.length) return []
    const response = await kernel.runTests(
      runnable.map((t) => ({ id: t.id, name: t.name, source: t.source })),
    )
    return response?.results || []
  }, [kernel])

  const addCell = useCallback((cellType) => {
    update((prev) => ({
      ...prev,
      cells: [...prev.cells, withKeys({ cells: [makeCell(cellType, ROLE_EDITABLE)] }).cells[0]],
    }))
  }, [update])

  const deleteCell = useCallback((index) => {
    update((prev) => ({ ...prev, cells: prev.cells.filter((_, i) => i !== index) }))
  }, [update])

  const moveCell = useCallback((index, delta) => {
    update((prev) => {
      const target = index + delta
      if (target < 0 || target >= prev.cells.length) return prev
      const cells = [...prev.cells]
      const [moved] = cells.splice(index, 1)
      cells.splice(target, 0, moved)
      return { ...prev, cells }
    })
  }, [update])

  const answeredCount = useMemo(
    () => doc.cells.filter(
      (cell) => cellRole(cell) === ROLE_ANSWER && sourceToText(cell.source).trim(),
    ).length,
    [doc.cells],
  )
  const answerTotal = useMemo(
    () => doc.cells.filter((cell) => cellRole(cell) === ROLE_ANSWER).length,
    [doc.cells],
  )

  // Imperative surface for the page: submitting needs to run every cell top to
  // bottom (a fresh, honest execution) and then run the tests in that namespace.
  useImperativeHandle(ref, () => ({
    getDocument: () => docRef.current,
    runAll,
    runTests,
    restart,
    stop,
    isReady: () => kernel.isReady,
    /** Fresh kernel -> run all cells -> run tests. Returns test results. */
    async executeForGrading(tests) {
      await restart()
      await runAll()
      return runTests(tests)
    },
  }), [kernel.isReady, restart, runAll, runTests, stop])

  const busy = kernel.isBusy || kernel.isLoading
  const kernelLabel = kernel.isLoading
    ? (kernel.status || 'Starting Python…')
    : kernel.isBusy
      ? 'Running'
      : kernel.isReady
        ? 'Python ready'
        : 'Kernel stopped'

  return (
    <div className="space-y-3">
      <div className="sticky top-0 z-10 flex flex-wrap items-center gap-2 rounded-xl border border-surface-200 dark:border-surface-700 bg-white/95 dark:bg-surface-800/95 backdrop-blur px-3 py-2">
        <span className="inline-flex items-center gap-1.5 text-xs font-medium">
          <CircleDot
            className={`w-3.5 h-3.5 ${
              kernel.isReady
                ? 'text-emerald-500'
                : busy
                  ? 'text-amber-500 animate-pulse'
                  : 'text-surface-400'
            }`}
          />
          <span className="text-surface-600 dark:text-surface-300">{kernelLabel}</span>
        </span>

        <div className="h-4 w-px bg-surface-200 dark:bg-surface-700" />

        <button
          type="button"
          onClick={runAll}
          disabled={busy}
          className="inline-flex items-center gap-1.5 rounded-lg bg-primary-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-primary-700 disabled:opacity-50"
        >
          {runningAll ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <FastForward className="w-3.5 h-3.5" />}
          Run all
        </button>
        {busy && (
          <button
            type="button"
            onClick={stop}
            className="inline-flex items-center gap-1.5 rounded-lg bg-red-500 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-600"
          >
            <Square className="w-3.5 h-3.5" /> Stop
          </button>
        )}
        <button
          type="button"
          onClick={restart}
          disabled={kernel.isBusy}
          className="inline-flex items-center gap-1.5 rounded-lg border border-surface-200 dark:border-surface-700 px-3 py-1.5 text-xs font-medium text-surface-600 dark:text-surface-300 hover:bg-surface-50 dark:hover:bg-surface-700 disabled:opacity-50"
          title="Clear all variables and outputs"
        >
          <RotateCcw className="w-3.5 h-3.5" /> Restart
        </button>

        {answerTotal > 0 && (
          <span className="text-xs text-surface-500 dark:text-surface-400">
            {answeredCount}/{answerTotal} answers written
          </span>
        )}

        <div className="ml-auto flex items-center gap-2">
          {datasets.length > 0 && (
            <span
              className="inline-flex items-center gap-1 text-xs text-surface-500 dark:text-surface-400"
              title={datasets.map((d) => d.filename).join(', ')}
            >
              <Database className="w-3.5 h-3.5" />
              {datasets.length} file{datasets.length > 1 ? 's' : ''}
            </span>
          )}
          <button
            type="button"
            onClick={() => downloadNotebook(doc, 'notebook.ipynb')}
            className="inline-flex items-center gap-1.5 rounded-lg border border-surface-200 dark:border-surface-700 px-3 py-1.5 text-xs font-medium text-surface-600 dark:text-surface-300 hover:bg-surface-50 dark:hover:bg-surface-700"
            title="Download as .ipynb (opens in Jupyter or Colab)"
          >
            <Download className="w-3.5 h-3.5" /> .ipynb
          </button>
          {headerExtra}
        </div>
      </div>

      {(datasetError || kernel.warnings.length > 0) && (
        <div className="rounded-xl border border-amber-200 dark:border-amber-900/40 bg-amber-50 dark:bg-amber-900/10 px-3 py-2 text-xs text-amber-800 dark:text-amber-300 space-y-1">
          {datasetError && (
            <div className="flex items-start gap-2">
              <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
              <span>{datasetError}</span>
            </div>
          )}
          {kernel.warnings.map((warning, index) => (
            <div key={index} className="flex items-start gap-2">
              <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
              <span>{warning}</span>
            </div>
          ))}
        </div>
      )}

      <div className="space-y-3">
        {doc.cells.map((cell, index) => (
          <NotebookCell
            key={cell.__key}
            cell={cell}
            index={index}
            editingMarkdown={editingMarkdown === index}
            isRunning={runningIndex === index}
            liveOutput={liveOutput}
            kernelBusy={busy}
            canEditStructure={canEditStructure}
            onChangeSource={setCellSource}
            onRun={runCellAt}
            onStop={stop}
            onToggleMarkdownEdit={(i) => setEditingMarkdown((prev) => (prev === i ? null : i))}
            onDelete={deleteCell}
            onMove={moveCell}
          />
        ))}
        {doc.cells.length === 0 && (
          <div className="rounded-xl border border-dashed border-surface-300 dark:border-surface-700 py-10 text-center text-sm text-surface-400">
            This notebook has no cells yet.
          </div>
        )}
      </div>

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => addCell('code')}
          className="inline-flex items-center gap-1.5 rounded-lg border border-dashed border-surface-300 dark:border-surface-600 px-3 py-1.5 text-xs font-medium text-surface-500 hover:border-primary-400 hover:text-primary-600"
        >
          <Plus className="w-3.5 h-3.5" /> Code cell
        </button>
        <button
          type="button"
          onClick={() => addCell('markdown')}
          className="inline-flex items-center gap-1.5 rounded-lg border border-dashed border-surface-300 dark:border-surface-600 px-3 py-1.5 text-xs font-medium text-surface-500 hover:border-primary-400 hover:text-primary-600"
        >
          <Plus className="w-3.5 h-3.5" /> Text cell
        </button>
      </div>
    </div>
  )
})

NotebookEditor.displayName = 'NotebookEditor'

export { NotebookEditor }
export default NotebookEditor
