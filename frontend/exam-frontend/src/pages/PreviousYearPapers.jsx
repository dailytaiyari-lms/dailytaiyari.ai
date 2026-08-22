import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { useQuery } from '@tanstack/react-query'
import { quizService } from '../services/quizService'
import { useFeatureLabel } from '../context/tenantStore'
import Loading from '../components/common/Loading'
import {
    FileText,
    Calendar,
    Clock,
    ChevronDown,
    ChevronUp,
    CheckCircle2,
    Award,
    TrendingUp,
    BookOpen,
    Search,
    Filter
} from 'lucide-react'

const PreviousYearPapers = () => {
    const navigate = useNavigate()
    const pyqLabel = useFeatureLabel('pyq', 'Previous Year Papers')
    const [expandedYear, setExpandedYear] = useState(null)
    const [selectedYear, setSelectedYear] = useState('')
    const [selectedSession, setSelectedSession] = useState('')
    const [showFilters, setShowFilters] = useState(false)

    const queryParams = {}
    if (selectedYear) queryParams.year = selectedYear
    if (selectedSession) queryParams.session = selectedSession

    const { data, isLoading } = useQuery({
        queryKey: ['pypByYear', queryParams],
        queryFn: () => quizService.getPYPByYear(queryParams),
    })

    const { data: filterOptions } = useQuery({
        queryKey: ['pypFilterOptions'],
        queryFn: () => quizService.getPYPFilterOptions(),
    })

    const handleStartPaper = async (testId) => {
        try {
            await quizService.startPYP(testId)
            navigate(`/mock-test/${testId}`)
        } catch (error) {
            console.error('Failed to start PYP:', error)
        }
    }

    const toggleYear = (year) => {
        setExpandedYear(expandedYear === year ? null : year)
    }

    const yearGroups = data?.years || []

    return (
        <div className="space-y-6">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-2xl font-display font-bold">{pyqLabel}</h1>
                    <p className="text-surface-500 mt-1">Practice with actual exam papers from previous years</p>
                </div>
                <button
                    onClick={() => setShowFilters(!showFilters)}
                    className={`btn-secondary flex items-center gap-2 ${showFilters ? 'bg-primary-100 dark:bg-primary-900/30' : ''}`}
                >
                    <Filter size={18} />
                    Filters
                </button>
            </div>

            {/* Info Banner */}
            <div className="card p-5 bg-gradient-to-r from-orange-50 to-amber-50 dark:from-orange-900/20 dark:to-amber-900/20">
                <div className="flex items-start gap-4">
                    <div className="w-12 h-12 rounded-xl bg-orange-100 dark:bg-orange-900/30 flex items-center justify-center text-orange-600">
                        <FileText size={28} />
                    </div>
                    <div>
                        <h3 className="font-semibold">About Previous Year Papers</h3>
                        <p className="text-sm text-surface-600 dark:text-surface-400 mt-1">
                            Attempt actual previous year exam papers with the same marking scheme, timing,
                            and question pattern. This is the best way to prepare for the real exam.
                        </p>
                    </div>
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
                            {/* Year Filter */}
                            <div>
                                <label className="block text-sm font-medium mb-2">Year</label>
                                <div className="flex flex-wrap gap-2">
                                    <button
                                        onClick={() => setSelectedYear('')}
                                        className={`px-4 py-2 rounded-full text-sm font-medium transition-all ${selectedYear === ''
                                                ? 'bg-primary-500 text-white'
                                                : 'bg-surface-100 dark:bg-surface-800 hover:bg-surface-200 dark:hover:bg-surface-700'
                                            }`}
                                    >
                                        All Years
                                    </button>
                                    {filterOptions?.years?.map((year) => (
                                        <button
                                            key={year}
                                            onClick={() => setSelectedYear(selectedYear === String(year) ? '' : String(year))}
                                            className={`px-4 py-2 rounded-full text-sm font-medium transition-all ${selectedYear === String(year)
                                                    ? 'bg-primary-500 text-white'
                                                    : 'bg-surface-100 dark:bg-surface-800 hover:bg-surface-200 dark:hover:bg-surface-700'
                                                }`}
                                        >
                                            {year}
                                        </button>
                                    ))}
                                </div>
                            </div>

                            {/* Session Filter */}
                            {filterOptions?.sessions?.length > 0 && (
                                <div>
                                    <label className="block text-sm font-medium mb-2">Session</label>
                                    <div className="flex flex-wrap gap-2">
                                        <button
                                            onClick={() => setSelectedSession('')}
                                            className={`px-4 py-2 rounded-full text-sm font-medium transition-all ${selectedSession === ''
                                                    ? 'bg-primary-500 text-white'
                                                    : 'bg-surface-100 dark:bg-surface-800 hover:bg-surface-200 dark:hover:bg-surface-700'
                                                }`}
                                        >
                                            All Sessions
                                        </button>
                                        {filterOptions.sessions.map((session) => (
                                            <button
                                                key={session}
                                                onClick={() => setSelectedSession(selectedSession === session ? '' : session)}
                                                className={`px-4 py-2 rounded-full text-sm font-medium transition-all ${selectedSession === session
                                                        ? 'bg-primary-500 text-white'
                                                        : 'bg-surface-100 dark:bg-surface-800 hover:bg-surface-200 dark:hover:bg-surface-700'
                                                    }`}
                                            >
                                                {session}
                                            </button>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {/* Clear */}
                            {(selectedYear || selectedSession) && (
                                <button
                                    onClick={() => { setSelectedYear(''); setSelectedSession('') }}
                                    className="text-sm text-primary-500 hover:text-primary-600 font-medium"
                                >
                                    Clear all filters
                                </button>
                            )}
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>

            {/* Papers by Year */}
            {isLoading ? (
                <Loading />
            ) : yearGroups.length === 0 ? (
                <div className="text-center py-12">
                    <div className="flex justify-center mb-4 text-surface-300">
                        <FileText size={64} />
                    </div>
                    <p className="text-surface-500">No previous year papers available yet</p>
                    <p className="text-sm text-surface-400 mt-2">Papers will appear here once they are added</p>
                </div>
            ) : (
                <div className="space-y-4">
                    {yearGroups.map((group) => {
                        const isExpanded = expandedYear === group.year || expandedYear === null

                        return (
                            <motion.div
                                key={group.year}
                                initial={{ opacity: 0, y: 20 }}
                                animate={{ opacity: 1, y: 0 }}
                                className="card overflow-hidden"
                            >
                                {/* Year Header */}
                                <button
                                    onClick={() => toggleYear(group.year)}
                                    className="w-full p-5 flex items-center justify-between hover:bg-surface-50 dark:hover:bg-surface-800/50 transition-colors"
                                >
                                    <div className="flex items-center gap-4">
                                        <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-orange-500 to-amber-500 flex items-center justify-center text-white font-bold text-lg shadow-lg">
                                            {String(group.year).slice(-2)}
                                        </div>
                                        <div className="text-left">
                                            <h2 className="text-xl font-bold">{group.year}</h2>
                                            <p className="text-sm text-surface-500">
                                                {group.count} paper{group.count > 1 ? 's' : ''} available
                                            </p>
                                        </div>
                                    </div>
                                    <div className="flex items-center gap-2 text-surface-400">
                                        {isExpanded ? <ChevronUp size={20} /> : <ChevronDown size={20} />}
                                    </div>
                                </button>

                                {/* Papers List */}
                                <AnimatePresence>
                                    {isExpanded && (
                                        <motion.div
                                            initial={{ height: 0 }}
                                            animate={{ height: 'auto' }}
                                            exit={{ height: 0 }}
                                            className="overflow-hidden"
                                        >
                                            <div className="px-5 pb-5 space-y-3">
                                                {group.papers.map((paper) => {
                                                    const attemptInfo = paper.user_attempt_info
                                                    const hasAttempted = attemptInfo?.attempted

                                                    return (
                                                        <div
                                                            key={paper.id}
                                                            className={`p-4 rounded-xl border transition-all ${hasAttempted
                                                                    ? 'border-primary-200 dark:border-primary-800 bg-primary-50/50 dark:bg-primary-900/10'
                                                                    : 'border-surface-200 dark:border-surface-700 bg-surface-50 dark:bg-surface-800/50'
                                                                }`}
                                                        >
                                                            <div className="flex items-start justify-between mb-3">
                                                                <div>
                                                                    <div className="flex items-center gap-2 mb-1">
                                                                        <span className="badge-primary">{paper.course_name}</span>
                                                                        {paper.pyp_session && (
                                                                            <span className="badge bg-orange-100 dark:bg-orange-900/30 text-orange-700 dark:text-orange-400">
                                                                                {paper.pyp_session}
                                                                            </span>
                                                                        )}
                                                                        {paper.pyp_shift && (
                                                                            <span className="badge bg-surface-100 dark:bg-surface-700 text-surface-600 dark:text-surface-300">
                                                                                {paper.pyp_shift}
                                                                            </span>
                                                                        )}
                                                                        {hasAttempted && (
                                                                            <span className={`badge ${attemptInfo.best_score >= 70 ? 'badge-success' :
                                                                                    attemptInfo.best_score >= 40 ? 'badge-warning' : 'badge-error'
                                                                                }`}>
                                                                                Best: {Math.round(attemptInfo.best_score)}%
                                                                            </span>
                                                                        )}
                                                                    </div>
                                                                    <h3 className="font-semibold text-lg">{paper.title}</h3>
                                                                    {paper.pyp_date && (
                                                                        <p className="text-xs text-surface-400 mt-0.5 flex items-center gap-1">
                                                                            <Calendar size={12} />
                                                                            Exam Date: {new Date(paper.pyp_date).toLocaleDateString('en-IN', {
                                                                                day: 'numeric', month: 'short', year: 'numeric'
                                                                            })}
                                                                        </p>
                                                                    )}
                                                                </div>
                                                            </div>

                                                            {/* Stats Row */}
                                                            <div className="grid grid-cols-4 gap-2 mb-4">
                                                                <div className="text-center p-2 rounded-lg bg-white dark:bg-surface-800">
                                                                    <p className="text-base font-bold">{paper.questions_count}</p>
                                                                    <p className="text-xs text-surface-500">Questions</p>
                                                                </div>
                                                                <div className="text-center p-2 rounded-lg bg-white dark:bg-surface-800">
                                                                    <p className="text-base font-bold">{paper.duration_minutes}m</p>
                                                                    <p className="text-xs text-surface-500">Duration</p>
                                                                </div>
                                                                <div className="text-center p-2 rounded-lg bg-white dark:bg-surface-800">
                                                                    <p className="text-base font-bold">{paper.total_marks}</p>
                                                                    <p className="text-xs text-surface-500">Marks</p>
                                                                </div>
                                                                <div className="text-center p-2 rounded-lg bg-white dark:bg-surface-800">
                                                                    <p className="text-base font-bold text-error-500">
                                                                        {paper.negative_marking ? '✓' : '✗'}
                                                                    </p>
                                                                    <p className="text-xs text-surface-500">-ve Marks</p>
                                                                </div>
                                                            </div>

                                                            {/* Action Buttons */}
                                                            {hasAttempted ? (
                                                                <div className="flex items-center justify-between">
                                                                    <div className="text-sm text-surface-500">
                                                                        <span>{attemptInfo.attempts_count} attempt{attemptInfo.attempts_count > 1 ? 's' : ''}</span>
                                                                        {attemptInfo.rank && <span> • Rank #{attemptInfo.rank}</span>}
                                                                        {attemptInfo.percentile && <span> • Top {Math.round(100 - attemptInfo.percentile)}%</span>}
                                                                    </div>
                                                                    <div className="flex items-center gap-2">
                                                                        <button
                                                                            onClick={() => navigate(`/mock-test/review/${attemptInfo.best_attempt_id}`)}
                                                                            className="btn-secondary text-sm px-4 py-2"
                                                                        >
                                                                            View Result
                                                                        </button>
                                                                        <button
                                                                            onClick={() => handleStartPaper(paper.id)}
                                                                            className="btn-primary text-sm px-4 py-2"
                                                                        >
                                                                            Retry
                                                                        </button>
                                                                    </div>
                                                                </div>
                                                            ) : (
                                                                <div className="flex items-center justify-between">
                                                                    <div className="text-sm text-surface-500">
                                                                        <span>{paper.total_attempts} student{paper.total_attempts !== 1 ? 's' : ''} attempted</span>
                                                                        {paper.average_score > 0 && (
                                                                            <span> • Avg: {Math.round(paper.average_score)}%</span>
                                                                        )}
                                                                    </div>
                                                                    <button
                                                                        onClick={() => handleStartPaper(paper.id)}
                                                                        className="btn-primary text-sm px-5 py-2 flex items-center gap-2"
                                                                    >
                                                                        <BookOpen size={16} />
                                                                        Start Paper
                                                                    </button>
                                                                </div>
                                                            )}
                                                        </div>
                                                    )
                                                })}
                                            </div>
                                        </motion.div>
                                    )}
                                </AnimatePresence>
                            </motion.div>
                        )
                    })}
                </div>
            )}
        </div>
    )
}

export default PreviousYearPapers
