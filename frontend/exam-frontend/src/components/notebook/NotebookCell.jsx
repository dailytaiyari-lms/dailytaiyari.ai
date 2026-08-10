import { lazy, Suspense, memo } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import {
  Play, Loader2, Lock, Pencil, Target, Trash2, ChevronUp, ChevronDown, Square,
  CheckCircle2, XCircle, RefreshCw,
} from 'lucide-react'
import CellOutput from './CellOutput'
import { ROLE_ANSWER, ROLE_READONLY, cellGradeId, cellRole, sourceToText } from './notebookDoc'

const CodeEditor = lazy(() => import('../coding/CodeEditor'))

const ROLE_BADGE = {
  [ROLE_READONLY]: {
    icon: Lock,
    label: 'Locked',
    className: 'bg-surface-100 text-surface-500 dark:bg-surface-800 dark:text-surface-400',
  },
  editable: {
    icon: Pencil,
    label: 'Scratch',
    className: 'bg-sky-50 text-sky-600 dark:bg-sky-900/20 dark:text-sky-400',
  },
  [ROLE_ANSWER]: {
    icon: Target,
    label: 'Graded answer',
    className: 'bg-primary-50 text-primary-600 dark:bg-primary-900/20 dark:text-primary-400',
  },
}

/** Rough editor height: grows with the code, clamped so the page stays usable. */
const editorHeight = (source) => {
  const lines = sourceToText(source).split('\n').length
  return Math.min(Math.max(lines + 2, 5), 30) * 19 + 24
}

const formatDuration = (ms) => {
  if (ms == null) return ''
  if (ms < 1000) return `${ms} ms`
  return `${(ms / 1000).toFixed(1)}s`
}

/**
 * The outcome of the last run, shown in the cell header.
 *
 * This is the only feedback for the many cells that legitimately print
 * nothing — a `def`, an import, an assignment — where otherwise the screen
 * simply doesn't change and the student can't tell the run happened.
 */
