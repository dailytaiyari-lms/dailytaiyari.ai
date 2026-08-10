import { useCallback, useEffect, useRef, useState } from 'react'
import toast from 'react-hot-toast'
import {
  Sparkles, Loader2, X, RefreshCw, Wand2, Check, Trash2, AlertTriangle,
  FlaskConical, FileCode2, BookOpen,
} from 'lucide-react'
import { notebookGenService as gen } from '../../services/notebookService'

const RUNNING = new Set(['pending', 'generating'])
const POLL_MS = 2500

const ROLE_BADGE = {
  readonly: 'bg-surface-100 text-surface-600 dark:bg-surface-700 dark:text-surface-300',
  editable: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
  answer: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
}

/**
 * Self-contained AI notebook generator. Generation runs in the background on the
 * server; this modal polls the job until it settles, then lets the admin modify
 * with AI, regenerate, or apply (which creates the real notebook).
 */
const NotebookAIGenerator = ({ open, onClose, courseId, topicId, subjectId, onApplied }) => {
  const [options, setOptions] = useState(null)
  const [form, setForm] = useState({
    prompt: '',
    difficulty: 'easy',
    graded: true,
    answer_cells: 2,
    provider: '',
    model: '',
  })
  const [job, setJob] = useState(null)
  const [phase, setPhase] = useState('compose') // compose | running | preview | failed
  const [busy, setBusy] = useState(false)
  const [refineText, setRefineText] = useState('')
  const pollRef = useRef(null)

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [])

  useEffect(() => () => stopPolling(), [stopPolling])

  useEffect(() => {
    if (!open) return
    gen.options().then(setOptions).catch(() => setOptions({ is_ready: true, providers: [] }))
  }, [open])

  const settle = useCallback((next) => {
    stopPolling()
    setJob(next)
    if (next.status === 'preview') {
      setPhase('preview')
    } else if (next.status === 'failed') {
      setPhase('failed')
    } else if (next.status === 'applied') {
      setPhase('preview')
    }
  }, [stopPolling])

  const poll = useCallback((jobId) => {
    stopPolling()
    pollRef.current = setInterval(async () => {
      try {
        const fresh = await gen.getJob(jobId)
        setJob(fresh)
        if (!RUNNING.has(fresh.status)) settle(fresh)
      } catch {
        /* keep polling; transient error */
      }
    }, POLL_MS)
  }, [settle, stopPolling])

  const track = useCallback((res) => {
    setJob(res)
    if (RUNNING.has(res.status)) {
      setPhase('running')
      poll(res.id)
    } else {
      settle(res)
    }
  }, [poll, settle])

  const handleGenerate = async () => {
    if (form.prompt.trim().length < 3) return toast.error('Describe the notebook you want.')
    setBusy(true)
    try {
      const res = await gen.generate({
        prompt: form.prompt.trim(),
        course: courseId,
        topic: topicId,
        ...(subjectId ? { subject: subjectId } : {}),
        provider: form.provider || '',
        model: form.model || '',
        options: {
          difficulty: form.difficulty,
          graded: form.graded,
          answer_cells: Number(form.answer_cells) || 0,
        },
      })
      track(res)
    } catch (err) {
      toast.error(err.response?.data?.detail || err.response?.data?.prompt || 'Could not start generation.')
    } finally {
      setBusy(false)
    }
  }

  const handleRefine = async () => {
    if (refineText.trim().length < 3) return toast.error('Tell the AI what to change.')
    setBusy(true)
    setPhase('running')
    try {
      const res = await gen.refine(job.id, refineText.trim())
      setRefineText('')
      track(res)
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Could not modify the draft.')
      setPhase('preview')
    } finally {
      setBusy(false)
    }
  }

  const handleRegenerate = async () => {
    setBusy(true)
    setPhase('running')
    try {
      track(await gen.regenerate(job.id))
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Could not regenerate.')
      setPhase('failed')
    } finally {
      setBusy(false)
    }
  }

  const handleApply = async () => {
    setBusy(true)
    try {
      const { summary } = await gen.apply(job.id)
      toast.success('Notebook created from AI draft.')
      onApplied?.(summary.notebook_id)
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Could not create the notebook.')
    } finally {
      setBusy(false)
    }
  }

  const handleClose = async () => {
    stopPolling()
    // Best-effort discard of an un-applied preview so it doesn't linger.
    if (job && job.status === 'preview') {
      gen.discard(job.id).catch(() => {})
    }
    setJob(null)
    setPhase('compose')
    setRefineText('')
    onClose?.()
  }

  if (!open) return null

  const draft = job?.draft || {}
  const summary = job?.summary || {}
  const cells = draft.cells || []
  const tests = draft.tests || []

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/50 p-4">
      <div className="my-6 w-full max-w-3xl rounded-2xl bg-white dark:bg-surface-900 shadow-2xl">
        <div className="flex items-center gap-2 border-b border-surface-200 dark:border-surface-700 px-5 py-3">
          <Sparkles className="w-5 h-5 text-primary-600" />
          <h2 className="text-base font-semibold">Generate notebook with AI</h2>
          <button onClick={handleClose} className="ml-auto text-surface-400 hover:text-surface-700">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="max-h-[75vh] overflow-y-auto px-5 py-4 space-y-4">
          {options && options.ai_enabled === false && (
            <div className="flex items-center gap-2 rounded-lg bg-amber-50 dark:bg-amber-900/30 px-3 py-2 text-sm text-amber-700 dark:text-amber-300">
              <AlertTriangle className="w-4 h-4" />
              AI features are turned off. Enable them under Admin → AI Features first.
            </div>
          )}

          {/* Composer */}
          {phase === 'compose' && (
            <>
              <div>
                <label className="block text-xs font-medium text-surface-500 mb-1">
                  What should this notebook teach or ask?
                </label>
                <textarea
                  rows={4}
                  value={form.prompt}
                  onChange={(e) => setForm((f) => ({ ...f, prompt: e.target.value }))}
                  placeholder="e.g. A hands-on notebook on training and evaluating a linear regression model with scikit-learn, with graded tasks."
                  className="w-full rounded-lg border border-surface-300 dark:border-surface-600 bg-transparent px-3 py-2 text-sm"
                />
              </div>

              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <div>
                  <label className="block text-xs font-medium text-surface-500 mb-1">Difficulty</label>
                  <select
                    value={form.difficulty}
                    onChange={(e) => setForm((f) => ({ ...f, difficulty: e.target.value }))}
                    className="w-full rounded-lg border border-surface-300 dark:border-surface-600 bg-transparent px-2 py-1.5 text-sm"
                  >
                    <option value="easy">Easy</option>
                    <option value="medium">Medium</option>
                    <option value="hard">Hard</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-surface-500 mb-1">Graded</label>
                  <select
                    value={form.graded ? 'yes' : 'no'}
                    onChange={(e) => setForm((f) => ({ ...f, graded: e.target.value === 'yes' }))}
                    className="w-full rounded-lg border border-surface-300 dark:border-surface-600 bg-transparent px-2 py-1.5 text-sm"
                  >
                    <option value="yes">Yes (answer cells + tests)</option>
                    <option value="no">No (exploratory)</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-surface-500 mb-1">Answer cells</label>
                  <input
                    type="number"
                    min={0}
                    max={10}
                    disabled={!form.graded}
                    value={form.answer_cells}
                    onChange={(e) => setForm((f) => ({ ...f, answer_cells: e.target.value }))}
                    className="w-full rounded-lg border border-surface-300 dark:border-surface-600 bg-transparent px-2 py-1.5 text-sm disabled:opacity-50"
                  />
                </div>
                {options?.providers?.length > 0 && (
                  <div>
                    <label className="block text-xs font-medium text-surface-500 mb-1">Model</label>
                    <select
                      value={form.provider ? `${form.provider}::${form.model}` : ''}
                      onChange={(e) => {
                        const [provider, model] = e.target.value.split('::')
                        setForm((f) => ({ ...f, provider: provider || '', model: model || '' }))
                      }}
                      className="w-full rounded-lg border border-surface-300 dark:border-surface-600 bg-transparent px-2 py-1.5 text-sm"
                    >
                      <option value="">Default</option>
                      {options.providers.flatMap((p) =>
                        (p.models || []).map((m) => (
                          <option key={`${p.provider}::${m}`} value={`${p.provider}::${m}`}>
                            {p.provider_label}: {m}
                          </option>
                        )),
                      )}
                    </select>
                  </div>
                )}
              </div>

              <div className="flex justify-end">
                <button
                  onClick={handleGenerate}
                  disabled={busy}
                  className="btn-primary text-sm px-4 py-2"
                >
                  {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
                  Generate
                </button>
              </div>
            </>
          )}

          {/* Running (background + polling) */}
          {phase === 'running' && (
            <div className="flex flex-col items-center justify-center gap-3 py-12 text-center">
              <Loader2 className="w-8 h-8 animate-spin text-primary-600" />
              <p className="text-sm font-medium">
                {job?.status === 'generating' ? 'The AI is writing your notebook…' : 'Queued — starting shortly…'}
              </p>
              <p className="text-xs text-surface-500">
                This can take up to a minute for a full graded notebook. You can keep this open.
              </p>
            </div>
          )}

          {/* Failed */}
          {phase === 'failed' && (
            <div className="space-y-3">
              <div className="flex items-start gap-2 rounded-lg bg-red-50 dark:bg-red-900/30 px-3 py-2 text-sm text-red-700 dark:text-red-300">
                <AlertTriangle className="w-4 h-4 mt-0.5" />
                <span>{job?.error || 'Generation failed.'}</span>
              </div>
              <div className="flex justify-end gap-2">
                <button onClick={() => setPhase('compose')} className="btn-secondary text-sm px-3 py-1.5">
                  Edit prompt
                </button>
                <button onClick={handleRegenerate} disabled={busy} className="btn-primary text-sm px-3 py-1.5">
                  {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
                  Regenerate
                </button>
              </div>
            </div>
          )}

          {/* Preview */}
          {phase === 'preview' && (
            <div className="space-y-4">
              <div>
                <h3 className="text-lg font-semibold">{draft.title || summary.title || 'Untitled notebook'}</h3>
                {draft.description && (
                  <p
                    className="text-sm text-surface-600 dark:text-surface-300 mt-1"
                    dangerouslySetInnerHTML={{ __html: draft.description }}
                  />
                )}
                <div className="mt-2 flex flex-wrap gap-2 text-xs">
                  <span className="rounded-full bg-surface-100 dark:bg-surface-800 px-2 py-0.5 capitalize">
                    {draft.difficulty || 'easy'}
                  </span>
                  <span className="inline-flex items-center gap-1 rounded-full bg-surface-100 dark:bg-surface-800 px-2 py-0.5">
                    <FileCode2 className="w-3 h-3" /> {cells.length} cells
                  </span>
                  <span className="inline-flex items-center gap-1 rounded-full bg-surface-100 dark:bg-surface-800 px-2 py-0.5">
                    <BookOpen className="w-3 h-3" /> {cells.filter((c) => c.role === 'answer').length} answer
                  </span>
                  <span className="inline-flex items-center gap-1 rounded-full bg-surface-100 dark:bg-surface-800 px-2 py-0.5">
                    <FlaskConical className="w-3 h-3" /> {tests.length} tests · {tests.reduce((s, t) => s + (Number(t.points) || 0), 0)} pts
                  </span>
                </div>
              </div>

              {/* Cells preview */}
              <div className="space-y-2 max-h-64 overflow-y-auto rounded-lg border border-surface-200 dark:border-surface-700 p-2">
                {cells.map((cell, i) => (
                  <div key={i} className="rounded-md bg-surface-50 dark:bg-surface-800/60 p-2">
                    <div className="mb-1 flex items-center gap-2 text-[10px]">
                      <span className={`rounded px-1.5 py-0.5 font-medium ${ROLE_BADGE[cell.role] || ROLE_BADGE.readonly}`}>
                        {cell.role}
                      </span>
                      <span className="text-surface-400 uppercase">{cell.cell_type}</span>
                      {cell.grade_id && <span className="text-amber-600">#{cell.grade_id}</span>}
                    </div>
                    <pre className="whitespace-pre-wrap break-words text-[11px] leading-snug text-surface-700 dark:text-surface-200 line-clamp-6">
                      {(cell.source || '').slice(0, 500)}
                    </pre>
                  </div>
                ))}
              </div>

              {/* Tests preview */}
              {tests.length > 0 && (
                <div className="space-y-1">
                  <p className="text-xs font-medium text-surface-500">Autograder tests</p>
                  {tests.map((t, i) => (
                    <div key={i} className="flex items-center gap-2 rounded-md bg-surface-50 dark:bg-surface-800/60 px-2 py-1 text-xs">
                      <FlaskConical className="w-3 h-3 text-surface-400" />
                      <span className="font-medium">{t.name}</span>
                      {t.grade_id && <span className="text-amber-600">#{t.grade_id}</span>}
                      <span className="ml-auto text-surface-500">{t.points} pt</span>
                      <span className={`rounded px-1.5 py-0.5 ${t.is_hidden ? 'bg-surface-200 dark:bg-surface-700' : 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300'}`}>
                        {t.is_hidden ? 'hidden' : 'visible'}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              {job?.error && (
                <div className="rounded-lg bg-amber-50 dark:bg-amber-900/30 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
                  Last change couldn’t be applied: {job.error}
                </div>
              )}

              {/* Modify with AI */}
              <div>
                <label className="block text-xs font-medium text-surface-500 mb-1">Modify with AI</label>
                <div className="flex gap-2">
                  <input
                    value={refineText}
                    onChange={(e) => setRefineText(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && !busy && handleRefine()}
                    placeholder="e.g. Add a harder hidden test, or switch the dataset to the iris data."
                    className="flex-1 rounded-lg border border-surface-300 dark:border-surface-600 bg-transparent px-3 py-2 text-sm"
                  />
                  <button onClick={handleRefine} disabled={busy} className="btn-secondary text-sm px-3 py-2 whitespace-nowrap">
                    <Wand2 className="w-4 h-4" /> Modify
                  </button>
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-2 border-t border-surface-200 dark:border-surface-700 pt-3">
                <button onClick={handleRegenerate} disabled={busy} className="btn-secondary text-sm px-3 py-1.5">
                  <RefreshCw className="w-4 h-4" /> Regenerate
                </button>
                <button
                  onClick={() => { gen.discard(job.id).catch(() => {}); setJob(null); setPhase('compose') }}
                  disabled={busy}
                  className="btn-secondary text-sm px-3 py-1.5"
                >
                  <Trash2 className="w-4 h-4" /> Discard
                </button>
                <button onClick={handleApply} disabled={busy} className="btn-primary text-sm px-4 py-1.5 ml-auto">
                  {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
                  Create notebook
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default NotebookAIGenerator
