import api from './api'

const list = (res) => {
  const d = res.data
  return Array.isArray(d) ? d : d?.results || []
}

/** Student-facing hackathon service. Reading is public; everything else needs auth. */
export const hackathonService = {
  getHackathons: async (params = {}) => (await api.get('/hackathons/', { params })).data,
  get: async (id) => (await api.get(`/hackathons/${id}/`)).data,
  winners: async (id) => (await api.get(`/hackathons/${id}/winners/`)).data,
  leaderboard: async (id, params = {}) =>
    (await api.get(`/hackathons/${id}/leaderboard/`, { params })).data,

  myRegistrations: async () => list(await api.get('/hackathons/my-registrations/')),
  myProgress: async (id) => (await api.get(`/hackathons/${id}/my-progress/`)).data,

  register: async (id, payload) =>
    (await api.post(`/hackathons/${id}/register/`, payload)).data,
  withdraw: async (id) => (await api.post(`/hackathons/${id}/withdraw/`)).data,

  // ── rounds ────────────────────────────────────────────────────────────────
  getStage: async (id, stageId) =>
    (await api.get(`/hackathons/${id}/stages/${stageId}/`)).data,
  startStage: async (id, stageId) =>
    (await api.post(`/hackathons/${id}/stages/${stageId}/start/`)).data,
  runCode: async (id, stageId, payload) =>
    (await api.post(`/hackathons/${id}/stages/${stageId}/run/`, payload)).data,
  submitStage: async (id, stageId, answers) =>
    (await api.post(`/hackathons/${id}/stages/${stageId}/submit/`, { answers })).data,
  syncLab: async (id, stageId) =>
    (await api.post(`/hackathons/${id}/stages/${stageId}/sync-lab/`)).data,

  submitProject: async (id, stageId, { title, summary, repo_url, demo_url, video_url, files }) => {
    const fd = new FormData()
    if (title != null) fd.append('title', title)
    if (summary != null) fd.append('summary', summary)
    if (repo_url != null) fd.append('repo_url', repo_url)
    if (demo_url != null) fd.append('demo_url', demo_url)
    if (video_url != null) fd.append('video_url', video_url)
    ;(files || []).forEach((f) => { if (f instanceof File) fd.append('files', f) })
    return (await api.post(`/hackathons/${id}/stages/${stageId}/submit-project/`, fd, {
      headers: { 'Content-Type': undefined },
    })).data
  },

  fileUrl: (id, fileId) => `/hackathons/${id}/submission-files/${fileId}/download/`,
}

export default hackathonService
