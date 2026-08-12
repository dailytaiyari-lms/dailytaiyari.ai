import { useState, useMemo, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import toast from 'react-hot-toast'
import { analyticsService } from '../services/analyticsService'
import { tenantAdminService } from '../services/tenantAdminService'
import { courseService } from '../services/courseService'
import { useTenantStore } from '../context/tenantStore'
import { THEME_LIST, applyTheme, DEFAULT_THEME } from '../config/themes'
import { DEFAULT_AUTH_PANEL } from '../config/authPanel'
import CourseBuilder from '../components/admin/CourseBuilder'
import AICourseStudio from '../components/admin/AICourseStudio'
import LandingBuilder from '../components/admin/LandingBuilder'
import MarketingPromotions from '../components/admin/MarketingPromotions'
import Announcements from '../components/admin/Announcements'
import EmailSettings from '../components/admin/EmailSettings'
import AIFeatures from '../components/admin/AIFeatures'
import {
    Users,
    GraduationCap,
    Zap,
    BarChart3,
    TrendingUp,
    CheckCircle2,
    Search,
    Shield,
    ShieldOff,
    RotateCcw,
    UserCog,
    Award,
    X,
    MapPin,
    School,
    BookOpen,
    ExternalLink,
    Library,
    LayoutTemplate,
    ChevronDown,
    Book,
    Layers,
    Clock,
    XCircle,
    Check,
    Pencil,
    Save,
    Loader2,
    Download,
    SlidersHorizontal,
    RefreshCw,
    Mail,
    Phone,
    Filter,
    Upload,
    Image as ImageIcon,
    ToggleRight,
    Palette,
    SlidersHorizontal as SlidersIcon,
    Lock as LockIcon,
    CreditCard,
    KeyRound,
    Trash2,
    ShieldCheck,
    IndianRupee,
    Receipt,
    Undo2,
    Ban,
    Wallet,
    Calendar,
    ShoppingCart,
    Megaphone,
    UserPlus,
    Plus,
    ArrowUpRight,
    ArrowDownRight,
    Minus,
    Sparkles,
    Wand2,
} from 'lucide-react'

/* ---------------------------------------------------------------------------
 * Choice constants — kept in sync with backend users/models.py
 * ------------------------------------------------------------------------- */
const GRADE_OPTIONS = [
    { value: '', label: '—' },
    { value: '6', label: 'Class 6' },
    { value: '7', label: 'Class 7' },
    { value: '8', label: 'Class 8' },
    { value: '9', label: 'Class 9' },
    { value: '10', label: 'Class 10' },
    { value: '11', label: 'Class 11' },
    { value: '12', label: 'Class 12' },
    { value: 'graduate', label: 'Graduate' },
    { value: 'other', label: 'Other' },
]

const BOARD_OPTIONS = [
    { value: '', label: '—' },
    { value: 'cbse', label: 'CBSE' },
    { value: 'icse', label: 'ICSE' },
    { value: 'state', label: 'State Board' },
    { value: 'ib', label: 'IB' },
    { value: 'igcse', label: 'IGCSE' },
    { value: 'other', label: 'Other' },
]

const MEDIUM_OPTIONS = [
    { value: 'english', label: 'English' },
    { value: 'hindi', label: 'Hindi' },
    { value: 'bilingual', label: 'Bilingual' },
    { value: 'other', label: 'Other' },
]

const STUDY_TIME_OPTIONS = [
    { value: 'morning', label: 'Morning (6AM-12PM)' },
    { value: 'afternoon', label: 'Afternoon (12PM-6PM)' },
    { value: 'evening', label: 'Evening (6PM-10PM)' },
    { value: 'night', label: 'Night (10PM-6AM)' },
]

const ROLE_OPTIONS = [
    { value: 'student', label: 'Student' },
    { value: 'instructor', label: 'Faculty' },
    { value: 'admin', label: 'Admin' },
]

const roleBadgeClass = (role) =>
    role === 'admin'
        ? 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400'
        : role === 'instructor'
            ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400'
            : 'bg-surface-100 text-surface-600 dark:bg-surface-800 dark:text-surface-300'

/* ---------------------------------------------------------------------------
 * StatCard
 * ------------------------------------------------------------------------- */
const TrendBadge = ({ change }) => {
    // change === null → growth from a zero baseline (no meaningful %)
    if (change === null || change === undefined) {
        return (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-bold bg-surface-100 dark:bg-surface-800 text-surface-500">
                New
            </span>
        )
    }
    const isUp = change > 0
    const isDown = change < 0
    const Icon = isUp ? ArrowUpRight : isDown ? ArrowDownRight : Minus
    const tone = isUp
        ? 'bg-emerald-50 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400'
        : isDown
            ? 'bg-rose-50 dark:bg-rose-900/30 text-rose-600 dark:text-rose-400'
            : 'bg-surface-100 dark:bg-surface-800 text-surface-500'
    return (
        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-bold ${tone}`}>
            <Icon className="w-3 h-3" />{Math.abs(change)}%
        </span>
    )
}

const StatCard = ({ title, value, icon: Icon, color, description, change }) => (
    <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="card p-5 sm:p-6"
    >
        <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
                <p className="text-sm font-medium text-surface-500 mb-1 truncate">{title}</p>
                <h3 className="text-2xl sm:text-3xl font-bold text-surface-900 dark:text-white">{value}</h3>
                <div className="mt-2 flex items-center gap-2 flex-wrap">
                    {change !== undefined && <TrendBadge change={change} />}
                    {description && <p className="text-xs sm:text-sm text-surface-500">{description}</p>}
                </div>
            </div>
            <div className={`p-3 rounded-xl shrink-0 ${color}`}>
                <Icon className="w-6 h-6 text-white" />
            </div>
        </div>
    </motion.div>
)

/* ---------------------------------------------------------------------------
 * Reusable form field helpers (used by the edit modal)
 * ------------------------------------------------------------------------- */
const Field = ({ label, children, hint }) => (
    <div className="space-y-1.5">
        <label className="block text-[11px] font-bold uppercase tracking-wider text-surface-400">{label}</label>
        {children}
        {hint && <p className="text-[10px] text-surface-400">{hint}</p>}
    </div>
)

const TextInput = (props) => <input {...props} className={`input ${props.className || ''}`} />
const SelectInput = ({ options, ...props }) => (
    <select {...props} className={`input ${props.className || ''}`}>
        {options.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
        ))}
    </select>
)

/* ---------------------------------------------------------------------------
 * StudentEditModal — edit ANY metadata of a student
 * ------------------------------------------------------------------------- */
const StudentEditModal = ({ student, onClose }) => {
    const queryClient = useQueryClient()

    const [form, setForm] = useState(() => ({
        // user
        first_name: student.user.first_name || '',
        last_name: student.user.last_name || '',
        phone: student.user.phone || '',
        role: student.user.role || 'student',
        // profile — personal
        date_of_birth: student.date_of_birth || '',
        bio: student.bio || '',
        instagram_handle: student.instagram_handle || '',
        parent_phone: student.parent_phone || '',
        // profile — academic
        grade: student.grade || '',
        school: student.school || '',
        coaching: student.coaching || '',
        board: student.board || '',
        medium: student.medium || 'english',
        target_year: student.target_year || '',
        // profile — location & prefs
        city: student.city || '',
        state: student.state || '',
        daily_study_goal_minutes: student.daily_study_goal_minutes ?? 60,
        preferred_study_time: student.preferred_study_time || 'evening',
    }))

    const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }))

    const mutation = useMutation({
        mutationFn: (payload) => tenantAdminService.updateStudent(student.id, payload),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['tenantStudents'] })
            toast.success('Student record updated')
            onClose()
        },
        onError: (err) => {
            const data = err?.response?.data
            const msg = typeof data === 'string'
                ? data
                : data
                    ? Object.entries(data).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : v}`).join(' • ')
                    : 'Failed to update record'
            toast.error(msg)
        },
    })

    const handleSubmit = (e) => {
        e.preventDefault()
        const payload = {
            user: {
                first_name: form.first_name.trim(),
                last_name: form.last_name.trim(),
                phone: form.phone.trim(),
                role: form.role,
            },
            date_of_birth: form.date_of_birth || null,
            bio: form.bio,
            instagram_handle: form.instagram_handle.replace('@', ''),
            parent_phone: form.parent_phone,
            grade: form.grade,
            school: form.school,
            coaching: form.coaching,
            board: form.board,
            medium: form.medium,
            target_year: form.target_year === '' ? null : Number(form.target_year),
            city: form.city,
            state: form.state,
            daily_study_goal_minutes: Number(form.daily_study_goal_minutes) || 0,
            preferred_study_time: form.preferred_study_time,
        }
        mutation.mutate(payload)
    }

    return (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-3 sm:p-4 bg-surface-900/60 backdrop-blur-sm">
            <motion.form
                onSubmit={handleSubmit}
                initial={{ opacity: 0, scale: 0.95, y: 20 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                className="bg-white dark:bg-surface-800 rounded-3xl w-full max-w-4xl max-h-[92vh] overflow-hidden shadow-2xl border border-surface-100 dark:border-surface-700 flex flex-col"
            >
                {/* Header */}
                <div className="p-5 sm:p-6 border-b dark:border-surface-700 flex items-center justify-between bg-surface-50/50 dark:bg-surface-900/20">
                    <div className="flex items-center gap-3 min-w-0">
                        <div className="w-11 h-11 rounded-2xl bg-primary-100 dark:bg-primary-900/30 flex items-center justify-center text-primary-600 text-lg font-black shrink-0">
                            {student.user.full_name.charAt(0) || '?'}
                        </div>
                        <div className="min-w-0">
                            <h2 className="text-lg font-bold text-surface-900 dark:text-white truncate">Edit Student Record</h2>
                            <p className="text-xs text-surface-500 truncate">{student.user.email}</p>
                        </div>
                    </div>
                    <button type="button" onClick={onClose} className="p-2 hover:bg-surface-100 dark:hover:bg-surface-700 rounded-xl transition-colors shrink-0">
                        <X className="w-5 h-5 text-surface-500" />
                    </button>
                </div>

                {/* Body */}
                <div className="flex-1 overflow-y-auto p-5 sm:p-8 space-y-8">
                    {/* Personal */}
                    <section className="space-y-4">
                        <h3 className="text-xs font-black uppercase tracking-widest text-primary-600 dark:text-primary-400 flex items-center gap-2">
                            <Users className="w-4 h-4" /> Personal Information
                        </h3>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                            <Field label="First Name"><TextInput value={form.first_name} onChange={set('first_name')} placeholder="First name" /></Field>
                            <Field label="Last Name"><TextInput value={form.last_name} onChange={set('last_name')} placeholder="Last name" /></Field>
                            <Field label="Email (read-only)"><TextInput value={student.user.email} disabled className="opacity-60 cursor-not-allowed" /></Field>
                            <Field label="Phone"><TextInput value={form.phone} onChange={set('phone')} placeholder="Phone number" /></Field>
                            <Field label="Date of Birth"><TextInput type="date" value={form.date_of_birth || ''} onChange={set('date_of_birth')} /></Field>
                            <Field label="Parent Contact"><TextInput value={form.parent_phone} onChange={set('parent_phone')} placeholder="Parent phone" /></Field>
                            <Field label="Instagram Handle"><TextInput value={form.instagram_handle} onChange={set('instagram_handle')} placeholder="username" /></Field>
                            <Field label="Role" hint="Controls platform permissions">
                                <SelectInput options={ROLE_OPTIONS} value={form.role} onChange={set('role')} />
                            </Field>
                            <div className="sm:col-span-2">
                                <Field label="Bio">
                                    <textarea
                                        value={form.bio}
                                        onChange={set('bio')}
                                        rows={3}
                                        maxLength={500}
                                        placeholder="Short bio…"
                                        className="input resize-none"
                                    />
                                </Field>
                            </div>
                        </div>
                    </section>

                    {/* Academic */}
                    <section className="space-y-4">
                        <h3 className="text-xs font-black uppercase tracking-widest text-primary-600 dark:text-primary-400 flex items-center gap-2">
                            <School className="w-4 h-4" /> Academic Details
                        </h3>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                            <Field label="Target Year"><TextInput type="number" value={form.target_year} onChange={set('target_year')} placeholder="e.g. 2026" /></Field>
                            <Field label="Grade / Class"><SelectInput options={GRADE_OPTIONS} value={form.grade} onChange={set('grade')} /></Field>
                            <Field label="Board / University"><SelectInput options={BOARD_OPTIONS} value={form.board} onChange={set('board')} /></Field>
                            <Field label="School / Institute"><TextInput value={form.school} onChange={set('school')} placeholder="School name" /></Field>
                            <Field label="Coaching Center"><TextInput value={form.coaching} onChange={set('coaching')} placeholder="Coaching name" /></Field>
                            <Field label="Study Medium"><SelectInput options={MEDIUM_OPTIONS} value={form.medium} onChange={set('medium')} /></Field>
                        </div>
                    </section>

                    {/* Location & Preferences */}
                    <section className="space-y-4">
                        <h3 className="text-xs font-black uppercase tracking-widest text-primary-600 dark:text-primary-400 flex items-center gap-2">
                            <MapPin className="w-4 h-4" /> Location & Preferences
                        </h3>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                            <Field label="City"><TextInput value={form.city} onChange={set('city')} placeholder="City" /></Field>
                            <Field label="State"><TextInput value={form.state} onChange={set('state')} placeholder="State" /></Field>
                            <Field label="Daily Study Goal (minutes)"><TextInput type="number" min="0" value={form.daily_study_goal_minutes} onChange={set('daily_study_goal_minutes')} /></Field>
                            <Field label="Preferred Study Time"><SelectInput options={STUDY_TIME_OPTIONS} value={form.preferred_study_time} onChange={set('preferred_study_time')} /></Field>
                        </div>
                    </section>
                </div>

                {/* Footer */}
                <div className="p-4 sm:p-5 bg-surface-50 dark:bg-surface-900/20 border-t dark:border-surface-700 flex items-center justify-end gap-3">
                    <button type="button" onClick={onClose} className="px-5 py-2.5 rounded-xl font-bold text-sm text-surface-600 dark:text-surface-300 hover:bg-surface-100 dark:hover:bg-surface-700 transition-colors">
                        Cancel
                    </button>
                    <button
                        type="submit"
                        disabled={mutation.isPending}
                        className="px-6 py-2.5 bg-primary-600 text-white rounded-xl font-bold text-sm hover:bg-primary-700 transition-colors flex items-center gap-2 disabled:opacity-60"
                    >
                        {mutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                        Save Changes
                    </button>
                </div>
            </motion.form>
        </div>
    )
}

/* ---------------------------------------------------------------------------
 * StudentDetailModal — read-only full profile
 * ------------------------------------------------------------------------- */
const StudentDetailModal = ({ student, onClose, onEdit }) => {
    if (!student) return null

    const sections = [
        {
            title: 'Personal Information',
            icon: Users,
            fields: [
                { label: 'Full Name', value: student.user.full_name },
                { label: 'Email', value: student.user.email },
                { label: 'Phone', value: student.user.phone || 'Not provided' },
                { label: 'Date of Birth', value: student.date_of_birth || 'Not provided' },
                { label: 'Bio', value: student.bio || 'No bio available', fullWidth: true },
            ],
        },
        {
            title: 'Academic Details',
            icon: School,
            fields: [
                { label: 'Enrolled Courses', value: (student.enrolled_courses || []).map((c) => c.name).filter(Boolean).join(', ') || 'None' },
                { label: 'Target Year', value: student.target_year || 'Not set' },
                { label: 'Grade/Level', value: student.grade || 'Not provided' },
                { label: 'School/Institute', value: student.school || 'Not provided' },
                { label: 'Coaching Center', value: student.coaching || 'Not provided' },
                { label: 'Board/University', value: student.board || 'Not provided' },
                { label: 'Study Medium', value: student.medium || 'Not provided' },
            ],
        },
        {
            title: 'Location & Preferences',
            icon: MapPin,
            fields: [
                { label: 'City', value: student.city || 'Not provided' },
                { label: 'State', value: student.state || 'Not provided' },
                { label: 'Daily Study Goal', value: `${student.daily_study_goal_minutes} minutes` },
                { label: 'Preferred Study Time', value: student.preferred_study_time, className: 'capitalize' },
                { label: 'Instagram', value: student.instagram_handle ? `@${student.instagram_handle}` : 'Not provided' },
                { label: 'Parent Contact', value: student.parent_phone || 'Not provided' },
            ],
        },
        {
            title: 'Performance Statistics',
            icon: BarChart3,
            fields: [
                { label: 'Current Level', value: `Level ${student.current_level}`, className: 'font-bold text-primary-600' },
                { label: 'Total XP', value: student.total_xp.toLocaleString() },
                { label: 'Overall Accuracy', value: `${student.overall_accuracy}%` },
                { label: 'Questions Attempted', value: student.total_questions_attempted },
                { label: 'Correct Answers', value: student.total_correct_answers },
                { label: 'Total Study Time', value: `${student.total_study_time_minutes} minutes` },
            ],
        },
    ]

    return (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-3 sm:p-4 bg-surface-900/60 backdrop-blur-sm">
            <motion.div
                initial={{ opacity: 0, scale: 0.95, y: 20 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                className="bg-white dark:bg-surface-800 rounded-3xl w-full max-w-4xl max-h-[90vh] overflow-hidden shadow-2xl border border-surface-100 dark:border-surface-700 flex flex-col"
            >
                <div className="p-5 sm:p-6 border-b dark:border-surface-700 flex items-center justify-between bg-surface-50/50 dark:bg-surface-900/20">
                    <div className="flex items-center gap-3 min-w-0">
                        <div className="w-11 h-11 rounded-2xl bg-primary-100 dark:bg-primary-900/30 flex items-center justify-center text-primary-600 text-lg font-black shrink-0">
                            {student.user.full_name.charAt(0) || '?'}
                        </div>
                        <div className="min-w-0">
                            <h2 className="text-lg sm:text-xl font-bold text-surface-900 dark:text-white truncate">{student.user.full_name}</h2>
                            <p className="text-xs sm:text-sm text-surface-500 truncate">{student.user.email}</p>
                        </div>
                    </div>
                    <button onClick={onClose} className="p-2 hover:bg-surface-100 dark:hover:bg-surface-700 rounded-xl transition-colors shrink-0">
                        <X className="w-5 h-5 text-surface-500" />
                    </button>
                </div>

                <div className="flex-1 overflow-y-auto p-5 sm:p-8 space-y-8 sm:space-y-10">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-8 sm:gap-10">
                        {sections.map((section, idx) => (
                            <div key={idx} className="space-y-4">
                                <h3 className="text-xs font-black uppercase tracking-widest text-primary-600 dark:text-primary-400 flex items-center gap-2">
                                    <section.icon className="w-4 h-4" />
                                    {section.title}
                                </h3>
                                <div className="grid grid-cols-2 gap-4">
                                    {section.fields.map((field, fIdx) => (
                                        <div key={fIdx} className={`${field.fullWidth ? 'col-span-2' : ''} space-y-1`}>
                                            <p className="text-[10px] font-bold text-surface-400 uppercase tracking-wider">{field.label}</p>
                                            <p className={`text-sm text-surface-700 dark:text-surface-200 break-words ${field.className || ''}`}>{field.value}</p>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        ))}
                    </div>
                </div>

                <div className="p-4 sm:p-5 bg-surface-50 dark:bg-surface-900/20 border-t dark:border-surface-700 flex justify-end gap-3">
                    <button onClick={onClose} className="px-5 py-2.5 rounded-xl font-bold text-sm text-surface-600 dark:text-surface-300 hover:bg-surface-100 dark:hover:bg-surface-700 transition-colors">
                        Close
                    </button>
                    <button onClick={() => onEdit(student)} className="px-6 py-2.5 bg-primary-600 text-white rounded-xl font-bold text-sm hover:bg-primary-700 transition-colors flex items-center gap-2">
                        <Pencil className="w-4 h-4" /> Edit Record
                    </button>
                </div>
            </motion.div>
        </div>
    )
}

/* ---------------------------------------------------------------------------
 * CourseMultiSelect — checkbox list of tenant courses
 * ------------------------------------------------------------------------- */
const CourseMultiSelect = ({ courses, selected, onToggle, disabledIds = [], emptyLabel = 'No courses available yet.' }) => {
    if (!courses.length) {
        return <p className="text-xs text-surface-400 italic">{emptyLabel}</p>
    }
    return (
        <div className="max-h-52 overflow-y-auto rounded-xl border border-surface-200 dark:border-surface-700 divide-y divide-surface-100 dark:divide-surface-800">
            {courses.map((course) => {
                const id = String(course.id)
                const isDisabled = disabledIds.map(String).includes(id)
                return (
                    <label
                        key={id}
                        className={`flex items-center gap-3 px-3 py-2.5 text-sm ${isDisabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer hover:bg-surface-50 dark:hover:bg-surface-800/50'}`}
                    >
                        <input
                            type="checkbox"
                            className="w-4 h-4 rounded accent-primary-600"
                            checked={isDisabled || selected.includes(id)}
                            disabled={isDisabled}
                            onChange={() => onToggle(id)}
                        />
                        <span className="flex-1 truncate text-surface-700 dark:text-surface-200">{course.name}</span>
                        {isDisabled && <span className="text-[10px] font-bold uppercase text-surface-400">Enrolled</span>}
                    </label>
                )
            })}
        </div>
    )
}

/* ---------------------------------------------------------------------------
 * CredentialsNotice — shown when the welcome email could not be delivered
 * ------------------------------------------------------------------------- */
const CredentialsNotice = ({ email, password }) => (
    <div className="rounded-xl border border-amber-200 bg-amber-50 dark:bg-amber-900/20 dark:border-amber-800 p-4 space-y-2">
        <p className="text-xs font-bold uppercase tracking-wider text-amber-700 dark:text-amber-400 flex items-center gap-2">
            <KeyRound className="w-3.5 h-3.5" /> Email could not be sent
        </p>
        <p className="text-xs text-amber-700 dark:text-amber-300">
            Share these credentials with the student manually — this password is shown only once.
        </p>
        <div className="text-sm font-mono bg-white dark:bg-surface-900 rounded-lg p-3 space-y-1 break-all">
            <div><span className="text-surface-400">Email:</span> {email}</div>
            <div><span className="text-surface-400">Password:</span> {password}</div>
        </div>
        <button
            type="button"
            onClick={() => {
                navigator.clipboard?.writeText(`Email: ${email}\nPassword: ${password}`)
                toast.success('Credentials copied')
            }}
            className="text-xs font-bold text-amber-700 dark:text-amber-400 hover:underline"
        >
            Copy credentials
        </button>
    </div>
)

/* ---------------------------------------------------------------------------
 * CreateStudentModal — admin-provisioned account + course assignment
 * ------------------------------------------------------------------------- */
const CreateStudentModal = ({ courses, onClose }) => {
    const queryClient = useQueryClient()
    const [form, setForm] = useState({
        first_name: '', last_name: '', email: '', phone: '', role: 'student',
        grade: '', board: '', medium: 'english', school: '', coaching: '',
        city: '', state: '', parent_phone: '', target_year: '',
    })
    const [courseIds, setCourseIds] = useState([])
    const [sendEmail, setSendEmail] = useState(true)
    const [credentials, setCredentials] = useState(null)

    const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }))
    const toggleCourse = (id) =>
        setCourseIds((ids) => (ids.includes(id) ? ids.filter((c) => c !== id) : [...ids, id]))

    const mutation = useMutation({
        mutationFn: (payload) => tenantAdminService.createStudent(payload),
        onSuccess: (data) => {
            queryClient.invalidateQueries({ queryKey: ['tenantStudents'] })
            if (data?.temporary_password) {
                // Email failed — keep the modal open so the admin can copy the password.
                setCredentials({ email: form.email.trim(), password: data.temporary_password })
                toast.error('Account created, but the welcome email failed to send')
                return
            }
            toast.success(sendEmail ? 'Account created — credentials emailed' : 'Account created')
            onClose()
        },
        onError: (err) => {
            const data = err?.response?.data
            const msg = typeof data === 'string'
                ? data
                : data
                    ? Object.entries(data).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : v}`).join(' • ')
                    : 'Failed to create account'
            toast.error(msg)
        },
    })

    const handleSubmit = (e) => {
        e.preventDefault()
        if (!form.first_name.trim()) return toast.error('First name is required')
        if (!form.email.trim()) return toast.error('Email is required')
        mutation.mutate({
            email: form.email.trim(),
            first_name: form.first_name.trim(),
            last_name: form.last_name.trim(),
            phone: form.phone.trim(),
            role: form.role,
            course_ids: courseIds,
            send_email: sendEmail,
            grade: form.grade,
            board: form.board,
            medium: form.medium,
            school: form.school.trim(),
            coaching: form.coaching.trim(),
            city: form.city.trim(),
            state: form.state.trim(),
            parent_phone: form.parent_phone.trim(),
            target_year: form.target_year === '' ? null : Number(form.target_year),
        })
    }

    return (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-3 sm:p-4 bg-surface-900/60 backdrop-blur-sm">
            <motion.form
                onSubmit={handleSubmit}
                initial={{ opacity: 0, scale: 0.95, y: 20 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                className="bg-white dark:bg-surface-800 rounded-3xl w-full max-w-3xl max-h-[92vh] overflow-hidden shadow-2xl border border-surface-100 dark:border-surface-700 flex flex-col"
            >
                <div className="p-5 sm:p-6 border-b dark:border-surface-700 flex items-center justify-between bg-surface-50/50 dark:bg-surface-900/20">
                    <div className="flex items-center gap-3 min-w-0">
                        <div className="w-11 h-11 rounded-2xl bg-primary-100 dark:bg-primary-900/30 flex items-center justify-center text-primary-600 shrink-0">
                            <UserPlus className="w-5 h-5" />
                        </div>
                        <div className="min-w-0">
                            <h2 className="text-lg font-bold text-surface-900 dark:text-white truncate">Add Student</h2>
                            <p className="text-xs text-surface-500 truncate">A password is generated automatically and emailed to them</p>
                        </div>
                    </div>
                    <button type="button" onClick={onClose} className="p-2 hover:bg-surface-100 dark:hover:bg-surface-700 rounded-xl transition-colors shrink-0">
                        <X className="w-5 h-5 text-surface-500" />
                    </button>
                </div>

                <div className="flex-1 overflow-y-auto p-5 sm:p-8 space-y-8">
                    {credentials && <CredentialsNotice email={credentials.email} password={credentials.password} />}

                    <section className="space-y-4">
                        <h3 className="text-xs font-black uppercase tracking-widest text-primary-600 dark:text-primary-400 flex items-center gap-2">
                            <Users className="w-4 h-4" /> Account Details
                        </h3>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                            <Field label="First Name *"><TextInput value={form.first_name} onChange={set('first_name')} placeholder="First name" required /></Field>
                            <Field label="Last Name"><TextInput value={form.last_name} onChange={set('last_name')} placeholder="Last name" /></Field>
                            <Field label="Email *" hint="Sign-in ID — credentials are sent here">
                                <TextInput type="email" value={form.email} onChange={set('email')} placeholder="student@example.com" required />
                            </Field>
                            <Field label="Phone"><TextInput value={form.phone} onChange={set('phone')} placeholder="Phone number" /></Field>
                            <Field label="Role" hint="Controls platform permissions">
                                <SelectInput
                                    options={[{ value: 'student', label: 'Student' }, { value: 'instructor', label: 'Faculty' }]}
                                    value={form.role}
                                    onChange={set('role')}
                                />
                            </Field>
                            <Field label="Parent Contact"><TextInput value={form.parent_phone} onChange={set('parent_phone')} placeholder="Parent phone" /></Field>
                        </div>
                    </section>

                    <section className="space-y-4">
                        <h3 className="text-xs font-black uppercase tracking-widest text-primary-600 dark:text-primary-400 flex items-center gap-2">
                            <BookOpen className="w-4 h-4" /> Course Enrollment
                        </h3>
                        <p className="text-xs text-surface-500">
                            Selected courses are approved immediately and listed in the welcome email.
                        </p>
                        <CourseMultiSelect courses={courses} selected={courseIds} onToggle={toggleCourse} />
                    </section>

                    <section className="space-y-4">
                        <h3 className="text-xs font-black uppercase tracking-widest text-primary-600 dark:text-primary-400 flex items-center gap-2">
                            <School className="w-4 h-4" /> Academic Details <span className="text-surface-400 font-bold">(optional)</span>
                        </h3>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                            <Field label="Grade / Class"><SelectInput options={GRADE_OPTIONS} value={form.grade} onChange={set('grade')} /></Field>
                            <Field label="Board / University"><SelectInput options={BOARD_OPTIONS} value={form.board} onChange={set('board')} /></Field>
                            <Field label="Target Year"><TextInput type="number" value={form.target_year} onChange={set('target_year')} placeholder="e.g. 2026" /></Field>
                            <Field label="Study Medium"><SelectInput options={MEDIUM_OPTIONS} value={form.medium} onChange={set('medium')} /></Field>
                            <Field label="School / Institute"><TextInput value={form.school} onChange={set('school')} placeholder="School name" /></Field>
                            <Field label="Coaching Center"><TextInput value={form.coaching} onChange={set('coaching')} placeholder="Coaching name" /></Field>
                            <Field label="City"><TextInput value={form.city} onChange={set('city')} placeholder="City" /></Field>
                            <Field label="State"><TextInput value={form.state} onChange={set('state')} placeholder="State" /></Field>
                        </div>
                    </section>

                    <label className="flex items-start gap-3 text-sm cursor-pointer">
                        <input
                            type="checkbox"
                            checked={sendEmail}
                            onChange={(e) => setSendEmail(e.target.checked)}
                            className="w-4 h-4 mt-0.5 rounded accent-primary-600"
                        />
                        <span className="text-surface-600 dark:text-surface-300">
                            Email the welcome message with sign-in credentials
                            <span className="block text-xs text-surface-400">
                                If unchecked, the generated password is shown to you once so you can share it yourself.
                            </span>
                        </span>
                    </label>
                </div>

                <div className="p-4 sm:p-5 bg-surface-50 dark:bg-surface-900/20 border-t dark:border-surface-700 flex items-center justify-end gap-3">
                    <button type="button" onClick={onClose} className="px-5 py-2.5 rounded-xl font-bold text-sm text-surface-600 dark:text-surface-300 hover:bg-surface-100 dark:hover:bg-surface-700 transition-colors">
                        {credentials ? 'Done' : 'Cancel'}
                    </button>
                    {!credentials && (
                        <button
                            type="submit"
                            disabled={mutation.isPending}
                            className="px-6 py-2.5 bg-primary-600 text-white rounded-xl font-bold text-sm hover:bg-primary-700 transition-colors flex items-center gap-2 disabled:opacity-60"
                        >
                            {mutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <UserPlus className="w-4 h-4" />}
                            Create Account
                        </button>
                    )}
                </div>
            </motion.form>
        </div>
    )
}

/* ---------------------------------------------------------------------------
 * AssignCoursesModal — enrol an existing student in more courses
 * ------------------------------------------------------------------------- */
const AssignCoursesModal = ({ student, courses, onClose }) => {
    const queryClient = useQueryClient()
    const [courseIds, setCourseIds] = useState([])
    const [sendEmail, setSendEmail] = useState(true)

    const enrolled = student.enrolled_courses || []
    const enrolledIds = enrolled.map((c) => String(c.id))

    const toggleCourse = (id) =>
        setCourseIds((ids) => (ids.includes(id) ? ids.filter((c) => c !== id) : [...ids, id]))

    const assignMutation = useMutation({
        mutationFn: () => tenantAdminService.assignCourses(student.id, courseIds, sendEmail),
        onSuccess: (data) => {
            queryClient.invalidateQueries({ queryKey: ['tenantStudents'] })
            const count = data?.assigned?.length || 0
            toast.success(count
                ? `Enrolled in ${count} course${count === 1 ? '' : 's'}${sendEmail ? ' — student notified' : ''}`
                : 'Student was already enrolled in the selected courses')
            onClose()
        },
        onError: (err) => toast.error(err?.response?.data?.detail || 'Failed to assign courses'),
    })

    const removeMutation = useMutation({
        mutationFn: (courseId) => tenantAdminService.removeCourse(student.id, courseId),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['tenantStudents'] })
            toast.success('Enrollment removed')
            onClose()
        },
        onError: () => toast.error('Failed to remove enrollment'),
    })

    return (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-3 sm:p-4 bg-surface-900/60 backdrop-blur-sm">
            <motion.div
                initial={{ opacity: 0, scale: 0.95, y: 20 }}
                animate={{ opacity: 1, scale: 1, y: 0 }}
                className="bg-white dark:bg-surface-800 rounded-3xl w-full max-w-xl max-h-[92vh] overflow-hidden shadow-2xl border border-surface-100 dark:border-surface-700 flex flex-col"
            >
                <div className="p-5 sm:p-6 border-b dark:border-surface-700 flex items-center justify-between bg-surface-50/50 dark:bg-surface-900/20">
                    <div className="min-w-0">
                        <h2 className="text-lg font-bold text-surface-900 dark:text-white truncate">Manage Courses</h2>
                        <p className="text-xs text-surface-500 truncate">{student.user.full_name} · {student.user.email}</p>
                    </div>
                    <button onClick={onClose} className="p-2 hover:bg-surface-100 dark:hover:bg-surface-700 rounded-xl transition-colors shrink-0">
                        <X className="w-5 h-5 text-surface-500" />
                    </button>
                </div>

                <div className="flex-1 overflow-y-auto p-5 sm:p-6 space-y-6">
                    <section className="space-y-3">
                        <h3 className="text-xs font-black uppercase tracking-widest text-surface-400">Currently Enrolled</h3>
                        {enrolled.length === 0 ? (
                            <p className="text-xs text-surface-400 italic">Not enrolled in any course yet.</p>
                        ) : (
                            <div className="flex flex-wrap gap-2">
                                {enrolled.map((c) => (
                                    <span key={c.id} className="inline-flex items-center gap-2 px-2.5 py-1 rounded-lg bg-surface-100 dark:bg-surface-800 text-xs">
                                        {c.name}
                                        <span className="text-[10px] uppercase font-bold text-surface-400">{c.status}</span>
                                        <button
                                            onClick={() => {
                                                if (window.confirm(`Remove ${student.user.full_name} from ${c.name}?`)) {
                                                    removeMutation.mutate(c.id)
                                                }
                                            }}
                                            className="text-surface-400 hover:text-rose-500"
                                            title="Remove enrollment"
                                        >
                                            <X className="w-3.5 h-3.5" />
                                        </button>
                                    </span>
                                ))}
                            </div>
                        )}
                    </section>

                    <section className="space-y-3">
                        <h3 className="text-xs font-black uppercase tracking-widest text-primary-600 dark:text-primary-400">Assign New Courses</h3>
                        <CourseMultiSelect
                            courses={courses}
                            selected={courseIds}
                            onToggle={toggleCourse}
                            disabledIds={enrolledIds}
                        />
                    </section>

                    <label className="flex items-start gap-3 text-sm cursor-pointer">
                        <input
                            type="checkbox"
                            checked={sendEmail}
                            onChange={(e) => setSendEmail(e.target.checked)}
                            className="w-4 h-4 mt-0.5 rounded accent-primary-600"
                        />
                        <span className="text-surface-600 dark:text-surface-300">Email the student about the new course(s)</span>
                    </label>
                </div>

                <div className="p-4 sm:p-5 bg-surface-50 dark:bg-surface-900/20 border-t dark:border-surface-700 flex items-center justify-end gap-3">
                    <button onClick={onClose} className="px-5 py-2.5 rounded-xl font-bold text-sm text-surface-600 dark:text-surface-300 hover:bg-surface-100 dark:hover:bg-surface-700 transition-colors">
                        Cancel
                    </button>
                    <button
                        onClick={() => assignMutation.mutate()}
                        disabled={assignMutation.isPending || courseIds.length === 0}
                        className="px-6 py-2.5 bg-primary-600 text-white rounded-xl font-bold text-sm hover:bg-primary-700 transition-colors flex items-center gap-2 disabled:opacity-60"
                    >
                        {assignMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <BookOpen className="w-4 h-4" />}
                        Enroll
                    </button>
                </div>
            </motion.div>
        </div>
    )
}

/* ---------------------------------------------------------------------------
 * Row action buttons shared between desktop table & mobile cards
 * ------------------------------------------------------------------------- */
const RowActions = ({ student, onView, onEdit, onReset, onCourses, onResetPassword }) => (
    <div className="flex items-center gap-1">
        <button onClick={() => onCourses(student)} className="p-2 text-surface-400 hover:text-primary-500 hover:bg-primary-50 dark:hover:bg-primary-900/20 rounded-lg transition-all" title="Manage courses">
            <BookOpen className="w-4 h-4" />
        </button>
        <button onClick={() => onEdit(student)} className="p-2 text-surface-400 hover:text-primary-500 hover:bg-primary-50 dark:hover:bg-primary-900/20 rounded-lg transition-all" title="Edit record">
            <Pencil className="w-4 h-4" />
        </button>
        <button onClick={() => onResetPassword(student)} className="p-2 text-surface-400 hover:text-primary-500 hover:bg-primary-50 dark:hover:bg-primary-900/20 rounded-lg transition-all" title="Email a new password">
            <KeyRound className="w-4 h-4" />
        </button>
        <button onClick={() => onView(student)} className="p-2 text-surface-400 hover:text-primary-500 hover:bg-primary-50 dark:hover:bg-primary-900/20 rounded-lg transition-all" title="View full profile">
            <ExternalLink className="w-4 h-4" />
        </button>
        <button onClick={() => onReset(student)} className="p-2 text-surface-400 hover:text-rose-500 hover:bg-rose-50 dark:hover:bg-rose-900/20 rounded-lg transition-all" title="Reset progress">
            <RotateCcw className="w-4 h-4" />
        </button>
    </div>
)

/* ---------------------------------------------------------------------------
 * StudentManagement — search, filters, export, edit
 * ------------------------------------------------------------------------- */
const StudentManagement = () => {
    const queryClient = useQueryClient()
    const [searchTerm, setSearchTerm] = useState('')
    const [filterRole, setFilterRole] = useState('all')
    const [filterStatus, setFilterStatus] = useState('all')
    const [filterExam, setFilterExam] = useState('all')
    const [sortBy, setSortBy] = useState('name')
    const [selectedStudent, setSelectedStudent] = useState(null)
    const [editingStudent, setEditingStudent] = useState(null)
    const [coursesStudent, setCoursesStudent] = useState(null)
    const [showCreate, setShowCreate] = useState(false)

    const { data: students, isLoading } = useQuery({
        queryKey: ['tenantStudents'],
        queryFn: () => tenantAdminService.getStudents(),
    })

    const { data: examsData } = useQuery({
        queryKey: ['adminExamOptions'],
        queryFn: () => courseService.getAvailableCoursesForEnrollment(),
    })
    const exams = Array.isArray(examsData) ? examsData : (examsData?.results || examsData?.courses || [])

    const resetMutation = useMutation({
        mutationFn: (id) => tenantAdminService.resetStudentProgress(id),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['tenantStudents'] })
            toast.success('Student progress reset')
        },
        onError: () => toast.error('Failed to reset progress'),
    })

    const statusMutation = useMutation({
        mutationFn: (id) => tenantAdminService.toggleStudentStatus(id),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['tenantStudents'] })
            toast.success('Account status updated')
        },
        onError: (err) => toast.error(err?.response?.data?.error || 'Failed to update status'),
    })

    const passwordMutation = useMutation({
        mutationFn: (id) => tenantAdminService.resetStudentPassword(id),
        onSuccess: (data) => {
            if (data?.temporary_password) {
                window.prompt('Email delivery failed — copy this temporary password:', data.temporary_password)
                toast.error('Password reset, but the email could not be sent')
                return
            }
            toast.success('New password emailed to the user')
        },
        onError: (err) => toast.error(err?.response?.data?.detail || 'Failed to reset password'),
    })

    const handleResetPassword = (student) => {
        if (window.confirm(`Generate a new password for ${student.user.full_name} and email it to them?`)) {
            passwordMutation.mutate(student.id)
        }
    }

    const studentList = Array.isArray(students) ? students : (students?.results || [])

    const filteredStudents = useMemo(() => {
        const term = searchTerm.trim().toLowerCase()
        const result = studentList.filter((s) => {
            const matchesSearch =
                !term ||
                s.user.full_name.toLowerCase().includes(term) ||
                s.user.email.toLowerCase().includes(term) ||
                (s.user.phone || '').toLowerCase().includes(term)
            const matchesRole = filterRole === 'all' || s.user.role === filterRole
            const matchesStatus =
                filterStatus === 'all' ||
                (filterStatus === 'active' && !s.user.is_suspended) ||
                (filterStatus === 'suspended' && s.user.is_suspended)
            const matchesExam = filterExam === 'all' || (s.enrolled_course_ids || []).some((cid) => String(cid) === String(filterExam))
            return matchesSearch && matchesRole && matchesStatus && matchesExam
        })

        const sorted = [...result].sort((a, b) => {
            switch (sortBy) {
                case 'xp':
                    return (b.total_xp || 0) - (a.total_xp || 0)
                case 'accuracy':
                    return (b.overall_accuracy || 0) - (a.overall_accuracy || 0)
                case 'level':
                    return (b.current_level || 0) - (a.current_level || 0)
                case 'email':
                    return a.user.email.localeCompare(b.user.email)
                default:
                    return a.user.full_name.localeCompare(b.user.full_name)
            }
        })
        return sorted
    }, [studentList, searchTerm, filterRole, filterStatus, filterExam, sortBy])

    const handleReset = (student) => {
        if (window.confirm(`Reset ALL progress for ${student.user.full_name}? This cannot be undone.`)) {
            resetMutation.mutate(student.id)
        }
    }

    const exportCsv = () => {
        if (filteredStudents.length === 0) {
            toast.error('No records to export')
            return
        }
        const headers = [
            'Full Name', 'Email', 'Phone', 'Role', 'Status', 'Enrolled Courses', 'Target Year',
            'Grade', 'School', 'Coaching', 'Board', 'Medium', 'City', 'State',
            'Level', 'Total XP', 'Accuracy %', 'Questions Attempted', 'Correct Answers', 'Study Minutes',
        ]
        const escape = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`
        const rows = filteredStudents.map((s) => [
            s.user.full_name, s.user.email, s.user.phone, s.user.role,
            s.user.is_suspended ? 'Suspended' : 'Active',
            (s.enrolled_courses || []).map((c) => c.name).filter(Boolean).join('; '),
            s.target_year, s.grade, s.school, s.coaching, s.board, s.medium,
            s.city, s.state, s.current_level, s.total_xp, s.overall_accuracy,
            s.total_questions_attempted, s.total_correct_answers, s.total_study_time_minutes,
        ].map(escape).join(','))
        const csv = [headers.map(escape).join(','), ...rows].join('\n')
        const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
        const url = URL.createObjectURL(blob)
        const link = document.createElement('a')
        link.href = url
        link.download = `student-records-${new Date().toISOString().slice(0, 10)}.csv`
        link.click()
        URL.revokeObjectURL(url)
        toast.success(`Exported ${filteredStudents.length} records`)
    }

    const resetFilters = () => {
        setSearchTerm(''); setFilterRole('all'); setFilterStatus('all'); setFilterExam('all'); setSortBy('name')
    }

    const hasActiveFilters = searchTerm || filterRole !== 'all' || filterStatus !== 'all' || filterExam !== 'all' || sortBy !== 'name'

    if (isLoading) return <div className="py-12 text-center text-surface-500">Loading students…</div>

    return (
        <div className="space-y-5">
            {/* Toolbar */}
            <div className="card p-4 sm:p-5 space-y-4">
                <div className="flex flex-col lg:flex-row gap-3 lg:items-center">
                    <div className="relative flex-1">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-surface-400" />
                        <input
                            type="text"
                            placeholder="Search by name, email or phone…"
                            className="input pl-10 w-full"
                            value={searchTerm}
                            onChange={(e) => setSearchTerm(e.target.value)}
                        />
                        {searchTerm && (
                            <button onClick={() => setSearchTerm('')} className="absolute right-3 top-1/2 -translate-y-1/2 text-surface-400 hover:text-surface-600">
                                <X className="w-4 h-4" />
                            </button>
                        )}
                    </div>
                    <button onClick={() => setShowCreate(true)} className="btn-primary justify-center whitespace-nowrap">
                        <UserPlus className="w-4 h-4" /> Add Student
                    </button>
                    <button onClick={exportCsv} className="btn-secondary justify-center whitespace-nowrap">
                        <Download className="w-4 h-4" /> Export CSV
                    </button>
                </div>

                <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                    <div className="space-y-1">
                        <label className="text-[10px] font-bold uppercase tracking-wider text-surface-400 flex items-center gap-1"><UserCog className="w-3 h-3" /> Role</label>
                        <select className="input py-2.5" value={filterRole} onChange={(e) => setFilterRole(e.target.value)}>
                            <option value="all">All Roles</option>
                            <option value="student">Student</option>
                            <option value="instructor">Faculty</option>
                            <option value="admin">Admin</option>
                        </select>
                    </div>
                    <div className="space-y-1">
                        <label className="text-[10px] font-bold uppercase tracking-wider text-surface-400 flex items-center gap-1"><Shield className="w-3 h-3" /> Status</label>
                        <select className="input py-2.5" value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}>
                            <option value="all">All Status</option>
                            <option value="active">Active</option>
                            <option value="suspended">Suspended</option>
                        </select>
                    </div>
                    <div className="space-y-1">
                        <label className="text-[10px] font-bold uppercase tracking-wider text-surface-400 flex items-center gap-1"><BookOpen className="w-3 h-3" /> Course</label>
                        <select className="input py-2.5" value={filterExam} onChange={(e) => setFilterExam(e.target.value)}>
                            <option value="all">All Courses</option>
                            {exams.map((ex) => <option key={ex.id} value={ex.id}>{ex.name}</option>)}
                        </select>
                    </div>
                    <div className="space-y-1">
                        <label className="text-[10px] font-bold uppercase tracking-wider text-surface-400 flex items-center gap-1"><SlidersHorizontal className="w-3 h-3" /> Sort By</label>
                        <select className="input py-2.5" value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
                            <option value="name">Name (A-Z)</option>
                            <option value="email">Email (A-Z)</option>
                            <option value="xp">XP (High-Low)</option>
                            <option value="accuracy">Accuracy (High-Low)</option>
                            <option value="level">Level (High-Low)</option>
                        </select>
                    </div>
                </div>

                <div className="flex items-center justify-between text-xs text-surface-500">
                    <span className="flex items-center gap-1.5">
                        <Filter className="w-3.5 h-3.5" />
                        Showing <span className="font-bold text-surface-700 dark:text-surface-200">{filteredStudents.length}</span> of {studentList.length} students
                    </span>
                    {hasActiveFilters && (
                        <button onClick={resetFilters} className="font-semibold text-primary-600 hover:underline">Clear filters</button>
                    )}
                </div>
            </div>

            {/* Desktop table */}
            <div className="card overflow-hidden hidden md:block">
                <div className="overflow-x-auto">
                    <table className="w-full text-left">
                        <thead className="bg-surface-50 dark:bg-surface-800/50 text-xs font-semibold text-surface-500 uppercase">
                            <tr>
                                <th className="px-6 py-4">Student</th>
                                <th className="px-6 py-4">Course</th>
                                <th className="px-6 py-4">Status</th>
                                <th className="px-6 py-4">Performance</th>
                                <th className="px-6 py-4 text-right">Actions</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-surface-100 dark:divide-surface-800">
                            {filteredStudents.map((student) => (
                                <tr key={student.id} className="hover:bg-surface-50/50 dark:hover:bg-surface-800/30 transition-colors">
                                    <td className="px-6 py-4">
                                        <div className="flex items-center gap-3">
                                            <div className="w-10 h-10 rounded-full bg-primary-100 dark:bg-primary-900/30 flex items-center justify-center text-primary-600 font-bold shrink-0">
                                                {student.user.full_name.charAt(0) || '?'}
                                            </div>
                                            <div className="min-w-0">
                                                <div className="font-medium text-surface-900 dark:text-white truncate">{student.user.full_name}</div>
                                                <div className="text-xs text-surface-500 truncate">{student.user.email}</div>
                                                <span className={`inline-block mt-1 px-2 py-0.5 rounded-full text-[10px] uppercase font-bold ${roleBadgeClass(student.user.role)}`}>
                                                    {student.user.role}
                                                </span>
                                            </div>
                                        </div>
                                    </td>
                                    <td className="px-6 py-4 text-sm text-surface-600 dark:text-surface-300">
                                        {(() => {
                                            const enrolled = student.enrolled_courses || []
                                            const names = [...new Set(enrolled.map((c) => c.name).filter(Boolean))]
                                            if (!names.length) return <span className="text-surface-400">—</span>
                                            return (
                                                <div className="flex flex-wrap gap-1">
                                                    {names.map((name) => (
                                                        <span key={name} className="inline-block px-2 py-0.5 rounded-md bg-surface-100 dark:bg-surface-800 text-xs">
                                                            {name}
                                                        </span>
                                                    ))}
                                                </div>
                                            )
                                        })()}
                                    </td>
                                    <td className="px-6 py-4">
                                        <button
                                            onClick={() => statusMutation.mutate(student.id)}
                                            className={`flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-lg border transition-all ${!student.user.is_suspended
                                                ? 'bg-emerald-50 border-emerald-100 text-emerald-700 dark:bg-emerald-900/20 dark:border-emerald-800 dark:text-emerald-400'
                                                : 'bg-rose-50 border-rose-100 text-rose-700 dark:bg-rose-900/20 dark:border-rose-800 dark:text-rose-400 hover:bg-rose-100'}`}
                                        >
                                            {!student.user.is_suspended ? <><Shield className="w-3.5 h-3.5" /> Active</> : <><ShieldOff className="w-3.5 h-3.5" /> Suspended</>}
                                        </button>
                                    </td>
                                    <td className="px-6 py-4 text-xs space-y-1 whitespace-nowrap">
                                        <div className="flex justify-between gap-4"><span className="text-surface-500">Lvl</span><span className="font-semibold text-surface-900 dark:text-white">{student.current_level}</span></div>
                                        <div className="flex justify-between gap-4"><span className="text-surface-500">XP</span><span className="font-semibold text-surface-900 dark:text-white">{student.total_xp}</span></div>
                                        <div className="flex justify-between gap-4"><span className="text-surface-500">Acc</span><span className="font-semibold text-surface-900 dark:text-white">{student.overall_accuracy}%</span></div>
                                    </td>
                                    <td className="px-6 py-4">
                                        <div className="flex justify-end">
                                            <RowActions student={student} onView={setSelectedStudent} onEdit={setEditingStudent} onReset={handleReset} onCourses={setCoursesStudent} onResetPassword={handleResetPassword} />
                                        </div>
                                    </td>
                                </tr>
                            ))}
                            {filteredStudents.length === 0 && (
                                <tr>
                                    <td colSpan="5" className="px-6 py-12 text-center text-surface-500 italic">No students match your filters.</td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                </div>
            </div>

            {/* Mobile cards */}
            <div className="md:hidden space-y-3">
                {filteredStudents.map((student) => (
                    <div key={student.id} className="card p-4 space-y-3">
                        <div className="flex items-start gap-3">
                            <div className="w-11 h-11 rounded-full bg-primary-100 dark:bg-primary-900/30 flex items-center justify-center text-primary-600 font-bold shrink-0">
                                {student.user.full_name.charAt(0) || '?'}
                            </div>
                            <div className="min-w-0 flex-1">
                                <div className="font-semibold text-surface-900 dark:text-white truncate">{student.user.full_name}</div>
                                <div className="text-xs text-surface-500 flex items-center gap-1 truncate"><Mail className="w-3 h-3 shrink-0" /> {student.user.email}</div>
                                {student.user.phone && <div className="text-xs text-surface-500 flex items-center gap-1"><Phone className="w-3 h-3" /> {student.user.phone}</div>}
                            </div>
                            <span className={`px-2 py-0.5 rounded-full text-[10px] uppercase font-bold shrink-0 ${roleBadgeClass(student.user.role)}`}>{student.user.role}</span>
                        </div>
                        <div className="grid grid-cols-3 gap-2 text-center text-xs bg-surface-50 dark:bg-surface-800/50 rounded-xl p-2.5">
                            <div><div className="font-bold text-surface-900 dark:text-white">{student.current_level}</div><div className="text-surface-400">Level</div></div>
                            <div><div className="font-bold text-surface-900 dark:text-white">{student.total_xp}</div><div className="text-surface-400">XP</div></div>
                            <div><div className="font-bold text-surface-900 dark:text-white">{student.overall_accuracy}%</div><div className="text-surface-400">Accuracy</div></div>
                        </div>
                        <div className="flex items-center justify-between">
                            <button
                                onClick={() => statusMutation.mutate(student.id)}
                                className={`flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-lg border ${!student.user.is_suspended
                                    ? 'bg-emerald-50 border-emerald-100 text-emerald-700 dark:bg-emerald-900/20 dark:border-emerald-800 dark:text-emerald-400'
                                    : 'bg-rose-50 border-rose-100 text-rose-700 dark:bg-rose-900/20 dark:border-rose-800 dark:text-rose-400'}`}
                            >
                                {!student.user.is_suspended ? <><Shield className="w-3.5 h-3.5" /> Active</> : <><ShieldOff className="w-3.5 h-3.5" /> Suspended</>}
                            </button>
                            <RowActions student={student} onView={setSelectedStudent} onEdit={setEditingStudent} onReset={handleReset} onCourses={setCoursesStudent} onResetPassword={handleResetPassword} />
                        </div>
                    </div>
                ))}
                {filteredStudents.length === 0 && (
                    <div className="card p-10 text-center text-surface-500 italic">No students match your filters.</div>
                )}
            </div>

            <AnimatePresence>
                {selectedStudent && (
                    <StudentDetailModal
                        student={selectedStudent}
                        onClose={() => setSelectedStudent(null)}
                        onEdit={(s) => { setSelectedStudent(null); setEditingStudent(s) }}
                    />
                )}
                {editingStudent && (
                    <StudentEditModal
                        student={editingStudent}
                        onClose={() => setEditingStudent(null)}
                    />
                )}
                {coursesStudent && (
                    <AssignCoursesModal
                        student={
                            // Keep the modal in sync with refetched roster data.
                            studentList.find((s) => s.id === coursesStudent.id) || coursesStudent
                        }
                        courses={exams}
                        onClose={() => setCoursesStudent(null)}
                    />
                )}
                {showCreate && (
                    <CreateStudentModal
                        courses={exams}
                        onClose={() => setShowCreate(false)}
                    />
                )}
            </AnimatePresence>
        </div>
    )
}

/* ---------------------------------------------------------------------------
 * PerformanceReports — course-level analytics + downloadable reports
 * ------------------------------------------------------------------------- */
const downloadCsv = (headers, rows, filename) => {
    const escape = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`
    const csv = [headers.map(escape).join(','), ...rows.map((r) => r.map(escape).join(','))].join('\n')
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    link.click()
    URL.revokeObjectURL(url)
}

const fmtDate = (v) => (v ? new Date(v).toLocaleDateString() : '')

const PerformanceReports = () => {
    const [filterCourse, setFilterCourse] = useState('all')
    const [filterStatus, setFilterStatus] = useState('all')
    const [reportOpen, setReportOpen] = useState(false)

    const { data: students, isLoading } = useQuery({
        queryKey: ['tenantStudents'],
        queryFn: () => tenantAdminService.getStudents(),
    })

    const { data: examsData } = useQuery({
        queryKey: ['adminExamOptions'],
        queryFn: () => courseService.getAvailableCoursesForEnrollment(),
    })
    const courses = Array.isArray(examsData) ? examsData : (examsData?.results || examsData?.courses || [])

    const studentList = Array.isArray(students) ? students : (students?.results || [])

    // Roster filtered by the active course + status selectors.
    const filtered = useMemo(() => {
        return studentList.filter((s) => {
            const matchesCourse = filterCourse === 'all' || (s.enrolled_course_ids || []).some((cid) => String(cid) === String(filterCourse))
            const matchesStatus =
                filterStatus === 'all' ||
                (filterStatus === 'active' && !s.user.is_suspended) ||
                (filterStatus === 'suspended' && s.user.is_suspended)
            return matchesCourse && matchesStatus
        })
    }, [studentList, filterCourse, filterStatus])

    // Aggregate the roster into per-course performance rows. A student counts
    // toward every course they're enrolled in (all courses are equal level).
    const courseStats = useMemo(() => {
        const map = new Map()
        const bump = (key, name, s) => {
            if (!map.has(key)) {
                map.set(key, { id: key, name, students: 0, active: 0, xp: 0, level: 0, accuracy: 0, questions: 0, correct: 0, minutes: 0 })
            }
            const g = map.get(key)
            g.students += 1
            if (!s.user.is_suspended) g.active += 1
            g.xp += s.total_xp || 0
            g.level += s.current_level || 0
            g.accuracy += s.overall_accuracy || 0
            g.questions += s.total_questions_attempted || 0
            g.correct += s.total_correct_answers || 0
            g.minutes += s.total_study_time_minutes || 0
        }
        studentList.forEach((s) => {
            const enrolled = s.enrolled_courses || []
            if (enrolled.length) {
                enrolled.forEach((c) => bump(c.id ?? 'none', c.name || 'Unnamed Course', s))
            } else {
                bump('none', 'No Course Assigned', s)
            }
        })
        return Array.from(map.values())
            .map((g) => ({
                ...g,
                avgAccuracy: g.students ? Math.round((g.accuracy / g.students) * 10) / 10 : 0,
                avgXp: g.students ? Math.round(g.xp / g.students) : 0,
                avgLevel: g.students ? Math.round((g.level / g.students) * 10) / 10 : 0,
                studyHours: Math.round(g.minutes / 60),
            }))
            .sort((a, b) => b.students - a.students)
    }, [studentList])

    const maxAccuracy = Math.max(100, ...courseStats.map((c) => c.avgAccuracy))

    // Institutional totals across the filtered roster.
    const totals = useMemo(() => {
        const count = filtered.length
        const active = filtered.filter((s) => !s.user.is_suspended).length
        const avgAccuracy = count ? Math.round((filtered.reduce((a, s) => a + (s.overall_accuracy || 0), 0) / count) * 10) / 10 : 0
        const totalXp = filtered.reduce((a, s) => a + (s.total_xp || 0), 0)
        const questions = filtered.reduce((a, s) => a + (s.total_questions_attempted || 0), 0)
        return { count, active, avgAccuracy, totalXp, questions }
    }, [filtered])

    const topPerformers = useMemo(
        () => [...filtered].sort((a, b) => (b.total_xp || 0) - (a.total_xp || 0)).slice(0, 5),
        [filtered]
    )

    const courseLabel = filterCourse === 'all' ? 'all-courses' : (courseStats.find((c) => String(c.id) === String(filterCourse))?.name || 'course')
    const courseNames = (s) => (s.enrolled_courses || []).map((c) => c.name).filter(Boolean).join('; ')
    const slug = (s) => String(s).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
    const stamp = new Date().toISOString().slice(0, 10)

    // -------- Report generators --------
    const reportRoster = () => {
        if (!filtered.length) return toast.error('No students match the current filters')
        const headers = ['Full Name', 'Email', 'Phone', 'Course', 'Status', 'Grade', 'Target Year', 'School', 'Coaching', 'Board', 'Medium', 'City', 'State', 'Level', 'Total XP', 'Accuracy %', 'Questions Attempted', 'Correct Answers', 'Study Minutes', 'Joined', 'Last Active']
        const rows = filtered.map((s) => [
            s.user.full_name, s.user.email, s.user.phone, courseNames(s), s.user.is_suspended ? 'Suspended' : 'Active',
            s.grade, s.target_year, s.school, s.coaching, s.board, s.medium, s.city, s.state,
            s.current_level, s.total_xp, s.overall_accuracy, s.total_questions_attempted, s.total_correct_answers, s.total_study_time_minutes,
            fmtDate(s.user.created_at), fmtDate(s.user.last_active),
        ])
        downloadCsv(headers, rows, `roster-${slug(courseLabel)}-${stamp}.csv`)
        toast.success(`Exported ${rows.length} students`)
    }

    const reportCourseSummary = () => {
        if (!courseStats.length) return toast.error('No course data available')
        const headers = ['Course', 'Students', 'Active', 'Avg Accuracy %', 'Avg Level', 'Avg XP', 'Total Questions', 'Total Correct', 'Study Hours']
        const rows = courseStats.map((c) => [c.name, c.students, c.active, c.avgAccuracy, c.avgLevel, c.avgXp, c.questions, c.correct, c.studyHours])
        downloadCsv(headers, rows, `course-summary-${stamp}.csv`)
        toast.success('Exported course performance summary')
    }

    const reportLeaderboard = () => {
        const ranked = [...filtered].sort((a, b) => (b.total_xp || 0) - (a.total_xp || 0))
        if (!ranked.length) return toast.error('No students match the current filters')
        const headers = ['Rank', 'Full Name', 'Email', 'Course', 'Level', 'Total XP', 'Accuracy %']
        const rows = ranked.map((s, i) => [i + 1, s.user.full_name, s.user.email, courseNames(s), s.current_level, s.total_xp, s.overall_accuracy])
        downloadCsv(headers, rows, `leaderboard-${slug(courseLabel)}-${stamp}.csv`)
        toast.success('Exported leaderboard')
    }

    const reportEngagement = () => {
        if (!filtered.length) return toast.error('No students match the current filters')
        const headers = ['Full Name', 'Email', 'Course', 'Status', 'Study Minutes', 'Questions Attempted', 'Correct Answers', 'Accuracy %', 'Joined', 'Last Active']
        const rows = filtered.map((s) => [
            s.user.full_name, s.user.email, courseNames(s), s.user.is_suspended ? 'Suspended' : 'Active',
            s.total_study_time_minutes, s.total_questions_attempted, s.total_correct_answers, s.overall_accuracy,
            fmtDate(s.user.created_at), fmtDate(s.user.last_active),
        ])
        downloadCsv(headers, rows, `engagement-${slug(courseLabel)}-${stamp}.csv`)
        toast.success('Exported engagement report')
    }

    const reportTypes = [
        { key: 'roster', label: 'Student Roster', desc: 'Full profile & performance for every student', icon: Users, run: reportRoster },
        { key: 'summary', label: 'Course Performance Summary', desc: 'Aggregated metrics per course', icon: BarChart3, run: reportCourseSummary },
        { key: 'leaderboard', label: 'Leaderboard', desc: 'Students ranked by XP', icon: Award, run: reportLeaderboard },
        { key: 'engagement', label: 'Engagement & Activity', desc: 'Study time, attempts & last active', icon: Clock, run: reportEngagement },
    ]

    if (isLoading) return <div className="py-12 text-center text-surface-500">Generating reports…</div>

    return (
        <div className="space-y-6">
            {/* Filter + download toolbar */}
            <div className="card p-4 sm:p-5 space-y-4">
                <div className="flex flex-col lg:flex-row gap-3 lg:items-end">
                    <div className="space-y-1 flex-1 min-w-0">
                        <label className="text-[10px] font-bold uppercase tracking-wider text-surface-400 flex items-center gap-1"><BookOpen className="w-3 h-3" /> Course</label>
                        <select className="input py-2.5 w-full" value={filterCourse} onChange={(e) => setFilterCourse(e.target.value)}>
                            <option value="all">All Courses</option>
                            {courses.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                        </select>
                    </div>
                    <div className="space-y-1 flex-1 min-w-0">
                        <label className="text-[10px] font-bold uppercase tracking-wider text-surface-400 flex items-center gap-1"><Shield className="w-3 h-3" /> Status</label>
                        <select className="input py-2.5 w-full" value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}>
                            <option value="all">All Status</option>
                            <option value="active">Active</option>
                            <option value="suspended">Suspended</option>
                        </select>
                    </div>
                    <div className="relative">
                        <button onClick={() => setReportOpen((v) => !v)} className="btn-primary justify-center whitespace-nowrap w-full lg:w-auto">
                            <Download className="w-4 h-4" /> Download Report <ChevronDown className={`w-4 h-4 transition-transform ${reportOpen ? 'rotate-180' : ''}`} />
                        </button>
                        <AnimatePresence>
                            {reportOpen && (
                                <>
                                    <div className="fixed inset-0 z-10" onClick={() => setReportOpen(false)} />
                                    <motion.div
                                        initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }}
                                        className="absolute right-0 mt-2 w-72 z-20 card p-2 shadow-xl border border-surface-200 dark:border-surface-700"
                                    >
                                        {reportTypes.map((r) => (
                                            <button
                                                key={r.key}
                                                onClick={() => { r.run(); setReportOpen(false) }}
                                                className="w-full flex items-start gap-3 p-2.5 rounded-lg hover:bg-surface-50 dark:hover:bg-surface-800 text-left transition-colors"
                                            >
                                                <div className="w-8 h-8 rounded-lg bg-primary-100 dark:bg-primary-900/30 flex items-center justify-center shrink-0">
                                                    <r.icon className="w-4 h-4 text-primary-600 dark:text-primary-400" />
                                                </div>
                                                <div className="min-w-0">
                                                    <div className="text-sm font-semibold text-surface-800 dark:text-surface-100">{r.label}</div>
                                                    <div className="text-[11px] text-surface-500 leading-tight">{r.desc}</div>
                                                </div>
                                            </button>
                                        ))}
                                    </motion.div>
                                </>
                            )}
                        </AnimatePresence>
                    </div>
                </div>
                <div className="flex items-center gap-1.5 text-xs text-surface-500">
                    <Filter className="w-3.5 h-3.5" />
                    Reporting on <span className="font-bold text-surface-700 dark:text-surface-200">{filtered.length}</span> student{filtered.length === 1 ? '' : 's'}
                    {filterCourse !== 'all' && <span>· {courseLabel}</span>}
                </div>
            </div>

            {/* Summary stat cards for the current filter */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
                {[
                    { label: 'Students', value: totals.count.toLocaleString(), icon: Users, color: 'text-primary-500' },
                    { label: 'Active', value: totals.active.toLocaleString(), icon: CheckCircle2, color: 'text-emerald-500' },
                    { label: 'Avg Accuracy', value: `${totals.avgAccuracy}%`, icon: TrendingUp, color: 'text-amber-500' },
                    { label: 'Total XP', value: totals.totalXp.toLocaleString(), icon: Zap, color: 'text-violet-500' },
                ].map((s) => (
                    <div key={s.label} className="card p-4">
                        <div className="flex items-center justify-between">
                            <span className="text-[10px] font-bold uppercase tracking-wider text-surface-400">{s.label}</span>
                            <s.icon className={`w-4 h-4 ${s.color}`} />
                        </div>
                        <div className="mt-2 text-2xl font-black text-surface-900 dark:text-white">{s.value}</div>
                    </div>
                ))}
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 lg:gap-8">
                {/* Course-wise performance */}
                <div className="lg:col-span-2 space-y-6">
                    <div className="card p-5 sm:p-6">
                        <h3 className="text-lg font-bold mb-6 flex items-center gap-2">
                            <BarChart3 className="w-5 h-5 text-primary-500" /> Course-wise Performance
                        </h3>
                        <div className="space-y-6">
                            {courseStats.map((item) => (
                                <div key={item.id} className="group">
                                    <div className="flex justify-between items-end mb-2">
                                        <div className="min-w-0">
                                            <span className="text-sm font-semibold text-surface-700 dark:text-surface-300 group-hover:text-primary-500 transition-colors">{item.name}</span>
                                            <span className="text-[10px] text-surface-500 ml-2">({item.students} student{item.students === 1 ? '' : 's'})</span>
                                        </div>
                                        <span className="text-sm font-bold text-primary-600 dark:text-primary-400">{item.avgAccuracy}%</span>
                                    </div>
                                    <div className="h-3 bg-surface-100 dark:bg-surface-800 rounded-full overflow-hidden">
                                        <motion.div initial={{ width: 0 }} animate={{ width: `${(item.avgAccuracy / maxAccuracy) * 100}%` }} className="h-full bg-gradient-to-r from-primary-500 to-primary-400" />
                                    </div>
                                    <div className="mt-1 flex justify-between text-[10px] text-surface-400">
                                        <span>Avg Level {item.avgLevel} · {item.avgXp.toLocaleString()} XP</span>
                                        <span>{item.studyHours}h studied · {item.questions.toLocaleString()} questions</span>
                                    </div>
                                </div>
                            ))}
                            {courseStats.length === 0 && (
                                <div className="text-center py-12 text-surface-500 italic font-medium">No course data available yet.</div>
                            )}
                        </div>
                    </div>
                </div>

                {/* Top performers for current filter */}
                <div className="space-y-6">
                    <div className="card p-5 sm:p-6 bg-gradient-to-br from-surface-50 to-white dark:from-surface-900 dark:to-surface-800 border-primary-500/10">
                        <h3 className="text-lg font-bold mb-6 flex items-center gap-2">
                            <Award className="w-5 h-5 text-amber-500" /> Top Performers
                        </h3>
                        <div className="space-y-4">
                            {topPerformers.map((student, index) => (
                                <div key={student.id} className="flex items-center gap-4 p-3 rounded-xl bg-white dark:bg-surface-800/50 shadow-sm border border-surface-100 dark:border-surface-700">
                                    <div className={`w-8 h-8 rounded-lg flex items-center justify-center font-bold text-sm ${index === 0 ? 'bg-amber-100 text-amber-600' : index === 1 ? 'bg-slate-100 text-slate-600' : index === 2 ? 'bg-orange-100 text-orange-600' : 'bg-surface-100 text-surface-500'}`}>
                                        {index + 1}
                                    </div>
                                    <div className="flex-1 min-w-0">
                                        <div className="font-bold text-sm truncate dark:text-white">{student.user.full_name}</div>
                                        <div className="text-[10px] text-surface-500">Level {student.current_level} • {student.overall_accuracy}% Accuracy</div>
                                    </div>
                                    <div className="text-right">
                                        <div className="text-xs font-black text-primary-600 dark:text-primary-400">{(student.total_xp || 0).toLocaleString()}</div>
                                        <div className="text-[8px] uppercase tracking-wider text-surface-400 font-bold">XP</div>
                                    </div>
                                </div>
                            ))}
                            {topPerformers.length === 0 && (
                                <p className="text-center text-surface-500 py-8 italic text-sm">No students match the current filters.</p>
                            )}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )
}

/* ---------------------------------------------------------------------------
 * ContentManagement
 * ------------------------------------------------------------------------- */
const ContentManagement = () => {
    const { data: explorer, isLoading } = useQuery({
        queryKey: ['contentExplorer'],
        queryFn: () => analyticsService.getContentExplorer(),
    })

    const [expandedExam, setExpandedExam] = useState(null)
    const [expandedSubject, setExpandedSubject] = useState(null)

    if (isLoading) return <div className="py-12 flex justify-center"><div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-500"></div></div>

    return (
        <div className="space-y-6">
            <div>
                <h2 className="text-xl font-bold text-surface-900 dark:text-white">Institutional Content Library</h2>
                <p className="text-sm text-surface-500">Explore courses, subjects, and chapters available to your students</p>
            </div>

            <div className="space-y-4">
                {explorer?.map((exam) => (
                    <div key={exam.id} className="bg-white dark:bg-surface-800 rounded-3xl border border-surface-100 dark:border-surface-700 overflow-hidden shadow-sm">
                        <button onClick={() => setExpandedExam(expandedExam === exam.id ? null : exam.id)} className="w-full p-5 sm:p-6 flex items-center justify-between hover:bg-surface-50/50 dark:hover:bg-surface-900/10 transition-colors">
                            <div className="flex items-center gap-4 min-w-0">
                                <div className="w-12 h-12 rounded-2xl bg-surface-100 dark:bg-surface-900/30 flex items-center justify-center shrink-0">
                                    <Library className="w-6 h-6 text-primary-500" />
                                </div>
                                <div className="text-left min-w-0">
                                    <h3 className="font-bold text-base sm:text-lg text-surface-900 dark:text-white truncate">{exam.name}</h3>
                                    <div className="flex items-center gap-3 mt-1">
                                        <span className="text-xs font-bold text-surface-400 uppercase tracking-widest">{exam.course_type}</span>
                                        <div className="w-1 h-1 rounded-full bg-surface-300"></div>
                                        <span className="text-xs text-surface-500">{exam.subjects_count} Subjects</span>
                                    </div>
                                </div>
                            </div>
                            <ChevronDown className={`w-5 h-5 text-surface-400 transition-transform shrink-0 ${expandedExam === exam.id ? 'rotate-180' : ''}`} />
                        </button>

                        <AnimatePresence>
                            {expandedExam === exam.id && (
                                <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }} className="overflow-hidden border-t dark:border-surface-700">
                                    <div className="p-5 sm:p-6 space-y-4">
                                        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
                                            <div className="p-4 bg-surface-50 dark:bg-surface-900/30 rounded-2xl">
                                                <p className="text-[10px] font-bold text-surface-400 uppercase tracking-wider mb-1">Duration</p>
                                                <p className="font-bold text-surface-700 dark:text-surface-200">{exam.duration_minutes} Minutes</p>
                                            </div>
                                            <div className="p-4 bg-surface-50 dark:bg-surface-900/30 rounded-2xl">
                                                <p className="text-[10px] font-bold text-surface-400 uppercase tracking-wider mb-1">Marking Scheme</p>
                                                <p className="font-bold text-surface-700 dark:text-surface-200">+{exam.total_marks} Total</p>
                                            </div>
                                            <div className="p-4 bg-surface-50 dark:bg-surface-900/30 rounded-2xl">
                                                <p className="text-[10px] font-bold text-surface-400 uppercase tracking-wider mb-1">Testing Resources</p>
                                                <p className="font-bold text-surface-700 dark:text-surface-200">{exam.mock_tests_count} Mocks / {exam.quizzes_count} Quizzes</p>
                                            </div>
                                            <div className="p-4 bg-surface-50 dark:bg-surface-900/30 rounded-2xl">
                                                <p className="text-[10px] font-bold text-surface-400 uppercase tracking-wider mb-1">Question Bank</p>
                                                <p className="font-bold text-surface-700 dark:text-surface-200">{exam.total_questions?.toLocaleString()}+ Questions</p>
                                            </div>
                                        </div>

                                        <div className="space-y-3">
                                            <h4 className="text-xs font-black text-surface-400 uppercase tracking-widest px-2">Subjects & Chapters</h4>
                                            {exam.subjects?.map((subject) => (
                                                <div key={subject.id} className="border dark:border-surface-700 rounded-2xl overflow-hidden bg-surface-50/30 dark:bg-surface-900/10">
                                                    <button onClick={(e) => { e.stopPropagation(); setExpandedSubject(expandedSubject === subject.id ? null : subject.id) }} className="w-full p-4 flex items-center justify-between hover:bg-surface-100/50 dark:hover:bg-surface-700/30 transition-colors">
                                                        <div className="flex items-center gap-3 min-w-0">
                                                            <div className="w-8 h-8 rounded-lg bg-white dark:bg-surface-800 flex items-center justify-center border border-surface-100 dark:border-surface-700 shrink-0">
                                                                <Book className="w-4 h-4 text-primary-600" />
                                                            </div>
                                                            <div className="text-left min-w-0">
                                                                <p className="font-bold text-surface-800 dark:text-surface-200 truncate">{subject.name}</p>
                                                                <p className="text-[10px] text-surface-500">{subject.weightage}% weightage • {subject.total_topics} Topics</p>
                                                            </div>
                                                        </div>
                                                        <ChevronDown className={`w-4 h-4 text-surface-400 transition-transform shrink-0 ${expandedSubject === subject.id ? 'rotate-180' : ''}`} />
                                                    </button>

                                                    <AnimatePresence>
                                                        {expandedSubject === subject.id && (
                                                            <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }} className="overflow-hidden bg-white dark:bg-surface-800">
                                                                <div className="p-4 pt-0 divide-y dark:divide-surface-700/50">
                                                                    {subject.chapters?.map((chapter) => (
                                                                        <div key={chapter.id} className="py-3 flex items-center justify-between group">
                                                                            <div className="flex items-center gap-3 min-w-0">
                                                                                <Layers className="w-3.5 h-3.5 text-surface-400 group-hover:text-primary-500 transition-colors shrink-0" />
                                                                                <div className="min-w-0">
                                                                                    <p className="text-sm font-medium text-surface-700 dark:text-surface-300 truncate">{chapter.name}</p>
                                                                                    <p className="text-[10px] text-surface-500 italic">{chapter.grade ? `Grade ${chapter.grade}` : 'Resource'} • {chapter.estimated_hours}h estimated</p>
                                                                                </div>
                                                                            </div>
                                                                            <span className="text-[10px] bg-surface-100 dark:bg-surface-900 border dark:border-surface-700 px-2 py-0.5 rounded-full text-surface-500 shrink-0">{chapter.topics_count} Topics</span>
                                                                        </div>
                                                                    ))}
                                                                    {subject.chapters?.length === 0 && (
                                                                        <p className="py-4 text-center text-xs text-surface-400 italic">No chapters defined for this subject.</p>
                                                                    )}
                                                                </div>
                                                            </motion.div>
                                                        )}
                                                    </AnimatePresence>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                </motion.div>
                            )}
                        </AnimatePresence>
                    </div>
                ))}
                {(!explorer || explorer.length === 0) && (
                    <div className="card p-10 text-center text-surface-500 italic">No content library available yet.</div>
                )}
            </div>
        </div>
    )
}

/* ---------------------------------------------------------------------------
 * EnrollmentRequests
 * ------------------------------------------------------------------------- */
const EnrollmentRequests = () => {
    const queryClient = useQueryClient()
    const [filter, setFilter] = useState('pending')
    const [busyId, setBusyId] = useState(null)
    const [studentQuery, setStudentQuery] = useState('')
    const [courseQuery, setCourseQuery] = useState('')
    const [emailQuery, setEmailQuery] = useState('')

    const { data: requests = [], isLoading } = useQuery({
        queryKey: ['enrollmentRequests', filter],
        queryFn: () => tenantAdminService.getEnrollmentRequests(filter === 'all' ? {} : { status: filter }),
    })
    const list = Array.isArray(requests) ? requests : (requests?.results || [])

    const filteredList = useMemo(() => {
        const s = studentQuery.trim().toLowerCase()
        const c = courseQuery.trim().toLowerCase()
        const e = emailQuery.trim().toLowerCase()
        return list.filter((r) => {
            const matchesStudent = !s || (r.student_name || '').toLowerCase().includes(s)
            const matchesCourse = !c ||
                (r.course_name || '').toLowerCase().includes(c) ||
                (r.course_code || '').toLowerCase().includes(c)
            const matchesEmail = !e || (r.student_email || '').toLowerCase().includes(e)
            return matchesStudent && matchesCourse && matchesEmail
        })
    }, [list, studentQuery, courseQuery, emailQuery])

    const hasActiveFilters = studentQuery || courseQuery || emailQuery
    const clearFilters = () => { setStudentQuery(''); setCourseQuery(''); setEmailQuery('') }

    const refresh = () => queryClient.invalidateQueries({ queryKey: ['enrollmentRequests'] })

    const approve = async (id) => {
        setBusyId(id)
        try { await tenantAdminService.approveEnrollment(id); refresh(); toast.success('Enrollment approved') }
        catch { toast.error('Failed to approve') } finally { setBusyId(null) }
    }
    const reject = async (id) => {
        const reason = window.prompt('Reason for rejection (optional):', '') ?? ''
        setBusyId(id)
        try { await tenantAdminService.rejectEnrollment(id, reason); refresh(); toast.success('Enrollment rejected') }
        catch { toast.error('Failed to reject') } finally { setBusyId(null) }
    }

    const badge = {
        pending: 'bg-amber-100 dark:bg-amber-900/30 text-amber-600',
        approved: 'bg-green-100 dark:bg-green-900/30 text-green-600',
        rejected: 'bg-red-100 dark:bg-red-900/30 text-red-600',
    }

    return (
        <div className="space-y-6">
            <div className="flex flex-wrap items-center justify-end gap-3">
                <div className="flex gap-1 p-1 bg-surface-100 dark:bg-surface-800 rounded-lg overflow-x-auto">
                    {['pending', 'approved', 'rejected', 'all'].map((f) => (
                        <button key={f} onClick={() => setFilter(f)} className={`px-4 py-1.5 rounded-md text-sm font-semibold capitalize transition-all whitespace-nowrap ${filter === f ? 'bg-white dark:bg-surface-700 text-primary-600 shadow-sm' : 'text-surface-500'}`}>
                            {f}
                        </button>
                    ))}
                </div>
            </div>

            {/* Filters: student, course, email */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div className="relative">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-surface-400" />
                    <input
                        type="text"
                        value={studentQuery}
                        onChange={(e) => setStudentQuery(e.target.value)}
                        placeholder="Filter by student"
                        className="w-full pl-9 pr-3 py-2 rounded-xl bg-surface-100 dark:bg-surface-800 border-none text-sm focus:ring-2 focus:ring-primary-500"
                    />
                </div>
                <div className="relative">
                    <BookOpen className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-surface-400" />
                    <input
                        type="text"
                        value={courseQuery}
                        onChange={(e) => setCourseQuery(e.target.value)}
                        placeholder="Filter by course"
                        className="w-full pl-9 pr-3 py-2 rounded-xl bg-surface-100 dark:bg-surface-800 border-none text-sm focus:ring-2 focus:ring-primary-500"
                    />
                </div>
                <div className="relative">
                    <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-surface-400" />
                    <input
                        type="text"
                        value={emailQuery}
                        onChange={(e) => setEmailQuery(e.target.value)}
                        placeholder="Filter by email"
                        className="w-full pl-9 pr-9 py-2 rounded-xl bg-surface-100 dark:bg-surface-800 border-none text-sm focus:ring-2 focus:ring-primary-500"
                    />
                    {hasActiveFilters && (
                        <button
                            onClick={clearFilters}
                            aria-label="Clear filters"
                            className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded-lg text-surface-400 hover:text-surface-600 hover:bg-surface-200 dark:hover:bg-surface-700"
                        >
                            <X className="w-4 h-4" />
                        </button>
                    )}
                </div>
            </div>

            {isLoading ? (
                <p className="text-surface-500">Loading…</p>
            ) : filteredList.length === 0 ? (
                <div className="card p-10 text-center text-surface-500">
                    <Clock className="w-10 h-10 mx-auto mb-3 text-surface-300" />
                    {hasActiveFilters ? 'No requests match your filters.' : `No ${filter !== 'all' ? filter : ''} requests.`}
                </div>
            ) : (
                <div className="card overflow-hidden">
                    <div className="overflow-x-auto">
                        <table className="w-full text-left">
                            <thead className="bg-surface-50 dark:bg-surface-800 text-xs uppercase text-surface-500">
                                <tr>
                                    <th className="px-4 py-3">Student</th>
                                    <th className="px-4 py-3">Course</th>
                                    <th className="px-4 py-3">Status</th>
                                    <th className="px-4 py-3 text-right">Action</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-surface-100 dark:divide-surface-700">
                                {filteredList.map((r) => (
                                    <tr key={r.id}>
                                        <td className="px-4 py-3">
                                            <p className="font-medium">{r.student_name || '—'}</p>
                                            <p className="text-xs text-surface-500">{r.student_email}</p>
                                        </td>
                                        <td className="px-4 py-3 whitespace-nowrap">{r.course_name} <span className="text-xs text-surface-400">{r.course_code}</span></td>
                                        <td className="px-4 py-3">
                                            <span className={`px-2.5 py-1 rounded-full text-xs font-semibold capitalize ${badge[r.status]}`}>{r.status}</span>
                                        </td>
                                        <td className="px-4 py-3">
                                            {r.status === 'pending' ? (
                                                <div className="flex items-center justify-end gap-2">
                                                    <button onClick={() => approve(r.id)} disabled={busyId === r.id} className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-green-500 text-white text-sm font-semibold hover:bg-green-600 disabled:opacity-50">
                                                        <Check size={14} /> Approve
                                                    </button>
                                                    <button onClick={() => reject(r.id)} disabled={busyId === r.id} className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-red-500 text-white text-sm font-semibold hover:bg-red-600 disabled:opacity-50">
                                                        <XCircle size={14} /> Reject
                                                    </button>
                                                </div>
                                            ) : r.status === 'rejected' ? (
                                                <div className="text-right">
                                                    <button onClick={() => approve(r.id)} disabled={busyId === r.id} className="text-sm text-green-600 hover:underline">Approve anyway</button>
                                                </div>
                                            ) : (
                                                <div className="text-right"><span className="text-sm text-surface-400">—</span></div>
                                            )}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}
        </div>
    )
}

/* ---------------------------------------------------------------------------
 * SalesDashboard — orders, revenue summary, refunds & access control
 * ------------------------------------------------------------------------- */
const ORDER_STATUS_META = {
    paid: { label: 'Paid', cls: 'bg-green-100 dark:bg-green-900/30 text-green-600' },
    refunded: { label: 'Refunded', cls: 'bg-purple-100 dark:bg-purple-900/30 text-purple-600' },
    failed: { label: 'Failed', cls: 'bg-red-100 dark:bg-red-900/30 text-red-600' },
    created: { label: 'Pending', cls: 'bg-amber-100 dark:bg-amber-900/30 text-amber-600' },
    cancelled: { label: 'Cancelled', cls: 'bg-surface-200 dark:bg-surface-700 text-surface-500' },
}
const PROVIDER_LABEL = { razorpay: 'Razorpay', cashfree: 'Cashfree', payu: 'PayU' }
const RANGE_PRESETS = [
    { id: 'all', label: 'All time' },
    { id: 'week', label: 'Last 7 days' },
    { id: 'month', label: 'Last 30 days' },
    { id: 'custom', label: 'Custom' },
]

const toISODate = (d) => {
    const tz = new Date(d.getTime() - d.getTimezoneOffset() * 60000)
    return tz.toISOString().slice(0, 10)
}
const rangeToDates = (range, from, to) => {
    if (range === 'custom') {
        const out = {}
        if (from) out.date_from = from
        if (to) out.date_to = to
        return out
    }
    if (range === 'week' || range === 'month') {
        const now = new Date()
        const start = new Date()
        start.setDate(now.getDate() - (range === 'week' ? 6 : 29))
        return { date_from: toISODate(start), date_to: toISODate(now) }
    }
    return {}
}
const fmtMoney = (amount, currency = 'INR') => {
    const n = Number(amount || 0)
    try {
        return new Intl.NumberFormat('en-IN', {
            style: 'currency', currency: currency || 'INR', maximumFractionDigits: 2,
        }).format(n)
    } catch {
        return `₹${n.toLocaleString('en-IN')}`
    }
}
const fmtDateTime = (s) => {
    if (!s) return '—'
    const d = new Date(s)
    return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' }) +
        ', ' + d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })
}

const SalesSummaryCard = ({ icon: Icon, label, value, sub, color }) => (
    <div className="card p-5 flex items-start gap-4">
        <div className={`p-3 rounded-xl ${color}`}><Icon className="w-5 h-5 text-white" /></div>
        <div className="min-w-0">
            <p className="text-sm text-surface-500">{label}</p>
            <p className="text-xl sm:text-2xl font-bold text-surface-900 dark:text-white truncate">{value}</p>
            {sub && <p className="text-xs text-surface-400 mt-0.5">{sub}</p>}
        </div>
    </div>
)

const SalesDashboard = () => {
    const queryClient = useQueryClient()
    const [range, setRange] = useState('all')
    const [customFrom, setCustomFrom] = useState('')
    const [customTo, setCustomTo] = useState('')
    const [statusFilter, setStatusFilter] = useState('all')
    const [providerFilter, setProviderFilter] = useState('all')
    const [courseFilter, setCourseFilter] = useState('all')
    const [search, setSearch] = useState('')
    const [busyId, setBusyId] = useState(null)

    const params = useMemo(() => {
        const p = { ...rangeToDates(range, customFrom, customTo) }
        if (statusFilter !== 'all') p.status = statusFilter
        if (providerFilter !== 'all') p.provider = providerFilter
        if (courseFilter !== 'all') p.course = courseFilter
        const s = search.trim()
        if (s) p.search = s
        return p
    }, [range, customFrom, customTo, statusFilter, providerFilter, courseFilter, search])

    const { data: ordersData, isLoading } = useQuery({
        queryKey: ['salesOrders', params],
        queryFn: () => tenantAdminService.getSalesOrders(params),
        keepPreviousData: true,
    })
    const { data: summary } = useQuery({
        queryKey: ['salesSummary', params],
        queryFn: () => tenantAdminService.getSalesSummary(params),
        keepPreviousData: true,
    })
    const { data: coursesRaw } = useQuery({
        queryKey: ['salesCourseOptions'],
        queryFn: () => courseService.getCourses(),
        staleTime: 5 * 60 * 1000,
    })

    const orders = Array.isArray(ordersData) ? ordersData : (ordersData?.results || [])
    const totalCount = ordersData?.count ?? orders.length
    const courseOptions = useMemo(() => {
        const list = Array.isArray(coursesRaw) ? coursesRaw : (coursesRaw?.results || [])
        return list.map((c) => ({ id: c.id, name: c.name || c.title || c.code }))
    }, [coursesRaw])

    const refresh = () => queryClient.invalidateQueries({ queryKey: ['salesOrders'] }) &&
        queryClient.invalidateQueries({ queryKey: ['salesSummary'] })
    const invalidateAll = () => {
        queryClient.invalidateQueries({ queryKey: ['salesOrders'] })
        queryClient.invalidateQueries({ queryKey: ['salesSummary'] })
    }

    const doRefund = async (order) => {
        if (!window.confirm(`Refund ${fmtMoney(order.amount, order.currency)} to ${order.student_email}? This calls ${PROVIDER_LABEL[order.provider] || order.provider} and revokes course access.`)) return
        const reason = window.prompt('Refund reason (optional):', '') ?? ''
        setBusyId(order.id)
        try {
            await tenantAdminService.refundOrder(order.id, { reason })
            invalidateAll()
            toast.success('Refund processed and access revoked')
        } catch (e) {
            toast.error(e?.response?.data?.detail || 'Refund failed')
        } finally { setBusyId(null) }
    }
    const doRevoke = async (order) => {
        if (!window.confirm(`Revoke ${order.student_email}'s access to ${order.course_name}?`)) return
        const reason = window.prompt('Reason (optional):', '') ?? ''
        setBusyId(order.id)
        try {
            await tenantAdminService.revokeOrderAccess(order.id, reason)
            invalidateAll()
            toast.success('Course access revoked')
        } catch (e) {
            toast.error(e?.response?.data?.detail || 'Failed to revoke access')
        } finally { setBusyId(null) }
    }
    const doRestore = async (order) => {
        setBusyId(order.id)
        try {
            await tenantAdminService.restoreOrderAccess(order.id)
            invalidateAll()
            toast.success('Course access restored')
        } catch (e) {
            toast.error(e?.response?.data?.detail || 'Failed to restore access')
        } finally { setBusyId(null) }
    }

    const clearFilters = () => {
        setStatusFilter('all'); setProviderFilter('all'); setCourseFilter('all')
        setSearch(''); setRange('all'); setCustomFrom(''); setCustomTo('')
    }
    const counts = summary?.counts || {}

    return (
        <div className="space-y-6">
            <div className="flex flex-wrap items-center justify-end gap-3">
                <div className="flex items-center gap-2">
                    <div className="flex gap-1 p-1 bg-surface-100 dark:bg-surface-800 rounded-lg">
                        {RANGE_PRESETS.map((r) => (
                            <button key={r.id} onClick={() => setRange(r.id)} className={`px-3 py-1.5 rounded-md text-sm font-semibold transition-all whitespace-nowrap ${range === r.id ? 'bg-white dark:bg-surface-700 text-primary-600 shadow-sm' : 'text-surface-500'}`}>
                                {r.label}
                            </button>
                        ))}
                    </div>
                    <button onClick={refresh} className="p-2 rounded-lg bg-surface-100 dark:bg-surface-800 text-surface-600 hover:text-surface-900" title="Refresh">
                        <RefreshCw className="w-4 h-4" />
                    </button>
                </div>
            </div>

            {range === 'custom' && (
                <div className="flex flex-wrap items-end gap-3 card p-4">
                    <div>
                        <label className="block text-xs text-surface-500 mb-1">From</label>
                        <input type="date" value={customFrom} onChange={(e) => setCustomFrom(e.target.value)} className="px-3 py-2 rounded-xl bg-surface-100 dark:bg-surface-800 border-none text-sm" />
                    </div>
                    <div>
                        <label className="block text-xs text-surface-500 mb-1">To</label>
                        <input type="date" value={customTo} onChange={(e) => setCustomTo(e.target.value)} className="px-3 py-2 rounded-xl bg-surface-100 dark:bg-surface-800 border-none text-sm" />
                    </div>
                    <Calendar className="w-4 h-4 text-surface-400 mb-3" />
                </div>
            )}

            {/* Summary cards */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                <SalesSummaryCard icon={IndianRupee} color="bg-emerald-500" label="Total sales" value={fmtMoney(summary?.total_sales, summary?.currency)} sub={`${counts.paid || 0} paid orders`} />
                <SalesSummaryCard icon={Receipt} color="bg-blue-500" label="Total orders" value={counts.total_orders ?? totalCount ?? 0} sub={`${counts.failed || 0} failed · ${counts.created || 0} pending`} />
                <SalesSummaryCard icon={Undo2} color="bg-purple-500" label="Refunded" value={fmtMoney(summary?.refunded_total, summary?.currency)} sub={`${counts.refunded || 0} refunds`} />
                <SalesSummaryCard icon={Wallet} color="bg-primary-500" label="Net revenue" value={fmtMoney(summary?.total_sales, summary?.currency)} sub="After refunds" />
            </div>

            {/* Per-course sales breakdown */}
            {summary?.by_course?.length > 0 && (
                <div className="card p-5">
                    <h3 className="text-sm font-bold text-surface-700 dark:text-surface-200 mb-4 flex items-center gap-2">
                        <BarChart3 className="w-4 h-4 text-primary-500" /> Sales by course
                    </h3>
                    <div className="space-y-3">
                        {summary.by_course.map((c) => {
                            const max = summary.by_course[0]?.amount || 1
                            const pct = Math.max(4, Math.round((Number(c.amount) / Number(max)) * 100))
                            return (
                                <div key={c.course_id}>
                                    <div className="flex justify-between text-sm mb-1">
                                        <span className="font-medium text-surface-700 dark:text-surface-200 truncate pr-2">{c.course_name} <span className="text-xs text-surface-400">{c.course_code}</span></span>
                                        <span className="text-surface-500 whitespace-nowrap">{fmtMoney(c.amount, summary.currency)} · {c.count}</span>
                                    </div>
                                    <div className="h-2 rounded-full bg-surface-100 dark:bg-surface-800 overflow-hidden">
                                        <div className="h-full rounded-full bg-primary-500" style={{ width: `${pct}%` }} />
                                    </div>
                                </div>
                            )
                        })}
                    </div>
                </div>
            )}

            {/* Filters */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                <div className="relative sm:col-span-2 lg:col-span-1">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-surface-400" />
                    <input type="text" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search student / order id" className="w-full pl-9 pr-3 py-2 rounded-xl bg-surface-100 dark:bg-surface-800 border-none text-sm focus:ring-2 focus:ring-primary-500" />
                </div>
                <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className="px-3 py-2 rounded-xl bg-surface-100 dark:bg-surface-800 border-none text-sm focus:ring-2 focus:ring-primary-500">
                    <option value="all">All statuses</option>
                    <option value="paid">Paid</option>
                    <option value="refunded">Refunded</option>
                    <option value="failed">Failed</option>
                    <option value="created">Pending</option>
                    <option value="cancelled">Cancelled</option>
                </select>
                <select value={providerFilter} onChange={(e) => setProviderFilter(e.target.value)} className="px-3 py-2 rounded-xl bg-surface-100 dark:bg-surface-800 border-none text-sm focus:ring-2 focus:ring-primary-500">
                    <option value="all">All providers</option>
                    <option value="razorpay">Razorpay</option>
                    <option value="cashfree">Cashfree</option>
                    <option value="payu">PayU</option>
                </select>
                <select value={courseFilter} onChange={(e) => setCourseFilter(e.target.value)} className="px-3 py-2 rounded-xl bg-surface-100 dark:bg-surface-800 border-none text-sm focus:ring-2 focus:ring-primary-500">
                    <option value="all">All courses</option>
                    {courseOptions.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
            </div>

            {/* Orders table */}
            {isLoading ? (
                <p className="text-surface-500">Loading orders…</p>
            ) : orders.length === 0 ? (
                <div className="card p-10 text-center text-surface-500">
                    <Receipt className="w-10 h-10 mx-auto mb-3 text-surface-300" />
                    No orders match your filters.
                    <div className="mt-3"><button onClick={clearFilters} className="text-sm text-primary-600 hover:underline">Clear filters</button></div>
                </div>
            ) : (
                <div className="card overflow-hidden">
                    <div className="overflow-x-auto">
                        <table className="w-full text-left">
                            <thead className="bg-surface-50 dark:bg-surface-800 text-xs uppercase text-surface-500">
                                <tr>
                                    <th className="px-4 py-3">Order</th>
                                    <th className="px-4 py-3">Student</th>
                                    <th className="px-4 py-3">Course</th>
                                    <th className="px-4 py-3 text-right">Amount</th>
                                    <th className="px-4 py-3">Provider</th>
                                    <th className="px-4 py-3">Status</th>
                                    <th className="px-4 py-3 text-right">Actions</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-surface-100 dark:divide-surface-700">
                                {orders.map((o) => {
                                    const meta = ORDER_STATUS_META[o.status] || ORDER_STATUS_META.created
                                    const accessActive = o.enrollment_active
                                    return (
                                        <tr key={o.id} className="align-top">
                                            <td className="px-4 py-3">
                                                <p className="text-xs font-mono text-surface-500">{o.provider_order_id || String(o.id).slice(0, 8)}</p>
                                                <p className="text-xs text-surface-400">{fmtDateTime(o.created_at)}</p>
                                                {o.is_test_mode && <span className="inline-block mt-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-amber-100 dark:bg-amber-900/30 text-amber-600">TEST</span>}
                                            </td>
                                            <td className="px-4 py-3">
                                                <p className="font-medium">{o.student_name || '—'}</p>
                                                <p className="text-xs text-surface-500">{o.student_email}</p>
                                            </td>
                                            <td className="px-4 py-3 whitespace-nowrap">{o.course_name} <span className="text-xs text-surface-400">{o.course_code}</span></td>
                                            <td className="px-4 py-3 text-right font-semibold whitespace-nowrap">
                                                {fmtMoney(o.amount, o.currency)}
                                                {o.status === 'refunded' && o.refund_amount != null && (
                                                    <p className="text-[11px] font-normal text-purple-500">-{fmtMoney(o.refund_amount, o.currency)} refunded</p>
                                                )}
                                            </td>
                                            <td className="px-4 py-3 whitespace-nowrap text-sm">{PROVIDER_LABEL[o.provider] || o.provider}</td>
                                            <td className="px-4 py-3">
                                                <span className={`px-2.5 py-1 rounded-full text-xs font-semibold ${meta.cls}`}>{meta.label}</span>
                                                {o.enrollment_status && (
                                                    <p className={`mt-1 text-[11px] ${accessActive ? 'text-green-600' : 'text-surface-400'}`}>
                                                        {accessActive ? 'Access active' : 'No access'}
                                                    </p>
                                                )}
                                            </td>
                                            <td className="px-4 py-3">
                                                <div className="flex items-center justify-end gap-2 flex-wrap">
                                                    {o.status === 'paid' && (
                                                        <button onClick={() => doRefund(o)} disabled={busyId === o.id} className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-purple-500 text-white text-xs font-semibold hover:bg-purple-600 disabled:opacity-50">
                                                            <Undo2 size={13} /> Refund
                                                        </button>
                                                    )}
                                                    {accessActive && (
                                                        <button onClick={() => doRevoke(o)} disabled={busyId === o.id} className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-red-500 text-white text-xs font-semibold hover:bg-red-600 disabled:opacity-50">
                                                            <Ban size={13} /> Revoke
                                                        </button>
                                                    )}
                                                    {o.enrollment_status && accessActive === false && (
                                                        <button onClick={() => doRestore(o)} disabled={busyId === o.id} className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-surface-200 dark:bg-surface-700 text-surface-700 dark:text-surface-200 text-xs font-semibold hover:bg-surface-300 disabled:opacity-50">
                                                            <RotateCcw size={13} /> Restore
                                                        </button>
                                                    )}
                                                    {o.status !== 'paid' && !o.enrollment_status && (
                                                        <span className="text-xs text-surface-400">—</span>
                                                    )}
                                                </div>
                                                {o.status === 'refunded' && o.refund_reason && (
                                                    <p className="text-[11px] text-surface-400 mt-1 text-right max-w-[180px] ml-auto truncate" title={o.refund_reason}>{o.refund_reason}</p>
                                                )}
                                            </td>
                                        </tr>
                                    )
                                })}
                            </tbody>
                        </table>
                    </div>
                    <div className="px-4 py-3 text-xs text-surface-500 border-t border-surface-100 dark:border-surface-800">
                        Showing {orders.length} of {totalCount} orders
                    </div>
                </div>
            )}
        </div>
    )
}

/* ---------------------------------------------------------------------------
 * Overview
 * ------------------------------------------------------------------------- */
const RANGE_OPTIONS = [
    { value: 7, label: '7 days' },
    { value: 30, label: '30 days' },
    { value: 90, label: '90 days' },
]

const Overview = ({ stats, range, onRangeChange }) => {
    const growth = stats?.growth || {}
    const rangeLabel = RANGE_OPTIONS.find((o) => o.value === range)?.label || `${range} days`
    return (
    <div className="space-y-6 sm:space-y-8">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 sm:gap-6">
            <StatCard title="Total Students" value={stats?.total_students || 0} icon={Users} color="bg-blue-500" description="Registered locally" />
            <StatCard title="Active Today" value={stats?.active_today || 0} icon={Zap} color="bg-amber-500" description="Student engagement" />
            <StatCard title="Avg. Accuracy" value={`${stats?.avg_accuracy || 0}%`} icon={CheckCircle2} color="bg-emerald-500" description="Target score performance" />
            <StatCard title="Total XP Distributed" value={stats?.total_xp?.toLocaleString() || 0} icon={TrendingUp} color="bg-purple-500" description="Collective progress" />
        </div>

        {/* Growth section --------------------------------------------------- */}
        <div className="space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div>
                    <h3 className="text-lg font-bold text-surface-900 dark:text-white">Growth</h3>
                    <p className="text-sm text-surface-500">Compared to the previous {rangeLabel}</p>
                </div>
                <div className="inline-flex items-center gap-1 p-1 rounded-xl bg-surface-100 dark:bg-surface-800">
                    {RANGE_OPTIONS.map((opt) => (
                        <button
                            key={opt.value}
                            onClick={() => onRangeChange(opt.value)}
                            className={`px-3 py-1.5 rounded-lg text-sm font-semibold transition-colors ${
                                range === opt.value
                                    ? 'bg-white dark:bg-surface-700 text-primary-600 dark:text-primary-400 shadow-sm'
                                    : 'text-surface-500 hover:text-surface-700 dark:hover:text-surface-200'
                            }`}
                        >
                            {opt.label}
                        </button>
                    ))}
                </div>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 sm:gap-6">
                <StatCard
                    title="New Signups"
                    value={growth.new_signups || 0}
                    icon={UserPlus}
                    color="bg-indigo-500"
                    change={growth.signup_change_pct}
                    description={`${growth.prev_new_signups || 0} in prior period`}
                />
                <StatCard
                    title={`Active (${rangeLabel})`}
                    value={growth.active_in_period || 0}
                    icon={Zap}
                    color="bg-amber-500"
                    change={growth.active_change_pct}
                    description={`${growth.prev_active_in_period || 0} in prior period`}
                />
                <StatCard
                    title="Total Students"
                    value={stats?.total_students || 0}
                    icon={Users}
                    color="bg-blue-500"
                    description={`Up from ${growth.total_students_start ?? 0} at period start`}
                />
            </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 sm:gap-8">
            <div className="card p-5 sm:p-6">
                <h3 className="text-lg font-bold mb-6">Student Level Distribution</h3>
                <div className="space-y-4">
                    {Object.entries(stats?.level_distribution || {}).map(([level, count]) => {
                        const percentage = stats?.total_students > 0 ? (count / stats.total_students) * 100 : 0
                        return (
                            <div key={level} className="space-y-2">
                                <div className="flex justify-between text-sm">
                                    <span className="font-medium text-surface-700 dark:text-surface-300">Level {level}</span>
                                    <span className="text-surface-500">{count} students ({Math.round(percentage)}%)</span>
                                </div>
                                <div className="h-2 bg-surface-100 dark:bg-surface-800 rounded-full overflow-hidden">
                                    <motion.div initial={{ width: 0 }} animate={{ width: `${percentage}%` }} className="h-full bg-primary-500" />
                                </div>
                            </div>
                        )
                    })}
                    {Object.keys(stats?.level_distribution || {}).length === 0 && (
                        <p className="text-center text-surface-500 py-8 italic">No institutional participation data yet.</p>
                    )}
                </div>
            </div>

            <div className="card p-5 sm:p-6">
                <h3 className="text-lg font-bold mb-6 flex items-center justify-between">
                    <span>{rangeLabel} Student Activity</span>
                    <div className="flex items-center gap-2 text-[10px] uppercase tracking-wider text-surface-400 font-bold">
                        <div className="w-2 h-2 rounded-full bg-primary-500"></div> Active Users
                    </div>
                </h3>
                <div className="relative h-56 sm:h-64">
                    <div className="absolute inset-0 flex flex-col justify-between pointer-events-none">
                        {[...Array(5)].map((_, i) => <div key={i} className="w-full border-t border-surface-100 dark:border-surface-800/50 h-0"></div>)}
                    </div>
                    <div className="relative h-full flex items-end gap-1 px-2">
                        {(() => {
                            const trend = stats?.activity_trend || []
                            const maxUsers = Math.max(...trend.map((i) => i.active_users), 1)
                            return trend.map((item) => {
                                const height = (item.active_users / maxUsers) * 100
                                return (
                                    <div key={item.date} className="group relative flex-1 h-full flex flex-col justify-end items-center">
                                        <div className="absolute inset-x-0 bottom-0 top-0 bg-primary-500/5 opacity-0 group-hover:opacity-100 transition-opacity rounded-t-lg"></div>
                                        <motion.div initial={{ height: 0 }} animate={{ height: `${height}%` }} className="w-1.5 md:w-2.5 bg-gradient-to-t from-primary-600 to-primary-400 rounded-full relative z-10 shadow-sm" />
                                        <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-4 hidden group-hover:block z-50">
                                            <div className="bg-surface-900 dark:bg-surface-800 text-white p-2 rounded-xl shadow-2xl border border-surface-700/50 whitespace-nowrap">
                                                <div className="text-[8px] uppercase tracking-tighter text-surface-400 font-black mb-0.5">{item.date}</div>
                                                <div className="text-sm font-black flex items-center gap-1.5"><div className="w-1.5 h-1.5 rounded-full bg-primary-400"></div>{item.active_users} Users</div>
                                            </div>
                                            <div className="w-2 h-2 bg-surface-900 dark:bg-surface-800 rotate-45 absolute -bottom-1 left-1/2 -translate-x-1/2 border-r border-b border-surface-700/50"></div>
                                        </div>
                                    </div>
                                )
                            })
                        })()}
                        {(!stats?.activity_trend || stats.activity_trend.length === 0) && (
                            <div className="absolute inset-0 flex items-center justify-center text-surface-500 italic text-sm">No activity trend data recorded.</div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    </div>
    )
}

/* ---------------------------------------------------------------------------
 * TenantSettings — branding (logo) + feature toggles
 * ------------------------------------------------------------------------- */
const TenantSettings = () => {
    const queryClient = useQueryClient()
    const fetchTenantConfig = useTenantStore((s) => s.fetchTenantConfig)
    const fileInputRef = useRef(null)
    const faviconInputRef = useRef(null)

    const { data: settings, isLoading } = useQuery({
        queryKey: ['tenantSettings'],
        queryFn: () => tenantAdminService.getSettings(),
    })

    const [features, setFeatures] = useState({})
    const [name, setName] = useState('')
    const [tagline, setTagline] = useState('')
    const [authPanel, setAuthPanel] = useState({ heading: '', heading_highlight: '', subtitle: '', stats: [] })
    const [subTab, setSubTab] = useState('general')

    useEffect(() => {
        if (settings?.features) setFeatures(settings.features)
        if (settings) {
            setName(settings.name || '')
            setTagline(settings.tagline || '')
            const ap = settings.auth_panel || {}
            setAuthPanel({
                heading: ap.heading || '',
                heading_highlight: ap.heading_highlight || '',
                subtitle: ap.subtitle || '',
                stats: Array.isArray(ap.stats) ? ap.stats.map((s) => ({ value: s.value || '', label: s.label || '' })) : [],
            })
        }
    }, [settings])

    const availableFeatures = settings?.available_features || []
    const lockedFeatures = settings?.locked_features || []
    const quotaStatus = settings?.quota_status || {}
    const planLabel = settings?.plan_label || settings?.plan
    const isBillingFrozen = Boolean(settings?.is_billing_frozen)
    const quotaRows = [
        { key: 'students', label: 'Students' },
        { key: 'courses', label: 'Courses' },
        { key: 'admins', label: 'Admins' },
    ]

    const featuresMutation = useMutation({
        mutationFn: (next) => tenantAdminService.updateFeatures(next),
        onSuccess: (data) => {
            queryClient.setQueryData(['tenantSettings'], data)
            fetchTenantConfig()
            toast.success('Features updated')
        },
        onError: () => toast.error('Failed to update features'),
    })

    const brandingMutation = useMutation({
        mutationFn: (payload) => tenantAdminService.updateBranding(payload),
        onSuccess: (data) => {
            queryClient.setQueryData(['tenantSettings'], data)
            fetchTenantConfig()
            toast.success('Branding updated')
        },
        onError: () => toast.error('Failed to update branding'),
    })

    const authPanelMutation = useMutation({
        mutationFn: (payload) => tenantAdminService.updateAuthPanel(payload),
        onSuccess: (data) => {
            queryClient.setQueryData(['tenantSettings'], data)
            fetchTenantConfig()
            toast.success('Login screen updated')
        },
        onError: () => toast.error('Failed to update login screen'),
    })

    const logoMutation = useMutation({
        mutationFn: (file) => tenantAdminService.updateLogo(file),
        onSuccess: (data) => {
            queryClient.setQueryData(['tenantSettings'], data)
            fetchTenantConfig()
            toast.success('Logo updated')
        },
        onError: () => toast.error('Failed to upload logo'),
    })

    const faviconMutation = useMutation({
        mutationFn: (file) => tenantAdminService.updateFavicon(file),
        onSuccess: (data) => {
            queryClient.setQueryData(['tenantSettings'], data)
            fetchTenantConfig()
            toast.success('Favicon updated')
        },
        onError: () => toast.error('Failed to upload favicon'),
    })

    const themeMutation = useMutation({
        mutationFn: (theme) => tenantAdminService.updateTheme(theme),
        onSuccess: (data) => {
            queryClient.setQueryData(['tenantSettings'], data)
            fetchTenantConfig()
            toast.success('Theme updated')
        },
        onError: () => {
            // Revert the live preview back to the saved theme on failure.
            applyTheme(settings?.theme || DEFAULT_THEME)
            toast.error('Failed to update theme')
        },
    })

    const activeTheme = settings?.theme || DEFAULT_THEME

    const selectTheme = (key) => {
        if (key === activeTheme || themeMutation.isPending) return
        applyTheme(key) // instant live preview
        themeMutation.mutate(key)
    }

    const showNameMutation = useMutation({
        mutationFn: (showName) => tenantAdminService.updateShowName(showName),
        onSuccess: (data) => {
            queryClient.setQueryData(['tenantSettings'], data)
            fetchTenantConfig()
            toast.success('Logo display updated')
        },
        onError: () => toast.error('Failed to update logo display'),
    })

    // "Logo already includes the name" is the inverse of show_name.
    const logoIncludesName = settings?.show_name === false

    const toggleFeature = (key) => {
        if (lockedFeatures.includes(key)) {
            toast.error('This feature is managed by DailyTaiyari. Contact the DailyTaiyari team to change it.')
            return
        }
        const next = { ...features, [key]: !features[key] }
        setFeatures(next)
        featuresMutation.mutate({ [key]: next[key] })
    }

    const saveBranding = () => {
        const trimmed = name.trim()
        if (!trimmed) {
            toast.error('Name cannot be empty')
            return
        }
        brandingMutation.mutate({ name: trimmed, tagline: tagline.trim() })
    }

    const brandingDirty =
        name.trim() !== (settings?.name || '') || tagline.trim() !== (settings?.tagline || '')

    const updateAuthStat = (index, field, value) => {
        setAuthPanel((prev) => {
            const stats = prev.stats.map((s, i) => (i === index ? { ...s, [field]: value } : s))
            return { ...prev, stats }
        })
    }

    const addAuthStat = () => {
        setAuthPanel((prev) => {
            if (prev.stats.length >= 4) return prev
            return { ...prev, stats: [...prev.stats, { value: '', label: '' }] }
        })
    }

    const removeAuthStat = (index) => {
        setAuthPanel((prev) => ({ ...prev, stats: prev.stats.filter((_, i) => i !== index) }))
    }

    const saveAuthPanel = () => {
        authPanelMutation.mutate({
            heading: authPanel.heading.trim(),
            heading_highlight: authPanel.heading_highlight.trim(),
            subtitle: authPanel.subtitle.trim(),
            stats: authPanel.stats
                .map((s) => ({ value: (s.value || '').trim(), label: (s.label || '').trim() }))
                .filter((s) => s.value || s.label),
        })
    }

    const handleLogoChange = (e) => {
        const file = e.target.files?.[0]
        if (!file) return
        if (!file.type.startsWith('image/')) {
            toast.error('Please choose an image file')
            return
        }
        logoMutation.mutate(file)
        e.target.value = ''
    }

    const handleFaviconChange = (e) => {
        const file = e.target.files?.[0]
        if (!file) return
        if (!file.type.startsWith('image/')) {
            toast.error('Please choose an image file')
            return
        }
        faviconMutation.mutate(file)
        e.target.value = ''
    }

    if (isLoading) {
        return (
            <div className="flex items-center justify-center min-h-[240px]">
                <Loader2 className="w-8 h-8 animate-spin text-primary-500" />
            </div>
        )
    }

    return (
        <div className="space-y-6">
            {/* Settings sub-tabs — General vs. Payments */}
            <div className="flex items-center gap-2 border-b border-surface-200 dark:border-surface-800">
                {[
                    { id: 'general', label: 'General', icon: SlidersIcon },
                    { id: 'payments', label: 'Payments', icon: CreditCard },
                    { id: 'email', label: 'Email & Notifications', icon: Mail },
                ].map((st) => {
                    const active = subTab === st.id
                    return (
                        <button
                            key={st.id}
                            onClick={() => setSubTab(st.id)}
                            className={`inline-flex items-center gap-2 px-4 py-2.5 text-sm font-semibold border-b-2 -mb-px transition-colors ${active
                                ? 'border-primary-500 text-primary-600 dark:text-primary-400'
                                : 'border-transparent text-surface-500 hover:text-surface-800 dark:hover:text-surface-200'}`}
                        >
                            <st.icon className="w-4 h-4" /> {st.label}
                        </button>
                    )
                })}
            </div>

            {subTab === 'payments' ? (
                <PaymentSettings settings={settings} />
            ) : subTab === 'email' ? (
                <EmailSettings settings={settings} />
            ) : (
            <div className="space-y-6">
            {/* Identity — name + tagline */}
            <div className="card p-6 space-y-4">
                <div className="flex items-center gap-2">
                    <ImageIcon className="w-5 h-5 text-primary-500" />
                    <h3 className="text-lg font-bold text-surface-900 dark:text-white">Institution Details</h3>
                </div>
                <p className="text-sm text-surface-500">Your institution's name and tagline appear in the sidebar, login screens and browser tab for all your students.</p>
                <div className="grid gap-4 sm:grid-cols-2">
                    <div>
                        <label className="block text-sm font-medium text-surface-700 dark:text-surface-300 mb-1.5">Name</label>
                        <input
                            type="text"
                            value={name}
                            onChange={(e) => setName(e.target.value)}
                            maxLength={255}
                            placeholder="e.g. Test Academy"
                            className="w-full px-3.5 py-2.5 rounded-xl border border-surface-200 dark:border-surface-700 bg-white dark:bg-surface-900 text-surface-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                        />
                    </div>
                    <div>
                        <label className="block text-sm font-medium text-surface-700 dark:text-surface-300 mb-1.5">Tagline</label>
                        <input
                            type="text"
                            value={tagline}
                            onChange={(e) => setTagline(e.target.value)}
                            maxLength={255}
                            placeholder="e.g. Ace Your Exams"
                            className="w-full px-3.5 py-2.5 rounded-xl border border-surface-200 dark:border-surface-700 bg-white dark:bg-surface-900 text-surface-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                        />
                    </div>
                </div>
                <div className="flex justify-end">
                    <button
                        onClick={saveBranding}
                        disabled={brandingMutation.isPending || !brandingDirty}
                        className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-primary-500 hover:bg-primary-600 text-white text-sm font-semibold transition-colors disabled:opacity-60"
                    >
                        {brandingMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                        Save Changes
                    </button>
                </div>
            </div>

            {/* Login screen panel — heading, subtitle & stats */}
            <div className="card p-6 space-y-4">
                <div className="flex items-center gap-2">
                    <ImageIcon className="w-5 h-5 text-primary-500" />
                    <h3 className="text-lg font-bold text-surface-900 dark:text-white">Login Screen</h3>
                </div>
                <p className="text-sm text-surface-500">Customise the welcome panel students see on the login and register pages. Leave any field blank to use the default text.</p>
                <div className="grid gap-4 sm:grid-cols-2">
                    <div>
                        <label className="block text-sm font-medium text-surface-700 dark:text-surface-300 mb-1.5">Heading</label>
                        <input
                            type="text"
                            value={authPanel.heading}
                            onChange={(e) => setAuthPanel((p) => ({ ...p, heading: e.target.value }))}
                            maxLength={255}
                            placeholder={DEFAULT_AUTH_PANEL.heading}
                            className="w-full px-3.5 py-2.5 rounded-xl border border-surface-200 dark:border-surface-700 bg-white dark:bg-surface-900 text-surface-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                        />
                    </div>
                    <div>
                        <label className="block text-sm font-medium text-surface-700 dark:text-surface-300 mb-1.5">Highlighted heading</label>
                        <input
                            type="text"
                            value={authPanel.heading_highlight}
                            onChange={(e) => setAuthPanel((p) => ({ ...p, heading_highlight: e.target.value }))}
                            maxLength={255}
                            placeholder={DEFAULT_AUTH_PANEL.heading_highlight}
                            className="w-full px-3.5 py-2.5 rounded-xl border border-surface-200 dark:border-surface-700 bg-white dark:bg-surface-900 text-surface-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                        />
                    </div>
                </div>
                <div>
                    <label className="block text-sm font-medium text-surface-700 dark:text-surface-300 mb-1.5">Subtitle</label>
                    <textarea
                        value={authPanel.subtitle}
                        onChange={(e) => setAuthPanel((p) => ({ ...p, subtitle: e.target.value }))}
                        maxLength={255}
                        rows={2}
                        placeholder={DEFAULT_AUTH_PANEL.subtitle}
                        className="w-full px-3.5 py-2.5 rounded-xl border border-surface-200 dark:border-surface-700 bg-white dark:bg-surface-900 text-surface-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                    />
                </div>
                <div className="space-y-3">
                    <div className="flex items-center justify-between">
                        <label className="block text-sm font-medium text-surface-700 dark:text-surface-300">Highlight stats <span className="text-surface-400 font-normal">(optional, up to 4)</span></label>
                        {authPanel.stats.length < 4 && (
                            <button
                                type="button"
                                onClick={addAuthStat}
                                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-semibold text-primary-600 dark:text-primary-400 hover:bg-primary-50 dark:hover:bg-primary-500/10 transition-colors"
                            >
                                <Plus className="w-4 h-4" /> Add stat
                            </button>
                        )}
                    </div>
                    {authPanel.stats.length === 0 && (
                        <p className="text-sm text-surface-400">No stats shown. Add a few (e.g. “10,000+ Students”) to display them on the login screen.</p>
                    )}
                    {authPanel.stats.map((stat, i) => (
                        <div key={i} className="flex items-center gap-2">
                            <input
                                type="text"
                                value={stat.value}
                                onChange={(e) => updateAuthStat(i, 'value', e.target.value)}
                                maxLength={32}
                                placeholder="10,000+"
                                className="w-32 px-3 py-2 rounded-xl border border-surface-200 dark:border-surface-700 bg-white dark:bg-surface-900 text-surface-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                            />
                            <input
                                type="text"
                                value={stat.label}
                                onChange={(e) => updateAuthStat(i, 'label', e.target.value)}
                                maxLength={48}
                                placeholder="Students"
                                className="flex-1 px-3 py-2 rounded-xl border border-surface-200 dark:border-surface-700 bg-white dark:bg-surface-900 text-surface-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                            />
                            <button
                                type="button"
                                onClick={() => removeAuthStat(i)}
                                className="p-2 rounded-lg text-surface-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-500/10 transition-colors"
                                aria-label="Remove stat"
                            >
                                <Trash2 className="w-4 h-4" />
                            </button>
                        </div>
                    ))}
                </div>
                <div className="flex justify-end">
                    <button
                        onClick={saveAuthPanel}
                        disabled={authPanelMutation.isPending}
                        className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-primary-500 hover:bg-primary-600 text-white text-sm font-semibold transition-colors disabled:opacity-60"
                    >
                        {authPanelMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                        Save Changes
                    </button>
                </div>
            </div>

            {/* Logo */}
            <div className="card p-6 space-y-4">
                <div className="flex items-center gap-2">
                    <ImageIcon className="w-5 h-5 text-primary-500" />
                    <h3 className="text-lg font-bold text-surface-900 dark:text-white">Logo</h3>
                </div>
                <p className="text-sm text-surface-500">Upload your institution's logo. It appears in the sidebar and login screens for all your students.</p>
                <div className="flex items-center gap-5">
                    <div className="w-20 h-20 rounded-2xl overflow-hidden flex items-center justify-center bg-surface-100 dark:bg-surface-800 border border-surface-200 dark:border-surface-700">
                        {settings?.logo ? (
                            <img src={settings.logo} alt="Logo" className="w-full h-full object-contain" />
                        ) : (
                            <span className="text-2xl font-bold text-surface-400">
                                {(settings?.name || 'DT').slice(0, 2).toUpperCase()}
                            </span>
                        )}
                    </div>
                    <div>
                        <input ref={fileInputRef} type="file" accept="image/*" onChange={handleLogoChange} className="hidden" />
                        <button
                            onClick={() => fileInputRef.current?.click()}
                            disabled={logoMutation.isPending}
                            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-primary-500 hover:bg-primary-600 text-white text-sm font-semibold transition-colors disabled:opacity-60"
                        >
                            {logoMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
                            {settings?.logo ? 'Change Logo' : 'Upload Logo'}
                        </button>
                        <p className="text-xs text-surface-400 mt-2">PNG, JPG or SVG. Square images look best.</p>
                    </div>
                </div>
                {/* Logo-includes-name toggle */}
                <div className="flex items-center justify-between gap-4 pt-4 border-t border-surface-100 dark:border-surface-800">
                    <div className="min-w-0">
                        <p className="font-medium text-surface-800 dark:text-surface-200">My logo already includes the name</p>
                        <p className="text-sm text-surface-500">Hides the separate text name and shows your logo full-width, with the tagline below it.</p>
                    </div>
                    <button
                        role="switch"
                        aria-checked={logoIncludesName}
                        onClick={() => showNameMutation.mutate(logoIncludesName)}
                        disabled={showNameMutation.isPending || !settings?.logo}
                        title={!settings?.logo ? 'Upload a logo first' : undefined}
                        className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors disabled:opacity-50 ${logoIncludesName ? 'bg-primary-500' : 'bg-surface-300 dark:bg-surface-700'}`}
                    >
                        <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${logoIncludesName ? 'translate-x-6' : 'translate-x-1'}`} />
                    </button>
                </div>
            </div>

            {/* Favicon */}
            <div className="card p-6 space-y-4">
                <div className="flex items-center gap-2">
                    <ImageIcon className="w-5 h-5 text-primary-500" />
                    <h3 className="text-lg font-bold text-surface-900 dark:text-white">Favicon</h3>
                </div>
                <p className="text-sm text-surface-500">The small icon shown in the browser tab. A square image works best.</p>
                <div className="flex items-center gap-5">
                    <div className="w-16 h-16 rounded-xl overflow-hidden flex items-center justify-center bg-surface-100 dark:bg-surface-800 border border-surface-200 dark:border-surface-700">
                        {settings?.favicon ? (
                            <img src={settings.favicon} alt="Favicon" className="w-full h-full object-contain" />
                        ) : (
                            <span className="text-xl font-bold text-surface-400">
                                {(settings?.name || 'DT').slice(0, 1).toUpperCase()}
                            </span>
                        )}
                    </div>
                    <div>
                        <input ref={faviconInputRef} type="file" accept="image/*" onChange={handleFaviconChange} className="hidden" />
                        <button
                            onClick={() => faviconInputRef.current?.click()}
                            disabled={faviconMutation.isPending}
                            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-primary-500 hover:bg-primary-600 text-white text-sm font-semibold transition-colors disabled:opacity-60"
                        >
                            {faviconMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
                            {settings?.favicon ? 'Change Favicon' : 'Upload Favicon'}
                        </button>
                        <p className="text-xs text-surface-400 mt-2">PNG, ICO or SVG. 32×32 or larger.</p>
                    </div>
                </div>
            </div>

            {/* Theme */}
            <div className="card p-6 space-y-4">
                <div className="flex items-center gap-2">
                    <Palette className="w-5 h-5 text-primary-500" />
                    <h3 className="text-lg font-bold text-surface-900 dark:text-white">Theme</h3>
                </div>
                <p className="text-sm text-surface-500">Pick a colour theme for your institution. It applies across the whole student app instantly.</p>
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                    {THEME_LIST.map((t) => {
                        const selected = t.key === activeTheme
                        return (
                            <button
                                key={t.key}
                                onClick={() => selectTheme(t.key)}
                                disabled={themeMutation.isPending}
                                className={`relative text-left rounded-2xl border p-4 transition-all disabled:opacity-60 ${
                                    selected
                                        ? 'border-primary-500 ring-2 ring-primary-500/40 bg-primary-50/50 dark:bg-primary-900/20'
                                        : 'border-surface-200 dark:border-surface-700 hover:border-primary-300 dark:hover:border-primary-700'
                                }`}
                            >
                                {selected && (
                                    <span className="absolute top-3 right-3 inline-flex items-center justify-center w-5 h-5 rounded-full bg-primary-500 text-white">
                                        <Check className="w-3.5 h-3.5" />
                                    </span>
                                )}
                                <div className="flex items-center gap-2 mb-2">
                                    <span className="w-8 h-8 rounded-lg shadow-sm" style={{ background: `linear-gradient(135deg, ${t.swatch[0]} 0%, ${t.swatch[0]} 55%, ${t.swatch[1]} 55%, ${t.swatch[1]} 100%)` }} />
                                    <span className="font-semibold text-surface-900 dark:text-white">{t.label}</span>
                                </div>
                                <p className="text-xs text-surface-500 leading-snug">{t.description}</p>
                            </button>
                        )
                    })}
                </div>
            </div>

            {/* Plan & usage */}
            <div className="card p-6 space-y-4">
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                        <CreditCard className="w-5 h-5 text-primary-500" />
                        <h3 className="text-lg font-bold text-surface-900 dark:text-white">Plan &amp; Usage</h3>
                    </div>
                    {planLabel && (
                        <span className="text-xs font-semibold px-3 py-1 rounded-full bg-primary-50 text-primary-700 dark:bg-primary-500/10 dark:text-primary-300">
                            {planLabel}
                        </span>
                    )}
                </div>
                {isBillingFrozen && (
                    <div className="rounded-lg bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/30 px-4 py-3 text-sm text-red-700 dark:text-red-300">
                        Your subscription is inactive. Please contact the DailyTaiyari team to restore full access.
                    </div>
                )}
                <p className="text-sm text-surface-500">Your usage against the limits set by the DailyTaiyari team. Contact us to raise a limit or change your plan.</p>
                <div className="space-y-3">
                    {quotaRows.map(({ key, label }) => {
                        const s = quotaStatus[key] || { used: 0, limit: null }
                        const unlimited = s.limit === null || s.limit === undefined
                        const pct = unlimited || s.limit === 0 ? 0 : Math.min((s.used / s.limit) * 100, 100)
                        const over = !unlimited && s.used >= s.limit
                        const near = !over && pct >= 80
                        const barColor = over ? 'bg-red-500' : near ? 'bg-amber-500' : 'bg-primary-500'
                        return (
                            <div key={key}>
                                <div className="flex items-center justify-between text-sm mb-1">
                                    <span className="text-surface-600 dark:text-surface-300">{label}</span>
                                    <span className={`font-medium ${over ? 'text-red-600 dark:text-red-400' : 'text-surface-700 dark:text-surface-200'}`}>
                                        {s.used}{unlimited ? ' / ∞' : ` / ${s.limit}`}
                                    </span>
                                </div>
                                <div className="h-1.5 rounded-full bg-surface-100 dark:bg-surface-800 overflow-hidden">
                                    <div className={`h-full rounded-full ${barColor}`} style={{ width: `${pct}%` }} />
                                </div>
                                {over && (
                                    <p className="text-xs text-red-600 dark:text-red-400 mt-1">
                                        Limit reached — contact the DailyTaiyari team to add more.
                                    </p>
                                )}
                            </div>
                        )
                    })}
                </div>
            </div>

            {/* Feature toggles */}
            <div className="card p-6 space-y-4">
                <div className="flex items-center gap-2">
                    <SlidersIcon className="w-5 h-5 text-primary-500" />
                    <h3 className="text-lg font-bold text-surface-900 dark:text-white">Features</h3>
                </div>
                <p className="text-sm text-surface-500">Show or hide modules for your students. Disabled features are removed from navigation and blocked entirely.</p>
                <div className="divide-y divide-surface-100 dark:divide-surface-800">
                    {availableFeatures.map((f) => {
                        const enabled = Boolean(features[f.key])
                        const locked = lockedFeatures.includes(f.key)
                        return (
                            <div key={f.key} className="flex items-center justify-between py-3">
                                <div className="min-w-0">
                                    <div className="flex items-center gap-1.5">
                                        <span className="font-medium text-surface-800 dark:text-surface-200">{f.label}</span>
                                        {locked && <LockIcon className="w-3.5 h-3.5 text-amber-500 shrink-0" />}
                                    </div>
                                    {locked && (
                                        <p className="text-xs text-amber-600 dark:text-amber-400 mt-0.5">
                                            Managed by DailyTaiyari — contact the DailyTaiyari team to change this.
                                        </p>
                                    )}
                                </div>
                                <button
                                    role="switch"
                                    aria-checked={enabled}
                                    onClick={() => toggleFeature(f.key)}
                                    disabled={featuresMutation.isPending || locked}
                                    title={locked ? 'Locked by DailyTaiyari' : undefined}
                                    className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors disabled:opacity-60 disabled:cursor-not-allowed ${enabled ? 'bg-primary-500' : 'bg-surface-300 dark:bg-surface-700'}`}
                                >
                                    <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${enabled ? 'translate-x-6' : 'translate-x-1'}`} />
                                </button>
                            </div>
                        )
                    })}
                </div>
            </div>
            </div>
            )}
        </div>
    )
}

/* ---------------------------------------------------------------------------
 * PaymentSettings — enrollment mode flags + payment gateway credentials
 * ------------------------------------------------------------------------- */
const PROVIDERS = [
    { id: 'razorpay', label: 'Razorpay', idLabel: 'Key ID', secretLabel: 'Key Secret', idHint: 'rzp_live_… / rzp_test_…' },
    { id: 'cashfree', label: 'Cashfree', idLabel: 'App ID (Client ID)', secretLabel: 'Secret Key', idHint: 'CF App ID' },
    { id: 'payu', label: 'PayU', idLabel: 'Merchant Key', secretLabel: 'Merchant Salt', idHint: 'PayU merchant key' },
]

const PaymentSettings = ({ settings }) => {
    const queryClient = useQueryClient()
    const fetchTenantConfig = useTenantStore((s) => s.fetchTenantConfig)

    const { data: gatewayData, isLoading } = useQuery({
        queryKey: ['tenantPaymentGateway'],
        queryFn: () => tenantAdminService.getPaymentGateway(),
    })

    // One stored config per provider; exactly one is active (the live gateway).
    const gateways = gatewayData?.gateways || []
    const activeProvider = gatewayData?.active_provider || null
    const byProvider = useMemo(
        () => Object.fromEntries(gateways.map((g) => [g.provider, g])),
        [gateways],
    )

    const [provider, setProvider] = useState('razorpay')
    const [keyId, setKeyId] = useState('')
    const [keySecret, setKeySecret] = useState('')
    const [webhookSecret, setWebhookSecret] = useState('')
    const [isActive, setIsActive] = useState(false)
    const [isTestMode, setIsTestMode] = useState(true)

    // On first load, focus the live gateway's tab (falling back to Razorpay).
    const [pickedInitial, setPickedInitial] = useState(false)
    useEffect(() => {
        if (!pickedInitial && gatewayData) {
            setProvider(activeProvider || gateways[0]?.provider || 'razorpay')
            setPickedInitial(true)
        }
    }, [gatewayData, activeProvider, gateways, pickedInitial])

    // Load the selected provider's stored config into the form.
    const current = byProvider[provider]
    useEffect(() => {
        const g = byProvider[provider]
        setKeyId(g?.key_id || '')
        setIsActive(Boolean(g?.is_active))
        setIsTestMode(g ? Boolean(g.is_test_mode) : true)
        setKeySecret('')
        setWebhookSecret('')
    }, [provider, byProvider])

    const isConfigured = Boolean(current)
    const hasStoredSecret = Boolean(current?.has_secret)
    const hasStoredWebhookSecret = Boolean(current?.has_webhook_secret)
    const providerMeta = PROVIDERS.find((p) => p.id === provider) || PROVIDERS[0]
    const activeMeta = activeProvider ? PROVIDERS.find((p) => p.id === activeProvider) : null
    const activeIsTest = activeProvider ? Boolean(byProvider[activeProvider]?.is_test_mode) : false

    // URL the admin registers in their provider dashboard. PayU uses a signed
    // browser+S2S callback (surl/furl); the others use a JSON webhook endpoint.
    const apiBase = import.meta.env.VITE_API_URL || `${window.location.origin}/api/v1`
    const cleanBase = apiBase.replace(/\/$/, '')
    const webhookUrl = provider === 'payu'
        ? `${cleanBase}/payments/payu/callback/`
        : `${cleanBase}/payments/webhook/${provider}/`

    // Enrollment flags live on the tenant settings object.
    const [enrollFree, setEnrollFree] = useState(true)
    const [enrollPaid, setEnrollPaid] = useState(true)
    useEffect(() => {
        if (settings) {
            setEnrollFree(settings.request_enrollment_free !== false)
            setEnrollPaid(settings.request_enrollment_paid !== false)
        }
    }, [settings])

    const hasActiveGateway = Boolean(settings?.has_active_payment_gateway)

    const enrollMutation = useMutation({
        mutationFn: (payload) => tenantAdminService.updateEnrollmentSettings(payload),
        onSuccess: (data) => {
            queryClient.setQueryData(['tenantSettings'], data)
            toast.success('Enrollment settings updated')
        },
        onError: (err) => {
            // Revert optimistic toggle and surface the server-side reason.
            setEnrollPaid(settings?.request_enrollment_paid !== false)
            setEnrollFree(settings?.request_enrollment_free !== false)
            const detail = err?.response?.data?.request_enrollment_paid
            toast.error(Array.isArray(detail) ? detail[0] : (detail || 'Failed to update enrollment settings'))
        },
    })

    const toggleEnrollFree = () => {
        const next = !enrollFree
        setEnrollFree(next)
        enrollMutation.mutate({ request_enrollment_free: next })
    }

    const toggleEnrollPaid = () => {
        const next = !enrollPaid
        if (next === false && !hasActiveGateway) {
            toast.error('Set up and activate a payment gateway before enabling self-enrolment for paid courses.')
            return
        }
        setEnrollPaid(next)
        enrollMutation.mutate({ request_enrollment_paid: next })
    }

    const saveMutation = useMutation({
        mutationFn: (payload) => tenantAdminService.savePaymentGateway(payload),
        onSuccess: (data) => {
            queryClient.setQueryData(['tenantPaymentGateway'], data)
            queryClient.invalidateQueries({ queryKey: ['tenantSettings'] })
            fetchTenantConfig()
            toast.success('Payment gateway saved')
        },
        onError: (err) => {
            const data = err?.response?.data
            const msg = data?.non_field_errors?.[0] || data?.detail || 'Failed to save payment gateway'
            toast.error(msg)
        },
    })

    const deleteMutation = useMutation({
        mutationFn: (prov) => tenantAdminService.deletePaymentGateway(prov),
        onSuccess: (data) => {
            queryClient.setQueryData(['tenantPaymentGateway'], data)
            queryClient.invalidateQueries({ queryKey: ['tenantSettings'] })
            fetchTenantConfig()
            setKeyId(''); setKeySecret(''); setWebhookSecret(''); setIsActive(false); setIsTestMode(true)
            toast.success('Credentials cleared')
        },
        onError: () => toast.error('Failed to clear credentials'),
    })

    const save = () => {
        if (!keyId.trim()) {
            toast.error(`${providerMeta.idLabel} is required`)
            return
        }
        if (!hasStoredSecret && !keySecret.trim()) {
            toast.error(`${providerMeta.secretLabel} is required`)
            return
        }
        const payload = {
            provider,
            key_id: keyId.trim(),
            is_active: isActive,
            is_test_mode: isTestMode,
        }
        // Only send secrets when the admin typed a new value.
        if (keySecret.trim()) payload.key_secret = keySecret.trim()
        if (webhookSecret.trim()) payload.webhook_secret = webhookSecret.trim()
        saveMutation.mutate(payload)
    }

    if (isLoading) {
        return (
            <div className="flex items-center justify-center min-h-[200px]">
                <Loader2 className="w-8 h-8 animate-spin text-primary-500" />
            </div>
        )
    }

    return (
        <div className="space-y-6">
            {/* Enrollment mode */}
            <div className="card p-6 space-y-4">
                <div className="flex items-center gap-2">
                    <GraduationCap className="w-5 h-5 text-primary-500" />
                    <h3 className="text-lg font-bold text-surface-900 dark:text-white">Enrollment Mode</h3>
                </div>
                <p className="text-sm text-surface-500">
                    Choose how students join your courses. When request-based enrolment is on, students
                    send a request that you approve. When off, free courses allow instant self-enrolment and
                    paid courses enrol after online payment (requires an active payment gateway below).
                </p>
                <div className="divide-y divide-surface-100 dark:divide-surface-800">
                    <div className="flex items-center justify-between py-3 gap-4">
                        <div>
                            <p className="font-medium text-surface-800 dark:text-surface-200">Request enrollment in free courses</p>
                            <p className="text-xs text-surface-500">On: students request &amp; you approve. Off: instant self-enrolment.</p>
                        </div>
                        <button
                            role="switch"
                            aria-checked={enrollFree}
                            onClick={toggleEnrollFree}
                            disabled={enrollMutation.isPending}
                            className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors disabled:opacity-60 ${enrollFree ? 'bg-primary-500' : 'bg-surface-300 dark:bg-surface-700'}`}
                        >
                            <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${enrollFree ? 'translate-x-6' : 'translate-x-1'}`} />
                        </button>
                    </div>
                    <div className="flex items-center justify-between py-3 gap-4">
                        <div>
                            <p className="font-medium text-surface-800 dark:text-surface-200">Request enrollment in paid courses</p>
                            <p className="text-xs text-surface-500">
                                On: students request &amp; you approve. Off: enrol after online payment.
                                {!hasActiveGateway && (
                                    <span className="text-amber-600 dark:text-amber-400"> Requires an active payment gateway to turn off.</span>
                                )}
                            </p>
                        </div>
                        <button
                            role="switch"
                            aria-checked={enrollPaid}
                            onClick={toggleEnrollPaid}
                            disabled={enrollMutation.isPending || (enrollPaid && !hasActiveGateway)}
                            title={!hasActiveGateway ? 'Configure an active payment gateway first' : undefined}
                            className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors disabled:opacity-60 ${enrollPaid ? 'bg-primary-500' : 'bg-surface-300 dark:bg-surface-700'}`}
                        >
                            <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${enrollPaid ? 'translate-x-6' : 'translate-x-1'}`} />
                        </button>
                    </div>
                </div>
            </div>

            {/* Payment gateway credentials */}
            <div className="card p-6 space-y-5">
                <div className="flex items-center gap-2 flex-wrap">
                    <CreditCard className="w-5 h-5 text-primary-500" />
                    <h3 className="text-lg font-bold text-surface-900 dark:text-white">Payment Gateways</h3>
                </div>

                {/* Live-gateway status: which provider is used for checkout right now. */}
                {activeProvider ? (
                    <div className="flex items-center gap-2 rounded-xl border border-emerald-200 dark:border-emerald-800/60 bg-emerald-50 dark:bg-emerald-900/20 px-4 py-3">
                        <ShieldCheck className="w-4 h-4 text-emerald-600 dark:text-emerald-400 shrink-0" />
                        <span className="text-sm text-emerald-800 dark:text-emerald-300">
                            <span className="font-semibold">{activeMeta?.label || activeProvider}</span> is live and used for checkout
                            <span className={`ml-2 inline-flex items-center px-1.5 py-0.5 rounded text-[11px] font-semibold ${activeIsTest ? 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300' : 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300'}`}>
                                {activeIsTest ? 'Test / sandbox' : 'Live'}
                            </span>
                        </span>
                    </div>
                ) : (
                    <div className="flex items-center gap-2 rounded-xl border border-surface-200 dark:border-surface-700 bg-surface-50 dark:bg-surface-900/40 px-4 py-3">
                        <ShieldCheck className="w-4 h-4 text-surface-400 shrink-0" />
                        <span className="text-sm text-surface-500">
                            No gateway is live yet. Configure a provider below and tick “Active” to start collecting payments.
                        </span>
                    </div>
                )}

                <p className="text-sm text-surface-500">
                    Store credentials for any of the providers below — Razorpay, Cashfree or PayU. Only the
                    one you mark <span className="font-medium">Active</span> is used for checkout; activating a
                    provider automatically switches the others off. Credentials are encrypted at rest and never
                    shown again after saving.
                </p>

                {/* Provider picker — badge shows which providers are saved / live. */}
                <div className="flex flex-wrap gap-3">
                    {PROVIDERS.map((p) => {
                        const selected = provider === p.id
                        const stored = byProvider[p.id]
                        const isLive = activeProvider === p.id
                        return (
                            <button
                                key={p.id}
                                onClick={() => { setProvider(p.id); setKeySecret(''); setWebhookSecret('') }}
                                className={`relative px-4 py-2.5 rounded-xl border text-sm font-semibold transition-colors ${selected
                                    ? 'border-primary-500 bg-primary-50 text-primary-700 dark:bg-primary-900/30 dark:text-primary-300'
                                    : 'border-surface-200 dark:border-surface-700 text-surface-600 dark:text-surface-300 hover:border-surface-300'}`}
                            >
                                {p.label}
                                {isLive ? (
                                    <span className="ml-2 inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300">
                                        LIVE
                                    </span>
                                ) : stored ? (
                                    <span className="ml-2 inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold bg-surface-100 text-surface-500 dark:bg-surface-800 dark:text-surface-400">
                                        SAVED
                                    </span>
                                ) : null}
                            </button>
                        )
                    })}
                </div>

                <div className="grid gap-4 sm:grid-cols-2">
                    <div>
                        <label className="block text-sm font-medium text-surface-700 dark:text-surface-300 mb-1.5">{providerMeta.idLabel}</label>
                        <input
                            type="text"
                            value={keyId}
                            onChange={(e) => setKeyId(e.target.value)}
                            placeholder={providerMeta.idHint}
                            autoComplete="off"
                            className="w-full px-3.5 py-2.5 rounded-xl border border-surface-200 dark:border-surface-700 bg-white dark:bg-surface-900 text-surface-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                        />
                    </div>
                    <div>
                        <label className="block text-sm font-medium text-surface-700 dark:text-surface-300 mb-1.5">
                            {providerMeta.secretLabel}
                        </label>
                        <div className="relative">
                            <KeyRound className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-surface-400" />
                            <input
                                type="password"
                                value={keySecret}
                                onChange={(e) => setKeySecret(e.target.value)}
                                placeholder={hasStoredSecret ? '•••••••• (leave blank to keep)' : 'Enter secret'}
                                autoComplete="new-password"
                                className="w-full pl-9 pr-3.5 py-2.5 rounded-xl border border-surface-200 dark:border-surface-700 bg-white dark:bg-surface-900 text-surface-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                            />
                        </div>
                    </div>
                </div>

                {/* Webhook */}
                <div className="rounded-xl border border-surface-200 dark:border-surface-700 p-4 space-y-3 bg-surface-50/60 dark:bg-surface-900/40">
                    <div className="flex items-center gap-2">
                        <ShieldCheck className="w-4 h-4 text-primary-500" />
                        <span className="text-sm font-semibold text-surface-800 dark:text-surface-200">
                            {provider === 'payu' ? 'Success / Failure URL' : 'Webhook'}
                        </span>
                    </div>
                    <p className="text-xs text-surface-500">
                        {provider === 'payu'
                            ? `Whitelist this Success/Failure (surl/furl) URL in your PayU dashboard. PayU also posts its server-to-server verification here — everything is signed with your Merchant Salt, so no extra secret is needed.`
                            : `Add this URL as a webhook in your ${providerMeta.label} dashboard so payments are confirmed reliably even if the learner closes the tab.`}
                    </p>
                    <div className="flex items-center gap-2">
                        <code className="flex-1 text-xs px-3 py-2 rounded-lg bg-surface-100 dark:bg-surface-800 text-surface-700 dark:text-surface-300 break-all">{webhookUrl}</code>
                        <button
                            type="button"
                            onClick={() => { navigator.clipboard?.writeText(webhookUrl); toast.success('URL copied') }}
                            className="shrink-0 px-3 py-2 rounded-lg text-xs font-semibold bg-surface-100 dark:bg-surface-800 hover:bg-surface-200 dark:hover:bg-surface-700 text-surface-600 dark:text-surface-300"
                        >
                            Copy
                        </button>
                    </div>
                    {provider !== 'payu' && (
                        <div>
                            <label className="block text-sm font-medium text-surface-700 dark:text-surface-300 mb-1.5">
                                Webhook secret {provider === 'cashfree' && <span className="text-surface-400 font-normal">(optional — defaults to your secret key)</span>}
                            </label>
                            <div className="relative">
                                <KeyRound className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-surface-400" />
                                <input
                                    type="password"
                                    value={webhookSecret}
                                    onChange={(e) => setWebhookSecret(e.target.value)}
                                    placeholder={hasStoredWebhookSecret ? '•••••••• (leave blank to keep)' : (provider === 'razorpay' ? 'Razorpay webhook secret' : 'Leave blank to use secret key')}
                                    autoComplete="new-password"
                                    className="w-full pl-9 pr-3.5 py-2.5 rounded-xl border border-surface-200 dark:border-surface-700 bg-white dark:bg-surface-900 text-surface-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                                />
                            </div>
                        </div>
                    )}
                </div>

                <div className="flex flex-col sm:flex-row sm:items-center gap-4">
                    <label className="inline-flex items-center gap-2 cursor-pointer">
                        <input type="checkbox" checked={isTestMode} onChange={(e) => setIsTestMode(e.target.checked)} className="rounded border-surface-300 text-primary-500 focus:ring-primary-500" />
                        <span className="text-sm text-surface-700 dark:text-surface-300">Test / sandbox mode</span>
                    </label>
                    <label className="inline-flex items-center gap-2 cursor-pointer">
                        <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} className="rounded border-surface-300 text-primary-500 focus:ring-primary-500" />
                        <span className="text-sm text-surface-700 dark:text-surface-300">Active — make {providerMeta.label} the live gateway (switches others off)</span>
                    </label>
                </div>

                <div className="flex items-center gap-3 pt-1">
                    <button
                        onClick={save}
                        disabled={saveMutation.isPending}
                        className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-primary-500 hover:bg-primary-600 text-white text-sm font-semibold disabled:opacity-60"
                    >
                        {saveMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                        {isConfigured ? `Update ${providerMeta.label}` : `Save ${providerMeta.label}`}
                    </button>
                    {isConfigured && (
                        <button
                            onClick={() => { if (window.confirm(`Clear the stored ${providerMeta.label} credentials?`)) deleteMutation.mutate(provider) }}
                            disabled={deleteMutation.isPending}
                            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-rose-50 hover:bg-rose-100 text-rose-600 dark:bg-rose-900/30 dark:text-rose-400 text-sm font-semibold disabled:opacity-60"
                        >
                            {deleteMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4" />}
                            Clear {providerMeta.label} credentials
                        </button>
                    )}
                </div>
            </div>
        </div>
    )
}

/* ---------------------------------------------------------------------------
 * AdminDashboard (root)
 * ------------------------------------------------------------------------- */
const TABS = [
    { id: 'overview', label: 'Overview', icon: TrendingUp, subtitle: 'Track key metrics and institutional performance at a glance' },
    { id: 'students', label: 'Student Records', icon: Users, subtitle: 'Search, view and manage every student on your platform' },
    { id: 'enrollments', label: 'Enrollments', icon: GraduationCap, subtitle: 'Review and approve student enrollment requests' },
    { id: 'sales', label: 'Sales & Orders', icon: ShoppingCart, subtitle: 'Monitor payments, orders and revenue' },
    { id: 'marketing', label: 'Marketing & Promotions', icon: Megaphone, subtitle: 'Run promotions and grow your reach' },
    { id: 'announcements', label: 'Announcements', icon: Megaphone, subtitle: 'Broadcast updates to everyone or to specific courses via in-app notifications and branded email' },
    { id: 'performance', label: 'Reports', icon: BarChart3, subtitle: 'Generate and export detailed performance reports' },
    { id: 'content', label: 'Course Builder', icon: Library, subtitle: 'Create and organise your courses and content' },
    { id: 'ai-studio', label: 'AI Course Studio', icon: Wand2, subtitle: 'Draft courses, outlines and study material with AI — you review and approve everything before it is saved' },
    { id: 'landing', label: 'Landing Page', icon: LayoutTemplate, subtitle: 'Design your public landing page' },
    { id: 'ai', label: 'AI Features', icon: Sparkles, subtitle: 'Connect your AI provider, tune the assistant and track usage & cost' },
    { id: 'settings', label: 'Settings', icon: SlidersIcon, subtitle: 'Manage branding, payments, email and platform settings' },
]

const AdminDashboard = () => {
    const [searchParams] = useSearchParams()
    const activeTab = searchParams.get('tab') || 'overview'
    const queryClient = useQueryClient()

    const activeMeta = TABS.find((t) => t.id === activeTab) || TABS[0]

    const [growthRange, setGrowthRange] = useState(30)

    const { data: stats, isLoading, error, isFetching } = useQuery({
        queryKey: ['tenantAdminStats', growthRange],
        queryFn: () => analyticsService.getTenantAdminStats(growthRange),
        refetchInterval: 60000,
        keepPreviousData: true,
    })

    useEffect(() => { window.scrollTo(0, 0) }, [activeTab])

    const refreshAll = () => {
        queryClient.invalidateQueries()
        toast.success('Dashboard refreshed')
    }

    if (isLoading) {
        return (
            <div className="flex items-center justify-center min-h-[400px]">
                <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-primary-500"></div>
            </div>
        )
    }

    if (error) {
        return (
            <div className="max-w-2xl mx-auto card p-8 text-center space-y-3">
                <ShieldOff className="w-10 h-10 mx-auto text-rose-500" />
                <h2 className="text-lg font-bold text-surface-900 dark:text-white">Unable to load dashboard</h2>
                <p className="text-surface-500 text-sm">Failed to load admin statistics. Please ensure you have administrator privileges.</p>
            </div>
        )
    }

    return (
        <div className="space-y-6 max-w-7xl mx-auto">
            {/* Section Header */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div className="flex items-center gap-3">
                    <div className="p-2.5 rounded-xl bg-primary-50 dark:bg-primary-900/30 text-primary-600 dark:text-primary-400">
                        <activeMeta.icon className="w-5 h-5" />
                    </div>
                    <div>
                        <h1 className="text-xl sm:text-2xl font-bold text-surface-900 dark:text-white">{activeMeta.label}</h1>
                        <p className="text-surface-500 text-sm">{activeMeta.subtitle || 'Manage student records and track institutional performance'}</p>
                    </div>
                </div>
                <button onClick={refreshAll} className="self-start sm:self-auto inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-surface-100 dark:bg-surface-800 hover:bg-surface-200 dark:hover:bg-surface-700 transition-colors text-sm font-semibold text-surface-700 dark:text-surface-200">
                    <RefreshCw className={`w-4 h-4 ${isFetching ? 'animate-spin' : ''}`} /> Refresh
                </button>
            </div>

            <AnimatePresence mode="wait">
                <motion.div key={activeTab} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.2 }}>
                    {activeTab === 'overview' && <Overview stats={stats} range={growthRange} onRangeChange={setGrowthRange} />}
                    {activeTab === 'students' && <StudentManagement />}
                    {activeTab === 'enrollments' && <EnrollmentRequests />}
                    {activeTab === 'sales' && <SalesDashboard />}
                    {activeTab === 'marketing' && <MarketingPromotions />}
                    {activeTab === 'announcements' && <Announcements />}
                    {activeTab === 'performance' && <PerformanceReports />}
                    {activeTab === 'content' && <CourseBuilder />}
                    {activeTab === 'ai-studio' && <AICourseStudio />}
                    {activeTab === 'landing' && <LandingBuilder />}
                    {activeTab === 'ai' && <AIFeatures />}
                    {activeTab === 'settings' && <TenantSettings />}
                </motion.div>
            </AnimatePresence>
        </div>
    )
}

export default AdminDashboard
