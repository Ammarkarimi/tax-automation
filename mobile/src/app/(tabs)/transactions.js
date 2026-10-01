import { useState } from 'react'
import { FlatList, Pressable, RefreshControl, Text, View } from 'react-native'
import { api, usd } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { Badge, Button, ErrorText, Muted, colors, styles, useAsync } from '../../components/ui'

// Most common categories for small shops & gig workers; the full list comes from /meta.
const QUICK = [
  'business_income', 'inventory_purchases', 'supplies', 'rent_property', 'utilities', 'car_truck',
  'commissions_fees', 'advertising', 'insurance', 'meals', 'software', 'repairs', 'taxes_licenses',
  'other_expense', 'personal', 'transfer',
]

export default function Transactions() {
  const { year } = useAuth()
  const [reviewOnly, setReviewOnly] = useState(true)
  const [open, setOpen] = useState(null)
  const [error, setError] = useState(null)
  const list = useAsync(
    () => api.get('/transactions', { year, page_size: 200, needs_review: reviewOnly ? true : undefined }),
    [year, reviewOnly],
  )

  const update = async (id, patch) => {
    try {
      await api.patch(`/transactions/${id}`, patch)
      setOpen(null)
      list.reload()
    } catch (e) {
      setError(e)
    }
  }

  return (
    <View style={styles.screen}>
      <View style={{ flexDirection: 'row', gap: 8, padding: 16, paddingBottom: 4 }}>
        <Pressable onPress={() => setReviewOnly(true)}><Badge text="Needs review" tone={reviewOnly ? 'amber' : 'slate'} /></Pressable>
        <Pressable onPress={() => setReviewOnly(false)}><Badge text="All" tone={!reviewOnly ? 'blue' : 'slate'} /></Pressable>
        <Muted style={{ marginLeft: 'auto' }}>{list.data?.total ?? 0} items</Muted>
      </View>
      <View style={{ paddingHorizontal: 16 }}><ErrorText error={error} /></View>
      <FlatList
        data={list.data?.items || []}
        keyExtractor={(t) => t.id}
        contentContainerStyle={{ padding: 16, gap: 8 }}
        refreshControl={<RefreshControl refreshing={list.loading} onRefresh={list.reload} />}
        ListEmptyComponent={!list.loading && <Muted>{reviewOnly ? 'All caught up! 🎉' : 'No transactions yet.'}</Muted>}
        renderItem={({ item: t }) => (
          <Pressable onPress={() => setOpen(open === t.id ? null : t.id)} style={[styles.card, t.needs_review && { borderColor: '#fde68a' }]}>
            <View style={{ flexDirection: 'row', justifyContent: 'space-between', gap: 8 }}>
              <Text style={{ flex: 1, fontWeight: '600' }} numberOfLines={1}>{t.description}</Text>
              <Text style={{ fontWeight: '700', color: t.direction === 'income' ? colors.green : colors.text }}>
                {t.direction === 'income' ? '+' : '−'}{usd(Number(t.amount), 2)}
              </Text>
            </View>
            <View style={{ flexDirection: 'row', gap: 6, marginTop: 6, alignItems: 'center' }}>
              <Muted>{t.txn_date}</Muted>
              <Badge text={t.category.replaceAll('_', ' ')} tone={t.category === 'uncategorized' ? 'red' : 'blue'} />
              {t.business_use_pct < 100 && <Badge text={`${t.business_use_pct}% biz`} />}
            </View>
            {open === t.id && (
              <View style={{ marginTop: 10 }}>
                {t.ai_rationale && <Muted style={{ marginBottom: 8 }}>{t.ai_rationale}</Muted>}
                <Text style={styles.label}>Change category</Text>
                <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 6 }}>
                  {QUICK.map((c) => (
                    <Pressable key={c} onPress={() => update(t.id, { category: c })}>
                      <Badge text={c.replaceAll('_', ' ')} tone={c === t.category ? 'blue' : 'slate'} />
                    </Pressable>
                  ))}
                </View>
                {t.needs_review && <Button title="Looks right ✓" style={{ marginTop: 10 }} onPress={() => update(t.id, { needs_review: false })} />}
              </View>
            )}
          </Pressable>
        )}
      />
    </View>
  )
}
