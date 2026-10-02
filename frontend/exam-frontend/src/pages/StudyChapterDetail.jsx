import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { useQuery } from '@tanstack/react-query'
import { courseService } from '../services/courseService'
import Loading from '../components/common/Loading'
import {
  BookOpen, PlayCircle, PenTool, ArrowLeft, ChevronRight,
  CheckCircle2, Clock, Eye, Bookmark, Trophy, FileText,
  RefreshCw, BarChart3, Star
} from 'lucide-react'

const TABS = [
  { key: 'reading', label: 'Reading', icon: BookOpen },
  { key: 'videos', label: 'Videos', icon: PlayCircle },
  { key: 'quizzes', label: 'Quizzes', icon: PenTool },
  { key: 'leaderboard', label: 'Leaderboard', icon: Trophy },
]

const StudyChapterDetail = () => {
  const { chapterId } = useParams()
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState('reading')

  const { data, isLoading } = useQuery({
    queryKey: ['studyChapterDetail', chapterId],
    queryFn: () => courseService.getStudyChapterDetail(chapterId),
    enabled: !!chapterId,
    refetchOnMount: 'always',
  })

  const { data: leaderboard } = useQuery({
    queryKey: ['studyLeaderboard', 'chapter', chapterId],
    queryFn: () => courseService.getStudyLeaderboard('chapter', chapterId),
    enabled: !!chapterId && activeTab === 'leaderboard',
  })

  if (isLoading) return <Loading fullScreen />

  const chapter = data?.chapter
  const reading = data?.reading || []
  const videos = data?.videos || []
  const quizzes = data?.quizzes || []

  const readingDone = reading.filter(r => r.is_completed).length
  const videosDone = videos.filter(v => v.is_completed).length
  const quizzesAttempted = quizzes.filter(q => q.attempts_count > 0).length

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
        <div className="flex flex-wrap items-center gap-5 mt-4 text-sm text-surface-500">
          <span className="flex items-center gap-1.5">
            <BookOpen size={16} className="text-blue-500" />
            {readingDone}/{reading.length} read
          </span>
          <span className="flex items-center gap-1.5">
            <PlayCircle size={16} className="text-red-500" />
            {videosDone}/{videos.length} watched
          </span>
          <span className="flex items-center gap-1.5">
            <PenTool size={16} className="text-green-500" />
            {quizzesAttempted}/{quizzes.length} quizzes
          </span>
          <span className="flex items-center gap-1.5">
            <Clock size={16} className="text-warning-500" />
            Est. {chapter?.estimated_hours}h
          </span>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 p-1 bg-surface-100 dark:bg-surface-800 rounded-xl overflow-x-auto scrollbar-hide">
        {TABS.map((tab) => {
          const Icon = tab.icon
          const count = tab.key === 'reading' ? reading.length
            : tab.key === 'videos' ? videos.length
            : tab.key === 'quizzes' ? quizzes.length
            : null
          return (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`flex-1 min-w-[100px] flex items-center justify-center gap-1.5 px-4 py-2.5 rounded-lg text-sm font-medium transition-all ${
                activeTab === tab.key
                  ? 'bg-white dark:bg-surface-700 shadow-sm text-primary-600'
                  : 'text-surface-500 hover:text-surface-700'
              }`}
            >
              <Icon size={16} />
              {tab.label}
              {count !== null && (
                <span className="text-xs bg-surface-200 dark:bg-surface-600 px-1.5 py-0.5 rounded-full">
                  {count}
                </span>
              )}
            </button>
          )
        })}
      </div>

      {/* Tab content */}
      <AnimatePresence mode="wait">
        <motion.div
          key={activeTab}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -10 }}
          transition={{ duration: 0.2 }}
        >
          {activeTab === 'reading' && <ReadingTab items={reading} navigate={navigate} />}
          {activeTab === 'videos' && <VideosTab items={videos} navigate={navigate} />}
          {activeTab === 'quizzes' && <QuizzesTab items={quizzes} navigate={navigate} />}
          {activeTab === 'leaderboard' && <LeaderboardTab entries={leaderboard || []} />}
        </motion.div>
      </AnimatePresence>
    </div>
  )
}

// ── Reading Tab ──────────────────────────────────────────────────────────

