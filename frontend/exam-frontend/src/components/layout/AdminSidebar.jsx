import { NavLink, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { motion } from 'framer-motion'
import { useAuthStore } from '../../context/authStore'
import { useAppStore } from '../../context/appStore'
import { useTenantStore } from '../../context/tenantStore'
import {
  TrendingUp,
  Users,
  GraduationCap,
  BarChart3,
  Library,
  LayoutTemplate,
  SlidersHorizontal,
  ClipboardList,
  Shield,
  Briefcase,
  ShoppingCart,
  Megaphone,
  Bell,
  Sparkles,
  Wand2,
  Brain,
} from 'lucide-react'

// Admin navigation sections. `tab` items drive the in-page section shown by
// AdminDashboard via the `?tab=` query param; `path` items navigate to a route.
export const ADMIN_NAV_ITEMS = [
  { tab: 'overview', label: 'Overview', icon: TrendingUp },
  { tab: 'students', label: 'Student Records', icon: Users },
  { tab: 'enrollments', label: 'Enrollments', icon: GraduationCap },
  { tab: 'sales', label: 'Sales & Orders', icon: ShoppingCart },
  { tab: 'marketing', label: 'Marketing & Promotions', icon: Megaphone },
  { tab: 'announcements', label: 'Announcements', icon: Bell },
  { tab: 'performance', label: 'Reports', icon: BarChart3 },
  { tab: 'content', label: 'Course Builder', icon: Library },
  { tab: 'ai-studio', label: 'AI Course Studio', icon: Wand2 },
  { tab: 'landing', label: 'Landing Page', icon: LayoutTemplate },
  { path: '/admin/mock-tests', label: 'Mock Tests', icon: ClipboardList },
  { path: '/admin/insights', label: 'Learning Insights', icon: Brain, feature: 'practice' },
  { path: '/admin/jobs', label: 'Jobs', icon: Briefcase },
  { tab: 'ai', label: 'AI Features', icon: Sparkles },
  { tab: 'settings', label: 'Settings', icon: SlidersHorizontal },
]

const AdminSidebar = () => {
  const location = useLocation()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const { profile } = useAuthStore()
  const { closeMobileMenu } = useAppStore()
  const tenant = useTenantStore((s) => s.tenant)
  const isFeatureEnabled = useTenantStore((s) => s.isFeatureEnabled)

  const activeTab = searchParams.get('tab') || 'overview'
  const onAdminDashboard = location.pathname === '/admin-dashboard'

  const selectTab = (tab) => {
    navigate(tab === 'overview' ? '/admin-dashboard' : `/admin-dashboard?tab=${tab}`)
    closeMobileMenu()
  }

  return (
    <div className="h-full bg-white dark:bg-surface-900 border-r border-surface-200 dark:border-surface-800 flex flex-col">
      {/* Logo */}
      <div className="p-6 border-b border-surface-200 dark:border-surface-800">
        {tenant?.logo && tenant?.show_name === false ? (
          <div className="flex flex-col items-center gap-2 text-center">
            <img src={tenant.logo} alt={tenant.name || 'Logo'} className="w-full max-h-16 object-contain" />
            <p className="text-xs text-surface-500">Admin Console</p>
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
              <p className="text-xs text-surface-500">Admin Console</p>
            </div>
          </div>
        )}
      </div>

      {/* Admin badge card */}
      <div className="p-4 mx-4 mt-4 rounded-xl bg-gradient-to-br from-primary-50 to-accent-50 dark:from-primary-900/20 dark:to-accent-900/20">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-primary-100 dark:bg-primary-800 flex items-center justify-center overflow-hidden">
            {profile?.user?.avatar ? (
              <img src={profile.user.avatar} alt={profile.user.full_name} className="w-full h-full object-cover" />
            ) : (
              <span className="text-primary-600 dark:text-primary-300 font-semibold">
                {profile?.user?.first_name?.charAt(0) || 'A'}
              </span>
            )}
          </div>
          <div className="flex-1 min-w-0">
            <p className="font-medium truncate">{profile?.user?.full_name || 'Administrator'}</p>
            <p className="text-xs text-surface-500 flex items-center gap-1">
              <Shield className="w-3 h-3" /> Institutional Admin
            </p>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-4 space-y-1 overflow-y-auto">
        {ADMIN_NAV_ITEMS.filter(
          (item) => !item.feature || isFeatureEnabled(item.feature)
        ).map((item) => {
          const IconComponent = item.icon

          // Route-based item (e.g. Mock Tests) — navigate to a separate page.
          if (item.path) {
            return (
              <NavLink
                key={item.path}
                to={item.path}
                onClick={closeMobileMenu}
                className={({ isActive }) =>
                  `relative flex items-center gap-3 px-4 py-3 rounded-xl transition-all duration-200 group ${
                    isActive
                      ? 'bg-primary-50 dark:bg-primary-900/30 text-primary-600 dark:text-primary-400'
                      : 'text-surface-600 dark:text-surface-400 hover:bg-surface-100 dark:hover:bg-surface-800'
                  }`
                }
              >
                <IconComponent size={20} strokeWidth={2} className="text-surface-500 group-hover:text-primary-400 transition-all" />
                <span className="font-medium">{item.label}</span>
              </NavLink>
            )
          }

          // Section item — toggles the in-page tab.
          const isActive = onAdminDashboard && activeTab === item.tab
          return (
            <button
              key={item.tab}
              onClick={() => selectTab(item.tab)}
              className={`relative w-full flex items-center gap-3 px-4 py-3 rounded-xl transition-all duration-200 group text-left ${
                isActive
                  ? 'bg-primary-50 dark:bg-primary-900/30 text-primary-600 dark:text-primary-400'
                  : 'text-surface-600 dark:text-surface-400 hover:bg-surface-100 dark:hover:bg-surface-800'
              }`}
            >
              {isActive && (
                <motion.div
                  layoutId="activeAdminNav"
                  className="absolute -left-4 top-1/2 -translate-y-1/2 w-1 h-8 bg-primary-500 rounded-r-full"
                />
              )}
              <IconComponent
                size={20}
                strokeWidth={isActive ? 2.5 : 2}
                className={`transition-all ${isActive ? 'text-primary-500' : 'text-surface-500 group-hover:text-primary-400'}`}
              />
              <span className="font-medium">{item.label}</span>
            </button>
          )
        })}
      </nav>
    </div>
  )
}

export default AdminSidebar
