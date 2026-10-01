import { useState } from 'react'
import { Activity, FileText, ListChecks, Users } from 'lucide-react'
import { api } from '../api/client'
import { useAuth } from '../context/AuthContext'
import { Badge, ErrorAlert, PageHeader, Spinner, StatCard, useAsync } from '../components/ui'

export default function Admin() {
  const { user } = useAuth()
  const isAdmin = user.role === 'admin'
  const [tab, setTab] = useState('overview')
  const [actionFilter, setActionFilter] = useState('')
  const stats = useAsync(() => api.get('/admin/stats'), [])
  const users = useAsync(() => api.get('/admin/users'), [])
  const logs = useAsync(() => api.get('/admin/audit-logs', { action: actionFilter, limit: 200 }), [actionFilter])
  const [error, setError] = useState(null)

  const updateUser = async (id, patch) => {
    try {
      await api.patch(`/admin/users/${id}`, patch)
      users.reload()
    } catch (err) {
      setError(err)
    }
  }

  return (
    <div>
      <PageHeader title="Admin panel" subtitle="Operational monitoring. Staff never see users' tax data, documents or full emails." />
      <div className="mb-4 flex gap-2">
        {['overview', 'users', 'audit'].map((t) => (
          <button key={t} className={tab === t ? 'btn-primary py-1.5' : 'btn-secondary py-1.5'} onClick={() => setTab(t)}>{t[0].toUpperCase() + t.slice(1)}</button>
        ))}
      </div>
      <ErrorAlert error={error} />

      {tab === 'overview' && (stats.loading ? <Spinner /> : stats.error ? <ErrorAlert error={stats.error} /> : (
        <div className="space-y-6">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard label="Users" value={stats.data.users.total} icon={Users} hint={`${stats.data.users.verified} verified · ${stats.data.users.locked} locked`} />
            <StatCard label="Documents" value={stats.data.documents.total} icon={FileText} hint={Object.entries(stats.data.documents.by_status).map(([k, v]) => `${v} ${k}`).join(' · ')} />
            <StatCard label="Transactions" value={stats.data.transactions.total} icon={ListChecks} hint={`${stats.data.transactions.needs_review} need review`} />
            <StatCard label="Logins (24h)" value={stats.data.last_24h.logins} icon={Activity} hint={`${stats.data.last_24h.failed_logins} failed · ${stats.data.last_24h.failed_otps} bad OTPs`} />
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="card text-sm">
              <h2 className="mb-2 font-semibold">Classification sources</h2>
              {Object.entries(stats.data.transactions.by_classifier).map(([k, v]) => <div key={k} className="flex justify-between py-1"><span>{k}</span><span>{v}</span></div>)}
            </div>
            <div className="card text-sm">
              <h2 className="mb-2 font-semibold">System</h2>
              <div className="flex justify-between py-1"><span>AI</span><Badge tone={stats.data.system.ai_enabled ? 'green' : 'slate'}>{stats.data.system.ai_enabled ? `enabled (${stats.data.system.ai_model})` : 'disabled'}</Badge></div>
              <div className="flex justify-between py-1"><span>Users consenting to AI</span><span>{stats.data.users.ai_consented}</span></div>
              <div className="flex justify-between py-1"><span>Refresh-token reuse alerts (24h)</span><span className={stats.data.last_24h.refresh_reuse_alerts ? 'font-semibold text-red-600' : ''}>{stats.data.last_24h.refresh_reuse_alerts}</span></div>
              <div className="flex justify-between py-1"><span>Tax calculations / PDFs</span><span>{stats.data.calculations} / {stats.data.reports}</span></div>
            </div>
          </div>
        </div>
      ))}

      {tab === 'users' && (users.loading ? <Spinner /> : (
        <div className="card overflow-x-auto p-0">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-slate-500"><tr><th className="p-3">User</th><th className="p-3">Role</th><th className="p-3">Status</th><th className="p-3">Docs / Txns</th><th className="p-3">Last login</th>{isAdmin && <th className="p-3">Actions</th>}</tr></thead>
            <tbody>
              {users.data?.map((u) => (
                <tr key={u.id} className="border-t border-slate-100">
                  <td className="p-3">{u.email_masked}<div className="font-mono text-xs text-slate-400">{u.id.slice(0, 8)}</div></td>
                  <td className="p-3">
                    {isAdmin ? (
                      <select className="input py-1" value={u.role} onChange={(e) => updateUser(u.id, { role: e.target.value })}>
                        <option value="user">user</option><option value="support">support</option><option value="admin">admin</option>
                      </select>
                    ) : <Badge>{u.role}</Badge>}
                  </td>
                  <td className="space-x-1 p-3">
                    <Badge tone={u.is_active ? 'green' : 'red'}>{u.is_active ? 'active' : 'disabled'}</Badge>
                    {u.locked && <Badge tone="amber">locked</Badge>}
                    {!u.email_verified && <Badge>unverified</Badge>}
                  </td>
                  <td className="p-3">{u.document_count} / {u.transaction_count}</td>
                  <td className="p-3 text-slate-500">{u.last_login_at ? new Date(u.last_login_at).toLocaleString() : '—'}</td>
                  {isAdmin && (
                    <td className="space-x-2 p-3">
                      <button className="text-brand-600 hover:underline" onClick={() => updateUser(u.id, { is_active: !u.is_active })}>{u.is_active ? 'Disable' : 'Enable'}</button>
                      {u.locked && <button className="text-brand-600 hover:underline" onClick={() => updateUser(u.id, { unlock: true })}>Unlock</button>}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}

      {tab === 'audit' && (
        <div>
          <input className="input mb-3 max-w-xs" placeholder="Filter by action prefix, e.g. auth." value={actionFilter} onChange={(e) => setActionFilter(e.target.value)} />
          {logs.loading ? <Spinner /> : (
            <div className="card overflow-x-auto p-0">
              <table className="w-full text-xs">
                <thead className="bg-slate-50 text-left text-slate-500"><tr><th className="p-2">Time</th><th className="p-2">Action</th><th className="p-2">Actor</th><th className="p-2">Resource</th><th className="p-2">IP</th><th className="p-2">Details</th></tr></thead>
                <tbody>
                  {logs.data?.map((l) => (
                    <tr key={l.id} className={`border-t border-slate-100 ${l.success ? '' : 'bg-red-50'}`}>
                      <td className="whitespace-nowrap p-2">{new Date(l.created_at).toLocaleString()}</td>
                      <td className="p-2 font-mono">{l.action}</td>
                      <td className="p-2 font-mono">{l.actor_id?.slice(0, 8) || '—'} {l.actor_role && <Badge>{l.actor_role}</Badge>}</td>
                      <td className="p-2 font-mono">{l.resource_type ? `${l.resource_type}:${l.resource_id?.slice(0, 8)}` : ''}</td>
                      <td className="p-2">{l.ip_address}</td>
                      <td className="p-2 font-mono text-slate-500">{l.details ? JSON.stringify(l.details) : ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
