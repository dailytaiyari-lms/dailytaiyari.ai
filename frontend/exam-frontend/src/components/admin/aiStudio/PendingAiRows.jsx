import { AlertTriangle, Eye, Loader2, Sparkles } from 'lucide-react'

/* ===========================================================================
 * PendingAiRows — in-flight AI work, shown where the material will land.
 *
 * Generation happens on the server and can take minutes, so an admin who closes
 * the studio used to lose all sight of it. These rows sit at the top of the
 * matching tab — a quiz being written appears under Quizzes — so the work is
 * visible exactly where it is expected, with no page to navigate to.
 *
 * A finished draft is still a draft: the row's action reopens the review panel,
 * because nothing is ever written to the course without an explicit confirm.
 * ========================================================================= */

const PendingAiRows = ({ entries = [], onReview }) => {
    if (!entries.length) return null

    return (
        <div className="mb-3 space-y-2">
            {entries.map((entry) => {
                const { job } = entry
                const running = job.is_running
                const failed = job.status === 'failed'

                return (
                    <div
                        key={entry.key}
                        className={`flex items-center gap-3 rounded-xl border p-3 ${
                            failed
                                ? 'border-rose-200 bg-rose-50/60 dark:border-rose-800/40 dark:bg-rose-900/10'
                                : 'border-primary-200 bg-primary-50/60 dark:border-primary-800/40 dark:bg-primary-900/10'
                        }`}
                    >
                        <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${
                            failed
                                ? 'bg-rose-100 text-rose-600 dark:bg-rose-900/30 dark:text-rose-300'
                                : 'bg-primary-100 text-primary-600 dark:bg-primary-900/30 dark:text-primary-300'
                        }`}>
                            {running
                                ? <Loader2 className="h-4 w-4 animate-spin" />
                                : failed
                                    ? <AlertTriangle className="h-4 w-4" />
                                    : <Sparkles className="h-4 w-4" />}
                        </span>

                        <div className="min-w-0 flex-1">
                            <p className="truncate text-sm font-semibold text-surface-800 dark:text-surface-100">
                                {entry.label}
                                <span className="ml-2 text-xs font-medium text-surface-500">
                                    {running
                                        ? (job.status === 'pending' ? 'queued…' : 'generating…')
                                        : failed
                                            ? 'generation failed'
                                            : 'draft ready to review'}
                                </span>
                            </p>
                            <p className="truncate text-xs text-surface-500">
                                {failed
                                    ? (job.error || 'Nothing was saved.')
                                    : running
                                        ? 'Writing on the server — you can keep working, this keeps going.'
                                        : 'Not saved yet. Review it to add it to this topic.'}
                            </p>
                        </div>

                        {!running && (
                            <button
                                type="button"
                                onClick={() => onReview?.(entry)}
                                className="btn-secondary shrink-0 text-xs px-3 py-1.5"
                            >
                                <Eye className="h-3.5 w-3.5" />
                                {failed ? 'Retry' : 'Review'}
                            </button>
                        )}
                    </div>
                )
            })}
        </div>
    )
}

export default PendingAiRows
