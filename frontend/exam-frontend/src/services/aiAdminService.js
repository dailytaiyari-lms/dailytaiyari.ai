import api from './api'

/**
 * Tenant-admin API for the "AI Features" screen: LLM provider credentials,
 * behaviour/spend guardrails, and the usage & cost report.
 */
export const aiAdminService = {
    // Providers + catalog + settings + platform grant, in one call.
    getProviders: async () => {
        const response = await api.get('/tenant-admin/ai/providers/')
        return response.data
    },

    // Create or update one provider. Leave `api_key` blank to keep the stored key.
    saveProvider: async (payload) => {
        const response = await api.put('/tenant-admin/ai/providers/', payload)
        return response.data
    },

    deleteProvider: async (provider) => {
        const response = await api.delete('/tenant-admin/ai/providers/', {
            params: { provider },
        })
        return response.data
    },

    // Sends a tiny prompt through the provider to verify the credentials work.
    testProvider: async (payload) => {
        const response = await api.post('/tenant-admin/ai/providers/test/', payload)
        return response.data
    },

    updateSettings: async (payload) => {
        const response = await api.patch('/tenant-admin/ai/settings/', payload)
        return response.data
    },

    // Models the platform has granted this academy, and the academy's own
    // choice of which to use. No API key involved — this is the path for a
    // non-technical admin.
    getIncludedModels: async () => {
        const response = await api.get('/tenant-admin/ai/included-models/')
        return response.data
    },

    saveIncludedModels: async (payload) => {
        const response = await api.put('/tenant-admin/ai/included-models/', payload)
        return response.data
    },

    getUsage: async (days = 30) => {
        const response = await api.get('/tenant-admin/ai/usage/', { params: { days } })
        return response.data
    },
}

export default aiAdminService
