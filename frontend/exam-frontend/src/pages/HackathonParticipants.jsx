import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  ArrowLeft, Download, Search, Users, Trophy, Megaphone, X, Loader2, Check,
  AlertTriangle, ChevronRight, Medal, Mail, FileText, ExternalLink, Send,
  Sparkles, Ban, Eye,
} from 'lucide-react'
import api from '../services/api'
import { hackathonAdminService } from '../services/hackathonAdminService'
import { formatApiError } from '../components/admin/builderShared'
import Loading from '../components/common/Loading'
import {
  stageMeta, formatDateTime, formatBytes, QUALIFICATION_BADGES,
  PARTICIPATION_STATES, QUALIFICATION_MODES, labelOf, RichContent,
} from '../components/hackathons/hackathonShared'

const TABS = [
  { id: 'registrations', label: 'Registrations', icon: Users },
  { id: 'rounds', label: 'Rounds & shortlisting', icon: ChevronRight },
  { id: 'winners', label: 'Winners', icon: Trophy },
  { id: 'announcements', label: 'Announcements', icon: Megaphone },
]

const downloadCsv = async (url, filename) => {
  try {
    const res = await api.get(url, { responseType: 'blob' })
    const href = URL.createObjectURL(res.data)
    const a = document.createElement('a')
    a.href = href
    a.download = filename
    a.click()
    URL.revokeObjectURL(href)
  } catch {
    toast.error('Could not export the CSV.')
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Grading drawer
// ─────────────────────────────────────────────────────────────────────────────

const GradingDrawer = ({ participationId, onClose, onGraded }) => {
  const [marks, setMarks] = useState({})
  const [feedbackByAnswer, setFeedbackByAnswer] = useState({})
  const [override, setOverride] = useState('')
  const [feedback, setFeedback] = useState('')

  const { data, isLoading } = useQuery({
    queryKey: ['admin-participation', participationId],
    queryFn: () => hackathonAdminService.getParticipation(participationId),
  })

  useEffect(() => {
    if (!data) return
    setOverride(data.override_score ?? '')
    setFeedback(data.feedback || '')
    const seeded = {}
    ;(data.answers || []).forEach((a) => { seeded[a.id] = a.marks_obtained })
    setMarks(seeded)
  }, [data])

  const gradeMutation = useMutation({
    mutationFn: () => hackathonAdminService.gradeParticipation(participationId, {
      answer_marks: marks,
      answer_feedback: feedbackByAnswer,
      override_score: override === '' ? null : Number(override),
      feedback,
    }),
    onSuccess: () => {
      toast.success('Grading saved')
      onGraded?.()
      onClose()
    },
    onError: (err) => toast.error(formatApiError(err, 'Could not save the grade')),
  })

  const openFile = async (file) => {
    try {
      const res = await api.get(hackathonAdminService.submissionFileUrl(file.id), {
        responseType: 'blob',
      })
      window.open(URL.createObjectURL(res.data), '_blank', 'noopener')
    } catch {
      toast.error('Could not open that file.')
    }
  }

  return (
    <div className="fixed inset-0 z-[60] flex justify-end bg-black/50">
      <div className="w-full max-w-2xl bg-white dark:bg-surface-900 h-full overflow-y-auto shadow-2xl">
        <div className="sticky top-0 z-10 flex items-center justify-between gap-4 p-5 border-b border-surface-100 dark:border-surface-800 bg-white dark:bg-surface-900">
          <div className="min-w-0">
            <h2 className="font-semibold truncate">
              {data?.participant_name || 'Reviewing submission'}
            </h2>
            <p className="text-xs text-surface-400 truncate">
              {data?.stage_title} · {data?.participant_email}
            </p>
          </div>
          <button type="button" onClick={onClose} className="btn-icon shrink-0">
            <X className="w-4 h-4" />
          </button>
        </div>

        {isLoading || !data ? <div className="p-10"><Loading /></div> : (
          <div className="p-5 space-y-5">
            <div className="grid grid-cols-3 gap-3">
              {[
                ['Auto score', data.auto_score],
                ['Effective', data.effective_score],
                ['Out of', data.max_score],
              ].map(([label, value]) => (
                <div key={label} className="rounded-xl bg-surface-50 dark:bg-surface-800 p-3 text-center">
                  <div className="text-lg font-bold">{value}</div>
                  <div className="text-xs text-surface-400">{label}</div>
                </div>
              ))}
            </div>

            {/* Project submission */}
            {data.submission && (
              <div className="card p-4 space-y-3">
                <h3 className="font-semibold text-sm">Project submission</h3>
                {data.submission.title && <p className="font-medium">{data.submission.title}</p>}
                {data.submission.summary && (
                  <p className="text-sm text-surface-600 dark:text-surface-300 whitespace-pre-wrap">
                    {data.submission.summary}
                  </p>
                )}
                <div className="flex flex-wrap gap-2">
                  {[
                    ['Repository', data.submission.repo_url],
                    ['Live demo', data.submission.demo_url],
                    ['Video', data.submission.video_url],
                  ].filter(([, url]) => url).map(([label, url]) => (
                    <a
                      key={label} href={url} target="_blank" rel="noreferrer"
                      className="btn-secondary text-xs !py-1"
                    >
                      <ExternalLink className="w-3.5 h-3.5" /> {label}
                    </a>
                  ))}
                </div>
                {(data.submission.files || []).map((f) => (
                  <button
                    key={f.id}
                    type="button"
                    onClick={() => openFile(f)}
                    className="w-full flex items-center gap-2 p-2.5 rounded-lg bg-surface-50 dark:bg-surface-800 text-sm hover:bg-surface-100 text-left"
                  >
                    <FileText className="w-4 h-4 text-surface-400 shrink-0" />
                    <span className="truncate flex-1">{f.original_name}</span>
                    <span className="text-xs text-surface-400 shrink-0">{formatBytes(f.size_bytes)}</span>
                    <Eye className="w-3.5 h-3.5 text-surface-400 shrink-0" />
                  </button>
                ))}
                {data.submission.is_late && (
                  <p className="text-xs text-amber-600 flex items-center gap-1.5">
                    <AlertTriangle className="w-3.5 h-3.5" /> Submitted after the deadline
                  </p>
                )}
              </div>
            )}

            {/* Answers */}
            {(data.answers || []).length > 0 && (
              <div className="space-y-3">
                <h3 className="font-semibold text-sm">Answers</h3>
                {data.answers.map((answer, i) => (
                  <div
                    key={answer.id}
                    className={`card p-4 ${answer.needs_manual_grading ? 'ring-1 ring-amber-300' : ''}`}
                  >
                    <div className="flex items-start justify-between gap-3 mb-2">
                      <p className="text-sm font-medium">
                        Q{i + 1}. {answer.item?.title || answer.item?.question_text?.slice(0, 90)}
                      </p>
                      {answer.needs_manual_grading && (
                        <span className="badge badge-warning shrink-0">Needs review</span>
                      )}
                    </div>

                    {answer.answer_text && (
                      <div className="rounded-lg bg-surface-50 dark:bg-surface-800 p-3 text-sm whitespace-pre-wrap mb-3">
                        {answer.answer_text}
                      </div>
                    )}
                    {answer.code && (
                      <pre className="rounded-lg bg-surface-900 text-surface-100 p-3 text-xs overflow-x-auto max-h-56 mb-3">
                        {answer.code}
                      </pre>
                    )}
                    {answer.total_count > 0 && (
                      <p className="text-xs text-surface-500 mb-3">
                        {answer.passed_count}/{answer.total_count} hidden tests passed
                      </p>
                    )}
                    {answer.item?.rubric && (
                      <div className="rounded-lg bg-primary-50/60 dark:bg-primary-900/15 p-3 text-xs mb-3">
                        <span className="font-semibold block mb-1">Rubric</span>
                        <RichContent content={answer.item.rubric} className="!text-xs" />
                      </div>
                    )}

                    <div className="flex items-center gap-3">
                      <label className="flex items-center gap-2 text-sm">
                        Marks
                        <input
                          type="number" min="0" step="0.5"
                          max={answer.max_marks}
                          className="input !py-1 !w-24"
                          value={marks[answer.id] ?? ''}
                          onChange={(e) => setMarks((m) => ({ ...m, [answer.id]: e.target.value }))}
                        />
                        <span className="text-surface-400">/ {answer.max_marks}</span>
                      </label>
                      <input
                        className="input !py-1 text-sm flex-1"
                        placeholder="Feedback for this answer"
                        defaultValue={answer.feedback}
                        onChange={(e) => setFeedbackByAnswer((f) => ({ ...f, [answer.id]: e.target.value }))}
                      />
                    </div>
                  </div>
                ))}
              </div>
            )}

            <div className="card p-4 space-y-3">
              <label className="block">
                <span className="text-sm font-medium">Override total score</span>
                <input
                  type="number" min="0" step="0.5"
                  className="input mt-1 max-w-xs"
                  value={override}
                  onChange={(e) => setOverride(e.target.value)}
                  placeholder="Leave blank to use the computed score"
                />
                <span className="block text-xs text-surface-400 mt-1">
                  Use this for lab and project rounds, or to correct an auto-graded total.
                </span>
              </label>
              <label className="block">
                <span className="text-sm font-medium">Feedback to the participant</span>
                <textarea
                  className="input mt-1 min-h-[80px]"
                  value={feedback}
                  onChange={(e) => setFeedback(e.target.value)}
                />
              </label>
            </div>
          </div>
        )}

        <div className="sticky bottom-0 flex items-center justify-end gap-2 p-5 border-t border-surface-100 dark:border-surface-800 bg-white dark:bg-surface-900">
          <button type="button" className="btn-secondary" onClick={onClose}>Close</button>
          <button
            type="button" className="btn-primary"
            onClick={() => gradeMutation.mutate()}
            disabled={gradeMutation.isPending}
          >
            {gradeMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
            Save grading
          </button>
        </div>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Round shortlisting
// ─────────────────────────────────────────────────────────────────────────────

const RoundPanel = ({ stage, onGrade }) => {
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const [picked, setPicked] = useState(null)     // null until the admin touches the list
  const [publishResults, setPublishResults] = useState(true)
  const [notify, setNotify] = useState(true)
  const [confirmForce, setConfirmForce] = useState(null)

  const key = ['admin-stage-participants', stage.id]
  const { data, isLoading } = useQuery({
    queryKey: key,
    queryFn: () => hackathonAdminService.getStageParticipants(stage.id),
  })

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: key })
    queryClient.invalidateQueries({ queryKey: ['admin-hackathon-overview'] })
  }

  const participants = data?.participants || []
  const stats = data?.stats || {}
  const suggested = data?.suggested_qualifiers || []

  // Start from what the round's rule suggests; the admin can then tick freely.
  const selection = picked ?? new Set(suggested)

  const toggle = (id) => {
    const next = new Set(selection)
    if (next.has(id)) next.delete(id); else next.add(id)
    setPicked(next)
  }

  const qualifyMutation = useMutation({
    mutationFn: ({ force }) => hackathonAdminService.qualify(stage.id, {
      mode: 'manual',
      participation_ids: [...selection],
      publish_results: publishResults,
      notify,
      ...(force ? { force: true } : {}),
    }),
    onSuccess: (result) => {
      toast.success(`${result.qualified ?? selection.size} participant(s) shortlisted`)
      setPicked(null)
      setConfirmForce(null)
      refresh()
    },
    onError: (err) => {
      const payload = err?.response?.data
      if (payload?.code === 'pending_review') {
        setConfirmForce(payload.pending)
        return
      }
      toast.error(formatApiError(err, 'Could not apply the shortlist'))
    },
  })

  const publishMutation = useMutation({
    mutationFn: () => hackathonAdminService.publishStageResults(stage.id),
    onSuccess: () => { toast.success('Scores are now visible to participants'); refresh() },
    onError: (err) => toast.error(formatApiError(err, 'Could not publish results')),
  })

  const filtered = useMemo(() => {
    if (!search.trim()) return participants
    const q = search.toLowerCase()
    return participants.filter((p) => `${p.participant_name} ${p.participant_email} ${p.institution}`
      .toLowerCase().includes(q))
  }, [participants, search])

  if (isLoading) return <Loading />

  const meta = stageMeta(stage.stage_type)

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 lg:grid-cols-6 gap-3">
        {[
          ['Eligible', stats.eligible], ['Started', stats.started],
          ['Submitted', stats.submitted], ['Awaiting review', stats.pending_review],
          ['Shortlisted', stats.qualified], ['Eliminated', stats.not_qualified],
        ].map(([label, value]) => (
          <div key={label} className="card p-3 text-center">
            <div className="text-lg font-bold">{value ?? 0}</div>
            <div className="text-xs text-surface-400">{label}</div>
          </div>
        ))}
      </div>

      <div className="card p-4 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="font-semibold">Decide who advances</h3>
            <p className="text-xs text-surface-400 mt-0.5">
              Rule: {labelOf(QUALIFICATION_MODES, stage.qualification_mode, 'Manual shortlist')}
              {stage.qualification_mode === 'cutoff' ? ` at ${stage.cutoff_score}` : ''}
              {stage.qualification_mode === 'top_n' ? ` (top ${stage.top_n})` : ''}
              {' — '}pre-ticked below. Adjust anything you like before applying.
            </p>
          </div>
          <div className="flex items-center gap-2">
            {!stage.results_published && (
              <button
                type="button" className="btn-secondary text-sm"
                onClick={() => publishMutation.mutate()}
                disabled={publishMutation.isPending}
              >
                <Eye className="w-4 h-4" /> Publish scores only
              </button>
            )}
            <button
              type="button" className="btn-primary text-sm"
              onClick={() => qualifyMutation.mutate({ force: false })}
              disabled={qualifyMutation.isPending}
            >
              {qualifyMutation.isPending
                ? <Loader2 className="w-4 h-4 animate-spin" />
                : <Check className="w-4 h-4" />}
              Shortlist {selection.size} participant{selection.size === 1 ? '' : 's'}
            </button>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-4 text-sm">
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={publishResults} onChange={(e) => setPublishResults(e.target.checked)} />
            Publish this round's scores
          </label>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={notify} onChange={(e) => setNotify(e.target.checked)} />
            Email everyone their result
          </label>
          <div className="flex items-center gap-2 ml-auto">
            <button type="button" className="text-xs text-primary-600 hover:underline"
              onClick={() => setPicked(new Set(suggested))}>
              Reset to rule
            </button>
            <button type="button" className="text-xs text-primary-600 hover:underline"
              onClick={() => setPicked(new Set(filtered.map((p) => p.id)))}>
              Select all
            </button>
            <button type="button" className="text-xs text-primary-600 hover:underline"
              onClick={() => setPicked(new Set())}>
              Clear
            </button>
          </div>
        </div>

        {stats.pending_review > 0 && (
          <div className="rounded-xl bg-amber-50 dark:bg-amber-900/15 p-3 text-sm text-amber-700 dark:text-amber-300 flex items-start gap-2">
            <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
            <span>
              {stats.pending_review} submission(s) still need your review. Grade them first
              so the shortlist reflects real scores.
            </span>
          </div>
        )}
      </div>

      <div className="relative">
        <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-surface-400" />
        <input
          className="input pl-9"
          placeholder="Search participants in this round"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {filtered.length === 0 ? (
        <div className="card p-10 text-center text-surface-500">
          Nobody has reached this round yet.
        </div>
      ) : (
        <div className="card p-0 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-surface-50 dark:bg-surface-800 text-xs text-surface-500">
              <tr>
                <th className="p-3 w-10" />
                <th className="p-3 text-left">Participant</th>
                <th className="p-3 text-left">Status</th>
                <th className="p-3 text-right">Score</th>
                <th className="p-3 text-left">Result</th>
                <th className="p-3 text-right">Review</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((p) => {
                const state = PARTICIPATION_STATES[p.status] || PARTICIPATION_STATES.pending
                const badge = QUALIFICATION_BADGES[p.qualification]
                return (
                  <tr key={p.id} className="border-t border-surface-100 dark:border-surface-800">
                    <td className="p-3">
                      <input
                        type="checkbox"
                        checked={selection.has(p.id)}
                        onChange={() => toggle(p.id)}
                      />
                    </td>
                    <td className="p-3">
                      <div className="font-medium truncate">{p.participant_name}</div>
                      <div className="text-xs text-surface-400 truncate">
                        {p.participant_email}{p.institution ? ` · ${p.institution}` : ''}
                      </div>
                    </td>
                    <td className="p-3">
                      <span className={`badge ${state.tint}`}>{state.label}</span>
                      {p.needs_manual_grading && (
                        <span className="badge badge-warning ml-1">Review</span>
                      )}
                    </td>
                    <td className="p-3 text-right tabular-nums">
                      {p.effective_score}<span className="text-surface-400">/{p.max_score}</span>
                    </td>
                    <td className="p-3">
                      {badge && <span className={`badge ${badge.tint}`}>{badge.label}</span>}
                    </td>
                    <td className="p-3 text-right">
                      <button
                        type="button"
                        className="btn-secondary text-xs !py-1"
                        onClick={() => onGrade(p.id)}
                      >
                        {meta.value === 'submission' ? 'Review' : 'Grade'}
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {confirmForce != null && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center p-4 bg-black/50">
          <div className="card w-full max-w-md p-6 text-center">
            <div className="w-12 h-12 rounded-full bg-amber-100 dark:bg-amber-900/30 flex items-center justify-center mx-auto mb-4">
              <AlertTriangle className="w-6 h-6 text-amber-500" />
            </div>
            <h3 className="text-lg font-bold">{confirmForce} submission(s) not reviewed</h3>
            <p className="text-sm text-surface-500 mt-1">
              Shortlisting now locks in the current scores, so ungraded entries may be
              eliminated unfairly. Grade them first, or continue anyway.
            </p>
            <div className="flex justify-center gap-2 mt-5">
              <button type="button" className="btn-secondary" onClick={() => setConfirmForce(null)}>
                Let me grade them
              </button>
              <button
                type="button" className="btn-primary"
                onClick={() => qualifyMutation.mutate({ force: true })}
                disabled={qualifyMutation.isPending}
              >
                Continue anyway
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Page
// ─────────────────────────────────────────────────────────────────────────────

const HackathonParticipants = () => {
  const { hackathonId } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [tab, setTab] = useState('registrations')
  const [search, setSearch] = useState('')
  const [activeStageId, setActiveStageId] = useState(null)
  const [gradingId, setGradingId] = useState(null)

  const [winnerRows, setWinnerRows] = useState([])
  const [announceWinners, setAnnounceWinners] = useState(true)
  const [notifyAll, setNotifyAll] = useState(true)

  const [announcement, setAnnouncement] = useState({
    title: '', body: '', audience: 'all', send_email: true, stage: '',
  })

  const { data: hackathon } = useQuery({
    queryKey: ['admin-hackathon', hackathonId],
    queryFn: () => hackathonAdminService.get(hackathonId),
  })

  const { data: stages = [] } = useQuery({
    queryKey: ['admin-hackathon-stages', hackathonId],
    queryFn: () => hackathonAdminService.getStages(hackathonId),
  })

  const registrationsKey = ['admin-hackathon-registrations', hackathonId, search]
  const { data: regData, isLoading } = useQuery({
    queryKey: registrationsKey,
    queryFn: () => hackathonAdminService.getRegistrations(hackathonId, { search: search || undefined }),
  })

  const { data: announcements = [] } = useQuery({
    queryKey: ['admin-hackathon-announcements', hackathonId],
    queryFn: () => hackathonAdminService.getAnnouncements(hackathonId),
    enabled: tab === 'announcements',
  })

  useEffect(() => {
    if (!activeStageId && stages.length) setActiveStageId(stages[0].id)
  }, [stages, activeStageId])

  const registrations = regData?.registrations || []

  // Seed the winner form from the current standings the first time it opens.
  useEffect(() => {
    if (tab !== 'winners' || winnerRows.length) return
    const existing = registrations.filter((r) => r.is_winner)
      .sort((a, b) => (a.final_rank || 99) - (b.final_rank || 99))
    if (existing.length) {
      setWinnerRows(existing.map((r) => ({
        registration_id: r.id, rank: r.final_rank || 1,
        title: r.winner_title || '', prize: r.prize || '',
      })))
    } else {
      const top = [...registrations]
        .sort((a, b) => Number(b.total_score) - Number(a.total_score))
        .slice(0, 3)
      setWinnerRows(top.map((r, i) => ({
        registration_id: r.id, rank: i + 1,
        title: ['Winner', 'First runner-up', 'Second runner-up'][i] || `Rank ${i + 1}`,
        prize: '',
      })))
    }
  }, [tab, registrations, winnerRows.length])

  const statusMutation = useMutation({
    mutationFn: ({ id, status }) => hackathonAdminService.updateRegistration(hackathonId, id, { status }),
    onSuccess: () => {
      toast.success('Registration updated')
      queryClient.invalidateQueries({ queryKey: registrationsKey })
    },
    onError: (err) => toast.error(formatApiError(err, 'Could not update')),
  })

  const winnersMutation = useMutation({
    mutationFn: () => hackathonAdminService.declareWinners(hackathonId, {
      winners: winnerRows
        .filter((w) => w.registration_id)
        .map((w) => ({ ...w, rank: Number(w.rank) || 1 })),
      announce: announceWinners,
      notify_all: notifyAll,
    }),
    onSuccess: () => {
      toast.success(announceWinners ? 'Winners announced 🎉' : 'Winners saved')
      queryClient.invalidateQueries({ queryKey: registrationsKey })
      queryClient.invalidateQueries({ queryKey: ['admin-hackathon', hackathonId] })
    },
    onError: (err) => toast.error(formatApiError(err, 'Could not declare winners')),
  })

  const announceMutation = useMutation({
    mutationFn: () => hackathonAdminService.announce(hackathonId, {
      ...announcement,
      stage: announcement.stage || null,
    }),
    onSuccess: (data) => {
      toast.success(`Sent to ${data.recipients_count} participant(s)`)
      setAnnouncement({ title: '', body: '', audience: 'all', send_email: true, stage: '' })
      queryClient.invalidateQueries({ queryKey: ['admin-hackathon-announcements', hackathonId] })
    },
    onError: (err) => toast.error(formatApiError(err, 'Could not send the announcement')),
  })

  const activeStage = stages.find((s) => s.id === activeStageId)

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <button
            type="button"
            onClick={() => navigate(`/admin/hackathons/${hackathonId}`)}
            className="inline-flex items-center gap-1.5 text-sm text-surface-500 hover:text-primary-600 mb-2"
          >
            <ArrowLeft className="w-4 h-4" /> Back to rounds
          </button>
          <h1 className="text-2xl font-bold truncate">
            {hackathon?.title || 'Participants'}
          </h1>
          <p className="text-sm text-surface-500 mt-1">
            {regData?.counts?.registered ?? 0} registered ·{' '}
            {regData?.counts?.withdrawn ?? 0} withdrawn
          </p>
        </div>
        <button
          type="button"
          className="btn-secondary"
          onClick={() => downloadCsv(
            hackathonAdminService.exportUrl(hackathonId),
            `${hackathon?.slug || 'hackathon'}-registrations.csv`,
          )}
        >
          <Download className="w-4 h-4" /> Export CSV
        </button>
      </div>

      <div className="flex items-center gap-1 border-b border-surface-200 dark:border-surface-800 overflow-x-auto">
        {TABS.map((t) => {
          const Icon = t.icon
          return (
            <button
              key={t.id}
              type="button"
              onClick={() => setTab(t.id)}
              className={`px-3.5 py-2.5 text-sm font-medium whitespace-nowrap inline-flex items-center gap-1.5 border-b-2 -mb-px transition-colors ${
                tab === t.id
                  ? 'border-primary-500 text-primary-600'
                  : 'border-transparent text-surface-500 hover:text-surface-700'
              }`}
            >
              <Icon className="w-4 h-4" />{t.label}
            </button>
          )
        })}
      </div>

      {/* Registrations */}
      {tab === 'registrations' && (
        <div className="space-y-4">
          <div className="relative">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-surface-400" />
            <input
              className="input pl-9"
              placeholder="Search by name, email or institution"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>

          {isLoading ? <Loading /> : registrations.length === 0 ? (
            <div className="card p-12 text-center">
              <Users className="w-10 h-10 text-surface-300 mx-auto mb-3" />
              <h3 className="font-semibold">No registrations yet</h3>
              <p className="text-sm text-surface-500 mt-1">
                Publish the hackathon and share the link — sign-ups will appear here in real time.
              </p>
            </div>
          ) : (
            <div className="card p-0 overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-surface-50 dark:bg-surface-800 text-xs text-surface-500">
                  <tr>
                    <th className="p-3 text-left">Participant</th>
                    <th className="p-3 text-left">Institution</th>
                    <th className="p-3 text-left">Registered</th>
                    <th className="p-3 text-right">Total score</th>
                    <th className="p-3 text-left">Status</th>
                    <th className="p-3 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {registrations.map((r) => (
                    <tr key={r.id} className="border-t border-surface-100 dark:border-surface-800">
                      <td className="p-3">
                        <div className="font-medium truncate">{r.participant_name}</div>
                        <a href={`mailto:${r.participant_email}`} className="text-xs text-surface-400 hover:text-primary-600 truncate inline-flex items-center gap-1">
                          <Mail className="w-3 h-3" />{r.participant_email}
                        </a>
                      </td>
                      <td className="p-3 text-surface-500 truncate">{r.institution || '—'}</td>
                      <td className="p-3 text-surface-500 whitespace-nowrap">
                        {formatDateTime(r.registered_at)}
                      </td>
                      <td className="p-3 text-right tabular-nums">{r.total_score}</td>
                      <td className="p-3">
                        <span className={`badge ${
                          r.status === 'registered' ? 'badge-success'
                            : r.status === 'disqualified' ? 'badge-error' : ''
                        }`}>
                          {r.status}
                        </span>
                        {r.is_winner && (
                          <span className="badge badge-primary ml-1">
                            <Medal className="w-3 h-3" />{r.winner_title || 'Winner'}
                          </span>
                        )}
                      </td>
                      <td className="p-3 text-right whitespace-nowrap">
                        {r.status === 'disqualified' ? (
                          <button
                            type="button" className="btn-secondary text-xs !py-1"
                            onClick={() => statusMutation.mutate({ id: r.id, status: 'registered' })}
                          >
                            Reinstate
                          </button>
                        ) : (
                          <button
                            type="button" className="btn-secondary text-xs !py-1 hover:text-rose-500"
                            onClick={() => {
                              if (window.confirm(`Disqualify ${r.participant_name}?`)) {
                                statusMutation.mutate({ id: r.id, status: 'disqualified' })
                              }
                            }}
                          >
                            <Ban className="w-3.5 h-3.5" /> Disqualify
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Rounds */}
      {tab === 'rounds' && (
        stages.length === 0 ? (
          <div className="card p-12 text-center">
            <h3 className="font-semibold">No rounds configured</h3>
            <button
              type="button" className="btn-primary mt-4"
              onClick={() => navigate(`/admin/hackathons/${hackathonId}`)}
            >
              Build the rounds
            </button>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="flex items-center gap-2 overflow-x-auto pb-1">
              {stages.map((s, i) => {
                const meta = stageMeta(s.stage_type)
                const Icon = meta.icon
                return (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => setActiveStageId(s.id)}
                    className={`px-3 py-2 rounded-xl text-sm font-medium whitespace-nowrap inline-flex items-center gap-1.5 border-2 transition-colors ${
                      activeStageId === s.id
                        ? 'border-primary-500 bg-primary-50/60 dark:bg-primary-900/20 text-primary-700 dark:text-primary-300'
                        : 'border-surface-200 dark:border-surface-700 text-surface-500 hover:border-primary-300'
                    }`}
                  >
                    <Icon className="w-4 h-4" />{i + 1}. {s.title}
                  </button>
                )
              })}
            </div>
            {activeStage && <RoundPanel stage={activeStage} onGrade={setGradingId} />}
          </div>
        )
      )}

      {/* Winners */}
      {tab === 'winners' && (
        <div className="max-w-3xl space-y-4">
          <div className="card p-5">
            <div className="flex items-start gap-3">
              <Sparkles className="w-5 h-5 text-primary-500 shrink-0 mt-0.5" />
              <div>
                <h3 className="font-semibold">Declare the winners</h3>
                <p className="text-sm text-surface-500 mt-0.5">
                  Ranks are pre-filled from the overall leaderboard. Announcing publishes
                  the podium on the hackathon page and emails every participant.
                </p>
              </div>
            </div>
          </div>

          <div className="space-y-3">
            {winnerRows.map((row, i) => (
              <div key={i} className="card p-4 grid sm:grid-cols-[80px_1fr_1fr_1fr_40px] gap-3 items-end">
                <label className="block">
                  <span className="text-xs font-medium">Rank</span>
                  <input
                    type="number" min="1" className="input mt-1 !py-1.5"
                    value={row.rank}
                    onChange={(e) => setWinnerRows((rows) => rows.map((r, idx) =>
                      idx === i ? { ...r, rank: e.target.value } : r))}
                  />
                </label>
                <label className="block">
                  <span className="text-xs font-medium">Participant</span>
                  <select
                    className="input mt-1 !py-1.5"
                    value={row.registration_id}
                    onChange={(e) => setWinnerRows((rows) => rows.map((r, idx) =>
                      idx === i ? { ...r, registration_id: e.target.value } : r))}
                  >
                    <option value="">Choose…</option>
                    {registrations.map((r) => (
                      <option key={r.id} value={r.id}>
                        {r.participant_name} — {r.total_score} pts
                      </option>
                    ))}
                  </select>
                </label>
                <label className="block">
                  <span className="text-xs font-medium">Title</span>
                  <input
                    className="input mt-1 !py-1.5"
                    placeholder="Winner"
                    value={row.title}
                    onChange={(e) => setWinnerRows((rows) => rows.map((r, idx) =>
                      idx === i ? { ...r, title: e.target.value } : r))}
                  />
                </label>
                <label className="block">
                  <span className="text-xs font-medium">Prize</span>
                  <input
                    className="input mt-1 !py-1.5"
                    placeholder="₹50,000 + internship"
                    value={row.prize}
                    onChange={(e) => setWinnerRows((rows) => rows.map((r, idx) =>
                      idx === i ? { ...r, prize: e.target.value } : r))}
                  />
                </label>
                <button
                  type="button" className="btn-icon hover:text-rose-500 mb-1"
                  onClick={() => setWinnerRows((rows) => rows.filter((_, idx) => idx !== i))}
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            ))}
            <button
              type="button"
              className="btn-secondary w-full justify-center"
              onClick={() => setWinnerRows((rows) => [...rows, {
                registration_id: '', rank: rows.length + 1, title: '', prize: '',
              }])}
            >
              Add a winner
            </button>
          </div>

          <div className="card p-4 space-y-3">
            <label className="flex items-start gap-3">
              <input type="checkbox" className="mt-1" checked={announceWinners} onChange={(e) => setAnnounceWinners(e.target.checked)} />
              <span>
                <span className="text-sm font-medium block">Announce publicly</span>
                <span className="text-xs text-surface-400">
                  Shows the podium on the hackathon page and marks the event completed.
                </span>
              </span>
            </label>
            <label className="flex items-start gap-3">
              <input type="checkbox" className="mt-1" checked={notifyAll} onChange={(e) => setNotifyAll(e.target.checked)} />
              <span>
                <span className="text-sm font-medium block">Email every participant</span>
                <span className="text-xs text-surface-400">
                  Winners get a congratulations mail; everyone else gets a thank-you with
                  the results link.
                </span>
              </span>
            </label>
            <button
              type="button"
              className="btn-primary w-full justify-center"
              onClick={() => winnersMutation.mutate()}
              disabled={winnersMutation.isPending || !winnerRows.some((w) => w.registration_id)}
            >
              {winnersMutation.isPending
                ? <Loader2 className="w-4 h-4 animate-spin" />
                : <Trophy className="w-4 h-4" />}
              {announceWinners ? 'Declare & announce winners' : 'Save winners'}
            </button>
          </div>
        </div>
      )}

      {/* Announcements */}
      {tab === 'announcements' && (
        <div className="max-w-3xl space-y-5">
          <div className="card p-5 space-y-4">
            <h3 className="font-semibold">Send an announcement</h3>
            <label className="block">
              <span className="text-sm font-medium">Subject</span>
              <input
                className="input mt-1"
                value={announcement.title}
                onChange={(e) => setAnnouncement((a) => ({ ...a, title: e.target.value }))}
                placeholder="Round 2 opens tomorrow at 10 AM"
              />
            </label>
            <label className="block">
              <span className="text-sm font-medium">Message</span>
              <textarea
                className="input mt-1 min-h-[140px]"
                value={announcement.body}
                onChange={(e) => setAnnouncement((a) => ({ ...a, body: e.target.value }))}
              />
            </label>
            <div className="grid sm:grid-cols-2 gap-4">
              <label className="block">
                <span className="text-sm font-medium">Audience</span>
                <select
                  className="input mt-1"
                  value={announcement.audience}
                  onChange={(e) => setAnnouncement((a) => ({ ...a, audience: e.target.value }))}
                >
                  <option value="all">Everyone registered</option>
                  <option value="active">Still in the running</option>
                  <option value="qualified">Shortlisted from a round</option>
                  <option value="winners">Winners only</option>
                </select>
              </label>
              {announcement.audience === 'qualified' && (
                <label className="block">
                  <span className="text-sm font-medium">From which round?</span>
                  <select
                    className="input mt-1"
                    value={announcement.stage}
                    onChange={(e) => setAnnouncement((a) => ({ ...a, stage: e.target.value }))}
                  >
                    <option value="">Choose a round…</option>
                    {stages.map((s, i) => (
                      <option key={s.id} value={s.id}>{i + 1}. {s.title}</option>
                    ))}
                  </select>
                </label>
              )}
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={announcement.send_email}
                onChange={(e) => setAnnouncement((a) => ({ ...a, send_email: e.target.checked }))}
              />
              Also send it as an email (otherwise it stays an in-app notification)
            </label>
            <button
              type="button"
              className="btn-primary w-full justify-center"
              onClick={() => announceMutation.mutate()}
              disabled={announceMutation.isPending || !announcement.title.trim() || !announcement.body.trim()}
            >
              {announceMutation.isPending
                ? <Loader2 className="w-4 h-4 animate-spin" />
                : <Send className="w-4 h-4" />}
              Send announcement
            </button>
          </div>

          <div className="space-y-3">
            <h3 className="font-semibold text-sm">Sent</h3>
            {announcements.length === 0 ? (
              <p className="text-sm text-surface-400">Nothing sent yet.</p>
            ) : announcements.map((a) => (
              <div key={a.id} className="card p-4">
                <div className="flex items-start justify-between gap-3">
                  <h4 className="font-medium">{a.title}</h4>
                  <span className="text-xs text-surface-400 shrink-0">
                    {formatDateTime(a.sent_at || a.created_at)}
                  </span>
                </div>
                <p className="text-sm text-surface-600 dark:text-surface-300 mt-1 whitespace-pre-wrap">
                  {a.body}
                </p>
                <div className="flex items-center gap-3 text-xs text-surface-400 mt-2">
                  <span>{a.audience}</span>
                  <span>{a.recipients_count} recipient(s)</span>
                  {a.send_email && <span className="inline-flex items-center gap-1"><Mail className="w-3 h-3" /> emailed</span>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {gradingId && (
        <GradingDrawer
          participationId={gradingId}
          onClose={() => setGradingId(null)}
          onGraded={() => {
            queryClient.invalidateQueries({ queryKey: ['admin-stage-participants'] })
            queryClient.invalidateQueries({ queryKey: registrationsKey })
          }}
        />
      )}
    </div>
  )
}

export default HackathonParticipants
