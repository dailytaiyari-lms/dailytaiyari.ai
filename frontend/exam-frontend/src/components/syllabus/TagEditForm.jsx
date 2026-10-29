import { useEffect, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { X } from 'lucide-react'
import { syllabusService, errorText } from '../../services/syllabusService'

/** Edit one item's tags. Saving locks them: the tagger never overwrites manual tags. */
export default function TagEditForm({ taggingId, onClose, onSaved }) {
  const { data } = useQuery({
    queryKey: ['tagReviewRow', taggingId],
    queryFn: () => syllabusService.getReviewRow(taggingId),
  })
  const [form, setForm] = useState(null)
  useEffect(() => {
    if (!data) return
    const row = data.row
    setForm({
      primary: row.primary?.id || '',
      secondary: row.secondary.map((n) => n.id),
      thinking_level: row.thinking_level,
      skills: row.skills.map(({ key, role, reason }) => ({ key, role, reason })),
      special_format: row.special_format,
      difficulty_prior: row.difficulty_prior,
      est_solve_seconds: row.est_solve_seconds ?? '',
    })
  }, [data])
  const save = useMutation({
    mutationFn: () => syllabusService.saveTags(taggingId, form),
    onSuccess: (row) => { toast.success('Tags saved'); onSaved?.(row); onClose() },
    onError: (error) => toast.error(errorText(error)),
  })

  if (!data || !form) return null
  const { choices } = data
  if (!choices) {
    return <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4"><div className="card p-6">This question has no subject tree.<button type="button" onClick={onClose} className="btn-secondary ml-3">Close</button></div></div>
  }
  const set = (patch) => setForm({ ...form, ...patch })
  const toggleSkill = (key) => {
    const has = form.skills.find((s) => s.key === key)
    set({ skills: has ? form.skills.filter((s) => s.key !== key) : [...form.skills, { key, role: 'supporting', reason: '' }] })
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4" role="dialog" aria-modal="true">
      <div className="card w-full max-w-2xl max-h-[90vh] overflow-y-auto p-6 space-y-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="font-semibold">Edit tags</h3>
            <p className="text-sm text-surface-500 mt-1 line-clamp-3">{data.row.question_text}</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close"><X size={18} /></button>
        </div>

        <label className="block text-sm">
          <span className="font-medium">Primary subtopic</span>
          <select value={form.primary} onChange={(e) => set({ primary: e.target.value })} className="input mt-1">
            <option value="">— pick —</option>
            {choices.topics.map((topic) => (
              <optgroup key={topic.id} label={topic.name}>
                {topic.subtopics.map((s) => <option key={s.id} value={s.id}>{s.name}{s.status === 'proposed' ? ' (suggested)' : ''}</option>)}
              </optgroup>
            ))}
          </select>
        </label>

        <label className="block text-sm">
          <span className="font-medium">Secondary subtopics</span>
          <select
            multiple
            value={form.secondary}
            onChange={(e) => set({ secondary: [...e.target.selectedOptions].map((o) => o.value) })}
            className="input mt-1 h-28"
          >
            {choices.topics.map((topic) => (
              <optgroup key={topic.id} label={topic.name}>
                {topic.subtopics.filter((s) => s.id !== form.primary).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </optgroup>
            ))}
          </select>
        </label>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <label className="block text-sm">
            <span className="font-medium">Thinking level</span>
            <select value={form.thinking_level} onChange={(e) => set({ thinking_level: e.target.value })} className="input mt-1">
              <option value="">— pick —</option>
              {choices.thinking_levels.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
            </select>
          </label>
          <label className="block text-sm">
            <span className="font-medium">Difficulty</span>
            <select value={form.difficulty_prior} onChange={(e) => set({ difficulty_prior: e.target.value })} className="input mt-1">
              <option value="">—</option>
              {['easy', 'medium', 'hard'].map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
          </label>
          <label className="block text-sm">
            <span className="font-medium">Solve time (s)</span>
            <input type="number" min="10" max="1800" value={form.est_solve_seconds} onChange={(e) => set({ est_solve_seconds: e.target.value })} className="input mt-1" />
          </label>
        </div>

        <label className="block text-sm">
          <span className="font-medium">Special format</span>
          <select value={form.special_format} onChange={(e) => set({ special_format: e.target.value })} className="input mt-1">
            <option value="">None</option>
            {choices.special_formats.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
          </select>
        </label>

        <div className="text-sm">
          <span className="font-medium">Skills</span>
          <div className="mt-2 space-y-1.5">
            {choices.skills.map((skill) => {
              const chosen = form.skills.find((s) => s.key === skill.key)
              return (
                <div key={skill.key} className="flex flex-wrap items-center gap-2">
                  <label className="flex items-center gap-2 min-w-[12rem]">
                    <input type="checkbox" checked={!!chosen} onChange={() => toggleSkill(skill.key)} /> {skill.label}
                  </label>
                  {chosen && (
                    <>
                      <select
                        value={chosen.role}
                        onChange={(e) => set({ skills: form.skills.map((s) => (s.key === skill.key ? { ...s, role: e.target.value } : s)) })}
                        className="input py-0.5 text-xs w-28"
                      >
                        <option value="core">core</option>
                        <option value="supporting">supporting</option>
                      </select>
                      <input
                        value={chosen.reason}
                        placeholder="why (optional)"
                        onChange={(e) => set({ skills: form.skills.map((s) => (s.key === skill.key ? { ...s, reason: e.target.value } : s)) })}
                        className="input py-0.5 text-xs flex-1 min-w-[8rem]"
                      />
                    </>
                  )}
                </div>
              )
            })}
          </div>
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <button type="button" onClick={onClose} className="btn-secondary text-sm">Cancel</button>
          <button type="button" onClick={() => save.mutate()} disabled={save.isPending || !form.primary} className="btn-primary text-sm">
            {save.isPending ? 'Saving…' : 'Save (locks these tags)'}
          </button>
        </div>
      </div>
    </div>
  )
}
