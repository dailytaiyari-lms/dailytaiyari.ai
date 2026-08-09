import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'framer-motion'
import {
    ClipboardList, Code2, FileText, Layers, ListChecks, Loader2, Plus,
    RefreshCw, Sparkles, X,
} from 'lucide-react'

import courseAiService from '../../../services/courseAiService'
import useVoiceDictation from '../../../hooks/useVoiceDictation'
import ConfirmApply from './ConfirmApply'
import DraftPreview, { collectSelectable } from './DraftPreview'
import { Field, ListeningBar, MicButton, Pill, inputClass } from './studioParts'

/* ===========================================================================
 * TopicStudio — generate material for ONE topic, in place.
 *
 * The full studio is built for bulk work: pick a course, pick a dozen topics,
 * review a long draft. That is the wrong shape when an admin is already looking
 * at a single topic in the course builder and just wants a quiz for it.
 *
 * So this panel asks only the three questions that actually matter here:
 *
 *   1. what kind of material (notes / quiz / assignment / coding problem),
 *   2. add it alongside what exists, or replace what exists,
 *   3. anything specific to say about it (typed or dictated).
 *
 * Everything else — course, subject, topic, surrounding curriculum, what is
 * already written — is inferred from where the admin opened it. The
 * preview-then-confirm guarantee is unchanged: this panel produces a draft and
 * routes the write through the same ConfirmApply gate as the full studio.
 * ========================================================================= */

const MATERIALS = [
    { id: 'notes', label: 'Reading notes', icon: FileText, blurb: 'The lesson itself' },
    { id: 'quiz', label: 'Practice quiz', icon: ListChecks, blurb: 'MCQs with explanations' },
    { id: 'assignment', label: 'Assignment', icon: ClipboardList, blurb: 'Graded submission' },
    { id: 'coding', label: 'Coding problem', icon: Code2, blurb: 'With test cases' },
]

const EXISTING_KEYS = {
    notes: 'notes',
    quiz: 'quizzes',
    assignment: 'assignments',
    coding: 'coding_problems',
}

const MaterialTile = ({ material, selected, existingCount, onToggle }) => {
    const Icon = material.icon
    return (
        <button
            type="button"
            onClick={() => onToggle(material.id)}
            className={`flex items-start gap-3 rounded-xl border p-3 text-left transition ${
                selected
                    ? 'border-primary-500 bg-primary-50 dark:border-primary-500 dark:bg-primary-900/20'
                    : 'border-surface-200 hover:border-surface-300 dark:border-surface-700 dark:hover:border-surface-600'
            }`}
        >
            <span
                className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${
                    selected
                        ? 'bg-primary-500 text-white'
                        : 'bg-surface-100 text-surface-500 dark:bg-surface-700 dark:text-surface-300'
                }`}
            >
                <Icon className="h-4 w-4" />
            </span>
            <span className="min-w-0">
                <span className="block text-sm font-semibold text-surface-900 dark:text-surface-100">
                    {material.label}
                </span>
                <span className="block text-xs text-surface-500">{material.blurb}</span>
                {existingCount > 0 && (
                    <span className="mt-1 inline-block text-[11px] font-medium text-amber-600 dark:text-amber-400">
                        {existingCount} already here
                    </span>
                )}
            </span>
        </button>
    )
}

const ModeCard = ({ active, icon: Icon, title, blurb, onClick, disabled }) => (
    <button
        type="button"
        onClick={onClick}
        disabled={disabled}
        className={`flex flex-1 items-start gap-2.5 rounded-xl border p-3 text-left transition disabled:cursor-not-allowed disabled:opacity-50 ${
            active
                ? 'border-primary-500 bg-primary-50 dark:border-primary-500 dark:bg-primary-900/20'
                : 'border-surface-200 hover:border-surface-300 dark:border-surface-700 dark:hover:border-surface-600'
        }`}
    >
        <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${active ? 'text-primary-500' : 'text-surface-400'}`} />
        <span className="min-w-0">
            <span className="block text-sm font-semibold text-surface-900 dark:text-surface-100">{title}</span>
            <span className="block text-xs text-surface-500">{blurb}</span>
        </span>
    </button>
)

