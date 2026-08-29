import { useState, useRef, useEffect } from 'react'
import { motion } from 'framer-motion'
import toast from 'react-hot-toast'
import {
    Plus, Pencil, Trash2, X, Loader2, Save, AlertTriangle,
    CheckCircle2, Circle, ImagePlus, Loader, FileText, GripVertical,
} from 'lucide-react'
import { contentBuilderService as svc } from '../../services/contentBuilderService'
import CertificatePreview from '../certificate/CertificatePreview'

/* Fast, cheap modal transitions (no backdrop-blur — it repaints the whole
 * builder tree behind the overlay and makes opening feel sluggish). */
const OVERLAY_MOTION = {
    initial: { opacity: 0 },
    animate: { opacity: 1 },
    exit: { opacity: 0 },
    transition: { duration: 0.12 },
}
const PANEL_MOTION = {
    initial: { opacity: 0, scale: 0.97, y: 8 },
    animate: { opacity: 1, scale: 1, y: 0 },
    exit: { opacity: 0, scale: 0.97, y: 8 },
    transition: { duration: 0.14, ease: 'easeOut' },
}

/* ===========================================================================
 * Drag & drop reordering
 * ------------------------------------------------------------------------
 * `useDragReorder` keeps a local copy of a list that is rearranged live while
 * a row is dragged, then reports the final id sequence once. Dragging only
 * starts from the grip handle so row clicks and row actions keep working, and
 * every handler stops propagation so nested lists (subject → chapter → topic)
 * never steal each other's drags.
 * ========================================================================= */
export const useDragReorder = (items, onReorder) => {
    const [list, setList] = useState(items)
    const [armedId, setArmedId] = useState(null)     // handle pressed → row is draggable
    const [draggingId, setDraggingId] = useState(null)
    const latest = useRef(items)
    const dirty = useRef(false)
    const pending = useRef(null)                     // id sequence awaiting server confirmation

    useEffect(() => {
        if (draggingId) return
        let next = items
        const want = pending.current
        if (want) {
            const byId = new Map(items.map((it) => [String(it.id), it]))
            const settled = items.length === want.length &&
                items.every((it, i) => String(it.id) === String(want[i]))
            if (settled || want.length !== items.length || want.some((id) => !byId.has(String(id)))) {
                pending.current = null
            } else {
                // Server hasn't caught up yet — keep showing the dropped order.
                next = want.map((id) => byId.get(String(id)))
            }
        }
        setList(next)
        latest.current = next
    }, [items, draggingId])

    const moveOver = (overId) => {
        setList((prev) => {
            const from = prev.findIndex((it) => it.id === draggingId)
            const to = prev.findIndex((it) => it.id === overId)
            if (from < 0 || to < 0 || from === to) return prev
            const next = prev.slice()
            next.splice(to, 0, next.splice(from, 1)[0])
            dirty.current = true
            latest.current = next
            return next
        })
    }

    const finish = () => {
        setArmedId(null)
        setDraggingId(null)
        if (!dirty.current) return
        dirty.current = false
        const ids = latest.current.map((it) => it.id)
        pending.current = ids
        onReorder(ids)
    }

    /** Spread on the row wrapper. */
    const rowProps = (id) => ({
        draggable: armedId === id,
        onDragStart: (e) => {
            e.stopPropagation()
            e.dataTransfer.effectAllowed = 'move'
            try { e.dataTransfer.setData('text/plain', String(id)) } catch { /* Safari */ }
            setDraggingId(id)
        },
        onDragOver: (e) => {
            if (!draggingId) return
            e.preventDefault()
            e.stopPropagation()
            e.dataTransfer.dropEffect = 'move'
            if (draggingId !== id) moveOver(id)
        },
        onDrop: (e) => {
            if (!draggingId) return
            e.preventDefault()
            e.stopPropagation()
        },
        onDragEnd: (e) => {
            e.stopPropagation()
            finish()
        },
    })

    /** Spread on the grip button inside the row. */
    const handleProps = (id) => ({
        onMouseDown: () => setArmedId(id),
        onMouseUp: () => setArmedId(null),
        onClick: (e) => { e.stopPropagation() },
    })

    return { list, draggingId, rowProps, handleProps }
}

/** Grip affordance that arms a row for dragging. */
export const DragHandle = ({ className = '', size = 14, title = 'Drag to reorder', ...props }) => (
    <span
        {...props}
        title={title}
        aria-label={title}
        className={`shrink-0 cursor-grab active:cursor-grabbing text-surface-300 hover:text-surface-500 dark:text-surface-600 dark:hover:text-surface-400 touch-none ${className}`}
    >
        <GripVertical width={size} height={size} />
    </span>
)

/** Read a File/Blob into a base64 data URL. */
export const fileToDataUrl = (file) =>
    new Promise((resolve, reject) => {
        const reader = new FileReader()
        reader.onload = () => resolve(reader.result)
        reader.onerror = reject
        reader.readAsDataURL(file)
    })

/**
 * Compact image attach / paste / drop control.
 * value = '' | existing URL | data: URL. onChange receives the new value.
 */
