import { useMemo, useState } from 'react'
import {
    ChevronDown, ListChecks, Plus, Repeat, SlidersHorizontal, Wand2,
} from 'lucide-react'
import BlueprintEditor from './BlueprintEditor'
import { CheckBox, Field, Pill, inputClass, itemMeta } from './mockStudioParts'

/* ===========================================================================
 * ModifyPanel — the "Modify with AI" composer.
 *
 * A revision is a much narrower job than writing a paper from scratch, and a
 * free-form sentence is a poor way to express it: "make it harder" could mean
 * rewrite everything or nudge two questions. So the admin picks an intent and,
 * optionally, the exact questions in scope. Both are sent to the model as hard
 * rules, and both are shown back here so it is obvious what will change.
 *
 * Everything on this panel is grounded in the paper itself — there is no course
 * or syllabus picker, because the paper *is* the source of truth.
 * ========================================================================= */

export const MODIFY_INTENTS = [
    {
        id: 'improve',
        label: 'Improve what is there',
        icon: Wand2,
        blurb: 'Sharper wording, better distractors, fuller explanations. Same questions.',
        placeholder: 'e.g. tighten the wording, make the distractors reflect real mistakes, and expand every explanation',
        scoped: true,
    },
    {
        id: 'add',
        label: 'Add new questions',
        icon: Plus,
        blurb: 'Existing questions are untouched; new ones are appended.',
        placeholder: 'e.g. add questions on list comprehensions and generators, same level as the rest',
        scoped: false,
    },
    {
        id: 'replace',
        label: 'Replace questions',
        icon: Repeat,
        blurb: 'Swap the questions you pick; everything else stays byte-identical.',
        placeholder: 'e.g. replace these with questions on the same concept but a different scenario',
        scoped: true,
    },
    {
        id: 'difficulty',
        label: 'Retune difficulty',
        icon: SlidersHorizontal,
        blurb: 'Same questions and concepts, dialled up or down.',
        placeholder: 'e.g. make section B noticeably harder, keep section A as an easy warm-up',
        scoped: true,
    },
    {
        id: 'custom',
        label: 'Something else',
        icon: ListChecks,
        blurb: 'Describe the change in your own words.',
        placeholder: 'e.g. move all numericals into a new Section C and drop negative marking there',
        scoped: true,
    },
]

export const intentMeta = (id) => MODIFY_INTENTS.find((entry) => entry.id === id) || MODIFY_INTENTS[0]

const GroundingCard = ({ title, snapshot, loading }) => {
    const stats = snapshot?.draft?.stats
    const counts = stats?.by_type || {}
    return (
        <div className="rounded-xl border border-primary-100 bg-primary-50/60 p-3 dark:border-primary-900/40 dark:bg-primary-900/10">
            <p className="text-xs font-semibold uppercase tracking-wide text-primary-600 dark:text-primary-300">
                Working on this paper
            </p>
            <p className="mt-1 font-medium text-surface-900 dark:text-surface-100">
                {title || 'This paper'}
            </p>
            <p className="mt-1 text-xs text-surface-500">
                {loading
                    ? 'Reading the paper…'
                    : [
                        stats?.items ? `${stats.items} questions` : '0 questions',
                        stats?.total_marks ? `${stats.total_marks} marks` : null,
                        snapshot?.mock_test?.total_attempts
                            ? `${snapshot.mock_test.total_attempts} attempts so far`
                            : null,
                    ].filter(Boolean).join(' · ')}
            </p>
            {!!Object.keys(counts).length && (
                <div className="mt-2 flex flex-wrap gap-1">
                    {Object.entries(counts).map(([type, count]) => (
                        <Pill key={type}>{itemMeta(type).label} × {count}</Pill>
                    ))}
                </div>
            )}
            <p className="mt-2 text-[11px] text-surface-400">
                Every revision is written from these questions — the AI never invents a
                different syllabus. Nothing is saved until you review it.
            </p>
        </div>
    )
}

