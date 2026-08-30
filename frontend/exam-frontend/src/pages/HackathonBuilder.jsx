import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  ArrowLeft, Plus, Trash2, Loader2, Save, Users, ExternalLink, Wand2,
  BarChart3, Eye, CheckCircle2, AlertTriangle,
} from 'lucide-react'
import { hackathonAdminService } from '../services/hackathonAdminService'
import {
  useDragReorder, DragHandle, ReorderStatus, ConfirmDialog, formatApiError,
} from '../components/admin/builderShared'
import StageSettings from '../components/admin/hackathon/StageSettings'
import StageItemsEditor from '../components/admin/hackathon/StageItemsEditor'
import Loading from '../components/common/Loading'
import { stageMeta, formatDateTime } from '../components/hackathons/hackathonShared'

const newStage = (index) => ({
  title: `Round ${index + 1}`,
  stage_type: 'quiz',
  status: 'draft',
  description: '',
  instructions: '',
  duration_minutes: 60,
  max_attempts: 1,
  shuffle_items: false,
  qualification_mode: 'cutoff',
  cutoff_score: 0,
  max_score: 100,
  allowed_file_types: [],
  max_file_mb: 50,
  max_files: 1,
  allow_resubmission: true,
})

const HackathonBuilder = () => {
  const { hackathonId } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const [selectedId, setSelectedId] = useState(null)
  const [draft, setDraft] = useState(null)
  const [dirty, setDirty] = useState(false)
  const [tab, setTab] = useState('settings')
  const [deleting, setDeleting] = useState(null)
  const [reorderSaving, setReorderSaving] = useState(false)

  const { data: hackathon, isLoading } = useQuery({
    queryKey: ['admin-hackathon', hackathonId],
    queryFn: () => hackathonAdminService.get(hackathonId),
  })

  const stagesKey = ['admin-hackathon-stages', hackathonId]
  const { data: stages = [] } = useQuery({
    queryKey: stagesKey,
    queryFn: () => hackathonAdminService.getStages(hackathonId),
  })

  const { data: overview } = useQuery({
    queryKey: ['admin-hackathon-overview', hackathonId],
    queryFn: () => hackathonAdminService.overview(hackathonId),
  })

  const refreshStages = () => {
    queryClient.invalidateQueries({ queryKey: stagesKey })
    queryClient.invalidateQueries({ queryKey: ['admin-hackathon-overview', hackathonId] })
  }

  // Select the first round automatically, and re-sync the editor when the
  // selected round changes on the server.
  useEffect(() => {
    if (!stages.length) { setSelectedId(null); setDraft(null); return }
    const current = stages.find((s) => s.id === selectedId)
    if (!current) {
      setSelectedId(stages[0].id)
      setDraft({ ...stages[0] })
      setDirty(false)
    } else if (!dirty) {
      setDraft({ ...current })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stages, selectedId])

  const createMutation = useMutation({
    mutationFn: () => hackathonAdminService.createStage(hackathonId, newStage(stages.length)),
    onSuccess: (data) => {
      toast.success('Round added')
      setSelectedId(data.id)
      setDraft({ ...data })
      setDirty(false)
      refreshStages()
    },
    onError: (err) => toast.error(formatApiError(err, 'Could not add the round')),
  })

  const saveMutation = useMutation({
    mutationFn: () => {
      // Send only writable fields; the serializer rejects nothing but the
      // read-only ones would be silently dropped anyway.
      const WRITABLE = [
        'title', 'description', 'instructions', 'stage_type', 'status',
        'starts_at', 'ends_at', 'duration_minutes', 'shuffle_items',
        'max_attempts', 'notebook', 'submission_instructions',
        'allowed_file_types', 'max_file_mb', 'max_files', 'require_repo_url',
        'require_demo_url', 'require_video_url', 'allow_resubmission',
        'max_score', 'qualification_mode', 'cutoff_score', 'top_n',
      ]
      const payload = {}
      WRITABLE.forEach((key) => { if (draft[key] !== undefined) payload[key] = draft[key] })
      return hackathonAdminService.updateStage(draft.id, payload)
    },
    onSuccess: () => {
      toast.success('Round saved')
      setDirty(false)
      refreshStages()
    },
    onError: (err) => toast.error(formatApiError(err, 'Could not save the round')),
  })

  const deleteMutation = useMutation({
    mutationFn: (id) => hackathonAdminService.deleteStage(id),
    onSuccess: () => {
      toast.success('Round deleted')
      setDeleting(null)
      setSelectedId(null)
      setDraft(null)
      refreshStages()
    },
    onError: (err) => toast.error(formatApiError(err, 'Could not delete the round')),
  })

  const reorder = async (ids) => {
    setReorderSaving(true)
    try {
      await hackathonAdminService.reorderStages(hackathonId, ids)
      refreshStages()
    } catch {
      toast.error('Could not save the new order')
    } finally {
      setReorderSaving(false)
    }
  }

  const { list, draggingId, rowProps, handleProps } = useDragReorder(stages, reorder)

  const statsByStage = useMemo(() => {
    const map = {}
    ;(overview?.stages || []).forEach((s) => { map[s.id] = s })
    return map
  }, [overview])

  const setField = (key, value) => {
    setDraft((d) => ({ ...d, [key]: value }))
    setDirty(true)
  }

  if (isLoading) return <Loading />
  if (!hackathon) {
    return (
      <div className="card p-12 text-center">
        <h2 className="font-semibold text-lg">Hackathon not found</h2>
        <button type="button" className="btn-primary mt-4" onClick={() => navigate('/admin/hackathons')}>
          Back to hackathons
        </button>
      </div>
    )
  }

  const canEditItems = draft && (draft.stage_type === 'quiz' || draft.stage_type === 'coding')

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <button
            type="button"
            onClick={() => navigate('/admin/hackathons')}
            className="inline-flex items-center gap-1.5 text-sm text-surface-500 hover:text-primary-600 mb-2"
          >
            <ArrowLeft className="w-4 h-4" /> All hackathons
          </button>
          <h1 className="text-2xl font-bold truncate">{hackathon.title}</h1>
          <p className="text-sm text-surface-500 mt-1">
            Build the rounds participants move through. Rounds run in order — clearing one
            unlocks the next.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button" className="btn-secondary"
            onClick={() => navigate(`/admin/hackathons/ai?hackathon=${hackathonId}`)}
          >
            <Wand2 className="w-4 h-4" /> AI Studio
          </button>
          <button
            type="button" className="btn-secondary"
            onClick={() => navigate(`/admin/hackathons/${hackathonId}/participants`)}
          >
            <BarChart3 className="w-4 h-4" /> Participants
          </button>
          <a href={`/hackathons/${hackathonId}`} target="_blank" rel="noreferrer" className="btn-secondary">
            <ExternalLink className="w-4 h-4" /> Preview
          </a>
        </div>
      </div>

      {/* Stats strip */}
      {overview && (
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
          {[
            ['Registered', overview.registrations_total, Users],
            ['Page views', overview.views, Eye],
            ['Rounds published', `${overview.stages_published}/${overview.stages_total}`, CheckCircle2],
            ['Awaiting review', overview.pending_review, AlertTriangle],
            ['Winners', overview.winners, BarChart3],
          ].map(([label, value, Icon]) => (
            <div key={label} className="card p-3 flex items-center gap-2.5">
              <Icon className="w-4 h-4 text-surface-400 shrink-0" />
              <div className="min-w-0">
                <div className="font-semibold">{value}</div>
                <div className="text-xs text-surface-400 truncate">{label}</div>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="grid lg:grid-cols-[300px_1fr] gap-6 items-start">
        {/* Round list */}
        <aside className="space-y-3 lg:sticky lg:top-4">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold">Rounds</h2>
            <button
              type="button"
              className="btn-primary text-xs !py-1.5"
              onClick={() => createMutation.mutate()}
              disabled={createMutation.isPending}
            >
              {createMutation.isPending
                ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
                : <Plus className="w-3.5 h-3.5" />}
              Add round
            </button>
          </div>

          <ReorderStatus saving={reorderSaving} saved={false} hint="Drag to change the order rounds run in" />

          {list.length === 0 ? (
            <div className="card p-6 text-center">
              <p className="text-sm text-surface-500">
                No rounds yet. A hackathon usually starts with a screening quiz, then a
                coding round, and ends with a project submission.
              </p>
              <button
                type="button" className="btn-primary mt-4 w-full justify-center"
                onClick={() => createMutation.mutate()}
              >
                <Plus className="w-4 h-4" /> Add the first round
              </button>
            </div>
          ) : (
            <div className="space-y-2">
              {list.map((stage, index) => {
                const meta = stageMeta(stage.stage_type)
                const Icon = meta.icon
                const active = stage.id === selectedId
                const stats = statsByStage[stage.id]
                return (
                  <div
                    key={stage.id}
                    {...rowProps(stage.id)}
                    className={`card p-3 cursor-pointer transition-all ${
                      active ? 'ring-2 ring-primary-500' : 'hover:border-primary-200'
                    } ${draggingId === stage.id ? 'opacity-50' : ''}`}
                    onClick={() => {
                      if (dirty && !window.confirm('Discard unsaved changes to this round?')) return
                      setSelectedId(stage.id)
                      setDraft({ ...stage })
                      setDirty(false)
                      setTab('settings')
                    }}
                  >
                    <div className="flex items-start gap-2.5">
                      <DragHandle {...handleProps(stage.id)} className="mt-1 shrink-0" />
                      <span className={`w-7 h-7 rounded-lg flex items-center justify-center shrink-0 ${meta.tint}`}>
                        <Icon className="w-3.5 h-3.5" />
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="text-sm font-medium truncate">
                          {index + 1}. {stage.title}
                        </div>
                        <div className="flex items-center gap-2 text-xs text-surface-400 mt-0.5">
                          <span>{meta.label}</span>
                          <span
                            className={stage.status === 'published' ? 'text-emerald-500' : ''}
                          >
                            {stage.status}
                          </span>
                        </div>
                        {stats && (
                          <div className="text-xs text-surface-400 mt-1">
                            {stats.submitted ?? 0} submitted · {stats.qualified ?? 0} shortlisted
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </aside>

        {/* Round editor */}
        <section className="min-w-0">
          {!draft ? (
            <div className="card p-12 text-center text-surface-500">
              Pick a round on the left, or add one to get started.
            </div>
          ) : (
            <div className="card p-0 overflow-hidden">
              <div className="flex flex-wrap items-center justify-between gap-3 p-5 border-b border-surface-100 dark:border-surface-800">
                <div className="flex items-center gap-1">
                  {[
                    ['settings', 'Round setup'],
                    ...(canEditItems ? [['items', draft.stage_type === 'coding' ? 'Problems' : 'Questions']] : []),
                  ].map(([id, label]) => (
                    <button
                      key={id}
                      type="button"
                      onClick={() => setTab(id)}
                      className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                        tab === id
                          ? 'bg-surface-100 dark:bg-surface-800'
                          : 'text-surface-500 hover:text-surface-700'
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
                <div className="flex items-center gap-2">
                  {draft.results_published && (
                    <span className="badge badge-success">Results published</span>
                  )}
                  <button
                    type="button"
                    className="btn-icon hover:text-rose-500"
                    onClick={() => setDeleting(draft)}
                    title="Delete round"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                  <button
                    type="button"
                    className="btn-primary text-sm"
                    onClick={() => saveMutation.mutate()}
                    disabled={!dirty || saveMutation.isPending}
                  >
                    {saveMutation.isPending
                      ? <Loader2 className="w-4 h-4 animate-spin" />
                      : <Save className="w-4 h-4" />}
                    {dirty ? 'Save changes' : 'Saved'}
                  </button>
                </div>
              </div>

              <div className="p-5">
                {tab === 'settings' ? (
                  <>
                    {draft.status === 'draft' && (
                      <div className="rounded-xl bg-amber-50 dark:bg-amber-900/15 p-3 text-sm text-amber-700 dark:text-amber-300 mb-5 flex items-start gap-2">
                        <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                        <span>
                          This round is a draft — students can't see it. Set it to
                          <strong> Published</strong> once the content is ready; that also
                          emails everyone who is eligible.
                        </span>
                      </div>
                    )}
                    <StageSettings form={draft} onChange={setField} />
                    {draft.starts_at && (
                      <p className="text-xs text-surface-400 mt-4">
                        Opens {formatDateTime(draft.starts_at)}
                        {draft.ends_at ? ` · closes ${formatDateTime(draft.ends_at)}` : ''}
                      </p>
                    )}
                  </>
                ) : (
                  <StageItemsEditor
                    stage={draft}
                    onOpenAi={() => navigate(
                      `/admin/hackathons/ai?hackathon=${hackathonId}&stage=${draft.id}`,
                    )}
                  />
                )}
              </div>
            </div>
          )}
        </section>
      </div>

      {deleting && (
        <ConfirmDialog
          label={`the round "${deleting.title}"`}
          deleting={deleteMutation.isPending}
          onCancel={() => setDeleting(null)}
          onConfirm={() => deleteMutation.mutate(deleting.id)}
        />
      )}
    </div>
  )
}

export default HackathonBuilder
