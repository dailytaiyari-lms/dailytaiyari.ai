import { useQuery } from '@tanstack/react-query'
import { Lightbulb } from 'lucide-react'
import { diagnosisService } from '../../services/diagnosisService'
import { useTenantStore } from '../../context/tenantStore'

/** The student's own answer notes for one attempt (diagnosis student view). */
export function useDiagnosisNotes(attemptKind, attemptId) {
  // Explicit true only, so no request is ever sent for an opted-out tenant.
  const optedIn = useTenantStore((s) => s.tenant?.features?.diagnosis_student_view === true)
  const { data } = useQuery({
    queryKey: ['diagnosisNotes', attemptKind, attemptId],
    queryFn: () => diagnosisService.getMyAttemptNotes(attemptKind, attemptId),
    enabled: optedIn && !!attemptId,
    staleTime: 60_000,
    retry: false,
  })
  return { notes: data?.notes || {} }
}

/** One plain-language line about how an answer went. Never a bare label. */
export default function DiagnosisNote({ text }) {
  if (!text) return null
  return (
    <p className="mt-3 text-sm text-surface-600 dark:text-surface-300 flex items-start gap-1.5">
      <Lightbulb size={14} className="mt-0.5 text-primary-500 shrink-0" />
      <span>{text}</span>
    </p>
  )
}