const ReadingTab = ({ items, navigate }) => {
  if (items.length === 0) {
    return <EmptyState icon={BookOpen} message="No reading materials available yet" />
  }

  const typeConfig = {
    notes: { icon: FileText, color: 'bg-blue-50 text-blue-600 dark:bg-blue-900/30', label: 'Notes' },
    pdf: { icon: FileText, color: 'bg-green-50 text-green-600 dark:bg-green-900/30', label: 'PDF' },
    revision: { icon: RefreshCw, color: 'bg-purple-50 text-purple-600 dark:bg-purple-900/30', label: 'Revision' },
    formula: { icon: BarChart3, color: 'bg-amber-50 text-amber-600 dark:bg-amber-900/30', label: 'Formulas' },
  }

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
      {items.map((item) => {
        const cfg = typeConfig[item.content_type] || typeConfig.notes
        const Icon = cfg.icon
        return (
          <motion.div
            key={item.id}
            whileHover={{ y: -4 }}
            onClick={() => navigate(`/content/${item.id}`)}
            className={`card p-4 cursor-pointer transition-all relative overflow-hidden ${
              item.is_completed ? 'border-success-200 dark:border-success-800' : 'hover:border-primary-200'
            }`}
          >
            {item.is_completed && (
              <div className="absolute top-2 right-2">
                <CheckCircle2 size={18} className="text-success-500" />
              </div>
            )}
            {item.is_bookmarked && (
              <div className="absolute top-2 left-2">
                <Bookmark size={14} className="text-warning-500 fill-warning-500" />
              </div>
            )}
            <div className={`w-12 h-12 rounded-xl flex items-center justify-center mb-3 ${cfg.color}`}>
              <Icon size={24} />
            </div>
            <h4 className="font-medium text-sm leading-snug line-clamp-2 mb-1.5">{item.title}</h4>
            <p className="text-[11px] text-surface-400 truncate">{item.topic_name}</p>
            <div className="flex items-center justify-between mt-3 pt-2 border-t border-surface-100 dark:border-surface-700">
              <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-surface-100 dark:bg-surface-700 text-surface-500">
                {cfg.label}
              </span>
              <span className="text-[10px] text-surface-400 flex items-center gap-1">
                <Clock size={10} /> {item.estimated_time_minutes}m
              </span>
            </div>
          </motion.div>
        )
      })}
    </div>
  )
}

// ── Videos Tab ───────────────────────────────────────────────────────────

const VideosTab = ({ items, navigate }) => {
  if (items.length === 0) {
    return <EmptyState icon={PlayCircle} message="No videos available yet" />
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {items.map((item) => (
        <div
          key={item.id}
          onClick={() => navigate(`/content/${item.id}`)}
          className="card overflow-hidden cursor-pointer hover:border-primary-200 hover:shadow-md transition-all"
        >
          <div className="relative bg-surface-100 dark:bg-surface-800 h-36 flex items-center justify-center">
            <PlayCircle size={48} className="text-surface-300" />
            {item.is_completed && (
              <div className="absolute top-2 right-2 bg-success-500 text-white text-xs px-2 py-1 rounded-full flex items-center gap-1">
                <CheckCircle2 size={12} /> Watched
              </div>
            )}
            {item.video_duration_minutes && (
              <div className="absolute bottom-2 right-2 bg-black/70 text-white text-xs px-2 py-1 rounded">
                {item.video_duration_minutes} min
              </div>
            )}
            {item.progress_percentage > 0 && item.progress_percentage < 100 && (
              <div className="absolute bottom-0 left-0 right-0 h-1 bg-surface-200">
                <div
                  className="h-full bg-primary-500"
                  style={{ width: `${item.progress_percentage}%` }}
                />
              </div>
            )}
          </div>
          <div className="p-3">
            <h4 className="font-medium text-sm truncate">{item.title}</h4>
            <p className="text-xs text-surface-500 mt-0.5 flex items-center gap-2">
              <span>{item.topic_name}</span>
              <span className="flex items-center gap-0.5"><Eye size={10} /> {item.views_count}</span>
            </p>
          </div>
        </div>
      ))}
    </div>
  )
}

// ── Quizzes Tab ──────────────────────────────────────────────────────────

