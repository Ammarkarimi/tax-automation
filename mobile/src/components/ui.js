import { useCallback, useEffect, useState } from 'react'
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from 'react-native'

export const colors = {
  brand: '#1f57c9',
  brandDark: '#142b5c',
  brandLight: '#eef5ff',
  text: '#0f172a',
  muted: '#64748b',
  border: '#e2e8f0',
  bg: '#f8fafc',
  green: '#047857',
  red: '#b91c1c',
  amber: '#b45309',
  white: '#ffffff',
}

/** Run an async loader on mount / when deps change. */
export function useAsync(fn, deps = []) {
  const [state, setState] = useState({ data: null, error: null, loading: true })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const load = useCallback(fn, deps)
  const reload = useCallback(() => {
    setState((s) => ({ ...s, loading: true, error: null }))
    return load()
      .then((data) => setState({ data, error: null, loading: false }))
      .catch((error) => setState({ data: null, error, loading: false }))
  }, [load])
  useEffect(() => {
    reload()
  }, [reload])
  return { ...state, reload }
}

export function Card({ children, style }) {
  return <View style={[styles.card, style]}>{children}</View>
}

export function H1({ children }) {
  return <Text style={styles.h1}>{children}</Text>
}

export function H2({ children }) {
  return <Text style={styles.h2}>{children}</Text>
}

export function Muted({ children, style }) {
  return <Text style={[styles.muted, style]}>{children}</Text>
}

export function Button({ title, onPress, variant = 'primary', disabled, loading, style }) {
  const v = variant === 'primary' ? styles.btnPrimary : variant === 'danger' ? styles.btnDanger : styles.btnSecondary
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      disabled={disabled || loading}
      style={({ pressed }) => [styles.btn, v, (disabled || loading) && { opacity: 0.5 }, pressed && { opacity: 0.8 }, style]}
    >
      {loading ? (
        <ActivityIndicator color={variant === 'primary' ? colors.white : colors.brand} />
      ) : (
        <Text style={[styles.btnText, variant === 'secondary' && { color: colors.text }]}>{title}</Text>
      )}
    </Pressable>
  )
}

export function Field({ label, ...props }) {
  return (
    <View style={{ marginBottom: 12 }}>
      {label && <Text style={styles.label}>{label}</Text>}
      <TextInput placeholderTextColor={colors.muted} style={styles.input} {...props} />
    </View>
  )
}

export function Stat({ label, value, tone, hint }) {
  const color = tone === 'bad' ? colors.red : tone === 'good' ? colors.green : tone === 'brand' ? colors.brand : colors.text
  return (
    <Card style={{ flex: 1, minWidth: '45%' }}>
      <Muted>{label}</Muted>
      <Text style={[styles.statValue, { color }]}>{value}</Text>
      {hint ? <Muted style={{ fontSize: 11 }}>{hint}</Muted> : null}
    </Card>
  )
}

export function Row({ label, value, bold }) {
  return (
    <View style={styles.row}>
      <Text style={[styles.rowLabel, bold && styles.bold]}>{label}</Text>
      <Text style={[styles.rowValue, bold && styles.bold]}>{value}</Text>
    </View>
  )
}

export function Badge({ text, tone = 'slate' }) {
  const map = {
    slate: ['#f1f5f9', '#334155'],
    green: ['#d1fae5', colors.green],
    red: ['#fee2e2', colors.red],
    amber: ['#fef3c7', colors.amber],
    blue: [colors.brandLight, colors.brand],
    purple: ['#f3e8ff', '#6b21a8'],
  }
  const [bg, fg] = map[tone] || map.slate
  return (
    <View style={[styles.badge, { backgroundColor: bg }]}>
      <Text style={{ color: fg, fontSize: 11, fontWeight: '600' }}>{text}</Text>
    </View>
  )
}

export function Loading() {
  return <ActivityIndicator style={{ marginTop: 40 }} color={colors.brand} />
}

export function ErrorText({ error }) {
  if (!error) return null
  return (
    <View style={styles.error}>
      <Text style={{ color: colors.red }}>{error.message || String(error)}</Text>
    </View>
  )
}

/** Minimal Markdown renderer for AI/template explanations (headings, bullets, **bold**). */
export function MarkdownText({ children }) {
  const lines = String(children || '').split('\n')
  return (
    <View>
      {lines.map((line, i) => {
        const trimmed = line.trim()
        if (!trimmed) return <View key={i} style={{ height: 6 }} />
        if (trimmed.startsWith('#')) {
          return <Text key={i} style={[styles.h2, { marginTop: 4 }]}>{inline(trimmed.replace(/^#+\s*/, ''))}</Text>
        }
        if (/^[-*•]\s/.test(trimmed) || /^\d+\.\s/.test(trimmed)) {
          return (
            <View key={i} style={{ flexDirection: 'row', marginBottom: 4 }}>
              <Text style={styles.body}>• </Text>
              <Text style={[styles.body, { flex: 1 }]}>{inline(trimmed.replace(/^([-*•]|\d+\.)\s/, ''))}</Text>
            </View>
          )
        }
        return <Text key={i} style={[styles.body, { marginBottom: 4 }]}>{inline(trimmed)}</Text>
      })}
    </View>
  )
}

function inline(text) {
  return text.split(/(\*\*[^*]+\*\*|_[^_]+_)/g).map((part, i) =>
    part.startsWith('**') ? (
      <Text key={i} style={styles.bold}>{part.slice(2, -2)}</Text>
    ) : part.startsWith('_') && part.endsWith('_') && part.length > 2 ? (
      <Text key={i} style={{ fontStyle: 'italic' }}>{part.slice(1, -1)}</Text>
    ) : (
      part
    ),
  )
}

export const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 16, paddingBottom: 40, gap: 12 },
  card: { backgroundColor: colors.white, borderRadius: 14, padding: 16, borderWidth: 1, borderColor: colors.border },
  h1: { fontSize: 22, fontWeight: '700', color: colors.text },
  h2: { fontSize: 16, fontWeight: '600', color: colors.text, marginBottom: 8 },
  body: { fontSize: 14, color: '#334155', lineHeight: 20 },
  muted: { fontSize: 13, color: colors.muted },
  label: { fontSize: 13, fontWeight: '600', color: '#334155', marginBottom: 4 },
  input: { borderWidth: 1, borderColor: '#cbd5e1', borderRadius: 10, paddingHorizontal: 12, paddingVertical: 10, fontSize: 15, backgroundColor: colors.white, color: colors.text },
  btn: { borderRadius: 10, paddingVertical: 12, paddingHorizontal: 16, alignItems: 'center', justifyContent: 'center' },
  btnPrimary: { backgroundColor: colors.brand },
  btnSecondary: { backgroundColor: colors.white, borderWidth: 1, borderColor: '#cbd5e1' },
  btnDanger: { backgroundColor: colors.red },
  btnText: { color: colors.white, fontWeight: '600', fontSize: 15 },
  statValue: { fontSize: 22, fontWeight: '700', marginVertical: 4 },
  row: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 6 },
  rowLabel: { color: '#475569', fontSize: 14, flex: 1, paddingRight: 8 },
  rowValue: { color: colors.text, fontSize: 14, fontVariant: ['tabular-nums'] },
  bold: { fontWeight: '700', color: colors.text },
  badge: { alignSelf: 'flex-start', borderRadius: 999, paddingHorizontal: 8, paddingVertical: 2 },
  error: { backgroundColor: '#fef2f2', borderColor: '#fecaca', borderWidth: 1, borderRadius: 10, padding: 10 },
})
