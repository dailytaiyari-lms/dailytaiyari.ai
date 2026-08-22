import { NavLink, useLocation } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { useAppStore } from '../../context/appStore'
import { useTenantStore } from '../../context/tenantStore'
import Sidebar from './Sidebar'
import {
  Home,
  GraduationCap,
  BookOpen,
  PenTool,
  BarChart3,
  Bot
} from 'lucide-react'

const navItems = [
  { path: '/dashboard', label: 'Home', icon: Home },
  { path: '/courses', label: 'Courses', icon: GraduationCap, feature: 'courses' },
  { path: '/study', label: 'Study', icon: BookOpen, feature: 'study' },
  { path: '/quiz', label: 'Quiz', icon: PenTool, feature: 'quiz' },
  { path: '/analytics', label: 'Stats', icon: BarChart3, feature: 'analytics' },
  { path: '/doubt-solver', label: 'AI', icon: Bot, feature: 'ai' },
]

const MobileNav = () => {
  const location = useLocation()
  const { mobileMenuOpen, closeMobileMenu } = useAppStore()
  const isFeatureEnabled = useTenantStore((s) => s.isFeatureEnabled)
  const featureLabel = useTenantStore((s) => s.featureLabel)

  const visibleNavItems = navItems
    .filter((item) => !item.feature || isFeatureEnabled(item.feature))
    .map((item) => (
      item.feature
        ? { ...item, label: featureLabel(item.feature, item.label) }
        : item
    ))

  return (
    <>
      {/* Mobile Slide-in Menu */}
      <AnimatePresence>
        {mobileMenuOpen && (
          <motion.div
            initial={{ x: -280 }}
            animate={{ x: 0 }}
            exit={{ x: -280 }}
            transition={{ type: 'spring', damping: 25, stiffness: 200 }}
            className="fixed left-0 top-0 z-50 h-screen w-64 lg:hidden"
          >
            <Sidebar />
          </motion.div>
        )}
      </AnimatePresence>

      {/* Bottom Navigation Bar (Mobile) */}
      <nav className="fixed bottom-0 left-0 right-0 z-40 bg-white dark:bg-surface-900 border-t border-surface-200 dark:border-surface-800 lg:hidden">
        <div className="flex items-center justify-around h-16 px-2">
          {visibleNavItems.map((item) => {
            const isActive = location.pathname === item.path ||
              (item.path !== '/dashboard' && location.pathname.startsWith(item.path))
            const IconComponent = item.icon

            return (
              <NavLink
                key={item.path}
                to={item.path}
                className={`flex flex-col items-center justify-center flex-1 py-2 rounded-lg transition-colors ${isActive
                    ? 'text-primary-600 dark:text-primary-400'
                    : 'text-surface-500 dark:text-surface-400'
                  }`}
              >
                <span className="mb-0.5"><IconComponent size={20} /></span>
                <span className="text-[10px] font-medium max-w-full truncate px-1">{item.label}</span>
                {isActive && (
                  <motion.div
                    layoutId="mobileNavIndicator"
                    className="absolute bottom-0 w-12 h-1 bg-primary-500 rounded-t-full"
                  />
                )}
              </NavLink>
            )
          })}
        </div>
      </nav>
    </>
  )
}

export default MobileNav

