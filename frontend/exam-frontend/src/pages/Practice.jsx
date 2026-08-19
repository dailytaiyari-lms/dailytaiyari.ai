import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { practiceService } from '../services/practiceService'
import Loading from '../components/common/Loading'
import {
  Target,
  RefreshCw,
  Clock,
  AlertTriangle,
  Repeat,
  Shuffle,
  Sparkles,
  CheckCircle2,
  X,
} from 'lucide-react'

// Deficit-kind presentation: label + icon + accent colour.
const DEFICIT_META = {
  low_mastery: { label: 'Needs rebuilding', icon: Target, className: 'bg-danger-100 text-danger-700 dark:bg-danger-900/40 dark:text-danger-300' },
  retention: { label: 'Fading — refresh it', icon: Clock, className: 'bg-warning-100 text-warning-700 dark:bg-warning-900/40 dark:text-warning-300' },
  misconception: { label: 'Repeated mistake', icon: AlertTriangle, className: 'bg-danger-100 text-danger-700 dark:bg-danger-900/40 dark:text-danger-300' },
  transfer_gap: { label: 'Mix it together', icon: Shuffle, className: 'bg-primary-100 text-primary-700 dark:bg-primary-900/40 dark:text-primary-300' },
  cognitive_gap: { label: 'Apply it', icon: Repeat, className: 'bg-primary-100 text-primary-700 dark:bg-primary-900/40 dark:text-primary-300' },
  starter: { label: 'Starter set', icon: Sparkles, className: 'bg-surface-100 text-surface-700 dark:bg-surface-800 dark:text-surface-300' },
}

