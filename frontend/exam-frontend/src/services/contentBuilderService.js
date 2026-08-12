import api from './api'

// Unwrap DRF pagination -> always return a plain array
const list = (res) => {
  const d = res.data
  return Array.isArray(d) ? d : d?.results || []
}

const PAGE = { page_size: 2000 }

// Build a multipart request config when a payload carries a File (e.g. PDF
// upload); otherwise send as plain JSON.
const withFiles = (data) => {
  const hasFile = Object.values(data).some((v) => v instanceof File)
  if (!hasFile) return { body: data, config: undefined }
  const fd = new FormData()
  Object.entries(data).forEach(([k, v]) => {
    if (v === undefined || v === null) return
    fd.append(k, v instanceof File ? v : String(v))
  })
  return { body: fd, config: { headers: { 'Content-Type': undefined } } }
}

/**
 * Admin Content Builder service.
 * Full CRUD over the hierarchy: Exam -> Subject -> Chapter -> Topic -> Content.
 */
export const contentBuilderService = {
  // ---- Exams ----
  getExams: async () => list(await api.get('/courses/admin/courses/', { params: PAGE })),
  createExam: async (data) => (await api.post('/courses/admin/courses/', data)).data,
  updateExam: async (id, data) => (await api.patch(`/courses/admin/courses/${id}/`, data)).data,
  updateCourseThumbnail: async (id, file) => {
    const { body, config } = withFiles({ thumbnail: file })
    return (await api.patch(`/courses/admin/courses/${id}/`, body, config)).data
  },
  deleteExam: async (id) => api.delete(`/courses/admin/courses/${id}/`),
  copyExam: async (id, name) =>
    (await api.post(`/courses/admin/courses/${id}/copy/`, { name })).data,
  getInstructors: async () => (await api.get('/courses/admin/courses/instructors/')).data,

  // ---- Subjects ----
  getSubjects: async (courseId) =>
    list(await api.get('/courses/admin/subjects/', { params: { course: courseId, ...PAGE } })),
  createSubject: async (data) => (await api.post('/courses/admin/subjects/', data)).data,
  updateSubject: async (id, data) => (await api.patch(`/courses/admin/subjects/${id}/`, data)).data,
  deleteSubject: async (id) => api.delete(`/courses/admin/subjects/${id}/`),

  // ---- Chapters ----
  getChapters: async (subjectId) =>
    list(await api.get('/courses/admin/chapters/', { params: { subject: subjectId, ...PAGE } })),
  createChapter: async (data) => (await api.post('/courses/admin/chapters/', data)).data,
  updateChapter: async (id, data) => (await api.patch(`/courses/admin/chapters/${id}/`, data)).data,
  deleteChapter: async (id) => api.delete(`/courses/admin/chapters/${id}/`),

  // ---- Topics ----
  getTopics: async ({ chapterId, subjectId }) =>
    list(
      await api.get('/courses/admin/topics/', {
        params: { ...(chapterId ? { chapter: chapterId } : {}), ...(subjectId ? { subject: subjectId } : {}), ...PAGE },
      })
    ),
  createTopic: async (data) => (await api.post('/courses/admin/topics/', data)).data,
  updateTopic: async (id, data) => (await api.patch(`/courses/admin/topics/${id}/`, data)).data,
  deleteTopic: async (id) => api.delete(`/courses/admin/topics/${id}/`),

  // ---- Content ----
  getContents: async (topicId) =>
    list(await api.get('/content/admin/contents/', { params: { topic: topicId, ...PAGE } })),
  createContent: async (data) => {
    const { body, config } = withFiles(data)
    return (await api.post('/content/admin/contents/', body, config)).data
  },
  updateContent: async (id, data) => {
    const { body, config } = withFiles(data)
    return (await api.patch(`/content/admin/contents/${id}/`, body, config)).data
  },
  deleteContent: async (id) => api.delete(`/content/admin/contents/${id}/`),

  // ---- Quizzes ----
  getQuizzes: async (topicId) =>
    list(await api.get('/quiz/admin/quizzes/', { params: { topic: topicId, ...PAGE } })),
  createQuiz: async (data) => (await api.post('/quiz/admin/quizzes/', data)).data,
  updateQuiz: async (id, data) => (await api.patch(`/quiz/admin/quizzes/${id}/`, data)).data,
  deleteQuiz: async (id) => api.delete(`/quiz/admin/quizzes/${id}/`),

  // ---- Questions ----
  getQuestions: async (quizId) =>
    list(await api.get('/quiz/admin/questions/', { params: { quiz: quizId, ...PAGE } })),
  createQuestion: async (data) => (await api.post('/quiz/admin/questions/', data)).data,
  updateQuestion: async (id, data) => (await api.patch(`/quiz/admin/questions/${id}/`, data)).data,
  deleteQuestion: async (id) => api.delete(`/quiz/admin/questions/${id}/`),

  // ---- Media ----
  uploadImage: async (dataUrl) =>
    (await api.post('/content/admin/upload-image/', { image: dataUrl })).data,

  // ---- Assignments ----
  getAssignments: async (topicId) =>
    list(await api.get('/assignments/admin/assignments/', { params: { topic: topicId, ...PAGE } })),
  createAssignment: async (data) => {
    const { body, config } = withFiles(data)
    return (await api.post('/assignments/admin/assignments/', body, config)).data
  },
  updateAssignment: async (id, data) => {
    const { body, config } = withFiles(data)
    return (await api.patch(`/assignments/admin/assignments/${id}/`, body, config)).data
  },
  deleteAssignment: async (id) => api.delete(`/assignments/admin/assignments/${id}/`),
  getAssignment: async (id) =>
    (await api.get(`/assignments/admin/assignments/${id}/`)).data,
  getAssignmentSubmissions: async (id) =>
    (await api.get(`/assignments/admin/assignments/${id}/submissions/`)).data,
  getSubmission: async (id) =>
    (await api.get(`/assignments/admin/submissions/${id}/`)).data,
  gradeSubmission: async (id, data) =>
    (await api.patch(`/assignments/admin/submissions/${id}/`, data)).data,
  // Authenticated view-only stream of a student's submitted PDF (for PdfReader).
  submissionFileUrl: (id) => `/assignments/admin/submissions/${id}/file/`,

  // ---- Coding problems ----
  getCodingProblems: async (topicId) =>
    list(await api.get('/coding/admin/problems/', { params: { topic: topicId, ...PAGE } })),
  createCodingProblem: async (data) => (await api.post('/coding/admin/problems/', data)).data,
  updateCodingProblem: async (id, data) => (await api.patch(`/coding/admin/problems/${id}/`, data)).data,
  deleteCodingProblem: async (id) => api.delete(`/coding/admin/problems/${id}/`),
  getCodingProblem: async (id) => (await api.get(`/coding/admin/problems/${id}/`)).data,
  getCodingSubmissions: async (id) =>
    (await api.get(`/coding/admin/problems/${id}/submissions/`)).data,
  getCodingSubmission: async (id) =>
    (await api.get(`/coding/admin/submissions/${id}/`)).data,
  getCodingMeta: async () => (await api.get('/coding/meta/')).data,

  // ---- Live classes ----
  getLiveClasses: async (topicId) =>
    list(await api.get('/live-classes/admin/classes/', { params: { topic: topicId, ...PAGE } })),
  createLiveClass: async (data) => (await api.post('/live-classes/admin/classes/', data)).data,
  updateLiveClass: async (id, data) => (await api.patch(`/live-classes/admin/classes/${id}/`, data)).data,
  deleteLiveClass: async (id) => api.delete(`/live-classes/admin/classes/${id}/`),
  // Retry creating/updating the Zoom meeting behind a live class.
  syncLiveClassZoom: async (id) => (await api.post(`/live-classes/admin/classes/${id}/zoom-sync/`)).data,
  // Host-only start URL — fetched on demand so it never sits in list payloads.
  getLiveClassHostLink: async (id) => (await api.get(`/live-classes/admin/classes/${id}/host-link/`)).data,

  // Attendance register: { live_class, summary, results: [...] }.
  getLiveClassAttendance: async (id, params = {}) =>
    (await api.get(`/live-classes/admin/classes/${id}/attendance/`, { params })).data,
  syncLiveClassAttendance: async (id) =>
    (await api.post(`/live-classes/admin/classes/${id}/attendance/sync/`)).data,
  updateLiveClassAttendanceRow: async (id, rowId, data) =>
    (await api.patch(`/live-classes/admin/classes/${id}/attendance/${rowId}/`, data)).data,
  // Streams the CSV through the authenticated client, then triggers a download.
  downloadLiveClassAttendance: async (id, filename = 'attendance.csv') => {
    const res = await api.get(`/live-classes/admin/classes/${id}/attendance/export/`, {
      responseType: 'blob',
    })
    const url = window.URL.createObjectURL(new Blob([res.data], { type: 'text/csv' }))
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.URL.revokeObjectURL(url)
  },
}

export default contentBuilderService
