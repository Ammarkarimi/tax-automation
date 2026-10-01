/**
 * Mobile API client.
 *
 * Security model (mobile):
 *  - Every request sends `X-Client-Type: mobile`, so the API returns the refresh
 *    token in the JSON body instead of a cookie.
 *  - The refresh token is stored with expo-secure-store (iOS Keychain / Android
 *    Keystore-backed encryption). The short-lived access token lives only in memory.
 *  - A 401 triggers one silent refresh + retry; refresh tokens rotate on every use.
 */
import * as SecureStore from 'expo-secure-store'

export const API_URL = (process.env.EXPO_PUBLIC_API_URL || 'http://localhost:8000').replace(/\/$/, '')
const BASE = `${API_URL}/api/v1`
const REFRESH_KEY = 'taxpilot.refresh_token'

let accessToken = null
let onAuthLost = () => {}
let refreshing = null

export const setOnAuthLost = (fn) => {
  onAuthLost = fn
}

export class ApiError extends Error {
  constructor(status, detail) {
    super(
      typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map((d) => d.msg).join('; ')
          : 'Request failed',
    )
    this.status = status
  }
}

export async function saveSession(data) {
  accessToken = data.access_token
  if (data.refresh_token) {
    await SecureStore.setItemAsync(REFRESH_KEY, data.refresh_token, {
      keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY, // never synced/backed up
    })
  }
}

export const getRefreshToken = () => SecureStore.getItemAsync(REFRESH_KEY)

export async function clearSession() {
  accessToken = null
  await SecureStore.deleteItemAsync(REFRESH_KEY)
}

export async function refreshSession() {
  if (!refreshing) {
    refreshing = (async () => {
      const token = await SecureStore.getItemAsync(REFRESH_KEY)
      if (!token) throw new ApiError(401, 'Not signed in')
      const res = await fetch(`${BASE}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Client-Type': 'mobile' },
        body: JSON.stringify({ refresh_token: token }),
      })
      if (!res.ok) {
        await clearSession()
        throw new ApiError(res.status, 'Session expired')
      }
      const data = await res.json()
      await saveSession(data)
      return data
    })().finally(() => {
      refreshing = null
    })
  }
  return refreshing
}

async function request(method, path, { body, query, form, retry = true } = {}) {
  const qs = Object.entries(query || {})
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
    .join('&')
  const headers = { 'X-Client-Type': 'mobile', Accept: 'application/json' }
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`
  let payload
  if (form) payload = form
  else if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }

  let res
  try {
    res = await fetch(`${BASE}${path}${qs ? `?${qs}` : ''}`, { method, headers, body: payload })
  } catch {
    throw new ApiError(0, `Can't reach the server at ${API_URL}. Check EXPO_PUBLIC_API_URL and that the backend is running.`)
  }

  if (res.status === 401 && retry && !path.startsWith('/auth/')) {
    try {
      await refreshSession()
      return request(method, path, { body, query, form, retry: false })
    } catch {
      onAuthLost()
      throw new ApiError(401, 'Your session expired. Please sign in again.')
    }
  }
  if (!res.ok) {
    let detail = `Error ${res.status}`
    try {
      detail = (await res.json()).detail ?? detail
    } catch {
      /* non-JSON */
    }
    throw new ApiError(res.status, detail)
  }
  return res.status === 204 ? null : res.json()
}

export const api = {
  get: (path, query) => request('GET', path, { query }),
  post: (path, body, query) => request('POST', path, { body, query }),
  put: (path, body, query) => request('PUT', path, { body, query }),
  patch: (path, body, query) => request('PATCH', path, { body, query }),
  del: (path, query) => request('DELETE', path, { query }),
  /** Upload a local file (camera photo, picked PDF/CSV) as multipart/form-data. */
  upload: (path, { uri, name, mimeType }, fields = {}, query) => {
    const form = new FormData()
    form.append('file', { uri, name, type: mimeType || 'application/octet-stream' })
    Object.entries(fields).forEach(([k, v]) => v && form.append(k, v))
    return request('POST', path, { form, query })
  },
}

export const usd = (n, digits = 0) =>
  `${n < 0 ? '-' : ''}$${Math.abs(n ?? 0).toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })}`
