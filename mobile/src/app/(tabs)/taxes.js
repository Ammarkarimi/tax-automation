import { useState } from 'react'
import { RefreshControl, ScrollView, View } from 'react-native'
import { api, usd } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { Badge, Button, Card, ErrorText, H2, Loading, MarkdownText, Muted, Row, Stat, styles, useAsync } from '../../components/ui'

const Q_TONE = { paid: 'green', covered: 'green', upcoming: 'amber', underpaid: 'red' }

export default function Taxes() {
  const { year } = useAuth()
  const [explanation, setExplanation] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const r = useAsync(async () => {
    const [annual, quarterly] = await Promise.all([
      api.get('/tax/annual', { year }),
      api.get('/tax/quarterly', { year: new Date().getFullYear() }).catch(() => null),
    ])
    return { annual, quarterly }
  }, [year])

  const explain = async () => {
    setBusy(true)
    try {
      setExplanation(await api.get('/tax/explain', { year }))
    } catch (e) {
      setError(e)
    } finally {
      setBusy(false)
    }
  }

  if (r.loading && !r.data) return <Loading />
  if (r.error) return <View style={styles.content}><ErrorText error={r.error} /></View>
  const { annual: a, quarterly: q } = r.data
  const s = a.summary, sc = a.schedule_c, f = a.form_1040

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content} refreshControl={<RefreshControl refreshing={r.loading} onRefresh={r.reload} />}>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 12 }}>
        <Stat label={`Total tax ${year}`} value={usd(s.total_tax)} />
        <Stat label={s.balance_due > 0 ? 'You owe' : 'Refund'} value={usd(s.balance_due || s.refund)} tone={s.balance_due > 0 ? 'bad' : 'good'} />
      </View>
      <Button title={busy ? 'Explaining…' : '✨ Explain my taxes'} variant="secondary" onPress={explain} loading={busy} />
      <ErrorText error={error} />
      {explanation && (
        <Card>
          <Badge text={explanation.source === 'ai' ? 'AI explanation' : 'Standard explanation'} tone={explanation.source === 'ai' ? 'purple' : 'slate'} />
          <View style={{ height: 8 }} />
          <MarkdownText>{explanation.markdown}</MarkdownText>
        </Card>
      )}
      <Card>
        <H2>Schedule C (business)</H2>
        <Row label="Gross receipts" value={usd(sc.line1_gross_receipts)} />
        {sc.line4_cogs > 0 && <Row label="Cost of goods sold" value={`−${usd(sc.line4_cogs)}`} />}
        <Row label="Expenses" value={`−${usd(sc.line28_total_expenses + sc.line30_home_office)}`} />
        <Row label="Net profit" value={usd(sc.line31_net_profit)} bold />
      </Card>
      <Card>
        <H2>Form 1040</H2>
        <Row label="Adjusted gross income" value={usd(f.line11_agi)} />
        <Row label="Standard + QBI deductions" value={`−${usd(f.line12_standard_deduction + f.line13a_qbi_deduction + f.line13b_schedule_1a_deductions)}`} />
        <Row label="Taxable income" value={usd(f.line15_taxable_income)} bold />
        <Row label="Income tax (after credits)" value={usd(f.line22_tax_after_credits)} />
        <Row label="Self-employment tax" value={usd(s.self_employment_tax)} />
        <Row label="Total tax" value={usd(f.line24_total_tax)} bold />
        <Row label="Paid / withheld" value={`−${usd(f.line33_total_payments)}`} />
      </Card>
      {q && (
        <Card>
          <H2>Quarterly estimates {q.tax_year}</H2>
          <Muted style={{ marginBottom: 6 }}>Target {usd(q.required_annual_payment)} ({q.safe_harbor_basis})</Muted>
          {q.quarters.map((row) => (
            <View key={row.quarter} style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingVertical: 6 }}>
              <Muted>Q{row.quarter} · {row.due_date}</Muted>
              <View style={{ flexDirection: 'row', gap: 8, alignItems: 'center' }}>
                <Muted>{usd(row.amount_due)}</Muted>
                <Badge text={row.status} tone={Q_TONE[row.status]} />
              </View>
            </View>
          ))}
        </Card>
      )}
      {a.warnings.map((w) => <Muted key={w}>⚠️ {w}</Muted>)}
      <Muted>Download the Form 1040 + Schedule C PDF from the web app. TaxPilot never files with the IRS.</Muted>
    </ScrollView>
  )
}
