import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  Plus, ClipboardList, Clock, Users, Trash2, Pencil, Search,
  CheckCircle2, FileEdit, Archive, Loader2, ArrowLeft, ClipboardCheck,
  Inbox, Sparkles,
} from 'lucide-react'
import { mockTestBuilderService } from '../services/mockTestBuilderService'
import MockAiJobBanners from '../components/admin/mockAi/MockAiJobBanners'

const STATUS_BADGE = {
  draft: { label: 'Draft', cls: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300', icon: FileEdit },
  published: { label: 'Published', cls: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300', icon: CheckCircle2 },
  archived: { label: 'Archived', cls: 'bg-surface-200 text-surface-600 dark:bg-surface-700 dark:text-surface-300', icon: Archive },
}

export default function MockTestManager() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')

  const { data: tests = [], isLoading } = useQuery({
    queryKey: ['admin-mock-tests'],
    queryFn: () => mockTestBuilderService.list(),
  })

  const createMut = useMutation({
    mutationFn: () => mockTestBuilderService.create({
      title: 'Untitled Mock Test', duration_minutes: 60, status: 'draft',
    }),
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: ['admin-mock-tests'] })
      navigate(`/admin/mock-tests/${created.id}`)
    },
    onError: () => toast.error('Could not create mock test'),
  })

  const deleteMut = useMutation({
    mutationFn: (id) => mockTestBuilderService.remove(id),
    onSuccess: () => {
      toast.success('Mock test deleted')
      qc.invalidateQueries({ queryKey: ['admin-mock-tests'] })
    },
    onError: () => toast.error('Delete failed'),
  })

  const filtered = tests.filter((t) => {
    if (statusFilter !== 'all' && t.status !== statusFilter) return false
    if (search && !t.title.toLowerCase().includes(search.toLowerCase())) return false
    return true
  })

  return (
    <div className="max-w-6xl mx-auto px-4 py-8">
      <button
        onClick={() => navigate('/admin-dashboard')}
        className="flex items-center gap-2 text-sm text-surface-500 hover:text-surface-800 dark:hover:text-surface-200 mb-4"
      >
        <ArrowLeft className="w-4 h-4" /> Back to Admin
      </button>

      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-surface-900 dark:text-white flex items-center gap-2">
            <ClipboardList className="w-6 h-6 text-primary-500" /> Mock Tests
          </h1>
          <p className="text-surface-500 text-sm mt-1">
            Create and manage full exams with MCQ, numerical, subjective and coding questions.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => navigate('/admin/mock-tests/grading')}
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl border border-surface-200 dark:border-surface-700 hover:bg-surface-50 dark:hover:bg-surface-800 font-medium"
          >
            <ClipboardCheck className="w-4 h-4" /> Grading
          </button>
          <button
            onClick={() => navigate('/admin/mock-tests/ai')}
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-gradient-to-r from-primary-600 to-purple-600 text-white font-medium shadow-sm hover:opacity-90"
          >
            <Sparkles className="w-4 h-4" /> Generate with AI
          </button>
          <button
            onClick={() => createMut.mutate()}
            disabled={createMut.isPending}
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-primary-600 hover:bg-primary-700 text-white font-medium shadow-sm disabled:opacity-60"
          >
            {createMut.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
            New Mock Test
          </button>
        </div>
      </div>

      {/* Generation runs on the server, so an in-flight or reviewable run shows
          up here every time the admin comes back to this screen. */}
      <MockAiJobBanners
        className="mb-5"
        onOpen={(job) => navigate(
          job.mock_test
            ? `/admin/mock-tests/${job.mock_test}?ai=1`
            : '/admin/mock-tests/ai',
        )}
      />

      <div className="flex flex-col sm:flex-row gap-3 mb-5">
        <div className="relative flex-1">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-surface-400" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search mock tests…"
            className="w-full pl-9 pr-3 py-2.5 rounded-xl border border-surface-200 dark:border-surface-700 bg-white dark:bg-surface-800 text-sm focus:outline-none focus:ring-2 focus:ring-primary-500/40"
          />
        </div>
        <div className="flex gap-1 bg-surface-100 dark:bg-surface-800 rounded-xl p-1">
          {['all', 'draft', 'published', 'archived'].map((s) => (
            <button
              key={s}
              onClick={() => setStatusFilter(s)}
              className={`px-3 py-1.5 rounded-lg text-sm capitalize transition ${
                statusFilter === s
                  ? 'bg-white dark:bg-surface-700 shadow-sm text-surface-900 dark:text-white font-medium'
                  : 'text-surface-500 hover:text-surface-800'
              }`}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-20"><Loader2 className="w-6 h-6 animate-spin text-primary-500" /></div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-20 border-2 border-dashed border-surface-200 dark:border-surface-700 rounded-2xl">
          <ClipboardList className="w-10 h-10 mx-auto text-surface-300 mb-3" />
          <p className="text-surface-500">No mock tests yet. Create your first one.</p>
        </div>
      ) : (
        <div className="grid gap-3">
          {filtered.map((t) => {
            const badge = STATUS_BADGE[t.status] || STATUS_BADGE.draft
            const BadgeIcon = badge.icon
            return (
              <div
                key={t.id}
                className="group flex items-center gap-4 p-4 rounded-2xl border border-surface-200 dark:border-surface-700 bg-white dark:bg-surface-800 hover:shadow-md transition cursor-pointer"
                onClick={() => navigate(`/admin/mock-tests/${t.id}`)}
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <h3 className="font-semibold text-surface-900 dark:text-white truncate">{t.title}</h3>
                    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${badge.cls}`}>
                      <BadgeIcon className="w-3 h-3" /> {badge.label}
                    </span>
                    {t.is_pyp && <span className="px-2 py-0.5 rounded-full text-xs bg-indigo-100 text-indigo-700">PYQ</span>}
                  </div>
                  <div className="flex flex-wrap items-center gap-4 text-xs text-surface-500">
                    <span className="flex items-center gap-1"><Clock className="w-3.5 h-3.5" /> {t.duration_minutes} min</span>
                    <span>{(t.items_count || 0) + (t.bank_questions_count || 0)} questions</span>
                    <span>{Number(t.computed_total_marks || t.total_marks || 0)} marks</span>
                    <span className="flex items-center gap-1"><Users className="w-3.5 h-3.5" /> {t.total_attempts || 0} attempts</span>
                  </div>
                </div>
                <button
                  onClick={(e) => { e.stopPropagation(); navigate(`/admin/mock-tests/${t.id}/submissions`) }}
                  className="p-2 rounded-lg text-surface-400 hover:text-primary-600 hover:bg-primary-50 dark:hover:bg-primary-900/20"
                  title="View submissions"
                >
                  <Inbox className="w-4 h-4" />
                </button>
                <button
                  onClick={(e) => { e.stopPropagation(); navigate(`/admin/mock-tests/${t.id}`) }}
                  className="p-2 rounded-lg text-surface-400 hover:text-primary-600 hover:bg-primary-50 dark:hover:bg-primary-900/20"
                  title="Edit"
                >
                  <Pencil className="w-4 h-4" />
                </button>
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    if (window.confirm(`Delete "${t.title}"? This cannot be undone.`)) deleteMut.mutate(t.id)
                  }}
                  className="p-2 rounded-lg text-surface-400 hover:text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-900/20"
                  title="Delete"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
