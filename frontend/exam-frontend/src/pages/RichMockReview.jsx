import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  ChevronLeft, Loader2, CheckCircle2, XCircle, Clock3, Award, Trophy,
  FileText, Code2, HelpCircle, Medal,
} from 'lucide-react'
import { mockTestBuilderService } from '../services/mockTestBuilderService'
import MathRenderer from '../components/chat/MathRenderer'
import WhatHappened, { useSelfReports } from '../components/review/WhatHappened'

export default function RichMockReview() {
  const { attemptId } = useParams()
  const navigate = useNavigate()
  const [tab, setTab] = useState('review')

  const { data, isLoading } = useQuery({
    queryKey: ['richReview', attemptId],
    queryFn: () => mockTestBuilderService.richReview(attemptId),
  })

  const selfReports = useSelfReports('mock', attemptId)

  const { data: lb } = useQuery({
    queryKey: ['richReviewLb', data?.mock_test_id],
    queryFn: () => mockTestBuilderService.leaderboard(data.mock_test_id),
    enabled: !!data?.mock_test_id && data?.results_visible,
  })

  if (isLoading) {
    return <div className="flex justify-center py-20"><Loader2 className="w-8 h-8 animate-spin text-primary-500" /></div>
  }

  if (!data) {
    return <div className="max-w-2xl mx-auto card p-10 text-center text-surface-500">Attempt not found.</div>
  }

  if (!data.results_visible) {
    return (
      <div className="max-w-lg mx-auto mt-10 card p-10 text-center">
        <Clock3 className="w-14 h-14 mx-auto mb-4 text-amber-400" />
        <h1 className="text-xl font-bold mb-2">{data.mock_test_title}</h1>
        <p className="text-surface-500 mb-6">{data.message}</p>
        <button onClick={() => navigate('/mock-test')} className="px-5 py-2.5 rounded-xl bg-primary-600 hover:bg-primary-700 text-white font-medium">
          Back to Mock Tests
        </button>
      </div>
    )
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <button onClick={() => navigate('/mock-test')} className="inline-flex items-center gap-1 text-sm text-surface-500 hover:text-surface-700">
        <ChevronLeft className="w-4 h-4" /> Mock Tests
      </button>

      {/* score header */}
      <div className="relative overflow-hidden rounded-3xl bg-gradient-to-br from-primary-600 to-primary-700 p-6 sm:p-8 text-white">
        <div className="absolute -right-8 -top-8 w-40 h-40 bg-white/10 rounded-full blur-2xl" />
        <div className="relative">
          <h1 className="text-2xl font-bold">{data.mock_test_title}</h1>
          <div className="flex flex-wrap gap-6 mt-4">
            <Stat label="Score" value={`${data.marks_obtained} / ${data.total_marks}`} />
            <Stat label="Percentage" value={`${Math.round(data.percentage)}%`} />
            <Stat label="Correct" value={data.correct_answers} />
            <Stat label="Wrong" value={data.wrong_answers} />
            {data.xp_earned > 0 && <Stat label="XP" value={`+${data.xp_earned}`} />}
          </div>
        </div>
      </div>

      {/* tabs */}
      <div className="flex gap-1 p-1 bg-surface-100 dark:bg-surface-800 rounded-xl w-fit">
        {[['review', 'Review', FileText], ['leaderboard', 'Leaderboard', Trophy]].map(([id, label, Icon]) => (
          <button key={id} onClick={() => setTab(id)}
            className={`px-4 py-2 rounded-lg text-sm font-semibold flex items-center gap-2 transition ${tab === id ? 'bg-white dark:bg-surface-700 text-primary-600 shadow-sm' : 'text-surface-500'}`}>
            <Icon className="w-4 h-4" /> {label}
          </button>
        ))}
      </div>

      {tab === 'review' ? (
        <div className="space-y-4">
          {data.questions.map((q, i) => <ReviewCard key={i} q={q} index={i} attemptId={attemptId} selfReports={selfReports} />)}
        </div>
      ) : (
        <LeaderboardTable lb={lb} />
      )}
    </div>
  )
}

const Stat = ({ label, value }) => (
  <div>
    <p className="text-white/70 text-xs uppercase tracking-wide">{label}</p>
    <p className="text-xl font-bold">{value}</p>
  </div>
)

