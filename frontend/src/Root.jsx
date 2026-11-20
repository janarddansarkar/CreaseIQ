import { useEffect, useState } from 'react'
import App from './App.jsx'
import Admin from './Admin.jsx'

/** Tiny hash router: #/admin shows the admin upload page, anything else the chat. */
export default function Root() {
  const [hash, setHash] = useState(window.location.hash)
  useEffect(() => {
    const on = () => setHash(window.location.hash)
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  return hash === '#/admin' ? <Admin /> : <App />
}