export const ImageDrop = ({ value, onChange, label = 'image', compact = false }) => {
    const inputRef = useRef(null)
    const [busy, setBusy] = useState(false)

    const accept = async (file) => {
        if (!file || !file.type?.startsWith('image/')) return
        if (file.size > 5 * 1024 * 1024) return toast.error('Image must be under 5 MB')
        setBusy(true)
        try {
            onChange(await fileToDataUrl(file))
        } catch {
            toast.error('Could not read image')
        } finally {
            setBusy(false)
        }
    }

    const onPaste = (e) => {
        const item = [...(e.clipboardData?.items || [])].find((i) => i.type.startsWith('image/'))
        if (item) { e.preventDefault(); accept(item.getAsFile()) }
    }
    const onDrop = (e) => { e.preventDefault(); accept(e.dataTransfer?.files?.[0]) }

    if (value) {
        return (
            <div className="relative inline-block mt-1.5 group/img">
                <img src={value} alt={label} className={`rounded-lg border border-surface-200 dark:border-surface-700 object-contain ${compact ? 'h-12' : 'max-h-40'}`} />
                <button type="button" onClick={() => onChange('')} title="Remove image"
                    className="absolute -top-2 -right-2 w-6 h-6 rounded-full bg-rose-500 text-white flex items-center justify-center shadow hover:bg-rose-600">
                    <X className="w-3.5 h-3.5" />
                </button>
            </div>
        )
    }

    return (
        <div
            tabIndex={0}
            onPaste={onPaste}
            onDrop={onDrop}
            onDragOver={(e) => e.preventDefault()}
            onClick={() => inputRef.current?.click()}
            className={`mt-1.5 flex items-center gap-2 rounded-lg border border-dashed border-surface-300 dark:border-surface-600 text-surface-400 hover:text-primary-600 hover:border-primary-400 cursor-pointer transition-colors focus:outline-none focus:ring-2 focus:ring-primary-400/40 ${compact ? 'px-2 py-1.5 text-[11px]' : 'px-3 py-2.5 text-xs'}`}
        >
            {busy ? <Loader className="w-3.5 h-3.5 animate-spin" /> : <ImagePlus className="w-3.5 h-3.5" />}
            <span>{busy ? 'Reading…' : `Paste, drop or click to add ${label}`}</span>
            <input ref={inputRef} type="file" accept="image/*" className="hidden" onChange={(e) => accept(e.target.files?.[0])} />
        </div>
    )
}

/** Serialize an image slot for submission: send data URLs (new), null to clear
 * a previously-set image, and omit unchanged existing URLs. */
export const imagePayload = (value, initial) => {
    if (typeof value === 'string' && value.startsWith('data:')) return { send: true, value }
    if (!value && initial) return { send: true, value: null }   // cleared
    return { send: false }
}

/**
 * Notes editor: a textarea that accepts pasted / dropped / picked images.
 * Images are uploaded to blob storage and inserted at the cursor as Markdown
 * (or an <img> tag when the note is already HTML), so they render for students.
 */
export const NotesTextarea = ({ value, onChange, rows }) => {
    const ref = useRef(null)
    const fileRef = useRef(null)
    const [busy, setBusy] = useState(false)

    const insertAtCursor = (text) => {
        const el = ref.current
        const start = el?.selectionStart ?? value.length
        const end = el?.selectionEnd ?? value.length
        onChange(value.slice(0, start) + text + value.slice(end))
    }

    const upload = async (file) => {
        if (!file || !file.type?.startsWith('image/')) return
        if (file.size > 8 * 1024 * 1024) return toast.error('Image must be under 8 MB')
        setBusy(true)
        try {
            const dataUrl = await fileToDataUrl(file)
            const { url } = await svc.uploadImage(dataUrl)
            const isHtml = (value || '').trimStart().startsWith('<')
            insertAtCursor(isHtml ? `\n<img src="${url}" alt="" />\n` : `\n\n![image](${url})\n\n`)
            toast.success('Image added')
        } catch {
            toast.error('Image upload failed')
        } finally {
            setBusy(false)
        }
    }

    const onPaste = (e) => {
        const item = [...(e.clipboardData?.items || [])].find((i) => i.type.startsWith('image/'))
        if (item) { e.preventDefault(); upload(item.getAsFile()) }
    }
    const onDrop = (e) => {
        if (e.dataTransfer?.files?.length && e.dataTransfer.files[0].type.startsWith('image/')) {
            e.preventDefault(); upload(e.dataTransfer.files[0])
        }
    }

    return (
        <div>
            <textarea
                ref={ref}
                className="input font-mono text-sm"
                rows={rows || 10}
                value={value ?? ''}
                onChange={(e) => onChange(e.target.value)}
                onPaste={onPaste}
                onDrop={onDrop}
            />
            <div className="flex items-center gap-2 mt-1.5">
                <button type="button" onClick={() => fileRef.current?.click()} className="text-xs font-semibold text-primary-600 hover:text-primary-700 inline-flex items-center gap-1">
                    {busy ? <Loader className="w-3.5 h-3.5 animate-spin" /> : <ImagePlus className="w-3.5 h-3.5" />} Add image
                </button>
                <span className="text-[11px] text-surface-400">or paste / drop an image directly into the editor</span>
                <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={(e) => upload(e.target.files?.[0])} />
            </div>
        </div>
    )
}

/* ===========================================================================
 * Shared field / form configuration and modals used by the admin content
 * tools (ContentBuilder table view and the focused CourseManager).
 * Single source of truth so both stay in sync.
 * ========================================================================= */
