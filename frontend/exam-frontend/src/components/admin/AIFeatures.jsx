import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'framer-motion'
import toast from 'react-hot-toast'
import {
    AlertTriangle,
    BadgeCheck,
    BarChart3,
    Check,
    CheckCircle2,
    ExternalLink,
    Eye,
    EyeOff,
    Gift,
    Info,
    Key,
    Loader2,
    Plug,
    Save,
    Server,
    Settings2,
    Sparkles,
    Trash2,
    XCircle,
    Zap,
} from 'lucide-react'

import { aiAdminService } from '../../services/aiAdminService'
import IncludedAI from './IncludedAI'

/* ---------------------------------------------------------------------------
 * Helpers
 * ------------------------------------------------------------------------- */

const formatNumber = (n) => new Intl.NumberFormat().format(Math.round(n || 0))

const formatCost = (usd) => {
    const value = Number(usd || 0)
    if (!value) return '$0.00'
    if (value < 0.01) return '< $0.01'
    return `$${value.toFixed(2)}`
}

const SUB_TABS = [
    { id: 'provider', label: 'AI Provider', icon: Plug },
    { id: 'behaviour', label: 'Behaviour & Limits', icon: Settings2 },
    { id: 'usage', label: 'Usage & Cost', icon: BarChart3 },
]

/* ---------------------------------------------------------------------------
 * Provider picker + credential form
 * ------------------------------------------------------------------------- */

const ProviderCard = ({ meta, saved, selected, onSelect }) => (
    <button
        type="button"
        onClick={() => onSelect(meta.id)}
        className={`relative text-left p-4 rounded-2xl border-2 transition-all ${selected
            ? 'border-primary-500 bg-primary-50/60 dark:bg-primary-900/20'
            : 'border-surface-200 dark:border-surface-800 hover:border-primary-300 dark:hover:border-primary-700'}`}
    >
        <div className="flex items-start justify-between gap-2">
            <span className="font-semibold text-sm text-surface-900 dark:text-white">{meta.label}</span>
            {saved?.is_active && (
                <span className="badge-success shrink-0"><BadgeCheck className="w-3 h-3" /> Live</span>
            )}
            {!saved?.is_active && saved && (
                <span className="badge-primary shrink-0">Saved</span>
            )}
        </div>
        <p className="text-xs text-surface-500 mt-1.5 leading-relaxed">{meta.description}</p>
        <div className="flex flex-wrap gap-1.5 mt-2.5">
            {meta.is_open_source && (
                <span className="badge bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400">
                    Open source
                </span>
            )}
            {!meta.requires_api_key && (
                <span className="badge bg-surface-100 text-surface-600 dark:bg-surface-800 dark:text-surface-300">
                    No key needed
                </span>
            )}
        </div>
    </button>
)

const emptyForm = (meta) => ({
    provider: meta?.id || '',
    api_key: '',
    base_url: '',
    model: meta?.default_model || '',
    api_version: '2024-10-21',
    temperature: 0.7,
    max_tokens: 2000,
    is_active: true,
})

