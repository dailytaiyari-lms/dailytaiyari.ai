import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { courseService } from '../services/courseService'
import { insightsService } from '../services/insightsService'
import Loading from '../components/common/Loading'
import { MasteryBar } from './Practice'
import { Brain, Flag, Archive, RefreshCw, Sparkles } from 'lucide-react'

const DEFICIT_LABELS = {
  low_mastery: 'Low mastery',
  retention: 'Fading retention',
  misconception: 'Repeated misconception',
  transfer_gap: 'Weak transfer',
  cognitive_gap: 'Application gap',
  starter: 'Starter',
}

const Tile = ({ title, children }) => (
  <div className="p-5 rounded-2xl bg-white dark:bg-surface-800 border border-surface-200 dark:border-surface-700">
    <h3 className="text-sm font-semibold text-surface-500 mb-3">{title}</h3>
    {children}
  </div>
)

const Toggle = ({ checked, onChange, label }) => (
  <label className="flex items-center justify-between gap-3 cursor-pointer">
    <span className="text-sm">{label}</span>
    <button
      onClick={onChange}
      className={`w-10 h-6 rounded-full transition-colors relative ${
        checked ? 'bg-primary-500' : 'bg-surface-300 dark:bg-surface-600'
      }`}
    >
      <span
        className={`absolute top-0.5 w-5 h-5 rounded-full bg-white transition-all ${
          checked ? 'left-[18px]' : 'left-0.5'
        }`}
      />
    </button>
  </label>
)

/**
 * Learner Intelligence home for teachers/admins: class concept mastery,
 * active deficits, practice adoption and the generated-item provenance list.
 */
