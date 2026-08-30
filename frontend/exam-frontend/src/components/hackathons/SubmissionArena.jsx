import { useRef, useState } from 'react'
import toast from 'react-hot-toast'
import {
  UploadCloud, File as FileIcon, X, Github, Globe, Video, Send, Loader2,
  Download, CheckCircle2, AlertTriangle,
} from 'lucide-react'
import { RichContent, formatBytes, formatDateTime } from './hackathonShared'

const extOf = (name) => (name.split('.').pop() || '').toLowerCase()

/** Project submission round: drag-and-drop deliverables plus repo/demo/video links. */
const SubmissionArena = ({ stage, submission, onSubmit, isSaving, onDownload }) => {
  const inputRef = useRef(null)
  const [dragging, setDragging] = useState(false)
  const [files, setFiles] = useState([])
  const [form, setForm] = useState({
    title: submission?.title || '',
    summary: submission?.summary || '',
    repo_url: submission?.repo_url || '',
    demo_url: submission?.demo_url || '',
    video_url: submission?.video_url || '',
  })

  const allowed = (stage.allowed_file_types || []).map((t) => String(t).toLowerCase().replace(/^\./, ''))
  const maxFiles = stage.max_files || 1
  const maxMb = stage.max_file_mb || 50
  const locked = Boolean(submission) && !stage.allow_resubmission

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }))

  const addFiles = (incoming) => {
    const next = []
    for (const file of incoming) {
      if (allowed.length && !allowed.includes(extOf(file.name))) {
        toast.error(`"${file.name}" isn't an accepted file type (${allowed.join(', ')}).`)
        continue
      }
      if (file.size > maxMb * 1024 * 1024) {
        toast.error(`"${file.name}" is larger than ${maxMb} MB.`)
        continue
      }
      next.push(file)
    }
    setFiles((current) => {
      const merged = [...current, ...next]
      if (merged.length > maxFiles) {
        toast.error(`You can attach at most ${maxFiles} file${maxFiles === 1 ? '' : 's'}.`)
        return merged.slice(0, maxFiles)
      }
      return merged
    })
  }

  const submit = (e) => {
    e.preventDefault()
    if (stage.require_repo_url && !form.repo_url.trim()) {
      toast.error('A repository URL is required for this round.')
      return
    }
    if (stage.require_demo_url && !form.demo_url.trim()) {
      toast.error('A demo URL is required for this round.')
      return
    }
    if (stage.require_video_url && !form.video_url.trim()) {
      toast.error('A video URL is required for this round.')
      return
    }
    if (!files.length && !submission
        && !form.repo_url.trim() && !form.demo_url.trim()
        && !form.video_url.trim() && !form.summary.trim()) {
      toast.error('Attach a file or share a link before submitting.')
      return
    }
    onSubmit({ ...form, files })
  }

  return (
    <form onSubmit={submit} className="max-w-3xl space-y-5">
      {stage.submission_instructions && (
        <div className="card p-6">
          <h3 className="font-semibold mb-3">What to submit</h3>
          <RichContent content={stage.submission_instructions} />
        </div>
      )}

      {submission && (
        <div className="card p-5 bg-emerald-50/60 dark:bg-emerald-900/10 border-emerald-100 dark:border-emerald-900/30">
          <div className="flex items-start gap-3">
            <CheckCircle2 className="w-5 h-5 text-emerald-600 shrink-0 mt-0.5" />
            <div className="min-w-0 flex-1">
              <p className="font-medium text-emerald-700 dark:text-emerald-300">
                Submitted {formatDateTime(submission.submitted_at)}
                {submission.is_late && (
                  <span className="badge badge-warning ml-2">Late</span>
                )}
              </p>
              {submission.files?.length > 0 && (
                <div className="mt-2 space-y-1">
                  {submission.files.map((f) => (
                    <button
                      key={f.id}
                      type="button"
                      onClick={() => onDownload?.(f)}
                      className="flex items-center gap-2 text-sm text-emerald-700 dark:text-emerald-300 hover:underline"
                    >
                      <Download className="w-3.5 h-3.5" />
                      {f.original_name}
                      <span className="text-emerald-600/60">{formatBytes(f.size_bytes)}</span>
                    </button>
                  ))}
                </div>
              )}
              {stage.allow_resubmission && (
                <p className="text-sm text-emerald-600/80 dark:text-emerald-300/70 mt-2">
                  You can replace this submission until the round closes.
                </p>
              )}
            </div>
          </div>
        </div>
      )}

      {locked ? (
        <div className="card p-5 flex items-center gap-3">
          <AlertTriangle className="w-5 h-5 text-amber-500 shrink-0" />
          <p className="text-sm text-surface-600 dark:text-surface-300">
            This round allows one submission only — yours is locked in and with the judges.
          </p>
        </div>
      ) : (
        <div className="card p-6 space-y-5">
          <label className="block">
            <span className="text-sm font-medium">Project title</span>
            <input className="input mt-1" value={form.title} onChange={set('title')} placeholder="Give your entry a name" />
          </label>

          <label className="block">
            <span className="text-sm font-medium">Summary</span>
            <textarea
              className="input mt-1 min-h-[120px]"
              value={form.summary}
              onChange={set('summary')}
              placeholder="What did you build, and what makes it work?"
            />
          </label>

          {/* Files */}
          <div>
            <span className="text-sm font-medium">Files</span>
            <div
              onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => {
                e.preventDefault()
                setDragging(false)
                addFiles(Array.from(e.dataTransfer.files || []))
              }}
              onClick={() => inputRef.current?.click()}
              className={`mt-1 rounded-xl border-2 border-dashed p-6 text-center cursor-pointer transition-colors ${
                dragging
                  ? 'border-primary-500 bg-primary-50 dark:bg-primary-900/20'
                  : 'border-surface-200 dark:border-surface-700 hover:border-primary-300'
              }`}
            >
              <UploadCloud className="w-8 h-8 mx-auto text-surface-400 mb-2" />
              <p className="text-sm font-medium">Drop files here, or click to browse</p>
              <p className="text-xs text-surface-400 mt-1">
                {allowed.length ? allowed.map((a) => `.${a}`).join(', ') : 'Any file type'}
                {' · '}up to {maxMb} MB each · max {maxFiles} file{maxFiles === 1 ? '' : 's'}
              </p>
              <input
                ref={inputRef}
                type="file"
                multiple={maxFiles > 1}
                className="hidden"
                accept={allowed.length ? allowed.map((a) => `.${a}`).join(',') : undefined}
                onChange={(e) => {
                  addFiles(Array.from(e.target.files || []))
                  e.target.value = ''
                }}
              />
            </div>

            {files.length > 0 && (
              <ul className="mt-3 space-y-2">
                {files.map((file, i) => (
                  <li
                    key={`${file.name}-${i}`}
                    className="flex items-center gap-3 p-2.5 rounded-lg bg-surface-50 dark:bg-surface-800"
                  >
                    <FileIcon className="w-4 h-4 text-surface-400 shrink-0" />
                    <span className="text-sm truncate flex-1">{file.name}</span>
                    <span className="text-xs text-surface-400 shrink-0">{formatBytes(file.size)}</span>
                    <button
                      type="button"
                      className="btn-icon shrink-0"
                      onClick={() => setFiles((f) => f.filter((_, idx) => idx !== i))}
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* Links */}
          <div className="grid sm:grid-cols-3 gap-4">
            {[
              ['repo_url', 'Repository', Github, stage.require_repo_url, 'https://github.com/…'],
              ['demo_url', 'Live demo', Globe, stage.require_demo_url, 'https://…'],
              ['video_url', 'Demo video', Video, stage.require_video_url, 'https://youtu.be/…'],
            ].map(([key, label, Icon, required, placeholder]) => (
              <label key={key} className="block">
                <span className="text-sm font-medium inline-flex items-center gap-1.5">
                  <Icon className="w-3.5 h-3.5" />{label}{required && ' *'}
                </span>
                <input
                  className="input mt-1"
                  value={form[key]}
                  onChange={set(key)}
                  placeholder={placeholder}
                  required={Boolean(required)}
                />
              </label>
            ))}
          </div>

          <div className="flex justify-end pt-2">
            <button type="submit" className="btn-primary" disabled={isSaving}>
              {isSaving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
              {submission ? 'Replace submission' : 'Submit project'}
            </button>
          </div>
        </div>
      )}
    </form>
  )
}

export default SubmissionArena
