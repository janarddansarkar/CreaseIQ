// Splits the backend's answer text into the part to show as the message body and the closing disclaimer.
//
// The backend ends every grounded answer with two fixed paragraphs: a "Sources: …" block and a disclaimer (for web answers: the "Sources:" list of links
// and the "General answer from web search" label). The UI already renders the structured sources (rules citations or web sources) as its own panel, so
// the text block is dropped here instead of being shown twice.
export function splitAnswer(text, hasStructuredSources) {
  const parts = (text || '').split(/\n\n+/)
  if (hasStructuredSources && parts.length >= 3) return { body: parts.slice(0, -2).join('\n\n'), disclaimer: parts[parts.length - 1] }
  return { body: text || '', disclaimer: '' }
}
