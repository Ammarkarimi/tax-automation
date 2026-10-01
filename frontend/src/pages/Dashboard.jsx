import { Link } from 'react-router-dom'
import { BadgePercent, CalendarClock, CircleDollarSign, FileText, Landmark, ShieldAlert, TrendingUp } from 'lucide-react'
import { api, pct, usd } from '../api/client'
import { useYear } from '../context/YearContext'
import { Alert, Badge, ErrorAlert, PageHeader, Spinner, StatCard, useAsync } from '../components/ui'

const RISK_TONE = { low: 'green', medium: 'amber', high: 'red' }

export default function Dashboard() {
  const { year } = useYear()
  const { data, error, loading } = useAsync(async () => {
    const [annual, quarterly, risk, deductions] = await Promise.all([
      api.get('/tax/annual', { year }),
      api.get('/tax/quarterly', { year: new Date().getFullYear() }).catch(() => null),
      api.get('/tax/audit-risk', { year }),
      api.get('/tax/deductions', { year }),
    ])
    return { annual, quarterly, risk, deductions }
  }, [year])

  if (loading) return <Spinner />
  if (error) return <ErrorAlert error={error} />
  const { annual, quarterly, risk, deductions } = data
  const s = annual.summary
  const dq = annual.data_quality
  const empty = dq.transactions === 0 && s.gross_income === 0

  return (
    <div>
      <PageHeader title={`Your ${year} taxes at a glance`} subtitle="Everything updates automatically as you add documents and transactions." />

      {empty && (
        <div className="card mb-6">
          <h2 className="mb-3 font-semibold">Get started in 3 steps</h2>
          <ol className="space-y-2 text-sm text-slate-600">
            <li>1. <Link to="/profile" className="text-brand-600 hover:underline">Fill your tax profile</Link> — filing status, business type, inventory.</li>
            <li>2. <Link to="/documents" className="text-brand-600 hover:underline">Upload documents</Link> — bank CSV export, 1099s, W-2s, receipts.</li>
            <li>3. Review the auto-categorized <Link to="/transactions" className="text-brand-600 hover:underline">transactions</Link>, then download your return PDF.</li>
          </ol>
        </div>
      )}

      {dq.needs_review > 0 && (
        <Alert kind="warning" className="mb-6">
          {dq.needs_review} transactions need a quick review. <Link to="/transactions?review=1" className="font-medium underline">Review now</Link>
        </Alert>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Business profit" value={usd(s.business_net_profit)} icon={TrendingUp} hint="Schedule C, line 31" />
        <StatCard label="Total tax" value={usd(s.total_tax)} icon={Landmark} hint={`Effective rate ${pct(s.effective_rate)}`} />
        <StatCard
          label={s.balance_due > 0 ? 'Still to pay' : 'Expected refund'}
          value={usd(s.balance_due > 0 ? s.balance_due : s.refund)}
          tone={s.balance_due > 0 ? 'bad' : 'good'}
          icon={CircleDollarSign}
          hint={`${usd(s.total_payments)} already paid/withheld`}
        />
        <StatCard
          label="Possible extra savings"
          value={usd(deductions.potential_savings)}
          tone="brand"
          icon={BadgePercent}
          hint={<Link to="/deductions" className="underline">See deduction ideas</Link>}
        />
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-3">
        <div className="card lg:col-span-2">
          <h2 className="mb-3 flex items-center gap-2 font-semibold"><CalendarClock className="h-4 w-4" /> Next quarterly payment</h2>
          {quarterly?.next_payment ? (
            <div>
              <div className="text-3xl font-semibold">{usd(quarterly.next_payment.amount)}</div>
              <div className="mt-1 text-sm text-slate-500">
                Q{quarterly.next_payment.quarter} {quarterly.tax_year} · due {quarterly.next_payment.due_date} · based on {quarterly.safe_harbor_basis}
              </div>
              <Link to="/quarterly" className="btn-secondary mt-4">Plan quarterly payments</Link>
            </div>
          ) : (
            <p className="text-sm text-slate-500">No payment due right now. <Link to="/quarterly" className="text-brand-600 hover:underline">View schedule</Link></p>
          )}
        </div>
        <div className="card">
          <h2 className="mb-3 flex items-center gap-2 font-semibold"><ShieldAlert className="h-4 w-4" /> Audit-risk check</h2>
          <div className="flex items-center gap-3">
            <div className="text-3xl font-semibold">{risk.score}</div>
            <Badge tone={RISK_TONE[risk.level]}>{risk.level.toUpperCase()}</Badge>
          </div>
          <ul className="mt-3 space-y-1 text-sm text-slate-600">
            {risk.factors.slice(0, 3).map((f) => <li key={f.id}>• {f.title}</li>)}
            {risk.factors.length === 0 && <li>No red flags found.</li>}
          </ul>
          <Link to="/audit-risk" className="mt-3 inline-block text-sm text-brand-600 hover:underline">Details →</Link>
        </div>
      </div>

      <div className="mt-6 grid gap-4 sm:grid-cols-3">
        <Link to="/documents" className="card hover:border-brand-500"><FileText className="mb-2 h-5 w-5 text-brand-600" /><div className="font-medium">Upload documents</div><div className="text-sm text-slate-500">{dq.transactions} transactions imported</div></Link>
        <Link to="/taxes" className="card hover:border-brand-500"><Landmark className="mb-2 h-5 w-5 text-brand-600" /><div className="font-medium">Annual return</div><div className="text-sm text-slate-500">Form 1040 + Schedule C PDF</div></Link>
        <Link to="/assistant" className="card hover:border-brand-500"><BadgePercent className="mb-2 h-5 w-5 text-brand-600" /><div className="font-medium">Ask the assistant</div><div className="text-sm text-slate-500">Plain-English answers about your taxes</div></Link>
      </div>
    </div>
  )
}
