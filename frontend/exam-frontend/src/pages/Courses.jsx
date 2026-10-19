import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { useQuery } from '@tanstack/react-query'
import { courseService } from '../services/courseService'
import { contentBuilderService } from '../services/contentBuilderService'
import { useAuthStore } from '../context/authStore'
import { useFeatureLabel } from '../context/tenantStore'
import Loading from '../components/common/Loading'
import CourseThumbnail from '../components/course/CourseThumbnail'
import { GraduationCap, CheckCircle2, Clock, ArrowRight, Settings2, Search, X, Award } from 'lucide-react'
import { stripHtml } from '../utils/html'

const InstructorLine = ({ instructors = [] }) => {
  if (!instructors.length) return null
  const shown = instructors.slice(0, 2)
  const extra = instructors.slice(2)
  const label = 'Faculty'
  return (
    <div className="flex items-center gap-1.5 mt-2 text-xs min-w-0">
      <span className="inline-flex items-center gap-1 shrink-0 text-primary-600 dark:text-primary-400 font-semibold uppercase tracking-wide text-[10px]">
        <GraduationCap size={13} className="shrink-0" />
        {label}
      </span>
      <span className="text-surface-300 dark:text-surface-600 shrink-0">·</span>
      <span className="truncate text-surface-600 dark:text-surface-300 font-medium">
        {shown.map((i) => i.name).join(', ')}
      </span>
      {extra.length > 0 && (
        <span className="relative group/instr shrink-0">
          <span className="inline-flex items-center justify-center px-1.5 h-[18px] rounded-full bg-surface-100 dark:bg-surface-800 text-surface-500 font-medium cursor-default">
            +{extra.length}
          </span>
          <span className="pointer-events-none absolute left-1/2 -translate-x-1/2 bottom-full mb-1.5 z-20 hidden group-hover/instr:block w-max max-w-[200px] px-2.5 py-1.5 rounded-lg text-[11px] leading-relaxed bg-surface-900 dark:bg-surface-100 text-white dark:text-surface-900 shadow-lg">
            {extra.map((i) => i.name).join(', ')}
          </span>
        </span>
      )}
    </div>
  )
}

const CURRENCY_SYMBOLS = { INR: '₹', USD: '$', EUR: '€', GBP: '£' }
const CoursePrice = ({ course }) => {
  const isFree = course.is_free || course.pricing_type === 'free' || !Number(course.price)
  if (isFree) {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-bold bg-success-50 dark:bg-success-900/30 text-success-700 dark:text-success-400">
        Free
      </span>
    )
  }
  const sym = CURRENCY_SYMBOLS[course.currency] || `${course.currency} `
  const hasDiscount = Number(course.discount_percent) > 0 && course.original_price
  return (
    <div className="flex items-baseline gap-2">
      <span className="text-lg font-display font-bold text-primary-600 dark:text-primary-400">
        {sym}{Number(course.price).toLocaleString('en-IN')}
      </span>
      {hasDiscount && (
        <>
          <span className="text-xs text-surface-400 line-through">
            {sym}{Number(course.original_price).toLocaleString('en-IN')}
          </span>
          <span className="text-[11px] font-semibold text-success-600 dark:text-success-400">
            {course.discount_percent}% off
          </span>
        </>
      )}
    </div>
  )
}

