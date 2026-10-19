import { useState } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { useQuery, useMutation } from '@tanstack/react-query'
import { quizService } from '../services/quizService'
import { courseService } from '../services/courseService'
import Loading from '../components/common/Loading'
import toast from 'react-hot-toast'
import WhatHappened, { useSelfReports } from '../components/review/WhatHappened'
import {
  XCircle,
  HelpCircle,
  FileText,
  Settings,
  Edit3,
  BookOpen,
  RefreshCw,
  Calendar,
  MessageSquare,
  AlertTriangle,
  Lightbulb,
  CheckCircle2,
  X,
  ChevronLeft,
  RotateCcw,
  Trophy,
  Clock
} from 'lucide-react'

const REPORT_TYPES = [
  { value: 'wrong_answer', label: 'Wrong Answer/Solution', icon: XCircle },
  { value: 'unclear_question', label: 'Unclear Question', icon: HelpCircle },
  { value: 'wrong_options', label: 'Wrong/Missing Options', icon: FileText },
  { value: 'formatting_issue', label: 'Formatting Issue', icon: Settings },
  { value: 'typo', label: 'Typo/Spelling Error', icon: Edit3 },
  { value: 'wrong_topic', label: 'Wrong Topic/Subject', icon: BookOpen },
  { value: 'duplicate', label: 'Duplicate Question', icon: RefreshCw },
  { value: 'outdated', label: 'Outdated Information', icon: Calendar },
  { value: 'other', label: 'Other', icon: MessageSquare },
]

