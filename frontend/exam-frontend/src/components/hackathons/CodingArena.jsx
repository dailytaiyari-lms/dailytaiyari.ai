import { useEffect, useMemo, useState } from 'react'
import {
  Play, Send, Loader2, CheckCircle2, XCircle, Terminal, ChevronLeft, ChevronRight,
} from 'lucide-react'
import CodeEditor from '../coding/CodeEditor'
import { RichContent } from './hackathonShared'

const LANGUAGE_LABELS = { python: 'Python', cpp: 'C++', java: 'Java' }

const VERDICTS = {
  passed: { label: 'Passed', tint: 'text-emerald-600', Icon: CheckCircle2 },
  wrong_answer: { label: 'Wrong answer', tint: 'text-rose-600', Icon: XCircle },
  runtime_error: { label: 'Runtime error', tint: 'text-rose-600', Icon: XCircle },
  compile_error: { label: 'Compile error', tint: 'text-rose-600', Icon: XCircle },
  timeout: { label: 'Time limit exceeded', tint: 'text-amber-600', Icon: XCircle },
}

const Pre = ({ children }) => (
  <pre className="text-xs bg-surface-900 text-surface-100 rounded-lg p-3 overflow-x-auto whitespace-pre-wrap break-words max-h-40">
    {children || '—'}
  </pre>
)

