import { LABEL_COLOR, LABEL_ORDER, LABEL_TEXT } from './labels'

/** One stacked bar: the share of each diagnosis label for a question. */
export default function LabelBar({ counts, total }) {
  if (!total) return <div className="h-2.5 rounded-full bg-surface-100 dark:bg-surface-700" />
  return (
    <div className="flex h-2.5 rounded-full overflow-hidden bg-surface-100 dark:bg-surface-700">
      {LABEL_ORDER.filter((label) => counts[label]).map((label) => (
        <div
          key={label}
          className={LABEL_COLOR[label]}
          style={{ width: `${(counts[label] / total) * 100}%` }}
          title={`${LABEL_TEXT[label]}: ${counts[label]}`}
        />
      ))}
    </div>
  )
}

export function LabelLegend() {
  return (
    <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-surface-500">
      {LABEL_ORDER.map((label) => (
        <span key={label} className="inline-flex items-center gap-1">
          <span className={`w-2.5 h-2.5 rounded-sm ${LABEL_COLOR[label]}`} /> {LABEL_TEXT[label]}
        </span>
      ))}
    </div>
  )
}
