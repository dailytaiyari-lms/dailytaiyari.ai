// Shared helpers for the Job Portal UI (stage labels, colors, formatting).

export const PIPELINE_STAGES = [
  'applied', 'under_review', 'shortlisted', 'interview', 'offer', 'hired',
]

export const STAGE_META = {
  applied: { label: 'Applied', tint: 'bg-surface-100 text-surface-600 dark:bg-surface-800 dark:text-surface-300' },
  under_review: { label: 'Under Review', tint: 'bg-blue-50 text-blue-700 dark:bg-blue-900/20 dark:text-blue-300' },
  shortlisted: { label: 'Shortlisted', tint: 'bg-violet-50 text-violet-700 dark:bg-violet-900/20 dark:text-violet-300' },
  interview: { label: 'Interview', tint: 'bg-amber-50 text-amber-700 dark:bg-amber-900/20 dark:text-amber-300' },
  offer: { label: 'Offer', tint: 'bg-cyan-50 text-cyan-700 dark:bg-cyan-900/20 dark:text-cyan-300' },
  hired: { label: 'Hired', tint: 'bg-success-50 text-success-700 dark:bg-success-900/20 dark:text-success-300' },
  rejected: { label: 'Rejected', tint: 'bg-error-50 text-error-700 dark:bg-error-900/20 dark:text-error-300' },
  withdrawn: { label: 'Withdrawn', tint: 'bg-surface-100 text-surface-500 dark:bg-surface-800 dark:text-surface-400' },
  applied_external: { label: 'Applied Externally', tint: 'bg-indigo-50 text-indigo-700 dark:bg-indigo-900/20 dark:text-indigo-300' },
}

export const stageMeta = (stage) =>
  STAGE_META[stage] || { label: stage || '—', tint: 'bg-surface-100 text-surface-600 dark:bg-surface-800 dark:text-surface-300' }

export const EMPLOYMENT_TYPES = [
  { value: 'full_time', label: 'Full-time' },
  { value: 'part_time', label: 'Part-time' },
  { value: 'internship', label: 'Internship' },
  { value: 'contract', label: 'Contract' },
  { value: 'temporary', label: 'Temporary' },
]

export const CATEGORIES = [
  { value: 'job', label: 'Job', icon: 'Briefcase', tint: 'bg-primary-50 text-primary-700 dark:bg-primary-900/20 dark:text-primary-300' },
  { value: 'internship', label: 'Internship', icon: 'GraduationCap', tint: 'bg-cyan-50 text-cyan-700 dark:bg-cyan-900/20 dark:text-cyan-300' },
]

export const categoryMeta = (category) =>
  CATEGORIES.find((c) => c.value === category) || CATEGORIES[0]

export const WORK_MODES = [
  { value: 'onsite', label: 'On-site' },
  { value: 'remote', label: 'Remote' },
  { value: 'hybrid', label: 'Hybrid' },
]

export const formatSalary = (job) => {
  const { salary_min, salary_max, salary_currency, salary_period } = job || {}
  if (!salary_min && !salary_max) return null
  const cur = salary_currency || 'INR'
  const fmt = (n) => {
    if (n == null) return ''
    return new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 }).format(n)
  }
  const range = salary_min && salary_max
    ? `${fmt(salary_min)}–${fmt(salary_max)}`
    : fmt(salary_min || salary_max)
  return `${cur} ${range}/${salary_period || 'year'}`
}

export const formatExperience = (job) => {
  const { experience_min, experience_max } = job || {}
  if (experience_min == null && experience_max == null) return null
  if (experience_min != null && experience_max != null) return `${experience_min}–${experience_max} yrs`
  return `${experience_min ?? experience_max}+ yrs`
}
