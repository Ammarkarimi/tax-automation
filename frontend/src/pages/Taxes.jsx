import { useState } from 'react'
import { FileDown, Sparkles } from 'lucide-react'
import { api, pct, usd } from '../api/client'
import { useYear } from '../context/YearContext'
import { Alert, ErrorAlert, Markdown, PageHeader, Row, SourceBadge, Spinner, StatCard, useAsync } from '../components/ui'

const LINE_LABELS = {
  8: 'Advertising', 9: 'Car & truck', 10: 'Commissions & fees', 11: 'Contract labor', 13: 'Depreciation',
  14: 'Employee benefits', 15: 'Insurance', '16a': 'Mortgage interest', '16b': 'Other interest',
  17: 'Legal & professional', 18: 'Office expense', 19: 'Pension plans', '20a': 'Rent: equipment',
  '20b': 'Rent: property', 21: 'Repairs', 22: 'Supplies', 23: 'Taxes & licenses', '24a': 'Travel',
  '24b': 'Meals (50%)', 25: 'Utilities', 26: 'Wages', '27b': 'Other expenses',
}

export default function Taxes() {
  const { year } = useYear()
  const { data: r, error, loading } = useAsync(() => api.get('/tax/annual', { year }), [year])
  const reports = useAsync(() => api.get('/tax/reports', { year }), [year])
  const [explanation, setExplanation] = useState(null)
  const [busy, setBusy] = useState(null)
  const [err, setErr] = useState(null)

  if (loading) return <Spinner />
  if (error) return <ErrorAlert error={error} />
  const s = r.summary, sc = r.schedule_c, f = r.form_1040

  const explain = async () => {
    setBusy('explain')
    try {
      setExplanation(await api.get('/tax/explain', { year }))
    } catch (e) {
      setErr(e)
    } finally {
      setBusy(null)
    }
  }

  const generatePdf = async () => {
    setBusy('pdf')
    setErr(null)
    try {
      const rep = await api.post('/tax/reports/return-pdf', undefined, { year })
      await api.download(`/tax/reports/${rep.id}/download`, `tax-return-${year}.pdf`)
      reports.reload()
    } catch (e) {
      setErr(e)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div>
      <PageHeader
        title={`${year} Annual Return`}
        subtitle="Form 1040 with Schedules C, SE, 1 & 2 — calculated from your data."
        actions={
          <>
            <button className="btn-secondary" onClick={explain} disabled={busy}><Sparkles className="h-4 w-4" />{busy === 'explain' ? 'Explaining…' : 'Explain my taxes'}</button>
            <button className="btn-primary" onClick={generatePdf} disabled={busy}><FileDown className="h-4 w-4" />{busy === 'pdf' ? 'Generating…' : 'Download return PDF'}</button>
          </>
        }
      />
      <ErrorAlert error={err} />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Total tax" value={usd(s.total_tax)} hint={`Effective ${pct(s.effective_rate)} · bracket ${pct(s.marginal_income_rate, 0)}`} />
        <StatCard label="Income tax" value={usd(s.income_tax)} />
        <StatCard label="Self-employment tax" value={usd(s.self_employment_tax)} hint="Social Security + Medicare" />
        <StatCard label={s.balance_due > 0 ? 'Amount you owe' : 'Refund'} value={usd(s.balance_due || s.refund)} tone={s.balance_due > 0 ? 'bad' : 'good'} />
      </div>

      {explanation && (
        <div className="card mt-6">
          <div className="mb-2"><SourceBadge source={explanation.source} /></div>
          <Markdown>{explanation.markdown}</Markdown>
        </div>
      )}

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <div className="card">
          <h2 className="mb-2 font-semibold">Schedule C — Profit or Loss</h2>
          <Row label="Gross receipts (line 1)" value={usd(sc.line1_gross_receipts)} />
          {sc.line2_returns_allowances > 0 && <Row label="Returns & allowances (2)" value={`−${usd(sc.line2_returns_allowances)}`} />}
          {sc.line4_cogs > 0 && <Row label="Cost of goods sold (4)" value={`−${usd(sc.line4_cogs)}`} />}
          {sc.line6_other_income > 0 && <Row label="Other income (6)" value={usd(sc.line6_other_income)} />}
          <Row label="Gross income (7)" value={usd(sc.line7_gross_income)} strong />
          {Object.entries(sc.expenses_by_line).map(([line, amt]) => (
            <Row key={line} indent label={`${LINE_LABELS[line] || 'Other'} (${line})`} value={`−${usd(amt)}`} />
          ))}
          {sc.line30_home_office > 0 && <Row indent label="Home office (30)" value={`−${usd(sc.line30_home_office)}`} />}
          <div className="mt-2 border-t pt-2"><Row label="Net profit (31)" value={usd(sc.line31_net_profit)} strong /></div>
        </div>

        <div className="card">
          <h2 className="mb-2 font-semibold">Form 1040 summary</h2>
          <Row label="Total income (9)" value={usd(f.line9_total_income)} />
          <Row indent label="½ SE tax, SEP, health ins. (10)" value={`−${usd(f.line10_adjustments)}`} />
          <Row label="Adjusted gross income (11)" value={usd(f.line11_agi)} strong />
          <Row indent label="Standard deduction (12)" value={`−${usd(f.line12_standard_deduction)}`} />
          <Row indent label="QBI deduction (13a)" value={`−${usd(f.line13a_qbi_deduction)}`} />
          {f.line13b_schedule_1a_deductions > 0 && <Row indent label="Tips / senior deductions (13b)" value={`−${usd(f.line13b_schedule_1a_deductions)}`} />}
          <Row label="Taxable income (15)" value={usd(f.line15_taxable_income)} strong />
          <Row label="Tax (16)" value={usd(f.line16_tax)} />
          {f.line19_child_tax_credit > 0 && <Row indent label="Child tax credit (19)" value={`−${usd(f.line19_child_tax_credit)}`} />}
          <Row label="Self-employment & other taxes (23)" value={usd(f.line23_other_taxes)} />
          <Row label="Total tax (24)" value={usd(f.line24_total_tax)} strong />
          <Row indent label="Withholding (25)" value={`−${usd(f.line25_withholding)}`} />
          <Row indent label="Estimated payments (26)" value={`−${usd(f.line26_estimated_payments)}`} />
          {f.line28_actc > 0 && <Row indent label="Additional child tax credit (28)" value={`−${usd(f.line28_actc)}`} />}
          <div className="mt-2 border-t pt-2">
            {f.line37_amount_owed > 0 ? <Row label="Amount you owe (37)" value={usd(f.line37_amount_owed)} strong /> : <Row label="Refund (34)" value={usd(f.line34_overpaid)} strong />}
          </div>
        </div>
      </div>

      {r.warnings.length > 0 && (
        <div className="mt-6 space-y-2">
          {r.warnings.map((w) => <Alert key={w} kind="warning">{w}</Alert>)}
        </div>
      )}

      <div className="card mt-6">
        <h2 className="mb-2 font-semibold">Generated PDFs</h2>
        <p className="mb-3 text-sm text-slate-500">
          The PDF is a filing-ready worksheet with official line numbers. Transcribe it onto the IRS forms or into filing software — TaxPilot never submits returns.
        </p>
        {reports.data?.length ? (
          <ul className="divide-y divide-slate-100 text-sm">
            {reports.data.map((rep) => (
              <li key={rep.id} className="flex items-center justify-between py-2">
                <span>{new Date(rep.created_at).toLocaleString()} <span className="font-mono text-xs text-slate-400">sha256 {rep.sha256.slice(0, 12)}…</span></span>
                <button className="text-brand-600 hover:underline" onClick={() => api.download(`/tax/reports/${rep.id}/download`, `tax-return-${year}.pdf`)}>Download</button>
              </li>
            ))}
          </ul>
        ) : <p className="text-sm text-slate-400">None yet.</p>}
      </div>
    </div>
  )
}
