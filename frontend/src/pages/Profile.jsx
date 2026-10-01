import { useEffect, useState } from 'react'
import { Save } from 'lucide-react'
import { api } from '../api/client'
import { useYear } from '../context/YearContext'
import { Alert, ErrorAlert, PageHeader, Spinner, useAsync } from '../components/ui'

const NUM_FIELDS = ['qualifying_children', 'other_dependents', 'home_office_sqft', 'business_miles']
const MONEY_FIELDS = ['beginning_inventory', 'ending_inventory', 'qualified_tips', 'other_income', 'prior_year_tax', 'prior_year_agi']

function Field({ label, hint, children }) {
  return (
    <div>
      <label className="label">{label}</label>
      {children}
      {hint && <p className="mt-1 text-xs text-slate-400">{hint}</p>}
    </div>
  )
}

export default function Profile() {
  const { year } = useYear()
  const p = useAsync(() => api.get('/profile', { year }), [year])
  const [f, setF] = useState(null)
  const [ssn, setSsn] = useState('')
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (p.data) setF(p.data)
  }, [p.data])

  if (p.loading || !f) return <Spinner />
  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })

  const save = async (e) => {
    e.preventDefault()
    setError(null)
    setSaved(false)
    const body = {
      filing_status: f.filing_status,
      taxpayer_name: f.taxpayer_name || null,
      address: f.address || null,
      business_name: f.business_name || null,
      business_description: f.business_description || null,
      business_code: f.business_code || null,
      is_cash_intensive: f.is_cash_intensive,
      is_sstb: f.is_sstb,
      age_65_or_older: f.age_65_or_older,
      spouse_age_65_or_older: f.spouse_age_65_or_older,
    }
    NUM_FIELDS.forEach((k) => (body[k] = Number(f[k] || 0)))
    MONEY_FIELDS.forEach((k) => (body[k] = f[k] === '' || f[k] == null ? (k.startsWith('prior') ? null : 0) : Number(f[k])))
    if (ssn) body.ssn = ssn
    try {
      setF(await api.put('/profile', body, { year }))
      setSsn('')
      setSaved(true)
    } catch (err) {
      setError(err)
    }
  }

  return (
    <form onSubmit={save}>
      <PageHeader
        title={`Tax profile — ${year}`}
        subtitle="Facts that aren't in your bank data. Sensitive fields (name, SSN, address) are encrypted."
        actions={<button className="btn-primary"><Save className="h-4 w-4" /> Save</button>}
      />
      <div className="mb-4 space-y-2">
        <ErrorAlert error={error} />
        {saved && <Alert kind="success">Saved. Your calculations are updated.</Alert>}
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="card space-y-4">
          <h2 className="font-semibold">You & your household</h2>
          <Field label="Filing status">
            <select className="input" value={f.filing_status} onChange={set('filing_status')}>
              <option value="single">Single</option>
              <option value="married_joint">Married filing jointly</option>
              <option value="married_separate">Married filing separately</option>
              <option value="head_of_household">Head of household</option>
            </select>
          </Field>
          <Field label="Legal name (for the PDF)"><input className="input" value={f.taxpayer_name || ''} onChange={set('taxpayer_name')} /></Field>
          <Field label="SSN" hint={f.ssn_last4 ? `On file: •••-••-${f.ssn_last4}. Enter a new one to replace it.` : 'Optional. Stored encrypted; the PDF shows only the last 4 digits.'}>
            <input className="input" autoComplete="off" inputMode="numeric" placeholder="123-45-6789" value={ssn} onChange={(e) => setSsn(e.target.value)} pattern="\d{3}-?\d{2}-?\d{4}" />
          </Field>
          <Field label="Address"><input className="input" value={f.address || ''} onChange={set('address')} /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Children under 17"><input type="number" min="0" className="input" value={f.qualifying_children} onChange={set('qualifying_children')} /></Field>
            <Field label="Other dependents"><input type="number" min="0" className="input" value={f.other_dependents} onChange={set('other_dependents')} /></Field>
          </div>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.age_65_or_older} onChange={set('age_65_or_older')} /> I am 65 or older</label>
          {f.filing_status === 'married_joint' && <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.spouse_age_65_or_older} onChange={set('spouse_age_65_or_older')} /> My spouse is 65 or older</label>}
        </section>

        <section className="card space-y-4">
          <h2 className="font-semibold">Your business (Schedule C)</h2>
          <Field label="Business name"><input className="input" value={f.business_name || ''} onChange={set('business_name')} /></Field>
          <Field label="What does the business do?" hint="Helps the AI categorize transactions, e.g. “convenience store”, “rideshare driver”.">
            <input className="input" value={f.business_description || ''} onChange={set('business_description')} />
          </Field>
          <Field label="Principal business code (NAICS, 6 digits)" hint="E.g. 445131 convenience retailers, 485310 taxi & rideshare, 541990 other professional services.">
            <input className="input" pattern="\d{6}" value={f.business_code || ''} onChange={set('business_code')} />
          </Field>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.is_cash_intensive} onChange={set('is_cash_intensive')} /> I take a lot of cash (shop, restaurant, salon…)</label>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.is_sstb} onChange={set('is_sstb')} /> Professional service (consulting, health, law, finance, performing arts)</label>
        </section>

        <section className="card space-y-4">
          <h2 className="font-semibold">Inventory (for shops & resellers)</h2>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Stock value on Jan 1"><input type="number" min="0" step="0.01" className="input" value={f.beginning_inventory} onChange={set('beginning_inventory')} /></Field>
            <Field label="Stock value on Dec 31"><input type="number" min="0" step="0.01" className="input" value={f.ending_inventory} onChange={set('ending_inventory')} /></Field>
          </div>
          <p className="text-xs text-slate-400">Cost of goods sold = opening stock + purchases (transactions in “inventory purchases”) − closing stock.</p>
        </section>

        <section className="card space-y-4">
          <h2 className="font-semibold">Deductions & planning</h2>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Home office (sq ft)" hint="Exclusive business use; max 300 counted"><input type="number" min="0" className="input" value={f.home_office_sqft} onChange={set('home_office_sqft')} /></Field>
            <Field label="Business miles driven" hint="From your mileage log"><input type="number" min="0" className="input" value={f.business_miles} onChange={set('business_miles')} /></Field>
            <Field label="Qualified tips received" hint="2025–2028 deduction"><input type="number" min="0" step="0.01" className="input" value={f.qualified_tips} onChange={set('qualified_tips')} /></Field>
            <Field label="Other taxable income"><input type="number" step="0.01" className="input" value={f.other_income} onChange={set('other_income')} /></Field>
            <Field label="Last year's total tax" hint="Form 1040 line 24 — used for safe harbor"><input type="number" min="0" step="0.01" className="input" value={f.prior_year_tax ?? ''} onChange={set('prior_year_tax')} /></Field>
            <Field label="Last year's AGI" hint="Form 1040 line 11"><input type="number" step="0.01" className="input" value={f.prior_year_agi ?? ''} onChange={set('prior_year_agi')} /></Field>
          </div>
        </section>
      </div>
    </form>
  )
}
