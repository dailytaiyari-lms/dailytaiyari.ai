import { useEffect, useMemo, useState } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  Sparkles, Wand2, Loader2, Check, X, AlertTriangle, RefreshCw, Trash2,
  ChevronDown, ChevronRight, Plus, Rocket, ArrowLeft, History, Send,
} from 'lucide-react'
import { hackathonAiService } from '../../../services/hackathonAdminService'
import useGenerationJob from '../../../hooks/useGenerationJob'
import Loading from '../../common/Loading'
import { RichContent, stageMeta, labelOf } from '../../hackathons/hackathonShared'

const KIND_COPY = {
  event: {
    label: 'Whole hackathon',
    blurb: 'Describe the event and get a full page — tagline, description, rules, prizes, FAQs and a round plan.',
    icon: Rocket,
    placeholder:
      'A 3-week AI hackathon for final-year engineering students, focused on building '
      + 'agents that help farmers. Screening quiz, then a coding round, then a project '
      + 'submission with a demo video. ₹1,00,000 prize pool.',
  },
  stages: {
    label: 'Rounds only',
    blurb: 'Already have the event? Generate a well-paced set of rounds for it.',
    icon: ChevronRight,
    placeholder:
      'Three rounds: a 30-minute aptitude + ML fundamentals quiz, a 2-hour DSA coding '
      + 'round, then a week-long project submission judged on impact and polish.',
  },
  stage_content: {
    label: 'Questions for a round',
    blurb: 'Fill an existing quiz or coding round with questions that match your brief.',
    icon: Plus,
    placeholder:
      'Questions on Python fundamentals, pandas and basic machine-learning intuition, '
      + 'pitched at second-year students.',
  },
}

const ITEM_TYPE_LABELS = {
  mcq: 'Single choice', mcq_multi: 'Multiple choice', numerical: 'Numerical',
  subjective: 'Written answer', coding: 'Coding',
}

const Field = ({ label, hint, children }) => (
  <label className="block">
    <span className="text-sm font-medium">{label}</span>
    {children}
    {hint && <span className="block text-xs text-surface-400 mt-1">{hint}</span>}
  </label>
)

// ─────────────────────────────────────────────────────────────────────────────
// Preview cards
// ─────────────────────────────────────────────────────────────────────────────

