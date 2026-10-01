import { useRef, useState } from 'react'
import { Download, FileUp, RefreshCw, Trash2, Upload } from 'lucide-react'
import { api, usd } from '../api/client'
import { useYear } from '../context/YearContext'
import { Alert, Badge, EmptyState, ErrorAlert, PageHeader, Spinner, useAsync } from '../components/ui'

const DOC_TYPES = [
  ['', 'Detect automatically'],
  ['bank_csv', 'Bank / card statement (CSV)'],
  ['1099_nec', '1099-NEC'],
  ['1099_k', '1099-K'],
  ['1099_misc', '1099-MISC'],
  ['1099_int', '1099-INT'],
  ['1099_div', '1099-DIV'],
  ['w2', 'W-2'],
  ['invoice', 'Invoice (you issued)'],
  ['receipt', 'Receipt / bill (you paid)'],
]

const FORM_FIELDS = {
  w2: [['wages', 'Box 1 wages'], ['federal_withholding', 'Box 2 federal tax withheld'], ['social_security_wages', 'Box 3 SS wages'], ['medicare_wages', 'Box 5 Medicare wages']],
  '1099_nec': [['nonemployee_compensation', 'Box 1 nonemployee comp'], ['federal_withholding', 'Box 4 federal tax withheld']],
  '1099_k': [['gross_payments', 'Box 1a gross payments'], ['federal_withholding', 'Box 4 federal tax withheld']],
  '1099_misc': [['other_income', 'Box 3 other income'], ['rents', 'Box 1 rents'], ['federal_withholding', 'Box 4 withheld']],
  '1099_int': [['interest_income', 'Box 1 interest'], ['federal_withholding', 'Box 4 withheld']],
  '1099_div': [['ordinary_dividends', 'Box 1a ordinary dividends'], ['qualified_dividends', 'Box 1b qualified']],
}

const STATUS_TONE = { processed: 'green', failed: 'red', processing: 'amber', uploaded: 'slate' }

