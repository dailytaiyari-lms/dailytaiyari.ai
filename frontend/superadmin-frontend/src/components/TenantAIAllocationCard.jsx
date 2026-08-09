import { useEffect, useMemo, useState } from 'react'
import { Bot, Loader2, Save, AlertTriangle, Sparkles } from 'lucide-react'
import toast from 'react-hot-toast'
import { fetchTenantAllocation, saveTenantAllocation } from '../services/superadminService'

const compact = (n) => Number(n || 0).toLocaleString()
const money = (n) => `$${Number(n || 0).toFixed(2)}`

/**
 * Grant this tenant a slice of the platform's own LLMs.
 *
 * The whole point is that an academy with no technical staff still gets working
 * AI — so the important controls here are the ceilings, since every token spent
 * through this grant is on the platform's invoice, not the tenant's.
 */
export default function TenantAIAllocationCard({ tenantId }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState(null)

  const load = async () => {
    setLoading(true)
    try {
      const result = await fetchTenantAllocation(tenantId)
      setData(result)
      setForm({
        is_enabled: result.is_enabled,
        granted_models: result.granted_models.map(String),
        default_model: result.default_model ? String(result.default_model) : '',
        monthly_token_limit: result.monthly_token_limit,
        monthly_cost_limit_usd: result.monthly_cost_limit_usd,
        notify_at_percent: result.notify_at_percent,
      })
    } catch {
      toast.error('Could not load the AI allocation')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (tenantId) load()
  }, [tenantId])

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }))

  const grouped = useMemo(() => {
    const groups = new Map()
    for (const model of data?.available_models || []) {
      if (!groups.has(model.provider_name)) groups.set(model.provider_name, [])
      groups.get(model.provider_name).push(model)
    }
    return [...groups.entries()]
  }, [data])

  const toggleModel = (id) => {
    const next = form.granted_models.includes(id)
      ? form.granted_models.filter((m) => m !== id)
      : [...form.granted_models, id]
    // A default that is no longer granted would be rejected by the API.
    setForm((f) => ({
      ...f,
      granted_models: next,
      default_model: next.includes(f.default_model) ? f.default_model : '',
    }))
  }

  const save = async () => {
    setSaving(true)
    try {
      const result = await saveTenantAllocation(tenantId, {
        is_enabled: form.is_enabled,
        granted_models: form.granted_models,
        default_model: form.default_model || null,
        monthly_token_limit: Number(form.monthly_token_limit) || 0,
        monthly_cost_limit_usd: Number(form.monthly_cost_limit_usd) || 0,
        notify_at_percent: Number(form.notify_at_percent) || 80,
      })
      setData((d) => ({ ...d, ...result }))
      toast.success('AI allocation saved')
    } catch (err) {
      const body = err?.response?.data
      toast.error(body ? Object.values(body).flat()[0] : 'Could not save')
    } finally {
      setSaving(false)
    }
  }

  if (loading || !form) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-6">
        <Loader2 className="h-5 w-5 animate-spin text-slate-400" />
      </div>
    )
  }

  const status = data.status || {}
  const percent = status.percent_used || 0

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-6">
      <div className="mb-1 flex items-center gap-2">
        <Bot className="h-5 w-5 text-indigo-500" />
        <h2 className="font-semibold text-slate-900">Included AI models</h2>
      </div>
      <p className="mb-4 text-xs text-slate-500">
        Lend this tenant our own LLM accounts so their AI works without them ever obtaining an
        API key. Every token here is billed to us, so set a ceiling.
      </p>

      {data.has_own_provider ? (
        <div className="mb-4 flex items-start gap-2 rounded-lg bg-sky-50 p-3 text-xs text-sky-800">
          <Sparkles className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            This tenant has its own working AI key, which always takes priority. The grant below
            only applies if their key stops working.
          </span>
        </div>
      ) : null}

      <label className="mb-4 flex items-center gap-3">
        <input
          type="checkbox"
          checked={form.is_enabled}
          onChange={(e) => set('is_enabled', e.target.checked)}
          className="h-4 w-4 rounded border-slate-300"
        />
        <span className="text-sm font-medium text-slate-800">
          Give this tenant access to our AI models
        </span>
      </label>

      {form.is_enabled ? (
        <>
          {grouped.length === 0 ? (
            <div className="mb-4 flex items-start gap-2 rounded-lg bg-amber-50 p-3 text-xs text-amber-800">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>
                No platform models exist yet. Add an account under AI Platform first.
              </span>
            </div>
          ) : (
            <div className="mb-4 space-y-3">
              <div>
                <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
                  Models behind their AI
                </p>
                <p className="mt-0.5 text-xs text-slate-400">
                  The tenant never sees these. Grant more than one and we fail over
                  automatically when a model errors or rate-limits.
                </p>
              </div>
              {grouped.map(([providerName, models]) => (
                <div key={providerName}>
                  <p className="mb-1 text-xs font-medium text-slate-600">{providerName}</p>
                  <div className="space-y-1">
                    {models.map((model) => (
                      <label
                        key={model.id}
                        className={`flex items-center justify-between gap-3 rounded-lg border px-3 py-2 ${
                          form.granted_models.includes(String(model.id))
                            ? 'border-indigo-200 bg-indigo-50/50'
                            : 'border-slate-200'
                        } ${model.is_usable ? '' : 'opacity-60'}`}
                      >
                        <div className="flex min-w-0 items-center gap-2">
                          <input
                            type="checkbox"
                            checked={form.granted_models.includes(String(model.id))}
                            onChange={() => toggleModel(String(model.id))}
                            className="h-4 w-4 rounded border-slate-300"
                          />
                          <div className="min-w-0">
                            <p className="truncate text-sm text-slate-800">
                              {model.display_label}
                              {!model.is_usable ? (
                                <span className="ml-2 text-xs text-amber-600">unavailable</span>
                              ) : null}
                            </p>
                            <p className="truncate text-xs text-slate-400">{model.model_name}</p>
                          </div>
                        </div>
                        <span className="shrink-0 text-xs text-slate-500">
                          {money(model.input_cost_per_million)} / {money(model.output_cost_per_million)}
                          <span className="text-slate-400"> per 1M</span>
                        </span>
                      </label>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}

          {form.granted_models.length > 0 ? (
            <div className="mb-4">
              <label className="text-sm font-medium text-slate-700">Preferred model</label>
              <select
                value={form.default_model}
                onChange={(e) => set('default_model', e.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-brand-500"
              >
                <option value="">First available</option>
                {(data.available_models || [])
                  .filter((m) => form.granted_models.includes(String(m.id)))
                  .map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.display_label}
                    </option>
                  ))}
              </select>
              <p className="mt-1 text-xs text-slate-500">
                Tried first; the others are used as fallbacks, in order.
              </p>
            </div>
          ) : null}

          <div className="mb-4 grid gap-3 sm:grid-cols-3">
            <label className="block">
              <span className="text-sm font-medium text-slate-700">Monthly tokens</span>
              <input
                type="number"
                min={0}
                value={form.monthly_token_limit}
                onChange={(e) => set('monthly_token_limit', e.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-brand-500"
              />
              <span className="mt-1 block text-xs text-slate-500">0 = unlimited</span>
            </label>
            <label className="block">
              <span className="text-sm font-medium text-slate-700">Monthly spend (USD)</span>
              <input
                type="number"
                min={0}
                step="0.01"
                value={form.monthly_cost_limit_usd}
                onChange={(e) => set('monthly_cost_limit_usd', e.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-brand-500"
              />
              <span className="mt-1 block text-xs text-slate-500">0 = unlimited</span>
            </label>
            <label className="block">
              <span className="text-sm font-medium text-slate-700">Warn at %</span>
              <input
                type="number"
                min={1}
                max={100}
                value={form.notify_at_percent}
                onChange={(e) => set('notify_at_percent', e.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-brand-500"
              />
              <span className="mt-1 block text-xs text-slate-500">Emails their admins</span>
            </label>
          </div>

          <div className="mb-4 rounded-lg bg-slate-50 p-3">
            <div className="flex items-center justify-between text-xs text-slate-600">
              <span>
                This month: {compact(status.tokens_used)} tokens · {money(status.cost_used_usd)}
              </span>
              <span className={percent >= 100 ? 'font-medium text-rose-600' : ''}>
                {status.token_limit || status.cost_limit_usd ? `${percent}% used` : 'No limit set'}
              </span>
            </div>
            {status.token_limit || status.cost_limit_usd ? (
              <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-200">
                <div
                  className={`h-full ${percent >= 100 ? 'bg-rose-500' : percent >= 80 ? 'bg-amber-500' : 'bg-emerald-500'}`}
                  style={{ width: `${Math.min(100, percent)}%` }}
                />
              </div>
            ) : null}
          </div>
        </>
      ) : null}

      <button
        onClick={save}
        disabled={saving}
        className="inline-flex items-center gap-2 rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-60"
      >
        {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
        Save allocation
      </button>
    </div>
  )
}
