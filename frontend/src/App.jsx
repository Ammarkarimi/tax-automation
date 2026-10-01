import { Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from './context/AuthContext'
import { YearProvider } from './context/YearContext'
import Layout from './components/Layout'
import { Spinner } from './components/ui'
import { LoginPage, RegisterPage, VerifyOtpPage } from './pages/AuthPages'
import Dashboard from './pages/Dashboard'
import Documents from './pages/Documents'
import Transactions from './pages/Transactions'
import Taxes from './pages/Taxes'
import { AuditRisk, Deductions, Quarterly } from './pages/Planning'
import Assistant from './pages/Assistant'
import Profile from './pages/Profile'
import Settings from './pages/Settings'
import Admin from './pages/Admin'

/** Client-side guard for UX only — the API enforces auth & roles on every request. */
function Protected({ children, roles }) {
  const { user, loading } = useAuth()
  if (loading) return <Spinner label="Restoring session…" />
  if (!user) return <Navigate to="/login" replace />
  if (roles && !roles.includes(user.role)) return <Navigate to="/" replace />
  return children
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/verify" element={<VerifyOtpPage />} />
      <Route
        element={
          <Protected>
            <YearProvider>
              <Layout />
            </YearProvider>
          </Protected>
        }
      >
        <Route index element={<Dashboard />} />
        <Route path="documents" element={<Documents />} />
        <Route path="transactions" element={<Transactions />} />
        <Route path="taxes" element={<Taxes />} />
        <Route path="quarterly" element={<Quarterly />} />
        <Route path="deductions" element={<Deductions />} />
        <Route path="audit-risk" element={<AuditRisk />} />
        <Route path="assistant" element={<Assistant />} />
        <Route path="profile" element={<Profile />} />
        <Route path="settings" element={<Settings />} />
        <Route path="admin" element={<Protected roles={['admin', 'support']}><Admin /></Protected>} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
