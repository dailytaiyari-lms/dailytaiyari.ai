import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import toast from 'react-hot-toast'
import {
  Briefcase, Plus, Users, ExternalLink, Pencil, Trash2, Loader2,
  ChevronRight, X, Building2, MapPin, Flag, RotateCcw,
} from 'lucide-react'
import { jobAdminService } from '../services/jobService'
import { useFeatureLabel } from '../context/tenantStore'
import { courseService } from '../services/courseService'
import { EMPLOYMENT_TYPES, WORK_MODES, CATEGORIES, categoryMeta } from '../components/jobs/jobShared'
import RichMarkdownEditor from '../components/common/RichMarkdownEditor'
import Loading from '../components/common/Loading'

const STATUS_TINT = {
  draft: 'bg-surface-100 text-surface-600 dark:bg-surface-800 dark:text-surface-300',
  published: 'bg-success-50 text-success-700 dark:bg-success-900/20 dark:text-success-300',
  closed: 'bg-amber-50 text-amber-700 dark:bg-amber-900/20 dark:text-amber-300',
  archived: 'bg-surface-100 text-surface-500 dark:bg-surface-800 dark:text-surface-400',
}

const EMPTY = {
  title: '', job_type: 'internal', category: 'job', department: '', location: '',
  work_mode: 'onsite', employment_type: 'full_time',
  experience_min: '', experience_max: '', salary_min: '', salary_max: '',
  salary_currency: 'INR', salary_period: 'year', description: '', requirements: '',
  external_url: '', openings: 1, deadline: '', status: 'draft', related_course_ids: [],
}

const Field = ({ label, children, required }) => (
  <div>
    <label className="block text-sm font-medium mb-1.5">
      {label} {required && <span className="text-error-500">*</span>}
    </label>
    {children}
  </div>
)

