import { useState } from 'react'
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, Text, View } from 'react-native'
import { Redirect } from 'expo-router'
import { useAuth } from '../lib/auth'
import { Button, Card, ErrorText, Field, Muted, colors, styles } from '../components/ui'

/** Password step + email-OTP step (MFA) on one screen. */
export default function Login() {
  const { user, challenge, setChallenge, login, register, verifyOtp, resendOtp } = useAuth()
  const [mode, setMode] = useState('login')
  const [form, setForm] = useState({ name: '', email: '', password: '' })
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [info, setInfo] = useState(null)

  if (user) return <Redirect href="/" />

  const run = (fn) => async () => {
    setBusy(true)
    setError(null)
    try {
      await fn()
    } catch (e) {
      setError(e)
    } finally {
      setBusy(false)
    }
  }

  return (
    <KeyboardAvoidingView style={{ flex: 1, backgroundColor: colors.brandDark }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView contentContainerStyle={{ flexGrow: 1, justifyContent: 'center', padding: 20 }} keyboardShouldPersistTaps="handled">
        <Text style={{ fontSize: 40, textAlign: 'center' }}>🧾</Text>
        <Text style={{ color: colors.white, fontSize: 26, fontWeight: '700', textAlign: 'center' }}>TaxPilot</Text>
        <Text style={{ color: '#c7d2fe', textAlign: 'center', marginBottom: 24 }}>Do your own taxes — no accountant needed.</Text>
        <Card>
          <ErrorText error={error} />
          {info && <Muted style={{ color: colors.green, marginBottom: 8 }}>{info}</Muted>}
          {!challenge ? (
            <View style={{ marginTop: 8 }}>
              {mode === 'register' && <Field label="Your name" value={form.name} onChangeText={(name) => setForm({ ...form, name })} autoComplete="name" />}
              <Field label="Email" value={form.email} onChangeText={(email) => setForm({ ...form, email })} autoCapitalize="none" keyboardType="email-address" autoComplete="email" textContentType="emailAddress" />
              <Field label="Password" value={form.password} onChangeText={(password) => setForm({ ...form, password })} secureTextEntry autoComplete={mode === 'login' ? 'current-password' : 'new-password'} textContentType="password" />
              {mode === 'register' && <Muted style={{ marginBottom: 12 }}>12+ characters with upper- & lowercase letters and a number.</Muted>}
              <Button
                title={mode === 'login' ? 'Continue' : 'Create account'}
                loading={busy}
                onPress={run(() => (mode === 'login' ? login(form.email.trim(), form.password) : register(form.email.trim(), form.password, form.name)))}
              />
              <Pressable onPress={() => setMode(mode === 'login' ? 'register' : 'login')} style={{ marginTop: 14 }}>
                <Text style={{ color: colors.brand, textAlign: 'center' }}>
                  {mode === 'login' ? 'New here? Create an account' : 'Have an account? Sign in'}
                </Text>
              </Pressable>
            </View>
          ) : (
            <View style={{ marginTop: 8 }}>
              <Text style={styles.h2}>Check your email</Text>
              <Muted style={{ marginBottom: 12 }}>Enter the 6-digit code we sent to {challenge.masked_email}.</Muted>
              <Field
                value={code}
                onChangeText={(t) => setCode(t.replace(/\D/g, '').slice(0, 6))}
                keyboardType="number-pad"
                autoComplete="one-time-code"
                textContentType="oneTimeCode"
                maxLength={6}
                style={[styles.input, { fontSize: 26, letterSpacing: 10, textAlign: 'center' }]}
              />
              <Button title="Verify & sign in" disabled={code.length !== 6} loading={busy} onPress={run(() => verifyOtp(code))} />
              <Button title="Send a new code" variant="secondary" style={{ marginTop: 10 }} onPress={run(async () => { await resendOtp(); setInfo('A new code is on its way.') })} />
              <Pressable onPress={() => { setChallenge(null); setCode('') }} style={{ marginTop: 14 }}>
                <Text style={{ color: colors.muted, textAlign: 'center' }}>Use a different account</Text>
              </Pressable>
            </View>
          )}
        </Card>
      </ScrollView>
    </KeyboardAvoidingView>
  )
}
