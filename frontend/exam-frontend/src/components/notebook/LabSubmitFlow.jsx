import { useEffect } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import {
  AlertTriangle, CheckCircle2, Loader2, Lock, RefreshCw, Send, Trophy, X, XCircle,
} from 'lucide-react'

/**
 * The submit → grade → result flow for a lab, as one continuous modal.
 *
 * Submitting used to be a `window.confirm` followed by a result panel appended
 * below the notebook, which on a long lab is far off-screen — students had no
 * idea whether they had been graded or what they scored. Keeping all three
 * phases in the same surface means the outcome appears exactly where the
 * student was already looking.
 */

/** How many attempts are left, phrased for a student rather than an API. */
export const attemptsSummary = (notebook) => {
  if (!notebook) return { text: '', canRetry: false }
  if (!notebook.allow_resubmission) {
    return { text: 'One submission only — resubmissions are not allowed.', canRetry: false }
  }
  const remaining = notebook.attempts_remaining
  if (remaining === null || remaining === undefined) {
    return { text: 'Resubmissions allowed — unlimited attempts.', canRetry: true }
  }
  if (remaining <= 0) {
    return { text: 'No attempts remaining.', canRetry: false }
  }
  return {
    text: `Resubmissions allowed — ${remaining} attempt${remaining === 1 ? '' : 's'} left.`,
    canRetry: true,
  }
}

const Backdrop = ({ children, onClose, dismissible }) => {
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape' && dismissible) onClose?.() }
    window.addEventListener('keydown', onKey)
    const { overflow } = window.document.body.style
    window.document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      window.document.body.style.overflow = overflow
    }
  }, [dismissible, onClose])

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4"
      onClick={dismissible ? onClose : undefined}
      role="dialog"
      aria-modal="true"
    >
      <motion.div
        initial={{ opacity: 0, scale: 0.96, y: 12 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.96, y: 12 }}
        transition={{ type: 'spring', damping: 26, stiffness: 320 }}
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-lg max-h-[85vh] overflow-y-auto rounded-2xl bg-white dark:bg-surface-800 shadow-2xl"
      >
        {children}
      </motion.div>
    </motion.div>
  )
}

const TestRow = ({ result }) => (
  <div className="flex items-start gap-2 rounded-lg px-3 py-2 bg-surface-50 dark:bg-surface-900/40">
    {result.passed
      ? <CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0 text-emerald-500" />
      : <XCircle className="w-4 h-4 mt-0.5 shrink-0 text-red-500" />}
    <div className="min-w-0 flex-1">
      <div className="flex items-center gap-1.5">
        <span className="text-sm font-medium text-surface-800 dark:text-surface-100 truncate">
          {result.name || 'Check'}
        </span>
        {result.is_hidden && <Lock className="w-3 h-3 text-surface-400" title="Hidden check" />}
      </div>
      {result.error && !result.passed && (
        <p className="mt-0.5 font-mono text-xs text-red-600 dark:text-red-400 whitespace-pre-wrap break-words">
          {result.error}
        </p>
      )}
    </div>
    <span className="shrink-0 text-xs font-semibold text-surface-500">
      {result.points}/{result.max_points}
    </span>
  </div>
)

const ConfirmBody = ({ notebook, onCancel, onConfirm }) => {
  const attempts = attemptsSummary(notebook)
  const hidden = notebook.hidden_test_count || 0

  return (
    <>
      <div className="flex items-start gap-3 p-5 pb-3">
        <div className="w-10 h-10 rounded-xl bg-emerald-50 dark:bg-emerald-900/20 flex items-center justify-center shrink-0">
          <Send className="w-5 h-5 text-emerald-600" />
        </div>
        <div className="min-w-0">
          <h2 className="text-lg font-bold text-surface-900 dark:text-white">
            Submit for grading?
          </h2>
          <p className="mt-0.5 text-sm text-surface-500 dark:text-surface-400">
            {notebook.title}
          </p>
        </div>
      </div>

      <div className="px-5 space-y-3">
        <ul className="space-y-2.5 text-sm text-surface-600 dark:text-surface-300">
          <li className="flex gap-2.5">
            <CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0 text-surface-400" />
            <span>
              Your <strong>whole lab</strong> is submitted and re-run from a fresh
              Python session, so the score reflects the code you wrote — not
              output left over from earlier runs.
            </span>
          </li>
          <li className="flex gap-2.5">
            <Lock className="w-4 h-4 mt-0.5 shrink-0 text-surface-400" />
            <span>
              It is graded against <strong>every test case</strong>
              {hidden > 0
                ? `, including ${hidden} hidden check${hidden === 1 ? '' : 's'} you haven't seen.`
                : '.'}
            </span>
          </li>
          <li className="flex gap-2.5">
            <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0 text-amber-500" />
            <span>Make sure you have completed every answer cell before submitting.</span>
          </li>
        </ul>

        <div
          className={`rounded-xl px-3 py-2.5 text-sm font-medium ${
            attempts.canRetry
              ? 'bg-surface-50 dark:bg-surface-900/40 text-surface-600 dark:text-surface-300'
              : 'bg-amber-50 dark:bg-amber-900/10 text-amber-700 dark:text-amber-300'
          }`}
        >
          {attempts.canRetry
            ? attempts.text
            : `${attempts.text} This submission is final.`}
        </div>
      </div>

      <div className="flex items-center justify-end gap-2 p-5 pt-4">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-lg px-4 py-2 text-sm font-medium text-surface-600 dark:text-surface-300 hover:bg-surface-100 dark:hover:bg-surface-700"
        >
          Keep working
        </button>
        <button
          type="button"
          onClick={onConfirm}
          className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-700"
        >
          <Send className="w-4 h-4" /> Submit for grading
        </button>
      </div>
    </>
  )
}

