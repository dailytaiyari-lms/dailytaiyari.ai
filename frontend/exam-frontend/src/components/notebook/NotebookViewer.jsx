import { memo } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import { Lock, Target, Pencil } from 'lucide-react'
import CellOutput from './CellOutput'
import { ROLE_ANSWER, ROLE_READONLY, cellGradeId, cellRole, sourceToText } from './notebookDoc'

const ROLE_BADGE = {
  [ROLE_READONLY]: { icon: Lock, label: 'Locked', className: 'bg-surface-100 text-surface-500 dark:bg-surface-800 dark:text-surface-400' },
  editable: { icon: Pencil, label: 'Scratch', className: 'bg-sky-50 text-sky-600 dark:bg-sky-900/20 dark:text-sky-400' },
  [ROLE_ANSWER]: { icon: Target, label: 'Graded answer', className: 'bg-primary-50 text-primary-600 dark:bg-primary-900/20 dark:text-primary-400' },
}

/**
 * Static renderer for a submitted notebook.
 *
 * Deliberately *not* the interactive editor: a reviewer should see exactly the
 * code and the outputs that were captured at grading time, with no kernel and
 * no chance of accidentally mutating the record. Outputs are rendered through
 * CellOutput, which sanitises any student-produced HTML.
 */
const NotebookViewer = ({ document: doc, highlightAnswers = true }) => {
  const cells = doc?.cells || []
  if (!cells.length) {
    return (
      <p className="rounded-xl border border-dashed border-surface-200 dark:border-surface-700 px-4 py-8 text-center text-sm text-surface-500">
        This submission has no cells.
      </p>
    )
  }

  return (
    <div className="space-y-3">
      {cells.map((cell, index) => {
        const role = cellRole(cell)
        const badge = ROLE_BADGE[role] || ROLE_BADGE.editable
        const Icon = badge.icon
        const gradeId = cellGradeId(cell)
        const text = sourceToText(cell.source)
        const isAnswer = role === ROLE_ANSWER

        if (cell.cell_type === 'markdown') {
          return (
            <div
              key={cell.__key || index}
              className="prose prose-sm dark:prose-invert max-w-none rounded-xl border border-surface-200 dark:border-surface-700 bg-white dark:bg-surface-800 px-4 py-3"
            >
              <ReactMarkdown
                remarkPlugins={[remarkGfm, remarkMath]}
                rehypePlugins={[rehypeKatex]}
              >
                {text}
              </ReactMarkdown>
            </div>
          )
        }

        return (
          <div
            key={cell.__key || index}
            className={`rounded-xl border bg-white dark:bg-surface-800 overflow-hidden ${
              isAnswer && highlightAnswers
                ? 'border-primary-300 dark:border-primary-700 ring-1 ring-primary-100 dark:ring-primary-900/40'
                : 'border-surface-200 dark:border-surface-700'
            }`}
          >
            <div className="flex items-center gap-2 border-b border-surface-100 dark:border-surface-700 px-3 py-1.5">
              <span className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium ${badge.className}`}>
                <Icon className="w-3 h-3" /> {badge.label}
              </span>
              {gradeId && (
                <span className="font-mono text-[11px] text-surface-400">{gradeId}</span>
              )}
              <span className="ml-auto font-mono text-[11px] text-surface-400">
                [{cell.execution_count ?? ' '}]
              </span>
            </div>
            <pre className="overflow-x-auto px-4 py-3 font-mono text-xs leading-relaxed text-surface-800 dark:text-surface-100 whitespace-pre">
              {text || <span className="italic text-surface-400">empty</span>}
            </pre>
            {cell.outputs?.length > 0 && (
              <div className="border-t border-surface-100 dark:border-surface-700 px-4 py-2">
                <CellOutput outputs={cell.outputs} />
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

export default memo(NotebookViewer)