export default function Documents() {
  const { year } = useYear()
  const fileRef = useRef(null)
  const [docType, setDocType] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const docs = useAsync(() => api.get('/documents', { year }), [year])
  const forms = useAsync(() => api.get('/income-forms', { year }), [year])

  const upload = async (files) => {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      for (const file of files) {
        const fd = new FormData()
        fd.append('file', file)
        if (docType) fd.append('doc_type', docType)
        const doc = await api.upload('/documents', fd, { year })
        const ex = doc.extracted_data || {}
        setNotice(
          doc.status === 'failed'
            ? null
            : ex.rows_imported != null
              ? `${file.name}: imported ${ex.rows_imported} transactions${ex.skipped_other_years ? ` (${ex.skipped_other_years} from other years skipped)` : ''}.`
              : `${file.name}: read as ${doc.doc_type.toUpperCase()} (${ex.method}). Please confirm the amounts below.`,
        )
        if (doc.status === 'failed') setError(new Error(`${file.name}: ${doc.error}`))
      }
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
      if (fileRef.current) fileRef.current.value = ''
      docs.reload()
      forms.reload()
    }
  }

  return (
    <div>
      <PageHeader title="Documents" subtitle="Files are encrypted (AES-256) before they're stored. Only you can download them." />

      <div className="card mb-6">
        <div
          className="flex flex-col items-center rounded-lg border-2 border-dashed border-slate-300 p-8 text-center"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault()
            upload([...e.dataTransfer.files])
          }}
        >
          <FileUp className="mb-2 h-8 w-8 text-slate-400" />
          <p className="text-sm text-slate-600">Drag & drop bank CSVs, 1099/W-2 PDFs, invoices or receipt photos</p>
          <p className="text-xs text-slate-400">PDF, CSV, JPG, PNG, WEBP · up to 15 MB</p>
          <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
            <select className="input w-60" value={docType} onChange={(e) => setDocType(e.target.value)} aria-label="Document type">
              {DOC_TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
            <input ref={fileRef} type="file" multiple accept=".pdf,.csv,image/*" className="hidden" onChange={(e) => upload([...e.target.files])} />
            <button className="btn-primary" disabled={busy} onClick={() => fileRef.current?.click()}>
              <Upload className="h-4 w-4" /> {busy ? 'Processing…' : 'Choose files'}
            </button>
          </div>
        </div>
        <div className="mt-3 space-y-2">
          <ErrorAlert error={error} />
          {notice && <Alert kind="success">{notice}</Alert>}
        </div>
      </div>

      <IncomeForms year={year} state={forms} />

      <h2 className="mb-3 mt-8 font-semibold">Uploaded files</h2>
      {docs.loading ? <Spinner /> : docs.data?.length === 0 ? (
        <EmptyState icon={FileUp} title="No documents yet">Start with your bank statement export (CSV) — it's the fastest way to capture a year of income and expenses.</EmptyState>
      ) : (
        <div className="card overflow-x-auto p-0">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-slate-500">
              <tr><th className="p-3">File</th><th className="p-3">Type</th><th className="p-3">Status</th><th className="p-3">Result</th><th className="p-3" /></tr>
            </thead>
            <tbody>
              {docs.data?.map((d) => (
                <tr key={d.id} className="border-t border-slate-100">
                  <td className="p-3 font-medium">{d.original_filename}<div className="text-xs text-slate-400">{new Date(d.created_at).toLocaleString()}</div></td>
                  <td className="p-3"><Badge tone="blue">{d.doc_type}</Badge></td>
                  <td className="p-3"><Badge tone={STATUS_TONE[d.status]}>{d.status}</Badge>{d.error && <div className="mt-1 text-xs text-red-600">{d.error}</div>}</td>
                  <td className="p-3 text-xs text-slate-500">{summarize(d)}</td>
                  <td className="p-3">
                    <div className="flex justify-end gap-1">
                      {d.doc_type !== 'bank_csv' && (
                        <button className="btn-secondary px-2 py-1" title="Re-process" onClick={async () => { await api.post(`/documents/${d.id}/process`).catch(setError); docs.reload(); forms.reload() }}>
                          <RefreshCw className="h-4 w-4" />
                        </button>
                      )}
                      <button className="btn-secondary px-2 py-1" title="Download" onClick={() => api.download(`/documents/${d.id}/download`, d.original_filename).catch(setError)}>
                        <Download className="h-4 w-4" />
                      </button>
                      <button
                        className="btn-secondary px-2 py-1 text-red-600"
                        title="Delete"
                        onClick={async () => {
                          if (!confirm('Delete this file and the transactions imported from it?')) return
                          await api.del(`/documents/${d.id}`).catch(setError)
                          docs.reload()
                          forms.reload()
                        }}
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function summarize(d) {
  const ex = d.extracted_data
  if (!ex) return '—'
  if (ex.rows_imported != null) return `${ex.rows_imported} transactions imported`
  const amounts = Object.entries(ex.amounts || {})
  const parts = amounts.map(([k, v]) => `${k.replaceAll('_', ' ')}: ${usd(v, 2)}`)
  if (ex.transactions_created) parts.push(`${ex.transactions_created} transactions`)
  if (ex.warning) parts.push(`⚠ ${ex.warning}`)
  return parts.join(' · ') || ex.notes || '—'
}

function IncomeForms({ year, state }) {
  const [adding, setAdding] = useState(false)
  const [form, setForm] = useState({ form_type: '1099_nec', payer_name: '', amounts: {} })
  const [error, setError] = useState(null)

  const save = async (e) => {
    e.preventDefault()
    setError(null)
    const amounts = Object.fromEntries(Object.entries(form.amounts).filter(([, v]) => v !== '' && v != null).map(([k, v]) => [k, Number(v)]))
    try {
      await api.post('/income-forms', { ...form, amounts, confirmed: true }, { year })
      setAdding(false)
      setForm({ form_type: '1099_nec', payer_name: '', amounts: {} })
      state.reload()
    } catch (err) {
      setError(err)
    }
  }

  const confirmForm = async (f) => {
    await api.put(`/income-forms/${f.id}`, { form_type: f.form_type, payer_name: f.payer_name, amounts: f.amounts, confirmed: true })
    state.reload()
  }

  return (
    <div className="card">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="font-semibold">W-2 & 1099 forms</h2>
        <button className="btn-secondary py-1" onClick={() => setAdding(!adding)}>{adding ? 'Cancel' : '+ Enter a form manually'}</button>
      </div>
      {adding && (
        <form onSubmit={save} className="mb-4 grid gap-3 rounded-lg bg-slate-50 p-4 sm:grid-cols-3">
          <ErrorAlert error={error} />
          <div>
            <label className="label">Form</label>
            <select className="input" value={form.form_type} onChange={(e) => setForm({ ...form, form_type: e.target.value, amounts: {} })}>
              {Object.keys(FORM_FIELDS).map((k) => <option key={k} value={k}>{k.toUpperCase().replace('_', '-')}</option>)}
            </select>
          </div>
          <div className="sm:col-span-2">
            <label className="label">Payer name</label>
            <input className="input" value={form.payer_name} onChange={(e) => setForm({ ...form, payer_name: e.target.value })} />
          </div>
          {FORM_FIELDS[form.form_type].map(([k, label]) => (
            <div key={k}>
              <label className="label">{label}</label>
              <input type="number" step="0.01" min="0" className="input" value={form.amounts[k] ?? ''} onChange={(e) => setForm({ ...form, amounts: { ...form.amounts, [k]: e.target.value } })} />
            </div>
          ))}
          <div className="sm:col-span-3"><button className="btn-primary">Save form</button></div>
        </form>
      )}
      {state.loading ? <Spinner /> : state.data?.length ? (
        <ul className="divide-y divide-slate-100 text-sm">
          {state.data.map((f) => (
            <li key={f.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <div>
                <Badge tone="blue">{f.form_type.toUpperCase().replace('_', '-')}</Badge>{' '}
                <span className="font-medium">{f.payer_name || 'Unknown payer'}</span>
                <div className="text-xs text-slate-500">
                  {Object.entries(f.amounts).map(([k, v]) => `${k.replaceAll('_', ' ')}: ${usd(v, 2)}`).join(' · ')}
                </div>
              </div>
              <div className="flex gap-2">
                {f.confirmed ? <Badge tone="green">confirmed</Badge> : <button className="btn-secondary py-1" onClick={() => confirmForm(f)}>Confirm amounts</button>}
                <button className="text-xs text-red-600 hover:underline" onClick={async () => { await api.del(`/income-forms/${f.id}`); state.reload() }}>Remove</button>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-slate-500">No forms yet. Upload 1099/W-2 PDFs above or enter them manually — the IRS gets a copy of each, so they must match your return.</p>
      )}
    </div>
  )
}
