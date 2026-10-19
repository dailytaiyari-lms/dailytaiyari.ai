import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { timelineService } from '../../services/timelineService'
import { useTenantStore } from '../../context/tenantStore'

const CHOICES = [
  ['slipped', 'Knew it, slipped'],
  ['ran_out_of_time', 'Ran out of time'],
  ['guessed', 'Guessed'],
  ['didnt_know', "Didn't know"],
]

/** Existing self-reports + never-seen items for one attempt (feature-gated). */
export function useSelfReports(attemptKind, attemptId) {
  const enabled = useTenantStore((s) => s.isFeatureEnabled)('response_diagnosis') && !!attemptId
  const { data } = useQuery({
    queryKey: ['selfReports', attemptKind, attemptId],
    queryFn: () => timelineService.getSelfReports(attemptKind, attemptId),
    enabled,
    staleTime: Infinity,
  })
  return {
    enabled,
    reports: data?.reports || {},
    notSeen: new Set(data?.not_seen || []),
  }
}

/** One-tap "what happened?" under a wrong or unanswered review item. Optional. */
export default function WhatHappened({ attemptKind, attemptId, itemKind, itemId, initial }) {
  const [choice, setChoice] = useState(initial || null)
  const [saving, setSaving] = useState(false)

  useEffect(() => { setChoice(initial || null) }, [initial])

  const pick = async (value) => {
    if (saving || value === choice) return
    const previous = choice
    setChoice(value)
    setSaving(true)
    try {
      await timelineService.saveSelfReport({
        attempt_kind: attemptKind,
        attempt_id: attemptId,
        item_kind: itemKind,
        item_id: itemId,
        choice: value,
      })
    } catch {
      setChoice(previous)
      toast.error('Could not save that — try again.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="mt-3 flex flex-wrap items-center gap-2">
      <span className="text-xs text-surface-500">What happened?</span>
      {CHOICES.map(([value, label]) => (
        <button
          key={value}
          type="button"
          disabled={saving}
          onClick={() => pick(value)}
          className={`text-xs px-3 py-1 rounded-full border transition-colors ${
            choice === value
              ? 'bg-primary-500 border-primary-500 text-white'
              : 'border-surface-300 dark:border-surface-700 hover:bg-surface-100 dark:hover:bg-surface-800'
          }`}
        >
          {label}
        </button>
      ))}
    </div>
  )
}
