import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { useQuery } from '@tanstack/react-query'
import { courseService } from '../services/courseService'
import { assignmentService } from '../services/assignmentService'
import { codingService } from '../services/codingService'
import { notebookService } from '../services/notebookService'
import { liveClassService } from '../services/liveClassService'
import Loading from '../components/common/Loading'
import {
  BookOpen, PlayCircle, PenTool, ArrowLeft, CheckCircle2, Clock,
  Bookmark, FileText, RefreshCw, BarChart3, Eye, Star, LayoutList,
  Circle, ChevronRight, Trophy, ClipboardList, Lock, Code2, Radio,
  Notebook as NotebookIcon
} from 'lucide-react'

const TABS = [
  { key: 'all', label: 'All', icon: LayoutList },
  { key: 'reading', label: 'Reading', icon: BookOpen },
  { key: 'videos', label: 'Videos', icon: PlayCircle },
  { key: 'quizzes', label: 'Quizzes', icon: PenTool },
  { key: 'assignments', label: 'Assignments', icon: ClipboardList },
  { key: 'coding', label: 'Coding', icon: Code2 },
  { key: 'notebooks', label: 'Labs', icon: NotebookIcon },
  { key: 'live', label: 'Live', icon: Radio },
]

/**
 * Shows notes and quizzes for a single topic within a chapter.
 * Flow: Course (StudyCourse) → [this page: topic content]
 */
