import { useEffect, useState } from 'react'
import { api, type PreconSummary, type ProductSummary } from '../api/client'
import { useDebounced } from '../hooks/useDebounced'
import { t } from '../i18n'

interface Props {
  onLoad: (text: string) => void
  onOpenBox: (key: string) => void
}

/** Find an official precon by its name, its commander or set code, and load its list. Boxes of small
 * decks (Beginner Box…) matching the query are offered first: they open in the Boxes tab. */
export function PreconSearch({ onLoad, onOpenBox }: Props) {
  const [query, setQuery] = useState('')
  // Results for one query; shown only while that is still the query.
  const [found, setFound] = useState<{ q: string; list: PreconSummary[]; boxes: ProductSummary[] } | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const debounced = useDebounced(query, 250)

  const q = debounced.trim()
  useEffect(() => {
    if (q.length < 2) return
    let cancelled = false
    Promise.all([api.precons(q), api.products(q, 3)]).then(
      ([list, boxes]) => !cancelled && setFound({ q, list, boxes }),
      (e: Error) => !cancelled && setError(e.message),
    )
    return () => {
      cancelled = true
    }
  }, [q])
  const current = q.length >= 2 && found?.q === q ? found : null
  const results = current?.list ?? null
  const boxes = current?.boxes ?? []

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
      {results !== null && results.length === 0 && boxes.length === 0 && (
        <p className="muted small">{t.precons.none}</p>
      )}
      {current !== null && (results!.length > 0 || boxes.length > 0) && (
        <ul className="precon-results">
          {boxes.map((b) => (
            <li key={b.key}>
              <button onClick={() => onOpenBox(b.key)}>
                <span className="pill">{t.precons.box}</span>
                <strong>{b.name}</strong>
                <span className="muted small">
                  {' '}
                  · {b.set_name ?? b.code.toUpperCase()}
                  {b.release_date && ` · ${b.release_date.slice(0, 4)}`} · {t.boxes.decks(b.decks)}
                </span>
                <span className="small precon-commander">{t.precons.openBox}</span>
              </button>
            </li>
          ))}
          {results!.map((p) => (
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
