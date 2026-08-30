import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  Plus, Trash2, Pencil, X, Loader2, CheckCircle2, Circle, Wand2,
} from 'lucide-react'
import { hackathonAdminService } from '../../../services/hackathonAdminService'
import {
  useDragReorder, DragHandle, ReorderStatus, ImageDrop, imagePayload, formatApiError,
} from '../builderShared'

const QUIZ_ITEM_TYPES = [
  { value: 'mcq', label: 'Single choice' },
  { value: 'mcq_multi', label: 'Multiple choice' },
  { value: 'numerical', label: 'Numerical' },
  { value: 'subjective', label: 'Written answer' },
]

const LANGUAGES = [
  { value: 'python', label: 'Python' },
  { value: 'cpp', label: 'C++' },
  { value: 'java', label: 'Java' },
]

const TYPE_LABEL = {
  mcq: 'Single choice',
  mcq_multi: 'Multiple choice',
  numerical: 'Numerical',
  subjective: 'Written answer',
  coding: 'Coding',
}

const blankItem = (stageType) => (stageType === 'coding'
  ? {
    item_type: 'coding', title: '', question_text: '', question_html: '',
    explanation: '', difficulty: 'medium', marks: 10, negative_marks: 0,
    allowed_languages: ['python'], starter_code: {}, time_limit_ms: 2000,
    memory_limit_mb: 256, coding_test_cases: [{ stdin: '', expected_output: '', is_sample: true, points: 1 }],
    options: [],
  }
  : {
    item_type: 'mcq', title: '', question_text: '', question_html: '',
    explanation: '', difficulty: 'medium', marks: 1, negative_marks: 0,
    options: [
      { text: '', is_correct: true }, { text: '', is_correct: false },
      { text: '', is_correct: false }, { text: '', is_correct: false },
    ],
    numerical_answer: null, numerical_tolerance: 0, max_words: 0,
    rubric: '', model_answer: '', question_image: '',
  })

const Field = ({ label, hint, children, className = '' }) => (
  <label className={`block ${className}`}>
    <span className="text-sm font-medium">{label}</span>
    {children}
    {hint && <span className="block text-xs text-surface-400 mt-1">{hint}</span>}
  </label>
)

// ─────────────────────────────────────────────────────────────────────────────

