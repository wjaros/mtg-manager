import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type MouseEvent } from 'react'
import { api, type Offer, type ShoppingList, type ShoppingRow } from '../api/client'
import { copyText } from '../clipboard'
import { formatMoney as money, t } from '../i18n'
import { openLinks } from '../openLinks'
import { BasketPanel } from './BasketPanel'

interface Props {
  deckId: number
  /** Changes whenever the deck's contents change, to refetch. */
  revision: string
  onHover: (card: { id: string; name: string; image_faces: number } | null, event?: MouseEvent) => void
}

function parseNumber(value: string): number | null {
  const n = Number(value.replace(',', '.'))
  return value.trim() === '' || Number.isNaN(n) ? null : n
}

/** A deck's shopping list: what it lacks (proxied cards too), searches per shop, ticks kept per deck,
offers noted at sellers, and the basket planner below. */
export function ShoppingPanel({ deckId, revision, onHover }: Props) {
  const [list, setList] = useState<ShoppingList | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [sourceId, setSourceId] = useState<number | null>(null)
  const [remaining, setRemaining] = useState<string[]>([])
  const [adding, setAdding] = useState<string | null>(null)
  const [lastSeller, setLastSeller] = useState('')
  const [basketVersion, setBasketVersion] = useState(0)

  const load = useCallback(
    () =>
      api.shoppingList(deckId).then(
        (next) => {
          setList(next)
          setError(null)
        },
        (e: Error) => setError(e.message),
      ),
    [deckId],
  )
  useEffect(() => {
    void load()
  }, [load, revision])

  const run = async (action: () => Promise<unknown>) => {
    setNote(null)
    try {
      await action()
    } catch (e) {
      setError((e as Error).message)
    }
    await load()
    setBasketVersion((v) => v + 1)
  }

  if (error && !list) return <p className="status error">{error}</p>
  if (!list) return <p className="muted">{t.common.loading}</p>
  if (!list.rows.length) return <p className="validation-ok">{t.buy.empty}</p>

  const source = list.sources.find((s) => s.id === sourceId) ?? list.sources[0]
  const done = list.rows.filter((r) => r.done).length
  const allSelected = list.rows.every((r) => selected.has(r.oracle_id))

  const openSelected = async () => {
    if (!source) return
    const urls = list.rows
      .filter((r) => selected.has(r.oracle_id))
      .map((r) => r.links.find((l) => l.source_id === source.id)?.url)
      .filter((u): u is string => !!u)
    try {
      const rest = await openLinks(urls)
      if (rest === null) return
      setRemaining(rest)
      if (!rest.length) setNote(t.buy.opened(urls.length))
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const copyCardmarket = async () => {
    try {
      await copyText(await api.missingExport(deckId, 'cardmarket', false, true))
      setNote(t.panels.copiedList('CardMarket'))
    } catch (e) {
      setNote(t.common.error((e as Error).message))
    }
  }

  const pending = list.rows.filter((r) => !r.done)
  const nextAfter = (oracleId: string) => {
    const i = pending.findIndex((r) => r.oracle_id === oracleId)
    return pending[i + 1]?.oracle_id ?? null
  }

  return (
    <div className="shopping-panel">
      <p className="muted small">{t.buy.intro}</p>
      {error && <p className="status error">{error}</p>}
      <div className="actions">
        <label className="checkbox">
          <input
            type="checkbox"
            checked={allSelected}
            onChange={() => setSelected(allSelected ? new Set() : new Set(list.rows.map((r) => r.oracle_id)))}
          />
          {t.buy.selectAll}
        </label>
        <button className="button primary" disabled={!selected.size || !source} onClick={openSelected}>
          {t.buy.openSelected} ({selected.size})
        </button>
        {list.sources.length > 1 && (
          <label>
            {t.buy.openIn}{' '}
            <select className="select small" value={source?.id ?? ''} onChange={(e) => setSourceId(Number(e.target.value))}>
              {list.sources.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </label>
        )}
        <button className="button" onClick={() => run(() => api.pickCheapest(deckId))}>
          {t.buy.pickCheapestAll}
        </button>
        <span className="muted small">{t.buy.doneCount(done, list.rows.length)}</span>
        {done > 0 && (
          <button
            className="link-button small"
            onClick={() => window.confirm(t.buy.confirmReset) && run(() => api.resetShoppingDone(deckId))}
          >
            {t.buy.reset}
          </button>
        )}
      </div>
      {remaining.length > 0 && (
        <div className="remaining-links">
          <span className="muted small">{t.buy.remaining}</span>
          {remaining.map((url) => (
            <a
              key={url}
              href={url}
              target="_blank"
              rel="noreferrer"
              className="small"
              onClick={() => setRemaining((r) => r.filter((u) => u !== url))}
            >
              {decodeURIComponent(url.replace(/\+/g, ' ')).slice(0, 80)}
            </a>
          ))}
        </div>
      )}
      <div className="actions">
        <button className="button" onClick={copyCardmarket}>
          {t.panels.copyCardmarket}
        </button>
        <span className="muted small">{t.buy.cardmarketHint}</span>
        {note && <span className="muted small">{note}</span>}
      </div>

      <table className="items-table shopping-table">
        <thead>
          <tr>
            <th />
            <th title={t.buy.doneTitle}>{t.buy.done}</th>
            <th>{t.panels.card}</th>
            <th className="num">{t.buy.qty}</th>
            <th>{t.buy.reason}</th>
            {list.sources.map((s) => (
              <th key={s.id}>{s.name}</th>
            ))}
            <th>{t.buy.offers}</th>
          </tr>
        </thead>
        <tbody>
          {list.rows.map((row) => (
            <Row
              key={row.oracle_id}
              row={row}
              list={list}
              selected={selected.has(row.oracle_id)}
              onSelect={() => {
                const next = new Set(selected)
                if (next.has(row.oracle_id)) next.delete(row.oracle_id)
                else next.add(row.oracle_id)
                setSelected(next)
              }}
              onHover={onHover}
              adding={adding === row.oracle_id}
              onAdding={(open) => setAdding(open ? row.oracle_id : null)}
              lastSeller={lastSeller}
              run={run}
              onSaved={(seller) => {
                setLastSeller(seller)
                setAdding(nextAfter(row.oracle_id))
              }}
            />
          ))}
        </tbody>
      </table>
      <datalist id="shopping-sellers">
        {list.sellers.map((s) => (
          <option key={s} value={s} />
        ))}
      </datalist>

      <BasketPanel deckId={deckId} version={basketVersion} currency={list.settings.currency ?? 'PLN'} onChanged={() => run(async () => {})} />
    </div>
  )
}

function Row({
  row,
  list,
  selected,
  onSelect,
  onHover,
  adding,
  onAdding,
  lastSeller,
  run,
  onSaved,
}: {
  row: ShoppingRow
  list: ShoppingList
  selected: boolean
  onSelect: () => void
  onHover: Props['onHover']
  adding: boolean
  onAdding: (open: boolean) => void
  lastSeller: string
  run: (action: () => Promise<unknown>) => Promise<void>
  onSaved: (seller: string) => void
}) {
  const deckId = list.deck_id
  const currency = list.settings.currency ?? 'PLN'
  return (
    <tr className={row.done ? 'done' : ''}>
      <td>
        <input type="checkbox" checked={selected} onChange={onSelect} aria-label={row.name} />
      </td>
      <td>
        <input
          type="checkbox"
          checked={row.done}
          title={t.buy.doneTitle}
          onChange={(e) => run(() => api.setShoppingDone(deckId, row.oracle_id, e.target.checked))}
        />
      </td>
      <td onMouseEnter={(e) => onHover(row.card, e)} onMouseLeave={() => onHover(null)}>
        {row.name}
      </td>
      <td className="num strong">{row.qty}</td>
      <td className={row.reason === 'proxy' ? 'proxy-text small' : 'small'}>
        {row.reason === 'proxy' ? t.buy.reasonProxy : t.buy.reasonMissing}
        {row.reason === 'missing' && row.proxied > 0 && <span className="muted"> (+{row.proxied} proxy)</span>}
      </td>
      {list.sources.map((s) => {
        const link = row.links.find((l) => l.source_id === s.id)
        return (
          <td key={s.id} className="nowrap">
            {link && (
              <a href={link.url} target="_blank" rel="noreferrer" className="small">
                {s.name} ↗
              </a>
            )}
          </td>
        )
      })}
      <td className="offers-cell">
        {row.offers.map((o) => (
          <OfferLine key={o.id} offer={o} qty={row.qty} currency={currency} deckId={deckId} oracleId={row.oracle_id} run={run} />
        ))}
        {adding ? (
          <OfferForm
            list={list}
            row={row}
            seller={lastSeller}
            onCancel={() => onAdding(false)}
            onSave={async (body) => {
              await run(() => api.addOffer(deckId, { oracle_id: row.oracle_id, ...body }))
              onSaved(body.seller_name ?? '')
            }}
          />
        ) : (
          <span className="offer-actions">
            <button className="link-button small" onClick={() => onAdding(true)}>
              {t.buy.addOffer}
            </button>
            {row.offers.length > 1 && (
              <button
                className="link-button small"
                title={t.buy.pickCheapestTitle}
                onClick={() => run(() => api.pickCheapest(deckId, row.oracle_id))}
              >
                {t.buy.pickCheapest}
              </button>
            )}
          </span>
        )}
      </td>
    </tr>
  )
}

function OfferLine({
  offer: o,
  qty,
  currency,
  deckId,
  oracleId,
  run,
}: {
  offer: Offer
  qty: number
  currency: string
  deckId: number
  oracleId: string
  run: (action: () => Promise<unknown>) => Promise<void>
}) {
  const short = o.qty_available != null && o.qty_available < qty
  return (
    <div className={`offer-line ${o.chosen ? 'chosen' : ''}`}>
      <label className="checkbox small">
        <input
          type="radio"
          checked={o.chosen}
          onChange={() => run(() => api.setChoices(deckId, { [oracleId]: o.id }))}
          onClick={() => o.chosen && run(() => api.setChoices(deckId, { [oracleId]: null }))}
          title={o.chosen ? t.buy.chosen : t.buy.choose}
        />
        {o.seller_name} · {money(o.price)} {currency}
        {o.qty_available != null && <span className="muted"> ({o.qty_available})</span>}
      </label>
      {short && <span className="warn-text small"> {t.buy.short}</span>}
      {o.url && (
        <a href={o.url} target="_blank" rel="noreferrer" className="small">
          {' '}
          ↗
        </a>
      )}
      <button className="link-button danger small" title={t.buy.removeOffer} onClick={() => run(() => api.deleteOffer(o.id))}>
        ×
      </button>
    </div>
  )
}

function OfferForm({
  list,
  row,
  seller: initialSeller,
  onSave,
  onCancel,
}: {
  list: ShoppingList
  row: ShoppingRow
  seller: string
  onSave: (body: { seller_name: string; price: number; qty_available: number | null; url: string | null; chosen: boolean }) => Promise<void>
  onCancel: () => void
}) {
  const [seller, setSeller] = useState(initialSeller)
  const [price, setPrice] = useState('')
  const [qty, setQty] = useState('')
  const [url, setUrl] = useState('')
  const first = useRef<HTMLInputElement>(null)
  const priceRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    // The seller is usually the one of the previous offer: start at the price then.
    ;(initialSeller ? priceRef : first).current?.focus()
  }, [initialSeller])

  const value = parseNumber(price)
  const valid = seller.trim() !== '' && value !== null && value >= 0
  const save = () => {
    if (!valid || value === null) return
    void onSave({
      seller_name: seller.trim(),
      price: value,
      qty_available: parseNumber(qty),
      url: url.trim() || null,
      // The card's first offer is chosen right away.
      chosen: row.offers.length === 0,
    })
  }
  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      save()
    } else if (e.key === 'Escape') onCancel()
  }

  return (
    <div className="offer-form" onKeyDown={onKey}>
      <input
        ref={first}
        className="input"
        list="shopping-sellers"
        value={seller}
        onChange={(e) => setSeller(e.target.value)}
        placeholder={t.buy.seller}
        aria-label={t.buy.seller}
      />
      <input
        ref={priceRef}
        className="input narrow"
        inputMode="decimal"
        value={price}
        onChange={(e) => setPrice(e.target.value)}
        placeholder={`${t.buy.price} (${list.settings.currency ?? 'PLN'})`}
        aria-label={t.buy.price}
      />
      <input
        className="input narrow"
        inputMode="numeric"
        value={qty}
        onChange={(e) => setQty(e.target.value)}
        placeholder={t.buy.qtyAvailable}
        aria-label={t.buy.qtyAvailable}
      />
      <input className="input" value={url} onChange={(e) => setUrl(e.target.value)} placeholder={t.buy.offerUrl} aria-label={t.buy.offerUrl} />
      <button className="button primary small" disabled={!valid} onClick={save} title={t.buy.saveOffer}>
        ✓
      </button>
      <button className="link-button small" onClick={onCancel}>
        {t.common.cancel}
      </button>
    </div>
  )
}
