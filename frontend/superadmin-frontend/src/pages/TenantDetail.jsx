import { useEffect, useState } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import {
  ArrowLeft,
  Loader2,
  Save,
  Users,
  GraduationCap,
  BookOpen,
  ShieldCheck,
  Lock,
  Unlock,
  AlertTriangle,
  History,
  CreditCard,
  Gauge,
  Globe,
} from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import toast from 'react-hot-toast'
import {
  fetchTenant,
  updateTenant,
  fetchAuditLogs,
} from '../services/superadminService'
import TenantAIAllocationCard from '../components/TenantAIAllocationCard'

function Toggle({ checked, onChange, label, disabled }) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className="flex items-center justify-between w-full py-2 disabled:opacity-50"
    >
      <span className="text-sm text-slate-700">{label}</span>
      <span
        className={`relative inline-flex h-6 w-11 items-center rounded-full transition ${
          checked ? 'bg-brand-600' : 'bg-slate-300'
        }`}
      >
        <span
          className={`inline-block h-4 w-4 transform rounded-full bg-white transition ${
            checked ? 'translate-x-6' : 'translate-x-1'
          }`}
        />
      </span>
    </button>
  )
}

function MiniStat({ icon: Icon, label, value }) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-4 flex items-center gap-3">
      <div className="w-9 h-9 rounded-lg bg-brand-50 text-brand-600 flex items-center justify-center">
        <Icon className="w-4 h-4" />
      </div>
      <div>
        <div className="text-lg font-bold text-slate-900 leading-none">{value}</div>
        <div className="text-xs text-slate-500 mt-0.5">{label}</div>
      </div>
    </div>
  )
}

