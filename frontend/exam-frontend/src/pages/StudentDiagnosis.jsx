import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { insightsService } from '../services/insightsService'
import Loading from '../components/common/Loading'
import { DeficitChip, MasteryBar } from './Practice'
import { User, CheckCircle2, XCircle, Hourglass } from 'lucide-react'

const STATUS_ICONS = {
  completed: <CheckCircle2 size={15} className="text-success-500" />,
  dismissed: <XCircle size={15} className="text-surface-400" />,
  expired: <Hourglass size={15} className="text-surface-400" />,
}

/**
 * Teacher view of one student: concept mastery map, current deficits and the
 * audit trail of what the system suggested and what came of it.
 */
const StudentDiagnosis = () => {
  const { studentId } = useParams()
  const { data, isLoading } = useQuery({
    queryKey: ['studentDiagnosis', studentId],
    queryFn: () => insightsService.getStudentDiagnosis(studentId),
  })

  if (isLoading) return <Loading fullScreen />
  if (!data) return null

  const weak = data.concepts.filter((row) => row.mastery < 0.5 && row.confidence !== 'low')
  const flagged = data.concepts.filter((row) => row.flags?.length)

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <div className="w-11 h-11 rounded-full bg-primary-100 dark:bg-primary-900/40 flex items-center justify-center">
          <User className="text-primary-500" size={20} />
        </div>
        <div>
          <h1 className="text-xl font-display font-bold">{data.student.name}</h1>
          <p className="text-sm text-surface-500">{data.student.email}</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Concept map */}
        <div className="p-5 rounded-2xl bg-white dark:bg-surface-800 border border-surface-200 dark:border-surface-700">
          <h3 className="text-sm font-semibold text-surface-500 mb-3">
            Concept mastery ({data.concepts.length})
          </h3>
          <div className="space-y-3 max-h-[30rem] overflow-y-auto pr-1">
            {data.concepts.map((row) => (
              <div key={row.concept_id}>
                <div className="flex items-center justify-between text-sm mb-1 gap-2">
                  <span className="truncate">
                    {row.concept}
                    <span className="text-surface-400"> · {row.subject}</span>
                  </span>
                  <span className="text-surface-400 shrink-0">
                    {Math.round(row.mastery * 100)}%
                    {row.confidence === 'low' && ' (low evidence)'}
                  </span>
                </div>
                <MasteryBar value={row.mastery} />
                {row.flags?.includes('weak_transfer') && (
                  <p className="text-xs text-primary-500 mt-1">
                    Applies it alone, struggles when concepts combine
                  </p>
                )}
                {row.flags?.includes('fading_retention') && (
                  <p className="text-xs text-warning-500 mt-1">Learned, but fading</p>
                )}
                {row.flags?.includes('repeat_misconception') && (
                  <p className="text-xs text-danger-500 mt-1">Repeats the same wrong answer</p>
                )}
              </div>
            ))}
            {!data.concepts.length && (
              <p className="text-sm text-surface-400">No concept evidence yet.</p>
            )}
          </div>
        </div>

        <div className="space-y-4">
          {/* Needs attention */}
          <div className="p-5 rounded-2xl bg-white dark:bg-surface-800 border border-surface-200 dark:border-surface-700">
            <h3 className="text-sm font-semibold text-surface-500 mb-3">Needs attention</h3>
            {weak.length || flagged.length ? (
              <ul className="space-y-1.5 text-sm">
                {weak.slice(0, 6).map((row) => (
                  <li key={row.concept_id}>
                    <span className="font-medium">{row.concept}</span>
                    <span className="text-surface-400"> — {Math.round(row.mastery * 100)}% mastery</span>
                  </li>
                ))}
                {flagged.slice(0, 4).map((row) => (
                  <li key={`flag-${row.concept_id}`}>
                    <span className="font-medium">{row.concept}</span>
                    <span className="text-surface-400"> — {row.flags.join(', ').replaceAll('_', ' ')}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-surface-400">Nothing alarming right now.</p>
            )}
          </div>

          {/* Practice audit trail */}
          <div className="p-5 rounded-2xl bg-white dark:bg-surface-800 border border-surface-200 dark:border-surface-700">
            <h3 className="text-sm font-semibold text-surface-500 mb-3">
              What was suggested, and what happened
            </h3>
            <div className="space-y-3 max-h-[22rem] overflow-y-auto pr-1">
              {data.practice_history.map((set) => (
                <div key={set.id} className="flex items-start gap-2 text-sm">
                  <span className="mt-0.5 shrink-0">
                    {STATUS_ICONS[set.status] || <Hourglass size={15} className="text-primary-500" />}
                  </span>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <DeficitChip kind={set.deficit_kind} />
                      <span className="text-xs text-surface-400">
                        {new Date(set.created_at).toLocaleDateString()}
                      </span>
                    </div>
                    <p className="text-surface-500 mt-1 text-xs">{set.reason_text}</p>
                    {set.status === 'completed' && (
                      <p className="text-xs mt-0.5 font-medium">
                        Scored {set.score_correct}/{set.score_total}
                      </p>
                    )}
                  </div>
                </div>
              ))}
              {!data.practice_history.length && (
                <p className="text-sm text-surface-400">No practice suggested yet.</p>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default StudentDiagnosis