export const EXAM_TYPES = ['competitive', 'board', 'entrance', 'government', 'skill']
export const EXAM_STATUS = ['active', 'coming_soon', 'inactive']
export const DIFFICULTY = ['easy', 'medium', 'hard']
export const IMPORTANCE = ['low', 'medium', 'high', 'critical']
export const CONTENT_TYPES = ['notes', 'pdf', 'video']
export const CONTENT_TYPE_OPTIONS = [
    { value: 'notes', label: 'Text Notes' },
    { value: 'pdf', label: 'PDF Notes' },
    { value: 'video', label: 'Video' },
]
export const MATERIAL_KIND_OPTIONS = [
    { value: 'study', label: 'Study material' },
    { value: 'practice', label: 'Practice questions' },
]
export const SUBMISSION_TYPE_OPTIONS = [
    { value: 'either', label: 'Text or file (PDF/ZIP)' },
    { value: 'text', label: 'Text answer only' },
    { value: 'pdf', label: 'File upload only (PDF/ZIP)' },
]
export const CONTENT_DIFFICULTY = ['beginner', 'intermediate', 'advanced']
export const CONTENT_STATUS = ['draft', 'published', 'archived']
export const QUIZ_TYPES = ['topic', 'subject', 'chapter', 'daily', 'custom', 'pyq']
export const QUIZ_STATUS = ['draft', 'published', 'archived']
export const QUESTION_TYPES = ['mcq', 'true_false', 'numerical', 'fill_blank']
export const QUESTION_STATUS = ['draft', 'review', 'published', 'archived']
export const QTYPE_LABEL = {
    mcq: 'Multiple Choice', true_false: 'True / False',
    numerical: 'Numerical', fill_blank: 'Fill in the Blank',
}

export const opt = (arr) => arr.map((v) => ({ value: v, label: v.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()) }))

