import { useState } from 'react'
import { motion } from 'framer-motion'
import {
  CheckCircle2, ChevronDown, History, Lock, RefreshCw, Send, Trophy, XCircle,
} from 'lucide-react'
import { attemptsSummary } from './LabSubmitFlow'

/**
 * The student's grade and submission status, shown directly above the lab.
 *
 * Everything a student needs to answer "was I graded, what did I score, and can
 * I try again" lives here, at the top of the page. Results used to be appended
 * below the notebook, where a long lab pushed them entirely out of view.
 */

const ScoreRing = ({ passed, total, failed }) => {
  const pct = total > 0 ? Math.round((passed / total) * 100) : 0
  const tone = failed || pct === 0
    ? 'text-red-500'
    : pct === 100
      ? 'text-emerald-500'
      : 'text-amber-500'
  return (
    <div className="relative w-14 h-14 shrink-0">
      <svg viewBox="0 0 36 36" className="w-14 h-14 -rotate-90">
        <circle
          cx="18" cy="18" r="15.9" fill="none" strokeWidth="3"
          className="stroke-surface-100 dark:stroke-surface-700"
        />
        <circle
          cx="18" cy="18" r="15.9" fill="none" strokeWidth="3" strokeLinecap="round"
          strokeDasharray={`${failed ? 0 : pct} 100`}
          className={`${tone} stroke-current transition-all duration-700`}
        />
      </svg>
      <span className="absolute inset-0 flex items-center justify-center text-xs font-bold text-surface-700 dark:text-surface-200 tabular-nums">
        {failed ? '—' : `${pct}%`}
      </span>
    </div>
  )
}

