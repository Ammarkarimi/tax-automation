import { useEffect, useState } from 'react'
import { Alert, ScrollView, Switch, Text, View } from 'react-native'
import { router } from 'expo-router'
import { API_URL, api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { Button, Card, ErrorText, Field, H2, Muted, colors, styles } from '../components/ui'

const STATUSES = [
  ['single', 'Single'],
  ['married_joint', 'Married (joint)'],
  ['married_separate', 'Married (separate)'],
  ['head_of_household', 'Head of household'],
]

export default function Settings() {
  const { user, setUser, logout, year } = useAuth()
  const [profile, setProfile] = useState(null)
  const [error, setError] = useState(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    api.get('/profile', { year }).then(setProfile).catch(setError)
  }, [year])

  const toggleAi = async (value) => {
    try {
      setUser(await api.patch('/me/settings', { ai_consent: value }))
    } catch (e) {
      setError(e)
    }
  }

  const saveProfile = async () => {
    setSaved(false)
    try {
      setProfile(await api.put('/profile', {
        filing_status: profile.filing_status,
        business_description: profile.business_description || null,
        business_miles: Number(profile.business_miles || 0),
        home_office_sqft: Number(profile.home_office_sqft || 0),
        qualifying_children: Number(profile.qualifying_children || 0),
        is_cash_intensive: profile.is_cash_intensive,
      }, { year }))
      setSaved(true)
    } catch (e) {
      setError(e)
    }
  }

  const signOut = async () => {
    await logout()
    router.replace('/login')
  }

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      <ErrorText error={error} />
      <Card>
        <H2>AI processing</H2>
        <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
          <Text style={{ flex: 1, paddingRight: 12 }}>Use OpenAI to read receipts and categorize transactions</Text>
          <Switch value={user.ai_consent} onValueChange={toggleAi} trackColor={{ true: colors.brand }} />
        </View>
        <Muted style={{ marginTop: 6 }}>Identifiers are removed from text before it's sent. Photos can't be redacted, so they're only sent while this is on.</Muted>
      </Card>

      {profile && (
        <Card>
          <H2>Tax profile ({year})</H2>
          <Text style={styles.label}>Filing status</Text>
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginBottom: 12 }}>
            {STATUSES.map(([v, l]) => (
              <Button key={v} title={l} variant={profile.filing_status === v ? 'primary' : 'secondary'} style={{ paddingVertical: 6 }} onPress={() => setProfile({ ...profile, filing_status: v })} />
            ))}
          </View>
          <Field label="What does your business do?" value={profile.business_description || ''} onChangeText={(t) => setProfile({ ...profile, business_description: t })} />
          <Field label="Business miles driven" keyboardType="number-pad" value={String(profile.business_miles ?? '')} onChangeText={(t) => setProfile({ ...profile, business_miles: t })} />
          <Field label="Home office (sq ft)" keyboardType="number-pad" value={String(profile.home_office_sqft ?? '')} onChangeText={(t) => setProfile({ ...profile, home_office_sqft: t })} />
          <Field label="Children under 17" keyboardType="number-pad" value={String(profile.qualifying_children ?? '')} onChangeText={(t) => setProfile({ ...profile, qualifying_children: t })} />
          <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <Text>I take a lot of cash (shop, salon…)</Text>
            <Switch value={profile.is_cash_intensive} onValueChange={(v) => setProfile({ ...profile, is_cash_intensive: v })} />
          </View>
          <Button title={saved ? 'Saved ✓' : 'Save profile'} onPress={saveProfile} />
          <Muted style={{ marginTop: 8 }}>Inventory, SSN and other details can be edited in the web app.</Muted>
        </Card>
      )}

      <Card>
        <H2>Account</H2>
        <Muted>{user.email}</Muted>
        <Muted style={{ marginBottom: 12 }}>Server: {API_URL}</Muted>
        <Button title="Sign out" variant="secondary" onPress={signOut} />
        <Button
          title="Delete my account"
          variant="danger"
          style={{ marginTop: 10 }}
          onPress={() => Alert.prompt
            ? Alert.prompt('Delete account', 'Enter your password to permanently delete all your data.', async (pw) => {
                try { await api.post('/me/delete', { password: pw }); await signOut() } catch (e) { setError(e) }
              }, 'secure-text')
            : Alert.alert('Delete account', 'Please delete your account from the web app (Settings & Privacy).')}
        />
      </Card>
    </ScrollView>
  )
}
