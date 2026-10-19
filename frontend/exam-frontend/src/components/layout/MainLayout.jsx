import { useEffect } from 'react'
import { Outlet } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import Sidebar from './Sidebar'
import Header from './Header'
import MobileNav from './MobileNav'
import PromoBanner from './PromoBanner'
import AnnouncementBanner from './AnnouncementBanner'
import StudyTimer from '../common/StudyTimer'
import BirthdayCelebration from '../common/BirthdayCelebration'
import { useAppStore } from '../../context/appStore'
import { useAuthStore } from '../../context/authStore'

const MainLayout = () => {
  const { sidebarOpen, mobileMenuOpen } = useAppStore()
  const { fetchProfile, isAuthenticated } = useAuthStore()

  useEffect(() => {
    if (isAuthenticated) fetchProfile()
  }, [isAuthenticated])

  return (
    <div className="min-h-screen bg-surface-50 dark:bg-surface-950">
      {/* Desktop Sidebar */}
      <AnimatePresence mode="wait">
        {sidebarOpen && (
          <motion.aside
            initial={{ x: -280 }}
            animate={{ x: 0 }}
            exit={{ x: -280 }}
            transition={{ type: 'spring', damping: 25, stiffness: 200 }}
            className="fixed left-0 top-0 z-40 hidden h-screen w-64 lg:block"
          >
            <Sidebar />
          </motion.aside>
        )}
      </AnimatePresence>

      {/* Mobile Navigation */}
      <MobileNav />

      {/* Main Content */}
      <div
        className={`min-h-screen transition-all duration-300 ${sidebarOpen ? 'lg:ml-64' : 'lg:ml-0'
          }`}
      >
        {/* Sitewide promotional banner */}
        <PromoBanner />

        {/* Platform announcements from the DailyTaiyari team */}
        <AnnouncementBanner />

        {/* Header */}
        <Header />

        {/* Page Content */}
        <main className="p-4 pb-24 lg:p-6 lg:pb-6">
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3 }}
          >
            <Outlet />
          </motion.div>
        </main>
      </div>

      {/* Study Timer Widget */}
      <StudyTimer />

      {/* Birthday celebration takeover (only when there is one to show) */}
      <BirthdayCelebration />

      {/* Mobile Menu Overlay */}
      <AnimatePresence>
        {mobileMenuOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-30 bg-black/50 backdrop-blur-sm lg:hidden"
            onClick={() => useAppStore.getState().closeMobileMenu()}
          />
        )}
      </AnimatePresence>
    </div>
  )
}

export default MainLayout

