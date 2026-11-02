import { useEffect, useState } from 'react'
import { MailCheck, LogOut } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'

import { useAuthStore } from '../../context/authStore'

const RegistrationPending = () => {
  const navigate = useNavigate()
  const { user, fetchGuardianConsentStatus, resendGuardianConsent, logout } = useAuthStore()
  const [status, setStatus] = useState(null)
  const [resending, setResending] = useState(false)

  useEffect(() => {
    let active = true
    const check = async () => {
      const result = await fetchGuardianConsentStatus()
      if (!active || !result) return
      setStatus(result)
      if (result.granted) navigate('/onboarding', { replace: true })
    }
    check()
    const timer = setInterval(check, 8000)
    return () => {
      active = false
      clearInterval(timer)
    }
  }, [fetchGuardianConsentStatus, navigate])

  const resend = async () => {
    setResending(true)
    const result = await resendGuardianConsent()
    setResending(false)
    if (result.success) toast.success('A new approval email has been sent')
    else toast.error(result.error)
  }

  return (
    <div className="min-h-screen bg-surface-50 dark:bg-surface-950 flex items-center justify-center p-4">
      <div className="card max-w-md w-full p-8 text-center">
        <div className="w-16 h-16 rounded-full bg-primary-100 dark:bg-primary-900/30 flex items-center justify-center mx-auto mb-5">
          <MailCheck className="w-8 h-8 text-primary-600" />
        </div>
        <h1 className="text-2xl font-bold">Waiting for parent approval</h1>
        <p className="text-surface-500 mt-3">
          Your email is verified. We sent a short approval request to{' '}
          <span className="font-medium">{status?.guardian_email || 'your parent or guardian'}</span>.
        </p>
        <button onClick={resend} disabled={resending} className="btn-primary w-full py-3 mt-7">
          {resending ? 'Sending…' : 'Resend approval email'}
        </button>
        <button onClick={() => { logout(); navigate('/login', { replace: true }) }} className="mt-4 inline-flex items-center gap-2 text-sm text-surface-500 hover:text-surface-700">
          <LogOut className="w-4 h-4" /> Sign out
        </button>
        {user?.email && <p className="text-xs text-surface-400 mt-5">Signed in as {user.email}</p>}
      </div>
    </div>
  )
}

export default RegistrationPending
