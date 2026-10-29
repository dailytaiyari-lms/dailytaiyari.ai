import { useState } from 'react'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { syllabusService, errorText } from '../../services/syllabusService'
import Loading from '../common/Loading'
import TagEditForm from './TagEditForm'

const REASON_TEXT = {
  low_confidence: 'Low confidence',
  invalid_key: 'No valid subtopic',
  proposed_subtopic: 'Suggests a new subtopic',
  stage_disagreement: 'Topic disagreement',
}

/** Tag review queue. With ``courseId`` it is filtered to one course. */
export default function TagReviewList({ courseId, courses }) {
  const queryClient = useQueryClient()
  const [filters, setFilters] = useState({ course: courseId || '', reason: '', page: 1 })
  const [selected, setSelected] = useState(new Set())
  const [editing, setEditing] = useState(null)
  const params = Object.fromEntries(Object.entries(filters).filter(([, v]) => v))
  const { data, isLoading } = useQuery({
    queryKey: ['tagReview', params],
    queryFn: () => syllabusService.getReview(params),
    placeholderData: keepPreviousData,
  })
  const refresh = () => {
    setSelected(new Set())
    queryClient.invalidateQueries({ queryKey: ['tagReview'] })
  }
  const act = (fn, message) => ({
    mutationFn: fn,
    onSuccess: (res) => {
      if (res?.queued === false) toast('Queue unavailable — it will be re-tagged on the next run.')
      else if (message) toast.success(message)
      refresh()
    },
    onError: (error) => toast.error(errorText(error)),
  })
  const accept = useMutation(act(syllabusService.acceptReview, 'Accepted'))
  const bulk = useMutation(act(() => syllabusService.bulkAccept([...selected]), 'Accepted'))
  const retag = useMutation(act(syllabusService.retag, 'Re-tag queued'))
  const addToTree = useMutation(act((id) => syllabusService.addToTree(id), 'Added to the tree'))

  if (isLoading) return <Loading />
  const rows = data?.results || []
  const toggle = (id) => {
    const next = new Set(selected)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setSelected(next)
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {!courseId && courses && (
          <select value={filters.course} onChange={(e) => setFilters({ ...filters, course: e.target.value, page: 1 })} className="input py-1 text-sm max-w-xs">
            <option value="">All my courses</option>
            {courses.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        )}
        <select value={filters.reason} onChange={(e) => setFilters({ ...filters, reason: e.target.value, page: 1 })} className="input py-1 text-sm max-w-xs">
          <option value="">Any reason</option>
          {Object.entries(REASON_TEXT).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
        </select>
        <span className="text-sm text-surface-500">{data?.total ?? 0} to review</span>
        {selected.size > 0 && (
          <button onClick={() => bulk.mutate()} className="btn-primary text-xs px-3 py-1 ml-auto">Accept {selected.size} selected</button>
        )}
      </div>

      {rows.length === 0 && <p className="text-sm text-surface-400">Nothing needs review.</p>}

      <ul className="divide-y divide-surface-100 dark:divide-surface-700/50">
        {rows.map((row) => (
          <li key={row.id} className="py-3 flex gap-3">
            <input type="checkbox" checked={selected.has(row.id)} onChange={() => toggle(row.id)} className="mt-1" />
            <div className="min-w-0 flex-1 text-sm space-y-1">
              <p className="line-clamp-2">{row.question_text}</p>
              <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-surface-500">
                <span>Primary: {row.primary ? `${row.primary.topic} › ${row.primary.name}` : '—'}</span>
                {row.secondary.length > 0 && <span>Also: {row.secondary.map((n) => n.name).join(', ')}</span>}
                {row.thinking_level && <span>Thinking: {row.thinking_level.replaceAll('_', ' ')}</span>}
                {row.special_format && <span>Format: {row.special_format.replaceAll('_', ' ')}</span>}
                {row.difficulty_prior && <span>Difficulty: {row.difficulty_prior}</span>}
                {row.est_solve_seconds && <span>~{row.est_solve_seconds}s</span>}
                <span>Confidence {Math.round(row.confidence * 100)}%</span>
              </div>
              {row.skills.length > 0 && (
                <p className="text-xs text-surface-500">
                  Skills: {row.skills.map((s) => `${s.label} (${s.role}${s.reason ? `: ${s.reason}` : ''})`).join('; ')}
                </p>
              )}
              <div className="flex flex-wrap gap-1">
                {row.review_reasons.map((reason) => (
                  <span key={reason} className="text-[10px] px-2 py-0.5 rounded-full bg-warning-50 dark:bg-warning-900/20 text-warning-700">{REASON_TEXT[reason] || reason}</span>
                ))}
                {row.proposed_subtopic && <span className="text-[10px] px-2 py-0.5 rounded-full bg-primary-50 text-primary-600">Suggests “{row.proposed_subtopic}”</span>}
              </div>
            </div>
            <div className="flex flex-col gap-1 shrink-0">
              <button onClick={() => accept.mutate(row.id)} className="btn-secondary text-xs px-2 py-1">Accept</button>
              <button onClick={() => setEditing(row.id)} className="btn-secondary text-xs px-2 py-1">Edit</button>
              <button onClick={() => retag.mutate(row.id)} className="btn-secondary text-xs px-2 py-1">Re-tag</button>
              {row.proposed_subtopic && (
                <button onClick={() => addToTree.mutate(row.id)} className="btn-secondary text-xs px-2 py-1">Add to tree</button>
              )}
            </div>
          </li>
        ))}
      </ul>

      {data?.pages > 1 && (
        <div className="flex justify-center items-center gap-3 text-sm">
          <button disabled={filters.page <= 1} onClick={() => setFilters({ ...filters, page: filters.page - 1 })} className="btn-secondary text-xs px-3 py-1 disabled:opacity-40">Previous</button>
          <span>Page {data.page} of {data.pages}</span>
          <button disabled={filters.page >= data.pages} onClick={() => setFilters({ ...filters, page: filters.page + 1 })} className="btn-secondary text-xs px-3 py-1 disabled:opacity-40">Next</button>
        </div>
      )}

      {editing && <TagEditForm taggingId={editing} onClose={() => setEditing(null)} onSaved={refresh} />}
    </div>
  )
}
