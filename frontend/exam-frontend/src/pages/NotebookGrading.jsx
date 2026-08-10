import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import {
  ArrowLeft, Users, CheckCircle2, Clock, Trophy, ChevronRight,
  Notebook as NotebookIcon, Lock, BarChart3, Percent,
} from 'lucide-react'
import { notebookAdminService as svc } from '../services/notebookService'
import Loading from '../components/common/Loading'

/**
 * Notebook submissions overview (mirrors CodingGrading).
 * Grading is automatic, so we surface completed / partial rather than a
 * "needs grading" queue — but instructors can still open any submission to
 * read the executed notebook and override the marks.
 */
const NotebookGrading = () => {
  const { courseId, notebookId } = useParams()
  const navigate = useNavigate()

  const { data, isLoading } = useQuery({
    queryKey: ['nb-admin-submissions', notebookId],
    queryFn: () => svc.submissions(notebookId),
    enabled: !!notebookId,
  })

  const { data: stats } = useQuery({
    queryKey: ['nb-admin-stats', notebookId],
    queryFn: () => svc.stats(notebookId),
    enabled: !!notebookId,
  })

  if (isLoading) return <Loading fullScreen />

  const notebook = data?.notebook || {}
  const counts = data?.counts || {}
  const submissions = data?.submissions || []
  const pending = data?.pending_students || []

  const cards = [
    { label: 'Students', value: counts.total_students || 0, icon: Users, tint: 'text-surface-500 bg-surface-100 dark:bg-surface-800' },
    { label: 'Submitted', value: counts.submitted || 0, icon: CheckCircle2, tint: 'text-blue-600 bg-blue-50 dark:bg-blue-900/20' },
    { label: 'Completed', value: counts.completed || 0, icon: Trophy, tint: 'text-success-600 bg-success-50 dark:bg-success-900/20' },
    { label: 'Not started', value: counts.pending || 0, icon: Clock, tint: 'text-amber-600 bg-amber-50 dark:bg-amber-900/20' },
    { label: 'Avg score', value: `${counts.average_percent || 0}%`, icon: Percent, tint: 'text-primary-600 bg-primary-50 dark:bg-primary-900/20' },
  ]

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2 text-sm flex-wrap">
        <button
          onClick={() => navigate(`/courses/${courseId}/manage`)}
          className="text-surface-500 hover:text-primary-600 flex items-center gap-1"
        >
          <ArrowLeft size={16} /> Course Manager
        </button>
        {notebook.topic_name && (
          <>
            <span className="text-surface-400">/</span>
            <span className="text-surface-500">{notebook.topic_name}</span>
          </>
        )}
      </div>

      <div className="card p-6">
        <div className="flex items-start gap-3">
          <div className="w-11 h-11 rounded-xl bg-primary-50 dark:bg-primary-900/20 text-primary-600 dark:text-primary-400 flex items-center justify-center shrink-0">
            <NotebookIcon className="w-5 h-5" />
          </div>
          <div className="min-w-0">
            <h1 className="text-xl font-bold text-surface-900 dark:text-white">
              {notebook.title}
            </h1>
            <div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-surface-500">
              <span className="capitalize">{notebook.difficulty}</span>
              <span>{notebook.total_points} points</span>
              {notebook.max_marks ? <span>{notebook.max_marks} marks</span> : null}
              {notebook.is_timed && notebook.due_at && (
                <span className="inline-flex items-center gap-1">
                  <Clock className="w-3 h-3" />
                  Due {new Date(notebook.due_at).toLocaleString()}
                </span>
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {cards.map((c) => (
          <div key={c.label} className="card p-4">
            <div className={`w-9 h-9 rounded-lg flex items-center justify-center mb-2 ${c.tint}`}>
              <c.icon className="w-4 h-4" />
            </div>
            <p className="text-xl font-bold text-surface-900 dark:text-white">{c.value}</p>
            <p className="text-xs text-surface-500">{c.label}</p>
          </div>
        ))}
      </div>

      {stats?.tests?.length > 0 && (
        <div className="card p-5">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-surface-800 dark:text-surface-100 mb-3">
            <BarChart3 className="w-4 h-4 text-primary-600" />
            Test pass rates
            <span className="ml-auto text-xs font-normal text-surface-500">
              across {stats.graded_submissions} graded submission
              {stats.graded_submissions === 1 ? '' : 's'}
            </span>
          </h2>
          <div className="space-y-2.5">
            {stats.tests.map((t) => (
              <div key={t.id} className="flex items-center gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <span className="text-sm text-surface-700 dark:text-surface-200 truncate">
                      {t.name}
                    </span>
                    {t.is_hidden && <Lock className="w-3 h-3 text-surface-400" />}
                    <span className="text-xs text-surface-400">{t.points} pt</span>
                  </div>
                  <div className="mt-1 h-1.5 rounded-full bg-surface-100 dark:bg-surface-700 overflow-hidden">
                    <div
                      className={`h-full rounded-full ${t.pass_rate >= 60 ? 'bg-success-500' : t.pass_rate >= 30 ? 'bg-amber-500' : 'bg-red-500'}`}
                      style={{ width: `${t.pass_rate}%` }}
                    />
                  </div>
                </div>
                <span className="shrink-0 text-xs font-semibold text-surface-600 dark:text-surface-300 w-20 text-right">
                  {t.pass_rate}% ({t.passed}/{t.attempted})
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="card overflow-hidden">
        <div className="px-5 py-3 border-b border-surface-100 dark:border-surface-700">
          <h2 className="text-sm font-semibold text-surface-800 dark:text-surface-100">
            Submissions ({submissions.length})
          </h2>
        </div>
        {submissions.length === 0 ? (
          <p className="px-5 py-8 text-center text-sm text-surface-500">
            No submissions yet.
          </p>
        ) : (
          <div className="divide-y divide-surface-100 dark:divide-surface-700">
            {submissions.map((s, i) => (
              <motion.button
                key={s.id}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: Math.min(i * 0.02, 0.3) }}
                onClick={() => navigate(
                  `/courses/${courseId}/manage/notebooks/${notebookId}/submissions/${s.id}`,
                )}
                className="w-full flex items-center gap-3 px-5 py-3 text-left hover:bg-surface-50 dark:hover:bg-surface-800/60"
              >
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-surface-800 dark:text-surface-100 truncate">
                    {s.student_name || s.student_email}
                  </p>
                  <p className="text-xs text-surface-500">
                    {s.attempts_used} attempt{s.attempts_used === 1 ? '' : 's'}
                    {' · '}
                    {new Date(s.submitted_at).toLocaleString()}
                    {s.is_late && <span className="text-amber-600"> · late</span>}
                  </p>
                </div>
                {s.status === 'graded' ? (
                  <>
                    <span className="shrink-0 text-xs font-semibold text-surface-600 dark:text-surface-300">
                      {s.passed_points}/{s.total_points} pts
                    </span>
                    <span className={`shrink-0 rounded-md px-2 py-0.5 text-xs font-semibold ${
                      s.score_percent >= 60
                        ? 'bg-success-50 text-success-600 dark:bg-success-900/20'
                        : 'bg-amber-50 text-amber-600 dark:bg-amber-900/20'
                    }`}>
                      {s.score_percent}%
                    </span>
                  </>
                ) : (
                  <span className="shrink-0 rounded-md bg-surface-100 dark:bg-surface-700 px-2 py-0.5 text-xs font-medium text-surface-500 capitalize">
                    {s.status}
                  </span>
                )}
                {s.override_marks !== null && s.override_marks !== undefined && (
                  <span className="shrink-0 rounded-md bg-primary-50 dark:bg-primary-900/20 px-2 py-0.5 text-xs font-medium text-primary-600">
                    overridden
                  </span>
                )}
                <ChevronRight className="w-4 h-4 shrink-0 text-surface-400" />
              </motion.button>
            ))}
          </div>
        )}
      </div>

      {pending.length > 0 && (
        <div className="card overflow-hidden">
          <div className="px-5 py-3 border-b border-surface-100 dark:border-surface-700">
            <h2 className="text-sm font-semibold text-surface-800 dark:text-surface-100">
              Not started ({pending.length})
            </h2>
          </div>
          <div className="divide-y divide-surface-100 dark:divide-surface-700">
            {pending.map((p) => (
              <div key={p.student} className="px-5 py-2.5">
                <p className="text-sm text-surface-700 dark:text-surface-200">
                  {p.student_name || p.student_email}
                </p>
                <p className="text-xs text-surface-500">{p.student_email}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default NotebookGrading