const StudyTopicContent = () => {
  const { chapterId, topicId } = useParams()
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState('all')

  // Carried into quiz attempt/review so their "Back to Course" returns here.
  const quizNavState = { from: 'course', chapterId, topicId }

  const { data, isLoading } = useQuery({
    queryKey: ['studyChapterDetail', chapterId],
    queryFn: () => courseService.getStudyChapterDetail(chapterId),
    enabled: !!chapterId,
  })

  const { data: assignments = [] } = useQuery({
    queryKey: ['topicAssignments', topicId],
    queryFn: () => assignmentService.getByTopic(topicId),
    enabled: !!topicId,
  })

  const { data: codingProblems = [] } = useQuery({
    queryKey: ['topicCoding', topicId],
    queryFn: () => codingService.getByTopic(topicId),
    enabled: !!topicId,
  })

  const { data: notebooks = [] } = useQuery({
    queryKey: ['topicNotebooks', topicId],
    queryFn: () => notebookService.getByTopic(topicId),
    enabled: !!topicId,
  })

  const { data: liveClasses = [] } = useQuery({
    queryKey: ['topicLive', topicId],
    queryFn: () => liveClassService.getByTopic(topicId),
    enabled: !!topicId,
  })

  if (isLoading) return <Loading fullScreen />

  const chapter = data?.chapter
  const topics = data?.topics || []
  const topicData = topics.find(t => t.topic.id === topicId)
  const topic = topicData?.topic
  const reading = topicData?.reading || []
  const videos = topicData?.videos || []
  const quizzes = topicData?.quizzes || []

  if (!topic) {
    return (
      <div className="card p-8 text-center">
        <p className="text-surface-500">Topic not found.</p>
        <button
          onClick={() => navigate(chapter?.course_id ? `/study/course/${chapter.course_id}` : '/study')}
          className="btn-outline mt-4"
        >
          Back to course
        </button>
      </div>
    )
  }

  // Chapter is locked behind sequential progression — allow the metadata to load
  // (so we can name the blocking chapter) but do not reveal the content itself.
  if (chapter?.locked) {
    const lockedBy = chapter?.locked_by
    return (
      <div className="max-w-lg mx-auto text-center py-16 space-y-4">
        <div className="w-16 h-16 rounded-2xl bg-warning-50 dark:bg-warning-900/20 flex items-center justify-center mx-auto">
          <Lock size={30} className="text-warning-600" />
        </div>
        <h1 className="text-xl font-semibold">This chapter is locked</h1>
        <p className="text-surface-500">
          Complete
          {lockedBy?.name ? <> <span className="font-semibold">“{lockedBy.name}”</span></> : ' the previous chapter'} to unlock “{topic.name}”.
        </p>
        <button
          onClick={() => navigate(chapter?.course_id ? `/study/course/${chapter.course_id}` : '/study')}
          className="btn-primary inline-flex items-center gap-2"
        >
          <ArrowLeft size={16} /> Back to course
        </button>
      </div>
    )
  }

  const readingDone = reading.filter(r => r.is_completed).length
  const videosDone = videos.filter(v => v.is_completed).length
  const quizzesAttempted = quizzes.filter(q => q.attempts_count > 0).length
  const codingDone = codingProblems.filter(p => p.my_best?.all_passed).length
  const assignmentsDone = assignments.filter(a => a.is_completed).length
  const notebooksDone = notebooks.filter(n => n.is_complete).length
  const liveNow = liveClasses.filter(l => l.live_status === 'live').length
  const headerStats = [
    { icon: BookOpen, color: 'text-blue-500', done: readingDone, total: reading.length, label: 'read' },
    { icon: PlayCircle, color: 'text-red-500', done: videosDone, total: videos.length, label: 'watched' },
    { icon: PenTool, color: 'text-green-500', done: quizzesAttempted, total: quizzes.length, label: 'quizzes' },
    { icon: Code2, color: 'text-primary-500', done: codingDone, total: codingProblems.length, label: 'coding' },
    { icon: NotebookIcon, color: 'text-indigo-500', done: notebooksDone, total: notebooks.length, label: 'labs' },
    { icon: ClipboardList, color: 'text-purple-500', done: assignmentsDone, total: assignments.length, label: 'assignments' },
    { icon: Radio, color: 'text-red-500', done: liveNow, total: liveClasses.length, label: 'live' },
  ].filter(s => s.total > 0)

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm flex-wrap">
        <button
          onClick={() => navigate(`/study/course/${chapter?.course_id}`)}
          className="text-surface-500 hover:text-primary-600 flex items-center gap-1"
        >
          <ArrowLeft size={16} /> {chapter?.course_name || 'Course'}
        </button>
        <span className="text-surface-400">/</span>
        <span className="text-surface-500">{chapter?.name}</span>
        <span className="text-surface-400">/</span>
        <span className="font-medium">{topic.name}</span>
      </div>

      {/* Topic header */}
      <div className="card p-6">
        <h1 className="text-2xl font-display font-bold">{topic.name}</h1>
        <p className="text-surface-500 text-sm mt-1">
          Notes and quizzes for this topic
        </p>
        <div className="flex flex-wrap items-center gap-5 mt-4 text-sm text-surface-500">
          {headerStats.map((s, i) => {
            const Icon = s.icon
            return (
              <span key={i} className="flex items-center gap-1.5">
                <Icon size={16} className={s.color} />
                {s.done}/{s.total} {s.label}
              </span>
            )
          })}
          {topic.estimated_study_hours > 0 && (
            <span className="flex items-center gap-1.5">
              <Clock size={16} className="text-warning-500" />
              Est. {topic.estimated_study_hours}h
            </span>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 p-1 bg-surface-100 dark:bg-surface-800 rounded-xl overflow-x-auto scrollbar-hide">
        {TABS.map((tab) => {
          const Icon = tab.icon
          const count = tab.key === 'all' ? reading.length + videos.length + quizzes.length + assignments.length + codingProblems.length + notebooks.length + liveClasses.length
            : tab.key === 'reading' ? reading.length
            : tab.key === 'videos' ? videos.length
            : tab.key === 'quizzes' ? quizzes.length
            : tab.key === 'assignments' ? assignments.length
            : tab.key === 'coding' ? codingProblems.length
            : tab.key === 'notebooks' ? notebooks.length
            : tab.key === 'live' ? liveClasses.length
            : 0
          // Hide categories that have no content (keep "All" always visible).
          if (tab.key !== 'all' && count === 0) return null
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
              <span className="text-xs bg-surface-200 dark:bg-surface-600 px-1.5 py-0.5 rounded-full">
                {count}
              </span>
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
          {activeTab === 'all' && <AllTab reading={reading} videos={videos} quizzes={quizzes} assignments={assignments} coding={codingProblems} labs={notebooks} live={liveClasses} navigate={navigate} quizNavState={quizNavState} />}
          {activeTab === 'reading' && <ReadingTab items={reading} navigate={navigate} />}
          {activeTab === 'videos' && <VideosTab items={videos} navigate={navigate} />}
          {activeTab === 'quizzes' && <QuizzesTab items={quizzes} navigate={navigate} quizNavState={quizNavState} />}
          {activeTab === 'assignments' && <AssignmentsTab items={assignments} navigate={navigate} />}
          {activeTab === 'coding' && <CodingTab items={codingProblems} navigate={navigate} />}
          {activeTab === 'notebooks' && <NotebooksTab items={notebooks} navigate={navigate} />}
          {activeTab === 'live' && <LiveTab items={liveClasses} />}
        </motion.div>
      </AnimatePresence>
    </div>
  )
}

// ── Tab components ───────────────────────────────────────────────────────

const EmptyState = ({ icon: Icon, message }) => (
  <div className="text-center py-12 text-surface-500">
    <Icon size={48} className="mx-auto mb-3 text-surface-300" />
    <p>{message}</p>
  </div>
)

// Shared type metadata for the unified list view
const READ_TYPE = {
  notes: { icon: FileText, color: 'bg-blue-50 text-blue-600 dark:bg-blue-900/30', label: 'Notes' },
  pdf: { icon: FileText, color: 'bg-green-50 text-green-600 dark:bg-green-900/30', label: 'PDF' },
  revision: { icon: RefreshCw, color: 'bg-purple-50 text-purple-600 dark:bg-purple-900/30', label: 'Revision' },
  formula: { icon: BarChart3, color: 'bg-amber-50 text-amber-600 dark:bg-amber-900/30', label: 'Formulas' },
}

const PRACTICE_CFG = { icon: ClipboardList, color: 'bg-orange-50 text-orange-600 dark:bg-orange-900/30', label: 'Practice' }

// Resolve the tile config for a reading item, accounting for practice-question material.
const readingCfg = (item) =>
  item.material_kind === 'practice' ? PRACTICE_CFG : (READ_TYPE[item.content_type] || READ_TYPE.notes)

const StatusPill = ({ tone, icon: Icon, label }) => {
  const tones = {
    success: 'bg-success-50 text-success-700 dark:bg-success-900/30 dark:text-success-300',
    progress: 'bg-primary-50 text-primary-700 dark:bg-primary-900/30 dark:text-primary-300',
    score: 'bg-warning-50 text-warning-700 dark:bg-warning-900/30 dark:text-warning-300',
    idle: 'bg-surface-100 text-surface-500 dark:bg-surface-700 dark:text-surface-400',
  }
  return (
    <span className={`inline-flex items-center gap-1 text-[11px] font-medium px-2.5 py-1 rounded-full whitespace-nowrap ${tones[tone]}`}>
      {Icon && <Icon size={12} />}
      {label}
    </span>
  )
}

const assignmentStatus = (a) => {
  const sub = a.my_submission
  if (sub && sub.status === 'graded') {
    const marks = sub.marks != null ? `${sub.marks}${a.max_marks ? `/${a.max_marks}` : ''}` : 'Graded'
    return { tone: 'score', icon: Trophy, label: marks }
  }
  if (sub) return { tone: 'progress', icon: CheckCircle2, label: 'Submitted' }
  if (!a.is_open) return { tone: 'idle', icon: Lock, label: 'Closed' }
  if (a.is_timed && a.due_at) return { tone: 'idle', icon: Clock, label: 'Due ' + new Date(a.due_at).toLocaleDateString() }
  return { tone: 'idle', icon: Circle, label: 'Not submitted' }
}

const codingStatus = (p) => {
  const b = p.my_best
  if (b && b.all_passed) return { tone: 'score', icon: Trophy, label: 'Solved' }
  if (b) return { tone: 'progress', icon: CheckCircle2, label: `${b.passed_count}/${b.total_count}` }
  return { tone: 'idle', icon: Circle, label: 'Not attempted' }
}

const liveStatus = (l) => {
  if (l.live_status === 'live') return { tone: 'score', icon: Radio, label: 'Live now' }
  if (l.live_status === 'ended') return { tone: 'idle', icon: CheckCircle2, label: 'Ended' }
  const when = l.scheduled_start ? new Date(l.scheduled_start).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : 'TBA'
  return { tone: 'progress', icon: Clock, label: when }
}

// Open a live class's join link (Google Meet) in a new tab.
const openLive = (l) => {
  if (l.meeting_url) window.open(l.meeting_url, '_blank', 'noopener,noreferrer')
}

const labStatus = (n) => {
  const best = n.my_best
  if (n.is_complete) return { tone: 'score', icon: Trophy, label: 'Completed' }
  if (best) {
    return {
      tone: 'progress',
      icon: CheckCircle2,
      label: `${best.passed_points}/${best.total_points}`,
    }
  }
  return { tone: 'idle', icon: Circle, label: 'Not started' }
}

const AllTab = ({ reading, videos, quizzes, assignments = [], coding = [], labs = [], live = [], navigate, quizNavState }) => {
  // An "editorial" note shares its exact title with a coding problem in this
  // topic (our authoring convention). We lift those notes out of the reading
  // block and place each one immediately before its problem, so the flow reads
  // concept note → quizzes → (editorial + problem) pairs. Notes with no matching
  // problem stay in the reading block, so topics without this pairing are
  // unaffected.
  const norm = (s) => (s || '').trim().toLowerCase()
  const codingTitles = new Set(coding.map(c => norm(c.title)))
  const editorialByTitle = {}
  reading.forEach(r => {
    if (r.content_type !== 'video' && codingTitles.has(norm(r.title))) {
      editorialByTitle[norm(r.title)] = r
    }
  })

  // Reading + videos share a real `order`; interleave them. Editorial notes are
  // excluded here — they travel with their coding problem below.
  const materials = [...reading.filter(r => !editorialByTitle[norm(r.title)]), ...videos]
    .map(item => ({ ...item, _kind: item.content_type === 'video' ? 'video' : 'reading' }))
    .sort((a, b) => (a.order ?? 0) - (b.order ?? 0))

  const codingRows = coding.flatMap(c => {
    const editorial = editorialByTitle[norm(c.title)]
    const pair = []
    if (editorial) pair.push({ ...editorial, _kind: 'reading' })
    pair.push({ ...c, _kind: 'coding' })
    return pair
  })

  const rows = [
    ...materials,
    ...quizzes.map(q => ({ ...q, _kind: 'quiz' })),
    ...assignments.map(a => ({ ...a, _kind: 'assignment' })),
    ...codingRows,
    ...labs.map(n => ({ ...n, _kind: 'lab' })),
    ...live.map(l => ({ ...l, _kind: 'live' })),
  ]

  if (rows.length === 0) {
    return <EmptyState icon={LayoutList} message="No content has been added to this topic yet" />
  }

  return (
    <div className="card divide-y divide-surface-100 dark:divide-surface-700 overflow-hidden">
      {rows.map((item, idx) => {
        const isQuiz = item._kind === 'quiz'
        const isVideo = item._kind === 'video'
        const isAssignment = item._kind === 'assignment'
        const isCoding = item._kind === 'coding'
        const isLab = item._kind === 'lab'
        const isLive = item._kind === 'live'

        let cfg
        if (isQuiz) cfg = { icon: PenTool, color: 'bg-green-50 text-green-600 dark:bg-green-900/30', label: 'Quiz' }
        else if (isVideo) cfg = { icon: PlayCircle, color: 'bg-red-50 text-red-600 dark:bg-red-900/30', label: 'Video' }
        else if (isAssignment) cfg = { icon: ClipboardList, color: 'bg-indigo-50 text-indigo-600 dark:bg-indigo-900/30', label: 'Assignment' }
        else if (isCoding) cfg = { icon: Code2, color: 'bg-primary-50 text-primary-600 dark:bg-primary-900/30', label: 'Coding' }
        else if (isLab) cfg = { icon: NotebookIcon, color: 'bg-indigo-50 text-indigo-600 dark:bg-indigo-900/30', label: 'Lab' }
        else if (isLive) cfg = { icon: Radio, color: 'bg-red-50 text-red-600 dark:bg-red-900/30', label: 'Live class' }
        else cfg = readingCfg(item)
        const Icon = cfg.icon

        // Status
        let status
        if (isQuiz) {
          status = item.attempts_count > 0
            ? <StatusPill tone="score" icon={Trophy} label={`Best ${Math.round(item.best_score)}%`} />
            : <StatusPill tone="idle" icon={Circle} label="Not attempted" />
        } else if (isAssignment) {
          const s = assignmentStatus(item)
          status = <StatusPill tone={s.tone} icon={s.icon} label={s.label} />
        } else if (isCoding) {
          const s = codingStatus(item)
          status = <StatusPill tone={s.tone} icon={s.icon} label={s.label} />
        } else if (isLab) {
          const s = labStatus(item)
          status = <StatusPill tone={s.tone} icon={s.icon} label={s.label} />
        } else if (isLive) {
          const s = liveStatus(item)
          status = <StatusPill tone={s.tone} icon={s.icon} label={s.label} />
        } else if (item.is_completed) {
          status = <StatusPill tone="success" icon={CheckCircle2} label={isVideo ? 'Watched' : 'Completed'} />
        } else if (isVideo && item.progress_percentage > 0) {
          status = <StatusPill tone="progress" icon={PlayCircle} label={`${Math.round(item.progress_percentage)}%`} />
        } else {
          status = <StatusPill tone="idle" icon={Circle} label="Not started" />
        }

        // Meta line
        const meta = []
        if (isQuiz) {
          meta.push(`${item.total_questions} Qs`)
          if (item.duration_minutes) meta.push(`${item.duration_minutes}m`)
          if (item.attempts_count > 0) meta.push(`${item.attempts_count} attempt${item.attempts_count > 1 ? 's' : ''}`)
        } else if (isVideo) {
          if (item.video_duration_minutes) meta.push(`${item.video_duration_minutes} min`)
          meta.push(`${item.views_count || 0} views`)
        } else if (isAssignment) {
          meta.push(item.is_timed ? 'Timed' : 'No deadline')
          if (item.max_marks) meta.push(`${item.max_marks} marks`)
        } else if (isCoding) {
          if (item.difficulty) meta.push(item.difficulty)
          if (item.max_marks) meta.push(`${item.max_marks} marks`)
        } else if (isLab) {
          if (item.difficulty) meta.push(item.difficulty)
          if (item.max_marks) meta.push(`${item.max_marks} marks`)
          if (item.estimated_time_minutes) meta.push(`${item.estimated_time_minutes} min`)
        } else if (isLive) {
          meta.push(item.provider_display || 'Google Meet')
          if (item.duration_minutes) meta.push(`${item.duration_minutes} min`)
        } else {
          if (item.estimated_time_minutes) meta.push(`${item.estimated_time_minutes} min read`)
        }

        const onClick = () => {
          if (isQuiz) navigate(`/quiz/${item.id}`, { state: quizNavState })
          else if (isAssignment) navigate(`/assignment/${item.id}`)
          else if (isCoding) navigate(`/coding/${item.id}`)
          else if (isLab) navigate(`/notebooks/${item.id}`)
          else if (isLive) openLive(item)
          else navigate(`/content/${item.id}`)
        }

        return (
          <motion.button
            key={`${item._kind}-${item.id}`}
            onClick={onClick}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: idx * 0.02 }}
            className="w-full flex items-center gap-3 sm:gap-4 px-3 sm:px-4 py-3.5 text-left hover:bg-surface-50 dark:hover:bg-surface-800/60 transition-colors group"
          >
            <span className="hidden sm:flex w-6 shrink-0 justify-center text-xs font-medium text-surface-400 tabular-nums">
              {idx + 1}
            </span>
            <span className={`w-10 h-10 shrink-0 rounded-xl flex items-center justify-center ${cfg.color}`}>
              <Icon size={20} />
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <h4 className="font-medium text-sm truncate">{item.title}</h4>
                {item.is_bookmarked && <Bookmark size={13} className="shrink-0 text-warning-500 fill-warning-500" />}
              </div>
              <div className="flex items-center gap-2 mt-1 text-[11px] text-surface-400">
                <span className="font-medium text-surface-500">{cfg.label}</span>
                {meta.length > 0 && <span className="text-surface-300">•</span>}
                <span className="truncate flex items-center gap-1"><Clock size={10} /> {meta.join(' · ')}</span>
              </div>
            </div>
            {status}
            <ChevronRight size={18} className="shrink-0 text-surface-300 group-hover:text-primary-500 transition-colors" />
          </motion.button>
        )
      })}
    </div>
  )
}

// Uniform grid + tile shared by all tabs so every card is the same size.
const TILE_GRID = 'grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4'

const Tile = ({ icon: Icon, iconColor, label, title, meta, onClick, completed, bookmarked, badge, action }) => (
  <motion.div
    whileHover={{ y: -4 }}
    onClick={onClick}
    className={`card p-4 cursor-pointer transition-all relative overflow-hidden h-full flex flex-col ${
      completed ? 'border-success-200 dark:border-success-800' : 'hover:border-primary-200 hover:shadow-md'
    }`}
  >
    <div className="absolute top-2 right-2 flex items-center gap-1">
      {badge}
      {completed && <CheckCircle2 size={18} className="text-success-500" />}
    </div>
    {bookmarked && (
      <div className="absolute top-2 left-2">
        <Bookmark size={14} className="text-warning-500 fill-warning-500" />
      </div>
    )}
    <div className={`w-12 h-12 rounded-xl flex items-center justify-center mb-3 ${iconColor}`}>
      <Icon size={24} />
    </div>
    <h4 className="font-medium text-sm leading-snug line-clamp-2 mb-1.5">{title}</h4>
    <div className="flex items-center justify-between gap-2 mt-auto pt-2 border-t border-surface-100 dark:border-surface-700">
      <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-surface-100 dark:bg-surface-700 text-surface-500 shrink-0">
        {label}
      </span>
      {meta && (
        <span className="text-[10px] text-surface-400 flex items-center gap-1 truncate">
          {meta}
        </span>
      )}
    </div>
    {action}
  </motion.div>
)

const ReadingCard = ({ item, navigate }) => {
  const cfg = readingCfg(item)
  return (
    <Tile
      icon={cfg.icon}
      iconColor={cfg.color}
      label={cfg.label}
      title={item.title}
      meta={<><Clock size={10} /> {item.estimated_time_minutes}m</>}
      completed={item.is_completed}
      bookmarked={item.is_bookmarked}
      onClick={() => navigate(`/content/${item.id}`)}
    />
  )
}

const ReadingSection = ({ icon: Icon, title, items, navigate }) => {
  if (items.length === 0) return null
  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <Icon size={16} className="text-surface-400" />
        <h3 className="text-sm font-semibold text-surface-600 dark:text-surface-300">{title}</h3>
        <span className="text-xs bg-surface-100 dark:bg-surface-700 text-surface-500 px-1.5 py-0.5 rounded-full">
          {items.length}
        </span>
      </div>
      <div className={TILE_GRID}>
        {items.map((item) => <ReadingCard key={item.id} item={item} navigate={navigate} />)}
      </div>
    </div>
  )
}

const ReadingTab = ({ items, navigate }) => {
  if (items.length === 0) {
    return <EmptyState icon={BookOpen} message="No reading materials available yet" />
  }
  const study = items.filter((i) => i.material_kind !== 'practice')
  const practice = items.filter((i) => i.material_kind === 'practice')

  // If everything is one kind, don't show redundant section headers.
  if (study.length === 0 || practice.length === 0) {
    return (
      <div className={TILE_GRID}>
        {items.map((item) => <ReadingCard key={item.id} item={item} navigate={navigate} />)}
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <ReadingSection icon={BookOpen} title="Notes & material" items={study} navigate={navigate} />
      <ReadingSection icon={ClipboardList} title="Practice questions" items={practice} navigate={navigate} />
    </div>
  )
}

const VideosTab = ({ items, navigate }) => {
  if (items.length === 0) {
    return <EmptyState icon={PlayCircle} message="No videos available yet" />
  }
  return (
    <div className={TILE_GRID}>
      {items.map((item) => {
        const inProgress = !item.is_completed && item.progress_percentage > 0
        return (
          <Tile
            key={item.id}
            icon={PlayCircle}
            iconColor="bg-red-50 text-red-600 dark:bg-red-900/30"
            label="Video"
            title={item.title}
            meta={
              item.video_duration_minutes
                ? <><Clock size={10} /> {item.video_duration_minutes}m</>
                : <><Eye size={10} /> {item.views_count || 0}</>
            }
            completed={item.is_completed}
            badge={inProgress && (
              <span className="text-[10px] font-semibold text-primary-600 bg-primary-50 dark:bg-primary-900/30 px-1.5 py-0.5 rounded-full">
                {Math.round(item.progress_percentage)}%
              </span>
            )}
            onClick={() => navigate(`/content/${item.id}`)}
          />
        )
      })}
    </div>
  )
}

const QuizzesTab = ({ items, navigate, quizNavState }) => {
  if (items.length === 0) {
    return <EmptyState icon={PenTool} message="No practice quizzes available yet" />
  }
  return (
    <div className={TILE_GRID}>
      {items.map((quiz) => {
        const attempted = quiz.attempts_count > 0
        return (
          <Tile
            key={quiz.id}
            icon={PenTool}
            iconColor={attempted
              ? 'bg-primary-50 text-primary-600 dark:bg-primary-900/30'
              : 'bg-green-50 text-green-600 dark:bg-green-900/30'}
            label="Quiz"
            title={quiz.title}
            meta={<>{quiz.total_questions} Qs · <Clock size={10} /> {quiz.duration_minutes}m</>}
            badge={attempted && (
              <span className="flex items-center gap-0.5 text-[11px] font-bold text-warning-600">
                <Star size={12} className="text-warning-500 fill-warning-500" />
                {Math.round(quiz.best_score)}%
              </span>
            )}
            onClick={() => navigate(`/quiz/${quiz.id}`, { state: quizNavState })}
            action={
              <div className="flex gap-2 mt-3">
                <button
                  onClick={(e) => { e.stopPropagation(); navigate(`/quiz/${quiz.id}`, { state: quizNavState }) }}
                  className="flex-1 btn-primary text-xs py-1.5"
                >
                  {attempted ? 'Retry' : 'Start'}
                </button>
                {attempted && quiz.last_attempt && (
                  <button
                    onClick={(e) => { e.stopPropagation(); navigate(`/quiz/review/${quiz.last_attempt.id}`, { state: quizNavState }) }}
                    className="flex-1 btn-outline text-xs py-1.5"
                  >
                    Review
                  </button>
                )}
              </div>
            }
          />
        )
      })}
    </div>
  )
}

const AssignmentsTab = ({ items, navigate }) => {
  if (items.length === 0) {
    return <EmptyState icon={ClipboardList} message="No assignments have been added yet" />
  }
  return (
    <div className={TILE_GRID}>
      {items.map((a) => {
        const s = assignmentStatus(a)
        const graded = a.my_submission?.status === 'graded'
        const submitted = !!a.my_submission
        return (
          <Tile
            key={a.id}
            icon={ClipboardList}
            iconColor={submitted
              ? 'bg-primary-50 text-primary-600 dark:bg-primary-900/30'
              : 'bg-indigo-50 text-indigo-600 dark:bg-indigo-900/30'}
            label="Assignment"
            title={a.title}
            meta={a.is_timed
              ? <><Clock size={10} /> {a.due_at ? new Date(a.due_at).toLocaleDateString() : 'Timed'}</>
              : <>No deadline</>}
            completed={submitted}
            badge={graded
              ? (
                <span className="flex items-center gap-0.5 text-[11px] font-bold text-warning-600">
                  <Star size={12} className="text-warning-500 fill-warning-500" />
                  {a.my_submission.marks != null ? a.my_submission.marks : ''}{a.max_marks ? `/${a.max_marks}` : ''}
                </span>
              )
              : (!a.is_open && !submitted && (
                <span className="flex items-center gap-0.5 text-[10px] font-semibold text-surface-400">
                  <Lock size={11} /> Closed
                </span>
              ))}
            onClick={() => navigate(`/assignment/${a.id}`)}
            action={
              <div className="mt-3">
                <button
                  onClick={(e) => { e.stopPropagation(); navigate(`/assignment/${a.id}`) }}
                  className={`w-full text-xs py-1.5 ${submitted || !a.is_open ? 'btn-outline' : 'btn-primary'}`}
                >
                  {graded ? 'View feedback' : submitted ? 'View submission' : a.is_open ? 'Start' : 'View'}
                </button>
              </div>
            }
          />
        )
      })}
    </div>
  )
}

const NotebooksTab = ({ items, navigate }) => {
  if (items.length === 0) {
    return <EmptyState icon={NotebookIcon} message="No labs have been added yet" />
  }
  return (
    <div className={TILE_GRID}>
      {items.map((n) => {
        const attempted = !!n.my_best
        const done = n.is_complete
        return (
          <Tile
            key={n.id}
            icon={NotebookIcon}
            iconColor={attempted
              ? 'bg-indigo-50 text-indigo-600 dark:bg-indigo-900/30'
              : 'bg-blue-50 text-blue-600 dark:bg-blue-900/30'}
            label="Lab"
            title={n.title}
            meta={<>{n.difficulty || 'lab'}{n.max_marks ? ` \u00b7 ${n.max_marks} marks` : ''}{n.estimated_time_minutes ? ` \u00b7 ${n.estimated_time_minutes} min` : ''}</>}
            completed={done}
            badge={attempted && (
              <span className={`flex items-center gap-0.5 text-[11px] font-bold ${done ? 'text-success-600' : 'text-warning-600'}`}>
                {done ? <CheckCircle2 size={12} /> : <Star size={12} className="text-warning-500" />}
                {n.my_best.passed_points}/{n.my_best.total_points}
              </span>
            )}
            onClick={() => navigate(`/notebooks/${n.id}`)}
            action={
              <div className="mt-3">
                <button
                  onClick={(e) => { e.stopPropagation(); navigate(`/notebooks/${n.id}`) }}
                  className={`w-full text-xs py-1.5 ${attempted ? 'btn-outline' : 'btn-primary'}`}
                >
                  {done ? 'Review' : attempted ? 'Continue' : 'Open'}
                </button>
              </div>
            }
          />
        )
      })}
    </div>
  )
}

const CodingTab = ({ items, navigate }) => {
  if (items.length === 0) {
    return <EmptyState icon={Code2} message="No coding problems have been added yet" />
  }
  return (
    <div className={TILE_GRID}>
      {items.map((p) => {
        const s = codingStatus(p)
        const solved = p.my_best?.all_passed
        const attempted = !!p.my_best
        return (
          <Tile
            key={p.id}
            icon={Code2}
            iconColor={attempted
              ? 'bg-primary-50 text-primary-600 dark:bg-primary-900/30'
              : 'bg-blue-50 text-blue-600 dark:bg-blue-900/30'}
            label="Coding"
            title={p.title}
            meta={<>{p.difficulty || 'coding'}{p.max_marks ? ` · ${p.max_marks} marks` : ''}</>}
            completed={solved}
            badge={attempted && (
              <span className={`flex items-center gap-0.5 text-[11px] font-bold ${solved ? 'text-success-600' : 'text-warning-600'}`}>
                {solved ? <CheckCircle2 size={12} /> : <Star size={12} className="text-warning-500" />}
                {p.my_best.passed_count}/{p.my_best.total_count}
              </span>
            )}
            onClick={() => navigate(`/coding/${p.id}`)}
            action={
              <div className="mt-3">
                <button
                  onClick={(e) => { e.stopPropagation(); navigate(`/coding/${p.id}`) }}
                  className={`w-full text-xs py-1.5 ${attempted ? 'btn-outline' : 'btn-primary'}`}
                >
                  {solved ? 'Review' : attempted ? 'Continue' : 'Solve'}
                </button>
              </div>
            }
          />
        )
      })}
    </div>
  )
}

const LiveTab = ({ items }) => {
  if (items.length === 0) {
    return <EmptyState icon={Radio} message="No live classes have been scheduled yet" />
  }
  return (
    <div className={TILE_GRID}>
      {items.map((l) => {
        const s = liveStatus(l)
        const isLive = l.live_status === 'live'
        const ended = l.live_status === 'ended'
        return (
          <Tile
            key={l.id}
            icon={Radio}
            iconColor={isLive
              ? 'bg-red-50 text-red-600 dark:bg-red-900/30'
              : 'bg-blue-50 text-blue-600 dark:bg-blue-900/30'}
            label={l.provider_display || 'Google Meet'}
            title={l.title}
            meta={<>{s.label}{l.duration_minutes ? ` · ${l.duration_minutes} min` : ''}</>}
            badge={isLive && (
              <span className="flex items-center gap-0.5 text-[11px] font-bold text-red-600">
                <Radio size={12} /> Live
              </span>
            )}
            onClick={() => openLive(l)}
            action={
              <div className="mt-3">
                <button
                  onClick={(e) => { e.stopPropagation(); openLive(l) }}
                  disabled={ended || !l.meeting_url}
                  className={`w-full text-xs py-1.5 ${isLive ? 'btn-primary' : 'btn-outline'} ${(ended || !l.meeting_url) ? 'opacity-50 cursor-not-allowed' : ''}`}
                >
                  {ended ? 'Ended' : isLive ? 'Join now' : 'Join'}
                </button>
              </div>
            }
          />
        )
      })}
    </div>
  )
}

export default StudyTopicContent
