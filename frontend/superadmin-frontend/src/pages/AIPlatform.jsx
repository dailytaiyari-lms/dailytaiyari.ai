import { useEffect, useMemo, useState } from 'react'
import {
  Bot,
  Loader2,
  Plus,
  Trash2,
  Pencil,
  X,
  Zap,
  KeyRound,
  CheckCircle2,
  AlertTriangle,
  DollarSign,
  Building2,
} from 'lucide-react'
import toast from 'react-hot-toast'
import {
  fetchPlatformAI,
  createPlatformProvider,
  updatePlatformProvider,
  deletePlatformProvider,
  testPlatformProvider,
  createPlatformModel,
  updatePlatformModel,
  deletePlatformModel,
  fetchPlatformAIUsage,
} from '../services/superadminService'

const money = (n) =>
  `$${Number(n || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
const compact = (n) => Number(n || 0).toLocaleString()

const EMPTY_PROVIDER = {
  name: '',
  provider: 'openai',
  base_url: '',
  api_version: '2024-10-21',
  api_key: '',
  is_enabled: true,
  notes: '',
}

const EMPTY_MODEL = {
  model_name: '',
  label: '',
  description: '',
  input_cost_per_million: '0',
  output_cost_per_million: '0',
  max_output_tokens: 4000,
  is_enabled: true,
}

function Field({ label, hint, children }) {
  return (
    <label className="block">
      <span className="text-sm font-medium text-slate-700">{label}</span>
      {children}
      {hint ? <span className="mt-1 block text-xs text-slate-500">{hint}</span> : null}
    </label>
  )
}

const inputClass =
  'mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100'

function ProviderEditor({ initial, catalog, onClose, onSaved }) {
  const [form, setForm] = useState(() => ({
    ...EMPTY_PROVIDER,
    ...(initial || {}),
    api_key: '',
  }))
  const [saving, setSaving] = useState(false)
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }))

  const meta = useMemo(
    () => catalog.find((c) => c.id === form.provider) || {},
    [catalog, form.provider],
  )

  const submit = async () => {
    if (!form.name.trim()) return toast.error('Give this account a name')
    setSaving(true)
    const payload = {
      name: form.name.trim(),
      provider: form.provider,
      base_url: form.base_url.trim(),
      api_version: form.api_version,
      is_enabled: form.is_enabled,
      notes: form.notes,
    }
    // Sending an empty key on edit would wipe the stored one.
    if (form.api_key.trim() || !initial) payload.api_key = form.api_key.trim()

    try {
      const saved = initial?.id
        ? await updatePlatformProvider(initial.id, payload)
        : await createPlatformProvider(payload)
      toast.success(initial?.id ? 'Account updated' : 'Account added')
      onSaved(saved)
    } catch (err) {
      const data = err?.response?.data
      toast.error(data ? Object.values(data).flat()[0] : 'Could not save')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
      <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-2xl bg-white p-6 shadow-xl">
        <div className="mb-4 flex items-start justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">
              {initial?.id ? 'Edit AI account' : 'Add AI account'}
            </h2>
            <p className="text-sm text-slate-500">
              Credentials the platform pays for and lends to tenants.
            </p>
          </div>
          <button onClick={onClose} className="rounded-lg p-1 text-slate-400 hover:bg-slate-100">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="space-y-4">
          <Field label="Name" hint="How you'll recognise it, e.g. “OpenAI — production”.">
            <input
              className={inputClass}
              value={form.name}
              onChange={(e) => set('name', e.target.value)}
              placeholder="OpenAI — production"
            />
          </Field>

          <Field label="Provider">
            <select
              className={inputClass}
              value={form.provider}
              onChange={(e) => {
                set('provider', e.target.value)
                const next = catalog.find((c) => c.id === e.target.value)
                set('base_url', next?.default_base_url || '')
              }}
            >
              {catalog.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.label}
                </option>
              ))}
            </select>
          </Field>

          {meta.description ? (
            <p className="rounded-lg bg-slate-50 p-3 text-xs text-slate-600">{meta.description}</p>
          ) : null}

          <Field
            label={initial?.id ? 'API key (leave blank to keep current)' : 'API key'}
            hint={
              initial?.has_api_key
                ? `A key is stored (${initial.api_key_hint}). Type a new one only to replace it.`
                : meta.docs_url
                  ? `Get one at ${meta.docs_url}`
                  : ''
            }
          >
            <input
              className={inputClass}
              type="password"
              autoComplete="new-password"
              value={form.api_key}
              onChange={(e) => set('api_key', e.target.value)}
              placeholder={initial?.id ? '••••••••' : 'sk-…'}
            />
          </Field>

          {meta.requires_base_url || form.base_url ? (
            <Field label="Endpoint URL">
              <input
                className={inputClass}
                value={form.base_url}
                onChange={(e) => set('base_url', e.target.value)}
                placeholder="https://…"
              />
            </Field>
          ) : null}

          {meta.uses_api_version ? (
            <Field label="API version">
              <input
                className={inputClass}
                value={form.api_version}
                onChange={(e) => set('api_version', e.target.value)}
              />
            </Field>
          ) : null}

          <Field label="Notes" hint="Internal only — billing account, owner, renewal date…">
            <textarea
              className={inputClass}
              rows={2}
              value={form.notes}
              onChange={(e) => set('notes', e.target.value)}
            />
          </Field>

          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              checked={form.is_enabled}
              onChange={(e) => set('is_enabled', e.target.checked)}
              className="h-4 w-4 rounded border-slate-300"
            />
            Enabled — turning this off immediately stops every tenant using it
          </label>
        </div>

        <div className="mt-6 flex justify-end gap-2">
          <button onClick={onClose} className="rounded-lg px-4 py-2 text-sm text-slate-600 hover:bg-slate-100">
            Cancel
          </button>
          <button
            onClick={submit}
            disabled={saving}
            className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-60"
          >
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            Save
          </button>
        </div>
      </div>
    </div>
  )
}

function ModelEditor({ providerId, initial, onClose, onSaved }) {
  const [form, setForm] = useState(() => ({ ...EMPTY_MODEL, ...(initial || {}) }))
  const [saving, setSaving] = useState(false)
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }))

  const submit = async () => {
    if (!form.model_name.trim()) return toast.error('Model name is required')
    setSaving(true)
    const payload = {
      model_name: form.model_name.trim(),
      label: form.label.trim(),
      description: form.description.trim(),
      input_cost_per_million: form.input_cost_per_million || 0,
      output_cost_per_million: form.output_cost_per_million || 0,
      max_output_tokens: Number(form.max_output_tokens) || 4000,
      is_enabled: form.is_enabled,
    }
    try {
      const saved = initial?.id
        ? await updatePlatformModel(initial.id, payload)
        : await createPlatformModel(providerId, payload)
      toast.success('Saved')
      onSaved(saved)
    } catch (err) {
      const data = err?.response?.data
      toast.error(data ? Object.values(data).flat()[0] : 'Could not save')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
      <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-2xl bg-white p-6 shadow-xl">
        <div className="mb-4 flex items-start justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">
              {initial?.id ? 'Edit model' : 'Add model'}
            </h2>
            <p className="text-sm text-slate-500">
              Prices drive tenant cost reports and spend ceilings.
            </p>
          </div>
          <button onClick={onClose} className="rounded-lg p-1 text-slate-400 hover:bg-slate-100">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="space-y-4">
          <Field label="Model name" hint="Exactly as the vendor names it — sent on the wire.">
            <input
              className={inputClass}
              value={form.model_name}
              onChange={(e) => set('model_name', e.target.value)}
              placeholder="gpt-4o-mini"
            />
          </Field>

          <Field label="Label" hint="What a tenant admin sees instead of the raw name.">
            <input
              className={inputClass}
              value={form.label}
              onChange={(e) => set('label', e.target.value)}
              placeholder="Fast — good for most questions"
            />
          </Field>

          <Field label="Description">
            <input
              className={inputClass}
              value={form.description}
              onChange={(e) => set('description', e.target.value)}
              placeholder="Best balance of speed and quality"
            />
          </Field>

          <div className="grid grid-cols-2 gap-3">
            <Field label="Input $ / 1M tokens">
              <input
                className={inputClass}
                type="number"
                step="0.0001"
                value={form.input_cost_per_million}
                onChange={(e) => set('input_cost_per_million', e.target.value)}
              />
            </Field>
            <Field label="Output $ / 1M tokens">
              <input
                className={inputClass}
                type="number"
                step="0.0001"
                value={form.output_cost_per_million}
                onChange={(e) => set('output_cost_per_million', e.target.value)}
              />
            </Field>
          </div>

          <Field label="Max output tokens">
            <input
              className={inputClass}
              type="number"
              value={form.max_output_tokens}
              onChange={(e) => set('max_output_tokens', e.target.value)}
            />
          </Field>

          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              checked={form.is_enabled}
              onChange={(e) => set('is_enabled', e.target.checked)}
              className="h-4 w-4 rounded border-slate-300"
            />
            Available to tenants
          </label>
        </div>

        <div className="mt-6 flex justify-end gap-2">
          <button onClick={onClose} className="rounded-lg px-4 py-2 text-sm text-slate-600 hover:bg-slate-100">
            Cancel
          </button>
          <button
            onClick={submit}
            disabled={saving}
            className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-60"
          >
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            Save
          </button>
        </div>
      </div>
    </div>
  )
}

function ProviderCard({ provider, onChanged }) {
  const [editing, setEditing] = useState(false)
  const [modelEditor, setModelEditor] = useState(null)
  const [testing, setTesting] = useState(false)

  const runTest = async () => {
    setTesting(true)
    try {
      const result = await testPlatformProvider(provider.id)
      result.ok ? toast.success(result.message) : toast.error(result.message)
      onChanged()
    } catch (err) {
      toast.error(err?.response?.data?.detail || 'Test failed')
    } finally {
      setTesting(false)
    }
  }

  const removeProvider = async () => {
    if (!window.confirm(`Delete “${provider.name}”? Tenants using it lose AI immediately.`)) return
    await deletePlatformProvider(provider.id)
    toast.success('Account deleted')
    onChanged()
  }

  const removeModel = async (model) => {
    if (!window.confirm(`Remove ${model.model_name}?`)) return
    await deletePlatformModel(model.id)
    toast.success('Model removed')
    onChanged()
  }

  return (
    <div className="rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 p-5">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="truncate text-base font-semibold text-slate-900">{provider.name}</h3>
            {provider.is_enabled ? (
              <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700">
                Enabled
              </span>
            ) : (
              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
                Disabled
              </span>
            )}
            {!provider.is_configured ? (
              <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700">
                <AlertTriangle className="h-3 w-3" /> Needs a key
              </span>
            ) : null}
          </div>
          <p className="mt-1 text-sm text-slate-500">
            {provider.provider_label}
            {provider.has_api_key ? ` · key ${provider.api_key_hint}` : ''}
          </p>
          {provider.last_test_ok === false && provider.last_test_error ? (
            <p className="mt-1 text-xs text-rose-600">{provider.last_test_error}</p>
          ) : null}
          {provider.last_test_ok ? (
            <p className="mt-1 inline-flex items-center gap-1 text-xs text-emerald-600">
              <CheckCircle2 className="h-3 w-3" /> Last test passed
            </p>
          ) : null}
        </div>

        <div className="flex shrink-0 items-center gap-1">
          <button
            onClick={runTest}
            disabled={testing}
            className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-60"
          >
            {testing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Zap className="h-4 w-4" />}
            Test
          </button>
          <button
            onClick={() => setEditing(true)}
            className="rounded-lg p-2 text-slate-500 hover:bg-slate-100"
          >
            <Pencil className="h-4 w-4" />
          </button>
          <button
            onClick={removeProvider}
            className="rounded-lg p-2 text-rose-500 hover:bg-rose-50"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>

      <div className="p-5">
        <div className="mb-3 flex items-center justify-between">
          <h4 className="text-sm font-semibold text-slate-700">Models</h4>
          <button
            onClick={() => setModelEditor({})}
            className="inline-flex items-center gap-1 text-sm font-medium text-indigo-600 hover:text-indigo-700"
          >
            <Plus className="h-4 w-4" /> Add model
          </button>
        </div>

        {provider.models.length === 0 ? (
          <p className="rounded-lg bg-slate-50 p-3 text-sm text-slate-500">
            No models yet. Add one before granting this account to a tenant.
          </p>
        ) : (
          <div className="divide-y divide-slate-100">
            {provider.models.map((model) => (
              <div key={model.id} className="flex items-center justify-between gap-3 py-2.5">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-slate-800">
                    {model.display_label}
                    {!model.is_enabled ? (
                      <span className="ml-2 text-xs font-normal text-slate-400">disabled</span>
                    ) : null}
                  </p>
                  <p className="truncate text-xs text-slate-500">
                    {model.model_name} · in {money(model.input_cost_per_million)} / out{' '}
                    {money(model.output_cost_per_million)} per 1M
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <button
                    onClick={() => setModelEditor(model)}
                    className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100"
                  >
                    <Pencil className="h-4 w-4" />
                  </button>
                  <button
                    onClick={() => removeModel(model)}
                    className="rounded-lg p-1.5 text-rose-500 hover:bg-rose-50"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {editing ? (
        <ProviderEditor
          initial={provider}
          catalog={provider._catalog || []}
          onClose={() => setEditing(false)}
          onSaved={() => {
            setEditing(false)
            onChanged()
          }}
        />
      ) : null}

      {modelEditor ? (
        <ModelEditor
          providerId={provider.id}
          initial={modelEditor.id ? modelEditor : null}
          onClose={() => setModelEditor(null)}
          onSaved={() => {
            setModelEditor(null)
            onChanged()
          }}
        />
      ) : null}
    </div>
  )
}

function UsagePanel({ usage, loading, days, onDays }) {
  if (loading) {
    return (
      <div className="flex justify-center py-10">
        <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
      </div>
    )
  }
  if (!usage) return null

  const stats = [
    { label: 'Spend', value: money(usage.totals.cost_usd), icon: DollarSign },
    { label: 'Tokens', value: compact(usage.totals.tokens), icon: Zap },
    { label: 'Calls', value: compact(usage.totals.calls), icon: Bot },
    { label: 'Tenants', value: compact(usage.totals.tenants), icon: Building2 },
  ]

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <p className="text-sm text-slate-500">
          What our own models cost us. Tenants on their own keys aren't counted.
        </p>
        <select
          value={days}
          onChange={(e) => onDays(Number(e.target.value))}
          className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm"
        >
          <option value={7}>Last 7 days</option>
          <option value={30}>Last 30 days</option>
          <option value={90}>Last 90 days</option>
        </select>
      </div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {stats.map(({ label, value, icon: Icon }) => (
          <div key={label} className="rounded-xl border border-slate-200 bg-white p-4">
            <div className="flex items-center gap-2 text-slate-500">
              <Icon className="h-4 w-4" />
              <span className="text-xs font-medium uppercase tracking-wide">{label}</span>
            </div>
            <p className="mt-2 text-2xl font-semibold text-slate-900">{value}</p>
          </div>
        ))}
      </div>

      <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
        <div className="border-b border-slate-100 px-5 py-3">
          <h3 className="text-sm font-semibold text-slate-800">By tenant</h3>
        </div>
        {usage.tenants.length === 0 ? (
          <p className="p-5 text-sm text-slate-500">
            No tenant has used the platform's models in this window.
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-5 py-2">Tenant</th>
                <th className="px-5 py-2 text-right">Spend</th>
                <th className="px-5 py-2 text-right">Tokens</th>
                <th className="px-5 py-2 text-right">Calls</th>
                <th className="px-5 py-2">This month</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {usage.tenants.map((row) => {
                const month = row.month
                const percent = month?.percent_used || 0
                return (
                  <tr key={row.tenant_id || row.tenant_name}>
                    <td className="px-5 py-3 font-medium text-slate-800">{row.tenant_name}</td>
                    <td className="px-5 py-3 text-right text-slate-700">{money(row.cost_usd)}</td>
                    <td className="px-5 py-3 text-right text-slate-600">{compact(row.tokens)}</td>
                    <td className="px-5 py-3 text-right text-slate-600">{compact(row.calls)}</td>
                    <td className="px-5 py-3">
                      {month && (month.token_limit || month.cost_limit_usd) ? (
                        <div className="flex items-center gap-2">
                          <div className="h-1.5 w-24 overflow-hidden rounded-full bg-slate-100">
                            <div
                              className={`h-full ${percent >= 100 ? 'bg-rose-500' : percent >= 80 ? 'bg-amber-500' : 'bg-emerald-500'}`}
                              style={{ width: `${Math.min(100, percent)}%` }}
                            />
                          </div>
                          <span className="text-xs text-slate-500">{percent}%</span>
                        </div>
                      ) : (
                        <span className="text-xs text-slate-400">No limit</span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {[
          { title: 'By model', rows: usage.by_model, key: 'model' },
          { title: 'By feature', rows: usage.by_feature, key: 'feature' },
        ].map((group) => (
          <div key={group.title} className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
            <div className="border-b border-slate-100 px-5 py-3">
              <h3 className="text-sm font-semibold text-slate-800">{group.title}</h3>
            </div>
            {group.rows.length === 0 ? (
              <p className="p-5 text-sm text-slate-500">Nothing yet.</p>
            ) : (
              <div className="divide-y divide-slate-100">
                {group.rows.map((row) => (
                  <div key={row[group.key]} className="flex items-center justify-between px-5 py-2.5">
                    <span className="truncate text-sm text-slate-700">{row[group.key] || '—'}</span>
                    <span className="shrink-0 text-sm text-slate-600">
                      {money(row.cost)} · {compact(row.tokens)} tok
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

export default function AIPlatform() {
  const [tab, setTab] = useState('providers')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [usage, setUsage] = useState(null)
  const [usageLoading, setUsageLoading] = useState(false)
  const [days, setDays] = useState(30)

  const load = async () => {
    setLoading(true)
    try {
      setData(await fetchPlatformAI())
    } catch {
      toast.error('Could not load AI accounts')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  useEffect(() => {
    if (tab !== 'usage') return
    let cancelled = false
    setUsageLoading(true)
    fetchPlatformAIUsage(days)
      .then((result) => !cancelled && setUsage(result))
      .catch(() => !cancelled && toast.error('Could not load usage'))
      .finally(() => !cancelled && setUsageLoading(false))
    return () => {
      cancelled = true
    }
  }, [tab, days])

  const providers = data?.providers || []
  const catalog = data?.catalog || []

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold text-slate-900">
            <Bot className="h-6 w-6 text-indigo-600" /> AI Platform
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            Our own LLM accounts, the models they serve, and what they cost. Grant them to a
            tenant from that tenant's page.
          </p>
        </div>
        {tab === 'providers' ? (
          <button
            onClick={() => setCreating(true)}
            className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
          >
            <Plus className="h-4 w-4" /> Add account
          </button>
        ) : null}
      </div>

      <div className="flex gap-1 border-b border-slate-200">
        {[
          { id: 'providers', label: 'Accounts & models', icon: KeyRound },
          { id: 'usage', label: 'Usage & cost', icon: DollarSign },
        ].map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={`-mb-px inline-flex items-center gap-2 border-b-2 px-4 py-2 text-sm font-medium ${
              tab === id
                ? 'border-indigo-600 text-indigo-600'
                : 'border-transparent text-slate-500 hover:text-slate-700'
            }`}
          >
            <Icon className="h-4 w-4" />
            {label}
          </button>
        ))}
      </div>

      {tab === 'providers' ? (
        loading ? (
          <div className="flex justify-center py-10">
            <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
          </div>
        ) : providers.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-10 text-center">
            <Bot className="mx-auto h-8 w-8 text-slate-300" />
            <h3 className="mt-3 text-base font-medium text-slate-800">No AI accounts yet</h3>
            <p className="mx-auto mt-1 max-w-md text-sm text-slate-500">
              Add an account so tenants who can't get their own API key still get working AI.
            </p>
            <button
              onClick={() => setCreating(true)}
              className="mt-4 inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
            >
              <Plus className="h-4 w-4" /> Add account
            </button>
          </div>
        ) : (
          <div className="space-y-4">
            {providers.map((provider) => (
              <ProviderCard
                key={provider.id}
                provider={{ ...provider, _catalog: catalog }}
                onChanged={load}
              />
            ))}
          </div>
        )
      ) : (
        <UsagePanel usage={usage} loading={usageLoading} days={days} onDays={setDays} />
      )}

      {creating ? (
        <ProviderEditor
          initial={null}
          catalog={catalog}
          onClose={() => setCreating(false)}
          onSaved={() => {
            setCreating(false)
            load()
          }}
        />
      ) : null}
    </div>
  )
}
