import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams, Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  ArrowLeft, Clock, Lock, XCircle, Hourglass, AlertTriangle, Play, Loader2,
  CheckCircle2, Trophy,
} from 'lucide-react'
import { hackathonService } from '../services/hackathonService'
import api from '../services/api'
import Loading from '../components/common/Loading'
import QuizArena from '../components/hackathons/QuizArena'
import CodingArena from '../components/hackathons/CodingArena'
import LabArena from '../components/hackathons/LabArena'
import SubmissionArena from '../components/hackathons/SubmissionArena'
import {
  RichContent, stageMeta, useStageTimer, formatDateTime, TIMING_STATES,
} from '../components/hackathons/hackathonShared'

const pad = (n) => String(n).padStart(2, '0')

// ─────────────────────────────────────────────────────────────────────────────

const Blocked = ({ icon: Icon, tone, title, body, hackathonId }) => (
  <div className="min-h-screen flex flex-col items-center justify-center p-6 text-center">
    <div className={`w-16 h-16 rounded-2xl flex items-center justify-center mb-5 ${tone}`}>
      <Icon className="w-8 h-8" />
    </div>
    <h1 className="text-2xl font-bold max-w-lg">{title}</h1>
    <p className="text-surface-500 mt-2 max-w-md">{body}</p>
    <Link to={`/hackathons/${hackathonId}`} className="btn-primary mt-6">
      <ArrowLeft className="w-4 h-4" /> Back to the hackathon
    </Link>
  </div>
)

