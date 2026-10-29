import { useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { STATUS_CLASS, STATUS_TEXT, pct } from './progressUi'

function Row({ node, depth }) {
  const [open, setOpen] = useState(false)
  const hasChildren = node.children?.length > 0
  return (
    <>
      <div
        className="flex items-center gap-3 py-2 border-b border-surface-100 dark:border-surface-700/50"
        style={{ paddingLeft: depth * 18 }}
      >
        <button
          type="button"
          disabled={!hasChildren}
          onClick={() => setOpen(!open)}
          className="w-5 shrink-0 text-surface-400 disabled:opacity-0"
          aria-label={open ? 'Collapse' : 'Expand'}
        >
          {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        </button>
        <span className="flex-1 min-w-0 truncate text-sm">{node.name}</span>
        <span className="hidden sm:block text-xs text-surface-400 w-28 text-right shrink-0">
          {node.total ? `${node.covered}/${node.total} covered` : ''}
        </span>
        <span className={`text-xs w-36 text-right shrink-0 ${STATUS_CLASS[node.status]}`}>
          {node.mastery != null ? `${pct(node.mastery)} · ${STATUS_TEXT[node.status]}` : STATUS_TEXT.not_enough_data}
        </span>
      </div>
      {open && node.children.map((child) => (
        <Row key={child.id} node={child} depth={depth + 1} />
      ))}
    </>
  )
}

/** Expandable subject breakdown: (sub-subject) → topic → subtopic. */
export default function RollupTree({ subject }) {
  if (!subject.children?.length) {
    return <p className="text-sm text-surface-400">No topics in this subject yet.</p>
  }
  return (
    <div>
      {subject.children.map((child) => <Row key={child.id} node={child} depth={0} />)}
    </div>
  )
}
