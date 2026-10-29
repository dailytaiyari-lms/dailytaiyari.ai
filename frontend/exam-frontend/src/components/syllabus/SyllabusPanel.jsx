import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { GitBranch, Loader2, Map, Tags } from 'lucide-react'
import { syllabusService, errorText } from '../../services/syllabusService'
import Loading from '../common/Loading'
import TreeEditor from './TreeEditor'
import TagReviewList from './TagReviewList'

const fmt = (n) => (n == null ? '—' : Number(n).toLocaleString())
const STATUS_STYLE = {
  queued: 'text-surface-500', running: 'text-primary-500', done: 'text-success-600', failed: 'text-error-600',
}

function Card({ icon: Icon, title, children }) {
  return (
    <div className="p-5 rounded-2xl bg-white dark:bg-surface-800 border border-surface-200 dark:border-surface-700">
      <h3 className="font-semibold mb-3 flex items-center gap-2"><Icon size={16} className="text-primary-500" /> {title}</h3>
      {children}
    </div>
  )
}

function BudgetLine({ budget }) {
  if (!budget || budget.monthly_budget == null) return <p className="text-xs text-surface-400">No monthly AI budget set.</p>
  return (
    <p className={`text-xs ${budget.exhausted ? 'text-error-600' : 'text-surface-400'}`}>
      Monthly budget: {fmt(budget.remaining)} of {fmt(budget.monthly_budget)} tokens left
    </p>
  )
}

// Poll one job until it finishes, then refresh the tree.
function useJobPoll(jobId, onDone) {
  const { data } = useQuery({
    queryKey: ['syllabusJob', jobId],
    queryFn: () => syllabusService.getJob(jobId),
    enabled: !!jobId,
    refetchInterval: (query) => (['queued', 'running'].includes(query.state.data?.status) ? 3000 : false),
  })
  useEffect(() => {
    if (data && ['done', 'failed'].includes(data.status)) onDone(data)
  }, [data?.status]) // eslint-disable-line react-hooks/exhaustive-deps
  return data
}

const ACTIVE = ['queued', 'running']

// A run started earlier (or by someone else) is picked up when the view opens.
const activeJobId = (tree, kind) => tree.jobs?.find((j) => j.kind === kind && ACTIVE.includes(j.status))?.id ?? null

// 409 means a run is already active: follow it instead of only showing the error.
const adoptActive = (error, follow) => {
  if (error?.response?.status === 409 && error.response.data?.job) follow(error.response.data.job.id)
  toast.error(errorText(error))
}

function BuildCard({ courseId, tree }) {
  const queryClient = useQueryClient()
  const [jobId, setJobId] = useState(() => activeJobId(tree, 'tree_build'))
  const estimate = useQuery({
    queryKey: ['syllabusBuildEstimate', courseId],
    queryFn: () => syllabusService.estimateBuild(courseId),
  })
  const start = useMutation({
    mutationFn: () => syllabusService.startBuild(courseId),
    onSuccess: (job) => setJobId(job.id),
    onError: (error) => adoptActive(error, setJobId),
  })
  const job = useJobPoll(jobId, (finished) => {
    queryClient.invalidateQueries({ queryKey: ['syllabusTree', courseId] })
    queryClient.invalidateQueries({ queryKey: ['syllabusBuildEstimate', courseId] })
    if (finished.status === 'failed') toast.error(finished.error || 'Build failed')
    else toast.success('Syllabus tree built')
  })
  const running = start.isPending || ['queued', 'running'].includes(job?.status)
  const e = estimate.data

  return (
    <Card icon={GitBranch} title="Build syllabus tree">
      <p className="text-sm text-surface-500 mb-3">
        Groups this course's topics, adds existing concepts as subtopics, and suggests missing ones.
        Suggestions show a “suggested” badge until you accept or edit them.
      </p>
      {e && (
        <p className="text-sm mb-1">
          About {fmt(e.llm_calls)} AI calls (~{fmt(e.approx_tokens)} tokens)
        </p>
      )}
      <BudgetLine budget={e?.budget} />
      <button
        type="button"
        onClick={() => start.mutate()}
        disabled={running || e?.budget?.exhausted || e?.llm_calls === 0}
        className="btn-primary mt-3 text-sm"
      >
        {running ? <><Loader2 size={14} className="animate-spin" /> Building…</> : (tree.kind === 'none' ? 'Build tree' : 'Update tree')}
      </button>
      {e?.llm_calls === 0 && <p className="text-xs text-surface-400 mt-2">Nothing new to build.</p>}
    </Card>
  )
}