export const SCHEMAS = {
    exam: {
        title: 'Course',
        fields: [
            { name: 'name', label: 'Name', type: 'text', required: true },
            { name: 'code', label: 'Code', type: 'text', required: true, hint: 'Unique slug, e.g. neet' },
            { name: 'subtitle', label: 'Subtitle / tagline', type: 'text', full: true, hint: 'Short line shown under the course title on the details page.' },
            { name: 'course_type', label: 'Type', type: 'select', options: opt(EXAM_TYPES), default: 'competitive' },
            { name: 'status', label: 'Status', type: 'select', options: opt(EXAM_STATUS), default: 'active' },
            { name: 'color', label: 'Color', type: 'color', default: '#3B82F6' },
            { name: 'duration_minutes', label: 'Duration (min)', type: 'number' },
            { name: 'total_marks', label: 'Total Marks', type: 'number' },
            { name: 'is_featured', label: 'Featured', type: 'checkbox' },
            { name: 'negative_marking', label: 'Negative Marking', type: 'checkbox' },
            { name: 'sequential_chapter_unlock', label: 'Lock chapters until previous ones are completed', type: 'checkbox', full: true, hint: 'When on, students must finish each chapter before the next one in the same subject unlocks.' },
            { name: 'pricing_type', label: 'Pricing', type: 'select', options: opt(['free', 'paid']), default: 'free' },
            { name: 'price', label: 'Price', type: 'number', step: '0.01', default: 0, showIf: (v) => v.pricing_type === 'paid', hint: 'Amount the student pays. Payment gateway is handled separately for now.' },
            { name: 'original_price', label: 'Original price (strike-through)', type: 'number', step: '0.01', showIf: (v) => v.pricing_type === 'paid', hint: 'Optional higher price to show a discount.' },
            { name: 'currency', label: 'Currency', type: 'select', options: opt(['INR', 'USD', 'EUR', 'GBP']), default: 'INR', showIf: (v) => v.pricing_type === 'paid' },
            { name: 'description', label: 'Description', type: 'textarea', full: true, image: true, rows: 10, hint: 'Supports rich HTML / Markdown and images — paste, drop, or add an image directly.' },
            { name: 'highlights', label: 'What you will get (one point per line)', type: 'stringlist', full: true, placeholder: 'All Previous Year Questions (PYQ)\nFully solved answers\nExam-oriented approach' },
            { name: 'refund_policy', label: 'Refund policy', type: 'textarea', full: true, hint: 'Shown on the course details page.' },
            { name: 'certificate_enabled', label: 'Issue certificate on completion', type: 'checkbox' },
            { name: 'certificate_template', label: 'Certificate design', type: 'select', options: [
                { value: 'classic', label: 'Classic — navy & gold, ornate' },
                { value: 'modern', label: 'Modern — bold color blocks' },
                { value: 'elegant', label: 'Elegant — cream & gold' },
                { value: 'minimal', label: 'Minimal — clean & monochrome' },
            ], default: 'classic', showIf: (v) => v.certificate_enabled, hint: 'Design students receive when they reach 100% completion.' },
            { name: '_certificate_preview', type: 'certificate_preview', full: true, showIf: (v) => v.certificate_enabled },
        ],
    },
    subject: {
        title: 'Subject',
        fields: [
            { name: 'name', label: 'Name', type: 'text', required: true },
            { name: 'code', label: 'Code', type: 'text', required: true },
            { name: 'weightage', label: 'Weightage (%)', type: 'number', step: '0.01' },
            { name: 'color', label: 'Color', type: 'color', default: '#10B981' },
            { name: 'icon', label: 'Icon name', type: 'text' },
            { name: 'description', label: 'Description', type: 'textarea', full: true },
        ],
    },
    chapter: {
        title: 'Chapter',
        fields: [
            { name: 'name', label: 'Name', type: 'text', required: true },
            { name: 'code', label: 'Code', type: 'text', required: true },
            { name: 'grade', label: 'Grade', type: 'text', hint: 'e.g. 11, 12' },
            { name: 'book_reference', label: 'Book Reference', type: 'text' },
            { name: 'estimated_hours', label: 'Est. Hours', type: 'number', step: '0.1', default: 2 },
            { name: 'description', label: 'Description', type: 'textarea', full: true },
        ],
    },
    topic: {
        title: 'Topic',
        fields: [
            { name: 'name', label: 'Name', type: 'text', required: true },
            { name: 'code', label: 'Code', type: 'text', required: true },
            { name: 'difficulty', label: 'Difficulty', type: 'select', options: opt(DIFFICULTY), default: 'medium' },
            { name: 'importance', label: 'Importance', type: 'select', options: opt(IMPORTANCE), default: 'medium' },
            { name: 'estimated_study_hours', label: 'Est. Study Hours', type: 'number', step: '0.1', default: 1 },
            { name: 'description', label: 'Description', type: 'textarea', full: true },
        ],
    },
    content: {
        title: 'Content',
        fields: [
            { name: 'title', label: 'Title', type: 'text', required: true, full: true },
            { name: 'content_type', label: 'Type', type: 'select', options: CONTENT_TYPE_OPTIONS, default: 'notes' },
            { name: 'material_kind', label: 'Reading purpose', type: 'select', options: MATERIAL_KIND_OPTIONS, default: 'study', showIf: (v) => v.content_type === 'notes' || v.content_type === 'pdf', hint: 'Study material is for learning; Practice questions groups worksheets/question PDFs separately for students.' },
            { name: 'status', label: 'Status', type: 'select', options: opt(CONTENT_STATUS), default: 'draft' },
            { name: 'difficulty', label: 'Difficulty', type: 'select', options: opt(CONTENT_DIFFICULTY), default: 'intermediate' },
            { name: 'estimated_time_minutes', label: 'Read Time (min)', type: 'number', default: 10 },
            { name: 'order', label: 'Order', type: 'number', default: 0 },
            { name: 'author_name', label: 'Author', type: 'text' },
            { name: 'video_url', label: 'Video URL (YouTube, Vimeo or Google Drive)', type: 'text', full: true, showIf: (v) => v.content_type === 'video', hint: 'Paste a YouTube, Vimeo or Google Drive link. Leave blank if uploading a file below.' },
            { name: 'is_free', label: 'Free', type: 'checkbox' },
            { name: 'is_premium', label: 'Premium', type: 'checkbox' },
            { name: 'description', label: 'Description', type: 'textarea', full: true },
            { name: 'content_html', label: 'Content (HTML / Markdown — supports pasted images)', type: 'textarea', full: true, rows: 10, image: true, showIf: (v) => v.content_type === 'notes' },
            { name: 'pdf_file', label: 'PDF File', type: 'file', accept: 'application/pdf', noun: 'PDF', full: true, showIf: (v) => v.content_type === 'pdf', hint: 'Uploaded PDF is shown in-app to students (view only — no download).' },
            { name: 'video_file', label: 'Upload Video', type: 'file', accept: 'video/*', noun: 'video', full: true, showIf: (v) => v.content_type === 'video', hint: 'Or upload a video file to play from our storage. A pasted URL above takes priority.' },
        ],
    },
    quiz: {
        title: 'Quiz',
        fields: [
            { name: 'title', label: 'Title', type: 'text', required: true, full: true },
            { name: 'quiz_type', label: 'Type', type: 'select', options: opt(QUIZ_TYPES), default: 'topic' },
            { name: 'status', label: 'Status', type: 'select', options: opt(QUIZ_STATUS), default: 'draft' },
            { name: 'duration_minutes', label: 'Duration (min)', type: 'number', default: 15 },
            { name: 'passing_marks', label: 'Passing Marks', type: 'number', step: '0.01' },
            { name: 'is_free', label: 'Free', type: 'checkbox' },
            { name: 'shuffle_questions', label: 'Shuffle Questions', type: 'checkbox', default: true },
            { name: 'shuffle_options', label: 'Shuffle Options', type: 'checkbox', default: true },
            { name: 'description', label: 'Description', type: 'textarea', full: true },
        ],
    },
    question: {
        title: 'Question',
        fields: [],
    },
    assignment: {
        title: 'Assignment',
        fields: [
            { name: 'title', label: 'Title', type: 'text', required: true, full: true },
            { name: 'submission_type', label: 'Students submit', type: 'select', options: SUBMISSION_TYPE_OPTIONS, default: 'either' },
            { name: 'status', label: 'Status', type: 'select', options: opt(CONTENT_STATUS), default: 'draft' },
            { name: 'max_marks', label: 'Max marks (optional)', type: 'number' },
            { name: 'order', label: 'Order', type: 'number', default: 0 },
            { name: 'is_timed', label: 'Timed — reject submissions after a deadline', type: 'checkbox' },
            { name: 'due_at', label: 'Due date & time', type: 'datetime-local', full: true, showIf: (v) => !!v.is_timed, hint: 'After this time, students can no longer submit.' },
            { name: 'attachment', label: 'Question paper (PDF or ZIP, optional)', type: 'file', accept: 'application/pdf,application/zip,.zip', noun: 'paper', full: true, hint: 'Optional PDF (shown in-app, view only) or ZIP archive (students download it).' },
            { name: 'instructions', label: 'Instructions (supports pasted images)', type: 'textarea', full: true, rows: 8, image: true },
        ],
    },
}

/** Format a DRF error payload into a human-readable toast string. */
export const formatApiError = (err, fallback = 'Something went wrong') => {
    const data = err?.response?.data
    if (data && typeof data === 'object') {
        return Object.entries(data)
            .map(([k, val]) => `${k}: ${Array.isArray(val) ? val.join(', ') : val}`)
            .join(' | ')
    }
    return data?.detail || fallback
}

