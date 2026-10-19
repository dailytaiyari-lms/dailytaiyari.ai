import { useState, useEffect, useCallback, useRef } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Trophy,
  Zap,
  BookOpen,
  ClipboardList,
  Timer,
  Award,
  FileText,
  PartyPopper,
  CheckCircle2,
  ChevronRight,
  ChevronLeft,
  ShieldCheck,
  AlertTriangle,
  Maximize2
} from 'lucide-react'
import { quizService } from '../services/quizService'
import { useAuthStore } from '../context/authStore'
import Loading from '../components/common/Loading'
import toast from 'react-hot-toast'
import Confetti from 'react-confetti'

const QuizAttempt = () => {
  const { quizId } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const queryClient = useQueryClient()
  const { fetchProfile, user } = useAuthStore()

  // Where the user came from (set when launched from a course topic page).
  const courseCtx = location.state
  const goBackToCourse = () => {
    if (courseCtx?.chapterId && courseCtx?.topicId) {
      navigate(`/study/chapter/${courseCtx.chapterId}/topic/${courseCtx.topicId}`)
    } else if (quiz?.topic) {
      navigate(`/topic/${quiz.topic}`)
    } else {
      navigate('/quiz')
    }
  }

  const [currentQuestion, setCurrentQuestion] = useState(0)
  const [answers, setAnswers] = useState({})
  const [timeLeft, setTimeLeft] = useState(0)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [result, setResult] = useState(null)
  const [showConfetti, setShowConfetti] = useState(false)
  const [proctoringStarted, setProctoringStarted] = useState(false)
  const [isStarting, setIsStarting] = useState(false)
  const [showProctorWarning, setShowProctorWarning] = useState(false)
  const [violationCount, setViolationCount] = useState(0)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const submittedRef = useRef(false)
  const lastViolationAtRef = useRef(0)
  const fullscreenSupported = Boolean(
    document.documentElement.requestFullscreen ||
    document.documentElement.webkitRequestFullscreen
  )

  // Fetch leaderboard after quiz is completed
  const { data: leaderboard } = useQuery({
    queryKey: ['quizLeaderboard', quizId],
    queryFn: () => quizService.getQuizLeaderboard(quizId),
    enabled: !!result, // Only fetch after result is available
  })

  const { data: quiz, isLoading } = useQuery({
    queryKey: ['quizDetail', quizId],
    queryFn: () => quizService.getQuizDetails(quizId),
  })

  const enterFullscreen = useCallback(async () => {
    const element = document.documentElement
    const requestFullscreen = element?.requestFullscreen || element?.webkitRequestFullscreen
    if (!requestFullscreen) {
      return false
    }
    await requestFullscreen.call(element)
    setIsFullscreen(true)
    return true
  }, [])

  const exitFullscreen = useCallback(async () => {
    const exit = document.exitFullscreen || document.webkitExitFullscreen
    if ((document.fullscreenElement || document.webkitFullscreenElement) && exit) {
      await exit.call(document)
    }
    setIsFullscreen(false)
  }, [])

  const beginProctoredQuiz = async () => {
    if (isStarting) return
    setIsStarting(true)
    try {
      // Fullscreen requests must originate from this explicit user action.
      await enterFullscreen()
      const attempt = await quizService.startQuiz(quizId)
      const elapsedSeconds = attempt?.started_at
        ? Math.max(0, Math.floor((Date.now() - Date.parse(attempt.started_at)) / 1000))
        : 0
      setTimeLeft(Math.max(0, quiz.duration_minutes * 60 - elapsedSeconds))
      setViolationCount(attempt?.proctoring_violations || 0)
      setProctoringStarted(true)
    } catch (error) {
      await exitFullscreen().catch(() => {})
      toast.error(error?.response?.data?.error || error.message || 'Could not start the proctored quiz')
    } finally {
      setIsStarting(false)
    }
  }

  const reportViolation = useCallback((eventType) => {
    if (submittedRef.current) return
    const now = Date.now()
    if (now - lastViolationAtRef.current < 1000) return
    lastViolationAtRef.current = now
    setViolationCount((count) => count + 1)
    setShowProctorWarning(true)
    quizService.reportProctoringEvent(quizId, eventType).catch(() => {
      toast.error('Could not record the proctoring event. Check your connection.')
    })
  }, [quizId])

  useEffect(() => {
    if (!proctoringStarted || result) return

    const onVisibilityChange = () => {
      if (document.hidden) reportViolation('tab_switch')
    }
    const onFullscreenChange = () => {
      const fullscreen = Boolean(document.fullscreenElement || document.webkitFullscreenElement)
      setIsFullscreen(fullscreen)
      if (fullscreenSupported && !fullscreen && !submittedRef.current) {
        reportViolation('fullscreen_exit')
      }
    }
    const onKeyDown = (event) => {
      const key = event.key.toLowerCase()
      const restrictedBrowserShortcut =
        (event.ctrlKey || event.metaKey) && ['l', 'n', 't', 'w'].includes(key)
      const restrictedTabShortcut =
        key === 'tab' && (event.ctrlKey || event.metaKey || event.altKey)
      if (restrictedBrowserShortcut || restrictedTabShortcut) {
        event.preventDefault()
        event.stopPropagation()
        reportViolation('restricted_shortcut')
      }
    }
    const onBeforeUnload = (event) => {
      event.preventDefault()
      event.returnValue = ''
    }

    document.addEventListener('visibilitychange', onVisibilityChange)
    document.addEventListener('fullscreenchange', onFullscreenChange)
    document.addEventListener('webkitfullscreenchange', onFullscreenChange)
    window.addEventListener('keydown', onKeyDown, true)
    window.addEventListener('beforeunload', onBeforeUnload)
    return () => {
      document.removeEventListener('visibilitychange', onVisibilityChange)
      document.removeEventListener('fullscreenchange', onFullscreenChange)
      document.removeEventListener('webkitfullscreenchange', onFullscreenChange)
      window.removeEventListener('keydown', onKeyDown, true)
      window.removeEventListener('beforeunload', onBeforeUnload)
    }
  }, [fullscreenSupported, proctoringStarted, reportViolation, result])

  // Timer countdown
  useEffect(() => {
    if (!proctoringStarted || timeLeft <= 0 || result) return

    const timer = setInterval(() => {
      setTimeLeft((prev) => {
        if (prev <= 1) {
          handleSubmit()
          return 0
        }
        return prev - 1
      })
    }, 1000)

    return () => clearInterval(timer)
  }, [timeLeft, result, proctoringStarted])

  const formatTime = (seconds) => {
    const mins = Math.floor(seconds / 60)
    const secs = seconds % 60
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`
  }

  const handleAnswerSelect = (questionId, optionIndex) => {
    setAnswers((prev) => ({
      ...prev,
      [questionId]: {
        question_id: questionId,
        selected_option: optionIndex.toString(),
        time_taken_seconds: Math.floor((quiz.duration_minutes * 60 - timeLeft) / quiz.questions.length),
      },
    }))
  }

  const handleSubmit = async () => {
    if (isSubmitting) return
    submittedRef.current = true
    setIsSubmitting(true)

    try {
      const response = await quizService.submitQuiz(quizId, {
        answers: Object.values(answers),
        time_taken_seconds: quiz.duration_minutes * 60 - timeLeft,
      })

      await exitFullscreen().catch(() => {})
      setResult(response)

      // Invalidate caches to refresh dashboard and analytics
      queryClient.invalidateQueries({ queryKey: ['dashboardStats'] })
      queryClient.invalidateQueries({ queryKey: ['recentAttempts'] })
      queryClient.invalidateQueries({ queryKey: ['topicMastery'] })
      queryClient.invalidateQueries({ queryKey: ['weakTopics'] })
      queryClient.invalidateQueries({ queryKey: ['strongTopics'] })
      queryClient.invalidateQueries({ queryKey: ['chartData'] })
      queryClient.invalidateQueries({ queryKey: ['currentStreak'] })
      queryClient.invalidateQueries({ queryKey: ['studyChapterDetail'] })

      // Refresh user profile to get updated XP
      fetchProfile()

      if (response.percentage >= 70) {
        setShowConfetti(true)
        setTimeout(() => setShowConfetti(false), 5000)
      }
    } catch (error) {
      submittedRef.current = false
      toast.error('Failed to submit quiz')
    } finally {
      setIsSubmitting(false)
    }
  }

  if (isLoading) return <Loading fullScreen />

  const questions = quiz?.questions || []
  const question = questions[currentQuestion]
  const progress = ((currentQuestion + 1) / questions.length) * 100
  const markingScheme = quiz?.marking_scheme

  if (!proctoringStarted) {
    return (
      <div className="min-h-[80vh] bg-surface-50 dark:bg-surface-950 flex items-center justify-center p-4">
        <div className="card p-8 max-w-lg w-full text-center">
          <ShieldCheck size={56} className="mx-auto mb-4 text-primary-500" />
          <h1 className="text-2xl font-bold mb-3">Proctored quiz</h1>
          <p className="text-surface-500 mb-5">
            When supported, this quiz runs in fullscreen. Switching tabs, leaving fullscreen,
            or using restricted browser shortcuts will be recorded and shown to your faculty.
          </p>
          <ul className="list-disc pl-5 text-left text-sm text-surface-600 dark:text-surface-300 space-y-2 mb-6">
            <li>Stay on this quiz until you submit it.</li>
            <li>Do not use Alt+Tab, Cmd+Tab, Ctrl+Tab, or browser navigation shortcuts.</li>
            {fullscreenSupported ? (
              <li>If fullscreen closes, you must re-enter it before continuing.</li>
            ) : (
              <li>Your browser does not support fullscreen; tab switching will still be monitored.</li>
            )}
          </ul>
          <button
            onClick={beginProctoredQuiz}
            disabled={isStarting}
            className="btn-primary w-full flex items-center justify-center gap-2"
          >
            <Maximize2 size={18} />
            {isStarting
              ? 'Starting...'
              : fullscreenSupported
                ? 'Enter fullscreen and start'
                : 'Start proctored quiz'}
          </button>
        </div>
      </div>
    )
  }

  // Result Screen
  if (result) {
    return (
      <div className="min-h-[80vh] flex items-center justify-center px-4">
        {showConfetti && <Confetti recycle={false} numberOfPieces={200} />}

        <motion.div
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          className="card p-8 max-w-2xl w-full"
        >
          {/* Result Header */}
          <div className="text-center mb-6">
            {result.percentage >= 70 ? (
              <>
                <div className="flex justify-center mb-4 text-success-500">
                  <PartyPopper size={64} />
                </div>
                <h2 className="text-2xl font-bold text-success-500">Excellent!</h2>
              </>
            ) : result.percentage >= 40 ? (
              <>
                <div className="flex justify-center mb-4 text-warning-500">
                  <Zap size={64} />
                </div>
                <h2 className="text-2xl font-bold text-warning-500">Good Effort!</h2>
              </>
            ) : (
              <>
                <div className="flex justify-center mb-4 text-error-500">
                  <BookOpen size={64} />
                </div>
                <h2 className="text-2xl font-bold text-error-500">Keep Practicing!</h2>
              </>
            )}
          </div>

          {/* Score Summary */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            <div className="p-4 rounded-xl bg-surface-50 dark:bg-surface-800 text-center">
              <p className="text-3xl font-bold">{Math.round(result.percentage)}%</p>
              <p className="text-sm text-surface-500">Score</p>
            </div>
            <div className="p-4 rounded-xl bg-surface-50 dark:bg-surface-800 text-center">
              <p className="text-3xl font-bold">
                <span className={result.marks_obtained >= 0 ? 'text-success-500' : 'text-error-500'}>
                  {result.marks_obtained}
                </span>
                <span className="text-lg text-surface-400">/{result.total_marks}</span>
              </p>
              <p className="text-sm text-surface-500">Marks</p>
            </div>
            <div className="p-4 rounded-xl bg-surface-50 dark:bg-surface-800 text-center">
              <p className="text-3xl font-bold text-success-500">{result.correct_answers}</p>
              <p className="text-sm text-surface-500">Correct</p>
            </div>
            <div className="p-4 rounded-xl bg-surface-50 dark:bg-surface-800 text-center">
              <p className="text-3xl font-bold text-primary-500">+{result.xp_earned}</p>
              <p className="text-sm text-surface-500">XP Earned</p>
            </div>
          </div>

          {/* Detailed Breakdown */}
          <div className="grid grid-cols-3 gap-3 mb-6">
            <div className="p-3 rounded-lg bg-success-50 dark:bg-success-900/10 text-center">
              <p className="text-lg font-bold text-success-600">{result.correct_answers}</p>
              <p className="text-xs text-success-500">Correct</p>
            </div>
            <div className="p-3 rounded-lg bg-error-50 dark:bg-error-900/10 text-center">
              <p className="text-lg font-bold text-error-600">{result.wrong_answers}</p>
              <p className="text-xs text-error-500">Wrong</p>
            </div>
            <div className="p-3 rounded-lg bg-surface-100 dark:bg-surface-800 text-center">
              <p className="text-lg font-bold text-surface-600 dark:text-surface-300">{result.skipped_questions}</p>
              <p className="text-xs text-surface-500">Skipped</p>
            </div>
          </div>

          {/* Marking Scheme Info */}
          {markingScheme && (
            <div className="p-4 rounded-xl bg-primary-50 dark:bg-primary-900/10 border border-primary-200 dark:border-primary-800 mb-6">
              <p className="text-sm font-semibold text-primary-700 dark:text-primary-300 mb-2 flex items-center gap-2">
                <ClipboardList size={18} /> Marking Scheme
              </p>
              <div className="grid grid-cols-2 gap-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-primary-600 dark:text-primary-400">Correct Answer:</span>
                  <span className="font-medium text-success-600">+{markingScheme.marks_per_question}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-primary-600 dark:text-primary-400">Wrong Answer:</span>
                  <span className="font-medium text-error-600">
                    {markingScheme.negative_marks_per_question > 0
                      ? `-${markingScheme.negative_marks_per_question}`
                      : 'No penalty'}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-primary-600 dark:text-primary-400">Total Marks:</span>
                  <span className="font-medium">{markingScheme.total_marks}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-primary-600 dark:text-primary-400">Questions:</span>
                  <span className="font-medium">{markingScheme.total_questions}</span>
                </div>
              </div>
            </div>
          )}

          {/* Time Taken */}
          <div className="flex items-center justify-center gap-2 text-surface-500 mb-6 font-medium">
            <Timer size={20} className="text-primary-500" />
            <span>Time Taken: {Math.floor((result.time_taken_seconds || 0) / 60)}:{String((result.time_taken_seconds || 0) % 60).padStart(2, '0')}</span>
          </div>

          {/* Leaderboard */}
          {leaderboard && leaderboard.leaderboard?.length > 0 && (
            <div className="mb-6">
              <h3 className="font-semibold text-lg mb-3 flex items-center gap-2">
                <Trophy size={20} className="text-warning-500" /> Leaderboard
              </h3>
              <div className="rounded-xl border border-surface-200 dark:border-surface-700 overflow-hidden">
                {/* Header */}
                <div className="grid grid-cols-12 gap-2 px-4 py-2 bg-surface-100 dark:bg-surface-800 text-xs font-medium text-surface-500 uppercase tracking-wider">
                  <div className="col-span-1">#</div>
                  <div className="col-span-5">Student</div>
                  <div className="col-span-3 text-right">Marks</div>
                  <div className="col-span-3 text-right">Score</div>
                </div>
                {/* Entries */}
                <div className="divide-y divide-surface-100 dark:divide-surface-800">
                  {leaderboard.leaderboard.slice(0, 10).map((entry) => {
                    const isCurrentUser = entry.student_email === user?.email || entry.is_current_user
                    return (
                      <div
                        key={entry.rank}
                        className={`grid grid-cols-12 gap-2 px-4 py-2.5 items-center transition-colors ${isCurrentUser
                          ? 'bg-primary-50 dark:bg-primary-900/20 font-semibold'
                          : 'hover:bg-surface-50 dark:hover:bg-surface-800/50'
                          }`}
                      >
                        <div className="col-span-1">
                          {entry.rank <= 3 ? (
                            <Award
                              size={20}
                              className={
                                entry.rank === 1 ? 'text-warning-500' :
                                  entry.rank === 2 ? 'text-surface-400' :
                                    'text-orange-400'
                              }
                            />
                          ) : (
                            <span className="text-surface-500 text-sm">{entry.rank}</span>
                          )}
                        </div>
                        <div className="col-span-5 truncate">
                          <span className={isCurrentUser ? 'text-primary-600 dark:text-primary-400' : ''}>
                            {entry.student_name || 'Student'}
                            {isCurrentUser && <span className="text-xs ml-1 opacity-70">(You)</span>}
                          </span>
                        </div>
                        <div className="col-span-3 text-right text-sm">
                          {entry.marks_obtained}/{entry.total_marks || result.total_marks}
                        </div>
                        <div className="col-span-3 text-right">
                          <span className={`text-sm font-medium ${entry.percentage >= 70 ? 'text-success-500' :
                            entry.percentage >= 40 ? 'text-warning-500' : 'text-error-500'
                            }`}>
                            {Math.round(entry.percentage)}%
                          </span>
                        </div>
                      </div>
                    )
                  })}
                </div>
                {/* Current user rank if not in top 10 */}
                {leaderboard.user_rank && leaderboard.user_rank > 10 && (
                  <div className="border-t-2 border-dashed border-surface-200 dark:border-surface-700">
                    <div className="grid grid-cols-12 gap-2 px-4 py-2.5 items-center bg-primary-50 dark:bg-primary-900/20 font-semibold">
                      <div className="col-span-1 text-surface-500 text-sm">{leaderboard.user_rank}</div>
                      <div className="col-span-5 truncate text-primary-600 dark:text-primary-400">
                        You
                      </div>
                      <div className="col-span-3 text-right text-sm">
                        {result.marks_obtained}/{result.total_marks}
                      </div>
                      <div className="col-span-3 text-right">
                        <span className={`text-sm font-medium ${result.percentage >= 70 ? 'text-success-500' :
                          result.percentage >= 40 ? 'text-warning-500' : 'text-error-500'
                          }`}>
                          {Math.round(result.percentage)}%
                        </span>
                      </div>
                    </div>
                  </div>
                )}
              </div>
              <p className="text-xs text-surface-400 mt-2 text-center">
                {leaderboard.total_participants} total participant{leaderboard.total_participants !== 1 ? 's' : ''}
              </p>
            </div>
          )}

          {/* Actions */}
          <div className="space-y-3">
            <button
              onClick={() => navigate(`/quiz/review/${result.id}`, { state: courseCtx })}
              className="btn-primary w-full flex items-center justify-center gap-2"
            >
              <FileText size={20} /> Review Answers
            </button>
            <div className="grid grid-cols-2 gap-3">
              <button
                onClick={goBackToCourse}
                className="btn-secondary"
              >
                Back to Course
              </button>
              <button
                onClick={() => navigate('/analytics')}
                className="btn-secondary"
              >
                View Analytics
              </button>
            </div>
          </div>
        </motion.div>
      </div>
    )
  }

  return (
    <div className="max-w-3xl mx-auto min-h-screen bg-surface-50 dark:bg-surface-950">
      {/* Header */}
      <div className="sticky top-0 z-20 bg-surface-50/95 dark:bg-surface-950/95 backdrop-blur-sm py-4 -mx-4 px-4">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h2 className="font-semibold">{quiz?.title}</h2>
            <p className="text-sm text-surface-500">
              Question {currentQuestion + 1} of {questions.length}
              {markingScheme && (
                <span className="ml-2 text-xs text-surface-400">
                  (+{markingScheme.marks_per_question} / -{markingScheme.negative_marks_per_question})
                </span>
              )}
            </p>
          </div>
          <div className={`px-4 py-2 rounded-xl font-mono font-bold flex items-center gap-2 ${timeLeft <= 60 ? 'bg-error-100 text-error-600 animate-pulse' :
            timeLeft <= 300 ? 'bg-warning-100 text-warning-600' :
              'bg-surface-100 dark:bg-surface-800'
            }`}>
            <Timer size={20} /> {formatTime(timeLeft)}
          </div>
        </div>

        {/* Progress Bar */}
        <div className="progress-bar h-2">
          <motion.div
            className="progress-bar-fill bg-gradient-to-r from-primary-500 to-accent-500"
            initial={{ width: 0 }}
            animate={{ width: `${progress}%` }}
            transition={{ duration: 0.3 }}
          />
        </div>
      </div>

      {/* Question */}
      <AnimatePresence mode="wait">
        <motion.div
          key={currentQuestion}
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: -20 }}
          className="card p-6 my-6"
        >
          <div className="flex items-start gap-4 mb-6">
            <span className="flex-shrink-0 w-10 h-10 rounded-xl bg-primary-100 dark:bg-primary-900/30 text-primary-600 dark:text-primary-400 flex items-center justify-center font-bold">
              {currentQuestion + 1}
            </span>
            <div>
              <p className="text-lg font-medium leading-relaxed">
                {question?.question_text}
              </p>
              {question?.question_image && (
                <img
                  src={question.question_image}
                  alt="Question"
                  className="mt-4 rounded-xl max-h-64 object-contain"
                />
              )}
              {/* Per-question marks display */}
              <div className="mt-2 flex items-center gap-3 text-xs text-surface-400">
                <span className="text-success-500">+{question?.marks || 1} marks</span>
                {(question?.negative_marks || 0) > 0 && (
                  <span className="text-error-500">-{question.negative_marks} for wrong</span>
                )}
                <span className="capitalize px-2 py-0.5 rounded-full bg-surface-100 dark:bg-surface-800">
                  {question?.difficulty || 'medium'}
                </span>
              </div>
            </div>
          </div>

          {/* Options */}
          <div className="space-y-3">
            {question?.options?.map((option, index) => {
              const isSelected = answers[question.id]?.selected_option === index.toString()

              return (
                <motion.button
                  key={option.id}
                  whileHover={{ scale: 1.01 }}
                  whileTap={{ scale: 0.99 }}
                  onClick={() => handleAnswerSelect(question.id, index)}
                  className={`w-full text-left p-4 rounded-xl border-2 transition-all ${isSelected
                    ? 'border-primary-500 bg-primary-50 dark:bg-primary-900/20'
                    : 'border-surface-200 dark:border-surface-700 hover:border-primary-300'
                    }`}
                >
                  <div className="flex items-center gap-3">
                    <span className={`w-8 h-8 rounded-lg flex items-center justify-center font-medium ${isSelected
                      ? 'bg-primary-500 text-white'
                      : 'bg-surface-100 dark:bg-surface-700'
                      }`}>
                      {String.fromCharCode(65 + index)}
                    </span>
                    <span className="flex-1">{option.option_text}</span>
                    {option.option_image && (
                      <img src={option.option_image} alt="" className="h-12 rounded" />
                    )}
                  </div>
                </motion.button>
              )
            })}
          </div>
        </motion.div>
      </AnimatePresence>

      {/* Navigation */}
      <div className="fixed bottom-20 lg:bottom-0 left-0 right-0 bg-white/95 dark:bg-surface-900/95 backdrop-blur-sm border-t border-surface-200 dark:border-surface-800 p-4">
        <div className="max-w-3xl mx-auto flex items-center justify-between gap-4">
          <button
            onClick={() => setCurrentQuestion(Math.max(0, currentQuestion - 1))}
            disabled={currentQuestion === 0}
            className="btn-secondary flex items-center gap-2"
          >
            <ChevronLeft size={18} /> Previous
          </button>

          {/* Question Navigator */}
          <div className="hidden md:flex items-center gap-1 overflow-x-auto">
            {questions.map((_, index) => (
              <button
                key={index}
                onClick={() => setCurrentQuestion(index)}
                className={`w-8 h-8 rounded-lg text-sm font-medium transition-colors ${index === currentQuestion
                  ? 'bg-primary-500 text-white'
                  : answers[questions[index]?.id]
                    ? 'bg-success-100 dark:bg-success-900/30 text-success-600'
                    : 'bg-surface-100 dark:bg-surface-700'
                  }`}
              >
                {index + 1}
              </button>
            ))}
          </div>

          {currentQuestion === questions.length - 1 ? (
            <button
              onClick={handleSubmit}
              disabled={isSubmitting}
              className="btn-primary flex items-center gap-2"
            >
              {isSubmitting ? 'Submitting...' : <><CheckCircle2 size={18} /> Submit Quiz</>}
            </button>
          ) : (
            <button
              onClick={() => setCurrentQuestion(Math.min(questions.length - 1, currentQuestion + 1))}
              className="btn-primary flex items-center gap-2"
            >
              Next <ChevronRight size={18} />
            </button>
          )}
        </div>
      </div>

      {showProctorWarning && (
        <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4">
          <div className="card p-6 max-w-sm w-full text-center">
            <AlertTriangle size={48} className="mx-auto mb-3 text-warning-500" />
            <h3 className="text-xl font-bold mb-2">Proctoring warning</h3>
            <p className="text-sm text-surface-500 mb-2">
              You left the quiz tab, exited fullscreen, or used a restricted shortcut.
            </p>
            <p className="font-semibold text-warning-600 mb-5">
              Recorded violations: {violationCount}
            </p>
            <button
              onClick={async () => {
                try {
                  if (!isFullscreen) await enterFullscreen()
                  setShowProctorWarning(false)
                } catch (error) {
                  toast.error(error.message || 'Fullscreen is required to continue')
                }
              }}
              className="btn-primary w-full flex items-center justify-center gap-2"
            >
              <Maximize2 size={18} />
              {fullscreenSupported ? 'Re-enter and continue' : 'Continue quiz'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export default QuizAttempt
