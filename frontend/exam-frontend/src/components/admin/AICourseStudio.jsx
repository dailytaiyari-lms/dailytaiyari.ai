import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'framer-motion'
import toast from 'react-hot-toast'
import {
    ArrowLeft, ChevronDown, Clock, Coins, History, Loader2, RotateCcw,
    Save, Send, Sparkles, Trash2, X,
} from 'lucide-react'
import courseAiService from '../../services/courseAiService'
import useVoiceDictation from '../../hooks/useVoiceDictation'
import { formatApiError } from './builderShared'
import DraftPreview, { collectSelectable } from './aiStudio/DraftPreview'
import TopicPicker from './aiStudio/TopicPicker'
import ConfirmApply from './aiStudio/ConfirmApply'
import {
    Field, KIND_META, ListeningBar, MicButton, Pill, STATUS_LABEL, STATUS_PILL,
    formatCost, inputClass, summaryLine,
} from './aiStudio/studioParts'

const emptySelection = () => ({
    subjects: new Set(), chapters: new Set(), topics: new Set(), fields: new Set(),
})

const toSelection = (buckets) => ({
    subjects: new Set(buckets.subjects),
    chapters: new Set(buckets.chapters),
    topics: new Set(buckets.topics),
    fields: new Set(buckets.fields),
})

const CONTENT_MATERIALS = [
    { id: 'notes', label: 'Reading notes' },
    { id: 'quiz', label: 'Practice quiz' },
    { id: 'assignment', label: 'Assignment' },
    { id: 'coding', label: 'Coding problem' },
]

/** Only send the buckets the current kind actually uses. */
const selectionPayload = (kind, selection) => {
    if (kind === 'outline') {
        return {
            subjects: [...selection.subjects],
            chapters: [...selection.chapters],
            topics: [...selection.topics],
        }
    }
    if (kind === 'content') return { topics: [...selection.topics] }
    if (kind === 'meta') return { fields: [...selection.fields] }
    return {}
}

const setIn = (object, path, value) => {
    const [head, ...rest] = path
    const clone = Array.isArray(object) ? [...object] : { ...object }
    clone[head] = rest.length ? setIn(clone[head] || {}, rest, value) : value
    return clone
}

/* ===========================================================================
 * AICourseStudio — draft-first AI authoring for the course builder.
 *
 * The screen has exactly two states: you are *composing* a request, or you are
 * *reviewing* a draft. Generation only ever fills the review pane; the course
 * itself changes at one moment only, when the admin confirms in ConfirmApply.
 * ========================================================================= */
