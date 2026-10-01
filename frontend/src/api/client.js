/**
 * API client.
 *
 * Security model (web):
 *  - The short-lived access token is kept ONLY in memory (never localStorage),
 *    so an XSS payload can't read a long-lived credential from storage.
 *  - The refresh token is an httpOnly, SameSite=Strict cookie set by the API and
 *    scoped to /api/v1/auth; JS can't read it. Refresh calls send
 *    X-Requested-With as a CSRF defense-in-depth signal.
 *  - On a 401 we transparently refresh once and retry.
 */

const BASE = '/api/v1'

let accessToken = null
let onAuthLost = () => {}
let refreshing = null

export function setAccessToken(token) {
  accessToken = token
}

export function setOnAuthLost(fn) {
  onAuthLost = fn
}

export class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === 'string' ? detail : formatDetail(detail))
    this.status = status
    this.detail = detail
  }
}

function formatDetail(detail) {
  if (Array.isArray(detail)) {
    return detail.map((d) => `${(d.loc || []).slice(-1)[0] ?? ''}: ${d.msg}`).join('; ')
  }
  return 'Request failed'
}

export async function refreshSession() {
  if (!refreshing) {
    refreshing = fetch(`${BASE}/auth/refresh`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
    })
      .then(async (r) => {
        if (!r.ok) throw new ApiError(r.status, 'Session expired')
        const data = await r.json()
        accessToken = data.access_token
        return data
      })
      .finally(() => {
        refreshing = null
      })
  }
  return refreshing
}

async function request(method, path, { body, query, form, raw, retry = true } = {}) {
  const url = new URL(BASE + path, window.location.origin)
  Object.entries(query || {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, v)
  })
  const headers = { 'X-Requested-With': 'XMLHttpRequest' }
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`
  let payload
  if (form) {
    payload = form // browser sets multipart boundary
  } else if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }
  const res = await fetch(url, { method, headers, body: payload, credentials: 'same-origin' })

  if (res.status === 401 && retry && !path.startsWith('/auth/')) {
    try {
      await refreshSession()
      return request(method, path, { body, query, form, raw, retry: false })
    } catch {
      accessToken = null
      onAuthLost()
      throw new ApiError(401, 'Your session expired. Please sign in again.')
    }
  }
  if (!res.ok) {
    let detail = res.statusText
    try {
      detail = (await res.json()).detail ?? detail
    } catch {
      /* non-JSON error */
    }
    throw new ApiError(res.status, detail)
  }
  if (raw) return res
  if (res.status === 204) return null
  return res.json()
}

export const api = {
  get: (path, query) => request('GET', path, { query }),
  post: (path, body, query) => request('POST', path, { body, query }),
  put: (path, body, query) => request('PUT', path, { body, query }),
  patch: (path, body, query) => request('PATCH', path, { body, query }),
  del: (path, query) => request('DELETE', path, { query }),
  upload: (path, form, query) => request('POST', path, { form, query }),
  /** Download a protected file (PDF/CSV) and trigger a save dialog. */
  async download(path, filename, { method = 'GET', query } = {}) {
    const res = await request(method, path, { query, raw: true })
    const blob = await res.blob()
    const href = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = href
    a.download = filename
    a.click()
    setTimeout(() => URL.revokeObjectURL(href), 1000)
  },
}

export const usd = (n, digits = 0) =>
  (n ?? 0).toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: digits, minimumFractionDigits: digits })

export const pct = (n, digits = 1) => `${((n ?? 0) * 100).toFixed(digits)}%`
