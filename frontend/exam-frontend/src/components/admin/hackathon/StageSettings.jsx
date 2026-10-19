import { useQuery } from '@tanstack/react-query'
import { Info } from 'lucide-react'
import { notebookAdminService } from '../../../services/notebookService'
import { STAGE_TYPES, QUALIFICATION_MODES } from '../../hackathons/hackathonShared'

const FILE_PRESETS = [
  ['zip', 'Archives (.zip)'],
  ['pdf', 'Documents (.pdf)'],
  ['mp4', 'Video (.mp4)'],
  ['pptx', 'Slides (.pptx)'],
  ['docx', 'Word (.docx)'],
  ['png', 'Images (.png)'],
  ['jpg', 'Images (.jpg)'],
  ['ipynb', 'Notebooks (.ipynb)'],
  ['csv', 'Data (.csv)'],
]

const Field = ({ label, hint, children, className = '' }) => (
  <label className={`block ${className}`}>
    <span className="text-sm font-medium">{label}</span>
    {children}
    {hint && <span className="block text-xs text-surface-400 mt-1">{hint}</span>}
  </label>
)

const Toggle = ({ label, hint, checked, onChange }) => (
  <label className="flex items-start gap-3 p-3 rounded-xl border border-surface-200 dark:border-surface-700 cursor-pointer">
    <input type="checkbox" className="mt-1" checked={Boolean(checked)} onChange={onChange} />
    <span>
      <span className="text-sm font-medium block">{label}</span>
      {hint && <span className="text-xs text-surface-400">{hint}</span>}
    </span>
  </label>
)

const toLocalInput = (iso) => {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
}

/**
 * The per-round configuration form. `form` is controlled by the builder page;
 * `onChange(key, value)` writes a single field.
 */
