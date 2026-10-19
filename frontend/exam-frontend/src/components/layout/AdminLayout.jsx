import { useEffect, useState } from 'react'
import { Outlet, useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { Menu, Moon, Sun, ArrowLeftRight, LogOut, User } from 'lucide-react'
import AdminSidebar from './AdminSidebar'
import BirthdayCelebration from '../common/BirthdayCelebration'
import { useAppStore } from '../../context/appStore'
import { useAuthStore } from '../../context/authStore'

const AdminLayout = () => {
  const navigate = useNavigate()
  const { mobileMenuOpen, toggleMobileMenu, closeMobileMenu, darkMode, toggleDarkMode } = useAppStore()
  const { profile, fetchProfile, logout } = useAuthStore()
  const [showUserMenu, setShowUserMenu] = useState(false)

  useEffect(() => {
    fetchProfile()
  }, [])

  return (
    <div className="min-h-screen bg-surface-50 dark:bg-surface-950">
      {/* Desktop Sidebar */}
      <aside className="fixed left-0 top-0 z-40 hidden h-screen w-64 lg:block">
        <AdminSidebar />
      </aside>

      {/* Mobile Slide-in Sidebar */}
      <AnimatePresence>
        {mobileMenuOpen && (
          <motion.div
            initial={{ x: -280 }}
            animate={{ x: 0 }}
            exit={{ x: -280 }}
            transition={{ type: 'spring', damping: 25, stiffness: 200 }}
            className="fixed left-0 top-0 z-50 h-screen w-64 lg:hidden"
          >
            <AdminSidebar />
          </motion.div>
        )}
      </AnimatePresence>

      {/* Main Content */}
      <div className="min-h-screen lg:ml-64">
        {/* Top Bar */}
        <header className="sticky top-0 z-30 bg-white/80 dark:bg-surface-900/80 backdrop-blur-lg border-b border-surface-200 dark:border-surface-800">
          <div className="flex items-center justify-between h-16 px-4 lg:px-6">
            {/* Left: mobile menu + single view switch button */}
            <div className="flex items-center gap-3">
              <button
                onClick={toggleMobileMenu}
                className="lg:hidden btn-icon"
                aria-label="Toggle menu"
              >
                <Menu className="w-6 h-6" />
              </button>

              <motion.button
                whileHover={{ scale: 1.03 }}
                whileTap={{ scale: 0.97 }}
                onClick={() => navigate('/dashboard')}
                className="flex items-center gap-2 px-4 py-2 rounded-xl border bg-accent-50 border-accent-200 text-accent-700 dark:bg-accent-900/30 dark:border-accent-800 dark:text-accent-400 transition-all"
              >
                <ArrowLeftRight className="w-4 h-4" />
                <span className="text-sm font-semibold">Back to Student View</span>
              </motion.button>
            </div>

            {/* Right: dark mode + user */}
            <div className="flex items-center gap-2 lg:gap-3">
              <button onClick={toggleDarkMode} className="btn-icon" aria-label="Toggle dark mode">
                {darkMode ? <Sun className="w-5 h-5" /> : <Moon className="w-5 h-5" />}
              </button>

              <div className="relative">
                <button
                  onClick={() => setShowUserMenu(!showUserMenu)}
                  className="flex items-center gap-2 p-1 rounded-xl hover:bg-surface-100 dark:hover:bg-surface-800 transition-colors"
                >
                  <div className="w-8 h-8 rounded-full bg-gradient-to-br from-primary-400 to-accent-400 flex items-center justify-center overflow-hidden">
                    {profile?.user?.avatar ? (
                      <img src={profile.user.avatar} alt={profile.user.full_name} className="w-full h-full object-cover" />
                    ) : (
                      <span className="text-white text-sm font-semibold">
                        {profile?.user?.first_name?.charAt(0) || 'A'}
                      </span>
                    )}
                  </div>
                </button>

                {showUserMenu && (
                  <motion.div
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="absolute right-0 mt-2 w-56 card shadow-lg overflow-hidden"
                  >
                    <div className="p-4 border-b border-surface-200 dark:border-surface-700">
                      <p className="font-medium">{profile?.user?.full_name || 'Administrator'}</p>
                      <p className="text-sm text-surface-500">{profile?.user?.email}</p>
                    </div>
                    <div className="p-2">
                      <button
                        onClick={() => { setShowUserMenu(false); navigate('/profile') }}
                        className="w-full flex items-center gap-2 text-left px-3 py-2 rounded-lg hover:bg-surface-100 dark:hover:bg-surface-800 transition-colors"
                      >
                        <User className="w-4 h-4" /> Profile Settings
                      </button>
                      <button
                        onClick={() => { setShowUserMenu(false); logout(); navigate('/login') }}
                        className="w-full flex items-center gap-2 text-left px-3 py-2 rounded-lg text-error-600 hover:bg-error-50 dark:hover:bg-error-900/20 transition-colors"
                      >
                        <LogOut className="w-4 h-4" /> Sign Out
                      </button>
                    </div>
                  </motion.div>
                )}
              </div>
            </div>
          </div>
        </header>

        {/* Page Content */}
        <main className="p-4 lg:p-6">
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3 }}
          >
            <Outlet />
          </motion.div>
        </main>
      </div>

      {/* Birthday celebration takeover (only when there is one to show) */}
      <BirthdayCelebration />

      {/* Mobile Menu Overlay */}
      <AnimatePresence>
        {mobileMenuOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm lg:hidden"
            onClick={closeMobileMenu}
          />
        )}
      </AnimatePresence>
    </div>
  )
}

export default AdminLayout
