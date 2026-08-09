import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { LayoutDashboard, Building2, LogOut, ShieldCheck, History, Users, Inbox, Megaphone, Bot } from 'lucide-react'
import { useAuthStore } from '../store/authStore'

const navItems = [
  { to: '/', label: 'Overview', icon: LayoutDashboard, end: true },
  { to: '/tenants', label: 'Tenants', icon: Building2, end: false },
  { to: '/users', label: 'Users', icon: Users, end: false },
  { to: '/support', label: 'Support Inbox', icon: Inbox, end: false },
  { to: '/announcements', label: 'Announcements', icon: Megaphone, end: false },
  { to: '/ai', label: 'AI Platform', icon: Bot, end: false },
  { to: '/audit', label: 'Audit Log', icon: History, end: false },
]

export default function Layout() {
  const user = useAuthStore((s) => s.user)
  const logout = useAuthStore((s) => s.logout)
  const navigate = useNavigate()

  const handleLogout = () => {
    logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="min-h-screen flex bg-slate-50">
      {/* Sidebar */}
      <aside className="w-64 shrink-0 bg-slate-900 text-slate-100 flex flex-col">
        <div className="px-6 py-6 flex items-center gap-2 border-b border-slate-800">
          <ShieldCheck className="w-7 h-7 text-brand-400" />
          <div>
            <div className="font-bold leading-tight">DailyTaiyari</div>
            <div className="text-xs text-slate-400">Super Admin</div>
          </div>
        </div>

        <nav className="flex-1 px-3 py-4 space-y-1">
          {navItems.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition ${
                  isActive
                    ? 'bg-brand-600 text-white'
                    : 'text-slate-300 hover:bg-slate-800 hover:text-white'
                }`
              }
            >
              <Icon className="w-5 h-5" />
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="px-3 py-4 border-t border-slate-800">
          <div className="px-3 pb-3">
            <div className="text-sm font-medium truncate">{user?.name || 'Super Admin'}</div>
            <div className="text-xs text-slate-400 truncate">{user?.email}</div>
          </div>
          <button
            onClick={handleLogout}
            className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium text-slate-300 hover:bg-slate-800 hover:text-white transition"
          >
            <LogOut className="w-5 h-5" />
            Sign out
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto">
        <div className="max-w-6xl mx-auto px-8 py-8">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
