import { Pressable, RefreshControl, ScrollView, Text, View } from 'react-native'
import { Link, Stack } from 'expo-router'
import { api, usd } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { Badge, Card, ErrorText, H1, H2, Loading, Muted, Stat, colors, styles, useAsync } from '../../components/ui'

const RISK_TONE = { low: 'green', medium: 'amber', high: 'red' }

export default function Home() {
  const { user, year, setYear } = useAuth()
  const { data, error, loading, reload } = useAsync(async () => {
    const [annual, quarterly, risk, deductions] = await Promise.all([
      api.get('/tax/annual', { year }),
      api.get('/tax/quarterly', { year: new Date().getFullYear() }).catch(() => null),
      api.get('/tax/audit-risk', { year }),
      api.get('/tax/deductions', { year }),
    ])
    return { annual, quarterly, risk, deductions }
  }, [year])

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content} refreshControl={<RefreshControl refreshing={loading} onRefresh={reload} />}>
      <Stack.Screen options={{ headerRight: () => <Link href="/settings" style={{ color: colors.white, marginRight: 16, fontSize: 18 }}>⚙️</Link> }} />
      <H1>Hi {user.full_name?.split(' ')[0] || 'there'} 👋</H1>
      <View style={{ flexDirection: 'row', gap: 8 }}>
        {[year - 1, year, year + 1].filter((y) => y >= 2024 && y <= 2026).map((y) => (
          <Pressable key={y} onPress={() => setYear(y)}>
            <Badge text={`TY ${y}`} tone={y === year ? 'blue' : 'slate'} />
          </Pressable>
        ))}
      </View>
      <ErrorText error={error} />
      {loading && !data ? <Loading /> : data && <Summary {...data} year={year} />}
    </ScrollView>
  )
}

function Summary({ annual, quarterly, risk, deductions, year }) {
  const s = annual.summary
  return (
    <>
      {annual.data_quality.needs_review > 0 && (
        <Link href="/transactions" asChild>
          <Pressable>
            <Card style={{ backgroundColor: '#fffbeb', borderColor: '#fde68a' }}>
              <Text style={{ color: colors.amber }}>⚠️ {annual.data_quality.needs_review} transactions need a quick review →</Text>
            </Card>
          </Pressable>
        </Link>
      )}
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 12 }}>
        <Stat label="Business profit" value={usd(s.business_net_profit)} />
        <Stat label="Total tax" value={usd(s.total_tax)} hint={`${(s.effective_rate * 100).toFixed(1)}% effective`} />
        <Stat label={s.balance_due > 0 ? 'Still to pay' : 'Refund'} value={usd(s.balance_due || s.refund)} tone={s.balance_due > 0 ? 'bad' : 'good'} />
        <Stat label="Possible savings" value={usd(deductions.potential_savings)} tone="brand" />
      </View>
      <Card>
        <H2>📅 Next quarterly payment</H2>
        {quarterly?.next_payment ? (
          <>
            <Text style={{ fontSize: 26, fontWeight: '700' }}>{usd(quarterly.next_payment.amount)}</Text>
            <Muted>Q{quarterly.next_payment.quarter} {quarterly.tax_year} · due {quarterly.next_payment.due_date}</Muted>
            <Muted>Pay with IRS Direct Pay or EFTPS.</Muted>
          </>
        ) : (
          <Muted>Nothing due right now.</Muted>
        )}
      </Card>
      <Card>
        <H2>🛡️ Audit-risk check ({year})</H2>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
          <Text style={{ fontSize: 26, fontWeight: '700' }}>{risk.score}</Text>
          <Badge text={risk.level.toUpperCase()} tone={RISK_TONE[risk.level]} />
        </View>
        {risk.factors.slice(0, 3).map((f) => <Muted key={f.id}>• {f.title}</Muted>)}
      </Card>
      <Card>
        <H2>💡 Top deduction ideas</H2>
        {deductions.suggestions.filter((d) => d.status === 'opportunity').slice(0, 3).map((d) => (
          <View key={d.id} style={{ marginBottom: 8 }}>
            <Text style={{ fontWeight: '600' }}>{d.title}</Text>
            {d.estimated_savings > 0 && <Muted>≈ {usd(d.estimated_savings)} saved</Muted>}
          </View>
        ))}
      </Card>
    </>
  )
}
