import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { insightsService } from '../../services/insightsService'
import Loading from '../common/Loading'
import ProgressView from '../progress/ProgressView'

/** Teacher: the student's My Progress data, limited to courses you teach. */
export default function StudentProgressTab({ studentId }) {
  const [courseId, setCourseId] = useState('')
  const { data, isLoading } = useQuery({
    queryKey: ['studentProgress', studentId, courseId],
    queryFn: () => insightsService.getStudentProgress(studentId, courseId || undefined),
  })
  if (isLoading) return <Loading />
  if (!data) return null
  if (!data.course) {
    return <p className="text-sm text-surface-400">This student has no approved course you teach.</p>
  }
  return <ProgressView data={data} onCourseChange={setCourseId} />
}