const QuizReview = () => {
  const { attemptId } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const [reportModalOpen, setReportModalOpen] = useState(false)
  const [reportingQuestion, setReportingQuestion] = useState(null)
  const [reportType, setReportType] = useState('')
  const [reportDescription, setReportDescription] = useState('')
  const [filter, setFilter] = useState('all') // all, correct, wrong, skipped

  // Where the user came from (set when launched from a course topic page).
  const courseCtx = location.state
  const goBackToCourse = () => {
    if (courseCtx?.chapterId && courseCtx?.topicId) {
      navigate(`/study/chapter/${courseCtx.chapterId}/topic/${courseCtx.topicId}`)
    } else if (attempt?.topic) {
      navigate(`/topic/${attempt.topic}`)
    } else {
      navigate('/quiz')
    }
  }

  const { data: attempt, isLoading, error } = useQuery({
    queryKey: ['attemptReview', attemptId],
    queryFn: () => quizService.getAttemptReview(attemptId),
  })

  const selfReports = useSelfReports('quiz', attemptId)

  const { data: leaderboard } = useQuery({
    queryKey: ['quizLeaderboard', attempt?.quiz],
    queryFn: () => courseService.getStudyLeaderboard('quiz', attempt.quiz),
    enabled: !!attempt?.quiz,
  })

  const reportMutation = useMutation({
    mutationFn: (data) => quizService.reportQuestion(data),
    onSuccess: () => {
      toast.success('Report submitted successfully!')
      setReportModalOpen(false)
      setReportingQuestion(null)
      setReportType('')
      setReportDescription('')
    },
    onError: (error) => {
      toast.error(error.response?.data?.error || 'Failed to submit report')
    },
  })

  const handleReport = (question) => {
    setReportingQuestion(question)
    setReportModalOpen(true)
  }

  const submitReport = () => {
    if (!reportType) {
      toast.error('Please select a report type')
      return
    }
    if (!reportDescription.trim()) {
      toast.error('Please describe the issue')
      return
    }

    reportMutation.mutate({
      question: reportingQuestion.id,
      report_type: reportType,
      description: reportDescription,
    })
  }

  if (isLoading) return <Loading fullScreen />

  if (error) {
    return (
      <div className="text-center py-12">
        <div className="flex justify-center mb-4 text-error-500">
          <XCircle size={48} />
        </div>
        <p className="text-surface-500">Failed to load attempt details</p>
        <button onClick={() => navigate('/quiz')} className="btn-primary mt-4">
          Back to Quizzes
        </button>
      </div>
    )
  }

  const getScoreColor = (percentage) => {
    if (percentage >= 70) return 'text-success-500'
    if (percentage >= 40) return 'text-warning-500'
    return 'text-error-500'
  }

  const getScoreBg = (percentage) => {
    if (percentage >= 70) return 'from-success-500 to-success-600'
    if (percentage >= 40) return 'from-warning-500 to-warning-600'
    return 'from-error-500 to-error-600'
  }

  // Use the new all_questions structure
  const allQuestions = attempt?.all_questions || []

  // Filter questions based on selected filter
  const filteredQuestions = allQuestions.filter(q => {
    if (filter === 'all') return true
    return q.status === filter
  })

  const questionCounts = {
    all: allQuestions.length,
    correct: allQuestions.filter(q => q.status === 'correct').length,
    wrong: allQuestions.filter(q => q.status === 'wrong').length,
    skipped: allQuestions.filter(q => q.status === 'skipped').length,
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <button
            onClick={goBackToCourse}
            className="flex items-center gap-1 text-surface-500 hover:text-surface-700 mb-2"
          >
            <ChevronLeft size={18} />
            Back to Course
          </button>
          <h1 className="text-2xl font-display font-bold">Quiz Review</h1>
          <p className="text-surface-500 mt-1">{attempt?.quiz_title}</p>
        </div>
        <button
          onClick={() => navigate(`/quiz/${attempt?.quiz}`, { state: courseCtx })}
          className="btn-primary"
        >
          Retry Quiz
        </button>
      </div>

      {/* Score Card */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className={`card p-6 bg-gradient-to-r ${getScoreBg(attempt?.percentage)} text-white`}
      >
        <div className="flex items-center justify-between">
          <div>
            <p className="text-white/80">Your Score</p>
            <p className="text-4xl font-bold">{Math.round(attempt?.percentage || 0)}%</p>
            <p className="text-white/70 mt-1">
              {attempt?.marks_obtained || 0} / {attempt?.total_marks || 0} marks
            </p>
          </div>
          <div className="text-right">
            <div className="flex items-center gap-4">
              <div>
                <p className="text-white/80 text-sm">Time Taken</p>
                <p className="text-xl font-semibold">
                  {Math.floor((attempt?.time_taken_seconds || 0) / 60)}:{String((attempt?.time_taken_seconds || 0) % 60).padStart(2, '0')}
                </p>
              </div>
              <div>
                <p className="text-white/80 text-sm">XP Earned</p>
                <p className="text-xl font-semibold">+{attempt?.xp_earned || 0}</p>
              </div>
            </div>
          </div>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-4 gap-4 mt-6 pt-6 border-t border-white/20">
          <div className="text-center">
            <p className="text-2xl font-bold">{attempt?.correct_answers || 0}</p>
            <p className="text-white/70 text-sm">Correct</p>
          </div>
          <div className="text-center">
            <p className="text-2xl font-bold">{attempt?.wrong_answers || 0}</p>
            <p className="text-white/70 text-sm">Wrong</p>
          </div>
          <div className="text-center">
            <p className="text-2xl font-bold">{attempt?.skipped_questions || 0}</p>
            <p className="text-white/70 text-sm">Skipped</p>
          </div>
          <div className="text-center">
            <p className="text-2xl font-bold">{attempt?.marks_obtained || 0}/{attempt?.total_marks || 0}</p>
            <p className="text-white/70 text-sm">Marks</p>
          </div>
        </div>
      </motion.div>

      {/* Quiz Leaderboard */}
      {leaderboard && leaderboard.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="card p-5"
        >
          <div className="flex items-center gap-2 mb-4">
            <Trophy size={20} className="text-warning-500" />
            <h2 className="font-semibold text-lg">Quiz Leaderboard</h2>
            <span className="text-sm text-surface-500">Top scores</span>
          </div>

          <div className="space-y-2">
            {leaderboard.map((entry) => (
              <div
                key={entry.rank}
                className={`p-3 rounded-xl flex items-center gap-3 border ${
                  entry.is_current_user
                    ? 'border-primary-300 bg-primary-50/60 dark:border-primary-700 dark:bg-primary-900/20'
                    : 'border-surface-200 dark:border-surface-700'
                }`}
              >
                <div className={`w-9 h-9 rounded-full flex items-center justify-center font-bold text-sm flex-shrink-0 ${
                  entry.rank === 1 ? 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-400' :
                  entry.rank === 2 ? 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300' :
                  entry.rank === 3 ? 'bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-400' :
                  'bg-surface-100 dark:bg-surface-800 text-surface-500'
                }`}>
                  {entry.rank <= 3 ? ['🥇', '🥈', '🥉'][entry.rank - 1] : `#${entry.rank}`}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="font-medium truncate">
                    {entry.student_name}
                    {entry.is_current_user && (
                      <span className="text-xs text-primary-600 dark:text-primary-400 ml-2">(You)</span>
                    )}
                  </p>
                  <div className="flex items-center gap-2 text-xs text-surface-500 mt-0.5">
                    <span className={getScoreColor(entry.accuracy)}>{Math.round(entry.accuracy)}%</span>
                    {entry.time_taken_seconds > 0 && (
                      <>
                        <span>•</span>
                        <span className="flex items-center gap-1">
                          <Clock size={12} />
                          {Math.floor(entry.time_taken_seconds / 60)}:{String(entry.time_taken_seconds % 60).padStart(2, '0')}
                        </span>
                      </>
                    )}
                  </div>
                </div>
                {entry.total_marks > 0 && (
                  <div className="text-right flex-shrink-0">
                    <p className="font-bold text-sm">{entry.marks_obtained}<span className="text-surface-400 font-normal">/{entry.total_marks}</span></p>
                    <p className="text-xs text-surface-500">marks</p>
                  </div>
                )}
              </div>
            ))}
          </div>
        </motion.div>
      )}

      {/* Filter Tabs */}
      <div className="flex gap-2 overflow-x-auto pb-2 scrollbar-hide">
        {[
          { value: 'all', label: 'All', color: 'bg-primary-500' },
          { value: 'correct', label: 'Correct', color: 'bg-success-500' },
          { value: 'wrong', label: 'Wrong', color: 'bg-error-500' },
          { value: 'skipped', label: 'Skipped', color: 'bg-surface-400' },
        ].map((tab) => (
          <button
            key={tab.value}
            onClick={() => setFilter(tab.value)}
            className={`px-4 py-2 rounded-full whitespace-nowrap transition-colors flex items-center gap-2 ${filter === tab.value
              ? `${tab.color} text-white`
              : 'bg-surface-100 dark:bg-surface-800 hover:bg-surface-200 dark:hover:bg-surface-700'
              }`}
          >
            {tab.label}
            <span className={`text-xs px-1.5 py-0.5 rounded-full ${filter === tab.value
              ? 'bg-white/20'
              : 'bg-surface-200 dark:bg-surface-700'
              }`}>
              {questionCounts[tab.value]}
            </span>
          </button>
        ))}
      </div>

      {/* Questions Review */}
      <div className="card p-5">
        <h2 className="font-semibold text-lg mb-4">Question-wise Review</h2>

        <div className="space-y-6">
          {filteredQuestions.map((item, index) => {
            const question = item.question
            const userAnswer = item.user_answer
            const questionStatus = item.status
            const isCorrect = questionStatus === 'correct'
            const isSkipped = questionStatus === 'skipped'
            const reviewKey = `bank:${question?.id}`
            const showWhatHappened = selfReports.enabled && !isCorrect && question?.id &&
              !selfReports.notSeen.has(reviewKey)
            const selectedOption = userAnswer?.selected_option

            let borderClass = ''
            let bgClass = ''
            let statusText = ''
            let statusIcon = ''

            if (isCorrect) {
              borderClass = 'border-success-200'
              bgClass = 'bg-success-50 dark:bg-success-900/10'
              statusText = '✓ Correct'
              statusIcon = 'bg-success-500'
            } else if (isSkipped) {
              borderClass = 'border-surface-300'
              bgClass = 'bg-surface-50 dark:bg-surface-800/50'
              statusText = '○ Skipped'
              statusIcon = 'bg-surface-400'
            } else {
              borderClass = 'border-error-200'
              bgClass = 'bg-error-50 dark:bg-error-900/10'
              statusText = '✗ Incorrect'
              statusIcon = 'bg-error-500'
            }

            return (
              <motion.div
                key={question.id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: index * 0.03 }}
                className={`p-4 rounded-xl border-2 ${borderClass} ${bgClass}`}
              >
                {/* Question Header */}
                <div className="flex items-start justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <span className={`w-8 h-8 rounded-full flex items-center justify-center text-white text-sm font-bold ${statusIcon}`}>
                      {item.question_number}
                    </span>
                    <span className={`text-sm font-medium ${isCorrect ? 'text-success-600' : isSkipped ? 'text-surface-500' : 'text-error-600'
                      }`}>
                      {statusText}
                    </span>
                  </div>
                  <div className="flex items-center gap-3">
                    {!isSkipped && (
                      <div className="flex items-center gap-2 text-sm text-surface-500">
                        <span>{userAnswer?.time_taken_seconds || 0}s</span>
                        <span>•</span>
                        <span className={isCorrect ? 'text-success-600' : 'text-error-600'}>
                          {(userAnswer?.marks_obtained || 0) > 0 ? '+' : ''}{userAnswer?.marks_obtained || 0} marks
                        </span>
                      </div>
                    )}
                    <button
                      onClick={() => handleReport(question)}
                      className="text-surface-400 hover:text-error-500 transition-colors p-1"
                      title="Report a problem"
                    >
                      <AlertTriangle size={18} />
                    </button>
                  </div>
                </div>

                {/* Question Text */}
                <div className="mb-4">
                  <p className="font-medium text-surface-900 dark:text-surface-100">
                    {question?.question_text || question?.question_html}
                  </p>
                  {question?.question_image && (
                    <img
                      src={question.question_image}
                      alt="Question"
                      className="mt-2 max-w-sm rounded-lg"
                    />
                  )}
                </div>

                {/* Options */}
                <div className="space-y-2">
                  {(question?.options || []).map((option, optIndex) => {
                    const isSelected = selectedOption === String(optIndex) || selectedOption === option.id
                    const isCorrectOption = option.is_correct

                    let optionClass = 'bg-surface-100 dark:bg-surface-800'
                    if (isCorrectOption) {
                      optionClass = 'bg-success-100 dark:bg-success-900/30 border-success-500'
                    } else if (isSelected && !isCorrectOption) {
                      optionClass = 'bg-error-100 dark:bg-error-900/30 border-error-500'
                    }

                    return (
                      <div
                        key={option.id || optIndex}
                        className={`p-3 rounded-lg border-2 ${optionClass} ${isSelected || isCorrectOption ? 'border-2' : 'border-transparent'
                          }`}
                      >
                        <div className="flex items-center gap-3">
                          <span className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold ${isCorrectOption
                            ? 'bg-success-500 text-white'
                            : isSelected
                              ? 'bg-error-500 text-white'
                              : 'bg-surface-300 dark:bg-surface-600 text-surface-600 dark:text-surface-300'
                            }`}>
                            {String.fromCharCode(65 + optIndex)}
                          </span>
                          <span className={`flex-1 ${isCorrectOption ? 'font-medium text-success-700 dark:text-success-400' : ''
                            }`}>
                            {option.option_text}
                          </span>
                          {isCorrectOption && (
                            <span className="text-success-500 text-sm flex items-center gap-1">
                              <CheckCircle2 size={14} /> Correct Answer
                            </span>
                          )}
                          {isSelected && !isCorrectOption && (
                            <span className="text-error-500 text-sm">Your Answer</span>
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>

                {/* Explanation */}
                {(question?.explanation || question?.explanation_image) && (
                  <div className="mt-4 p-3 rounded-lg bg-primary-50 dark:bg-primary-900/20 border border-primary-200 dark:border-primary-800">
                    <p className="text-sm font-medium text-primary-700 dark:text-primary-300 mb-1 flex items-center gap-1.5">
                      <Lightbulb size={16} /> Explanation
                    </p>
                    {question.explanation && (
                      <p className="text-sm text-primary-600 dark:text-primary-400">
                        {question.explanation}
                      </p>
                    )}
                    {question.explanation_image && (
                      <img src={question.explanation_image} alt="Explanation" className="mt-2 max-h-64 rounded-lg" />
                    )}
                  </div>
                )}

                {/* Topic Tag */}
                {question?.topic_name && (
                  <div className="mt-3 flex items-center gap-2">
                    <span className="text-xs text-surface-500">Topic:</span>
                    <span className="badge bg-surface-200 dark:bg-surface-700 text-xs">
                      {question.topic_name}
                    </span>
                    {question?.subject_name && (
                      <span className="badge bg-surface-200 dark:bg-surface-700 text-xs">
                        {question.subject_name}
                      </span>
                    )}
                  </div>
                )}
                {showWhatHappened && (
                  <WhatHappened
                    attemptKind="quiz"
                    attemptId={attemptId}
                    itemKind="bank"
                    itemId={question.id}
                    initial={selfReports.reports[reviewKey]}
                  />
                )}
              </motion.div>
            )
          })}
        </div>

        {filteredQuestions.length === 0 && (
          <div className="text-center py-8 text-surface-500">
            No questions match this filter
          </div>
        )}
      </div>

      {/* Bottom Actions */}
      <div className="flex gap-4 justify-center pb-8">
        <button
          onClick={goBackToCourse}
          className="btn-secondary"
        >
          Back to Course
        </button>
        <button
          onClick={() => navigate(`/quiz/${attempt?.quiz}`, { state: courseCtx })}
          className="btn-primary"
        >
          Retry This Quiz
        </button>
      </div>

      {/* Report Modal */}
      <AnimatePresence>
        {reportModalOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
            onClick={() => setReportModalOpen(false)}
          >
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="bg-white dark:bg-surface-900 rounded-2xl p-6 max-w-md w-full shadow-xl"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold">Report a Problem</h3>
                <button
                  onClick={() => setReportModalOpen(false)}
                  className="text-surface-400 hover:text-surface-600"
                >
                  <X size={20} />
                </button>
              </div>

              <p className="text-sm text-surface-500 mb-4">
                Help us improve by reporting issues with this question.
              </p>

              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium mb-2">Issue Type</label>
                  <select
                    value={reportType}
                    onChange={(e) => setReportType(e.target.value)}
                    className="input w-full"
                  >
                    <option value="">Select an issue type</option>
                    {REPORT_TYPES.map((type) => (
                      <option key={type.value} value={type.value}>
                        {type.label}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-sm font-medium mb-2">Description</label>
                  <textarea
                    value={reportDescription}
                    onChange={(e) => setReportDescription(e.target.value)}
                    placeholder="Please describe the issue in detail..."
                    rows={4}
                    className="input w-full resize-none"
                  />
                </div>

                <div className="flex gap-3 pt-2">
                  <button
                    onClick={() => setReportModalOpen(false)}
                    className="btn-secondary flex-1"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={submitReport}
                    disabled={reportMutation.isPending}
                    className="btn-primary flex-1"
                  >
                    {reportMutation.isPending ? 'Submitting...' : 'Submit Report'}
                  </button>
                </div>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

export default QuizReview
