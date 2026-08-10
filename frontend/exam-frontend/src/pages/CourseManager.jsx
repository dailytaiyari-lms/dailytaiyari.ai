import { useState } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'framer-motion'
import toast from 'react-hot-toast'
import {
    ArrowLeft, Plus, ChevronRight, ChevronDown, Loader2, Layers, Book,
    FileText, ListChecks, GraduationCap, Pencil, Eye, Video, FileType,
    Sparkles, HelpCircle, ClipboardList, Clock, Users, X, CheckCircle2, Save,
    Code2, Trash2, Image as ImageIcon, Upload, Radio, Calendar, Link2,
    Notebook as NotebookIcon,
} from 'lucide-react'
import { contentBuilderService as svc } from '../services/contentBuilderService'
import { notebookAdminService } from '../services/notebookService'
import courseAiService from '../services/courseAiService'
import { useAuthStore } from '../context/authStore'
import {
    EntityModal, ConfirmDialog, RowActions, QuestionModal, formatApiError, QTYPE_LABEL,
} from '../components/admin/builderShared'
import TopicStudio from '../components/admin/aiStudio/TopicStudio'
import Loading from '../components/common/Loading'

/* Content-type icon + tint */
const CONTENT_ICON = { video: Video, pdf: FileType, notes: FileText, revision: FileText, formula: Sparkles, interactive: Sparkles }
const statusPill = (status) =>
    status === 'published'
        ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400'
        : status === 'archived'
            ? 'bg-surface-200 text-surface-600 dark:bg-surface-700 dark:text-surface-300'
            : 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400'

/* ===========================================================================
 * Content list for the selected topic
 * ========================================================================= */
const ContentSection = ({ topic, subjectId, openModal, askDelete }) => {
    const { data: contents = [], isLoading } = useQuery({
        queryKey: ['cb-contents', topic.id],
        queryFn: () => svc.getContents(topic.id),
    })

    const videos = contents.filter((ct) => ct.content_type === 'video')
    const reading = contents.filter((ct) => ct.content_type !== 'video')

    const ContentRow = ({ ct }) => {
        const Icon = CONTENT_ICON[ct.content_type] || FileText
        return (
            <div className="group card p-3.5 flex items-center justify-between gap-3 hover:border-primary-200 dark:hover:border-primary-800 transition-colors">
                <div className="flex items-center gap-3 min-w-0">
                    <div className="w-9 h-9 rounded-xl bg-primary-50 dark:bg-primary-900/20 text-primary-600 dark:text-primary-400 flex items-center justify-center shrink-0">
                        <Icon className="w-4 h-4" />
                    </div>
                    <div className="min-w-0">
                        <p className="text-sm font-semibold text-surface-800 dark:text-surface-100 truncate">{ct.title}</p>
                        <div className="flex items-center gap-1.5 mt-1">
                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-surface-100 dark:bg-surface-800 text-surface-500 capitalize">{ct.content_type}</span>
                            <span className={`text-[10px] px-1.5 py-0.5 rounded capitalize ${statusPill(ct.status)}`}>{ct.status}</span>
                        </div>
                    </div>
                </div>
                <div className="opacity-0 group-hover:opacity-100 transition-opacity">
                    <RowActions
                        onEdit={() => openModal('content', ct, { topicId: topic.id, subjectId })}
                        onDelete={() => askDelete('content', ct, ct.title)}
                    />
                </div>
            </div>
        )
    }

    if (isLoading) {
        return <div className="py-8 flex justify-center"><Loader2 className="w-5 h-5 animate-spin text-surface-400" /></div>
    }

    return (
        <div className="space-y-6">
            {/* Reading material */}
            <div className="space-y-2">
                <div className="flex items-center justify-between">
                    <h4 className="text-sm font-bold text-surface-700 dark:text-surface-200">Reading material</h4>
                    <button
                        onClick={() => openModal('content', null, { topicId: topic.id, subjectId, defaults: { content_type: 'notes' } })}
                        className="btn-primary text-xs px-3 py-1.5"
                    >
                        <Plus className="w-3.5 h-3.5" /> Add material
                    </button>
                </div>
                {reading.length === 0 ? (
                    <EmptyHint icon={FileText} text="No notes or PDFs yet." sub="Add notes or upload a PDF for students to read." />
                ) : (
                    <div className="space-y-2">
                        {reading.map((ct) => <ContentRow key={ct.id} ct={ct} />)}
                    </div>
                )}
            </div>

            {/* Videos */}
            <div className="space-y-2">
                <div className="flex items-center justify-between">
                    <h4 className="text-sm font-bold text-surface-700 dark:text-surface-200">Videos</h4>
                    <button
                        onClick={() => openModal('content', null, { topicId: topic.id, subjectId, defaults: { content_type: 'video' } })}
                        className="btn-secondary text-xs px-3 py-1.5"
                    >
                        <Plus className="w-3.5 h-3.5" /> Add video
                    </button>
                </div>
                {videos.length === 0 ? (
                    <EmptyHint icon={Video} text="No videos yet." sub="Add a video by pasting its URL." />
                ) : (
                    <div className="space-y-2">
                        {videos.map((ct) => <ContentRow key={ct.id} ct={ct} />)}
                    </div>
                )}
            </div>
        </div>
    )
}

/* ===========================================================================
 * Questions inside one quiz
 * ========================================================================= */
const QuestionSection = ({ quiz, topicId, subjectId, askDelete }) => {
    const queryClient = useQueryClient()
    const [qModal, setQModal] = useState(null) // { instance } | null
    const { data: questions = [], isLoading } = useQuery({
        queryKey: ['cb-questions', quiz.id],
        queryFn: () => svc.getQuestions(quiz.id),
    })

    const saveMutation = useMutation({
        mutationFn: ({ instance, payload }) =>
            instance
                ? svc.updateQuestion(instance.id, payload)
                : svc.createQuestion({ ...payload, quiz: quiz.id, topic: topicId, subject: subjectId }),
        onSuccess: (_d, vars) => {
            toast.success(`Question ${vars.instance ? 'updated' : 'added'}`)
            queryClient.invalidateQueries({ queryKey: ['cb-questions', quiz.id] })
            queryClient.invalidateQueries({ queryKey: ['cb-quizzes', topicId] })
            setQModal(null)
        },
        onError: (err) => toast.error(formatApiError(err)),
    })

    return (
        <div className="mt-3 pl-3 border-l-2 border-surface-100 dark:border-surface-800 space-y-1.5">
            <div className="flex items-center justify-between">
                <span className="text-[10px] font-black uppercase tracking-widest text-surface-400">
                    {questions.length} question{questions.length === 1 ? '' : 's'}
                </span>
                <button onClick={() => setQModal({ instance: null })} className="text-xs font-semibold text-primary-600 hover:text-primary-700 inline-flex items-center gap-1">
                    <Plus className="w-3.5 h-3.5" /> Add question
                </button>
            </div>

            {isLoading ? (
                <div className="py-3 flex justify-center"><Loader2 className="w-4 h-4 animate-spin text-surface-400" /></div>
            ) : questions.length === 0 ? (
                <p className="text-xs text-surface-400 italic py-1">No questions yet.</p>
            ) : (
                questions.map((q, i) => (
                    <div key={q.id} className="group flex items-start justify-between gap-2 py-1.5">
                        <div className="flex items-start gap-2 min-w-0">
                            <span className="text-[11px] font-bold text-surface-400 mt-0.5 shrink-0">{i + 1}.</span>
                            <div className="min-w-0">
                                <p className="text-sm text-surface-700 dark:text-surface-200 line-clamp-2">{q.question_text}</p>
                                <span className="text-[10px] text-surface-400">{QTYPE_LABEL[q.question_type] || q.question_type} · {q.marks} marks</span>
                            </div>
                        </div>
                        <div className="opacity-0 group-hover:opacity-100 transition-opacity">
                            <RowActions
                                onEdit={() => setQModal({ instance: q })}
                                onDelete={() => askDelete('question', q, 'this question')}
                            />
                        </div>
                    </div>
                ))
            )}

            <AnimatePresence>
                {qModal && (
                    <QuestionModal
                        instance={qModal.instance}
                        saving={saveMutation.isPending}
                        onClose={() => setQModal(null)}
                        onSubmit={(payload) => saveMutation.mutate({ instance: qModal.instance, payload })}
                    />
                )}
            </AnimatePresence>
        </div>
    )
}

/* ===========================================================================
 * Quizzes for the selected topic
 * ========================================================================= */
