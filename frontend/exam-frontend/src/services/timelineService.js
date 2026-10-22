import api, { API_BASE_URL, TENANT_ID } from './api'

const TIMELINE_URL = '/intelligence/timeline/'

// fetch() with keepalive survives page hide/unload, which axios can't do —
// so it has to rebuild the auth + tenant headers the axios instance adds.
const authHeaders = () => {
  try {
    const raw = localStorage.getItem('auth-storage')
    const token = raw && JSON.parse(raw)?.state?.tokens?.access
    return token ? { Authorization: `Bearer ${token}` } : {}
  } catch {
    return {}
  }
}

export const timelineService = {
  // payload: { attempt_kind, attempt_id | parent_id, session_id, elapsed_ms, truncated, events }
  sync: (payload) => api.post(TIMELINE_URL, payload),

  // body: the already-serialized JSON payload string
  syncOnUnload: (body) => {
    try {
      fetch(`${API_BASE_URL}${TIMELINE_URL}`, {
        method: 'POST',
        keepalive: true,
        headers: {
          'Content-Type': 'application/json',
          ...(TENANT_ID ? { 'X-Tenant-ID': TENANT_ID } : {}),
          ...authHeaders(),
        },
        body,
      }).catch(() => {})
    } catch {
      /* best effort */
    }
  },

  getSelfReports: async (attemptKind, attemptId) => {
    const response = await api.get('/intelligence/self-report/', {
      params: { attempt_kind: attemptKind, attempt_id: attemptId },
    })
    return response.data
  },

  // payload: { attempt_kind, attempt_id, item_kind: 'bank' | 'item', item_id, choice }
  saveSelfReport: async (payload) => {
    const response = await api.post('/intelligence/self-report/', payload)
    return response.data
  },
}
