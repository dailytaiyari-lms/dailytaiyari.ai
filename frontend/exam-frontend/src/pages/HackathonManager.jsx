import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  Plus, Search, Trophy, Users, Layers, Wand2, Pencil, Trash2, Eye, X, Loader2,
  Settings2, BarChart3, ExternalLink,
} from 'lucide-react'
import { hackathonAdminService } from '../services/hackathonAdminService'
import { ImageDrop, imagePayload, ConfirmDialog, formatApiError } from '../components/admin/builderShared'
import Loading from '../components/common/Loading'
import {
  MODES, DIFFICULTIES, labelOf, formatDate, registrationMeta,
} from '../components/hackathons/hackathonShared'

const STATUSES = [
  { value: 'draft', label: 'Draft' },
  { value: 'published', label: 'Published' },
  { value: 'completed', label: 'Completed' },
  { value: 'archived', label: 'Archived' },
]

const STATUS_TINT = {
  draft: 'bg-surface-100 text-surface-600 dark:bg-surface-800 dark:text-surface-300',
  published: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-300',
  completed: 'bg-violet-50 text-violet-700 dark:bg-violet-900/20 dark:text-violet-300',
  archived: 'bg-surface-100 text-surface-400 dark:bg-surface-800 dark:text-surface-500',
}

const emptyForm = {
  title: '', tagline: '', description: '', rules: '', prizes_description: '',
  eligibility: '', theme_color: '#4f46e5', tags: '', mode: 'online', location: '',
  difficulty: 'all_levels', organizer_name: '', contact_email: '',
  prize_pool: '', prize_currency: 'INR', registration_opens_at: '',
  registration_deadline: '', starts_at: '', ends_at: '', max_participants: '',
  show_registration_count: true, show_leaderboard: true, email_notifications: true,
  status: 'draft', thumbnail: '', banner: '', faqs: [],
}

/** Converts an ISO timestamp to the value a datetime-local input expects. */
const toLocalInput = (iso) => {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const offset = d.getTimezoneOffset() * 60000
  return new Date(d.getTime() - offset).toISOString().slice(0, 16)
}

const fromLocalInput = (value) => (value ? new Date(value).toISOString() : null)

const Field = ({ label, hint, children, className = '' }) => (
  <label className={`block ${className}`}>
    <span className="text-sm font-medium">{label}</span>
    {children}
    {hint && <span className="block text-xs text-surface-400 mt-1">{hint}</span>}
  </label>
)

