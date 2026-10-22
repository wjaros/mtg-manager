import { useEffect, useState } from 'react'
import { api, type CardUsage } from '../api/client'
import { t } from '../i18n'

// Usage per card and deck, refreshed when the deck changes (key includes the deck revision).
const cache = new Map<string, CardUsage>()

interface Props {
  cardId: string
  deckId: number
  /** Changes whenever the deck's contents change. */
  revision: string
  paper: boolean
}

/** Under the hover preview: copies in this deck, where the owned copies are, other decks using it. */
export function CardUsageInfo({ cardId, deckId, revision, paper }: Props) {
  const key = `${deckId}:${cardId}:${revision}`
  const [loaded, setLoaded] = useState<{ key: string; usage: CardUsage } | null>(null)
  const usage = cache.get(key) ?? (loaded?.key === key ? loaded.usage : null)

  useEffect(() => {
    if (cache.has(key)) return
    let cancelled = false
    // Short delay: sweeping the mouse over the grid should not fire a request per card.
    const timer = setTimeout(() => {
      api.cardUsage(cardId, deckId).then(
        (u) => {
          if (cache.size > 500) cache.clear()
          cache.set(key, u)
          if (!cancelled) setLoaded({ key, usage: u })
        },
        () => {},
      )
    }, 120)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [key, cardId, deckId])

  if (!usage) return <div className="usage-info muted small">…</div>
  return (
    <div className="usage-info small">
      <div className={usage.in_deck ? 'usage-in-deck' : 'muted'}>
        {usage.in_deck ? t.panels.inThisDeck(usage.in_deck) : t.panels.notInThisDeck}
      </div>
      {paper && (
        <div>
          {usage.owned === 0 && !usage.proxies ? (
            <span className="muted">{t.panels.notOwned}</span>
          ) : (
            <>
              {t.panels.owned(usage.owned)}
              {usage.free !== usage.owned && <span className="muted">{t.panels.free(usage.free)}</span>}
              <ul>
                {usage.locations.map((l) => (
                  <li
                    key={`${l.location_id ?? 'none'}-${l.kind}`}
                    className={l.deck_id !== null && l.deck_id !== deckId && l.kind === 'real' ? 'usage-taken' : ''}
                  >
                    {l.quantity}× {l.kind === 'proxy' && <span className="proxy-chip">PROXY</span>}{' '}
                    {l.deck_id !== null ? t.panels.deckBox(l.deck_name) : (l.name ?? t.common.noLocation)}
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
      {usage.decks.length > 0 && (
        <div className="muted">
          {t.panels.alsoIn(usage.decks.map((d) => `${d.name}${d.quantity > 1 ? ` (${d.quantity})` : ''}`).join(', '))}
        </div>
      )}
    </div>
  )
}
