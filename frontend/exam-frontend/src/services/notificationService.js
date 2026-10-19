import api from './api'

/**
 * In-app notifications + admin announcements.
 *
 * The bell polls `getUnreadCount` for the badge; the notifications page and
 * dropdown use `getNotifications`. Admin announcement compose/list live under
 * the same resource (tenant-admin only on the backend).
 */
export const notificationService = {
    // --- Current user's notifications ---
    getNotifications: async (params = {}) => {
        const response = await api.get('/notifications/', { params })
        return response.data
    },

    getUnreadCount: async () => {
        const response = await api.get('/notifications/unread-count/')
        return response.data?.unread_count ?? 0
    },

    markRead: async (id) => {
        const response = await api.post(`/notifications/${id}/read/`)
        return response.data
    },

    markAllRead: async () => {
        const response = await api.post('/notifications/mark-all-read/')
        return response.data
    },

    // Pending birthday celebration for the current user (null when there is
    // none). Dismissing it is just marking the notification read.
    getBirthday: async () => {
        const response = await api.get('/notifications/birthday/')
        return response.data?.celebration ?? null
    },

    // --- Tenant-admin: announcements ---
    getAnnouncements: async (params = {}) => {
        const response = await api.get('/notifications/announcements/', { params })
        return response.data
    },

    createAnnouncement: async (payload) => {
        const response = await api.post('/notifications/announcements/', payload)
        return response.data
    },

    // --- Tenant-admin: editable email templates ---
    getEmailTemplates: async () => {
        const response = await api.get('/notifications/email-templates/')
        return response.data?.templates ?? []
    },

    updateEmailTemplate: async (type, payload) => {
        const response = await api.put(`/notifications/email-templates/${type}/`, payload)
        return response.data
    },

    resetEmailTemplate: async (type) => {
        const response = await api.delete(`/notifications/email-templates/${type}/`)
        return response.data
    },
}
