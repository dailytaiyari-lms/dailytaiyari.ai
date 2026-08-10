import { motion } from 'framer-motion'
import { AlertTriangle, Check, Loader2, ShieldCheck } from 'lucide-react'

/* ===========================================================================
 * ConfirmApply — the last gate before anything is written.
 *
 * It spells out exactly what will be created or changed, in plain counts, so
 * "Save to course" is never a leap of faith. The backend independently refuses
 * to write without the confirmation this dialog sends.
 * ========================================================================= */

const line = (count, singular, plural) =>
    count ? `${count} ${count === 1 ? singular : plural}` : null

const describe = (job, selection, isNotebook) => {
    const draft = job?.draft || {}
    const items = []

    if (isNotebook) {
        const cells = (draft.cells || []).length
        const tests = (draft.tests || []).length
        items.push(
            `the notebook “${draft.title || 'Untitled notebook'}”`,
            line(cells, 'cell', 'cells'),
            tests ? `${line(tests, 'autograder test', 'autograder tests')} (graded)` : null,
        )
        return items.filter(Boolean)
    }

    if (job?.kind === 'outline') {
        if (!job.course) items.push(`a new course “${draft.course?.name}” (hidden until you publish it)`)
        items.push(
            line(selection.subjects.size, 'module', 'modules'),
            line(selection.chapters.size, 'chapter', 'chapters'),
            line(selection.topics.size, 'topic', 'topics'),
        )
    } else if (job?.kind === 'content') {
        const chosen = (draft.topics || []).filter((t) => selection.topics.has(String(t.topic_id)))
        const notes = chosen.filter((t) => t.note?.include).length
        const quizzes = chosen.filter((t) => t.quiz?.include).length
        const questions = chosen.reduce((sum, t) => sum + (t.quiz?.include ? (t.quiz.questions || []).length : 0), 0)
        const assignments = chosen.reduce((sum, t) => sum + (t.assignments || []).length, 0)
        const problems = chosen.reduce((sum, t) => sum + (t.coding_problems || []).length, 0)
        const cases = chosen.reduce(
            (sum, t) => sum + (t.coding_problems || []).reduce((n, p) => n + (p.test_cases || []).length, 0),
            0,
        )
        items.push(
            line(notes, 'set of reading notes', 'sets of reading notes'),
            line(quizzes, 'quiz', 'quizzes'),
            line(questions, 'question', 'questions'),
            line(assignments, 'assignment', 'assignments'),
            line(problems, 'coding problem', 'coding problems'),
            line(cases, 'test case', 'test cases'),
        )
    } else if (job?.kind === 'meta') {
        items.push(line(selection.fields.size, 'course field', 'course fields'))
    }

    return items.filter(Boolean)
}

const ConfirmApply = ({ job, selection, saving, onCancel, onConfirm, isNotebook = false }) => {
    const items = describe(job, selection, isNotebook)
    const publishing = !isNotebook && !!job?.options?.publish_immediately
    const overwriting = !isNotebook && job?.kind === 'content'
    const adding = (job?.options?.mode || 'replace') === 'add'

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm">
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
                            Save this to your course?
                        </h3>
                        <p className="mt-1 text-sm text-surface-500">
                            This is the only step that changes your course. Everything before it was a draft.
                        </p>
                    </div>
                </div>

                <div className="mt-5 rounded-lg bg-surface-50 p-4 dark:bg-surface-800/60">
                    <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-surface-500">
                        What will be created
                    </p>
                    {items.length ? (
                        <ul className="space-y-1.5">
                            {items.map((item) => (
                                <li key={item} className="flex items-start gap-2 text-sm text-surface-700 dark:text-surface-200">
                                    <Check className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" />
                                    {item}
                                </li>
                            ))}
                        </ul>
                    ) : (
                        <p className="text-sm text-surface-500">Nothing is selected.</p>
                    )}
                </div>

                {(publishing || overwriting) && (
                    <div className="mt-3 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800 dark:border-amber-800/40 dark:bg-amber-900/20 dark:text-amber-200">
                        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                        <div className="space-y-1">
                            {publishing && <p>This material will be published to learners immediately.</p>}
                            {overwriting && (adding ? (
                                <p>
                                    This is added alongside the topic&rsquo;s existing material — nothing
                                    already there is changed or removed.
                                </p>
                            ) : (
                                <p>
                                    Existing reading notes on these topics will be replaced, and an
                                    assignment or coding problem with the same title will be updated in
                                    place. Anything learners have already attempted or submitted to is
                                    never overwritten — a new copy is added alongside it instead.
                                </p>
                            ))}
                        </div>
                    </div>
                )}

                <div className="mt-6 flex justify-end gap-2">
                    <button
                        type="button"
                        onClick={onCancel}
                        disabled={saving}
                        className="rounded-lg px-4 py-2 text-sm font-medium text-surface-600 hover:bg-surface-100 dark:text-surface-300 dark:hover:bg-surface-700"
                    >
                        Keep reviewing
                    </button>
                    <button
                        type="button"
                        onClick={onConfirm}
                        disabled={saving || !items.length}
                        className="flex items-center gap-2 rounded-lg bg-primary-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-primary-700 disabled:opacity-50"
                    >
                        {saving && <Loader2 className="h-4 w-4 animate-spin" />}
                        {saving ? 'Saving…' : 'Yes, save to course'}
                    </button>
                </div>
            </motion.div>
        </div>
    )
}

export default ConfirmApply
