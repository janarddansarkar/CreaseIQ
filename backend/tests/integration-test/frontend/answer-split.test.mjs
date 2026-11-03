// The UI shows sources as their own panel, so the backend's trailing "Sources: …" block must be removed from the message text (never shown twice).
// Run: node --test "backend/tests/integration-test/frontend/*.test.mjs"
import test from 'node:test'
import assert from 'node:assert/strict'
import { splitAnswer } from '../../../../frontend/src/answer.js'

const DISCLAIMER = 'This is an informational interpretation of the cited playing conditions, not an official ruling by the match officials.'
const WEB_LABEL = 'General answer from web search. Not based on the ICC Playing Conditions.'

test('rules answer: drops the Sources paragraph, keeps the disclaimer', () => {
  const text = `A bowler may bowl four overs (clause 13.9.1).\n\nSources: ICC Men's T20I Playing Conditions, clause p23, p.23\n\n${DISCLAIMER}`
  assert.deepEqual(splitAnswer(text, true), { body: 'A bowler may bowl four overs (clause 13.9.1).', disclaimer: DISCLAIMER })
})

test('web answer: drops the inline Sources block (the web-sources panel shows it) and shows the web label as the closing note', () => {
  const text = `Argentina won the 2022 World Cup.\n\nSources:\n- 2022 FIFA World Cup - Wikipedia: https://en.wikipedia.org/wiki/2022_FIFA_World_Cup\n\n${WEB_LABEL}`
  const { body, disclaimer } = splitAnswer(text, true)
  assert.equal(body, 'Argentina won the 2022 World Cup.')
  assert.equal(disclaimer, WEB_LABEL)
  assert.ok(!body.includes('https://') && !body.includes('Sources'))
})

test('a multi-paragraph body is preserved', () => {
  const text = `Para one.\n\nPara two.\n\nSources: x\n\n${DISCLAIMER}`
  assert.equal(splitAnswer(text, true).body, 'Para one.\n\nPara two.')
})

test('cache-hit label stays in the body', () => {
  const text = `⚡ Cache hit: answered from Redis.\n\nBody.\n\nSources: x\n\n${DISCLAIMER}`
  assert.equal(splitAnswer(text, true).body, '⚡ Cache hit: answered from Redis.\n\nBody.')
})

test('no structured sources (refusals, clarifications, errors, "no web results"): the text is shown unchanged', () => {
  const text = "I can only help with men's ODI and T20I cricket rules."
  assert.deepEqual(splitAnswer(text, false), { body: text, disclaimer: '' })
  const long = 'a\n\nb\n\nc'
  assert.deepEqual(splitAnswer(long, false), { body: long, disclaimer: '' })
})

test('too few paragraphs to contain a sources block: unchanged even with sources', () => {
  assert.deepEqual(splitAnswer('Only one paragraph.', true), { body: 'Only one paragraph.', disclaimer: '' })
  assert.deepEqual(splitAnswer('One.\n\nTwo.', true), { body: 'One.\n\nTwo.', disclaimer: '' })
})

test('empty / missing text', () => {
  assert.deepEqual(splitAnswer('', true), { body: '', disclaimer: '' })
  assert.deepEqual(splitAnswer(undefined, false), { body: '', disclaimer: '' })
})
