import { useState } from 'react'
import { Link, useNavigate, useLocation } from 'react-router-dom'
import { motion } from 'framer-motion'
import { useAuthStore } from '../../context/authStore'
import { useTenantStore } from '../../context/tenantStore'
import toast from 'react-hot-toast'

const Login = () => {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const { login, isLoading, error, clearError } = useAuthStore()
  const { tenant } = useTenantStore()
  const navigate = useNavigate()
  const location = useLocation()
  // Return the user to the page they were gated out of, when provided.
  const from = location.state?.from

  const handleSubmit = async (e) => {
    e.preventDefault()
    clearError()

    const result = await login(email, password)
    if (result.success) {
      toast.success('Welcome back! 🎉')
      // Get updated state after login
      const { user, isOnboarded } = useAuthStore.getState()
      if (user?.guardian_consent_required && !user?.guardian_consent_granted_at) {
        navigate('/registration-pending', { replace: true })
        return
      }
      // Navigate based on onboarding status
      if (isOnboarded) {
        navigate(from || '/dashboard', { replace: true })
      } else {
        navigate('/onboarding', { replace: true })
      }
    } else if (result.needsVerification) {
      toast('Please verify your email to continue', { icon: '✉️' })
      navigate('/verify-email', { replace: true, state: { email, password } })
    } else {
      toast.error(result.error || 'Login failed')
    }
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
    >
      {/* Mobile Logo */}
      <div className="mb-8 lg:hidden">
        {tenant?.logo && tenant?.show_name === false ? (
          <div className="flex flex-col items-start gap-2">
            <img
              src={tenant.logo}
              alt={`${tenant.name || 'DailyTaiyari'} Logo`}
              className="max-h-16 w-auto max-w-full object-contain"
            />
            {tenant?.tagline && <p className="text-xs text-surface-500">{tenant.tagline}</p>}
          </div>
        ) : (
          <div className="flex items-center gap-3">
            {tenant?.logo ? (
              <img
                src={tenant.logo}
                alt={`${tenant.name} Logo`}
                className="w-12 h-12 shrink-0 rounded-xl object-contain bg-white dark:bg-surface-800 p-1"
              />
            ) : (
              <div className="w-12 h-12 shrink-0 bg-gradient-to-br from-primary-500 to-accent-500 rounded-xl flex items-center justify-center">
                <span className="text-white text-xl font-bold">
                  {tenant?.name ? tenant.name.substring(0, 2).toLowerCase() : 'dt'}
                </span>
              </div>
            )}
            <div className="min-w-0">
              <h1 title={tenant?.name || 'DailyTaiyari'} className="font-display font-bold text-xl gradient-text leading-tight break-words line-clamp-2">
                {tenant?.name || 'DailyTaiyari'}
              </h1>
              <p className="text-xs text-surface-500">{tenant?.tagline || 'Ace Your Exams'}</p>
            </div>
          </div>
        )}
      </div>

      {/* Welcome Text */}
      <div className="mb-8">
        <h2 className="text-2xl font-display font-bold mb-2">Welcome Back! 👋</h2>
        <p className="text-surface-500">Sign in to continue your learning journey</p>
      </div>

      {/* Login Form */}
      <form onSubmit={handleSubmit} className="space-y-5">
        {/* Email */}
        <div>
          <label className="block text-sm font-medium mb-2">Email Address</label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
            className="input"
            required
          />
        </div>

        {/* Password */}
        <div>
          <label className="block text-sm font-medium mb-2">Password</label>
          <div className="relative">
            <input
              type={showPassword ? 'text' : 'password'}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Enter your password"
              className="input pr-10"
              required
            />
            <button
              type="button"
              onClick={() => setShowPassword(!showPassword)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-surface-400 hover:text-surface-600"
            >
              {showPassword ? '👁️' : '👁️‍🗨️'}
            </button>
          </div>
        </div>

        {/* Forgot Password */}
        <div className="flex justify-end">
          <Link to="/forgot-password" className="text-sm text-primary-600 hover:text-primary-700">
            Forgot password?
          </Link>
        </div>

        {/* Error Message */}
        {error && (
          <div className="p-3 bg-error-50 dark:bg-error-900/20 text-error-600 dark:text-error-400 rounded-xl text-sm">
            {error}
          </div>
        )}

        {/* Submit Button */}
        <button
          type="submit"
          disabled={isLoading}
          className="btn-primary w-full py-3"
        >
          {isLoading ? (
            <span className="flex items-center gap-2">
              <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
              </svg>
              Signing in...
            </span>
          ) : (
            'Sign In'
          )}
        </button>
      </form>

      {/* Divider */}
      <div className="relative my-8">
        <div className="absolute inset-0 flex items-center">
          <div className="w-full border-t border-surface-200 dark:border-surface-700" />
        </div>
        <div className="relative flex justify-center text-sm">
          <span className="px-4 bg-surface-50 dark:bg-surface-950 text-surface-500">
            New to {tenant?.name || 'DailyTaiyari'}?
          </span>
        </div>
      </div>

      {/* Register Link */}
      <Link
        to="/register"
        className="btn-secondary w-full py-3 text-center"
      >
        Create an Account
      </Link>
    </motion.div>
  )
}

export default Login
