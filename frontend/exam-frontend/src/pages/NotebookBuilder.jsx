import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  ArrowLeft, Save, Upload, Loader2, Plus, Trash2, Lock, Unlock, Target,
  Database, FlaskConical, Settings2, Users, CheckCircle2, XCircle,
  Notebook as NotebookIcon, Play, AlertTriangle,
} from 'lucide-react'
import { notebookAdminService as svc } from '../services/notebookService'
import NotebookEditor from '../components/notebook/NotebookEditor'
import Loading from '../components/common/Loading'
import {
  CELL_ROLES, ROLE_ANSWER, ROLE_LABELS, META_KEY,
  cellGradeId, cellRole, emptyNotebook, forApi, sourceToText, withKeys,
} from '../components/notebook/notebookDoc'

const TABS = [
  { id: 'notebook', label: 'Notebook', icon: NotebookIcon },
  { id: 'roles', label: 'Cell roles', icon: Target },
  { id: 'tests', label: 'Tests', icon: FlaskConical },
  { id: 'datasets', label: 'Datasets', icon: Database },
  { id: 'settings', label: 'Settings', icon: Settings2 },
]

const blankTest = (order) => ({
  _key: `t${Date.now()}${order}`,
  grade_id: '',
  name: '',
  source: '',
  points: 1,
  is_hidden: false,
  failure_hint: '',
  order,
})

const defaultSettings = {
  title: '',
  description: '',
  difficulty: 'easy',
  status: 'draft',
  max_marks: '',
  packages: [],
  time_limit_ms: 60000,
  memory_limit_mb: 512,
  estimated_time_minutes: 30,
  is_timed: false,
  due_at: '',
  allow_resubmission: true,
  max_attempts: '',
  provisional_grading: 'visible',
  show_results_to_students: true,
}

