import { NavLink, useLocation } from 'react-router-dom'
import { motion } from 'framer-motion'
import { useAuthStore } from '../../context/authStore'
import { useAppStore } from '../../context/appStore'
import { useTenantStore } from '../../context/tenantStore'
import {
  LayoutDashboard,
  BookOpen,
  GraduationCap,
  PenTool,
  ClipboardList,
  FileText,
  BarChart3,
  Trophy,
  MessageSquareText,
  Sparkles,
  Settings,
  Users,
  Briefcase,
  Bookmark
} from 'lucide-react'

// Navigation items with professional icons.
// `feature` (optional) gates the item behind a tenant feature toggle.
// `renamable` marks the item as the primary entry point for that feature, so a
// tenant admin's custom feature name replaces its label. Secondary items of the
// same feature (e.g. Revision under Study) keep their own names.
const navItems = [
  { path: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { path: '/courses', label: 'Courses', icon: GraduationCap, feature: 'courses', renamable: true },
  { path: '/study', label: 'Study', icon: BookOpen, feature: 'study', renamable: true },
  { path: '/revision', label: 'Revision', icon: Bookmark, feature: 'study' },
  { path: '/quiz', label: 'Practice Quiz', icon: PenTool, feature: 'quiz', renamable: true },
  { path: '/mock-test', label: 'Mock Tests', icon: ClipboardList, feature: 'mock_tests', renamable: true },
  { path: '/pyp', label: 'PYQ Papers', icon: FileText, feature: 'pyq', renamable: true },
  { path: '/community', label: 'Community', icon: Users, feature: 'community', renamable: true },
  { path: '/jobs', label: 'Careers', icon: Briefcase, feature: 'jobs', renamable: true },
  { path: '/analytics', label: 'Analytics', icon: BarChart3, feature: 'analytics', renamable: true },
  { path: '/leaderboard', label: 'Leaderboard', icon: Trophy, feature: 'leaderboard', renamable: true },
  { path: '/doubt-solver', label: 'AI Doubt Solver', icon: MessageSquareText, feature: 'ai', renamable: true },
  { path: '/ai-learning', label: 'AI Learning', icon: Sparkles, badge: 'XP', feature: 'ai' },
]

const Sidebar = () => {
  const location = useLocation()
  const { profile, isAuthenticated } = useAuthStore()
  const { closeMobileMenu } = useAppStore()
  const tenant = useTenantStore((s) => s.tenant)
  const isFeatureEnabled = useTenantStore((s) => s.isFeatureEnabled)
  const featureLabel = useTenantStore((s) => s.featureLabel)

  const visibleNavItems = navItems
    .filter((item) => !item.feature || isFeatureEnabled(item.feature))
    .map((item) => (
      item.feature && item.renamable
        ? { ...item, label: featureLabel(item.feature, item.label) }
        : item
    ))

  return (
    <div className="h-full bg-white dark:bg-surface-900 border-r border-surface-200 dark:border-surface-800 flex flex-col">
      {/* Logo */}
      <div className="p-6 border-b border-surface-200 dark:border-surface-800">
        {tenant?.logo && tenant?.show_name === false ? (
          <div className="flex flex-col items-center gap-2 text-center">
            <img src={tenant.logo} alt={tenant.name || 'Logo'} className="w-full max-h-16 object-contain" />
            {tenant?.tagline && <p className="text-xs text-surface-500">{tenant.tagline}</p>}
          </div>
        ) : (
          <div className="flex items-center gap-3">
            {tenant?.logo ? (
              <div className="w-10 h-10 shrink-0 rounded-xl overflow-hidden flex items-center justify-center bg-surface-100 dark:bg-surface-800">
                <img src={tenant.logo} alt={tenant.name || 'Logo'} className="w-full h-full object-contain" />
              </div>
            ) : (
              <div className="w-10 h-10 shrink-0 bg-gradient-to-br from-primary-500 to-accent-500 rounded-xl flex items-center justify-center">
                <span className="text-white font-bold">
                  {(tenant?.name || 'dt').slice(0, 2).toLowerCase()}
                </span>
              </div>
            )}
            <div className="min-w-0">
              <h1 title={tenant?.name || 'DailyTaiyari'} className="font-display font-bold text-lg gradient-text leading-tight break-words line-clamp-2">{tenant?.name || 'DailyTaiyari'}</h1>
              <p className="text-xs text-surface-500">{tenant?.tagline || 'Ace Your Exams'}</p>
            </div>
          </div>
        )}
      </div>

      {/* Guest CTA card */}
      {!isAuthenticated && (
        <div className="p-4 mx-4 mt-4 rounded-xl bg-gradient-to-br from-primary-50 to-accent-50 dark:from-primary-900/20 dark:to-accent-900/20">
          <p className="text-sm font-medium">You're browsing as a guest</p>
          <p className="text-xs text-surface-500 mt-1">
            Log in to track progress, take quizzes and mock tests.
          </p>
          <NavLink
            to="/login"
            onClick={closeMobileMenu}
            className="btn-primary w-full mt-3 text-sm justify-center"
          >
            Log in / Sign up
          </NavLink>
        </div>
      )}

      {/* User Profile Card */}
      {profile && (
        <div className="p-4 mx-4 mt-4 rounded-xl bg-gradient-to-br from-primary-50 to-accent-50 dark:from-primary-900/20 dark:to-accent-900/20">
          <div className="flex items-center gap-3 mb-3">
            <div className="w-10 h-10 rounded-full bg-primary-100 dark:bg-primary-800 flex items-center justify-center overflow-hidden">
              {profile.user?.avatar ? (
                <img src={profile.user.avatar} alt={profile.user.full_name} className="w-full h-full object-cover" />
              ) : (
                <span className="text-primary-600 dark:text-primary-300 font-semibold">
                  {profile.user?.first_name?.charAt(0) || 'U'}
                </span>
              )}
            </div>

            <div className="flex-1 min-w-0">
              <p className="font-medium truncate">{profile.user?.full_name || 'Student'}</p>
              <p className="text-xs text-surface-500">Level {profile.current_level}</p>
            </div>
          </div>

          {/* XP Progress */}
          <div className="space-y-1">
            <div className="flex justify-between text-xs">
              <span className="text-surface-600 dark:text-surface-400">XP Progress</span>
              <span className="font-medium">{(profile.total_xp || 0).toLocaleString()} XP</span>
            </div>
            <div className="progress-bar">
              <div
                className="progress-bar-fill bg-gradient-to-r from-primary-500 to-accent-500"
                style={{
                  width: profile.total_xp > 0
                    ? `${Math.max(5, 100 - ((profile.xp_for_next_level || 100) / ((profile.current_level || 1) * 150) * 100))}%`
                    : '0%'
                }}
              />
            </div>
          </div>
        </div>
      )}

      {/* Navigation */}
      <nav className="flex-1 p-4 space-y-1 overflow-y-auto">
        {visibleNavItems.map((item) => {
          const isActive = location.pathname === item.path ||
            (item.path !== '/dashboard' && location.pathname.startsWith(item.path))
          const IconComponent = item.icon

          return (
            <NavLink
              key={item.path}
              to={item.path}
              onClick={closeMobileMenu}
              className={`relative flex items-center gap-3 px-4 py-3 rounded-xl transition-all duration-200 group ${isActive
                ? 'bg-primary-50 dark:bg-primary-900/30 text-primary-600 dark:text-primary-400'
                : 'text-surface-600 dark:text-surface-400 hover:bg-surface-100 dark:hover:bg-surface-800'
                }`}
            >
              {isActive && (
                <motion.div
                  layoutId="activeNav"
                  className="absolute -left-4 top-1/2 -translate-y-1/2 w-1 h-8 bg-primary-500 rounded-r-full"
                />
              )}
              <IconComponent
                size={20}
                strokeWidth={isActive ? 2.5 : 2}
                className={`transition-all ${isActive ? 'text-primary-500' : 'text-surface-500 group-hover:text-primary-400'}`}
              />
              <span className="font-medium">{item.label}</span>

              {/* Special badges */}
              {item.path === '/doubt-solver' && (
                <span className="ml-auto px-2 py-0.5 bg-gradient-to-r from-primary-500 to-accent-500 text-white text-[10px] rounded-full font-semibold">
                  AI
                </span>
              )}
              {item.badge && item.path !== '/doubt-solver' && (
                <span className="ml-auto px-2 py-0.5 bg-gradient-to-r from-violet-500 to-purple-600 text-white text-[10px] rounded-full font-semibold">
                  {item.badge}
                </span>
              )}
            </NavLink>
          )
        })}
      </nav>

      {/* Bottom Section */}
      <div className="p-4 border-t border-surface-200 dark:border-surface-800">
        <NavLink
          to="/profile"
          onClick={closeMobileMenu}
          className="flex items-center gap-3 px-4 py-3 rounded-xl text-surface-600 dark:text-surface-400 hover:bg-surface-100 dark:hover:bg-surface-800 transition-colors group"
        >
          <Settings
            size={20}
            strokeWidth={2}
            className="text-surface-500 group-hover:text-primary-400 transition-colors"
          />
          <span className="font-medium">Settings</span>
        </NavLink>
      </div>
    </div>
  )
}

export default Sidebar
