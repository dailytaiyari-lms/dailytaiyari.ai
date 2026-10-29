import api from './api'

export const diagnosisService = {
  // { notes: { 'bank:<id>' | 'item:<id>': 'note text' } } — the student's own attempt
  getMyAttemptNotes: async (kind, attemptId) => {
    const response = await api.get(`/intelligence/my/attempts/${kind}/${attemptId}/diagnosis/`)
    return response.data
  },
}
