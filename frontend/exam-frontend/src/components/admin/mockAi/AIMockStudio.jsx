import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'framer-motion'
import toast from 'react-hot-toast'
import {
    ArrowLeft, ChevronDown, Clock, Coins, History, Loader2, RotateCcw,
    Save, Send, Sparkles, Trash2, X,
} from 'lucide-react'
import mockAiService from '../../../services/mockAiService'
import useGenerationJob from '../../../hooks/useGenerationJob'
import useVoiceDictation from '../../../hooks/useVoiceDictation'
import { formatApiError } from '../builderShared'
import BlueprintEditor from './BlueprintEditor'
import ConfirmApplyMock from './ConfirmApplyMock'
import MockDraftPreview, { collectItemKeys } from './MockDraftPreview'
import {
    Field, KIND_LABEL, Pill, STATUS_LABEL, STATUS_PILL, formatCost, inputClass, summaryLine,
} from './mockStudioParts'
import { ListeningBar, MicButton } from '../aiStudio/studioParts'

/** Immutable set-at-path, so editing a draft never mutates React state. */
const setIn = (object, path, value) => {
    const [head, ...rest] = path
    const clone = Array.isArray(object) ? [...object] : { ...object }
    clone[head] = rest.length ? setIn(clone[head] || {}, rest, value) : value
    return clone
}

const DEFAULT_BLUEPRINT = [
    { item_type: 'mcq', count: 10, marks: 4, negative_marks: 1, difficulty: 'mixed', section: 0 },
]

/* ===========================================================================
 * AIMockStudio — draft-first AI authoring for mock tests.
 *
 * Two modes, one screen:
 *   • `create` writes a brand-new paper from a blueprint plus a brief;
 *   • `modify` rewrites an existing one — and works on *any* paper, including
 *     hand-typed ones, because the server can render a saved paper back into
 *     the same draft shape the model emits.
 *
 * Generation always runs on the server. The job is the source of truth, so an
 * admin can close this screen mid-run and pick the draft back up later; on
 * mount we look for an unfinished job and resume it rather than starting over.
 * ========================================================================= */
