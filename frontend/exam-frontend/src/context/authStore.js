import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import api from '../services/api'

export const useAuthStore = create(
  persist(
    (set, get) => ({
      user: null,
      profile: null,
      tokens: null,
      isAuthenticated: false,
      isOnboarded: false,
      isLoading: false,
      error: null,

      // Login action
      login: async (email, password) => {
        set({ isLoading: true, error: null })
        try {
          const response = await api.post('/auth/login/', { email, password })
          const { access, refresh, user } = response.data

          set({
            user,
            tokens: { access, refresh },
            isAuthenticated: true,
            isOnboarded: user.is_onboarded,
            isLoading: false,
          })

          // Fetch profile if onboarded
          if (user.is_onboarded) {
            get().fetchProfile()
          }

          return { success: true }
        } catch (error) {
          const data = error.response?.data || {}
          const pick = (v) => (Array.isArray(v) ? v[0] : v)
          const code = pick(data.code)

          // Backend blocks login until the email is verified.
          if (code === 'email_not_verified') {
            set({ isLoading: false, error: null })
            return {
              success: false,
              needsVerification: true,
              email: pick(data.email) || email,
            }
          }

          const message = pick(data.detail) || 'Login failed'
          set({ error: message, isLoading: false })
          return { success: false, error: message }
        }
      },

      // Register action — does NOT auto-login; email must be verified first.
      register: async (data) => {
        set({ isLoading: true, error: null })
        try {
          await api.post('/auth/register/', data)
          set({ isLoading: false })
          return { success: true, needsVerification: true, email: data.email }
        } catch (error) {
          const data = error.response?.data || {}
          const firstValue = Object.values(data)[0]
          const message = data.email?.[0] ||
            data.detail ||
            (Array.isArray(firstValue) ? firstValue[0] : firstValue) ||
            'Registration failed'
          set({ error: message, isLoading: false })
          return { success: false, error: message }
        }
      },

      fetchGuardianConsentStatus: async () => {
        try {
          const response = await api.get('/auth/guardian-consent/status/')
          if (response.data?.granted) {
            const current = get().user
            set({
              user: current
                ? { ...current, guardian_consent_granted_at: new Date().toISOString() }
                : current,
            })
          }
          return response.data
        } catch {
          return null
        }
      },

      resendGuardianConsent: async () => {
        try {
          await api.post('/auth/guardian-consent/resend/')
          return { success: true }
        } catch (error) {
          return {
            success: false,
            error: error.response?.data?.error || 'Could not resend the approval email',
          }
        }
      },

      // Verify email with the OTP sent on registration
      verifyEmail: async (email, code) => {
        set({ isLoading: true, error: null })
        try {
          await api.post('/auth/verify-email/', { email, code })
          // Reflect verification locally so any in-app verify gate clears.
          const current = get().user
          set({
            isLoading: false,
            user: current ? { ...current, is_email_verified: true } : current,
          })
          // Refresh profile if we're an authenticated, onboarded session.
          if (get().isAuthenticated && get().isOnboarded) {
            get().fetchProfile()
          }
          return { success: true }
        } catch (error) {
          const message = error.response?.data?.error ||
            error.response?.data?.detail || 'Verification failed'
          set({ error: message, isLoading: false })
          return { success: false, error: message }
        }
      },

      // Mark the current session as suspended (driven by a 403 account_suspended
      // response). Keeps the session so the blocking overlay can show.
      markSuspended: () => {
        const current = get().user
        if (current && !current.is_suspended) {
          set({ user: { ...current, is_suspended: true } })
        }
      },

      // Resend the email-verification OTP
      resendOtp: async (email) => {
        try {
          await api.post('/auth/resend-otp/', { email })
          return { success: true }
        } catch (error) {
          const message = error.response?.data?.error || 'Could not resend code'
          return { success: false, error: message }
        }
      },

      // Request a password-reset code
      requestPasswordReset: async (email) => {
        try {
          await api.post('/auth/password/forgot/', { email })
          return { success: true }
        } catch (error) {
          const message = error.response?.data?.error || 'Could not send reset code'
          return { success: false, error: message }
        }
      },

      // Confirm a password reset with the OTP + new password
      resetPassword: async (email, code, new_password) => {
        set({ isLoading: true, error: null })
        try {
          await api.post('/auth/password/reset/', { email, code, new_password })
          set({ isLoading: false })
          return { success: true }
        } catch (error) {
          const message = error.response?.data?.error ||
            error.response?.data?.new_password?.[0] ||
            error.response?.data?.detail || 'Password reset failed'
          set({ error: message, isLoading: false })
          return { success: false, error: message }
        }
      },

      // Change password for an authenticated user
      changePassword: async (old_password, new_password) => {
        set({ isLoading: true, error: null })
        try {
          await api.post('/auth/password/change/', { old_password, new_password })
          set({ isLoading: false })
          return { success: true }
        } catch (error) {
          const data = error.response?.data
          const message = data?.error ||
            data?.old_password?.[0] ||
            data?.new_password?.[0] ||
            data?.non_field_errors?.[0] ||
            data?.detail || 'Password change failed'
          set({ error: message, isLoading: false })
          return { success: false, error: message }
        }
      },

      // Complete onboarding
      completeOnboarding: async (data) => {
        set({ isLoading: true, error: null })
        try {
          const response = await api.post('/auth/onboarding/', data)
          set({
            profile: response.data.profile,
            isOnboarded: true,
            isLoading: false,
          })
          return { success: true }
        } catch (error) {
          const message = error.response?.data?.detail || 'Onboarding failed'
          set({ error: message, isLoading: false })
          return { success: false, error: message }
        }
      },

      // Fetch user profile
      fetchProfile: async () => {
        try {
          const response = await api.get('/auth/profile/')
          set({ profile: response.data })
          return response.data
        } catch (error) {
          console.error('Failed to fetch profile:', error)
          return null
        }
      },

      // Update profile
      updateProfile: async (data) => {
        try {
          const config = {}
          if (data instanceof FormData) {
            config.headers = { 'Content-Type': 'multipart/form-data' }
          }
          const response = await api.patch('/auth/profile/', data, config)
          set({ profile: response.data, user: response.data.user || get().user })
          return { success: true }
        } catch (error) {
          console.error('Update profile error:', error.response?.data)
          return { success: false, error: 'Failed to update profile' }
        }
      },


      // Refresh token
      refreshToken: async () => {
        const { tokens } = get()
        if (!tokens?.refresh) return false

        try {
          const response = await api.post('/auth/refresh/', {
            refresh: tokens.refresh,
          })
          set({
            tokens: {
              ...tokens,
              access: response.data.access,
            },
          })
          return true
        } catch (error) {
          get().logout()
          return false
        }
      },

      // Logout
      logout: () => {
        set({
          user: null,
          profile: null,
          tokens: null,
          isAuthenticated: false,
          isOnboarded: false,
          error: null,
        })
      },

      // Clear error
      clearError: () => set({ error: null }),
    }),
    {
      name: 'auth-storage',
      partialize: (state) => ({
        user: state.user,
        profile: state.profile,
        tokens: state.tokens,
        isAuthenticated: state.isAuthenticated,
        isOnboarded: state.isOnboarded,
      }),
    }
  )
)
