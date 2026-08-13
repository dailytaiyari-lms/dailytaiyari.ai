import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, Eye, Loader2, Sparkles } from 'lucide-react'
import mockAiService from '../../../services/mockAiService'
import { KIND_LABEL, summaryLine } from './mockStudioParts'

/* ===========================================================================
 * MockAiJobBanners — in-flight AI work, shown where the paper will land.
 *
 * Generation happens on the server and can take minutes. Without this, an admin
 * who leaves the studio has no way of knowing a run is still going — so the
 * banner is driven by the job rows themselves, not by local state: it reappears
 * on every visit to the mock-test list (or to a specific paper) until the draft
 * is reviewed and applied, or discarded.
 *
 * A finished run still says "ready to review", never "done": nothing is written
 * without an explicit confirm in the studio.
 * ========================================================================= */

const POLL_MS = 4000

const MockAiJobBanners = ({ mockTestId = null, onOpen, className = '' }) => {
    const { data: jobs = [] } = useQuery({
        queryKey: ['mockgen-jobs', 'open', mockTestId || 'all'],
        queryFn: () => mockAiService.listJobs({
            status: 'open', page_size: 10, ...(mockTestId ? { mock_test: mockTestId } : {}),
        }),
        // Keep polling while anything is still running, then fall quiet.
        refetchInterval: (query) => (
            (query.state.data || []).some((job) => job.is_running) ? POLL_MS : false
        ),
        refetchOnWindowFocus: true,
    })

    if (!jobs.length) return null

    return (
        <div className={`space-y-2 ${className}`}>
            {jobs.map((job) => {
                const running = job.is_running
                const label = job.kind === 'modify'
                    ? `${KIND_LABEL.modify}${job.mock_test_title ? ` · ${job.mock_test_title}` : ''}`
                    : 'New paper with AI'

                return (
                    <div
                        key={job.id}
                        className="flex items-center gap-3 rounded-xl border border-primary-200 bg-primary-50/60 p-3 dark:border-primary-800/40 dark:bg-primary-900/10"
                    >
                        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary-100 text-primary-600 dark:bg-primary-900/30 dark:text-primary-300">
                            {running
                                ? <Loader2 className="h-4 w-4 animate-spin" />
                                : <Sparkles className="h-4 w-4" />}
                        </span>

                        <div className="min-w-0 flex-1">
                            <p className="truncate text-sm font-semibold text-surface-800 dark:text-surface-100">
                                {label}
                                <span className="ml-2 text-xs font-medium text-surface-500">
                                    {running
                                        ? (job.status === 'pending' ? 'queued…' : 'generating…')
                                        : 'draft ready to review'}
                                </span>
                            </p>
                            <p className="truncate text-xs text-surface-500">
                                {running
                                    ? 'Writing on the server — you can keep working, this keeps going.'
                                    : `Not saved yet. ${summaryLine(job.summary) || 'Review it to save it.'}`}
                            </p>
                        </div>

                        {!running && (
                            <button
                                type="button"
                                onClick={() => onOpen?.(job)}
                                className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-surface-200 bg-white px-3 py-1.5 text-xs font-medium text-surface-600 hover:bg-surface-50 dark:border-surface-700 dark:bg-surface-800 dark:text-surface-300"
                            >
                                <Eye className="h-3.5 w-3.5" /> Review
                            </button>
                        )}
                    </div>
                )
            })}
        </div>
    )
}

/** Same data, one line — used inside the builder header. */
export const MockAiFailureNote = ({ job }) => {
    if (!job || job.status !== 'failed') return null
    return (
        <p className="flex items-center gap-2 rounded-lg bg-rose-50 p-2.5 text-xs text-rose-700 dark:bg-rose-900/20 dark:text-rose-300">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
            {job.error || 'The last AI run failed. Nothing was changed.'}
        </p>
    )
}

export default MockAiJobBanners
