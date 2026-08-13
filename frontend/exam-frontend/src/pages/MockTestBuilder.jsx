import { useState, useEffect } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  ArrowLeft, Save, Plus, Trash2, GripVertical, Loader2, Settings2, Inbox,
  ListChecks, Calculator, FileText, Code2, CheckSquare, Library, X, Search,
  Sparkles,
} from 'lucide-react'
import { mockTestBuilderService } from '../services/mockTestBuilderService'
import RichMarkdownEditor from '../components/common/RichMarkdownEditor'
import AIMockStudio from '../components/admin/mockAi/AIMockStudio'
import MockAiJobBanners from '../components/admin/mockAi/MockAiJobBanners'

const ITEM_TYPES = [
  { value: 'mcq', label: 'MCQ (single)', icon: ListChecks, color: 'text-blue-500' },
  { value: 'mcq_multi', label: 'MCQ (multiple)', icon: CheckSquare, color: 'text-cyan-500' },
  { value: 'numerical', label: 'Numerical', icon: Calculator, color: 'text-violet-500' },
  { value: 'subjective', label: 'Subjective', icon: FileText, color: 'text-amber-500' },
  { value: 'coding', label: 'Coding', icon: Code2, color: 'text-emerald-500' },
]
const typeMeta = (t) => ITEM_TYPES.find((x) => x.value === t) || ITEM_TYPES[0]

const Field = ({ label, children, hint }) => (
  <label className="block">
    <span className="text-sm font-medium text-surface-700 dark:text-surface-300">{label}</span>
    {hint && <span className="text-xs text-surface-400 ml-2">{hint}</span>}
    <div className="mt-1">{children}</div>
  </label>
)
const inputCls =
  'w-full px-3 py-2 rounded-lg border border-surface-200 dark:border-surface-700 bg-white dark:bg-surface-800 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500/40'

