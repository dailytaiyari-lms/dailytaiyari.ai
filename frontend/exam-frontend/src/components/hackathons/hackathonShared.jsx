import { useEffect, useMemo, useState } from 'react'
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import {
  Brain, Code2, FlaskConical, UploadCloud, Trophy, Clock, CheckCircle2,
  Lock, XCircle, Hourglass, CircleDot,
} from 'lucide-react'

// ── content ──────────────────────────────────────────────────────────────────
const looksLikeHtml = (s) => /<\/?[a-z][\s\S]*>/i.test(s || '')

/**
 * Renders hackathon prose. Organisers (and the AI studio) may author either rich
 * HTML or Markdown, so we detect which, convert, then sanitize before rendering.
 */
export const RichContent = ({ content, className = '' }) => {
  const html = useMemo(() => {
    const raw = content || ''
    if (!raw.trim()) return ''
    const asHtml = looksLikeHtml(raw) ? raw : marked.parse(raw, { breaks: true, gfm: true })
    return DOMPurify.sanitize(asHtml, { ADD_ATTR: ['target', 'rel'] })
  }, [content])

  if (!html) return null
  return (
    <div
      className={`prose prose-sm sm:prose-base dark:prose-invert max-w-none prose-p:my-2.5 prose-headings:mt-5 prose-headings:mb-2 prose-li:my-1 prose-a:text-primary-600 dark:prose-a:text-primary-400 ${className}`}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}

// ── vocabulary ───────────────────────────────────────────────────────────────
export const STAGE_TYPES = [
  {
    value: 'quiz', label: 'Quiz round', icon: Brain,
    tint: 'bg-violet-50 text-violet-700 dark:bg-violet-900/20 dark:text-violet-300',
    blurb: 'Timed MCQ / numerical screening paper',
  },
  {
    value: 'coding', label: 'Coding round', icon: Code2,
    tint: 'bg-sky-50 text-sky-700 dark:bg-sky-900/20 dark:text-sky-300',
    blurb: 'Judge-evaluated programming problems',
  },
  {
    value: 'lab', label: 'Hands-on lab', icon: FlaskConical,
    tint: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-300',
    blurb: 'A guided notebook, auto-graded on completion',
  },
  {
    value: 'submission', label: 'Project submission', icon: UploadCloud,
    tint: 'bg-amber-50 text-amber-700 dark:bg-amber-900/20 dark:text-amber-300',
    blurb: 'Files, repo and demo links reviewed by judges',
  },
]

export const stageMeta = (type) => STAGE_TYPES.find((s) => s.value === type) || STAGE_TYPES[0]

export const QUALIFICATION_MODES = [
  { value: 'cutoff', label: 'Score cut-off', blurb: 'Everyone at or above the cut-off advances' },
  { value: 'top_n', label: 'Top N', blurb: 'The highest N scorers advance' },
  { value: 'manual', label: 'Manual shortlist', blurb: 'You pick who advances, one by one' },
  { value: 'all', label: 'Everyone advances', blurb: 'A participation round with no elimination' },
]

export const MODES = [
  { value: 'online', label: 'Online' },
  { value: 'offline', label: 'In person' },
  { value: 'hybrid', label: 'Hybrid' },
]

export const DIFFICULTIES = [
  { value: 'beginner', label: 'Beginner' },
  { value: 'intermediate', label: 'Intermediate' },
  { value: 'advanced', label: 'Advanced' },
  { value: 'all_levels', label: 'All levels' },
]

export const labelOf = (options, value, fallback = '') =>
  options.find((o) => o.value === value)?.label || fallback

// ── registration state ───────────────────────────────────────────────────────
export const REGISTRATION_STATES = {
  open: {
    label: 'Registrations open',
    tint: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-300',
  },
  opening_soon: {
    label: 'Opening soon',
    tint: 'bg-sky-50 text-sky-700 dark:bg-sky-900/20 dark:text-sky-300',
  },
  not_open: {
    label: 'Not open yet',
    tint: 'bg-surface-100 text-surface-600 dark:bg-surface-800 dark:text-surface-300',
  },
  closed: {
    label: 'Registrations closed',
    tint: 'bg-surface-100 text-surface-500 dark:bg-surface-800 dark:text-surface-400',
  },
  full: {
    label: 'Full',
    tint: 'bg-amber-50 text-amber-700 dark:bg-amber-900/20 dark:text-amber-300',
  },
}

export const registrationMeta = (state) =>
  REGISTRATION_STATES[state] || REGISTRATION_STATES.closed

export const TIMING_STATES = {
  not_open: { label: 'Not scheduled', icon: CircleDot, tint: 'text-surface-400' },
  upcoming: { label: 'Upcoming', icon: Clock, tint: 'text-sky-500' },
  live: { label: 'Live now', icon: CircleDot, tint: 'text-emerald-500' },
  ended: { label: 'Ended', icon: CheckCircle2, tint: 'text-surface-400' },
}

export const PARTICIPATION_STATES = {
  locked: {
    label: 'Locked', icon: Lock,
    tint: 'bg-surface-100 text-surface-500 dark:bg-surface-800 dark:text-surface-400',
  },
  pending: {
    label: 'Not started', icon: Hourglass,
    tint: 'bg-surface-100 text-surface-600 dark:bg-surface-800 dark:text-surface-300',
  },
  in_progress: {
    label: 'In progress', icon: CircleDot,
    tint: 'bg-sky-50 text-sky-700 dark:bg-sky-900/20 dark:text-sky-300',
  },
  submitted: {
    label: 'Submitted', icon: CheckCircle2,
    tint: 'bg-violet-50 text-violet-700 dark:bg-violet-900/20 dark:text-violet-300',
  },
  evaluated: {
    label: 'Evaluated', icon: CheckCircle2,
    tint: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-300',
  },
}

export const QUALIFICATION_BADGES = {
  qualified: {
    label: 'Shortlisted', icon: Trophy,
    tint: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-300',
  },
  not_qualified: {
    label: 'Not shortlisted', icon: XCircle,
    tint: 'bg-rose-50 text-rose-700 dark:bg-rose-900/20 dark:text-rose-300',
  },
  undecided: {
    label: 'Awaiting results', icon: Hourglass,
    tint: 'bg-surface-100 text-surface-600 dark:bg-surface-800 dark:text-surface-300',
  },
}

// ── formatting ───────────────────────────────────────────────────────────────
export const formatDate = (value, opts = {}) => {
  if (!value) return ''
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleDateString(undefined, {
    day: 'numeric', month: 'short', year: 'numeric', ...opts,
  })
}

export const formatDateTime = (value) => {
  if (!value) return ''
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleString(undefined, {
    day: 'numeric', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit',
  })
}

export const formatPrize = (hackathon) => {
  const amount = Number(hackathon?.prize_pool || 0)
  if (!amount) return ''
  const currency = hackathon.prize_currency || 'INR'
  try {
    return new Intl.NumberFormat(undefined, {
      style: 'currency', currency, maximumFractionDigits: 0,
    }).format(amount)
  } catch {
    return `${currency} ${amount.toLocaleString()}`
  }
}

export const formatBytes = (bytes) => {
  const n = Number(bytes || 0)
  if (!n) return ''
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

/** Groups a hackathon into the three tabs students actually think in. */
export const bucketOf = (hackathon) => {
  const now = Date.now()
  const start = hackathon.starts_at ? new Date(hackathon.starts_at).getTime() : null
  const end = hackathon.ends_at ? new Date(hackathon.ends_at).getTime() : null
  if (end && end < now) return 'past'
  if (start && start > now) return 'upcoming'
  if (start && start <= now) return 'live'
  return hackathon.registration_state === 'closed' ? 'past' : 'upcoming'
}

// ── countdown ────────────────────────────────────────────────────────────────
const pad = (n) => String(n).padStart(2, '0')

/** Live countdown to a deadline. Returns null when there is no target. */
export const useCountdown = (target) => {
  const targetMs = target ? new Date(target).getTime() : null
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (!targetMs) return undefined
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [targetMs])

  if (!targetMs || Number.isNaN(targetMs)) return null
  const diff = targetMs - now
  if (diff <= 0) return { expired: true, days: 0, hours: 0, minutes: 0, seconds: 0 }
  return {
    expired: false,
    days: Math.floor(diff / 86400000),
    hours: Math.floor((diff % 86400000) / 3600000),
    minutes: Math.floor((diff % 3600000) / 60000),
    seconds: Math.floor((diff % 60000) / 1000),
  }
}

export const Countdown = ({ target, label = 'Closes in', compact = false }) => {
  const t = useCountdown(target)
  if (!t) return null
  if (t.expired) {
    return <span className="text-sm text-surface-400">{label.replace(/ in$/, '')} passed</span>
  }
  if (compact) {
    return (
      <span className="tabular-nums font-medium">
        {t.days > 0 ? `${t.days}d ` : ''}{pad(t.hours)}:{pad(t.minutes)}:{pad(t.seconds)}
      </span>
    )
  }
  const cells = [
    { value: t.days, unit: 'days' },
    { value: t.hours, unit: 'hrs' },
    { value: t.minutes, unit: 'min' },
    { value: t.seconds, unit: 'sec' },
  ]
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-surface-400 mb-1.5">{label}</div>
      <div className="flex items-center gap-2">
        {cells.map((cell) => (
          <div
            key={cell.unit}
            className="text-center min-w-[3rem] rounded-xl bg-surface-900/5 dark:bg-white/10 px-2.5 py-1.5"
          >
            <div className="text-xl font-bold tabular-nums leading-none">{pad(cell.value)}</div>
            <div className="text-[10px] uppercase tracking-wide text-surface-400 mt-1">
              {cell.unit}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

/** Countdown for a round in progress; fires `onExpire` exactly once. */
export const useStageTimer = (endsAt, onExpire) => {
  const t = useCountdown(endsAt)
  const [fired, setFired] = useState(false)
  const expired = Boolean(t?.expired)
  useEffect(() => {
    if (expired && !fired) {
      setFired(true)
      onExpire?.()
    }
  }, [expired, fired, onExpire])
  return t
}
