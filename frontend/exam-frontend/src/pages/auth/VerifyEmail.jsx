import { useEffect, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { useAuthStore } from '../../context/authStore'
import toast from 'react-hot-toast'

const RESEND_COOLDOWN = 60

const VerifyEmail = () => {
  const location = useLocation()
  const navigate = useNavigate()
  const { verifyEmail, resendOtp, login, isLoading, error, clearError } = useAuthStore()

  const email = location.state?.email || ''
  const password = location.state?.password || ''

  const [code, setCode] = useState('')
  const [cooldown, setCooldown] = useState(RESEND_COOLDOWN)

  // No email in navigation state → nothing to verify, bounce to register.
  useEffect(() => {
    if (!email) navigate('/register', { replace: true })
  }, [email, navigate])

  useEffect(() => {
    if (cooldown <= 0) return
    const t = setInterval(() => setCooldown((c) => c - 1), 1000)
    return () => clearInterval(t)
  }, [cooldown])

  const handleSubmit = async (e) => {
    e.preventDefault()
    clearError()

    if (code.trim().length < 4) {
      toast.error('Enter the code from your email')
      return
    }

    const result = await verifyEmail(email, code.trim())
    if (!result.success) {
      toast.error(result.error || 'Verification failed')
      return
    }

    toast.success('Email verified! 🎉')

    // If we have the password (came straight from register), log in and
    // continue to onboarding; otherwise send them to sign in.
    if (password) {
      const loginResult = await login(email, password)
      if (loginResult.success) {
        const { isOnboarded } = useAuthStore.getState()
        navigate(isOnboarded ? '/dashboard' : '/onboarding', { replace: true })
        return
      }
    }
    navigate('/login', { replace: true })
  }

  const handleResend = async () => {
    const result = await resendOtp(email)
    if (result.success) {
      toast.success('A new code is on its way')
      setCooldown(RESEND_COOLDOWN)
    } else {
      toast.error(result.error || 'Could not resend code')
    }
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
    >
      <div className="mb-6">
        <h2 className="text-2xl font-display font-bold mb-2">Verify your email 📧</h2>
        <p className="text-surface-500">
          We sent a 6-digit code to <span className="font-medium">{email}</span>. Enter it below to
          activate your account.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-5">
        <div>
          <label className="block text-sm font-medium mb-2">Verification Code</label>
          <input
            type="text"
            inputMode="numeric"
            autoComplete="one-time-code"
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
            placeholder="123456"
            className="input text-center text-2xl tracking-[0.5em] font-semibold"
            maxLength={6}
            required
          />
        </div>

        {error && (
          <div className="p-3 bg-error-50 dark:bg-error-900/20 text-error-600 dark:text-error-400 rounded-xl text-sm">
            {error}
          </div>
        )}

        <button type="submit" disabled={isLoading} className="btn-primary w-full py-3">
          {isLoading ? 'Verifying...' : 'Verify Email'}
        </button>
      </form>

      <div className="mt-6 text-center text-sm">
        <span className="text-surface-500">Didn't get the code? </span>
        {cooldown > 0 ? (
          <span className="text-surface-400">Resend in {cooldown}s</span>
        ) : (
          <button
            type="button"
            onClick={handleResend}
            className="text-primary-600 font-medium hover:underline"
          >
            Resend code
          </button>
        )}
      </div>

      <div className="mt-4 text-center">
        <Link to="/login" className="text-sm text-surface-500 hover:underline">
          Back to sign in
        </Link>
      </div>
    </motion.div>
  )
}

export default VerifyEmail
