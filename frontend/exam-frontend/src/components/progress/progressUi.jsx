// Shared presentation for My Progress (student page and teacher tab).

export const STATUS_TEXT = {
  weak: 'Needs work',
  in_progress: 'Getting there',
  strong: 'Strong',
  not_enough_data: 'Not enough data yet',
}

export const STATUS_CLASS = {
  weak: 'text-error-600 dark:text-error-400',
  in_progress: 'text-warning-600 dark:text-warning-400',
  strong: 'text-success-600 dark:text-success-400',
  not_enough_data: 'text-surface-400',
}

export const BAR_CLASS = {
  weak: 'bg-error-500',
  in_progress: 'bg-warning-500',
  strong: 'bg-success-500',
  not_enough_data: 'bg-surface-300 dark:bg-surface-600',
}

export const pct = (value) => (value == null ? '—' : `${Math.round(value * 100)}%`)

/** Four weekly points (nulls skipped) as a small line. */
export function Sparkline({ points }) {
  const coords = (points || [])
    .map((value, index) => (value == null ? null : [(index * 60) / 3, 20 - value * 18]))
    .filter(Boolean)
  if (coords.length === 0) {
    return <span className="text-xs text-surface-400">no recent answers</span>
  }
  return (
    <svg viewBox="0 0 60 20" className="w-16 h-5 text-primary-500" aria-label="4-week trend">
      {coords.length > 1 && (
        <polyline fill="none" stroke="currentColor" strokeWidth="2"
          points={coords.map(([x, y]) => `${x},${y}`).join(' ')} />
      )}
      {coords.map(([x, y]) => <circle key={x} cx={x} cy={y} r="1.8" fill="currentColor" />)}
    </svg>
  )
}

/** Mastery bar coloured by band; empty when there is not enough data. */
export function BandBar({ node }) {
  return (
    <div className="w-full h-2 rounded-full bg-surface-200 dark:bg-surface-700 overflow-hidden">
      {node.mastery != null && (
        <div
          className={`h-full rounded-full ${BAR_CLASS[node.status]}`}
          style={{ width: `${Math.round(node.mastery * 100)}%` }}
        />
      )}
    </div>
  )
}
