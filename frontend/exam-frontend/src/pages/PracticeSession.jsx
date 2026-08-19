import { useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { practiceService } from '../services/practiceService'
import Loading from '../components/common/Loading'
import { DeficitChip } from './Practice'
import { ArrowRight, CheckCircle2, XCircle, PartyPopper, TrendingUp } from 'lucide-react'

/**
 * Formative practice player: one question at a time, graded immediately with
 * the explanation shown before moving on — practice is learning, not testing.
 */
const PracticeSession = () => {
  const { setId } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const [index, setIndex] = useState(0)
  const [selected, setSelected] = useState([])
  const [numerical, setNumerical] = useState('')
  const [review, setReview] = useState(null) // grading payload for current item
  const [startedAt, setStartedAt] = useState(Date.now())
  const [summary, setSummary] = useState(null)

  const { data: set, isLoading } = useQuery({
    queryKey: ['practiceSet', setId],
    queryFn: () => practiceService.getSet(setId),
  })

  const items = useMemo(
    () => (set?.items ?? []).filter((item) => !item.answered),
    // Freeze the queue on first load; answered state changes locally after.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [set?.id],
  )
  const item = items[index]

  const answerMutation = useMutation({
    mutationFn: (payload) => practiceService.answerItem(setId, payload),
    onSuccess: (data) => setReview(data),
  })

  const submitMutation = useMutation({
    mutationFn: () => practiceService.submitSet(setId),
    onSuccess: (data) => {
      setSummary(data)
      queryClient.invalidateQueries({ queryKey: ['practiceSets'] })
      queryClient.invalidateQueries({ queryKey: ['practiceMastery'] })
    },
  })

  if (isLoading) return <Loading fullScreen />
  if (!set) return null

  const total = items.length
  const answeredCount = review ? index + 1 : index

  const submitAnswer = () => {
    const payload = {
      item_id: item.id,
      time_taken_seconds: Math.round((Date.now() - startedAt) / 1000),
    }
    if (item.question_type === 'numerical') {
      payload.numerical_answer = numerical
    } else {
      payload.selected_options = selected
    }
    answerMutation.mutate(payload)
  }

  const nextQuestion = () => {
    setReview(null)
    setSelected([])
    setNumerical('')
    setStartedAt(Date.now())
    if (index + 1 < total) {
      setIndex(index + 1)
    } else {
      submitMutation.mutate()
    }
  }

  const toggleOption = (optionIndex) => {
    if (review) return
    if (item.question_type === 'mcq') {
      setSelected([optionIndex])
    } else {
      setSelected((current) =>
        current.includes(optionIndex)
          ? current.filter((i) => i !== optionIndex)
          : [...current, optionIndex],
      )
    }
  }

  // ── Finish screen ────────────────────────────────────────────────────────
  if (summary) {
    const deltas = Object.keys(summary.mastery_after || {}).map((conceptId) => ({
      before: summary.mastery_before?.[conceptId],
      after: summary.mastery_after[conceptId],
    }))
    return (
      <div className="max-w-xl mx-auto text-center space-y-6 py-10">
        <PartyPopper size={44} className="mx-auto text-primary-500" />
        <h1 className="text-2xl font-display font-bold">Set complete</h1>
        <p className="text-4xl font-bold">
          {summary.score_correct}
          <span className="text-surface-400 text-2xl">/{summary.score_total}</span>
        </p>
        {summary.xp_awarded > 0 && (
          <p className="text-warning-500 font-medium">+{summary.xp_awarded} XP</p>
        )}
        {deltas.map(
          (delta, i) =>
            delta.before !== undefined &&
            delta.after !== undefined &&
            delta.after !== delta.before && (
              <p key={i} className="inline-flex items-center gap-2 text-sm text-surface-500">
                <TrendingUp size={16} className={delta.after > delta.before ? 'text-success-500' : 'text-danger-500'} />
                Mastery {Math.round(delta.before * 100)}% → {Math.round(delta.after * 100)}%
              </p>
            ),
        )}
        <button
          onClick={() => navigate('/practice')}
          className="px-6 py-3 rounded-xl bg-primary-500 text-white font-medium hover:bg-primary-600 transition-colors"
        >
          Back to Practice
        </button>
      </div>
    )
  }

  if (!item) {
    // Everything already answered (e.g. reload mid-set) — allow submission.
    return (
      <div className="max-w-xl mx-auto text-center space-y-6 py-10">
        <p className="text-surface-500">All questions in this set are answered.</p>
        <button
          onClick={() => submitMutation.mutate()}
          disabled={submitMutation.isPending}
          className="px-6 py-3 rounded-xl bg-primary-500 text-white font-medium hover:bg-primary-600 transition-colors disabled:opacity-50"
        >
          Finish set
        </button>
      </div>
    )
  }

  const canSubmit =
    item.question_type === 'numerical' ? numerical.trim() !== '' : selected.length > 0

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      {/* Header: why + progress */}
      <div className="space-y-3">
        <div className="flex items-center justify-between gap-3">
          <DeficitChip kind={set.deficit_kind} />
          <span className="text-sm text-surface-400">
            {answeredCount}/{total}
          </span>
        </div>
        <p className="text-sm text-surface-500">{set.reason_text}</p>
        <div className="flex gap-1.5">
          {items.map((_, i) => (
            <div
              key={i}
              className={`h-1.5 flex-1 rounded-full ${
                i < answeredCount ? 'bg-primary-500' : 'bg-surface-200 dark:bg-surface-700'
              }`}
            />
          ))}
        </div>
      </div>

      {/* Question */}
      <div className="p-6 rounded-2xl bg-white dark:bg-surface-800 border border-surface-200 dark:border-surface-700 space-y-5">
        <div className="flex items-start justify-between gap-3">
          <p className="font-medium whitespace-pre-wrap">{item.question_text}</p>
          <span className="text-xs px-2 py-1 rounded-full bg-surface-100 dark:bg-surface-700 text-surface-500 capitalize shrink-0">
            {item.difficulty}
          </span>
        </div>

        {item.question_type === 'numerical' ? (
          <input
            type="text"
            inputMode="decimal"
            value={numerical}
            onChange={(e) => setNumerical(e.target.value)}
            disabled={!!review}
            placeholder="Your numeric answer"
            className="w-full px-4 py-3 rounded-xl border border-surface-300 dark:border-surface-600 bg-transparent focus:outline-none focus:ring-2 focus:ring-primary-500"
          />
        ) : (
          <div className="space-y-2">
            {item.options.map((option) => {
              const isPicked = selected.includes(option.index)
              const isCorrectOption = review?.correct_options?.includes(option.index)
              let className =
                'w-full text-left px-4 py-3 rounded-xl border transition-colors '
              if (review) {
                if (isCorrectOption) {
                  className += 'border-success-500 bg-success-50 dark:bg-success-900/20'
                } else if (isPicked) {
                  className += 'border-danger-500 bg-danger-50 dark:bg-danger-900/20'
                } else {
                  className += 'border-surface-200 dark:border-surface-700 opacity-60'
                }
              } else if (isPicked) {
                className += 'border-primary-500 bg-primary-50 dark:bg-primary-900/20'
              } else {
                className +=
                  'border-surface-200 dark:border-surface-700 hover:border-primary-300'
              }
              return (
                <button key={option.index} onClick={() => toggleOption(option.index)} className={className}>
                  {option.text}
                </button>
              )
            })}
          </div>
        )}

        {/* Post-answer review */}
        {review && (
          <div
            className={`p-4 rounded-xl ${
              review.is_correct
                ? 'bg-success-50 dark:bg-success-900/20'
                : 'bg-danger-50 dark:bg-danger-900/20'
            }`}
          >
            <p className="flex items-center gap-2 font-medium">
              {review.is_correct ? (
                <>
                  <CheckCircle2 size={18} className="text-success-500" /> Correct
                </>
              ) : (
                <>
                  <XCircle size={18} className="text-danger-500" /> Not quite
                  {review.correct_numerical != null && (
                    <span className="text-sm font-normal text-surface-500">
                      — answer: {review.correct_numerical}
                    </span>
                  )}
                </>
              )}
            </p>
            {review.explanation && (
              <p className="text-sm text-surface-600 dark:text-surface-300 mt-2 whitespace-pre-wrap">
                {review.explanation}
              </p>
            )}
          </div>
        )}

        <div className="flex justify-end">
          {review ? (
            <button
              onClick={nextQuestion}
              disabled={submitMutation.isPending}
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-primary-500 text-white font-medium hover:bg-primary-600 transition-colors disabled:opacity-50"
            >
              {index + 1 < total ? 'Next question' : 'Finish set'}
              <ArrowRight size={16} />
            </button>
          ) : (
            <button
              onClick={submitAnswer}
              disabled={!canSubmit || answerMutation.isPending}
              className="px-5 py-2.5 rounded-xl bg-primary-500 text-white font-medium hover:bg-primary-600 transition-colors disabled:opacity-40"
            >
              Check answer
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

export default PracticeSession
