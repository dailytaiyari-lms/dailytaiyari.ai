import api from './api'

const BASE = '/tenant-admin/course-ai'

/**
 * AI Course Studio API.
 *
 * Two things are worth knowing about this surface:
 *
 *  1. `generate` and `refine` never write course data — they only produce a
 *     draft on the job. `apply` is the single endpoint that touches the real
 *     course tables, and it refuses to run without `confirm: true`.
 *  2. Generation runs in the background. `generate` / `refine` / `regenerate`
 *     answer 202 with a job in `pending`, and the caller polls `getJob` until
 *     its status leaves `pending`/`generating` — see `useGenerationJob`.
 */
export const courseAiService = {
    // Providers, models, editable courses, limits and defaults for the composer.
    getOptions: async () => {
        const response = await api.get(`${BASE}/options/`)
        return response.data
    },

    // Cheap probe used to gate the "Generate with AI" entry points.
    getHealth: async () => {
        const response = await api.get(`${BASE}/health/`)
        return response.data
    },

    // Subject → chapter → topic tree, annotated with has_notes / has_quiz.
    getCourseTree: async (courseId) => {
        const response = await api.get(`${BASE}/courses/${courseId}/tree/`)
        return response.data
    },

    // Everything already attached to one topic — the focused studio opens on
    // this so "add more" is an informed choice rather than a guess.
    getTopicMaterial: async (courseId, topicId) => {
        const response = await api.get(`${BASE}/courses/${courseId}/topics/${topicId}/material/`)
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

    // Produces a draft for review. Returns 502 with the failed job on error.
    generate: async (payload) => {
        const response = await api.post(`${BASE}/jobs/`, payload)
        return response.data
    },

    // Retry a failed job with its original prompt, options and topics.
    regenerate: async (jobId) => {
        const response = await api.post(`${BASE}/jobs/${jobId}/regenerate/`)
        return response.data
    },

    // Regenerate from an instruction; the old draft survives a failure.
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

    // Fallback for browsers without the Web Speech API.
    transcribe: async (blob, filename = 'prompt.webm') => {
        const form = new FormData()
        form.append('audio', blob, filename)
        const response = await api.post(`${BASE}/transcribe/`, form, {
            headers: { 'Content-Type': 'multipart/form-data' },
        })
        return response.data
    },
}

export default courseAiService
