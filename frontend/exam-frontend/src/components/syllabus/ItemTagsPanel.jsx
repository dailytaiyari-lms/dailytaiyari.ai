import { useState } from 'react'
import { createPortal } from 'react-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Tags } from 'lucide-react'
import { syllabusService } from '../../services/syllabusService'
import { useTenantStore } from '../../context/tenantStore'
import TagEditForm from './TagEditForm'

/** Read-only tags for one question, with an "Edit tags" link (syllabus tools). */
export default function ItemTagsPanel({ kind, id }) {
  const on = useTenantStore((s) => s.tenant?.features?.syllabus_tools === true)
  const [editing, setEditing] = useState(false)
  const queryClient = useQueryClient()
  const { data } = useQuery({
    queryKey: ['itemTags', kind, id],
    queryFn: () => syllabusService.getItemTags(kind, id),
    enabled: on && !!id,
    retry: false,
  })
  if (!on || !id || !data) return null
  const t = data.tagging

  return (
    <div className="rounded-xl border border-surface-200 dark:border-surface-700 p-3 text-xs space-y-1">
      <div className="flex items-center justify-between">
        <span className="font-semibold flex items-center gap-1"><Tags size={12} /> Tags</span>
        {t && <button type="button" onClick={() => setEditing(true)} className="text-primary-600 hover:underline">Edit tags</button>}
      </div>
      {!t ? (
        <p className="text-surface-400">Not tagged yet.</p>
      ) : (
        <>
          <p>Subtopic: {t.primary ? `${t.primary.topic} › ${t.primary.name}` : '—'}{t.source === 'manual' && ' (set by a teacher)'}</p>
          {t.thinking_level && <p>Thinking: {t.thinking_level.replaceAll('_', ' ')}</p>}
          {t.skills.length > 0 && <p>Skills: {t.skills.map((s) => `${s.label} (${s.role})`).join(', ')}</p>}
          {t.review_status === 'needs_review' && <p className="text-warning-600">Needs review</p>}
        </>
      )}
      {/* Portalled out of the host editor's <form>, so Enter or a stray submit
          inside the tag form can never submit the question editor. */}
      {editing && t && createPortal(
        <TagEditForm
          taggingId={t.id}
          onClose={() => setEditing(false)}
          onSaved={() => queryClient.invalidateQueries({ queryKey: ['itemTags', kind, id] })}
        />,
        document.body,
      )}
    </div>
  )
}
