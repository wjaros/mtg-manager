import { useEffect, useMemo, useState } from 'react'
import { api, type ProductOverview } from '../api/client'
import { useDebounced } from '../hooks/useDebounced'
import { formatNumber, t } from '../i18n'
import { ManaCost } from './ManaCost'

const COLORS = ['W', 'U', 'B', 'R', 'G'] as const
type Order = 'newest' | 'owned' | 'price'

interface Props {
  opening: string | null
  onOpen: (key: string) => void
  onOpenBox: (boxId: number) => void
}

/** Boxes of small decks like the precon list: their cards' colors, how much of them you own, the cards'
 * value, and a link to the box when it is already in Decks. Big pools (Jumpstart) show numbers only once
 * all their packs are stored. */
export function ProductBrowser({ opening, onOpen, onOpenBox }: Props) {
  const [list, setList] = useState<ProductOverview[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [colors, setColors] = useState<string[]>([])
  const [order, setOrder] = useState<Order>('newest')
  // The search runs on the server (word starts, typos, "starter kit"): its keys filter the list.
  const [matched, setMatched] = useState<{ q: string; keys: Set<string> } | null>(null)
  const q = useDebounced(query, 250).trim()

  useEffect(() => {
    api.productsOverview().then(setList, (e: Error) => setError(e.message))
  }, [])

  useEffect(() => {
    if (!q) return
    let cancelled = false
    api.products(q, 200).then(
      (found) => !cancelled && setMatched({ q, keys: new Set(found.map((p) => p.key)) }),
      (e: Error) => !cancelled && setError(e.message),
    )
    return () => {
      cancelled = true
    }
  }, [q])

  const shown = useMemo(() => {
    const keys = q && matched?.q === q ? matched.keys : null
    const filtered = (list ?? []).filter(
      (o) => (!q || keys?.has(o.product.key)) && colors.every((c) => o.colors.includes(c)),
    )
    const share = (o: ProductOverview) => (o.loaded ? o.owned / (o.cards || 1) : -1)
    const by: Record<Order, (a: ProductOverview, b: ProductOverview) => number> = {
      newest: (a, b) => (b.product.release_date ?? '').localeCompare(a.product.release_date ?? ''),
      owned: (a, b) => share(b) - share(a),
      price: (a, b) => b.price_eur - a.price_eur,
    }
    return [...filtered].sort(by[order])
  }, [list, q, matched, colors, order])

  if (error) return <p className="status error">{error}</p>
  if (list === null) return <p className="muted">{t.common.loading}</p>
  if (list.length === 0) return <p className="muted">{t.boxes.none}</p>

  return (
    <>
      <div className="precon-filters">
        <input
          className="input"
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t.boxes.placeholder}
          aria-label={t.boxes.placeholder}
        />
        <div className="color-toggles" role="group" aria-label={t.boxes.colors}>
          {COLORS.map((c) => (
            <button
              key={c}
              className={`color-toggle ${colors.includes(c) ? 'on' : ''}`}
              onClick={() => setColors((prev) => (prev.includes(c) ? prev.filter((x) => x !== c) : [...prev, c]))}
              title={t.boxes.colorTitle}
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
        <span className="muted small">{t.boxes.count(shown.length)}</span>
      </div>
      <table className="items-table precon-table">
        <thead>
          <tr>
            <th>{t.boxes.boxLabel}</th>
            <th>{t.boxes.decksColumn}</th>
            <th />
            <th>{t.precons.owned}</th>
            <th className="num">{t.precons.value}</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {shown.map((o) => (
            <tr key={o.product.key}>
              <td>
                {o.product.name}
                <div className="muted small">
                  {o.product.set_name ?? o.product.code.toUpperCase()}
                  {o.product.release_date && ` · ${o.product.release_date.slice(0, 4)}`}
                </div>
              </td>
              <td className="small">{o.product.decks}</td>
              <td>
                <ManaCost cost={o.colors.map((c) => `{${c}}`).join('')} />
              </td>
              {o.loaded ? (
                <>
                  <td className="small">
                    <div className="owned-bar" title={t.precons.ownedTitle(o.owned, o.cards)}>
                      <div style={{ width: `${o.cards ? (o.owned / o.cards) * 100 : 0}%` }} />
                    </div>
                    {o.owned}/{o.cards}
                  </td>
                  <td className="num small">€{formatNumber(Math.round(o.price_eur))}</td>
                </>
              ) : (
                <td colSpan={2} className="muted small" title={t.boxes.notLoadedTitle}>
                  {t.boxes.notLoadedShort}
                </td>
              )}
              <td className="row-actions">
                {o.box_id !== null && (
                  <button className="link-button small" onClick={() => onOpenBox(o.box_id!)}>
                    {t.boxes.inDecks}
                  </button>
                )}
                <button className="link-button small" onClick={() => onOpen(o.product.key)} disabled={opening !== null}>
                  {opening === o.product.key ? t.common.loading : t.boxes.openProduct}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted small">{t.precons.valueNote}</p>
    </>
  )
}
