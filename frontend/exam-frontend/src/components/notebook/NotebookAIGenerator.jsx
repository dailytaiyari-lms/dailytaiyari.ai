import { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import {
  Sparkles, Loader2, X, RefreshCw, Wand2, Check, Trash2, AlertTriangle,
} from 'lucide-react'
import { notebookGenService as gen } from '../../services/notebookService'
import useGenerationJob from '../../hooks/useGenerationJob'
import NotebookDraftPreview from './NotebookDraftPreview'
import NotebookGenFields, { defaultNotebookGenForm } from './NotebookGenFields'

/**
 * AI notebook generator.
 *
 * Generation runs in the background on the server; this modal polls the job
 * until it settles, then lets the admin modify with AI, regenerate or apply.
 * Applying is the only call that creates a real notebook.
 */
const NotebookAIGenerator = ({ open, onClose, courseId, topicId, subjectId, onApplied }) => {
  const [options, setOptions] = useState(null)
  const [form, setForm] = useState(defaultNotebookGenForm)
  const [refineText, setRefineText] = useState('')
  const [applying, setApplying] = useState(false)

  const { job, error, busy, run, reset, setError } = useGenerationJob(gen.getJob)

  useEffect(() => {
    if (!open) return
    gen.options().then(setOptions).catch(() => setOptions({ ai_enabled: true, providers: [] }))
  }, [open])

  const handleGenerate = () => {
    if (form.prompt.trim().length < 3) return setError('Describe the notebook you want.')
    return run(() => gen.generate({
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
    }))
  }

  const handleRefine = () => {
    if (refineText.trim().length < 3) return setError('Tell the AI what to change.')
    const instruction = refineText.trim()
    setRefineText('')
    return run(() => gen.refine(job.id, instruction))
  }

  const handleApply = async () => {
    setApplying(true)
    try {
      const { summary } = await gen.apply(job.id)
      toast.success('Notebook created from the AI draft.')
      reset()
      onApplied?.(summary.notebook_id)
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not create the notebook.')
    } finally {
      setApplying(false)
    }
  }

  const handleClose = () => {
    // Best-effort discard so an un-applied preview doesn't linger as clutter.
    if (job?.status === 'preview') gen.discard(job.id).catch(() => {})
    reset()
    setRefineText('')
    onClose?.()
  }

  if (!open) return null

  let phase = 'compose'
  if (busy) phase = 'running'
  else if (job?.status === 'preview') phase = 'preview'
  else if (job?.status === 'failed') phase = 'failed'

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/50 p-4">
      <div className="my-6 w-full max-w-3xl rounded-2xl bg-white shadow-2xl dark:bg-surface-900">
        <div className="flex items-center gap-2 border-b border-surface-200 px-5 py-3 dark:border-surface-700">
          <Sparkles className="h-5 w-5 text-primary-600" />
          <h2 className="text-base font-semibold">Generate notebook with AI</h2>
          <button onClick={handleClose} className="ml-auto text-surface-400 hover:text-surface-700">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="max-h-[75vh] space-y-4 overflow-y-auto px-5 py-4">
          {options && options.ai_enabled === false && (
            <div className="flex items-center gap-2 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-700 dark:bg-amber-900/30 dark:text-amber-300">
              <AlertTriangle className="h-4 w-4" />
              AI features are turned off. Enable them under Admin → AI Features first.
            </div>
          )}

          {phase === 'compose' && (
            <>
              <NotebookGenFields form={form} setForm={setForm} providers={options?.providers} />
              <div className="flex justify-end">
                <button onClick={handleGenerate} className="btn-primary px-4 py-2 text-sm">
                  <Sparkles className="h-4 w-4" /> Generate
                </button>
              </div>
            </>
          )}

          {phase === 'running' && (
            <div className="flex flex-col items-center justify-center gap-3 py-12 text-center">
              <Loader2 className="h-8 w-8 animate-spin text-primary-600" />
              <p className="text-sm font-medium">
                {job?.status === 'generating'
                  ? 'The AI is writing your notebook…'
                  : 'Queued — starting shortly…'}
              </p>
              <p className="text-xs text-surface-500">
                A full graded notebook can take a couple of minutes. It keeps running on the server,
                even if this looks quiet.
              </p>
            </div>
          )}

          {phase === 'failed' && (
            <div className="space-y-3">
              <div className="flex items-start gap-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{job?.error || error || 'Generation failed.'}</span>
              </div>
              <div className="flex justify-end gap-2">
                <button onClick={reset} className="btn-secondary px-3 py-1.5 text-sm">
                  Edit prompt
                </button>
                <button
                  onClick={() => run(() => gen.regenerate(job.id))}
                  className="btn-primary px-3 py-1.5 text-sm"
                >
                  <RefreshCw className="h-4 w-4" /> Regenerate
                </button>
              </div>
            </div>
          )}

          {phase === 'preview' && (
            <div className="space-y-4">
              <NotebookDraftPreview draft={job.draft || {}} />

              {job.error && (
                <div className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700 dark:bg-amber-900/30 dark:text-amber-300">
                  The last change couldn’t be applied: {job.error}
                </div>
              )}

              <div>
                <label className="mb-1 block text-xs font-medium text-surface-500">Modify with AI</label>
                <div className="flex gap-2">
                  <input
                    value={refineText}
                    onChange={(e) => setRefineText(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleRefine()}
                    placeholder="e.g. Add a harder hidden test, or switch the dataset to the iris data."
                    className="flex-1 rounded-lg border border-surface-300 bg-transparent px-3 py-2 text-sm dark:border-surface-600"
                  />
                  <button onClick={handleRefine} className="btn-secondary whitespace-nowrap px-3 py-2 text-sm">
                    <Wand2 className="h-4 w-4" /> Modify
                  </button>
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-2 border-t border-surface-200 pt-3 dark:border-surface-700">
                <button
                  onClick={() => run(() => gen.regenerate(job.id))}
                  className="btn-secondary px-3 py-1.5 text-sm"
                >
                  <RefreshCw className="h-4 w-4" /> Regenerate
                </button>
                <button
                  onClick={() => { gen.discard(job.id).catch(() => {}); reset() }}
                  className="btn-secondary px-3 py-1.5 text-sm"
                >
                  <Trash2 className="h-4 w-4" /> Discard
                </button>
                <button
                  onClick={handleApply}
                  disabled={applying}
                  className="btn-primary ml-auto px-4 py-1.5 text-sm"
                >
                  {applying ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                  Create notebook
                </button>
              </div>
            </div>
          )}

          {error && phase !== 'failed' && (
            <p className="rounded-lg bg-rose-50 p-3 text-sm text-rose-600 dark:bg-rose-900/20 dark:text-rose-300">
              {error}
            </p>
          )}
        </div>
      </div>
    </div>
  )
}

export default NotebookAIGenerator