const QuizzesTab = ({ items, navigate }) => {
  if (items.length === 0) {
    return <EmptyState icon={PenTool} message="No practice quizzes available yet" />
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      {items.map((quiz) => (
        <motion.div
          key={quiz.id}
          whileHover={{ y: -4 }}
          className={`card p-4 transition-all relative overflow-hidden ${
            quiz.attempts_count > 0 ? 'border-primary-100 dark:border-primary-900' : 'hover:border-primary-200'
          }`}
        >
          {quiz.attempts_count > 0 && (
            <div className="absolute top-3 right-3 flex items-center gap-1">
              <Star size={14} className="text-warning-500 fill-warning-500" />
              <span className="font-bold text-xs">{Math.round(quiz.best_score)}%</span>
            </div>
          )}

          <div className={`w-11 h-11 rounded-xl flex items-center justify-center mb-3 ${
            quiz.attempts_count > 0
              ? 'bg-primary-50 text-primary-600 dark:bg-primary-900/30'
              : 'bg-green-50 text-green-600 dark:bg-green-900/30'
          }`}>
            <PenTool size={22} />
          </div>

          <h4 className="font-semibold text-sm leading-snug line-clamp-2 mb-1">{quiz.title}</h4>
          <p className="text-[11px] text-surface-400 truncate mb-2">{quiz.topic_name}</p>

          <div className="flex items-center gap-3 text-[11px] text-surface-500 mb-3">
            <span>{quiz.total_questions} Qs</span>
            <span className="flex items-center gap-0.5"><Clock size={10} /> {quiz.duration_minutes}m</span>
            {quiz.attempts_count > 0 && (
              <span>{quiz.attempts_count} attempt{quiz.attempts_count > 1 ? 's' : ''}</span>
            )}
          </div>

          {quiz.attempts_count > 0 && quiz.last_attempt && (
            <div className="text-[10px] text-surface-400 mb-3 p-1.5 bg-surface-50 dark:bg-surface-800 rounded">
              Last: {Math.round(quiz.last_attempt.percentage)}% ({quiz.last_attempt.correct_answers}/{quiz.last_attempt.total_questions})
            </div>
          )}

          <div className="flex gap-2 mt-auto">
            {quiz.attempts_count > 0 ? (
              <>
                <button
                  onClick={() => navigate(`/quiz/${quiz.id}`)}
                  className="flex-1 btn-primary text-xs py-1.5"
                >
                  Retry
                </button>
                <button
                  onClick={() => navigate(`/quiz/review/${quiz.last_attempt?.id}`)}
                  className="flex-1 btn-outline text-xs py-1.5"
                >
                  Review
                </button>
              </>
            ) : (
              <button
                onClick={() => navigate(`/quiz/${quiz.id}`)}
                className="flex-1 btn-primary text-xs py-1.5"
              >
                Start Quiz
              </button>
            )}
          </div>
        </motion.div>
      ))}
    </div>
  )
}

// ── Leaderboard Tab ──────────────────────────────────────────────────────

const LeaderboardTab = ({ entries }) => {
  if (entries.length === 0) {
    return <EmptyState icon={Trophy} message="No leaderboard data yet. Be the first!" />
  }

  return (
    <div className="space-y-2">
      {entries.map((entry) => (
        <div
          key={entry.rank}
          className={`card p-4 flex items-center gap-4 ${
            entry.is_current_user ? 'border-primary-300 bg-primary-50/50 dark:bg-primary-900/10' : ''
          }`}
        >
          <div className={`w-10 h-10 rounded-full flex items-center justify-center font-bold text-sm flex-shrink-0 ${
            entry.rank === 1 ? 'bg-yellow-100 text-yellow-700' :
            entry.rank === 2 ? 'bg-gray-100 text-gray-600' :
            entry.rank === 3 ? 'bg-orange-100 text-orange-700' :
            'bg-surface-100 text-surface-500'
          }`}>
            {entry.rank <= 3 ? ['🥇', '🥈', '🥉'][entry.rank - 1] : `#${entry.rank}`}
          </div>
          <div className="flex-1 min-w-0">
            <h4 className="font-medium truncate">
              {entry.student_name}
              {entry.is_current_user && (
                <span className="text-xs text-primary-600 ml-2">(You)</span>
              )}
            </h4>
            <p className="text-xs text-surface-500">{entry.accuracy}% accuracy</p>
          </div>
          <div className="text-right flex-shrink-0">
            <p className="font-bold text-sm">{entry.total_xp} XP</p>
          </div>
        </div>
      ))}
    </div>
  )
}

// ── Empty State ──────────────────────────────────────────────────────────

const EmptyState = ({ icon: Icon, message }) => (
  <div className="text-center py-12 text-surface-500">
    <Icon size={48} className="mx-auto mb-3 text-surface-300" />
    <p>{message}</p>
  </div>
)

export default StudyChapterDetail
