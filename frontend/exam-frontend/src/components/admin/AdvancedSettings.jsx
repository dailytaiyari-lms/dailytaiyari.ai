import { useEffect, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Cake, Loader2, Mail, Sparkles, UserCheck, Users } from 'lucide-react'
import toast from 'react-hot-toast'

import { tenantAdminService } from '../../services/tenantAdminService'

/**
 * Settings → Advanced.
 *
 * Behaviour switches that tune how the platform acts in the background, as
 * opposed to the Features tab which shows/hides whole product areas. Today this
 * is the automated birthday greetings; the list is driven by
 * `available_advanced_settings` from the API, so new switches added on the
 * backend appear here without a frontend change.
 */

// Per-key presentation. Keys the backend sends that aren't listed here still
// render, just with the generic icon.
const SETTING_META = {
    birthday_greetings: { Icon: Cake, accent: 'text-pink-500', bg: 'bg-pink-100 dark:bg-pink-900/30' },
    birthday_email_student: { Icon: Mail, accent: 'text-blue-500', bg: 'bg-blue-100 dark:bg-blue-900/30' },
    birthday_include_past_students: { Icon: UserCheck, accent: 'text-emerald-500', bg: 'bg-emerald-100 dark:bg-emerald-900/30' },
    birthday_notify_admins: { Icon: Users, accent: 'text-violet-500', bg: 'bg-violet-100 dark:bg-violet-900/30' },
    birthday_email_admins: { Icon: Mail, accent: 'text-amber-500', bg: 'bg-amber-100 dark:bg-amber-900/30' },
}

// Sub-switches are meaningless while their parent is off, so they grey out and
// stop responding until it's turned back on.
const DEPENDS_ON = {
    birthday_email_student: 'birthday_greetings',
    birthday_include_past_students: 'birthday_greetings',
    birthday_notify_admins: 'birthday_greetings',
    birthday_email_admins: 'birthday_greetings',
}

const Toggle = ({ checked, disabled, onChange, label }) => (
    <button
        role="switch"
        aria-checked={checked}
        aria-label={label}
        onClick={onChange}
        disabled={disabled}
        className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${checked ? 'bg-primary-500' : 'bg-surface-300 dark:bg-surface-700'}`}
    >
        <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${checked ? 'translate-x-6' : 'translate-x-1'}`} />
    </button>
)

const AdvancedSettings = ({ settings }) => {
    const queryClient = useQueryClient()
    const available = settings?.available_advanced_settings || []
    const [values, setValues] = useState({})

    useEffect(() => {
        if (settings?.advanced_settings) setValues(settings.advanced_settings)
    }, [settings])

    const mutation = useMutation({
        mutationFn: (payload) => tenantAdminService.updateAdvancedSettings(payload),
        onSuccess: (data) => {
            queryClient.setQueryData(['tenantSettings'], data)
            if (data?.advanced_settings) setValues(data.advanced_settings)
            toast.success('Settings saved')
        },
        onError: (error) => {
            // Roll back the optimistic flip so the UI matches what is stored.
            if (settings?.advanced_settings) setValues(settings.advanced_settings)
            toast.error(error?.response?.data?.detail || 'Could not save settings')
        },
    })

    const toggle = (key) => {
        const next = !values[key]
        setValues((v) => ({ ...v, [key]: next }))
        mutation.mutate({ [key]: next })
    }

    if (!available.length) {
        return (
            <div className="card p-6">
                <div className="flex items-center justify-center gap-2 text-surface-500">
                    <Loader2 className="w-4 h-4 animate-spin" /> Loading advanced settings…
                </div>
            </div>
        )
    }

    return (
        <div className="space-y-6">
            <div className="card p-6 space-y-1">
                <div className="flex items-center gap-2">
                    <Sparkles className="w-5 h-5 text-primary-500" />
                    <h3 className="text-lg font-bold text-surface-900 dark:text-white">Birthday Greetings</h3>
                </div>
                <p className="text-sm text-surface-500">
                    Wish your students on their birthday, automatically. Anyone who has a date
                    of birth on their profile gets a celebratory in-app greeting on the day —
                    and, if you like, a branded email carrying your logo and institution name.
                    Past students are included too, which makes it a natural moment to invite
                    them back.
                </p>
            </div>

            <div className="card divide-y divide-surface-100 dark:divide-surface-800">
                {available.map((setting) => {
                    const meta = SETTING_META[setting.key] || { Icon: Sparkles, accent: 'text-primary-500', bg: 'bg-primary-100 dark:bg-primary-900/30' }
                    const { Icon } = meta
                    const parent = DEPENDS_ON[setting.key]
                    const blocked = Boolean(parent) && !values[parent]
                    const checked = Boolean(values[setting.key]) && !blocked

                    return (
                        <div
                            key={setting.key}
                            className={`flex items-start gap-4 p-5 transition-opacity ${blocked ? 'opacity-50' : ''} ${parent ? 'sm:pl-10' : ''}`}
                        >
                            <div className={`shrink-0 w-9 h-9 rounded-xl flex items-center justify-center ${meta.bg}`}>
                                <Icon className={`w-4.5 h-4.5 ${meta.accent}`} />
                            </div>
                            <div className="min-w-0 flex-1">
                                <p className="font-semibold text-surface-800 dark:text-surface-200">{setting.label}</p>
                                <p className="text-sm text-surface-500 mt-0.5">{setting.description}</p>
                            </div>
                            <Toggle
                                label={setting.label}
                                checked={checked}
                                disabled={blocked || mutation.isPending}
                                onChange={() => toggle(setting.key)}
                            />
                        </div>
                    )
                })}
            </div>

            <div className="card p-5 bg-surface-50/60 dark:bg-surface-900/40">
                <p className="text-sm text-surface-500">
                    <strong className="text-surface-700 dark:text-surface-300">Good to know:</strong>{' '}
                    greetings go out once per person per year and are only sent to students who
                    have filled in their date of birth. You can reword every birthday email from{' '}
                    <span className="font-medium text-surface-700 dark:text-surface-300">Settings → Email &amp; Notifications</span>.
                </p>
            </div>
        </div>
    )
}

export default AdvancedSettings
