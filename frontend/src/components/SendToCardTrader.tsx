import { useEffect, useState } from 'react'
import { api, type CardTraderWishlistRequest, type WishlistResult } from '../api/client'
import { t } from '../i18n'
import { wants } from '../wants'

/** "Send to CardTrader": the shopping list (a deck's missing cards put on it first) as the one private
CardTrader wishlist, any printing. CardTrader silently drops cards it doesn't recognize, so those are
listed. Without a token: a link to Settings. */
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
      wants.refresh() // a deck's missing cards went on the shopping list
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
          {(result.added ?? 0) > 0 && ` ${t.cardtrader.added(result.added ?? 0)}`}
          {result.language && !result.language_ignored && ` ${t.cardtrader.inLanguage(t.cardtrader.languages[result.language] ?? result.language)}`}
          {result.language_ignored && <span className="status error"> {t.cardtrader.languageIgnored}</span>}
          {result.not_found.length > 0 && (
            <span className="status error"> {t.cardtrader.notFound(result.not_found.join(', '))}</span>
          )}
        </span>
      )}
      {error && <span className="status error small">{error}</span>}
    </>
  )
}
