import { useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { LineChart } from 'lucide-react'
import { progressService } from '../services/progressService'
import { useTenantStore } from '../context/tenantStore'
import Loading from '../components/common/Loading'
import ProgressView from '../components/progress/ProgressView'

/** Student: mastery by subject and topic, skills, and recent answers. */
export default function MyProgress() {
  const [courseId, setCourseId] = useState('')
  const practiceOn = useTenantStore((s) => s.tenant?.features?.practice === true)
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['myProgress', courseId],
    queryFn: () => progressService.getMyProgress(courseId || undefined),
    placeholderData: keepPreviousData,
  })

  if (!data && isLoading) return <Loading fullScreen />
  if (!data && isError) {
    return (
      <p className="text-sm text-error-600 dark:text-error-300">
        {error?.response?.data?.error || 'Could not load progress.'}
      </p>
    )
  }
  if (!data) return null

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-display font-bold flex items-center gap-2">
          <LineChart className="text-primary-500" /> My Progress
        </h1>
        <p className="text-surface-500 mt-1">
          How well you know each part of your course, from your quizzes and tests
        </p>
      </div>
      {data.course ? (
        <ProgressView
          data={data}
          onCourseChange={setCourseId}
          practiceOn={practiceOn}
          linkReviews
        />
      ) : (
        <div className="p-8 rounded-2xl bg-surface-50 dark:bg-surface-800/50 border border-dashed border-surface-300 dark:border-surface-700 text-center text-surface-500">
          Join a course to see your progress here.
        </div>
      )}
    </div>
  )
}
