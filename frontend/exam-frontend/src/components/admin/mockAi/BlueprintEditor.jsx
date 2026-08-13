import { Plus, Trash2 } from 'lucide-react'
import { ITEM_TYPE_META, inputClass } from './mockStudioParts'

/* ===========================================================================
 * BlueprintEditor — "how many questions of what kind, worth what".
 *
 * This is the part of the brief a prompt is bad at: an admin knows the exact
 * paper structure they want, and typing "20 MCQs of 4 marks with -1" into prose
 * gives the model room to disagree. Structured rows go straight into the
 * generation batches, so counts and marks come out exactly as asked.
 * ========================================================================= */

const DIFFICULTIES = ['mixed', 'easy', 'medium', 'hard']

const blankRow = (sectionCount) => ({
    item_type: 'mcq', count: 5, marks: 4, negative_marks: 1,
    difficulty: 'mixed', section: Math.max(0, sectionCount - 1),
})

const BlueprintEditor = ({ rows, sections, onChange, maxTotal }) => {
    const total = rows.reduce((sum, row) => sum + Number(row.count || 0), 0)
    const over = total > maxTotal

    const patch = (index, changes) => onChange(
        rows.map((row, i) => (i === index ? { ...row, ...changes } : row)),
    )

    return (
        <div className="space-y-2">
            {rows.map((row, index) => (
                <div
                    key={index}
                    className="space-y-2 rounded-lg border border-surface-200 p-2.5 dark:border-surface-700"
                >
                    <div className="flex items-center gap-2">
                        <select
                            className={inputClass}
                            value={row.item_type}
                            onChange={(e) => patch(index, {
                                item_type: e.target.value,
                                // Hand-graded and judged types never carry a penalty.
                                negative_marks: ['subjective', 'coding'].includes(e.target.value)
                                    ? 0 : row.negative_marks,
                            })}
                        >
                            {Object.entries(ITEM_TYPE_META).map(([value, meta]) => (
                                <option key={value} value={value}>{meta.long}</option>
                            ))}
                        </select>
                        <button
                            type="button"
                            onClick={() => onChange(rows.filter((_, i) => i !== index))}
                            disabled={rows.length === 1}
                            className="shrink-0 rounded-lg p-2 text-surface-400 hover:bg-rose-50 hover:text-rose-500 disabled:opacity-30 dark:hover:bg-rose-900/20"
                            title="Remove this row"
                        >
                            <Trash2 className="h-4 w-4" />
                        </button>
                    </div>

                    <div className="grid grid-cols-3 gap-2">
                        <label className="block">
                            <span className="mb-1 block text-[11px] font-medium text-surface-400">Count</span>
                            <input
                                type="number" min={1} max={maxTotal} className={inputClass}
                                value={row.count}
                                onChange={(e) => patch(index, { count: Number(e.target.value) })}
                            />
                        </label>
                        <label className="block">
                            <span className="mb-1 block text-[11px] font-medium text-surface-400">Marks</span>
                            <input
                                type="number" min={0} step="0.5" className={inputClass}
                                value={row.marks}
                                onChange={(e) => patch(index, { marks: Number(e.target.value) })}
                            />
                        </label>
                        <label className="block">
                            <span className="mb-1 block text-[11px] font-medium text-surface-400">Negative</span>
                            <input
                                type="number" min={0} step="0.25" className={inputClass}
                                value={row.negative_marks}
                                disabled={['subjective', 'coding'].includes(row.item_type)}
                                onChange={(e) => patch(index, { negative_marks: Number(e.target.value) })}
                            />
                        </label>
                    </div>

                    <div className="grid grid-cols-2 gap-2">
                        <select
                            className={inputClass}
                            value={row.difficulty || 'mixed'}
                            onChange={(e) => patch(index, { difficulty: e.target.value })}
                        >
                            {DIFFICULTIES.map((value) => (
                                <option key={value} value={value}>{value} difficulty</option>
                            ))}
                        </select>
                        <select
                            className={inputClass}
                            value={row.section ?? 0}
                            onChange={(e) => patch(index, { section: Number(e.target.value) })}
                        >
                            {(sections.length ? sections : [{ name: 'Section 1' }]).map((section, i) => (
                                <option key={i} value={i}>{section.name || `Section ${i + 1}`}</option>
                            ))}
                        </select>
                    </div>

                    <input
                        className={inputClass}
                        value={row.note || ''}
                        placeholder="Optional: what these questions should cover"
                        onChange={(e) => patch(index, { note: e.target.value })}
                    />
                </div>
            ))}

            <div className="flex items-center gap-2">
                <button
                    type="button"
                    onClick={() => onChange([...rows, blankRow(sections.length)])}
                    className="flex items-center gap-1.5 rounded-lg border border-dashed border-surface-300 px-3 py-1.5 text-xs font-medium text-surface-500 hover:border-primary-400 hover:text-primary-600 dark:border-surface-600"
                >
                    <Plus className="h-3.5 w-3.5" /> Add question type
                </button>
                <span className={`ml-auto text-xs ${over ? 'font-semibold text-rose-500' : 'text-surface-400'}`}>
                    {total} question{total === 1 ? '' : 's'}
                    {over ? ` — max ${maxTotal} per run` : ''}
                </span>
            </div>
        </div>
    )
}

export default BlueprintEditor