/** What the topic already has, so "add" vs "replace" is an informed choice. */
const ExistingMaterial = ({ material }) => {
    const rows = [
        { key: 'notes', label: 'Reading', items: material.notes },
        { key: 'quizzes', label: 'Quiz', items: material.quizzes },
        { key: 'assignments', label: 'Assignment', items: material.assignments },
        { key: 'coding_problems', label: 'Coding', items: material.coding_problems },
    ].filter((row) => (row.items || []).length)

    if (!rows.length) {
        return (
            <p className="rounded-lg border border-dashed border-surface-300 p-3 text-xs text-surface-500 dark:border-surface-600">
                This topic is empty — anything you generate will be its first material.
            </p>
        )
    }

    return (
        <div className="space-y-1.5">
            {rows.map((row) => row.items.map((item) => (
                <div
                    key={`${row.key}-${item.id}`}
                    className="flex flex-wrap items-center gap-2 rounded-lg bg-surface-50 px-3 py-2 text-xs dark:bg-surface-800/60"
                >
                    <span className="font-medium text-surface-500">{row.label}</span>
                    <span className="min-w-0 flex-1 truncate text-surface-800 dark:text-surface-200">{item.title}</span>
                    <Pill tone={item.status === 'published' ? 'emerald' : 'surface'}>{item.status}</Pill>
                    {item.locked && <Pill tone="amber">in use</Pill>}
                </div>
            )))}
        </div>
    )
}