const StageSettings = ({ form, onChange }) => {
  const isLab = form.stage_type === 'lab'
  const isSubmission = form.stage_type === 'submission'
  const isPaper = form.stage_type === 'quiz' || form.stage_type === 'coding'

  const { data: notebooks = [] } = useQuery({
    queryKey: ['admin-notebooks-for-lab'],
    queryFn: () => notebookAdminService.list({ page_size: 200 }),
    enabled: isLab,
  })

  const set = (key) => (e) => {
    const value = e.target.type === 'checkbox' ? e.target.checked : e.target.value
    onChange(key, value)
  }
  const setNumber = (key) => (e) => onChange(key, e.target.value === '' ? null : Number(e.target.value))
  const setDate = (key) => (e) => onChange(key, e.target.value ? new Date(e.target.value).toISOString() : null)

  const allowed = form.allowed_file_types || []
  const toggleFileType = (ext) => onChange(
    'allowed_file_types',
    allowed.includes(ext) ? allowed.filter((x) => x !== ext) : [...allowed, ext],
  )

  return (
    <div className="space-y-5">
      <div className="grid sm:grid-cols-2 gap-4">
        <Field label="Round title *">
          <input className="input mt-1" value={form.title || ''} onChange={set('title')} />
        </Field>
        <Field label="Round type" hint={STAGE_TYPES.find((s) => s.value === form.stage_type)?.blurb}>
          <select className="input mt-1" value={form.stage_type} onChange={set('stage_type')}>
            {STAGE_TYPES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
          </select>
        </Field>
      </div>

      <Field label="Description" hint="Shown on the hackathon page timeline.">
        <textarea className="input mt-1 min-h-[80px]" value={form.description || ''} onChange={set('description')} />
      </Field>

      <Field label="Instructions" hint="Shown on the round's own screen, right before a participant starts.">
        <textarea className="input mt-1 min-h-[100px]" value={form.instructions || ''} onChange={set('instructions')} />
      </Field>

      {/* Window */}
      <div className="grid sm:grid-cols-3 gap-4">
        <Field label="Opens at">
          <input type="datetime-local" className="input mt-1" value={toLocalInput(form.starts_at)} onChange={setDate('starts_at')} />
        </Field>
        <Field label="Closes at">
          <input type="datetime-local" className="input mt-1" value={toLocalInput(form.ends_at)} onChange={setDate('ends_at')} />
        </Field>
        <Field label="Time limit (min)" hint="0 = no per-attempt timer.">
          <input type="number" min="0" className="input mt-1" value={form.duration_minutes ?? 0} onChange={setNumber('duration_minutes')} />
        </Field>
      </div>

      {/* Type-specific */}
      {isPaper && (
        <div className="grid sm:grid-cols-2 gap-4">
          <Field label="Attempts allowed">
            <input type="number" min="1" className="input mt-1" value={form.max_attempts ?? 1} onChange={setNumber('max_attempts')} />
          </Field>
          <div className="flex items-end">
            <Toggle
              label="Shuffle questions"
              hint="Each participant sees a different order."
              checked={form.shuffle_items}
              onChange={set('shuffle_items')}
            />
          </div>
        </div>
      )}

      {isLab && (
        <Field
          label="Lab notebook *"
          hint="Participants work in the notebook workspace; their best passing score is pulled into this round."
        >
          <select className="input mt-1" value={form.notebook || ''} onChange={(e) => onChange('notebook', e.target.value || null)}>
            <option value="">Choose a notebook…</option>
            {notebooks.map((n) => <option key={n.id} value={n.id}>{n.title}</option>)}
          </select>
        </Field>
      )}

      {isSubmission && (
        <div className="space-y-4">
          <Field label="What to submit" hint="Deliverables, naming, format expectations.">
            <textarea
              className="input mt-1 min-h-[100px]"
              value={form.submission_instructions || ''}
              onChange={set('submission_instructions')}
            />
          </Field>

          <div>
            <span className="text-sm font-medium">Accepted file types</span>
            <div className="flex flex-wrap gap-1.5 mt-2">
              {FILE_PRESETS.map(([ext, label]) => (
                <button
                  key={ext}
                  type="button"
                  onClick={() => toggleFileType(ext)}
                  className={`px-2.5 py-1 rounded-lg text-xs font-medium border transition-colors ${
                    allowed.includes(ext)
                      ? 'border-primary-500 bg-primary-50 text-primary-700 dark:bg-primary-900/20 dark:text-primary-300'
                      : 'border-surface-200 dark:border-surface-700 text-surface-500 hover:border-primary-300'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
            <span className="block text-xs text-surface-400 mt-1.5">
              Leave all off to accept any file type.
            </span>
          </div>

          <div className="grid sm:grid-cols-2 gap-4">
            <Field label="Max file size (MB)">
              <input type="number" min="1" className="input mt-1" value={form.max_file_mb ?? 50} onChange={setNumber('max_file_mb')} />
            </Field>
            <Field label="Max files">
              <input type="number" min="1" className="input mt-1" value={form.max_files ?? 1} onChange={setNumber('max_files')} />
            </Field>
          </div>

          <div className="grid sm:grid-cols-2 gap-3">
            <Toggle label="Require a repository URL" checked={form.require_repo_url} onChange={set('require_repo_url')} />
            <Toggle label="Require a live demo URL" checked={form.require_demo_url} onChange={set('require_demo_url')} />
            <Toggle label="Require a demo video URL" checked={form.require_video_url} onChange={set('require_video_url')} />
            <Toggle
              label="Allow resubmission"
              hint="Participants can replace their entry until the round closes."
              checked={form.allow_resubmission}
              onChange={set('allow_resubmission')}
            />
          </div>
        </div>
      )}

      {!isPaper && (
        <Field label="Maximum score" hint="Used to compute percentages and cut-offs for this round.">
          <input type="number" min="0" className="input mt-1 max-w-xs" value={form.max_score ?? 100} onChange={setNumber('max_score')} />
        </Field>
      )}

      {/* Progression */}
      <div className="rounded-xl border border-surface-200 dark:border-surface-700 p-4 space-y-4">
        <div className="flex items-start gap-2">
          <Info className="w-4 h-4 text-primary-500 mt-0.5 shrink-0" />
          <p className="text-sm text-surface-500">
            Shortlisting decides who reaches the next round. Whatever you choose, you
            always get to review and override the list before it is applied.
          </p>
        </div>

        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {QUALIFICATION_MODES.map((mode) => (
            <button
              key={mode.value}
              type="button"
              onClick={() => onChange('qualification_mode', mode.value)}
              className={`text-left p-3 rounded-xl border-2 transition-colors ${
                form.qualification_mode === mode.value
                  ? 'border-primary-500 bg-primary-50/60 dark:bg-primary-900/20'
                  : 'border-surface-200 dark:border-surface-700 hover:border-primary-300'
              }`}
            >
              <span className="text-sm font-medium block">{mode.label}</span>
              <span className="text-xs text-surface-400">{mode.blurb}</span>
            </button>
          ))}
        </div>

        {form.qualification_mode === 'cutoff' && (
          <Field label="Qualifying score *" hint="Participants scoring at or above this advance.">
            <input type="number" min="0" step="0.5" className="input mt-1 max-w-xs" value={form.cutoff_score ?? ''} onChange={setNumber('cutoff_score')} />
          </Field>
        )}
        {form.qualification_mode === 'top_n' && (
          <Field label="How many advance? *">
            <input type="number" min="1" className="input mt-1 max-w-xs" value={form.top_n ?? ''} onChange={setNumber('top_n')} />
          </Field>
        )}
      </div>

      <Field label="Status" hint="Publishing a round opens it and emails every eligible participant.">
        <select className="input mt-1 max-w-xs" value={form.status} onChange={set('status')}>
          <option value="draft">Draft — hidden from students</option>
          <option value="published">Published — visible and open</option>
          <option value="completed">Completed — closed</option>
        </select>
      </Field>
    </div>
  )
}

export default StageSettings
