import api from './api'

const list = (res) => {
  const d = res.data
  return Array.isArray(d) ? d : d?.results || []
}

/**
 * Student-facing notebook service.
 *
 * Notebooks live under a Topic (like coding problems and assignments). The
 * interactive kernel runs in the browser, so there is no "run" endpoint —
 * only draft autosave and graded submission.
 */
export const notebookService = {
  getByTopic: async (topicId) =>
    list(await api.get('/notebooks/notebooks/', { params: { topic: topicId } })),
  getByCourse: async (courseId) =>
    list(await api.get('/notebooks/notebooks/', { params: { course: courseId } })),
  getNotebook: async (id) => (await api.get(`/notebooks/notebooks/${id}/`)).data,

  getDraft: async (id) => (await api.get(`/notebooks/notebooks/${id}/draft/`)).data,
  saveDraft: async (id, { notebook_json, time_spent_seconds }) =>
    (await api.put(`/notebooks/notebooks/${id}/draft/`, {
      notebook_json,
      time_spent_seconds,
    })).data,
  resetDraft: async (id) => (await api.delete(`/notebooks/notebooks/${id}/draft/`)).data,

  submit: async (id, { notebook_json, provisional_results }) =>
    (await api.post(`/notebooks/notebooks/${id}/submit/`, {
      notebook_json,
      provisional_results,
    })).data,
  submissionStatus: async (id, submissionId) =>
    (await api.get(`/notebooks/notebooks/${id}/submissions/${submissionId}/`)).data,
  submissionNotebook: async (id, submissionId) =>
    (await api.get(`/notebooks/notebooks/${id}/submissions/${submissionId}/notebook/`)).data,
  mySubmissions: async (id) =>
    (await api.get(`/notebooks/notebooks/${id}/my-submissions/`)).data,

  meta: async () => (await api.get('/notebooks/meta/')).data,
}

/**
 * Tenant-admin authoring + grading service.
 */
export const notebookAdminService = {
  list: async (params) => list(await api.get('/notebooks/admin/notebooks/', { params })),
  get: async (id) => (await api.get(`/notebooks/admin/notebooks/${id}/`)).data,
  create: async (payload) => (await api.post('/notebooks/admin/notebooks/', payload)).data,
  update: async (id, payload) =>
    (await api.patch(`/notebooks/admin/notebooks/${id}/`, payload)).data,
  remove: async (id) => api.delete(`/notebooks/admin/notebooks/${id}/`),
  duplicate: async (id) =>
    (await api.post(`/notebooks/admin/notebooks/${id}/duplicate/`)).data,
  reorder: async (order) =>
    (await api.post('/notebooks/admin/notebooks/reorder/', { order })).data,

  importIpynb: async (file) => {
    const form = new FormData()
    form.append('file', file)
    return (await api.post('/notebooks/admin/notebooks/import-ipynb/', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })).data
  },
  testRun: async (id, notebook_json) =>
    (await api.post(`/notebooks/admin/notebooks/${id}/test-run/`, { notebook_json })).data,

  submissions: async (id) =>
    (await api.get(`/notebooks/admin/notebooks/${id}/submissions/`)).data,
  stats: async (id) => (await api.get(`/notebooks/admin/notebooks/${id}/stats/`)).data,
  getSubmission: async (submissionId) =>
    (await api.get(`/notebooks/admin/submissions/${submissionId}/`)).data,
  listSubmissions: async (params) =>
    list(await api.get('/notebooks/admin/submissions/', { params })),
  gradeSubmission: async (submissionId, { override_marks, feedback }) =>
    (await api.post(`/notebooks/admin/submissions/${submissionId}/grade/`, {
      override_marks,
      feedback,
    })).data,
  regradeSubmission: async (submissionId) =>
    (await api.post(`/notebooks/admin/submissions/${submissionId}/regrade/`)).data,

  datasets: async (notebookId) =>
    list(await api.get('/notebooks/admin/datasets/', { params: { notebook: notebookId } })),
  uploadDataset: async ({ notebook, filename, file, description }) => {
    const form = new FormData()
    form.append('notebook', notebook)
    form.append('filename', filename)
    form.append('file', file)
    if (description) form.append('description', description)
    return (await api.post('/notebooks/admin/datasets/', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })).data
  },
  deleteDataset: async (id) => api.delete(`/notebooks/admin/datasets/${id}/`),
}

export default notebookService