const InsightsHome = () => {
  const queryClient = useQueryClient()
  const [courseId, setCourseId] = useState('')
  const [tab, setTab] = useState('class') // class | generated

  const { data: courses } = useQuery({
    queryKey: ['insightCourses'],
    queryFn: courseService.getCourses,
  })
  const courseList = courses?.results ?? courses ?? []
  const activeCourse = courseId || courseList[0]?.id

  const { data: overview, isLoading } = useQuery({
    queryKey: ['insightsOverview', activeCourse],
    queryFn: () => insightsService.getOverview(activeCourse),
    enabled: !!activeCourse,
  })

  const { data: generated } = useQuery({
    queryKey: ['generatedItems', activeCourse],
    queryFn: () => insightsService.getGeneratedItems(activeCourse),
    enabled: !!activeCourse && tab === 'generated',
  })

  const configMutation = useMutation({
    mutationFn: (payload) => insightsService.updatePracticeConfig(activeCourse, payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['insightsOverview'] }),
  })
  const retireMutation = useMutation({
    mutationFn: insightsService.retireGeneratedItem,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['generatedItems'] }),
  })
  const taggingMutation = useMutation({ mutationFn: insightsService.runTagging })

  if (!activeCourse) return <Loading fullScreen />

  const config = overview?.config

  return (
    <div className="space-y-6">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-display font-bold flex items-center gap-2">
            <Brain className="text-primary-500" /> Learning Insights
          </h1>
          <p className="text-surface-500 mt-1">
            What your students understand, and how your assessments are performing
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={activeCourse}
            onChange={(e) => setCourseId(e.target.value)}
            className="px-3 py-2 rounded-xl border border-surface-300 dark:border-surface-600 bg-white dark:bg-surface-800 text-sm"
          >
            {courseList.map((course) => (
              <option key={course.id} value={course.id}>{course.name}</option>
            ))}
          </select>
          <button
            onClick={() => taggingMutation.mutate()}
            disabled={taggingMutation.isPending}
            title="Queue an AI tagging pass over untagged questions"
            className="inline-flex items-center gap-2 px-3 py-2 rounded-xl bg-surface-100 dark:bg-surface-800 text-sm hover:bg-surface-200 dark:hover:bg-surface-700"
          >
            <RefreshCw size={14} className={taggingMutation.isPending ? 'animate-spin' : ''} />
            {taggingMutation.isSuccess ? 'Tagging queued' : 'Tag questions'}
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-2">
        {[['class', 'Class view'], ['generated', 'Generated questions']].map(([key, label]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`px-4 py-2 rounded-xl text-sm font-medium transition-colors ${
              tab === key
                ? 'bg-primary-500 text-white'
                : 'bg-surface-100 dark:bg-surface-800 hover:bg-surface-200'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {isLoading ? (
        <Loading />
      ) : tab === 'class' ? (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* Concept mastery */}
          <div className="lg:col-span-2">
            <Tile title="Class concept mastery (weakest first)">
              {overview?.concepts?.length ? (
                <div className="space-y-3 max-h-[28rem] overflow-y-auto pr-1">
                  {overview.concepts.map((row) => (
                    <div key={row.concept_id}>
                      <div className="flex items-center justify-between text-sm mb-1 gap-2">
                        <span className="truncate">
                          {row.name}
                          <span className="text-surface-400"> · {row.subject}</span>
                        </span>
                        <span className="text-surface-400 shrink-0">
                          {Math.round(row.avg_mastery * 100)}% · {row.students} students
                        </span>
                      </div>
                      <MasteryBar value={row.avg_mastery} />
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-surface-400">
                  No concept evidence yet — it accumulates as students take quizzes
                  and mock tests.
                </p>
              )}
            </Tile>
          </div>

          <div className="space-y-4">
            <Tile title="Active deficits (last 30 days)">
              {Object.keys(overview?.deficit_counts || {}).length ? (
                <ul className="space-y-2 text-sm">
                  {Object.entries(overview.deficit_counts).map(([kind, count]) => (
                    <li key={kind} className="flex justify-between">
                      <span>{DEFICIT_LABELS[kind] || kind}</span>
                      <span className="font-semibold">{count}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-surface-400">No open deficits.</p>
              )}
            </Tile>

            <Tile title="Practice adoption (30 days)">
              <ul className="space-y-2 text-sm">
                <li className="flex justify-between"><span>Suggested</span><span className="font-semibold">{overview?.practice_adoption?.suggested ?? 0}</span></li>
                <li className="flex justify-between"><span>Completed</span><span className="font-semibold text-success-500">{overview?.practice_adoption?.completed ?? 0}</span></li>
                <li className="flex justify-between"><span>Dismissed</span><span className="font-semibold text-surface-400">{overview?.practice_adoption?.dismissed ?? 0}</span></li>
                <li className="flex justify-between pt-2 border-t border-surface-200 dark:border-surface-700">
                  <span className="flex items-center gap-1"><Flag size={14} /> Flagged questions</span>
                  <span className="font-semibold">{overview?.flagged_items ?? 0}</span>
                </li>
              </ul>
            </Tile>

            {config && (
              <Tile title="Smart Practice controls">
                <div className="space-y-3">
                  <Toggle
                    label="Practice suggestions"
                    checked={config.practice_enabled}
                    onChange={() =>
                      configMutation.mutate({ practice_enabled: !config.practice_enabled })
                    }
                  />
                  <Toggle
                    label="AI question generation"
                    checked={config.generation_enabled}
                    onChange={() =>
                      configMutation.mutate({ generation_enabled: !config.generation_enabled })
                    }
                  />
                </div>
              </Tile>
            )}
          </div>
        </div>
      ) : (
        <Tile title={`AI-generated practice questions (${overview?.generated_pool?.active ?? 0} active)`}>
          {generated?.length ? (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-surface-400 border-b border-surface-200 dark:border-surface-700">
                    <th className="py-2 pr-3">Question</th>
                    <th className="py-2 pr-3">Made for</th>
                    <th className="py-2 pr-3">Served</th>
                    <th className="py-2 pr-3">% correct</th>
                    <th className="py-2 pr-3">Health</th>
                    <th className="py-2" />
                  </tr>
                </thead>
                <tbody>
                  {generated.map((row) => (
                    <tr key={row.id} className="border-b border-surface-100 dark:border-surface-700/50">
                      <td className="py-2 pr-3 max-w-md truncate">{row.question_text}</td>
                      <td className="py-2 pr-3">{DEFICIT_LABELS[row.deficit_kind] || row.deficit_kind}</td>
                      <td className="py-2 pr-3">{row.times_served}</td>
                      <td className="py-2 pr-3">
                        {row.p_value != null ? `${Math.round(row.p_value * 100)}%` : '—'}
                      </td>
                      <td className="py-2 pr-3">
                        {row.retired_at ? (
                          <span className="text-surface-400">Retired</span>
                        ) : row.flagged ? (
                          <span className="text-warning-500">Review</span>
                        ) : (
                          <span className="text-success-500">OK</span>
                        )}
                      </td>
                      <td className="py-2 text-right">
                        {!row.retired_at && (
                          <button
                            onClick={() => retireMutation.mutate(row.id)}
                            className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-lg bg-surface-100 dark:bg-surface-700 hover:bg-danger-100 hover:text-danger-600"
                          >
                            <Archive size={12} /> Retire
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-sm text-surface-400 flex items-center gap-2">
              <Sparkles size={16} />
              No generated questions yet — they appear when a diagnosed gap has too
              few existing questions to practise with.
            </p>
          )}
        </Tile>
      )}
    </div>
  )
}

export default InsightsHome
