import { Check, Loader2, Mic, MicOff, Square } from 'lucide-react'

/* ===========================================================================
 * Small presentational pieces shared across the AI Course Studio.
 * ========================================================================= */

export const KIND_META = {
    outline: {
        label: 'Course outline',
        blurb: 'Modules, chapters and topics — the skeleton of a course.',
        placeholder:
            'e.g. A 10-week Python course for absolute beginners heading into data analytics. '
            + 'Cover the basics, then pandas and simple charts. Practical, lots of small exercises.',
    },
    content: {
        label: 'Study material',
        blurb: 'Notes, quizzes, assignments and coding problems for topics you pick.',
        placeholder:
            'Optional: anything specific you want emphasised — worked examples, exam traps, '
            + 'a particular syllabus, the tone to use.',
    },
    meta: {
        label: 'Course description',
        blurb: 'Landing-page copy: subtitle, description and highlights.',
        placeholder:
            'Optional: who the course is for, what makes it different, the outcome a learner '
            + 'should expect.',
    },
}

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
    applied: 'Saved to the course',
    failed: 'Failed',
    discarded: 'Discarded',
    generating: 'Generating',
    pending: 'Queued',
}

export const Pill = ({ children, tone = 'surface' }) => {
    const tones = {
        surface: 'bg-surface-100 text-surface-600 dark:bg-surface-700/60 dark:text-surface-300',
        primary: 'bg-primary-100 text-primary-700 dark:bg-primary-900/30 dark:text-primary-300',
        emerald: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300',
        amber: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300',
    }
    return (
        <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${tones[tone] || tones.surface}`}>
            {children}
        </span>
    )
}

export const Field = ({ label, hint, children }) => (
    <label className="block">
        <span className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-surface-500 dark:text-surface-400">
            {label}
        </span>
        {children}
        {hint && <span className="mt-1 block text-xs text-surface-400">{hint}</span>}
    </label>
)

export const inputClass =
    'w-full rounded-lg border border-surface-200 bg-white px-3 py-2 text-sm text-surface-900 '
    + 'outline-none transition focus:border-primary-500 focus:ring-2 focus:ring-primary-500/20 '
    + 'dark:border-surface-700 dark:bg-surface-800 dark:text-surface-100'

export const AssignmentShapeFields = ({ form, setForm, maxAssignments = 5 }) => (
    <div className="space-y-3 rounded-lg border border-surface-200 p-3 dark:border-surface-700">
        <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-surface-500">
                Shape the assignment
            </p>
            <p className="mt-1 text-xs text-surface-400">
                These choices override any default AI pattern. Describe the exact task if you already know it.
            </p>
        </div>
        <div className="grid gap-2 sm:grid-cols-2">
            <Field label="Assignments per topic">
                <input
                    type="number"
                    min={1}
                    max={maxAssignments}
                    className={inputClass}
                    value={form.assignments_per_topic ?? 1}
                    onChange={(e) => setForm((current) => ({
                        ...current,
                        assignments_per_topic: Number(e.target.value),
                    }))}
                />
            </Field>
            <Field label="Difficulty">
                <select
                    className={inputClass}
                    value={form.assignment_difficulty || 'easy'}
                    onChange={(e) => setForm((current) => ({
                        ...current,
                        assignment_difficulty: e.target.value,
                    }))}
                >
                    <option value="very easy">Very easy — young learners</option>
                    <option value="easy">Easy — simple classroom task</option>
                    <option value="medium">Medium</option>
                    <option value="challenging">Challenging</option>
                </select>
            </Field>
        </div>
        <Field
            label="Type or format"
            hint="Examples: algorithm and flowchart, drawing, worksheet, oral activity, short answer."
        >
            <input
                className={inputClass}
                value={form.assignment_type || ''}
                onChange={(e) => setForm((current) => ({
                    ...current,
                    assignment_type: e.target.value,
                }))}
                placeholder="e.g. Algorithm and flowchart — no code"
            />
        </Field>
        <Field
            label="Exact task or requirements"
            hint="The AI must follow this and will not add harder requirements."
        >
            <textarea
                className={`${inputClass} min-h-[6rem] resize-y`}
                value={form.assignment_instructions || ''}
                onChange={(e) => setForm((current) => ({
                    ...current,
                    assignment_instructions: e.target.value,
                }))}
                placeholder={'e.g. Ask students to write simple steps for calculating the average of 3 marks, assign a grade, and draw a flowchart. Do not write Python code.'}
            />
        </Field>
    </div>
)

/** A checkbox that reads as a row, used everywhere in the review tree. */
export const CheckRow = ({ checked, onChange, disabled, children, className = '' }) => (
    <label
        className={`flex cursor-pointer items-start gap-2.5 ${disabled ? 'cursor-not-allowed opacity-50' : ''} ${className}`}
    >
        <span
            className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border transition ${
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
        <span className="min-w-0 flex-1">{children}</span>
    </label>
)

/** Mic button + live transcript indicator for the prompt box. */
export const MicButton = ({ voice }) => {
    if (!voice.supported) return null
    const busy = voice.transcribing
    return (
        <button
            type="button"
            onClick={voice.toggle}
            disabled={busy}
            title={
                voice.listening
                    ? 'Stop dictating'
                    : voice.mode === 'recording'
                        ? 'Record your request (transcribed by your AI provider)'
                        : 'Dictate your request'
            }
            className={`flex h-9 w-9 items-center justify-center rounded-full transition ${
                voice.listening
                    ? 'bg-rose-500 text-white shadow-lg shadow-rose-500/30'
                    : 'bg-surface-100 text-surface-500 hover:bg-surface-200 hover:text-surface-700 dark:bg-surface-700 dark:text-surface-300 dark:hover:bg-surface-600'
            }`}
        >
            {busy
                ? <Loader2 className="h-4 w-4 animate-spin" />
                : voice.listening
                    ? <Square className="h-3.5 w-3.5 fill-current" />
                    : voice.mode === 'none' ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
        </button>
    )
}

/** The pulsing "I'm listening" strip shown under the textarea. */
export const ListeningBar = ({ voice }) => {
    if (!voice.listening && !voice.transcribing && !voice.error) return null
    if (voice.error) {
        return <p className="mt-2 text-xs text-rose-500">{voice.error}</p>
    }
    return (
        <div className="mt-2 flex items-center gap-2 text-xs text-surface-500 dark:text-surface-400">
            <span className="flex gap-0.5">
                {[0, 1, 2].map((i) => (
                    <span
                        key={i}
                        className="h-3 w-0.5 animate-pulse rounded-full bg-rose-500"
                        style={{ animationDelay: `${i * 150}ms` }}
                    />
                ))}
            </span>
            {voice.transcribing
                ? 'Transcribing your recording…'
                : voice.interim
                    ? <span className="italic text-surface-400">{voice.interim}</span>
                    : voice.mode === 'recording'
                        ? 'Recording — press stop when you are done.'
                        : 'Listening…'}
        </div>
    )
}

export const summaryLine = (kind, summary) => {
    if (!summary) return ''
    if (kind === 'outline') {
        return `${summary.subjects || 0} modules · ${summary.chapters || 0} chapters · ${summary.topics || 0} topics`
    }
    if (kind === 'content') {
        const parts = [
            summary.notes ? `${summary.notes} notes` : null,
            summary.quizzes ? `${summary.quizzes} quizzes` : null,
            summary.questions ? `${summary.questions} questions` : null,
            summary.assignments ? `${summary.assignments} assignments` : null,
            summary.coding_problems ? `${summary.coding_problems} coding problems` : null,
        ].filter(Boolean)
        return parts.join(' · ') || 'nothing generated'
    }
    if (kind === 'meta') return `${summary.fields || 0} fields`
    return ''
}

export const formatCost = (value) => {
    const amount = Number(value || 0)
    if (!amount) return null
    return amount < 0.01 ? '<$0.01' : `$${amount.toFixed(2)}`
}
