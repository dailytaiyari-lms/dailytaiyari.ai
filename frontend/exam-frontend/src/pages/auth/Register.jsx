import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { useAuthStore } from '../../context/authStore'
import { useTenantStore } from '../../context/tenantStore'
import toast from 'react-hot-toast'

const FIELD_OPTIONS = {
  gender: [
    ['female', 'Female'],
    ['male', 'Male'],
    ['non_binary', 'Non-binary'],
    ['prefer_not_to_say', 'Prefer not to say'],
    ['other', 'Other'],
  ],
  preferred_language: [['en', 'English'], ['hi', 'Hindi']],
  grade: [
    ['6', 'Class 6'], ['7', 'Class 7'], ['8', 'Class 8'], ['9', 'Class 9'],
    ['10', 'Class 10'], ['11', 'Class 11'], ['12', 'Class 12'],
    ['graduate', 'Graduate'], ['other', 'Other'],
  ],
  board: [
    ['cbse', 'CBSE'], ['icse', 'ICSE'], ['state', 'State Board'],
    ['ib', 'IB'], ['igcse', 'IGCSE'], ['other', 'Other'],
  ],
  medium: [
    ['english', 'English'], ['hindi', 'Hindi'],
    ['bilingual', 'Bilingual'], ['other', 'Other'],
  ],
}

