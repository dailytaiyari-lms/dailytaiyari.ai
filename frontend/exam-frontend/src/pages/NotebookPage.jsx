import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import toast from 'react-hot-toast'
import {
  ArrowLeft, Send, Loader2, CheckCircle2, XCircle, Clock, AlertTriangle,
  RotateCcw, Save, Lock, FlaskConical, Notebook as NotebookIcon,
} from 'lucide-react'
import notebookService from '../services/notebookService'
import NotebookEditor from '../components/notebook/NotebookEditor'
import LabStatusCard from '../components/notebook/LabStatusCard'
import SubmitFlowModal from '../components/notebook/LabSubmitFlow'
import Loading from '../components/common/Loading'
import { forApi } from '../components/notebook/notebookDoc'

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

// Poll a queued submission until the authoritative server grade lands.
// Transient failures are tolerated — grading continues server-side regardless.
const pollSubmission = async (notebookId, submissionId) => {
  const deadline = Date.now() + 300000
  let delay = 1500
  let consecutiveErrors = 0
  while (Date.now() < deadline) {
    await sleep(delay)
    try {
      const s = await notebookService.submissionStatus(notebookId, submissionId)
      consecutiveErrors = 0
      if (s.status === 'graded' || s.status === 'error') return s
    } catch (e) {
      if (++consecutiveErrors >= 5) throw e
    }
    delay = Math.min(delay + 400, 4000)
  }
  const err = new Error('grading-timeout')
  err.friendly =
    'Still grading — this is taking longer than usual. Check your submissions in a moment.'
  throw err
}

const AUTOSAVE_MS = 2500

const DIFF_TINT = {
  easy: 'bg-emerald-50 text-emerald-600 dark:bg-emerald-900/20 dark:text-emerald-400',
  medium: 'bg-amber-50 text-amber-600 dark:bg-amber-900/20 dark:text-amber-400',
  hard: 'bg-red-50 text-red-600 dark:bg-red-900/20 dark:text-red-400',
}

