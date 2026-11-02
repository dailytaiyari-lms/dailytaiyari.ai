import { useEffect, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Baby, Loader2, ShieldCheck, UserRoundCog } from 'lucide-react'
import toast from 'react-hot-toast'

import { tenantAdminService } from '../../services/tenantAdminService'

const Toggle = ({ checked, disabled, onChange, label }) => (
  <button
    type="button"
    role="switch"
    aria-checked={checked}
    aria-label={label}
    disabled={disabled}
    onClick={onChange}
    className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors disabled:opacity-50 ${checked ? 'bg-primary-500' : 'bg-surface-300 dark:bg-surface-700'}`}
  >
    <span className={`h-4 w-4 rounded-full bg-white transition-transform ${checked ? 'translate-x-6' : 'translate-x-1'}`} />
  </button>
)

const RegistrationSettings = ({ settings }) => {
  const queryClient = useQueryClient()
  const available = settings?.available_registration_fields || []
  const [value, setValue] = useState({ fields: {}, guardian_consent: { enabled: false } })

  useEffect(() => {
    if (settings?.registration_settings) setValue(settings.registration_settings)
  }, [settings])

  const mutation = useMutation({
    mutationFn: (registrationSettings) => tenantAdminService.updateRegistrationSettings(registrationSettings),
    onSuccess: (data) => {
      queryClient.setQueryData(['tenantSettings'], data)
      setValue(data.registration_settings)
      toast.success('Registration settings saved')
    },
    onError: (error) => {
      if (settings?.registration_settings) setValue(settings.registration_settings)
      toast.error(error?.response?.data?.detail || 'Could not save registration settings')
    },
  })

  const save = (next) => {
    setValue(next)
    mutation.mutate({
      ...next.fields,
      guardian_consent: next.guardian_consent,
    })
  }

  const toggleEnabled = (key) => {
    const current = value.fields?.[key] || {}
    const enabled = !current.enabled
    save({
      ...value,
      fields: {
        ...value.fields,
        [key]: { enabled, required: enabled ? Boolean(current.required) : false },
      },
    })
  }

  const toggleRequired = (key) => {
    const current = value.fields?.[key] || {}
    save({
      ...value,
      fields: {
        ...value.fields,
        [key]: { enabled: true, required: !current.required },
      },
    })
  }

  const toggleGuardian = () => {
    const enabled = !value.guardian_consent?.enabled
    save({
      ...value,
      guardian_consent: { enabled },
      fields: {
        ...value.fields,
        ...(enabled ? { date_of_birth: { enabled: true, required: true } } : {}),
      },
    })
  }

  if (!available.length) {
    return <div className="card p-6 flex items-center justify-center gap-2 text-surface-500"><Loader2 className="w-4 h-4 animate-spin" /> Loading registration settings…</div>
  }

  return (
    <div className="space-y-6">
      <div className="card p-6">
        <div className="flex items-center gap-2">
          <UserRoundCog className="w-5 h-5 text-primary-500" />
          <h3 className="text-lg font-bold">Registration fields</h3>
        </div>
        <p className="text-sm text-surface-500 mt-1">
          Choose which standard details students provide. Field names, choices and validation stay consistent across the platform.
        </p>
      </div>

      <div className="card divide-y divide-surface-100 dark:divide-surface-800">
        {available.map((field) => {
          const config = value.fields?.[field.key] || {}
          const locked = field.key === 'date_of_birth' && value.guardian_consent?.enabled
          return (
            <div key={field.key} className="p-5 flex flex-col gap-3 sm:flex-row sm:items-center">
              <div className="min-w-0 flex-1">
                <p className="font-semibold text-surface-800 dark:text-surface-200">{field.label}</p>
                <p className="text-xs text-surface-500 mt-0.5">Standard {field.type} field</p>
              </div>
              <div className="flex items-center gap-5">
                <label className="flex items-center gap-2 text-sm text-surface-600 dark:text-surface-300">
                  Required
                  <Toggle
                    label={`${field.label} required`}
                    checked={Boolean(config.required)}
                    disabled={!config.enabled || locked || mutation.isPending}
                    onChange={() => toggleRequired(field.key)}
                  />
                </label>
                <label className="flex items-center gap-2 text-sm text-surface-600 dark:text-surface-300">
                  Enabled
                  <Toggle
                    label={`${field.label} enabled`}
                    checked={Boolean(config.enabled)}
                    disabled={locked || mutation.isPending}
                    onChange={() => toggleEnabled(field.key)}
                  />
                </label>
              </div>
            </div>
          )
        })}
      </div>

      <div className="card p-6 flex items-start gap-4">
        <div className="w-10 h-10 rounded-xl bg-violet-100 dark:bg-violet-900/30 flex items-center justify-center shrink-0">
          <Baby className="w-5 h-5 text-violet-600" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="font-semibold">Parent approval for students under 18</p>
          <p className="text-sm text-surface-500 mt-1">
            Date of birth becomes required. Underage students provide a parent or guardian email, and the account stays pending until the guardian approves it.
          </p>
          {value.guardian_consent?.enabled && (
            <p className="text-xs text-success-600 mt-2 flex items-center gap-1">
              <ShieldCheck className="w-3.5 h-3.5" /> Date of birth and guardian approval are enforced automatically.
            </p>
          )}
        </div>
        <Toggle
          label="Parent approval for underage students"
          checked={Boolean(value.guardian_consent?.enabled)}
          disabled={mutation.isPending}
          onChange={toggleGuardian}
        />
      </div>
    </div>
  )
}

export default RegistrationSettings
