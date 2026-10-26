import { useEffect, useState } from 'react'
import {
  api,
  type Basket,
  type BasketProposal,
  type BasketTotals,
  type Comparison,
  type CompareOption,
  type QuoteJob,
  type SellerBasket,
} from '../api/client'
import { copyText } from '../clipboard'
import { formatDateTime, formatMoney as money, t } from '../i18n'
import { openLinks } from '../openLinks'

interface Props {
  deckId: number
  /** Changes when offers or choices change, to refetch. */
  version: number
  currency: string
  /** Choices changed here: the shopping list above reloads. */
  onChanged: () => void
}

/** The chosen offers per seller with progress to free delivery, suggestions to reach it, a proposed
basket and the comparison with CardTrader Zero. */
export function BasketPanel({ deckId, version, currency, onChanged }: Props) {
  const [basket, setBasket] = useState<Basket | null>(null)
  const [proposal, setProposal] = useState<BasketProposal | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [remaining, setRemaining] = useState<string[]>([])

  useEffect(() => {
    api.basket(deckId).then(setBasket, (e: Error) => setError(e.message))
  }, [deckId, version])

  const choose = async (choices: Record<string, number | null>) => {
    setError(null)
    try {
      setBasket(await api.setChoices(deckId, choices))
      setProposal(null)
      onChanged()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const suggest = async () => {
    setError(null)
    try {
      setProposal(await api.basketProposal(deckId))
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const openOffers = async (seller: SellerBasket) => {
    try {
      const rest = await openLinks(seller.cards.map((c) => c.url).filter((u): u is string => !!u))
      if (rest) setRemaining(rest)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const copyList = async (seller: SellerBasket) => {
    await copyText(seller.cards.map((c) => `${c.qty} ${c.name} – ${money(c.price)}`).join('\n') + '\n')
    setNote(t.buy.copied)
  }

  return (
    <div className="basket-panel">
      <h3>{t.buy.basketTitle}</h3>
      {error && <p className="status error">{error}</p>}
      {basket && !basket.sellers.length && <p className="muted small">{t.buy.basketEmpty}</p>}
      <div className="seller-blocks">
        {basket?.sellers.map((s) => (
          <div key={s.seller} className={`seller-block ${s.reached ? 'reached' : ''}`}>
            <div className="seller-head">
              <strong>{s.seller}</strong>
              <span className="small">
                {t.buy.progress(money(s.subtotal), money(s.threshold), currency)} ·{' '}
                {s.reached ? <span className="validation-ok">{t.buy.free}</span> : t.buy.toFree(money(s.missing))}
              </span>
            </div>
            <div className="progress" role="progressbar" aria-valuenow={s.subtotal} aria-valuemax={s.threshold}>
              <div className="progress-fill" style={{ width: `${Math.min(100, s.threshold ? (s.subtotal / s.threshold) * 100 : 100)}%` }} />
            </div>
            <ul className="seller-cards small">
              {s.cards.map((c) => (
                <li key={c.oracle_id}>
                  {c.qty} {c.name} – {money(c.price)}
                  {c.short && <span className="warn-text"> · {t.buy.short}</span>}
                </li>
              ))}
            </ul>
            {s.suggestions.length > 0 && (
              <div className="seller-suggestions small">
                <span className="muted">{t.buy.suggestions}</span>
                <ul>
                  {s.suggestions.map((g) => (
                    <li key={g.oracle_id}>
                      {t.buy.suggestion(
                        g.name,
                        money(g.price),
                        g.diff != null ? `${g.diff >= 0 ? '+' : '−'}${money(Math.abs(g.diff))}` : null,
                        g.current_seller ?? null,
                      )}{' '}
                      <button className="link-button small" onClick={() => choose({ [g.oracle_id]: g.offer_id })}>
                        {t.buy.moveHere}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <div className="actions">
              {s.cards.some((c) => c.url) && (
                <button className="button small" onClick={() => openOffers(s)}>
                  {t.buy.openOffers}
                </button>
              )}
              <button className="button small" onClick={() => copyList(s)}>
                {t.buy.copyList}
              </button>
            </div>
          </div>
        ))}
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
              {url.slice(0, 80)}
            </a>
          ))}
        </div>
      )}

      {basket && basket.unassigned.length > 0 && (
        <p className="small">
          <span className="muted">{t.buy.unassigned}: </span>
          {basket.unassigned
            .map((u) => `${u.name} (${u.offers ? t.buy.offersCount(u.offers) : t.buy.noOffersYet})`)
            .join(', ')}
        </p>
      )}

      {basket && basket.sellers.length > 0 && <TotalsLine totals={basket.summary} currency={currency} />}

      <div className="actions">
        <button className="button" onClick={suggest} title={t.buy.suggestTitle}>
          {t.buy.suggestBasket}
        </button>
        {note && <span className="muted small">{note}</span>}
      </div>

      {proposal && (
        <div className="proposal panel-inset">
          <h4>{t.buy.proposal}</h4>
          {proposal.changes.length === 0 ? (
            <p className="muted small">{t.buy.proposalNone}</p>
          ) : (
            <>
              <p className="small">
                {t.buy.proposalNow}: <TotalsLine totals={proposal.current} currency={currency} inline />
                <br />
                {t.buy.proposalNew}: <TotalsLine totals={proposal.proposed} currency={currency} inline />
              </p>
              <ul className="small">
                {proposal.changes.map((c) => (
                  <li key={c.oracle_id}>
                    {t.buy.proposalChange(c.name, c.from_seller ?? null, c.to_seller)} ({money(c.price)})
                  </li>
                ))}
              </ul>
            </>
          )}
          <div className="actions">
            {proposal.changes.length > 0 && (
              <button className="button primary" onClick={() => choose(proposal.choices)}>
                {t.buy.accept}
              </button>
            )}
            <button className="button" onClick={() => setProposal(null)}>
              {t.buy.discard}
            </button>
          </div>
        </div>
      )}

      <CardTraderCompare deckId={deckId} version={version} currency={currency} />
    </div>
  )
}

function TotalsLine({ totals, currency, inline = false }: { totals: BasketTotals; currency: string; inline?: boolean }) {
  const text = (
    <>
      {t.buy.cards} {money(totals.cards)} · {t.buy.shippingTotal} {money(totals.shipping)}
      {totals.shipping_unknown > 0 && t.buy.shippingUnknown(totals.shipping_unknown)} · {t.buy.parcels} {totals.parcels} ·{' '}
      <strong>
        {t.buy.total} {money(totals.total)} {currency}
      </strong>
    </>
  )
  return inline ? text : <p className="basket-totals">{text}</p>
}

function CardTraderCompare({ deckId, version, currency }: { deckId: number; version: number; currency: string }) {
  const [compare, setCompare] = useState<Comparison | null>(null)
  const [job, setJob] = useState<QuoteJob | null>(null)
  const [connected, setConnected] = useState(false)
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null)

  useEffect(() => {
    api.cardtrader().then((s) => setConnected(s.connected), () => setConnected(false))
    api.cardtraderQuotes(deckId).then(setJob, () => setJob(null))
  }, [deckId])

  const running = !!job?.running
  useEffect(() => {
    if (running) return
    api.basketCompare(deckId).then(setCompare, () => setCompare(null))
  }, [deckId, version, running])

  useEffect(() => {
    if (!running) return
    const timer = window.setInterval(() => {
      api.cardtraderQuotes(deckId).then(setJob, () => undefined)
    }, 700)
    return () => window.clearInterval(timer)
  }, [deckId, running])

  const start = async () => {
    setMessage(null)
    try {
      setJob(await api.startCardtraderQuotes(deckId))
    } catch (e) {
      setMessage({ ok: false, text: (e as Error).message })
    }
  }

  const sendToCart = async (oracleIds: string[]) => {
    setMessage(null)
    try {
      const result = await api.cardtraderCart(deckId, oracleIds)
      const failed = result.failed.length ? ` ${t.buy.cartFailed(result.failed.join(', '))}` : ''
      setMessage({ ok: !result.failed.length, text: t.buy.cartResult(result.added) + failed })
    } catch (e) {
      setMessage({ ok: false, text: (e as Error).message })
    }
  }

  const option = (label: string, value: CompareOption | null | undefined, hint?: string) =>
    value && (
      <li>
        <strong>{label}:</strong>{' '}
        {t.buy.optionLine(money(value.cards), money(value.shipping), money(value.total), currency, value.parcels)}
        {value.shipping_unknown > 0 && t.buy.shippingUnknown(value.shipping_unknown)}
        {!value.complete && <span className="warn-text"> · {t.buy.incomplete}</span>}
        {hint && <div className="muted small">{hint}</div>}
      </li>
    )

  const names = new Map(compare?.cardtrader_cards.map((c) => [c.oracle_id, c.name]))

  return (
    <div className="cardtrader-compare">
      <h3>{t.buy.ctTitle}</h3>
      <p className="muted small">{t.buy.ctIntro}</p>
      <div className="actions">
        {connected ? (
          <button className="button" disabled={running} onClick={start}>
            {running ? t.buy.ctFetching(job?.done ?? 0, job?.total ?? 0) : t.buy.ctFetch}
          </button>
        ) : (
          <span className="muted small">{t.buy.ctNoToken}</span>
        )}
        {compare?.fetched_at && <span className="muted small">{t.buy.ctFetchedAt(formatDateTime(compare.fetched_at))}</span>}
      </div>
      {job?.error && <p className="status error">{job.error}</p>}
      {compare && compare.rate_missing.length > 0 && (
        <p className="warn-text small">{t.buy.ctRateMissing(compare.rate_missing.join(', '))}</p>
      )}
      {compare && (compare.cardtrader || compare.sellers.parcels > 0) && (
        <ul className="compare-options">
          {option(t.buy.optionSellers, compare.sellers)}
          {option(t.buy.optionCardtrader, compare.cardtrader)}
          {option(t.buy.optionMixed, compare.mixed, t.buy.optionMixedHint)}
        </ul>
      )}
      {compare?.cardtrader && compare.not_on_cardtrader.length > 0 && (
        <p className="small">
          <span className="muted">{t.buy.notOnCt} </span>
          {compare.not_on_cardtrader.join(', ')}
        </p>
      )}
      {compare?.mixed && compare.to_cardtrader.length > 0 && (
        <>
          <p className="small">
            <span className="muted">{t.buy.toCardtrader} </span>
            {compare.to_cardtrader.map((id) => names.get(id) ?? id).join(', ')}
          </p>
          <div className="actions">
            <button className="button" onClick={() => sendToCart(compare.to_cardtrader)} title={t.buy.sendToCartTitle}>
              {t.buy.sendToCart}
            </button>
          </div>
        </>
      )}
      {message && <p className={`status ${message.ok ? 'ok' : 'error'} small`}>{message.text}</p>}
    </div>
  )
}
