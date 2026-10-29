import api from './api'

export const progressService = {
  getMyProgress: async (courseId) => {
    const response = await api.get('/intelligence/my/progress/', {
      params: courseId ? { course: courseId } : {},
    })
    return response.data
  },
}
