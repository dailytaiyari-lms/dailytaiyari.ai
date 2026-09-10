import { useState, useEffect, useMemo, lazy, Suspense } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import toast from 'react-hot-toast'
import {
  ArrowLeft, Play, Send, Loader2, Code2, CheckCircle2, XCircle,
  Clock, AlertTriangle, Trophy, Terminal, ExternalLink, Circle,
} from 'lucide-react'
import { codingService } from '../services/codingService'
import Loading from '../components/common/Loading'

const CodeEditor = lazy(() => import('../components/coding/CodeEditor'))

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

// Poll a queued/async submission until it is graded (or a generous deadline).
// Sync submissions return a terminal status directly and never reach here.
// Transient poll failures are tolerated (grading continues server-side).
const pollSubmission = async (problemId, submissionId) => {
  const deadline = Date.now() + 180000
  let delay = 1200
  let consecutiveErrors = 0
  while (Date.now() < deadline) {
    await sleep(delay)
    try {
      const s = await codingService.submissionStatus(problemId, submissionId)
      consecutiveErrors = 0
      if (s.status === 'done' || s.status === 'error') return s
    } catch (e) {
      // A single 5xx/network blip shouldn't abort — keep polling. Give up only
      // after several consecutive failures (server likely unreachable).
      if (++consecutiveErrors >= 5) throw e
    }
    delay = Math.min(delay + 300, 3000)
  }
  const err = new Error('grading-timeout')
  err.friendly = 'Still grading — this is taking longer than usual. Check "My submissions" in a moment.'
  throw err
}

const DIFF_TINT = {
  easy: 'bg-emerald-50 text-emerald-600 dark:bg-emerald-900/20',
  medium: 'bg-amber-50 text-amber-600 dark:bg-amber-900/20',
  hard: 'bg-red-50 text-red-600 dark:bg-red-900/20',
}

// Friendly platform label from an external problem URL (e.g. leetcode.com -> LeetCode).
const PLATFORM_LABELS = [
  [/leetcode\.com/i, 'LeetCode'],
  [/geeksforgeeks\.org/i, 'GeeksforGeeks'],
  [/hackerrank\.com/i, 'HackerRank'],
  [/hackerearth\.com/i, 'HackerEarth'],
  [/codeforces\.com/i, 'Codeforces'],
  [/codechef\.com/i, 'CodeChef'],
  [/spoj\.com/i, 'SPOJ'],
  [/atcoder\.jp/i, 'AtCoder'],
  [/interviewbit\.com/i, 'InterviewBit'],
]
const platformName = (url) => {
  if (!url) return 'the external platform'
  const hit = PLATFORM_LABELS.find(([re]) => re.test(url))
  return hit ? hit[1] : 'the external platform'
}

const VERDICT = {
  passed: { label: 'Passed', icon: CheckCircle2, cls: 'text-emerald-600 bg-emerald-50 dark:bg-emerald-900/20' },
  wrong_answer: { label: 'Wrong answer', icon: XCircle, cls: 'text-red-600 bg-red-50 dark:bg-red-900/20' },
  compile_error: { label: 'Compile error', icon: AlertTriangle, cls: 'text-orange-600 bg-orange-50 dark:bg-orange-900/20' },
  runtime_error: { label: 'Runtime error', icon: AlertTriangle, cls: 'text-orange-600 bg-orange-50 dark:bg-orange-900/20' },
  time_limit: { label: 'Time limit', icon: Clock, cls: 'text-purple-600 bg-purple-50 dark:bg-purple-900/20' },
}

const IOBlock = ({ label, text }) => (
  <div>
    <p className="text-[10px] font-semibold uppercase tracking-wide text-surface-400 mb-1">{label}</p>
    <pre className="text-xs bg-surface-900 text-surface-100 rounded-lg p-2.5 overflow-x-auto whitespace-pre-wrap max-h-40">
      {text === '' || text == null ? <span className="text-surface-500">(empty)</span> : text}
    </pre>
  </div>
)

// Statements authored in the AI studio / rich editor are HTML; older ones are
// plain text. Render markup as HTML and fall back to pre-wrapped text.
const looksLikeHtml = (s) => /<\/?[a-z][\s\S]*>/i.test(s || '')

const ProblemStatement = ({ statement }) => {
  if (!statement) {
    return <div className="text-sm text-surface-500">No statement provided.</div>
  }
  if (looksLikeHtml(statement)) {
    return (
      <div
        className="prose prose-sm dark:prose-invert max-w-none prose-headings:font-display prose-p:leading-relaxed prose-pre:bg-surface-900 prose-pre:text-surface-100"
        dangerouslySetInnerHTML={{ __html: statement }}
      />
    )
  }
  return (
    <div className="text-sm text-surface-700 dark:text-surface-200 whitespace-pre-wrap leading-relaxed">
      {statement}
    </div>
  )
}

