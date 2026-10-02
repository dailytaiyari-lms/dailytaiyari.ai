import { useParams, useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { useQuery } from '@tanstack/react-query'
import { courseService } from '../services/courseService'
import Loading from '../components/common/Loading'
import {
  BookOpen, PlayCircle, PenTool, ArrowLeft, ChevronRight, Clock, ClipboardList, Code2, Lock,
} from 'lucide-react'

/**
 * Lists all topics in a chapter. Clicking a topic goes to topic content (notes & quizzes).
 * Flow: Study → Subject → Chapters → [this page: Topics] → Topic content
 */
const StudyChapterTopics = () => {
  const { chapterId } = useParams()
  const navigate = useNavigate()

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['studyChapterDetail', chapterId],
    queryFn: () => courseService.getStudyChapterDetail(chapterId),
    enabled: !!chapterId,
    refetchOnMount: 'always',
    retry: (count, err) => err?.response?.status !== 403 && count < 2,
  })

  if (isLoading) return <Loading fullScreen />

  // Chapter is locked behind sequential progression.
  if (isError && error?.response?.status === 403) {
    const info = error.response.data || {}
    const subjectId = info?.subject_id || info?.locked_by?.subject_id
    return (
      <div className="max-w-lg mx-auto text-center py-16 space-y-4">
        <div className="w-16 h-16 rounded-2xl bg-surface-100 dark:bg-surface-700 flex items-center justify-center mx-auto">
          <Lock size={30} className="text-surface-400" />
        </div>
        <h1 className="text-xl font-semibold">Chapter locked</h1>
        <p className="text-surface-500">
          {info.detail || 'Complete the previous chapter to unlock this one.'}
        </p>
        <button
          onClick={() => navigate(subjectId ? `/study/${subjectId}` : -1)}
          className="btn-primary inline-flex items-center gap-2"
        >
          <ArrowLeft size={16} /> Back to chapters
        </button>
      </div>
    )
  }

  const chapter = data?.chapter
  const topics = data?.topics || []
  const locked = chapter?.locked || false
  const lockedBy = chapter?.locked_by || null

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm flex-wrap">
        <button
          onClick={() => navigate('/study')}
          className="text-surface-500 hover:text-primary-600 flex items-center gap-1"
        >
          <ArrowLeft size={16} /> Study
        </button>
        <span className="text-surface-400">/</span>
        <button
          onClick={() => navigate(`/study/${chapter?.subject_id}`)}
          className="text-surface-500 hover:text-primary-600"
        >
          {chapter?.subject_name}
        </button>
        <span className="text-surface-400">/</span>
        <span className="font-medium">{chapter?.name}</span>
      </div>

      {/* Chapter header */}
      <div className="card p-6">
        <h1 className="text-2xl font-display font-bold">{chapter?.name}</h1>
        {chapter?.description && (
          <p className="text-surface-500 mt-1">{chapter.description}</p>
        )}
        <p className="text-sm text-surface-500 mt-2">
          {topics.length} topic{topics.length !== 1 ? 's' : ''} in this chapter · Select a topic to view notes and quizzes
        </p>
        <div className="flex items-center gap-2 mt-3 text-sm text-surface-500">
          <Clock size={16} />
          Est. {chapter?.estimated_hours}h
        </div>
      </div>

      {/* Topics list */}
      <div>
        <h2 className="text-lg font-semibold mb-3">Topics</h2>
        {locked && (
          <div className="card p-4 mb-3 flex items-start gap-3 bg-warning-50 dark:bg-warning-900/20 border-warning-100 dark:border-warning-900/40">
            <Lock size={18} className="text-warning-600 flex-shrink-0 mt-0.5" />
            <div className="text-sm text-warning-700 dark:text-warning-300">
              <p className="font-semibold">This chapter is locked</p>
              <p className="mt-0.5">
                Complete
                {lockedBy?.name ? <> <span className="font-semibold">“{lockedBy.name}”</span></> : ' the previous chapter'} to unlock these topics. You can preview what’s inside below.
              </p>
            </div>
          </div>
        )}
        {topics.length === 0 ? (
          <div className="card p-8 text-center text-surface-500">
            <p>No topics in this chapter yet.</p>
          </div>
        ) : (
          <div className="space-y-2">
            {topics.map((item, index) => {
              const { topic, reading = [], videos = [], quizzes = [], assignments = [], coding = [] } = item
              const readingDone = reading.filter(r => r.is_completed).length
              const videosDone = videos.filter(v => v.is_completed).length
              const quizzesAttempted = quizzes.filter(q => q.attempts_count > 0).length
              const assignmentsDone = assignments.filter(a => a.is_completed).length
              const codingDone = coding.filter(c => c.is_completed).length
              const total = reading.length + videos.length + quizzes.length + assignments.length + coding.length
              const completed = readingDone + videosDone + quizzesAttempted + assignmentsDone + codingDone
              const progress = total > 0 ? Math.round((completed / total) * 100) : 0
              const stats = [
                { icon: BookOpen, done: readingDone, total: reading.length, label: 'read' },
                { icon: PlayCircle, done: videosDone, total: videos.length, label: 'watched' },
                { icon: PenTool, done: quizzesAttempted, total: quizzes.length, label: 'quizzes' },
                { icon: Code2, done: codingDone, total: coding.length, label: 'coding' },
                { icon: ClipboardList, done: assignmentsDone, total: assignments.length, label: 'assignments' },
              ].filter(s => s.total > 0)

              return (
                <motion.div
                  key={topic.id}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: index * 0.03 }}
                  onClick={() => { if (!locked) navigate(`/study/chapter/${chapterId}/topic/${topic.id}`) }}
                  className={`card p-4 flex items-center gap-4 transition-all group ${
                    locked
                      ? 'opacity-70 cursor-not-allowed'
                      : 'cursor-pointer hover:border-primary-200 hover:shadow-md'
                  }`}
                >
                  <div className="w-10 h-10 rounded-xl bg-primary-50 dark:bg-primary-900/20 flex items-center justify-center text-primary-600 font-semibold text-sm flex-shrink-0">
                    {index + 1}
                  </div>
                  <div className="flex-1 min-w-0">
                    <h3 className="font-semibold truncate">{topic.name}</h3>
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-1 text-xs text-surface-500">
                      {stats.map((s, i) => {
                        const Icon = s.icon
                        return (
                          <span key={i} className="flex items-center gap-1">
                            <Icon size={12} />
                            {s.done}/{s.total} {s.label}
                          </span>
                        )
                      })}
                    </div>
                  </div>
                  <div className="flex items-center gap-3 flex-shrink-0">
                    <div className="w-16 text-right">
                      <span className="text-sm font-semibold">{progress}%</span>
                    </div>
                    {locked ? (
                      <Lock size={18} className="text-surface-400" />
                    ) : (
                      <ChevronRight size={20} className="text-surface-400 group-hover:text-primary-500" />
                    )}
                  </div>
                </motion.div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}

export default StudyChapterTopics
