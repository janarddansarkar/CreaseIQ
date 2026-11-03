// Integration test for the browser-side SSE client (frontend/src/api.js) with a faked fetch.  Run: node --test backend/tests/integration-test/frontend
import test from 'node:test'
import assert from 'node:assert/strict'
import { sendChat, sendChatStream } from '../../../../frontend/src/api.js'

const enc = new TextEncoder()
const sse = (event, data) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`

/** A Response whose body arrives in the given string chunks (to test events split across network reads). */
function streamResponse(chunks, init = { status: 200 }) {
  const body = new ReadableStream({
    start(c) { for (const ch of chunks) c.enqueue(enc.encode(ch)); c.close() },
  })
  return new Response(body, init)
}

function mockFetch(impl) {
  const calls = []
  globalThis.fetch = async (url, opts) => { calls.push({ url, opts }); return impl(url, opts) }
  return calls
}

const FINAL = { request_id: 'r1', conversation_id: 'c1', status: 'answered', message: 'four overs', citations: [] }

test('streams steps in order and resolves with the final response', async () => {
  const calls = mockFetch(() => streamResponse([sse('step', { node: 'input_guard' }), sse('step', { node: 'retrieve_rules' }), sse('final', FINAL)]))
  const steps = []
  const r = await sendChatStream({ conversationId: 'c1', message: 'hi', language: 'hi', onStep: (n) => steps.push(n) })
  assert.deepEqual(steps, ['input_guard', 'retrieve_rules'])
  assert.deepEqual(r, FINAL)
  assert.equal(calls[0].url, '/api/v1/chat/stream')
  assert.equal(calls[0].opts.method, 'POST')
  assert.deepEqual(JSON.parse(calls[0].opts.body), { conversation_id: 'c1', message: 'hi', response_language: 'hi' })
})

test('sends a null language when none is chosen', async () => {
  const calls = mockFetch(() => streamResponse([sse('final', FINAL)]))
  await sendChatStream({ conversationId: 'c1', message: 'hi' })
  assert.equal(JSON.parse(calls[0].opts.body).response_language, null)
})

test('reassembles events split across network chunks (even mid-line and mid-UTF8)', async () => {
  const text = sse('step', { node: 'a' }) + sse('final', { ...FINAL, message: 'ओवर ⚡' })
  const bytes = enc.encode(text)
  const body = new ReadableStream({ start(c) { for (let i = 0; i < bytes.length; i += 7) c.enqueue(bytes.slice(i, i + 7)); c.close() } })
  mockFetch(() => new Response(body, { status: 200 }))
  const steps = []
  const r = await sendChatStream({ conversationId: 'c', message: 'm', onStep: (n) => steps.push(n) })
  assert.deepEqual(steps, ['a'])
  assert.equal(r.message, 'ओवर ⚡')
})

test('ignores unknown events and works without an onStep callback', async () => {
  mockFetch(() => streamResponse([sse('ping', {}), sse('step', { node: 'x' }), sse('final', FINAL)]))
  assert.deepEqual(await sendChatStream({ conversationId: 'c', message: 'm' }), FINAL)
})

test('an error event rejects with the server detail', async () => {
  mockFetch(() => streamResponse([sse('step', { node: 'x' }), sse('error', { detail: 'Something went wrong. (request abc)' })]))
  await assert.rejects(sendChatStream({ conversationId: 'c', message: 'm' }), /Something went wrong\. \(request abc\)/)
})

test('a stream that ends without a final event rejects', async () => {
  mockFetch(() => streamResponse([sse('step', { node: 'x' })]))
  await assert.rejects(sendChatStream({ conversationId: 'c', message: 'm' }), /ended without a result/)
})

test('HTTP errors surface the JSON detail, or a generic message', async () => {
  mockFetch(() => new Response(JSON.stringify({ detail: 'Unsupported response_language' }), { status: 422 }))
  await assert.rejects(sendChatStream({ conversationId: 'c', message: 'm' }), /Unsupported response_language/)
  mockFetch(() => new Response('<html>bad gateway</html>', { status: 502 }))
  await assert.rejects(sendChatStream({ conversationId: 'c', message: 'm' }), /Request failed \(502\)/)
  mockFetch(() => new Response(JSON.stringify({ detail: [{ msg: 'field required' }] }), { status: 422 }))      // FastAPI validation errors are arrays
  await assert.rejects(sendChatStream({ conversationId: 'c', message: 'm' }), /Request failed \(422\)/)
})

test('passes the abort signal to fetch', async () => {
  const calls = mockFetch(() => streamResponse([sse('final', FINAL)]))
  const ctl = new AbortController()
  await sendChatStream({ conversationId: 'c', message: 'm', signal: ctl.signal })
  assert.equal(calls[0].opts.signal, ctl.signal)
})

test('non-streaming sendChat still works against /chat', async () => {
  const calls = mockFetch(() => new Response(JSON.stringify(FINAL), { status: 200 }))
  assert.deepEqual(await sendChat({ conversationId: 'c', message: 'm' }), FINAL)
  assert.equal(calls[0].url, '/api/v1/chat')
})
