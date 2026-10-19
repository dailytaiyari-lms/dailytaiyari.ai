import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
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
  ChevronLeft,
  ChevronRight
} from 'lucide-react'
import { quizService } from '../services/quizService'
import useResponseTimeline from '../hooks/useResponseTimeline'
import { useAuthStore } from '../context/authStore'
import Loading from '../components/common/Loading'
import toast from 'react-hot-toast'

const MockTestAttempt = () => {
  const { testId } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { fetchProfile, user } = useAuthStore()

  const [currentQuestion, setCurrentQuestion] = useState(0)
  const [answers, setAnswers] = useState({})
  const [timeLeft, setTimeLeft] = useState(0)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [result, setResult] = useState(null)

  // Fetch leaderboard after mock test is completed
  const { data: leaderboard } = useQuery({
    queryKey: ['mockTestLeaderboard', testId],
    queryFn: () => quizService.getMockTestLeaderboard(testId),
    enabled: !!result,
  })

  const { data: test, isLoading } = useQuery({
    queryKey: ['mockTestDetail', testId],
    queryFn: () => quizService.getMockTestDetails(testId),
  })

  const currentQ = test?.questions?.[currentQuestion]
  const timeline = useResponseTimeline({
    attemptKind: 'mock',
    parentId: testId,
    currentKey: currentQ ? `bank:${currentQ.id}` : null,
    active: Boolean(test) && !result,
  })

  useEffect(() => {
    if (test) {
      setTimeLeft(test.duration_minutes * 60)
    }
  }, [test])

  useEffect(() => {
    if (timeLeft <= 0 || result) return

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
  }, [timeLeft, result])

  const formatTime = (seconds) => {
    const hrs = Math.floor(seconds / 3600)
    const mins = Math.floor((seconds % 3600) / 60)
    const secs = seconds % 60
    return `${hrs.toString().padStart(2, '0')}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`
  }

  const handleAnswerSelect = (questionId, optionIndex) => {
    timeline.recordAnswer(`bank:${questionId}`, { sel: [Number(optionIndex)] })
    setAnswers((prev) => ({
      ...prev,
      [questionId]: {
        question_id: questionId,
        selected_option: optionIndex.toString(),
      },
    }))
  }

  const handleSubmit = async () => {
    if (isSubmitting) return
    setIsSubmitting(true)

    try {
      await timeline.flush({ final: true })
      const response = await quizService.submitMockTest(testId, {
        answers: Object.values(answers).map((a) => ({
          ...a,
          time_taken_seconds: Math.round(timeline.activeSeconds(`bank:${a.question_id}`)),
        })),
        time_taken_seconds: test.duration_minutes * 60 - timeLeft,
      })
      setResult(response)

      // Invalidate caches to refresh dashboard and analytics
      queryClient.invalidateQueries({ queryKey: ['dashboardStats'] })
      queryClient.invalidateQueries({ queryKey: ['topicMastery'] })
      queryClient.invalidateQueries({ queryKey: ['weakTopics'] })
      queryClient.invalidateQueries({ queryKey: ['strongTopics'] })
      queryClient.invalidateQueries({ queryKey: ['chartData'] })
      queryClient.invalidateQueries({ queryKey: ['currentStreak'] })

      // Refresh user profile to get updated XP
      fetchProfile()
    } catch (error) {
      toast.error('Failed to submit test')
    } finally {
      setIsSubmitting(false)
    }
  }

  if (isLoading) return <Loading fullScreen />

  const questions = test?.questions || []
  const question = questions[currentQuestion]
  const markingScheme = test?.marking_scheme
  const answeredCount = Object.keys(answers).length

  // Result Screen
  if (result) {
    const totalMarks = markingScheme?.total_marks || test?.total_marks || 0

    return (
      <div className="max-w-2xl mx-auto py-8 px-4">
        <motion.div
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          className="card p-8"
        >
          {/* Header */}
          <div className="text-center mb-6">
            <div className="flex justify-center mb-4">
              {result.percentage >= 70 ? (
                <PartyPopper size={64} className="text-success-500" />
              ) : result.percentage >= 40 ? (
                <Zap size={64} className="text-warning-500" />
              ) : (
                <BookOpen size={64} className="text-error-500" />
              )}
            </div>
            <h2 className="text-2xl font-bold mb-1">Mock Test Completed!</h2>
            <p className="text-surface-500">{test?.title}</p>
          </div>

          {/* Main Score */}
          <div className="text-center p-6 rounded-2xl bg-gradient-to-br from-primary-500/10 to-accent-500/10 mb-6">
            <p className="text-5xl font-bold mb-1">
              <span className={result.marks_obtained >= 0 ? '' : 'text-error-500'}>
                {result.marks_obtained}
              </span>
              <span className="text-2xl text-surface-400">/{totalMarks}</span>
            </p>
            <p className="text-surface-500">Marks Scored</p>
            <p className="text-lg font-semibold mt-1">{Math.round(result.percentage)}%</p>
          </div>

          {/* Detailed Stats */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
            <div className="p-3 rounded-xl bg-success-50 dark:bg-success-900/10 text-center">
              <p className="text-2xl font-bold text-success-600">{result.correct_answers}</p>
              <p className="text-xs text-success-500">Correct</p>
            </div>
            <div className="p-3 rounded-xl bg-error-50 dark:bg-error-900/10 text-center">
              <p className="text-2xl font-bold text-error-600">{result.wrong_answers}</p>
              <p className="text-xs text-error-500">Wrong</p>
            </div>
            <div className="p-3 rounded-xl bg-surface-100 dark:bg-surface-800 text-center">
              <p className="text-2xl font-bold text-surface-600 dark:text-surface-300">
                {(result.total_questions || questions.length) - result.attempted_questions}
              </p>
              <p className="text-xs text-surface-500">Unanswered</p>
            </div>
            <div className="p-3 rounded-xl bg-primary-50 dark:bg-primary-900/10 text-center">
              <p className="text-2xl font-bold text-primary-600">
                {Math.floor((result.time_taken_seconds || 0) / 60)}m
              </p>
              <p className="text-xs text-primary-500">Time Taken</p>
            </div>
          </div>

          {/* Marking Scheme */}
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
                  <span className="text-primary-600 dark:text-primary-400">Duration:</span>
                  <span className="font-medium">{markingScheme.duration_minutes} min</span>
                </div>
              </div>
            </div>
          )}

          {/* Rank */}
          {result.rank && (
            <div className="mb-6 p-4 rounded-xl bg-gradient-to-r from-yellow-50 to-amber-50 dark:from-yellow-900/10 dark:to-amber-900/10 border border-yellow-200 dark:border-yellow-800 text-center">
              <p className="text-lg">Your Rank: <span className="font-bold text-primary-600 text-2xl">#{result.rank}</span></p>
              {result.percentile && <p className="text-sm text-surface-500">Top {result.percentile}%</p>}
            </div>
          )}

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
                          {entry.marks_obtained}/{entry.total_marks || totalMarks}
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
                        {result.marks_obtained}/{totalMarks}
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
              onClick={() => navigate(`/mock-test/review/${result.id}`)}
              className="btn-primary w-full flex items-center justify-center gap-2"
            >
              <FileText size={20} /> Review Answers
            </button>
            <div className="grid grid-cols-2 gap-3">
              <button
                onClick={() => navigate('/mock-test')}
                className="btn-secondary"
              >
                Back to Tests
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
    <div className="max-w-4xl mx-auto">
      {/* Header */}
      <div className="sticky top-0 z-20 bg-surface-50/95 dark:bg-surface-950/95 backdrop-blur-sm py-4 -mx-4 px-4 mb-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="font-semibold">{test?.title}</h2>
            <p className="text-sm text-surface-500">
              Question {currentQuestion + 1} of {questions.length}
              <span className="ml-2 text-xs text-surface-400">
                ({answeredCount} answered)
              </span>
              {markingScheme && (
                <span className="ml-2 text-xs text-surface-400">
                  +{markingScheme.marks_per_question} / -{markingScheme.negative_marks_per_question}
                </span>
              )}
            </p>
          </div>
          <div className={`px-4 py-2 rounded-xl font-mono font-bold text-lg flex items-center gap-2 ${timeLeft <= 300 ? 'bg-error-100 text-error-600 animate-pulse' :
            timeLeft <= 600 ? 'bg-warning-100 text-warning-600' :
              'bg-surface-100 dark:bg-surface-800'
            }`}>
            <Timer size={20} /> {formatTime(timeLeft)}
          </div>
        </div>
      </div>

      {/* Question */}
      <div className="card p-6 mb-6">
        <div className="flex items-start gap-4 mb-6">
          <span className="w-10 h-10 rounded-xl bg-primary-100 dark:bg-primary-900/30 text-primary-600 flex items-center justify-center font-bold">
            {currentQuestion + 1}
          </span>
          <div className="flex-1">
            <p className="text-lg font-medium leading-relaxed">
              {question?.question_text}
            </p>
            {/* Per-question marks */}
            <div className="mt-2 flex items-center gap-3 text-xs text-surface-400">
              <span className="text-success-500">+{question?.marks || 1} marks</span>
              {(question?.negative_marks || 0) > 0 && (
                <span className="text-error-500">-{question.negative_marks} for wrong</span>
              )}
              <span className="capitalize px-2 py-0.5 rounded-full bg-surface-100 dark:bg-surface-800">
                {question?.difficulty || 'medium'}
              </span>
              {question?.subject_name && (
                <span className="px-2 py-0.5 rounded-full bg-surface-100 dark:bg-surface-800">
                  {question.subject_name}
                </span>
              )}
            </div>
          </div>
        </div>

        <div className="space-y-3">
          {question?.options?.map((option, index) => {
            const isSelected = answers[question.id]?.selected_option === index.toString()

            return (
              <button
                key={option.id}
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
                </div>
              </button>
            )
          })}
        </div>
      </div>

      {/* Question Navigator */}
      <div className="card p-4 mb-20">
        <div className="flex items-center justify-between mb-3">
          <p className="text-sm font-medium text-surface-500">Question Navigator</p>
          <div className="flex gap-3 text-xs text-surface-500">
            <span className="flex items-center gap-1">
              <span className="w-3 h-3 rounded bg-success-100 dark:bg-success-900/30"></span> Answered ({answeredCount})
            </span>
            <span className="flex items-center gap-1">
              <span className="w-3 h-3 rounded bg-surface-100 dark:bg-surface-700"></span> Unanswered ({questions.length - answeredCount})
            </span>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {questions.map((_, index) => (
            <button
              key={index}
              onClick={() => setCurrentQuestion(index)}
              className={`w-10 h-10 rounded-lg text-sm font-medium transition-colors ${index === currentQuestion
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
      </div>

      {/* Navigation */}
      <div className="fixed bottom-20 lg:bottom-0 left-0 right-0 bg-white/95 dark:bg-surface-900/95 backdrop-blur-sm border-t border-surface-200 dark:border-surface-800 p-4">
        <div className="max-w-4xl mx-auto flex justify-between">
          <button
            onClick={() => setCurrentQuestion(Math.max(0, currentQuestion - 1))}
            disabled={currentQuestion === 0}
            className="btn-secondary flex items-center gap-2"
          >
            <ChevronLeft size={18} /> Previous
          </button>

          <button
            onClick={handleSubmit}
            disabled={isSubmitting}
            className="btn-primary flex items-center gap-2"
          >
            {isSubmitting ? 'Submitting...' : <><CheckCircle2 size={18} /> Submit Test</>}
          </button>

          <button
            onClick={() => setCurrentQuestion(Math.min(questions.length - 1, currentQuestion + 1))}
            disabled={currentQuestion === questions.length - 1}
            className="btn-secondary flex items-center gap-2"
          >
            Next <ChevronRight size={18} />
          </button>
        </div>
      </div>
    </div>
  )
}

export default MockTestAttempt
