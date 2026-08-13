import api from './api'

const BASE = '/tenant-admin/mock-ai'

/**
 * AI Mock Studio API.
 *
 * Same two rules as the course studio:
 *
 *  1. `generate`, `refine` and `regenerate` never touch a mock test — they only
 *     fill the job's draft. `apply` is the single writing endpoint and it
 *     refuses to run without `confirm: true`.
 *  2. Generation runs on a worker. Those three calls answer 202 with a job in
 *     `pending`, and the caller polls `getJob` until the status leaves
 *     `pending`/`generating` — see `useGenerationJob`. Because the job lives on
 *     the server, an admin can navigate away and still find the run in progress.
 */
export const mockAiService = {
    // Providers, models, courses, question types and composer defaults.
    getOptions: async () => {
        const response = await api.get(`${BASE}/options/`)
        return response.data
    },

    // Cheap probe used to gate the "Generate with AI" entry points.
    getHealth: async () => {
        const response = await api.get(`${BASE}/health/`)
        return response.data
    },

    // Subject → chapter → topic tree, for grounding a paper in a syllabus.
    getCourseSyllabus: async (courseId) => {
        const response = await api.get(`${BASE}/courses/${courseId}/syllabus/`)
        return response.data
    },

    // A saved paper rendered as a draft. Works for hand-typed papers too, which
    // is what makes "Modify with AI" available on every mock test.
    getMockSnapshot: async (mockTestId) => {
        const response = await api.get(`${BASE}/mock-tests/${mockTestId}/snapshot/`)
        return response.data
    },

    listJobs: async (params = {}) => {
        const response = await api.get(`${BASE}/jobs/`, { params })
        const data = response.data
        return Array.isArray(data) ? data : data?.results || []
    },

    getJob: async (jobId) => {
        const response = await api.get(`${BASE}/jobs/${jobId}/`)
        return response.data
    },

    // Produces a draft paper for review. Answers 502 with the failed job on error.
    generate: async (payload) => {
        const response = await api.post(`${BASE}/jobs/`, payload)
        return response.data
    },

    // Retry a failed job with its original prompt and blueprint.
    regenerate: async (jobId) => {
        const response = await api.post(`${BASE}/jobs/${jobId}/regenerate/`)
        return response.data
    },

    // Revise the draft from an instruction; the old draft survives a failure.
    refine: async (jobId, instruction) => {
        const response = await api.post(`${BASE}/jobs/${jobId}/refine/`, { instruction })
        return response.data
    },

    // Save the admin's hand-edits to the draft (re-normalised server-side).
    saveDraft: async (jobId, draft) => {
        const response = await api.patch(`${BASE}/jobs/${jobId}/`, { draft })
        return response.data
    },

    // The only call that writes. `confirm` must be true.
    apply: async (jobId, selection = null) => {
        const response = await api.post(`${BASE}/jobs/${jobId}/apply/`, {
            confirm: true,
            ...(selection ? { selection } : {}),
        })
        return response.data
    },

    discard: async (jobId) => {
        const response = await api.post(`${BASE}/jobs/${jobId}/discard/`)
        return response.data
    },

    deleteJob: async (jobId) => {
        await api.delete(`${BASE}/jobs/${jobId}/`)
        return true
    },
}

export default mockAiService
