import { useState, useMemo, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { useQuery } from '@tanstack/react-query'
import { quizService } from '../services/quizService'
import { useAuthStore } from '../context/authStore'
import { useFeatureLabel } from '../context/tenantStore'
import Loading from '../components/common/Loading'
import {
  Filter,
  Search,
  CheckCircle2,
  Sparkles,
  BadgePercent,
  Star,
  ChevronRight,
  TrendingUp,
  Clock,
  Award,
  Settings2
} from 'lucide-react'

const MockTest = () => {
  const navigate = useNavigate()
  const mockLabel = useFeatureLabel('mock_tests', 'Mock Tests')
  const { user, profile } = useAuthStore()
  const isAdmin = (user?.role || profile?.user?.role) === 'admin'
  const [showFilters, setShowFilters] = useState(false)

  // Filter state. Course defaults to '' (All courses) so mock tests from every
  // enrolled course are visible by default — otherwise a test created in a
  // course other than the last-used one stays hidden until manually selected.
  const [filters, setFilters] = useState({
    course: '',
    attempted: '', // '', 'true', 'false'
    is_free: '',
    search: '',
  })

  // Build query params
  const queryParams = useMemo(() => {
    const params = {}
    if (filters.course) params.course = filters.course
    if (filters.attempted) params.attempted = filters.attempted
    if (filters.is_free) params.is_free = filters.is_free
    if (filters.search) params.search = filters.search
    return params
  }, [filters])

  const { data: mockTests, isLoading } = useQuery({
    queryKey: ['mockTests', queryParams],
    queryFn: () => quizService.getMockTests(queryParams),
  })

  const { data: filterOptions } = useQuery({
    queryKey: ['mockTestFilterOptions'],
    queryFn: () => quizService.getMockTestFilterOptions(),
  })

  const { data: recentAttempts } = useQuery({
    queryKey: ['recentMockAttempts'],
    queryFn: () => quizService.getMockAttempts(),
  })

  // Persist a specific course selection for cross-page context, but never force
  // one — an empty selection ("All courses") is a valid, respected state.
  useEffect(() => {
    if (filters.course) localStorage.setItem('study:lastCourseId', filters.course)
  }, [filters.course])

  const handleStartTest = async (testId) => {
    navigate(`/mock-test/live/${testId}`)
  }

  const updateFilter = (key, value) => {
    setFilters(prev => ({ ...prev, [key]: value }))
  }

  const clearFilters = () => {
    setFilters((prev) => ({
      course: prev.course, // keep course context
      attempted: '',
      is_free: '',
      search: '',
    }))
  }

  const activeFilterCount = Object.entries(filters)
    .filter(([k, v]) => k !== 'course' && Boolean(v)).length

  const tests = mockTests?.results || mockTests || []

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-display font-bold">{mockLabel}</h1>
          <p className="text-surface-500 mt-1">Practice with full-length exam simulations</p>
        </div>
        <div className="flex items-center gap-2">
          {isAdmin && (
            <button
              onClick={() => navigate('/admin/mock-tests')}
              className="btn-secondary flex items-center gap-2"
            >
              <Settings2 size={18} />
              Manage {mockLabel}
            </button>
          )}
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
      </div>

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
                    placeholder={`Search ${mockLabel.toLowerCase()}...`}
                    className="input pl-10 w-full"
                  />
                </div>
              </div>

              {/* Quick Filters - Attempt Status */}
              <div>
                <label className="block text-sm font-medium mb-2">Status</label>
                <div className="flex flex-wrap gap-2">
                  <button
                    onClick={() => updateFilter('attempted', '')}
                    className={`px-4 py-2 rounded-full text-sm font-medium transition-all ${filters.attempted === ''
                      ? 'bg-primary-500 text-white'
                      : 'bg-surface-100 dark:bg-surface-800 hover:bg-surface-200 dark:hover:bg-surface-700'
                      }`}
                  >
                    All Tests
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

              {/* Course Filter */}
              <div>
                <label className="block text-sm font-medium mb-2">Course</label>
                <div className="flex flex-wrap gap-2">
                  <button
                    onClick={() => updateFilter('course', '')}
                    className={`px-4 py-2 rounded-full text-sm font-medium transition-all ${filters.course === ''
                      ? 'bg-primary-500 text-white'
                      : 'bg-surface-100 dark:bg-surface-800 hover:bg-surface-200 dark:hover:bg-surface-700'
                      }`}
                  >
                    All courses
                  </button>
                  {filterOptions?.courses?.map((course) => (
                    <button
                      key={course.id}
                      onClick={() => updateFilter('course', course.id)}
                      className={`px-4 py-2 rounded-full text-sm font-medium transition-all ${filters.course === course.id
                        ? 'bg-primary-500 text-white'
                        : 'bg-surface-100 dark:bg-surface-800 hover:bg-surface-200 dark:hover:bg-surface-700'
                        }`}
                    >
                      {course.name}
                    </button>
                  ))}
                </div>
              </div>

              {/* Price Filter */}
              <div>
                <label className="block text-sm font-medium mb-2">Price</label>
                <div className="flex flex-wrap gap-2">
                  <button
                    onClick={() => updateFilter('is_free', '')}
                    className={`px-4 py-2 rounded-full text-sm font-medium transition-all ${filters.is_free === ''
                      ? 'bg-primary-500 text-white'
                      : 'bg-surface-100 dark:bg-surface-800 hover:bg-surface-200 dark:hover:bg-surface-700'
                      }`}
                  >
                    All
                  </button>
                  <button
                    onClick={() => updateFilter('is_free', filters.is_free === 'true' ? '' : 'true')}
                    className={`px-4 py-2 rounded-full text-sm font-medium transition-all flex items-center gap-2 ${filters.is_free === 'true'
                      ? 'bg-success-500 text-white'
                      : 'bg-surface-100 dark:bg-surface-800 hover:bg-surface-200 dark:hover:bg-surface-700'
                      }`}
                  >
                    <BadgePercent size={16} /> Free
                  </button>
                  <button
                    onClick={() => updateFilter('is_free', filters.is_free === 'false' ? '' : 'false')}
                    className={`px-4 py-2 rounded-full text-sm font-medium transition-all flex items-center gap-2 ${filters.is_free === 'false'
                      ? 'bg-warning-500 text-white'
                      : 'bg-surface-100 dark:bg-surface-800 hover:bg-surface-200 dark:hover:bg-surface-700'
                      }`}
                  >
                    <Star size={16} /> Premium
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
          {filters.is_free === 'true' && (
            <span className="badge badge-success flex items-center gap-1">
              <BadgePercent size={12} /> Free
              <button onClick={() => updateFilter('is_free', '')} className="ml-1 hover:text-white">×</button>
            </span>
          )}
          {filters.is_free === 'false' && (
            <span className="badge badge-warning flex items-center gap-1">
              <Star size={12} /> Premium
              <button onClick={() => updateFilter('is_free', '')} className="ml-1 hover:text-white">×</button>
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
        {isLoading ? 'Loading...' : `${tests.length} found`}
      </div>

      {/* Mock Tests Grid */}
      {isLoading ? (
        <Loading />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {tests.map((test) => {
            const attemptInfo = test.user_attempt_info
            const hasAttempted = attemptInfo?.attempted

            return (
              <motion.div
                key={test.id}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                className={`card p-5 ${hasAttempted ? 'ring-2 ring-primary-200 dark:ring-primary-800' : ''}`}
              >
                <div className="flex items-start justify-between mb-4">
                  <div>
                    <div className="flex items-center gap-2 mb-2">
                      <span className="badge-primary">{test.course_name}</span>
                      {hasAttempted && attemptInfo.has_score && (
                        <span className={`badge ${attemptInfo.best_score >= 70 ? 'badge-success' :
                          attemptInfo.best_score >= 40 ? 'badge-warning' : 'badge-error'
                          }`}>
                          Best: {Math.round(attemptInfo.best_score)}%
                        </span>
                      )}
                      {hasAttempted && !attemptInfo.has_score && attemptInfo.results_pending && (
                        <span className="badge badge-warning">Awaiting grading</span>
                      )}
                    </div>
                    <h3 className="text-lg font-semibold">{test.title}</h3>
                  </div>
                  {!hasAttempted && (
                    test.is_free ? (
                      <span className="badge-success">Free</span>
                    ) : (
                      <span className="badge-warning">Premium</span>
                    )
                  )}
                </div>

                <p className="text-sm text-surface-500 mb-4">{test.description}</p>

                <div className="grid grid-cols-4 gap-3 mb-4 text-center">
                  <div className="p-2 rounded-lg bg-surface-50 dark:bg-surface-800">
                    <p className="text-lg font-bold">{test.questions_count}</p>
                    <p className="text-xs text-surface-500">Questions</p>
                  </div>
                  <div className="p-2 rounded-lg bg-surface-50 dark:bg-surface-800">
                    <p className="text-lg font-bold">{test.duration_minutes}m</p>
                    <p className="text-xs text-surface-500">Duration</p>
                  </div>
                  <div className="p-2 rounded-lg bg-surface-50 dark:bg-surface-800">
                    <p className="text-lg font-bold">{test.total_marks}</p>
                    <p className="text-xs text-surface-500">Marks</p>
                  </div>
                  <div className="p-2 rounded-lg bg-surface-50 dark:bg-surface-800">
                    <p className="text-lg font-bold text-error-500">
                      {test.negative_marking ? '✓' : '✗'}
                    </p>
                    <p className="text-xs text-surface-500">-ve Marks</p>
                  </div>
                </div>

                {hasAttempted ? (
                  <>
                    <div className="text-sm text-surface-500 mb-3">
                      <span>{attemptInfo.attempts_count} attempt{attemptInfo.attempts_count > 1 ? 's' : ''}</span>
                      {typeof attemptInfo.max_attempts === 'number' && <span> of {attemptInfo.max_attempts} allowed</span>}
                      {attemptInfo.rank && <span> • Rank #{attemptInfo.rank}</span>}
                      {attemptInfo.percentile && <span> • Top {Math.round(100 - attemptInfo.percentile)}%</span>}
                    </div>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => navigate(`/mock-test/live-review/${attemptInfo.best_attempt_id}`)}
                        className={`btn-secondary ${(attemptInfo.active_attempt_id || attemptInfo.can_reattempt) ? 'flex-1' : 'w-full'}`}
                      >
                        View Result
                      </button>
                      {attemptInfo.active_attempt_id ? (
                        <button
                          onClick={() => handleStartTest(test.id)}
                          className="btn-primary flex-1"
                        >
                          Resume
                        </button>
                      ) : attemptInfo.can_reattempt ? (
                        <button
                          onClick={() => handleStartTest(test.id)}
                          className="btn-primary flex-1"
                        >
                          Retry
                        </button>
                      ) : null}
                    </div>
                    {!attemptInfo.active_attempt_id && !attemptInfo.can_reattempt && (
                      <p className="text-xs text-surface-400 mt-2 text-center">No attempts remaining</p>
                    )}
                  </>
                ) : (
                  <div className="flex items-center justify-between">
                    <div className="text-sm text-surface-500">
                      <span>{test.total_attempts} attempts</span>
                      {test.average_score > 0 && (
                        <span> • Avg: {Math.round(test.average_score)}%</span>
                      )}
                    </div>
                    <button
                      onClick={() => handleStartTest(test.id)}
                      className="btn-primary"
                    >
                      Start Test
                    </button>
                  </div>
                )}
              </motion.div>
            )
          })}
        </div>
      )}

      {/* Empty State */}
      {!isLoading && tests.length === 0 && (
        <div className="text-center py-12">
          <div className="flex justify-center mb-4 text-surface-300">
            <Search size={64} />
          </div>
          <p className="text-surface-500">Nothing found matching your filters</p>
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
                  <p className="font-medium">{attempt.mock_test_title}</p>
                  <p className="text-sm text-surface-500">
                    {attempt.completed_at ? new Date(attempt.completed_at).toLocaleDateString() : 'In Progress'}
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <div className="text-right">
                    <p className={`font-bold ${attempt.percentage >= 70 ? 'text-success-500' :
                      attempt.percentage >= 40 ? 'text-warning-500' : 'text-error-500'
                      }`}>
                      {Math.round(attempt.percentage || 0)}%
                    </p>
                    <p className="text-sm text-surface-500">
                      {attempt.correct_answers}/{attempt.total_questions}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => navigate(`/mock-test/live-review/${attempt.id}`)}
                      className="btn-secondary text-xs px-3 py-1.5"
                    >
                      View Result
                    </button>
                    <button
                      onClick={() => handleStartTest(attempt.mock_test)}
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

export default MockTest
