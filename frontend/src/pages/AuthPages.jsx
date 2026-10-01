import { useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { KeyRound, Lock, Mail } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { Alert, ErrorAlert } from '../components/ui'

function AuthShell({ title, subtitle, children }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-brand-900 to-brand-600 p-4">
      <div className="w-full max-w-md rounded-2xl bg-white p-8 shadow-xl">
        <div className="mb-6 text-center">
          <div className="text-3xl">🧾</div>
          <h1 className="mt-2 text-xl font-semibold">{title}</h1>
          {subtitle && <p className="mt-1 text-sm text-slate-500">{subtitle}</p>}
        </div>
        {children}
      </div>
    </div>
  )
}

export function LoginPage() {
  const { login, user } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  if (user) return <Navigate to="/" replace />

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(email, password)
      navigate('/verify')
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthShell title="Sign in to TaxPilot" subtitle="Your taxes, done right — without hiring a CA/CPA.">
      <form onSubmit={submit} className="space-y-4">
        <ErrorAlert error={error} />
        <div>
          <label className="label" htmlFor="email">Email</label>
          <input id="email" type="email" autoComplete="email" required className="input" value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div>
          <label className="label" htmlFor="password">Password</label>
          <input id="password" type="password" autoComplete="current-password" required className="input" value={password} onChange={(e) => setPassword(e.target.value)} />
        </div>
        <button className="btn-primary w-full" disabled={busy}>
          <Lock className="h-4 w-4" /> {busy ? 'Checking…' : 'Continue'}
        </button>
        <p className="text-center text-sm text-slate-500">
          New here? <Link className="text-brand-600 hover:underline" to="/register">Create an account</Link>
        </p>
      </form>
    </AuthShell>
  )
}

export function RegisterPage() {
  const { register } = useAuth()
  const navigate = useNavigate()
  const [form, setForm] = useState({ name: '', email: '', password: '', confirm: '' })
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })

  const rules = [
    [form.password.length >= 12, 'At least 12 characters'],
    [/[a-z]/.test(form.password), 'A lowercase letter'],
    [/[A-Z]/.test(form.password), 'An uppercase letter'],
    [/\d/.test(form.password), 'A number'],
  ]

  const submit = async (e) => {
    e.preventDefault()
    if (form.password !== form.confirm) return setError(new Error('Passwords do not match'))
    setBusy(true)
    setError(null)
    try {
      await register(form.email, form.password, form.name)
      navigate('/verify')
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthShell title="Create your account" subtitle="We'll email you a code to verify it's you.">
      <form onSubmit={submit} className="space-y-4">
        <ErrorAlert error={error} />
        <div>
          <label className="label" htmlFor="name">Your name</label>
          <input id="name" className="input" autoComplete="name" value={form.name} onChange={set('name')} />
        </div>
        <div>
          <label className="label" htmlFor="remail">Email</label>
          <input id="remail" type="email" required className="input" autoComplete="email" value={form.email} onChange={set('email')} />
        </div>
        <div>
          <label className="label" htmlFor="rpw">Password</label>
          <input id="rpw" type="password" required className="input" autoComplete="new-password" value={form.password} onChange={set('password')} />
          <ul className="mt-2 grid grid-cols-2 gap-1 text-xs">
            {rules.map(([ok, text]) => (
              <li key={text} className={ok ? 'text-emerald-600' : 'text-slate-400'}>
                {ok ? '✓' : '○'} {text}
              </li>
            ))}
          </ul>
        </div>
        <div>
          <label className="label" htmlFor="rpw2">Confirm password</label>
          <input id="rpw2" type="password" required className="input" autoComplete="new-password" value={form.confirm} onChange={set('confirm')} />
        </div>
        <button className="btn-primary w-full" disabled={busy || !rules.every(([ok]) => ok)}>
          {busy ? 'Creating…' : 'Create account'}
        </button>
        <p className="text-center text-sm text-slate-500">
          Already have an account? <Link className="text-brand-600 hover:underline" to="/login">Sign in</Link>
        </p>
      </form>
    </AuthShell>
  )
}

export function VerifyOtpPage() {
  const { challenge, verifyOtp, resendOtp, user } = useAuth()
  const navigate = useNavigate()
  const [code, setCode] = useState('')
  const [error, setError] = useState(null)
  const [info, setInfo] = useState(null)
  const [busy, setBusy] = useState(false)

  if (user) return <Navigate to="/" replace />
  if (!challenge) return <Navigate to="/login" replace />

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await verifyOtp(code)
      navigate('/')
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthShell title="Check your email" subtitle={`We sent a 6-digit code to ${challenge.masked_email}.`}>
      <form onSubmit={submit} className="space-y-4">
        <ErrorAlert error={error} />
        {info && <Alert kind="success">{info}</Alert>}
        <div>
          <label className="label" htmlFor="otp">Verification code</label>
          <input
            id="otp"
            inputMode="numeric"
            autoComplete="one-time-code"
            pattern="\d{6}"
            maxLength={6}
            required
            autoFocus
            className="input text-center font-mono text-2xl tracking-[0.5em]"
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
          />
        </div>
        <button className="btn-primary w-full" disabled={busy || code.length !== 6}>
          <KeyRound className="h-4 w-4" /> {busy ? 'Verifying…' : 'Verify & sign in'}
        </button>
        <button
          type="button"
          className="btn-secondary w-full"
          onClick={async () => {
            try {
              await resendOtp()
              setInfo('A new code is on its way.')
            } catch (err) {
              setError(err)
            }
          }}
        >
          <Mail className="h-4 w-4" /> Send a new code
        </button>
        <p className="text-center text-xs text-slate-400">
          Local dev: the code is printed in the backend console (or Mailpit at localhost:8025).
        </p>
      </form>
    </AuthShell>
  )
}
