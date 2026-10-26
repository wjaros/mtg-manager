import { useCallback, useEffect, useState } from 'react'
import { api, wantsExportUrl, type Want, type WantList } from '../api/client'
import { copyText } from '../clipboard'
import { useHoverPreview } from '../hooks/useHoverPreview'
import { locale, t } from '../i18n'
import { wants } from '../wants'
import { BuyMenu } from '../components/BuyMenu'
import { SendToCardTrader } from '../components/SendToCardTrader'

/** Cardmarket's search for a card (any printing); a double-faced card by its front face. */
function cardmarketUrl(name: string): string {
  return `https://www.cardmarket.com/en/Magic/Products/Search?searchString=${encodeURIComponent(name.split(' // ')[0])}`
}

/** Collection › To buy: cards wanted by hand or for decks, minus copies bought since; exported for
Cardmarket's wants list, whose Shopping Wizard finds the sellers. */
export function WantsView() {
  const [list, setList] = useState<WantList | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const preview = useHoverPreview()

  const run = useCallback(async (action: () => Promise<WantList>) => {
    setError(null)
    try {
      const next = await action()
      setList(next)
      wants.update(next)
    } catch (e) {
      setError((e as Error).message)
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    api.wants().then(
      (next) => {
        if (cancelled) return
        setList(next)
        wants.update(next)
      },
      (e: Error) => !cancelled && setError(e.message),
    )
    return () => {
      cancelled = true
    }
  }, [])

  const copy = async () => {
    try {
      await copyText(await api.wantsExport('cardmarket'))
      setNote(t.panels.copiedList('Cardmarket'))
    } catch (e) {
      setNote(t.common.error((e as Error).message))
    }
  }

  if (!list) return <div className="view wants-view">{error ? <p className="status error">{error}</p> : null}</div>
  const asOf = list.prices_as_of ? new Date(list.prices_as_of).toLocaleDateString(locale) : null

  return (
    <div className="view wants-view">
      <p className="muted small">{t.wants.intro}</p>
      {error && <p className="status error">{error}</p>}
      {list.entries.length === 0 ? (
        <p className="muted">{t.wants.empty}</p>
      ) : (
        <>
          <div className="stat-tiles">
            <div className="stat-tile">
              <span className="stat-label">{t.wants.toBuy}</span>
              <span className="stat-value">{list.copies}</span>
              <span className="stat-note">{t.panels.distinctCards(list.entries.length)}</span>
            </div>
            <div className="stat-tile">
              <span className="stat-label">{t.panels.estimatedCost}</span>
              <span className="stat-value">€{list.total_eur.toFixed(2)}</span>
              <span className="stat-note">
                ${list.total_usd.toFixed(2)}
                {asOf && t.panels.pricesAsOf(asOf)}
              </span>
            </div>
          </div>

          <div className="actions">
            <button className="button primary" onClick={copy}>
              {t.panels.copyCardmarket}
            </button>
            <a className="button" href={wantsExportUrl('csv')} download>
              {t.panels.downloadCsv}
            </a>
            <SendToCardTrader request={{ source: 'wants' }} />
            <button
              className="button"
              onClick={() => window.confirm(t.wants.confirmClear) && run(api.clearWants)}
            >
              {t.wants.clear}
            </button>
            {note && <span className="muted small">{note}</span>}
          </div>
          <p className="muted small">{t.wants.cardmarketHint}</p>

          <table className="items-table wants-table">
            <thead>
              <tr>
                <th className="num">{t.wants.toBuy}</th>
                <th>{t.panels.card}</th>
                <th>{t.wants.forWhat}</th>
                <th className="num">{t.panels.have}</th>
                <th className="num">{t.panels.price}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {list.entries.map((w) => (
                <WantRow key={w.oracle_id} want={w} run={run} onHover={preview.show} />
              ))}
            </tbody>
          </table>
        </>
      )}
      {preview.element}
    </div>
  )
}

function WantRow({
  want: w,
  run,
  onHover,
}: {
  want: Want
  run: (action: () => Promise<WantList>) => void
  onHover: ReturnType<typeof useHoverPreview>['show']
}) {
  const bought = w.wanted - w.quantity
  return (
    <tr>
      <td className="num nowrap">
        <span className="deck-row-actions visible">
          <button onClick={() => run(() => api.reduceWant(w.oracle_id))} title={t.wants.fewer}>
            −
          </button>
          <span className="qty">{w.quantity}</span>
          <button onClick={() => run(() => api.addWant(w.card.id))} title={t.wants.more}>
            +
          </button>
        </span>
      </td>
      <td onMouseEnter={(e) => onHover(w.card, e)} onMouseLeave={() => onHover(null)}>
        {w.name}
      </td>
      <td className="muted small">
        {w.sources
          .map((s) => (s.deck_name ? `${s.deck_name} (${s.quantity})` : t.wants.byHand(s.quantity)))
          .join(' · ')}
        {bought > 0 && <span className="validation-ok"> · {t.wants.bought(bought)}</span>}
      </td>
      <td className="num muted">{w.owned}</td>
      <td className="num">{w.price_eur != null ? `€${(w.price_eur * w.quantity).toFixed(2)}` : '—'}</td>
      <td className="nowrap">
        <a href={cardmarketUrl(w.name)} target="_blank" rel="noreferrer" className="small">
          Cardmarket ↗
        </a>
        <BuyMenu cardId={w.card.id} />
        <button className="link-button danger small" onClick={() => run(() => api.removeWant(w.oracle_id))}>
          {t.wants.remove}
        </button>
      </td>
    </tr>
  )
}
