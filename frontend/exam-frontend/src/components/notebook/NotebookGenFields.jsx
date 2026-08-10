/* ===========================================================================
 * NotebookGenFields — the composer inputs for an AI-generated notebook.
 *
 * Shared by the notebook builder's generator modal and the topic studio so the
 * same knobs (difficulty, graded, how many cells to solve, which model) mean
 * the same thing wherever a notebook is generated from.
 * ========================================================================= */

export const defaultNotebookGenForm = {
    prompt: '',
    difficulty: 'easy',
    graded: true,
    answer_cells: 2,
    provider: '',
    model: '',
}

const selectClass =
    'w-full rounded-lg border border-surface-300 bg-transparent px-2 py-1.5 text-sm dark:border-surface-600'

/** The model picker, flattened across every configured provider. */
export const ModelPicker = ({ form, setForm, providers = [] }) => {
    if (!providers.length) return null
    return (
        <div>
            <label className="mb-1 block text-xs font-medium text-surface-500">Model</label>
            <select
                value={form.provider ? `${form.provider}::${form.model}` : ''}
                onChange={(e) => {
                    const [provider, model] = e.target.value.split('::')
                    setForm((f) => ({ ...f, provider: provider || '', model: model || '' }))
                }}
                className={selectClass}
            >
                <option value="">Default model</option>
                {providers.flatMap((p) => (p.models || []).map((m) => (
                    <option key={`${p.provider}::${m}`} value={`${p.provider}::${m}`}>
                        {p.provider_label || p.provider}: {m}
                    </option>
                )))}
            </select>
        </div>
    )
}

/** Difficulty / graded / answer-cell count — the shape of the notebook. */
export const NotebookShapeFields = ({ form, setForm }) => (
    <>
        <div>
            <label className="mb-1 block text-xs font-medium text-surface-500">Difficulty</label>
            <select
                value={form.difficulty}
                onChange={(e) => setForm((f) => ({ ...f, difficulty: e.target.value }))}
                className={selectClass}
            >
                <option value="easy">Easy</option>
                <option value="medium">Medium</option>
                <option value="hard">Hard</option>
            </select>
        </div>
        <div>
            <label className="mb-1 block text-xs font-medium text-surface-500">Graded</label>
            <select
                value={form.graded ? 'yes' : 'no'}
                onChange={(e) => setForm((f) => ({ ...f, graded: e.target.value === 'yes' }))}
                className={selectClass}
            >
                <option value="yes">Yes — tasks + autograded tests</option>
                <option value="no">No — exploratory only</option>
            </select>
        </div>
        <div>
            <label className="mb-1 block text-xs font-medium text-surface-500">Cells to solve</label>
            <input
                type="number"
                min={0}
                max={10}
                disabled={!form.graded}
                value={form.answer_cells}
                onChange={(e) => setForm((f) => ({ ...f, answer_cells: e.target.value }))}
                className={`${selectClass} disabled:opacity-50`}
            />
        </div>
    </>
)

/** The full composer, used by the standalone generator modal. */
const NotebookGenFields = ({ form, setForm, providers = [] }) => (
    <>
        <div>
            <label className="mb-1 block text-xs font-medium text-surface-500">
                What should this notebook teach or ask?
            </label>
            <textarea
                rows={4}
                value={form.prompt}
                onChange={(e) => setForm((f) => ({ ...f, prompt: e.target.value }))}
                placeholder="e.g. A hands-on notebook on training and evaluating a linear regression model with scikit-learn, with graded tasks."
                className="w-full rounded-lg border border-surface-300 bg-transparent px-3 py-2 text-sm dark:border-surface-600"
            />
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <NotebookShapeFields form={form} setForm={setForm} />
            <ModelPicker form={form} setForm={setForm} providers={providers} />
        </div>
    </>
)

export default NotebookGenFields
