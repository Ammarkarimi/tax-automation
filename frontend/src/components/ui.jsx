import { useCallback, useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { AlertTriangle, CheckCircle2, Info, Loader2 } from 'lucide-react'

/** Load data on mount / when deps change; returns { data, error, loading, reload }. */
export function useAsync(fn, deps = []) {
  const [state, setState] = useState({ data: null, error: null, loading: true })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(fn, deps)
  const reload = useCallback(() => {
    setState((s) => ({ ...s, loading: true, error: null }))
    return run()
      .then((data) => setState({ data, error: null, loading: false }))
      .catch((error) => setState({ data: null, error, loading: false }))
  }, [run])
  useEffect(() => {
    reload()
  }, [reload])
  return { ...state, reload }
}

export function Spinner({ label = 'Loading…' }) {
  return (
    <div className="flex items-center gap-2 py-8 text-sm text-slate-500" role="status">
      <Loader2 className="h-4 w-4 animate-spin" /> {label}
    </div>
  )
}

const ALERT_STYLES = {
  error: ['border-red-200 bg-red-50 text-red-800', AlertTriangle],
  warning: ['border-amber-200 bg-amber-50 text-amber-900', AlertTriangle],
  success: ['border-emerald-200 bg-emerald-50 text-emerald-800', CheckCircle2],
  info: ['border-brand-100 bg-brand-50 text-brand-900', Info],
}

export function Alert({ kind = 'info', children, className = '' }) {
  const [cls, Icon] = ALERT_STYLES[kind]
  return (
    <div className={`flex gap-2 rounded-lg border px-3 py-2 text-sm ${cls} ${className}`} role={kind === 'error' ? 'alert' : undefined}>
      <Icon className="mt-0.5 h-4 w-4 shrink-0" />
      <div>{children}</div>
    </div>
  )
}

export function ErrorAlert({ error }) {
  if (!error) return null
  return <Alert kind="error">{error.message || String(error)}</Alert>
}

export function PageHeader({ title, subtitle, actions }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-slate-500">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  )
}

export function StatCard({ label, value, hint, tone = 'default', icon: Icon }) {
  const tones = {
    default: 'text-slate-900',
    good: 'text-emerald-700',
    bad: 'text-red-700',
    brand: 'text-brand-700',
  }
  return (
    <div className="card">
      <div className="flex items-center justify-between text-sm text-slate-500">
        <span>{label}</span>
        {Icon && <Icon className="h-4 w-4" />}
      </div>
      <div className={`mt-2 text-2xl font-semibold ${tones[tone]}`}>{value}</div>
      {hint && <div className="mt-1 text-xs text-slate-500">{hint}</div>}
    </div>
  )
}

export function Badge({ children, tone = 'slate' }) {
  const tones = {
    slate: 'bg-slate-100 text-slate-700',
    green: 'bg-emerald-100 text-emerald-800',
    red: 'bg-red-100 text-red-800',
    amber: 'bg-amber-100 text-amber-900',
    blue: 'bg-brand-100 text-brand-700',
    purple: 'bg-purple-100 text-purple-800',
  }
  return <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${tones[tone]}`}>{children}</span>
}

/** Renders model/template Markdown safely (react-markdown never injects raw HTML). */
export function Markdown({ children }) {
  return (
    <div className="prose-tax text-sm leading-relaxed text-slate-700">
      <ReactMarkdown>{children || ''}</ReactMarkdown>
    </div>
  )
}

export function EmptyState({ icon: Icon, title, children }) {
  return (
    <div className="card flex flex-col items-center py-12 text-center">
      {Icon && <Icon className="mb-3 h-10 w-10 text-slate-300" />}
      <h3 className="font-medium text-slate-800">{title}</h3>
      <div className="mt-1 max-w-md text-sm text-slate-500">{children}</div>
    </div>
  )
}

export function SourceBadge({ source }) {
  return source === 'ai' ? <Badge tone="purple">AI explanation</Badge> : <Badge>Standard explanation</Badge>
}

export function Row({ label, value, strong, indent }) {
  return (
    <div className={`flex justify-between py-1.5 text-sm ${strong ? 'font-semibold text-slate-900' : 'text-slate-600'} ${indent ? 'pl-4' : ''}`}>
      <span>{label}</span>
      <span className="tabular-nums">{value}</span>
    </div>
  )
}
