import { useMemo } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import courseAiService from '../services/courseAiService'
import { notebookGenService } from '../services/notebookService'

/* ===========================================================================
 * useTopicAiJobs — what the AI is currently writing for one topic.
 *
 * Generation runs on the server, so an admin who closes the studio (or the
 * whole tab) would otherwise have no idea a draft was on its way. This asks the
 * two job APIs for anything still open on this topic — queued, being written,
 * or written and waiting to be reviewed — so the course builder can show that
 * work in the very tab the material will land in.
 *
 * Polling only runs while something is actually in flight; once every job has
 * settled it falls back to the normal cache lifetime.
 * ========================================================================= */

export const MATERIAL_TABS = {
    notes: 'content',
    quiz: 'quizzes',
    assignment: 'assignments',
    coding: 'coding',
    notebook: 'notebooks',
}

const LABELS = {
    notes: 'Reading notes',
    quiz: 'Practice quiz',
    assignment: 'Assignment',
    coding: 'Coding problem',
    notebook: 'Python notebook',
}

const POLL_MS = 4000

/** Which tabs a coursegen content job will write into. */
const materialsOf = (job) => {
    const picked = job?.options?.materials
    return Array.isArray(picked) && picked.length ? picked : ['notes']
}

/**
 * @param {string} courseId
 * @param {string} topicId
 * @param {boolean} enabled
 */
const useTopicAiJobs = (courseId, topicId, enabled = true) => {
    const queryClient = useQueryClient()
    const on = !!courseId && !!topicId && enabled

    const courseJobs = useQuery({
        queryKey: ['topic-ai-jobs', 'course', courseId, topicId],
        queryFn: () => courseAiService.listJobs({ course: courseId, topic: topicId, status: 'open' }),
        enabled: on,
        refetchInterval: (query) => (
            (query.state.data || []).some((job) => job.is_running) ? POLL_MS : false
        ),
    })

    const notebookJobs = useQuery({
        queryKey: ['topic-ai-jobs', 'notebook', courseId, topicId],
        queryFn: () => notebookGenService.listJobs({ course: courseId, topic: topicId, status: 'open' }),
        enabled: on,
        refetchInterval: (query) => (
            (query.state.data || []).some((job) => job.is_running) ? POLL_MS : false
        ),
    })

    // One flat list of "an AI job is producing this kind of material", so each
    // tab can render its own pending rows without knowing which API made them.
    const entries = useMemo(() => {
        const list = []
        for (const job of courseJobs.data || []) {
            for (const material of materialsOf(job)) {
                list.push({
                    key: `${job.id}:${material}`,
                    job,
                    isNotebook: false,
                    material,
                    tab: MATERIAL_TABS[material] || 'content',
                    label: LABELS[material] || material,
                })
            }
        }
        for (const job of notebookJobs.data || []) {
            list.push({
                key: `${job.id}:notebook`,
                job,
                isNotebook: true,
                material: 'notebook',
                tab: 'notebooks',
                label: LABELS.notebook,
            })
        }
        return list
    }, [courseJobs.data, notebookJobs.data])

    const byTab = useMemo(() => {
        const map = {}
        for (const entry of entries) {
            (map[entry.tab] = map[entry.tab] || []).push(entry)
        }
        return map
    }, [entries])

    const refresh = () => {
        queryClient.invalidateQueries({ queryKey: ['topic-ai-jobs'] })
    }

    return {
        entries,
        byTab,
        anyRunning: entries.some((entry) => entry.job.is_running),
        refresh,
    }
}

export default useTopicAiJobs
