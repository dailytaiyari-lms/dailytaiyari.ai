import api from './api'

const list = (res) => {
  const d = res.data
  return Array.isArray(d) ? d : d?.results || []
}

/**
 * Student-facing live-class service.
 * Live classes live under a Topic (mirrors coding problems). For now only
 * Google Meet classes exist; students join via `meeting_url`.
 */
export const liveClassService = {
  getByTopic: async (topicId) =>
    list(await api.get('/live-classes/classes/', { params: { topic: topicId } })),
  getClass: async (id) => (await api.get(`/live-classes/classes/${id}/`)).data,
  // Ask the backend for this student's join link. For a registered Zoom
  // meeting that is their personal URL (which is what makes attendance map to
  // them); for Google Meet it is the shared link. Either way the click is
  // recorded as an attendance signal.
  join: async (id) => (await api.post(`/live-classes/classes/${id}/join/`)).data,
}

export default liveClassService