/** Multi-problem coding round: problem statement, Monaco editor, run + submit. */
const CodingArena = ({ items, answers, onChange, onRun, onSubmit, readOnly = false, isRunning = false }) => {
  const [index, setIndex] = useState(0)
  const [output, setOutput] = useState({})
  const [tab, setTab] = useState('samples')

  const item = items?.[index]
  const answer = answers[item?.id] || {}

  const languages = useMemo(
    () => (item?.allowed_languages?.length ? item.allowed_languages : ['python']),
    [item],
  )
  const language = answer.language || languages[0]

  // Seed the editor with the problem's starter code the first time it is opened.
  useEffect(() => {
    if (!item || readOnly) return
    if (answers[item.id]?.code !== undefined) return
    onChange(item.id, {
      language,
      code: item.starter_code?.[language] || '',
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item?.id])

  if (!items?.length) {
    return (
      <div className="card p-10 text-center text-surface-500">
        No problems have been added to this round yet.
      </div>
    )
  }

  const switchLanguage = (next) => {
    const untouched = !answer.code?.trim()
      || answer.code === (item.starter_code?.[language] || '')
    onChange(item.id, {
      ...answer,
      language: next,
      code: untouched ? (item.starter_code?.[next] || '') : answer.code,
    })
  }

  const run = async () => {
    setTab('output')
    const result = await onRun({ item_id: item.id, language, source_code: answer.code || '' })
    if (result) setOutput((o) => ({ ...o, [item.id]: result }))
  }

  const result = output[item.id]

  return (
    <div className="grid xl:grid-cols-2 gap-5 items-start">
      {/* Problem */}
      <div className="card p-6 xl:sticky xl:top-24 xl:max-h-[calc(100vh-8rem)] xl:overflow-y-auto">
        <div className="flex items-center justify-between gap-3 mb-3">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs uppercase tracking-wide text-surface-400">
              Problem {index + 1} of {items.length}
            </span>
            <span className="badge badge-primary">{item.marks} marks</span>
            {item.difficulty && <span className="badge">{item.difficulty}</span>}
          </div>
          <div className="flex items-center gap-1">
            <button
              type="button" className="btn-icon" disabled={index === 0}
              onClick={() => setIndex((i) => i - 1)}
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <button
              type="button" className="btn-icon" disabled={index === items.length - 1}
              onClick={() => setIndex((i) => i + 1)}
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>

        {item.title && <h2 className="text-lg font-semibold mb-2">{item.title}</h2>}
        {item.question_html
          ? <RichContent content={item.question_html} />
          : <p className="whitespace-pre-wrap text-sm">{item.question_text}</p>}

        {item.sample_test_cases?.length > 0 && (
          <div className="mt-5 space-y-3">
            <h3 className="text-sm font-semibold">Examples</h3>
            {item.sample_test_cases.map((sample, i) => (
              <div key={i} className="rounded-xl border border-surface-200 dark:border-surface-700 p-3 space-y-2">
                <div>
                  <div className="text-xs font-medium text-surface-500 mb-1">Input</div>
                  <Pre>{sample.stdin}</Pre>
                </div>
                <div>
                  <div className="text-xs font-medium text-surface-500 mb-1">Expected output</div>
                  <Pre>{sample.expected_output}</Pre>
                </div>
                {sample.explanation && (
                  <p className="text-xs text-surface-500">{sample.explanation}</p>
                )}
              </div>
            ))}
          </div>
        )}

        <p className="text-xs text-surface-400 mt-5">
          Time limit {item.time_limit_ms} ms · Memory {item.memory_limit_mb} MB
        </p>
      </div>

      {/* Editor */}
      <div className="space-y-4">
        <div className="card p-4">
          <div className="flex items-center justify-between gap-3 mb-3">
            <select
              className="input !py-1.5 !w-auto text-sm"
              value={language}
              disabled={readOnly}
              onChange={(e) => switchLanguage(e.target.value)}
            >
              {languages.map((l) => (
                <option key={l} value={l}>{LANGUAGE_LABELS[l] || l}</option>
              ))}
            </select>
            <div className="flex items-center gap-2">
              <button
                type="button" className="btn-secondary text-sm"
                onClick={run} disabled={readOnly || isRunning}
              >
                {isRunning ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
                Run samples
              </button>
              {!readOnly && (
                <button type="button" className="btn-primary text-sm" onClick={onSubmit}>
                  <Send className="w-4 h-4" /> Submit round
                </button>
              )}
            </div>
          </div>

          <CodeEditor
            value={answer.code || ''}
            onChange={(code) => onChange(item.id, { ...answer, language, code })}
            language={language === 'cpp' ? 'cpp' : language}
            readOnly={readOnly}
            height={420}
          />
          <p className="text-xs text-surface-400 mt-2">
            Running only checks the visible examples. Your final score comes from the
            hidden tests when you submit the round.
          </p>
        </div>

        {/* Console */}
        <div className="card p-4">
          <div className="flex items-center gap-1 mb-3">
            {['samples', 'output'].map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setTab(t)}
                className={`px-3 py-1.5 rounded-lg text-sm font-medium ${
                  tab === t
                    ? 'bg-surface-100 dark:bg-surface-800'
                    : 'text-surface-500 hover:text-surface-700'
                }`}
              >
                {t === 'samples' ? 'Test cases' : 'Output'}
              </button>
            ))}
          </div>

          {tab === 'output' ? (
            isRunning ? (
              <div className="flex items-center gap-2 text-sm text-surface-500 py-6 justify-center">
                <Loader2 className="w-4 h-4 animate-spin" /> Running your code…
              </div>
            ) : !result ? (
              <div className="text-sm text-surface-400 py-6 text-center flex flex-col items-center gap-2">
                <Terminal className="w-6 h-6" />
                Hit “Run samples” to see how your code behaves.
              </div>
            ) : result.compile_error ? (
              <>
                <p className="text-sm font-medium text-rose-600 mb-2">Compilation failed</p>
                <Pre>{result.compile_output}</Pre>
              </>
            ) : (
              <div className="space-y-3">
                <p className="text-sm font-medium">
                  {result.passed_count}/{result.total_count} sample cases passed
                </p>
                {(result.results || []).map((r) => {
                  const verdict = VERDICTS[r.verdict] || VERDICTS.wrong_answer
                  const Icon = verdict.Icon
                  return (
                    <div key={r.index} className="rounded-xl border border-surface-200 dark:border-surface-700 p-3">
                      <div className={`flex items-center gap-1.5 text-sm font-medium ${verdict.tint} mb-2`}>
                        <Icon className="w-4 h-4" /> Case {r.index + 1} · {verdict.label}
                        {r.time_ms != null && (
                          <span className="text-surface-400 font-normal ml-auto">{r.time_ms} ms</span>
                        )}
                      </div>
                      {r.stdin !== undefined && (
                        <div className="grid sm:grid-cols-3 gap-2">
                          <div>
                            <div className="text-xs text-surface-500 mb-1">Input</div>
                            <Pre>{r.stdin}</Pre>
                          </div>
                          <div>
                            <div className="text-xs text-surface-500 mb-1">Expected</div>
                            <Pre>{r.expected_output}</Pre>
                          </div>
                          <div>
                            <div className="text-xs text-surface-500 mb-1">Yours</div>
                            <Pre>{r.stdout || r.stderr}</Pre>
                          </div>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )
          ) : (
            <div className="space-y-2">
              {(item.sample_test_cases || []).length === 0 && (
                <p className="text-sm text-surface-400">No visible examples for this problem.</p>
              )}
              {(item.sample_test_cases || []).map((sample, i) => (
                <div key={i} className="grid sm:grid-cols-2 gap-2">
                  <Pre>{sample.stdin}</Pre>
                  <Pre>{sample.expected_output}</Pre>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default CodingArena