const QuestionPicker = ({ items, selected, onToggle, onClear }) => {
    const [open, setOpen] = useState(false)
    const [search, setSearch] = useState('')

    const filtered = useMemo(() => {
        const needle = search.trim().toLowerCase()
        if (!needle) return items
        return items.filter((item) => (item.question_text || '').toLowerCase().includes(needle))
    }, [items, search])

    return (
        <div className="rounded-lg border border-surface-200 dark:border-surface-700">
            <button
                type="button"
                onClick={() => setOpen((value) => !value)}
                className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm"
            >
                <span className="text-surface-700 dark:text-surface-200">
                    {selected.size
                        ? `${selected.size} question${selected.size > 1 ? 's' : ''} in scope`
                        : 'Whole paper'}
                </span>
                <ChevronDown className={`h-4 w-4 shrink-0 text-surface-400 transition ${open ? 'rotate-180' : ''}`} />
            </button>

            {open && (
                <div className="border-t border-surface-100 p-2 dark:border-surface-700">
                    <input
                        className={`${inputClass} mb-2`}
                        value={search}
                        placeholder="Search questions…"
                        onChange={(event) => setSearch(event.target.value)}
                    />
                    <div className="max-h-56 space-y-1 overflow-y-auto pr-1">
                        {!filtered.length && (
                            <p className="px-1 py-2 text-xs text-surface-400">No questions match.</p>
                        )}
                        {filtered.map((item, index) => {
                            const meta = itemMeta(item.item_type)
                            return (
                                <label
                                    key={item.key || index}
                                    className="flex cursor-pointer items-start gap-2 rounded-lg p-1.5 hover:bg-surface-50 dark:hover:bg-surface-800"
                                >
                                    <span className="pt-0.5">
                                        <CheckBox
                                            checked={selected.has(item.key)}
                                            onChange={(checked) => onToggle(item.key, checked)}
                                        />
                                    </span>
                                    <span className="min-w-0">
                                        <span className={`mr-1.5 text-[11px] font-semibold ${meta.tone}`}>
                                            {meta.label}
                                        </span>
                                        <span className="text-xs text-surface-600 line-clamp-2 dark:text-surface-300">
                                            {item.question_text || 'Untitled question'}
                                        </span>
                                    </span>
                                </label>
                            )
                        })}
                    </div>
                    {!!selected.size && (
                        <button
                            type="button"
                            onClick={onClear}
                            className="mt-2 text-xs font-medium text-primary-600 hover:underline"
                        >
                            Clear selection — apply to the whole paper
                        </button>
                    )}
                </div>
            )}
        </div>
    )
}

const ModifyPanel = ({
    mockTestTitle,
    snapshot,
    loadingSnapshot,
    intent,
    onIntentChange,
    targets,
    onToggleTarget,
    onClearTargets,
    addBlueprint,
    onAddBlueprintChange,
    maxPerRun,
}) => {
    const items = snapshot?.draft?.items || []
    const meta = intentMeta(intent)

    return (
        <div className="space-y-4">
            <GroundingCard title={mockTestTitle} snapshot={snapshot} loading={loadingSnapshot} />

            <Field label="What kind of change?">
                <div className="grid gap-1.5">
                    {MODIFY_INTENTS.map((entry) => {
                        const Icon = entry.icon
                        const active = entry.id === intent
                        return (
                            <button
                                key={entry.id}
                                type="button"
                                onClick={() => onIntentChange(entry.id)}
                                className={`flex items-start gap-2.5 rounded-lg border p-2.5 text-left transition ${
                                    active
                                        ? 'border-primary-400 bg-primary-50 dark:border-primary-500/60 dark:bg-primary-900/20'
                                        : 'border-surface-200 hover:border-surface-300 hover:bg-surface-50 dark:border-surface-700 dark:hover:bg-surface-800'
                                }`}
                            >
                                <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${active ? 'text-primary-600' : 'text-surface-400'}`} />
                                <span className="min-w-0">
                                    <span className={`block text-sm font-medium ${active ? 'text-primary-700 dark:text-primary-200' : 'text-surface-800 dark:text-surface-200'}`}>
                                        {entry.label}
                                    </span>
                                    <span className="block text-xs text-surface-500">{entry.blurb}</span>
                                </span>
                            </button>
                        )
                    })}
                </div>
            </Field>

            {intent === 'add' ? (
                <Field label="What to add" hint="Existing questions are never touched by this.">
                    <BlueprintEditor
                        rows={addBlueprint}
                        sections={snapshot?.draft?.sections || []}
                        onChange={onAddBlueprintChange}
                        maxTotal={maxPerRun}
                    />
                </Field>
            ) : (
                <Field
                    label="Which questions?"
                    hint={meta.id === 'replace'
                        ? 'Pick the ones to swap out — or leave it on the whole paper.'
                        : 'Leave it on the whole paper, or narrow it to a few questions.'}
                >
                    <QuestionPicker
                        items={items}
                        selected={targets}
                        onToggle={onToggleTarget}
                        onClear={onClearTargets}
                    />
                </Field>
            )}
        </div>
    )
}

export default ModifyPanel
