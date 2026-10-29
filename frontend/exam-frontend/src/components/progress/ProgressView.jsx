import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Target, TrendingDown, TrendingUp } from 'lucide-react'
import RollupTree from './RollupTree'
import ProfilesPanel from './ProfilesPanel'
import { BandBar, STATUS_CLASS, STATUS_TEXT, Sparkline, pct } from './progressUi'

const REVIEW_PATH = {
  quiz: (id) => `/quiz/review/${id}`,
  mock: (id) => `/mock-test/review/${id}`,
  rich_mock: (id) => `/mock-test/live-review/${id}`,
}

const Card = ({ title, children }) => (
  <div className="p-5 rounded-2xl bg-white dark:bg-surface-800 border border-surface-200 dark:border-surface-700">
    {title && <h3 className="text-sm font-semibold text-surface-500 mb-3">{title}</h3>}
    {children}
  </div>
)

function TopicList({ title, icon: Icon, topics, practiceOn, empty }) {
  return (
    <Card title={<span className="flex items-center gap-2"><Icon size={15} /> {title}</span>}>
      {topics.length === 0 ? (
        <p className="text-sm text-surface-400">{empty}</p>
      ) : (
        <ul className="space-y-3">
          {topics.map((topic) => (
            <li key={topic.id}>
              <div className="flex items-center justify-between gap-2 text-sm mb-1">
                <span className="truncate">
                  {topic.name}
                  <span className="text-surface-400"> · {topic.subject}</span>
                </span>
                <span className={`shrink-0 ${STATUS_CLASS[topic.status]}`}>{pct(topic.mastery)}</span>
              </div>
              <BandBar node={topic} />
              {practiceOn && topic.status === 'weak' && topic.concept_ids.length > 0 && (
                <Link
                  to={`/practice?concepts=${topic.concept_ids.join(',')}&topic=${encodeURIComponent(topic.name)}`}
                  className="inline-flex items-center gap-1 mt-1.5 text-xs font-medium text-primary-500 hover:text-primary-600"
                >
                  <Target size={12} /> Practise this
                </Link>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

/**
 * The body of My Progress: course picker, subject cards, weak / strong
 * topics, breakdown, skill profiles and recent answers. Used by the student
 * page and by the teacher's Progress tab.
 */
export default function ProgressView({ data, onCourseChange, practiceOn = false, linkReviews = false }) {
  const [subjectId, setSubjectId] = useState(null)
  const subject = data.subjects.find((s) => s.id === subjectId) || data.subjects[0]

  return (
    <div className="space-y-6">
      {data.courses.length > 1 && (
        <select
          value={data.course.id}
          onChange={(e) => { setSubjectId(null); onCourseChange(e.target.value) }}
          className="px-3 py-2 rounded-xl border border-surface-300 dark:border-surface-600 bg-white dark:bg-surface-800 text-sm"
        >
          {data.courses.map((course) => <option key={course.id} value={course.id}>{course.name}</option>)}
        </select>
      )}

      {/* Subject cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
        {data.subjects.map((s) => (
          <button
            key={s.id}
            type="button"
            onClick={() => setSubjectId(s.id)}
            className={`text-left p-5 rounded-2xl bg-white dark:bg-surface-800 border transition-colors ${
              subject?.id === s.id
                ? 'border-primary-400 dark:border-primary-500'
                : 'border-surface-200 dark:border-surface-700 hover:border-surface-300'
            }`}
          >
            <div className="flex items-start justify-between gap-2">
              <p className="font-semibold truncate">{s.name}</p>
              <Sparkline points={s.trend_4w} />
            </div>
            <p className={`text-2xl font-bold mt-2 ${STATUS_CLASS[s.status]}`}>
              {s.mastery != null ? pct(s.mastery) : '—'}
            </p>
            <p className="text-xs text-surface-400 mt-1">
              {s.mastery != null ? STATUS_TEXT[s.status] : STATUS_TEXT.not_enough_data}
              {s.total > 0 && ` · ${s.covered} of ${s.total} ${s.has_tree ? 'subtopics' : 'concepts'} practised`}
            </p>
          </button>
        ))}
      </div>

      {/* Weak and strong topics */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <TopicList
          title="Topics to work on" icon={TrendingDown} topics={data.weak}
          practiceOn={practiceOn} empty="Nothing weak with enough answers yet."
        />
        <TopicList
          title="Strong topics" icon={TrendingUp} topics={data.strong}
          practiceOn={false} empty="Keep going — strong topics show up here."
        />
      </div>

      {/* Breakdown */}
      {subject && (
        <Card title={`${subject.name}: breakdown`}>
          <RollupTree subject={subject} />
        </Card>
      )}

      <ProfilesPanel profiles={data.profiles} />

      {/* Recent answers (only when the payload carries them) */}
      {Array.isArray(data.recent_answers) && (
        <Card title="Recent answers">
          {data.recent_answers.length === 0 ? (
            <p className="text-sm text-surface-400">No finished tests in this course yet.</p>
          ) : (
            <ul className="divide-y divide-surface-100 dark:divide-surface-700/50">
              {data.recent_answers.map((row) => {
                const body = (
                  <div className="flex items-center justify-between gap-3 py-2.5">
                    <div className="min-w-0">
                      <p className="text-sm font-medium truncate">{row.title}</p>
                      <p className="text-xs text-surface-400">
                        {row.completed_at ? new Date(row.completed_at).toLocaleDateString() : ''}
                      </p>
                    </div>
                    <p className="text-xs text-surface-500 text-right">
                      {row.results_pending
                        ? 'Results not released yet'
                        : row.noted ? row.summary : 'Nothing to flag'}
                    </p>
                  </div>
                )
                return (
                  <li key={row.attempt_id}>
                    {linkReviews && REVIEW_PATH[row.review] ? (
                      <Link to={REVIEW_PATH[row.review](row.attempt_id)} className="block hover:bg-surface-50 dark:hover:bg-surface-700/40 rounded-lg px-1">
                        {body}
                      </Link>
                    ) : body}
                  </li>
                )
              })}
            </ul>
          )}
        </Card>
      )}
    </div>
  )
}
