import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
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
  // Explicitly enabled in the loaded tenant config only (not while loading or
  // after a failed load), so no self-report request is ever sent otherwise.
  const optedIn = useTenantStore((s) => s.tenant?.features?.response_diagnosis === true)
  const enabled = optedIn && !!attemptId
  const { data, isSuccess } = useQuery({
    queryKey: ['selfReports', attemptKind, attemptId],
    queryFn: () => timelineService.getSelfReports(attemptKind, attemptId),
    enabled,
    staleTime: Infinity,
  })
  const notSeen = useMemo(() => new Set(data?.not_seen || []), [data])
  return {
    enabled,
    ready: isSuccess,
    reports: data?.reports || {},
    notSeen,
  }
}

/** One-tap "what happened?" under a wrong or unanswered review item. Optional. */
export default function WhatHappened({ attemptKind, attemptId, itemKind, itemId, initial }) {
  const [choice, setChoice] = useState(initial || null)
  const [saving, setSaving] = useState(false)
  const savingRef = useRef(false)
  const queryClient = useQueryClient()

  // Don't let a server-state sync clobber a choice that is mid-save.
  useEffect(() => {
    if (!savingRef.current) setChoice(initial || null)
  }, [initial])

  const pick = async (value) => {
    if (savingRef.current || value === choice) return
    const previous = choice
    setChoice(value)
    setSaving(true)
    savingRef.current = true
    try {
      await timelineService.saveSelfReport({
        attempt_kind: attemptKind,
        attempt_id: attemptId,
        item_kind: itemKind,
        item_id: itemId,
        choice: value,
      })
      queryClient.setQueryData(['selfReports', attemptKind, attemptId], (d) => ({
        ...(d || {}),
        reports: { ...(d?.reports || {}), [`${itemKind}:${itemId}`]: value },
        not_seen: d?.not_seen || [],
      }))
    } catch {
      setChoice(previous)
      toast.error('Could not save that — try again.')
    } finally {
      savingRef.current = false
      setSaving(false)
    }
  }

  return (
    <div
      role="group"
      aria-label="Not quite? Tell us what happened."
      className={`mt-3 flex flex-wrap items-center gap-2 transition-opacity ${
        saving ? 'opacity-60' : ''
      }`}
    >
      <span className="text-xs text-surface-500">Not quite? Tell us what happened.</span>
      {CHOICES.map(([value, label]) => (
        <button
          key={value}
          type="button"
          aria-pressed={choice === value}
          aria-disabled={saving}
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
