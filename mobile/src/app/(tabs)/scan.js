import { useState } from 'react'
import { Alert, Pressable, RefreshControl, ScrollView, Text, View } from 'react-native'
import * as DocumentPicker from 'expo-document-picker'
import * as ImagePicker from 'expo-image-picker'
import { api, usd } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { Badge, Button, Card, ErrorText, H2, Muted, colors, styles, useAsync } from '../../components/ui'

const TYPES = [
  ['', 'Auto'],
  ['receipt', 'Receipt'],
  ['invoice', 'Invoice'],
  ['1099_nec', '1099-NEC'],
  ['1099_k', '1099-K'],
  ['w2', 'W-2'],
  ['bank_csv', 'Bank CSV'],
]
const STATUS_TONE = { processed: 'green', failed: 'red', processing: 'amber', uploaded: 'slate' }

export default function Scan() {
  const { year, user } = useAuth()
  const [docType, setDocType] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)
  const docs = useAsync(() => api.get('/documents', { year }), [year])

  const send = async (file) => {
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      const doc = await api.upload('/documents', file, { doc_type: docType }, { year })
      setResult(doc)
      docs.reload()
    } catch (e) {
      setError(e)
    } finally {
      setBusy(false)
    }
  }

  const fromCamera = async () => {
    const perm = await ImagePicker.requestCameraPermissionsAsync()
    if (!perm.granted) return Alert.alert('Camera access needed', 'Allow camera access in Settings to scan receipts.')
    const r = await ImagePicker.launchCameraAsync({ mediaTypes: ['images'], quality: 0.7 })
    if (!r.canceled) {
      const a = r.assets[0]
      await send({ uri: a.uri, name: a.fileName || `receipt-${Date.now()}.jpg`, mimeType: a.mimeType || 'image/jpeg' })
    }
  }

  const fromLibrary = async () => {
    const r = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ['images'], quality: 0.7 })
    if (!r.canceled) {
      const a = r.assets[0]
      await send({ uri: a.uri, name: a.fileName || `photo-${Date.now()}.jpg`, mimeType: a.mimeType || 'image/jpeg' })
    }
  }

  const fromFiles = async () => {
    const r = await DocumentPicker.getDocumentAsync({
      type: ['application/pdf', 'text/csv', 'text/comma-separated-values', 'image/*'],
      copyToCacheDirectory: true,
    })
    if (!r.canceled) {
      const a = r.assets[0]
      const mimeType = a.mimeType || (a.name.toLowerCase().endsWith('.csv') ? 'text/csv' : 'application/pdf')
      await send({ uri: a.uri, name: a.name, mimeType })
    }
  }

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content} refreshControl={<RefreshControl refreshing={docs.loading} onRefresh={docs.reload} />}>
      <Card>
        <H2>Add a document for {year}</H2>
        <Muted style={{ marginBottom: 10 }}>Files are encrypted before they're stored.{!user.ai_consent ? ' Turn on AI processing in Settings to read photos automatically.' : ''}</Muted>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginBottom: 12 }}>
          {TYPES.map(([v, l]) => (
            <Pressable key={v} onPress={() => setDocType(v)}>
              <Badge text={l} tone={docType === v ? 'blue' : 'slate'} />
            </Pressable>
          ))}
        </View>
        <Button title="📷  Scan with camera" onPress={fromCamera} loading={busy} />
        <Button title="🖼️  Choose a photo" variant="secondary" onPress={fromLibrary} disabled={busy} style={{ marginTop: 8 }} />
        <Button title="📄  Pick PDF or CSV" variant="secondary" onPress={fromFiles} disabled={busy} style={{ marginTop: 8 }} />
      </Card>
      <ErrorText error={error} />
      {result && (
        <Card style={{ borderColor: result.status === 'failed' ? '#fecaca' : '#a7f3d0' }}>
          <H2>{result.status === 'failed' ? 'Could not read the file' : 'Done ✓'}</H2>
          <Muted>{describe(result)}</Muted>
        </Card>
      )}
      <H2>Your documents</H2>
      {docs.data?.map((d) => (
        <Card key={d.id}>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between', gap: 8 }}>
            <Text style={{ fontWeight: '600', flex: 1 }} numberOfLines={1}>{d.original_filename}</Text>
            <Badge text={d.status} tone={STATUS_TONE[d.status]} />
          </View>
          <Muted>{d.doc_type} · {new Date(d.created_at).toLocaleDateString()}</Muted>
          <Muted>{describe(d)}</Muted>
        </Card>
      ))}
      {docs.data?.length === 0 && <Muted>No documents yet. Start with a receipt or your bank statement CSV.</Muted>}
    </ScrollView>
  )
}

function describe(d) {
  if (d.error) return d.error
  const ex = d.extracted_data || {}
  if (ex.rows_imported != null) return `${ex.rows_imported} transactions imported`
  const amounts = Object.entries(ex.amounts || {}).map(([k, v]) => `${k.replaceAll('_', ' ')} ${usd(v, 2)}`)
  if (ex.transactions_created) amounts.push(`${ex.transactions_created} transaction(s) added`)
  return amounts.join(' · ') || ex.notes || ''
}