const AICourseStudio = ({ initialCourseId = null, onClose = null }) => {
    const queryClient = useQueryClient()

    const [kind, setKind] = useState(initialCourseId ? 'content' : 'outline')
    const [courseId, setCourseId] = useState(initialCourseId || '')
    const [prompt, setPrompt] = useState('')
    const [usedVoice, setUsedVoice] = useState(false)
    const [provider, setProvider] = useState('')
    const [model, setModel] = useState('')
    const [topicIds, setTopicIds] = useState([])
    const [showAdvanced, setShowAdvanced] = useState(false)
    const [options, setOptions] = useState({
        chapters_per_subject: 5,
        topics_per_chapter: 4,
        questions_per_quiz: 5,
        materials: ['notes', 'quiz'],
        depth: 'standard',
        language: 'English',
        publish_immediately: false,
    })

    const [job, setJob] = useState(null)
    const [selection, setSelection] = useState(emptySelection)
    const [draftDirty, setDraftDirty] = useState(false)
    const [instruction, setInstruction] = useState('')
    const [confirming, setConfirming] = useState(false)
    const [showHistory, setShowHistory] = useState(false)
    const promptRef = useRef(null)

    /* ------------------------------------------------------------- options */

    const { data: config, isLoading: loadingConfig } = useQuery({
        queryKey: ['coursegen-options'],
        queryFn: () => courseAiService.getOptions(),
    })

    useEffect(() => {
        if (!config?.providers?.length || provider) return
        const active = config.providers.find((p) => p.is_active) || config.providers[0]
        setProvider(active.provider)
        setModel(active.default_model)
    }, [config, provider])

    useEffect(() => {
        if (config?.defaults) setOptions((prev) => ({ ...config.defaults, ...prev }))
    }, [config])

    const providerEntry = useMemo(
        () => (config?.providers || []).find((p) => p.provider === provider),
        [config, provider],
    )

    const maxTopics = config?.limits?.max_topics_per_content_job || 12

    /* --------------------------------------------------------------- voice */

    const appendTranscript = useCallback((text) => {
        setUsedVoice(true)
        setPrompt((prev) => (prev ? `${prev.replace(/\s+$/, '')} ${text}` : text))
    }, [])

    const voice = useVoiceDictation({ onTranscript: appendTranscript })

    /* ---------------------------------------------------------- generation */

    const loadJob = useCallback((next) => {
        setJob(next)
        setSelection(toSelection(collectSelectable(next.kind, next.draft)))
        setDraftDirty(false)
        setInstruction('')
    }, [])

    const generateMutation = useMutation({
        mutationFn: () => courseAiService.generate({
            kind,
            prompt: prompt.trim(),
            input_mode: usedVoice ? 'voice' : 'text',
            course: kind === 'outline' && !courseId ? null : courseId || null,
            provider,
            model,
            options,
            ...(kind === 'content' ? { topic_ids: topicIds } : {}),
        }),
        onSuccess: (data) => {
            loadJob(data)
            queryClient.invalidateQueries({ queryKey: ['coursegen-jobs'] })
        },
        onError: (err) => {
            const data = err?.response?.data
            // A 502 still carries the failed job, so show its error verbatim.
            if (data?.error) toast.error(data.error, { duration: 6000 })
            else toast.error(formatApiError(err, 'Generation failed'))
        },
    })

    const refineMutation = useMutation({
        mutationFn: () => courseAiService.refine(job.id, instruction.trim()),
        onSuccess: (data) => {
            loadJob(data)
            toast.success('Draft updated')
        },
        onError: (err) => toast.error(formatApiError(err, 'Could not refine the draft')),
    })

    const saveDraftMutation = useMutation({
        mutationFn: () => courseAiService.saveDraft(job.id, job.draft),
        onSuccess: (data) => {
            setJob(data)
            setDraftDirty(false)
            toast.success('Edits saved to the draft')
        },
        onError: (err) => toast.error(formatApiError(err, 'Could not save your edits')),
    })

    const applyMutation = useMutation({
        mutationFn: () => courseAiService.apply(job.id, selectionPayload(job.kind, selection)),
        onSuccess: ({ job: applied, summary }) => {
            setJob(applied)
            setConfirming(false)
            toast.success(
                summary?.course_name
                    ? `Saved to “${summary.course_name}”`
                    : 'Saved to your course',
            )
            // The course builder is now stale everywhere.
            queryClient.invalidateQueries({ queryKey: ['cb-courses'] })
            queryClient.invalidateQueries({ queryKey: ['availableCourses'] })
            queryClient.invalidateQueries({ queryKey: ['coursegen-jobs'] })
            queryClient.invalidateQueries({ queryKey: ['coursegen-tree'] })
        },
        onError: (err) => {
            setConfirming(false)
            toast.error(formatApiError(err, 'Could not save this draft'))
        },
    })

    const discardMutation = useMutation({
        mutationFn: () => courseAiService.discard(job.id),
        onSuccess: () => {
            setJob(null)
            queryClient.invalidateQueries({ queryKey: ['coursegen-jobs'] })
        },
        onError: (err) => toast.error(formatApiError(err)),
    })

    /* ------------------------------------------------------------- history */

    const { data: history = [] } = useQuery({
        queryKey: ['coursegen-jobs'],
        queryFn: () => courseAiService.listJobs({ page_size: 20 }),
        enabled: showHistory,
    })

    const openHistoryJob = async (id) => {
        try {
            loadJob(await courseAiService.getJob(id))
            setShowHistory(false)
        } catch (err) {
            toast.error(formatApiError(err))
        }
    }

    /* ------------------------------------------------------------ handlers */

    const toggleSelection = (bucket, node, checked) => {
        setSelection((prev) => {
            const next = toSelection({
                subjects: prev.subjects, chapters: prev.chapters,
                topics: prev.topics, fields: prev.fields,
            })
            const apply = (key, code) => (checked ? next[key].add(code) : next[key].delete(code))

            apply(bucket, node.code)

            // Ticking a parent takes its children with it, and vice versa.
            if (bucket === 'subjects') {
                (node.chapters || []).forEach((chapter) => {
                    apply('chapters', chapter.code)
                    ;(chapter.topics || []).forEach((topic) => apply('topics', topic.code))
                })
            }
            if (bucket === 'chapters') {
                (node.topics || []).forEach((topic) => apply('topics', topic.code))
            }
            // Ticking a child re-includes its ancestors, otherwise it would be
            // selected but unreachable.
            if (checked && job?.kind === 'outline' && bucket !== 'subjects') {
                (job.draft?.subjects || []).forEach((subject) => {
                    (subject.chapters || []).forEach((chapter) => {
                        const hit = bucket === 'chapters'
                            ? chapter.code === node.code
                            : (chapter.topics || []).some((topic) => topic.code === node.code)
                        if (hit) {
                            next.chapters.add(chapter.code)
                            next.subjects.add(subject.code)
                        }
                    })
                })
            }
            return next
        })
    }

    const editDraft = (path, value) => {
        setJob((prev) => ({ ...prev, draft: setIn(prev.draft || {}, path, value) }))
        setDraftDirty(true)
    }

    const canGenerate = useMemo(() => {
        if (!config?.is_ready || generateMutation.isPending) return false
        if (kind === 'outline') {
            // Only admins may create a course from nothing.
            if (!courseId && !config.can_create_courses) return false
            return prompt.trim().length > 3
        }
        if (kind === 'content') return !!courseId && topicIds.length > 0
        if (kind === 'meta') return !!courseId
        return false
    }, [config, generateMutation.isPending, kind, prompt, courseId, topicIds])

    const selectedCount = job
        ? selectionPayload(job.kind, selection)[job.kind === 'meta' ? 'fields' : 'topics']?.length || 0
        : 0

    /* --------------------------------------------------------------- views */

    if (loadingConfig) {
        return (
            <div className="card flex items-center justify-center gap-2 p-16 text-surface-500">
                <Loader2 className="h-5 w-5 animate-spin" /> Loading the studio…
            </div>
        )
    }

    if (!config?.is_ready) {
        return (
            <div className="card p-10 text-center">
                <Sparkles className="mx-auto mb-3 h-8 w-8 text-surface-300" />
                <h3 className="text-lg font-semibold text-surface-900 dark:text-surface-100">
                    AI Course Studio is not connected yet
                </h3>
                <p className="mx-auto mt-2 max-w-md text-sm text-surface-500">
                    {config?.not_ready_reason
                        || 'Connect an AI provider under Admin → AI Features to start generating courses.'}
                </p>
            </div>
        )
    }

    const meta = KIND_META[kind]

    return (
        <div className="space-y-5">
            {/* Header actions only — AdminDashboard renders the section title. */}
            <div className="flex flex-wrap items-center justify-end gap-3">
                {onClose && (
                    <button
                        type="button"
                        onClick={onClose}
                        className="mr-auto flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-sm text-surface-500 hover:bg-surface-100 dark:hover:bg-surface-700"
                    >
                        <ArrowLeft className="h-4 w-4" /> Back
                    </button>
                )}
                <button
                    type="button"
                    onClick={() => setShowHistory(true)}
                    className="flex items-center gap-1.5 rounded-lg border border-surface-200 px-3 py-2 text-sm text-surface-600 hover:bg-surface-50 dark:border-surface-700 dark:text-surface-300 dark:hover:bg-surface-700"
                >
                    <History className="h-4 w-4" /> History
                </button>
            </div>

            <div className="grid gap-5 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
                {/* ---------------------------------------------------- composer */}
                <div className="card h-fit space-y-4 p-5">
                    <div className="grid grid-cols-3 gap-1.5 rounded-lg bg-surface-100 p-1 dark:bg-surface-800">
                        {Object.entries(KIND_META).map(([id, info]) => (
                            <button
                                key={id}
                                type="button"
                                onClick={() => { setKind(id); setTopicIds([]) }}
                                className={`rounded-md px-2 py-1.5 text-xs font-medium transition ${
                                    kind === id
                                        ? 'bg-white text-primary-600 shadow-sm dark:bg-surface-700 dark:text-primary-300'
                                        : 'text-surface-500 hover:text-surface-700 dark:hover:text-surface-200'
                                }`}
                            >
                                {info.label}
                            </button>
                        ))}
                    </div>
                    <p className="-mt-2 text-xs text-surface-500">{meta.blurb}</p>

                    <Field
                        label="Course"
                        hint={kind === 'outline' && config.can_create_courses
                            ? 'Leave as "new course" to start from scratch, or pick one to extend.'
                            : undefined}
                    >
                        <select
                            className={inputClass}
                            value={courseId}
                            onChange={(e) => { setCourseId(e.target.value); setTopicIds([]) }}
                        >
                            <option value="">
                                {kind === 'outline' && config.can_create_courses
                                    ? 'Create a new course'
                                    : 'Select a course…'}
                            </option>
                            {(config.courses || []).map((course) => (
                                <option key={course.id} value={course.id}>{course.name}</option>
                            ))}
                        </select>
                    </Field>

                    {kind === 'outline' && !courseId && !config.can_create_courses && (
                        <p className="rounded-lg bg-amber-50 p-2.5 text-xs text-amber-700 dark:bg-amber-900/20 dark:text-amber-300">
                            Only an admin can create a brand-new course. Pick one of your courses to
                            extend it instead.
                        </p>
                    )}

                    <Field label={kind === 'outline' ? 'What should this course cover?' : 'Extra guidance (optional)'}>
                        <div className="relative">
                            <textarea
                                ref={promptRef}
                                rows={5}
                                value={prompt}
                                onChange={(e) => setPrompt(e.target.value)}
                                placeholder={meta.placeholder}
                                className={`${inputClass} resize-y pr-12`}
                            />
                            <div className="absolute right-2 top-2">
                                <MicButton voice={voice} />
                            </div>
                        </div>
                        <ListeningBar voice={voice} />
                    </Field>

                    {kind === 'content' && (
                        <Field label="Topics to write for">
                            <TopicPicker
                                courseId={courseId}
                                selected={topicIds}
                                onChange={setTopicIds}
                                max={maxTopics}
                            />
                        </Field>
                    )}

                    <Field label="Model">
                        {/* The included allowance is managed by us: we choose the
                            model and fail over between several, so there is no
                            model field to show for it. */}
                        <div className={providerEntry?.is_managed ? '' : 'grid grid-cols-2 gap-2'}>
                            <select
                                className={inputClass}
                                value={provider}
                                onChange={(e) => {
                                    const next = (config.providers || []).find((p) => p.provider === e.target.value)
                                    setProvider(e.target.value)
                                    setModel(next?.default_model || '')
                                }}
                            >
                                {(config.providers || []).map((entry) => (
                                    <option key={entry.provider} value={entry.provider}>
                                        {entry.provider_label}
                                    </option>
                                ))}
                            </select>
                            {providerEntry?.is_managed ? null : providerEntry?.allows_custom_model ? (
                                <input
                                    className={inputClass}
                                    value={model}
                                    list="coursegen-models"
                                    onChange={(e) => setModel(e.target.value)}
                                    placeholder="Model"
                                />
                            ) : (
                                <input className={`${inputClass} opacity-60`} value={model} readOnly />
                            )}
                            <datalist id="coursegen-models">
                                {(providerEntry?.models || []).map((name) => <option key={name} value={name} />)}
                            </datalist>
                        </div>
                        {providerEntry?.is_managed ? (
                            <p className="mt-1.5 text-xs text-surface-500">
                                We pick the best available model for you and switch automatically
                                if one is busy.
                            </p>
                        ) : null}
                    </Field>

                    <button
                        type="button"
                        onClick={() => setShowAdvanced((v) => !v)}
                        className="flex w-full items-center justify-between text-xs font-semibold uppercase tracking-wide text-surface-500 hover:text-surface-700"
                    >
                        Options
                        <ChevronDown className={`h-4 w-4 transition ${showAdvanced ? 'rotate-180' : ''}`} />
                    </button>

                    {showAdvanced && (
                        <div className="space-y-3 rounded-lg bg-surface-50 p-3 dark:bg-surface-800/60">
                            {kind === 'outline' && (
                                <div className="grid grid-cols-2 gap-2">
                                    <Field label="Chapters / module">
                                        <input
                                            type="number" min={1} max={20} className={inputClass}
                                            value={options.chapters_per_subject}
                                            onChange={(e) => setOptions((o) => ({ ...o, chapters_per_subject: Number(e.target.value) }))}
                                        />
                                    </Field>
                                    <Field label="Topics / chapter">
                                        <input
                                            type="number" min={1} max={12} className={inputClass}
                                            value={options.topics_per_chapter}
                                            onChange={(e) => setOptions((o) => ({ ...o, topics_per_chapter: Number(e.target.value) }))}
                                        />
                                    </Field>
                                </div>
                            )}
                            {kind === 'content' && (
                                <>
                                    <Field
                                        label="Material to write"
                                        hint="Assignments and coding problems are written per topic, alongside the notes and quiz."
                                    >
                                        <div className="grid grid-cols-2 gap-1.5">
                                            {CONTENT_MATERIALS.map((item) => {
                                                const active = options.materials.includes(item.id)
                                                return (
                                                    <button
                                                        key={item.id}
                                                        type="button"
                                                        onClick={() => setOptions((o) => ({
                                                            ...o,
                                                            materials: active
                                                                ? o.materials.filter((m) => m !== item.id)
                                                                : [...o.materials, item.id],
                                                        }))}
                                                        className={`rounded-lg border px-2.5 py-1.5 text-xs font-medium transition ${
                                                            active
                                                                ? 'border-primary-500 bg-primary-50 text-primary-700 dark:bg-primary-900/20 dark:text-primary-300'
                                                                : 'border-surface-200 text-surface-500 hover:border-surface-300 dark:border-surface-700'
                                                        }`}
                                                    >
                                                        {item.label}
                                                    </button>
                                                )
                                            })}
                                        </div>
                                    </Field>
                                    <div className="grid grid-cols-2 gap-2">
                                        {options.materials.includes('quiz') && (
                                            <Field label="Questions / quiz">
                                                <input
                                                    type="number" min={0}
                                                    max={config.limits?.max_questions_per_quiz || 20}
                                                    className={inputClass}
                                                    value={options.questions_per_quiz}
                                                    onChange={(e) => setOptions((o) => ({ ...o, questions_per_quiz: Number(e.target.value) }))}
                                                />
                                            </Field>
                                        )}
                                        {options.materials.includes('notes') && (
                                            <Field label="Depth">
                                                <select
                                                    className={inputClass}
                                                    value={options.depth}
                                                    onChange={(e) => setOptions((o) => ({ ...o, depth: e.target.value }))}
                                                >
                                                    <option value="concise">Concise</option>
                                                    <option value="standard">Standard</option>
                                                    <option value="deep">Detailed</option>
                                                </select>
                                            </Field>
                                        )}
                                    </div>
                                </>
                            )}
                            <Field label="Language">
                                <input
                                    className={inputClass}
                                    value={options.language}
                                    onChange={(e) => setOptions((o) => ({ ...o, language: e.target.value }))}
                                />
                            </Field>
                            {kind !== 'outline' && (
                                <label className="flex items-center gap-2 text-sm text-surface-600 dark:text-surface-300">
                                    <input
                                        type="checkbox"
                                        checked={options.publish_immediately}
                                        onChange={(e) => setOptions((o) => ({ ...o, publish_immediately: e.target.checked }))}
                                    />
                                    Publish to learners as soon as I approve it
                                </label>
                            )}
                        </div>
                    )}

                    <button
                        type="button"
                        onClick={() => generateMutation.mutate()}
                        disabled={!canGenerate}
                        className="flex w-full items-center justify-center gap-2 rounded-lg bg-gradient-to-r from-primary-600 to-purple-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-primary-500/25 transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                        {generateMutation.isPending
                            ? <><Loader2 className="h-4 w-4 animate-spin" /> Writing your draft…</>
                            : <><Sparkles className="h-4 w-4" /> Generate draft</>}
                    </button>
                    {generateMutation.isPending && (
                        <p className="text-center text-xs text-surface-400">
                            Good material takes a moment — this can run for a minute or two. Keep this tab open.
                        </p>
                    )}
                </div>

                {/* ----------------------------------------------------- preview */}
                <div className="card min-h-[24rem] p-5">
                    {!job && (
                        <div className="flex h-full flex-col items-center justify-center py-16 text-center">
                            <span className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-surface-100 text-surface-400 dark:bg-surface-800">
                                <Sparkles className="h-6 w-6" />
                            </span>
                            <h3 className="font-semibold text-surface-800 dark:text-surface-200">
                                Your draft will appear here
                            </h3>
                            <p className="mt-1 max-w-sm text-sm text-surface-500">
                                Describe what you need on the left — type it or use the microphone. You will
                                see the full result and choose exactly what to keep before anything is saved.
                            </p>
                        </div>
                    )}

                    {job && (
                        <div className="space-y-4">
                            <div className="flex flex-wrap items-center gap-2 border-b border-surface-100 pb-3 dark:border-surface-700">
                                <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${STATUS_PILL[job.status]}`}>
                                    {STATUS_LABEL[job.status] || job.status}
                                </span>
                                <span className="text-sm font-medium text-surface-700 dark:text-surface-200">
                                    {summaryLine(job.kind, job.summary)}
                                </span>
                                <div className="ml-auto flex items-center gap-2 text-xs text-surface-400">
                                    {job.model && <Pill>{job.model}</Pill>}
                                    {!!job.total_tokens && <span className="flex items-center gap-1"><Coins className="h-3 w-3" />{job.total_tokens.toLocaleString()} tokens</span>}
                                    {formatCost(job.estimated_cost_usd) && <span>{formatCost(job.estimated_cost_usd)}</span>}
                                    {!!job.generation_ms && <span className="flex items-center gap-1"><Clock className="h-3 w-3" />{(job.generation_ms / 1000).toFixed(1)}s</span>}
                                </div>
                            </div>

                            {job.status === 'failed' && (
                                <div className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700 dark:border-rose-800/40 dark:bg-rose-900/20 dark:text-rose-300">
                                    {job.error || 'Generation failed.'}
                                </div>
                            )}

                            {job.status === 'applied' && (
                                <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800 dark:border-emerald-800/40 dark:bg-emerald-900/20 dark:text-emerald-300">
                                    Saved to your course. Open the Content Builder to fine-tune it.
                                </div>
                            )}

                            {job.draft && job.status !== 'failed' && (
                                <DraftPreview
                                    job={job}
                                    selection={selection}
                                    onToggle={toggleSelection}
                                    onEdit={editDraft}
                                    editable={job.can_apply}
                                />
                            )}

                            {job.can_apply && (
                                <div className="space-y-3 border-t border-surface-100 pt-4 dark:border-surface-700">
                                    <div className="flex gap-2">
                                        <input
                                            className={inputClass}
                                            value={instruction}
                                            onChange={(e) => setInstruction(e.target.value)}
                                            onKeyDown={(e) => {
                                                if (e.key === 'Enter' && instruction.trim() && !refineMutation.isPending) {
                                                    refineMutation.mutate()
                                                }
                                            }}
                                            placeholder="What should change? e.g. “add a module on testing, make topics shorter”"
                                        />
                                        <button
                                            type="button"
                                            onClick={() => refineMutation.mutate()}
                                            disabled={!instruction.trim() || refineMutation.isPending}
                                            className="flex shrink-0 items-center gap-1.5 rounded-lg border border-surface-200 px-3 py-2 text-sm font-medium text-surface-600 hover:bg-surface-50 disabled:opacity-50 dark:border-surface-700 dark:text-surface-300"
                                        >
                                            {refineMutation.isPending
                                                ? <Loader2 className="h-4 w-4 animate-spin" />
                                                : <RotateCcw className="h-4 w-4" />}
                                            Refine
                                        </button>
                                    </div>

                                    <div className="flex flex-wrap items-center gap-2">
                                        <button
                                            type="button"
                                            onClick={() => discardMutation.mutate()}
                                            disabled={discardMutation.isPending}
                                            className="flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm text-surface-500 hover:bg-surface-100 dark:hover:bg-surface-700"
                                        >
                                            <Trash2 className="h-4 w-4" /> Discard
                                        </button>
                                        {draftDirty && (
                                            <button
                                                type="button"
                                                onClick={() => saveDraftMutation.mutate()}
                                                disabled={saveDraftMutation.isPending}
                                                className="flex items-center gap-1.5 rounded-lg border border-surface-200 px-3 py-2 text-sm text-surface-600 hover:bg-surface-50 dark:border-surface-700 dark:text-surface-300"
                                            >
                                                {saveDraftMutation.isPending
                                                    ? <Loader2 className="h-4 w-4 animate-spin" />
                                                    : <Save className="h-4 w-4" />}
                                                Save edits
                                            </button>
                                        )}
                                        <button
                                            type="button"
                                            onClick={() => setConfirming(true)}
                                            disabled={draftDirty || !selectedCount}
                                            title={draftDirty ? 'Save your edits first' : undefined}
                                            className="ml-auto flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-emerald-700 disabled:opacity-50"
                                        >
                                            <Send className="h-4 w-4" /> Review &amp; save to course
                                        </button>
                                    </div>
                                </div>
                            )}
                        </div>
                    )}
                </div>
            </div>

            {/* ------------------------------------------------------- dialogs */}
            <AnimatePresence>
                {confirming && (
                    <ConfirmApply
                        job={job}
                        selection={selection}
                        saving={applyMutation.isPending}
                        onCancel={() => setConfirming(false)}
                        onConfirm={() => applyMutation.mutate()}
                    />
                )}
            </AnimatePresence>

            <AnimatePresence>
                {showHistory && (
                    <div
                        className="fixed inset-0 z-50 flex justify-end bg-black/40"
                        onClick={() => setShowHistory(false)}
                    >
                        <motion.div
                            initial={{ x: 400 }}
                            animate={{ x: 0 }}
                            exit={{ x: 400 }}
                            onClick={(e) => e.stopPropagation()}
                            className="h-full w-full max-w-md overflow-y-auto bg-white p-5 dark:bg-surface-900"
                        >
                            <div className="mb-4 flex items-center justify-between">
                                <h3 className="font-semibold text-surface-900 dark:text-surface-100">Recent generations</h3>
                                <button type="button" onClick={() => setShowHistory(false)} className="rounded p-1 hover:bg-surface-100 dark:hover:bg-surface-800">
                                    <X className="h-4 w-4" />
                                </button>
                            </div>
                            {!history.length && <p className="text-sm text-surface-500">Nothing generated yet.</p>}
                            <ul className="space-y-2">
                                {history.map((entry) => (
                                    <li key={entry.id}>
                                        <button
                                            type="button"
                                            onClick={() => openHistoryJob(entry.id)}
                                            className="w-full rounded-lg border border-surface-200 p-3 text-left transition hover:border-primary-300 hover:bg-surface-50 dark:border-surface-700 dark:hover:bg-surface-800"
                                        >
                                            <div className="flex items-center gap-2">
                                                <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${STATUS_PILL[entry.status]}`}>
                                                    {STATUS_LABEL[entry.status] || entry.status}
                                                </span>
                                                <span className="text-xs text-surface-400">{KIND_META[entry.kind]?.label}</span>
                                                <span className="ml-auto text-xs text-surface-400">
                                                    {new Date(entry.created_at).toLocaleDateString()}
                                                </span>
                                            </div>
                                            <p className="mt-1.5 line-clamp-2 text-sm text-surface-700 dark:text-surface-200">
                                                {entry.prompt || entry.course_name || '—'}
                                            </p>
                                            <p className="mt-1 text-xs text-surface-400">
                                                {summaryLine(entry.kind, entry.summary)}
                                            </p>
                                        </button>
                                    </li>
                                ))}
                            </ul>
                        </motion.div>
                    </div>
                )}
            </AnimatePresence>
        </div>
    )
}

export default AICourseStudio