// Progress bar for a resource's usage against its cap.
function UsageBar({ label, status }) {
  const { used, limit } = status || { used: 0, limit: null }
  const unlimited = limit === null || limit === undefined
  const pct = unlimited || limit === 0 ? 0 : Math.min((used / limit) * 100, 100)
  const over = !unlimited && used >= limit
  const near = !over && pct >= 80
  const barColor = over ? 'bg-rose-500' : near ? 'bg-amber-500' : 'bg-brand-500'
  return (
    <div>
      <div className="flex items-center justify-between text-xs mb-1">
        <span className="text-slate-600">{label}</span>
        <span className={`font-medium ${over ? 'text-rose-600' : 'text-slate-700'}`}>
          {used}
          {unlimited ? ' / ∞' : ` / ${limit}`}
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-slate-100 overflow-hidden">
        <div className={`h-full rounded-full ${barColor}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

// ISO datetime -> value for <input type="date"> (YYYY-MM-DD), or ''.
function isoToDateInput(iso) {
  if (!iso) return ''
  return iso.slice(0, 10)
}
function FeatureRow({ feature, mode, tenantValue, onChange }) {
  const options = [
    { key: 'tenant', label: 'Tenant' },
    { key: 'on', label: 'Force On' },
    { key: 'off', label: 'Force Off' },
  ]
  const locked = mode !== 'tenant'
  return (
    <div className="flex items-center justify-between py-2.5">
      <div className="flex items-center gap-2 min-w-0">
        {locked ? (
          <Lock className="w-3.5 h-3.5 text-amber-500 shrink-0" />
        ) : (
          <Unlock className="w-3.5 h-3.5 text-slate-300 shrink-0" />
        )}
        <div className="min-w-0">
          <div className="text-sm text-slate-800 truncate">{feature.label}</div>
          <div className="text-[11px] text-slate-400">
            {locked
              ? 'Locked — tenant cannot change'
              : `Tenant-controlled (currently ${tenantValue ? 'on' : 'off'})`}
          </div>
        </div>
      </div>
      <div className="flex rounded-lg border border-slate-200 overflow-hidden shrink-0">
        {options.map((o) => (
          <button
            key={o.key}
            type="button"
            onClick={() => onChange(feature.key, o.key)}
            className={`px-2.5 py-1 text-xs font-medium transition ${
              mode === o.key
                ? o.key === 'off'
                  ? 'bg-rose-600 text-white'
                  : o.key === 'on'
                  ? 'bg-emerald-600 text-white'
                  : 'bg-slate-700 text-white'
                : 'bg-white text-slate-500 hover:bg-slate-50'
            }`}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  )
}

// Map API feature_locks map -> per-feature UI mode ('tenant' | 'on' | 'off').
function locksToModes(availableFeatures, featureLocks) {
  const modes = {}
  for (const f of availableFeatures) {
    if (Object.prototype.hasOwnProperty.call(featureLocks, f.key)) {
      modes[f.key] = featureLocks[f.key] ? 'on' : 'off'
    } else {
      modes[f.key] = 'tenant'
    }
  }
  return modes
}

function modesToLocks(modes) {
  const locks = {}
  for (const [key, mode] of Object.entries(modes)) {
    if (mode === 'on') locks[key] = true
    else if (mode === 'off') locks[key] = false
  }
  return locks
}

function actionLabel(action) {
  const map = {
    'tenant.create': 'Created tenant',
    'tenant.update': 'Updated tenant',
    'tenant.suspend': 'Suspended tenant',
    'tenant.unsuspend': 'Unsuspended tenant',
    'tenant.feature_locks': 'Changed feature locks',
    'tenant.plan': 'Changed plan / quotas',
  }
  return map[action] || action
}

export default function TenantDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [tenant, setTenant] = useState(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState(null)
  const [logs, setLogs] = useState([])

  const loadLogs = () =>
    fetchAuditLogs({ tenant: id })
      .then((d) => setLogs((d.results || d).slice(0, 8)))
      .catch(() => {})

  useEffect(() => {
    fetchTenant(id)
      .then((data) => {
        setTenant(data)
        setForm({
          name: data.name,
          tagline: data.tagline || '',
          subdomain: data.subdomain || '',
          theme: data.theme,
          show_name: data.show_name,
          is_active: data.is_active,
          is_suspended: data.is_suspended,
          suspension_message: data.suspension_message || '',
          plan: data.plan || 'trial',
          billing_status: data.billing_status || 'trialing',
          trial_ends_at: isoToDateInput(data.trial_ends_at),
          current_period_end: isoToDateInput(data.current_period_end),
          max_students: data.max_students ?? '',
          max_courses: data.max_courses ?? '',
          max_admins: data.max_admins ?? '',
          origins_text: (data.allowed_origins || []).join('\n'),
          featureModes: locksToModes(data.available_features || [], data.feature_locks || {}),
        })
      })
      .catch(() => {
        toast.error('Tenant not found')
        navigate('/tenants', { replace: true })
      })
      .finally(() => setLoading(false))
    loadLogs()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, navigate])

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }))
  const setFeatureMode = (key, mode) =>
    setForm((f) => ({ ...f, featureModes: { ...f.featureModes, [key]: mode } }))

  // Apply a plan's default caps into the form (super admin can still tweak).
  const applyPlanDefaults = (planKey) => {
    const plan = (tenant.available_plans || []).find((p) => p.key === planKey)
    const d = plan?.defaults || {}
    setForm((f) => ({
      ...f,
      plan: planKey,
      max_students: d.max_students ?? '',
      max_courses: d.max_courses ?? '',
      max_admins: d.max_admins ?? '',
    }))
  }

  const capOrNull = (v) => {
    if (v === '' || v === null || v === undefined) return null
    const n = Number(v)
    return Number.isFinite(n) && n >= 0 ? n : null
  }

  const save = async () => {
    setSaving(true)
    try {
      const payload = {
        name: form.name.trim(),
        tagline: form.tagline.trim(),
        theme: form.theme,
        show_name: form.show_name,
        is_active: form.is_active,
        is_suspended: form.is_suspended,
        suspension_message: form.suspension_message,
        feature_locks: modesToLocks(form.featureModes),
        plan: form.plan,
        billing_status: form.billing_status,
        trial_ends_at: form.trial_ends_at || null,
        current_period_end: form.current_period_end || null,
        max_students: capOrNull(form.max_students),
        max_courses: capOrNull(form.max_courses),
        max_admins: capOrNull(form.max_admins),
        allowed_origins: form.origins_text
          .split('\n')
          .map((s) => s.trim())
          .filter(Boolean),
      }
      const sub = form.subdomain.trim().toLowerCase()
      if (sub !== (tenant.subdomain || '')) payload.subdomain = sub
      const updated = await updateTenant(id, payload)
      setTenant(updated)
      setForm((f) => ({
        ...f,
        trial_ends_at: isoToDateInput(updated.trial_ends_at),
        current_period_end: isoToDateInput(updated.current_period_end),
        max_students: updated.max_students ?? '',
        max_courses: updated.max_courses ?? '',
        max_admins: updated.max_admins ?? '',
        origins_text: (updated.allowed_origins || []).join('\n'),
        featureModes: locksToModes(updated.available_features || [], updated.feature_locks || {}),
      }))
      loadLogs()
      toast.success('Saved')
    } catch (err) {
      const d = err.response?.data || {}
      const msg =
        (Array.isArray(d.subdomain) && d.subdomain[0]) ||
        (Array.isArray(d.name) && d.name[0]) ||
        (Array.isArray(d.plan) && d.plan[0]) ||
        (Array.isArray(d.billing_status) && d.billing_status[0]) ||
        (Array.isArray(d.allowed_origins) && d.allowed_origins[0]) ||
        'Could not save changes'
      toast.error(msg)
    } finally {
      setSaving(false)
    }
  }

  if (loading || !form) {
    return (
      <div className="flex items-center justify-center py-24 text-slate-400">
        <Loader2 className="w-6 h-6 animate-spin" />
      </div>
    )
  }

  const lockedCount = Object.values(form.featureModes).filter((m) => m !== 'tenant').length

  return (
    <div className="space-y-6">
      <Link
        to="/tenants"
        className="inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-800"
      >
        <ArrowLeft className="w-4 h-4" /> Back to tenants
      </Link>

      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">{tenant.name}</h1>
          <p className="text-slate-500 text-sm mt-1 flex items-center gap-2">
            {tenant.subdomain || 'no subdomain'} ·{' '}
            <span className={tenant.is_active ? 'text-emerald-600' : 'text-rose-600'}>
              {tenant.is_active ? 'Active' : 'Inactive'}
            </span>
            {tenant.is_suspended && (
              <span className="inline-flex items-center gap-1 text-amber-600 font-medium">
                <AlertTriangle className="w-3.5 h-3.5" /> Suspended
              </span>
            )}
            {!tenant.is_suspended && tenant.is_billing_frozen && (
              <span className="inline-flex items-center gap-1 text-rose-600 font-medium">
                <CreditCard className="w-3.5 h-3.5" /> Subscription inactive
              </span>
            )}
            <span className="inline-flex items-center gap-1 text-slate-500">
              <CreditCard className="w-3.5 h-3.5" />
              {(tenant.available_plans || []).find((p) => p.key === tenant.plan)?.label ||
                tenant.plan}
            </span>
          </p>
        </div>
        <button
          onClick={save}
          disabled={saving}
          className="flex items-center gap-2 px-4 py-2.5 rounded-lg bg-brand-600 hover:bg-brand-700 disabled:opacity-60 text-white font-semibold"
        >
          {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
          Save Changes
        </button>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MiniStat icon={Users} label="Users" value={tenant.user_count} />
        <MiniStat icon={GraduationCap} label="Students" value={tenant.student_count} />
        <MiniStat icon={ShieldCheck} label="Admins" value={tenant.admin_count} />
        <MiniStat icon={BookOpen} label="Courses" value={tenant.course_count} />
      </div>

      <div className="grid md:grid-cols-2 gap-6">
        {/* Details */}
        <div className="bg-white rounded-xl border border-slate-200 p-6 space-y-4">
          <h2 className="font-semibold text-slate-900">Details</h2>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1.5">Name</label>
            <input
              value={form.name}
              onChange={(e) => set('name', e.target.value)}
              className="w-full px-4 py-2.5 rounded-lg border border-slate-300 focus:ring-2 focus:ring-brand-500 outline-none"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1.5">Tagline</label>
            <input
              value={form.tagline}
              onChange={(e) => set('tagline', e.target.value)}
              className="w-full px-4 py-2.5 rounded-lg border border-slate-300 focus:ring-2 focus:ring-brand-500 outline-none"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1.5">Subdomain</label>
            <input
              value={form.subdomain}
              onChange={(e) => set('subdomain', e.target.value)}
              className="w-full px-4 py-2.5 rounded-lg border border-slate-300 focus:ring-2 focus:ring-brand-500 outline-none"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1.5">Theme</label>
            <select
              value={form.theme}
              onChange={(e) => set('theme', e.target.value)}
              className="w-full px-4 py-2.5 rounded-lg border border-slate-300 focus:ring-2 focus:ring-brand-500 outline-none capitalize"
            >
              {(tenant.available_themes || []).map((t) => (
                <option key={t.key} value={t.key}>{t.label}</option>
              ))}
            </select>
          </div>
          <div className="pt-2 border-t border-slate-100 space-y-1">
            <Toggle
              checked={form.is_active}
              onChange={(v) => set('is_active', v)}
              label="Tenant active"
            />
            <Toggle
              checked={form.show_name}
              onChange={(v) => set('show_name', v)}
              label="Show name alongside logo"
            />
          </div>
        </div>

        {/* Feature governance */}
        <div className="bg-white rounded-xl border border-slate-200 p-6">
          <div className="flex items-center justify-between mb-1">
            <h2 className="font-semibold text-slate-900">Feature Governance</h2>
            {lockedCount > 0 && (
              <span className="text-xs font-medium text-amber-600 bg-amber-50 px-2 py-0.5 rounded-full">
                {lockedCount} locked
              </span>
            )}
          </div>
          <p className="text-xs text-slate-500 mb-3">
            <strong>Tenant</strong> lets the academy admin decide. <strong>Force On/Off</strong>
            {' '}locks the feature — the tenant admin sees it greyed out and is told to contact
            the DailyTaiyari team.
          </p>
          <div className="divide-y divide-slate-100">
            {(tenant.available_features || []).map((f) => (
              <FeatureRow
                key={f.key}
                feature={f}
                mode={form.featureModes[f.key] || 'tenant'}
                tenantValue={tenant.features?.[f.key]}
                onChange={setFeatureMode}
              />
            ))}
          </div>
        </div>
      </div>

      {/* Plan & Quota */}
      <div className="bg-white rounded-xl border border-slate-200 p-6 space-y-5">
        <div className="flex items-center gap-2">
          <Gauge className="w-5 h-5 text-brand-600" />
          <h2 className="font-semibold text-slate-900">Plan &amp; Quotas</h2>
        </div>

        <div className="grid md:grid-cols-2 gap-6">
          {/* Plan + billing */}
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1.5">Plan</label>
              <select
                value={form.plan}
                onChange={(e) => applyPlanDefaults(e.target.value)}
                className="w-full px-4 py-2.5 rounded-lg border border-slate-300 focus:ring-2 focus:ring-brand-500 outline-none"
              >
                {(tenant.available_plans || []).map((p) => (
                  <option key={p.key} value={p.key}>{p.label}</option>
                ))}
              </select>
              <p className="text-[11px] text-slate-400 mt-1">
                Changing the plan pre-fills its default caps — tweak them below if needed.
              </p>
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1.5">Billing status</label>
              <select
                value={form.billing_status}
                onChange={(e) => set('billing_status', e.target.value)}
                className="w-full px-4 py-2.5 rounded-lg border border-slate-300 focus:ring-2 focus:ring-brand-500 outline-none"
              >
                {(tenant.billing_statuses || []).map((s) => (
                  <option key={s.key} value={s.key}>{s.label}</option>
                ))}
              </select>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1.5">Trial ends</label>
                <input
                  type="date"
                  value={form.trial_ends_at}
                  onChange={(e) => set('trial_ends_at', e.target.value)}
                  className="w-full px-3 py-2.5 rounded-lg border border-slate-300 focus:ring-2 focus:ring-brand-500 outline-none text-sm"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1.5">Renews / period end</label>
                <input
                  type="date"
                  value={form.current_period_end}
                  onChange={(e) => set('current_period_end', e.target.value)}
                  className="w-full px-3 py-2.5 rounded-lg border border-slate-300 focus:ring-2 focus:ring-brand-500 outline-none text-sm"
                />
              </div>
            </div>
          </div>

          {/* Quota caps + live usage */}
          <div className="space-y-4">
            <p className="text-xs text-slate-500">
              Caps limit what the tenant can create. Leave blank for <strong>unlimited</strong>.
              When a cap is hit, the tenant admin is told to contact the DailyTaiyari team.
            </p>
            {[
              { key: 'max_students', label: 'Max students', resource: 'students' },
              { key: 'max_courses', label: 'Max courses', resource: 'courses' },
              { key: 'max_admins', label: 'Max admins', resource: 'admins' },
            ].map(({ key, label, resource }) => (
              <div key={key} className="space-y-1.5">
                <div className="flex items-center justify-between gap-3">
                  <label className="text-sm font-medium text-slate-700">{label}</label>
                  <input
                    type="number"
                    min="0"
                    placeholder="∞"
                    value={form[key]}
                    onChange={(e) => set(key, e.target.value)}
                    className="w-28 px-3 py-1.5 rounded-lg border border-slate-300 focus:ring-2 focus:ring-brand-500 outline-none text-sm text-right"
                  />
                </div>
                <UsageBar label="Current usage" status={tenant.quota_status?.[resource]} />
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Allowed frontend origins (self-serve CORS) */}
      <div className="bg-white rounded-xl border border-slate-200 p-6">
        <div className="flex items-center gap-2 mb-1">
          <Globe className="w-5 h-5 text-brand-600" />
          <h2 className="font-semibold text-slate-900">Frontend Origins (CORS)</h2>
        </div>
        <p className="text-xs text-slate-500 mb-3">
          Exact browser origins this tenant&apos;s own frontend is served from, allowed to call
          the platform API cross-origin. One per line, scheme + host [+ port], no path — e.g.
          <code className="mx-1 px-1 bg-slate-100 rounded">https://academy.netlify.app</code>.
          Changes take effect within a minute — no code deploy needed.
        </p>
        <textarea
          value={form.origins_text}
          onChange={(e) => set('origins_text', e.target.value)}
          placeholder={'https://academy.netlify.app\nhttps://app.academy.com'}
          rows={3}
          spellCheck={false}
          className="w-full px-4 py-2.5 rounded-lg border border-slate-300 focus:ring-2 focus:ring-brand-500 outline-none text-sm font-mono"
        />
      </div>

      {/* Included AI models */}
      <TenantAIAllocationCard tenantId={id} />

      {/* Suspension */}
      <div
        className={`rounded-xl border p-6 ${
          form.is_suspended ? 'border-amber-300 bg-amber-50' : 'border-slate-200 bg-white'
        }`}
      >
        <div className="flex items-center gap-2 mb-1">
          <AlertTriangle className={`w-5 h-5 ${form.is_suspended ? 'text-amber-600' : 'text-slate-400'}`} />
          <h2 className="font-semibold text-slate-900">Suspension</h2>
        </div>
        <p className="text-xs text-slate-500 mb-3">
          A suspended tenant is frozen: logins and all data access are blocked and the message
          below is shown to its users. Use this for billing or compliance holds.
        </p>
        <Toggle
          checked={form.is_suspended}
          onChange={(v) => set('is_suspended', v)}
          label="Suspend this tenant"
        />
        <textarea
          value={form.suspension_message}
          onChange={(e) => set('suspension_message', e.target.value)}
          placeholder="Message shown to the tenant while suspended (e.g. Account on billing hold — contact the DailyTaiyari team)."
          rows={2}
          className="mt-2 w-full px-4 py-2.5 rounded-lg border border-slate-300 focus:ring-2 focus:ring-brand-500 outline-none text-sm"
        />
      </div>

      {/* Audit log */}
      <div className="bg-white rounded-xl border border-slate-200">
        <div className="flex items-center gap-2 px-5 py-4 border-b border-slate-100">
          <History className="w-4 h-4 text-slate-400" />
          <h2 className="font-semibold text-slate-900">Recent Changes</h2>
        </div>
        {logs.length === 0 ? (
          <div className="px-5 py-6 text-sm text-slate-400 text-center">No changes recorded yet.</div>
        ) : (
          <ul className="divide-y divide-slate-100">
            {logs.map((log) => (
              <li key={log.id} className="px-5 py-3 flex items-center justify-between text-sm">
                <div>
                  <span className="font-medium text-slate-800">{actionLabel(log.action)}</span>
                  {log.changes && Object.keys(log.changes).length > 0 && (
                    <span className="text-slate-400">
                      {' '}· {Object.keys(log.changes).join(', ')}
                    </span>
                  )}
                  <div className="text-xs text-slate-400">{log.actor_email || 'system'}</div>
                </div>
                <span className="text-xs text-slate-400 whitespace-nowrap">
                  {formatDistanceToNow(new Date(log.created_at), { addSuffix: true })}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
