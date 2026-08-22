import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import {
  Briefcase, MapPin, Building2, ExternalLink, Clock, GraduationCap, Code2,
  ArrowRight, ClipboardList, Search, SlidersHorizontal, X,
} from 'lucide-react'
import { jobService } from '../services/jobService'
import { useFeatureLabel } from '../context/tenantStore'
import { useAuthStore } from '../context/authStore'
import {
  stageMeta, formatSalary, formatExperience, categoryMeta,
  CATEGORIES, WORK_MODES, EMPLOYMENT_TYPES,
} from '../components/jobs/jobShared'
import Loading from '../components/common/Loading'

const TABS = [
  { id: 'open', label: 'Open Positions' },
  { id: 'mine', label: 'My Applications' },
]

const CATEGORY_ICONS = { Briefcase, GraduationCap, Code2 }

const HIRING_TYPES = [
  { value: 'internal', label: 'Internal' },
  { value: 'external', label: 'External' },
]

const CategoryIcon = ({ category, className }) => {
  const Icon = CATEGORY_ICONS[categoryMeta(category).icon] || Briefcase
  return <Icon className={className} />
}

const JobTile = ({ job, onOpen }) => {
  const salary = formatSalary(job)
  const exp = formatExperience(job)
  const app = job.my_application
  const cat = categoryMeta(job.category)
  return (
    <motion.button
      type="button"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      onClick={() => onOpen(job)}
      className="h-full text-left card p-5 flex flex-col hover:border-primary-200 dark:hover:border-primary-800 hover:shadow-md transition-all group"
    >
      <div className="flex items-start justify-between gap-2">
        <div className={`w-11 h-11 rounded-xl flex items-center justify-center shrink-0 ${cat.tint}`}>
          <CategoryIcon category={job.category} className="w-5 h-5" />
        </div>
        {job.is_external ? (
          <span className="badge bg-indigo-50 text-indigo-700 dark:bg-indigo-900/20 dark:text-indigo-300 shrink-0">
            <ExternalLink className="w-3 h-3" /> External
          </span>
        ) : (
          <span className="badge badge-primary shrink-0">Internal</span>
        )}
      </div>

      <div className="mt-3 flex items-center gap-2">
        <span className={`badge ${cat.tint}`}>{cat.label}</span>
      </div>
      <h3 className="font-semibold text-lg mt-2 line-clamp-2">{job.title}</h3>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-2 text-xs text-surface-500">
        {job.department && <span className="inline-flex items-center gap-1"><Building2 className="w-3.5 h-3.5" />{job.department}</span>}
        {job.location && <span className="inline-flex items-center gap-1"><MapPin className="w-3.5 h-3.5" />{job.location}</span>}
      </div>
      <div className="flex flex-wrap items-center gap-1.5 mt-2 text-xs">
        {job.employment_type_display && <span className="px-2 py-0.5 rounded bg-surface-100 dark:bg-surface-800 text-surface-600 dark:text-surface-300">{job.employment_type_display}</span>}
        {job.work_mode_display && <span className="px-2 py-0.5 rounded bg-surface-100 dark:bg-surface-800 text-surface-600 dark:text-surface-300">{job.work_mode_display}</span>}
        {exp && <span className="px-2 py-0.5 rounded bg-surface-100 dark:bg-surface-800 text-surface-600 dark:text-surface-300">{exp}</span>}
      </div>

      <div className="flex items-center justify-between gap-2 mt-auto pt-4">
        <div className="text-sm font-medium text-surface-700 dark:text-surface-300">
          {salary || <span className="text-surface-400 font-normal">Not disclosed</span>}
        </div>
        {app ? (
          <span className={`badge ${stageMeta(app.stage).tint}`}>{stageMeta(app.stage).label}</span>
        ) : (
          <span className="text-primary-600 dark:text-primary-400 text-sm font-medium inline-flex items-center gap-1 group-hover:gap-2 transition-all">
            View <ArrowRight className="w-4 h-4" />
          </span>
        )}
      </div>
    </motion.button>
  )
}