const RunningBody = ({ phase }) => (
  <div className="p-8 text-center">
    <div className="w-14 h-14 mx-auto rounded-2xl bg-primary-50 dark:bg-primary-900/20 flex items-center justify-center">
      <Loader2 className="w-7 h-7 text-primary-600 animate-spin" />
    </div>
    <h2 className="mt-4 text-lg font-bold text-surface-900 dark:text-white">
      Grading your lab
    </h2>
    <p className="mt-1 text-sm text-surface-500 dark:text-surface-400">
      {phase || 'Working…'}
    </p>
    <p className="mt-4 text-xs text-surface-400">
      Keep this tab open — this usually takes a few seconds.
    </p>
  </div>
)

const ResultBody = ({ notebook, result, onClose, onRetry }) => {
  const failed = result.status === 'error'
  const total = result.total_points || 0
  const passed = result.passed_points || 0
  const pct = total > 0 ? Math.round((passed / total) * 100) : 0
  const allPassed = !failed && total > 0 && passed === total
  const attempts = attemptsSummary(notebook)

  const tone = failed
    ? { bg: 'bg-red-50 dark:bg-red-900/20', fg: 'text-red-600', Icon: XCircle }
    : allPassed
      ? { bg: 'bg-emerald-50 dark:bg-emerald-900/20', fg: 'text-emerald-600', Icon: Trophy }
      : pct > 0
        ? { bg: 'bg-amber-50 dark:bg-amber-900/20', fg: 'text-amber-600', Icon: CheckCircle2 }
        : { bg: 'bg-red-50 dark:bg-red-900/20', fg: 'text-red-600', Icon: XCircle }

  return (
    <>
      <div className="relative p-5 pb-3 text-center">
        <button
          type="button"
          onClick={onClose}
          className="absolute right-3 top-3 p-1.5 rounded-lg text-surface-400 hover:bg-surface-100 dark:hover:bg-surface-700"
          aria-label="Close"
        >
          <X className="w-4 h-4" />
        </button>

        <div className={`w-14 h-14 mx-auto rounded-2xl flex items-center justify-center ${tone.bg}`}>
          <tone.Icon className={`w-7 h-7 ${tone.fg}`} />
        </div>

        <h2 className="mt-3 text-lg font-bold text-surface-900 dark:text-white">
          {failed
            ? 'Grading failed'
            : allPassed
              ? 'All checks passed!'
              : 'Graded'}
        </h2>

        {!failed && (
          <>
            <p className="mt-2 text-3xl font-bold text-surface-900 dark:text-white tabular-nums">
              {passed}<span className="text-surface-400">/{total}</span>
              <span className="ml-1.5 text-base font-semibold text-surface-400">points</span>
            </p>
            {result.final_marks !== null && result.notebook_max_marks ? (
              <p className="mt-1 inline-flex items-center rounded-md bg-emerald-50 dark:bg-emerald-900/20 px-2.5 py-1 text-sm font-semibold text-emerald-600">
                {result.final_marks} / {result.notebook_max_marks} marks
              </p>
            ) : null}
            <p className="mt-2 text-sm text-surface-500 dark:text-surface-400">
              Attempt {result.attempt_number} · recorded and saved
              {result.is_late ? ' · submitted late' : ''}
            </p>
          </>
        )}
      </div>

      <div className="px-5 space-y-2">
        {result.execution_error && (
          <pre className="rounded-lg bg-red-50 dark:bg-red-900/10 p-3 font-mono text-xs text-red-700 dark:text-red-300 whitespace-pre-wrap break-words">
            {result.execution_error}
          </pre>
        )}
        {(result.results || []).map((r, i) => <TestRow key={i} result={r} />)}
      </div>

      <div className="p-5 pt-4 space-y-2">
        <p className="text-center text-xs text-surface-500 dark:text-surface-400">
          {attempts.text}
        </p>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onClose}
            className="flex-1 rounded-lg border border-surface-200 dark:border-surface-700 px-4 py-2 text-sm font-medium text-surface-600 dark:text-surface-300 hover:bg-surface-50 dark:hover:bg-surface-700"
          >
            {allPassed ? 'Done' : 'Back to my lab'}
          </button>
          {attempts.canRetry && !allPassed && (
            <button
              type="button"
              onClick={onRetry}
              className="flex-1 inline-flex items-center justify-center gap-1.5 rounded-lg bg-primary-600 px-4 py-2 text-sm font-semibold text-white hover:bg-primary-700"
            >
              <RefreshCw className="w-4 h-4" /> Try again
            </button>
          )}
        </div>
      </div>
    </>
  )
}

const SubmitFlowModal = ({
  phase, notebook, progress, result, onCancel, onConfirm, onClose, onRetry,
}) => (
  <AnimatePresence>
    {phase && (
      <Backdrop onClose={onCancel} dismissible={phase === 'confirm' || phase === 'result'}>
        {phase === 'confirm' && (
          <ConfirmBody notebook={notebook} onCancel={onCancel} onConfirm={onConfirm} />
        )}
        {phase === 'running' && <RunningBody phase={progress} />}
        {phase === 'result' && result && (
          <ResultBody
            notebook={notebook}
            result={result}
            onClose={onClose}
            onRetry={onRetry}
          />
        )}
      </Backdrop>
    )}
  </AnimatePresence>
)

export default SubmitFlowModal
