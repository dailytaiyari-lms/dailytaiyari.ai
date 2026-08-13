import { useState } from 'react'
import { ChevronDown, Pencil, Timer } from 'lucide-react'
import { CheckBox, Field, Pill, inputClass, itemMeta } from './mockStudioParts'

/* ===========================================================================
 * MockDraftPreview — read, edit and choose from a generated paper.
 *
 * Nothing here is saved: this renders `job.draft`, which lives only on the job
 * until the admin confirms. Every question can be ticked (only ticked ones are
 * written) and hand-edited in place, because a good generated paper still
 * usually wants one number changed.
 *
 * Editing is keyed by the item's `key`, which the server keeps stable across a
 * refine — so a tick or an edit survives "make section B harder".
 * ========================================================================= */

/** Every item key in a draft — the default "keep everything" selection. */
export const collectItemKeys = (draft) => (draft?.items || []).map((item) => item.key)

const Row = ({ label, children }) => (
    <div className="grid grid-cols-[7rem_minmax(0,1fr)] items-center gap-2">
        <span className="text-xs font-medium text-surface-500">{label}</span>
        {children}
    </div>
)

const OptionRow = ({ option, index, editable, onEdit }) => (
    <div className={`flex items-start gap-2 rounded-lg px-2 py-1.5 text-sm ${
        option.is_correct
            ? 'bg-emerald-50 text-emerald-800 dark:bg-emerald-900/20 dark:text-emerald-300'
            : 'text-surface-600 dark:text-surface-300'
    }`}>
        <span className="mt-0.5 text-xs font-semibold text-surface-400">
            {String.fromCharCode(65 + index)}.
        </span>
        {editable ? (
            <input
                className="min-w-0 flex-1 border-b border-transparent bg-transparent text-sm outline-none focus:border-primary-400"
                value={option.text}
                onChange={(e) => onEdit(['text'], e.target.value)}
            />
        ) : (
            <span className="min-w-0 flex-1">{option.text}</span>
        )}
        {editable ? (
            <button
                type="button"
                onClick={() => onEdit(['is_correct'], !option.is_correct)}
                className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium ${
                    option.is_correct
                        ? 'bg-emerald-500 text-white'
                        : 'bg-surface-100 text-surface-500 dark:bg-surface-700'
                }`}
            >
                {option.is_correct ? 'Correct' : 'Mark correct'}
            </button>
        ) : option.is_correct && <Pill tone="emerald">Correct</Pill>}
    </div>
)

const ItemCard = ({ item, index, checked, onToggle, editable, onEdit }) => {
    const [open, setOpen] = useState(false)
    const meta = itemMeta(item.item_type)
    const Icon = meta.icon

    // `onEdit` is scoped to this item, so callers never juggle draft indices.
    const edit = (path, value) => onEdit(['items', index, ...path], value)

    return (
        <div className={`rounded-xl border transition ${
            checked
                ? 'border-surface-200 bg-white dark:border-surface-700 dark:bg-surface-800'
                : 'border-dashed border-surface-200 bg-surface-50/60 opacity-60 dark:border-surface-700 dark:bg-surface-800/40'
        }`}>
            <div className="flex items-start gap-3 p-3">
                <div className="pt-0.5">
                    <CheckBox checked={checked} onChange={onToggle} disabled={!editable} />
                </div>

                <div className="min-w-0 flex-1">
                    <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
                        <span className="text-xs font-semibold text-surface-400">Q{index + 1}</span>
                        <Pill><Icon className={`h-3 w-3 ${meta.tone}`} /> {meta.label}</Pill>
                        <Pill tone={item.difficulty === 'hard' ? 'rose' : item.difficulty === 'easy' ? 'emerald' : 'amber'}>
                            {item.difficulty}
                        </Pill>
                        <Pill>{item.marks} marks</Pill>
                        {!!item.negative_marks && <Pill tone="rose">−{item.negative_marks}</Pill>}
                        {item.concept && <span className="text-xs text-surface-400">{item.concept}</span>}
                    </div>

                    {editable ? (
                        <textarea
                            rows={2}
                            value={item.question_text}
                            onChange={(e) => edit(['question_text'], e.target.value)}
                            className="w-full resize-y rounded-lg border border-transparent bg-transparent p-1 text-sm text-surface-800 outline-none transition hover:border-surface-200 focus:border-primary-400 dark:text-surface-100 dark:hover:border-surface-700"
                        />
                    ) : (
                        <p className="whitespace-pre-wrap text-sm text-surface-800 dark:text-surface-100">
                            {item.question_text}
                        </p>
                    )}

                    {(item.item_type === 'mcq' || item.item_type === 'mcq_multi') && (
                        <div className="mt-1.5 space-y-0.5">
                            {(item.options || []).map((option, optionIndex) => (
                                <OptionRow
                                    key={optionIndex}
                                    option={option}
                                    index={optionIndex}
                                    editable={editable}
                                    onEdit={(path, value) => {
                                        if (path[0] === 'is_correct' && item.item_type === 'mcq' && value) {
                                            // Single-answer: ticking one option unticks the rest,
                                            // otherwise the server would silently pick for us.
                                            edit(['options'], item.options.map((o, i) => ({
                                                ...o, is_correct: i === optionIndex,
                                            })))
                                            return
                                        }
                                        edit(['options', optionIndex, ...path], value)
                                    }}
                                />
                            ))}
                        </div>
                    )}

                    {item.item_type === 'numerical' && (
                        <p className="mt-1.5 text-sm text-emerald-700 dark:text-emerald-300">
                            Answer: <strong>{item.numerical_answer}</strong>
                            {item.unit ? ` ${item.unit}` : ''}
                            <span className="ml-2 text-xs text-surface-400">
                                ± {item.numerical_tolerance}
                            </span>
                        </p>
                    )}

                    <button
                        type="button"
                        onClick={() => setOpen((v) => !v)}
                        className="mt-1.5 flex items-center gap-1 text-xs font-medium text-surface-400 hover:text-surface-600"
                    >
                        <ChevronDown className={`h-3.5 w-3.5 transition ${open ? 'rotate-180' : ''}`} />
                        {open ? 'Hide details' : 'Details'}
                    </button>

                    {open && (
                        <div className="mt-2 space-y-2 rounded-lg bg-surface-50 p-3 dark:bg-surface-900/40">
                            <Row label="Marks">
                                <div className="flex gap-2">
                                    <input
                                        type="number" min={0} step="0.5" className={inputClass}
                                        value={item.marks} disabled={!editable}
                                        onChange={(e) => edit(['marks'], Number(e.target.value))}
                                    />
                                    <input
                                        type="number" min={0} step="0.25" className={inputClass}
                                        value={item.negative_marks} disabled={!editable}
                                        onChange={(e) => edit(['negative_marks'], Number(e.target.value))}
                                        title="Negative marks"
                                    />
                                </div>
                            </Row>

                            {item.item_type === 'numerical' && (
                                <Row label="Answer">
                                    <input
                                        type="number" step="any" className={inputClass}
                                        value={item.numerical_answer} disabled={!editable}
                                        onChange={(e) => edit(['numerical_answer'], Number(e.target.value))}
                                    />
                                </Row>
                            )}

                            {item.item_type === 'subjective' && (
                                <>
                                    <Row label="Model answer">
                                        <textarea
                                            rows={3} className={inputClass} value={item.model_answer || ''}
                                            disabled={!editable}
                                            onChange={(e) => edit(['model_answer'], e.target.value)}
                                        />
                                    </Row>
                                    <Row label="Rubric">
                                        <textarea
                                            rows={2} className={inputClass} value={item.rubric || ''}
                                            disabled={!editable}
                                            onChange={(e) => edit(['rubric'], e.target.value)}
                                        />
                                    </Row>
                                </>
                            )}

                            {item.item_type === 'coding' && (
                                <>
                                    <Row label="Languages">
                                        <span className="flex flex-wrap gap-1">
                                            {(item.allowed_languages || []).map((lang) => (
                                                <Pill key={lang} tone="primary">{lang}</Pill>
                                            ))}
                                        </span>
                                    </Row>
                                    <Row label="Limits">
                                        <span className="flex items-center gap-2 text-xs text-surface-500">
                                            <Timer className="h-3.5 w-3.5" />
                                            {item.time_limit_ms} ms · {item.memory_limit_mb} MB
                                        </span>
                                    </Row>
                                    <div className="space-y-1.5">
                                        {(item.coding_test_cases || []).map((testCase, caseIndex) => (
                                            <div
                                                key={caseIndex}
                                                className="rounded-lg border border-surface-200 p-2 text-xs dark:border-surface-700"
                                            >
                                                <div className="mb-1 flex items-center gap-2">
                                                    <span className="font-semibold text-surface-500">
                                                        Case {caseIndex + 1}
                                                    </span>
                                                    {testCase.is_sample && <Pill tone="primary">sample</Pill>}
                                                    <Pill>{testCase.points} pt</Pill>
                                                </div>
                                                <pre className="overflow-x-auto whitespace-pre-wrap font-mono text-[11px] text-surface-600 dark:text-surface-300">
                                                    in: {testCase.stdin || '—'}{'\n'}out: {testCase.expected_output}
                                                </pre>
                                            </div>
                                        ))}
                                    </div>
                                </>
                            )}

                            <Row label="Explanation">
                                <textarea
                                    rows={2} className={inputClass} value={item.explanation || ''}
                                    disabled={!editable}
                                    onChange={(e) => edit(['explanation'], e.target.value)}
                                />
                            </Row>
                        </div>
                    )}
                </div>
            </div>
        </div>
    )
}

const MockDraftPreview = ({ draft, selected, onToggle, onToggleAll, onEdit, editable = true }) => {
    if (!draft) return null

    const items = draft.items || []
    const sections = draft.sections || []
    const stats = draft.stats || {}
    const test = draft.test || {}

    // Group by section so the preview reads like the paper a student will see.
    const grouped = sections.length
        ? sections.map((section, index) => ({
            section,
            entries: items
                .map((item, itemIndex) => ({ item, itemIndex }))
                .filter(({ item }) => (item.section || 0) === index),
        }))
        : [{ section: null, entries: items.map((item, itemIndex) => ({ item, itemIndex })) }]

    const allChecked = items.length > 0 && items.every((item) => selected.has(item.key))

    return (
        <div className="space-y-4">
            <div className="rounded-xl border border-surface-200 p-4 dark:border-surface-700">
                <div className="grid gap-3 sm:grid-cols-2">
                    <Field label="Paper title">
                        <input
                            className={inputClass} value={test.title || ''} disabled={!editable}
                            onChange={(e) => onEdit(['test', 'title'], e.target.value)}
                        />
                    </Field>
                    <Field label="Duration (minutes)">
                        <input
                            type="number" min={1} className={inputClass}
                            value={test.duration_minutes || 0} disabled={!editable}
                            onChange={(e) => onEdit(['test', 'duration_minutes'], Number(e.target.value))}
                        />
                    </Field>
                </div>
                <div className="mt-3 flex flex-wrap items-center gap-1.5">
                    <Pill tone="primary">{stats.items || 0} questions</Pill>
                    <Pill>{stats.total_marks || 0} marks</Pill>
                    {!!stats.sections && <Pill>{stats.sections} sections</Pill>}
                    {Object.entries(stats.by_type || {}).map(([type, count]) => (
                        <Pill key={type}>{count} × {itemMeta(type).label}</Pill>
                    ))}
                    {!!stats.needs_manual_grading && (
                        <Pill tone="amber">{stats.needs_manual_grading} need manual grading</Pill>
                    )}
                </div>
                {draft.partial_failures?.length > 0 && (
                    <p className="mt-3 rounded-lg bg-amber-50 p-2.5 text-xs text-amber-700 dark:bg-amber-900/20 dark:text-amber-300">
                        Some question types could not be written this time
                        ({draft.partial_failures.map((f) => f.types.join(', ')).join('; ')}).
                        Everything else below is fine — refine or regenerate to fill the gap.
                    </p>
                )}
            </div>

            {editable && items.length > 0 && (
                <div className="flex items-center gap-2 text-xs text-surface-500">
                    <CheckBox checked={allChecked} onChange={(checked) => onToggleAll(checked)} />
                    <span>{selected.size} of {items.length} questions selected</span>
                    <span className="ml-auto flex items-center gap-1 text-surface-400">
                        <Pencil className="h-3 w-3" /> Click any question to edit it
                    </span>
                </div>
            )}

            <div className="space-y-4">
                {grouped.map(({ section, entries }, groupIndex) => (
                    <div key={groupIndex} className="space-y-2">
                        {section && (
                            <div className="flex items-baseline gap-2">
                                <h4 className="text-sm font-semibold text-surface-700 dark:text-surface-200">
                                    {section.name}
                                </h4>
                                <span className="text-xs text-surface-400">
                                    {entries.length} question{entries.length === 1 ? '' : 's'}
                                    {section.description ? ` · ${section.description}` : ''}
                                </span>
                            </div>
                        )}
                        {entries.map(({ item, itemIndex }) => (
                            <ItemCard
                                key={item.key}
                                item={item}
                                index={itemIndex}
                                checked={selected.has(item.key)}
                                onToggle={(checked) => onToggle(item.key, checked)}
                                editable={editable}
                                onEdit={onEdit}
                            />
                        ))}
                        {!entries.length && (
                            <p className="rounded-lg border border-dashed border-surface-200 p-3 text-xs text-surface-400 dark:border-surface-700">
                                No questions in this section.
                            </p>
                        )}
                    </div>
                ))}
            </div>
        </div>
    )
}

export default MockDraftPreview
