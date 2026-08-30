import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams, Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { motion, AnimatePresence } from 'framer-motion'
import toast from 'react-hot-toast'
import {
  Trophy, ArrowLeft, MapPin, CalendarDays, Users, Clock, Share2, ChevronRight,
  Sparkles, Gift, ScrollText, HelpCircle, Layers, Medal, LogIn, Check, X,
  ExternalLink, Loader2, BookOpen, Lock, PartyPopper, Info, Mail,
} from 'lucide-react'
import { hackathonService } from '../services/hackathonService'
import { useAuthStore } from '../context/authStore'
import { useTenantStore } from '../context/tenantStore'
import Loading from '../components/common/Loading'
import {
  RichContent, Countdown, stageMeta, registrationMeta, labelOf, formatDate,
  formatDateTime, formatPrize, MODES, DIFFICULTIES, TIMING_STATES,
  PARTICIPATION_STATES, QUALIFICATION_BADGES,
} from '../components/hackathons/hackathonShared'

const TABS = [
  { id: 'overview', label: 'Overview', icon: Info },
  { id: 'rounds', label: 'Rounds', icon: Layers },
  { id: 'prizes', label: 'Prizes', icon: Gift },
  { id: 'rules', label: 'Rules', icon: ScrollText },
  { id: 'faq', label: 'FAQ', icon: HelpCircle },
]

// ─────────────────────────────────────────────────────────────────────────────
// Registration
// ─────────────────────────────────────────────────────────────────────────────

