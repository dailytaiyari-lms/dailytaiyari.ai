import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  AlertTriangle,
  BookOpen,
  Check,
  ChevronDown,
  Copy,
  GraduationCap,
  ListChecks,
  Loader2,
  Maximize2,
  MessageSquarePlus,
  Minimize2,
  PanelLeftClose,
  PanelLeftOpen,
  Search,
  Send,
  Sparkles,
  Square,
  Target,
  ThumbsDown,
  ThumbsUp,
  Trash2,
  TrendingUp,
  X,
} from 'lucide-react'

import { chatService } from '../services/chatService'
import { useAuthStore } from '../context/authStore'
import { useFeatureLabel } from '../context/tenantStore'
import MathRenderer from '../components/chat/MathRenderer'
import ChatQuiz from '../components/chat/ChatQuiz'
import { looksLikeQuiz, parseQuizFromMessage } from '../components/chat/quizParser'

/* ---------------------------------------------------------------------------
 * Small helpers
 * ------------------------------------------------------------------------- */

// Icons for the backend-generated starter prompts, keyed by their `kind`.
const PROMPT_ICONS = {
  progress: TrendingUp,
  pending: ListChecks,
  mistakes: Target,
  quiz: GraduationCap,
  plan: BookOpen,
  idea: Sparkles,
}

const greeting = () => {
  const h = new Date().getHours()
  if (h < 12) return 'Good morning'
  if (h < 17) return 'Good afternoon'
  return 'Good evening'
}

// Groups conversations the way ChatGPT/Claude do, so long histories stay scannable.
const groupSessions = (sessions) => {
  const now = new Date()
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const startOfYesterday = new Date(startOfToday.getTime() - 86400000)
  const weekAgo = new Date(startOfToday.getTime() - 7 * 86400000)

  const groups = { Today: [], Yesterday: [], 'Previous 7 days': [], Older: [] }
  sessions.forEach((s) => {
    const when = new Date(s.updated_at || s.created_at)
    if (when >= startOfToday) groups.Today.push(s)
    else if (when >= startOfYesterday) groups.Yesterday.push(s)
    else if (when >= weekAgo) groups['Previous 7 days'].push(s)
    else groups.Older.push(s)
  })
  return Object.entries(groups).filter(([, items]) => items.length > 0)
}

/* ---------------------------------------------------------------------------
 * Course selector
 * ------------------------------------------------------------------------- */

/**
 * Scopes the conversation to one enrolled course. Once selected, the backend
 * feeds the AI that course's syllabus and the student's own progress, so it can
 * answer "what's pending?", "where am I weak?" and course-specific doubts.
 */
