import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  ArrowLeft, CheckCircle2, XCircle, Lock, Loader2, RefreshCw, Save,
  AlertTriangle, Download, User,
} from 'lucide-react'
import { notebookAdminService as svc } from '../services/notebookService'
import NotebookViewer from '../components/notebook/NotebookViewer'
import { downloadNotebook } from '../components/notebook/notebookDoc'
import Loading from '../components/common/Loading'

const StatusPill = ({ status }) => {
  const tint = {
    graded: 'bg-success-50 text-success-600 dark:bg-success-900/20',
    error: 'bg-red-50 text-red-600 dark:bg-red-900/20',
    queued: 'bg-amber-50 text-amber-600 dark:bg-amber-900/20',
    running: 'bg-amber-50 text-amber-600 dark:bg-amber-900/20',
  }[status] || 'bg-surface-100 text-surface-500 dark:bg-surface-800'
  return (
    <span className={`rounded-md px-2 py-0.5 text-xs font-semibold capitalize ${tint}`}>
      {status}
    </span>
  )
}

const NotebookSubmissionReview = () => {
  const { courseId, notebookId, submissionId } = useParams()
  const navigate = useNavigate()

  const [marks, setMarks] = useState('')
  const [feedback, setFeedback] = useState('')
  const [saving, setSaving] = useState(false)
  const [regrading, setRegrading] = useState(false)

  const { data: submission, isLoading, refetch } = useQuery({
    queryKey: ['nb-admin-submission', submissionId],
    queryFn: () => svc.getSubmission(submissionId),
    enabled: !!submissionId,
    // Keep polling while the authoritative grade is still in flight.
    refetchInterval: (query) =>
      ['queued', 'running'].includes(query.state.data?.status) ? 3000 : false,
  })

  useEffect(() => {
    if (!submission) return
    setMarks(submission.override_marks ?? '')
    setFeedback(submission.feedback || '')
  }, [submission?.id, submission?.override_marks, submission?.feedback])

  const handleSave = async () => {
    setSaving(true)
    try {
      await svc.gradeSubmission(submissionId, {
        override_marks: marks === '' ? null : marks,
        feedback,
      })
      await refetch()
      toast.success('Grade saved.')
    } catch (err) {
      toast.error(err.response?.data?.error || 'Could not save the grade.')
    } finally {
      setSaving(false)
    }
  }

  const handleRegrade = async () => {
    if (!window.confirm('Re-run the autograder on this submission?')) return
    setRegrading(true)
    try {
      await svc.regradeSubmission(submissionId)
      await refetch()
      toast.success('Regrade started.')
    } catch (err) {
      toast.error(err.response?.data?.error || 'Could not start a regrade.')
    } finally {
      setRegrading(false)
    }
  }

  if (isLoading) return <Loading fullScreen />
  if (!submission) {
    return (
      <div className="py-16 text-center">
        <AlertTriangle className="w-10 h-10 mx-auto text-amber-500 mb-3" />
        <p className="text-surface-600 dark:text-surface-300">Submission not found.</p>
      </div>
    )
  }

  const results = submission.results || []
  const maxMarks = submission.notebook_max_marks

  return (
    <div className="space-y-5">
      <button
        onClick={() => navigate(`/courses/${courseId}/manage/notebooks/${notebookId}`)}
        className="flex items-center gap-1 text-sm text-surface-500 hover:text-primary-600"
      >
        <ArrowLeft size={16} /> All submissions
      </button>

      <div className="card p-5">
        <div className="flex flex-wrap items-start gap-3">
          <div className="w-10 h-10 rounded-xl bg-surface-100 dark:bg-surface-800 text-surface-500 flex items-center justify-center shrink-0">
            <User className="w-5 h-5" />
          </div>
          <div className="min-w-0 flex-1">
            <h1 className="text-lg font-bold text-surface-900 dark:text-white truncate">
              {submission.student_name || submission.student_email}
            </h1>
            <p className="text-xs text-surface-500">
              {submission.notebook_title} · Attempt {submission.attempt_number} ·{' '}
              {new Date(submission.submitted_at).toLocaleString()}
              {submission.is_late && <span className="text-amber-600"> · late</span>}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <StatusPill status={submission.status} />
            {submission.status === 'graded' && (
              <span className="text-sm font-semibold text-surface-800 dark:text-surface-100">
                {submission.passed_points}/{submission.total_points} pts ({submission.score_percent}%)
              </span>
            )}
          </div>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          <button
            onClick={handleRegrade}
            disabled={regrading}
            className="inline-flex items-center gap-1.5 rounded-lg border border-surface-200 dark:border-surface-700 px-3 py-1.5 text-xs font-medium text-surface-600 dark:text-surface-300 hover:bg-surface-50 dark:hover:bg-surface-700 disabled:opacity-50"
          >
            {regrading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
            Re-run autograder
          </button>
          <button
            onClick={() => downloadNotebook(
              submission.notebook_json,
              `${(submission.student_name || 'submission').replace(/\s+/g, '_')}_attempt${submission.attempt_number}.ipynb`,
            )}
            className="inline-flex items-center gap-1.5 rounded-lg border border-surface-200 dark:border-surface-700 px-3 py-1.5 text-xs font-medium text-surface-600 dark:text-surface-300 hover:bg-surface-50 dark:hover:bg-surface-700"
          >
            <Download className="w-3.5 h-3.5" /> Download .ipynb
          </button>
        </div>
      </div>

      {submission.execution_error && (
        <div className="card p-4">
          <p className="text-xs font-semibold text-red-600 mb-1">Execution error</p>
          <pre className="overflow-x-auto rounded-lg bg-red-50 dark:bg-red-900/10 p-3 font-mono text-xs text-red-700 dark:text-red-300 whitespace-pre-wrap">
            {submission.execution_error}
          </pre>
        </div>
      )}

      <div className="grid gap-5 lg:grid-cols-3">
        <div className="lg:col-span-2 space-y-3">
          <h2 className="text-sm font-semibold text-surface-800 dark:text-surface-100">
            Submitted notebook
          </h2>
          <NotebookViewer document={submission.notebook_json} />
        </div>

        <div className="space-y-4">
          <div className="card p-4">
            <h2 className="text-sm font-semibold text-surface-800 dark:text-surface-100 mb-3">
              Autograder results
            </h2>
            {results.length === 0 ? (
              <p className="text-xs text-surface-500">No results yet.</p>
            ) : (
              <div className="space-y-2">
                {results.map((r, i) => (
                  <div key={i} className="flex items-start gap-2 rounded-lg bg-surface-50 dark:bg-surface-900/40 px-3 py-2">
                    {r.passed
                      ? <CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0 text-emerald-500" />
                      : <XCircle className="w-4 h-4 mt-0.5 shrink-0 text-red-500" />}
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5">
                        <span className="text-sm text-surface-800 dark:text-surface-100 truncate">
                          {r.name}
                        </span>
                        {r.is_hidden && <Lock className="w-3 h-3 shrink-0 text-surface-400" />}
                      </div>
                      {r.error && !r.passed && (
                        <p className="mt-0.5 font-mono text-[11px] text-red-600 dark:text-red-400 whitespace-pre-wrap break-words">
                          {r.error}
                        </p>
                      )}
                    </div>
                    <span className="shrink-0 text-xs font-semibold text-surface-500">
                      {r.points}/{r.max_points}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {submission.provisional_total_points > 0 && (
            <div className="card p-4">
              <p className="text-xs font-semibold text-surface-500 mb-1">
                In-browser provisional score
              </p>
              <p className="text-sm text-surface-700 dark:text-surface-200">
                {submission.provisional_passed_points}/{submission.provisional_total_points} points
                {submission.status === 'graded'
                  && submission.provisional_passed_points !== submission.passed_points && (
                  <span className="ml-2 text-amber-600 text-xs">
                    differs from the server grade
                  </span>
                )}
              </p>
            </div>
          )}

          <div className="card p-4 space-y-3">
            <h2 className="text-sm font-semibold text-surface-800 dark:text-surface-100">
              Instructor grade
            </h2>
            <div>
              <label className="block text-xs font-medium text-surface-500 mb-1">
                Override marks {maxMarks ? `(0–${maxMarks})` : ''}
              </label>
              <input
                type="number"
                min="0"
                max={maxMarks || undefined}
                step="0.5"
                value={marks}
                onChange={(e) => setMarks(e.target.value)}
                placeholder={
                  submission.marks !== null && submission.marks !== undefined
                    ? `Auto: ${submission.marks}`
                    : 'Auto'
                }
                className="w-full rounded-lg border border-surface-200 dark:border-surface-700 bg-white dark:bg-surface-900 px-3 py-2 text-sm"
              />
              <p className="mt-1 text-[11px] text-surface-400">
                Leave blank to keep the autograded marks.
              </p>
            </div>
            <div>
              <label className="block text-xs font-medium text-surface-500 mb-1">
                Feedback
              </label>
              <textarea
                rows={5}
                value={feedback}
                onChange={(e) => setFeedback(e.target.value)}
                placeholder="Visible to the student with their result."
                className="w-full rounded-lg border border-surface-200 dark:border-surface-700 bg-white dark:bg-surface-900 px-3 py-2 text-sm"
              />
            </div>
            <button
              onClick={handleSave}
              disabled={saving}
              className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg bg-primary-600 px-3 py-2 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-50"
            >
              {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
              Save grade
            </button>
            {submission.graded_by_name && (
              <p className="text-[11px] text-surface-400">
                Last graded by {submission.graded_by_name}
                {submission.graded_at && ` · ${new Date(submission.graded_at).toLocaleString()}`}
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export default NotebookSubmissionReview