const Courses = () => {
  const navigate = useNavigate()
  const coursesLabel = useFeatureLabel('courses', 'Courses')
  const { user, profile, isAuthenticated } = useAuthStore()
  const role = user?.role || profile?.user?.role
  const isAdmin = role === 'admin'
  const isInstructor = role === 'instructor'
  const canManage = isAdmin || isInstructor

  // Courses this user can manage (backend scopes instructors to assigned courses).
  const { data: manageableRaw } = useQuery({
    queryKey: ['manageableCourses'],
    queryFn: () => contentBuilderService.getExams(),
    enabled: canManage,
  })
  const manageable = Array.isArray(manageableRaw) ? manageableRaw : (manageableRaw?.results || [])

  const { data: availableRaw, isLoading: availLoading } = useQuery({
    queryKey: ['availableCourses'],
    queryFn: () => courseService.getAvailableCoursesForEnrollment(),
  })
  const available = Array.isArray(availableRaw) ? availableRaw : (availableRaw?.results || [])

  const { data: studyData = { courses: [], pending: [] } } = useQuery({
    queryKey: ['studyCourses'],
    queryFn: () => courseService.getStudyCourses(),
    enabled: isAuthenticated,
  })

  const statusById = useMemo(() => {
    const map = {}
    ;(studyData.courses || []).forEach((c) => { map[c.id] = 'approved' })
    ;(studyData.pending || []).forEach((c) => { map[c.id] = 'pending' })
    return map
  }, [studyData])

  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState('all')

  const counts = useMemo(() => {
    let enrolled = 0
    let pending = 0
    available.forEach((c) => {
      const s = statusById[c.id]
      if (s === 'approved') enrolled += 1
      else if (s === 'pending') pending += 1
    })
    return { all: available.length, enrolled, pending }
  }, [available, statusById])

  const visibleCourses = useMemo(() => {
    const q = query.trim().toLowerCase()
    return available.filter((c) => {
      const status = statusById[c.id]
      if (filter === 'enrolled' && status !== 'approved') return false
      if (filter === 'pending' && status !== 'pending') return false
      if (!q) return true
      const haystack = [c.name, stripHtml(c.description), c.code, c.course_type]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
      return haystack.includes(q)
    })
  }, [available, statusById, query, filter])

  const filterTabs = [
    { key: 'all', label: 'All', count: counts.all },
    ...(isAuthenticated
      ? [
          { key: 'enrolled', label: 'Enrolled', count: counts.enrolled },
          { key: 'pending', label: 'Pending', count: counts.pending },
        ]
      : []),
  ]

  if (availLoading) return <Loading fullScreen />

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-display font-bold">{coursesLabel}</h1>
        <p className="text-surface-500 mt-1">Explore all available courses and request enrollment</p>
      </div>

      {isInstructor && (
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <Settings2 size={18} className="text-primary-500" />
            <h2 className="text-lg font-display font-bold">Courses you teach</h2>
          </div>
          {manageable.length === 0 ? (
            <div className="card p-6 text-center text-surface-500">
              <p>You haven't been assigned to any courses yet. Ask an admin to add you as faculty.</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
              {manageable.map((course) => (
                <motion.div
                  key={course.id}
                  whileHover={{ y: -4 }}
                  className="card p-5 flex flex-col gap-3"
                >
                  <div className="flex items-center gap-3">
                    <span
                      className="w-10 h-10 rounded-xl flex items-center justify-center text-white shrink-0 bg-gradient-to-br from-primary-400 to-primary-600"
                    >
                      <GraduationCap size={20} />
                    </span>
                    <div className="min-w-0">
                      <h3 className="font-semibold truncate">{course.name}</h3>
                      <p className="text-xs text-surface-400">{course.subjects_count || 0} subjects</p>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => navigate(`/courses/${course.id}/manage`)}
                    className="btn-primary w-full inline-flex items-center justify-center gap-2 text-sm"
                  >
                    <Settings2 size={15} /> Manage course
                  </button>
                </motion.div>
              ))}
            </div>
          )}
        </div>
      )}

      {available.length === 0 ? (
        <div className="card p-8 text-center text-surface-500">
          <GraduationCap size={48} className="mx-auto mb-3 text-surface-300" />
          <p>No courses available yet. Check back soon.</p>
        </div>
      ) : (
        <>
          {/* Toolbar: search + status filters */}
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="relative w-full sm:max-w-xs">
              <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-surface-400 pointer-events-none" />
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search courses..."
                className="w-full pl-9 pr-9 py-2.5 rounded-xl text-sm bg-white dark:bg-surface-900 border border-surface-200 dark:border-surface-700 focus:border-primary-400 dark:focus:border-primary-600 focus:ring-2 focus:ring-primary-500/20 outline-none transition-colors"
              />
              {query && (
                <button
                  type="button"
                  onClick={() => setQuery('')}
                  aria-label="Clear search"
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 p-0.5 rounded-md text-surface-400 hover:text-surface-600 hover:bg-surface-100 dark:hover:bg-surface-800 transition-colors"
                >
                  <X size={15} />
                </button>
              )}
            </div>

            <div className="inline-flex items-center gap-1 p-1 rounded-xl bg-surface-100 dark:bg-surface-800 self-start sm:self-auto">
              {filterTabs.map((tab) => {
                const isActive = filter === tab.key
                return (
                  <button
                    key={tab.key}
                    type="button"
                    onClick={() => setFilter(tab.key)}
                    className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                      isActive
                        ? 'bg-white dark:bg-surface-900 text-primary-600 dark:text-primary-400 shadow-sm'
                        : 'text-surface-500 hover:text-surface-700 dark:hover:text-surface-300'
                    }`}
                  >
                    {tab.label}
                    <span className={`inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full text-[11px] font-semibold ${
                      isActive
                        ? 'bg-primary-100 dark:bg-primary-900/40 text-primary-700 dark:text-primary-300'
                        : 'bg-surface-200 dark:bg-surface-700 text-surface-500'
                    }`}>
                      {tab.count}
                    </span>
                  </button>
                )
              })}
            </div>
          </div>

          {visibleCourses.length === 0 ? (
            <div className="card p-8 text-center text-surface-500">
              <Search size={40} className="mx-auto mb-3 text-surface-300" />
              <p className="font-medium">No courses match your filters</p>
              <p className="text-sm mt-1">Try a different search term or filter.</p>
              {(query || filter !== 'all') && (
                <button
                  type="button"
                  onClick={() => { setQuery(''); setFilter('all') }}
                  className="mt-4 inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-sm font-medium text-primary-600 dark:text-primary-400 bg-primary-50 dark:bg-primary-900/20 hover:bg-primary-100 dark:hover:bg-primary-900/30 transition-colors"
                >
                  <X size={14} /> Clear filters
                </button>
              )}
            </div>
          ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
          {visibleCourses.map((course, index) => {
            const status = statusById[course.id]
            const statusBadge =
              status === 'approved' ? (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-semibold bg-success-500/95 text-white shadow-sm">
                  <CheckCircle2 size={11} /> Enrolled
                </span>
              ) : status === 'pending' ? (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-semibold bg-amber-400/95 text-amber-950 shadow-sm">
                  <Clock size={11} /> Pending
                </span>
              ) : null
            return (
              <motion.div
                key={course.id}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: index * 0.06 }}
                className="group card-hover overflow-hidden flex flex-col"
              >
                <CourseThumbnail course={course} statusBadge={statusBadge} />

                <div className="p-4 sm:p-5 flex flex-col flex-1">
                  <h3 className="text-base sm:text-lg font-semibold leading-snug line-clamp-1">{course.name}</h3>
                  <InstructorLine instructors={course.instructors} />
                  {course.description && (
                    <p className="text-sm text-surface-500 mt-2.5 line-clamp-2">{stripHtml(course.description)}</p>
                  )}

                  <div className="mt-3">
                    <CoursePrice course={course} />
                  </div>

                  {course.certificate_enabled && (
                    <div className="mt-3">
                      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-300 ring-1 ring-amber-200/80 dark:ring-amber-800/60">
                        <Award size={13} className="text-amber-500" />
                        Certificate on completion
                      </span>
                    </div>
                  )}

                  <div className="mt-auto pt-4">
                    {status === 'approved' ? (
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() => navigate(`/courses/${course.id}`)}
                          className="shrink-0 inline-flex items-center justify-center gap-1.5 px-4 py-2.5 rounded-xl text-sm font-medium text-surface-600 dark:text-surface-300 bg-surface-100 dark:bg-surface-800 hover:bg-surface-200 dark:hover:bg-surface-700 transition-colors"
                        >
                          View details
                        </button>
                        <button
                          type="button"
                          onClick={() => navigate(`/study/course/${course.id}`)}
                          className="btn-primary flex-1 group/btn"
                        >
                          Enter course
                          <ArrowRight size={16} className="transition-transform group-hover/btn:translate-x-0.5" />
                        </button>
                      </div>
                    ) : status === 'pending' ? (
                      <button
                        type="button"
                        onClick={() => navigate(`/courses/${course.id}`)}
                        className="w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-300 border border-amber-200 dark:border-amber-800/60 hover:bg-amber-100 dark:hover:bg-amber-900/30 transition-colors"
                      >
                        <Clock size={16} />
                        Awaiting approval · View
                      </button>
                    ) : (
                      <button
                        type="button"
                        onClick={() => navigate(`/courses/${course.id}`)}
                        className="btn-primary w-full group/btn"
                      >
                        View details
                        <ArrowRight size={16} className="transition-transform group-hover/btn:translate-x-0.5" />
                      </button>
                    )}
                  </div>

                  {isAdmin && (
                    <button
                      type="button"
                      onClick={() => navigate(`/courses/${course.id}/manage`)}
                      className="mt-2 w-full inline-flex items-center justify-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold text-surface-600 dark:text-surface-300 bg-surface-100 dark:bg-surface-800 hover:bg-surface-200 dark:hover:bg-surface-700 transition-colors"
                    >
                      <Settings2 size={15} /> Manage course
                    </button>
                  )}
                </div>
              </motion.div>
            )
          })}
        </div>
          )}
        </>
      )}
    </div>
  )
}

export default Courses
