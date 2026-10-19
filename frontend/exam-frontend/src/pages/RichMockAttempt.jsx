import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import {
  Clock, ChevronLeft, ChevronRight, Flag, Maximize2, AlertTriangle,
  Loader2, Play, CheckCircle2, XCircle, Send, ListChecks,
} from 'lucide-react'
import { mockTestBuilderService } from '../services/mockTestBuilderService'
import { useFeatureLabel } from '../context/tenantStore'
import CodeEditor from '../components/coding/CodeEditor'
import MathRenderer from '../components/chat/MathRenderer'

const MONACO_MODE = { python: 'python', cpp: 'cpp', java: 'java' }

const qKey = (q) => `${q.kind}:${q.ref_id}`

export default function RichMockAttempt() {
  const mockLabel = useFeatureLabel('mock_tests', 'Mock Tests')
  const { testId } = useParams()
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [phase, setPhase] = useState('instructions') // 'instructions' | 'attempt'
  const [starting, setStarting] = useState(false)
  const [meta, setMeta] = useState(null)
  const [paperInfo, setPaperInfo] = useState(null)  // attempts/limits/active id
  const [questions, setQuestions] = useState([])
  const [attemptId, setAttemptId] = useState(null)
  const [current, setCurrent] = useState(0)
  const [answers, setAnswers] = useState({})       // qKey -> answer payload
  const [flagged, setFlagged] = useState({})       // qKey -> bool
  const [remaining, setRemaining] = useState(0)    // seconds
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState(null)
  const [violations, setViolations] = useState(0)
  const [showWarn, setShowWarn] = useState(false)
  const containerRef = useRef(null)
  const startedRef = useRef(Date.now())
  const submittedRef = useRef(false)
  const expiryRef = useRef(null)   // absolute deadline in client-clock ms

  /* ------------------- load paper (no attempt created yet) ------------------- */
  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const paper = await mockTestBuilderService.getPaper(testId)
        if (!alive) return
        setMeta({ mock_test: paper.mock_test })
        setQuestions(paper.questions || [])
        setPaperInfo({
          active_attempt_id: paper.active_attempt_id || null,
          attempts_used: paper.attempts_used ?? 0,
          attempts_remaining: paper.attempts_remaining ?? null,
          can_start: paper.can_start !== false,
        })
      } catch (e) {
        const msg = e?.response?.data?.error || 'Could not load this test.'
        toast.error(msg)
        navigate('/mock-test')
      } finally {
        if (alive) setLoading(false)
      }
    })()
    return () => { alive = false }
  }, [testId, navigate])

  const mt = meta?.mock_test

  /* --------------- convert server saved answers into UI state --------------- */
  const restoreAnswers = useCallback((saved) => {
    if (!saved || typeof saved !== 'object') return
    const next = {}
    const nextFlags = {}
    Object.entries(saved).forEach(([key, v]) => {
      const entry = {}
      if (Array.isArray(v.selected)) entry.selected = v.selected
      if (v.numerical_answer != null) entry.numerical_answer = v.numerical_answer
      if (v.answer_text != null) entry.answer_text = v.answer_text
      if (v.code != null) entry.code = v.code
      if (v.language != null) entry.language = v.language
      next[key] = entry
      if (v.is_marked_for_review) nextFlags[key] = true
    })
    setAnswers(next)
    setFlagged(nextFlags)
  }, [])

  /* --------------- start (or resume) the attempt on user action --------------- */
  const beginAttempt = useCallback(async () => {
    setStarting(true)
    try {
      const started = await mockTestBuilderService.startRich(testId)
      if (started.expired) {
        toast('Your previous attempt timed out and was submitted.', { icon: '⏰' })
        navigate(`/mock-test/live-review/${started.attempt_id}`)
        return
      }
      setQuestions(started.questions || questions)
      setAttemptId(started.attempt?.id)
      if (started.resumed) restoreAnswers(started.saved_answers)
      // Anchor the timer to the server clock so a closed tab never pauses it.
      const t = started.timing
      if (t) {
        const offset = Date.now() - Date.parse(t.server_now)
        expiryRef.current = Date.parse(t.expires_at) + offset
      } else {
        expiryRef.current = Date.now() + (mt?.duration_minutes || 60) * 60000
      }
      startedRef.current = Date.now()
      setRemaining(Math.max(0, Math.round((expiryRef.current - Date.now()) / 1000)))
      setPhase('attempt')
    } catch (e) {
      toast.error(e?.response?.data?.error || 'Could not start this test.')
    } finally {
      setStarting(false)
    }
  }, [testId, navigate, questions, restoreAnswers, mt])

  /* ------------------------- fullscreen ------------------------- */
  const enterFullscreen = useCallback(() => {
    const el = containerRef.current
    if (el?.requestFullscreen) el.requestFullscreen().catch(() => {})
  }, [])

  useEffect(() => {
    if (!mt?.fullscreen_required || phase !== 'attempt' || result) return
    enterFullscreen()
  }, [mt, phase, result, enterFullscreen])

  /* ------------------------- timer (server-anchored) ------------------------- */
  useEffect(() => {
    if (phase !== 'attempt' || result) return
    const tick = () => {
      const secs = expiryRef.current
        ? Math.max(0, Math.round((expiryRef.current - Date.now()) / 1000))
        : 0
      setRemaining(secs)
      if (secs <= 0) { clearInterval(id); handleSubmit(true) }
    }
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, result])

  /* ------------------- proctoring: tab-switch / fullscreen exit ------------------- */
  useEffect(() => {
    if (phase !== 'attempt' || result) return
    const onVisibility = () => {
      if (document.hidden) { bumpViolation(); autosave() }
    }
    const onFsChange = () => {
      if (mt?.fullscreen_required && !document.fullscreenElement && !submittedRef.current) {
        bumpViolation()
      }
    }
    document.addEventListener('visibilitychange', onVisibility)
    document.addEventListener('fullscreenchange', onFsChange)
    return () => {
      document.removeEventListener('visibilitychange', onVisibility)
      document.removeEventListener('fullscreenchange', onFsChange)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, result, mt])

  /* ------------------------- autosave (survives tab close) ------------------------- */
  const savingRef = useRef(false)
  const autosave = useCallback(async () => {
    if (phase !== 'attempt' || result || submittedRef.current || savingRef.current) return
    savingRef.current = true
    try {
      const p = buildPayload()
      const r = await mockTestBuilderService.saveRich(testId, {
        bank_answers: p.bank_answers, item_answers: p.item_answers,
      })
      if (r?.expired) { submittedRef.current = true; setResult(r) }
    } catch { /* best-effort */ } finally { savingRef.current = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, result, testId])

  useEffect(() => {
    if (phase !== 'attempt' || result) return
    const id = setInterval(() => { autosave() }, 15000)
    return () => clearInterval(id)
  }, [phase, result, autosave])

  const bumpViolation = () => {
    setViolations((v) => v + 1)
    setShowWarn(true)
  }

  /* ------------------------- answer helpers ------------------------- */
  const q = questions[current]
  const setAns = (patch) => setAnswers((a) => ({ ...a, [qKey(q)]: { ...(a[qKey(q)] || {}), ...patch } }))
  const cur = q ? (answers[qKey(q)] || {}) : {}

  const isAnswered = (question) => {
    const a = answers[qKey(question)]
    if (!a) return false
    if (['mcq', 'mcq_multi'].includes(question.item_type)) return (a.selected != null && a.selected.length > 0) || a.selected_option != null
    if (question.item_type === 'numerical') return a.numerical_answer != null && a.numerical_answer !== ''
    if (question.item_type === 'subjective') return !!(a.answer_text && a.answer_text.trim())
    if (question.item_type === 'coding') return !!(a.code && a.code.trim())
    return false
  }

  const toggleFlag = () => setFlagged((f) => ({ ...f, [qKey(q)]: !f[qKey(q)] }))

  /* ------------------------- coding run ------------------------- */
  const [running, setRunning] = useState(false)
  const [runResult, setRunResult] = useState(null)
  const runSamples = async () => {
    if (!cur.code || !cur.language) { toast.error('Write some code and pick a language first.'); return }
    setRunning(true); setRunResult(null)
    try {
      const r = await mockTestBuilderService.runCode(testId, { item_id: q.ref_id, code: cur.code, language: cur.language })
      setRunResult(r)
    } catch (e) {
      toast.error(e?.response?.data?.error || 'Run failed')
    } finally { setRunning(false) }
  }

  /* ------------------------- submit ------------------------- */
  const buildPayload = () => {
    const bank_answers = []
    const item_answers = []
    questions.forEach((question) => {
      const a = answers[qKey(question)]
      if (!a) return
      const marked = !!flagged[qKey(question)]
      if (question.kind === 'bank') {
        const entry = { question_id: question.ref_id, is_marked_for_review: marked }
        if (question.item_type === 'numerical') entry.numerical_answer = a.numerical_answer
        else entry.selected_option = a.selected != null && a.selected.length ? String(a.selected[0]) : ''
        bank_answers.push(entry)
      } else {
        const entry = { item_id: question.ref_id, is_marked_for_review: marked }
        if (['mcq', 'mcq_multi'].includes(question.item_type)) entry.selected_options = a.selected || []
        if (question.item_type === 'numerical') entry.numerical_answer = a.numerical_answer
        if (question.item_type === 'subjective') entry.answer_text = a.answer_text || ''
        if (question.item_type === 'coding') { entry.code = a.code || ''; entry.language = a.language || '' }
        item_answers.push(entry)
      }
    })
    return { time_taken_seconds: Math.round((Date.now() - startedRef.current) / 1000), bank_answers, item_answers }
  }

  const handleSubmit = async (auto = false) => {
    if (submittedRef.current) return
    if (!auto && !window.confirm('Submit your test? You cannot change answers afterwards.')) return
    submittedRef.current = true
    setSubmitting(true)
    try {
      const r = await mockTestBuilderService.submitRich(testId, buildPayload())
      setResult(r)
      if (document.fullscreenElement) document.exitFullscreen().catch(() => {})
    } catch (e) {
      submittedRef.current = false
      toast.error(e?.response?.data?.error || 'Submission failed')
    } finally { setSubmitting(false) }
  }

  const fmt = (s) => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`

  if (loading) return <div className="flex justify-center items-center h-screen"><Loader2 className="w-8 h-8 animate-spin text-primary-500" /></div>

  /* ------------------------- result screen ------------------------- */
  if (result) {
    const visible = result.results_visible
    const a = result.attempt
    return (
      <div className="min-h-screen flex items-center justify-center p-4 bg-surface-50 dark:bg-surface-950">
        <div className="max-w-md w-full bg-white dark:bg-surface-900 rounded-3xl shadow-xl p-8 text-center">
          <CheckCircle2 className="w-14 h-14 text-emerald-500 mx-auto mb-4" />
          <h2 className="text-2xl font-bold mb-2">Test submitted</h2>
          {result.pending_manual ? (
            <p className="text-surface-500 mb-6">Your test includes subjective questions. Results will be available after grading.</p>
          ) : visible ? (
            <div className="mb-6">
              <p className="text-4xl font-bold text-primary-600">{Number(a.marks_obtained)}<span className="text-lg text-surface-400"> / {Number(a.total_marks || mt.total_marks)}</span></p>
              <p className="text-surface-500 mt-1">{Number(a.percentage)}% · {a.correct_answers} correct</p>
              {a.xp_earned > 0 && <p className="text-amber-500 font-medium mt-2">+{a.xp_earned} XP</p>}
            </div>
          ) : (
            <p className="text-surface-500 mb-6">Your responses were recorded. Results will be released by your faculty.</p>
          )}
          <div className="flex gap-3">
            <button onClick={() => navigate('/mock-test')} className="flex-1 px-4 py-2.5 rounded-xl bg-primary-600 hover:bg-primary-700 text-white font-medium">Back to {mockLabel}</button>
            {attemptId && (
              <button onClick={() => navigate(`/mock-test/live-review/${attemptId}`)} className="flex-1 px-4 py-2.5 rounded-xl border border-surface-200 dark:border-surface-700 font-medium">
                {result.pending_manual ? 'View status' : 'Review'}
              </button>
            )}
          </div>
        </div>
      </div>
    )
  }

  const lowTime = remaining < 60

  /* ------------------------- instructions screen ------------------------- */
  if (phase === 'instructions') {
    const hasResume = !!paperInfo?.active_attempt_id
    const remainingAttempts = paperInfo?.attempts_remaining
    const blocked = !hasResume && paperInfo?.can_start === false
    const deadlinePassed = mt?.start_deadline && new Date(mt.start_deadline) < new Date()
    const startBlocked = !hasResume && (blocked || deadlinePassed)
    return (
      <div className="min-h-screen flex items-center justify-center p-4 bg-surface-50 dark:bg-surface-950">
        <div className="max-w-lg w-full bg-white dark:bg-surface-900 rounded-3xl shadow-xl p-8">
          <h1 className="text-2xl font-bold mb-1 text-surface-900 dark:text-white">{mt?.title}</h1>
          <p className="text-surface-500 mb-6">Please read the instructions carefully before you begin.</p>

          <div className="grid grid-cols-2 gap-3 mb-6 text-sm">
            <Info label="Duration" value={`${mt?.duration_minutes || 0} min`} />
            <Info label="Total marks" value={Number(mt?.total_marks || 0)} />
            <Info label="Questions" value={questions.length} />
            <Info label="Negative marking" value={mt?.negative_marking ? 'Yes' : 'No'} />
            {typeof remainingAttempts === 'number' && (
              <Info label="Attempts left" value={`${remainingAttempts} of ${mt?.max_attempts ?? 1}`} />
            )}
            {mt?.start_deadline && (
              <Info label="Start before" value={new Date(mt.start_deadline).toLocaleString()} />
            )}
          </div>

          <ul className="space-y-2 text-sm text-surface-600 dark:text-surface-300 mb-6 list-disc pl-5">
            <li>The timer starts as soon as you begin and <strong>keeps running even if you close the tab</strong>.</li>
            <li>If you leave, you can return and <strong>resume</strong> — but the clock will not pause.</li>
            <li>When the time is up, your test is submitted automatically.</li>
            {mt?.fullscreen_required && <li>The test runs in <strong>fullscreen</strong>. Leaving fullscreen or switching tabs is recorded.</li>}
            <li>Your answers are saved automatically as you go.</li>
            {(mt?.max_attempts ?? 1) <= 1
              ? <li>Only <strong>one attempt</strong> is allowed — you cannot re-take this test.</li>
              : <li>You are allowed <strong>{mt?.max_attempts} attempts</strong> in total.</li>}
          </ul>

          {startBlocked ? (
            <div className="rounded-xl bg-rose-50 dark:bg-rose-900/20 text-rose-700 dark:text-rose-300 px-4 py-3 text-sm mb-4">
              {deadlinePassed ? 'The window to start this test has closed.' : 'You have used all your allowed attempts for this test.'}
            </div>
          ) : null}

          <div className="flex gap-3">
            <button onClick={() => navigate('/mock-test')}
              className="flex-1 px-4 py-2.5 rounded-xl border border-surface-200 dark:border-surface-700 font-medium">
              Cancel
            </button>
            <button onClick={beginAttempt} disabled={starting || (startBlocked && !hasResume)}
              className="flex-1 px-4 py-2.5 rounded-xl bg-primary-600 hover:bg-primary-700 disabled:opacity-50 text-white font-medium flex items-center justify-center gap-2">
              {starting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
              {hasResume ? 'Resume test' : 'Start test'}
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div ref={containerRef} className="min-h-screen bg-surface-50 dark:bg-surface-950 flex flex-col">
      {/* top bar */}
      <div className="flex items-center justify-between px-4 py-3 bg-white dark:bg-surface-900 border-b border-surface-200 dark:border-surface-700 sticky top-0 z-20">
        <div className="min-w-0">
          <h1 className="font-semibold text-surface-900 dark:text-white truncate">{mt?.title}</h1>
          <p className="text-xs text-surface-400">Question {current + 1} of {questions.length}</p>
        </div>
        <div className="flex items-center gap-3">
          <div className={`flex items-center gap-2 px-3 py-1.5 rounded-lg font-mono font-semibold ${lowTime ? 'bg-rose-100 text-rose-700 animate-pulse' : 'bg-surface-100 dark:bg-surface-800'}`}>
            <Clock className="w-4 h-4" /> {fmt(remaining)}
          </div>
          {mt?.fullscreen_required && !document.fullscreenElement && (
            <button onClick={enterFullscreen} className="p-2 rounded-lg bg-amber-100 text-amber-700" title="Re-enter fullscreen"><Maximize2 className="w-4 h-4" /></button>
          )}
          <button onClick={() => handleSubmit(false)} disabled={submitting}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-medium disabled:opacity-60">
            {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />} Submit
          </button>
        </div>
      </div>

      <div className="flex-1 flex flex-col lg:flex-row gap-4 p-4 max-w-6xl mx-auto w-full">
        {/* question panel */}
        <div className="flex-1 bg-white dark:bg-surface-900 rounded-2xl border border-surface-200 dark:border-surface-700 p-5 sm:p-6">
          {q && (
            <>
              <div className="flex items-start justify-between gap-3 mb-4">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-semibold px-2 py-1 rounded-full bg-primary-100 text-primary-700 dark:bg-primary-900/30 dark:text-primary-300 uppercase">{q.item_type.replace('_', ' ')}</span>
                  <span className="text-xs text-surface-400">{q.marks} mark{q.marks !== 1 ? 's' : ''}{q.negative_marks ? ` · -${q.negative_marks}` : ''}</span>
                </div>
                <button onClick={toggleFlag} className={`inline-flex items-center gap-1 text-sm px-3 py-1.5 rounded-lg ${flagged[qKey(q)] ? 'bg-amber-100 text-amber-700' : 'text-surface-400 hover:bg-surface-100 dark:hover:bg-surface-800'}`}>
                  <Flag className="w-4 h-4" /> {flagged[qKey(q)] ? 'Flagged' : 'Flag'}
                </button>
              </div>

              {q.question_html ? (
                <div className="prose dark:prose-invert max-w-none mb-5" dangerouslySetInnerHTML={{ __html: q.question_html }} />
              ) : (
                <div className="mb-5"><MathRenderer content={q.question_text} className="prose-base" /></div>
              )}
              {q.question_image && <img src={q.question_image} alt="" className="max-h-72 rounded-lg mb-5" />}

              <AnswerInput q={q} value={cur} onChange={setAns}
                running={running} runResult={runResult} onRun={runSamples} />
            </>
          )}

          {/* nav buttons */}
          <div className="flex items-center justify-between mt-8 pt-4 border-t border-surface-200 dark:border-surface-700">
            <button onClick={() => setCurrent((c) => Math.max(0, c - 1))} disabled={current === 0}
              className="inline-flex items-center gap-1 px-4 py-2 rounded-xl border border-surface-200 dark:border-surface-700 text-sm disabled:opacity-40">
              <ChevronLeft className="w-4 h-4" /> Previous
            </button>
            {current < questions.length - 1 ? (
              <button onClick={() => setCurrent((c) => Math.min(questions.length - 1, c + 1))}
                className="inline-flex items-center gap-1 px-4 py-2 rounded-xl bg-primary-600 hover:bg-primary-700 text-white text-sm">
                Next <ChevronRight className="w-4 h-4" />
              </button>
            ) : (
              <button onClick={() => handleSubmit(false)} disabled={submitting}
                className="inline-flex items-center gap-1 px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white text-sm">
                Finish <Send className="w-4 h-4" />
              </button>
            )}
          </div>
        </div>

        {/* navigator */}
        <div className="lg:w-64 bg-white dark:bg-surface-900 rounded-2xl border border-surface-200 dark:border-surface-700 p-4 h-fit">
          <p className="text-sm font-semibold mb-3 flex items-center gap-2"><ListChecks className="w-4 h-4" /> Questions</p>
          <div className="grid grid-cols-6 lg:grid-cols-5 gap-2">
            {questions.map((question, i) => {
              const answered = isAnswered(question)
              const isFlag = flagged[qKey(question)]
              return (
                <button key={qKey(question)} onClick={() => setCurrent(i)}
                  className={`relative w-9 h-9 rounded-lg text-sm font-medium transition ${
                    i === current ? 'ring-2 ring-primary-500 ' : ''}${
                    answered ? 'bg-emerald-500 text-white' : 'bg-surface-100 dark:bg-surface-800 text-surface-500'}`}>
                  {i + 1}
                  {isFlag && <Flag className="w-3 h-3 text-amber-500 absolute -top-1 -right-1" />}
                </button>
              )
            })}
          </div>
          <div className="mt-4 space-y-1.5 text-xs text-surface-500">
            <p className="flex items-center gap-2"><span className="w-3 h-3 rounded bg-emerald-500 inline-block" /> Answered</p>
            <p className="flex items-center gap-2"><span className="w-3 h-3 rounded bg-surface-200 dark:bg-surface-700 inline-block" /> Not answered</p>
            <p className="flex items-center gap-2"><Flag className="w-3 h-3 text-amber-500" /> Flagged for review</p>
          </div>
        </div>
      </div>

      {/* proctoring warning */}
      {showWarn && (
        <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4">
          <div className="bg-white dark:bg-surface-900 rounded-2xl max-w-sm w-full p-6 text-center">
            <AlertTriangle className="w-12 h-12 text-amber-500 mx-auto mb-3" />
            <h3 className="text-lg font-bold mb-2">Stay on the test</h3>
            <p className="text-surface-500 text-sm mb-4">
              Leaving the test window or fullscreen is recorded. Warning {violations} of 3. Repeated violations may be flagged to your faculty.
            </p>
            <button onClick={() => { setShowWarn(false); if (mt?.fullscreen_required) enterFullscreen() }}
              className="w-full px-4 py-2.5 rounded-xl bg-primary-600 hover:bg-primary-700 text-white font-medium">
              Resume test
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

/* ------------------------- small info tile ------------------------- */
function Info({ label, value }) {
  return (
    <div className="rounded-xl bg-surface-50 dark:bg-surface-800/60 px-3 py-2">
      <p className="text-[11px] uppercase tracking-wide text-surface-400">{label}</p>
      <p className="font-semibold text-surface-800 dark:text-surface-100">{value}</p>
    </div>
  )
}

/* ------------------------- per-type answer input ------------------------- */
function AnswerInput({ q, value, onChange, running, runResult, onRun }) {
  if (['mcq', 'mcq_multi'].includes(q.item_type)) {
    const selected = value.selected || []
    const toggle = (idx) => {
      if (q.item_type === 'mcq') onChange({ selected: [idx] })
      else onChange({ selected: selected.includes(idx) ? selected.filter((x) => x !== idx) : [...selected, idx] })
    }
    return (
      <div className="space-y-2">
        {(q.options || []).map((o) => (
          <div key={o.index} role="button" tabIndex={0}
            onClick={() => toggle(o.index)}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(o.index) } }}
            className={`w-full cursor-pointer text-left px-4 py-3 rounded-xl border transition flex items-center gap-3 ${
              selected.includes(o.index)
                ? 'border-primary-500 bg-primary-50 dark:bg-primary-900/20'
                : 'border-surface-200 dark:border-surface-700 hover:border-surface-300'}`}>
            <span className={`shrink-0 w-5 h-5 rounded-${q.item_type === 'mcq' ? 'full' : 'md'} border flex items-center justify-center ${selected.includes(o.index) ? 'border-primary-500 bg-primary-500' : 'border-surface-300'}`}>
              {selected.includes(o.index) && <CheckCircle2 className="w-4 h-4 text-white" />}
            </span>
            <div className="text-surface-800 dark:text-surface-100 flex-1 min-w-0"><MathRenderer content={o.text} className="prose-sm prose-p:my-0" /></div>
            {o.image && <img src={o.image} alt="" className="h-12 rounded ml-auto" />}
          </div>
        ))}
      </div>
    )
  }

  if (q.item_type === 'numerical') {
    return (
      <input type="number" step="any" value={value.numerical_answer ?? ''}
        onChange={(e) => onChange({ numerical_answer: e.target.value === '' ? null : Number(e.target.value) })}
        placeholder="Enter your numerical answer"
        className="w-full max-w-xs px-4 py-3 rounded-xl border border-surface-200 dark:border-surface-700 bg-white dark:bg-surface-800 text-lg focus:outline-none focus:ring-2 focus:ring-primary-500/40" />
    )
  }

  if (q.item_type === 'subjective') {
    const words = (value.answer_text || '').trim().split(/\s+/).filter(Boolean).length
    return (
      <div>
        <textarea value={value.answer_text || ''} onChange={(e) => onChange({ answer_text: e.target.value })}
          rows={10} placeholder="Write your answer…"
          className="w-full px-4 py-3 rounded-xl border border-surface-200 dark:border-surface-700 bg-white dark:bg-surface-800 focus:outline-none focus:ring-2 focus:ring-primary-500/40" />
        <p className="text-xs text-surface-400 mt-1">{words} words{q.max_words ? ` / ${q.max_words} max` : ''}</p>
      </div>
    )
  }

  if (q.item_type === 'coding') {
    const langs = q.allowed_languages || []
    const lang = value.language || langs[0] || 'python'
    if (!value.language && langs[0] && !value.code) {
      // lazy default starter code
    }
    return (
      <div>
        <div className="flex items-center gap-2 mb-2">
          <select value={lang} onChange={(e) => onChange({ language: e.target.value })}
            className="px-3 py-1.5 rounded-lg border border-surface-200 dark:border-surface-700 bg-white dark:bg-surface-800 text-sm">
            {langs.map((l) => <option key={l} value={l}>{l}</option>)}
          </select>
          <button onClick={onRun} disabled={running}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-surface-800 text-white text-sm disabled:opacity-60">
            {running ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />} Run samples
          </button>
        </div>
        <CodeEditor value={value.code || (q.starter_code?.[lang] ?? '')} onChange={(v) => onChange({ code: v, language: lang })} language={MONACO_MODE[lang] || 'python'} height={360} />
        {runResult && (
          <div className="mt-3 space-y-2">
            <p className="text-sm font-medium">{runResult.passed_count}/{runResult.total_count} sample cases passed</p>
            {(runResult.results || []).map((r, i) => (
              <div key={i} className={`text-xs rounded-lg p-2 border ${r.verdict === 'passed' ? 'border-emerald-200 bg-emerald-50 dark:bg-emerald-900/10' : 'border-rose-200 bg-rose-50 dark:bg-rose-900/10'}`}>
                <p className="flex items-center gap-1 font-medium">{r.verdict === 'passed' ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" /> : <XCircle className="w-3.5 h-3.5 text-rose-500" />} Case {i + 1}: {r.verdict}</p>
                {r.stdin != null && <pre className="mt-1 whitespace-pre-wrap"><b>in:</b> {r.stdin}</pre>}
                {r.expected_output != null && <pre className="whitespace-pre-wrap"><b>expected:</b> {r.expected_output}</pre>}
                {r.stdout != null && <pre className="whitespace-pre-wrap"><b>got:</b> {r.stdout}</pre>}
              </div>
            ))}
          </div>
        )}
      </div>
    )
  }
  return null
}