const ProviderSettings = ({ data }) => {
    const queryClient = useQueryClient()
    const catalog = data?.catalog || []
    const providers = data?.providers || []

    const [selectedId, setSelectedId] = useState(
        () => data?.active_provider || providers[0]?.provider || catalog[0]?.id,
    )
    const [form, setForm] = useState(() => emptyForm(catalog.find((c) => c.id === selectedId)))
    const [showKey, setShowKey] = useState(false)

    const meta = useMemo(() => catalog.find((c) => c.id === selectedId), [catalog, selectedId])
    const saved = useMemo(
        () => providers.find((p) => p.provider === selectedId),
        [providers, selectedId],
    )

    // Reload the form whenever the admin switches provider, or the server data
    // refreshes after a save, so the fields always mirror what is stored.
    useEffect(() => {
        if (!meta) return
        setShowKey(false)
        setForm({
            provider: meta.id,
            api_key: '',
            base_url: saved?.base_url || '',
            model: saved?.model || meta.default_model || '',
            api_version: saved?.api_version || '2024-10-21',
            temperature: saved?.temperature ?? 0.7,
            max_tokens: saved?.max_tokens ?? 2000,
            is_active: saved ? saved.is_active : true,
        })
    }, [meta, saved])

    const update = (patch) => setForm((prev) => ({ ...prev, ...patch }))

    const invalidate = () => queryClient.invalidateQueries({ queryKey: ['aiProviders'] })

    const saveMutation = useMutation({
        mutationFn: () => aiAdminService.saveProvider(form),
        onSuccess: () => {
            toast.success('AI provider saved')
            invalidate()
        },
        onError: (err) => {
            const detail = err?.response?.data
            const message =
                typeof detail === 'string'
                    ? detail
                    : Object.values(detail || {}).flat()[0] || 'Could not save the provider'
            toast.error(message)
        },
    })

    const testMutation = useMutation({
        mutationFn: () =>
            aiAdminService.testProvider({
                provider: form.provider,
                api_key: form.api_key || undefined,
                base_url: form.base_url || undefined,
                model: form.model || undefined,
                api_version: form.api_version || undefined,
            }),
        onSuccess: (res) => {
            toast.success(res.message || 'Connection successful')
            invalidate()
        },
        onError: (err) => {
            const detail = err?.response?.data
            toast.error(detail?.message || Object.values(detail || {}).flat()[0] || 'Connection failed')
            invalidate()
        },
    })

    const deleteMutation = useMutation({
        mutationFn: () => aiAdminService.deleteProvider(selectedId),
        onSuccess: () => {
            toast.success('Provider removed')
            invalidate()
        },
        onError: () => toast.error('Could not remove the provider'),
    })

    if (!meta) return null

    const busy = saveMutation.isPending || testMutation.isPending

    return (
        <div className="space-y-6">
            {/* Status banner — is the assistant actually answering students? */}
            <div
                className={`card p-5 flex flex-col sm:flex-row sm:items-center gap-4 ${data?.is_ready
                    ? 'border-emerald-200 dark:border-emerald-900'
                    : 'border-amber-200 dark:border-amber-900'}`}
            >
                <div
                    className={`w-11 h-11 rounded-xl flex items-center justify-center shrink-0 ${data?.is_ready
                        ? 'bg-emerald-50 text-emerald-600 dark:bg-emerald-900/30 dark:text-emerald-400'
                        : 'bg-amber-50 text-amber-600 dark:bg-amber-900/30 dark:text-amber-400'}`}
                >
                    {data?.is_ready ? <CheckCircle2 className="w-5 h-5" /> : <AlertTriangle className="w-5 h-5" />}
                </div>
                <div className="flex-1">
                    <h3 className="font-bold text-surface-900 dark:text-white">
                        {data?.is_ready ? 'AI Doubt Solver is live' : 'AI Doubt Solver is not connected yet'}
                    </h3>
                    <p className="text-sm text-surface-500 mt-0.5">
                        {data?.is_ready
                            ? data.active_provider
                                ? `Students are being answered using your ${catalog.find((c) => c.id === data.active_provider)?.label || data.active_provider} key.`
                                : 'Students are being answered from your included platform allowance.'
                            : 'Connect a provider below. Until then students see a message asking them to contact you.'}
                    </p>
                </div>
            </div>

            {/* The no-API-key path: AI we supply, nothing to configure. */}
            <IncludedAI hasOwnKey={Boolean(data?.active_provider)} />

            {/* Provider selection */}
            <div className="card p-6 space-y-4">
                <div>
                    <div className="flex items-center gap-2">
                        <Sparkles className="w-5 h-5 text-primary-500" />
                        <h3 className="text-lg font-bold text-surface-900 dark:text-white">Choose your AI provider</h3>
                    </div>
                    <p className="text-sm text-surface-500 mt-1">
                        Bring your own key so AI usage is billed to your own account. Prefer zero cost? Google Gemini,
                        Groq and OpenRouter all have free tiers, and self-hosted Ollama runs open-source models on your
                        own server for free.
                    </p>
                </div>

                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                    {catalog.map((c) => (
                        <ProviderCard
                            key={c.id}
                            meta={c}
                            saved={providers.find((p) => p.provider === c.id)}
                            selected={c.id === selectedId}
                            onSelect={setSelectedId}
                        />
                    ))}
                </div>
            </div>

            {/* Credentials for the selected provider */}
            <div className="card p-6 space-y-5">
                <div className="flex items-start justify-between gap-3 flex-wrap">
                    <div>
                        <div className="flex items-center gap-2">
                            <Key className="w-5 h-5 text-primary-500" />
                            <h3 className="text-lg font-bold text-surface-900 dark:text-white">
                                {meta.label} configuration
                            </h3>
                        </div>
                        {meta.docs_url && (
                            <a
                                href={meta.docs_url}
                                target="_blank"
                                rel="noreferrer"
                                className="text-sm text-primary-600 dark:text-primary-400 hover:underline inline-flex items-center gap-1 mt-1"
                            >
                                Get a key from {meta.label} <ExternalLink className="w-3.5 h-3.5" />
                            </a>
                        )}
                    </div>
                    {saved?.last_test_ok === true && (
                        <span className="badge-success"><Check className="w-3 h-3" /> Last test passed</span>
                    )}
                    {saved?.last_test_ok === false && (
                        <span className="badge-error" title={saved.last_test_error}>
                            <XCircle className="w-3 h-3" /> Last test failed
                        </span>
                    )}
                </div>

                {saved?.last_test_ok === false && saved.last_test_error && (
                    <div className="text-sm rounded-xl px-4 py-3 bg-rose-50 dark:bg-rose-900/20 text-rose-700 dark:text-rose-300">
                        {saved.last_test_error}
                    </div>
                )}

                <div className="grid gap-4 sm:grid-cols-2">
                    {meta.requires_api_key && (
                        <div className="sm:col-span-2">
                            <label className="block text-sm font-medium text-surface-700 dark:text-surface-300 mb-1.5">
                                API key
                            </label>
                            <div className="relative">
                                <input
                                    type={showKey ? 'text' : 'password'}
                                    value={form.api_key}
                                    onChange={(e) => update({ api_key: e.target.value })}
                                    placeholder={saved?.has_api_key ? '•••••••••• (stored — leave blank to keep)' : 'Paste your API key'}
                                    className="input pr-12"
                                    autoComplete="off"
                                />
                                <button
                                    type="button"
                                    onClick={() => setShowKey((v) => !v)}
                                    className="absolute right-3 top-1/2 -translate-y-1/2 text-surface-400 hover:text-surface-600"
                                >
                                    {showKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                                </button>
                            </div>
                            <p className="text-xs text-surface-500 mt-1.5">
                                Stored encrypted. It is never shown again and never sent to students' browsers.
                            </p>
                        </div>
                    )}

                    <div className={meta.uses_api_version ? '' : 'sm:col-span-2'}>
                        <label className="block text-sm font-medium text-surface-700 dark:text-surface-300 mb-1.5">
                            {meta.uses_api_version ? 'Deployment name' : 'Model'}
                        </label>
                        <input
                            type="text"
                            value={form.model}
                            onChange={(e) => update({ model: e.target.value })}
                            placeholder={meta.default_model || 'e.g. gpt-4o-mini'}
                            className="input"
                            list={`models-${meta.id}`}
                        />
                        <datalist id={`models-${meta.id}`}>
                            {(meta.model_suggestions || []).map((m) => (
                                <option key={m} value={m} />
                            ))}
                        </datalist>
                        {meta.model_suggestions?.length > 0 && (
                            <div className="flex flex-wrap gap-1.5 mt-2">
                                {meta.model_suggestions.map((m) => (
                                    <button
                                        key={m}
                                        type="button"
                                        onClick={() => update({ model: m })}
                                        className="text-xs px-2 py-1 rounded-lg bg-surface-100 dark:bg-surface-800 hover:bg-primary-100 dark:hover:bg-primary-900/30 text-surface-600 dark:text-surface-300"
                                    >
                                        {m}
                                    </button>
                                ))}
                            </div>
                        )}
                    </div>

                    {meta.uses_api_version && (
                        <div>
                            <label className="block text-sm font-medium text-surface-700 dark:text-surface-300 mb-1.5">
                                API version
                            </label>
                            <input
                                type="text"
                                value={form.api_version}
                                onChange={(e) => update({ api_version: e.target.value })}
                                className="input"
                            />
                        </div>
                    )}

                    <div className="sm:col-span-2">
                        <label className="block text-sm font-medium text-surface-700 dark:text-surface-300 mb-1.5">
                            Endpoint URL {!meta.requires_base_url && <span className="text-surface-400">(optional)</span>}
                        </label>
                        <input
                            type="text"
                            value={form.base_url}
                            onChange={(e) => update({ base_url: e.target.value })}
                            placeholder={meta.default_base_url || 'https://…'}
                            className="input"
                        />
                        {meta.uses_api_version && (
                            <p className="text-xs text-surface-500 mt-1.5">
                                Your Azure resource endpoint, e.g. https://my-resource.openai.azure.com
                            </p>
                        )}
                    </div>

                    <div>
                        <label className="block text-sm font-medium text-surface-700 dark:text-surface-300 mb-1.5">
                            Creativity (temperature) — {form.temperature}
                        </label>
                        <input
                            type="range"
                            min="0"
                            max="1.5"
                            step="0.1"
                            value={form.temperature}
                            onChange={(e) => update({ temperature: parseFloat(e.target.value) })}
                            className="w-full accent-primary-500"
                        />
                        <p className="text-xs text-surface-500">Lower is more factual, higher is more varied.</p>
                    </div>

                    <div>
                        <label className="block text-sm font-medium text-surface-700 dark:text-surface-300 mb-1.5">
                            Max answer length (tokens)
                        </label>
                        <input
                            type="number"
                            min={128}
                            max={32000}
                            step={128}
                            value={form.max_tokens}
                            onChange={(e) => update({ max_tokens: parseInt(e.target.value, 10) || 2000 })}
                            className="input"
                        />
                        <p className="text-xs text-surface-500 mt-1">Caps the cost of any single answer.</p>
                    </div>
                </div>

                <label className="flex items-center gap-3 p-4 rounded-xl bg-surface-50 dark:bg-surface-800/50 cursor-pointer">
                    <input
                        type="checkbox"
                        checked={form.is_active}
                        onChange={(e) => update({ is_active: e.target.checked })}
                        className="w-4 h-4 accent-primary-500"
                    />
                    <span className="text-sm">
                        <span className="font-medium text-surface-900 dark:text-white">Use this provider for students</span>
                        <span className="block text-surface-500 text-xs mt-0.5">
                            Only one provider is live at a time — turning this on switches the others off.
                        </span>
                    </span>
                </label>

                <div className="flex flex-wrap items-center gap-3 pt-1">
                    <button
                        onClick={() => saveMutation.mutate()}
                        disabled={busy}
                        className="btn-primary"
                    >
                        {saveMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                        Save provider
                    </button>
                    <button
                        onClick={() => testMutation.mutate()}
                        disabled={busy}
                        className="btn-secondary"
                    >
                        {testMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
                        Test connection
                    </button>
                    {saved && (
                        <button
                            onClick={() => {
                                if (window.confirm(`Remove the saved ${meta.label} credentials?`)) {
                                    deleteMutation.mutate()
                                }
                            }}
                            disabled={deleteMutation.isPending}
                            className="btn-ghost text-rose-600 dark:text-rose-400 ml-auto"
                        >
                            <Trash2 className="w-4 h-4" /> Remove
                        </button>
                    )}
                </div>
            </div>
        </div>
    )
}

/* ---------------------------------------------------------------------------
 * Behaviour & limits
 * ------------------------------------------------------------------------- */

const Toggle = ({ checked, onChange, title, description }) => (
    <label className="flex items-start gap-3 p-4 rounded-xl bg-surface-50 dark:bg-surface-800/50 cursor-pointer">
        <input
            type="checkbox"
            checked={checked}
            onChange={(e) => onChange(e.target.checked)}
            className="w-4 h-4 mt-0.5 accent-primary-500"
        />
        <span className="text-sm">
            <span className="font-medium text-surface-900 dark:text-white">{title}</span>
            <span className="block text-surface-500 text-xs mt-0.5">{description}</span>
        </span>
    </label>
)

const BehaviourSettings = ({ data }) => {
    const queryClient = useQueryClient()
    const stored = data?.settings || {}
    const [form, setForm] = useState(stored)

    useEffect(() => setForm(stored), [data?.settings])

    const update = (patch) => setForm((prev) => ({ ...prev, ...patch }))

    const saveMutation = useMutation({
        mutationFn: () => aiAdminService.updateSettings(form),
        onSuccess: () => {
            toast.success('AI settings saved')
            queryClient.invalidateQueries({ queryKey: ['aiProviders'] })
        },
        onError: (err) => {
            const detail = err?.response?.data
            toast.error(Object.values(detail || {}).flat()[0] || 'Could not save settings')
        },
    })

    return (
        <div className="space-y-6">
            <div className="card p-6 space-y-4">
                <div className="flex items-center gap-2">
                    <Settings2 className="w-5 h-5 text-primary-500" />
                    <h3 className="text-lg font-bold text-surface-900 dark:text-white">Assistant behaviour</h3>
                </div>

                <Toggle
                    checked={!!form.is_enabled}
                    onChange={(v) => update({ is_enabled: v })}
                    title="AI Doubt Solver is available to students"
                    description="Turn this off to pause the assistant without deleting your provider credentials."
                />
                <Toggle
                    checked={!!form.allow_course_context}
                    onChange={(v) => update({ allow_course_context: v })}
                    title="Let the AI see a student's course progress"
                    description="Enables answers about completion, pending chapters and repeated mistakes for the course a student selects."
                />
                <Toggle
                    checked={!!form.allow_quiz_generation}
                    onChange={(v) => update({ allow_quiz_generation: v })}
                    title="Allow AI-generated practice quizzes"
                    description="Students can say 'quiz me on…' and get an interactive quiz worth XP."
                />

                <div>
                    <label className="block text-sm font-medium text-surface-700 dark:text-surface-300 mb-1.5">
                        Custom instructions
                    </label>
                    <textarea
                        rows={4}
                        maxLength={2000}
                        value={form.custom_instructions || ''}
                        onChange={(e) => update({ custom_instructions: e.target.value })}
                        placeholder="e.g. Always answer in simple English with a Hindi summary. Refer to our NCERT-aligned notes."
                        className="input resize-y"
                    />
                    <p className="text-xs text-surface-500 mt-1.5">
                        Added to every conversation — keep it short, it is billed with each message.
                        {' '}
                        {(form.custom_instructions || '').length}/2000
                    </p>
                </div>
            </div>

            <div className="card p-6 space-y-4">
                <div className="flex items-center gap-2">
                    <AlertTriangle className="w-5 h-5 text-amber-500" />
                    <h3 className="text-lg font-bold text-surface-900 dark:text-white">Spend guardrails</h3>
                </div>
                <p className="text-sm text-surface-500">
                    These caps apply to your own provider key, so a burst of usage can never surprise you with a bill.
                </p>

                <div className="grid gap-4 sm:grid-cols-2">
                    <div>
                        <label className="block text-sm font-medium text-surface-700 dark:text-surface-300 mb-1.5">
                            Messages per student per day
                        </label>
                        <input
                            type="number"
                            min={0}
                            value={form.student_daily_message_limit ?? 50}
                            onChange={(e) =>
                                update({ student_daily_message_limit: parseInt(e.target.value, 10) || 0 })
                            }
                            className="input"
                        />
                        <p className="text-xs text-surface-500 mt-1.5">0 = unlimited.</p>
                    </div>
                    <div>
                        <label className="block text-sm font-medium text-surface-700 dark:text-surface-300 mb-1.5">
                            Monthly token budget
                        </label>
                        <input
                            type="number"
                            min={0}
                            step={1000}
                            value={form.monthly_token_budget ?? 0}
                            onChange={(e) => update({ monthly_token_budget: parseInt(e.target.value, 10) || 0 })}
                            className="input"
                        />
                        <p className="text-xs text-surface-500 mt-1.5">
                            0 = unlimited. ~700 tokens is a typical question and answer.
                        </p>
                    </div>
                </div>

                <button
                    onClick={() => saveMutation.mutate()}
                    disabled={saveMutation.isPending}
                    className="btn-primary"
                >
                    {saveMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                    Save settings
                </button>
            </div>
        </div>
    )
}

/* ---------------------------------------------------------------------------
 * Usage & cost
 * ------------------------------------------------------------------------- */

const StatCard = ({ icon: Icon, label, value, hint }) => (
    <div className="card p-5">
        <div className="flex items-center gap-2 text-surface-500">
            <Icon className="w-4 h-4" />
            <span className="text-xs font-semibold uppercase tracking-wide">{label}</span>
        </div>
        <p className="text-2xl font-bold text-surface-900 dark:text-white mt-2">{value}</p>
        {hint && <p className="text-xs text-surface-500 mt-1">{hint}</p>}
    </div>
)

const UsageReport = () => {
    const [days, setDays] = useState(30)
    const { data, isLoading } = useQuery({
        queryKey: ['aiUsage', days],
        queryFn: () => aiAdminService.getUsage(days),
    })

    if (isLoading) {
        return (
            <div className="flex items-center justify-center min-h-[200px]">
                <Loader2 className="w-8 h-8 animate-spin text-primary-500" />
            </div>
        )
    }

    return (
        <div className="space-y-6">
            <div className="flex items-center gap-2">
                {[7, 30, 90].map((d) => (
                    <button
                        key={d}
                        onClick={() => setDays(d)}
                        className={`px-3 py-1.5 rounded-lg text-sm font-semibold transition-colors ${days === d
                            ? 'bg-primary-500 text-white'
                            : 'bg-surface-100 dark:bg-surface-800 text-surface-600 dark:text-surface-300'}`}
                    >
                        Last {d} days
                    </button>
                ))}
            </div>

            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <StatCard icon={Sparkles} label="Messages" value={formatNumber(data?.messages)} />
                <StatCard
                    icon={Server}
                    label="Tokens"
                    value={formatNumber(data?.total_tokens)}
                    hint={`${formatNumber(data?.prompt_tokens)} in · ${formatNumber(data?.completion_tokens)} out`}
                />
                <StatCard
                    icon={BarChart3}
                    label="Estimated cost"
                    value={formatCost(data?.estimated_cost_usd)}
                    hint="Approximate — check your provider for the exact bill."
                />
                <StatCard
                    icon={CheckCircle2}
                    label="Active students"
                    value={formatNumber(data?.active_students)}
                    hint={data?.failures ? `${data.failures} failed request(s)` : 'No failed requests'}
                />
            </div>

            {data?.platform_grant_tokens > 0 && (
                <div className="card p-5">
                    <div className="flex items-center gap-2 mb-2">
                        <Gift className="w-5 h-5 text-primary-500" />
                        <h3 className="font-bold text-surface-900 dark:text-white">Included allowance this month</h3>
                    </div>
                    <p className="text-sm text-surface-500">
                        {formatNumber(data.platform_used_tokens)} of {formatNumber(data.platform_grant_tokens)} tokens
                        used · {formatNumber(data.platform_remaining_tokens)} remaining
                    </p>
                </div>
            )}

            <div className="card p-6">
                <h3 className="font-bold text-surface-900 dark:text-white mb-4">Breakdown by model</h3>
                {data?.by_model?.length ? (
                    <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                            <thead>
                                <tr className="text-left text-surface-500 border-b border-surface-200 dark:border-surface-800">
                                    <th className="py-2 font-semibold">Provider</th>
                                    <th className="py-2 font-semibold">Model</th>
                                    <th className="py-2 font-semibold text-right">Messages</th>
                                    <th className="py-2 font-semibold text-right">Tokens</th>
                                    <th className="py-2 font-semibold text-right">Est. cost</th>
                                </tr>
                            </thead>
                            <tbody>
                                {data.by_model.map((row) => (
                                    <tr
                                        key={`${row.provider}-${row.model}`}
                                        className="border-b border-surface-100 dark:border-surface-800/50 last:border-0"
                                    >
                                        <td className="py-2.5 capitalize">{row.provider.replace('_', ' ')}</td>
                                        <td className="py-2.5 font-mono text-xs">{row.model}</td>
                                        <td className="py-2.5 text-right">{formatNumber(row.messages)}</td>
                                        <td className="py-2.5 text-right">{formatNumber(row.tokens)}</td>
                                        <td className="py-2.5 text-right">
                                            {/* Included usage costs the academy nothing, so a
                                                figure here would only confuse. */}
                                            {row.estimated_cost_usd == null
                                                ? <span className="text-surface-400">Included</span>
                                                : formatCost(row.estimated_cost_usd)}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                ) : (
                    <p className="text-sm text-surface-500">No AI usage in this period yet.</p>
                )}
            </div>
        </div>
    )
}

/* ---------------------------------------------------------------------------
 * Root
 * ------------------------------------------------------------------------- */

const AIFeatures = () => {
    const [subTab, setSubTab] = useState('provider')

    const { data, isLoading, error } = useQuery({
        queryKey: ['aiProviders'],
        queryFn: () => aiAdminService.getProviders(),
    })

    if (isLoading) {
        return (
            <div className="flex items-center justify-center min-h-[240px]">
                <Loader2 className="w-8 h-8 animate-spin text-primary-500" />
            </div>
        )
    }

    if (error) {
        return (
            <div className="card p-8 text-center space-y-2">
                <AlertTriangle className="w-8 h-8 mx-auto text-rose-500" />
                <p className="text-surface-500 text-sm">Could not load AI settings. Please try again.</p>
            </div>
        )
    }

    return (
        <div className="space-y-6">
            <div className="flex items-center gap-2 border-b border-surface-200 dark:border-surface-800 overflow-x-auto">
                {SUB_TABS.map((st) => {
                    const active = subTab === st.id
                    return (
                        <button
                            key={st.id}
                            onClick={() => setSubTab(st.id)}
                            className={`inline-flex items-center gap-2 px-4 py-2.5 text-sm font-semibold border-b-2 -mb-px whitespace-nowrap transition-colors ${active
                                ? 'border-primary-500 text-primary-600 dark:text-primary-400'
                                : 'border-transparent text-surface-500 hover:text-surface-800 dark:hover:text-surface-200'}`}
                        >
                            <st.icon className="w-4 h-4" /> {st.label}
                        </button>
                    )
                })}
            </div>

            <AnimatePresence mode="wait">
                <motion.div
                    key={subTab}
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -8 }}
                    transition={{ duration: 0.15 }}
                >
                    {subTab === 'provider' && <ProviderSettings data={data} />}
                    {subTab === 'behaviour' && <BehaviourSettings data={data} />}
                    {subTab === 'usage' && <UsageReport />}
                </motion.div>
            </AnimatePresence>

            <div className="flex items-start gap-3 text-sm text-surface-500 px-1">
                <Info className="w-4 h-4 mt-0.5 shrink-0" />
                <p>
                    Your API key is encrypted before it is stored and is only ever used server-side. Students never see
                    it, and removing a provider deletes the stored key immediately.
                </p>
            </div>
        </div>
    )
}

export default AIFeatures
