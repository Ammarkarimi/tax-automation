import { useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import {
  BadgePercent,
  Bot,
  CalendarClock,
  FileText,
  LayoutDashboard,
  ListChecks,
  LogOut,
  Menu,
  Receipt,
  Settings,
  ShieldAlert,
  ShieldCheck,
  UserCog,
  X,
} from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { useYear } from '../context/YearContext'

const NAV = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/documents', label: 'Documents', icon: FileText },
  { to: '/transactions', label: 'Transactions', icon: ListChecks },
  { to: '/taxes', label: 'Annual Return', icon: Receipt },
  { to: '/quarterly', label: 'Quarterly Estimates', icon: CalendarClock },
  { to: '/deductions', label: 'Deductions', icon: BadgePercent },
  { to: '/audit-risk', label: 'Audit Risk', icon: ShieldAlert },
  { to: '/assistant', label: 'AI Assistant', icon: Bot },
  { to: '/profile', label: 'Tax Profile', icon: UserCog },
  { to: '/settings', label: 'Settings & Privacy', icon: Settings },
]

export default function Layout() {
  const { user, logout } = useAuth()
  const { year, setYear, meta } = useYear()
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()
  const staff = user?.role === 'admin' || user?.role === 'support'

  const links = (
    <nav className="flex flex-col gap-1">
      {NAV.map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          onClick={() => setOpen(false)}
          className={({ isActive }) =>
            `flex items-center gap-3 rounded-lg px-3 py-2 text-sm ${
              isActive ? 'bg-brand-600 text-white' : 'text-slate-300 hover:bg-white/10 hover:text-white'
            }`
          }
        >
          <Icon className="h-4 w-4" /> {label}
        </NavLink>
      ))}
      {staff && (
        <NavLink
          to="/admin"
          onClick={() => setOpen(false)}
          className={({ isActive }) =>
            `mt-4 flex items-center gap-3 rounded-lg px-3 py-2 text-sm ${
              isActive ? 'bg-amber-500 text-white' : 'text-amber-300 hover:bg-white/10'
            }`
          }
        >
          <ShieldCheck className="h-4 w-4" /> Admin Panel
        </NavLink>
      )}
    </nav>
  )

  return (
    <div className="min-h-screen lg:flex">
      {/* Sidebar */}
      <aside
        className={`fixed inset-y-0 left-0 z-30 w-64 transform bg-brand-900 p-4 transition lg:static lg:translate-x-0 ${
          open ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="mb-6 flex items-center justify-between">
          <div className="text-lg font-bold text-white">🧾 TaxPilot</div>
          <button className="text-white lg:hidden" onClick={() => setOpen(false)} aria-label="Close menu">
            <X className="h-5 w-5" />
          </button>
        </div>
        {links}
      </aside>
      {open && <div className="fixed inset-0 z-20 bg-black/40 lg:hidden" onClick={() => setOpen(false)} />}

      {/* Main */}
      <div className="flex-1">
        <header className="sticky top-0 z-10 flex items-center justify-between border-b border-slate-200 bg-white/90 px-4 py-3 backdrop-blur lg:px-8">
          <button className="lg:hidden" onClick={() => setOpen(true)} aria-label="Open menu">
            <Menu className="h-5 w-5" />
          </button>
          <div className="flex items-center gap-2 text-sm">
            <label htmlFor="year" className="text-slate-500">
              Tax year
            </label>
            <select id="year" className="input w-28 py-1" value={year || ''} onChange={(e) => setYear(Number(e.target.value))}>
              {meta.supported_years.map((y) => (
                <option key={y} value={y}>
                  {y}
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-3 text-sm">
            <span className="hidden text-slate-600 sm:inline">{user?.full_name || user?.email}</span>
            <button
              className="btn-secondary py-1.5"
              onClick={async () => {
                await logout()
                navigate('/login')
              }}
            >
              <LogOut className="h-4 w-4" /> Sign out
            </button>
          </div>
        </header>
        <main className="mx-auto max-w-6xl p-4 lg:p-8">{year ? <Outlet /> : null}</main>
        <footer className="px-8 pb-6 text-center text-xs text-slate-400">
          TaxPilot prepares and explains returns; it does not file with or transmit anything to the IRS. Not legal or tax advice.
        </footer>
      </div>
    </div>
  )
}
