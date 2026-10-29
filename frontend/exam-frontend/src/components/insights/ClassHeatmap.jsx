import { Fragment, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { insightsService } from '../../services/insightsService'
import { pct } from '../progress/progressUi'

const BAND_TEXT = {
  weak: 'Below 50%',
  in_progress: '50–80%',
  strong: '80% and up',
  not_enough_data: 'Not enough data',
}
const BAND_CELL = {
  weak: 'bg-error-100 text-error-700 dark:bg-error-900/40 dark:text-error-200',
  in_progress: 'bg-warning-100 text-warning-700 dark:bg-warning-900/40 dark:text-warning-200',
  strong: 'bg-success-100 text-success-700 dark:bg-success-900/40 dark:text-success-200',
  not_enough_data: 'bg-surface-100 text-surface-500 dark:bg-surface-700 dark:text-surface-300',
}

/** Insights home: students per topic and mastery band, for one course. */
export default function ClassHeatmap({ courseId }) {
  const [selected, setSelected] = useState(null) // { topicId, band }
  const { data, isError, error } = useQuery({
    queryKey: ['courseHeatmap', courseId],
    queryFn: () => insightsService.getCourseHeatmap(courseId),
    enabled: !!courseId,
  })
  if (isError) {
    return (
      <p className="text-sm text-error-600 dark:text-error-300">
        {error?.response?.data?.error || 'Could not load the heatmap.'}
      </p>
    )
  }
  if (!data) return null

  const picked = selected && data.topics.find((t) => t.id === selected.topicId)
  return (
    <div className="p-5 rounded-2xl bg-white dark:bg-surface-800 border border-surface-200 dark:border-surface-700">
      <h3 className="text-sm font-semibold text-surface-500 mb-3">
        Class topic heatmap ({data.students} students{data.capped ? ', first 500' : ''})
      </h3>
      {data.topics.length === 0 ? (
        <p className="text-sm text-surface-400">No topics yet. Add a syllabus or tag questions to see this.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-surface-400 border-b border-surface-200 dark:border-surface-700">
                <th className="py-2 pr-3">Topic</th>
                <th className="py-2 pr-3">Coverage</th>
                {data.bands.map((band) => <th key={band} className="py-2 pr-2 text-center">{BAND_TEXT[band]}</th>)}
              </tr>
            </thead>
            <tbody>
              {data.topics.map((topic) => (
                <Fragment key={topic.id}>
                  <tr className="border-b border-surface-100 dark:border-surface-700/50">
                    <td className="py-2 pr-3">
                      <span className="block truncate max-w-[14rem]">{topic.name}</span>
                      <span className="text-xs text-surface-400">{topic.subject}</span>
                    </td>
                    <td className="py-2 pr-3 text-surface-500">{pct(topic.coverage)}</td>
                    {data.bands.map((band) => {
                      const isOpen = picked?.id === topic.id && selected.band === band
                      return (
                        <td key={band} className="py-1 pr-2 text-center">
                          <button
                            type="button"
                            disabled={!topic.counts[band]}
                            aria-expanded={isOpen}
                            onClick={() => setSelected(isOpen ? null : { topicId: topic.id, band })}
                            className={`w-full min-w-[3rem] px-2 py-1.5 rounded-lg font-semibold disabled:opacity-40 ${BAND_CELL[band]} ${isOpen ? 'ring-2 ring-primary-400' : ''}`}
                          >
                            {topic.counts[band]}
                          </button>
                        </td>
                      )
                    })}
                  </tr>
                  {picked?.id === topic.id && (
                    <tr className="border-b border-surface-100 dark:border-surface-700/50">
                      <td colSpan={2 + data.bands.length} className="py-3">
                        <p className="text-xs font-semibold text-surface-500 mb-2">
                          {picked.name} · {BAND_TEXT[selected.band]}
                        </p>
                        <ul className="flex flex-wrap gap-2 text-sm">
                          {picked.students[selected.band].map((student) => (
                            <li key={student.id}>
                              <Link
                                to={`/admin/insights/students/${student.id}`}
                                className="px-2.5 py-1 rounded-full bg-surface-100 dark:bg-surface-700 hover:text-primary-500"
                              >
                                {student.name}
                              </Link>
                            </li>
                          ))}
                        </ul>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
