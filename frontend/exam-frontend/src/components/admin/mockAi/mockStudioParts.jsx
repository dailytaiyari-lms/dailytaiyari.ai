import { Calculator, Check, Code2, FileText, ListChecks } from 'lucide-react'

/* ===========================================================================
 * Small presentational pieces shared across the AI Mock Studio.
 *
 * Kept apart from the course studio's `studioParts` deliberately: the two
 * screens share an idea (draft first, apply later) but not a vocabulary — a
 * mock test talks about sections, marks and negative marking, not chapters.
 * ========================================================================= */

export const ITEM_TYPE_META = {
    mcq: { label: 'MCQ', long: 'MCQ (single answer)', icon: ListChecks, tone: 'text-blue-500' },
    mcq_multi: { label: 'Multi', long: 'MCQ (multiple answers)', icon: Check, tone: 'text-cyan-500' },
    numerical: { label: 'Numerical', long: 'Numerical', icon: Calculator, tone: 'text-violet-500' },
    subjective: { label: 'Subjective', long: 'Subjective (written)', icon: FileText, tone: 'text-amber-500' },
    coding: { label: 'Coding', long: 'Coding', icon: Code2, tone: 'text-emerald-500' },
}

export const itemMeta = (type) => ITEM_TYPE_META[type] || ITEM_TYPE_META.mcq

export const STATUS_PILL = {
    preview: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300',
    applied: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300',
    failed: 'bg-rose-100 text-rose-700 dark:bg-rose-900/30 dark:text-rose-300',
    discarded: 'bg-surface-200 text-surface-600 dark:bg-surface-700 dark:text-surface-300',
    generating: 'bg-primary-100 text-primary-700 dark:bg-primary-900/30 dark:text-primary-300',
    pending: 'bg-surface-200 text-surface-600 dark:bg-surface-700 dark:text-surface-300',
}

export const STATUS_LABEL = {
    preview: 'Awaiting your review',
    applied: 'Saved',
    failed: 'Failed',
    discarded: 'Discarded',
    generating: 'Generating',
    pending: 'Queued',
}

export const KIND_LABEL = {
    create: 'New paper',
    modify: 'Modify with AI',
}

export const inputClass =
    'w-full rounded-lg border border-surface-200 bg-white px-3 py-2 text-sm text-surface-900 '
    + 'outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-500/20 '
    + 'dark:border-surface-700 dark:bg-surface-800 dark:text-surface-100'

export const Field = ({ label, hint, children }) => (
    <label className="block">
        <span className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-surface-500 dark:text-surface-400">
            {label}
        </span>
        {children}
        {hint && <span className="mt-1 block text-xs text-surface-400">{hint}</span>}
    </label>
)

export const Pill = ({ children, tone = 'surface' }) => {
    const tones = {
        surface: 'bg-surface-100 text-surface-600 dark:bg-surface-700/60 dark:text-surface-300',
        primary: 'bg-primary-100 text-primary-700 dark:bg-primary-900/30 dark:text-primary-300',
        emerald: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300',
        amber: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300',
        rose: 'bg-rose-100 text-rose-700 dark:bg-rose-900/30 dark:text-rose-300',
    }
    return (
        <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${tones[tone] || tones.surface}`}>
            {children}
        </span>
    )
}

/** A checkbox used to pick which generated questions to keep. */
export const CheckBox = ({ checked, onChange, disabled }) => (
    <label className={`inline-flex ${disabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer'}`}>
        <span
            className={`flex h-4 w-4 shrink-0 items-center justify-center rounded border transition ${
                checked
                    ? 'border-primary-500 bg-primary-500 text-white'
                    : 'border-surface-300 bg-white dark:border-surface-600 dark:bg-surface-800'
            }`}
        >
            {checked && <Check className="h-3 w-3" strokeWidth={3} />}
        </span>
        <input
            type="checkbox"
            className="sr-only"
            checked={checked}
            disabled={disabled}
            onChange={(e) => onChange(e.target.checked)}
        />
    </label>
)

export const formatCost = (value) => {
    const amount = Number(value || 0)
    if (!amount) return null
    return amount < 0.01 ? '<$0.01' : `$${amount.toFixed(2)}`
}

/** One-line description of a draft, used in banners and the history drawer. */
export const summaryLine = (summary) => {
    if (!summary) return ''
    const parts = [
        summary.items ? `${summary.items} questions` : null,
        summary.total_marks ? `${summary.total_marks} marks` : null,
        summary.duration_minutes ? `${summary.duration_minutes} min` : null,
        summary.needs_manual_grading
            ? `${summary.needs_manual_grading} to grade by hand`
            : null,
    ].filter(Boolean)
    return parts.join(' · ')
}