const QuizSection = ({ topic, subjectId, openModal, askDelete }) => {
    const [expanded, setExpanded] = useState({})
    const { data: quizzes = [], isLoading } = useQuery({
        queryKey: ['cb-quizzes', topic.id],
        queryFn: () => svc.getQuizzes(topic.id),
    })

    return (
        <div className="space-y-2">
            <div className="flex items-center justify-between">
                <h4 className="text-sm font-bold text-surface-700 dark:text-surface-200">Quizzes</h4>
                <button
                    onClick={() => openModal('quiz', null, { topicId: topic.id, subjectId })}
                    className="btn-primary text-xs px-3 py-1.5"
                >
                    <Plus className="w-3.5 h-3.5" /> Add quiz
                </button>
            </div>

            {isLoading ? (
                <div className="py-8 flex justify-center"><Loader2 className="w-5 h-5 animate-spin text-surface-400" /></div>
            ) : quizzes.length === 0 ? (
                <EmptyHint icon={ListChecks} text="No quizzes yet." sub="Create a quiz, then add questions to it." />
            ) : (
                <div className="space-y-2">
                    {quizzes.map((qz) => {
                        const open = !!expanded[qz.id]
                        return (
                            <div key={qz.id} className="card overflow-hidden">
                                <div className="flex items-center justify-between gap-3 p-3.5">
                                    <button onClick={() => setExpanded((p) => ({ ...p, [qz.id]: !p[qz.id] }))} className="flex items-center gap-2.5 min-w-0 text-left flex-1">
                                        {open ? <ChevronDown className="w-4 h-4 text-surface-400 shrink-0" /> : <ChevronRight className="w-4 h-4 text-surface-400 shrink-0" />}
                                        <div className="w-9 h-9 rounded-xl bg-accent-50 dark:bg-accent-900/20 text-accent-600 dark:text-accent-400 flex items-center justify-center shrink-0">
                                            <ListChecks className="w-4 h-4" />
                                        </div>
                                        <div className="min-w-0">
                                            <p className="text-sm font-semibold text-surface-800 dark:text-surface-100 truncate">{qz.title}</p>
                                            <div className="flex items-center gap-1.5 mt-1">
                                                <span className={`text-[10px] px-1.5 py-0.5 rounded capitalize ${statusPill(qz.status)}`}>{qz.status}</span>
                                                <span className="text-[10px] text-surface-400">{qz.duration_minutes} min</span>
                                            </div>
                                        </div>
                                    </button>
                                    <div className="opacity-0 group-hover:opacity-100 sm:opacity-100 transition-opacity">
                                        <RowActions
                                            onEdit={() => openModal('quiz', qz, { topicId: topic.id, subjectId })}
                                            onDelete={() => askDelete('quiz', qz, qz.title)}
                                        />
                                    </div>
                                </div>
                                <AnimatePresence>
                                    {open && (
                                        <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="px-4 pb-4">
                                            <QuestionSection quiz={qz} topicId={topic.id} subjectId={subjectId} askDelete={askDelete} />
                                        </motion.div>
                                    )}
                                </AnimatePresence>
                            </div>
                        )
                    })}
                </div>
            )}
        </div>
    )
}

/* ===========================================================================
 * Topic list inside a chapter (in the left navigator)
 * ========================================================================= */
const TopicList = ({ chapter, subjectId, subjectName, sel, onSelectTopic, openModal, askDelete }) => {
    const { data: topics = [], isLoading } = useQuery({
        queryKey: ['cb-topics', chapter.id],
        queryFn: () => svc.getTopics({ chapterId: chapter.id }),
    })

    return (
        <div className="pl-4 py-1 space-y-0.5">
            {isLoading ? (
                <div className="py-2 flex justify-center"><Loader2 className="w-3.5 h-3.5 animate-spin text-surface-400" /></div>
            ) : topics.length === 0 ? (
                <p className="text-[11px] text-surface-400 italic px-2 py-1">No topics yet</p>
            ) : (
                topics.map((tp) => {
                    const active = sel.topicId === tp.id
                    return (
                        <div
                            key={tp.id}
                            className={`group flex items-center justify-between gap-1 pl-2 pr-1 py-1.5 rounded-lg cursor-pointer transition-colors ${active ? 'bg-primary-50 dark:bg-primary-900/25 text-primary-700 dark:text-primary-300' : 'hover:bg-surface-100 dark:hover:bg-surface-800'}`}
                            onClick={() => onSelectTopic(tp, subjectId, chapter.id, subjectName)}
                        >
                            <span className="flex items-center gap-1.5 min-w-0 text-sm">
                                <FileText className={`w-3.5 h-3.5 shrink-0 ${active ? 'text-primary-500' : 'text-surface-400'}`} />
                                <span className="truncate">{tp.name}</span>
                            </span>
                            <div className="opacity-0 group-hover:opacity-100 transition-opacity">
                                <RowActions
                                    onEdit={() => openModal('topic', tp, { subjectId, chapterId: chapter.id })}
                                    onDelete={() => askDelete('topic', tp, tp.name)}
                                />
                            </div>
                        </div>
                    )
                })
            )}
            <button
                onClick={() => openModal('topic', null, { subjectId, chapterId: chapter.id })}
                className="ml-2 mt-0.5 text-[11px] font-semibold text-primary-600 hover:text-primary-700 inline-flex items-center gap-1"
            >
                <Plus className="w-3 h-3" /> Add topic
            </button>
        </div>
    )
}

/* ===========================================================================
 * Chapter list inside a subject (in the left navigator)
 * ========================================================================= */
const ChapterList = ({ subject, sel, onSelectTopic, openModal, askDelete }) => {
    const [open, setOpen] = useState({})
    const { data: chapters = [], isLoading } = useQuery({
        queryKey: ['cb-chapters', subject.id],
        queryFn: () => svc.getChapters(subject.id),
    })

    return (
        <div className="pl-4 py-1 space-y-0.5">
            {isLoading ? (
                <div className="py-2 flex justify-center"><Loader2 className="w-3.5 h-3.5 animate-spin text-surface-400" /></div>
            ) : chapters.length === 0 ? (
                <p className="text-[11px] text-surface-400 italic px-2 py-1">No chapters yet</p>
            ) : (
                chapters.map((ch) => (
                    <div key={ch.id}>
                        <div className="group flex items-center justify-between gap-1 pl-1 pr-1 py-1.5 rounded-lg hover:bg-surface-100 dark:hover:bg-surface-800 transition-colors">
                            <button onClick={() => setOpen((p) => ({ ...p, [ch.id]: !p[ch.id] }))} className="flex items-center gap-1.5 min-w-0 text-sm text-left flex-1">
                                {open[ch.id] ? <ChevronDown className="w-3.5 h-3.5 text-surface-400 shrink-0" /> : <ChevronRight className="w-3.5 h-3.5 text-surface-400 shrink-0" />}
                                <Book className="w-3.5 h-3.5 text-surface-400 shrink-0" />
                                <span className="truncate font-medium">{ch.name}</span>
                            </button>
                            <div className="opacity-0 group-hover:opacity-100 transition-opacity">
                                <RowActions
                                    onEdit={() => openModal('chapter', ch, { subjectId: subject.id })}
                                    onDelete={() => askDelete('chapter', ch, ch.name)}
                                />
                            </div>
                        </div>
                        <AnimatePresence>
                            {open[ch.id] && (
                                <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
                                    <TopicList chapter={ch} subjectId={subject.id} subjectName={subject.name} sel={sel} onSelectTopic={onSelectTopic} openModal={openModal} askDelete={askDelete} />
                                </motion.div>
                            )}
                        </AnimatePresence>
                    </div>
                ))
            )}
            <button
                onClick={() => openModal('chapter', null, { subjectId: subject.id })}
                className="ml-1 mt-0.5 text-[11px] font-semibold text-primary-600 hover:text-primary-700 inline-flex items-center gap-1"
            >
                <Plus className="w-3 h-3" /> Add chapter
            </button>
        </div>
    )
}

/* ===========================================================================
 * Left navigator: Subjects → Chapters → Topics
 * ========================================================================= */