const Register = () => {
  const [formData, setFormData] = useState({
    first_name: '',
    last_name: '',
    email: '',
    phone: '',
    date_of_birth: '',
    gender: '',
    preferred_language: 'en',
    grade: '',
    board: '',
    school: '',
    coaching: '',
    medium: '',
    stream: '',
    city: '',
    state: '',
    admission_number: '',
    batch_section: '',
    guardian_name: '',
    guardian_email: '',
    guardian_phone: '',
    guardian_relationship: '',
    password: '',
    password_confirm: '',
  })
  const [showPassword, setShowPassword] = useState(false)
  const { register, isLoading, error, clearError } = useAuthStore()
  const { tenant } = useTenantStore()
  const navigate = useNavigate()
  const registrationFields = tenant?.registration_schema?.fields || []
  const guardianConsentEnabled = Boolean(tenant?.registration_schema?.guardian_consent?.enabled)
  const birthDate = formData.date_of_birth ? new Date(`${formData.date_of_birth}T00:00:00`) : null
  const today = new Date()
  const age = birthDate
    ? today.getFullYear() - birthDate.getFullYear() -
      (today < new Date(today.getFullYear(), birthDate.getMonth(), birthDate.getDate()) ? 1 : 0)
    : null
  const needsGuardian = guardianConsentEnabled && age !== null && age < 18

  const handleChange = (e) => {
    setFormData({ ...formData, [e.target.name]: e.target.value })
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    clearError()

    if (formData.password !== formData.password_confirm) {
      toast.error('Passwords do not match')
      return
    }

    if (formData.password.length < 8) {
      toast.error('Password must be at least 8 characters')
      return
    }

    const payload = {
      first_name: formData.first_name,
      last_name: formData.last_name,
      email: formData.email,
      password: formData.password,
      password_confirm: formData.password_confirm,
    }
    registrationFields.forEach((field) => {
      const value = formData[field.key]
      if (value !== '' && value !== null && value !== undefined) payload[field.key] = value
    })
    if (needsGuardian) {
      payload.guardian_name = formData.guardian_name
      payload.guardian_email = formData.guardian_email
      payload.guardian_phone = formData.guardian_phone
      payload.guardian_relationship = formData.guardian_relationship
    }

    const result = await register(payload)
    if (result.success) {
      toast.success('Account created! Check your email for a verification code ✉️')
      navigate('/verify-email', {
        replace: true,
        state: { email: formData.email, password: formData.password },
      })
    } else {
      toast.error(result.error || 'Registration failed')
    }
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
    >
      {/* Mobile Logo */}
      <div className="mb-6 lg:hidden">
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
      <div className="mb-6">
        <h2 className="text-2xl font-display font-bold mb-2">Create Account 🎯</h2>
        <p className="text-surface-500">Start your journey to exam success</p>
      </div>

      {/* Register Form */}
      <form onSubmit={handleSubmit} className="space-y-4">
        {/* Name Fields */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium mb-2">First Name</label>
            <input
              type="text"
              name="first_name"
              value={formData.first_name}
              onChange={handleChange}
              placeholder="John"
              className="input"
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-2">Last Name</label>
            <input
              type="text"
              name="last_name"
              value={formData.last_name}
              onChange={handleChange}
              placeholder="Doe"
              className="input"
              required
            />
          </div>
        </div>

        {/* Email */}
        <div>
          <label className="block text-sm font-medium mb-2">Email Address</label>
          <input
            type="email"
            name="email"
            value={formData.email}
            onChange={handleChange}
            placeholder="you@example.com"
            className="input"
            required
          />
        </div>

        {registrationFields.length > 0 && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {registrationFields.map((field) => {
              const options = FIELD_OPTIONS[field.key]
              const type = field.type === 'phone' ? 'tel' : field.type === 'date' ? 'date' : 'text'
              return (
                <div key={field.key} className={['school', 'coaching'].includes(field.key) ? 'sm:col-span-2' : ''}>
                  <label className="block text-sm font-medium mb-2">
                    {field.label}{field.required ? ' *' : ''}
                  </label>
                  {options ? (
                    <select
                      name={field.key}
                      value={formData[field.key] || ''}
                      onChange={handleChange}
                      className="input"
                      required={field.required}
                    >
                      <option value="">Select</option>
                      {options.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                    </select>
                  ) : (
                    <input
                      type={type}
                      name={field.key}
                      value={formData[field.key] || ''}
                      onChange={handleChange}
                      className="input"
                      required={field.required}
                    />
                  )}
                </div>
              )
            })}
          </div>
        )}

        {needsGuardian && (
          <div className="rounded-2xl border border-primary-200 dark:border-primary-900/50 bg-primary-50/50 dark:bg-primary-900/10 p-4 space-y-4">
            <div>
              <h3 className="font-semibold">Parent or guardian approval</h3>
              <p className="text-sm text-surface-500 mt-1">
                Because the student is under 18, we’ll email a short approval request to a parent or lawful guardian.
              </p>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium mb-2">Guardian Name *</label>
                <input name="guardian_name" value={formData.guardian_name} onChange={handleChange} className="input" required />
              </div>
              <div>
                <label className="block text-sm font-medium mb-2">Relationship *</label>
                <select name="guardian_relationship" value={formData.guardian_relationship} onChange={handleChange} className="input" required>
                  <option value="">Select</option>
                  <option value="parent">Parent</option>
                  <option value="legal_guardian">Legal guardian</option>
                  <option value="other">Other</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium mb-2">Guardian Email *</label>
                <input type="email" name="guardian_email" value={formData.guardian_email} onChange={handleChange} className="input" required />
              </div>
              <div>
                <label className="block text-sm font-medium mb-2">Guardian Phone</label>
                <input type="tel" name="guardian_phone" value={formData.guardian_phone} onChange={handleChange} className="input" />
              </div>
            </div>
          </div>
        )}

        {/* Password */}
        <div>
          <label className="block text-sm font-medium mb-2">Password</label>
          <div className="relative">
            <input
              type={showPassword ? 'text' : 'password'}
              name="password"
              value={formData.password}
              onChange={handleChange}
              placeholder="At least 8 characters"
              className="input pr-10"
              required
              minLength={8}
            />
            <button
              type="button"
              onClick={() => setShowPassword(!showPassword)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-surface-400"
            >
              {showPassword ? '👁️' : '👁️‍🗨️'}
            </button>
          </div>
        </div>

        {/* Confirm Password */}
        <div>
          <label className="block text-sm font-medium mb-2">Confirm Password</label>
          <input
            type="password"
            name="password_confirm"
            value={formData.password_confirm}
            onChange={handleChange}
            placeholder="Confirm your password"
            className="input"
            required
          />
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
            <span className="flex items-center justify-center gap-2">
              <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
              </svg>
              Creating account...
            </span>
          ) : (
            'Create Account'
          )}
        </button>

        {/* Terms */}
        <p className="text-xs text-center text-surface-500">
          By creating an account, you agree to our{' '}
          <Link to="/terms" target="_blank" className="text-primary-600 hover:underline">Terms of Service</Link>
          {' '}and{' '}
          <Link to="/privacy-policy" target="_blank" className="text-primary-600 hover:underline">Privacy Policy</Link>
        </p>
      </form>

      {/* Login Link */}
      <div className="mt-6 text-center">
        <span className="text-surface-500">Already have an account? </span>
        <Link to="/login" className="text-primary-600 font-medium hover:underline">
          Sign In
        </Link>
      </div>
    </motion.div>
  )
}

export default Register
