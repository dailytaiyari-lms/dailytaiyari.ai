import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { insightsService } from '../../services/insightsService'

const RATES = [
  ['guess', 'Guesses'],
  ['careless_slip', 'Careless slips'],
  ['time_pressure', 'Time pressure'],
]
const pct = (value) => (value == null ? '—' : `${Math.round(value * 100)}%`)

function Spark({ points }) {
  const values = points.map((p) => p ?? 0)
  const max = Math.max(0.01, ...values)
  return (
    <svg viewBox="0 0 60 20" className="w-16 h-5" aria-hidden="true">
      <polyline
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        points={values.map((v, i) => `${(i * 60) / Math.max(1, values.length - 1)},${20 - (v / max) * 18}`).join(' ')}
      />
    </svg>
  )
}

/** Insights home: guess / slip / time-pressure rates for one course. */
export default function AnswerBehaviourTile({ courseId }) {
  const { data } = useQuery({
    queryKey: ['courseBehaviour', courseId],
    queryFn: () => insightsService.getCourseBehaviour(courseId),
    enabled: !!courseId,
  })
  if (!data) return null

  return (
    <div className="p-5 rounded-2xl bg-white dark:bg-surface-800 border border-surface-200 dark:border-surface-700">
      <h3 className="text-sm font-semibold text-surface-500 mb-3">
        Answer behaviour (last {data.days} days · {data.rates.answers} answers)
      </h3>
      <ul className="space-y-2 text-sm">
        {RATES.map(([key, label]) => (
          <li key={key} className="flex items-center justify-between gap-2">
            <span>{label}</span>
            <span className="flex items-center gap-2 text-primary-500">
              <Spark points={data.trend.map((week) => week[key])} />
              <span className="font-semibold text-surface-800 dark:text-surface-100 w-10 text-right">
                {pct(data.rates[key])}
              </span>
            </span>
          </li>
        ))}
      </ul>

      {data.students_to_check.length > 0 && (
        <div className="mt-4 pt-3 border-t border-surface-200 dark:border-surface-700">
          <p className="text-xs font-semibold text-surface-500 mb-2">Students to check</p>
          <ul className="space-y-1 text-sm">
            {data.students_to_check.map((row) => (
              <li key={row.student_id} className="flex justify-between gap-2">
                <Link to={`/admin/insights/students/${row.student_id}`} className="truncate hover:text-primary-500">
                  {row.name}
                </Link>
                <span className="text-xs text-surface-400 shrink-0">
                  slips {pct(row.careless_slip)} · time {pct(row.time_pressure)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {data.recent_assessments.length > 0 && (
        <div className="mt-4 pt-3 border-t border-surface-200 dark:border-surface-700">
          <p className="text-xs font-semibold text-surface-500 mb-2">Recent assessments</p>
          <ul className="space-y-1 text-sm">
            {data.recent_assessments.map((row) => (
              <li key={`${row.kind}:${row.id}`}>
                <Link to={`/admin/insights/assessments/${row.kind}/${row.id}`} className="truncate hover:text-primary-500">
                  {row.title}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
