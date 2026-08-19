import api from './api'

const BASE = '/tenant-admin/intelligence'

export const insightsService = {
  getOverview: async (courseId) => {
    const response = await api.get(`${BASE}/overview/`, { params: { course: courseId } })
    return response.data
  },

  getAssessmentReport: async (kind, assessmentId) => {
    const response = await api.get(`${BASE}/assessments/${kind}/${assessmentId}/report/`)
    return response.data
  },

  getStudentDiagnosis: async (studentId, courseId) => {
    const response = await api.get(`${BASE}/students/${studentId}/diagnosis/`, {
      params: courseId ? { course: courseId } : {},
    })
    return response.data
  },

  getGeneratedItems: async (courseId) => {
    const response = await api.get(`${BASE}/generated-items/`, {
      params: courseId ? { course: courseId } : {},
    })
    return response.data
  },

  retireGeneratedItem: async (id) => {
    const response = await api.post(`${BASE}/generated-items/`, { id })
    return response.data
  },

  getGenerationJobs: async () => {
    const response = await api.get(`${BASE}/generation-jobs/`)
    return response.data
  },

  runTagging: async () => {
    const response = await api.post(`${BASE}/tagging/run/`)
    return response.data
  },

  getPracticeConfig: async (courseId) => {
    const response = await api.get(`${BASE}/courses/${courseId}/practice-config/`)
    return response.data
  },

  updatePracticeConfig: async (courseId, payload) => {
    const response = await api.patch(`${BASE}/courses/${courseId}/practice-config/`, payload)
    return response.data
  },
}