const toLocalInput = (iso) => {
  if (!iso) return ''
  const d = new Date(iso)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const NotebookBuilder = () => {
  const { courseId, notebookId } = useParams()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const editorRef = useRef(null)

  const isNew = notebookId === 'new'
  const topicId = params.get('topic') || ''
  const subjectId = params.get('subject') || ''

  const [tab, setTab] = useState('notebook')
  const [settings, setSettings] = useState(defaultSettings)
  const [doc, setDoc] = useState(() => withKeys(emptyNotebook()))
  const [tests, setTests] = useState([])
  const [saving, setSaving] = useState(false)
  const [importing, setImporting] = useState(false)
  const [testRun, setTestRun] = useState(null)
  const [running, setRunning] = useState(false)

  const { data: notebook, isLoading, refetch } = useQuery({
    queryKey: ['nb-admin-notebook', notebookId],
    queryFn: () => svc.get(notebookId),
    enabled: !isNew && !!notebookId,
  })

  const { data: datasets = [], refetch: refetchDatasets } = useQuery({
    queryKey: ['nb-admin-datasets', notebookId],
    queryFn: () => svc.datasets(notebookId),
    enabled: !isNew && !!notebookId,
  })

  useEffect(() => {
    if (!notebook) return
    setSettings({
      title: notebook.title || '',
      description: notebook.description || '',
      difficulty: notebook.difficulty || 'easy',
      status: notebook.status || 'draft',
      max_marks: notebook.max_marks ?? '',
      packages: notebook.packages || [],
      time_limit_ms: notebook.time_limit_ms ?? 60000,
      memory_limit_mb: notebook.memory_limit_mb ?? 512,
      estimated_time_minutes: notebook.estimated_time_minutes ?? 30,
      is_timed: !!notebook.is_timed,
      due_at: toLocalInput(notebook.due_at),
      allow_resubmission: !!notebook.allow_resubmission,
      max_attempts: notebook.max_attempts ?? '',
      provisional_grading: notebook.provisional_grading || 'visible',
      show_results_to_students: notebook.show_results_to_students !== false,
    })
    setDoc(withKeys(notebook.template_json))
    setTests((notebook.tests || []).map((t, i) => ({ ...t, _key: t.id || `t${i}`, order: i })))
  }, [notebook?.id, notebook?.updated_at])

  const set = (key, value) => setSettings((prev) => ({ ...prev, [key]: value }))

  const answerIds = useMemo(
    () => doc.cells.filter((c) => cellRole(c) === ROLE_ANSWER).map(cellGradeId).filter(Boolean),
    [doc.cells],
  )

  const setCellMeta = useCallback((index, patch) => {
    setDoc((prev) => {
      const cells = [...prev.cells]
      const cell = cells[index]
      const metadata = { ...(cell.metadata || {}) }
      metadata[META_KEY] = { ...(metadata[META_KEY] || {}), ...patch }
      cells[index] = { ...cell, metadata }
      return { ...prev, cells }
    })
  }, [])

  const handleImport = async (event) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    setImporting(true)
    try {
      const data = await svc.importIpynb(file)
      setDoc(withKeys(data.notebook_json || data.template_json))
      if (data.packages?.length) set('packages', data.packages)
      toast.success('Notebook imported. Now mark the answer cells.')
      setTab('roles')
    } catch (err) {
      toast.error(err.response?.data?.error || 'Could not import that file.')
    } finally {
      setImporting(false)
    }
  }

  const buildPayload = () => {
    const template = forApi(editorRef.current?.getDocument() || doc, { includeOutputs: false })
    return {
      course: courseId,
      ...(subjectId ? { subject: subjectId } : {}),
      ...(topicId ? { topic: topicId } : {}),
      title: settings.title.trim(),
      description: settings.description,
      difficulty: settings.difficulty,
      status: settings.status,
      max_marks: settings.max_marks === '' ? null : Number(settings.max_marks),
      packages: settings.packages,
      time_limit_ms: Number(settings.time_limit_ms) || 60000,
      memory_limit_mb: Number(settings.memory_limit_mb) || 512,
      estimated_time_minutes: Number(settings.estimated_time_minutes) || 0,
      is_timed: settings.is_timed,
      due_at: settings.is_timed && settings.due_at
        ? new Date(settings.due_at).toISOString()
        : null,
      allow_resubmission: settings.allow_resubmission,
      max_attempts: settings.max_attempts === '' ? null : Number(settings.max_attempts),
      provisional_grading: settings.provisional_grading,
      show_results_to_students: settings.show_results_to_students,
      template_json: template,
      tests: tests.map((t, i) => ({
        ...(t.id ? { id: t.id } : {}),
        grade_id: t.grade_id || '',
        name: t.name || `Check ${i + 1}`,
        source: t.source || '',
        points: Number(t.points) || 1,
        is_hidden: !!t.is_hidden,
        failure_hint: t.failure_hint || '',
        order: i,
      })),
    }
  }

  const handleSave = async () => {
    if (!settings.title.trim()) {
      setTab('settings')
      return toast.error('Give the notebook a title.')
    }
    if (!isNew && !tests.length) {
      toast('Heads up: this notebook has no tests, so submissions will score 0.')
    }
    setSaving(true)
    try {
      const payload = buildPayload()
      const saved = isNew ? await svc.create(payload) : await svc.update(notebookId, payload)
      toast.success(isNew ? 'Notebook created.' : 'Saved.')
      if (isNew) {
        navigate(
          `/courses/${courseId}/manage/notebooks/${saved.id}/edit?topic=${topicId}&subject=${subjectId}`,
          { replace: true },
        )
      } else {
        refetch()
      }
    } catch (err) {
      const data = err.response?.data
      toast.error(
        data?.error
        || (typeof data === 'object' ? Object.entries(data).map(([k, v]) => `${k}: ${v}`).join('; ') : null)
        || 'Could not save.',
      )
    } finally {
      setSaving(false)
    }
  }

  // Run the template + tests against the *reference* solution the author has
  // typed into the answer cells, so they can confirm the tests actually pass.
  const handleTestRun = async () => {
    setRunning(true)
    setTestRun(null)
    try {
      const results = await editorRef.current.executeForGrading(
        tests.filter((t) => t.source).map((t, i) => ({
          id: t.id || t._key || String(i),
          name: t.name || `Check ${i + 1}`,
          source: t.source,
        })),
      )
      setTestRun(results)
      const failed = results.filter((r) => !r.passed).length
      if (failed) toast.error(`${failed} test${failed === 1 ? '' : 's'} failed against your solution.`)
      else toast.success('All tests pass against your solution.')
    } catch (err) {
      toast.error(err.message || 'Could not run the tests.')
    } finally {
      setRunning(false)
    }
  }

  const handleUploadDataset = async (event) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file || isNew) return
    try {
      await svc.uploadDataset({ notebook: notebookId, filename: file.name, file })
      refetchDatasets()
      toast.success(`${file.name} uploaded.`)
    } catch (err) {
      toast.error(err.response?.data?.filename?.[0] || 'Upload failed.')
    }
  }

  if (!isNew && isLoading) return <Loading fullScreen />

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2">
        <button
          onClick={() => navigate(`/courses/${courseId}/manage`)}
          className="flex items-center gap-1 text-sm text-surface-500 hover:text-primary-600"
        >
          <ArrowLeft size={16} /> Course Manager
        </button>
        <span className="text-surface-400">/</span>
        <span className="text-sm text-surface-600 dark:text-surface-300">
          {isNew ? 'New notebook' : settings.title || 'Notebook'}
        </span>

        <div className="ml-auto flex items-center gap-2">
          {!isNew && (
            <button
              onClick={() => navigate(`/courses/${courseId}/manage/notebooks/${notebookId}`)}
              className="btn-secondary text-xs px-3 py-1.5"
            >
              <Users className="w-3.5 h-3.5" /> Submissions
            </button>
          )}
          <button onClick={handleSave} disabled={saving} className="btn-primary text-xs px-3 py-1.5">
            {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
            Save
          </button>
        </div>
      </div>

      <div className="flex flex-wrap gap-1 border-b border-surface-200 dark:border-surface-700">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`inline-flex items-center gap-1.5 px-3 py-2 text-sm font-medium border-b-2 -mb-px ${
              tab === t.id
                ? 'border-primary-600 text-primary-600'
                : 'border-transparent text-surface-500 hover:text-surface-700 dark:hover:text-surface-200'
            }`}
          >
            <t.icon className="w-4 h-4" /> {t.label}
            {t.id === 'tests' && tests.length > 0 && (
              <span className="rounded bg-surface-100 dark:bg-surface-800 px-1.5 text-[10px]">
                {tests.length}
              </span>
            )}
          </button>
        ))}
      </div>

      {tab === 'notebook' && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <label className="btn-secondary text-xs px-3 py-1.5 cursor-pointer">
              {importing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Upload className="w-3.5 h-3.5" />}
              Import .ipynb
              <input type="file" accept=".ipynb" hidden onChange={handleImport} />
            </label>
            <button
              onClick={handleTestRun}
              disabled={running || !tests.some((t) => t.source)}
              className="btn-secondary text-xs px-3 py-1.5 disabled:opacity-50"
              title="Run your tests against the solution you typed in the answer cells"
            >
              {running ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
              Validate tests
            </button>
            <p className="text-xs text-surface-500">
              Write the notebook here, then mark which cells students answer under
              <strong> Cell roles</strong>.
            </p>
          </div>

          {testRun && (
            <div className="card p-4 space-y-2">
              <h3 className="text-sm font-semibold text-surface-800 dark:text-surface-100">
                Validation against your solution
              </h3>
              {testRun.map((r, i) => (
                <div key={i} className="flex items-start gap-2 text-sm">
                  {r.passed
                    ? <CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0 text-emerald-500" />
                    : <XCircle className="w-4 h-4 mt-0.5 shrink-0 text-red-500" />}
                  <div className="min-w-0">
                    <span className="text-surface-700 dark:text-surface-200">{r.name}</span>
                    {r.error && !r.passed && (
                      <pre className="mt-0.5 font-mono text-[11px] text-red-600 whitespace-pre-wrap">
                        {r.error}
                      </pre>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          <NotebookEditor
            ref={editorRef}
            document={doc}
            datasets={datasets}
            packages={settings.packages}
            onChange={setDoc}
            canEditStructure
          />
        </div>
      )}

      {tab === 'roles' && (
        <div className="space-y-2">
          <div className="card p-4 text-xs text-surface-500 space-y-1">
            <p><strong>Locked</strong> — students can read but not edit (setup, imports, instructions).</p>
            <p><strong>Scratch</strong> — students can edit; not graded.</p>
            <p><strong>Graded answer</strong> — students edit; give it a <em>grade id</em> so tests can target it and so their work survives reordering.</p>
          </div>
          {doc.cells.map((cell, index) => {
            const role = cellRole(cell)
            const preview = sourceToText(cell.source).split('\n').slice(0, 2).join('\n')
            return (
              <div key={cell.__key || index} className="card p-3">
                <div className="flex flex-wrap items-start gap-3">
                  <span className="mt-1 shrink-0 rounded bg-surface-100 dark:bg-surface-800 px-1.5 py-0.5 font-mono text-[11px] text-surface-500">
                    {index + 1} · {cell.cell_type}
                  </span>
                  <pre className="min-w-0 flex-1 overflow-hidden font-mono text-xs text-surface-600 dark:text-surface-300 whitespace-pre-wrap">
                    {preview || <span className="italic text-surface-400">empty</span>}
                  </pre>
                  <select
                    value={role}
                    onChange={(e) => setCellMeta(index, { role: e.target.value })}
                    className="input text-xs py-1 w-40 shrink-0"
                  >
                    {CELL_ROLES.map((r) => (
                      <option key={r} value={r}>{ROLE_LABELS[r] || r}</option>
                    ))}
                  </select>
                  {role === ROLE_ANSWER && (
                    <input
                      value={cellGradeId(cell)}
                      onChange={(e) => setCellMeta(index, { grade_id: e.target.value })}
                      placeholder="grade id e.g. q1"
                      className="input text-xs py-1 w-36 shrink-0 font-mono"
                    />
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {tab === 'tests' && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-xs text-surface-500">
              Each test is a snippet of Python run <em>after</em> the student&apos;s notebook, in
              the same namespace. Raise <code>AssertionError</code> to fail.
            </p>
            <button
              onClick={() => setTests((prev) => [...prev, blankTest(prev.length)])}
              className="btn-primary text-xs px-3 py-1.5"
            >
              <Plus className="w-3.5 h-3.5" /> Add test
            </button>
          </div>

          {tests.length === 0 && (
            <div className="card p-8 text-center text-sm text-surface-500">
              No tests yet — submissions would score 0.
            </div>
          )}

          {tests.map((t, i) => (
            <div key={t._key || t.id} className="card p-4 space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <input
                  value={t.name}
                  onChange={(e) => setTests((p) => p.map((x, j) => j === i ? { ...x, name: e.target.value } : x))}
                  placeholder={`Check ${i + 1}`}
                  className="input text-sm flex-1 min-w-[12rem]"
                />
                <select
                  value={t.grade_id || ''}
                  onChange={(e) => setTests((p) => p.map((x, j) => j === i ? { ...x, grade_id: e.target.value } : x))}
                  className="input text-xs py-1.5 w-40"
                  title="Which answer cell this test grades"
                >
                  <option value="">(any cell)</option>
                  {answerIds.map((id) => <option key={id} value={id}>{id}</option>)}
                </select>
                <input
                  type="number"
                  min="1"
                  value={t.points}
                  onChange={(e) => setTests((p) => p.map((x, j) => j === i ? { ...x, points: e.target.value } : x))}
                  className="input text-xs py-1.5 w-20"
                  title="Points"
                />
                <button
                  onClick={() => setTests((p) => p.map((x, j) => j === i ? { ...x, is_hidden: !x.is_hidden } : x))}
                  className={`inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs font-medium ${
                    t.is_hidden
                      ? 'bg-surface-800 text-white dark:bg-surface-700'
                      : 'bg-surface-100 text-surface-500 dark:bg-surface-800'
                  }`}
                  title={t.is_hidden ? 'Hidden from students' : 'Visible to students'}
                >
                  {t.is_hidden ? <Lock className="w-3.5 h-3.5" /> : <Unlock className="w-3.5 h-3.5" />}
                  {t.is_hidden ? 'Hidden' : 'Visible'}
                </button>
                <button
                  onClick={() => setTests((p) => p.filter((_, j) => j !== i))}
                  className="p-1.5 rounded-lg text-surface-400 hover:bg-red-50 hover:text-red-600"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
              <textarea
                rows={5}
                value={t.source}
                onChange={(e) => setTests((p) => p.map((x, j) => j === i ? { ...x, source: e.target.value } : x))}
                placeholder={'assert round(accuracy, 2) >= 0.8, "Model accuracy is too low"'}
                className="input font-mono text-xs resize-y"
              />
              <input
                value={t.failure_hint || ''}
                onChange={(e) => setTests((p) => p.map((x, j) => j === i ? { ...x, failure_hint: e.target.value } : x))}
                placeholder="Hint shown to the student when this fails (optional)"
                className="input text-xs"
              />
            </div>
          ))}
        </div>
      )}

      {tab === 'datasets' && (
        <div className="space-y-3">
          {isNew ? (
            <div className="card p-6 flex items-center gap-2 text-sm text-surface-500">
              <AlertTriangle className="w-4 h-4 text-amber-500" />
              Save the notebook first, then attach datasets.
            </div>
          ) : (
            <>
              <div className="flex items-center justify-between">
                <p className="text-xs text-surface-500">
                  Files are placed next to the notebook, so students can
                  <code className="mx-1">pd.read_csv(&quot;data.csv&quot;)</code> directly.
                </p>
                <label className="btn-primary text-xs px-3 py-1.5 cursor-pointer">
                  <Upload className="w-3.5 h-3.5" /> Upload file
                  <input type="file" hidden onChange={handleUploadDataset} />
                </label>
              </div>
              {datasets.length === 0 ? (
                <div className="card p-8 text-center text-sm text-surface-500">
                  No datasets attached.
                </div>
              ) : datasets.map((d) => (
                <div key={d.id} className="card p-3 flex items-center gap-3">
                  <Database className="w-4 h-4 shrink-0 text-primary-500" />
                  <div className="min-w-0 flex-1">
                    <p className="font-mono text-sm text-surface-800 dark:text-surface-100 truncate">
                      {d.filename}
                    </p>
                    <p className="text-xs text-surface-500">
                      {Math.round((d.size_bytes || 0) / 1024)} KB
                      {d.description ? ` · ${d.description}` : ''}
                    </p>
                  </div>
                  <button
                    onClick={async () => {
                      if (!window.confirm(`Remove ${d.filename}?`)) return
                      await svc.deleteDataset(d.id)
                      refetchDatasets()
                    }}
                    className="p-1.5 rounded-lg text-surface-400 hover:bg-red-50 hover:text-red-600"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              ))}
            </>
          )}
        </div>
      )}

      {tab === 'settings' && (
        <div className="card p-5 space-y-4 max-w-3xl">
          <div>
            <label className="block text-xs font-semibold text-surface-500 mb-1">Title</label>
            <input
              className="input"
              value={settings.title}
              onChange={(e) => set('title', e.target.value)}
              placeholder="e.g. Linear regression on the housing dataset"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold text-surface-500 mb-1">
              Description (shown above the notebook)
            </label>
            <textarea
              rows={4}
              className="input resize-y"
              value={settings.description}
              onChange={(e) => set('description', e.target.value)}
            />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div>
              <label className="block text-xs font-semibold text-surface-500 mb-1">Difficulty</label>
              <select className="input" value={settings.difficulty} onChange={(e) => set('difficulty', e.target.value)}>
                <option value="easy">Easy</option>
                <option value="medium">Medium</option>
                <option value="hard">Hard</option>
              </select>
            </div>
            <div>
              <label className="block text-xs font-semibold text-surface-500 mb-1">Status</label>
              <select className="input" value={settings.status} onChange={(e) => set('status', e.target.value)}>
                <option value="draft">Draft</option>
                <option value="published">Published</option>
                <option value="archived">Archived</option>
              </select>
            </div>
            <div>
              <label className="block text-xs font-semibold text-surface-500 mb-1">Max marks</label>
              <input
                type="number" min="0" className="input"
                value={settings.max_marks}
                onChange={(e) => set('max_marks', e.target.value)}
                placeholder="optional"
              />
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div>
              <label className="block text-xs font-semibold text-surface-500 mb-1">
                Grading time limit (ms)
              </label>
              <input
                type="number" min="1000" step="1000" className="input"
                value={settings.time_limit_ms}
                onChange={(e) => set('time_limit_ms', e.target.value)}
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-surface-500 mb-1">Memory (MB)</label>
              <input
                type="number" min="128" step="64" className="input"
                value={settings.memory_limit_mb}
                onChange={(e) => set('memory_limit_mb', e.target.value)}
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-surface-500 mb-1">
                Estimated time (min)
              </label>
              <input
                type="number" min="0" className="input"
                value={settings.estimated_time_minutes}
                onChange={(e) => set('estimated_time_minutes', e.target.value)}
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-surface-500 mb-1">
              Extra Python packages
            </label>
            <input
              className="input font-mono text-sm"
              value={settings.packages.join(', ')}
              onChange={(e) => set(
                'packages',
                e.target.value.split(',').map((s) => s.trim()).filter(Boolean),
              )}
              placeholder="numpy, pandas, scikit-learn, matplotlib"
            />
            <p className="mt-1 text-[11px] text-surface-400">
              Only packages available both in the browser kernel and the grading
              image will load — numpy, pandas, scipy, scikit-learn, matplotlib,
              sympy, statsmodels, networkx, pillow.
            </p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold text-surface-500 mb-1">
                Attempts
              </label>
              <select
                className="input"
                value={settings.allow_resubmission ? 'many' : 'one'}
                onChange={(e) => set('allow_resubmission', e.target.value === 'many')}
              >
                <option value="one">Single attempt only</option>
                <option value="many">Allow resubmission</option>
              </select>
            </div>
            {settings.allow_resubmission && (
              <div>
                <label className="block text-xs font-semibold text-surface-500 mb-1">
                  Max attempts
                </label>
                <input
                  type="number" min="0" className="input"
                  value={settings.max_attempts}
                  onChange={(e) => set('max_attempts', e.target.value)}
                  placeholder="blank = unlimited"
                />
              </div>
            )}
          </div>

          <div>
            <label className="block text-xs font-semibold text-surface-500 mb-1">
              In-browser provisional score
            </label>
            <select
              className="input"
              value={settings.provisional_grading}
              onChange={(e) => set('provisional_grading', e.target.value)}
            >
              <option value="visible">Visible tests only (recommended)</option>
              <option value="none">Off — server grade only</option>
              <option value="all">All tests, including hidden</option>
            </select>
            <p className="mt-1 text-[11px] text-amber-600">
              {settings.provisional_grading === 'all'
                ? 'Warning: hidden test code is sent to the browser and students can read it.'
                : 'The authoritative grade always comes from the server.'}
            </p>
          </div>

          <label className="flex items-center gap-2 text-sm text-surface-700 dark:text-surface-200">
            <input
              type="checkbox"
              checked={settings.show_results_to_students}
              onChange={(e) => set('show_results_to_students', e.target.checked)}
            />
            Show the per-test breakdown to students
          </label>

          <label className="flex items-center gap-2 text-sm text-surface-700 dark:text-surface-200">
            <input
              type="checkbox"
              checked={settings.is_timed}
              onChange={(e) => set('is_timed', e.target.checked)}
            />
            Has a due date
          </label>
          {settings.is_timed && (
            <div>
              <label className="block text-xs font-semibold text-surface-500 mb-1">Due at</label>
              <input
                type="datetime-local"
                className="input"
                value={settings.due_at}
                onChange={(e) => set('due_at', e.target.value)}
              />
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default NotebookBuilder
