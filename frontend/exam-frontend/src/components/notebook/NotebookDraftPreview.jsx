import { BookOpen, FileCode2, FlaskConical } from 'lucide-react'

/* ===========================================================================
 * NotebookDraftPreview — read-only render of an AI notebook draft.
 *
 * Shared by the notebook builder's generator modal and the topic studio, so a
 * generated notebook is reviewed exactly the same way wherever it was asked
 * for. Nothing here writes; applying the draft is always a separate call.
 * ========================================================================= */

const ROLE_BADGE = {
    readonly: 'bg-surface-100 text-surface-600 dark:bg-surface-700 dark:text-surface-300',
    editable: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
    answer: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
}

const NotebookDraftPreview = ({ draft = {}, compact = false }) => {
    const cells = draft.cells || []
    const tests = draft.tests || []
    const answerCells = cells.filter((c) => c.role === 'answer').length
    const points = tests.reduce((sum, t) => sum + (Number(t.points) || 0), 0)

    return (
        <div className="space-y-4">
            <div>
                <h3 className="text-lg font-semibold text-surface-900 dark:text-surface-100">
                    {draft.title || 'Untitled notebook'}
                </h3>
                {draft.description && (
                    <div
                        className="prose prose-sm mt-1 max-w-none text-surface-600 dark:prose-invert dark:text-surface-300"
                        dangerouslySetInnerHTML={{ __html: draft.description }}
                    />
                )}
                <div className="mt-2 flex flex-wrap gap-2 text-xs">
                    <span className="rounded-full bg-surface-100 px-2 py-0.5 capitalize dark:bg-surface-800">
                        {draft.difficulty || 'easy'}
                    </span>
                    <span className="inline-flex items-center gap-1 rounded-full bg-surface-100 px-2 py-0.5 dark:bg-surface-800">
                        <FileCode2 className="h-3 w-3" /> {cells.length} cells
                    </span>
                    <span className="inline-flex items-center gap-1 rounded-full bg-surface-100 px-2 py-0.5 dark:bg-surface-800">
                        <BookOpen className="h-3 w-3" /> {answerCells} to solve
                    </span>
                    <span className="inline-flex items-center gap-1 rounded-full bg-surface-100 px-2 py-0.5 dark:bg-surface-800">
                        <FlaskConical className="h-3 w-3" /> {tests.length} tests · {points} pts
                    </span>
                    {(draft.packages || []).map((pkg) => (
                        <span key={pkg} className="rounded-full bg-surface-100 px-2 py-0.5 dark:bg-surface-800">
                            {pkg}
                        </span>
                    ))}
                </div>
            </div>

            <div
                className={`space-y-2 overflow-y-auto rounded-lg border border-surface-200 p-2 dark:border-surface-700 ${
                    compact ? 'max-h-56' : 'max-h-72'
                }`}
            >
                {cells.map((cell, index) => (
                    <div key={index} className="rounded-md bg-surface-50 p-2 dark:bg-surface-800/60">
                        <div className="mb-1 flex items-center gap-2 text-[10px]">
                            <span className={`rounded px-1.5 py-0.5 font-medium ${ROLE_BADGE[cell.role] || ROLE_BADGE.readonly}`}>
                                {cell.role}
                            </span>
                            <span className="uppercase text-surface-400">{cell.cell_type}</span>
                            {cell.grade_id && <span className="text-amber-600">#{cell.grade_id}</span>}
                            {cell.points ? <span className="text-surface-400">{cell.points} pt</span> : null}
                        </div>
                        <pre className="whitespace-pre-wrap break-words text-[11px] leading-snug text-surface-700 dark:text-surface-200">
                            {(cell.source || '').slice(0, 600)}
                        </pre>
                    </div>
                ))}
                {!cells.length && (
                    <p className="p-2 text-xs text-surface-400">This draft has no cells.</p>
                )}
            </div>

            {tests.length > 0 && (
                <div className="space-y-1">
                    <p className="text-xs font-semibold uppercase tracking-wide text-surface-500">
                        Autograder tests
                    </p>
                    {tests.map((test, index) => (
                        <div
                            key={index}
                            className="flex flex-wrap items-center gap-2 rounded-md bg-surface-50 px-2 py-1 text-xs dark:bg-surface-800/60"
                        >
                            <FlaskConical className="h-3 w-3 shrink-0 text-surface-400" />
                            <span className="font-medium text-surface-800 dark:text-surface-200">{test.name}</span>
                            {test.grade_id && <span className="text-amber-600">#{test.grade_id}</span>}
                            <span className="ml-auto text-surface-500">{test.points} pt</span>
                            <span
                                className={`rounded px-1.5 py-0.5 ${
                                    test.is_hidden
                                        ? 'bg-surface-200 text-surface-600 dark:bg-surface-700 dark:text-surface-300'
                                        : 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300'
                                }`}
                            >
                                {test.is_hidden ? 'hidden' : 'visible'}
                            </span>
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}

export default NotebookDraftPreview