const FilterGroup = ({ title, options, selected, onToggle }) => (
  <div>
    <p className="text-xs font-semibold uppercase tracking-wide text-surface-400 mb-2">{title}</p>
    <div className="space-y-1.5">
      {options.map((o) => (
        <label key={o.value} className="flex items-center gap-2.5 text-sm cursor-pointer group">
          <input
            type="checkbox"
            checked={selected.includes(o.value)}
            onChange={() => onToggle(o.value)}
            className="rounded border-surface-300 text-primary-600 focus:ring-primary-500"
          />
          <span className="text-surface-600 dark:text-surface-300 group-hover:text-surface-900 dark:group-hover:text-surface-100">{o.label}</span>
        </label>
      ))}
    </div>
  </div>
)

const FiltersPanel = ({ filters, toggle, onClear, hasActive }) => (
  <div className="space-y-5">
    <div className="flex items-center justify-between">
      <h3 className="font-semibold inline-flex items-center gap-2"><SlidersHorizontal className="w-4 h-4" /> Filters</h3>
      {hasActive && (
        <button onClick={onClear} className="text-xs text-primary-600 dark:text-primary-400 hover:underline inline-flex items-center gap-1">
          <X className="w-3 h-3" /> Clear
        </button>
      )}
    </div>
    <FilterGroup title="Category" options={CATEGORIES} selected={filters.category} onToggle={toggle('category')} />
    <FilterGroup title="Hiring type" options={HIRING_TYPES} selected={filters.job_type} onToggle={toggle('job_type')} />
    <FilterGroup title="Work mode" options={WORK_MODES} selected={filters.work_mode} onToggle={toggle('work_mode')} />
    <FilterGroup title="Employment" options={EMPLOYMENT_TYPES} selected={filters.employment_type} onToggle={toggle('employment_type')} />
  </div>
)

const EMPTY_FILTERS = { category: [], job_type: [], work_mode: [], employment_type: [] }

