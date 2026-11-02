import { useEffect, useRef, useState } from 'react'
import { getLanguages, sendChat } from './api'
import Message from './Message'

const TIMEOUT_MS = 120000
const EXAMPLES = [
  'What happens after a no ball in an ODI?',
  'What is a free hit in a T20I match?',
  'What does clause 21.18 say?',
  'Compare the free hit rule in ODI and T20I',
]

const newId = () => (crypto.randomUUID ? crypto.randomUUID().replace(/-/g, '').slice(0, 24) : String(Date.now()))

function loadConv() {
  try {
    const s = JSON.parse(localStorage.getItem('creaseiq') || 'null')
    if (s?.id) return s
  } catch { /* ignore */ }
  return { id: newId(), messages: [] }
}

export default function App() {
  const [conv, setConv] = useState(loadConv)
  const [input, setInput] = useState('')
  const [language, setLanguage] = useState('')
  const [languages, setLanguages] = useState({ en: 'English', hi: 'Hindi' })
  const [loading, setLoading] = useState(false)
  const endRef = useRef(null)
  const abortRef = useRef(null)

  useEffect(() => { getLanguages().then((d) => setLanguages(d.languages)).catch(() => {}) }, [])
  useEffect(() => {
    try { localStorage.setItem('creaseiq', JSON.stringify(conv)) } catch { /* ignore */ }
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [conv, loading])

  const last = conv.messages[conv.messages.length - 1]
  const awaitingClarification = last?.role === 'assistant' && last.status === 'clarification_required'

  async function send(text) {
    const message = text.trim()
    if (!message || loading) return
    setInput('')
    setConv((c) => ({ ...c, messages: [...c.messages, { role: 'user', text: message }] }))
    setLoading(true)
    const ctl = new AbortController()
    abortRef.current = ctl
    const timer = setTimeout(() => ctl.abort('timeout'), TIMEOUT_MS)
    try {
      const r = await sendChat({ conversationId: conv.id, message, language, signal: ctl.signal })
      setConv((c) => ({ ...c, id: r.conversation_id, messages: [...c.messages, { role: 'assistant', ...r, text: r.message }] }))
    } catch (e) {
      const text = ctl.signal.aborted ? (ctl.signal.reason === 'timeout' ? 'The request timed out. Please try again.' : 'Cancelled.') : e.message || 'Something went wrong.'
      setConv((c) => ({ ...c, messages: [...c.messages, { role: 'assistant', status: 'error', text, citations: [] }] }))
    } finally {
      clearTimeout(timer)
      setLoading(false)
    }
  }

  function reset() {
    abortRef.current?.abort('reset')
    setConv({ id: newId(), messages: [] })
    setLoading(false)
  }

  const onKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(input) }
  }

  return (
    <div className="app">
      <header className="top">
        <div className="brand">
          <span className="logo" aria-hidden>🏏</span>
          <div>
            <h1>CreaseIQ</h1>
            <p>ICC playing conditions assistant · ODI &amp; T20I</p>
          </div>
        </div>
        <div className="controls">
          <label>
            <span className="sr">Response language</span>
            <select value={language} onChange={(e) => setLanguage(e.target.value)} aria-label="Response language">
              <option value="">Auto language</option>
              {Object.entries(languages).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
          <button className="ghost" onClick={reset} disabled={!conv.messages.length && !loading}>New chat</button>
        </div>
      </header>

      <main className="thread" aria-live="polite">
        {conv.messages.length === 0 && (
          <div className="empty">
            <h2>Ask about a cricket scenario</h2>
            <p>Describe what happened on the field and get an answer grounded in the ICC Men's playing conditions, with citations.</p>
            <div className="chips">
              {EXAMPLES.map((e) => <button key={e} className="chip" onClick={() => send(e)}>{e}</button>)}
            </div>
          </div>
        )}
        {conv.messages.map((m, i) => (
          <Message key={i} m={m} showFormatChoices={m === last && awaitingClarification && !loading} onChoose={send} />
        ))}
        {loading && (
          <div className="row assistant"><div className="bubble typing" aria-label="Thinking"><i /><i /><i /></div></div>
        )}
        <div ref={endRef} />
      </main>

      <footer className="composer">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKey}
          rows={1}
          maxLength={2000}
          placeholder={awaitingClarification ? 'Answer the question above…' : 'Describe a cricket scenario or ask about a clause…'}
          aria-label="Message"
        />
        <button className="send" onClick={() => send(input)} disabled={loading || !input.trim()}>Send</button>
        <p className="note">Informational only — not an official ruling by match officials.</p>
      </footer>
    </div>
  )
}
