// Presentation only: renders the backend's status, text and citations without interpreting them.
const STATUS = {
  answered: null,
  answered_general: { label: 'General answer (web)', tone: 'info' },
  clarification_required: { label: 'Clarification needed', tone: 'warn' },
  unsupported: { label: 'Not supported', tone: 'warn' },
  insufficient_evidence: { label: 'Insufficient evidence', tone: 'warn' },
  out_of_scope: { label: 'Out of scope', tone: 'warn' },
  error: { label: 'Error', tone: 'err' },
}

// The backend appends "Sources: …" and a disclaimer as the last two paragraphs; show them as structured UI instead.
function splitAnswer(text, hasCitations) {
  const parts = (text || '').split(/\n\n+/)
  if (hasCitations && parts.length >= 3) return { body: parts.slice(0, -2).join('\n\n'), disclaimer: parts[parts.length - 1] }
  return { body: text || '', disclaimer: '' }
}

export default function Message({ m, showFormatChoices, onChoose }) {
  if (m.role === 'user') {
    return <div className="row user"><div className="bubble">{m.text}</div></div>
  }
  const st = STATUS[m.status]
  const cites = m.citations || []
  const { body, disclaimer } = splitAnswer(m.text, cites.length > 0)
  return (
    <div className="row assistant">
      <div className={`bubble ${m.status === 'error' ? 'error' : ''}`}>
        {st && <span className={`badge ${st.tone}`}>{st.label}</span>}
        {m.format && m.format !== 'unknown' && m.status === 'answered' && <span className="badge fmt">{m.format}</span>}
        <p className="body">{body}</p>
        {cites.length > 0 && (
          <div className="cites">
            <h3>Sources</h3>
            <ul>
              {cites.map((c, i) => (
                <li key={c.chunk_id || i}>
                  <strong>{c.source_title || 'Source'}</strong>
                  <span>{[c.clause_number && `clause ${c.clause_number}`, c.page && `p.${c.page}`, c.version].filter(Boolean).join(' · ')}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {m.web_sources?.length > 0 && (
          <div className="cites">
            <h3>Web sources</h3>
            <ul>
              {m.web_sources.map((s, i) => (
                <li key={i}>
                  {s.url ? <a href={s.url} target="_blank" rel="noreferrer noopener">{s.title || s.url}</a> : <strong>{s.title || 'Source'}</strong>}
                </li>
              ))}
            </ul>
          </div>
        )}
        {disclaimer && <p className="disclaimer">{disclaimer}</p>}
        {showFormatChoices && (
          <div className="chips">
            <button className="chip" onClick={() => onChoose('ODI')}>ODI</button>
            <button className="chip" onClick={() => onChoose('T20I')}>T20I</button>
          </div>
        )}
      </div>
    </div>
  )
}