export default function MockTestBuilder() {
  const { testId } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const [tab, setTab] = useState('settings')
  const [form, setForm] = useState(null)
  const [editingItem, setEditingItem] = useState(null)
  const [showBank, setShowBank] = useState(false)
  // `?ai=1` lets the mock-test list deep-link straight back into a run that is
  // still in progress, so a reviewable draft is never more than one click away.
  const showAi = searchParams.get('ai') === '1'
  const setShowAi = (open) => setSearchParams(
    (params) => {
      const next = new URLSearchParams(params)
      if (open) next.set('ai', '1')
      else next.delete('ai')
      return next
    },
    { replace: true },
  )

  const { data: test, isLoading } = useQuery({
    queryKey: ['admin-mock-test', testId],
    queryFn: () => mockTestBuilderService.get(testId),
  })
  const { data: items = [] } = useQuery({
    queryKey: ['admin-mock-items', testId],
    queryFn: () => mockTestBuilderService.listItems(testId),
  })
  const { data: bankLinks = [] } = useQuery({
    queryKey: ['admin-mock-bank', testId],
    queryFn: () => mockTestBuilderService.getBankQuestions(testId),
  })
  const { data: courses = [] } = useQuery({
    queryKey: ['admin-courses-for-mock'],
    queryFn: () => mockTestBuilderService.getCourses(),
  })

  useEffect(() => { if (test) setForm(test) }, [test])

  const saveMut = useMutation({
    mutationFn: (payload) => mockTestBuilderService.update(testId, payload),
    onSuccess: (updated) => {
      setForm(updated)
      qc.invalidateQueries({ queryKey: ['admin-mock-test', testId] })
      qc.invalidateQueries({ queryKey: ['admin-mock-tests'] })
      toast.success('Saved')
    },
    onError: (e) => toast.error(e?.response?.data?.detail || 'Save failed'),
  })

  const set = (k) => (v) => setForm((f) => ({ ...f, [k]: v }))
  const toggleCourse = (id) => setForm((f) => {
    const has = (f.courses || []).includes(id)
    return { ...f, courses: has ? f.courses.filter((c) => c !== id) : [...(f.courses || []), id] }
  })

  const saveSettings = () => {
    const { id, created_at, updated_at, items: _i, course_name, items_count,
      bank_questions_count, computed_total_marks, total_attempts, ...payload } = form
    saveMut.mutate(payload)
  }

  if (isLoading || !form) {
    return <div className="flex justify-center py-24"><Loader2 className="w-6 h-6 animate-spin text-primary-500" /></div>
  }

  const totalQuestions = items.length + bankLinks.length

  return (
    <div className="max-w-5xl mx-auto px-4 py-8">
      <button onClick={() => navigate('/admin/mock-tests')}
        className="flex items-center gap-2 text-sm text-surface-500 hover:text-surface-800 dark:hover:text-surface-200 mb-4">
        <ArrowLeft className="w-4 h-4" /> All Mock Tests
      </button>

      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-6">
        <div>
          <input
            value={form.title}
            onChange={(e) => set('title')(e.target.value)}
            onBlur={saveSettings}
            className="text-2xl font-bold bg-transparent text-surface-900 dark:text-white focus:outline-none border-b-2 border-transparent focus:border-primary-400 w-full"
          />
          <p className="text-xs text-surface-400 mt-1">
            {totalQuestions} questions · {Number(form.computed_total_marks || 0)} marks · {form.duration_minutes} min
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => setShowAi(true)}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-gradient-to-r from-primary-600 to-purple-600 text-white font-medium text-sm shadow-sm hover:opacity-90">
            <Sparkles className="w-4 h-4" /> Modify with AI
          </button>
          <button onClick={() => navigate(`/admin/mock-tests/${testId}/submissions`)}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-xl border border-surface-200 dark:border-surface-700 hover:bg-surface-50 dark:hover:bg-surface-800 font-medium text-sm">
            <Inbox className="w-4 h-4" /> Submissions
          </button>
          <select value={form.status} onChange={(e) => { set('status')(e.target.value); saveMut.mutate({ status: e.target.value }) }}
            className={`${inputCls} w-auto`}>
            <option value="draft">Draft</option>
            <option value="published">Published</option>
            <option value="archived">Archived</option>
          </select>
          <button onClick={saveSettings} disabled={saveMut.isPending}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-primary-600 hover:bg-primary-700 text-white font-medium disabled:opacity-60">
            {saveMut.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />} Save
          </button>
        </div>
      </div>

      <MockAiJobBanners
        mockTestId={testId}
        className="mb-5"
        onOpen={() => setShowAi(true)}
      />

      <div className="flex gap-1 border-b border-surface-200 dark:border-surface-700 mb-6">
        {[['settings', 'Settings', Settings2], ['questions', `Questions (${totalQuestions})`, ListChecks]].map(([k, label, Icon]) => (
          <button key={k} onClick={() => setTab(k)}
            className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition ${
              tab === k ? 'border-primary-500 text-primary-600' : 'border-transparent text-surface-500 hover:text-surface-800'}`}>
            <Icon className="w-4 h-4" /> {label}
          </button>
        ))}
      </div>

      {tab === 'settings' && (
        <div className="grid md:grid-cols-2 gap-5">
          <Field label="Description">
            <textarea value={form.description || ''} onChange={(e) => set('description')(e.target.value)} rows={3} className={inputCls} />
          </Field>
          <div className="grid grid-cols-2 gap-4">
            <Field label="Duration (min)">
              <input type="number" min={1} value={form.duration_minutes || ''} onChange={(e) => set('duration_minutes')(Number(e.target.value))} className={inputCls} />
            </Field>
            <Field label="Start deadline" hint="optional">
              <input type="datetime-local" value={form.start_deadline ? form.start_deadline.slice(0, 16) : ''}
                onChange={(e) => set('start_deadline')(e.target.value ? new Date(e.target.value).toISOString() : null)} className={inputCls} />
            </Field>
          </div>

          <Field label="Attempts allowed" hint="1 = no re-attempts (default)">
            <input type="number" min={1} value={form.max_attempts || 1}
              onChange={(e) => set('max_attempts')(Math.max(1, Number(e.target.value) || 1))} className={inputCls} />
          </Field>

          <Field label="Result visibility">
            <select value={form.result_visibility} onChange={(e) => set('result_visibility')(e.target.value)} className={inputCls}>
              <option value="immediate">Show results on submission</option>
              <option value="on_release">Hide until I release them</option>
            </select>
          </Field>
          <div className="flex flex-col gap-3 justify-end">
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={form.fullscreen_required} onChange={(e) => set('fullscreen_required')(e.target.checked)} /> Require fullscreen during attempt
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={form.negative_marking} onChange={(e) => set('negative_marking')(e.target.checked)} /> Enable negative marking
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={form.results_released} onChange={(e) => set('results_released')(e.target.checked)} /> Results released (for hidden results)
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={form.is_free} onChange={(e) => set('is_free')(e.target.checked)} /> Free to attempt
            </label>
          </div>

          <div className="md:col-span-2">
            <Field label="Linked courses" hint="empty = open to all registered students">
              <div className="grid sm:grid-cols-2 gap-2 max-h-52 overflow-auto p-2 rounded-lg border border-surface-200 dark:border-surface-700">
                {courses.length === 0 && <span className="text-sm text-surface-400">No courses</span>}
                {courses.map((c) => (
                  <label key={c.id} className="flex items-center gap-2 text-sm p-1.5 rounded hover:bg-surface-50 dark:hover:bg-surface-700/50">
                    <input type="checkbox" checked={(form.courses || []).includes(c.id)} onChange={() => toggleCourse(c.id)} />
                    {c.name}
                  </label>
                ))}
              </div>
            </Field>
          </div>
          <div className="md:col-span-2">
            <button onClick={saveSettings} disabled={saveMut.isPending}
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-primary-600 hover:bg-primary-700 text-white font-medium disabled:opacity-60">
              {saveMut.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />} Save settings
            </button>
          </div>
        </div>
      )}

      {tab === 'questions' && (
        <QuestionsTab
          testId={testId} items={items} bankLinks={bankLinks}
          onEditItem={setEditingItem} onOpenBank={() => setShowBank(true)}
        />
      )}

      {editingItem && (
        <ItemEditor testId={testId} item={editingItem} onClose={() => setEditingItem(null)} />
      )}
      {showBank && (
        <BankImport testId={testId} onClose={() => setShowBank(false)} />
      )}

      {showAi && (
        <div className="fixed inset-0 z-50 flex justify-end bg-black/40" onClick={() => setShowAi(false)}>
          <div
            onClick={(e) => e.stopPropagation()}
            className="h-full w-full max-w-6xl overflow-y-auto bg-surface-50 p-5 dark:bg-surface-900"
          >
            <div className="mb-4 flex items-center justify-between">
              <div>
                <h2 className="flex items-center gap-2 text-lg font-semibold text-surface-900 dark:text-white">
                  <Sparkles className="h-5 w-5 text-primary-500" /> Modify with AI
                </h2>
                <p className="text-xs text-surface-500">
                  The AI reads this paper first — it works even if you wrote it by hand.
                </p>
              </div>
              <button onClick={() => setShowAi(false)}
                className="rounded-lg p-2 text-surface-400 hover:bg-surface-100 dark:hover:bg-surface-800">
                <X className="h-4 w-4" />
              </button>
            </div>
            <AIMockStudio
              mockTestId={testId}
              mockTestTitle={form.title}
              onApplied={() => {
                qc.invalidateQueries({ queryKey: ['admin-mock-test', testId] })
                qc.invalidateQueries({ queryKey: ['admin-mock-items', testId] })
                setShowAi(false)
              }}
            />
          </div>
        </div>
      )}
    </div>
  )
}

/* ----------------------------- Questions tab ----------------------------- */
function QuestionsTab({ testId, items, bankLinks, onEditItem, onOpenBank }) {
  const qc = useQueryClient()
  const [addType, setAddType] = useState('mcq')

  const createMut = useMutation({
    mutationFn: (item_type) => mockTestBuilderService.createItem({ mock_test: testId, item_type, marks: 1 }),
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: ['admin-mock-items', testId] })
      qc.invalidateQueries({ queryKey: ['admin-mock-test', testId] })
      onEditItem(created)
    },
    onError: () => toast.error('Could not add item'),
  })
  const delItem = useMutation({
    mutationFn: (id) => mockTestBuilderService.deleteItem(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-mock-items', testId] })
      qc.invalidateQueries({ queryKey: ['admin-mock-test', testId] })
    },
  })
  const delBank = useMutation({
    mutationFn: (qid) => mockTestBuilderService.removeBankQuestion(testId, qid),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-mock-bank', testId] })
      qc.invalidateQueries({ queryKey: ['admin-mock-test', testId] })
    },
  })

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 mb-5">
        <select value={addType} onChange={(e) => setAddType(e.target.value)} className={`${inputCls} w-auto`}>
          {ITEM_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
        </select>
        <button onClick={() => createMut.mutate(addType)} disabled={createMut.isPending}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-primary-600 hover:bg-primary-700 text-white text-sm font-medium disabled:opacity-60">
          <Plus className="w-4 h-4" /> Add inline question
        </button>
        <button onClick={onOpenBank}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-xl border border-surface-200 dark:border-surface-700 text-sm font-medium hover:bg-surface-50 dark:hover:bg-surface-800">
          <Library className="w-4 h-4" /> Import from question bank
        </button>
      </div>

      {items.length === 0 && bankLinks.length === 0 && (
        <div className="text-center py-16 border-2 border-dashed border-surface-200 dark:border-surface-700 rounded-2xl text-surface-500">
          No questions yet. Add an inline question or import from the bank.
        </div>
      )}

      <div className="space-y-2">
        {items.map((it, i) => {
          const m = typeMeta(it.item_type)
          const Icon = m.icon
          return (
            <div key={it.id} className="flex items-center gap-3 p-3 rounded-xl border border-surface-200 dark:border-surface-700 bg-white dark:bg-surface-800">
              <GripVertical className="w-4 h-4 text-surface-300" />
              <span className="text-xs font-mono text-surface-400 w-6">{i + 1}</span>
              <Icon className={`w-4 h-4 ${m.color}`} />
              <div className="flex-1 min-w-0">
                <p className="text-sm text-surface-800 dark:text-surface-200 truncate">
                  {it.question_text || <span className="italic text-surface-400">Untitled {m.label}</span>}
                </p>
                <p className="text-xs text-surface-400">{m.label} · {Number(it.marks)} marks</p>
              </div>
              <button onClick={() => onEditItem(it)} className="px-3 py-1.5 rounded-lg text-sm text-primary-600 hover:bg-primary-50 dark:hover:bg-primary-900/20">Edit</button>
              <button onClick={() => { if (confirm('Delete this question?')) delItem.mutate(it.id) }} className="p-1.5 rounded-lg text-surface-400 hover:text-rose-600"><Trash2 className="w-4 h-4" /></button>
            </div>
          )
        })}
        {bankLinks.map((b) => (
          <div key={b.id} className="flex items-center gap-3 p-3 rounded-xl border border-indigo-200 dark:border-indigo-800 bg-indigo-50/50 dark:bg-indigo-900/10">
            <Library className="w-4 h-4 text-indigo-500" />
            <div className="flex-1 min-w-0">
              <p className="text-sm text-surface-800 dark:text-surface-200 truncate">{b.question_detail?.question_text || 'Bank question'}</p>
              <p className="text-xs text-surface-400">Bank · {b.question_detail?.question_type} · {Number(b.effective_marks)} marks</p>
            </div>
            <button onClick={() => { if (confirm('Remove this bank question?')) delBank.mutate(b.question) }} className="p-1.5 rounded-lg text-surface-400 hover:text-rose-600"><Trash2 className="w-4 h-4" /></button>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ------------------------------ Item editor ------------------------------ */
function ItemEditor({ testId, item, onClose }) {
  const qc = useQueryClient()
  const [f, setF] = useState(() => ({
    ...item,
    options: item.options?.length ? item.options : (['mcq', 'mcq_multi'].includes(item.item_type) ? [{ text: '', is_correct: false }, { text: '', is_correct: false }] : []),
    allowed_languages: item.allowed_languages || [],
    starter_code: item.starter_code || {},
    coding_test_cases: item.coding_test_cases || [],
  }))
  const { data: meta } = useQuery({ queryKey: ['coding-meta'], queryFn: () => mockTestBuilderService.getLanguages(), enabled: f.item_type === 'coding' })
  const set = (k) => (v) => setF((s) => ({ ...s, [k]: v }))

  const saveMut = useMutation({
    mutationFn: () => {
      const payload = {
        item_type: f.item_type, question_text: f.question_text || '', question_html: '',
        explanation: f.explanation || '', marks: f.marks, negative_marks: f.negative_marks || 0, section: f.section || 0,
      }
      if (['mcq', 'mcq_multi'].includes(f.item_type)) payload.options = f.options
      if (f.item_type === 'numerical') { payload.numerical_answer = f.numerical_answer; payload.numerical_tolerance = f.numerical_tolerance || 0.01 }
      if (f.item_type === 'subjective') { payload.max_words = f.max_words || null; payload.rubric = f.rubric || ''; payload.model_answer = f.model_answer || '' }
      if (f.item_type === 'coding') {
        payload.allowed_languages = f.allowed_languages; payload.starter_code = f.starter_code
        payload.time_limit_ms = f.time_limit_ms || 3000; payload.memory_limit_mb = f.memory_limit_mb || 256
        payload.coding_test_cases = f.coding_test_cases
      }
      return mockTestBuilderService.updateItem(item.id, payload)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-mock-items', testId] })
      qc.invalidateQueries({ queryKey: ['admin-mock-test', testId] })
      toast.success('Question saved'); onClose()
    },
    onError: (e) => toast.error(e?.response?.data ? JSON.stringify(e.response.data) : 'Save failed'),
  })

  const setOpt = (i, patch) => setF((s) => ({ ...s, options: s.options.map((o, idx) => idx === i ? { ...o, ...patch } : (patch.is_correct && f.item_type === 'mcq' ? { ...o, is_correct: false } : o)) }))
  const langs = meta?.languages || []
  const m = typeMeta(f.item_type)

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-start justify-center overflow-auto p-4">
      <div className="bg-white dark:bg-surface-900 rounded-2xl w-full max-w-2xl my-6 shadow-2xl">
        <div className="flex items-center justify-between p-4 border-b border-surface-200 dark:border-surface-700">
          <h3 className="font-semibold flex items-center gap-2"><m.icon className={`w-5 h-5 ${m.color}`} /> Edit {m.label}</h3>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-surface-100 dark:hover:bg-surface-800"><X className="w-5 h-5" /></button>
        </div>
        <div className="p-5 space-y-4 max-h-[70vh] overflow-auto">
          <Field label="Question"><RichMarkdownEditor value={f.question_text} onChange={set('question_text')} rows={4} /></Field>
          <div className="grid grid-cols-3 gap-3">
            <Field label="Marks"><input type="number" step="0.5" value={f.marks} onChange={(e) => set('marks')(Number(e.target.value))} className={inputCls} /></Field>
            <Field label="Negative"><input type="number" step="0.5" value={f.negative_marks || 0} onChange={(e) => set('negative_marks')(Number(e.target.value))} className={inputCls} /></Field>
            <Field label="Section"><input type="number" value={f.section || 0} onChange={(e) => set('section')(Number(e.target.value))} className={inputCls} /></Field>
          </div>

          {['mcq', 'mcq_multi'].includes(f.item_type) && (
            <div>
              <p className="text-sm font-medium mb-2">Options <span className="text-xs text-surface-400">(check the correct one{f.item_type === 'mcq_multi' ? 's' : ''})</span></p>
              <div className="space-y-2">
                {f.options.map((o, i) => (
                  <div key={i} className="flex items-start gap-2">
                    <input type={f.item_type === 'mcq' ? 'radio' : 'checkbox'} checked={!!o.is_correct} name="correct" onChange={(e) => setOpt(i, { is_correct: e.target.checked })} className="mt-3.5" />
                    <div className="flex-1">
                      <RichMarkdownEditor value={o.text} onChange={(v) => setF((s) => ({ ...s, options: s.options.map((x, idx) => idx === i ? { ...x, text: v } : x) }))} rows={2} />
                    </div>
                    <button onClick={() => setF((s) => ({ ...s, options: s.options.filter((_, idx) => idx !== i) }))} className="mt-3 p-1.5 text-surface-400 hover:text-rose-600"><Trash2 className="w-4 h-4" /></button>
                  </div>
                ))}
              </div>
              <button onClick={() => setF((s) => ({ ...s, options: [...s.options, { text: '', is_correct: false }] }))} className="mt-2 text-sm text-primary-600 flex items-center gap-1"><Plus className="w-4 h-4" /> Add option</button>
            </div>
          )}

          {f.item_type === 'numerical' && (
            <div className="grid grid-cols-2 gap-3">
              <Field label="Correct answer"><input type="number" step="any" value={f.numerical_answer ?? ''} onChange={(e) => set('numerical_answer')(e.target.value === '' ? null : Number(e.target.value))} className={inputCls} /></Field>
              <Field label="Tolerance (±)"><input type="number" step="any" value={f.numerical_tolerance ?? 0.01} onChange={(e) => set('numerical_tolerance')(Number(e.target.value))} className={inputCls} /></Field>
            </div>
          )}

          {f.item_type === 'subjective' && (
            <>
              <Field label="Max words" hint="optional"><input type="number" value={f.max_words ?? ''} onChange={(e) => set('max_words')(e.target.value === '' ? null : Number(e.target.value))} className={inputCls} /></Field>
              <Field label="Grading rubric" hint="admins only"><RichMarkdownEditor value={f.rubric} onChange={set('rubric')} rows={2} /></Field>
              <Field label="Model answer" hint="admins only"><RichMarkdownEditor value={f.model_answer} onChange={set('model_answer')} rows={2} /></Field>
            </>
          )}

          {f.item_type === 'coding' && (
            <div className="space-y-3">
              <Field label="Allowed languages">
                <div className="flex flex-wrap gap-3">
                  {langs.map((l) => (
                    <label key={l.key} className="flex items-center gap-1.5 text-sm">
                      <input type="checkbox" checked={f.allowed_languages.includes(l.key)}
                        onChange={(e) => set('allowed_languages')(e.target.checked ? [...f.allowed_languages, l.key] : f.allowed_languages.filter((x) => x !== l.key))} />
                      {l.label}
                    </label>
                  ))}
                </div>
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Time limit (ms)"><input type="number" value={f.time_limit_ms || 3000} onChange={(e) => set('time_limit_ms')(Number(e.target.value))} className={inputCls} /></Field>
                <Field label="Memory (MB)"><input type="number" value={f.memory_limit_mb || 256} onChange={(e) => set('memory_limit_mb')(Number(e.target.value))} className={inputCls} /></Field>
              </div>
              <div>
                <p className="text-sm font-medium mb-2">Test cases <span className="text-xs text-surface-400">(mark some as sample to show students)</span></p>
                <div className="space-y-2">
                  {f.coding_test_cases.map((c, i) => (
                    <div key={i} className="p-3 rounded-lg border border-surface-200 dark:border-surface-700 space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-medium">Case {i + 1}</span>
                        <div className="flex items-center gap-3">
                          <label className="text-xs flex items-center gap-1"><input type="checkbox" checked={!!c.is_sample} onChange={(e) => setF((s) => ({ ...s, coding_test_cases: s.coding_test_cases.map((x, idx) => idx === i ? { ...x, is_sample: e.target.checked } : x) }))} /> sample</label>
                          <input type="number" value={c.points ?? 1} onChange={(e) => setF((s) => ({ ...s, coding_test_cases: s.coding_test_cases.map((x, idx) => idx === i ? { ...x, points: Number(e.target.value) } : x) }))} className="w-16 px-2 py-1 text-xs rounded border border-surface-200 dark:border-surface-700 bg-transparent" title="points" />
                          <button onClick={() => setF((s) => ({ ...s, coding_test_cases: s.coding_test_cases.filter((_, idx) => idx !== i) }))} className="text-surface-400 hover:text-rose-600"><Trash2 className="w-4 h-4" /></button>
                        </div>
                      </div>
                      <textarea value={c.stdin || ''} onChange={(e) => setF((s) => ({ ...s, coding_test_cases: s.coding_test_cases.map((x, idx) => idx === i ? { ...x, stdin: e.target.value } : x) }))} placeholder="stdin" rows={2} className={`${inputCls} font-mono text-xs`} />
                      <textarea value={c.expected_output || ''} onChange={(e) => setF((s) => ({ ...s, coding_test_cases: s.coding_test_cases.map((x, idx) => idx === i ? { ...x, expected_output: e.target.value } : x) }))} placeholder="expected output" rows={2} className={`${inputCls} font-mono text-xs`} />
                    </div>
                  ))}
                </div>
                <button onClick={() => setF((s) => ({ ...s, coding_test_cases: [...s.coding_test_cases, { stdin: '', expected_output: '', points: 1, is_sample: false }] }))} className="mt-2 text-sm text-primary-600 flex items-center gap-1"><Plus className="w-4 h-4" /> Add test case</button>
              </div>
            </div>
          )}

          <Field label="Explanation" hint="shown after submission"><RichMarkdownEditor value={f.explanation} onChange={set('explanation')} rows={2} /></Field>
        </div>
        <div className="flex justify-end gap-2 p-4 border-t border-surface-200 dark:border-surface-700">
          <button onClick={onClose} className="px-4 py-2 rounded-xl border border-surface-200 dark:border-surface-700 text-sm">Cancel</button>
          <button onClick={() => saveMut.mutate()} disabled={saveMut.isPending}
            className="inline-flex items-center gap-2 px-5 py-2 rounded-xl bg-primary-600 hover:bg-primary-700 text-white text-sm font-medium disabled:opacity-60">
            {saveMut.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />} Save question
          </button>
        </div>
      </div>
    </div>
  )
}

/* ------------------------------ Bank import ------------------------------ */
function BankImport({ testId, onClose }) {
  const qc = useQueryClient()
  const [q, setQ] = useState('')
  const [selected, setSelected] = useState([])
  const { data: results = [], isFetching } = useQuery({
    queryKey: ['bank-search', q],
    queryFn: () => mockTestBuilderService.searchBankQuestions(q ? { search: q } : {}),
  })
  const addMut = useMutation({
    mutationFn: () => mockTestBuilderService.addBankQuestions(testId, { question_ids: selected }),
    onSuccess: (r) => {
      toast.success(`${r.added} question(s) added`)
      qc.invalidateQueries({ queryKey: ['admin-mock-bank', testId] })
      qc.invalidateQueries({ queryKey: ['admin-mock-test', testId] })
      onClose()
    },
    onError: () => toast.error('Import failed'),
  })
  const toggle = (id) => setSelected((s) => s.includes(id) ? s.filter((x) => x !== id) : [...s, id])

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-start justify-center overflow-auto p-4">
      <div className="bg-white dark:bg-surface-900 rounded-2xl w-full max-w-2xl my-6 shadow-2xl">
        <div className="flex items-center justify-between p-4 border-b border-surface-200 dark:border-surface-700">
          <h3 className="font-semibold flex items-center gap-2"><Library className="w-5 h-5 text-indigo-500" /> Import from question bank</h3>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-surface-100 dark:hover:bg-surface-800"><X className="w-5 h-5" /></button>
        </div>
        <div className="p-4">
          <div className="relative mb-3">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-surface-400" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search questions…" className={`${inputCls} pl-9`} />
          </div>
          <div className="max-h-[50vh] overflow-auto space-y-2">
            {isFetching && <div className="flex justify-center py-6"><Loader2 className="w-5 h-5 animate-spin text-primary-500" /></div>}
            {results.map((r) => (
              <label key={r.id} className="flex items-start gap-3 p-3 rounded-lg border border-surface-200 dark:border-surface-700 cursor-pointer hover:bg-surface-50 dark:hover:bg-surface-800">
                <input type="checkbox" checked={selected.includes(r.id)} onChange={() => toggle(r.id)} className="mt-1" />
                <div className="min-w-0">
                  <p className="text-sm text-surface-800 dark:text-surface-200 line-clamp-2">{r.question_text}</p>
                  <p className="text-xs text-surface-400 mt-0.5">{r.question_type} · {Number(r.marks)} marks</p>
                </div>
              </label>
            ))}
            {!isFetching && results.length === 0 && <p className="text-center text-sm text-surface-400 py-6">No questions found.</p>}
          </div>
        </div>
        <div className="flex justify-between items-center gap-2 p-4 border-t border-surface-200 dark:border-surface-700">
          <span className="text-sm text-surface-500">{selected.length} selected</span>
          <div className="flex gap-2">
            <button onClick={onClose} className="px-4 py-2 rounded-xl border border-surface-200 dark:border-surface-700 text-sm">Cancel</button>
            <button onClick={() => addMut.mutate()} disabled={!selected.length || addMut.isPending}
              className="inline-flex items-center gap-2 px-5 py-2 rounded-xl bg-primary-600 hover:bg-primary-700 text-white text-sm font-medium disabled:opacity-60">
              {addMut.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />} Import selected
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
