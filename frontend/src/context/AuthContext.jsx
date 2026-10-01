import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { api, refreshSession, setAccessToken, setOnAuthLost } from '../api/client'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)
  // Pending MFA challenge between the password step and the OTP step (memory only).
  const [challenge, setChallenge] = useState(null)

  // On page load, try to resume the session via the httpOnly refresh cookie.
  useEffect(() => {
    setOnAuthLost(() => setUser(null))
    refreshSession()
      .then((data) => setUser(data.user))
      .catch(() => setUser(null))
      .finally(() => setLoading(false))
  }, [])

  const login = useCallback(async (email, password) => {
    const c = await api.post('/auth/login', { email, password })
    setChallenge(c)
    return c
  }, [])

  const register = useCallback(async (email, password, fullName) => {
    const c = await api.post('/auth/register', { email, password, full_name: fullName || null })
    setChallenge(c)
    return c
  }, [])

  const verifyOtp = useCallback(
    async (code) => {
      if (!challenge) throw new Error('No pending sign-in. Start again.')
      const data = await api.post('/auth/verify-otp', { mfa_token: challenge.mfa_token, code })
      setAccessToken(data.access_token)
      setUser(data.user)
      setChallenge(null)
      return data.user
    },
    [challenge],
  )

  const resendOtp = useCallback(async () => {
    if (!challenge) return
    setChallenge(await api.post('/auth/resend-otp', { mfa_token: challenge.mfa_token }))
  }, [challenge])

  const logout = useCallback(async () => {
    try {
      await api.post('/auth/logout')
    } finally {
      setAccessToken(null)
      setUser(null)
    }
  }, [])

  const value = useMemo(
    () => ({ user, setUser, loading, challenge, login, register, verifyOtp, resendOtp, logout }),
    [user, loading, challenge, login, register, verifyOtp, resendOtp, logout],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export const useAuth = () => useContext(AuthContext)