const RunStatusChip = ({ isRunning, status }) => {
  if (isRunning) {
    return (
      <span className="inline-flex items-center gap-1 rounded-md bg-amber-50 px-1.5 py-0.5 text-[11px] font-medium text-amber-700 dark:bg-amber-900/20 dark:text-amber-300">
        <Loader2 className="w-3 h-3 animate-spin" />
        Running…
      </span>
    )
  }
  if (!status) return null

  if (status.state === 'ok') {
    return (
      <span
        key={status.at}
        className="nb-run-flash inline-flex items-center gap-1 rounded-md bg-emerald-50 px-1.5 py-0.5 text-[11px] font-medium text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-300"
      >
        <CheckCircle2 className="w-3 h-3" />
        Ran in {formatDuration(status.ms)}
      </span>
    )
  }
  if (status.state === 'error') {
    return (
      <span className="inline-flex items-center gap-1 rounded-md bg-red-50 px-1.5 py-0.5 text-[11px] font-medium text-red-700 dark:bg-red-900/20 dark:text-red-300">
        <XCircle className="w-3 h-3" />
        Error
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-md bg-surface-100 px-1.5 py-0.5 text-[11px] font-medium text-surface-500 dark:bg-surface-700 dark:text-surface-300">
      <RefreshCw className="w-3 h-3" />
      Edited — run again
    </span>
  )
}

const MarkdownCell = ({ cell, editing, onChange, onToggleEdit, readOnly }) => {
  const text = sourceToText(cell.source)
  if (editing && !readOnly) {
    return (
      <textarea
        className="w-full rounded-xl border border-surface-200 dark:border-surface-700 bg-white dark:bg-surface-900 p-3 font-mono text-sm min-h-[8rem] focus:outline-none focus:ring-2 focus:ring-primary-400"
        value={text}
        autoFocus
        onChange={(e) => onChange(e.target.value)}
        onBlur={onToggleEdit}
      />
    )
  }
  return (
    <div
      className={`prose prose-sm dark:prose-invert max-w-none px-4 py-3 ${
        readOnly ? '' : 'cursor-text'
      }`}
      onDoubleClick={readOnly ? undefined : onToggleEdit}
      title={readOnly ? undefined : 'Double-click to edit'}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
      >
        {text || '_Empty cell_'}
      </ReactMarkdown>
    </div>
  )
}

const NotebookCell = ({
  cell,
  index,
  editingMarkdown,
  isRunning,
  liveOutput,
  onChangeSource,
  onRun,
  onStop,
  onToggleMarkdownEdit,
  onDelete,
  onMove,
  canEditStructure = false,
  kernelBusy = false,
  runStatus = null,
}) => {
  const role = cellRole(cell)
  const readOnly = role === ROLE_READONLY
  const badge = ROLE_BADGE[role] || ROLE_BADGE.editable
  const BadgeIcon = badge.icon
  const gradeId = cellGradeId(cell)
  const isCode = cell.cell_type === 'code'
  const ranClean = isCode && !isRunning && runStatus?.state === 'ok' && !runStatus.hasOutput

  return (
    <div
      className={`group rounded-xl border transition-colors ${
        isRunning
          ? 'border-amber-300 dark:border-amber-700'
          : runStatus?.state === 'error'
            ? 'border-red-200 dark:border-red-900/60'
            : runStatus?.state === 'ok'
              ? 'border-emerald-200 dark:border-emerald-900/60'
              : role === ROLE_ANSWER
                ? 'border-primary-200 dark:border-primary-800'
                : 'border-surface-200 dark:border-surface-700'
      } bg-white dark:bg-surface-800`}
    >
      <div className="flex items-center gap-2 px-3 py-1.5 border-b border-surface-100 dark:border-surface-700">
        <span
          className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium ${badge.className}`}
        >
          <BadgeIcon className="w-3 h-3" />
          {badge.label}
          {gradeId ? <span className="opacity-70">· {gradeId}</span> : null}
        </span>
        <span className="text-[11px] text-surface-400">
          {isCode ? `[${cell.execution_count ?? ' '}]` : 'Markdown'}
        </span>
        {isCode && <RunStatusChip isRunning={isRunning} status={runStatus} />}

        <div
          className={`ml-auto flex items-center gap-1 transition-opacity ${
            isRunning ? 'opacity-100' : 'opacity-0 group-hover:opacity-100 focus-within:opacity-100'
          }`}
        >
          {canEditStructure && (
            <>
              <button
                type="button"
                onClick={() => onMove?.(index, -1)}
                className="p-1 rounded text-surface-400 hover:text-surface-700 dark:hover:text-surface-200"
                title="Move up"
              >
                <ChevronUp className="w-3.5 h-3.5" />
              </button>
              <button
                type="button"
                onClick={() => onMove?.(index, 1)}
                className="p-1 rounded text-surface-400 hover:text-surface-700 dark:hover:text-surface-200"
                title="Move down"
              >
                <ChevronDown className="w-3.5 h-3.5" />
              </button>
              <button
                type="button"
                onClick={() => onDelete?.(index)}
                className="p-1 rounded text-surface-400 hover:text-red-500"
                title="Delete cell"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </>
          )}
          {isCode && (
            isRunning ? (
              <button
                type="button"
                onClick={onStop}
                className="inline-flex items-center gap-1 rounded-md bg-red-500 px-2 py-1 text-[11px] font-medium text-white hover:bg-red-600"
                title="Stop execution"
              >
                <Square className="w-3 h-3" /> Stop
              </button>
            ) : (
              <button
                type="button"
                onClick={() => onRun?.(index)}
                disabled={kernelBusy}
                className="inline-flex items-center gap-1 rounded-md bg-surface-100 dark:bg-surface-700 px-2 py-1 text-[11px] font-medium text-surface-600 dark:text-surface-200 hover:bg-primary-100 hover:text-primary-700 disabled:opacity-40"
                title="Run this cell (Shift+Enter)"
              >
                <Play className="w-3 h-3" /> Run
              </button>
            )
          )}
        </div>
      </div>

      {isCode ? (
        <Suspense
          fallback={
            <div className="h-24 flex items-center justify-center text-xs text-surface-400">
              <Loader2 className="w-4 h-4 animate-spin mr-2" /> Loading editor…
            </div>
          }
        >
          <div className="px-1 pt-1">
            <CodeEditor
              value={sourceToText(cell.source)}
              onChange={(value) => onChangeSource?.(index, value)}
              language="python"
              readOnly={readOnly}
              height={editorHeight(cell.source)}
            />
          </div>
        </Suspense>
      ) : (
        <MarkdownCell
          cell={cell}
          editing={editingMarkdown}
          readOnly={readOnly}
          onChange={(value) => onChangeSource?.(index, value)}
          onToggleEdit={() => onToggleMarkdownEdit?.(index)}
        />
      )}

      {isCode && (
        <>
          <CellOutput outputs={cell.outputs} live={isRunning ? liveOutput : ''} />
          {ranClean && (
            <div
              key={runStatus.at}
              className="nb-run-flash flex items-center gap-1.5 border-t border-emerald-100 dark:border-emerald-900/40 rounded-b-xl bg-emerald-50/60 dark:bg-emerald-900/10 px-3 py-1.5 text-[11px] text-emerald-700 dark:text-emerald-300"
            >
              <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
              Ran successfully — this cell doesn&apos;t print anything.
            </div>
          )}
        </>
      )}
    </div>
  )
}

export default memo(NotebookCell)