const Jobs = () => {
  const navigate = useNavigate()
  const jobsLabel = useFeatureLabel('jobs', 'Careers')
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const [tab, setTab] = useState('open')
  const [q, setQ] = useState('')
  const [filters, setFilters] = useState(EMPTY_FILTERS)
  const [showMobileFilters, setShowMobileFilters] = useState(false)

  const { data: jobs = [], isLoading } = useQuery({
    queryKey: ['jobs', 'open'],
    queryFn: () => jobService.getJobs(),
  })
  const { data: mine = [], isLoading: mineLoading } = useQuery({
    queryKey: ['jobs', 'mine'],
    queryFn: () => jobService.myApplications(),
    enabled: tab === 'mine' && isAuthenticated,
  })

  const toggle = (key) => (value) =>
    setFilters((s) => ({
      ...s,
      [key]: s[key].includes(value) ? s[key].filter((v) => v !== value) : [...s[key], value],
    }))

  const hasActive = Object.values(filters).some((arr) => arr.length > 0)

  const filtered = useMemo(() => {
    const term = q.trim().toLowerCase()
    return jobs.filter((j) => {
      if (term && !(
        j.title?.toLowerCase().includes(term) ||
        j.department?.toLowerCase().includes(term) ||
        j.location?.toLowerCase().includes(term)
      )) return false
      if (filters.category.length && !filters.category.includes(j.category || 'job')) return false
      if (filters.job_type.length && !filters.job_type.includes(j.job_type)) return false
      if (filters.work_mode.length && !filters.work_mode.includes(j.work_mode)) return false
      if (filters.employment_type.length && !filters.employment_type.includes(j.employment_type)) return false
      return true
    })
  }, [jobs, q, filters])

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="card-gradient p-6">
        <div className="flex items-center gap-3">
          <div className="w-12 h-12 rounded-2xl bg-white/20 flex items-center justify-center">
            <Briefcase className="w-6 h-6 text-white" />
          </div>
          <div>
            <h1 className="text-2xl font-display font-bold text-white">{jobsLabel}</h1>
            <p className="text-white/80 text-sm">Explore jobs, internships & hackathons, and track your applications</p>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-2 border-b border-surface-200 dark:border-surface-800">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => {
              if (t.id === 'mine' && !isAuthenticated) {
                navigate('/login', { state: { from: '/jobs' } })
                return
              }
              setTab(t.id)
            }}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors ${
              tab === t.id
                ? 'border-primary-500 text-primary-600 dark:text-primary-400'
                : 'border-transparent text-surface-500 hover:text-surface-800 dark:hover:text-surface-200'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'open' ? (
        <div className="flex flex-col lg:flex-row gap-6">
          {/* Left filters */}
          <aside className="lg:w-60 shrink-0 hidden lg:block">
            <div className="card p-5 sticky top-4">
              <FiltersPanel filters={filters} toggle={toggle} onClear={() => setFilters(EMPTY_FILTERS)} hasActive={hasActive} />
            </div>
          </aside>

          <div className="flex-1 min-w-0 space-y-4">
            <div className="flex items-center gap-2">
              <div className="relative flex-1">
                <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-surface-400" />
                <input
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  placeholder="Search by title, team or location"
                  className="input pl-9 py-2.5 w-full"
                />
              </div>
              <button
                onClick={() => setShowMobileFilters(true)}
                className="lg:hidden btn-secondary inline-flex items-center gap-2 shrink-0"
              >
                <SlidersHorizontal className="w-4 h-4" />
                {hasActive && <span className="w-2 h-2 rounded-full bg-primary-500" />}
              </button>
            </div>

            {isLoading ? (
              <Loading />
            ) : filtered.length === 0 ? (
              <div className="card p-10 text-center text-surface-500">
                <Briefcase className="w-10 h-10 mx-auto mb-2 text-surface-300" />
                <p>{hasActive || q ? 'No positions match your filters.' : 'No open positions right now. Check back soon!'}</p>
              </div>
            ) : (
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                {filtered.map((job) => (
                  <JobTile key={job.id} job={job} onOpen={(j) => navigate(`/jobs/${j.id}`)} />
                ))}
              </div>
            )}
          </div>

          {/* Mobile filters drawer */}
          {showMobileFilters && (
            <div className="fixed inset-0 z-50 lg:hidden" onClick={() => setShowMobileFilters(false)}>
              <div className="absolute inset-0 bg-black/50" />
              <div className="absolute left-0 top-0 bottom-0 w-72 max-w-[85%] bg-white dark:bg-surface-900 p-5 overflow-y-auto" onClick={(e) => e.stopPropagation()}>
                <div className="flex justify-end mb-2">
                  <button onClick={() => setShowMobileFilters(false)} className="text-surface-400 hover:text-surface-700"><X className="w-5 h-5" /></button>
                </div>
                <FiltersPanel filters={filters} toggle={toggle} onClear={() => setFilters(EMPTY_FILTERS)} hasActive={hasActive} />
              </div>
            </div>
          )}
        </div>
      ) : (
        <>
          {mineLoading ? (
            <Loading />
          ) : mine.length === 0 ? (
            <div className="card p-10 text-center text-surface-500">
              <ClipboardList className="w-10 h-10 mx-auto mb-2 text-surface-300" />
              <p>You haven't applied to any jobs yet.</p>
            </div>
          ) : (
            <div className="grid gap-3">
              {mine.map((app) => (
                <motion.button
                  key={app.id}
                  type="button"
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  onClick={() => app.job?.id && navigate(`/jobs/${app.job.id}`)}
                  className="w-full text-left card p-5 hover:shadow-md transition-all"
                >
                  <div className="flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <h3 className="font-semibold truncate">{app.job?.title || 'Job'}</h3>
                      <p className="text-xs text-surface-500 mt-1 flex flex-wrap items-center gap-x-3 gap-y-1">
                        {app.job?.department && <span className="inline-flex items-center gap-1"><Building2 className="w-3.5 h-3.5" />{app.job.department}</span>}
                        {app.job?.location && <span className="inline-flex items-center gap-1"><MapPin className="w-3.5 h-3.5" />{app.job.location}</span>}
                        <span className="inline-flex items-center gap-1"><Clock className="w-3.5 h-3.5" />Applied {new Date(app.applied_at).toLocaleDateString()}</span>
                      </p>
                    </div>
                    <span className={`badge shrink-0 ${stageMeta(app.stage).tint}`}>{stageMeta(app.stage).label}</span>
                  </div>
                </motion.button>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}

export default Jobs
