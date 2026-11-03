import axios from 'axios'

const API_BASE_URL = import.meta.env.VITE_API_URL || '/api/v1'
const TENANT_ID = import.meta.env.VITE_TENANT_ID

// Exported for the streaming endpoints, which use raw fetch() and therefore
// can't rely on the axios instance's default headers / interceptors below.
export { API_BASE_URL, TENANT_ID }

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
    ...(TENANT_ID ? { 'X-Tenant-ID': TENANT_ID } : {})
  },
})

export const tenantApi = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
    ...(TENANT_ID ? { 'X-Tenant-ID': TENANT_ID } : {})
  },
})

// Request interceptor - add auth token
api.interceptors.request.use(
  (config) => {
    const authData = localStorage.getItem('auth-storage')
    if (authData) {
      const { state } = JSON.parse(authData)
      if (state?.tokens?.access) {
        config.headers.Authorization = `Bearer ${state.tokens.access}`
      }
    }
    return config
  },
  (error) => Promise.reject(error)
)

// Response interceptor - handle token refresh
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config

    // Suspended account: keep the session, flip the flag so the blocking
    // overlay renders app-wide. Do NOT logout or redirect.
    if (error.response?.status === 403 && error.response?.data?.code === 'account_suspended') {
      import('../context/authStore')
        .then(({ useAuthStore }) => useAuthStore.getState().markSuspended())
        .catch(() => {})
      return Promise.reject(error)
    }

    // If 401 and not already retrying, try to refresh token
    if (error.response?.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true

      const authData = localStorage.getItem('auth-storage')
      if (authData) {
        const { state } = JSON.parse(authData)
        if (state?.tokens?.refresh) {
          try {
            const response = await axios.post(
              `${API_BASE_URL}/auth/refresh/`,
              { refresh: state.tokens.refresh }
            )

            const newAccess = response.data.access

            // Update stored tokens
            const newState = {
              ...state,
              tokens: { ...state.tokens, access: newAccess },
            }
            localStorage.setItem(
              'auth-storage',
              JSON.stringify({ state: newState })
            )

            // Retry original request
            originalRequest.headers.Authorization = `Bearer ${newAccess}`
            return api(originalRequest)
          } catch (refreshError) {
            // Refresh failed, logout user
            localStorage.removeItem('auth-storage')
            window.location.href = '/login'
            return Promise.reject(refreshError)
          }
        }
      }
    }

    return Promise.reject(error)
  }
)

export default api