const JobFormModal = ({ initial, onClose, onSaved }) => {
  const [form, setForm] = useState(() => ({
    ...EMPTY,
    ...(initial || {}),
    related_course_ids: (initial?.related_courses || []).map((c) => c.id),
  }))
  const set = (k) => (v) => setForm((s) => ({ ...s, [k]: v }))
  const setInput = (k) => (e) => set(k)(e.target.value)
  const isEdit = !!initial?.id

  const { data: coursesRaw } = useQuery({
    queryKey: ['admin-courses-for-jobs'],
    queryFn: () => courseService.getCourses(),
  })
  const courses = Array.isArray(coursesRaw) ? coursesRaw : (coursesRaw?.results || [])
  const toggleCourse = (id) =>
    setForm((s) => ({
      ...s,
      related_course_ids: s.related_course_ids.includes(id)
        ? s.related_course_ids.filter((x) => x !== id)
        : [...s.related_course_ids, id],
    }))

  const save = useMutation({
    mutationFn: () => {
      const payload = {
        ...form,
        experience_min: form.experience_min === '' ? null : Number(form.experience_min),
        experience_max: form.experience_max === '' ? null : Number(form.experience_max),
        salary_min: form.salary_min === '' ? null : Number(form.salary_min),
        salary_max: form.salary_max === '' ? null : Number(form.salary_max),
        openings: Number(form.openings) || 1,
        deadline: form.deadline || null,
        related_course_ids: form.related_course_ids,
      }
      delete payload.related_courses
      return isEdit ? jobAdminService.updateJob(initial.id, payload) : jobAdminService.createJob(payload)
    },
    onSuccess: () => { toast.success(isEdit ? 'Job updated.' : 'Job created.'); onSaved() },
    onError: (e) => {
      const d = e?.response?.data
      toast.error(d?.external_url?.[0] || d?.detail || 'Could not save job.')
    },
  })

  const submit = () => {
    if (!form.title.trim()) { toast.error('Title is required.'); return }
    if (form.job_type === 'external' && !form.external_url.trim()) {
      toast.error('External postings need an application link.'); return
    }
    save.mutate()
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50" onClick={onClose}>
      <div className="card p-6 w-full max-w-2xl max-h-[92vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-xl font-display font-bold">{isEdit ? 'Edit Job' : 'Create Job'}</h2>
          <button onClick={onClose} className="text-surface-400 hover:text-surface-700"><X className="w-5 h-5" /></button>
        </div>

        <div className="space-y-4">
          <Field label="Job title" required>
            <input value={form.title} onChange={setInput('title')} className="input py-2.5" placeholder="e.g. Senior Content Engineer" />
          </Field>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <Field label="Category" required>
              <select value={form.category} onChange={setInput('category')} className="input py-2.5">
                {CATEGORIES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
              </select>
            </Field>
            <Field label="Hiring type" required>
              <select value={form.job_type} onChange={setInput('job_type')} className="input py-2.5">
                <option value="internal">Internal Hiring (managed here)</option>
                <option value="external">External Posting (link out)</option>
              </select>
            </Field>
            <Field label="Status">
              <select value={form.status} onChange={setInput('status')} className="input py-2.5">
                <option value="draft">Draft</option>
                <option value="published">Published</option>
                <option value="closed">Closed</option>
                <option value="archived">Archived</option>
              </select>
            </Field>
          </div>

          {form.job_type === 'external' && (
            <Field label="External application URL" required>
              <input value={form.external_url} onChange={setInput('external_url')} className="input py-2.5" placeholder="https://careers.example.com/job/123" />
            </Field>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Field label="Department"><input value={form.department} onChange={setInput('department')} className="input py-2.5" /></Field>
            <Field label="Location"><input value={form.location} onChange={setInput('location')} className="input py-2.5" placeholder="City / Remote" /></Field>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <Field label="Employment">
              <select value={form.employment_type} onChange={setInput('employment_type')} className="input py-2.5">
                {EMPLOYMENT_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
              </select>
            </Field>
            <Field label="Work mode">
              <select value={form.work_mode} onChange={setInput('work_mode')} className="input py-2.5">
                {WORK_MODES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
              </select>
            </Field>
            <Field label="Openings"><input type="number" min={1} value={form.openings} onChange={setInput('openings')} className="input py-2.5" /></Field>
            <Field label="Deadline"><input type="date" value={form.deadline ? String(form.deadline).slice(0, 10) : ''} onChange={setInput('deadline')} className="input py-2.5" /></Field>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <Field label="Exp min (yrs)"><input type="number" min={0} value={form.experience_min} onChange={setInput('experience_min')} className="input py-2.5" /></Field>
            <Field label="Exp max (yrs)"><input type="number" min={0} value={form.experience_max} onChange={setInput('experience_max')} className="input py-2.5" /></Field>
            <Field label="Salary min"><input type="number" min={0} value={form.salary_min} onChange={setInput('salary_min')} className="input py-2.5" /></Field>
            <Field label="Salary max"><input type="number" min={0} value={form.salary_max} onChange={setInput('salary_max')} className="input py-2.5" /></Field>
          </div>

          <Field label="Description">
            <RichMarkdownEditor value={form.description} onChange={set('description')} rows={6} />
          </Field>
          <Field label="Requirements">
            <RichMarkdownEditor value={form.requirements} onChange={set('requirements')} rows={4} />
          </Field>

          <Field label="Recommended courses">
            <p className="text-xs text-surface-500 -mt-1 mb-2">
              Suggest courses that help candidates upskill for this role. Shown as tiles on the job page.
            </p>
            {courses.length === 0 ? (
              <p className="text-sm text-surface-400">No courses available in this tenant yet.</p>
            ) : (
              <div className="max-h-44 overflow-y-auto rounded-xl border border-surface-200 dark:border-surface-700 divide-y divide-surface-100 dark:divide-surface-800">
                {courses.map((c) => {
                  const checked = form.related_course_ids.includes(c.id)
                  return (
                    <label key={c.id} className="flex items-center gap-3 px-3 py-2 text-sm cursor-pointer hover:bg-surface-50 dark:hover:bg-surface-800/50">
                      <input type="checkbox" checked={checked} onChange={() => toggleCourse(c.id)} className="rounded border-surface-300 text-primary-600 focus:ring-primary-500" />
                      <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: c.color || '#3B82F6' }} />
                      <span className="flex-1 min-w-0 truncate">{c.name}</span>
                      <span className="text-xs text-surface-400 shrink-0">{c.pricing_type === 'paid' ? `${c.currency || 'INR'} ${c.price}` : 'Free'}</span>
                    </label>
                  )
                })}
              </div>
            )}
            {form.related_course_ids.length > 0 && (
              <p className="text-xs text-surface-500 mt-1.5">{form.related_course_ids.length} course{form.related_course_ids.length === 1 ? '' : 's'} selected</p>
            )}
          </Field>
        </div>

        <div className="flex items-center justify-end gap-2 mt-6">
          <button onClick={onClose} className="btn-secondary">Cancel</button>
          <button onClick={submit} disabled={save.isPending} className="btn-primary inline-flex items-center gap-2">
            {save.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
            {isEdit ? 'Save changes' : 'Create job'}
          </button>
        </div>
      </div>
    </div>
  )
}

const JobManager = () => {
  const navigate = useNavigate()
  const jobsLabel = useFeatureLabel('jobs', 'Jobs')
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(null) // job object or {} for new
  const [showForm, setShowForm] = useState(false)

  const { data: jobs = [], isLoading } = useQuery({
    queryKey: ['admin-jobs'],
    queryFn: () => jobAdminService.getJobs(),
  })

  const del = useMutation({
    mutationFn: (id) => jobAdminService.deleteJob(id),
    onSuccess: () => { toast.success('Job deleted.'); queryClient.invalidateQueries({ queryKey: ['admin-jobs'] }) },
    onError: () => toast.error('Could not delete job.'),
  })

  const restore = useMutation({
    mutationFn: (id) => jobAdminService.restoreJob(id),
    onSuccess: (data) => { toast.success(data?.message || 'Job restored.'); queryClient.invalidateQueries({ queryKey: ['admin-jobs'] }) },
    onError: () => toast.error('Could not restore job.'),
  })

  const onSaved = () => {
    setShowForm(false); setEditing(null)
    queryClient.invalidateQueries({ queryKey: ['admin-jobs'] })
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-display font-bold flex items-center gap-2">
            <Briefcase className="w-6 h-6 text-primary-500" /> {jobsLabel}
          </h1>
          <p className="text-surface-500 text-sm mt-1">Create openings and manage your hiring pipeline.</p>
        </div>
        <button onClick={() => { setEditing(null); setShowForm(true) }} className="btn-primary inline-flex items-center gap-2">
          <Plus className="w-4 h-4" /> New Job
        </button>
      </div>

      {isLoading ? (
        <Loading />
      ) : jobs.length === 0 ? (
        <div className="card p-10 text-center text-surface-500">
          <Briefcase className="w-10 h-10 mx-auto mb-2 text-surface-300" />
          <p>No jobs yet. Create your first opening.</p>
        </div>
      ) : (
        <div className="grid gap-3">
          {jobs.map((job, i) => (
            <motion.div
              key={job.id}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.03 }}
              className="card p-5"
            >
              <div className="flex items-start justify-between gap-3 flex-wrap">
                <button
                  onClick={() => !job.is_external && navigate(`/admin/jobs/${job.id}`)}
                  className="text-left flex-1 min-w-0 group"
                >
                  <div className="flex items-center gap-2 flex-wrap">
                    <h3 className="font-semibold text-lg truncate">{job.title}</h3>
                    <span className={`badge ${categoryMeta(job.category).tint}`}>{categoryMeta(job.category).label}</span>
                    <span className={`badge ${STATUS_TINT[job.status] || STATUS_TINT.draft} capitalize`}>{job.status}</span>
                    {job.is_external ? (
                      <span className="badge bg-indigo-50 text-indigo-700 dark:bg-indigo-900/20 dark:text-indigo-300"><ExternalLink className="w-3 h-3" /> External</span>
                    ) : (
                      <span className="badge badge-primary">Internal</span>
                    )}
                  </div>
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-2 text-xs text-surface-500">
                    {job.department && <span className="inline-flex items-center gap-1"><Building2 className="w-3.5 h-3.5" />{job.department}</span>}
                    {job.location && <span className="inline-flex items-center gap-1"><MapPin className="w-3.5 h-3.5" />{job.location}</span>}
                    <span className="inline-flex items-center gap-1"><Users className="w-3.5 h-3.5" />{job.applications_count ?? 0} applicant{(job.applications_count ?? 0) === 1 ? '' : 's'}</span>
                    {(job.reports_count ?? 0) > 0 && (
                      <span className="inline-flex items-center gap-1 text-amber-600 dark:text-amber-400"><Flag className="w-3.5 h-3.5" />{job.reports_count} closed-report{job.reports_count === 1 ? '' : 's'}</span>
                    )}
                  </div>
                </button>

                <div className="flex items-center gap-1.5 shrink-0">
                  {(job.status === 'archived' || job.status === 'closed') && (
                    <button
                      onClick={() => restore.mutate(job.id)}
                      disabled={restore.isPending}
                      className="btn-secondary text-sm inline-flex items-center gap-1.5"
                      title="Republish and clear closed-reports"
                    >
                      <RotateCcw className="w-4 h-4" /> Restore
                    </button>
                  )}
                  {!job.is_external && (
                    <button
                      onClick={() => navigate(`/admin/jobs/${job.id}`)}
                      className="btn-secondary text-sm inline-flex items-center gap-1.5"
                    >
                      <Users className="w-4 h-4" /> Pipeline <ChevronRight className="w-4 h-4" />
                    </button>
                  )}
                  <button
                    onClick={() => { setEditing(job); setShowForm(true) }}
                    className="p-2 rounded-lg hover:bg-surface-100 dark:hover:bg-surface-800 text-surface-500"
                    title="Edit"
                  >
                    <Pencil className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => { if (confirm(`Delete "${job.title}"? This removes all its applications.`)) del.mutate(job.id) }}
                    className="p-2 rounded-lg hover:bg-error-50 dark:hover:bg-error-900/20 text-error-500"
                    title="Delete"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>
            </motion.div>
          ))}
        </div>
      )}

      {showForm && (
        <JobFormModal
          initial={editing}
          onClose={() => { setShowForm(false); setEditing(null) }}
          onSaved={onSaved}
        />
      )}
    </div>
  )
}

export default JobManager
