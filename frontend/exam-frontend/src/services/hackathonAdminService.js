import api from './api'

const list = (res) => {
  const d = res.data
  return Array.isArray(d) ? d : d?.results || []
}

const BASE = '/hackathons/admin'

/** Tenant-admin hackathon management service. */
export const hackathonAdminService = {
  // ── events ────────────────────────────────────────────────────────────────
  getHackathons: async (params = {}) => list(await api.get(`${BASE}/hackathons/`, { params })),
  get: async (id) => (await api.get(`${BASE}/hackathons/${id}/`)).data,
  create: async (data) => (await api.post(`${BASE}/hackathons/`, data)).data,
  update: async (id, data) => (await api.patch(`${BASE}/hackathons/${id}/`, data)).data,
  remove: async (id) => (await api.delete(`${BASE}/hackathons/${id}/`)).data,
  overview: async (id) => (await api.get(`${BASE}/hackathons/${id}/overview/`)).data,

  // ── rounds ────────────────────────────────────────────────────────────────
  getStages: async (id) => (await api.get(`${BASE}/hackathons/${id}/stages/`)).data,
  createStage: async (id, data) =>
    (await api.post(`${BASE}/hackathons/${id}/stages/`, data)).data,
  reorderStages: async (id, ids) =>
    (await api.post(`${BASE}/hackathons/${id}/stages/reorder/`, { ids })).data,
  getStage: async (stageId) => (await api.get(`${BASE}/stages/${stageId}/`)).data,
  updateStage: async (stageId, data) =>
    (await api.patch(`${BASE}/stages/${stageId}/`, data)).data,
  deleteStage: async (stageId) => (await api.delete(`${BASE}/stages/${stageId}/`)).data,
  publishStageResults: async (stageId) =>
    (await api.post(`${BASE}/stages/${stageId}/publish-results/`)).data,

  // ── questions ─────────────────────────────────────────────────────────────
  getItems: async (stageId) => (await api.get(`${BASE}/stages/${stageId}/items/`)).data,
  createItem: async (stageId, data) =>
    (await api.post(`${BASE}/stages/${stageId}/items/`, data)).data,
  updateItem: async (itemId, data) => (await api.patch(`${BASE}/items/${itemId}/`, data)).data,
  deleteItem: async (itemId) => (await api.delete(`${BASE}/items/${itemId}/`)).data,
  reorderItems: async (stageId, ids) =>
    (await api.post(`${BASE}/stages/${stageId}/items/reorder/`, { ids })).data,

  // ── participants ──────────────────────────────────────────────────────────
  getRegistrations: async (id, params = {}) =>
    (await api.get(`${BASE}/hackathons/${id}/registrations/`, { params })).data,
  updateRegistration: async (id, regId, data) =>
    (await api.patch(`${BASE}/hackathons/${id}/registrations/${regId}/`, data)).data,
  exportUrl: (id) => `${BASE}/hackathons/${id}/registrations/export/`,

  getStageParticipants: async (stageId, params = {}) =>
    (await api.get(`${BASE}/stages/${stageId}/participants/`, { params })).data,
  qualify: async (stageId, payload) =>
    (await api.post(`${BASE}/stages/${stageId}/qualify/`, payload)).data,

  getParticipation: async (participationId) =>
    (await api.get(`${BASE}/participations/${participationId}/`)).data,
  gradeParticipation: async (participationId, payload) =>
    (await api.post(`${BASE}/participations/${participationId}/grade/`, payload)).data,
  submissionFileUrl: (fileId) => `${BASE}/submission-files/${fileId}/download/`,

  // ── results & comms ───────────────────────────────────────────────────────
  declareWinners: async (id, payload) =>
    (await api.post(`${BASE}/hackathons/${id}/declare-winners/`, payload)).data,
  getAnnouncements: async (id) =>
    (await api.get(`${BASE}/hackathons/${id}/announcements/`)).data,
  announce: async (id, payload) =>
    (await api.post(`${BASE}/hackathons/${id}/announcements/`, payload)).data,
}

const AI = '/tenant-admin/hackathon-ai'

/** AI Hackathon Studio service — mirrors the course/mock studios. */
export const hackathonAiService = {
  options: async () => (await api.get(`${AI}/options/`)).data,
  health: async () => (await api.get(`${AI}/health/`)).data,
  stagesFor: async (hackathonId) =>
    (await api.get(`${AI}/hackathons/${hackathonId}/stages/`)).data,

  listJobs: async (params = {}) => list(await api.get(`${AI}/jobs/`, { params })),
  createJob: async (payload) => (await api.post(`${AI}/jobs/`, payload)).data,
  getJob: async (jobId) => (await api.get(`${AI}/jobs/${jobId}/`)).data,
  updateDraft: async (jobId, draft) => (await api.patch(`${AI}/jobs/${jobId}/`, { draft })).data,
  deleteJob: async (jobId) => (await api.delete(`${AI}/jobs/${jobId}/`)).data,
  refine: async (jobId, instruction) =>
    (await api.post(`${AI}/jobs/${jobId}/refine/`, { instruction })).data,
  regenerate: async (jobId) => (await api.post(`${AI}/jobs/${jobId}/regenerate/`)).data,
  apply: async (jobId, selection = {}) =>
    (await api.post(`${AI}/jobs/${jobId}/apply/`, { confirm: true, selection })).data,
  discard: async (jobId) => (await api.post(`${AI}/jobs/${jobId}/discard/`)).data,
}

export default hackathonAdminService
