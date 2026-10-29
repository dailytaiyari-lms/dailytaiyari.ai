import { useState } from 'react'
import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { AlertTriangle, ChevronLeft, ChevronRight } from 'lucide-react'
import { insightsService } from '../../services/insightsService'
import Loading from '../common/Loading'
import { CONFIDENCE_TEXT, LABEL_COLOR } from './labels'

const SELF_REPORT_TEXT = {
  slipped: 'Knew it, slipped',
  ran_out_of_time: 'Ran out of time',
  guessed: 'Guessed',
  didnt_know: "Didn't know",
}

/** Teacher view: one student's diagnosed answers, newest attempt first. */
export default function StudentAnswersTab({ studentId }) {
  const [page, setPage] = useState(1)
  const [highlight, setHighlight] = useState(null) // Set of answer ids from a pattern
  const { data, isLoading } = useQuery({
    queryKey: ['studentAnswers', studentId, page],
    queryFn: () => insightsService.getStudentAnswers(studentId, page),
    placeholderData: keepPreviousData,
  })

  if (isLoading) return <Loading />
  if (!data) return null

  return (
    <div className="space-y-4">
      {page === 1 && data.patterns.length > 0 && (
        <div className="p-4 rounded-2xl bg-warning-50 dark:bg-warning-900/10 border border-warning-200 dark:border-warning-900/30">
          <h3 className="text-sm font-semibold mb-2 flex items-center gap-1">
            <AlertTriangle size={14} className="text-warning-500" /> Patterns in the last 10 attempts
          </h3>
          <ul className="flex flex-wrap gap-2">
            {data.patterns.map((pattern) => {
              const active = highlight && pattern.answer_ids.every((id) => highlight.has(id))
              return (
                <li key={pattern.code}>
                  <button
                    type="button"
                    onClick={() => setHighlight(active ? null : new Set(pattern.answer_ids))}
                    className={`text-xs px-3 py-1 rounded-full border ${
                      active ? 'bg-warning-500 border-warning-500 text-white' : 'border-warning-400'
                    }`}
                  >
                    {pattern.message} · {pattern.count}
                  </button>
                </li>
              )
            })}
          </ul>
        </div>
      )}

      {data.attempts.length === 0 && (
        <p className="text-sm text-surface-400">No diagnosed answers yet.</p>
      )}

      {data.attempts.map((attempt) => (
        <div
          key={`${attempt.attempt_kind}:${attempt.attempt_id}`}
          className="p-4 rounded-2xl bg-white dark:bg-surface-800 border border-surface-200 dark:border-surface-700"
        >
          <div className="flex items-center justify-between gap-2 mb-2">
            <h4 className="font-medium text-sm">{attempt.title}</h4>
            <span className="text-xs text-surface-400">
              {attempt.completed_at ? new Date(attempt.completed_at).toLocaleString() : ''}
            </span>
          </div>
          <ul className="divide-y divide-surface-100 dark:divide-surface-700/50">
            {attempt.answers.map((answer) => (
              <li
                key={answer.id}
                className={`py-2 text-sm ${highlight?.has(answer.id) ? 'bg-warning-50 dark:bg-warning-900/10 -mx-2 px-2 rounded-lg' : ''}`}
              >
                <div className="flex items-start justify-between gap-3">
                  <span className="truncate">{answer.question_text}</span>
                  <span className="inline-flex items-center gap-1.5 shrink-0 text-xs">
                    <span className={`w-2 h-2 rounded-full ${LABEL_COLOR[answer.label]}`} />
                    {answer.label_display}
                    <span className="text-surface-400">({CONFIDENCE_TEXT[answer.confidence]})</span>
                  </span>
                </div>
                <div className="text-xs text-surface-500 mt-0.5 space-y-0.5">
                  {answer.topic && <p className="text-surface-400">{answer.topic}</p>}
                  {answer.evidence.map((sentence) => <p key={sentence}>{sentence}</p>)}
                  {answer.active_s != null && <p>On screen {Math.round(answer.active_s)} s</p>}
                  {answer.self_report && (
                    <p>Student said: “{SELF_REPORT_TEXT[answer.self_report] || answer.self_report}”</p>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </div>
      ))}

      {data.pages > 1 && (
        <div className="flex items-center justify-center gap-3 text-sm">
          <button
            type="button"
            disabled={page <= 1}
            onClick={() => { setHighlight(null); setPage(page - 1) }}
            className="p-2 rounded-lg disabled:opacity-40 hover:bg-surface-100 dark:hover:bg-surface-800"
          >
            <ChevronLeft size={16} />
          </button>
          <span>Page {data.page} of {data.pages}</span>
          <button
            type="button"
            disabled={page >= data.pages}
            onClick={() => { setHighlight(null); setPage(page + 1) }}
            className="p-2 rounded-lg disabled:opacity-40 hover:bg-surface-100 dark:hover:bg-surface-800"
          >
            <ChevronRight size={16} />
          </button>
        </div>
      )}
    </div>
  )
}