function ReviewCard({ q, index, attemptId, selfReports }) {
  const pending = q.needs_manual_grading
  const correct = q.is_correct
  const TypeIcon = q.item_type === 'coding' ? Code2 : q.item_type === 'subjective' ? FileText : HelpCircle
  const statusColor = pending ? 'border-amber-200' : correct ? 'border-emerald-200' : 'border-rose-200'

  return (
    <div className={`card p-5 border ${statusColor} dark:border-surface-700`}>
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="flex items-center gap-2">
          <span className="w-7 h-7 rounded-lg bg-surface-100 dark:bg-surface-800 flex items-center justify-center text-sm font-bold">{index + 1}</span>
          <TypeIcon className="w-4 h-4 text-primary-500" />
          <span className="text-xs uppercase text-surface-400 font-semibold">{q.item_type.replace('_', ' ')}</span>
        </div>
        <div className="flex items-center gap-2 text-sm">
          {pending ? <span className="text-amber-600 font-medium">Awaiting grade</span>
            : correct ? <span className="inline-flex items-center gap-1 text-emerald-600 font-medium"><CheckCircle2 className="w-4 h-4" /> Correct</span>
            : <span className="inline-flex items-center gap-1 text-rose-600 font-medium"><XCircle className="w-4 h-4" /> Incorrect</span>}
          <span className="text-surface-400">{q.marks_obtained} / {q.max_marks}</span>
        </div>
      </div>

      {q.question_html
        ? <div className="prose dark:prose-invert max-w-none text-sm mb-3" dangerouslySetInnerHTML={{ __html: q.question_html }} />
        : <div className="mb-3"><MathRenderer content={q.question_text} className="prose-sm" /></div>}

      {/* options for MCQ types */}
      {q.options && (
        <div className="space-y-1.5 mb-2">
          {q.options.map((o) => (
            <div key={o.index} className={`px-3 py-2 rounded-lg text-sm flex items-center gap-2 border ${
              o.is_correct ? 'border-emerald-300 bg-emerald-50 dark:bg-emerald-900/10'
              : o.is_selected ? 'border-rose-300 bg-rose-50 dark:bg-rose-900/10'
              : 'border-surface-200 dark:border-surface-700'}`}>
              {o.is_correct ? <CheckCircle2 className="w-4 h-4 text-emerald-500 shrink-0" />
                : o.is_selected ? <XCircle className="w-4 h-4 text-rose-500 shrink-0" />
                : <span className="w-4 h-4 shrink-0" />}
              <div className="flex-1 min-w-0"><MathRenderer content={o.text} className="prose-sm prose-p:my-0" /></div>
              {o.is_selected && <span className="ml-auto text-xs text-surface-400">your answer</span>}
            </div>
          ))}
        </div>
      )}

      {/* numerical */}
      {q.item_type === 'numerical' && (
        <div className="text-sm flex gap-6 mb-2">
          <span>Your answer: <b>{q.your_answer || '—'}</b></span>
          <span className="text-emerald-600">Correct: <b>{q.correct_answer}</b></span>
        </div>
      )}

      {/* subjective */}
      {q.item_type === 'subjective' && (
        <div className="rounded-lg bg-surface-50 dark:bg-surface-800/50 border border-surface-200 dark:border-surface-700 p-3 text-sm whitespace-pre-wrap mb-2">
          {q.your_answer || <span className="text-surface-400 italic">(no answer)</span>}
        </div>
      )}

      {/* coding */}
      {q.item_type === 'coding' && (
        <div className="mb-2">
          <p className="text-xs text-surface-400 mb-1">{q.language || 'n/a'} · {q.passed_count}/{q.total_count} hidden cases passed</p>
          <pre className="text-xs overflow-x-auto whitespace-pre-wrap font-mono rounded-lg bg-surface-50 dark:bg-surface-800/50 border border-surface-200 dark:border-surface-700 p-3">{q.code || '(no code)'}</pre>
        </div>
      )}

      {q.feedback && (
        <div className="mt-2 text-sm rounded-lg bg-primary-50 dark:bg-primary-900/10 border border-primary-100 dark:border-primary-900/30 p-3">
          <span className="font-medium text-primary-700 dark:text-primary-300">Faculty feedback: </span>{q.feedback}
        </div>
      )}
      {q.explanation && (
        <details className="mt-2 text-sm">
          <summary className="cursor-pointer text-surface-500 font-medium">Explanation</summary>
          <div className="mt-1 text-surface-600 dark:text-surface-300"><MathRenderer content={q.explanation} className="prose-sm" /></div>
        </details>
      )}

      {selfReports.enabled && selfReports.ready && !pending && !correct && q.ref_id &&
        !selfReports.notSeen.has(`${q.kind}:${q.ref_id}`) && (
        <WhatHappened
          attemptKind="mock"
          attemptId={attemptId}
          itemKind={q.kind}
          itemId={q.ref_id}
          initial={selfReports.reports[`${q.kind}:${q.ref_id}`]}
        />
      )}
    </div>
  )
}

function LeaderboardTable({ lb }) {
  if (!lb) return <div className="flex justify-center py-10"><Loader2 className="w-6 h-6 animate-spin text-primary-500" /></div>
  if (!lb.leaderboard?.length) return <div className="card p-10 text-center text-surface-500">No participants yet.</div>
  const medal = (r) => r === 1 ? 'text-amber-400' : r === 2 ? 'text-surface-400' : r === 3 ? 'text-amber-600' : ''
  return (
    <div className="card overflow-hidden">
      <div className="p-4 border-b border-surface-200 dark:border-surface-700 flex items-center justify-between">
        <p className="font-semibold flex items-center gap-2"><Trophy className="w-4 h-4 text-amber-500" /> Leaderboard</p>
        <p className="text-sm text-surface-500">{lb.total_participants} participants{lb.user_rank ? ` · You: #${lb.user_rank}` : ''}</p>
      </div>
      <div className="divide-y divide-surface-100 dark:divide-surface-800">
        {lb.leaderboard.map((e) => (
          <div key={e.rank} className={`flex items-center gap-3 px-4 py-3 ${e.is_current_user ? 'bg-primary-50 dark:bg-primary-900/10' : ''}`}>
            <span className={`w-8 text-center font-bold ${medal(e.rank)}`}>
              {e.rank <= 3 ? <Medal className={`w-5 h-5 mx-auto ${medal(e.rank)}`} /> : e.rank}
            </span>
            <span className="flex-1 font-medium truncate">{e.student_name}{e.is_current_user && <span className="text-xs text-primary-500 ml-2">You</span>}</span>
            <span className="text-sm text-surface-500">{Math.round(e.percentage)}%</span>
            <span className="font-semibold w-16 text-right">{e.marks_obtained}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
