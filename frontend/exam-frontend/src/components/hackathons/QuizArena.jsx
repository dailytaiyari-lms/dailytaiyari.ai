import { useMemo, useState } from 'react'
import { CheckCircle2, Circle, Flag, ChevronLeft, ChevronRight, Send } from 'lucide-react'
import { RichContent } from './hackathonShared'

/**
 * Timed MCQ / numerical / subjective paper with a question palette.
 * `answers` is a controlled map of itemId -> answer object.
 */
const QuizArena = ({ items, answers, onChange, onSubmit, readOnly = false, revealed = false, myAnswers = [] }) => {
  const [index, setIndex] = useState(0)
  const [flagged, setFlagged] = useState({})

  const resultByItem = useMemo(() => {
    const map = {}
    myAnswers.forEach((a) => { map[a.item_id] = a })
    return map
  }, [myAnswers])

  if (!items?.length) {
    return (
      <div className="card p-10 text-center text-surface-500">
        The organisers haven't added any questions to this round yet.
      </div>
    )
  }

  const item = items[index]
  const answer = answers[item.id] || {}
  const result = resultByItem[item.id]

  const answeredCount = items.filter((i) => {
    const a = answers[i.id]
    if (!a) return false
    return (a.selected_options?.length > 0)
      || (a.numerical_answer !== undefined && a.numerical_answer !== '')
      || Boolean(a.answer_text?.trim())
  }).length

  const setAnswer = (patch) => onChange(item.id, { ...answer, ...patch })

  const toggleOption = (optionIndex) => {
    if (readOnly) return
    const current = answer.selected_options || []
    if (item.item_type === 'mcq') {
      setAnswer({ selected_options: current[0] === optionIndex ? [] : [optionIndex] })
    } else {
      setAnswer({
        selected_options: current.includes(optionIndex)
          ? current.filter((i) => i !== optionIndex)
          : [...current, optionIndex].sort((a, b) => a - b),
      })
    }
  }

  const paletteTone = (i) => {
    const a = answers[items[i].id]
    const done = a && ((a.selected_options?.length > 0)
      || (a.numerical_answer !== undefined && a.numerical_answer !== '')
      || Boolean(a.answer_text?.trim()))
    if (i === index) return 'bg-primary-600 text-white ring-2 ring-primary-300'
    if (flagged[items[i].id]) return 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300'
    if (done) return 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300'
    return 'bg-surface-100 text-surface-500 dark:bg-surface-800 dark:text-surface-400'
  }

  return (
    <div className="grid lg:grid-cols-[1fr_240px] gap-6">
      {/* Paper */}
      <div className="card p-6">
        <div className="flex items-center justify-between gap-3 mb-4">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold">Question {index + 1}</span>
            <span className="text-xs text-surface-400">of {items.length}</span>
            <span className="badge badge-primary">{item.marks} mark{item.marks === 1 ? '' : 's'}</span>
            {item.negative_marks > 0 && (
              <span className="badge badge-error">-{item.negative_marks} wrong</span>
            )}
          </div>
          {!readOnly && (
            <button
              type="button"
              onClick={() => setFlagged((f) => ({ ...f, [item.id]: !f[item.id] }))}
              className={`btn-icon ${flagged[item.id] ? 'text-amber-500' : ''}`}
              title="Flag for review"
            >
              <Flag className="w-4 h-4" />
            </button>
          )}
        </div>

        {item.question_html
          ? <RichContent content={item.question_html} />
          : <p className="whitespace-pre-wrap">{item.question_text}</p>}
        {item.question_image && (
          <img src={item.question_image} alt="" className="mt-3 rounded-xl max-h-72" />
        )}

        <div className="mt-5 space-y-2.5">
          {(item.item_type === 'mcq' || item.item_type === 'mcq_multi') && (
            item.options.map((option) => {
              const selected = (answer.selected_options || []).includes(option.index)
              const isCorrect = revealed && (item.correct_options || []).includes(option.index)
              const isWrongPick = revealed && selected && !isCorrect
              return (
                <button
                  key={option.index}
                  type="button"
                  disabled={readOnly}
                  onClick={() => toggleOption(option.index)}
                  className={`w-full text-left p-3.5 rounded-xl border-2 flex items-start gap-3 transition-colors ${
                    isCorrect
                      ? 'border-emerald-400 bg-emerald-50 dark:bg-emerald-900/20'
                      : isWrongPick
                        ? 'border-rose-400 bg-rose-50 dark:bg-rose-900/20'
                        : selected
                          ? 'border-primary-500 bg-primary-50 dark:bg-primary-900/20'
                          : 'border-surface-200 dark:border-surface-700 hover:border-primary-300'
                  } ${readOnly ? 'cursor-default' : ''}`}
                >
                  {selected
                    ? <CheckCircle2 className="w-5 h-5 shrink-0 mt-0.5 text-primary-600" />
                    : <Circle className="w-5 h-5 shrink-0 mt-0.5 text-surface-300" />}
                  <span className="flex-1">
                    {option.text}
                    {option.image && <img src={option.image} alt="" className="mt-2 rounded-lg max-h-40" />}
                  </span>
                </button>
              )
            })
          )}

          {item.item_type === 'numerical' && (
            <label className="block">
              <span className="text-sm font-medium">Your answer</span>
              <input
                type="number"
                step="any"
                readOnly={readOnly}
                className="input mt-1 max-w-xs"
                value={answer.numerical_answer ?? ''}
                onChange={(e) => setAnswer({ numerical_answer: e.target.value })}
              />
              {item.numerical_tolerance > 0 && (
                <span className="block text-xs text-surface-400 mt-1">
                  Tolerance ±{item.numerical_tolerance}
                </span>
              )}
            </label>
          )}

          {item.item_type === 'subjective' && (
            <label className="block">
              <span className="text-sm font-medium">Your answer</span>
              <textarea
                readOnly={readOnly}
                className="input mt-1 min-h-[180px] font-normal"
                value={answer.answer_text || ''}
                onChange={(e) => setAnswer({ answer_text: e.target.value })}
                placeholder="Write your response…"
              />
              <span className="block text-xs text-surface-400 mt-1">
                {(answer.answer_text || '').trim().split(/\s+/).filter(Boolean).length} words
                {item.max_words ? ` · max ${item.max_words}` : ''}
                {' · reviewed by a judge'}
              </span>
            </label>
          )}
        </div>

        {revealed && (result || item.explanation) && (
          <div className="mt-5 pt-5 border-t border-surface-100 dark:border-surface-800">
            {result && (
              <p className="text-sm font-medium mb-2">
                You scored {result.marks_obtained} / {result.max_marks}
                {result.feedback ? ` — ${result.feedback}` : ''}
              </p>
            )}
            {item.explanation && (
              <>
                <p className="text-sm font-semibold mb-1">Explanation</p>
                <RichContent content={item.explanation} />
              </>
            )}
          </div>
        )}

        <div className="flex items-center justify-between gap-3 mt-6 pt-5 border-t border-surface-100 dark:border-surface-800">
          <button
            type="button"
            className="btn-secondary"
            disabled={index === 0}
            onClick={() => setIndex((i) => i - 1)}
          >
            <ChevronLeft className="w-4 h-4" /> Previous
          </button>
          {index < items.length - 1 ? (
            <button type="button" className="btn-primary" onClick={() => setIndex((i) => i + 1)}>
              Next <ChevronRight className="w-4 h-4" />
            </button>
          ) : !readOnly && (
            <button type="button" className="btn-primary" onClick={onSubmit}>
              <Send className="w-4 h-4" /> Submit round
            </button>
          )}
        </div>
      </div>

      {/* Palette */}
      <aside className="lg:sticky lg:top-24 h-fit space-y-4">
        <div className="card p-4">
          <div className="flex items-center justify-between text-sm mb-3">
            <span className="font-semibold">Progress</span>
            <span className="text-surface-500">{answeredCount}/{items.length}</span>
          </div>
          <div className="h-1.5 rounded-full bg-surface-100 dark:bg-surface-800 overflow-hidden mb-4">
            <div
              className="h-full bg-primary-500 transition-all"
              style={{ width: `${(answeredCount / items.length) * 100}%` }}
            />
          </div>
          <div className="grid grid-cols-5 gap-1.5">
            {items.map((_, i) => (
              <button
                key={i}
                type="button"
                onClick={() => setIndex(i)}
                className={`aspect-square rounded-lg text-xs font-semibold transition-all ${paletteTone(i)}`}
              >
                {i + 1}
              </button>
            ))}
          </div>
        </div>

        {!readOnly && (
          <button type="button" className="btn-primary w-full justify-center" onClick={onSubmit}>
            <Send className="w-4 h-4" /> Submit round
          </button>
        )}
      </aside>
    </div>
  )
}

export default QuizArena
