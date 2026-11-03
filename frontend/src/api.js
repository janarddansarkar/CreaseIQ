const BASE = '/api/v1'

async function call(path, opts) {
  const res = await fetch(BASE + path, opts)
  if (!res.ok) {
    let detail = ''
    try { detail = (await res.json()).detail } catch { /* ignore */ }
    throw new Error(typeof detail === 'string' && detail ? detail : `Request failed (${res.status})`)
  }
  return res.json()
}

export const getLanguages = () => call('/languages')

export function sendChat({ conversationId, message, language, signal }) {
  return call('/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ conversation_id: conversationId, message, response_language: language || null }),
    signal,
  })
}

/** Streaming variant of sendChat (SSE over fetch). Calls onStep(node) per graph node; resolves with the final ChatResponse. */
export async function sendChatStream({ conversationId, message, language, signal, onStep }) {
  const res = await fetch(BASE + '/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ conversation_id: conversationId, message, response_language: language || null }),
    signal,
  })
  if (!res.ok) {
    let detail = ''
    try { detail = (await res.json()).detail } catch { /* ignore */ }
    throw new Error(typeof detail === 'string' && detail ? detail : `Request failed (${res.status})`)
  }
  const reader = res.body.getReader()
  const dec = new TextDecoder()
  let buf = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buf += dec.decode(value, { stream: true })
    let i
    while ((i = buf.indexOf('\n\n')) >= 0) {
      const block = buf.slice(0, i)
      buf = buf.slice(i + 2)
      const event = /^event: (.*)$/m.exec(block)?.[1]
      const data = JSON.parse(/^data: (.*)$/m.exec(block)?.[1] || '{}')
      if (event === 'step') onStep?.(data.node)
      else if (event === 'final') return data
      else if (event === 'error') throw new Error(data.detail || 'Request failed')
    }
  }
  throw new Error('Stream ended without a result')
}
