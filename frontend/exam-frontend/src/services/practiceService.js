import api from './api'

export const practiceService = {
  // Practice sets
  getSets: async (status) => {
    const response = await api.get('/intelligence/practice/sets/', {
      params: status ? { status } : {},
    })
    return response.data
  },

  getSet: async (setId) => {
    const response = await api.get(`/intelligence/practice/sets/${setId}/`)
    return response.data
  },

  startSet: async (setId) => {
    const response = await api.post(`/intelligence/practice/sets/${setId}/start/`)
    return response.data
  },

  answerItem: async (setId, payload) => {
    // payload: { item_id, selected_options | numerical_answer, time_taken_seconds }
    const response = await api.post(`/intelligence/practice/sets/${setId}/answer/`, payload)
    return response.data
  },

  submitSet: async (setId) => {
    const response = await api.post(`/intelligence/practice/sets/${setId}/submit/`)
    return response.data
  },

  dismissSet: async (setId) => {
    const response = await api.post(`/intelligence/practice/sets/${setId}/dismiss/`)
    return response.data
  },

  refreshSuggestions: async () => {
    const response = await api.post('/intelligence/practice/refresh/')
    return response.data
  },

  // Concept mastery map
  getMastery: async (courseId) => {
    const response = await api.get('/intelligence/mastery/', {
      params: courseId ? { course: courseId } : {},
    })
    return response.data
  },
}
