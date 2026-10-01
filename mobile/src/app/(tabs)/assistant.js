import { useRef, useState } from 'react'
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, Text, TextInput, View } from 'react-native'
import { api } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { Badge, Button, MarkdownText, Muted, colors, styles } from '../../components/ui'

const STARTERS = ['How much should I save each month?', 'Can I deduct my phone?', 'What records should I keep?']

export default function Assistant() {
  const { year } = useAuth()
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const scroll = useRef(null)

  const ask = async (q) => {
    if (q.trim().length < 3 || busy) return
    setMessages((m) => [...m, { role: 'user', text: q }])
    setInput('')
    setBusy(true)
    try {
      const a = await api.post('/tax/ask', { question: q }, { year })
      setMessages((m) => [...m, { role: 'assistant', text: a.markdown, source: a.source }])
    } catch (e) {
      setMessages((m) => [...m, { role: 'assistant', text: `⚠️ ${e.message}` }])
    } finally {
      setBusy(false)
      setTimeout(() => scroll.current?.scrollToEnd({ animated: true }), 100)
    }
  }

  return (
    <KeyboardAvoidingView style={styles.screen} behavior={Platform.OS === 'ios' ? 'padding' : undefined} keyboardVerticalOffset={90}>
      <ScrollView ref={scroll} contentContainerStyle={styles.content}>
        {messages.length === 0 && (
          <View style={{ gap: 8 }}>
            <Muted>Ask about your {year} taxes. Answers use your numbers — never your name, SSN or documents.</Muted>
            {STARTERS.map((s) => (
              <Pressable key={s} onPress={() => ask(s)} style={[styles.card, { padding: 12 }]}>
                <Text style={{ color: colors.brand }}>{s}</Text>
              </Pressable>
            ))}
          </View>
        )}
        {messages.map((m, i) => (
          <View key={i} style={[styles.card, m.role === 'user' ? { backgroundColor: colors.brand, alignSelf: 'flex-end', maxWidth: '85%' } : {}]}>
            {m.role === 'user' ? <Text style={{ color: colors.white }}>{m.text}</Text> : (
              <>
                {m.source && <Badge text={m.source === 'ai' ? 'AI' : 'Standard'} tone={m.source === 'ai' ? 'purple' : 'slate'} />}
                <MarkdownText>{m.text}</MarkdownText>
              </>
            )}
          </View>
        ))}
        {busy && <Muted>Thinking…</Muted>}
      </ScrollView>
      <View style={{ flexDirection: 'row', gap: 8, padding: 12, borderTopWidth: 1, borderColor: colors.border, backgroundColor: colors.white }}>
        <TextInput style={[styles.input, { flex: 1 }]} value={input} onChangeText={setInput} placeholder="Ask a question…" maxLength={1000} onSubmitEditing={() => ask(input)} returnKeyType="send" />
        <Button title="Send" onPress={() => ask(input)} disabled={busy || input.trim().length < 3} />
      </View>
    </KeyboardAvoidingView>
  )
}