export const DeficitChip = ({ kind }) => {
  const meta = DEFICIT_META[kind] || DEFICIT_META.starter
  const Icon = meta.icon
  return (
    <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium ${meta.className}`}>
      <Icon size={12} />
      {meta.label}
    </span>
  )
}

export const MasteryBar = ({ value }) => (
  <div className="w-full h-2 rounded-full bg-surface-200 dark:bg-surface-700 overflow-hidden">
    <div
      className={`h-full rounded-full transition-all ${
        value >= 0.7 ? 'bg-success-500' : value >= 0.45 ? 'bg-warning-500' : 'bg-danger-500'
      }`}
      style={{ width: `${Math.round(value * 100)}%` }}
    />
  </div>
)

const LadderPreview = ({ ladder }) => {
  const parts = []
  if (ladder?.ladder_easy) parts.push(`${ladder.ladder_easy} warm-up`)
  if (ladder?.core) parts.push(`${ladder.core} core`)
  if (ladder?.ladder_stretch) parts.push(`${ladder.ladder_stretch} stretch`)
  if (ladder?.retention_interleave) parts.push(`${ladder.retention_interleave} review`)
  if (!parts.length) return null
  return <p className="text-xs text-surface-400">{parts.join(' · ')}</p>
}

const SuggestedCard = ({ set, onStart, onDismiss }) => (
  <div className="p-5 rounded-2xl bg-white dark:bg-surface-800 border border-surface-200 dark:border-surface-700 shadow-sm flex flex-col gap-3">
    <div className="flex items-start justify-between gap-2">
      <DeficitChip kind={set.deficit_kind} />
      <button
        onClick={() => onDismiss(set.id)}
        className="text-surface-400 hover:text-surface-600 dark:hover:text-surface-200"
        title="Dismiss this suggestion"
      >
        <X size={16} />
      </button>
    </div>
    <div>
      <p className="font-semibold">{set.concepts?.join(', ') || set.course_name}</p>
      <p className="text-sm text-surface-500 mt-1">{set.reason_text}</p>
    </div>
    <div className="flex items-center justify-between mt-auto pt-2">
      <LadderPreview ladder={set.ladder} />
      <button
        onClick={() => onStart(set.id)}
        className="px-4 py-2 rounded-xl bg-primary-500 text-white text-sm font-medium hover:bg-primary-600 transition-colors"
      >
        Start {set.item_count} questions
      </button>
    </div>
  </div>
)

const HistoryRow = ({ set }) => (
  <div className="flex items-center justify-between p-4 rounded-xl bg-white dark:bg-surface-800 border border-surface-200 dark:border-surface-700">
    <div className="flex items-center gap-3 min-w-0">
      <CheckCircle2 size={18} className="text-success-500 shrink-0" />
      <div className="min-w-0">
        <p className="text-sm font-medium truncate">{set.concepts?.join(', ') || 'Practice set'}</p>
        <p className="text-xs text-surface-400">
          {set.completed_at ? new Date(set.completed_at).toLocaleDateString() : ''}
        </p>
      </div>
    </div>
    <div className="text-sm font-semibold shrink-0">
      {set.score_correct}/{set.score_total}
      {set.xp_awarded > 0 && <span className="ml-2 text-xs text-warning-500">+{set.xp_awarded} XP</span>}
    </div>
  </div>
)

const Practice = () => {
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const { data: suggested, isLoading } = useQuery({
    queryKey: ['practiceSets', 'suggested'],
    queryFn: () => practiceService.getSets('suggested,in_progress'),
  })
  const { data: completed } = useQuery({
    queryKey: ['practiceSets', 'completed'],
    queryFn: () => practiceService.getSets('completed'),
  })
  const { data: mastery } = useQuery({
    queryKey: ['practiceMastery'],
    queryFn: () => practiceService.getMastery(),
  })

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['practiceSets'] })

  const refreshMutation = useMutation({
    mutationFn: practiceService.refreshSuggestions,
    onSuccess: invalidate,
  })
  const dismissMutation = useMutation({
    mutationFn: practiceService.dismissSet,
    onSuccess: invalidate,
  })

  if (isLoading) return <Loading fullScreen />

  const sets = (suggested?.results ?? suggested ?? [])
  const history = (completed?.results ?? completed ?? []).slice(0, 10)
  const masteryRows = (mastery ?? []).filter((row) => row.confidence !== 'low').slice(0, 12)

  return (
    <div className="space-y-8">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-display font-bold">Practice</h1>
          <p className="text-surface-500 mt-1">
            Sets picked for you from what your quizzes and mock tests reveal
          </p>
        </div>
        <button
          onClick={() => refreshMutation.mutate()}
          disabled={refreshMutation.isPending}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-surface-100 dark:bg-surface-800 text-sm font-medium hover:bg-surface-200 dark:hover:bg-surface-700 transition-colors disabled:opacity-50"
        >
          <RefreshCw size={15} className={refreshMutation.isPending ? 'animate-spin' : ''} />
          Refresh suggestions
        </button>
      </div>

      {/* Suggested sets */}
      <section>
        <h2 className="text-lg font-semibold mb-3">Suggested for you</h2>
        {sets.length === 0 ? (
          <div className="p-8 rounded-2xl bg-surface-50 dark:bg-surface-800/50 border border-dashed border-surface-300 dark:border-surface-700 text-center text-surface-500">
            <Sparkles className="mx-auto mb-2" />
            <p className="font-medium">Nothing to practise right now.</p>
            <p className="text-sm mt-1">
              Complete a quiz or mock test and suggestions will appear here as the
              system learns what you know.
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {sets.map((set) => (
              <SuggestedCard
                key={set.id}
                set={set}
                onStart={(id) => navigate(`/practice/${id}`)}
                onDismiss={(id) => dismissMutation.mutate(id)}
              />
            ))}
          </div>
        )}
      </section>

      {/* Mastery map */}
      {masteryRows.length > 0 && (
        <section>
          <h2 className="text-lg font-semibold mb-3">My understanding</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {masteryRows.map((row) => (
              <div
                key={row.concept_id}
                className="p-4 rounded-xl bg-white dark:bg-surface-800 border border-surface-200 dark:border-surface-700"
              >
                <div className="flex items-center justify-between mb-2 gap-2">
                  <p className="text-sm font-medium truncate">{row.concept}</p>
                  <span className="text-xs text-surface-400 shrink-0">
                    {Math.round(row.mastery * 100)}%
                  </span>
                </div>
                <MasteryBar value={row.mastery} />
                {row.flags?.includes('fading_retention') && (
                  <p className="text-xs text-warning-500 mt-1.5">Fading — worth a refresh</p>
                )}
                {row.flags?.includes('weak_transfer') && (
                  <p className="text-xs text-primary-500 mt-1.5">
                    Strong alone, harder in combination
                  </p>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* History */}
      {history.length > 0 && (
        <section>
          <h2 className="text-lg font-semibold mb-3">Completed</h2>
          <div className="space-y-2">
            {history.map((set) => (
              <HistoryRow key={set.id} set={set} />
            ))}
          </div>
        </section>
      )}
    </div>
  )
}

export default Practice