const HackathonModal = ({ instance, onClose, onSubmit, saving }) => {
  const [tab, setTab] = useState('basics')
  const [form, setForm] = useState(() => {
    if (!instance) return emptyForm
    return {
      ...emptyForm,
      ...instance,
      tags: (instance.tags || []).join(', '),
      prize_pool: instance.prize_pool ?? '',
      max_participants: instance.max_participants ?? '',
      registration_opens_at: toLocalInput(instance.registration_opens_at),
      registration_deadline: toLocalInput(instance.registration_deadline),
      starts_at: toLocalInput(instance.starts_at),
      ends_at: toLocalInput(instance.ends_at),
      thumbnail: instance.thumbnail_url || '',
      banner: instance.banner_url || '',
      faqs: instance.faqs || [],
    }
  })

  const set = (key) => (e) => {
    const value = e.target.type === 'checkbox' ? e.target.checked : e.target.value
    setForm((f) => ({ ...f, [key]: value }))
  }

  const submit = (e) => {
    e.preventDefault()
    if (!form.title.trim()) {
      toast.error('Give the hackathon a title.')
      return
    }
    const payload = {
      title: form.title.trim(),
      tagline: form.tagline,
      description: form.description,
      rules: form.rules,
      prizes_description: form.prizes_description,
      eligibility: form.eligibility,
      theme_color: form.theme_color,
      tags: form.tags.split(',').map((t) => t.trim()).filter(Boolean),
      mode: form.mode,
      location: form.location,
      difficulty: form.difficulty,
      organizer_name: form.organizer_name,
      contact_email: form.contact_email,
      prize_pool: form.prize_pool === '' ? 0 : Number(form.prize_pool),
      prize_currency: form.prize_currency,
      registration_opens_at: fromLocalInput(form.registration_opens_at),
      registration_deadline: fromLocalInput(form.registration_deadline),
      starts_at: fromLocalInput(form.starts_at),
      ends_at: fromLocalInput(form.ends_at),
      max_participants: form.max_participants === '' ? null : Number(form.max_participants),
      show_registration_count: form.show_registration_count,
      show_leaderboard: form.show_leaderboard,
      email_notifications: form.email_notifications,
      status: form.status,
      faqs: form.faqs.filter((f) => f.question?.trim()),
    }
    const thumb = imagePayload(form.thumbnail, instance?.thumbnail_url)
    if (thumb.send) payload.thumbnail = thumb.value
    const banner = imagePayload(form.banner, instance?.banner_url)
    if (banner.send) payload.banner = banner.value

    onSubmit(payload)
  }

  const TABS = [
    { id: 'basics', label: 'Basics' },
    { id: 'content', label: 'Page content' },
    { id: 'schedule', label: 'Schedule' },
    { id: 'settings', label: 'Settings' },
  ]

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center p-4 bg-black/50 overflow-y-auto">
      <form onSubmit={submit} className="card w-full max-w-3xl my-8 p-0 overflow-hidden">
        <div className="flex items-center justify-between gap-4 p-5 border-b border-surface-100 dark:border-surface-800">
          <h2 className="text-lg font-semibold">
            {instance ? 'Edit hackathon' : 'New hackathon'}
          </h2>
          <button type="button" onClick={onClose} className="btn-icon">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="flex items-center gap-1 px-5 pt-3 border-b border-surface-100 dark:border-surface-800">
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setTab(t.id)}
              className={`px-3 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
                tab === t.id
                  ? 'border-primary-500 text-primary-600'
                  : 'border-transparent text-surface-500 hover:text-surface-700'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        <div className="p-5 space-y-4 max-h-[60vh] overflow-y-auto">
          {tab === 'basics' && (
            <>
              <Field label="Title *">
                <input className="input mt-1" value={form.title} onChange={set('title')} required />
              </Field>
              <Field label="Tagline" hint="One punchy line shown on the card and hero.">
                <input className="input mt-1" value={form.tagline} onChange={set('tagline')} />
              </Field>
              <div className="grid sm:grid-cols-2 gap-4">
                <Field label="Thumbnail" hint="Square-ish. Shown on listing cards.">
                  <ImageDrop
                    value={form.thumbnail}
                    onChange={(v) => setForm((f) => ({ ...f, thumbnail: v }))}
                    label="thumbnail"
                  />
                </Field>
                <Field label="Banner" hint="Wide. Fills the hero of the dedicated page.">
                  <ImageDrop
                    value={form.banner}
                    onChange={(v) => setForm((f) => ({ ...f, banner: v }))}
                    label="banner"
                  />
                </Field>
              </div>
              <div className="grid sm:grid-cols-3 gap-4">
                <Field label="Mode">
                  <select className="input mt-1" value={form.mode} onChange={set('mode')}>
                    {MODES.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
                  </select>
                </Field>
                <Field label="Location" className="sm:col-span-2">
                  <input
                    className="input mt-1" value={form.location} onChange={set('location')}
                    placeholder={form.mode === 'online' ? 'Online' : 'Campus / city'}
                  />
                </Field>
              </div>
              <div className="grid sm:grid-cols-3 gap-4">
                <Field label="Difficulty">
                  <select className="input mt-1" value={form.difficulty} onChange={set('difficulty')}>
                    {DIFFICULTIES.map((d) => <option key={d.value} value={d.value}>{d.label}</option>)}
                  </select>
                </Field>
                <Field label="Prize pool">
                  <input type="number" min="0" className="input mt-1" value={form.prize_pool} onChange={set('prize_pool')} />
                </Field>
                <Field label="Currency">
                  <input className="input mt-1" value={form.prize_currency} onChange={set('prize_currency')} />
                </Field>
              </div>
              <Field label="Tags" hint="Comma separated — e.g. AI, Web3, Design">
                <input className="input mt-1" value={form.tags} onChange={set('tags')} />
              </Field>
              <div className="grid sm:grid-cols-3 gap-4">
                <Field label="Organiser">
                  <input className="input mt-1" value={form.organizer_name} onChange={set('organizer_name')} />
                </Field>
                <Field label="Contact email">
                  <input type="email" className="input mt-1" value={form.contact_email} onChange={set('contact_email')} />
                </Field>
                <Field label="Theme colour">
                  <input type="color" className="input mt-1 h-10 p-1" value={form.theme_color} onChange={set('theme_color')} />
                </Field>
              </div>
            </>
          )}

          {tab === 'content' && (
            <>
              {[
                ['description', 'About this hackathon', 'The main story: what it is, what participants build, why it matters. Markdown or HTML.'],
                ['eligibility', 'Who can take part', 'Year, branch, prior experience — anything that decides who is allowed in.'],
                ['prizes_description', 'Prizes', 'Break down the prize pool, perks, certificates and internships.'],
                ['rules', 'Rules & code of conduct', 'Team size, plagiarism policy, judging criteria, disqualification rules.'],
              ].map(([key, label, hint]) => (
                <Field key={key} label={label} hint={hint}>
                  <textarea className="input mt-1 min-h-[120px]" value={form[key]} onChange={set(key)} />
                </Field>
              ))}

              <div>
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium">FAQs</span>
                  <button
                    type="button"
                    className="btn-secondary text-xs !py-1"
                    onClick={() => setForm((f) => ({ ...f, faqs: [...f.faqs, { question: '', answer: '' }] }))}
                  >
                    <Plus className="w-3.5 h-3.5" /> Add FAQ
                  </button>
                </div>
                <div className="space-y-3 mt-2">
                  {form.faqs.map((faq, i) => (
                    <div key={i} className="rounded-xl border border-surface-200 dark:border-surface-700 p-3 space-y-2">
                      <div className="flex items-center gap-2">
                        <input
                          className="input !py-1.5 text-sm"
                          placeholder="Question"
                          value={faq.question}
                          onChange={(e) => setForm((f) => ({
                            ...f,
                            faqs: f.faqs.map((x, idx) => idx === i ? { ...x, question: e.target.value } : x),
                          }))}
                        />
                        <button
                          type="button" className="btn-icon shrink-0"
                          onClick={() => setForm((f) => ({ ...f, faqs: f.faqs.filter((_, idx) => idx !== i) }))}
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                      <textarea
                        className="input !py-1.5 text-sm min-h-[60px]"
                        placeholder="Answer"
                        value={faq.answer}
                        onChange={(e) => setForm((f) => ({
                          ...f,
                          faqs: f.faqs.map((x, idx) => idx === i ? { ...x, answer: e.target.value } : x),
                        }))}
                      />
                    </div>
                  ))}
                  {form.faqs.length === 0 && (
                    <p className="text-xs text-surface-400">
                      No FAQs yet — these show as an expandable list on the hackathon page.
                    </p>
                  )}
                </div>
              </div>
            </>
          )}

          {tab === 'schedule' && (
            <>
              <div className="grid sm:grid-cols-2 gap-4">
                <Field label="Registration opens" hint="Leave blank to open immediately.">
                  <input type="datetime-local" className="input mt-1" value={form.registration_opens_at} onChange={set('registration_opens_at')} />
                </Field>
                <Field label="Registration deadline">
                  <input type="datetime-local" className="input mt-1" value={form.registration_deadline} onChange={set('registration_deadline')} />
                </Field>
                <Field label="Hackathon starts">
                  <input type="datetime-local" className="input mt-1" value={form.starts_at} onChange={set('starts_at')} />
                </Field>
                <Field label="Hackathon ends">
                  <input type="datetime-local" className="input mt-1" value={form.ends_at} onChange={set('ends_at')} />
                </Field>
              </div>
              <Field label="Participant cap" hint="Leave blank for unlimited. Registrations close automatically when the cap is hit.">
                <input type="number" min="0" className="input mt-1" value={form.max_participants} onChange={set('max_participants')} />
              </Field>
            </>
          )}

          {tab === 'settings' && (
            <>
              <Field label="Status" hint="Only published hackathons are visible to students.">
                <select className="input mt-1" value={form.status} onChange={set('status')}>
                  {STATUSES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
                </select>
              </Field>

              {[
                ['show_registration_count', 'Show the registration count publicly',
                  'Turn this off and the number disappears from cards and the hero — nobody sees how many people signed up.'],
                ['show_leaderboard', 'Show a public leaderboard',
                  'Ranks participants once round results are published.'],
                ['email_notifications', 'Send email notifications',
                  'Registration confirmations, round openings, results and winner announcements.'],
              ].map(([key, label, hint]) => (
                <label key={key} className="flex items-start gap-3 p-3 rounded-xl border border-surface-200 dark:border-surface-700 cursor-pointer">
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={form[key]}
                    onChange={set(key)}
                  />
                  <span>
                    <span className="text-sm font-medium block">{label}</span>
                    <span className="text-xs text-surface-400">{hint}</span>
                  </span>
                </label>
              ))}
            </>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 p-5 border-t border-surface-100 dark:border-surface-800">
          <button type="button" className="btn-secondary" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn-primary" disabled={saving}>
            {saving && <Loader2 className="w-4 h-4 animate-spin" />}
            {instance ? 'Save changes' : 'Create hackathon'}
          </button>
        </div>
      </form>
    </div>
  )
}

const HackathonManager = () => {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [editing, setEditing] = useState(null)
  const [showModal, setShowModal] = useState(false)
  const [deleting, setDeleting] = useState(null)

  const { data: hackathons = [], isLoading } = useQuery({
    queryKey: ['admin-hackathons'],
    queryFn: () => hackathonAdminService.getHackathons({ page_size: 200 }),
  })

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['admin-hackathons'] })

  const saveMutation = useMutation({
    mutationFn: (payload) => (editing
      ? hackathonAdminService.update(editing.id, payload)
      : hackathonAdminService.create(payload)),
    onSuccess: (data) => {
      toast.success(editing ? 'Hackathon updated' : 'Hackathon created')
      setShowModal(false)
      setEditing(null)
      refresh()
      if (!editing) navigate(`/admin/hackathons/${data.id}`)
    },
    onError: (err) => toast.error(formatApiError(err, 'Could not save the hackathon')),
  })

  const deleteMutation = useMutation({
    mutationFn: (id) => hackathonAdminService.remove(id),
    onSuccess: () => {
      toast.success('Hackathon deleted')
      setDeleting(null)
      refresh()
    },
    onError: (err) => toast.error(formatApiError(err, 'Could not delete')),
  })

  const filtered = useMemo(() => hackathons.filter((h) => {
    if (statusFilter && h.status !== statusFilter) return false
    if (!search.trim()) return true
    const q = search.toLowerCase()
    return `${h.title} ${h.tagline} ${h.organizer_name}`.toLowerCase().includes(q)
  }), [hackathons, search, statusFilter])

  const totals = useMemo(() => ({
    all: hackathons.length,
    live: hackathons.filter((h) => h.status === 'published').length,
    participants: hackathons.reduce((sum, h) => sum + (h.registrations_count || 0), 0),
  }), [hackathons])

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">Hackathons</h1>
          <p className="text-surface-500 text-sm mt-1">
            Run multi-round competitions end to end — rounds, shortlisting, grading,
            winners and participant emails.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            className="btn-secondary"
            onClick={() => navigate('/admin/hackathons/ai')}
          >
            <Wand2 className="w-4 h-4" /> AI Studio
          </button>
          <button
            type="button"
            className="btn-primary"
            onClick={() => { setEditing(null); setShowModal(true) }}
          >
            <Plus className="w-4 h-4" /> New hackathon
          </button>
        </div>
      </div>

      <div className="grid sm:grid-cols-3 gap-4">
        {[
          ['Hackathons', totals.all, Trophy],
          ['Published', totals.live, Eye],
          ['Total registrations', totals.participants, Users],
        ].map(([label, value, Icon]) => (
          <div key={label} className="card p-4 flex items-center gap-3">
            <span className="w-10 h-10 rounded-xl bg-primary-50 dark:bg-primary-900/20 flex items-center justify-center">
              <Icon className="w-5 h-5 text-primary-600" />
            </span>
            <div>
              <div className="text-xl font-bold">{value}</div>
              <div className="text-xs text-surface-400">{label}</div>
            </div>
          </div>
        ))}
      </div>

      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-surface-400" />
          <input
            className="input pl-9"
            placeholder="Search hackathons"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <select className="input sm:w-44" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="">All statuses</option>
          {STATUSES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
        </select>
      </div>

      {isLoading ? <Loading /> : filtered.length === 0 ? (
        <div className="card p-12 text-center">
          <Trophy className="w-12 h-12 text-surface-300 mx-auto mb-4" />
          <h3 className="font-semibold text-lg">No hackathons yet</h3>
          <p className="text-sm text-surface-500 mt-1 max-w-md mx-auto">
            Create one from scratch, or let the AI Studio draft the whole event —
            description, rules, prizes and a full round structure — in one go.
          </p>
          <div className="flex items-center justify-center gap-2 mt-5">
            <button type="button" className="btn-primary" onClick={() => { setEditing(null); setShowModal(true) }}>
              <Plus className="w-4 h-4" /> New hackathon
            </button>
            <button type="button" className="btn-secondary" onClick={() => navigate('/admin/hackathons/ai')}>
              <Wand2 className="w-4 h-4" /> Draft with AI
            </button>
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          {filtered.map((h) => (
            <div key={h.id} className="card p-4 flex flex-wrap items-center gap-4">
              <div className="w-14 h-14 rounded-xl overflow-hidden shrink-0 flex items-center justify-center"
                style={{ background: `${h.theme_color || '#4f46e5'}22` }}>
                {h.thumbnail_url
                  ? <img src={h.thumbnail_url} alt="" className="w-full h-full object-cover" />
                  : <Trophy className="w-6 h-6" style={{ color: h.theme_color || '#4f46e5' }} />}
              </div>

              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <button
                    type="button"
                    onClick={() => navigate(`/admin/hackathons/${h.id}`)}
                    className="font-semibold hover:text-primary-600 truncate text-left"
                  >
                    {h.title}
                  </button>
                  <span className={`badge ${STATUS_TINT[h.status]}`}>
                    {labelOf(STATUSES, h.status, h.status)}
                  </span>
                  {h.status === 'published' && (
                    <span className={`badge ${registrationMeta(h.registration_state).tint}`}>
                      {registrationMeta(h.registration_state).label}
                    </span>
                  )}
                  {h.results_announced && <span className="badge badge-success">Winners out</span>}
                </div>
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-surface-500 mt-1.5">
                  <span className="inline-flex items-center gap-1">
                    <Users className="w-3.5 h-3.5" />{h.registrations_count} registered
                  </span>
                  <span className="inline-flex items-center gap-1">
                    <Layers className="w-3.5 h-3.5" />{h.stages_count} round{h.stages_count === 1 ? '' : 's'}
                  </span>
                  {h.starts_at && <span>Starts {formatDate(h.starts_at)}</span>}
                  {!h.show_registration_count && (
                    <span className="text-amber-600">Count hidden from students</span>
                  )}
                </div>
              </div>

              <div className="flex items-center gap-1.5 shrink-0">
                <button
                  type="button" className="btn-secondary text-xs !py-1.5"
                  onClick={() => navigate(`/admin/hackathons/${h.id}`)}
                >
                  <Settings2 className="w-3.5 h-3.5" /> Rounds
                </button>
                <button
                  type="button" className="btn-secondary text-xs !py-1.5"
                  onClick={() => navigate(`/admin/hackathons/${h.id}/participants`)}
                >
                  <BarChart3 className="w-3.5 h-3.5" /> Participants
                </button>
                <a
                  href={`/hackathons/${h.id}`}
                  target="_blank"
                  rel="noreferrer"
                  className="btn-icon"
                  title="Preview the public page"
                >
                  <ExternalLink className="w-4 h-4" />
                </a>
                <button
                  type="button" className="btn-icon"
                  onClick={() => { setEditing(h); setShowModal(true) }}
                  title="Edit"
                >
                  <Pencil className="w-4 h-4" />
                </button>
                <button
                  type="button" className="btn-icon hover:text-rose-500"
                  onClick={() => setDeleting(h)}
                  title="Delete"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {showModal && (
        <HackathonModal
          instance={editing}
          saving={saveMutation.isPending}
          onClose={() => { setShowModal(false); setEditing(null) }}
          onSubmit={(payload) => saveMutation.mutate(payload)}
        />
      )}

      {deleting && (
        <ConfirmDialog
          label={`the hackathon "${deleting.title}" and every registration and submission in it`}
          deleting={deleteMutation.isPending}
          onCancel={() => setDeleting(null)}
          onConfirm={() => deleteMutation.mutate(deleting.id)}
        />
      )}
    </div>
  )
}

export default HackathonManager
