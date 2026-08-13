import { motion } from 'framer-motion'
import { AlertTriangle, Check, Loader2, ShieldCheck } from 'lucide-react'

/* ===========================================================================
 * ConfirmApplyMock — the last gate before a paper is written.
 *
 * Everything up to this point lives on the job. This dialog spells out, in
 * plain counts, what the confirm will do — including the two things that are
 * genuinely destructive (replacing the questions of an existing paper, and
 * publishing it straight away). The backend independently refuses to write
 * without the confirmation this sends.
 * ========================================================================= */

const line = (count, singular, plural) =>
    count ? `${count} ${count === 1 ? singular : plural}` : null

const ConfirmApplyMock = ({ job, selectedKeys, saving, onCancel, onConfirm }) => {
    const draft = job?.draft || {}
    const items = (draft.items || []).filter((item) => selectedKeys.has(item.key))
    const marks = items.reduce((sum, item) => sum + Number(item.marks || 0), 0)
    const manual = items.filter(
        (item) => !['mcq', 'mcq_multi', 'numerical', 'coding'].includes(item.item_type),
    ).length

    const isModify = job?.kind === 'modify'
    const replacing = isModify && (job?.options?.apply_mode || 'replace') === 'replace'
    const publishing = !isModify && !!job?.options?.publish_immediately

    const bullets = [
        isModify
            ? `update “${job.mock_test_title || draft.test?.title}”`
            : `create the mock test “${draft.test?.title || 'Untitled'}” as a draft`,
        line(items.length, 'question', 'questions'),
        marks ? `${marks} marks in total` : null,
        line(draft.sections?.length, 'section', 'sections'),
    ].filter(Boolean)

    return (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm">
            <motion.div
                initial={{ opacity: 0, scale: 0.96, y: 8 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                className="card w-full max-w-lg p-6"
            >
                <div className="flex items-start gap-3">
                    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-primary-100 text-primary-600 dark:bg-primary-900/30 dark:text-primary-300">
                        <ShieldCheck className="h-5 w-5" />
                    </span>
                    <div>
                        <h3 className="text-lg font-semibold text-surface-900 dark:text-surface-100">
                            Save this paper?
                        </h3>
                        <p className="mt-1 text-sm text-surface-500">
                            This is the first and only moment anything is written.
                        </p>
                    </div>
                </div>

                <ul className="mt-4 space-y-1.5 rounded-xl bg-surface-50 p-4 text-sm text-surface-700 dark:bg-surface-800/60 dark:text-surface-200">
                    {bullets.map((entry) => (
                        <li key={entry} className="flex items-start gap-2">
                            <Check className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" />
                            {entry}
                        </li>
                    ))}
                </ul>

                {replacing && (
                    <p className="mt-3 flex items-start gap-2 rounded-lg bg-amber-50 p-3 text-xs text-amber-700 dark:bg-amber-900/20 dark:text-amber-300">
                        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                        The paper's current questions will be replaced by these. Questions students
                        have already answered are always kept.
                    </p>
                )}

                {!!manual && (
                    <p className="mt-3 text-xs text-surface-500">
                        {manual} question{manual === 1 ? '' : 's'} will need grading by hand.
                    </p>
                )}

                {publishing && (
                    <p className="mt-3 flex items-start gap-2 rounded-lg bg-amber-50 p-3 text-xs text-amber-700 dark:bg-amber-900/20 dark:text-amber-300">
                        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                        You chose to publish immediately — students will see this paper as soon as
                        it is saved.
                    </p>
                )}

                <div className="mt-6 flex justify-end gap-2">
                    <button
                        type="button"
                        onClick={onCancel}
                        disabled={saving}
                        className="rounded-lg px-4 py-2 text-sm text-surface-600 hover:bg-surface-100 disabled:opacity-50 dark:text-surface-300 dark:hover:bg-surface-700"
                    >
                        Keep reviewing
                    </button>
                    <button
                        type="button"
                        onClick={onConfirm}
                        disabled={saving || !items.length}
                        className="flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-emerald-700 disabled:opacity-50"
                    >
                        {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                        {isModify ? 'Update the paper' : 'Create the paper'}
                    </button>
                </div>
            </motion.div>
        </div>
    )
}

export default ConfirmApplyMock