function ExamCard({ courseId, tree }) {
  const queryClient = useQueryClient()
  const [exam, setExam] = useState(tree.exam_tree || tree.exam_trees[0]?.key || '')
  const [map, setMap] = useState(() => {
    const initial = {}
    Object.entries(tree.subject_map || {}).forEach(([subjectId, key]) => { initial[subjectId] = key })
    return initial
  })
  const option = tree.exam_trees.find((t) => t.key === exam)
  const save = useMutation({
    mutationFn: () => syllabusService.mapExam(courseId, {
      exam, subjects: Object.fromEntries(Object.entries(map).filter(([, key]) => key)),
    }),
    onSuccess: () => {
      toast.success('Exam syllabus applied')
      queryClient.invalidateQueries({ queryKey: ['syllabusTree', courseId] })
    },
    onError: (error) => toast.error(errorText(error)),
  })
  if (!tree.exam_trees.length) return null

  return (
    <Card icon={Map} title="Use an exam syllabus">
      <p className="text-sm text-surface-500 mb-3">Pick a shipped exam tree and match each subject. No AI calls.</p>
      <select value={exam} onChange={(e) => setExam(e.target.value)} className="input text-sm mb-3">
        {tree.exam_trees.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
      </select>
      <div className="space-y-2">
        {tree.subjects.map((subject) => (
          <label key={subject.id} className="flex items-center justify-between gap-3 text-sm">
            <span>{subject.name}</span>
            <select
              value={map[subject.id] || ''}
              onChange={(e) => setMap({ ...map, [subject.id]: e.target.value })}
              className="input py-1 text-sm max-w-[12rem]"
            >
              <option value="">— not mapped —</option>
              {option?.subjects.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
            </select>
          </label>
        ))}
      </div>
      <button type="button" onClick={() => save.mutate()} disabled={save.isPending} className="btn-primary mt-3 text-sm">
        {save.isPending ? 'Applying…' : 'Apply exam syllabus'}
      </button>
    </Card>
  )
}

function TagCard({ courseId, tree }) {
  const queryClient = useQueryClient()
  const [runId, setRunId] = useState(() => activeJobId(tree, 'tagging'))
  const estimate = useQuery({
    queryKey: ['syllabusTagEstimate', courseId],
    queryFn: () => syllabusService.estimateTagging(courseId),
  })
  const start = useMutation({
    mutationFn: () => syllabusService.startTagging(courseId),
    onSuccess: (run) => setRunId(run.id),
    onError: (error) => adoptActive(error, setRunId),
  })
  const run = useJobPoll(runId, (finished) => {
    queryClient.invalidateQueries({ queryKey: ['syllabusTree', courseId] })
    queryClient.invalidateQueries({ queryKey: ['syllabusTagEstimate', courseId] })
    queryClient.invalidateQueries({ queryKey: ['tagReview'] })
    if (finished.status === 'failed') toast.error(finished.error || 'Tagging failed')
  })
  const running = start.isPending || ['queued', 'running'].includes(run?.status)
  const e = estimate.data

  return (
    <Card icon={Tags} title="Tag questions">
      {e?.subjects_with_tree === 0 ? (
        <p className="text-sm text-surface-500">Build or map a syllabus tree first.</p>
      ) : (
        <>
          <p className="text-sm mb-1">About {fmt(e?.questions)} questions to tag (~{fmt(e?.approx_tokens)} tokens; up to 500 per run)</p>
          <BudgetLine budget={e?.budget} />
          <button
            type="button"
            onClick={() => start.mutate()}
            disabled={running || !e?.questions || e?.budget?.exhausted}
            className="btn-primary mt-3 text-sm"
          >
            {running ? <><Loader2 size={14} className="animate-spin" /> Tagging…</> : 'Tag questions'}
          </button>
          {run?.status === 'done' && (
            <p className="text-sm mt-2">
              Tagged {run.summary.tagged ?? 0} · needs review {run.summary.needs_review ?? 0} · failed {run.summary.failed ?? 0}
            </p>
          )}
        </>
      )}
    </Card>
  )
}

function JobHistory({ jobs }) {
  if (!jobs.length) return null
  return (
    <div className="p-5 rounded-2xl bg-white dark:bg-surface-800 border border-surface-200 dark:border-surface-700">
      <h3 className="font-semibold mb-3">Recent runs</h3>
      <ul className="divide-y divide-surface-100 dark:divide-surface-700/50 text-sm">
        {jobs.map((job) => (
          <li key={job.id} className="py-2 flex flex-wrap items-center justify-between gap-2">
            <span>
              {job.kind === 'tree_build' ? 'Tree build' : 'Tagging'}
              <span className={`ml-2 ${STATUS_STYLE[job.status]}`}>{job.status}</span>
              {job.error && <span className="ml-2 text-xs text-error-600">{job.error}</span>}
            </span>
            <span className="text-xs text-surface-400">
              {job.started_by && `${job.started_by} · `}
              {fmt(job.tokens)} tokens · {new Date(job.created_at).toLocaleString()}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** Course editor "Syllabus" view (syllabus & tagging tools). */
export default function SyllabusPanel({ courseId }) {
  const { data: tree, isLoading } = useQuery({
    queryKey: ['syllabusTree', courseId],
    queryFn: () => syllabusService.getTree(courseId),
  })
  if (isLoading) return <Loading />
  if (!tree) return null

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {tree.kind !== 'exam' && <BuildCard courseId={courseId} tree={tree} />}
        {tree.kind !== 'custom' && <ExamCard courseId={courseId} tree={tree} />}
        <TagCard courseId={courseId} tree={tree} />
      </div>
      <JobHistory jobs={tree.jobs} />
      <TreeEditor courseId={courseId} tree={tree} />
      <div className="p-5 rounded-2xl bg-white dark:bg-surface-800 border border-surface-200 dark:border-surface-700">
        <h3 className="font-semibold mb-3">Questions needing review</h3>
        <TagReviewList courseId={courseId} />
      </div>
    </div>
  )
}
