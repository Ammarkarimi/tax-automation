import { useState } from 'react'
import { Bot, Send, User } from 'lucide-react'
import { api } from '../api/client'
import { useYear } from '../context/YearContext'
import { Alert, Markdown, PageHeader, SourceBadge } from '../components/ui'

const SUGGESTIONS = [
  'Why is my self-employment tax so high?',
  'How much should I set aside each month?',
  'Can I deduct my phone bill?',
  'What records should I keep for my shop?',
  'What is the QBI deduction?',
]

export default function Assistant() {
  const { year } = useYear()
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)

  const ask = async (question) => {
    if (!question.trim() || busy) return
    setMessages((m) => [...m, { role: 'user', text: question }])
    setInput('')
    setBusy(true)
    try {
      const a = await api.post('/tax/ask', { question }, { year })
      setMessages((m) => [...m, { role: 'assistant', text: a.markdown, source: a.source }])
    } catch (err) {
      setMessages((m) => [...m, { role: 'assistant', text: `⚠️ ${err.message}`, source: 'error' }])
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex h-[calc(100vh-12rem)] flex-col">
      <PageHeader title="AI tax assistant" subtitle={`Answers are grounded in your ${year} numbers. Your name, SSN and documents are never sent to the AI.`} />
      <div className="card flex-1 space-y-4 overflow-y-auto">
        {messages.length === 0 && (
          <div>
            <Alert>Ask anything about your taxes in plain language. For complex situations, confirm with a tax professional.</Alert>
            <div className="mt-4 flex flex-wrap gap-2">
              {SUGGESTIONS.map((s) => <button key={s} className="btn-secondary py-1 text-xs" onClick={() => ask(s)}>{s}</button>)}
            </div>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`flex gap-3 ${m.role === 'user' ? 'justify-end' : ''}`}>
            {m.role === 'assistant' && <Bot className="mt-1 h-5 w-5 shrink-0 text-brand-600" />}
            <div className={`max-w-2xl rounded-xl px-4 py-3 ${m.role === 'user' ? 'bg-brand-600 text-sm text-white' : 'bg-slate-50'}`}>
              {m.role === 'user' ? m.text : (<>{m.source && m.source !== 'error' && <div className="mb-1"><SourceBadge source={m.source} /></div>}<Markdown>{m.text}</Markdown></>)}
            </div>
            {m.role === 'user' && <User className="mt-1 h-5 w-5 shrink-0 text-slate-400" />}
          </div>
        ))}
        {busy && <div className="text-sm text-slate-400">Thinking…</div>}
      </div>
      <form className="mt-4 flex gap-2" onSubmit={(e) => { e.preventDefault(); ask(input) }}>
        <input className="input" maxLength={1000} placeholder="Ask about your taxes…" value={input} onChange={(e) => setInput(e.target.value)} />
        <button className="btn-primary" disabled={busy || input.trim().length < 3}><Send className="h-4 w-4" /></button>
      </form>
    </div>
  )
}
