import { useEffect, useState } from 'react'
import { ShieldCheck, X } from 'lucide-react'
import toast from 'react-hot-toast'

import api from '../../services/api'
import { useAuthStore } from '../../context/authStore'
import { useTenantStore } from '../../context/tenantStore'

const ExistingStudentConsentNotice = () => {
  const { user, isAuthenticated } = useAuthStore()
  const { tenant } = useTenantStore()
  const [status, setStatus] = useState(null)
  const [dismissed, setDismissed] = useState(false)
  const [saving, setSaving] = useState(false)
  const [dateOfBirth, setDateOfBirth] = useState('')
  const [guardian, setGuardian] = useState({
    guardian_name: '',
    guardian_email: '',
    guardian_phone: '',
    guardian_relationship: '',
  })

  const load = async () => {
    if (!isAuthenticated || !user || user.guardian_consent_required) return
    try {
      const response = await api.get('/auth/compliance-status/')
      setStatus(response.data)
      const key = `consent-reminder:${user.id}:${response.data.status}`
      setDismissed(sessionStorage.getItem(key) === 'dismissed')
    } catch {
      setStatus(null)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthenticated, user?.id, tenant?.registration_schema?.guardian_consent?.enabled])

  const dismiss = () => {
    if (user?.id && status?.status) {
      sessionStorage.setItem(`consent-reminder:${user.id}:${status.status}`, 'dismissed')
    }
    setDismissed(true)
  }

  const saveDateOfBirth = async () => {
    if (!dateOfBirth) return toast.error('Enter your date of birth')
    setSaving(true)
    try {
      const response = await api.post('/auth/compliance-status/', {
        action: 'save_date_of_birth',
        date_of_birth: dateOfBirth,
      })
      setStatus(response.data)
      setDismissed(false)
      if (response.data.status === 'not_required') toast.success('Date of birth saved')
    } catch (error) {
      toast.error(error.response?.data?.date_of_birth?.[0] || 'Could not save date of birth')
    } finally {
      setSaving(false)
    }
  }

  const requestApproval = async () => {
    setSaving(true)
    try {
      const response = await api.post('/auth/compliance-status/', {
        action: 'request_guardian_approval',
        ...guardian,
      })
      setStatus(response.data)
      setDismissed(false)
      toast.success('Approval email sent')
    } catch (error) {
      const data = error.response?.data || {}
      const first = Object.values(data)[0]
      toast.error(data.error || (Array.isArray(first) ? first[0] : first) || 'Could not send approval email')
    } finally {
      setSaving(false)
    }
  }

  const resend = async () => {
    setSaving(true)
    try {
      await api.post('/auth/guardian-consent/resend/')
      toast.success('A new approval email has been sent')
    } catch (error) {
      toast.error(error.response?.data?.error || 'Could not resend the approval email')
    } finally {
      setSaving(false)
    }
  }

  const current = status?.status
  if (
    !isAuthenticated ||
    user?.guardian_consent_required ||
    dismissed ||
    !current ||
    ['not_required', 'compliant'].includes(current)
  ) {
    return null
  }

  return (
    <div className="fixed inset-0 z-[9996] bg-surface-900/65 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="relative card max-w-lg w-full p-6 sm:p-8">
        <button type="button" onClick={dismiss} aria-label="Remind me later" className="absolute right-4 top-4 p-2 text-surface-400 hover:text-surface-700">
          <X className="w-5 h-5" />
        </button>
        <div className="w-12 h-12 rounded-2xl bg-primary-100 dark:bg-primary-900/30 flex items-center justify-center mb-5">
          <ShieldCheck className="w-6 h-6 text-primary-600" />
        </div>

        {current === 'date_of_birth_required' && (
          <>
            <h2 className="text-xl font-bold">Confirm your date of birth</h2>
            <p className="text-sm text-surface-500 mt-2">
              {tenant?.name || 'Your institution'} needs this to determine whether parent or guardian approval is required.
            </p>
            <input type="date" value={dateOfBirth} onChange={(e) => setDateOfBirth(e.target.value)} className="input mt-5" />
            <button onClick={saveDateOfBirth} disabled={saving} className="btn-primary w-full py-3 mt-4">
              {saving ? 'Saving…' : 'Continue'}
            </button>
          </>
        )}

        {current === 'guardian_details_required' && (
          <>
            <h2 className="text-xl font-bold">Parent or guardian approval</h2>
            <p className="text-sm text-surface-500 mt-2">
              Add a parent or lawful guardian’s email. They’ll receive a short approval request from {tenant?.name || 'your institution'}.
            </p>
            <div className="grid sm:grid-cols-2 gap-3 mt-5">
              <input className="input" placeholder="Guardian name" value={guardian.guardian_name} onChange={(e) => setGuardian({ ...guardian, guardian_name: e.target.value })} />
              <select className="input" value={guardian.guardian_relationship} onChange={(e) => setGuardian({ ...guardian, guardian_relationship: e.target.value })}>
                <option value="">Relationship</option>
                <option value="parent">Parent</option>
                <option value="legal_guardian">Legal guardian</option>
                <option value="other">Other</option>
              </select>
              <input type="email" className="input sm:col-span-2" placeholder="Guardian email" value={guardian.guardian_email} onChange={(e) => setGuardian({ ...guardian, guardian_email: e.target.value })} />
              <input type="tel" className="input sm:col-span-2" placeholder="Guardian phone (optional)" value={guardian.guardian_phone} onChange={(e) => setGuardian({ ...guardian, guardian_phone: e.target.value })} />
            </div>
            <button onClick={requestApproval} disabled={saving} className="btn-primary w-full py-3 mt-4">
              {saving ? 'Sending…' : 'Send approval request'}
            </button>
          </>
        )}

        {current === 'guardian_approval_pending' && (
          <>
            <h2 className="text-xl font-bold">Waiting for parent approval</h2>
            <p className="text-sm text-surface-500 mt-2">
              We sent an approval request to <span className="font-medium">{status.guardian_email}</span>.
              You may continue using your account while it is pending.
            </p>
            <button onClick={resend} disabled={saving} className="btn-primary w-full py-3 mt-5">
              {saving ? 'Sending…' : 'Resend approval email'}
            </button>
          </>
        )}

        <button type="button" onClick={dismiss} className="w-full mt-3 py-2 text-sm text-surface-500 hover:text-surface-700">
          Remind me later
        </button>
      </div>
    </div>
  )
}

export default ExistingStudentConsentNotice