const Navigator = ({ courseId, sel, onSelectTopic, openModal, askDelete }) => {
    const [open, setOpen] = useState({})
    const { data: subjects = [], isLoading } = useQuery({
        queryKey: ['cb-subjects', courseId],
        queryFn: () => svc.getSubjects(courseId),
    })

    return (
        <div className="card p-3 lg:sticky lg:top-4 lg:max-h-[calc(100vh-2rem)] lg:overflow-y-auto">
            <div className="flex items-center justify-between px-1 mb-2">
                <h3 className="text-xs font-black uppercase tracking-widest text-surface-400">Subjects</h3>
                <button
                    onClick={() => openModal('subject', null, {})}
                    className="text-xs font-semibold text-primary-600 hover:text-primary-700 inline-flex items-center gap-1"
                >
                    <Plus className="w-3.5 h-3.5" /> Add
                </button>
            </div>

            {isLoading ? (
                <div className="py-8 flex justify-center"><Loader2 className="w-5 h-5 animate-spin text-surface-400" /></div>
            ) : subjects.length === 0 ? (
                <EmptyHint icon={Layers} text="No subjects yet." sub="Start by adding a subject." />
            ) : (
                <div className="space-y-0.5">
                    {subjects.map((sub) => (
                        <div key={sub.id}>
                            <div className="group flex items-center justify-between gap-1 px-1 py-2 rounded-lg hover:bg-surface-100 dark:hover:bg-surface-800 transition-colors">
                                <button onClick={() => setOpen((p) => ({ ...p, [sub.id]: !p[sub.id] }))} className="flex items-center gap-2 min-w-0 text-left flex-1">
                                    {open[sub.id] ? <ChevronDown className="w-4 h-4 text-surface-400 shrink-0" /> : <ChevronRight className="w-4 h-4 text-surface-400 shrink-0" />}
                                    <span className="w-6 h-6 rounded-lg flex items-center justify-center shrink-0" style={{ backgroundColor: `${sub.color || '#10B981'}22` }}>
                                        <Layers className="w-3.5 h-3.5" style={{ color: sub.color || '#10B981' }} />
                                    </span>
                                    <span className="truncate font-semibold text-sm">{sub.name}</span>
                                </button>
                                <div className="opacity-0 group-hover:opacity-100 transition-opacity">
                                    <RowActions
                                        onEdit={() => openModal('subject', sub, {})}
                                        onDelete={() => askDelete('subject', sub, sub.name)}
                                    />
                                </div>
                            </div>
                            <AnimatePresence>
                                {open[sub.id] && (
                                    <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
                                        <ChapterList subject={sub} sel={sel} onSelectTopic={onSelectTopic} openModal={openModal} askDelete={askDelete} />
                                    </motion.div>
                                )}
                            </AnimatePresence>
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}

const EmptyHint = ({ icon: Icon, text, sub }) => (
    <div className="py-8 px-4 text-center">
        <Icon className="w-8 h-8 mx-auto mb-2 text-surface-300 dark:text-surface-600" />
        <p className="text-sm font-medium text-surface-500">{text}</p>
        {sub && <p className="text-xs text-surface-400 mt-0.5">{sub}</p>}
    </div>
)

/* ===========================================================================
 * Main panel: content + quizzes for the selected topic
 * ========================================================================= */
/* ===========================================================================
 * Assignments for the selected topic
 * ========================================================================= */
const SUBMISSION_TYPE_LABEL = { text: 'Text answer', pdf: 'File upload (PDF/ZIP)', either: 'Text or file (PDF/ZIP)' }


const AssignmentSection = ({ topic, subjectId, openModal, askDelete }) => {
    const navigate = useNavigate()
    const { courseId } = useParams()
    const { data: assignments = [], isLoading } = useQuery({
        queryKey: ['cb-assignments', topic.id],
        queryFn: () => svc.getAssignments(topic.id),
    })

    if (isLoading) {
        return <div className="py-8 flex justify-center"><Loader2 className="w-5 h-5 animate-spin text-surface-400" /></div>
    }

    return (
        <div className="space-y-2">
            <div className="flex items-center justify-between">
                <h4 className="text-sm font-bold text-surface-700 dark:text-surface-200">Assignments</h4>
                <button
                    onClick={() => openModal('assignment', null, { topicId: topic.id, subjectId })}
                    className="btn-primary text-xs px-3 py-1.5"
                >
                    <Plus className="w-3.5 h-3.5" /> Add assignment
                </button>
            </div>
            {assignments.length === 0 ? (
                <EmptyHint icon={ClipboardList} text="No assignments yet." sub="Create a timed or timeless assignment for students to submit." />
            ) : (
                <div className="space-y-2">
                    {assignments.map((a) => (
                        <div key={a.id} className="group card p-3.5 flex items-center justify-between gap-3 hover:border-primary-200 dark:hover:border-primary-800 transition-colors">
                            <div className="flex items-center gap-3 min-w-0">
                                <div className="w-9 h-9 rounded-xl bg-orange-50 dark:bg-orange-900/20 text-orange-600 dark:text-orange-400 flex items-center justify-center shrink-0">
                                    <ClipboardList className="w-4 h-4" />
                                </div>
                                <div className="min-w-0">
                                    <p className="text-sm font-semibold text-surface-800 dark:text-surface-100 truncate">{a.title}</p>
                                    <div className="flex flex-wrap items-center gap-1.5 mt-1">
                                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-surface-100 dark:bg-surface-800 text-surface-500">{SUBMISSION_TYPE_LABEL[a.submission_type] || a.submission_type}</span>
                                        <span className={`text-[10px] px-1.5 py-0.5 rounded capitalize ${statusPill(a.status)}`}>{a.status}</span>
                                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-surface-100 dark:bg-surface-800 text-surface-500 inline-flex items-center gap-1">
                                            <Clock className="w-2.5 h-2.5" />
                                            {a.is_timed && a.due_at ? `Due ${new Date(a.due_at).toLocaleDateString()}` : 'No deadline'}
                                        </span>
                                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-primary-50 dark:bg-primary-900/20 text-primary-600">{a.submissions_count || 0} submitted</span>
                                    </div>
                                </div>
                            </div>
                            <div className="flex items-center gap-2 shrink-0">
                                <button onClick={() => navigate(`/courses/${courseId}/manage/assignments/${a.id}`)} className="btn-secondary text-xs px-2.5 py-1.5">
                                    <Users className="w-3.5 h-3.5" /> <span className="hidden sm:inline">Submissions</span>
                                </button>
                                <div className="opacity-0 group-hover:opacity-100 transition-opacity">
                                    <RowActions
                                        onEdit={() => openModal('assignment', a, { topicId: topic.id, subjectId })}
                                        onDelete={() => askDelete('assignment', a, a.title)}
                                    />
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}

const CODING_LANGS = [
    { key: 'python', label: 'Python 3.12' },
    { key: 'cpp', label: 'C++ (GCC 10.2)' },
    { key: 'java', label: 'Java 15' },
]

const blankCase = () => ({ stdin: '', expected_output: '', is_sample: false, points: 1, explanation: '' })

const CodingProblemModal = ({ instance, onClose, onSubmit, saving }) => {
    const [form, setForm] = useState(() => ({
        title: instance?.title || '',
        statement: instance?.statement || '',
        difficulty: instance?.difficulty || 'easy',
        status: instance?.status || 'draft',
        max_marks: instance?.max_marks ?? '',
        time_limit_ms: instance?.time_limit_ms ?? 3000,
        memory_limit_mb: instance?.memory_limit_mb ?? 256,
        solve_mode: instance?.solve_mode || 'in_app',
        external_url: instance?.external_url || '',
        allowed_languages: instance?.allowed_languages?.length ? instance.allowed_languages : ['python'],
        starter_code: instance?.starter_code || {},
        test_cases: instance?.test_cases?.length ? instance.test_cases.map((c) => ({ ...c })) : [{ ...blankCase(), is_sample: true }],
    }))

    const set = (k, v) => setForm((f) => ({ ...f, [k]: v }))
    const toggleLang = (key) => setForm((f) => {
        const has = f.allowed_languages.includes(key)
        return { ...f, allowed_languages: has ? f.allowed_languages.filter((l) => l !== key) : [...f.allowed_languages, key] }
    })
    const setStarter = (key, code) => setForm((f) => ({ ...f, starter_code: { ...f.starter_code, [key]: code } }))
    const setCase = (i, k, v) => setForm((f) => ({ ...f, test_cases: f.test_cases.map((c, idx) => idx === i ? { ...c, [k]: v } : c) }))
    const addCase = () => setForm((f) => ({ ...f, test_cases: [...f.test_cases, blankCase()] }))
    const removeCase = (i) => setForm((f) => ({ ...f, test_cases: f.test_cases.filter((_, idx) => idx !== i) }))

    const submit = (e) => {
        e.preventDefault()
        if (!form.title.trim()) return toast.error('Title is required')
        const needsExternal = form.solve_mode === 'external' || form.solve_mode === 'both'
        if (needsExternal && !form.external_url.trim()) return toast.error('Add the external problem link (required for external/both)')
        const inAppRequired = form.solve_mode === 'in_app' || form.solve_mode === 'both'
        if (inAppRequired && !form.allowed_languages.length) return toast.error('Pick at least one language')
        if (inAppRequired && !form.test_cases.length) return toast.error('Add at least one test case')
        onSubmit({
            title: form.title.trim(),
            statement: form.statement,
            difficulty: form.difficulty,
            status: form.status,
            max_marks: form.max_marks === '' ? null : Number(form.max_marks),
            time_limit_ms: Number(form.time_limit_ms) || 3000,
            memory_limit_mb: Number(form.memory_limit_mb) || 256,
            solve_mode: form.solve_mode,
            external_url: form.external_url.trim(),
            allowed_languages: form.allowed_languages,
            starter_code: Object.fromEntries(form.allowed_languages.map((k) => [k, form.starter_code[k] || ''])),
            test_cases: form.test_cases.map((c, i) => ({
                stdin: c.stdin || '',
                expected_output: c.expected_output || '',
                is_sample: !!c.is_sample,
                points: Number(c.points) || 1,
                explanation: c.explanation || '',
                order: i,
            })),
        })
    }

    return (
        <motion.div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose}>
            <motion.div
                className="bg-white dark:bg-surface-900 rounded-2xl w-full max-w-3xl max-h-[90vh] overflow-y-auto shadow-xl"
                initial={{ scale: 0.95, y: 10 }} animate={{ scale: 1, y: 0 }} exit={{ scale: 0.95, y: 10 }}
                onClick={(e) => e.stopPropagation()}
            >
                <div className="sticky top-0 bg-white dark:bg-surface-900 border-b border-surface-100 dark:border-surface-800 px-5 py-3.5 flex items-center justify-between z-10">
                    <h3 className="font-bold flex items-center gap-2"><Code2 className="w-4 h-4 text-primary-500" /> {instance ? 'Edit' : 'New'} coding problem</h3>
                    <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-surface-100 dark:hover:bg-surface-800"><X className="w-4 h-4" /></button>
                </div>

                <form onSubmit={submit} className="p-5 space-y-4">
                    <div>
                        <label className="block text-xs font-semibold text-surface-500 mb-1">Title</label>
                        <input className="input" value={form.title} onChange={(e) => set('title', e.target.value)} placeholder="e.g. Two Sum" />
                    </div>
                    <div>
                        <label className="block text-xs font-semibold text-surface-500 mb-1">Problem statement</label>
                        <textarea rows={6} className="input resize-y" value={form.statement} onChange={(e) => set('statement', e.target.value)} placeholder="Describe the problem, input format, output format, constraints…" />
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                        <div>
                            <label className="block text-xs font-semibold text-surface-500 mb-1">Where to solve</label>
                            <select className="input" value={form.solve_mode} onChange={(e) => set('solve_mode', e.target.value)}>
                                <option value="in_app">In app only</option>
                                <option value="external">External platform only</option>
                                <option value="both">Both (in app or external)</option>
                            </select>
                        </div>
                        {(form.solve_mode === 'external' || form.solve_mode === 'both') && (
                            <div className="sm:col-span-2">
                                <label className="block text-xs font-semibold text-surface-500 mb-1">External problem link</label>
                                <input type="url" className="input" value={form.external_url} onChange={(e) => set('external_url', e.target.value)} placeholder="https://leetcode.com/problems/two-sum/" />
                                <p className="text-[11px] text-surface-400 mt-1">Works with LeetCode, GeeksforGeeks, HackerRank, etc. Students get a link + a self-report “Mark as solved” button.</p>
                            </div>
                        )}
                    </div>

                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                        <div>
                            <label className="block text-xs font-semibold text-surface-500 mb-1">Difficulty</label>
                            <select className="input" value={form.difficulty} onChange={(e) => set('difficulty', e.target.value)}>
                                <option value="easy">Easy</option><option value="medium">Medium</option><option value="hard">Hard</option>
                            </select>
                        </div>
                        <div>
                            <label className="block text-xs font-semibold text-surface-500 mb-1">Status</label>
                            <select className="input" value={form.status} onChange={(e) => set('status', e.target.value)}>
                                <option value="draft">Draft</option><option value="published">Published</option><option value="archived">Archived</option>
                            </select>
                        </div>
                        <div>
                            <label className="block text-xs font-semibold text-surface-500 mb-1">Max marks</label>
                            <input type="number" min="0" className="input" value={form.max_marks} onChange={(e) => set('max_marks', e.target.value)} placeholder="optional" />
                        </div>
                        <div>
                            <label className="block text-xs font-semibold text-surface-500 mb-1">Time limit (ms)</label>
                            <input type="number" min="100" className="input" value={form.time_limit_ms} onChange={(e) => set('time_limit_ms', e.target.value)} />
                        </div>
                    </div>

                    {form.solve_mode !== 'external' && (
                      <>
                    <div>
                        <label className="block text-xs font-semibold text-surface-500 mb-1.5">Allowed languages</label>
                        <div className="flex flex-wrap gap-2">
                            {CODING_LANGS.map((l) => (
                                <button key={l.key} type="button" onClick={() => toggleLang(l.key)}
                                    className={`px-3 py-1.5 rounded-lg text-sm font-medium border transition-colors ${form.allowed_languages.includes(l.key) ? 'border-primary-500 bg-primary-50 dark:bg-primary-900/20 text-primary-600' : 'border-surface-200 dark:border-surface-700 text-surface-500'}`}>
                                    {l.label}
                                </button>
                            ))}
                        </div>
                    </div>

                    {form.allowed_languages.length > 0 && (
                        <div className="space-y-2">
                            <label className="block text-xs font-semibold text-surface-500">Starter code (optional, per language)</label>
                            {form.allowed_languages.map((k) => (
                                <div key={k}>
                                    <p className="text-[11px] text-surface-400 mb-1">{CODING_LANGS.find((l) => l.key === k)?.label}</p>
                                    <textarea rows={3} className="input resize-y font-mono text-xs" value={form.starter_code[k] || ''} onChange={(e) => setStarter(k, e.target.value)} placeholder="Boilerplate shown to students…" />
                                </div>
                            ))}
                        </div>
                    )}

                    <div className="space-y-2">
                        <div className="flex items-center justify-between">
                            <label className="block text-xs font-semibold text-surface-500">Test cases</label>
                            <button type="button" onClick={addCase} className="btn-secondary text-xs px-2.5 py-1"><Plus className="w-3.5 h-3.5" /> Add</button>
                        </div>
                        <p className="text-[11px] text-surface-400">Sample cases are shown to students (with input/output). Hidden cases are used for grading only.</p>
                        {form.test_cases.map((c, i) => (
                            <div key={i} className="rounded-lg border border-surface-200 dark:border-surface-700 p-3 space-y-2">
                                <div className="flex items-center justify-between">
                                    <span className="text-xs font-semibold text-surface-500">Test {i + 1}</span>
                                    <div className="flex items-center gap-3">
                                        <label className="flex items-center gap-1.5 text-xs text-surface-500 cursor-pointer">
                                            <input type="checkbox" checked={!!c.is_sample} onChange={(e) => setCase(i, 'is_sample', e.target.checked)} /> Sample (visible)
                                        </label>
                                        <div className="flex items-center gap-1">
                                            <span className="text-xs text-surface-400">pts</span>
                                            <input type="number" min="1" className="input py-1 w-16 text-xs" value={c.points} onChange={(e) => setCase(i, 'points', e.target.value)} />
                                        </div>
                                        {form.test_cases.length > 1 && (
                                            <button type="button" onClick={() => removeCase(i)} className="p-1 rounded hover:bg-red-50 dark:hover:bg-red-900/20 text-red-500"><Trash2 className="w-3.5 h-3.5" /></button>
                                        )}
                                    </div>
                                </div>
                                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                                    <textarea rows={2} className="input resize-y font-mono text-xs" value={c.stdin} onChange={(e) => setCase(i, 'stdin', e.target.value)} placeholder="Input (stdin)" />
                                    <textarea rows={2} className="input resize-y font-mono text-xs" value={c.expected_output} onChange={(e) => setCase(i, 'expected_output', e.target.value)} placeholder="Expected output" />
                                </div>
                                {c.is_sample && (
                                    <input className="input text-xs" value={c.explanation} onChange={(e) => setCase(i, 'explanation', e.target.value)} placeholder="Explanation (shown with sample)" />
                                )}
                            </div>
                        ))}
                    </div>
                      </>
                    )}

                    <div className="flex justify-end gap-2 pt-2">
                        <button type="button" onClick={onClose} className="btn-secondary">Cancel</button>
                        <button type="submit" disabled={saving} className="btn-primary">
                            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />} {instance ? 'Save' : 'Create'}
                        </button>
                    </div>
                </form>
            </motion.div>
        </motion.div>
    )
}

const DIFF_BADGE = {
    easy: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400',
    medium: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
    hard: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
}

const CodingSection = ({ topic, subjectId }) => {
    const navigate = useNavigate()
    const { courseId } = useParams()
    const queryClient = useQueryClient()
    const [modal, setModal] = useState(null) // { instance } | null
    const [del, setDel] = useState(null)

    const { data: problems = [], isLoading } = useQuery({
        queryKey: ['cb-coding', topic.id],
        queryFn: () => svc.getCodingProblems(topic.id),
    })

    const invalidate = () => queryClient.invalidateQueries({ queryKey: ['cb-coding', topic.id] })

    const saveMutation = useMutation({
        mutationFn: ({ instance, payload }) => {
            const body = { ...payload, course: courseId, subject: subjectId, topic: topic.id }
            return instance ? svc.updateCodingProblem(instance.id, body) : svc.createCodingProblem(body)
        },
        onSuccess: (_d, vars) => { toast.success(vars.instance ? 'Problem saved' : 'Problem created'); invalidate(); setModal(null) },
        onError: (err) => toast.error(formatApiError(err)),
    })

    const deleteMutation = useMutation({
        mutationFn: (p) => svc.deleteCodingProblem(p.id),
        onSuccess: () => { toast.success('Deleted'); invalidate(); setDel(null) },
        onError: (err) => toast.error(formatApiError(err)),
    })

    // Fetch full problem (with test cases) before editing.
    const openEdit = async (p) => {
        try {
            const full = await svc.getCodingProblem(p.id)
            setModal({ instance: full })
        } catch (err) {
            toast.error(formatApiError(err))
        }
    }

    if (isLoading) {
        return <div className="py-8 flex justify-center"><Loader2 className="w-5 h-5 animate-spin text-surface-400" /></div>
    }

    return (
        <div className="space-y-2">
            <div className="flex items-center justify-between">
                <h4 className="text-sm font-bold text-surface-700 dark:text-surface-200">Coding problems</h4>
                <button onClick={() => setModal({ instance: null })} className="btn-primary text-xs px-3 py-1.5">
                    <Plus className="w-3.5 h-3.5" /> Add problem
                </button>
            </div>
            {problems.length === 0 ? (
                <EmptyHint icon={Code2} text="No coding problems yet." sub="Create a problem with test cases; grading runs automatically." />
            ) : (
                <div className="space-y-2">
                    {problems.map((p) => (
                        <div key={p.id} className="group card p-3.5 flex items-center justify-between gap-3 hover:border-primary-200 dark:hover:border-primary-800 transition-colors">
                            <div className="flex items-center gap-3 min-w-0">
                                <div className="w-9 h-9 rounded-xl bg-primary-50 dark:bg-primary-900/20 text-primary-600 dark:text-primary-400 flex items-center justify-center shrink-0">
                                    <Code2 className="w-4 h-4" />
                                </div>
                                <div className="min-w-0">
                                    <p className="text-sm font-semibold text-surface-800 dark:text-surface-100 truncate">{p.title}</p>
                                    <div className="flex flex-wrap items-center gap-1.5 mt-1">
                                        <span className={`text-[10px] px-1.5 py-0.5 rounded capitalize ${DIFF_BADGE[p.difficulty] || ''}`}>{p.difficulty}</span>
                                        <span className={`text-[10px] px-1.5 py-0.5 rounded capitalize ${statusPill(p.status)}`}>{p.status}</span>
                                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-surface-100 dark:bg-surface-800 text-surface-500">{p.test_case_count || 0} tests</span>
                                        {p.max_marks != null && <span className="text-[10px] px-1.5 py-0.5 rounded bg-surface-100 dark:bg-surface-800 text-surface-500">{p.max_marks} marks</span>}
                                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-primary-50 dark:bg-primary-900/20 text-primary-600">{p.submission_count || 0} submitted</span>
                                    </div>
                                </div>
                            </div>
                            <div className="flex items-center gap-2 shrink-0">
                                <button onClick={() => navigate(`/courses/${courseId}/manage/coding/${p.id}`)} className="btn-secondary text-xs px-2.5 py-1.5">
                                    <Users className="w-3.5 h-3.5" /> <span className="hidden sm:inline">Submissions</span>
                                </button>
                                <div className="opacity-0 group-hover:opacity-100 transition-opacity">
                                    <RowActions onEdit={() => openEdit(p)} onDelete={() => setDel(p)} />
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            )}

            <AnimatePresence>
                {modal && (
                    <CodingProblemModal
                        instance={modal.instance}
                        saving={saveMutation.isPending}
                        onClose={() => setModal(null)}
                        onSubmit={(payload) => saveMutation.mutate({ instance: modal.instance, payload })}
                    />
                )}
                {del && (
                    <ConfirmDialog label={del.title} deleting={deleteMutation.isPending} onCancel={() => setDel(null)} onConfirm={() => deleteMutation.mutate(del)} />
                )}
            </AnimatePresence>
        </div>
    )
}

/* ===========================================================================
 * Python notebooks for the selected topic
 *
 * Authoring is rich enough (cell roles, tests, datasets) that it lives on its
 * own page rather than in a modal — this section is just the list plus the
 * links into the builder and the submissions dashboard.
 * ========================================================================= */
const NotebookSection = ({ topic, subjectId }) => {
    const navigate = useNavigate()
    const { courseId } = useParams()
    const queryClient = useQueryClient()
    const [del, setDel] = useState(null)

    const { data: notebooks = [], isLoading } = useQuery({
        queryKey: ['cb-notebooks', topic.id],
        queryFn: () => notebookAdminService.list({ topic: topic.id }),
    })

    const invalidate = () => queryClient.invalidateQueries({ queryKey: ['cb-notebooks', topic.id] })

    const deleteMutation = useMutation({
        mutationFn: (n) => notebookAdminService.remove(n.id),
        onSuccess: () => { toast.success('Deleted'); invalidate(); setDel(null) },
        onError: (err) => toast.error(formatApiError(err)),
    })

    const duplicateMutation = useMutation({
        mutationFn: (n) => notebookAdminService.duplicate(n.id),
        onSuccess: () => { toast.success('Duplicated'); invalidate() },
        onError: (err) => toast.error(formatApiError(err)),
    })

    const builderUrl = (id) =>
        `/courses/${courseId}/manage/notebooks/${id}/edit?topic=${topic.id}&subject=${subjectId || ''}`

    if (isLoading) {
        return <div className="py-8 flex justify-center"><Loader2 className="w-5 h-5 animate-spin text-surface-400" /></div>
    }

    return (
        <div className="space-y-2">
            <div className="flex items-center justify-between">
                <h4 className="text-sm font-bold text-surface-700 dark:text-surface-200">Python notebooks</h4>
                <button onClick={() => navigate(builderUrl('new'))} className="btn-primary text-xs px-3 py-1.5">
                    <Plus className="w-3.5 h-3.5" /> Add notebook
                </button>
            </div>
            {notebooks.length === 0 ? (
                <EmptyHint icon={NotebookIcon} text="No notebooks yet." sub="Import an .ipynb or start from scratch; students run Python in the browser and it grades automatically." />
            ) : (
                <div className="space-y-2">
                    {notebooks.map((n) => (
                        <div key={n.id} className="group card p-3.5 flex items-center justify-between gap-3 hover:border-primary-200 dark:hover:border-primary-800 transition-colors">
                            <div className="flex items-center gap-3 min-w-0">
                                <div className="w-9 h-9 rounded-xl bg-primary-50 dark:bg-primary-900/20 text-primary-600 dark:text-primary-400 flex items-center justify-center shrink-0">
                                    <NotebookIcon className="w-4 h-4" />
                                </div>
                                <div className="min-w-0">
                                    <p className="text-sm font-semibold text-surface-800 dark:text-surface-100 truncate">{n.title}</p>
                                    <div className="flex flex-wrap items-center gap-1.5 mt-1">
                                        <span className={`text-[10px] px-1.5 py-0.5 rounded capitalize ${DIFF_BADGE[n.difficulty] || ''}`}>{n.difficulty}</span>
                                        <span className={`text-[10px] px-1.5 py-0.5 rounded capitalize ${statusPill(n.status)}`}>{n.status}</span>
                                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-surface-100 dark:bg-surface-800 text-surface-500">{n.test_count || 0} tests</span>
                                        {n.max_marks != null && <span className="text-[10px] px-1.5 py-0.5 rounded bg-surface-100 dark:bg-surface-800 text-surface-500">{n.max_marks} marks</span>}
                                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-primary-50 dark:bg-primary-900/20 text-primary-600">{n.submission_count || 0} submitted</span>
                                    </div>
                                </div>
                            </div>
                            <div className="flex items-center gap-2 shrink-0">
                                <button onClick={() => navigate(`/courses/${courseId}/manage/notebooks/${n.id}`)} className="btn-secondary text-xs px-2.5 py-1.5">
                                    <Users className="w-3.5 h-3.5" /> <span className="hidden sm:inline">Submissions</span>
                                </button>
                                <div className="opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1">
                                    <button
                                        onClick={() => duplicateMutation.mutate(n)}
                                        disabled={duplicateMutation.isPending}
                                        title="Duplicate"
                                        className="p-1.5 rounded-lg text-surface-400 hover:bg-surface-100 dark:hover:bg-surface-800 hover:text-primary-600"
                                    >
                                        <Layers className="w-4 h-4" />
                                    </button>
                                    <RowActions
                                        onEdit={() => navigate(builderUrl(n.id))}
                                        onDelete={() => setDel(n)}
                                    />
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            )}

            <AnimatePresence>
                {del && (
                    <ConfirmDialog label={del.title} deleting={deleteMutation.isPending} onCancel={() => setDel(null)} onConfirm={() => deleteMutation.mutate(del)} />
                )}
            </AnimatePresence>
        </div>
    )
}

/* ===========================================================================
 * Live classes for the selected topic
 * ========================================================================= */
const LIVE_PROVIDERS = [
    { key: 'gmeet', label: 'Google Meet', hint: 'Paste a Google Meet link students join at class time.', soon: false },
    { key: 'in_house', label: 'In-house Live', hint: 'Go live from the portal with your own device.', soon: true },
]

const LIVE_STATUS_BADGE = {
    upcoming: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
    live: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
    ended: 'bg-surface-200 text-surface-600 dark:bg-surface-700 dark:text-surface-300',
}

// Format an ISO datetime into a value usable by <input type="datetime-local">
// (local time, "YYYY-MM-DDTHH:MM"). Returns '' for empty/invalid input.
const toLocalInput = (iso) => {
    if (!iso) return ''
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return ''
    const pad = (n) => String(n).padStart(2, '0')
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const LiveClassModal = ({ instance, onClose, onSubmit, saving }) => {
    const [form, setForm] = useState(() => ({
        title: instance?.title || '',
        description: instance?.description || '',
        provider: instance?.provider || 'gmeet',
        meeting_url: instance?.meeting_url || '',
        scheduled_start: toLocalInput(instance?.scheduled_start),
        duration_minutes: instance?.duration_minutes ?? 60,
        host_name: instance?.host_name || '',
        status: instance?.status || 'draft',
    }))

    const set = (k, v) => setForm((f) => ({ ...f, [k]: v }))

    const submit = (e) => {
        e.preventDefault()
        if (!form.title.trim()) return toast.error('Title is required')
        if (form.provider === 'gmeet' && !form.meeting_url.trim()) return toast.error('A Google Meet link is required')
        onSubmit({
            title: form.title.trim(),
            description: form.description,
            provider: form.provider,
            meeting_url: form.meeting_url.trim(),
            scheduled_start: form.scheduled_start ? new Date(form.scheduled_start).toISOString() : null,
            duration_minutes: Number(form.duration_minutes) || 60,
            host_name: form.host_name.trim(),
            status: form.status,
        })
    }

    return (
        <motion.div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose}>
            <motion.div
                className="bg-white dark:bg-surface-900 rounded-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto shadow-xl"
                initial={{ scale: 0.95, y: 10 }} animate={{ scale: 1, y: 0 }} exit={{ scale: 0.95, y: 10 }}
                onClick={(e) => e.stopPropagation()}
            >
                <div className="sticky top-0 bg-white dark:bg-surface-900 border-b border-surface-100 dark:border-surface-800 px-5 py-3.5 flex items-center justify-between z-10">
                    <h3 className="font-bold flex items-center gap-2"><Radio className="w-4 h-4 text-primary-500" /> {instance ? 'Edit' : 'New'} live class</h3>
                    <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-surface-100 dark:hover:bg-surface-800"><X className="w-4 h-4" /></button>
                </div>

                <form onSubmit={submit} className="p-5 space-y-4">
                    <div>
                        <label className="block text-xs font-semibold text-surface-500 mb-1">Title</label>
                        <input className="input" value={form.title} onChange={(e) => set('title', e.target.value)} placeholder="e.g. Doubt-clearing session: Kinematics" />
                    </div>

                    <div>
                        <label className="block text-xs font-semibold text-surface-500 mb-1.5">Platform</label>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                            {LIVE_PROVIDERS.map((p) => {
                                const active = form.provider === p.key
                                return (
                                    <button
                                        key={p.key}
                                        type="button"
                                        disabled={p.soon}
                                        onClick={() => !p.soon && set('provider', p.key)}
                                        className={`text-left px-3 py-2.5 rounded-xl border transition-colors ${active ? 'border-primary-500 bg-primary-50 dark:bg-primary-900/20' : 'border-surface-200 dark:border-surface-700'} ${p.soon ? 'opacity-60 cursor-not-allowed' : 'hover:border-primary-300'}`}
                                    >
                                        <div className="flex items-center gap-1.5">
                                            <span className={`text-sm font-semibold ${active ? 'text-primary-600 dark:text-primary-400' : 'text-surface-700 dark:text-surface-200'}`}>{p.label}</span>
                                            {p.soon && <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">Coming soon</span>}
                                        </div>
                                        <p className="text-[11px] text-surface-400 mt-0.5">{p.hint}</p>
                                    </button>
                                )
                            })}
                        </div>
                    </div>

                    {form.provider === 'gmeet' && (
                        <div>
                            <label className="block text-xs font-semibold text-surface-500 mb-1">Google Meet link</label>
                            <div className="relative">
                                <Link2 className="w-4 h-4 text-surface-400 absolute left-3 top-1/2 -translate-y-1/2" />
                                <input className="input pl-9" value={form.meeting_url} onChange={(e) => set('meeting_url', e.target.value)} placeholder="https://meet.google.com/abc-defg-hij" />
                            </div>
                        </div>
                    )}

                    <div>
                        <label className="block text-xs font-semibold text-surface-500 mb-1">Description</label>
                        <textarea rows={4} className="input resize-y" value={form.description} onChange={(e) => set('description', e.target.value)} placeholder="What will be covered, prerequisites, etc." />
                    </div>

                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                        <div className="col-span-2">
                            <label className="block text-xs font-semibold text-surface-500 mb-1">Starts at</label>
                            <input type="datetime-local" className="input" value={form.scheduled_start} onChange={(e) => set('scheduled_start', e.target.value)} />
                        </div>
                        <div>
                            <label className="block text-xs font-semibold text-surface-500 mb-1">Duration (min)</label>
                            <input type="number" min="1" className="input" value={form.duration_minutes} onChange={(e) => set('duration_minutes', e.target.value)} />
                        </div>
                        <div>
                            <label className="block text-xs font-semibold text-surface-500 mb-1">Status</label>
                            <select className="input" value={form.status} onChange={(e) => set('status', e.target.value)}>
                                <option value="draft">Draft</option><option value="published">Published</option><option value="archived">Archived</option>
                            </select>
                        </div>
                    </div>

                    <div>
                        <label className="block text-xs font-semibold text-surface-500 mb-1">Host name (optional)</label>
                        <input className="input" value={form.host_name} onChange={(e) => set('host_name', e.target.value)} placeholder="e.g. Prof. Sharma" />
                    </div>

                    <div className="flex justify-end gap-2 pt-2">
                        <button type="button" onClick={onClose} className="btn-secondary">Cancel</button>
                        <button type="submit" disabled={saving} className="btn-primary">
                            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />} {instance ? 'Save' : 'Create'}
                        </button>
                    </div>
                </form>
            </motion.div>
        </motion.div>
    )
}

const LiveClassSection = ({ topic, subjectId }) => {
    const { courseId } = useParams()
    const queryClient = useQueryClient()
    const [modal, setModal] = useState(null) // { instance } | null
    const [del, setDel] = useState(null)

    const { data: classes = [], isLoading } = useQuery({
        queryKey: ['cb-live', topic.id],
        queryFn: () => svc.getLiveClasses(topic.id),
    })

    const invalidate = () => queryClient.invalidateQueries({ queryKey: ['cb-live', topic.id] })

    const saveMutation = useMutation({
        mutationFn: ({ instance, payload }) => {
            const body = { ...payload, course: courseId, subject: subjectId, topic: topic.id }
            return instance ? svc.updateLiveClass(instance.id, body) : svc.createLiveClass(body)
        },
        onSuccess: (_d, vars) => { toast.success(vars.instance ? 'Live class saved' : 'Live class created'); invalidate(); setModal(null) },
        onError: (err) => toast.error(formatApiError(err)),
    })

    const deleteMutation = useMutation({
        mutationFn: (c) => svc.deleteLiveClass(c.id),
        onSuccess: () => { toast.success('Deleted'); invalidate(); setDel(null) },
        onError: (err) => toast.error(formatApiError(err)),
    })

    if (isLoading) {
        return <div className="py-8 flex justify-center"><Loader2 className="w-5 h-5 animate-spin text-surface-400" /></div>
    }

    const fmtWhen = (iso) => {
        if (!iso) return 'Not scheduled'
        const d = new Date(iso)
        if (Number.isNaN(d.getTime())) return 'Not scheduled'
        return d.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })
    }

    return (
        <div className="space-y-2">
            <div className="flex items-center justify-between">
                <h4 className="text-sm font-bold text-surface-700 dark:text-surface-200">Live classes</h4>
                <button onClick={() => setModal({ instance: null })} className="btn-primary text-xs px-3 py-1.5">
                    <Plus className="w-3.5 h-3.5" /> Add live class
                </button>
            </div>
            {classes.length === 0 ? (
                <EmptyHint icon={Radio} text="No live classes yet." sub="Schedule a Google Meet live class for students to join." />
            ) : (
                <div className="space-y-2">
                    {classes.map((c) => (
                        <div key={c.id} className="group card p-3.5 flex items-center justify-between gap-3 hover:border-primary-200 dark:hover:border-primary-800 transition-colors">
                            <div className="flex items-center gap-3 min-w-0">
                                <div className="w-9 h-9 rounded-xl bg-primary-50 dark:bg-primary-900/20 text-primary-600 dark:text-primary-400 flex items-center justify-center shrink-0">
                                    <Radio className="w-4 h-4" />
                                </div>
                                <div className="min-w-0">
                                    <p className="text-sm font-semibold text-surface-800 dark:text-surface-100 truncate">{c.title}</p>
                                    <div className="flex flex-wrap items-center gap-1.5 mt-1">
                                        {c.live_status && <span className={`text-[10px] px-1.5 py-0.5 rounded capitalize ${LIVE_STATUS_BADGE[c.live_status] || ''}`}>{c.live_status}</span>}
                                        <span className={`text-[10px] px-1.5 py-0.5 rounded capitalize ${statusPill(c.status)}`}>{c.status}</span>
                                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-surface-100 dark:bg-surface-800 text-surface-500">{c.provider_display || 'Google Meet'}</span>
                                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-surface-100 dark:bg-surface-800 text-surface-500 inline-flex items-center gap-1"><Calendar className="w-3 h-3" /> {fmtWhen(c.scheduled_start)}</span>
                                    </div>
                                </div>
                            </div>
                            <div className="flex items-center gap-2 shrink-0">
                                {c.meeting_url && (
                                    <a href={c.meeting_url} target="_blank" rel="noreferrer" className="btn-secondary text-xs px-2.5 py-1.5">
                                        <Link2 className="w-3.5 h-3.5" /> <span className="hidden sm:inline">Join</span>
                                    </a>
                                )}
                                <div className="opacity-0 group-hover:opacity-100 transition-opacity">
                                    <RowActions onEdit={() => setModal({ instance: c })} onDelete={() => setDel(c)} />
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            )}

            <AnimatePresence>
                {modal && (
                    <LiveClassModal
                        instance={modal.instance}
                        saving={saveMutation.isPending}
                        onClose={() => setModal(null)}
                        onSubmit={(payload) => saveMutation.mutate({ instance: modal.instance, payload })}
                    />
                )}
                {del && (
                    <ConfirmDialog label={del.title} deleting={deleteMutation.isPending} onCancel={() => setDel(null)} onConfirm={() => deleteMutation.mutate(del)} />
                )}
            </AnimatePresence>
        </div>
    )
}

const TopicPanel = ({ topic, subjectId, subjectName, openModal, askDelete }) => {
    const { courseId } = useParams()
    const queryClient = useQueryClient()
    const [tab, setTab] = useState('content')
    const [aiOpen, setAiOpen] = useState(false)

    // The studio entry point only appears once we know an AI provider is
    // actually configured — a button that always fails is worse than no button.
    const { data: aiHealth } = useQuery({
        queryKey: ['coursegen-health'],
        queryFn: courseAiService.getHealth,
        staleTime: 5 * 60_000,
        retry: false,
    })

    // Everything the panel shows for this topic is refetched after a write, so
    // generated material appears in the tabs without a manual reload.
    const refreshTopic = () => {
        for (const key of ['cb-contents', 'cb-quizzes', 'cb-assignments', 'cb-coding', 'cb-notebooks']) {
            queryClient.invalidateQueries({ queryKey: [key, topic.id] })
        }
    }

    return (
        <div className="card p-4 sm:p-6">
            <div className="flex items-start justify-between gap-3 mb-1">
                <div className="min-w-0">
                    <h2 className="text-xl font-display font-bold truncate">{topic.name}</h2>
                    <div className="flex flex-wrap items-center gap-2 mt-1.5">
                        {topic.difficulty && <span className="text-[11px] px-2 py-0.5 rounded-md bg-surface-100 dark:bg-surface-800 text-surface-500 capitalize">{topic.difficulty}</span>}
                        {topic.importance && <span className="text-[11px] px-2 py-0.5 rounded-md bg-surface-100 dark:bg-surface-800 text-surface-500 capitalize">{topic.importance} importance</span>}
                    </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                    {aiHealth?.is_ready && (
                        <button onClick={() => setAiOpen(true)} className="btn-primary text-xs px-3 py-1.5">
                            <Sparkles className="w-3.5 h-3.5" /> Generate with AI
                        </button>
                    )}
                    <button onClick={() => openModal('topic', topic, { subjectId })} className="btn-secondary text-xs px-3 py-1.5">
                        <Pencil className="w-3.5 h-3.5" /> Edit topic
                    </button>
                </div>
            </div>

            <div className="flex gap-1 p-1 bg-surface-100 dark:bg-surface-800 rounded-xl w-fit my-4">
                {[{ id: 'content', label: 'Content', icon: FileText }, { id: 'quizzes', label: 'Quizzes', icon: ListChecks }, { id: 'assignments', label: 'Assignments', icon: ClipboardList }, { id: 'coding', label: 'Coding', icon: Code2 }, { id: 'notebooks', label: 'Notebooks', icon: NotebookIcon }, { id: 'live', label: 'Live', icon: Radio }].map((t) => (
                    <button
                        key={t.id}
                        onClick={() => setTab(t.id)}
                        className={`px-4 py-1.5 rounded-lg text-sm font-semibold inline-flex items-center gap-1.5 transition-all ${tab === t.id ? 'bg-white dark:bg-surface-700 text-primary-600 dark:text-primary-400 shadow-sm' : 'text-surface-500 hover:text-surface-700 dark:hover:text-surface-300'}`}
                    >
                        <t.icon className="w-3.5 h-3.5" /> {t.label}
                    </button>
                ))}
            </div>

            {tab === 'content' && <ContentSection topic={topic} subjectId={subjectId} openModal={openModal} askDelete={askDelete} />}
            {tab === 'quizzes' && <QuizSection topic={topic} subjectId={subjectId} openModal={openModal} askDelete={askDelete} />}
            {tab === 'assignments' && <AssignmentSection topic={topic} subjectId={subjectId} openModal={openModal} askDelete={askDelete} />}
            {tab === 'coding' && <CodingSection topic={topic} subjectId={subjectId} />}
            {tab === 'notebooks' && <NotebookSection topic={topic} subjectId={subjectId} />}
            {tab === 'live' && <LiveClassSection topic={topic} subjectId={subjectId} />}

            <AnimatePresence>
                {aiOpen && (
                    <TopicStudio
                        courseId={courseId}
                        topic={topic}
                        subjectName={subjectName}
                        onClose={() => setAiOpen(false)}
                        onApplied={refreshTopic}
                    />
                )}
            </AnimatePresence>
        </div>
    )
}

/* ===========================================================================
 * Root page
 * ========================================================================= */
const InstructorsModal = ({ course, onClose, onSaved }) => {
    const { data: instructors = [], isLoading } = useQuery({
        queryKey: ['cb-instructors'],
        queryFn: () => svc.getInstructors(),
    })
    const [selected, setSelected] = useState(() => new Set((course.instructors_detail || []).map((i) => String(i.id))))

    const saveMutation = useMutation({
        mutationFn: () => svc.updateExam(course.id, { instructors: Array.from(selected) }),
        onSuccess: () => {
            toast.success('Faculty updated')
            onSaved?.()
            onClose()
        },
        onError: (err) => toast.error(formatApiError(err)),
    })

    const toggle = (id) => setSelected((prev) => {
        const next = new Set(prev)
        next.has(id) ? next.delete(id) : next.add(id)
        return next
    })

    return (
        <motion.div
            className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60"
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            onMouseDown={(e) => e.target === e.currentTarget && onClose()}
        >
            <motion.div
                className="card w-full max-w-lg max-h-[85vh] overflow-hidden flex flex-col"
                initial={{ scale: 0.96, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.96, opacity: 0 }}
            >
                <div className="flex items-center justify-between p-5 border-b border-surface-200 dark:border-surface-800">
                    <div className="min-w-0">
                        <h3 className="text-lg font-bold truncate">Assign faculty</h3>
                        <p className="text-xs text-surface-500">Faculty can edit this course's content but can't manage faculty.</p>
                    </div>
                    <button onClick={onClose} className="btn-icon"><X className="w-5 h-5" /></button>
                </div>

                <div className="p-5 overflow-y-auto space-y-2">
                    {isLoading ? (
                        <div className="py-8 flex justify-center"><Loader2 className="w-5 h-5 animate-spin text-surface-400" /></div>
                    ) : instructors.length === 0 ? (
                        <div className="text-center py-8 text-surface-500 text-sm">
                            <Users className="w-8 h-8 mx-auto mb-2 text-surface-300" />
                            <p>No faculty yet.</p>
                            <p className="text-xs mt-1">Set a user's role to "Faculty" in the admin dashboard first.</p>
                        </div>
                    ) : (
                        instructors.map((ins) => {
                            const id = String(ins.id)
                            const checked = selected.has(id)
                            return (
                                <label
                                    key={id}
                                    className={`flex items-center gap-3 p-3 rounded-xl border cursor-pointer transition-colors ${checked ? 'border-primary-300 bg-primary-50/50 dark:bg-primary-900/20' : 'border-surface-200 dark:border-surface-700 hover:border-surface-300'}`}
                                >
                                    <input type="checkbox" checked={checked} onChange={() => toggle(id)} className="accent-primary-600 w-4 h-4" />
                                    <div className="min-w-0">
                                        <p className="text-sm font-semibold truncate">{ins.name}</p>
                                        <p className="text-xs text-surface-400 truncate">{ins.email}</p>
                                    </div>
                                    {checked && <CheckCircle2 className="w-4 h-4 text-primary-500 ml-auto shrink-0" />}
                                </label>
                            )
                        })
                    )}
                </div>

                <div className="flex justify-end gap-2 p-4 border-t border-surface-200 dark:border-surface-800">
                    <button onClick={onClose} className="btn-secondary text-sm px-4 py-2">Cancel</button>
                    <button onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending} className="btn-primary text-sm px-4 py-2 inline-flex items-center gap-2">
                        {saveMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />} Save
                    </button>
                </div>
            </motion.div>
        </motion.div>
    )
}

const ThumbnailModal = ({ course, onClose, onSaved }) => {
    const [preview, setPreview] = useState(course.thumbnail || null)
    const [file, setFile] = useState(null)

    const saveMutation = useMutation({
        mutationFn: () => svc.updateCourseThumbnail(course.id, file),
        onSuccess: () => {
            toast.success('Thumbnail updated')
            onSaved?.()
            onClose()
        },
        onError: (err) => toast.error(formatApiError(err)),
    })

    const onPick = (e) => {
        const f = e.target.files?.[0]
        if (!f) return
        if (!f.type.startsWith('image/')) { toast.error('Please choose an image file'); return }
        setFile(f)
        setPreview(URL.createObjectURL(f))
        e.target.value = ''
    }

    return (
        <motion.div
            className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60"
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            onMouseDown={(e) => e.target === e.currentTarget && onClose()}
        >
            <motion.div
                className="card w-full max-w-lg overflow-hidden flex flex-col"
                initial={{ scale: 0.96, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.96, opacity: 0 }}
            >
                <div className="flex items-center justify-between p-5 border-b border-surface-200 dark:border-surface-800">
                    <div className="min-w-0">
                        <h3 className="text-lg font-bold truncate">Course thumbnail</h3>
                        <p className="text-xs text-surface-500">Shown on course tiles. The full image is used exactly as uploaded — a 16:9 image looks best.</p>
                    </div>
                    <button onClick={onClose} className="btn-icon"><X className="w-5 h-5" /></button>
                </div>

                <div className="p-5 space-y-4">
                    <div className="relative aspect-[16/9] w-full rounded-xl overflow-hidden bg-surface-100 dark:bg-surface-800 border border-surface-200 dark:border-surface-700">
                        {preview ? (
                            <img src={preview} alt="Thumbnail preview" className="w-full h-full object-contain" />
                        ) : (
                            <div className="w-full h-full flex flex-col items-center justify-center text-surface-400">
                                <ImageIcon className="w-8 h-8 mb-2" />
                                <p className="text-sm">No thumbnail yet</p>
                            </div>
                        )}
                    </div>

                    <label className="btn-secondary w-full inline-flex items-center justify-center gap-2 cursor-pointer">
                        <Upload className="w-4 h-4" /> {preview ? 'Choose a different image' : 'Choose image'}
                        <input type="file" accept="image/*" onChange={onPick} className="hidden" />
                    </label>
                </div>

                <div className="flex justify-end gap-2 p-4 border-t border-surface-200 dark:border-surface-800">
                    <button onClick={onClose} className="btn-secondary text-sm px-4 py-2">Cancel</button>
                    <button
                        onClick={() => saveMutation.mutate()}
                        disabled={!file || saveMutation.isPending}
                        className="btn-primary text-sm px-4 py-2 inline-flex items-center gap-2 disabled:opacity-50"
                    >
                        {saveMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />} Save thumbnail
                    </button>
                </div>
            </motion.div>
        </motion.div>
    )
}

const CourseManager = () => {
    const { courseId } = useParams()
    const navigate = useNavigate()
    const location = useLocation()
    const queryClient = useQueryClient()
    const { user, profile } = useAuthStore()
    const isAdmin = (user?.role || profile?.user?.role) === 'admin'

    // When opened from the admin console, keep the user inside the admin flow.
    const inAdmin = location.pathname.startsWith('/admin-dashboard')
    const backTo = inAdmin ? '/admin-dashboard?tab=content' : '/courses'

    const [sel, setSel] = useState({ subjectId: null, chapterId: null, topicId: null, topic: null })
    const [modal, setModal] = useState(null)   // { type, instance, extra }
    const [del, setDel] = useState(null)        // { type, instance, label }
    const [instructorsOpen, setInstructorsOpen] = useState(false)
    const [thumbnailOpen, setThumbnailOpen] = useState(false)

    const { data: courses = [], isLoading } = useQuery({
        queryKey: ['cb-courses'],
        queryFn: () => svc.getExams(),
    })
    const course = courses.find((c) => String(c.id) === String(courseId))

    const onSelectTopic = (topic, subjectId, chapterId, subjectName) => setSel({ subjectId, chapterId, topicId: topic.id, topic, subjectName })
    const openModal = (type, instance, extra = {}) => setModal({ type, instance, extra })
    const askDelete = (type, instance, label) => setDel({ type, instance, label })

    /* invalidate the right queries after a change */
    const invalidateFor = (type, extra = {}) => {
        const q = queryClient
        if (type === 'exam') q.invalidateQueries({ queryKey: ['cb-courses'] })
        if (type === 'subject') q.invalidateQueries({ queryKey: ['cb-subjects', courseId] })
        if (type === 'chapter') q.invalidateQueries({ queryKey: ['cb-chapters', extra.subjectId] })
        if (type === 'topic') q.invalidateQueries({ queryKey: ['cb-topics', extra.chapterId] })
        if (type === 'content') q.invalidateQueries({ queryKey: ['cb-contents', extra.topicId] })
        if (type === 'quiz') q.invalidateQueries({ queryKey: ['cb-quizzes', extra.topicId] })
        if (type === 'assignment') q.invalidateQueries({ queryKey: ['cb-assignments', extra.topicId] })
    }

    const saveMutation = useMutation({
        mutationFn: ({ type, instance, payload, extra }) => {
            const withParents = { ...payload }
            if (type === 'subject') withParents.course = courseId
            if (type === 'chapter') withParents.subject = extra.subjectId
            if (type === 'topic') { withParents.subject = extra.subjectId; if (extra.chapterId) withParents.chapter = extra.chapterId }
            if (type === 'content') { withParents.topic = extra.topicId; withParents.subject = extra.subjectId }
            if (type === 'quiz') withParents.topic = extra.topicId
            if (type === 'assignment') { withParents.topic = extra.topicId; withParents.subject = extra.subjectId; withParents.course = courseId }
            const map = {
                exam: [svc.updateExam, svc.createExam],
                subject: [svc.updateSubject, svc.createSubject],
                chapter: [svc.updateChapter, svc.createChapter],
                topic: [svc.updateTopic, svc.createTopic],
                content: [svc.updateContent, svc.createContent],
                quiz: [svc.updateQuiz, svc.createQuiz],
                assignment: [svc.updateAssignment, svc.createAssignment],
            }
            const [update, create] = map[type]
            return instance ? update(instance.id, withParents) : create(withParents)
        },
        onSuccess: (_d, vars) => {
            toast.success(`${vars.type === 'exam' ? 'Course' : vars.type[0].toUpperCase() + vars.type.slice(1)} ${vars.instance ? 'saved' : 'created'}`)
            invalidateFor(vars.type, vars.extra)
            setModal(null)
        },
        onError: (err) => toast.error(formatApiError(err)),
    })

    const deleteMutation = useMutation({
        mutationFn: ({ type, instance }) => {
            const map = { subject: svc.deleteSubject, chapter: svc.deleteChapter, topic: svc.deleteTopic, content: svc.deleteContent, quiz: svc.deleteQuiz, question: svc.deleteQuestion, assignment: svc.deleteAssignment }
            return map[type](instance.id)
        },
        onSuccess: (_d, vars) => {
            toast.success('Deleted')
            // broad invalidation covering the affected level
            queryClient.invalidateQueries({ queryKey: ['cb-subjects', courseId] })
            queryClient.invalidateQueries({ predicate: (query) => ['cb-chapters', 'cb-topics', 'cb-contents', 'cb-quizzes', 'cb-questions', 'cb-assignments'].includes(query.queryKey[0]) })
            if (vars.type === 'topic' && sel.topicId === vars.instance.id) setSel({ subjectId: null, chapterId: null, topicId: null, topic: null })
            setDel(null)
        },
        onError: (err) => toast.error(formatApiError(err)),
    })

    if (isLoading) return <Loading fullScreen />

    return (
        <div className="space-y-5">
            {/* Header */}
            <div className="flex items-center gap-3">
                <button onClick={() => navigate(backTo)} className="p-2 rounded-lg hover:bg-surface-100 dark:hover:bg-surface-800 transition-colors" aria-label="Back to courses">
                    <ArrowLeft size={20} />
                </button>
                <span className="w-9 h-9 rounded-xl flex items-center justify-center text-white shrink-0" style={{ backgroundColor: course?.color || '#f97316' }}>
                    <GraduationCap size={18} />
                </span>
                <div className="min-w-0 flex-1">
                    <h1 className="text-xl sm:text-2xl font-display font-bold truncate">{course?.name || 'Course'}</h1>
                    <p className="text-xs sm:text-sm text-surface-500">Manage subjects, chapters, topics, content & quizzes</p>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                    {course && isAdmin && (
                        <button onClick={() => setThumbnailOpen(true)} className="btn-secondary text-xs px-3 py-1.5 hidden sm:inline-flex">
                            <ImageIcon className="w-3.5 h-3.5" /> Thumbnail
                        </button>
                    )}
                    {course && isAdmin && (
                        <button onClick={() => setInstructorsOpen(true)} className="btn-secondary text-xs px-3 py-1.5 hidden sm:inline-flex">
                            <Users className="w-3.5 h-3.5" /> Faculty
                        </button>
                    )}
                    {course && (
                        <button onClick={() => openModal('exam', course, {})} className="btn-secondary text-xs px-3 py-1.5 hidden sm:inline-flex">
                            <Pencil className="w-3.5 h-3.5" /> Edit course
                        </button>
                    )}
                    <button onClick={() => navigate(`/study/course/${courseId}`)} className="btn-secondary text-xs px-3 py-1.5">
                        <Eye className="w-3.5 h-3.5" /> <span className="hidden sm:inline">View as student</span>
                    </button>
                </div>
            </div>

            {/* Body: navigator + panel */}
            <div className="grid grid-cols-1 lg:grid-cols-[340px_1fr] gap-5 items-start">
                <Navigator courseId={courseId} sel={sel} onSelectTopic={onSelectTopic} openModal={openModal} askDelete={askDelete} />

                {sel.topic ? (
                    <TopicPanel topic={sel.topic} subjectId={sel.subjectId} subjectName={sel.subjectName} openModal={openModal} askDelete={askDelete} />
                ) : (
                    <div className="card p-10 flex flex-col items-center justify-center text-center min-h-[300px]">
                        <div className="w-14 h-14 rounded-2xl bg-primary-50 dark:bg-primary-900/20 flex items-center justify-center mb-3">
                            <HelpCircle className="w-7 h-7 text-primary-500" />
                        </div>
                        <h3 className="font-semibold text-surface-700 dark:text-surface-200">Select a topic to start editing</h3>
                        <p className="text-sm text-surface-500 mt-1 max-w-sm">
                            Expand a subject and chapter on the left, then pick a topic to add notes, videos, PDFs and quizzes — all in one focused place.
                        </p>
                    </div>
                )}
            </div>

            {/* Modals */}
            <AnimatePresence>
                {instructorsOpen && course && (
                    <InstructorsModal course={course} onClose={() => setInstructorsOpen(false)} onSaved={() => queryClient.invalidateQueries({ queryKey: ['cb-courses'] })} />
                )}
                {thumbnailOpen && course && (
                    <ThumbnailModal course={course} onClose={() => setThumbnailOpen(false)} onSaved={() => { queryClient.invalidateQueries({ queryKey: ['cb-courses'] }); queryClient.invalidateQueries({ queryKey: ['availableCourses'] }) }} />
                )}
                {modal && (
                    <EntityModal
                        type={modal.type}
                        instance={modal.instance}
                        defaults={modal.extra?.defaults}
                        saving={saveMutation.isPending}
                        onClose={() => setModal(null)}
                        onSubmit={(payload) => saveMutation.mutate({ type: modal.type, instance: modal.instance, payload, extra: modal.extra })}
                    />
                )}
                {del && (
                    <ConfirmDialog
                        label={del.label}
                        deleting={deleteMutation.isPending}
                        onCancel={() => setDel(null)}
                        onConfirm={() => deleteMutation.mutate({ type: del.type, instance: del.instance })}
                    />
                )}
            </AnimatePresence>
        </div>
    )
}

export default CourseManager