const TestResultRow = ({ result }) => (
  <div className="flex items-start gap-2 rounded-lg px-3 py-2 bg-surface-50 dark:bg-surface-900/40">
    {result.passed ? (
      <CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0 text-emerald-500" />
    ) : (
      <XCircle className="w-4 h-4 mt-0.5 shrink-0 text-red-500" />
    )}
    <div className="min-w-0 flex-1">
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium text-surface-800 dark:text-surface-100 truncate">
          {result.name || 'Check'}
        </span>
        {result.is_hidden && (
          <Lock className="w-3 h-3 text-surface-400" title="Hidden test" />
        )}
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

const NotebookPage = () => {
  const { notebookId } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const editorRef = useRef(null)

  const [working, setWorking] = useState(null)
  const [saveState, setSaveState] = useState('idle') // idle | saving | saved
  const [submitting, setSubmitting] = useState(false)
  const [submitPhase, setSubmitPhase] = useState('')
  const [result, setResult] = useState(null)
  const [selfCheck, setSelfCheck] = useState(null)
  // Drives the submit modal: null | 'confirm' | 'running' | 'result'.
  const [flowPhase, setFlowPhase] = useState(null)

  const saveTimer = useRef(null)
  const pendingDoc = useRef(null)
  const openedAt = useRef(Date.now())

  const { data: notebook, isLoading, error } = useQuery({
    queryKey: ['notebook', notebookId],
    queryFn: () => notebookService.getNotebook(notebookId),
    enabled: !!notebookId,
  })

  const { data: history = [], refetch: refetchHistory } = useQuery({
    queryKey: ['notebook-submissions', notebookId],
    queryFn: () => notebookService.mySubmissions(notebookId),
    enabled: !!notebookId,
  })

  const initialDocument = useMemo(() => notebook?.notebook_json, [notebook?.notebook_json])

  // Tests whose source the browser is allowed to see (visible checks, plus
  // hidden ones only when the author opted into full in-browser grading).
  const runnableTests = useMemo(
    () => (notebook?.tests || []).filter((t) => t.source),
    [notebook?.tests],
  )
  const visibleTests = useMemo(
    () => (notebook?.tests || []).filter((t) => t.source && !t.is_hidden),
    [notebook?.tests],
  )

  const flushSave = useCallback(async () => {
    const doc = pendingDoc.current
    if (!doc || !notebookId) return
    pendingDoc.current = null
    setSaveState('saving')
    try {
      const elapsed = Math.round((Date.now() - openedAt.current) / 1000)
      openedAt.current = Date.now()
      await notebookService.saveDraft(notebookId, {
        notebook_json: forApi(doc),
        time_spent_seconds: elapsed,
      })
      setSaveState('saved')
    } catch {
      setSaveState('idle')
    }
  }, [notebookId])

  const handleChange = useCallback((doc) => {
    setWorking(doc)
    pendingDoc.current = doc
    setSaveState('saving')
    clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(flushSave, AUTOSAVE_MS)
  }, [flushSave])

  // Never lose work on navigate-away or tab close.
  useEffect(() => {
    const onHide = () => { if (pendingDoc.current) flushSave() }
    window.addEventListener('beforeunload', onHide)
    document.addEventListener('visibilitychange', onHide)
    return () => {
      window.removeEventListener('beforeunload', onHide)
      document.removeEventListener('visibilitychange', onHide)
      clearTimeout(saveTimer.current)
      if (pendingDoc.current) flushSave()
    }
  }, [flushSave])

  const handleReset = async () => {
    if (!window.confirm('Reset the lab back to the original template? Your current work will be lost.')) return
    try {
      const data = await notebookService.resetDraft(notebookId)
      pendingDoc.current = null
      queryClient.setQueryData(['notebook', notebookId], (prev) =>
        prev ? { ...prev, notebook_json: data.notebook_json } : prev)
      setSelfCheck(null)
      toast.success('Lab reset to the template.')
    } catch {
      toast.error('Could not reset the lab.')
    }
  }

  const handleSelfCheck = async () => {
    if (!visibleTests.length) {
      toast('This lab has no practice checks — use Submit when you are ready.')
      return
    }
    try {
      const results = await editorRef.current.executeForGrading(visibleTests)
      const byId = new Map(results.map((r) => [r.id, r]))
      setSelfCheck(visibleTests.map((t) => ({
        name: t.name,
        is_hidden: false,
        passed: !!byId.get(t.id)?.passed,
        error: byId.get(t.id)?.error || '',
        points: byId.get(t.id)?.passed ? t.points : 0,
        max_points: t.points,
      })))
    } catch (err) {
      toast.error(err.message || 'Could not run the checks.')
    }
  }

  const handleSubmit = () => {
    if (!notebook?.can_submit || submitting) return
    setSubmitPhase('')
    setFlowPhase('confirm')
  }

  const runSubmission = async () => {
    setFlowPhase('running')
    setSubmitting(true)
    setResult(null)
    setSelfCheck(null)
    try {
      // Re-run everything from a clean kernel so the score reflects the code as
      // written, not stale outputs from an earlier state.
      let provisional = []
      if (notebook.provisional_grading !== 'none' && runnableTests.length) {
        setSubmitPhase('Running your lab…')
        try {
          provisional = await editorRef.current.executeForGrading(runnableTests, {
            onProgress: setSubmitPhase,
          })
        } catch {
          provisional = []
        }
      }

      setSubmitPhase('Submitting…')
      await flushSave()
      const doc = editorRef.current.getDocument()
      const submission = await notebookService.submit(notebookId, {
        notebook_json: forApi(doc),
        provisional_results: provisional,
      })

      let final = submission
      if (submission.status === 'queued' || submission.status === 'running') {
        setSubmitPhase('Grading on the server…')
        setResult(submission)
        final = await pollSubmission(notebookId, submission.id)
      }
      setResult(final)
      setFlowPhase('result')

      queryClient.invalidateQueries({ queryKey: ['notebook', notebookId] })
      refetchHistory()
    } catch (err) {
      const message = err.friendly
        || err.response?.data?.error
        || err.message
        || 'Could not submit. Please try again.'
      toast.error(message)
      setFlowPhase(null)
    } finally {
      setSubmitting(false)
      setSubmitPhase('')
    }
  }

  if (isLoading) return <Loading />
  if (error || !notebook) {
    return (
      <div className="max-w-3xl mx-auto px-4 py-16 text-center">
        <AlertTriangle className="w-10 h-10 mx-auto text-amber-500 mb-3" />
        <p className="text-surface-600 dark:text-surface-300">
          This lab is not available.
        </p>
        <button
          onClick={() => navigate(-1)}
          className="mt-4 text-sm font-medium text-primary-600 hover:underline"
        >
          Go back
        </button>
      </div>
    )
  }

  const displayed = result || null
  const hasSubmitted = !!result || history.length > 0

  return (
    <div className="max-w-6xl mx-auto px-4 py-6 space-y-5">
      <div className="flex items-start gap-3">
        <button
          onClick={() => navigate(-1)}
          className="mt-1 p-2 rounded-lg hover:bg-surface-100 dark:hover:bg-surface-800 text-surface-500"
          aria-label="Back"
        >
          <ArrowLeft className="w-4 h-4" />
        </button>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <NotebookIcon className="w-5 h-5 text-primary-600 shrink-0" />
            <h1 className="text-xl font-bold text-surface-900 dark:text-white truncate">
              {notebook.title}
            </h1>
            <span className={`rounded-md px-2 py-0.5 text-xs font-medium ${DIFF_TINT[notebook.difficulty] || DIFF_TINT.easy}`}>
              {notebook.difficulty}
            </span>
            {notebook.max_marks ? (
              <span className="rounded-md bg-surface-100 dark:bg-surface-800 px-2 py-0.5 text-xs font-medium text-surface-600 dark:text-surface-300">
                {notebook.max_marks} marks
              </span>
            ) : null}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-surface-500 dark:text-surface-400">
            {notebook.is_timed && notebook.due_at && (
              <span className={`inline-flex items-center gap-1 ${notebook.is_past_due ? 'text-red-500' : ''}`}>
                <Clock className="w-3 h-3" />
                Due {new Date(notebook.due_at).toLocaleString()}
              </span>
            )}
            {notebook.hidden_test_count > 0 && (
              <span className="inline-flex items-center gap-1">
                <Lock className="w-3 h-3" />
                {notebook.hidden_test_count} hidden check
                {notebook.hidden_test_count > 1 ? 's' : ''}
              </span>
            )}
            <span className="inline-flex items-center gap-1">
              {saveState === 'saving' ? (
                <><Loader2 className="w-3 h-3 animate-spin" /> Saving…</>
              ) : saveState === 'saved' ? (
                <><Save className="w-3 h-3" /> Saved</>
              ) : null}
            </span>
          </div>
        </div>
      </div>

      {notebook.description ? (
        <div
          className="prose prose-sm dark:prose-invert max-w-none rounded-xl border border-surface-200 dark:border-surface-700 bg-white dark:bg-surface-800 p-4"
          dangerouslySetInnerHTML={{ __html: notebook.description }}
        />
      ) : null}

      {notebook.is_past_due && (
        <div className="flex items-center gap-2 rounded-xl border border-red-200 dark:border-red-900/40 bg-red-50 dark:bg-red-900/10 px-4 py-2.5 text-sm text-red-700 dark:text-red-300">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          The due date has passed — this lab no longer accepts submissions.
        </div>
      )}

      <LabStatusCard
        notebook={notebook}
        result={displayed}
        history={history}
        submitting={submitting}
        onSubmit={handleSubmit}
        onViewDetails={() => setFlowPhase('result')}
      />

      {selfCheck && (
        <motion.div
          initial={{ opacity: 0, y: -6 }}
          animate={{ opacity: 1, y: 0 }}
          className="rounded-xl border border-surface-200 dark:border-surface-700 bg-white dark:bg-surface-800 p-4 space-y-2"
        >
          <h2 className="flex items-center gap-2 text-sm font-semibold text-surface-800 dark:text-surface-100">
            <FlaskConical className="w-4 h-4 text-primary-600" />
            Practice checks
            <span className="ml-auto text-xs font-normal text-surface-500">
              These don&apos;t count towards your grade
            </span>
          </h2>
          {selfCheck.map((r, i) => <TestResultRow key={i} result={r} />)}
        </motion.div>
      )}

      <NotebookEditor
        ref={editorRef}
        document={initialDocument}
        datasets={notebook.datasets || []}
        packages={notebook.packages || []}
        onChange={handleChange}
        headerExtra={
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleReset}
              className="inline-flex items-center gap-1.5 rounded-lg border border-surface-200 dark:border-surface-700 px-3 py-1.5 text-xs font-medium text-surface-600 dark:text-surface-300 hover:bg-surface-50 dark:hover:bg-surface-700"
              title="Reset to the original template"
            >
              <RotateCcw className="w-3.5 h-3.5" /> Reset
            </button>
            {visibleTests.length > 0 && (
              <button
                type="button"
                onClick={handleSelfCheck}
                disabled={submitting}
                className="inline-flex items-center gap-1.5 rounded-lg border border-primary-200 dark:border-primary-800 px-3 py-1.5 text-xs font-medium text-primary-600 hover:bg-primary-50 dark:hover:bg-primary-900/20 disabled:opacity-50"
                title="Run the practice checks without using an attempt"
              >
                <FlaskConical className="w-3.5 h-3.5" /> Check
              </button>
            )}
            <button
              type="button"
              onClick={handleSubmit}
              disabled={submitting || !notebook.can_submit}
              className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium ${
                notebook.can_submit
                  ? 'bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50'
                  : 'bg-surface-100 dark:bg-surface-700 text-surface-400 dark:text-surface-500 cursor-not-allowed'
              }`}
              title={
                notebook.can_submit
                  ? 'Submit for grading'
                  : notebook.is_past_due
                    ? 'The due date has passed'
                    : 'No attempts remaining'
              }
            >
              {submitting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
              {hasSubmitted && notebook.can_submit ? 'Resubmit' : 'Submit'}
            </button>
          </div>
        }
      />

      <SubmitFlowModal
        phase={flowPhase}
        notebook={notebook}
        progress={submitPhase}
        result={displayed}
        onCancel={() => { if (!submitting) setFlowPhase(null) }}
        onConfirm={runSubmission}
        onClose={() => setFlowPhase(null)}
        onRetry={() => setFlowPhase('confirm')}
      />

    </div>
  )
}

export default NotebookPage
