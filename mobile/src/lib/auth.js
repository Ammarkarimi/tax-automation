import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { api, clearSession, getRefreshToken, refreshSession, saveSession, setOnAuthLost } from './api'

const AuthContext = createContext(null)

/** Picks the tax year being filed: last year until the Oct 15 extension deadline. */
export function defaultTaxYear(supported = [2024, 2025, 2026]) {
  const now = new Date()
  const filing = now.getMonth() < 9 || (now.getMonth() === 9 && now.getDate() <= 15)
  const y = filing ? now.getFullYear() - 1 : now.getFullYear()
  return supported.includes(y) ? y : supported[supported.length - 1]
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)
  const [challenge, setChallenge] = useState(null)
  const [year, setYear] = useState(defaultTaxYear())

  useEffect(() => {
    setOnAuthLost(() => setUser(null))
    // Resume a previous session from the refresh token in SecureStore.
    refreshSession()
      .then((d) => setUser(d.user))
      .catch(() => setUser(null))
      .finally(() => setLoading(false))
  }, [])

  const login = useCallback(async (email, password) => {
    setChallenge(await api.post('/auth/login', { email, password }))
  }, [])

  const register = useCallback(async (email, password, fullName) => {
    setChallenge(await api.post('/auth/register', { email, password, full_name: fullName || null }))
  }, [])

  const verifyOtp = useCallback(
    async (code) => {
      const data = await api.post('/auth/verify-otp', { mfa_token: challenge.mfa_token, code })
      await saveSession(data)
      setChallenge(null)
      setUser(data.user)
    },
    [challenge],
  )

  const resendOtp = useCallback(async () => {
    setChallenge(await api.post('/auth/resend-otp', { mfa_token: challenge.mfa_token }))
  }, [challenge])

  const logout = useCallback(async () => {
    try {
      const token = await getRefreshToken()
      if (token) await api.post('/auth/logout', { refresh_token: token })
    } catch {
      /* best effort */
    }
    await clearSession()
    setUser(null)
  }, [])

  const value = useMemo(
    () => ({ user, setUser, loading, challenge, setChallenge, login, register, verifyOtp, resendOtp, logout, year, setYear }),
    [user, loading, challenge, login, register, verifyOtp, resendOtp, logout, year],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export const useAuth = () => useContext(AuthContext)