export const buildInitial = (fields, instance) => {
    const out = {}
    fields.forEach((f) => {
        let v = instance ? instance[f.name] : undefined
        if (v === undefined || v === null) {
            v = f.default ?? (f.type === 'checkbox' ? false : f.type === 'stringlist' ? [] : '')
        }
        if (f.type === 'stringlist' && !Array.isArray(v)) v = v ? [String(v)] : []
        // datetime-local inputs need a trimmed "YYYY-MM-DDTHH:mm" value.
        if (f.type === 'datetime-local' && typeof v === 'string' && v.length > 16) v = v.slice(0, 16)
        out[f.name] = v
    })
    return out
}

/* ===========================================================================
 * Generic entity modal (course/subject/chapter/topic/content/quiz)
 * ========================================================================= */
export const EntityModal = ({ type, instance, defaults, onClose, onSubmit, saving }) => {
    const schema = SCHEMAS[type]
    const [values, setValues] = useState(() => ({
        ...buildInitial(schema.fields, instance),
        ...(!instance && defaults ? defaults : {}),
    }))
    const isEdit = !!instance

    const set = (name, val) => setValues((p) => ({ ...p, [name]: val }))

    const visibleFields = schema.fields.filter((f) => !f.showIf || f.showIf(values))

    const handleSubmit = (e) => {
        e.preventDefault()
        const payload = {}
        visibleFields.forEach((f) => {
            let v = values[f.name]
            if (f.type === 'certificate_preview') return
            if (f.type === 'file') {
                // Only send when a new file was chosen; otherwise preserve existing.
                if (v instanceof File) payload[f.name] = v
                return
            }
            if (f.type === 'number') {
                v = v === '' || v === null ? null : Number(v)
                if (v === null && !f.required) return
            }
            if (f.type === 'stringlist') {
                const arr = Array.isArray(v) ? v : String(v || '').split('\n')
                v = arr.map((s) => String(s).trim()).filter(Boolean)
            }
            payload[f.name] = v
        })
        onSubmit(payload)
    }

    return (
        <motion.div
            className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60"
            {...OVERLAY_MOTION}
            onMouseDown={(e) => e.target === e.currentTarget && onClose()}
        >
            <motion.div
                className="card w-full max-w-3xl max-h-[92vh] overflow-hidden flex flex-col"
                {...PANEL_MOTION}
            >
                <div className="flex items-center justify-between p-5 border-b border-surface-200 dark:border-surface-800">
                    <h3 className="text-lg font-bold text-surface-900 dark:text-white">
                        {isEdit ? 'Edit' : 'New'} {schema.title}
                    </h3>
                    <button onClick={onClose} className="btn-icon"><X className="w-5 h-5" /></button>
                </div>

                <form onSubmit={handleSubmit} className="p-5 overflow-y-auto space-y-4">
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                        {visibleFields.map((f) => (
                            <div key={f.name} className={f.full || f.type === 'textarea' || f.type === 'stringlist' || f.type === 'certificate_preview' ? 'sm:col-span-2' : ''}>
                                {f.type === 'certificate_preview' ? (
                                    <div>
                                        <label className="block text-xs font-semibold text-surface-500 mb-1.5">
                                            Certificate preview
                                        </label>
                                        <CertificatePreview
                                            template={values.certificate_template || 'classic'}
                                            data={{ courseName: values.name, accent: values.color }}
                                        />
                                        <p className="text-[11px] text-surface-400 mt-1.5">
                                            Sample preview — the student&apos;s name, your institute logo/name, date and a unique number are filled in automatically.
                                        </p>
                                    </div>
                                ) : f.type === 'checkbox' ? (
                                    <label className="flex items-center gap-2 cursor-pointer py-2">
                                        <input
                                            type="checkbox"
                                            checked={!!values[f.name]}
                                            onChange={(e) => set(f.name, e.target.checked)}
                                            className="w-4 h-4 rounded accent-primary-500"
                                        />
                                        <span className="text-sm font-medium text-surface-700 dark:text-surface-300">{f.label}</span>
                                    </label>
                                ) : (
                                    <>
                                        <label className="block text-xs font-semibold text-surface-500 mb-1.5">
                                            {f.label}{f.required && <span className="text-rose-500"> *</span>}
                                        </label>
                                        {f.type === 'textarea' ? (
                                            f.image ? (
                                                <NotesTextarea value={values[f.name] ?? ''} onChange={(val) => set(f.name, val)} rows={f.rows} />
                                            ) : (
                                                <textarea
                                                    className="input font-mono text-sm" rows={f.rows || 3}
                                                    value={values[f.name] ?? ''}
                                                    onChange={(e) => set(f.name, e.target.value)}
                                                />
                                            )
                                        ) : f.type === 'stringlist' ? (
                                            <textarea
                                                className="input text-sm" rows={f.rows || 4}
                                                placeholder={f.placeholder || 'One item per line'}
                                                value={(Array.isArray(values[f.name]) ? values[f.name] : []).join('\n')}
                                                onChange={(e) => set(f.name, e.target.value.split('\n'))}
                                            />
                                        ) : f.type === 'file' ? (
                                            <div className="space-y-2">
                                                {values[f.name] instanceof File ? (
                                                    <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-success-50 dark:bg-success-900/20 text-success-700 dark:text-success-300 text-xs font-medium">
                                                        <FileText className="w-4 h-4 flex-shrink-0" />
                                                        <span className="truncate">New file selected: {values[f.name].name}</span>
                                                    </div>
                                                ) : typeof values[f.name] === 'string' && values[f.name] ? (
                                                    <div className="flex items-center justify-between gap-2 px-3 py-2 rounded-lg bg-surface-100 dark:bg-surface-800 text-xs">
                                                        <span className="flex items-center gap-2 text-surface-600 dark:text-surface-300 font-medium truncate">
                                                            <FileText className="w-4 h-4 flex-shrink-0 text-primary-500" />
                                                            {f.noun || 'File'} already uploaded
                                                        </span>
                                                        <a href={values[f.name]} target="_blank" rel="noopener noreferrer" className="text-primary-600 hover:underline font-semibold flex-shrink-0">View</a>
                                                    </div>
                                                ) : (
                                                    <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-surface-100 dark:bg-surface-800 text-xs text-surface-400">
                                                        <FileText className="w-4 h-4 flex-shrink-0" />
                                                        No {f.noun || 'file'} uploaded yet
                                                    </div>
                                                )}
                                                <label className="inline-flex items-center gap-2 cursor-pointer">
                                                    <span className="btn-secondary text-sm">
                                                        {(values[f.name] instanceof File) || (typeof values[f.name] === 'string' && values[f.name]) ? `Replace ${f.noun || 'file'}` : `Choose ${f.noun || 'file'}`}
                                                    </span>
                                                    <input
                                                        type="file"
                                                        accept={f.accept}
                                                        onChange={(e) => set(f.name, e.target.files?.[0] || values[f.name])}
                                                        className="hidden"
                                                    />
                                                </label>
                                            </div>
                                        ) : f.type === 'select' ? (
                                            <select className="input" value={values[f.name] ?? ''} onChange={(e) => set(f.name, e.target.value)}>
                                                {f.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                                            </select>
                                        ) : f.type === 'color' ? (
                                            <div className="flex items-center gap-2">
                                                <input type="color" value={values[f.name] || '#3B82F6'} onChange={(e) => set(f.name, e.target.value)} className="h-11 w-14 rounded-lg border border-surface-200 dark:border-surface-700 bg-transparent cursor-pointer" />
                                                <input type="text" className="input" value={values[f.name] ?? ''} onChange={(e) => set(f.name, e.target.value)} />
                                            </div>
                                        ) : (
                                            <input
                                                type={f.type} step={f.step}
                                                className="input"
                                                value={values[f.name] ?? ''}
                                                onChange={(e) => set(f.name, e.target.value)}
                                                required={f.required}
                                            />
                                        )}
                                        {f.hint && <p className="text-[11px] text-surface-400 mt-1">{f.hint}</p>}
                                    </>
                                )}
                            </div>
                        ))}
                    </div>

                    <div className="flex justify-end gap-2 pt-2">
                        <button type="button" onClick={onClose} className="btn-secondary">Cancel</button>
                        <button type="submit" disabled={saving} className="btn-primary">
                            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                            {isEdit ? 'Save Changes' : 'Create'}
                        </button>
                    </div>
                </form>
            </motion.div>
        </motion.div>
    )
}

/* ===========================================================================
 * Confirm delete dialog
 * ========================================================================= */
export const ConfirmDialog = ({ label, onCancel, onConfirm, deleting }) => (
    <motion.div
        className="fixed inset-0 z-[60] flex items-center justify-center p-4 bg-black/60"
        {...OVERLAY_MOTION}
        onMouseDown={(e) => e.target === e.currentTarget && onCancel()}
    >
        <motion.div className="card w-full max-w-md p-6 text-center" {...PANEL_MOTION}>
            <div className="w-12 h-12 rounded-full bg-rose-100 dark:bg-rose-900/30 flex items-center justify-center mx-auto mb-4">
                <AlertTriangle className="w-6 h-6 text-rose-500" />
            </div>
            <h3 className="text-lg font-bold text-surface-900 dark:text-white">Delete {label}?</h3>
            <p className="text-sm text-surface-500 mt-1">This action cannot be undone. All nested content will be removed.</p>
            <div className="flex justify-center gap-2 mt-5">
                <button onClick={onCancel} className="btn-secondary">Cancel</button>
                <button onClick={onConfirm} disabled={deleting} className="btn bg-rose-500 text-white hover:bg-rose-600">
                    {deleting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4" />} Delete
                </button>
            </div>
        </motion.div>
    </motion.div>
)

/* ===========================================================================
 * Small row action buttons
 * ========================================================================= */
export const RowActions = ({ onEdit, onDelete, onAdd, addLabel }) => (
    <div className="flex items-center gap-1 shrink-0" onClick={(e) => e.stopPropagation()}>
        {onAdd && (
            <button onClick={onAdd} title={addLabel} className="p-1.5 rounded-lg text-surface-400 hover:text-primary-600 hover:bg-primary-50 dark:hover:bg-primary-900/20 transition-colors">
                <Plus className="w-4 h-4" />
            </button>
        )}
        {onEdit && (
            <button onClick={onEdit} title="Edit" className="p-1.5 rounded-lg text-surface-400 hover:text-primary-600 hover:bg-surface-100 dark:hover:bg-surface-800 transition-colors">
                <Pencil className="w-3.5 h-3.5" />
            </button>
        )}
        {onDelete && (
            <button onClick={onDelete} title="Delete" className="p-1.5 rounded-lg text-surface-400 hover:text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-900/20 transition-colors">
                <Trash2 className="w-3.5 h-3.5" />
            </button>
        )}
    </div>
)

/* ===========================================================================
 * Question editor modal (dynamic by question type)
 * ========================================================================= */
export const QuestionModal = ({ instance, onClose, onSubmit, saving }) => {
    const isEdit = !!instance
    const initType = instance?.question_type || 'mcq'

    const initOptions = () => {
        if (instance?.options?.length) {
            return [...instance.options]
                .sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
                .map((o) => ({ id: o.id, option_text: o.option_text, option_image: o.option_image || '' }))
        }
        return [{ option_text: '', option_image: '' }, { option_text: '', option_image: '' }]
    }
    const initCorrect = () => {
        const n = Number(instance?.correct_answer)
        return Number.isInteger(n) && n >= 0 ? n : 0
    }

    const [v, setV] = useState(() => ({
        question_text: instance?.question_text || '',
        question_type: initType,
        difficulty: instance?.difficulty || 'medium',
        status: instance?.status || 'published',
        marks: instance?.marks ?? 1,
        negative_marks: instance?.negative_marks ?? 0,
        explanation: instance?.explanation || '',
        numerical_answer: instance?.numerical_answer ?? '',
        numerical_tolerance: instance?.numerical_tolerance ?? 0.01,
        fill_answer: initType === 'fill_blank' ? (instance?.correct_answer || '') : '',
        question_image: instance?.question_image || '',
        explanation_image: instance?.explanation_image || '',
    }))
    const [options, setOptions] = useState(initOptions)
    const [correctIndex, setCorrectIndex] = useState(initCorrect)

    const set = (k, val) => setV((p) => ({ ...p, [k]: val }))
    const type = v.question_type

    const setOption = (i, text) => setOptions((p) => p.map((o, idx) => (idx === i ? { ...o, option_text: text } : o)))
    const setOptionImage = (i, img) => setOptions((p) => p.map((o, idx) => (idx === i ? { ...o, option_image: img } : o)))
    const addOption = () => setOptions((p) => [...p, { option_text: '', option_image: '' }])
    const removeOption = (i) => {
        setOptions((p) => p.filter((_, idx) => idx !== i))
        setCorrectIndex((c) => (c === i ? 0 : c > i ? c - 1 : c))
    }

    const handleSubmit = (e) => {
        e.preventDefault()
        if (!v.question_text.trim()) return toast.error('Question text is required')

        const base = {
            question_text: v.question_text.trim(),
            question_type: type,
            difficulty: v.difficulty,
            status: v.status,
            marks: Number(v.marks) || 0,
            negative_marks: Number(v.negative_marks) || 0,
            explanation: v.explanation,
        }

        const qImg = imagePayload(v.question_image, instance?.question_image || '')
        if (qImg.send) base.question_image = qImg.value
        const eImg = imagePayload(v.explanation_image, instance?.explanation_image || '')
        if (eImg.send) base.explanation_image = eImg.value

        // Serialize one option, preserving id and image (data URL = new, http URL
        // = keep, null = clear).
        const serializeOpt = (o, isCorrect) => {
            const opt = { option_text: o.option_text, is_correct: isCorrect }
            if (o.id) opt.id = o.id
            if (typeof o.option_image === 'string' && o.option_image) opt.option_image = o.option_image
            else if (o.id && !o.option_image) opt.option_image = null
            return opt
        }

        if (type === 'mcq') {
            const cleaned = options
                .map((o, i) => ({ ...o, option_text: o.option_text.trim(), is_correct: i === correctIndex }))
                .filter((o) => o.option_text !== '' || o.option_image)
            if (cleaned.length < 2) return toast.error('Add at least two options')
            let ci = cleaned.findIndex((o) => o.is_correct)
            if (ci < 0) ci = 0
            base.options = cleaned.map((o, i) => serializeOpt(o, i === ci))
            base.correct_answer = String(ci)
        } else if (type === 'true_false') {
            base.options = [
                { option_text: 'True', is_correct: correctIndex === 0 },
                { option_text: 'False', is_correct: correctIndex === 1 },
            ]
            base.correct_answer = String(correctIndex)
        } else if (type === 'numerical') {
            if (v.numerical_answer === '' || v.numerical_answer === null)
                return toast.error('Numerical answer is required')
            base.numerical_answer = Number(v.numerical_answer)
            base.numerical_tolerance = Number(v.numerical_tolerance) || 0
            base.correct_answer = String(v.numerical_answer)
            base.options = []
        } else if (type === 'fill_blank') {
            if (!v.fill_answer.trim()) return toast.error('Expected answer is required')
            base.correct_answer = v.fill_answer.trim()
            base.options = []
        }
        onSubmit(base)
    }

    const tfIndex = correctIndex === 1 ? 1 : 0

    return (
        <motion.div
            className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60"
            {...OVERLAY_MOTION}
            onMouseDown={(e) => e.target === e.currentTarget && onClose()}
        >
            <motion.div
                className="card w-full max-w-2xl max-h-[90vh] overflow-hidden flex flex-col"
                {...PANEL_MOTION}
            >
                <div className="flex items-center justify-between p-5 border-b border-surface-200 dark:border-surface-800">
                    <h3 className="text-lg font-bold text-surface-900 dark:text-white">{isEdit ? 'Edit' : 'New'} Question</h3>
                    <button onClick={onClose} className="btn-icon"><X className="w-5 h-5" /></button>
                </div>

                <form onSubmit={handleSubmit} className="p-5 overflow-y-auto space-y-4">
                    <div>
                        <label className="block text-xs font-semibold text-surface-500 mb-1.5">Question<span className="text-rose-500"> *</span></label>
                        <textarea className="input" rows={3} value={v.question_text} onChange={(e) => set('question_text', e.target.value)} />
                        <ImageDrop value={v.question_image} onChange={(val) => set('question_image', val)} label="question image" />
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                        <div>
                            <label className="block text-xs font-semibold text-surface-500 mb-1.5">Type</label>
                            <select className="input" value={type} onChange={(e) => { set('question_type', e.target.value); setCorrectIndex(0) }}>
                                {QUESTION_TYPES.map((t) => <option key={t} value={t}>{QTYPE_LABEL[t]}</option>)}
                            </select>
                        </div>
                        <div>
                            <label className="block text-xs font-semibold text-surface-500 mb-1.5">Difficulty</label>
                            <select className="input" value={v.difficulty} onChange={(e) => set('difficulty', e.target.value)}>
                                {DIFFICULTY.map((d) => <option key={d} value={d}>{d}</option>)}
                            </select>
                        </div>
                        <div>
                            <label className="block text-xs font-semibold text-surface-500 mb-1.5">Status</label>
                            <select className="input" value={v.status} onChange={(e) => set('status', e.target.value)}>
                                {QUESTION_STATUS.map((s) => <option key={s} value={s}>{s}</option>)}
                            </select>
                        </div>
                    </div>

                    {/* Type-specific answer editor */}
                    {type === 'mcq' && (
                        <div className="space-y-2">
                            <label className="block text-xs font-semibold text-surface-500">Options <span className="text-surface-400 font-normal">(select the correct one)</span></label>
                            {options.map((o, i) => (
                                <div key={i} className="flex items-start gap-2">
                                    <button type="button" onClick={() => setCorrectIndex(i)} title="Mark correct" className="shrink-0 mt-2.5">
                                        {correctIndex === i
                                            ? <CheckCircle2 className="w-5 h-5 text-emerald-500" />
                                            : <Circle className="w-5 h-5 text-surface-300 hover:text-surface-400" />}
                                    </button>
                                    <div className="flex-1">
                                        <input className="input" placeholder={`Option ${i + 1}`} value={o.option_text} onChange={(e) => setOption(i, e.target.value)} />
                                        <ImageDrop value={o.option_image} onChange={(val) => setOptionImage(i, val)} label="option image" compact />
                                    </div>
                                    {options.length > 2 && (
                                        <button type="button" onClick={() => removeOption(i)} className="btn-icon text-surface-400 hover:text-rose-500 mt-1.5"><X className="w-4 h-4" /></button>
                                    )}
                                </div>
                            ))}
                            <button type="button" onClick={addOption} className="text-xs font-semibold text-primary-600 hover:text-primary-700 inline-flex items-center gap-1"><Plus className="w-3.5 h-3.5" /> Add Option</button>
                        </div>
                    )}

                    {type === 'true_false' && (
                        <div>
                            <label className="block text-xs font-semibold text-surface-500 mb-1.5">Correct Answer</label>
                            <div className="flex gap-2">
                                {['True', 'False'].map((lbl, i) => (
                                    <button key={lbl} type="button" onClick={() => setCorrectIndex(i)}
                                        className={`flex-1 py-2.5 rounded-xl border text-sm font-semibold transition-all ${tfIndex === i ? 'bg-primary-500 text-white border-primary-500' : 'bg-white dark:bg-surface-900 text-surface-600 dark:text-surface-300 border-surface-200 dark:border-surface-700'}`}>
                                        {lbl}
                                    </button>
                                ))}
                            </div>
                        </div>
                    )}

                    {type === 'numerical' && (
                        <div className="grid grid-cols-2 gap-4">
                            <div>
                                <label className="block text-xs font-semibold text-surface-500 mb-1.5">Answer<span className="text-rose-500"> *</span></label>
                                <input type="number" step="any" className="input" value={v.numerical_answer} onChange={(e) => set('numerical_answer', e.target.value)} />
                            </div>
                            <div>
                                <label className="block text-xs font-semibold text-surface-500 mb-1.5">Tolerance (±)</label>
                                <input type="number" step="any" className="input" value={v.numerical_tolerance} onChange={(e) => set('numerical_tolerance', e.target.value)} />
                            </div>
                        </div>
                    )}

                    {type === 'fill_blank' && (
                        <div>
                            <label className="block text-xs font-semibold text-surface-500 mb-1.5">Expected Answer<span className="text-rose-500"> *</span></label>
                            <input className="input" value={v.fill_answer} onChange={(e) => set('fill_answer', e.target.value)} />
                            <p className="text-[11px] text-surface-400 mt-1">Matched case-insensitively, ignoring leading/trailing spaces.</p>
                        </div>
                    )}

                    <div className="grid grid-cols-2 gap-4">
                        <div>
                            <label className="block text-xs font-semibold text-surface-500 mb-1.5">Marks</label>
                            <input type="number" step="0.01" className="input" value={v.marks} onChange={(e) => set('marks', e.target.value)} />
                        </div>
                        <div>
                            <label className="block text-xs font-semibold text-surface-500 mb-1.5">Negative Marks</label>
                            <input type="number" step="0.01" className="input" value={v.negative_marks} onChange={(e) => set('negative_marks', e.target.value)} />
                        </div>
                    </div>

                    <div>
                        <label className="block text-xs font-semibold text-surface-500 mb-1.5">Explanation</label>
                        <textarea className="input" rows={2} value={v.explanation} onChange={(e) => set('explanation', e.target.value)} />
                        <ImageDrop value={v.explanation_image} onChange={(val) => set('explanation_image', val)} label="explanation image" />
                    </div>

                    <div className="flex justify-end gap-2 pt-2">
                        <button type="button" onClick={onClose} className="btn-secondary">Cancel</button>
                        <button type="submit" disabled={saving} className="btn-primary">
                            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                            {isEdit ? 'Save Changes' : 'Create'}
                        </button>
                    </div>
                </form>
            </motion.div>
        </motion.div>
    )
}
