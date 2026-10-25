import { useEffect, useState } from 'react'
import { api, type CardTraderWishlistRequest, type WishlistResult } from '../api/client'
import { t } from '../i18n'

/** "Send to CardTrader": the cards to buy as a private wishlist there (any printing). CardTrader
silently drops cards it doesn't recognize, so those are listed. Without a token: a link to Settings. */
export function SendToCardTrader({ request }: { request: CardTraderWishlistRequest }) {
  const [connected, setConnected] = useState<boolean | null>(null)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<WishlistResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.cardtrader().then(
      (s) => setConnected(s.connected),
      () => setConnected(false),
    )
  }, [])

  if (connected === false) {
    return (
      <a className="button" href="#/settings" title={t.cardtrader.needsToken}>
        {t.cardtrader.send}
      </a>
    )
  }

  const send = async () => {
    setBusy(true)
    setResult(null)
    setError(null)
    try {
      setResult(await api.cardtraderWishlist(request))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <button className="button" disabled={busy || connected === null} onClick={send} title={t.cardtrader.sendTitle}>
        {busy ? t.cardtrader.sending : t.cardtrader.send}
      </button>
      {result && (
        <span className="small">
          {t.cardtrader.sent(result.name, result.copies)}
          {result.not_found.length > 0 && (
            <span className="status error"> {t.cardtrader.notFound(result.not_found.join(', '))}</span>
          )}
        </span>
      )}
      {error && <span className="status error small">{error}</span>}
    </>
  )
}
