import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { useQuery } from '@tanstack/react-query'
import { courseService } from '../services/courseService'
import { useFeatureLabel } from '../context/tenantStore'
import Loading from '../components/common/Loading'
import CourseThumbnail from '../components/course/CourseThumbnail'
import { GraduationCap, Clock, Compass, ArrowRight } from 'lucide-react'
import { stripHtml } from '../utils/html'

const Study = () => {
  const navigate = useNavigate()
  const studyLabel = useFeatureLabel('study', 'Study')
  const coursesLabel = useFeatureLabel('courses', 'courses')

  const { data: studyData = { courses: [], pending: [] }, isLoading } = useQuery({
    queryKey: ['studyCourses'],
    queryFn: () => courseService.getStudyCourses(),
  })
  const courses = studyData.courses || []
  const pending = studyData.pending || []

  if (isLoading && !courses.length) return <Loading fullScreen />

  const PendingBanner = () => (
    pending.length > 0 ? (
      <div className="card p-5 border-amber-200 dark:border-amber-800/60 bg-amber-50/60 dark:bg-amber-900/10">
        <div className="flex items-center gap-2 mb-3">
          <Clock size={18} className="text-amber-500" />
          <h3 className="font-semibold text-amber-700 dark:text-amber-400">Pending admin approval</h3>
        </div>
        <ul className="flex flex-wrap gap-2">
          {pending.map((p) => (
            <li key={p.id} className="px-3 py-1.5 rounded-full text-sm bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300 border border-amber-200 dark:border-amber-800">
              {p.name} &middot; awaiting approval
            </li>
          ))}
        </ul>
        <p className="text-xs text-surface-500 mt-3">
          These courses unlock once your institution admin approves them.
        </p>
      </div>
    ) : null
  )

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h1 className="text-2xl font-display font-bold">{studyLabel}</h1>
          <p className="text-surface-500 mt-1">Your enrolled courses</p>
        </div>
        <button
          type="button"
          onClick={() => navigate('/courses')}
          className="btn-secondary inline-flex items-center gap-2 text-sm"
        >
          <Compass size={18} />
          Browse all {coursesLabel.toLowerCase()}
        </button>
      </div>

      <PendingBanner />

      {courses.length === 0 ? (
        <div className="card p-8 text-center text-surface-600 dark:text-surface-400">
          <GraduationCap size={48} className="mx-auto mb-3 text-surface-400" />
          <p className="font-medium">No enrolled courses yet</p>
          <p className="mt-1 text-sm mb-6">
            Browse the course catalog and request enrollment. Once an admin approves, the course appears here.
          </p>
          <button
            type="button"
            onClick={() => navigate('/courses')}
            className="btn-primary inline-flex items-center gap-2"
          >
            <Compass size={20} />
            Explore courses
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
          {courses.map((course, index) => {
            return (
            <motion.div
              key={course.id}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: index * 0.07 }}
              className="group card-hover overflow-hidden flex flex-col"
            >
              <CourseThumbnail course={course} />
              <div className="p-4 sm:p-5 flex flex-col flex-1">
                <h3 className="text-base sm:text-lg font-semibold leading-snug line-clamp-1">{course.name}</h3>
                {course.description && (
                  <p className="text-sm text-surface-500 mt-2.5 line-clamp-2">{stripHtml(course.description)}</p>
                )}

                <div className="mt-auto pt-4 flex items-center gap-2">
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
                    <ArrowRight size={18} className="transition-transform group-hover/btn:translate-x-0.5" />
                  </button>
                </div>
              </div>
            </motion.div>
            )
          })}
        </div>
      )}
    </div>
  )
}

export default Study