const CourseSelector = ({ courses, value, onChange, compact = false }) => {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    const onClickAway = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', onClickAway)
    return () => document.removeEventListener('mousedown', onClickAway)
  }, [])

  const selected = courses.find((c) => c.id === value)

  if (!courses.length) return null

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={`inline-flex items-center gap-2 rounded-full border transition-colors ${compact ? 'px-3 py-1.5 text-xs' : 'px-4 py-2 text-sm'
          } ${selected
            ? 'border-primary-300 dark:border-primary-700 bg-primary-50 dark:bg-primary-900/25 text-primary-700 dark:text-primary-300'
            : 'border-surface-200 dark:border-surface-700 text-surface-600 dark:text-surface-300 hover:border-surface-300 dark:hover:border-surface-600'
          }`}
      >
        <BookOpen className={compact ? 'w-3.5 h-3.5' : 'w-4 h-4'} />
        <span className="font-medium max-w-[180px] truncate">
          {selected ? selected.name : 'All courses'}
        </span>
        <ChevronDown className={`${compact ? 'w-3 h-3' : 'w-3.5 h-3.5'} opacity-60`} />
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -4, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, scale: 0.98 }}
            transition={{ duration: 0.12 }}
            className="absolute z-30 mt-2 w-72 rounded-2xl border border-surface-200 dark:border-surface-700 bg-white dark:bg-surface-900 shadow-xl p-1.5"
          >
            <p className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-surface-400">
              Answer using my course data
            </p>
            <button
              type="button"
              onClick={() => {
                onChange(null)
                setOpen(false)
              }}
              className="w-full flex items-center justify-between gap-2 px-3 py-2.5 rounded-xl text-sm hover:bg-surface-100 dark:hover:bg-surface-800 text-left"
            >
              <span>
                <span className="font-medium text-surface-900 dark:text-white">All courses</span>
                <span className="block text-xs text-surface-500">General doubts, no progress data</span>
              </span>
              {!value && <Check className="w-4 h-4 text-primary-500 shrink-0" />}
            </button>
            {courses.map((course) => (
              <button
                key={course.id}
                type="button"
                onClick={() => {
                  onChange(course.id)
                  setOpen(false)
                }}
                className="w-full flex items-center justify-between gap-2 px-3 py-2.5 rounded-xl text-sm hover:bg-surface-100 dark:hover:bg-surface-800 text-left"
              >
                <span className="flex items-center gap-2.5 min-w-0">
                  <span
                    className="w-2.5 h-2.5 rounded-full shrink-0"
                    style={{ backgroundColor: course.color || '#6366f1' }}
                  />
                  <span className="min-w-0">
                    <span className="font-medium text-surface-900 dark:text-white block truncate">
                      {course.name}
                    </span>
                    <span className="block text-xs text-surface-500">{course.course_type}</span>
                  </span>
                </span>
                {value === course.id && <Check className="w-4 h-4 text-primary-500 shrink-0" />}
              </button>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

/* ---------------------------------------------------------------------------
 * Conversation list
 * ------------------------------------------------------------------------- */

const ConversationList = ({
  sessions,
  activeSession,
  onSelect,
  onNewChat,
  onDelete,
  isLoading,
}) => {
  const [query, setQuery] = useState('')

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return sessions
    return sessions.filter((s) => (s.title || '').toLowerCase().includes(q))
  }, [sessions, query])

  const grouped = useMemo(() => groupSessions(filtered), [filtered])

  return (
    <div className="h-full flex flex-col bg-surface-50 dark:bg-surface-950/60">
      <div className="p-3 space-y-3">
        <button
          onClick={onNewChat}
          className="w-full inline-flex items-center gap-2 px-3.5 py-2.5 rounded-xl border border-surface-200 dark:border-surface-700 bg-white dark:bg-surface-900 hover:border-primary-300 dark:hover:border-primary-700 hover:bg-primary-50/50 dark:hover:bg-primary-900/10 transition-colors text-sm font-semibold text-surface-800 dark:text-surface-100"
        >
          <MessageSquarePlus className="w-4 h-4 text-primary-500" />
          New chat
        </button>

        {sessions.length > 4 && (
          <div className="relative">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-surface-400" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search chats"
              className="w-full pl-9 pr-3 py-2 text-sm rounded-xl bg-white dark:bg-surface-900 border border-surface-200 dark:border-surface-800 focus:outline-none focus:ring-2 focus:ring-primary-500/40"
            />
          </div>
        )}
      </div>

      <div className="flex-1 overflow-y-auto px-2 pb-3">
        {isLoading ? (
          <div className="flex justify-center py-8">
            <Loader2 className="w-5 h-5 animate-spin text-surface-400" />
          </div>
        ) : grouped.length === 0 ? (
          <p className="text-center text-sm text-surface-400 py-8 px-3">
            {query ? 'No chats match your search.' : 'Your conversations will appear here.'}
          </p>
        ) : (
          grouped.map(([label, items]) => (
            <div key={label} className="mb-4">
              <p className="px-3 pb-1.5 text-[11px] font-semibold uppercase tracking-wide text-surface-400">
                {label}
              </p>
              <div className="space-y-0.5">
                {items.map((session) => {
                  const active = activeSession === session.id
                  return (
                    <div
                      key={session.id}
                      className={`group relative rounded-xl transition-colors ${active
                        ? 'bg-white dark:bg-surface-800 shadow-sm'
                        : 'hover:bg-white/70 dark:hover:bg-surface-800/60'
                        }`}
                    >
                      <button
                        onClick={() => onSelect(session.id)}
                        className="w-full text-left px-3 py-2.5 pr-9"
                      >
                        <p
                          className={`text-sm truncate ${active
                            ? 'font-semibold text-surface-900 dark:text-white'
                            : 'text-surface-700 dark:text-surface-300'
                            }`}
                        >
                          {session.title || 'New chat'}
                        </p>
                        {session.course_name && (
                          <p className="text-[11px] text-surface-400 truncate mt-0.5">
                            {session.course_name}
                          </p>
                        )}
                      </button>
                      <button
                        onClick={() => onDelete(session)}
                        title="Delete chat"
                        className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 rounded-lg text-surface-400 opacity-0 group-hover:opacity-100 focus:opacity-100 hover:text-rose-500 hover:bg-rose-50 dark:hover:bg-rose-900/20 transition-all"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  )
                })}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}

/* ---------------------------------------------------------------------------
 * Message rendering
 * ------------------------------------------------------------------------- */

const AssistantAvatar = () => (
  <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-primary-500 to-primary-600 flex items-center justify-center shrink-0 shadow-sm shadow-primary-500/25">
    <Sparkles className="w-4 h-4 text-white" />
  </div>
)

const TypingDots = () => (
  <div className="flex items-center gap-1.5 h-6">
    {[0, 150, 300].map((delay) => (
      <span
        key={delay}
        className="w-1.5 h-1.5 rounded-full bg-primary-500/70 animate-bounce"
        style={{ animationDelay: `${delay}ms` }}
      />
    ))}
  </div>
)

const AssistantMessage = ({ content, isStreaming, sessionId, onCopy, onFeedback, messageId }) => {
  const [copied, setCopied] = useState(false)
  const [feedback, setFeedback] = useState(null)

  // While streaming we deliberately avoid the quiz parser: it would reveal the
  // correct answers as the model types them out.
  if (isStreaming) {
    return (
      <div className="text-[15px] leading-relaxed text-surface-800 dark:text-surface-200">
        {looksLikeQuiz(content) ? (
          <div className="flex items-center gap-3 rounded-xl border border-primary-200 dark:border-primary-800 bg-primary-50/60 dark:bg-primary-900/20 px-4 py-3">
            <Loader2 className="w-4 h-4 animate-spin text-primary-500" />
            <div>
              <p className="text-sm font-medium text-surface-800 dark:text-surface-100">
                Building your practice quiz…
              </p>
              <p className="text-xs text-surface-500">Answers stay hidden until it's ready.</p>
            </div>
          </div>
        ) : (
          <>
            <MathRenderer content={content} />
            <span className="inline-block w-1.5 h-4 bg-primary-500 animate-pulse ml-0.5 align-middle" />
          </>
        )}
      </div>
    )
  }

  const quizData = parseQuizFromMessage(content)

  const copy = () => {
    navigator.clipboard.writeText(content)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
    onCopy?.()
  }

  const rate = (helpful) => {
    setFeedback(helpful)
    onFeedback?.(messageId, helpful)
  }

  return (
    <div className="group">
      <div className="text-[15px] leading-relaxed text-surface-800 dark:text-surface-200">
        {quizData ? (
          <div className="space-y-4">
            {quizData.remainingContent && <MathRenderer content={quizData.remainingContent} />}
            <ChatQuiz quiz={quizData.quiz} sessionId={sessionId} />
          </div>
        ) : (
          <MathRenderer content={content} />
        )}
      </div>

      {messageId && (
        <div className="flex items-center gap-1 mt-2 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity">
          <button
            onClick={copy}
            title="Copy"
            className="p-1.5 rounded-lg text-surface-400 hover:text-surface-700 dark:hover:text-surface-200 hover:bg-surface-100 dark:hover:bg-surface-800"
          >
            {copied ? <Check className="w-3.5 h-3.5 text-emerald-500" /> : <Copy className="w-3.5 h-3.5" />}
          </button>
          <button
            onClick={() => rate(true)}
            title="Helpful"
            className={`p-1.5 rounded-lg hover:bg-surface-100 dark:hover:bg-surface-800 ${feedback === true ? 'text-emerald-500' : 'text-surface-400 hover:text-surface-700 dark:hover:text-surface-200'
              }`}
          >
            <ThumbsUp className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={() => rate(false)}
            title="Not helpful"
            className={`p-1.5 rounded-lg hover:bg-surface-100 dark:hover:bg-surface-800 ${feedback === false ? 'text-rose-500' : 'text-surface-400 hover:text-surface-700 dark:hover:text-surface-200'
              }`}
          >
            <ThumbsDown className="w-3.5 h-3.5" />
          </button>
        </div>
      )}
    </div>
  )
}

const UserMessage = ({ content }) => (
  <div className="flex justify-end">
    <div className="max-w-[85%] rounded-2xl rounded-br-md bg-primary-500 text-white px-4 py-2.5 shadow-sm shadow-primary-500/20">
      <p className="whitespace-pre-wrap text-sm leading-relaxed">{content}</p>
    </div>
  </div>
)

/* ---------------------------------------------------------------------------
 * Page
 * ------------------------------------------------------------------------- */

const AIDoubtSolver = () => {
  const queryClient = useQueryClient()
  const { profile } = useAuthStore()
  const aiLabel = useFeatureLabel('ai', 'AI Study Assistant')

  const [input, setInput] = useState('')
  const [activeSession, setActiveSession] = useState(null)
  const [courseId, setCourseId] = useState(null)
  const [isStreaming, setIsStreaming] = useState(false)
  const [streamingContent, setStreamingContent] = useState('')
  const [pendingUserMessage, setPendingUserMessage] = useState(null)
  const [showSidebar, setShowSidebar] = useState(true)
  const [mobileSidebar, setMobileSidebar] = useState(false)
  const [isFullscreen, setIsFullscreen] = useState(false)

  const scrollRef = useRef(null)
  const textareaRef = useRef(null)
  const abortStreamRef = useRef(false)

  const { data: sessions, isLoading: sessionsLoading } = useQuery({
    queryKey: ['chatSessions'],
    queryFn: () => chatService.getSessions(),
  })

  // Enrolled courses + progress-aware starter prompts + availability status.
  const { data: workspace } = useQuery({
    queryKey: ['chatWorkspace', courseId],
    queryFn: () => chatService.getWorkspace(courseId),
  })

  const { data: sessionData, refetch: refetchSession } = useQuery({
    queryKey: ['chatSession', activeSession],
    queryFn: () => chatService.getSession(activeSession),
    enabled: !!activeSession,
  })

  const createSessionMutation = useMutation({
    mutationFn: (data) => chatService.createSession(data),
    onSuccess: (data) => {
      setActiveSession(data.id)
      queryClient.invalidateQueries({ queryKey: ['chatSessions'] })
    },
  })

  const deleteSessionMutation = useMutation({
    mutationFn: (sessionId) => chatService.deleteSession(sessionId),
    onSuccess: (_data, sessionId) => {
      if (activeSession === sessionId) setActiveSession(null)
      queryClient.invalidateQueries({ queryKey: ['chatSessions'] })
      toast.success('Chat deleted')
    },
    onError: () => toast.error('Could not delete the chat'),
  })

  const courses = workspace?.courses || []
  const starters = workspace?.starter_prompts || []
  const aiAvailable = workspace?.is_available !== false

  const messages = sessionData?.messages || []
  const sessionsList = sessions?.results || sessions || []

  // The server echoes the user message back once it is persisted; drop our
  // optimistic copy so it never renders twice.
  const visibleMessages = pendingUserMessage
    ? messages.filter((m) => !(m.role === 'user' && m.content === pendingUserMessage.content))
    : messages

  const isEmpty = visibleMessages.length === 0 && !pendingUserMessage && !isStreaming

  const scrollToBottom = useCallback(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [])

  useEffect(() => {
    const t = setTimeout(scrollToBottom, 50)
    return () => clearTimeout(t)
  }, [visibleMessages.length, streamingContent, scrollToBottom])

  // Grow the composer with its content, up to a comfortable ceiling.
  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`
  }, [input])

  useEffect(() => {
    textareaRef.current?.focus()
  }, [activeSession])

  useEffect(() => {
    const onKeyDown = (e) => {
      if (e.key === 'Escape' && isFullscreen) setIsFullscreen(false)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [isFullscreen])

  // Keep the picker in sync when opening an older, course-scoped conversation.
  useEffect(() => {
    if (sessionData?.course) setCourseId(sessionData.course)
  }, [sessionData?.course])

  // A course can stop being selectable after it was picked (deactivated, or the
  // enrollment revoked). Drop the stale selection so the UI doesn't keep showing
  // a course the server will no longer accept.
  useEffect(() => {
    if (!workspace || !courseId) return
    if (!workspace.courses?.some((c) => c.id === courseId)) setCourseId(null)
  }, [workspace, courseId])

  const handleNewChat = () => {
    setActiveSession(null)
    setStreamingContent('')
    setPendingUserMessage(null)
    setInput('')
    setMobileSidebar(false)
    textareaRef.current?.focus()
  }

  const handleSelectCourse = async (nextCourseId) => {
    setCourseId(nextCourseId)
    if (activeSession) {
      try {
        await chatService.setSessionCourse(activeSession, nextCourseId)
        queryClient.invalidateQueries({ queryKey: ['chatSession', activeSession] })
        queryClient.invalidateQueries({ queryKey: ['chatSessions'] })
      } catch {
        toast.error('Could not switch the course for this chat')
      }
    }
  }

  const send = useCallback(
    async (text) => {
      const message = (text ?? input).trim()
      if (!message || isStreaming) return

      setInput('')
      setStreamingContent('')
      setIsStreaming(true)
      abortStreamRef.current = false
      setPendingUserMessage({ role: 'user', content: message })

      let sessionId = activeSession
      if (!sessionId) {
        try {
          const session = await createSessionMutation.mutateAsync({
            title: message.slice(0, 80),
            course_id: courseId || undefined,
          })
          sessionId = session.id
        } catch {
          toast.error('Could not start the conversation')
          setIsStreaming(false)
          setPendingUserMessage(null)
          return
        }
      }

      try {
        await chatService.sendMessageStream(
          sessionId,
          message,
          (_chunk, fullContent) => {
            if (!abortStreamRef.current) setStreamingContent(fullContent)
          },
          async () => {
            setIsStreaming(false)
            setStreamingContent('')
            setPendingUserMessage(null)
            await refetchSession()
            queryClient.invalidateQueries({ queryKey: ['chatSessions'] })
          },
          (error) => {
            setIsStreaming(false)
            setStreamingContent('')
            setPendingUserMessage(null)
            toast.error(error?.message || 'Could not get a response. Please try again.')
            refetchSession()
          },
        )
      } catch {
        setIsStreaming(false)
        setStreamingContent('')
        setPendingUserMessage(null)
        toast.error('Could not send your message')
      }
    },
    [input, activeSession, isStreaming, courseId, refetchSession, queryClient, createSessionMutation],
  )

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  const handleFeedback = async (messageId, isHelpful) => {
    try {
      await chatService.markHelpful(messageId, isHelpful)
      toast.success(isHelpful ? 'Thanks — glad it helped!' : 'Thanks for the feedback')
    } catch {
      toast.error('Could not send your feedback')
    }
  }

  const handleDeleteSession = (session) => {
    if (window.confirm(`Delete "${session.title || 'this chat'}"?`)) {
      deleteSessionMutation.mutate(session.id)
    }
  }

  const shellClasses = isFullscreen
    ? 'fixed inset-0 z-50 bg-white dark:bg-surface-900 flex overflow-hidden'
    : 'flex h-[calc(100vh-8rem)] lg:h-[calc(100vh-6rem)] overflow-hidden rounded-2xl border border-surface-200 dark:border-surface-800 bg-white dark:bg-surface-900 shadow-sm'

  const conversationList = (
    <ConversationList
      sessions={sessionsList}
      activeSession={activeSession}
      onSelect={(id) => {
        setActiveSession(id)
        setMobileSidebar(false)
      }}
      onNewChat={handleNewChat}
      onDelete={handleDeleteSession}
      isLoading={sessionsLoading}
    />
  )

  return (
    <div className={shellClasses}>
      {/* Desktop rail */}
      <AnimatePresence initial={false}>
        {showSidebar && (
          <motion.aside
            initial={{ width: 0, opacity: 0 }}
            animate={{ width: 272, opacity: 1 }}
            exit={{ width: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: 'easeInOut' }}
            className="hidden lg:block shrink-0 border-r border-surface-200 dark:border-surface-800 overflow-hidden"
          >
            <div className="w-[272px] h-full">{conversationList}</div>
          </motion.aside>
        )}
      </AnimatePresence>

      {/* Mobile drawer */}
      <AnimatePresence>
        {mobileSidebar && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setMobileSidebar(false)}
              className="lg:hidden fixed inset-0 bg-black/40 z-40"
            />
            <motion.div
              initial={{ x: -300 }}
              animate={{ x: 0 }}
              exit={{ x: -300 }}
              transition={{ type: 'spring', damping: 28, stiffness: 260 }}
              className="lg:hidden fixed left-0 top-0 h-full w-[280px] z-50 shadow-2xl"
            >
              <button
                onClick={() => setMobileSidebar(false)}
                className="absolute right-2 top-3 p-2 rounded-lg text-surface-500 hover:bg-surface-200/60 dark:hover:bg-surface-800 z-10"
              >
                <X className="w-4 h-4" />
              </button>
              {conversationList}
            </motion.div>
          </>
        )}
      </AnimatePresence>

      {/* Main column */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <header className="shrink-0 h-14 px-3 sm:px-4 flex items-center gap-2 border-b border-surface-200 dark:border-surface-800">
          <button
            onClick={() => setShowSidebar((v) => !v)}
            title={showSidebar ? 'Hide chats' : 'Show chats'}
            className="hidden lg:inline-flex p-2 rounded-lg text-surface-500 hover:bg-surface-100 dark:hover:bg-surface-800"
          >
            {showSidebar ? <PanelLeftClose className="w-4 h-4" /> : <PanelLeftOpen className="w-4 h-4" />}
          </button>
          <button
            onClick={() => setMobileSidebar(true)}
            className="lg:hidden p-2 rounded-lg text-surface-500 hover:bg-surface-100 dark:hover:bg-surface-800"
          >
            <PanelLeftOpen className="w-4 h-4" />
          </button>

          <div className="flex items-center gap-2 min-w-0">
            <h1 className="font-semibold text-surface-900 dark:text-white truncate">
              {sessionData?.title && activeSession ? sessionData.title : aiLabel}
            </h1>
          </div>

          <div className="ml-auto flex items-center gap-2">
            <div className="hidden sm:block">
              <CourseSelector courses={courses} value={courseId} onChange={handleSelectCourse} compact />
            </div>
            <button
              onClick={handleNewChat}
              title="New chat"
              className="p-2 rounded-lg text-surface-500 hover:bg-surface-100 dark:hover:bg-surface-800"
            >
              <MessageSquarePlus className="w-4 h-4" />
            </button>
            <button
              onClick={() => setIsFullscreen((v) => !v)}
              title={isFullscreen ? 'Exit fullscreen (Esc)' : 'Fullscreen'}
              className="p-2 rounded-lg text-surface-500 hover:bg-surface-100 dark:hover:bg-surface-800"
            >
              {isFullscreen ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
            </button>
          </div>
        </header>

        {!aiAvailable && (
          <div className="shrink-0 px-4 py-3 flex items-start gap-3 bg-amber-50 dark:bg-amber-900/20 border-b border-amber-200 dark:border-amber-900">
            <AlertTriangle className="w-4 h-4 text-amber-600 dark:text-amber-400 mt-0.5 shrink-0" />
            <p className="text-sm text-amber-800 dark:text-amber-200">
              {workspace?.unavailable_message || 'The AI assistant is not available right now.'}
            </p>
          </div>
        )}

        {/* Messages */}
        <div ref={scrollRef} className="flex-1 overflow-y-auto overscroll-contain" style={{ minHeight: 0 }}>
          {isEmpty ? (
            <div className="min-h-full flex flex-col items-center justify-center px-4 py-10">
              <motion.div
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                className="w-full max-w-2xl text-center"
              >
                <div className="w-14 h-14 mx-auto rounded-2xl bg-gradient-to-br from-primary-500 to-primary-600 flex items-center justify-center shadow-lg shadow-primary-500/25 mb-5">
                  <Sparkles className="w-7 h-7 text-white" />
                </div>

                <h2 className="text-2xl sm:text-3xl font-bold text-surface-900 dark:text-white">
                  {greeting()}, {profile?.user?.first_name || 'there'}
                </h2>
                <p className="text-surface-500 mt-2 max-w-md mx-auto">
                  {courses.length
                    ? 'Pick a course to get answers about your own progress, mistakes and what’s left — or just ask any doubt.'
                    : 'Ask any doubt and I’ll explain it step by step.'}
                </p>

                {courses.length > 0 && (
                  <div className="flex justify-center mt-5">
                    <CourseSelector courses={courses} value={courseId} onChange={handleSelectCourse} />
                  </div>
                )}

                {starters.length > 0 && (
                  <div className="grid gap-2.5 sm:grid-cols-2 mt-8 text-left">
                    {starters.map((prompt, index) => {
                      const Icon = PROMPT_ICONS[prompt.kind] || Sparkles
                      return (
                        <motion.button
                          key={prompt.text}
                          initial={{ opacity: 0, y: 8 }}
                          animate={{ opacity: 1, y: 0 }}
                          transition={{ delay: 0.05 * index }}
                          onClick={() => send(prompt.text)}
                          disabled={!aiAvailable}
                          className="group flex items-start gap-3 p-3.5 rounded-2xl border border-surface-200 dark:border-surface-800 hover:border-primary-300 dark:hover:border-primary-700 hover:bg-primary-50/50 dark:hover:bg-primary-900/10 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                          <span className="w-8 h-8 rounded-xl bg-surface-100 dark:bg-surface-800 group-hover:bg-primary-100 dark:group-hover:bg-primary-900/30 flex items-center justify-center shrink-0 transition-colors">
                            <Icon className="w-4 h-4 text-primary-500" />
                          </span>
                          <span className="text-sm text-surface-700 dark:text-surface-200 leading-snug pt-1">
                            {prompt.text}
                          </span>
                        </motion.button>
                      )
                    })}
                  </div>
                )}
              </motion.div>
            </div>
          ) : (
            <div className="max-w-3xl mx-auto w-full px-4 sm:px-6 py-6 space-y-6">
              {visibleMessages.map((message, index) =>
                message.role === 'user' ? (
                  <UserMessage key={message.id || index} content={message.content} />
                ) : (
                  <div key={message.id || index} className="flex gap-3">
                    <AssistantAvatar />
                    <div className="min-w-0 flex-1">
                      <AssistantMessage
                        content={message.content}
                        messageId={message.id}
                        sessionId={activeSession}
                        onFeedback={handleFeedback}
                      />
                    </div>
                  </div>
                ),
              )}

              {pendingUserMessage && <UserMessage content={pendingUserMessage.content} />}

              {isStreaming && (
                <div className="flex gap-3">
                  <AssistantAvatar />
                  <div className="min-w-0 flex-1">
                    {streamingContent ? (
                      <AssistantMessage content={streamingContent} isStreaming />
                    ) : (
                      <TypingDots />
                    )}
                  </div>
                </div>
              )}

              <div className="h-2" />
            </div>
          )}
        </div>

        {/* Composer */}
        <div className="shrink-0 px-4 sm:px-6 pb-4 pt-2 bg-gradient-to-t from-white dark:from-surface-900 to-transparent">
          <div className="max-w-3xl mx-auto">
            <div className="rounded-2xl border border-surface-200 dark:border-surface-700 bg-white dark:bg-surface-800/60 shadow-sm focus-within:border-primary-400 dark:focus-within:border-primary-600 focus-within:ring-2 focus-within:ring-primary-500/15 transition-all">
              <textarea
                ref={textareaRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                rows={1}
                disabled={!aiAvailable}
                placeholder={
                  aiAvailable
                    ? courseId
                      ? 'Ask about your progress, a pending chapter, or any doubt…'
                      : 'Ask a doubt, or say “quiz me on…”'
                    : 'The AI assistant is unavailable right now'
                }
                className="w-full bg-transparent resize-none px-4 pt-3.5 pb-1 text-sm leading-relaxed text-surface-900 dark:text-surface-100 placeholder:text-surface-400 focus:outline-none max-h-[200px] disabled:cursor-not-allowed"
              />
              <div className="flex items-center gap-2 px-3 pb-2.5">
                <div className="sm:hidden">
                  <CourseSelector courses={courses} value={courseId} onChange={handleSelectCourse} compact />
                </div>
                <p className="hidden sm:block text-xs text-surface-400">
                  Enter to send · Shift+Enter for a new line
                </p>
                <button
                  onClick={() => {
                    if (isStreaming) {
                      abortStreamRef.current = true
                      setIsStreaming(false)
                      setStreamingContent('')
                      setPendingUserMessage(null)
                      refetchSession()
                    } else {
                      send()
                    }
                  }}
                  disabled={!isStreaming && (!input.trim() || !aiAvailable)}
                  title={isStreaming ? 'Stop' : 'Send'}
                  className="ml-auto w-9 h-9 rounded-xl bg-primary-500 hover:bg-primary-600 text-white flex items-center justify-center transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  {isStreaming ? <Square className="w-3.5 h-3.5 fill-current" /> : <Send className="w-4 h-4" />}
                </button>
              </div>
            </div>
            <p className="text-center text-[11px] text-surface-400 mt-2">
              AI can make mistakes — always double-check important answers against your study material.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}

export default AIDoubtSolver
