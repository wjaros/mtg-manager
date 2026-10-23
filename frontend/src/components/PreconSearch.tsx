import { useEffect, useState } from 'react'
import { api, type PreconSummary } from '../api/client'
import { useDebounced } from '../hooks/useDebounced'
import { t } from '../i18n'

/** Find an official precon by its name, its commander or set code, and load its list. */
export function PreconSearch({ onLoad }: { onLoad: (text: string) => void }) {
  const [query, setQuery] = useState('')
  // Results for one query; shown only while that is still the query.
  const [found, setFound] = useState<{ q: string; list: PreconSummary[] } | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const debounced = useDebounced(query, 250)

  const q = debounced.trim()
  useEffect(() => {
    if (q.length < 2) return
    let cancelled = false
    api.precons(q).then(
      (list) => !cancelled && setFound({ q, list }),
      (e: Error) => !cancelled && setError(e.message),
    )
    return () => {
      cancelled = true
    }
  }, [q])
  const results = q.length >= 2 && found?.q === q ? found.list : null

  const load = async (precon: PreconSummary) => {
    setBusy(precon.file_name)
    setError(null)
    try {
      const deck = await api.preconDecklist(precon.file_name)
      onLoad(deck.text)
      setQuery('')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="precon-search">
      <input
        className="input"
        type="search"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder={t.precons.placeholder}
        aria-label={t.precons.placeholder}
      />
      {results !== null && results.length === 0 && <p className="muted small">{t.precons.none}</p>}
      {results !== null && results.length > 0 && (
        <ul className="precon-results">
          {results.map((p) => (
            <li key={p.file_name}>
              <button onClick={() => load(p)} disabled={busy !== null}>
                <strong>{p.name}</strong>
                <span className="muted small">
                  {' '}
                  · {p.set_name ?? p.code.toUpperCase()}
                  {p.release_date && ` · ${p.release_date.slice(0, 4)}`}
                  {p.type !== 'Commander Deck' && ` · ${p.type}`}
                </span>
                {p.commanders.length > 0 && <span className="small precon-commander">{p.commanders.join(' & ')}</span>}
                {busy === p.file_name && <span className="muted small"> {t.common.loading}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
      {error && <p className="status error small">{error}</p>}
    </div>
  )
}