const LabStatusCard = ({
  notebook, result, history = [], submitting, onSubmit, onViewDetails,
}) => {
  const [showHistory, setShowHistory] = useState(false)
  const attempts = attemptsSummary(notebook)
  const canSubmit = notebook.can_submit && !submitting
  const graded = result && result.status === 'graded'
  const failed = result && result.status === 'error'
  const hasSubmitted = !!result || history.length > 0

  // Fall back to the stored best when this page load hasn't graded anything yet,
  // so a returning student still sees their score immediately.
  const shown = result || (notebook.my_best
    ? {
      status: 'graded',
      passed_points: notebook.my_best.passed_points,
      total_points: notebook.my_best.total_points,
      final_marks: notebook.my_best.final_marks ?? null,
      notebook_max_marks: notebook.max_marks ?? null,
      attempt_number: notebook.my_best.attempt_number,
    }
    : null)

  const allPassed = shown
    && shown.total_points > 0
    && shown.passed_points === shown.total_points

  return (
    <motion.div
      initial={{ opacity: 0, y: -6 }}
      animate={{ opacity: 1, y: 0 }}
      className={`rounded-2xl border bg-white dark:bg-surface-800 ${
        allPassed
          ? 'border-emerald-200 dark:border-emerald-900/50'
          : failed
            ? 'border-red-200 dark:border-red-900/50'
            : 'border-surface-200 dark:border-surface-700'
      }`}
    >
      <div className="flex flex-wrap items-center gap-4 p-4">
        {shown ? (
          <ScoreRing
            passed={shown.passed_points}
            total={shown.total_points}
            failed={failed}
          />
        ) : (
          <div className="w-14 h-14 shrink-0 rounded-2xl bg-surface-50 dark:bg-surface-900/40 flex items-center justify-center">
            <Send className="w-6 h-6 text-surface-300" />
          </div>
        )}

        <div className="min-w-0 flex-1">
          {shown ? (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <span className="inline-flex items-center gap-1.5 text-sm font-bold text-surface-900 dark:text-white">
                  {failed ? (
                    <><XCircle className="w-4 h-4 text-red-500" /> Grading failed</>
                  ) : allPassed ? (
                    <><Trophy className="w-4 h-4 text-emerald-500" /> All checks passed</>
                  ) : (
                    <><CheckCircle2 className="w-4 h-4 text-amber-500" /> Graded</>
                  )}
                </span>
                {!failed && (
                  <span className="text-sm font-semibold text-surface-700 dark:text-surface-200 tabular-nums">
                    {shown.passed_points}/{shown.total_points} points
                  </span>
                )}
                {shown.final_marks !== null && shown.notebook_max_marks ? (
                  <span className="rounded-md bg-emerald-50 dark:bg-emerald-900/20 px-2 py-0.5 text-xs font-semibold text-emerald-600">
                    {shown.final_marks} / {shown.notebook_max_marks} marks
                  </span>
                ) : null}
              </div>
              <p className="mt-0.5 text-xs text-surface-500 dark:text-surface-400">
                Attempt {shown.attempt_number} · {attempts.text}
              </p>
            </>
          ) : (
            <>
              <p className="text-sm font-bold text-surface-900 dark:text-white">
                Not submitted yet
              </p>
              <p className="mt-0.5 text-xs text-surface-500 dark:text-surface-400">
                {attempts.text}
                {notebook.hidden_test_count > 0 && (
                  <>
                    {' · '}
                    <span className="inline-flex items-center gap-1">
                      <Lock className="w-3 h-3" />
                      {notebook.hidden_test_count} hidden check
                      {notebook.hidden_test_count > 1 ? 's' : ''}
                    </span>
                  </>
                )}
              </p>
            </>
          )}
        </div>

        <div className="flex items-center gap-2">
          {result && (result.results || []).length > 0 && (
            <button
              type="button"
              onClick={onViewDetails}
              className="rounded-lg border border-surface-200 dark:border-surface-700 px-3 py-2 text-xs font-medium text-surface-600 dark:text-surface-300 hover:bg-surface-50 dark:hover:bg-surface-700"
            >
              View results
            </button>
          )}
          <button
            type="button"
            onClick={onSubmit}
            disabled={!canSubmit}
            title={
              canSubmit
                ? 'Submit for grading'
                : notebook.is_past_due
                  ? 'The due date has passed'
                  : 'No attempts remaining'
            }
            className={`inline-flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-semibold transition-colors ${
              canSubmit
                ? 'bg-emerald-600 text-white hover:bg-emerald-700'
                : 'bg-surface-100 dark:bg-surface-700 text-surface-400 dark:text-surface-500 cursor-not-allowed'
            }`}
          >
            {hasSubmitted && canSubmit
              ? <><RefreshCw className="w-4 h-4" /> Resubmit</>
              : <><Send className="w-4 h-4" /> Submit</>}
          </button>
        </div>
      </div>

      {!notebook.can_submit && (
        <p className="border-t border-surface-100 dark:border-surface-700 px-4 py-2 text-xs text-surface-500 dark:text-surface-400">
          {notebook.is_past_due
            ? 'The due date has passed, so this lab no longer accepts submissions.'
            : notebook.allow_resubmission
              ? 'You have used all of your attempts, so this lab can no longer be submitted.'
              : 'This lab allowed a single submission, which you have already used.'}
        </p>
      )}

      {history.length > 0 && (
        <div className="border-t border-surface-100 dark:border-surface-700">
          <button
            type="button"
            onClick={() => setShowHistory((v) => !v)}
            className="flex w-full items-center gap-2 px-4 py-2.5 text-xs font-semibold text-surface-500 dark:text-surface-400 hover:text-surface-700 dark:hover:text-surface-200"
          >
            <History className="w-3.5 h-3.5" />
            Previous attempts ({history.length})
            <ChevronDown
              className={`ml-auto w-3.5 h-3.5 transition-transform ${showHistory ? 'rotate-180' : ''}`}
            />
          </button>
          {showHistory && (
            <div className="divide-y divide-surface-100 dark:divide-surface-700 border-t border-surface-100 dark:border-surface-700">
              {history.map((s) => (
                <div key={s.id} className="flex items-center gap-3 px-4 py-2 text-xs">
                  <span className="font-medium text-surface-700 dark:text-surface-200">
                    Attempt {s.attempt_number}
                  </span>
                  <span className="text-surface-400">
                    {new Date(s.submitted_at).toLocaleString()}
                  </span>
                  <span className="ml-auto font-semibold text-surface-600 dark:text-surface-300 tabular-nums">
                    {s.status === 'graded'
                      ? `${s.passed_points}/${s.total_points} pts`
                      : s.status}
                  </span>
                  {s.final_marks !== null && (
                    <span className="font-semibold text-emerald-600">
                      {s.final_marks} marks
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </motion.div>
  )
}

export default LabStatusCard
