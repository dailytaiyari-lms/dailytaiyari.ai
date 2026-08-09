import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { Gift, CheckCircle2, AlertTriangle, Loader2, Star, Sparkles } from 'lucide-react'

import { aiAdminService } from '../../services/aiAdminService'

const formatNumber = (n) => new Intl.NumberFormat().format(Math.round(n || 0))

/**
 * The "you don't need an API key" panel.
 *
 * Most academy owners will never obtain an OpenAI key, so when we've granted
 * them models this is the only AI setup they ever have to see: pick which
 * models your staff may use, star a default, and watch the allowance. It shows
 * an allowance in messages rather than tokens because "412,000 tokens" means
 * nothing to a non-technical admin.
 */
const IncludedModels = ({ hasOwnKey }) => {
    const queryClient = useQueryClient()
    const { data, isLoading } = useQuery({
        queryKey: ['ai-included-models'],
        queryFn: aiAdminService.getIncludedModels,
    })

    const [enabled, setEnabled] = useState([])
    const [defaultId, setDefaultId] = useState('')

    // Seed once. A background refetch (window focus) must not wipe out edits
    // the admin hasn't saved yet.
    const seeded = useRef(false)
    useEffect(() => {
        if (!data || seeded.current) return
        seeded.current = true
        setEnabled(data.enabled_model_ids || [])
        setDefaultId(data.default_model_id || '')
    }, [data])

    const save = useMutation({
        mutationFn: aiAdminService.saveIncludedModels,
        onSuccess: (result) => {
            queryClient.setQueryData(['ai-included-models'], result)
            setEnabled(result.enabled_model_ids || [])
            setDefaultId(result.default_model_id || '')
            queryClient.invalidateQueries({ queryKey: ['aiProviders'] })
            toast.success('AI models updated')
        },
        onError: (error) => {
            const body = error?.response?.data
            toast.error(body ? Object.values(body).flat()[0] : 'Could not save')
        },
    })

    const models = data?.models || []
    // An empty selection means "all of them" server-side, which is the right
    // default but would render as nothing being ticked.
    const effectiveEnabled = useMemo(
        () => (enabled.length ? enabled : models.map((m) => m.id)),
        [enabled, models],
    )

    const dirty = useMemo(() => {
        if (!data) return false
        const sameDefault = (data.default_model_id || '') === defaultId
        const before = [...(data.enabled_model_ids || [])].sort().join(',')
        const now = [...enabled].sort().join(',')
        return !sameDefault || before !== now
    }, [data, enabled, defaultId])

    if (isLoading) {
        return (
            <div className="card p-6 flex justify-center">
                <Loader2 className="w-5 h-5 animate-spin text-surface-400" />
            </div>
        )
    }

    if (!data?.is_enabled) return null

    const toggle = (id) => {
        const next = effectiveEnabled.includes(id)
            ? effectiveEnabled.filter((m) => m !== id)
            : [...effectiveEnabled, id]
        // Leaving nothing selected would silently mean "all" — confusing, so
        // we refuse the last removal instead.
        if (next.length === 0) {
            toast.error('Keep at least one model enabled')
            return
        }
        setEnabled(next)
        if (!next.includes(defaultId)) setDefaultId('')
    }

    // When the admin hasn't picked a default, star whichever model actually
    // gets used so the panel never looks like nothing is selected.
    const shownDefault = defaultId || data.effective_model_id || ''

    const percent = data.percent_used || 0
    const messagesLeft = data.tokens_remaining != null
        ? Math.max(0, Math.round(data.tokens_remaining / 700))
        : null

    return (
        <div className="card p-5 space-y-5">
            <div className="flex items-start gap-3">
                <div className="w-11 h-11 rounded-xl bg-primary-50 text-primary-600 dark:bg-primary-900/30 dark:text-primary-400 flex items-center justify-center shrink-0">
                    <Gift className="w-5 h-5" />
                </div>
                <div className="flex-1 min-w-0">
                    <h3 className="font-bold text-surface-900 dark:text-white">
                        Included AI — no setup needed
                    </h3>
                    <p className="text-sm text-surface-500 mt-0.5">
                        {data.is_exhausted
                            ? 'This month’s included AI has run out. It resets at the start of next month, or you can connect your own key below to continue right away.'
                            : 'Your plan includes ready-to-use AI. Pick which models your academy uses — there’s nothing to install and no API key to buy.'}
                    </p>
                </div>
                {data.is_available ? (
                    <span className="hidden sm:inline-flex items-center gap-1 text-xs font-medium text-emerald-600 shrink-0">
                        <CheckCircle2 className="w-3.5 h-3.5" /> Active
                    </span>
                ) : (
                    <span className="hidden sm:inline-flex items-center gap-1 text-xs font-medium text-amber-600 shrink-0">
                        <AlertTriangle className="w-3.5 h-3.5" /> Paused
                    </span>
                )}
            </div>

            {hasOwnKey ? (
                <div className="flex items-start gap-2 rounded-xl bg-sky-50 dark:bg-sky-900/20 p-3 text-xs text-sky-800 dark:text-sky-300">
                    <Sparkles className="w-4 h-4 shrink-0 mt-0.5" />
                    <span>
                        You’ve connected your own AI key, which is used first. These included models
                        are your safety net if that key stops working.
                    </span>
                </div>
            ) : null}

            {data.token_limit > 0 && (
                <div>
                    <div className="h-2 rounded-full bg-surface-100 dark:bg-surface-800 overflow-hidden">
                        <div
                            className={`h-full ${percent >= 100
                                ? 'bg-red-500'
                                : percent >= 80
                                    ? 'bg-amber-500'
                                    : 'bg-gradient-to-r from-primary-500 to-primary-600'}`}
                            style={{ width: `${Math.min(100, percent)}%` }}
                        />
                    </div>
                    <p className="text-xs text-surface-500 mt-1.5">
                        {percent}% of this month’s allowance used
                        {messagesLeft != null
                            ? ` · roughly ${formatNumber(messagesLeft)} student messages left`
                            : ''}
                    </p>
                </div>
            )}

            {models.length > 0 && (
                <div className="space-y-2">
                    <p className="text-xs font-semibold uppercase tracking-wide text-surface-400">
                        Models your academy can use
                    </p>
                    {models.map((model) => {
                        const isOn = effectiveEnabled.includes(model.id)
                        const isDefault = shownDefault === model.id
                        return (
                            <div
                                key={model.id}
                                className={`flex items-center gap-3 rounded-xl border p-3 transition-colors ${isOn
                                    ? 'border-primary-200 bg-primary-50/40 dark:border-primary-900 dark:bg-primary-900/10'
                                    : 'border-surface-200 dark:border-surface-700'}`}
                            >
                                <input
                                    type="checkbox"
                                    checked={isOn}
                                    onChange={() => toggle(model.id)}
                                    className="w-4 h-4 rounded border-surface-300 shrink-0"
                                />
                                <div className="flex-1 min-w-0">
                                    <p className="text-sm font-medium text-surface-900 dark:text-white truncate">
                                        {model.display_label}
                                    </p>
                                    {model.description ? (
                                        <p className="text-xs text-surface-500 truncate">{model.description}</p>
                                    ) : null}
                                </div>
                                <button
                                    type="button"
                                    onClick={() => isOn && setDefaultId(model.id)}
                                    disabled={!isOn}
                                    title={isDefault ? 'This is your default model' : 'Make this the default'}
                                    className={`shrink-0 inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors ${isDefault
                                        ? 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400'
                                        : 'text-surface-400 hover:bg-surface-100 dark:hover:bg-surface-800 disabled:opacity-40'}`}
                                >
                                    <Star className={`w-3.5 h-3.5 ${isDefault ? 'fill-current' : ''}`} />
                                    {isDefault ? 'Default' : 'Set default'}
                                </button>
                            </div>
                        )
                    })}
                </div>
            )}

            {dirty && (
                <div className="flex items-center justify-end gap-2 pt-1">
                    <button
                        type="button"
                        onClick={() => {
                            setEnabled(data.enabled_model_ids || [])
                            setDefaultId(data.default_model_id || '')
                        }}
                        className="btn-ghost text-sm"
                    >
                        Cancel
                    </button>
                    <button
                        type="button"
                        disabled={save.isPending}
                        onClick={() =>
                            save.mutate({
                                // Selecting everything is the same as no filter,
                                // so store it as one and let the grant grow.
                                enabled_model_ids:
                                    effectiveEnabled.length === models.length ? [] : effectiveEnabled,
                                default_model_id: defaultId || null,
                            })
                        }
                        className="btn-primary text-sm inline-flex items-center gap-2"
                    >
                        {save.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
                        Save changes
                    </button>
                </div>
            )}
        </div>
    )
}

export default IncludedModels
