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
