import api from './api'

export const login = (email, password) =>
  api.post('/superadmin/auth/login/', { email, password }).then((r) => r.data)

export const fetchMe = () => api.get('/superadmin/auth/me/').then((r) => r.data)

export const fetchStats = () => api.get('/superadmin/stats/').then((r) => r.data)

export const fetchTenants = (params = {}) =>
  api.get('/superadmin/tenants/', { params }).then((r) => r.data)

export const createTenant = (payload) =>
  api.post('/superadmin/tenants/', payload).then((r) => r.data)

export const fetchTenant = (id) =>
  api.get(`/superadmin/tenants/${id}/`).then((r) => r.data)

export const updateTenant = (id, payload) =>
  api.patch(`/superadmin/tenants/${id}/`, payload).then((r) => r.data)

export const fetchAuditLogs = (params = {}) =>
  api.get('/superadmin/audit-logs/', { params }).then((r) => r.data)

// ── Phase 3: users ─────────────────────────────────────────────────────────
export const fetchUsers = (params = {}) =>
  api.get('/superadmin/users/', { params }).then((r) => r.data)

export const userAction = (id, action) =>
  api.post(`/superadmin/users/${id}/action/`, { action }).then((r) => r.data)

// ── Phase 3: support inbox (leads) ─────────────────────────────────────────
export const fetchLeads = (params = {}) =>
  api.get('/superadmin/leads/', { params }).then((r) => r.data)

export const updateLead = (type, id, payload) =>
  api.patch(`/superadmin/leads/${type}/${id}/`, payload).then((r) => r.data)

// ── Phase 3: announcements ─────────────────────────────────────────────────
export const fetchAnnouncements = (params = {}) =>
  api.get('/superadmin/announcements/', { params }).then((r) => r.data)

export const createAnnouncement = (payload) =>
  api.post('/superadmin/announcements/', payload).then((r) => r.data)

export const updateAnnouncement = (id, payload) =>
  api.patch(`/superadmin/announcements/${id}/`, payload).then((r) => r.data)

export const deleteAnnouncement = (id) =>
  api.delete(`/superadmin/announcements/${id}/`).then((r) => r.data)

// ── Platform-supplied LLMs ─────────────────────────────────────────────────
// These are the platform's own AI accounts: credentials we pay for and lend to
// tenants. API keys are write-only server-side, so responses only ever carry a
// masked hint.
export const fetchPlatformAI = () =>
  api.get('/superadmin/ai/providers/').then((r) => r.data)

export const createPlatformProvider = (payload) =>
  api.post('/superadmin/ai/providers/', payload).then((r) => r.data)

export const updatePlatformProvider = (id, payload) =>
  api.patch(`/superadmin/ai/providers/${id}/`, payload).then((r) => r.data)

export const deletePlatformProvider = (id) =>
  api.delete(`/superadmin/ai/providers/${id}/`).then((r) => r.data)

export const testPlatformProvider = (id, model) =>
  api.post(`/superadmin/ai/providers/${id}/test/`, { model }).then((r) => r.data)

export const createPlatformModel = (providerId, payload) =>
  api.post(`/superadmin/ai/providers/${providerId}/models/`, payload).then((r) => r.data)

export const updatePlatformModel = (id, payload) =>
  api.patch(`/superadmin/ai/models/${id}/`, payload).then((r) => r.data)

export const deletePlatformModel = (id) =>
  api.delete(`/superadmin/ai/models/${id}/`).then((r) => r.data)

export const fetchPlatformAIUsage = (days = 30) =>
  api.get('/superadmin/ai/usage/', { params: { days } }).then((r) => r.data)

export const fetchTenantAllocation = (tenantId) =>
  api.get(`/superadmin/tenants/${tenantId}/ai-allocation/`).then((r) => r.data)

export const saveTenantAllocation = (tenantId, payload) =>
  api.put(`/superadmin/tenants/${tenantId}/ai-allocation/`, payload).then((r) => r.data)
