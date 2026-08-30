import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import {
  Trophy, Search, MapPin, Users, CalendarDays, ArrowRight, Sparkles,
  Radio, Clock, Archive, Award, Layers,
} from 'lucide-react'
import { hackathonService } from '../services/hackathonService'
import { useFeatureLabel } from '../context/tenantStore'
import { useAuthStore } from '../context/authStore'
import Loading from '../components/common/Loading'
import {
  bucketOf, formatDate, formatPrize, registrationMeta, labelOf,
  MODES, DIFFICULTIES, Countdown,
} from '../components/hackathons/hackathonShared'

const TABS = [
  { id: 'live', label: 'Live now', icon: Radio },
  { id: 'upcoming', label: 'Upcoming', icon: Clock },
  { id: 'past', label: 'Past', icon: Archive },
  { id: 'mine', label: 'My hackathons', icon: Award },
]

const HackathonTile = ({ hackathon, onOpen }) => {
  const meta = registrationMeta(hackathon.registration_state)
  const prize = formatPrize(hackathon)
  const accent = hackathon.theme_color || '#4f46e5'

  return (
    <motion.button
      type="button"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      onClick={() => onOpen(hackathon)}
      className="h-full text-left card p-0 overflow-hidden flex flex-col hover:border-primary-200 dark:hover:border-primary-800 hover:shadow-lg transition-all group"
    >
      <div
        className="relative h-32 shrink-0 flex items-center justify-center"
        style={{ background: `linear-gradient(135deg, ${accent}22, ${accent}66)` }}
      >
        {hackathon.thumbnail_url ? (
          <img
            src={hackathon.thumbnail_url}
            alt=""
            className="absolute inset-0 w-full h-full object-cover"
            loading="lazy"
          />
        ) : (
          <Trophy className="w-10 h-10 opacity-60" style={{ color: accent }} />
        )}
        <span className={`absolute top-3 left-3 badge ${meta.tint} backdrop-blur`}>
          {meta.label}
        </span>
        {hackathon.is_registered && (
          <span className="absolute top-3 right-3 badge badge-primary backdrop-blur">
            Registered
          </span>
        )}
      </div>

      <div className="p-5 flex flex-col flex-1">
        <h3 className="font-semibold text-lg line-clamp-2 group-hover:text-primary-600 dark:group-hover:text-primary-400 transition-colors">
          {hackathon.title}
        </h3>
        {hackathon.tagline && (
          <p className="text-sm text-surface-500 mt-1 line-clamp-2">{hackathon.tagline}</p>
        )}

        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-3 text-xs text-surface-500">
          <span className="inline-flex items-center gap-1">
            <MapPin className="w-3.5 h-3.5" />
            {hackathon.mode === 'online'
              ? 'Online'
              : hackathon.location || labelOf(MODES, hackathon.mode, 'Online')}
          </span>
          {hackathon.starts_at && (
            <span className="inline-flex items-center gap-1">
              <CalendarDays className="w-3.5 h-3.5" />{formatDate(hackathon.starts_at)}
            </span>
          )}
          {hackathon.stages_count > 0 && (
            <span className="inline-flex items-center gap-1">
              <Layers className="w-3.5 h-3.5" />
              {hackathon.stages_count} round{hackathon.stages_count === 1 ? '' : 's'}
            </span>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-1.5 mt-3">
          <span className="px-2 py-0.5 rounded bg-surface-100 dark:bg-surface-800 text-surface-600 dark:text-surface-300 text-xs">
            {labelOf(DIFFICULTIES, hackathon.difficulty, 'All levels')}
          </span>
          {(hackathon.tags || []).slice(0, 2).map((tag) => (
            <span
              key={tag}
              className="px-2 py-0.5 rounded bg-surface-100 dark:bg-surface-800 text-surface-600 dark:text-surface-300 text-xs"
            >
              {tag}
            </span>
          ))}
        </div>

        <div className="flex items-center justify-between gap-2 mt-auto pt-4">
          <div className="min-w-0">
            {prize ? (
              <div className="text-sm font-semibold text-surface-800 dark:text-surface-100 truncate">
                {prize} <span className="font-normal text-surface-400">in prizes</span>
              </div>
            ) : hackathon.registration_count != null ? (
              <div className="text-sm text-surface-500 inline-flex items-center gap-1.5">
                <Users className="w-3.5 h-3.5" />
                {hackathon.registration_count} registered
              </div>
            ) : (
              <div className="text-sm text-surface-400">Free to enter</div>
            )}
          </div>
          <span className="text-primary-600 dark:text-primary-400 text-sm font-medium inline-flex items-center gap-1 group-hover:gap-2 transition-all shrink-0">
            View <ArrowRight className="w-4 h-4" />
          </span>
        </div>

        {hackathon.registration_state === 'open' && hackathon.registration_deadline && (
          <div className="mt-3 pt-3 border-t border-surface-100 dark:border-surface-800 text-xs text-surface-500 flex items-center gap-1.5">
            <Clock className="w-3.5 h-3.5" />
            Registration closes in{' '}
            <Countdown target={hackathon.registration_deadline} compact />
          </div>
        )}
      </div>
    </motion.button>
  )
}

const EmptyState = ({ icon: Icon, title, body }) => (
  <div className="card p-12 text-center">
    <div className="w-14 h-14 rounded-2xl bg-surface-100 dark:bg-surface-800 flex items-center justify-center mx-auto mb-4">
      <Icon className="w-7 h-7 text-surface-400" />
    </div>
    <h3 className="font-semibold text-lg">{title}</h3>
    <p className="text-sm text-surface-500 mt-1 max-w-md mx-auto">{body}</p>
  </div>
)

const Hackathons = () => {
  const navigate = useNavigate()
  const label = useFeatureLabel('hackathons')
  const { isAuthenticated } = useAuthStore()
  const [tab, setTab] = useState('live')
  const [search, setSearch] = useState('')
  const [mode, setMode] = useState('')
  const [difficulty, setDifficulty] = useState('')

  const { data, isLoading } = useQuery({
    queryKey: ['hackathons', { search, mode, difficulty }],
    queryFn: () => hackathonService.getHackathons({
      search: search || undefined,
      mode: mode || undefined,
      difficulty: difficulty || undefined,
      page_size: 60,
    }),
  })

  const { data: mine, isLoading: mineLoading } = useQuery({
    queryKey: ['my-hackathons'],
    queryFn: hackathonService.myRegistrations,
    enabled: isAuthenticated && tab === 'mine',
  })

  const hackathons = useMemo(() => data?.results || [], [data])

  const buckets = useMemo(() => {
    const grouped = { live: [], upcoming: [], past: [] }
    hackathons.forEach((h) => { grouped[bucketOf(h)]?.push(h) })
    return grouped
  }, [hackathons])

  const open = (hackathon) => navigate(`/hackathons/${hackathon.id}`)

  const renderGrid = (items, empty) => {
    if (!items.length) return empty
    return (
      <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
        {items.map((h) => <HackathonTile key={h.id} hackathon={h} onOpen={open} />)}
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Hero */}
      <div className="card-gradient p-6 sm:p-8 relative overflow-hidden">
        <div className="relative z-10 max-w-2xl">
          <div className="inline-flex items-center gap-2 badge badge-primary mb-3">
            <Sparkles className="w-3.5 h-3.5" /> Compete & build
          </div>
          <h1 className="text-2xl sm:text-3xl font-bold">{label}</h1>
          <p className="text-surface-600 dark:text-surface-300 mt-2">
            Multi-round competitions with quizzes, coding challenges, hands-on labs and
            project submissions. Clear a round, get shortlisted, and go all the way to the
            winners' podium.
          </p>
        </div>
        <Trophy className="absolute -right-6 -bottom-8 w-48 h-48 opacity-[0.06] pointer-events-none" />
      </div>

      {/* Controls */}
      <div className="flex flex-col lg:flex-row lg:items-center gap-3">
        <div className="flex items-center gap-1 p-1 rounded-xl bg-surface-100 dark:bg-surface-800 overflow-x-auto">
          {TABS.filter((t) => t.id !== 'mine' || isAuthenticated).map((t) => {
            const Icon = t.icon
            const active = tab === t.id
            return (
              <button
                key={t.id}
                type="button"
                onClick={() => setTab(t.id)}
                className={`px-3.5 py-2 rounded-lg text-sm font-medium whitespace-nowrap inline-flex items-center gap-1.5 transition-colors ${
                  active
                    ? 'bg-white dark:bg-surface-900 shadow-sm text-primary-600 dark:text-primary-400'
                    : 'text-surface-500 hover:text-surface-700 dark:hover:text-surface-300'
                }`}
              >
                <Icon className="w-4 h-4" />
                {t.label}
                {t.id !== 'mine' && buckets[t.id]?.length > 0 && (
                  <span className="ml-0.5 text-xs text-surface-400">
                    {buckets[t.id].length}
                  </span>
                )}
              </button>
            )
          })}
        </div>

        <div className="flex-1 flex flex-col sm:flex-row gap-3 lg:justify-end">
          <div className="relative flex-1 sm:max-w-xs">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-surface-400" />
            <input
              className="input pl-9"
              placeholder="Search hackathons"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <select className="input sm:w-40" value={mode} onChange={(e) => setMode(e.target.value)}>
            <option value="">Any mode</option>
            {MODES.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
          </select>
          <select
            className="input sm:w-44"
            value={difficulty}
            onChange={(e) => setDifficulty(e.target.value)}
          >
            <option value="">Any level</option>
            {DIFFICULTIES.map((d) => <option key={d.value} value={d.value}>{d.label}</option>)}
          </select>
        </div>
      </div>

      {/* Results */}
      {tab === 'mine' ? (
        mineLoading ? <Loading /> : (
          (mine || []).length === 0 ? (
            <EmptyState
              icon={Award}
              title="You haven't entered a hackathon yet"
              body="Register for a live or upcoming hackathon and it will show up here, along with your progress through every round."
            />
          ) : (
            <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
              {(mine || []).map((registration) => (
                <HackathonTile
                  key={registration.id}
                  hackathon={{ ...registration.hackathon, is_registered: true }}
                  onOpen={open}
                />
              ))}
            </div>
          )
        )
      ) : isLoading ? <Loading /> : renderGrid(
        buckets[tab] || [],
        <EmptyState
          icon={tab === 'past' ? Archive : tab === 'upcoming' ? Clock : Radio}
          title={
            tab === 'live' ? 'No hackathons running right now'
              : tab === 'upcoming' ? 'Nothing scheduled just yet'
                : 'No past hackathons'
          }
          body={
            tab === 'live'
              ? 'Check the Upcoming tab — new competitions are announced regularly.'
              : tab === 'upcoming'
                ? 'When your academy announces the next hackathon, it will appear here first.'
                : 'Completed hackathons and their winners will be archived here.'
          }
        />
      )}
    </div>
  )
}

export default Hackathons
