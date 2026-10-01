import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Check, Download, Plus, Sparkles, Trash2 } from 'lucide-react'
import { api, usd } from '../api/client'
import { useYear } from '../context/YearContext'
import { Alert, Badge, ErrorAlert, PageHeader, Spinner, useAsync } from '../components/ui'

const SOURCE_TONE = { ai: 'purple', rules: 'blue', user: 'green', import: 'slate' }

export default function Transactions() {
  const { year, meta } = useYear()
  const [params, setParams] = useSearchParams()
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('')
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState(new Set())
  const [bulkCat, setBulkCat] = useState('')
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [showAdd, setShowAdd] = useState(false)
  const reviewOnly = params.get('review') === '1'

  const list = useAsync(
    () => api.get('/transactions', { year, page, page_size: 50, search, category, needs_review: reviewOnly ? true : undefined }),
    [year, page, search, category, reviewOnly],
  )

  const update = async (id, patch) => {
    try {
      await api.patch(`/transactions/${id}`, patch)
      list.reload()
    } catch (err) {
      setError(err)
    }
  }

  const toggle = (id) => {
    const next = new Set(selected)
    next.has(id) ? next.delete(id) : next.add(id)
    setSelected(next)
  }

  const bulk = async () => {
    if (!bulkCat || selected.size === 0) return
    await api.post('/transactions/bulk-categorize', { ids: [...selected], category: bulkCat }).catch(setError)
    setSelected(new Set())
    list.reload()
  }

  const reclassify = async () => {
    setNotice(null)
    try {
      const r = await api.post('/transactions/reclassify', { only_needs_review: true }, { year })
      setNotice(`Re-checked ${r.reclassified} transactions. Your own edits are never overwritten.`)
      list.reload()
    } catch (err) {
      setError(err)
    }
  }

  const items = list.data?.items || []
  const totalPages = list.data ? Math.max(1, Math.ceil(list.data.total / list.data.page_size)) : 1

  return (
    <div>
      <PageHeader
        title="Transactions"
        subtitle="Categories map to Schedule C lines. Set business-use % for mixed personal/business costs."
        actions={
          <>
            <button className="btn-secondary" onClick={reclassify}><Sparkles className="h-4 w-4" /> Auto-categorize</button>
            <button className="btn-secondary" onClick={() => api.download('/transactions/export.csv', `transactions-${year}.csv`, { query: { year } }).catch(setError)}>
              <Download className="h-4 w-4" /> Export CSV
            </button>
            <button className="btn-primary" onClick={() => setShowAdd(!showAdd)}><Plus className="h-4 w-4" /> Add</button>
          </>
        }
      />
      <div className="mb-4 space-y-2">
        <ErrorAlert error={error} />
        {notice && <Alert kind="success">{notice}</Alert>}
      </div>

      {showAdd && <AddTransaction year={year} categories={meta.categories} onDone={() => { setShowAdd(false); list.reload() }} />}

      <div className="card mb-4 flex flex-wrap items-center gap-3">
        <input className="input max-w-xs" placeholder="Search description…" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1) }} />
        <select className="input max-w-xs" value={category} onChange={(e) => { setCategory(e.target.value); setPage(1) }}>
          <option value="">All categories</option>
          {meta.categories.map((c) => <option key={c.id} value={c.id}>{c.id.replaceAll('_', ' ')}</option>)}
        </select>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={reviewOnly} onChange={(e) => { setParams(e.target.checked ? { review: '1' } : {}); setPage(1) }} />
          Needs review only
        </label>
        {selected.size > 0 && (
          <div className="ml-auto flex items-center gap-2">
            <span className="text-sm text-slate-500">{selected.size} selected</span>
            <select className="input w-48" value={bulkCat} onChange={(e) => setBulkCat(e.target.value)}>
              <option value="">Set category…</option>
              {meta.categories.map((c) => <option key={c.id} value={c.id}>{c.id.replaceAll('_', ' ')}</option>)}
            </select>
            <button className="btn-primary py-1.5" onClick={bulk}>Apply</button>
          </div>
        )}
      </div>

      {list.loading ? <Spinner /> : (
        <div className="card overflow-x-auto p-0">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-slate-500">
              <tr>
                <th className="p-3"><input type="checkbox" aria-label="Select all" onChange={(e) => setSelected(e.target.checked ? new Set(items.map((t) => t.id)) : new Set())} /></th>
                <th className="p-3">Date</th><th className="p-3">Description</th><th className="p-3 text-right">Amount</th>
                <th className="p-3">Category</th><th className="p-3">Business %</th><th className="p-3">Source</th><th className="p-3" />
              </tr>
            </thead>
            <tbody>
              {items.map((t) => (
                <tr key={t.id} className={`border-t border-slate-100 ${t.needs_review ? 'bg-amber-50/60' : ''}`}>
                  <td className="p-3"><input type="checkbox" checked={selected.has(t.id)} onChange={() => toggle(t.id)} aria-label="Select" /></td>
                  <td className="whitespace-nowrap p-3 text-slate-500">{t.txn_date}</td>
                  <td className="p-3">
                    <div className="font-medium">{t.description}</div>
                    {t.ai_rationale && <div className="text-xs text-slate-400" title={t.ai_rationale}>{t.ai_rationale.slice(0, 80)}</div>}
                  </td>
                  <td className={`whitespace-nowrap p-3 text-right font-medium tabular-nums ${t.direction === 'income' ? 'text-emerald-700' : 'text-slate-800'}`}>
                    {t.direction === 'income' ? '+' : '−'}{usd(Number(t.amount), 2)}
                  </td>
                  <td className="p-3">
                    <select className="input py-1 text-xs" value={t.category} onChange={(e) => update(t.id, { category: e.target.value })}>
                      {meta.categories.map((c) => <option key={c.id} value={c.id} title={c.description}>{c.id.replaceAll('_', ' ')}{c.schedule_c_line ? ` (L${c.schedule_c_line})` : ''}</option>)}
                    </select>
                  </td>
                  <td className="p-3">
                    <input type="number" min="0" max="100" className="input w-20 py-1 text-xs" defaultValue={t.business_use_pct}
                      onBlur={(e) => Number(e.target.value) !== t.business_use_pct && update(t.id, { business_use_pct: Number(e.target.value) })} />
                  </td>
                  <td className="p-3">
                    <Badge tone={SOURCE_TONE[t.classified_by]}>{t.classified_by}</Badge>
                    {t.confidence != null && t.classified_by !== 'user' && <div className="text-xs text-slate-400">{Math.round(t.confidence * 100)}% sure</div>}
                  </td>
                  <td className="whitespace-nowrap p-3">
                    {t.needs_review && <button className="mr-1 text-emerald-600" title="Looks right" onClick={() => update(t.id, { needs_review: false })}><Check className="h-4 w-4" /></button>}
                    <button className="text-red-500" title="Delete" onClick={async () => { if (confirm('Delete this transaction?')) { await api.del(`/transactions/${t.id}`); list.reload() } }}><Trash2 className="h-4 w-4" /></button>
                  </td>
                </tr>
              ))}
              {items.length === 0 && <tr><td colSpan={8} className="p-8 text-center text-slate-500">No transactions match.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
      <div className="mt-4 flex items-center justify-between text-sm text-slate-500">
        <span>{list.data?.total ?? 0} transactions</span>
        <div className="flex items-center gap-2">
          <button className="btn-secondary py-1" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
          <span>Page {page} / {totalPages}</span>
          <button className="btn-secondary py-1" disabled={page >= totalPages} onClick={() => setPage(page + 1)}>Next</button>
        </div>
      </div>
    </div>
  )
}

function AddTransaction({ year, categories, onDone }) {
  const [f, setF] = useState({ txn_date: `${year}-01-01`, description: '', amount: '', direction: 'expense', category: '', business_use_pct: 100 })
  const [error, setError] = useState(null)
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  const submit = async (e) => {
    e.preventDefault()
    try {
      await api.post('/transactions', { ...f, amount: Number(f.amount), business_use_pct: Number(f.business_use_pct), category: f.category || null }, { year })
      onDone()
    } catch (err) {
      setError(err)
    }
  }
  return (
    <form onSubmit={submit} className="card mb-4 grid gap-3 sm:grid-cols-6">
      <div className="sm:col-span-6"><ErrorAlert error={error} /></div>
      <div><label className="label">Date</label><input type="date" className="input" min={`${year}-01-01`} max={`${year}-12-31`} required value={f.txn_date} onChange={set('txn_date')} /></div>
      <div className="sm:col-span-2"><label className="label">Description</label><input className="input" required value={f.description} onChange={set('description')} placeholder="e.g. Shelving for stockroom" /></div>
      <div><label className="label">Amount</label><input type="number" step="0.01" min="0.01" className="input" required value={f.amount} onChange={set('amount')} /></div>
      <div><label className="label">Type</label><select className="input" value={f.direction} onChange={set('direction')}><option value="expense">Expense</option><option value="income">Income</option></select></div>
      <div><label className="label">Category</label>
        <select className="input" value={f.category} onChange={set('category')}>
          <option value="">Auto-detect</option>
          {categories.map((c) => <option key={c.id} value={c.id}>{c.id.replaceAll('_', ' ')}</option>)}
        </select>
      </div>
      <div className="sm:col-span-6"><button className="btn-primary">Save transaction</button></div>
    </form>
  )
}