const ItemModal = ({ stageType, instance, onClose, onSubmit, saving }) => {
  const [form, setForm] = useState(() => ({
    ...blankItem(stageType),
    ...(instance || {}),
    question_image: instance?.question_image_url || '',
  }))

  const set = (key) => (e) => {
    const value = e.target.type === 'checkbox' ? e.target.checked : e.target.value
    setForm((f) => ({ ...f, [key]: value }))
  }
  const setNumber = (key) => (e) => setForm((f) => ({
    ...f, [key]: e.target.value === '' ? null : Number(e.target.value),
  }))

  const isChoice = form.item_type === 'mcq' || form.item_type === 'mcq_multi'
  const isCoding = form.item_type === 'coding'

  const setOption = (i, patch) => setForm((f) => ({
    ...f,
    options: f.options.map((o, idx) => {
      if (idx !== i) {
        // Single-choice questions can only have one correct answer.
        return f.item_type === 'mcq' && patch.is_correct ? { ...o, is_correct: false } : o
      }
      return { ...o, ...patch }
    }),
  }))

  const setCase = (i, patch) => setForm((f) => ({
    ...f,
    coding_test_cases: f.coding_test_cases.map((c, idx) => idx === i ? { ...c, ...patch } : c),
  }))

  const toggleLanguage = (lang) => setForm((f) => {
    const current = f.allowed_languages || []
    return {
      ...f,
      allowed_languages: current.includes(lang)
        ? current.filter((l) => l !== lang)
        : [...current, lang],
    }
  })

  const submit = (e) => {
    e.preventDefault()
    if (!form.question_text.trim() && !form.question_html.trim()) {
      toast.error('Write the question first.')
      return
    }
    const payload = {
      item_type: form.item_type,
      title: form.title,
      question_text: form.question_text,
      question_html: form.question_html,
      explanation: form.explanation,
      difficulty: form.difficulty,
      marks: Number(form.marks) || 0,
      negative_marks: Number(form.negative_marks) || 0,
    }
    if (isChoice) {
      payload.options = form.options.filter((o) => o.text.trim())
    } else if (form.item_type === 'numerical') {
      payload.numerical_answer = form.numerical_answer
      payload.numerical_tolerance = form.numerical_tolerance || 0
    } else if (form.item_type === 'subjective') {
      payload.max_words = form.max_words || 0
      payload.rubric = form.rubric || ''
      payload.model_answer = form.model_answer || ''
    } else if (isCoding) {
      payload.allowed_languages = form.allowed_languages
      payload.starter_code = form.starter_code || {}
      payload.time_limit_ms = form.time_limit_ms
      payload.memory_limit_mb = form.memory_limit_mb
      payload.coding_test_cases = (form.coding_test_cases || [])
        .filter((c) => c.expected_output !== undefined)
        .map((c) => ({
          stdin: c.stdin || '',
          expected_output: c.expected_output || '',
          is_sample: Boolean(c.is_sample),
          points: Number(c.points) || 1,
          explanation: c.explanation || '',
        }))
    }
    if (!isCoding) {
      const image = imagePayload(form.question_image, instance?.question_image_url)
      if (image.send) payload.question_image = image.value
    }
    onSubmit(payload)
  }

  return (
    <div className="fixed inset-0 z-[60] flex items-start justify-center p-4 bg-black/50 overflow-y-auto">
      <form onSubmit={submit} className="card w-full max-w-3xl my-8 p-0 overflow-hidden">
        <div className="flex items-center justify-between gap-4 p-5 border-b border-surface-100 dark:border-surface-800">
          <h3 className="font-semibold">{instance ? 'Edit question' : 'New question'}</h3>
          <button type="button" onClick={onClose} className="btn-icon"><X className="w-4 h-4" /></button>
        </div>

        <div className="p-5 space-y-4 max-h-[65vh] overflow-y-auto">
          {!isCoding && (
            <div className="grid sm:grid-cols-3 gap-4">
              <Field label="Question type">
                <select className="input mt-1" value={form.item_type} onChange={set('item_type')}>
                  {QUIZ_ITEM_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
                </select>
              </Field>
              <Field label="Marks">
                <input type="number" min="0" step="0.5" className="input mt-1" value={form.marks} onChange={setNumber('marks')} />
              </Field>
              <Field label="Negative marks" hint="Applied on a wrong attempt.">
                <input type="number" min="0" step="0.25" className="input mt-1" value={form.negative_marks} onChange={setNumber('negative_marks')} />
              </Field>
            </div>
          )}

          {isCoding && (
            <div className="grid sm:grid-cols-3 gap-4">
              <Field label="Marks">
                <input type="number" min="0" className="input mt-1" value={form.marks} onChange={setNumber('marks')} />
              </Field>
              <Field label="Time limit (ms)">
                <input type="number" min="100" className="input mt-1" value={form.time_limit_ms} onChange={setNumber('time_limit_ms')} />
              </Field>
              <Field label="Memory (MB)">
                <input type="number" min="16" className="input mt-1" value={form.memory_limit_mb} onChange={setNumber('memory_limit_mb')} />
              </Field>
            </div>
          )}

          <Field label="Title" hint="Optional short name — handy for coding problems.">
            <input className="input mt-1" value={form.title} onChange={set('title')} />
          </Field>

          <Field label="Question *">
            <textarea className="input mt-1 min-h-[120px]" value={form.question_text} onChange={set('question_text')} />
          </Field>

          {!isCoding && (
            <Field label="Question image">
              <ImageDrop
                value={form.question_image}
                onChange={(v) => setForm((f) => ({ ...f, question_image: v }))}
                label="question image"
              />
            </Field>
          )}

          {isChoice && (
            <div>
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium">Options</span>
                <button
                  type="button"
                  className="btn-secondary text-xs !py-1"
                  onClick={() => setForm((f) => ({ ...f, options: [...f.options, { text: '', is_correct: false }] }))}
                >
                  <Plus className="w-3.5 h-3.5" /> Add option
                </button>
              </div>
              <p className="text-xs text-surface-400 mt-1">
                Click the circle to mark the correct answer
                {form.item_type === 'mcq_multi' ? 's' : ''}.
              </p>
              <div className="space-y-2 mt-2">
                {form.options.map((option, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => setOption(i, { is_correct: !option.is_correct })}
                      className="shrink-0"
                      title="Mark as correct"
                    >
                      {option.is_correct
                        ? <CheckCircle2 className="w-5 h-5 text-emerald-500" />
                        : <Circle className="w-5 h-5 text-surface-300" />}
                    </button>
                    <input
                      className="input !py-1.5 text-sm"
                      placeholder={`Option ${i + 1}`}
                      value={option.text}
                      onChange={(e) => setOption(i, { text: e.target.value })}
                    />
                    <button
                      type="button" className="btn-icon shrink-0"
                      onClick={() => setForm((f) => ({ ...f, options: f.options.filter((_, idx) => idx !== i) }))}
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {form.item_type === 'numerical' && (
            <div className="grid sm:grid-cols-2 gap-4">
              <Field label="Correct answer *">
                <input type="number" step="any" className="input mt-1" value={form.numerical_answer ?? ''} onChange={setNumber('numerical_answer')} />
              </Field>
              <Field label="Tolerance" hint="Answers within ± this margin count as correct.">
                <input type="number" step="any" min="0" className="input mt-1" value={form.numerical_tolerance ?? 0} onChange={setNumber('numerical_tolerance')} />
              </Field>
            </div>
          )}

          {form.item_type === 'subjective' && (
            <>
              <Field label="Word limit" hint="0 = no limit.">
                <input type="number" min="0" className="input mt-1 max-w-xs" value={form.max_words ?? 0} onChange={setNumber('max_words')} />
              </Field>
              <Field label="Marking rubric" hint="Only you see this — it guides manual grading.">
                <textarea className="input mt-1 min-h-[80px]" value={form.rubric || ''} onChange={set('rubric')} />
              </Field>
              <Field label="Model answer">
                <textarea className="input mt-1 min-h-[80px]" value={form.model_answer || ''} onChange={set('model_answer')} />
              </Field>
            </>
          )}

          {isCoding && (
            <>
              <div>
                <span className="text-sm font-medium">Allowed languages *</span>
                <div className="flex gap-2 mt-2">
                  {LANGUAGES.map((l) => (
                    <button
                      key={l.value}
                      type="button"
                      onClick={() => toggleLanguage(l.value)}
                      className={`px-3 py-1.5 rounded-lg text-sm font-medium border transition-colors ${
                        (form.allowed_languages || []).includes(l.value)
                          ? 'border-primary-500 bg-primary-50 text-primary-700 dark:bg-primary-900/20 dark:text-primary-300'
                          : 'border-surface-200 dark:border-surface-700 text-surface-500'
                      }`}
                    >
                      {l.label}
                    </button>
                  ))}
                </div>
              </div>

              {(form.allowed_languages || []).map((lang) => (
                <Field key={lang} label={`Starter code — ${LANGUAGES.find((l) => l.value === lang)?.label || lang}`}>
                  <textarea
                    className="input mt-1 min-h-[80px] font-mono text-xs"
                    value={form.starter_code?.[lang] || ''}
                    onChange={(e) => setForm((f) => ({
                      ...f, starter_code: { ...(f.starter_code || {}), [lang]: e.target.value },
                    }))}
                  />
                </Field>
              ))}

              <div>
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium">Test cases *</span>
                  <button
                    type="button"
                    className="btn-secondary text-xs !py-1"
                    onClick={() => setForm((f) => ({
                      ...f,
                      coding_test_cases: [...(f.coding_test_cases || []),
                        { stdin: '', expected_output: '', is_sample: false, points: 1 }],
                    }))}
                  >
                    <Plus className="w-3.5 h-3.5" /> Add case
                  </button>
                </div>
                <p className="text-xs text-surface-400 mt-1">
                  Sample cases are visible to participants and used by “Run”. The rest stay hidden
                  and decide the score.
                </p>
                <div className="space-y-3 mt-2">
                  {(form.coding_test_cases || []).map((c, i) => (
                    <div key={i} className="rounded-xl border border-surface-200 dark:border-surface-700 p-3 space-y-2">
                      <div className="flex items-center justify-between gap-2">
                        <label className="flex items-center gap-2 text-xs font-medium">
                          <input type="checkbox" checked={Boolean(c.is_sample)} onChange={(e) => setCase(i, { is_sample: e.target.checked })} />
                          Visible sample
                        </label>
                        <div className="flex items-center gap-2">
                          <input
                            type="number" min="0" className="input !py-1 !w-20 text-xs"
                            value={c.points ?? 1}
                            onChange={(e) => setCase(i, { points: Number(e.target.value) })}
                            title="Points"
                          />
                          <button
                            type="button" className="btn-icon"
                            onClick={() => setForm((f) => ({
                              ...f, coding_test_cases: f.coding_test_cases.filter((_, idx) => idx !== i),
                            }))}
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </div>
                      <div className="grid sm:grid-cols-2 gap-2">
                        <textarea
                          className="input !py-1.5 text-xs font-mono min-h-[70px]"
                          placeholder="stdin"
                          value={c.stdin || ''}
                          onChange={(e) => setCase(i, { stdin: e.target.value })}
                        />
                        <textarea
                          className="input !py-1.5 text-xs font-mono min-h-[70px]"
                          placeholder="expected output"
                          value={c.expected_output || ''}
                          onChange={(e) => setCase(i, { expected_output: e.target.value })}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}

          <Field label="Explanation" hint="Revealed to participants once round results are published.">
            <textarea className="input mt-1 min-h-[70px]" value={form.explanation || ''} onChange={set('explanation')} />
          </Field>
        </div>

        <div className="flex items-center justify-end gap-2 p-5 border-t border-surface-100 dark:border-surface-800">
          <button type="button" className="btn-secondary" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn-primary" disabled={saving}>
            {saving && <Loader2 className="w-4 h-4 animate-spin" />}
            {instance ? 'Save question' : 'Add question'}
          </button>
        </div>
      </form>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────

const StageItemsEditor = ({ stage, onOpenAi }) => {
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(null)
  const [showModal, setShowModal] = useState(false)
  const [reorderSaving, setReorderSaving] = useState(false)

  const key = ['admin-hackathon-items', stage.id]
  const { data: items = [], isLoading } = useQuery({
    queryKey: key,
    queryFn: () => hackathonAdminService.getItems(stage.id),
  })

  const refresh = () => queryClient.invalidateQueries({ queryKey: key })

  const saveMutation = useMutation({
    mutationFn: (payload) => (editing
      ? hackathonAdminService.updateItem(editing.id, payload)
      : hackathonAdminService.createItem(stage.id, payload)),
    onSuccess: () => {
      toast.success(editing ? 'Question updated' : 'Question added')
      setShowModal(false)
      setEditing(null)
      refresh()
    },
    onError: (err) => toast.error(formatApiError(err, 'Could not save the question')),
  })

  const deleteMutation = useMutation({
    mutationFn: (id) => hackathonAdminService.deleteItem(id),
    onSuccess: () => { toast.success('Question removed'); refresh() },
    onError: (err) => toast.error(formatApiError(err, 'Could not delete')),
  })

  const reorder = async (ids) => {
    setReorderSaving(true)
    try {
      await hackathonAdminService.reorderItems(stage.id, ids)
      refresh()
    } catch {
      toast.error('Could not save the new order')
    } finally {
      setReorderSaving(false)
    }
  }

  const { list, draggingId, rowProps, handleProps } = useDragReorder(items, reorder)

  const totalMarks = items.reduce((sum, i) => sum + Number(i.marks || 0), 0)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="font-semibold">
            {stage.stage_type === 'coding' ? 'Problems' : 'Questions'}
          </h3>
          <p className="text-xs text-surface-400 mt-0.5">
            {items.length} item{items.length === 1 ? '' : 's'} · {totalMarks} marks total
          </p>
        </div>
        <div className="flex items-center gap-2">
          {onOpenAi && (
            <button type="button" className="btn-secondary text-sm" onClick={onOpenAi}>
              <Wand2 className="w-4 h-4" /> Generate with AI
            </button>
          )}
          <button
            type="button" className="btn-primary text-sm"
            onClick={() => { setEditing(null); setShowModal(true) }}
          >
            <Plus className="w-4 h-4" /> Add {stage.stage_type === 'coding' ? 'problem' : 'question'}
          </button>
        </div>
      </div>

      <ReorderStatus saving={reorderSaving} saved={false} />

      {isLoading ? (
        <div className="card p-8 text-center text-surface-400">Loading…</div>
      ) : list.length === 0 ? (
        <div className="card p-8 text-center">
          <p className="text-sm text-surface-500">
            No {stage.stage_type === 'coding' ? 'problems' : 'questions'} yet. Add them by
            hand, or let the AI Studio draft a full set for this round.
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {list.map((item, index) => (
            <div
              key={item.id}
              {...rowProps(item.id)}
              className={`card p-3 flex items-start gap-3 ${
                draggingId === item.id ? 'opacity-50' : ''
              }`}
            >
              <DragHandle {...handleProps(item.id)} className="mt-1 shrink-0" />
              <span className="w-6 h-6 rounded-lg bg-surface-100 dark:bg-surface-800 text-xs font-semibold flex items-center justify-center shrink-0 mt-0.5">
                {index + 1}
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-sm line-clamp-2">
                  {item.title || item.question_text || '(untitled)'}
                </p>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-surface-400 mt-1">
                  <span>{TYPE_LABEL[item.item_type] || item.item_type}</span>
                  <span>{item.marks} marks</span>
                  {item.negative_marks > 0 && <span>-{item.negative_marks} wrong</span>}
                  {item.item_type === 'coding' && (
                    <span>{(item.coding_test_cases || []).length} test cases</span>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-1 shrink-0">
                <button
                  type="button" className="btn-icon"
                  onClick={() => { setEditing(item); setShowModal(true) }}
                >
                  <Pencil className="w-4 h-4" />
                </button>
                <button
                  type="button" className="btn-icon hover:text-rose-500"
                  onClick={() => {
                    if (window.confirm('Remove this question?')) deleteMutation.mutate(item.id)
                  }}
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {showModal && (
        <ItemModal
          stageType={stage.stage_type}
          instance={editing}
          saving={saveMutation.isPending}
          onClose={() => { setShowModal(false); setEditing(null) }}
          onSubmit={(payload) => saveMutation.mutate(payload)}
        />
      )}
    </div>
  )
}

export default StageItemsEditor