const AIMockStudio = ({
    mockTestId = null,
    mockTestTitle = '',
    onClose = null,
    onApplied = null,
}) => {
    const queryClient = useQueryClient()
    const isModify = !!mockTestId

    const [prompt, setPrompt] = useState('')
    const [usedVoice, setUsedVoice] = useState(false)
    const [provider, setProvider] = useState('')
    const [model, setModel] = useState('')
    const [courseId, setCourseId] = useState('')
    const [blueprint, setBlueprint] = useState(DEFAULT_BLUEPRINT)
    const [sections, setSections] = useState([{ name: 'Section 1', description: '' }])
    const [showAdvanced, setShowAdvanced] = useState(false)
    const [options, setOptions] = useState({
        title: '',
        duration_minutes: 60,
        difficulty: 'mixed',
        language: 'English',
        negative_marking: true,
        publish_immediately: false,
        apply_mode: 'replace',
        coding_languages: ['python'],
        syllabus: '',
    })

    const [selected, setSelected] = useState(() => new Set())
    const [draftDirty, setDraftDirty] = useState(false)
    const [instruction, setInstruction] = useState('')
    const [confirming, setConfirming] = useState(false)
    const [showHistory, setShowHistory] = useState(false)
    const resumedRef = useRef(false)

    /* ------------------------------------------------------------- options */

    const { data: config, isLoading: loadingConfig } = useQuery({
        queryKey: ['mockgen-options'],
        queryFn: () => mockAiService.getOptions(),
    })

    useEffect(() => {
        if (!config?.providers?.length || provider) return
        const active = config.providers.find((p) => p.is_active) || config.providers[0]
        setProvider(active.provider)
        setModel(active.default_model)
    }, [config, provider])

    useEffect(() => {
        if (!config?.defaults) return
        const { blueprint: defaultBlueprint, sections: defaultSections, ...rest } = config.defaults
        setOptions((prev) => ({ ...rest, ...prev }))
    }, [config])

    const providerEntry = useMemo(
        () => (config?.providers || []).find((p) => p.provider === provider),
        [config, provider],
    )
    const maxPerRun = config?.limits?.max_items_per_request || 60

    /* --------------------------------------------------------------- voice */

    const appendTranscript = useCallback((text) => {
        setUsedVoice(true)
        setPrompt((prev) => (prev ? `${prev.replace(/\s+$/, '')} ${text}` : text))
    }, [])
    const voice = useVoiceDictation({ onTranscript: appendTranscript })

    /* ---------------------------------------------------------- generation */

    const adoptDraft = useCallback((next) => {
        setSelected(new Set(collectItemKeys(next.draft)))
        setDraftDirty(false)
        setInstruction('')
    }, [])

    const {
        job, setJob, error: jobError, busy: generating, run, reset,
    } = useGenerationJob(mockAiService.getJob, {
        onSettled: (settled) => {
            if (settled.status === 'failed') {
                toast.error(settled.error || 'Generation failed', { duration: 6000 })
                return
            }
            adoptDraft(settled)
            queryClient.invalidateQueries({ queryKey: ['mockgen-jobs'] })
        },
    })

    useEffect(() => { if (jobError) toast.error(jobError) }, [jobError])

    // Resume: an admin who navigated away mid-run comes back to the live job
    // rather than an empty composer.
    const { data: openJobs = [] } = useQuery({
        queryKey: ['mockgen-jobs', 'open', mockTestId || 'new'],
        queryFn: () => mockAiService.listJobs({
            status: 'open', page_size: 5, ...(mockTestId ? { mock_test: mockTestId } : {}),
        }),
    })

    useEffect(() => {
        if (resumedRef.current || job || !openJobs.length) return
        const candidate = openJobs.find((entry) => (isModify ? true : entry.kind === 'create'))
        if (!candidate) return
        resumedRef.current = true
        run(() => mockAiService.getJob(candidate.id))
    }, [openJobs, job, isModify, run])

    const startGeneration = () => run(() => mockAiService.generate({
        kind: isModify ? 'modify' : 'create',
        prompt: prompt.trim(),
        input_mode: usedVoice ? 'voice' : 'text',
        mock_test: mockTestId || null,
        course: courseId || null,
        provider,
        model,
        options: {
            ...options,
            sections,
            ...(isModify ? {} : { blueprint }),
        },
    }))

    const regenerate = () => run(() => mockAiService.regenerate(job.id))
    const refineDraft = () => run(() => mockAiService.refine(job.id, instruction.trim()))

    const saveDraftMutation = useMutation({
        mutationFn: () => mockAiService.saveDraft(job.id, job.draft),
        onSuccess: (data) => {
            setJob(data)
            // Re-normalisation can drop an item the admin broke while editing.
            setSelected((prev) => new Set(
                collectItemKeys(data.draft).filter((key) => prev.has(key)),
            ))
            setDraftDirty(false)
            toast.success('Edits saved to the draft')
        },
        onError: (err) => toast.error(formatApiError(err, 'Could not save your edits')),
    })

    const applyMutation = useMutation({
        mutationFn: () => mockAiService.apply(job.id, { items: [...selected] }),
        onSuccess: ({ job: applied, summary }) => {
            setJob(applied)
            setConfirming(false)
            toast.success(isModify ? 'Mock test updated' : `Created “${summary.title}”`)
            queryClient.invalidateQueries({ queryKey: ['admin-mock-tests'] })
            queryClient.invalidateQueries({ queryKey: ['mockgen-jobs'] })
            if (summary?.mock_test) {
                queryClient.invalidateQueries({ queryKey: ['admin-mock-test', summary.mock_test] })
                queryClient.invalidateQueries({ queryKey: ['admin-mock-items', summary.mock_test] })
            }
            onApplied?.(summary)
        },
        onError: (err) => {
            setConfirming(false)
            toast.error(formatApiError(err, 'Could not save this paper'))
        },
    })

    const discardMutation = useMutation({
        mutationFn: () => mockAiService.discard(job.id),
        onSuccess: () => {
            reset()
            setSelected(new Set())
            queryClient.invalidateQueries({ queryKey: ['mockgen-jobs'] })
        },
        onError: (err) => toast.error(formatApiError(err)),
    })

    /* ------------------------------------------------------------- history */

    const { data: history = [] } = useQuery({
        queryKey: ['mockgen-jobs', 'history', mockTestId || 'all'],
        queryFn: () => mockAiService.listJobs({
            page_size: 20, ...(mockTestId ? { mock_test: mockTestId } : {}),
        }),
        enabled: showHistory,
    })

    const openHistoryJob = async (id) => {
        try {
            const next = await mockAiService.getJob(id)
            setJob(next)
            adoptDraft(next)
            setShowHistory(false)
        } catch (err) {
            toast.error(formatApiError(err))
        }
    }

    /* ------------------------------------------------------------ handlers */

    const toggleItem = (key, checked) => setSelected((prev) => {
        const next = new Set(prev)
        if (checked) next.add(key)
        else next.delete(key)
        return next
    })

    const toggleAll = (checked) => setSelected(
        checked ? new Set(collectItemKeys(job?.draft)) : new Set(),
    )

    const editDraft = (path, value) => {
        setJob((prev) => ({ ...prev, draft: setIn(prev.draft || {}, path, value) }))
        setDraftDirty(true)
    }

    const totalRequested = blueprint.reduce((sum, row) => sum + Number(row.count || 0), 0)

    const canGenerate = useMemo(() => {
        if (!config?.is_ready || generating) return false
        if (isModify) return prompt.trim().length > 3
        if (!totalRequested || totalRequested > maxPerRun) return false
        return prompt.trim().length > 3 || !!courseId || !!options.syllabus?.trim()
    }, [config, generating, isModify, prompt, totalRequested, maxPerRun, courseId, options.syllabus])

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
                    The AI Mock Studio is not connected yet
                </h3>
                <p className="mx-auto mt-2 max-w-md text-sm text-surface-500">
                    {config?.not_ready_reason
                        || 'Connect an AI provider under Admin → AI Features to start generating papers.'}
                </p>
            </div>
        )
    }

    return (
        <div className="space-y-5">
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

            <div className="grid gap-5 lg:grid-cols-[minmax(0,23rem)_minmax(0,1fr)]">
                {/* ---------------------------------------------------- composer */}
                <div className="card h-fit space-y-4 p-5">
                    {isModify ? (
                        <div className="rounded-lg bg-surface-50 p-3 text-sm dark:bg-surface-800/60">
                            <p className="font-medium text-surface-800 dark:text-surface-100">
                                Modifying “{mockTestTitle || 'this paper'}”
                            </p>
                            <p className="mt-1 text-xs text-surface-500">
                                The AI reads the whole paper first, so it can rewrite, replace or add
                                questions — even if this test was written by hand.
                            </p>
                        </div>
                    ) : (
                        <Field label="Paper title" hint="Leave blank and the AI will name it.">
                            <input
                                className={inputClass}
                                value={options.title}
                                placeholder="e.g. JEE Main — Full Mock 3"
                                onChange={(e) => setOptions((o) => ({ ...o, title: e.target.value }))}
                            />
                        </Field>
                    )}

                    <Field
                        label={isModify ? 'What should change?' : 'What should this paper cover?'}
                    >
                        <div className="relative">
                            <textarea
                                rows={5}
                                value={prompt}
                                onChange={(e) => setPrompt(e.target.value)}
                                placeholder={isModify
                                    ? 'e.g. make section B harder, replace the two calculus questions with vectors, and add a coding question on recursion'
                                    : 'e.g. Class 12 Physics half-yearly: rotational motion, thermodynamics and waves. NCERT level, exam-style traps, one long numerical per topic.'}
                                className={`${inputClass} resize-y pr-12`}
                            />
                            <div className="absolute right-2 top-2">
                                <MicButton voice={voice} />
                            </div>
                        </div>
                        <ListeningBar voice={voice} />
                    </Field>

                    {!isModify && (
                        <>
                            <Field label="Question blueprint">
                                <BlueprintEditor
                                    rows={blueprint}
                                    sections={sections}
                                    onChange={setBlueprint}
                                    maxTotal={maxPerRun}
                                />
                            </Field>

                            <div className="grid grid-cols-2 gap-2">
                                <Field label="Duration (min)">
                                    <input
                                        type="number" min={1} max={600} className={inputClass}
                                        value={options.duration_minutes}
                                        onChange={(e) => setOptions((o) => ({
                                            ...o, duration_minutes: Number(e.target.value),
                                        }))}
                                    />
                                </Field>
                                <Field label="Overall level">
                                    <select
                                        className={inputClass}
                                        value={options.difficulty}
                                        onChange={(e) => setOptions((o) => ({ ...o, difficulty: e.target.value }))}
                                    >
                                        {['mixed', 'easy', 'medium', 'hard'].map((value) => (
                                            <option key={value} value={value}>{value}</option>
                                        ))}
                                    </select>
                                </Field>
                            </div>
                        </>
                    )}

                    <Field
                        label="Ground it in a course"
                        hint="Optional — the AI uses that course's syllabus as the source of truth."
                    >
                        <select
                            className={inputClass}
                            value={courseId}
                            onChange={(e) => setCourseId(e.target.value)}
                        >
                            <option value="">No course</option>
                            {(config.courses || []).map((course) => (
                                <option key={course.id} value={course.id}>{course.name}</option>
                            ))}
                        </select>
                    </Field>

                    <Field label="Model">
                        <div className="grid grid-cols-2 gap-2">
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
                            {providerEntry?.allows_custom_model ? (
                                <input
                                    className={inputClass}
                                    value={model}
                                    list="mockgen-models"
                                    onChange={(e) => setModel(e.target.value)}
                                    placeholder="Model"
                                />
                            ) : (
                                <input className={`${inputClass} opacity-60`} value={model} readOnly />
                            )}
                            <datalist id="mockgen-models">
                                {(providerEntry?.models || []).map((name) => <option key={name} value={name} />)}
                            </datalist>
                        </div>
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
                            {isModify ? (
                                <Field
                                    label="How to apply changes"
                                    hint="Questions students have already answered are never deleted."
                                >
                                    <select
                                        className={inputClass}
                                        value={options.apply_mode}
                                        onChange={(e) => setOptions((o) => ({ ...o, apply_mode: e.target.value }))}
                                    >
                                        <option value="replace">Replace the paper with the revision</option>
                                        <option value="append">Keep everything, add what is new</option>
                                    </select>
                                </Field>
                            ) : (
                                <>
                                    <Field label="Sections">
                                        <div className="space-y-1.5">
                                            {sections.map((section, index) => (
                                                <div key={index} className="flex gap-1.5">
                                                    <input
                                                        className={inputClass}
                                                        value={section.name}
                                                        onChange={(e) => setSections(sections.map((s, i) => (
                                                            i === index ? { ...s, name: e.target.value } : s
                                                        )))}
                                                    />
                                                    <button
                                                        type="button"
                                                        onClick={() => setSections(sections.filter((_, i) => i !== index))}
                                                        disabled={sections.length === 1}
                                                        className="shrink-0 rounded-lg p-2 text-surface-400 hover:text-rose-500 disabled:opacity-30"
                                                    >
                                                        <Trash2 className="h-4 w-4" />
                                                    </button>
                                                </div>
                                            ))}
                                            <button
                                                type="button"
                                                onClick={() => setSections([
                                                    ...sections,
                                                    { name: `Section ${sections.length + 1}`, description: '' },
                                                ])}
                                                className="text-xs font-medium text-primary-600 hover:underline"
                                            >
                                                + Add section
                                            </button>
                                        </div>
                                    </Field>

                                    <Field label="Syllabus / source material" hint="Optional — pasted text the AI must stick to.">
                                        <textarea
                                            rows={3} className={inputClass} value={options.syllabus || ''}
                                            onChange={(e) => setOptions((o) => ({ ...o, syllabus: e.target.value }))}
                                        />
                                    </Field>

                                    <label className="flex items-center gap-2 text-sm text-surface-600 dark:text-surface-300">
                                        <input
                                            type="checkbox" checked={options.negative_marking}
                                            onChange={(e) => setOptions((o) => ({ ...o, negative_marking: e.target.checked }))}
                                        />
                                        Negative marking
                                    </label>
                                    <label className="flex items-center gap-2 text-sm text-surface-600 dark:text-surface-300">
                                        <input
                                            type="checkbox" checked={options.publish_immediately}
                                            onChange={(e) => setOptions((o) => ({ ...o, publish_immediately: e.target.checked }))}
                                        />
                                        Publish as soon as I save it
                                    </label>
                                </>
                            )}

                            <Field label="Language">
                                <input
                                    className={inputClass} value={options.language || 'English'}
                                    onChange={(e) => setOptions((o) => ({ ...o, language: e.target.value }))}
                                />
                            </Field>

                            <Field label="Coding languages">
                                <div className="flex flex-wrap gap-1.5">
                                    {(config.coding_languages || []).map((lang) => {
                                        const on = (options.coding_languages || []).includes(lang.id)
                                        return (
                                            <button
                                                key={lang.id}
                                                type="button"
                                                onClick={() => setOptions((o) => ({
                                                    ...o,
                                                    coding_languages: on
                                                        ? o.coding_languages.filter((id) => id !== lang.id)
                                                        : [...(o.coding_languages || []), lang.id],
                                                }))}
                                                className={`rounded-full px-2.5 py-1 text-xs font-medium transition ${
                                                    on
                                                        ? 'bg-primary-500 text-white'
                                                        : 'bg-surface-100 text-surface-500 dark:bg-surface-700'
                                                }`}
                                            >
                                                {lang.label}
                                            </button>
                                        )
                                    })}
                                </div>
                            </Field>
                        </div>
                    )}

                    <button
                        type="button"
                        onClick={startGeneration}
                        disabled={!canGenerate}
                        className="flex w-full items-center justify-center gap-2 rounded-lg bg-gradient-to-r from-primary-600 to-purple-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-primary-500/25 transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                        {generating
                            ? <><Loader2 className="h-4 w-4 animate-spin" /> Writing your paper…</>
                            : <><Sparkles className="h-4 w-4" /> {isModify ? 'Generate revision' : 'Generate paper'}</>}
                    </button>
                    {generating && (
                        <p className="text-center text-xs text-surface-400">
                            This runs on the server. You can leave this page — the run keeps going and
                            the draft will be waiting for you.
                        </p>
                    )}
                </div>

                {/* ----------------------------------------------------- preview */}
                <div className="card min-h-[24rem] p-5">
                    {generating && (
                        <div className="flex h-full flex-col items-center justify-center py-16 text-center">
                            <Loader2 className="mb-4 h-8 w-8 animate-spin text-primary-500" />
                            <h3 className="font-semibold text-surface-800 dark:text-surface-200">
                                {job?.status === 'generating'
                                    ? 'The AI is writing your paper…'
                                    : 'Queued — starting shortly…'}
                            </h3>
                            <p className="mt-1 max-w-sm text-sm text-surface-500">
                                Questions are written in batches, so a long paper takes a couple of
                                minutes. Nothing is saved until you review and confirm.
                            </p>
                        </div>
                    )}

                    {!job && !generating && (
                        <div className="flex h-full flex-col items-center justify-center py-16 text-center">
                            <span className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-surface-100 text-surface-400 dark:bg-surface-800">
                                <Sparkles className="h-6 w-6" />
                            </span>
                            <h3 className="font-semibold text-surface-800 dark:text-surface-200">
                                Your paper will appear here
                            </h3>
                            <p className="mt-1 max-w-sm text-sm text-surface-500">
                                Describe the paper on the left — type it or use the microphone. You
                                will see every question, edit anything you like, and choose exactly
                                what to keep before it is saved.
                            </p>
                        </div>
                    )}

                    {job && !generating && (
                        <div className="space-y-4">
                            <div className="flex flex-wrap items-center gap-2 border-b border-surface-100 pb-3 dark:border-surface-700">
                                <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${STATUS_PILL[job.status]}`}>
                                    {STATUS_LABEL[job.status] || job.status}
                                </span>
                                <span className="text-sm font-medium text-surface-700 dark:text-surface-200">
                                    {summaryLine(job.summary)}
                                </span>
                                <div className="ml-auto flex items-center gap-2 text-xs text-surface-400">
                                    {job.model && <Pill>{job.model}</Pill>}
                                    {!!job.total_tokens && (
                                        <span className="flex items-center gap-1">
                                            <Coins className="h-3 w-3" />{job.total_tokens.toLocaleString()} tokens
                                        </span>
                                    )}
                                    {formatCost(job.estimated_cost_usd) && <span>{formatCost(job.estimated_cost_usd)}</span>}
                                    {!!job.generation_ms && (
                                        <span className="flex items-center gap-1">
                                            <Clock className="h-3 w-3" />{(job.generation_ms / 1000).toFixed(1)}s
                                        </span>
                                    )}
                                </div>
                            </div>

                            {job.status === 'failed' && (
                                <div className="space-y-3">
                                    <div className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700 dark:border-rose-800/40 dark:bg-rose-900/20 dark:text-rose-300">
                                        {job.error || 'Generation failed.'}
                                    </div>
                                    <p className="text-xs text-surface-500">
                                        Nothing was saved. Run it again with the same brief, or change
                                        the brief on the left.
                                    </p>
                                    <button
                                        type="button"
                                        onClick={regenerate}
                                        className="flex items-center gap-1.5 rounded-lg border border-surface-200 px-3 py-2 text-sm font-medium text-surface-600 hover:bg-surface-50 dark:border-surface-700 dark:text-surface-300"
                                    >
                                        <RotateCcw className="h-4 w-4" /> Try again
                                    </button>
                                </div>
                            )}

                            {job.status === 'applied' && (
                                <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800 dark:border-emerald-800/40 dark:bg-emerald-900/20 dark:text-emerald-300">
                                    Saved. Open the mock test builder to fine-tune anything.
                                </div>
                            )}

                            {job.draft && job.status !== 'failed' && (
                                <MockDraftPreview
                                    draft={job.draft}
                                    selected={selected}
                                    onToggle={toggleItem}
                                    onToggleAll={toggleAll}
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
                                                if (e.key === 'Enter' && instruction.trim() && !generating) {
                                                    refineDraft()
                                                }
                                            }}
                                            placeholder="What should change? e.g. “make Q3–Q6 harder, add units to the numericals”"
                                        />
                                        <button
                                            type="button"
                                            onClick={refineDraft}
                                            disabled={!instruction.trim() || generating}
                                            className="flex shrink-0 items-center gap-1.5 rounded-lg border border-surface-200 px-3 py-2 text-sm font-medium text-surface-600 hover:bg-surface-50 disabled:opacity-50 dark:border-surface-700 dark:text-surface-300"
                                        >
                                            {generating
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
                                        <button
                                            type="button"
                                            onClick={regenerate}
                                            className="flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm text-surface-500 hover:bg-surface-100 dark:hover:bg-surface-700"
                                        >
                                            <RotateCcw className="h-4 w-4" /> Regenerate
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
                                            disabled={draftDirty || !selected.size}
                                            title={draftDirty ? 'Save your edits first' : undefined}
                                            className="ml-auto flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-emerald-700 disabled:opacity-50"
                                        >
                                            <Send className="h-4 w-4" />
                                            {isModify ? 'Review & update paper' : 'Review & create paper'}
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
                    <ConfirmApplyMock
                        job={job}
                        selectedKeys={selected}
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
                                <h3 className="font-semibold text-surface-900 dark:text-surface-100">
                                    Recent generations
                                </h3>
                                <button
                                    type="button"
                                    onClick={() => setShowHistory(false)}
                                    className="rounded p-1 hover:bg-surface-100 dark:hover:bg-surface-800"
                                >
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
                                                <span className="text-xs text-surface-400">
                                                    {KIND_LABEL[entry.kind] || entry.kind}
                                                </span>
                                                <span className="ml-auto text-xs text-surface-400">
                                                    {new Date(entry.created_at).toLocaleDateString()}
                                                </span>
                                            </div>
                                            <p className="mt-1.5 line-clamp-2 text-sm text-surface-700 dark:text-surface-200">
                                                {entry.prompt || entry.mock_test_title || '—'}
                                            </p>
                                            <p className="mt-1 text-xs text-surface-400">
                                                {summaryLine(entry.summary)}
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

export default AIMockStudio