const TopicStudio = ({ courseId, topic, subjectName, onClose, onApplied }) => {
    const queryClient = useQueryClient()

    const [materials, setMaterials] = useState(['notes'])
    const [mode, setMode] = useState('replace')
    const [brief, setBrief] = useState('')
    const [inputMode, setInputMode] = useState('text')
    const [model, setModel] = useState('')
    const [questionsPerQuiz, setQuestionsPerQuiz] = useState(5)
    const [depth, setDepth] = useState('standard')

    const [job, setJob] = useState(null)
    const [selection, setSelection] = useState(null)
    const [confirming, setConfirming] = useState(false)
    const [error, setError] = useState('')

    const { data: options } = useQuery({
        queryKey: ['coursegen-options'],
        queryFn: courseAiService.getOptions,
        staleTime: 60_000,
    })

    const { data: material, isLoading: loadingMaterial } = useQuery({
        queryKey: ['coursegen-topic-material', courseId, topic?.id],
        queryFn: () => courseAiService.getTopicMaterial(courseId, topic.id),
        enabled: !!courseId && !!topic?.id,
    })

    const voice = useVoiceDictation({
        onTranscript: (text) => {
            setInputMode('voice')
            setBrief((prev) => (prev ? `${prev} ${text}` : text))
        },
    })

    // Flatten every configured provider's models into one picker: the admin
    // chose the providers under AI Features, and may use any model they serve.
    const modelChoices = useMemo(() => {
        const list = []
        for (const provider of options?.providers || []) {
            // The included allowance is one opaque choice: we manage which
            // model runs it and fail over between several behind the scenes.
            if (provider.is_managed) {
                list.push({
                    value: `${provider.provider}:`,
                    label: provider.provider_label || 'Included AI',
                    isDefault: provider.is_active,
                })
                continue
            }
            for (const name of provider.models || []) {
                list.push({
                    value: `${provider.provider}:${name}`,
                    label: `${provider.provider_label || provider.provider} · ${name}`,
                    isDefault: provider.is_active && name === provider.default_model,
                })
            }
        }
        return list
    }, [options])

    // Preselect the provider's active default so the picker never reads as
    // "no model chosen" when there plainly is one.
    useEffect(() => {
        if (model) return
        const preferred = modelChoices.find((choice) => choice.isDefault)
        if (preferred) setModel(preferred.value)
    }, [modelChoices, model])

    // A topic with nothing on it can only be added to, so don't offer a choice
    // that would do exactly the same thing under a scarier name.
    const isEmptyTopic = !!material && !Object.values(material.counts || {}).some(Boolean)
    useEffect(() => {
        if (isEmptyTopic) setMode('add')
    }, [isEmptyTopic])

    const toggleMaterial = (id) => {
        setMaterials((prev) => (prev.includes(id) ? prev.filter((m) => m !== id) : [...prev, id]))
    }

    const generate = useMutation({
        mutationFn: () => {
            const [provider, modelName] = model ? model.split(':') : ['', '']
            return courseAiService.generate({
                kind: 'content',
                course: courseId,
                topic_ids: [topic.id],
                prompt: brief,
                input_mode: inputMode,
                provider,
                model: modelName,
                options: {
                    materials,
                    mode,
                    depth,
                    questions_per_quiz: questionsPerQuiz,
                },
            })
        },
        onSuccess: (data) => {
            setJob(data)
            setSelection(toSelection(collectSelectable('content', data.draft)))
            setError('')
        },
        onError: (err) => {
            setError(
                err?.response?.data?.detail
                || err?.response?.data?.error
                || 'Generation failed. Try again, or add more detail to your brief.',
            )
        },
    })

    const apply = useMutation({
        mutationFn: () => courseAiService.apply(job.id, {
            topics: [...(selection?.topics || [])],
        }),
        onSuccess: () => {
            setConfirming(false)
            setJob(null)
            queryClient.invalidateQueries({ queryKey: ['coursegen-topic-material', courseId, topic?.id] })
            onApplied?.()
            onClose?.()
        },
        onError: (err) => {
            setConfirming(false)
            setError(err?.response?.data?.detail || 'Could not save this material.')
        },
    })

    const toggleSelection = (bucket, item, checked) => {
        setSelection((prev) => {
            const next = { ...prev, [bucket]: new Set(prev[bucket]) }
            if (checked) next[bucket].add(item.code)
            else next[bucket].delete(item.code)
            return next
        })
    }

    const counts = material?.counts || {}
    const busy = generate.isPending
    const canGenerate = materials.length > 0 && !busy

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm">
            <motion.div
                initial={{ opacity: 0, scale: 0.97, y: 10 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                className="card flex max-h-[92vh] w-full max-w-3xl flex-col overflow-hidden p-0"
            >
                <div className="flex items-start gap-3 border-b border-surface-100 p-5 dark:border-surface-700">
                    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary-100 text-primary-600 dark:bg-primary-900/30 dark:text-primary-300">
                        <Sparkles className="h-5 w-5" />
                    </span>
                    <div className="min-w-0 flex-1">
                        <h3 className="truncate text-lg font-semibold text-surface-900 dark:text-surface-100">
                            {topic?.name}
                        </h3>
                        <p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-surface-500">
                            {subjectName && (
                                <span className="inline-flex items-center gap-1">
                                    <Layers className="h-3 w-3" />{subjectName}
                                </span>
                            )}
                            <span>Generate material for this topic only</span>
                        </p>
                    </div>
                    <button
                        type="button"
                        onClick={onClose}
                        className="rounded-lg p-1.5 text-surface-400 transition hover:bg-surface-100 hover:text-surface-600 dark:hover:bg-surface-700"
                    >
                        <X className="h-4.5 w-4.5" />
                    </button>
                </div>

                <div className="min-h-0 flex-1 overflow-y-auto p-5">
                    {job ? (
                        <div className="space-y-4">
                            <DraftPreview job={job} selection={selection} onToggle={toggleSelection} editable={false} />
                        </div>
                    ) : (
                        <div className="space-y-5">
                            <div>
                                <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-surface-500">
                                    Already on this topic
                                </p>
                                {loadingMaterial ? (
                                    <p className="text-xs text-surface-400">Checking…</p>
                                ) : (
                                    <ExistingMaterial material={material || {}} />
                                )}
                            </div>

                            <div>
                                <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-surface-500">
                                    What should the AI write?
                                </p>
                                <div className="grid gap-2 sm:grid-cols-2">
                                    {MATERIALS.map((item) => (
                                        <MaterialTile
                                            key={item.id}
                                            material={item}
                                            selected={materials.includes(item.id)}
                                            existingCount={counts[EXISTING_KEYS[item.id]] || 0}
                                            onToggle={toggleMaterial}
                                        />
                                    ))}
                                </div>
                            </div>

                            {!isEmptyTopic && (
                                <div>
                                    <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-surface-500">
                                        How should it sit with what is already here?
                                    </p>
                                    <div className="flex flex-col gap-2 sm:flex-row">
                                        <ModeCard
                                            active={mode === 'add'}
                                            icon={Plus}
                                            title="Add more"
                                            blurb="Keeps what exists and writes material that complements it."
                                            onClick={() => setMode('add')}
                                        />
                                        <ModeCard
                                            active={mode === 'replace'}
                                            icon={RefreshCw}
                                            title="Replace"
                                            blurb="Rewrites this topic's material from scratch."
                                            onClick={() => setMode('replace')}
                                        />
                                    </div>
                                </div>
                            )}

                            <Field
                                label="Anything specific? (optional)"
                                hint="Leave blank and the AI works from the topic name, its summary and the rest of the course."
                            >
                                <div className="relative">
                                    <textarea
                                        className={`${inputClass} min-h-[5.5rem] pr-12`}
                                        value={brief}
                                        onChange={(e) => { setBrief(e.target.value); setInputMode('text') }}
                                        placeholder="e.g. Focus on real interview questions, and use a worked example with Indian rupees."
                                    />
                                    <span className="absolute right-2 top-2">
                                        <MicButton voice={voice} />
                                    </span>
                                </div>
                                <ListeningBar voice={voice} />
                            </Field>

                            <div className="grid gap-3 sm:grid-cols-3">
                                <Field label="Model">
                                    <select
                                        className={inputClass}
                                        value={model}
                                        onChange={(e) => setModel(e.target.value)}
                                    >
                                        <option value="">Default model</option>
                                        {modelChoices.map((choice) => (
                                            <option key={choice.value} value={choice.value}>{choice.label}</option>
                                        ))}
                                    </select>
                                </Field>
                                {materials.includes('notes') && (
                                    <Field label="Depth">
                                        <select
                                            className={inputClass}
                                            value={depth}
                                            onChange={(e) => setDepth(e.target.value)}
                                        >
                                            <option value="concise">Concise (~5 min)</option>
                                            <option value="standard">Standard (~10 min)</option>
                                            <option value="deep">In depth (~20 min)</option>
                                        </select>
                                    </Field>
                                )}
                                {materials.includes('quiz') && (
                                    <Field label="Questions">
                                        <input
                                            type="number"
                                            min={1}
                                            max={options?.limits?.max_questions_per_quiz || 20}
                                            className={inputClass}
                                            value={questionsPerQuiz}
                                            onChange={(e) => setQuestionsPerQuiz(Number(e.target.value))}
                                        />
                                    </Field>
                                )}
                            </div>
                        </div>
                    )}

                    {error && (
                        <p className="mt-4 rounded-lg bg-rose-50 p-3 text-sm text-rose-600 dark:bg-rose-900/20 dark:text-rose-300">
                            {error}
                        </p>
                    )}
                </div>

                <div className="flex flex-wrap items-center gap-2 border-t border-surface-100 p-4 dark:border-surface-700">
                    {job ? (
                        <>
                            <button
                                type="button"
                                onClick={() => { setJob(null); setSelection(null) }}
                                className="btn-secondary text-sm"
                            >
                                Start over
                            </button>
                            <p className="ml-auto mr-2 hidden text-xs text-surface-400 sm:block">
                                Nothing is saved until you confirm.
                            </p>
                            <button
                                type="button"
                                onClick={() => setConfirming(true)}
                                disabled={!selection?.topics?.size}
                                className="btn-primary text-sm disabled:opacity-50"
                            >
                                Review &amp; save
                            </button>
                        </>
                    ) : (
                        <>
                            <button type="button" onClick={onClose} className="btn-secondary text-sm">
                                Cancel
                            </button>
                            <button
                                type="button"
                                onClick={() => generate.mutate()}
                                disabled={!canGenerate}
                                className="btn-primary ml-auto text-sm disabled:opacity-50"
                            >
                                {busy
                                    ? <><Loader2 className="h-4 w-4 animate-spin" /> Writing…</>
                                    : <><Sparkles className="h-4 w-4" /> Generate</>}
                            </button>
                        </>
                    )}
                </div>
            </motion.div>

            <AnimatePresence>
                {confirming && (
                    <ConfirmApply
                        job={job}
                        selection={selection}
                        saving={apply.isPending}
                        onCancel={() => setConfirming(false)}
                        onConfirm={() => apply.mutate()}
                    />
                )}
            </AnimatePresence>
        </div>
    )
}

/** collectSelectable returns arrays; the preview works in Sets. */
const toSelection = (selectable) => ({
    subjects: new Set(selectable.subjects),
    chapters: new Set(selectable.chapters),
    topics: new Set(selectable.topics),
    fields: new Set(selectable.fields),
})

export default TopicStudio
