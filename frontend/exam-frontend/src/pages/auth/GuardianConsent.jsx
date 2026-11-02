import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { CheckCircle2, ShieldCheck } from 'lucide-react'
import toast from 'react-hot-toast'

import { tenantApi } from '../../services/api'
import { useTenantStore } from '../../context/tenantStore'

const GuardianConsent = () => {
  const { token } = useParams()
  const { tenant } = useTenantStore()
  const [details, setDetails] = useState(null)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [approved, setApproved] = useState(false)
  const [checks, setChecks] = useState({
    adult_confirmed: false,
    guardian_confirmed: false,
    privacy_accepted: false,
  })

  useEffect(() => {
    tenantApi.get(`/auth/guardian-consent/${token}/`)
      .then((response) => setDetails(response.data))
      .catch((err) => setError(err.response?.data?.error || 'This approval link is invalid.'))
  }, [token])

  const submit = async () => {
    if (!Object.values(checks).every(Boolean)) {
      toast.error('Please confirm all three statements')
      return
    }
    setSubmitting(true)
    try {
      await tenantApi.post(`/auth/guardian-consent/${token}/`, checks)
      setApproved(true)
    } catch (err) {
      toast.error(err.response?.data?.error || 'Could not approve the account')
    } finally {
      setSubmitting(false)
    }
  }

  if (error) {
    return <div className="card p-8 text-center"><h2 className="text-xl font-bold">Approval unavailable</h2><p className="text-surface-500 mt-2">{error}</p></div>
  }
  if (!details) {
    return <div className="card p-8 text-center text-surface-500">Loading approval request…</div>
  }
  if (approved) {
    return (
      <div className="card p-8 text-center">
        <CheckCircle2 className="w-14 h-14 text-success-500 mx-auto mb-4" />
        <h2 className="text-2xl font-bold">Account approved</h2>
        <p className="text-surface-500 mt-2">
          {details.student_name} can now continue with their {tenant?.name || details.tenant_name} account.
        </p>
      </div>
    )
  }

  const toggle = (key) => setChecks((value) => ({ ...value, [key]: !value[key] }))

  return (
    <div className="card p-6 sm:p-8">
      <div className="w-14 h-14 rounded-2xl bg-primary-100 dark:bg-primary-900/30 flex items-center justify-center mb-5">
        <ShieldCheck className="w-7 h-7 text-primary-600" />
      </div>
      <h2 className="text-2xl font-bold">Approve {details.student_name}’s account</h2>
      <p className="text-surface-500 mt-2">
        {details.tenant_name} will use the student’s information to manage their account,
        provide learning activities and progress reports, send essential notifications,
        and protect the account.
      </p>

      <div className="mt-6 space-y-4">
        {[
          ['adult_confirmed', 'I confirm that I am at least 18 years old.'],
          ['guardian_confirmed', `I confirm that I am ${details.student_name}’s parent or lawful guardian.`],
          ['privacy_accepted', `I have read ${details.tenant_name}’s Privacy Notice and consent to the processing described above.`],
        ].map(([key, label]) => (
          <label key={key} className="flex items-start gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={checks[key]}
              onChange={() => toggle(key)}
              className="mt-1 w-4 h-4 accent-primary-600"
            />
            <span className="text-sm text-surface-700 dark:text-surface-300">{label}</span>
          </label>
        ))}
        <a href="/privacy-policy" target="_blank" rel="noreferrer" className="inline-block text-sm text-primary-600 hover:underline">
          Read the complete Privacy Notice
        </a>
      </div>

      <button onClick={submit} disabled={submitting} className="btn-primary w-full py-3 mt-7">
        {submitting ? 'Approving…' : 'Verify and approve'}
      </button>
    </div>
  )
}

export default GuardianConsent
