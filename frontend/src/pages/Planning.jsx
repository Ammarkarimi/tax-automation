/** Planning pages: quarterly estimates, deduction finder, audit risk. */
import { useState } from 'react'
import { BadgePercent, Plus, ShieldAlert, Sparkles, Trash2 } from 'lucide-react'
import { api, usd } from '../api/client'
import { useYear } from '../context/YearContext'
import { Alert, Badge, ErrorAlert, Markdown, PageHeader, SourceBadge, Spinner, StatCard, useAsync } from '../components/ui'

const Q_TONE = { paid: 'green', covered: 'green', upcoming: 'amber', underpaid: 'red' }

export function Quarterly() {
  const { meta } = useYear()
  const thisYear = new Date().getFullYear()
  const years = meta.supported_years.filter((y) => y >= thisYear - 1)
  const [year, setYear] = useState(meta.supported_years.includes(thisYear) ? thisYear : meta.supported_years.at(-1))
  const q = useAsync(() => api.get('/tax/quarterly', { year }), [year])
  const payments = useAsync(() => api.get('/estimated-payments', { year }), [year])
  const [form, setForm] = useState({ quarter: 1, amount: '', paid_on: '' })
  const [error, setError] = useState(null)

  const addPayment = async (e) => {
    e.preventDefault()
    try {
      await api.post('/estimated-payments', { ...form, quarter: Number(form.quarter), amount: Number(form.amount) }, { year })
      setForm({ quarter: 1, amount: '', paid_on: '' })
      payments.reload()
      q.reload()
    } catch (err) {
      setError(err)
    }
  }

  return (
    <div>
      <PageHeader
        title="Quarterly estimated taxes"
        subtitle="Self-employed people pay tax during the year (Form 1040-ES). Pay enough on time and there's no underpayment penalty."
        actions={
          <select className="input w-28" value={year} onChange={(e) => setYear(Number(e.target.value))}>
            {years.map((y) => <option key={y}>{y}</option>)}
          </select>
        }
      />
      {q.loading ? <Spinner /> : q.error ? <ErrorAlert error={q.error} /> : (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            <StatCard label="Projected full-year tax" value={usd(q.data.projected_total_tax)} hint={`Annualized from activity to ${q.data.as_of}`} />
            <StatCard label="Safe-harbor target" value={usd(q.data.required_annual_payment)} hint={q.data.safe_harbor_basis} tone="brand" />
            <StatCard label="Each installment" value={usd(q.data.installment_amount)} hint={`${usd(q.data.total_estimated_paid)} paid so far`} />
          </div>
          <div className="card mt-6 overflow-x-auto p-0">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-slate-500"><tr><th className="p-3">Quarter</th><th className="p-3">Due date</th><th className="p-3 text-right">Cumulative target</th><th className="p-3 text-right">Paid by due date</th><th className="p-3 text-right">Amount due</th><th className="p-3">Status</th></tr></thead>
              <tbody>
                {q.data.quarters.map((row) => (
                  <tr key={row.quarter} className="border-t border-slate-100">
                    <td className="p-3 font-medium">Q{row.quarter}</td>
                    <td className="p-3">{row.due_date}</td>
                    <td className="p-3 text-right tabular-nums">{usd(row.cumulative_required)}</td>
                    <td className="p-3 text-right tabular-nums">{usd(row.paid_by_due_date)}</td>
                    <td className="p-3 text-right font-medium tabular-nums">{usd(row.amount_due)}</td>
                    <td className="p-3"><Badge tone={Q_TONE[row.status]}>{row.status}</Badge></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-4 space-y-2">{q.data.notes.map((n) => <Alert key={n}>{n}</Alert>)}</div>
        </>
      )}

      <div className="card mt-6">
        <h2 className="mb-3 font-semibold">Payments you've made ({year})</h2>
        <form onSubmit={addPayment} className="mb-4 flex flex-wrap items-end gap-3">
          <ErrorAlert error={error} />
          <div><label className="label">Quarter</label><select className="input" value={form.quarter} onChange={(e) => setForm({ ...form, quarter: e.target.value })}>{[1, 2, 3, 4].map((n) => <option key={n} value={n}>Q{n}</option>)}</select></div>
          <div><label className="label">Amount</label><input type="number" min="0.01" step="0.01" required className="input" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} /></div>
          <div><label className="label">Paid on</label><input type="date" required className="input" value={form.paid_on} onChange={(e) => setForm({ ...form, paid_on: e.target.value })} /></div>
          <button className="btn-primary"><Plus className="h-4 w-4" /> Record payment</button>
        </form>
        <ul className="divide-y divide-slate-100 text-sm">
          {payments.data?.map((p) => (
            <li key={p.id} className="flex items-center justify-between py-2">
              <span>Q{p.quarter} · {p.paid_on} · <strong>{usd(Number(p.amount), 2)}</strong></span>
              <button className="text-red-500" onClick={async () => { await api.del(`/estimated-payments/${p.id}`); payments.reload(); q.reload() }} aria-label="Delete payment"><Trash2 className="h-4 w-4" /></button>
            </li>
          ))}
          {payments.data?.length === 0 && <li className="py-2 text-slate-400">No payments recorded. Bank transactions categorized as “estimated tax payment” are used when this list is empty.</li>}
        </ul>
      </div>
    </div>
  )
}

const STATUS = {
  warning: ['amber', 'Check this'],
  opportunity: ['blue', 'Opportunity'],
  info: ['slate', 'Tip'],
  applied: ['green', 'Applied'],
}

export function Deductions() {
  const { year } = useYear()
  const [withAi, setWithAi] = useState(false)
  const d = useAsync(() => api.get('/tax/deductions', { year, include_ai: withAi }), [year, withAi])

  return (
    <div>
      <PageHeader
        title="Deduction finder"
        subtitle="Every legitimate deduction lowers both income tax and self-employment tax."
        actions={<button className="btn-secondary" onClick={() => setWithAi(true)} disabled={withAi}><Sparkles className="h-4 w-4" /> Find more with AI</button>}
      />
      {d.loading ? <Spinner /> : d.error ? <ErrorAlert error={d.error} /> : (
        <>
          <StatCard label="Estimated savings from open opportunities" value={usd(d.data.potential_savings)} tone="brand" icon={BadgePercent} />
          {withAi && !d.data.ai_used && <Alert kind="info" className="mt-4">AI suggestions need an OpenAI key on the server and AI processing switched on in Settings.</Alert>}
          <div className="mt-6 grid gap-4 md:grid-cols-2">
            {d.data.suggestions.map((s) => {
              const [tone, label] = STATUS[s.status] || STATUS.info
              return (
                <div key={s.id} className="card">
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <h3 className="font-semibold">{s.title}</h3>
                    <div className="flex gap-1">{s.source === 'ai' && <Badge tone="purple">AI</Badge>}<Badge tone={tone}>{label}</Badge></div>
                  </div>
                  <p className="text-sm text-slate-600">{s.description}</p>
                  {s.estimated_savings > 0 && (
                    <p className="mt-2 text-sm"><strong className="text-emerald-700">≈ {usd(s.estimated_savings)} saved</strong> <span className="text-slate-400">on {usd(s.estimated_deduction)} deducted</span></p>
                  )}
                  <p className="mt-2 text-xs font-medium text-brand-700">→ {s.action}</p>
                </div>
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}

const SEV_TONE = { high: 'red', medium: 'amber', low: 'slate' }

export function AuditRisk() {
  const { year } = useYear()
  const [explain, setExplain] = useState(false)
  const r = useAsync(() => api.get('/tax/audit-risk', { year, explain }), [year, explain])

  return (
    <div>
      <PageHeader
        title="Audit-risk check"
        subtitle="Fix these before filing. Accurate, documented returns are your best protection."
        actions={<button className="btn-secondary" onClick={() => setExplain(true)} disabled={explain}><Sparkles className="h-4 w-4" /> Explain in plain English</button>}
      />
      {r.loading ? <Spinner /> : r.error ? <ErrorAlert error={r.error} /> : (
        <>
          <div className="card flex items-center gap-6">
            <ShieldAlert className={`h-12 w-12 ${r.data.level === 'high' ? 'text-red-500' : r.data.level === 'medium' ? 'text-amber-500' : 'text-emerald-500'}`} />
            <div>
              <div className="text-3xl font-semibold">{r.data.score}<span className="text-base text-slate-400">/100</span></div>
              <Badge tone={{ low: 'green', medium: 'amber', high: 'red' }[r.data.level]}>{r.data.level.toUpperCase()} RISK</Badge>
            </div>
            <p className="ml-auto max-w-md text-xs text-slate-500">{r.data.disclaimer}</p>
          </div>
          {r.data.explanation && (
            <div className="card mt-6"><div className="mb-2"><SourceBadge source={r.data.explanation.source} /></div><Markdown>{r.data.explanation.markdown}</Markdown></div>
          )}
          <div className="mt-6 space-y-3">
            {r.data.factors.map((f) => (
              <div key={f.id} className="card">
                <div className="flex items-center justify-between"><h3 className="font-semibold">{f.title}</h3><Badge tone={SEV_TONE[f.severity]}>{f.severity} · +{f.points}</Badge></div>
                <p className="mt-1 text-sm text-slate-600">{f.detail}</p>
                <p className="mt-2 text-sm text-brand-700"><strong>What to do:</strong> {f.recommendation}</p>
              </div>
            ))}
            {r.data.factors.length === 0 && <Alert kind="success">No red flags found for {year}.</Alert>}
          </div>
        </>
      )}
    </div>
  )
}
