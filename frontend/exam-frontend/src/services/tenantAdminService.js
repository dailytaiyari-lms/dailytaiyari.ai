import api from './api'

export const tenantAdminService = {
    // Student Management
    createStudent: async (payload) => {
        const response = await api.post('/auth/tenant-students/', payload)
        return response.data
    },

    assignCourses: async (studentId, courseIds, sendEmail = true) => {
        const response = await api.post(`/auth/tenant-students/${studentId}/assign-courses/`, {
            course_ids: courseIds,
            send_email: sendEmail,
        })
        return response.data
    },

    removeCourse: async (studentId, courseId) => {
        const response = await api.post(`/auth/tenant-students/${studentId}/remove-course/`, {
            course_id: courseId,
        })
        return response.data
    },

    resetStudentPassword: async (studentId) => {
        const response = await api.post(`/auth/tenant-students/${studentId}/reset-password/`)
        return response.data
    },

    getStudents: async (params = {}) => {
        // Pull the full institution roster (high page_size) so search, filters
        // and CSV export operate over every student, not just the first page.
        const response = await api.get('/auth/tenant-students/', {
            params: { page_size: 5000, ...params },
        })
        return response.data
    },

    resetStudentProgress: async (studentId) => {
        const response = await api.post(`/auth/tenant-students/${studentId}/reset_progress/`)
        return response.data
    },

    toggleStudentStatus: async (studentId) => {
        const response = await api.post(`/auth/tenant-students/${studentId}/toggle_status/`)
        return response.data
    },

    updateStudent: async (studentId, data) => {
        const response = await api.patch(`/auth/tenant-students/${studentId}/`, data)
        return response.data
    },

    // Exam Enrollment Approvals
    getEnrollmentRequests: async (params = {}) => {
        const response = await api.get('/auth/enrollment-requests/', { params })
        return response.data
    },

    approveEnrollment: async (id) => {
        const response = await api.post(`/auth/enrollment-requests/${id}/approve/`)
        return response.data
    },

    rejectEnrollment: async (id, reason = '') => {
        const response = await api.post(`/auth/enrollment-requests/${id}/reject/`, { reason })
        return response.data
    },

    // Tenant Settings — branding (logo) + feature toggles
    getSettings: async () => {
        const response = await api.get('/tenant-admin/settings/')
        return response.data
    },

    updateFeatures: async (features) => {
        const response = await api.patch('/tenant-admin/settings/', { features })
        return response.data
    },

    // Branding text — institution name and tagline.
    updateBranding: async ({ name, tagline }) => {
        const payload = {}
        if (name !== undefined) payload.name = name
        if (tagline !== undefined) payload.tagline = tagline
        const response = await api.patch('/tenant-admin/settings/', payload)
        return response.data
    },

    // Login/register marketing panel content (heading, subtitle, stats).
    updateAuthPanel: async (authPanel) => {
        const response = await api.patch('/tenant-admin/settings/', { auth_panel: authPanel })
        return response.data
    },

    updateTheme: async (theme) => {
        const response = await api.patch('/tenant-admin/settings/', { theme })
        return response.data
    },

    updateShowName: async (showName) => {
        const response = await api.patch('/tenant-admin/settings/', { show_name: showName })
        return response.data
    },

    // Address(es) where admin notification emails (e.g. enrollment requests)
    // are delivered. Accepts a comma-separated list; blank falls back to admins.
    updateNotificationEmail: async (notificationEmail) => {
        const response = await api.patch('/tenant-admin/settings/', { notification_email: notificationEmail })
        return response.data
    },

    // Enrollment mode flags — request/approve vs. self-enrol (+ paid-via-payment).
    updateEnrollmentSettings: async ({ request_enrollment_free, request_enrollment_paid }) => {
        const payload = {}
        if (request_enrollment_free !== undefined) payload.request_enrollment_free = request_enrollment_free
        if (request_enrollment_paid !== undefined) payload.request_enrollment_paid = request_enrollment_paid
        const response = await api.patch('/tenant-admin/settings/', payload)
        return response.data
    },

    // Payment Gateways — one stored config per provider (Razorpay / Cashfree /
    // PayU); exactly one is active. Secrets are write-only. Returns
    // { gateways: [...], active_provider }.
    getPaymentGateway: async () => {
        const response = await api.get('/tenant-admin/payment-gateway/')
        return response.data
    },

    savePaymentGateway: async (payload) => {
        const response = await api.put('/tenant-admin/payment-gateway/', payload)
        return response.data
    },

    deletePaymentGateway: async (provider) => {
        const response = await api.delete('/tenant-admin/payment-gateway/', {
            params: provider ? { provider } : undefined,
        })
        return response.data
    },

    // Zoom — one Server-to-Server OAuth connection per tenant. Secrets are
    // write-only; the response carries has_* flags and the webhook URL to paste
    // into the Zoom app. Returns { zoom, webhook_url }.
    getZoomIntegration: async () => {
        const response = await api.get('/tenant-admin/zoom/')
        return response.data
    },

    saveZoomIntegration: async (payload) => {
        const response = await api.put('/tenant-admin/zoom/', payload)
        return response.data
    },

    // "Test connection" — asks Zoom for a token and the host account.
    testZoomIntegration: async () => {
        const response = await api.post('/tenant-admin/zoom/')
        return response.data
    },

    // Opens a short window in which the legacy (unscoped) webhook URL will
    // answer Zoom's URL-validation challenge. Only needed for Zoom apps
    // configured before tenant-scoped webhook URLs existed.
    startZoomWebhookVerification: async () => {
        const response = await api.post('/tenant-admin/zoom/', {
            action: 'start_verification',
        })
        return response.data
    },

    disconnectZoom: async () => {
        const response = await api.delete('/tenant-admin/zoom/')
        return response.data
    },

    // Sales dashboard — payment orders, summary aggregates, refunds & access.
    getSalesOrders: async (params = {}) => {
        const response = await api.get('/payments/admin/sales/orders/', {
            params: { page_size: 100, ...params },
        })
        return response.data
    },

    getSalesSummary: async (params = {}) => {
        const response = await api.get('/payments/admin/sales/summary/', { params })
        return response.data
    },

    refundOrder: async (id, { reason = '', amount } = {}) => {
        const payload = { reason }
        if (amount !== undefined && amount !== null && amount !== '') payload.amount = amount
        const response = await api.post(`/payments/admin/sales/orders/${id}/refund/`, payload)
        return response.data
    },

    revokeOrderAccess: async (id, reason = '') => {
        const response = await api.post(`/payments/admin/sales/orders/${id}/revoke/`, { reason })
        return response.data
    },

    restoreOrderAccess: async (id) => {
        const response = await api.post(`/payments/admin/sales/orders/${id}/revoke/`, { restore: true })
        return response.data
    },

    updateLogo: async (file) => {
        const formData = new FormData()
        formData.append('logo', file)
        const response = await api.patch('/tenant-admin/settings/', formData, {
            headers: { 'Content-Type': 'multipart/form-data' },
        })
        return response.data
    },

    updateFavicon: async (file) => {
        const formData = new FormData()
        formData.append('favicon', file)
        const response = await api.patch('/tenant-admin/settings/', formData, {
            headers: { 'Content-Type': 'multipart/form-data' },
        })
        return response.data
    },
}
