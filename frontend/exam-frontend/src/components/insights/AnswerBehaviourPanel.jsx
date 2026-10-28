import { useQuery } from '@tanstack/react-query'
import { Activity, Flag } from 'lucide-react'
import { insightsService } from '../../services/insightsService'
import LabelBar, { LabelLegend } from './LabelBar'

const secs = (value) => (value == null ? '—' : `${Math.round(value)} s`)

/** Per-question answer behaviour for one assessment (diagnosis teacher view). */
export default function AnswerBehaviourPanel({ kind, assessmentId }) {
  const { data, isLoading } = useQuery({
    queryKey: ['assessmentBehaviour', kind, assessmentId],
    queryFn: () => insightsService.getAssessmentBehaviour(kind, assessmentId),
  })
  if (isLoading || !data) return null

  return (
    <div className="p-5 rounded-2xl bg-white dark:bg-surface-800 border border-surface-200 dark:border-surface-700">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <h3 className="text-sm font-semibold text-surface-500 flex items-center gap-1">
          <Activity size={14} /> Answer behaviour
        </h3>
        <span className="text-xs text-surface-400">
          {data.answers} diagnosed answers · {data.flagged} questions flagged
        </span>
      </div>
      <LabelLegend />
      {data.answers === 0 ? (
        <p className="text-sm text-surface-400 mt-4">
          No diagnosed answers yet — they appear once students finish this assessment.
        </p>
      ) : (
        <ul className="mt-4 space-y-4">
          {data.items.map((item, index) => (
            <li key={item.item_key}>
              <div className="flex items-start justify-between gap-3 text-sm mb-1">
                <span className="truncate">
                  <span className="text-surface-400">Q{index + 1}.</span> {item.question_text}
                </span>
                <span className="text-xs text-surface-400 shrink-0">
                  {item.distribution.total} answers · median {secs(item.median_active_s)}
                  {item.usual_s != null && ` (usual ${secs(item.usual_s)})`}
                  {item.self_reports > 0 && ` · ${item.self_reports} self-reports`}
                </span>
              </div>
              <LabelBar counts={item.distribution.counts} total={item.distribution.total} />
              {item.flags.map((flag) => (
                <p key={flag.code} className="text-xs text-warning-600 mt-1 flex items-center gap-1">
                  <Flag size={12} /> {flag.message} ({Math.round(flag.share * 100)}%)
                </p>
              ))}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