const StagePreview = ({ stage, checked, onToggle }) => {
  const [open, setOpen] = useState(false)
  const meta = stageMeta(stage.stage_type)
  const Icon = meta.icon
  return (
    <div className={`card p-4 transition-opacity ${checked ? '' : 'opacity-50'}`}>
      <div className="flex items-start gap-3">
        <input type="checkbox" className="mt-1.5" checked={checked} onChange={onToggle} />
        <span className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${meta.tint}`}>
          <Icon className="w-4 h-4" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <h4 className="font-medium truncate">{stage.title}</h4>
            <button type="button" className="btn-icon shrink-0" onClick={() => setOpen((o) => !o)}>
              {open ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
            </button>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs text-surface-400 mt-1">
            <span>{meta.label}</span>
            {stage.duration_minutes > 0 && <span>{stage.duration_minutes} min</span>}
            <span>Max {stage.max_score}</span>
            <span>
              {stage.qualification_mode === 'cutoff' ? `Cut-off ${stage.cutoff_score}`
                : stage.qualification_mode === 'top_n' ? `Top ${stage.top_n}`
                  : stage.qualification_mode === 'all' ? 'Everyone advances' : 'Manual shortlist'}
            </span>
            {(stage.blueprint || []).length > 0 && (
              <span>
                {stage.blueprint.reduce((n, b) => n + b.count, 0)} questions planned
              </span>
            )}
          </div>
          {open && (
            <div className="mt-3 space-y-2 text-sm">
              {stage.description && <RichContent content={stage.description} />}
              {stage.instructions && (
                <div className="rounded-lg bg-surface-50 dark:bg-surface-800 p-3">
                  <span className="text-xs font-semibold block mb-1">Instructions</span>
                  <RichContent content={stage.instructions} className="!text-sm" />
                </div>
              )}
              {(stage.blueprint || []).map((b, i) => (
                <div key={i} className="text-xs text-surface-500">
                  {b.count} × {ITEM_TYPE_LABELS[b.item_type] || b.item_type}
                  {b.marks ? ` · ${b.marks} marks each` : ''}
                  {b.difficulty ? ` · ${b.difficulty}` : ''}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

const ItemPreview = ({ item, index, checked, onToggle }) => {
  const [open, setOpen] = useState(false)
  return (
    <div className={`card p-4 transition-opacity ${checked ? '' : 'opacity-50'} ${
      item.issues?.length ? 'ring-1 ring-amber-300' : ''
    }`}>
      <div className="flex items-start gap-3">
        <input type="checkbox" className="mt-1" checked={checked} onChange={onToggle} />
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <p className="text-sm font-medium">
              {index + 1}. {item.title || item.question_text?.slice(0, 110)}
            </p>
            <button type="button" className="btn-icon shrink-0" onClick={() => setOpen((o) => !o)}>
              {open ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
            </button>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs text-surface-400 mt-1">
            <span className="badge">{ITEM_TYPE_LABELS[item.item_type] || item.item_type}</span>
            <span>{item.marks} marks</span>
            {item.difficulty && <span>{item.difficulty}</span>}
            {item.issues?.length > 0 && (
              <span className="badge badge-warning">
                <AlertTriangle className="w-3 h-3" />{item.issues.length} to check
              </span>
            )}
          </div>
          {open && (
            <div className="mt-3 space-y-2 text-sm">
              <RichContent content={item.question_text} />
              {(item.options || []).map((opt, i) => (
                <div
                  key={i}
                  className={`flex items-start gap-2 p-2 rounded-lg text-sm ${
                    opt.is_correct
                      ? 'bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-300'
                      : 'bg-surface-50 dark:bg-surface-800'
                  }`}
                >
                  {opt.is_correct ? <Check className="w-4 h-4 shrink-0 mt-0.5" /> : <span className="w-4" />}
                  <RichContent content={opt.text} className="!text-sm" />
                </div>
              ))}
              {item.numerical_answer != null && (
                <p className="text-sm">Answer: <strong>{item.numerical_answer}</strong> (±{item.numerical_tolerance})</p>
              )}
              {item.rubric && (
                <div className="rounded-lg bg-surface-50 dark:bg-surface-800 p-3 text-xs">
                  <span className="font-semibold block mb-1">Rubric</span>
                  <RichContent content={item.rubric} className="!text-xs" />
                </div>
              )}
              {(item.coding_test_cases || []).length > 0 && (
                <p className="text-xs text-surface-500">
                  {item.coding_test_cases.length} test case(s),{' '}
                  {item.coding_test_cases.filter((c) => c.is_sample).length} shown as samples
                </p>
              )}
              {item.explanation && (
                <div className="rounded-lg bg-primary-50/60 dark:bg-primary-900/15 p-3 text-xs">
                  <span className="font-semibold block mb-1">Explanation</span>
                  <RichContent content={item.explanation} className="!text-xs" />
                </div>
              )}
              {item.issues?.map((issue, i) => (
                <p key={i} className="text-xs text-amber-600 flex items-start gap-1.5">
                  <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />{issue}
                </p>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Studio
// ─────────────────────────────────────────────────────────────────────────────

const AIHackathonStudio = () => {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()

  const [kind, setKind] = useState('event')
  const [prompt, setPrompt] = useState('')
  const [hackathonId, setHackathonId] = useState(params.get('hackathon') || '')
  const [stageId, setStageId] = useState(params.get('stage') || '')
  const [provider, setProvider] = useState('')
  const [model, setModel] = useState('')
  const [options, setOptions] = useState({
    stage_count: 3, difficulty: 'all_levels', mode: 'online',
    language: 'English', include_stages: true, audience: '', theme: '',
  })
  const [blueprint, setBlueprint] = useState([
    { item_type: 'mcq', count: 10, marks: 4, negative_marks: 1, difficulty: 'mixed' },
  ])
  const [selection, setSelection] = useState(null)
  const [instruction, setInstruction] = useState('')
  const [applying, setApplying] = useState(false)
  const [confirmApply, setConfirmApply] = useState(false)
  const [showHistory, setShowHistory] = useState(false)

  const { data: studio, isLoading } = useQuery({
    queryKey: ['hackathon-ai-options'],
    queryFn: hackathonAiService.options,
  })

  const { data: stages = [] } = useQuery({
    queryKey: ['hackathon-ai-stages', hackathonId],
    queryFn: async () => (await hackathonAiService.stagesFor(hackathonId)).stages || [],
    enabled: !!hackathonId && kind === 'stage_content',
  })

  const { data: history = [], refetch: refetchHistory } = useQuery({
    queryKey: ['hackathon-ai-jobs'],
    queryFn: () => hackathonAiService.listJobs({ page_size: 20 }),
    enabled: showHistory,
  })

  const { job, setJob, error, setError, busy, run, reset } = useGenerationJob(
    hackathonAiService.getJob,
    { onSettled: () => setSelection(null) },
  )

  // Seed provider/model from whatever the tenant has configured.
  useEffect(() => {
    if (!studio?.providers?.length || provider) return
    const first = studio.providers[0]
    setProvider(first.provider || '')
    setModel(first.default_model || first.models?.[0] || '')
    setOptions((o) => ({ ...o, ...(studio.defaults || {}) }))
    if (studio.defaults?.blueprint) setBlueprint(studio.defaults.blueprint)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [studio])

  const providerModels = useMemo(() => {
    const p = (studio?.providers || []).find((x) => x.provider === provider)
    return (p?.models || []).map((m) => (typeof m === 'string' ? { id: m, label: m } : m))
  }, [studio, provider])

  // Keep the model dropdown honest whenever the provider changes.
  useEffect(() => {
    if (!providerModels.length) return
    if (!providerModels.some((m) => m.id === model)) setModel(providerModels[0].id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [providerModels])


  const draft = job?.draft || null
  const draftStages = draft?.stages || []
  const draftItems = draft?.items || []

  const sel = selection ?? {
    stages: new Set(draftStages.filter((s) => s.include !== false).map((s) => s.key)),
    items: new Set(draftItems.filter((i) => i.include !== false).map((i) => i.key)),
  }

  const toggleIn = (bucket, key) => {
    const next = {
      stages: new Set(sel.stages), items: new Set(sel.items),
    }
    if (next[bucket].has(key)) next[bucket].delete(key); else next[bucket].add(key)
    setSelection(next)
  }

  const generate = () => {
    const payload = {
      kind, prompt, provider, model,
      options: kind === 'stage_content'
        ? { ...options, blueprint }
        : options,
      ...(kind !== 'event' ? { hackathon: hackathonId } : {}),
      ...(kind === 'stage_content' ? { stage: stageId } : {}),
      ...(kind === 'event' && hackathonId ? { hackathon: hackathonId } : {}),
    }
    run(() => hackathonAiService.createJob(payload))
  }

  const applyDraft = async () => {
    setApplying(true)
    try {
      const result = await hackathonAiService.apply(job.id, {
        stages: [...sel.stages],
        items: [...sel.items],
      })
      toast.success('Applied to your hackathon 🎉')
      setConfirmApply(false)
      const targetId = result?.summary?.hackathon_id || hackathonId
      if (targetId) navigate(`/admin/hackathons/${targetId}`)
      else reset()
    } catch (err) {
      toast.error(err?.response?.data?.error || err?.response?.data?.detail
        || 'Could not apply the draft.')
    } finally {
      setApplying(false)
    }
  }

  if (isLoading) return <Loading />

  const kindCopy = KIND_COPY[kind]
  const KindIcon = kindCopy.icon
  const canGenerate = !busy && studio?.is_ready
    && (kind !== 'stages' || hackathonId)
    && (kind !== 'stage_content' || stageId)

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <button
            type="button"
            onClick={() => navigate('/admin/hackathons')}
            className="inline-flex items-center gap-1.5 text-sm text-surface-500 hover:text-primary-600 mb-2"
          >
            <ArrowLeft className="w-4 h-4" /> All hackathons
          </button>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Sparkles className="w-6 h-6 text-primary-500" /> AI Hackathon Studio
          </h1>
          <p className="text-sm text-surface-500 mt-1">
            Describe what you want, review everything the AI drafts, then apply only the
            parts you like. Nothing is saved until you confirm.
          </p>
        </div>
        <button type="button" className="btn-secondary" onClick={() => setShowHistory((s) => !s)}>
          <History className="w-4 h-4" /> History
        </button>
      </div>

      {!studio?.is_ready && (
        <div className="card p-4 flex items-start gap-3 border-amber-200 bg-amber-50/60 dark:bg-amber-900/15">
          <AlertTriangle className="w-5 h-5 text-amber-500 shrink-0 mt-0.5" />
          <p className="text-sm text-amber-700 dark:text-amber-300">
            {studio?.not_ready_reason || 'AI generation is not available for this tenant yet.'}
          </p>
        </div>
      )}

      <div className="grid lg:grid-cols-[380px_1fr] gap-6 items-start">
        {/* Composer */}
        <div className="card p-5 space-y-4 lg:sticky lg:top-4">
          <div>
            <span className="text-sm font-medium block mb-2">What should I build?</span>
            <div className="grid gap-2">
              {Object.entries(KIND_COPY).map(([id, copy]) => {
                const Icon = copy.icon
                return (
                  <button
                    key={id}
                    type="button"
                    onClick={() => { setKind(id); reset() }}
                    className={`text-left p-3 rounded-xl border-2 transition-colors ${
                      kind === id
                        ? 'border-primary-500 bg-primary-50/60 dark:bg-primary-900/20'
                        : 'border-surface-200 dark:border-surface-700 hover:border-primary-300'
                    }`}
                  >
                    <span className="flex items-center gap-2 font-medium text-sm">
                      <Icon className="w-4 h-4" />{copy.label}
                    </span>
                    <span className="block text-xs text-surface-500 mt-1">{copy.blurb}</span>
                  </button>
                )
              })}
            </div>
          </div>

          {kind !== 'event' && (
            <Field label="Hackathon">
              <select
                className="input mt-1"
                value={hackathonId}
                onChange={(e) => {
                  setHackathonId(e.target.value)
                  setStageId('')
                  setParams((p) => { p.set('hackathon', e.target.value); return p })
                }}
              >
                <option value="">Choose a hackathon…</option>
                {(studio?.hackathons || []).map((h) => (
                  <option key={h.id} value={h.id}>
                    {h.title} ({h.stages} round{h.stages === 1 ? '' : 's'})
                  </option>
                ))}
              </select>
            </Field>
          )}

          {kind === 'stage_content' && (
            <Field label="Round" hint="Only quiz and coding rounds can hold questions.">
              <select
                className="input mt-1"
                value={stageId}
                onChange={(e) => setStageId(e.target.value)}
                disabled={!hackathonId}
              >
                <option value="">Choose a round…</option>
                {stages.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.title} — {s.stage_type}
                  </option>
                ))}
              </select>
            </Field>
          )}

          <Field label="Your brief">
            <textarea
              className="input mt-1 min-h-[140px]"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder={kindCopy.placeholder}
            />
          </Field>

          {kind === 'event' && (
            <div className="grid grid-cols-2 gap-3">
              <Field label="Difficulty">
                <select
                  className="input mt-1"
                  value={options.difficulty}
                  onChange={(e) => setOptions((o) => ({ ...o, difficulty: e.target.value }))}
                >
                  <option value="beginner">Beginner</option>
                  <option value="intermediate">Intermediate</option>
                  <option value="advanced">Advanced</option>
                  <option value="all_levels">All levels</option>
                </select>
              </Field>
              <Field label="Mode">
                <select
                  className="input mt-1"
                  value={options.mode}
                  onChange={(e) => setOptions((o) => ({ ...o, mode: e.target.value }))}
                >
                  <option value="online">Online</option>
                  <option value="offline">In person</option>
                  <option value="hybrid">Hybrid</option>
                </select>
              </Field>
            </div>
          )}

          {kind !== 'stage_content' && (
            <Field
              label="How many rounds?"
              hint={`Up to ${studio?.limits?.max_stages ?? 10}.`}
            >
              <input
                type="number" min="0" max={studio?.limits?.max_stages ?? 10}
                className="input mt-1"
                value={options.stage_count}
                onChange={(e) => setOptions((o) => ({ ...o, stage_count: e.target.value }))}
              />
            </Field>
          )}

          {kind === 'stage_content' && (
            <div className="space-y-2">
              <span className="text-sm font-medium">Question mix</span>
              {blueprint.map((row, i) => (
                <div key={i} className="flex items-center gap-2">
                  <select
                    className="input !py-1.5 flex-1"
                    value={row.item_type}
                    onChange={(e) => setBlueprint((b) => b.map((r, idx) =>
                      idx === i ? { ...r, item_type: e.target.value } : r))}
                  >
                    {(studio?.item_types || []).map((t) => (
                      <option key={t.id} value={t.id}>{t.label}</option>
                    ))}
                  </select>
                  <input
                    type="number" min="1" className="input !py-1.5 !w-16"
                    value={row.count}
                    onChange={(e) => setBlueprint((b) => b.map((r, idx) =>
                      idx === i ? { ...r, count: Number(e.target.value) } : r))}
                  />
                  <input
                    type="number" min="0" step="0.5" className="input !py-1.5 !w-20"
                    title="Marks each"
                    value={row.marks ?? 1}
                    onChange={(e) => setBlueprint((b) => b.map((r, idx) =>
                      idx === i ? { ...r, marks: Number(e.target.value) } : r))}
                  />
                  <button
                    type="button" className="btn-icon hover:text-rose-500"
                    onClick={() => setBlueprint((b) => b.filter((_, idx) => idx !== i))}
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>
              ))}
              <button
                type="button"
                className="btn-secondary w-full justify-center text-xs !py-1.5"
                onClick={() => setBlueprint((b) => [...b,
                  { item_type: 'mcq', count: 5, marks: 4, negative_marks: 0 }])}
              >
                <Plus className="w-3.5 h-3.5" /> Add a question type
              </button>
              <p className="text-xs text-surface-400">
                Up to {studio?.limits?.max_items_per_request ?? 25} questions per run —
                generate again to add more.
              </p>
            </div>
          )}

          {(studio?.providers || []).length > 1 && (
            <div className="grid grid-cols-2 gap-3">
              <Field label="Provider">
                <select
                  className="input mt-1"
                  value={provider}
                  onChange={(e) => { setProvider(e.target.value); setModel('') }}
                >
                  {studio.providers.map((p) => (
                    <option key={p.provider} value={p.provider}>
                      {p.provider_label || p.provider}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Model">
                <select className="input mt-1" value={model} onChange={(e) => setModel(e.target.value)}>
                  {providerModels.map((m) => (
                    <option key={m.id} value={m.id}>{m.label || m.id}</option>
                  ))}
                </select>
              </Field>
            </div>
          )}

          <button
            type="button"
            className="btn-primary w-full justify-center"
            onClick={generate}
            disabled={!canGenerate}
          >
            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Wand2 className="w-4 h-4" />}
            {busy ? 'Drafting…' : `Generate ${kindCopy.label.toLowerCase()}`}
          </button>

          {error && (
            <p className="text-sm text-rose-500 flex items-start gap-1.5">
              <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />{error}
            </p>
          )}
        </div>

        {/* Preview */}
        <div className="min-w-0 space-y-4">
          {!job ? (
            <div className="card p-12 text-center">
              <KindIcon className="w-12 h-12 text-surface-300 mx-auto mb-4" />
              <h3 className="font-semibold text-lg">Your draft will appear here</h3>
              <p className="text-sm text-surface-500 mt-1 max-w-md mx-auto">
                Write a brief on the left and hit generate. You'll be able to read every
                round and question, untick anything you don't want, and ask for changes
                before a single thing is saved.
              </p>
            </div>
          ) : busy ? (
            <div className="card p-12 text-center">
              <Loader2 className="w-10 h-10 text-primary-500 animate-spin mx-auto mb-4" />
              <h3 className="font-semibold">Drafting your hackathon…</h3>
              <p className="text-sm text-surface-500 mt-1">
                This usually takes 20–60 seconds. You can leave this page open.
              </p>
            </div>
          ) : job.status === 'failed' ? (
            <div className="card p-10 text-center">
              <AlertTriangle className="w-10 h-10 text-rose-400 mx-auto mb-3" />
              <h3 className="font-semibold">That run didn't work out</h3>
              <p className="text-sm text-surface-500 mt-1">{job.error || 'Unknown error.'}</p>
              <button
                type="button" className="btn-primary mt-4"
                onClick={() => run(() => hackathonAiService.regenerate(job.id))}
              >
                <RefreshCw className="w-4 h-4" /> Try again
              </button>
            </div>
          ) : (
            <>
              <div className="card p-4 flex flex-wrap items-center justify-between gap-3">
                <div className="text-sm">
                  <strong>{job.summary?.title || 'Draft ready'}</strong>
                  <span className="text-surface-400">
                    {' '}· {draftStages.length} round(s)
                    {draftItems.length ? ` · ${draftItems.length} question(s)` : ''}
                    {job.summary?.flagged ? ` · ${job.summary.flagged} flagged` : ''}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    type="button" className="btn-icon"
                    title="Regenerate"
                    onClick={() => run(() => hackathonAiService.regenerate(job.id))}
                  >
                    <RefreshCw className="w-4 h-4" />
                  </button>
                  <button
                    type="button" className="btn-icon hover:text-rose-500"
                    title="Discard draft"
                    onClick={async () => {
                      await hackathonAiService.discard(job.id)
                      reset()
                    }}
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                  <button
                    type="button" className="btn-primary text-sm"
                    onClick={() => setConfirmApply(true)}
                    disabled={!job.can_apply}
                  >
                    <Check className="w-4 h-4" /> Apply selected
                  </button>
                </div>
              </div>

              {/* Event details */}
              {draft?.hackathon && (
                <div className="card p-5 space-y-3">
                  <h3 className="text-xl font-bold">{draft.hackathon.title}</h3>
                  {draft.hackathon.tagline && (
                    <p className="text-surface-500">{draft.hackathon.tagline}</p>
                  )}
                  <div className="flex flex-wrap gap-1.5">
                    {(draft.hackathon.tags || []).map((t) => (
                      <span key={t} className="badge">{t}</span>
                    ))}
                  </div>
                  {[
                    ['About', draft.hackathon.description],
                    ['Prizes', draft.hackathon.prizes_description],
                    ['Eligibility', draft.hackathon.eligibility],
                    ['Rules', draft.hackathon.rules],
                  ].filter(([, v]) => v).map(([label, value]) => (
                    <div key={label}>
                      <h4 className="text-sm font-semibold mb-1">{label}</h4>
                      <RichContent content={value} />
                    </div>
                  ))}
                  {(draft.hackathon.faqs || []).length > 0 && (
                    <div>
                      <h4 className="text-sm font-semibold mb-1">FAQs</h4>
                      {draft.hackathon.faqs.map((f, i) => (
                        <div key={i} className="py-2 border-b border-surface-100 dark:border-surface-800 last:border-0">
                          <p className="text-sm font-medium">{f.question}</p>
                          <p className="text-sm text-surface-500 mt-0.5">{f.answer}</p>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {draftStages.length > 0 && (
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <h3 className="font-semibold text-sm">
                      Rounds ({sel.stages.size}/{draftStages.length} selected)
                    </h3>
                    <button
                      type="button" className="text-xs text-primary-600 hover:underline"
                      onClick={() => setSelection({
                        stages: sel.stages.size === draftStages.length
                          ? new Set() : new Set(draftStages.map((s) => s.key)),
                        items: sel.items,
                      })}
                    >
                      {sel.stages.size === draftStages.length ? 'Deselect all' : 'Select all'}
                    </button>
                  </div>
                  {draftStages.map((stage) => (
                    <StagePreview
                      key={stage.key}
                      stage={stage}
                      checked={sel.stages.has(stage.key)}
                      onToggle={() => toggleIn('stages', stage.key)}
                    />
                  ))}
                </div>
              )}

              {draftItems.length > 0 && (
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <h3 className="font-semibold text-sm">
                      Questions ({sel.items.size}/{draftItems.length} selected)
                    </h3>
                    <button
                      type="button" className="text-xs text-primary-600 hover:underline"
                      onClick={() => setSelection({
                        stages: sel.stages,
                        items: sel.items.size === draftItems.length
                          ? new Set() : new Set(draftItems.map((i) => i.key)),
                      })}
                    >
                      {sel.items.size === draftItems.length ? 'Deselect all' : 'Select all'}
                    </button>
                  </div>
                  {draftItems.map((item, i) => (
                    <ItemPreview
                      key={item.key}
                      item={item}
                      index={i}
                      checked={sel.items.has(item.key)}
                      onToggle={() => toggleIn('items', item.key)}
                    />
                  ))}
                </div>
              )}

              {/* Refine */}
              <div className="card p-4">
                <h3 className="font-semibold text-sm mb-2">Ask for changes</h3>
                <div className="flex gap-2">
                  <input
                    className="input flex-1"
                    placeholder="Make round 2 harder and add two graph questions"
                    value={instruction}
                    onChange={(e) => setInstruction(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && instruction.trim()) {
                        run(() => hackathonAiService.refine(job.id, instruction))
                        setInstruction('')
                      }
                    }}
                  />
                  <button
                    type="button" className="btn-primary"
                    disabled={!instruction.trim() || busy}
                    onClick={() => {
                      run(() => hackathonAiService.refine(job.id, instruction))
                      setInstruction('')
                    }}
                  >
                    <Send className="w-4 h-4" /> Refine
                  </button>
                </div>
                {(job.revisions || []).length > 0 && (
                  <ul className="mt-3 space-y-1">
                    {job.revisions.slice(-5).map((rev, i) => (
                      <li key={i} className="text-xs text-surface-400">
                        {rev.action}: {rev.note}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </>
          )}
        </div>
      </div>

      {/* History drawer */}
      {showHistory && (
        <div className="fixed inset-0 z-[60] flex justify-end bg-black/50" onClick={() => setShowHistory(false)}>
          <div
            className="w-full max-w-md bg-white dark:bg-surface-900 h-full overflow-y-auto p-5 space-y-3"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between">
              <h2 className="font-semibold">Recent runs</h2>
              <button type="button" className="btn-icon" onClick={() => setShowHistory(false)}>
                <X className="w-4 h-4" />
              </button>
            </div>
            {history.length === 0 ? (
              <p className="text-sm text-surface-400">No runs yet.</p>
            ) : history.map((h) => (
              <button
                key={h.id}
                type="button"
                className="card card-hover p-3 w-full text-left"
                onClick={async () => {
                  const full = await hackathonAiService.getJob(h.id)
                  setJob(full)
                  setKind(full.kind)
                  setSelection(null)
                  setError('')
                  setShowHistory(false)
                }}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium truncate">
                    {h.summary?.title || h.hackathon_title || labelOf(
                      Object.entries(KIND_COPY).map(([id, c]) => ({ value: id, label: c.label })),
                      h.kind, h.kind,
                    )}
                  </span>
                  <span className={`badge shrink-0 ${
                    h.status === 'applied' ? 'badge-success'
                      : h.status === 'failed' ? 'badge-error' : ''
                  }`}>{h.status}</span>
                </div>
                <p className="text-xs text-surface-400 mt-1 line-clamp-2">{h.prompt}</p>
              </button>
            ))}
            <button
              type="button" className="btn-secondary w-full justify-center"
              onClick={() => refetchHistory()}
            >
              <RefreshCw className="w-4 h-4" /> Refresh
            </button>
          </div>
        </div>
      )}

      {/* Apply confirmation */}
      {confirmApply && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center p-4 bg-black/50">
          <div className="card w-full max-w-md p-6">
            <h3 className="text-lg font-bold">Apply this draft?</h3>
            <p className="text-sm text-surface-500 mt-2">
              {kind === 'event'
                ? `A new hackathon will be created as a draft with ${sel.stages.size} round(s). Nothing goes live until you publish it.`
                : kind === 'stages'
                  ? `${sel.stages.size} round(s) will be added to the hackathon, as drafts.`
                  : `${sel.items.size} question(s) will be added to the round.`}
            </p>
            <div className="flex justify-end gap-2 mt-5">
              <button type="button" className="btn-secondary" onClick={() => setConfirmApply(false)}>
                Cancel
              </button>
              <button
                type="button" className="btn-primary"
                onClick={applyDraft}
                disabled={applying}
              >
                {applying ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
                Apply
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default AIHackathonStudio
