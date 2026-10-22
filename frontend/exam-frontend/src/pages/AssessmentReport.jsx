import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { insightsService } from '../services/insightsService'
import Loading from '../components/common/Loading'
import { MasteryBar } from './Practice'
import { FileSearch, Flag } from 'lucide-react'

const StatsCell = ({ stats }) => {
  if (!stats) return <span className="text-surface-400">no data</span>
  return (
    <div className="text-xs space-y-0.5">
      <p>{stats.attempts} attempts · {Math.round((stats.p_value ?? 0) * 100)}% correct</p>
      <p className="text-surface-400">
        observed {stats.observed_difficulty}
        {stats.discrimination != null && ` · discrimination ${stats.discrimination.toFixed(2)}`}
      </p>
    </div>
  )
}

/**
 * Post-assessment intelligence report: how each question performed, which
 * concepts the class struggled with, and what the paper never tested.
 */
const AssessmentReport = () => {
  const { kind, assessmentId } = useParams()
  const { data, isLoading } = useQuery({
    queryKey: ['assessmentReport', kind, assessmentId],
    queryFn: () => insightsService.getAssessmentReport(kind, assessmentId),
  })

  if (isLoading) return <Loading fullScreen />
  if (!data) return null

  const flaggedItems = data.items.filter((item) => item.stats?.difficulty_divergence)

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-display font-bold flex items-center gap-2">
          <FileSearch className="text-primary-500" /> {data.assessment.title}
        </h1>
        <p className="text-surface-500 mt-1">Assessment intelligence report</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Concept performance */}
        <div className="p-5 rounded-2xl bg-white dark:bg-surface-800 border border-surface-200 dark:border-surface-700">
          <h3 className="text-sm font-semibold text-surface-500 mb-3">Concept performance</h3>
          <div className="space-y-3 max-h-96 overflow-y-auto pr-1">
            {data.concept_performance.map((row) => (
              <div key={row.concept}>
                <div className="flex justify-between text-sm mb-1 gap-2">
                  <span className="truncate">{row.concept}</span>
                  <span className="text-surface-400 shrink-0">
                    {row.accuracy != null ? `${Math.round(row.accuracy * 100)}%` : '—'}
                  </span>
                </div>
                <MasteryBar value={row.accuracy ?? 0} />
              </div>
            ))}
            {!data.concept_performance.length && (
              <p className="text-sm text-surface-400">
                No answer data yet — the report fills in as students take it.
              </p>
            )}
          </div>
        </div>

        {/* Question quality flags */}
        <div className="p-5 rounded-2xl bg-white dark:bg-surface-800 border border-surface-200 dark:border-surface-700">
          <h3 className="text-sm font-semibold text-surface-500 mb-3 flex items-center gap-1">
            <Flag size={14} /> Questions worth reviewing
          </h3>
          {flaggedItems.length ? (
            <ul className="space-y-3 text-sm max-h-96 overflow-y-auto pr-1">
              {flaggedItems.map((item) => (
                <li key={item.item_id}>
                  <p className="truncate font-medium">{item.question_text}</p>
                  <p className="text-xs text-warning-500">
                    Authored {item.difficulty || '—'}, plays {item.stats.observed_difficulty} in
                    practice ({Math.round(item.stats.p_value * 100)}% correct)
                  </p>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-surface-400">No quality flags at current volume.</p>
          )}
        </div>

        {/* Coverage gaps */}
        <div className="p-5 rounded-2xl bg-white dark:bg-surface-800 border border-surface-200 dark:border-surface-700">
          <h3 className="text-sm font-semibold text-surface-500 mb-3">Concepts this paper never tested</h3>
          {data.untested_concepts.length ? (
            <div className="flex flex-wrap gap-1.5 max-h-96 overflow-y-auto">
              {data.untested_concepts.map((name) => (
                <span
                  key={name}
                  className="px-2 py-1 rounded-full text-xs bg-surface-100 dark:bg-surface-700 text-surface-600 dark:text-surface-300"
                >
                  {name}
                </span>
              ))}
            </div>
          ) : (
            <p className="text-sm text-surface-400">Full concept coverage.</p>
          )}
        </div>
      </div>

      {/* Item table */}
      <div className="p-5 rounded-2xl bg-white dark:bg-surface-800 border border-surface-200 dark:border-surface-700">
        <h3 className="text-sm font-semibold text-surface-500 mb-3">
          Every question ({data.items.length})
        </h3>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-surface-400 border-b border-surface-200 dark:border-surface-700">
                <th className="py-2 pr-3">Question</th>
                <th className="py-2 pr-3">Type</th>
                <th className="py-2 pr-3">Concepts</th>
                <th className="py-2 pr-3">Difficulty</th>
                <th className="py-2">Empirical</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((item) => (
                <tr key={item.item_id} className="border-b border-surface-100 dark:border-surface-700/50 align-top">
                  <td className="py-2 pr-3 max-w-sm truncate">{item.question_text}</td>
                  <td className="py-2 pr-3 capitalize">{item.item_type}</td>
                  <td className="py-2 pr-3">
                    {item.concepts.length ? item.concepts.join(', ') : (
                      <span className="text-surface-400">untagged</span>
                    )}
                  </td>
                  <td className="py-2 pr-3 capitalize">{item.difficulty || '—'}</td>
                  <td className="py-2"><StatsCell stats={item.stats} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

export default AssessmentReport
