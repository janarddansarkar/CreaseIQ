import { useEffect, useRef, useState } from 'react'
import { getJob, getKb, uploadDocument } from './api'

const STEPS = { queued: 'Queued', building: 'Building the new index', checking: 'Checking the new index', swapping: 'Switching over', done: 'Done', failed: 'Failed' }
const fmtDate = (iso) => iso ? new Date(iso).toLocaleString(undefined, { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—'

/** Hidden admin page (#/admin): upload a replacement rulebook; the server rebuilds the knowledge base and reports progress. */
export default function Admin() {
  const [token, setToken] = useState('')
  const [file, setFile] = useState(null)
  const [format, setFormat] = useState('ODI')
  const [version, setVersion] = useState('')
  const [job, setJob] = useState(null)
  const [error, setError] = useState('')
  const [kb, setKb] = useState(null)
  const timer = useRef(null)
  const running = job && !['done', 'failed'].includes(job.status)

  const refreshKb = () => getKb().then(setKb).catch(() => {})
  useEffect(() => { refreshKb(); return () => clearTimeout(timer.current) }, [])

  function poll(id, tk) {
    getJob(tk, id).then((j) => {
      setJob(j)
      if (['done', 'failed'].includes(j.status)) { refreshKb(); return }
      timer.current = setTimeout(() => poll(id, tk), 2000)
    }).catch((e) => { setError(e.message); setJob(null) })
  }

  async function submit(e) {
    e.preventDefault()
    setError(''); setJob(null)
    try {
      const { job_id } = await uploadDocument({ token, file, format, version: version.trim() })
      setJob({ id: job_id, status: 'queued', detail: '' })
      poll(job_id, token)
    } catch (err) { setError(err.message) }
  }

  return (
    <div className="app admin">
      <header className="top">
        <div className="brand">
          <span className="logo" aria-hidden>🛠️</span>
          <div><h1>Knowledge base admin</h1><p>Upload a replacement rulebook</p></div>
        </div>
        <a className="ghost" href="#/">← Back to chat</a>
      </header>

      <main className="thread">
        <section className="card">
          <h2>Current knowledge base</h2>
          <p className="muted">Last updated: {fmtDate(kb?.updated_at)}</p>
          <ul className="docs">
            {(kb?.documents || []).map((d) => (
              <li key={d.format}><strong>{d.format}</strong> {d.title}<span>{d.version ? `version ${d.version} · ` : ''}{d.pages} pages · {d.chunks} chunks</span></li>
            ))}
          </ul>
        </section>

        <form className="card" onSubmit={submit}>
          <h2>Upload a rulebook</h2>
          <label>Admin token
            <input type="password" value={token} onChange={(e) => setToken(e.target.value)} autoComplete="off" required />
          </label>
          <label>Format
            <select value={format} onChange={(e) => setFormat(e.target.value)}>
              <option value="ODI">ODI</option><option value="T20I">T20I</option>
            </select>
          </label>
          <label>Version label (optional)
            <input type="text" value={version} onChange={(e) => setVersion(e.target.value)} maxLength={64} placeholder="e.g. Jan 2027" />
          </label>
          <label>PDF file
            <input type="file" accept="application/pdf,.pdf" onChange={(e) => setFile(e.target.files[0] || null)} required />
          </label>
          <p className="muted">This replaces the current {format} rulebook (the old PDF is archived on the server). It takes about a minute.</p>
          <button className="send" type="submit" disabled={running || !file || !token}>{running ? 'Working…' : `Upload and rebuild`}</button>
          {error && <p className="msg err" role="alert">{error}</p>}
          {job && (
            <p className={`msg ${job.status === 'failed' ? 'err' : job.status === 'done' ? 'ok' : 'info'}`} role="status">
              <strong>{STEPS[job.status] || job.status}</strong>{job.detail ? ` — ${job.detail}` : ''}
            </p>
          )}
        </form>
      </main>
    </div>
  )
}
