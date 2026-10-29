import { useQuery } from '@tanstack/react-query'
import { ClipboardCheck } from 'lucide-react'
import { contentBuilderService } from '../services/contentBuilderService'
import TagReviewList from '../components/syllabus/TagReviewList'

/** Learning Insights → Tag review: every flagged question in the user's courses. */
export default function TagReview() {
  const { data: courses } = useQuery({ queryKey: ['insightCourses'], queryFn: contentBuilderService.getExams })
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-display font-bold flex items-center gap-2">
          <ClipboardCheck className="text-primary-500" /> Tag review
        </h1>
        <p className="text-surface-500 mt-1">Questions the tagger was unsure about. Accept, edit, re-tag, or add a suggested subtopic.</p>
      </div>
      <div className="p-5 rounded-2xl bg-white dark:bg-surface-800 border border-surface-200 dark:border-surface-700">
        <TagReviewList courses={courses || []} />
      </div>
    </div>
  )
}