const RegisterModal = ({ hackathon, user, profile, onClose, onSubmit, isSaving }) => {
  const [form, setForm] = useState({
    full_name: user?.full_name || '',
    email: user?.email || '',
    phone: profile?.phone || '',
    institution: profile?.school_name || '',
    year_of_study: profile?.grade || '',
    skills: '',
    github_url: '',
    linkedin_url: '',
    portfolio_url: '',
    motivation: '',
  })
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }))

  const submit = (e) => {
    e.preventDefault()
    if (!form.full_name.trim() || !form.email.trim()) {
      toast.error('Name and email are required.')
      return
    }
    onSubmit({
      ...form,
      skills: form.skills.split(',').map((s) => s.trim()).filter(Boolean),
    })
  }

  return (
    <div className="fixed inset-0 z-[70] flex items-start sm:items-center justify-center p-4 bg-black/60 overflow-y-auto">
      <motion.form
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        onSubmit={submit}
        className="card w-full max-w-2xl my-8 p-0 overflow-hidden"
      >
        <div className="flex items-start justify-between gap-4 p-5 border-b border-surface-100 dark:border-surface-800">
          <div>
            <h2 className="text-lg font-semibold">Register for {hackathon.title}</h2>
            <p className="text-sm text-surface-500 mt-0.5">
              These details go to the organisers and appear on the judging sheet.
            </p>
          </div>
          <button type="button" onClick={onClose} className="btn-icon shrink-0">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-5 space-y-4 max-h-[60vh] overflow-y-auto">
          <div className="grid sm:grid-cols-2 gap-4">
            <label className="block">
              <span className="text-sm font-medium">Full name *</span>
              <input className="input mt-1" value={form.full_name} onChange={set('full_name')} required />
            </label>
            <label className="block">
              <span className="text-sm font-medium">Email *</span>
              <input type="email" className="input mt-1" value={form.email} onChange={set('email')} required />
            </label>
            <label className="block">
              <span className="text-sm font-medium">Phone</span>
              <input className="input mt-1" value={form.phone} onChange={set('phone')} />
            </label>
            <label className="block">
              <span className="text-sm font-medium">Institution</span>
              <input className="input mt-1" value={form.institution} onChange={set('institution')} />
            </label>
            <label className="block">
              <span className="text-sm font-medium">Year / class</span>
              <input className="input mt-1" value={form.year_of_study} onChange={set('year_of_study')} />
            </label>
            <label className="block">
              <span className="text-sm font-medium">Skills</span>
              <input
                className="input mt-1"
                placeholder="python, react, ml"
                value={form.skills}
                onChange={set('skills')}
              />
              <span className="text-xs text-surface-400">Comma separated</span>
            </label>
            <label className="block">
              <span className="text-sm font-medium">GitHub</span>
              <input className="input mt-1" placeholder="https://github.com/…" value={form.github_url} onChange={set('github_url')} />
            </label>
            <label className="block">
              <span className="text-sm font-medium">LinkedIn</span>
              <input className="input mt-1" placeholder="https://linkedin.com/in/…" value={form.linkedin_url} onChange={set('linkedin_url')} />
            </label>
          </div>
          <label className="block">
            <span className="text-sm font-medium">Why do you want to take part?</span>
            <textarea
              className="input mt-1 min-h-[90px]"
              value={form.motivation}
              onChange={set('motivation')}
              placeholder="A couple of lines is plenty."
            />
          </label>
        </div>

        <div className="flex items-center justify-end gap-2 p-5 border-t border-surface-100 dark:border-surface-800">
          <button type="button" onClick={onClose} className="btn-secondary">Cancel</button>
          <button type="submit" className="btn-primary" disabled={isSaving}>
            {isSaving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
            Confirm registration
          </button>
        </div>
      </motion.form>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Rounds
// ─────────────────────────────────────────────────────────────────────────────

const StageCard = ({ stage, index, progress, hackathonId, isRegistered, isLast }) => {
  const meta = stageMeta(stage.stage_type)
  const Icon = meta.icon
  const timing = TIMING_STATES[stage.timing_state] || TIMING_STATES.not_open
  const TimingIcon = timing.icon
  const state = PARTICIPATION_STATES[progress?.status] || PARTICIPATION_STATES.pending
  const StateIcon = state.icon
  const qualification = progress?.results_published
    ? QUALIFICATION_BADGES[progress?.qualification]
    : null
  const QualIcon = qualification?.icon

  const canEnter = isRegistered && progress?.eligible && stage.timing_state !== 'not_open'
  const notShortlisted = progress?.qualification === 'not_qualified' && progress?.results_published

  return (
    <div className="relative pl-10">
      {!isLast && (
        <span className="absolute left-[15px] top-10 bottom-0 w-px bg-surface-200 dark:bg-surface-700" />
      )}
      <span
        className={`absolute left-0 top-1 w-8 h-8 rounded-xl flex items-center justify-center ${meta.tint}`}
      >
        <Icon className="w-4 h-4" />
      </span>

      <div className="card p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-xs uppercase tracking-wide text-surface-400">
                Round {index + 1}
              </span>
              <span className={`badge ${meta.tint}`}>{meta.label}</span>
              <span className={`inline-flex items-center gap-1 text-xs ${timing.tint}`}>
                <TimingIcon className="w-3 h-3" />{timing.label}
              </span>
            </div>
            <h3 className="font-semibold text-lg mt-1">{stage.title}</h3>
          </div>

          {isRegistered && (
            <div className="flex items-center gap-2 shrink-0">
              {qualification && (
                <span className={`badge ${qualification.tint}`}>
                  <QualIcon className="w-3 h-3" />{qualification.label}
                </span>
              )}
              <span className={`badge ${state.tint}`}>
                <StateIcon className="w-3 h-3" />{state.label}
              </span>
            </div>
          )}
        </div>

        {stage.description && (
          <RichContent content={stage.description} className="mt-3 text-surface-600 dark:text-surface-300" />
        )}

        <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 mt-3 text-xs text-surface-500">
          {stage.duration_minutes > 0 && (
            <span className="inline-flex items-center gap-1">
              <Clock className="w-3.5 h-3.5" />{stage.duration_minutes} min
            </span>
          )}
          {stage.items_count != null && (
            <span>{stage.items_count} question{stage.items_count === 1 ? '' : 's'}</span>
          )}
          {stage.total_marks > 0 && <span>{stage.total_marks} marks</span>}
          {stage.starts_at && (
            <span className="inline-flex items-center gap-1">
              <CalendarDays className="w-3.5 h-3.5" />{formatDateTime(stage.starts_at)}
            </span>
          )}
        </div>

        {/* Result / action row */}
        {isRegistered && (
          <div className="mt-4 pt-4 border-t border-surface-100 dark:border-surface-800">
            {notShortlisted ? (
              <div className="rounded-xl bg-rose-50 dark:bg-rose-900/15 border border-rose-100 dark:border-rose-900/30 p-4">
                <div className="flex items-start gap-3">
                  <X className="w-5 h-5 text-rose-500 shrink-0 mt-0.5" />
                  <div>
                    <p className="font-medium text-rose-700 dark:text-rose-300">
                      You weren't shortlisted for the next round
                    </p>
                    <p className="text-sm text-rose-600/80 dark:text-rose-300/70 mt-1">
                      Thank you for taking part — your effort here still counts towards the
                      overall leaderboard. Keep an eye out for the next hackathon.
                    </p>
                    {progress?.score != null && (
                      <p className="text-sm text-rose-600/80 dark:text-rose-300/70 mt-2">
                        Your score: <strong>{progress.score}</strong> / {progress.max_score}
                      </p>
                    )}
                  </div>
                </div>
              </div>
            ) : (
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="text-sm text-surface-500">
                  {progress?.results_published && progress?.score != null ? (
                    <span>
                      Score <strong className="text-surface-800 dark:text-surface-100">
                        {progress.score}
                      </strong> / {progress.max_score}
                      {progress.rank ? ` · Rank #${progress.rank}` : ''}
                    </span>
                  ) : progress?.status === 'submitted' ? (
                    'Submitted — results will be published by the organisers.'
                  ) : !progress?.eligible ? (
                    <span className="inline-flex items-center gap-1.5">
                      <Lock className="w-3.5 h-3.5" />
                      Unlocks when you clear the previous round
                    </span>
                  ) : stage.timing_state === 'upcoming' ? (
                    <span>Opens {formatDateTime(stage.starts_at)}</span>
                  ) : (
                    'Ready when you are.'
                  )}
                </div>
                {canEnter && (
                  <Link
                    to={`/hackathons/${hackathonId}/rounds/${stage.id}`}
                    className="btn-primary"
                  >
                    {progress?.status === 'in_progress' ? 'Resume round'
                      : progress?.status === 'submitted' || progress?.status === 'evaluated'
                        ? 'View round' : 'Enter round'}
                    <ChevronRight className="w-4 h-4" />
                  </Link>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Page
// ─────────────────────────────────────────────────────────────────────────────

const HackathonDetail = () => {
  const { hackathonId } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { isAuthenticated, user, profile } = useAuthStore()
  const tenant = useTenantStore((s) => s.tenant)
  const [tab, setTab] = useState('overview')
  const [showRegister, setShowRegister] = useState(false)

  const { data: hackathon, isLoading, error } = useQuery({
    queryKey: ['hackathon', hackathonId],
    queryFn: () => hackathonService.get(hackathonId),
  })

  const { data: progress } = useQuery({
    queryKey: ['hackathon-progress', hackathonId],
    queryFn: () => hackathonService.myProgress(hackathonId),
    enabled: isAuthenticated && Boolean(hackathon?.my_registration),
  })

  // A dedicated page: keep the browser tab in sync with the event.
  useEffect(() => {
    if (hackathon?.title) {
      const previous = document.title
      document.title = `${hackathon.title}${tenant?.name ? ` · ${tenant.name}` : ''}`
      return () => { document.title = previous }
    }
    return undefined
  }, [hackathon?.title, tenant?.name])

  const registerMutation = useMutation({
    mutationFn: (payload) => hackathonService.register(hackathonId, payload),
    onSuccess: () => {
      setShowRegister(false)
      toast.success("You're in! Check your email for the confirmation.")
      queryClient.invalidateQueries({ queryKey: ['hackathon', hackathonId] })
      queryClient.invalidateQueries({ queryKey: ['hackathon-progress', hackathonId] })
      queryClient.invalidateQueries({ queryKey: ['my-hackathons'] })
    },
    onError: (err) => {
      toast.error(err?.response?.data?.error || 'Could not complete your registration.')
    },
  })

  const withdrawMutation = useMutation({
    mutationFn: () => hackathonService.withdraw(hackathonId),
    onSuccess: () => {
      toast.success('You have withdrawn from this hackathon.')
      queryClient.invalidateQueries({ queryKey: ['hackathon', hackathonId] })
      queryClient.invalidateQueries({ queryKey: ['my-hackathons'] })
    },
    onError: () => toast.error('Could not withdraw right now.'),
  })

  const progressByStage = useMemo(() => {
    const map = {}
    ;(progress?.stages || []).forEach((row) => { map[row.stage_id] = row })
    return map
  }, [progress])

  if (isLoading) {
    return <div className="min-h-screen flex items-center justify-center"><Loading /></div>
  }

  if (error || !hackathon) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center p-6 text-center">
        <Trophy className="w-12 h-12 text-surface-300 mb-4" />
        <h1 className="text-xl font-semibold">Hackathon not found</h1>
        <p className="text-surface-500 mt-1">
          It may have been unpublished, or the link is no longer valid.
        </p>
        <Link to="/hackathons" className="btn-primary mt-5">
          <ArrowLeft className="w-4 h-4" /> Back to all hackathons
        </Link>
      </div>
    )
  }

  const accent = hackathon.theme_color || '#4f46e5'
  const regMeta = registrationMeta(hackathon.registration_state)
  const registration = hackathon.my_registration
  const canRegister = hackathon.registration_state === 'open' && !registration
  const prize = formatPrize(hackathon)
  const winners = hackathon.winners || []

  const handleRegisterClick = () => {
    if (!isAuthenticated) {
      navigate('/login', { state: { from: `/hackathons/${hackathonId}` } })
      return
    }
    setShowRegister(true)
  }

  const share = async () => {
    const url = window.location.href
    try {
      if (navigator.share) {
        await navigator.share({ title: hackathon.title, text: hackathon.tagline, url })
      } else {
        await navigator.clipboard.writeText(url)
        toast.success('Link copied')
      }
    } catch { /* the user dismissed the share sheet */ }
  }

  const tabs = winners.length ? [...TABS, { id: 'winners', label: 'Winners', icon: Medal }] : TABS

  return (
    <div className="min-h-screen bg-surface-50 dark:bg-surface-950">
      {/* Dedicated top bar — this page deliberately has no app sidebar. */}
      <header className="sticky top-0 z-40 border-b border-surface-200/70 dark:border-surface-800 bg-white/85 dark:bg-surface-900/85 backdrop-blur">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 h-14 flex items-center justify-between gap-3">
          <button
            type="button"
            onClick={() => navigate('/hackathons')}
            className="inline-flex items-center gap-2 text-sm font-medium text-surface-600 dark:text-surface-300 hover:text-primary-600 dark:hover:text-primary-400 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            <span className="hidden sm:inline">All hackathons</span>
          </button>

          <div className="flex-1 min-w-0 text-center">
            <span className="text-sm font-semibold truncate block">{hackathon.title}</span>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            <button type="button" onClick={share} className="btn-icon" title="Share">
              <Share2 className="w-4 h-4" />
            </button>
            {canRegister && (
              <button type="button" onClick={handleRegisterClick} className="btn-primary !py-1.5 !px-3 text-sm">
                {isAuthenticated ? 'Register' : <><LogIn className="w-4 h-4" /> Log in to register</>}
              </button>
            )}
          </div>
        </div>
      </header>

      {/* Hero */}
      <div
        className="relative overflow-hidden border-b border-surface-200/70 dark:border-surface-800"
        style={{ background: `linear-gradient(135deg, ${accent}1a, ${accent}44)` }}
      >
        {hackathon.banner_url && (
          <img
            src={hackathon.banner_url}
            alt=""
            className="absolute inset-0 w-full h-full object-cover opacity-30"
          />
        )}
        <div className="relative max-w-6xl mx-auto px-4 sm:px-6 py-10 sm:py-14">
          <div className="flex flex-col lg:flex-row lg:items-end gap-8">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-3 flex-wrap">
                {hackathon.thumbnail_url && (
                  <img
                    src={hackathon.thumbnail_url}
                    alt=""
                    className="w-14 h-14 rounded-2xl object-cover shadow-lg ring-2 ring-white/60 dark:ring-white/10"
                  />
                )}
                <span className={`badge ${regMeta.tint}`}>{regMeta.label}</span>
                {hackathon.results_announced && (
                  <span className="badge badge-success">
                    <PartyPopper className="w-3 h-3" /> Results out
                  </span>
                )}
              </div>

              <h1 className="text-3xl sm:text-4xl font-bold mt-4 leading-tight">
                {hackathon.title}
              </h1>
              {hackathon.tagline && (
                <p className="text-lg text-surface-600 dark:text-surface-300 mt-2 max-w-2xl">
                  {hackathon.tagline}
                </p>
              )}

              <div className="flex flex-wrap items-center gap-x-5 gap-y-2 mt-5 text-sm text-surface-600 dark:text-surface-300">
                <span className="inline-flex items-center gap-1.5">
                  <MapPin className="w-4 h-4" />
                  {hackathon.mode === 'online'
                    ? 'Online' : hackathon.location || labelOf(MODES, hackathon.mode)}
                </span>
                {hackathon.starts_at && (
                  <span className="inline-flex items-center gap-1.5">
                    <CalendarDays className="w-4 h-4" />
                    {formatDate(hackathon.starts_at)}
                    {hackathon.ends_at ? ` – ${formatDate(hackathon.ends_at)}` : ''}
                  </span>
                )}
                <span className="inline-flex items-center gap-1.5">
                  <Sparkles className="w-4 h-4" />
                  {labelOf(DIFFICULTIES, hackathon.difficulty, 'All levels')}
                </span>
                {/* Registration count — hidden entirely when the organiser turns it off. */}
                {hackathon.registration_count != null && (
                  <span className="inline-flex items-center gap-1.5">
                    <Users className="w-4 h-4" />
                    <strong>{hackathon.registration_count}</strong> registered
                  </span>
                )}
              </div>

              {(hackathon.tags || []).length > 0 && (
                <div className="flex flex-wrap gap-1.5 mt-4">
                  {hackathon.tags.map((tag) => (
                    <span
                      key={tag}
                      className="px-2.5 py-1 rounded-lg bg-white/60 dark:bg-white/10 text-xs font-medium"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              )}
            </div>

            {/* Action panel */}
            <div className="w-full lg:w-80 shrink-0">
              <div className="card p-5 space-y-4">
                {prize && (
                  <div>
                    <div className="text-xs uppercase tracking-wide text-surface-400">
                      Prize pool
                    </div>
                    <div className="text-2xl font-bold" style={{ color: accent }}>{prize}</div>
                  </div>
                )}

                {hackathon.registration_state === 'open' && hackathon.registration_deadline && (
                  <Countdown target={hackathon.registration_deadline} label="Registration closes in" />
                )}
                {hackathon.registration_state === 'opening_soon' && (
                  <Countdown target={hackathon.registration_opens_at} label="Registration opens in" />
                )}

                {registration ? (
                  <div className="space-y-3">
                    <div className="rounded-xl bg-emerald-50 dark:bg-emerald-900/15 border border-emerald-100 dark:border-emerald-900/30 p-3">
                      <p className="text-sm font-medium text-emerald-700 dark:text-emerald-300 flex items-center gap-1.5">
                        <Check className="w-4 h-4" /> You're registered
                      </p>
                      <p className="text-xs text-emerald-600/80 dark:text-emerald-300/70 mt-1">
                        Registered {formatDate(registration.registered_at)}. We'll email you
                        before every round.
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => setTab('rounds')}
                      className="btn-primary w-full justify-center"
                    >
                      <Layers className="w-4 h-4" /> Go to my rounds
                    </button>
                    {!hackathon.results_announced && (
                      <button
                        type="button"
                        onClick={() => {
                          if (window.confirm('Withdraw from this hackathon? You can register again while registrations are open.')) {
                            withdrawMutation.mutate()
                          }
                        }}
                        className="w-full text-xs text-surface-400 hover:text-rose-500 transition-colors"
                      >
                        Withdraw my registration
                      </button>
                    )}
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={handleRegisterClick}
                    disabled={!canRegister}
                    className="btn-primary w-full justify-center disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {!isAuthenticated ? (
                      <><LogIn className="w-4 h-4" /> Log in to register</>
                    ) : canRegister ? (
                      <><Trophy className="w-4 h-4" /> Register now</>
                    ) : (
                      regMeta.label
                    )}
                  </button>
                )}

                {!isAuthenticated && (
                  <p className="text-xs text-surface-400 text-center">
                    You can read everything on this page without an account — you only need
                    one to enter.
                  </p>
                )}

                <div className="pt-3 border-t border-surface-100 dark:border-surface-800 space-y-1.5 text-xs text-surface-500">
                  {hackathon.organizer_name && (
                    <div>Organised by <strong>{hackathon.organizer_name}</strong></div>
                  )}
                  {hackathon.contact_email && (
                    <a
                      href={`mailto:${hackathon.contact_email}`}
                      className="inline-flex items-center gap-1.5 hover:text-primary-600"
                    >
                      <Mail className="w-3.5 h-3.5" />{hackathon.contact_email}
                    </a>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="sticky top-14 z-30 border-b border-surface-200/70 dark:border-surface-800 bg-white/85 dark:bg-surface-900/85 backdrop-blur">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 flex items-center gap-1 overflow-x-auto">
          {tabs.map((t) => {
            const Icon = t.icon
            const active = tab === t.id
            return (
              <button
                key={t.id}
                type="button"
                onClick={() => setTab(t.id)}
                className={`px-3.5 py-3 text-sm font-medium whitespace-nowrap inline-flex items-center gap-1.5 border-b-2 transition-colors ${
                  active
                    ? 'border-primary-500 text-primary-600 dark:text-primary-400'
                    : 'border-transparent text-surface-500 hover:text-surface-700 dark:hover:text-surface-300'
                }`}
              >
                <Icon className="w-4 h-4" />{t.label}
              </button>
            )
          })}
        </div>
      </div>

      {/* Body */}
      <main className="max-w-6xl mx-auto px-4 sm:px-6 py-8">
        <AnimatePresence mode="wait">
          <motion.div
            key={tab}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
          >
            {tab === 'overview' && (
              <div className="grid lg:grid-cols-3 gap-8">
                <div className="lg:col-span-2 space-y-6">
                  <section className="card p-6">
                    <h2 className="text-lg font-semibold mb-3">About this hackathon</h2>
                    {hackathon.description ? (
                      <RichContent content={hackathon.description} />
                    ) : (
                      <p className="text-surface-500">
                        The organisers haven't added a description yet.
                      </p>
                    )}
                  </section>

                  {hackathon.eligibility && (
                    <section className="card p-6">
                      <h2 className="text-lg font-semibold mb-3">Who can take part</h2>
                      <RichContent content={hackathon.eligibility} />
                    </section>
                  )}
                </div>

                <aside className="space-y-6">
                  <section className="card p-5">
                    <h3 className="font-semibold mb-3">Key dates</h3>
                    <dl className="space-y-3 text-sm">
                      {[
                        ['Registration opens', hackathon.registration_opens_at],
                        ['Registration closes', hackathon.registration_deadline],
                        ['Hackathon starts', hackathon.starts_at],
                        ['Hackathon ends', hackathon.ends_at],
                      ].filter(([, value]) => value).map(([label, value]) => (
                        <div key={label} className="flex justify-between gap-3">
                          <dt className="text-surface-500">{label}</dt>
                          <dd className="font-medium text-right">{formatDateTime(value)}</dd>
                        </div>
                      ))}
                    </dl>
                  </section>

                  {hackathon.stages?.length > 0 && (
                    <section className="card p-5">
                      <h3 className="font-semibold mb-3">Format</h3>
                      <ol className="space-y-2.5">
                        {hackathon.stages.map((stage, i) => {
                          const meta = stageMeta(stage.stage_type)
                          const Icon = meta.icon
                          return (
                            <li key={stage.id} className="flex items-start gap-2.5 text-sm">
                              <span className={`w-7 h-7 rounded-lg flex items-center justify-center shrink-0 ${meta.tint}`}>
                                <Icon className="w-3.5 h-3.5" />
                              </span>
                              <div className="min-w-0">
                                <div className="font-medium truncate">
                                  {i + 1}. {stage.title}
                                </div>
                                <div className="text-xs text-surface-400">{meta.label}</div>
                              </div>
                            </li>
                          )
                        })}
                      </ol>
                    </section>
                  )}

                  {hackathon.related_courses?.length > 0 && (
                    <section className="card p-5">
                      <h3 className="font-semibold mb-3">Prepare with</h3>
                      <div className="space-y-2">
                        {hackathon.related_courses.map((course) => (
                          <Link
                            key={course.id}
                            to={`/courses/${course.id}`}
                            className="flex items-center gap-2.5 p-2 rounded-lg hover:bg-surface-50 dark:hover:bg-surface-800 transition-colors text-sm"
                          >
                            <BookOpen className="w-4 h-4 text-surface-400 shrink-0" />
                            <span className="truncate">{course.name}</span>
                            <ExternalLink className="w-3.5 h-3.5 text-surface-300 ml-auto shrink-0" />
                          </Link>
                        ))}
                      </div>
                    </section>
                  )}
                </aside>
              </div>
            )}

            {tab === 'rounds' && (
              <div className="max-w-3xl">
                {hackathon.stages?.length ? (
                  <>
                    {!registration && (
                      <div className="card p-4 mb-6 flex items-start gap-3 bg-primary-50/60 dark:bg-primary-900/10 border-primary-100 dark:border-primary-900/30">
                        <Info className="w-5 h-5 text-primary-500 shrink-0 mt-0.5" />
                        <div className="text-sm">
                          <p className="font-medium">This is the full round-by-round format.</p>
                          <p className="text-surface-500 mt-0.5">
                            Register to unlock the first round — each round opens for you as
                            soon as you're shortlisted from the one before it.
                          </p>
                        </div>
                      </div>
                    )}
                    <div className="space-y-5">
                      {hackathon.stages.map((stage, i) => (
                        <StageCard
                          key={stage.id}
                          stage={stage}
                          index={i}
                          progress={progressByStage[stage.id]}
                          hackathonId={hackathonId}
                          isRegistered={Boolean(registration)}
                          isLast={i === hackathon.stages.length - 1}
                        />
                      ))}
                    </div>
                  </>
                ) : (
                  <div className="card p-10 text-center">
                    <Layers className="w-10 h-10 text-surface-300 mx-auto mb-3" />
                    <h3 className="font-semibold">Rounds not announced yet</h3>
                    <p className="text-sm text-surface-500 mt-1">
                      The organisers will publish the format soon. Register to be notified.
                    </p>
                  </div>
                )}
              </div>
            )}

            {tab === 'prizes' && (
              <div className="max-w-3xl card p-6">
                <h2 className="text-lg font-semibold mb-3 flex items-center gap-2">
                  <Gift className="w-5 h-5" style={{ color: accent }} /> Prizes
                </h2>
                {prize && <div className="text-3xl font-bold mb-4" style={{ color: accent }}>{prize}</div>}
                {hackathon.prizes_description ? (
                  <RichContent content={hackathon.prizes_description} />
                ) : (
                  <p className="text-surface-500">Prize details will be announced soon.</p>
                )}
              </div>
            )}

            {tab === 'rules' && (
              <div className="max-w-3xl card p-6">
                <h2 className="text-lg font-semibold mb-3 flex items-center gap-2">
                  <ScrollText className="w-5 h-5" /> Rules & code of conduct
                </h2>
                {hackathon.rules ? (
                  <RichContent content={hackathon.rules} />
                ) : (
                  <p className="text-surface-500">No specific rules have been published.</p>
                )}
              </div>
            )}

            {tab === 'faq' && (
              <div className="max-w-3xl space-y-3">
                {(hackathon.faqs || []).length ? (
                  hackathon.faqs.map((faq, i) => (
                    <details key={i} className="card p-5 group">
                      <summary className="font-medium cursor-pointer list-none flex items-center justify-between gap-3">
                        {faq.question}
                        <ChevronRight className="w-4 h-4 text-surface-400 group-open:rotate-90 transition-transform shrink-0" />
                      </summary>
                      <p className="text-sm text-surface-600 dark:text-surface-300 mt-3">
                        {faq.answer}
                      </p>
                    </details>
                  ))
                ) : (
                  <div className="card p-10 text-center">
                    <HelpCircle className="w-10 h-10 text-surface-300 mx-auto mb-3" />
                    <h3 className="font-semibold">No FAQs yet</h3>
                    {hackathon.contact_email && (
                      <p className="text-sm text-surface-500 mt-1">
                        Email <a className="text-primary-600" href={`mailto:${hackathon.contact_email}`}>
                          {hackathon.contact_email}
                        </a> with any question.
                      </p>
                    )}
                  </div>
                )}
              </div>
            )}

            {tab === 'winners' && (
              <div className="max-w-3xl">
                <div className="card-gradient p-6 mb-6 text-center">
                  <PartyPopper className="w-10 h-10 mx-auto mb-3" style={{ color: accent }} />
                  <h2 className="text-xl font-bold">Congratulations to our winners!</h2>
                  <p className="text-sm text-surface-500 mt-1">
                    Announced {formatDate(hackathon.results_announced_at)}
                  </p>
                </div>
                <div className="space-y-3">
                  {winners.map((winner) => (
                    <div key={winner.id} className="card p-5 flex items-center gap-4">
                      <div
                        className="w-12 h-12 rounded-xl flex items-center justify-center font-bold text-lg shrink-0"
                        style={{ background: `${accent}22`, color: accent }}
                      >
                        {winner.final_rank ? `#${winner.final_rank}` : <Medal className="w-5 h-5" />}
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="font-semibold truncate">{winner.name}</div>
                        <div className="text-sm text-surface-500 truncate">
                          {winner.winner_title}
                          {winner.institution ? ` · ${winner.institution}` : ''}
                        </div>
                      </div>
                      {winner.prize && (
                        <span className="badge badge-success shrink-0">{winner.prize}</span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </motion.div>
        </AnimatePresence>
      </main>

      {showRegister && (
        <RegisterModal
          hackathon={hackathon}
          user={user}
          profile={profile}
          isSaving={registerMutation.isPending}
          onClose={() => setShowRegister(false)}
          onSubmit={(payload) => registerMutation.mutate(payload)}
        />
      )}
    </div>
  )
}

export default HackathonDetail
