import { useState, useMemo, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { useQuery } from '@tanstack/react-query'
import { quizService } from '../services/quizService'
import { useFeatureLabel } from '../context/tenantStore'
import Loading from '../components/common/Loading'
import SearchableSelect from '../components/common/SearchableSelect'
import {
  Filter,
  Search,
  CheckCircle2,
  Sparkles,
  Target,
  BookOpen,
  Book,
  Shuffle,
  History,
  FileText,
  PenTool,
  Clock,
  Award,
  ChevronRight
} from 'lucide-react'

const Quiz = () => {
  const navigate = useNavigate()
  const quizLabel = useFeatureLabel('quiz', 'Practice Quiz')
  const [showFilters, setShowFilters] = useState(false)

  // Filter state. Course defaults to '' (All courses) so quizzes from every
  // enrolled course are visible by default — otherwise a quiz created in a
  // course other than the last-used one stays hidden until manually selected.
  const [filters, setFilters] = useState({
    course: '',
    quiz_type: '',
    subject: '',
    topic: '',
    attempted: '', // '', 'true', 'false'
    difficulty: '',
    search: '',
  })

  // Build query params
  const queryParams = useMemo(() => {
    const params = {}
    if (filters.course) params.course = filters.course
    if (filters.quiz_type) params.quiz_type = filters.quiz_type
    if (filters.subject) params.subject = filters.subject
    if (filters.topic) params.topic = filters.topic
    if (filters.attempted) params.attempted = filters.attempted
    if (filters.difficulty) params.difficulty = filters.difficulty
    if (filters.search) params.search = filters.search
    return params
  }, [filters])

  const { data: quizzes, isLoading } = useQuery({
    queryKey: ['quizzes', queryParams],
    queryFn: () => quizService.getQuizzes(queryParams),
  })

  const { data: filterOptions } = useQuery({
    queryKey: ['quizFilterOptions'],
    queryFn: () => quizService.getFilterOptions(),
  })

  const { data: dailyChallenge } = useQuery({
    queryKey: ['dailyChallenge', filters.course],
    queryFn: () => quizService.getDailyChallenge(filters.course || undefined),
  })

  const { data: recentAttempts } = useQuery({
    queryKey: ['recentAttempts'],
    queryFn: () => quizService.getRecentAttempts(),
  })

  // Persist a specific course selection for cross-page context, but never force
  // one — an empty selection ("All courses") is a valid, respected state.
  useEffect(() => {
    if (filters.course) localStorage.setItem('study:lastCourseId', filters.course)
  }, [filters.course])

  // Subjects scoped to selected exam
  const examSubjects = useMemo(() => {
    if (!filterOptions?.subjects) return []
    if (!filters.course) return filterOptions.subjects
    return filterOptions.subjects.filter((s) => s.course_id === filters.course)
  }, [filterOptions?.subjects, filters.course])

  // Filter topics based on selected exam + subject
  const filteredTopics = useMemo(() => {
    if (!filterOptions?.topics) return []
    let topics = filterOptions.topics
    if (filters.course) topics = topics.filter((t) => t.course_id === filters.course)
    if (filters.subject) topics = topics.filter((t) => t.subject_id === filters.subject)
    return topics
  }, [filterOptions?.topics, filters.course, filters.subject])

  const handleStartQuiz = async (quizId) => {
    try {
      await quizService.startQuiz(quizId)
      navigate(`/quiz/${quizId}`)
    } catch (error) {
      console.error('Failed to start quiz:', error)
    }
  }

  const updateFilter = (key, value) => {
    setFilters(prev => {
      const newFilters = { ...prev, [key]: value }
      // Reset dependent filters
      if (key === 'subject') {
        newFilters.topic = ''
      }
      if (key === 'course') {
        newFilters.subject = ''
        newFilters.topic = ''
      }
      return newFilters
    })
  }

  const clearFilters = () => {
    setFilters((prev) => ({
      course: prev.course, // keep course context
      quiz_type: '',
      subject: '',
      topic: '',
      attempted: '',
      difficulty: '',
      search: '',
    }))
  }

  const activeFilterCount = Object.entries(filters)
    .filter(([k, v]) => k !== 'course' && Boolean(v)).length

  const quizTypeIcons = {
    topic: <Book size={18} />,
    subject: <BookOpen size={18} />,
    mixed: <Shuffle size={18} />,
    pyq: <History size={18} />,
    daily: <Target size={18} />,
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-display font-bold">{quizLabel}</h1>
          <p className="text-surface-500 mt-1">Test your knowledge and earn XP</p>
        </div>
        <button
          onClick={() => setShowFilters(!showFilters)}
          className={`btn-secondary flex items-center gap-2 ${showFilters ? 'bg-primary-100 dark:bg-primary-900/30' : ''}`}
        >
          <Filter size={18} />
          Filters
          {activeFilterCount > 0 && (
            <span className="w-5 h-5 rounded-full bg-primary-500 text-white text-xs flex items-center justify-center">
              {activeFilterCount}
            </span>
          )}
        </button>
      </div>

      {/* Daily Challenge Banner */}
      {dailyChallenge && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="card p-6 bg-gradient-to-r from-primary-500 to-accent-500 text-white"
        >
          <div className="flex items-center justify-between">
            <div>
              <div className="flex flex-wrap items-center gap-2 mb-2">
                <span className="px-2 py-0.5 bg-white/20 rounded-full text-xs font-medium flex items-center gap-1">
                  <Target size={12} /> Daily Challenge
                </span>
                <span className="px-2 py-0.5 bg-white/20 rounded-full text-xs font-medium">
                  +{dailyChallenge.total_marks * 5} XP
                </span>
                {dailyChallenge.user_attempt_info?.attempted && (
                  <span className="px-2 py-0.5 bg-white/30 rounded-full text-xs font-medium flex items-center gap-1">
                    <CheckCircle2 size={12} /> Best: {Math.round(dailyChallenge.user_attempt_info.best_score)}%
                  </span>
                )}
              </div>
              <h2 className="text-xl font-semibold">{dailyChallenge.title}</h2>
              <p className="text-white/80 mt-1">
                {dailyChallenge.questions_count} questions • {dailyChallenge.duration_minutes} minutes
              </p>
            </div>
            <div className="flex gap-2">
              {dailyChallenge.user_attempt_info?.attempted && (
                <button
                  onClick={() => navigate(`/quiz/review/${dailyChallenge.user_attempt_info.best_attempt_id}`)}
                  className="btn bg-white/20 text-white hover:bg-white/30"
                >
                  View Result
                </button>
              )}
              <button
                onClick={() => handleStartQuiz(dailyChallenge.id)}
                className="btn bg-white text-primary-600 hover:bg-white/90"
              >
                {dailyChallenge.user_attempt_info?.attempted ? 'Retry' : 'Start Now'}
              </button>
            </div>
          </div>
        </motion.div>
      )}

      {/* Filters Panel */}
      <AnimatePresence>
        {showFilters && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="overflow-hidden"
          >
            <div className="card p-5 space-y-4">
              {/* Search */}
              <div>
                <label className="block text-sm font-medium mb-2">Search</label>
                <div className="relative">
                  <Search size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-surface-400" />
                  <input
                    type="text"
                    value={filters.search}
                    onChange={(e) => updateFilter('search', e.target.value)}
                    placeholder="Search quizzes..."
                    className="input pl-10 w-full"
                  />
                </div>
              </div>

              {/* Course Filter */}
              {filterOptions?.courses?.length > 1 && (
                <div>
                  <label className="block text-sm font-medium mb-2">Course</label>
                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      onClick={() => updateFilter('course', '')}
                      className={`px-4 py-2 rounded-full text-sm font-medium transition-all ${filters.course === ''
                          ? 'bg-primary-500 text-white'
                          : 'bg-surface-100 dark:bg-surface-800 hover:bg-surface-200 dark:hover:bg-surface-700'
                        }`}
                    >
                      All courses
                    </button>
                    <SearchableSelect
                      options={filterOptions.courses.map((c) => ({ value: c.id, label: c.name }))}
                      value={filters.course}
                      onChange={(val) => updateFilter('course', val || '')}
                      placeholder="Filter by course"
                      searchPlaceholder="Search courses..."
                      buttonClassName={`px-4 py-2 rounded-full text-sm font-medium transition-all border ${filters.course
                          ? 'bg-primary-500 text-white border-primary-500'
                          : 'bg-surface-100 dark:bg-surface-800 border-surface-200 dark:border-surface-700 hover:bg-surface-200 dark:hover:bg-surface-700'
                        }`}
                    />
                  </div>
                </div>
              )}

              {/* Quick Filters - Attempt Status */}
              <div>
                <label className="block text-sm font-medium mb-2">Status</label>
                <div className="flex flex-wrap gap-2">
                  <button
                    onClick={() => updateFilter('attempted', filters.attempted === '' ? '' : '')}
                    className={`px-4 py-2 rounded-full text-sm font-medium transition-all ${filters.attempted === ''
                        ? 'bg-primary-500 text-white'
                        : 'bg-surface-100 dark:bg-surface-800 hover:bg-surface-200 dark:hover:bg-surface-700'
                      }`}
                  >
                    All Quizzes
                    {filterOptions?.attempt_status && (
                      <span className="ml-1 opacity-70">
                        ({filterOptions.attempt_status.attempted + filterOptions.attempt_status.not_attempted})
                      </span>
                    )}
                  </button>
                  <button
                    onClick={() => updateFilter('attempted', filters.attempted === 'true' ? '' : 'true')}
                    className={`px-4 py-2 rounded-full text-sm font-medium transition-all flex items-center gap-2 ${filters.attempted === 'true'
                        ? 'bg-success-500 text-white'
                        : 'bg-surface-100 dark:bg-surface-800 hover:bg-surface-200 dark:hover:bg-surface-700'
                      }`}
                  >
                    <CheckCircle2 size={16} />
                    Attempted
                    {filterOptions?.attempt_status && (
                      <span className="opacity-70">({filterOptions.attempt_status.attempted})</span>
                    )}
                  </button>
                  <button
                    onClick={() => updateFilter('attempted', filters.attempted === 'false' ? '' : 'false')}
                    className={`px-4 py-2 rounded-full text-sm font-medium transition-all flex items-center gap-2 ${filters.attempted === 'false'
                        ? 'bg-warning-500 text-white'
                        : 'bg-surface-100 dark:bg-surface-800 hover:bg-surface-200 dark:hover:bg-surface-700'
                      }`}
                  >
                    <Sparkles size={16} />
                    Not Attempted
                    {filterOptions?.attempt_status && (
                      <span className="opacity-70">({filterOptions.attempt_status.not_attempted})</span>
                    )}
                  </button>
                </div>
              </div>

              {/* Quiz Type Filter */}
              <div>
                <label className="block text-sm font-medium mb-2">Quiz Type</label>
                <div className="flex flex-wrap gap-2">
                  <button
                    onClick={() => updateFilter('quiz_type', '')}
                    className={`px-4 py-2 rounded-full text-sm font-medium transition-all ${filters.quiz_type === ''
                        ? 'bg-primary-500 text-white'
                        : 'bg-surface-100 dark:bg-surface-800 hover:bg-surface-200 dark:hover:bg-surface-700'
                      }`}
                  >
                    All Types
                  </button>
                  {filterOptions?.quiz_types?.map((type) => (
                    <button
                      key={type.value}
                      onClick={() => updateFilter('quiz_type', filters.quiz_type === type.value ? '' : type.value)}
                      className={`px-4 py-2 rounded-full text-sm font-medium transition-all flex items-center gap-2 ${filters.quiz_type === type.value
                          ? 'bg-primary-500 text-white'
                          : 'bg-surface-100 dark:bg-surface-800 hover:bg-surface-200 dark:hover:bg-surface-700'
                        }`}
                    >
                      {quizTypeIcons[type.value] || <FileText size={16} />}
                      {type.label}
                      {type.count > 0 && <span className="opacity-70">({type.count})</span>}
                    </button>
                  ))}
                </div>
              </div>

              {/* Subject & Topic Filters */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium mb-2">Subject</label>
                  <select
                    value={filters.subject}
                    onChange={(e) => updateFilter('subject', e.target.value)}
                    className="input w-full"
                  >
                    <option value="">All Subjects</option>
                    {examSubjects.map((subject) => (
                      <option key={subject.id} value={subject.id}>
                        {subject.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium mb-2">Topic</label>
                  <select
                    value={filters.topic}
                    onChange={(e) => updateFilter('topic', e.target.value)}
                    className="input w-full"
                    disabled={!filters.subject}
                  >
                    <option value="">{filters.subject ? 'All Topics' : 'Select subject first'}</option>
                    {filteredTopics.map((topic) => (
                      <option key={topic.id} value={topic.id}>
                        {topic.name}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              {/* Difficulty Filter */}
              <div>
                <label className="block text-sm font-medium mb-2">Difficulty</label>
                <div className="flex flex-wrap gap-2">
                  <button
                    onClick={() => updateFilter('difficulty', '')}
                    className={`px-4 py-2 rounded-full text-sm font-medium transition-all ${filters.difficulty === ''
                        ? 'bg-primary-500 text-white'
                        : 'bg-surface-100 dark:bg-surface-800 hover:bg-surface-200 dark:hover:bg-surface-700'
                      }`}
                  >
                    All Levels
                  </button>
                  <button
                    onClick={() => updateFilter('difficulty', filters.difficulty === 'easy' ? '' : 'easy')}
                    className={`px-4 py-2 rounded-full text-sm font-medium transition-all flex items-center gap-2 ${filters.difficulty === 'easy'
                        ? 'bg-success-500 text-white'
                        : 'bg-surface-100 dark:bg-surface-800 hover:bg-surface-200 dark:hover:bg-surface-700'
                      }`}
                  >
                    <div className="w-2 h-2 rounded-full bg-success-500" /> Easy
                  </button>
                  <button
                    onClick={() => updateFilter('difficulty', filters.difficulty === 'medium' ? '' : 'medium')}
                    className={`px-4 py-2 rounded-full text-sm font-medium transition-all flex items-center gap-2 ${filters.difficulty === 'medium'
                        ? 'bg-warning-500 text-white'
                        : 'bg-surface-100 dark:bg-surface-800 hover:bg-surface-200 dark:hover:bg-surface-700'
                      }`}
                  >
                    <div className="w-2 h-2 rounded-full bg-warning-500" /> Medium
                  </button>
                  <button
                    onClick={() => updateFilter('difficulty', filters.difficulty === 'hard' ? '' : 'hard')}
                    className={`px-4 py-2 rounded-full text-sm font-medium transition-all flex items-center gap-2 ${filters.difficulty === 'hard'
                        ? 'bg-error-500 text-white'
                        : 'bg-surface-100 dark:bg-surface-800 hover:bg-surface-200 dark:hover:bg-surface-700'
                      }`}
                  >
                    <div className="w-2 h-2 rounded-full bg-error-500" /> Hard
                  </button>
                </div>
              </div>

              {/* Clear Filters */}
              {activeFilterCount > 0 && (
                <div className="flex justify-end">
                  <button
                    onClick={clearFilters}
                    className="text-sm text-primary-500 hover:text-primary-600 font-medium"
                  >
                    Clear all filters
                  </button>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Active Filters Summary (when filter panel is closed) */}
      {!showFilters && activeFilterCount > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm text-surface-500">Active filters:</span>
          {filters.attempted === 'true' && (
            <span className="badge badge-success flex items-center gap-1">
              <CheckCircle2 size={12} /> Attempted
              <button onClick={() => updateFilter('attempted', '')} className="ml-1 hover:text-white">×</button>
            </span>
          )}
          {filters.attempted === 'false' && (
            <span className="badge badge-warning flex items-center gap-1">
              <Sparkles size={12} /> Not Attempted
              <button onClick={() => updateFilter('attempted', '')} className="ml-1 hover:text-white">×</button>
            </span>
          )}
          {filters.quiz_type && (
            <span className="badge badge-primary flex items-center gap-1">
              {quizTypeIcons[filters.quiz_type]} {filters.quiz_type}
              <button onClick={() => updateFilter('quiz_type', '')} className="ml-1 hover:text-white">×</button>
            </span>
          )}
          {filters.subject && (
            <span className="badge bg-surface-200 dark:bg-surface-700 flex items-center gap-1">
              <BookOpen size={12} /> {filterOptions?.subjects?.find(s => s.id === filters.subject)?.name}
              <button onClick={() => updateFilter('subject', '')} className="ml-1 hover:opacity-70">×</button>
            </span>
          )}
          {filters.topic && (
            <span className="badge bg-surface-200 dark:bg-surface-700 flex items-center gap-1">
              <Book size={12} /> {filterOptions?.topics?.find(t => t.id === filters.topic)?.name}
              <button onClick={() => updateFilter('topic', '')} className="ml-1 hover:opacity-70">×</button>
            </span>
          )}
          {filters.difficulty && (
            <span className={`badge flex items-center gap-1 ${filters.difficulty === 'easy' ? 'badge-success' :
                filters.difficulty === 'medium' ? 'badge-warning' : 'badge-error'
              }`}>
              <div className={`w-1.5 h-1.5 rounded-full ${filters.difficulty === 'easy' ? 'bg-white' :
                  filters.difficulty === 'medium' ? 'bg-white' : 'bg-white'
                }`} /> {filters.difficulty}
              <button onClick={() => updateFilter('difficulty', '')} className="ml-1 hover:text-white">×</button>
            </span>
          )}
          {filters.search && (
            <span className="badge bg-surface-200 dark:bg-surface-700 flex items-center gap-1">
              <Search size={12} /> "{filters.search}"
              <button onClick={() => updateFilter('search', '')} className="ml-1 hover:opacity-70">×</button>
            </span>
          )}
          <button
            onClick={clearFilters}
            className="text-sm text-primary-500 hover:text-primary-600 font-medium ml-2"
          >
            Clear all
          </button>
        </div>
      )}

      {/* Results Count */}
      <div className="text-sm text-surface-500">
        {isLoading ? 'Loading...' : `${(quizzes?.results || quizzes || []).length} quizzes found`}
      </div>

      {/* Quiz Grid */}
      {isLoading ? (
        <Loading />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {(quizzes?.results || quizzes || []).map((quiz) => {
            const attemptInfo = quiz.user_attempt_info
            const hasAttempted = attemptInfo?.attempted

            return (
              <motion.div
                key={quiz.id}
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                whileHover={{ scale: 1.02 }}
                className={`card p-5 ${hasAttempted ? 'ring-2 ring-primary-200 dark:ring-primary-800' : ''}`}
              >
                <div className="flex items-start justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <div className="p-2 rounded-lg bg-surface-100 dark:bg-surface-800 text-primary-500">
                      {quizTypeIcons[quiz.quiz_type] || <PenTool size={20} />}
                    </div>
                    <span className={`badge ${quiz.quiz_type === 'daily' ? 'badge-primary' :
                        quiz.quiz_type === 'pyq' ? 'badge-warning' : 'badge-success'
                      }`}>
                      {quiz.quiz_type}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    {hasAttempted && (
                      <span className={`badge ${attemptInfo.best_score >= 70 ? 'badge-success' :
                          attemptInfo.best_score >= 40 ? 'badge-warning' : 'badge-error'
                        }`}>
                        Best: {Math.round(attemptInfo.best_score)}%
                      </span>
                    )}
                    {quiz.is_free && !hasAttempted && (
                      <span className="badge-success">Free</span>
                    )}
                  </div>
                </div>

                <h3 className="font-semibold mb-2 line-clamp-2">{quiz.title}</h3>

                <div className="flex items-center gap-4 text-sm text-surface-500 mb-4">
                  <span>{quiz.questions_count} Qs</span>
                  <span>•</span>
                  <span>{quiz.duration_minutes} min</span>
                  <span>•</span>
                  <span>{quiz.total_marks} marks</span>
                  {hasAttempted && (
                    <>
                      <span>•</span>
                      <span className="text-primary-500">{attemptInfo.attempts_count} attempt{attemptInfo.attempts_count > 1 ? 's' : ''}</span>
                    </>
                  )}
                </div>

                {quiz.subject_name && (
                  <div className="flex items-center gap-2 mb-4">
                    <span className="badge bg-surface-100 dark:bg-surface-800 text-xs">
                      {quiz.subject_name}
                    </span>
                    {quiz.topic_name && (
                      <span className="badge bg-surface-100 dark:bg-surface-800 text-xs">
                        {quiz.topic_name}
                      </span>
                    )}
                  </div>
                )}

                {hasAttempted ? (
                  <div className="flex items-center justify-between gap-2">
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        navigate(`/quiz/review/${attemptInfo.best_attempt_id}`)
                      }}
                      className="btn-secondary text-sm px-4 py-2 flex-1"
                    >
                      View Result
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        handleStartQuiz(quiz.id)
                      }}
                      className="btn-primary text-sm px-4 py-2 flex-1"
                    >
                      Retry
                    </button>
                  </div>
                ) : (
                  <div className="flex items-center justify-between">
                    <div className="text-sm">
                      <span className="text-surface-500">Avg Score: </span>
                      <span className="font-medium">{Math.round(quiz.average_score || 0)}%</span>
                    </div>
                    <button
                      onClick={() => handleStartQuiz(quiz.id)}
                      className="btn-primary text-sm px-4 py-2"
                    >
                      Start Quiz
                    </button>
                  </div>
                )}
              </motion.div>
            )
          })}
        </div>
      )}

      {/* Empty State */}
      {!isLoading && (quizzes?.results || quizzes || []).length === 0 && (
        <div className="text-center py-12">
          <div className="flex justify-center mb-4 text-surface-300">
            <Search size={64} />
          </div>
          <p className="text-surface-500">No quizzes found matching your filters</p>
          <button onClick={clearFilters} className="btn-primary mt-4">
            Clear Filters
          </button>
        </div>
      )}

      {/* Recent Attempts */}
      {recentAttempts?.length > 0 && (
        <div className="card p-5">
          <h3 className="font-semibold mb-4">Recent Attempts</h3>
          <div className="space-y-3">
            {recentAttempts.slice(0, 5).map((attempt) => (
              <div
                key={attempt.id}
                className="flex items-center justify-between p-3 rounded-xl bg-surface-50 dark:bg-surface-800"
              >
                <div>
                  <p className="font-medium">{attempt.quiz_title}</p>
                  <p className="text-sm text-surface-500">
                    {new Date(attempt.completed_at).toLocaleDateString()}
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <div className="text-right">
                    <p className={`font-bold ${attempt.percentage >= 70 ? 'text-success-500' :
                        attempt.percentage >= 40 ? 'text-warning-500' : 'text-error-500'
                      }`}>
                      {Math.round(attempt.percentage)}%
                    </p>
                    <p className="text-sm text-surface-500">
                      {attempt.correct_answers}/{attempt.total_questions}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => navigate(`/quiz/review/${attempt.id}`)}
                      className="btn-secondary text-xs px-3 py-1.5"
                    >
                      View Result
                    </button>
                    <button
                      onClick={() => handleStartQuiz(attempt.quiz)}
                      className="btn-primary text-xs px-3 py-1.5"
                    >
                      Retry
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default Quiz
