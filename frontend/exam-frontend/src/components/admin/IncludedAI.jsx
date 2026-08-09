import { useQuery } from '@tanstack/react-query'
import { Gift, CheckCircle2, AlertTriangle, Loader2, ShieldCheck, Sparkles } from 'lucide-react'

import { aiAdminService } from '../../services/aiAdminService'

const formatNumber = (n) => new Intl.NumberFormat().format(Math.round(n || 0))

/**
 * The "you don't need an API key" panel.
 *
 * Most academy owners will never buy an OpenAI key, so this is the only AI
 * setup they should ever have to see — and there is nothing in it to
 * configure. We deliberately don't name the models behind the allowance:
 * naming them would turn our operational choices into a promise, and we'd no
 * longer be able to retire, reprice or fail over between models without an
 * academy noticing. An academy that wants a specific model connects its own
 * key below, which always takes precedence.
 */
const IncludedAI = ({ hasOwnKey }) => {
    const { data, isLoading } = useQuery({
        queryKey: ['ai-included'],
        queryFn: aiAdminService.getIncluded,
    })

    if (isLoading) {
        return (
            <div className="card p-6 flex justify-center">
                <Loader2 className="w-5 h-5 animate-spin text-surface-400" />
            </div>
        )
    }

    if (!data?.is_enabled) return null

    const percent = data.percent_used || 0
    // Tokens mean nothing to a non-technical admin; messages do.
    const messagesLeft = data.tokens_remaining != null
        ? Math.max(0, Math.round(data.tokens_remaining / 700))
        : null

    return (
        <div className="card p-5 space-y-4">
            <div className="flex items-start gap-3">
                <div className="w-11 h-11 rounded-xl bg-primary-50 text-primary-600 dark:bg-primary-900/30 dark:text-primary-400 flex items-center justify-center shrink-0">
                    <Gift className="w-5 h-5" />
                </div>
                <div className="flex-1 min-w-0">
                    <h3 className="font-bold text-surface-900 dark:text-white">
                        AI is included in your plan
                    </h3>
                    <p className="text-sm text-surface-500 mt-0.5">
                        {data.is_exhausted
                            ? 'This month’s included AI has run out. It resets at the start of next month — or connect your own key below to continue right away.'
                            : 'Everything AI-powered already works: the student assistant, practice quizzes and the course builder. There’s nothing to install and no API key to buy.'}
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

            {data.token_limit > 0 && (
                <div>
                    <div className="h-2 rounded-full bg-surface-100 dark:bg-surface-800 overflow-hidden">
                        <div
                            className={`h-full transition-all ${percent >= 100
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

            {data.model_count > 1 && !data.is_exhausted && (
                <div className="flex items-start gap-2 rounded-xl bg-surface-50 dark:bg-surface-800/50 p-3 text-xs text-surface-600 dark:text-surface-300">
                    <ShieldCheck className="w-4 h-4 shrink-0 mt-0.5 text-emerald-600" />
                    <span>
                        Backed by {data.model_count} AI models. If one is busy or unavailable we
                        switch to another automatically, so your students aren’t interrupted.
                    </span>
                </div>
            )}

            {hasOwnKey ? (
                <div className="flex items-start gap-2 rounded-xl bg-sky-50 dark:bg-sky-900/20 p-3 text-xs text-sky-800 dark:text-sky-300">
                    <Sparkles className="w-4 h-4 shrink-0 mt-0.5" />
                    <span>
                        You’ve connected your own AI key, so that’s used first. The included AI
                        stays as your safety net if it ever stops working.
                    </span>
                </div>
            ) : null}
        </div>
    )
}

export default IncludedAI
