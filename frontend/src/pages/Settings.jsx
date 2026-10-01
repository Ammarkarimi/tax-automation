import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Download, KeyRound, ShieldCheck, Trash2 } from 'lucide-react'
import { api } from '../api/client'
import { useAuth } from '../context/AuthContext'
import { Alert, ErrorAlert, PageHeader } from '../components/ui'

export default function Settings() {
  const { user, setUser, logout } = useAuth()
  const navigate = useNavigate()
  const [msg, setMsg] = useState(null)
  const [error, setError] = useState(null)
  const [pw, setPw] = useState({ current: '', next: '' })
  const [deletePw, setDeletePw] = useState('')

  const toggleAi = async () => {
    try {
      setUser(await api.patch('/me/settings', { ai_consent: !user.ai_consent }))
      setMsg(user.ai_consent ? 'AI processing turned off.' : 'AI processing turned on.')
    } catch (err) {
      setError(err)
    }
  }

  const changePassword = async (e) => {
    e.preventDefault()
    try {
      await api.post('/auth/change-password', { current_password: pw.current, new_password: pw.next })
      await logout()
      navigate('/login')
    } catch (err) {
      setError(err)
    }
  }

  const exportData = async () => {
    const data = await api.get('/me/export')
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = 'taxpilot-my-data.json'
    a.click()
  }

  const deleteAccount = async (e) => {
    e.preventDefault()
    if (!confirm('Permanently delete your account, documents and all tax data? This cannot be undone.')) return
    try {
      await api.post('/me/delete', { password: deletePw })
      await logout().catch(() => {})
      navigate('/login')
    } catch (err) {
      setError(err)
    }
  }

  return (
    <div className="max-w-3xl">
      <PageHeader title="Settings & privacy" />
      <div className="mb-4 space-y-2"><ErrorAlert error={error} />{msg && <Alert kind="success">{msg}</Alert>}</div>

      <section className="card mb-6">
        <h2 className="mb-2 flex items-center gap-2 font-semibold"><ShieldCheck className="h-4 w-4" /> AI processing (OpenAI)</h2>
        <p className="text-sm text-slate-600">
          When on, TaxPilot uses OpenAI to read documents, categorize transactions and explain your taxes. Before anything is sent we remove
          SSNs, EINs, account numbers, emails and phone numbers, and we ask OpenAI not to store the data. Photos of documents can't be
          redacted, so they're only sent when this is on. When off, everything runs on built-in rules.
        </p>
        <button className={user.ai_consent ? 'btn-secondary mt-3' : 'btn-primary mt-3'} onClick={toggleAi}>
          {user.ai_consent ? 'Turn AI processing off' : 'Turn AI processing on'}
        </button>
      </section>

      <form className="card mb-6 space-y-3" onSubmit={changePassword}>
        <h2 className="flex items-center gap-2 font-semibold"><KeyRound className="h-4 w-4" /> Change password</h2>
        <input type="password" className="input" placeholder="Current password" autoComplete="current-password" required value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} />
        <input type="password" className="input" placeholder="New password (12+ chars, upper, lower, digit)" autoComplete="new-password" required minLength={12} value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} />
        <button className="btn-primary">Update password (signs out all devices)</button>
      </form>

      <section className="card mb-6">
        <h2 className="mb-2 flex items-center gap-2 font-semibold"><Download className="h-4 w-4" /> Your data</h2>
        <p className="text-sm text-slate-600">Download everything we store about you as JSON.</p>
        <button className="btn-secondary mt-3" onClick={() => exportData().catch(setError)}>Export my data</button>
      </section>

      <form className="card border-red-200" onSubmit={deleteAccount}>
        <h2 className="mb-2 flex items-center gap-2 font-semibold text-red-700"><Trash2 className="h-4 w-4" /> Delete account</h2>
        <p className="text-sm text-slate-600">Deletes your account, all transactions, forms, encrypted files and generated PDFs. Audit records keep only an anonymous id.</p>
        <div className="mt-3 flex gap-2">
          <input type="password" className="input max-w-xs" placeholder="Confirm with password" required value={deletePw} onChange={(e) => setDeletePw(e.target.value)} />
          <button className="btn-danger">Delete everything</button>
        </div>
      </form>
    </div>
  )
}