const StageTimer = ({ endsAt, durationMinutes, startedAt, onExpire }) => {
  // A round can be bounded by its own window, by the per-attempt duration, or both.
  const deadline = useMemo(() => {
    const candidates = []
    if (endsAt) candidates.push(new Date(endsAt).getTime())
    if (durationMinutes > 0 && startedAt) {
      candidates.push(new Date(startedAt).getTime() + durationMinutes * 60000)
    }
    if (!candidates.length) return null
    return new Date(Math.min(...candidates)).toISOString()
  }, [endsAt, durationMinutes, startedAt])

  const t = useStageTimer(deadline, onExpire)
  if (!t) return null

  const urgent = !t.expired && t.days === 0 && t.hours === 0 && t.minutes < 5
  return (
    <div
      className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-semibold tabular-nums ${
        urgent
          ? 'bg-rose-50 text-rose-600 dark:bg-rose-900/20 dark:text-rose-300 animate-pulse'
          : 'bg-surface-100 text-surface-700 dark:bg-surface-800 dark:text-surface-200'
      }`}
    >
      <Clock className="w-4 h-4" />
      {t.expired ? "Time's up" : (
        <>{t.days > 0 ? `${t.days}d ` : ''}{pad(t.hours)}:{pad(t.minutes)}:{pad(t.seconds)}</>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────

const HackathonStage = () => {
  const { hackathonId, stageId } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const [answers, setAnswers] = useState({})
  const [paper, setPaper] = useState(null)
  const [confirmSubmit, setConfirmSubmit] = useState(false)
  const [isRunning, setIsRunning] = useState(false)

  const { data: stage, isLoading, error } = useQuery({
    queryKey: ['hackathon-stage', hackathonId, stageId],
    queryFn: () => hackathonService.getStage(hackathonId, stageId),
    retry: false,
  })

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['hackathon-stage', hackathonId, stageId] })
    queryClient.invalidateQueries({ queryKey: ['hackathon-progress', hackathonId] })
  }

  const startMutation = useMutation({
    mutationFn: () => hackathonService.startStage(hackathonId, stageId),
    onSuccess: (data) => {
      setPaper(data.items || [])
      setAnswers({})
      invalidate()
      toast.success('Round started. Good luck!')
    },
    onError: (err) => toast.error(err?.response?.data?.error || 'Could not start this round.'),
  })

  const submitMutation = useMutation({
    mutationFn: () => {
      const payload = Object.entries(answers).map(([itemId, a]) => ({
        item_id: itemId,
        selected_options: a.selected_options || [],
        numerical_answer: a.numerical_answer === '' ? null : a.numerical_answer,
        answer_text: a.answer_text || '',
        code: a.code || '',
        language: a.language || '',
      }))
      return hackathonService.submitStage(hackathonId, stageId, payload)
    },
    onSuccess: (data) => {
      setConfirmSubmit(false)
      setPaper(null)
      toast.success(data.message || 'Submitted!')
      invalidate()
    },
    onError: (err) => toast.error(err?.response?.data?.error || 'Could not submit your round.'),
  })

  const projectMutation = useMutation({
    mutationFn: (payload) => hackathonService.submitProject(hackathonId, stageId, payload),
    onSuccess: () => {
      toast.success('Your project is with the judges.')
      invalidate()
    },
    onError: (err) => toast.error(err?.response?.data?.error || 'Could not upload your submission.'),
  })

  const syncMutation = useMutation({
    mutationFn: () => hackathonService.syncLab(hackathonId, stageId),
    onSuccess: () => {
      toast.success('Lab progress synced.')
      invalidate()
    },
    onError: () => toast.error('Could not sync your lab progress.'),
  })

  const autoSubmit = useCallback(() => {
    if (paper && !submitMutation.isPending) {
      toast('Time is up — submitting your answers.', { icon: '⏱️' })
      submitMutation.mutate()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paper])

  useEffect(() => {
    if (stage?.title) {
      const previous = document.title
      document.title = `${stage.title} · Round`
      return () => { document.title = previous }
    }
    return undefined
  }, [stage?.title])

  // Warn before a tab close mid-attempt.
  useEffect(() => {
    if (!paper) return undefined
    const handler = (e) => { e.preventDefault(); e.returnValue = '' }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [paper])

  const setAnswer = (itemId, value) => setAnswers((a) => ({ ...a, [itemId]: value }))

  const runCode = async (payload) => {
    setIsRunning(true)
    try {
      return await hackathonService.runCode(hackathonId, stageId, payload)
    } catch (err) {
      toast.error(err?.response?.data?.error || 'The judge is unavailable right now.')
      return null
    } finally {
      setIsRunning(false)
    }
  }

  const downloadFile = async (file) => {
    try {
      const res = await api.get(hackathonService.fileUrl(hackathonId, file.id), {
        responseType: 'blob',
      })
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      a.download = file.original_name || 'submission'
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      toast.error('Could not download that file.')
    }
  }

  if (isLoading) {
    return <div className="min-h-screen flex items-center justify-center"><Loading /></div>
  }

  // ── gated states ──────────────────────────────────────────────────────────
  if (error) {
    const data = error?.response?.data || {}
    if (data.code === 'not_registered') {
      return (
        <Blocked
          icon={Lock}
          tone="bg-surface-100 text-surface-500 dark:bg-surface-800"
          title="You're not registered for this hackathon"
          body="Register on the hackathon page to unlock the rounds. It only takes a minute."
          hackathonId={hackathonId}
        />
      )
    }
    if (data.code === 'not_qualified') {
      return (
        <Blocked
          icon={XCircle}
          tone="bg-rose-50 text-rose-500 dark:bg-rose-900/20"
          title="You weren't shortlisted for this round"
          body="Thank you for competing — the previous round's results are final. Your scores still count on the overall leaderboard, and we'd love to see you in the next hackathon."
          hackathonId={hackathonId}
        />
      )
    }
    if (data.code === 'awaiting_results') {
      return (
        <Blocked
          icon={Hourglass}
          tone="bg-sky-50 text-sky-500 dark:bg-sky-900/20"
          title="Results for the previous round are still being finalised"
          body="Shortlisting happens once every submission has been reviewed. We'll email you the moment this round unlocks for you."
          hackathonId={hackathonId}
        />
      )
    }
    return (
      <Blocked
        icon={AlertTriangle}
        tone="bg-amber-50 text-amber-500 dark:bg-amber-900/20"
        title="This round isn't available"
        body={data.error || 'It may not be published yet, or the link is no longer valid.'}
        hackathonId={hackathonId}
      />
    )
  }

  const meta = stageMeta(stage.stage_type)
  const Icon = meta.icon
  const timing = TIMING_STATES[stage.timing_state] || TIMING_STATES.not_open
  const participation = stage.participation || {}
  const isPaperRound = stage.stage_type === 'quiz' || stage.stage_type === 'coding'
  const alreadyDone = participation.status === 'submitted' || participation.status === 'evaluated'
  const attemptsLeft = (stage.max_attempts || 1) - (participation.attempt_number || 0)
  const inAttempt = Boolean(paper) || participation.status === 'in_progress'

  const header = (
    <header className="sticky top-0 z-40 border-b border-surface-200/70 dark:border-surface-800 bg-white/90 dark:bg-surface-900/90 backdrop-blur">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 h-14 flex items-center justify-between gap-3">
        <button
          type="button"
          onClick={() => {
            if (inAttempt && !window.confirm('Leave this round? Unsubmitted answers will be lost.')) return
            navigate(`/hackathons/${hackathonId}`)
          }}
          className="inline-flex items-center gap-2 text-sm font-medium text-surface-600 dark:text-surface-300 hover:text-primary-600 transition-colors shrink-0"
        >
          <ArrowLeft className="w-4 h-4" />
          <span className="hidden sm:inline">Exit round</span>
        </button>

        <div className="flex-1 min-w-0 flex items-center justify-center gap-2">
          <span className={`w-6 h-6 rounded-lg flex items-center justify-center shrink-0 ${meta.tint}`}>
            <Icon className="w-3.5 h-3.5" />
          </span>
          <span className="text-sm font-semibold truncate">{stage.title}</span>
        </div>

        <div className="shrink-0">
          {inAttempt ? (
            <StageTimer
              endsAt={stage.ends_at}
              durationMinutes={stage.duration_minutes}
              startedAt={participation.started_at}
              onExpire={autoSubmit}
            />
          ) : (
            <span className={`text-xs font-medium ${timing.tint}`}>{timing.label}</span>
          )}
        </div>
      </div>
    </header>
  )

  // ── the brief (shown before an attempt begins) ────────────────────────────
  const showBrief = isPaperRound && !inAttempt

  return (
    <div className="min-h-screen bg-surface-50 dark:bg-surface-950">
      {header}

      <main className="max-w-7xl mx-auto px-4 sm:px-6 py-8">
        {showBrief ? (
          <div className="max-w-2xl mx-auto">
            <div className="card p-8 text-center">
              <span className={`w-16 h-16 rounded-2xl mx-auto flex items-center justify-center mb-5 ${meta.tint}`}>
                <Icon className="w-8 h-8" />
              </span>
              <h1 className="text-2xl font-bold">{stage.title}</h1>
              <p className="text-surface-500 mt-1">{meta.blurb}</p>

              <div className="grid grid-cols-3 gap-3 my-7">
                {[
                  ['Questions', stage.items?.length ?? '—'],
                  ['Marks', stage.max_score || '—'],
                  ['Duration', stage.duration_minutes ? `${stage.duration_minutes} min` : 'Open'],
                ].map(([label, value]) => (
                  <div key={label} className="rounded-xl bg-surface-50 dark:bg-surface-800 p-3">
                    <div className="text-lg font-bold">{value}</div>
                    <div className="text-xs text-surface-400">{label}</div>
                  </div>
                ))}
              </div>

              {stage.instructions && (
                <div className="text-left rounded-xl bg-surface-50 dark:bg-surface-800 p-4 mb-6">
                  <h3 className="text-sm font-semibold mb-2">Before you begin</h3>
                  <RichContent content={stage.instructions} className="text-sm" />
                </div>
              )}

              {alreadyDone ? (
                <div className="space-y-4">
                  <div className="rounded-xl bg-emerald-50 dark:bg-emerald-900/15 p-4 text-left flex items-start gap-3">
                    <CheckCircle2 className="w-5 h-5 text-emerald-600 shrink-0 mt-0.5" />
                    <div>
                      <p className="font-medium text-emerald-700 dark:text-emerald-300">
                        You've completed this round
                      </p>
                      <p className="text-sm text-emerald-600/80 dark:text-emerald-300/70 mt-0.5">
                        {stage.results_published && participation.score != null
                          ? `You scored ${participation.score} / ${participation.max_score}.`
                          : 'Results will be published once every entry has been reviewed.'}
                      </p>
                    </div>
                  </div>

                  {stage.results_published && stage.items?.length > 0 && (
                    <QuizArena
                      items={stage.items}
                      answers={{}}
                      onChange={() => {}}
                      onSubmit={() => {}}
                      readOnly
                      revealed
                      myAnswers={stage.my_answers || []}
                    />
                  )}

                  {attemptsLeft > 0 && stage.is_open && (
                    <button
                      type="button"
                      className="btn-secondary w-full justify-center"
                      onClick={() => startMutation.mutate()}
                    >
                      Use another attempt ({attemptsLeft} left)
                    </button>
                  )}
                </div>
              ) : !stage.is_open ? (
                <div className="rounded-xl bg-surface-100 dark:bg-surface-800 p-4 text-sm text-surface-500">
                  {stage.timing_state === 'upcoming'
                    ? `This round opens ${formatDateTime(stage.starts_at)}.`
                    : stage.timing_state === 'ended'
                      ? 'This round has closed.'
                      : 'The organisers haven\'t scheduled this round yet.'}
                </div>
              ) : (
                <>
                  <button
                    type="button"
                    className="btn-primary w-full justify-center text-base !py-3"
                    onClick={() => startMutation.mutate()}
                    disabled={startMutation.isPending}
                  >
                    {startMutation.isPending
                      ? <Loader2 className="w-5 h-5 animate-spin" />
                      : <Play className="w-5 h-5" />}
                    Start round
                  </button>
                  <p className="text-xs text-surface-400 mt-3">
                    {stage.duration_minutes > 0
                      ? `The timer starts the moment you click. You have ${stage.duration_minutes} minutes.`
                      : 'You can submit any time before the round closes.'}
                    {stage.max_attempts > 1 ? ` ${stage.max_attempts} attempts allowed.` : ''}
                  </p>
                </>
              )}
            </div>
          </div>
        ) : stage.stage_type === 'quiz' ? (
          <QuizArena
            items={paper || stage.items || []}
            answers={answers}
            onChange={setAnswer}
            onSubmit={() => setConfirmSubmit(true)}
          />
        ) : stage.stage_type === 'coding' ? (
          <CodingArena
            items={paper || stage.items || []}
            answers={answers}
            onChange={setAnswer}
            onRun={runCode}
            onSubmit={() => setConfirmSubmit(true)}
            isRunning={isRunning}
          />
        ) : stage.stage_type === 'lab' ? (
          <LabArena
            stage={stage}
            participation={participation}
            onSync={() => syncMutation.mutate()}
            isSyncing={syncMutation.isPending}
          />
        ) : (
          <SubmissionArena
            stage={stage}
            submission={stage.my_submission}
            onSubmit={(payload) => projectMutation.mutate(payload)}
            isSaving={projectMutation.isPending}
            onDownload={downloadFile}
          />
        )}
      </main>

      {confirmSubmit && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50">
          <div className="card w-full max-w-md p-6">
            <div className="w-12 h-12 rounded-2xl bg-primary-50 dark:bg-primary-900/20 flex items-center justify-center mb-4">
              <Trophy className="w-6 h-6 text-primary-600" />
            </div>
            <h2 className="text-lg font-semibold">Submit this round?</h2>
            <p className="text-sm text-surface-500 mt-1">
              You answered {Object.keys(answers).length} of {(paper || stage.items || []).length}{' '}
              {stage.stage_type === 'coding' ? 'problems' : 'questions'}.
              {attemptsLeft > 1
                ? ` You'll have ${attemptsLeft - 1} attempt(s) left.`
                : ' This is your final attempt.'}
            </p>
            <div className="flex justify-end gap-2 mt-6">
              <button
                type="button" className="btn-secondary"
                onClick={() => setConfirmSubmit(false)}
              >
                Keep working
              </button>
              <button
                type="button" className="btn-primary"
                onClick={() => submitMutation.mutate()}
                disabled={submitMutation.isPending}
              >
                {submitMutation.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
                Submit
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default HackathonStage