const VerdictPill = ({ verdict }) => {
  const v = VERDICT[verdict] || { label: verdict, icon: XCircle, cls: 'text-surface-500 bg-surface-100 dark:bg-surface-800' }
  const Icon = v.icon
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-semibold ${v.cls}`}>
      <Icon className="w-3.5 h-3.5" /> {v.label}
    </span>
  )
}

const CodingProblem = () => {
  const { problemId } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const { data: problem, isLoading } = useQuery({
    queryKey: ['codingProblem', problemId],
    queryFn: () => codingService.getProblem(problemId),
    enabled: !!problemId,
  })

  const languages = useMemo(() => problem?.languages || [], [problem])
  const [lang, setLang] = useState(null)
  const [code, setCode] = useState('')
  const [runResult, setRunResult] = useState(null)
  const [submitResult, setSubmitResult] = useState(null)

  // Seed language + starter code once the problem loads / language changes.
  useEffect(() => {
    if (languages.length && !lang) setLang(languages[0].key)
  }, [languages, lang])

  useEffect(() => {
    if (!problem || !lang) return
    const starter = problem.starter_code?.[lang] ?? ''
    setCode(starter)
    setRunResult(null)
    setSubmitResult(null)
  }, [lang, problem?.id])

  const runMutation = useMutation({
    mutationFn: () => codingService.run(problemId, { language: lang, source_code: code }),
    onSuccess: (data) => { setRunResult(data); setSubmitResult(null) },
    onError: (err) => toast.error(err?.response?.data?.error || 'Run failed. Try again.'),
  })

  const submitMutation = useMutation({
    mutationFn: async () => {
      const res = await codingService.submit(problemId, { language: lang, source_code: code })
      // Async judging returns a queued submission (HTTP 202) — poll until graded.
      if (res && res.id && (res.status === 'queued' || res.status === 'running')) {
        return pollSubmission(problemId, res.id)
      }
      return res
    },
    onSuccess: (data) => {
      setSubmitResult(data)
      setRunResult(null)
      if (data.status === 'error' && (data.total_count || 0) === 0) {
        toast.error(data.compile_output || 'Could not grade your submission. Please try again.')
        return
      }
      if (data.all_passed) {
        toast.success(data.xp_awarded > 0 ? `All test cases passed! +${data.xp_awarded} XP 🎉` : 'All test cases passed! 🎉')
        queryClient.invalidateQueries({ queryKey: ['codingProblem', problemId] })
      } else {
        toast(`${data.passed_count}/${data.total_count} test cases passed`)
      }
    },
    onError: (err) => toast.error(err?.friendly || err?.response?.data?.error || 'Submission failed. Try again.'),
  })

  const toggleExternalMutation = useMutation({
    mutationFn: () => codingService.toggleExternalSolved(problemId),
    onSuccess: (data) => {
      if (data.is_solved) {
        toast.success(data.xp_awarded > 0 ? `Marked as solved! +${data.xp_awarded} XP 🎉` : 'Marked as solved 🎉')
      } else {
        toast('Marked as not solved')
      }
      queryClient.invalidateQueries({ queryKey: ['codingProblem', problemId] })
    },
    onError: (err) => toast.error(err?.response?.data?.error || 'Could not update. Try again.'),
  })

  if (isLoading) return <Loading fullScreen />
  if (!problem) {
    return (
      <div className="card p-8 text-center">
        <p className="text-surface-500">Problem not found.</p>
        <button onClick={() => navigate(-1)} className="btn-outline mt-4">Go back</button>
      </div>
    )
  }

  const monacoLang = languages.find((l) => l.key === lang)?.monaco || 'python'
  const samples = problem.sample_cases || []
  const best = problem.my_best
  const busy = runMutation.isPending || submitMutation.isPending

  const solveMode = problem.solve_mode || 'in_app'
  const canExternal = (solveMode === 'external' || solveMode === 'both') && !!problem.external_url
  const showEditor = solveMode === 'in_app' || solveMode === 'both'
  const isSolved = !!problem.is_solved
  const completion = problem.my_completion

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center gap-3 flex-wrap">
        <button onClick={() => navigate(-1)} className="p-2 rounded-lg hover:bg-surface-100 dark:hover:bg-surface-800" aria-label="Back">
          <ArrowLeft size={20} />
        </button>
        <div className="w-10 h-10 rounded-xl bg-primary-50 dark:bg-primary-900/20 text-primary-600 dark:text-primary-400 flex items-center justify-center shrink-0">
          <Code2 className="w-5 h-5" />
        </div>
        <div className="min-w-0 flex-1">
          <h1 className="text-xl sm:text-2xl font-display font-bold truncate">{problem.title}</h1>
          <div className="flex flex-wrap items-center gap-2 mt-1 text-xs text-surface-500">
            {problem.difficulty && <span className={`px-2 py-0.5 rounded capitalize ${DIFF_TINT[problem.difficulty] || 'bg-surface-100 dark:bg-surface-800'}`}>{problem.difficulty}</span>}
            {problem.max_marks != null && <span className="px-2 py-0.5 rounded bg-surface-100 dark:bg-surface-800">{problem.max_marks} marks</span>}
            <span className="px-2 py-0.5 rounded bg-surface-100 dark:bg-surface-800 inline-flex items-center gap-1"><Clock className="w-3 h-3" /> {problem.time_limit_ms}ms</span>
            {isSolved && (
              <span className="px-2 py-0.5 rounded bg-success-50 dark:bg-success-900/20 text-success-600 inline-flex items-center gap-1">
                <CheckCircle2 className="w-3 h-3" /> Solved{completion?.method === 'external' ? ' (external)' : ''}
              </span>
            )}
            {!isSolved && best && (
              <span className="px-2 py-0.5 rounded bg-success-50 dark:bg-success-900/20 text-success-600 inline-flex items-center gap-1">
                <Trophy className="w-3 h-3" /> Best {best.passed_count}/{best.total_count}
              </span>
            )}
          </div>
        </div>
      </div>

      {canExternal && (
        <ExternalSolveCard
          url={problem.external_url}
          isSolved={isSolved}
          completion={completion}
          onToggle={() => toggleExternalMutation.mutate()}
          toggling={toggleExternalMutation.isPending}
        />
      )}

      <div className={`grid grid-cols-1 gap-4 items-start ${showEditor ? 'lg:grid-cols-2' : ''}`}>
        {/* Left: statement + samples */}
        <div className="space-y-4">
          <div className="card p-5">
            <h3 className="text-sm font-semibold text-surface-600 dark:text-surface-300 mb-2">Problem</h3>
            <ProblemStatement statement={problem.statement} />
          </div>

          {samples.length > 0 && (
            <div className="card p-5 space-y-3">
              <h3 className="text-sm font-semibold text-surface-600 dark:text-surface-300">Sample test cases</h3>
              {samples.map((s, i) => (
                <div key={s.id} className="rounded-lg border border-surface-200 dark:border-surface-700 p-3 space-y-2">
                  <p className="text-xs font-semibold text-surface-500">Sample {i + 1}</p>
                  <IOBlock label="Input" text={s.stdin} />
                  <IOBlock label="Expected output" text={s.expected_output} />
                  {s.explanation && <p className="text-xs text-surface-500 italic">{s.explanation}</p>}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Right: editor + actions + results */}
        {showEditor && (
        <div className="space-y-3">
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <div className="flex items-center gap-2">
              <label className="text-xs font-semibold text-surface-500">Language</label>
              <select
                value={lang || ''}
                onChange={(e) => setLang(e.target.value)}
                className="input py-1.5 text-sm w-auto"
              >
                {languages.map((l) => (
                  <option key={l.key} value={l.key}>{l.label}</option>
                ))}
              </select>
            </div>
            <div className="flex items-center gap-2">
              <button onClick={() => runMutation.mutate()} disabled={busy} className="btn-secondary text-sm px-3 py-1.5 disabled:opacity-50">
                {runMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />} Run
              </button>
              <button onClick={() => submitMutation.mutate()} disabled={busy} className="btn-primary text-sm px-3 py-1.5 disabled:opacity-50">
                {submitMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />} Submit
              </button>
            </div>
          </div>

          <Suspense fallback={<div className="h-[440px] rounded-xl border border-surface-200 dark:border-surface-700 flex items-center justify-center text-sm text-surface-400">Loading editor…</div>}>
            <CodeEditor value={code} onChange={setCode} language={monacoLang} height={440} />
          </Suspense>

          {/* Run results (samples, with I/O) */}
          {runResult && (
            <RunResultPanel result={runResult} />
          )}

          {/* Grading in progress (async submissions are queued then polled) */}
          {submitMutation.isPending && (
            <div className="flex items-center gap-2 rounded-xl border border-surface-200 dark:border-surface-700 bg-surface-50 dark:bg-surface-800/40 px-4 py-3 text-sm text-surface-500">
              <Loader2 className="w-4 h-4 animate-spin" /> Grading your submission…
            </div>
          )}

          {/* Submit results */}
          {!submitMutation.isPending && submitResult && (
            <SubmitResultPanel result={submitResult} maxMarks={problem.max_marks} />
          )}
        </div>
        )}
      </div>
    </div>
  )
}

const ExternalSolveCard = ({ url, isSolved, completion, onToggle, toggling }) => {
  const name = platformName(url)
  const solvedExternally = isSolved && completion?.method === 'external'
  const solvedInApp = isSolved && completion?.method === 'in_app'
  return (
    <div className="card p-4 sm:p-5 border border-primary-100 dark:border-primary-900/40 bg-primary-50/40 dark:bg-primary-900/10">
      <div className="flex flex-col sm:flex-row sm:items-center gap-3 sm:justify-between">
        <div className="min-w-0">
          <h3 className="text-sm font-bold flex items-center gap-1.5">
            <ExternalLink className="w-4 h-4 text-primary-500" /> Solve on {name}
          </h3>
          <p className="text-xs text-surface-500 mt-1">
            {solvedInApp
              ? 'You already solved this in the app. Nice work!'
              : `Open the problem on ${name}, solve it there, then mark it as solved here.`}
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <a href={url} target="_blank" rel="noopener noreferrer" className="btn-secondary text-sm px-3 py-1.5 inline-flex items-center gap-1.5">
            <ExternalLink className="w-4 h-4" /> Open on {name}
          </a>
          {!solvedInApp && (
            <button
              onClick={onToggle}
              disabled={toggling}
              className={`text-sm px-3 py-1.5 inline-flex items-center gap-1.5 disabled:opacity-50 ${solvedExternally ? 'btn-outline' : 'btn-primary'}`}
            >
              {toggling
                ? <Loader2 className="w-4 h-4 animate-spin" />
                : solvedExternally ? <Circle className="w-4 h-4" /> : <CheckCircle2 className="w-4 h-4" />}
              {solvedExternally ? 'Mark as not solved' : 'Mark as solved'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

const RunResultPanel = ({ result }) => {
  if (result.mode === 'custom') {
    const r = result.run || {}
    return (
      <div className="card p-4 space-y-2">
        <h3 className="text-sm font-semibold flex items-center gap-1.5"><Terminal className="w-4 h-4" /> Output</h3>
        <IOBlock label="Stdout" text={r.stdout} />
        {r.stderr ? <IOBlock label="Stderr" text={r.stderr} /> : null}
      </div>
    )
  }
  const results = result.results || []
  return (
    <div className="card p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold flex items-center gap-1.5"><Terminal className="w-4 h-4" /> Sample run</h3>
        <span className="text-xs font-semibold text-surface-500">{result.passed_count}/{result.total_count} passed</span>
      </div>
      {result.compile_output ? <IOBlock label="Compiler output" text={result.compile_output} /> : null}
      {results.map((r) => (
        <div key={r.index} className="rounded-lg border border-surface-200 dark:border-surface-700 p-3 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-surface-500">Sample {r.index + 1}</span>
            <VerdictPill verdict={r.verdict} />
          </div>
          {r.stdin != null && <IOBlock label="Input" text={r.stdin} />}
          {r.expected_output != null && <IOBlock label="Expected" text={r.expected_output} />}
          {r.stdout != null && <IOBlock label="Your output" text={r.stdout} />}
          {r.stderr ? <IOBlock label="Stderr" text={r.stderr} /> : null}
        </div>
      ))}
    </div>
  )
}

const SubmitResultPanel = ({ result, maxMarks }) => {
  const results = result.results || []
  const allPassed = result.all_passed
  return (
    <div className="card p-4 space-y-3">
      <div className={`rounded-xl p-4 flex items-center gap-3 ${allPassed ? 'bg-success-50 dark:bg-success-900/20' : 'bg-amber-50 dark:bg-amber-900/20'}`}>
        {allPassed
          ? <CheckCircle2 className="w-8 h-8 text-success-500 shrink-0" />
          : <AlertTriangle className="w-8 h-8 text-amber-500 shrink-0" />}
        <div>
          <p className="font-bold">{allPassed ? 'Accepted' : 'Partial'} — {result.passed_count}/{result.total_count} test cases passed</p>
          {maxMarks != null && result.marks != null && (
            <p className="text-sm text-surface-600 dark:text-surface-300">Score: {result.marks} / {maxMarks} marks</p>
          )}
          {result.xp_awarded > 0 && (
            <p className="text-sm font-semibold text-success-600 dark:text-success-400">+{result.xp_awarded} XP earned</p>
          )}
        </div>
      </div>
      {result.compile_output ? <IOBlock label="Compiler output" text={result.compile_output} /> : null}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
        {results.map((r) => {
          const v = VERDICT[r.verdict] || {}
          const Icon = v.icon || XCircle
          return (
            <div key={r.index} className={`rounded-lg p-2.5 flex items-center gap-2 text-xs font-medium ${v.cls || 'bg-surface-100 dark:bg-surface-800'}`}>
              <Icon className="w-4 h-4 shrink-0" />
              <span>{r.is_sample ? `Sample ${r.index + 1}` : `Test ${r.index + 1}`}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default CodingProblem
