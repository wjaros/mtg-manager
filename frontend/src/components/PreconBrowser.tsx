import { useEffect, useMemo, useState } from 'react'
import { api, type PreconOverview } from '../api/client'
import { formatNumber, t } from '../i18n'
import { ManaCost } from './ManaCost'

const COLORS = ['W', 'U', 'B', 'R', 'G'] as const
type Order = 'newest' | 'owned' | 'price'

/** Commander precons: their commanders' colors, how much of each you own, the cards' value. */
export function PreconBrowser({ onImport }: { onImport: (fileName: string) => void }) {
  const [list, setList] = useState<PreconOverview[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [colors, setColors] = useState<string[]>([])
  const [order, setOrder] = useState<Order>('newest')

  useEffect(() => {
    api.commanderPrecons().then(setList, (e: Error) => setError(e.message))
  }, [])

  const shown = useMemo(() => {
    const words = query.toLowerCase().split(/\s+/).filter(Boolean)
    const filtered = (list ?? []).filter((o) => {
      const text = `${o.precon.name} ${o.precon.commanders.join(' ')} ${o.precon.set_name ?? ''} ${o.precon.code}`.toLowerCase()
      // Colors: the commander's identity contains every chosen color.
      return words.every((w) => text.includes(w)) && colors.every((c) => o.colors.includes(c))
    })
    const by: Record<Order, (a: PreconOverview, b: PreconOverview) => number> = {
      newest: (a, b) => (b.precon.release_date ?? '').localeCompare(a.precon.release_date ?? ''),
      owned: (a, b) => b.owned / (b.cards || 1) - a.owned / (a.cards || 1),
      price: (a, b) => b.price_eur - a.price_eur,
    }
    return [...filtered].sort(by[order])
  }, [list, query, colors, order])

  if (error) return <p className="status error">{error}</p>
  if (list === null) return <p className="muted">{t.common.loading}</p>
  if (list.length === 0) return <p className="muted">{t.precons.notSynced}</p>

  return (
    <section className="panel precon-browser">
      <div className="precon-filters">
        <input
          className="input"
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t.precons.filterPlaceholder}
          aria-label={t.precons.filterPlaceholder}
        />
        <div className="color-toggles" role="group" aria-label={t.precons.colors}>
          {COLORS.map((c) => (
            <button
              key={c}
              className={`color-toggle ${colors.includes(c) ? 'on' : ''}`}
              onClick={() => setColors((prev) => (prev.includes(c) ? prev.filter((x) => x !== c) : [...prev, c]))}
              title={t.precons.colorTitle}
            >
              <ManaCost cost={`{${c}}`} />
            </button>
          ))}
        </div>
        <select className="select small" value={order} onChange={(e) => setOrder(e.target.value as Order)}>
          <option value="newest">{t.precons.orderNewest}</option>
          <option value="owned">{t.precons.orderOwned}</option>
          <option value="price">{t.precons.orderPrice}</option>
        </select>
        <span className="muted small">{t.precons.count(shown.length)}</span>
      </div>
      <table className="items-table precon-table">
        <thead>
          <tr>
            <th>{t.precons.deck}</th>
            <th>{t.precons.commander}</th>
            <th />
            <th>{t.precons.owned}</th>
            <th className="num">{t.precons.value}</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {shown.map((o) => (
            <tr key={o.precon.file_name}>
              <td>
                {o.precon.name}
                <div className="muted small">
                  {o.precon.set_name ?? o.precon.code.toUpperCase()}
                  {o.precon.release_date && ` · ${o.precon.release_date.slice(0, 4)}`}
                </div>
              </td>
              <td className="small">{o.precon.commanders.join(' & ')}</td>
              <td>
                <ManaCost cost={o.colors.map((c) => `{${c}}`).join('')} />
              </td>
              <td className="small">
                <div className="owned-bar" title={t.precons.ownedTitle(o.owned, o.cards)}>
                  <div style={{ width: `${o.cards ? (o.owned / o.cards) * 100 : 0}%` }} />
                </div>
                {o.owned}/{o.cards}
              </td>
              <td className="num small">€{formatNumber(Math.round(o.price_eur))}</td>
              <td className="row-actions">
                <button className="link-button small" onClick={() => onImport(o.precon.file_name)}>
                  {t.precons.import}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted small">{t.precons.valueNote}</p>
    </section>
  )
}
