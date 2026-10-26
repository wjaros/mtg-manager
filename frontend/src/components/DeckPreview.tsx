import { useEffect, useState } from 'react'
import { api, type CardDetail, type DeckCard, type Holding } from '../api/client'
import { BOARD_SECTIONS, holdState, holdTitle } from '../decks'
import { locale, t } from '../i18n'
import { CardImage } from './CardImage'

// Prices of the cards shown so far (they change only with a data sync).
const prices = new Map<string, Pick<CardDetail, 'prices' | 'prices_updated_at'>>()

interface Props {
  entry: DeckCard
  holding: Holding | undefined
  onDetails: (entry: DeckCard) => void
}

/** The hovered deck card, large, in a panel beside the deck's cards (like Moxfield), instead of an
enlarged copy at the cursor; with its printing, copies, state in the collection and price.
Keyed by the card id, so a new card starts on its front face. */
export function DeckPreview({ entry, holding, onDetails }: Props) {
  const { card } = entry
  const [face, setFace] = useState(0)
  const [price, setPrice] = useState(() => prices.get(card.id) ?? null)
  useEffect(() => {
    if (prices.has(card.id)) return
    let cancelled = false
    api.card(card.id).then(
      (detail) => {
        prices.set(card.id, detail)
        if (!cancelled) setPrice(detail)
      },
      () => undefined, // no price shown
    )
    return () => {
      cancelled = true
    }
  }, [card.id])

  const hold = holdState(holding)
  const part = BOARD_SECTIONS.find((s) => s.board === entry.board)?.label ?? entry.board
  const eur = price?.prices.eur
  const usd = price?.prices.usd
  return (
    <aside className="deck-preview" aria-label={card.name}>
      <div className="deck-preview-image">
        <CardImage key={`${card.id}-${face}`} cardId={card.id} name={card.name} face={face} hasImage={card.image_faces > 0} />
        {card.image_faces > 1 && (
          <button
            className="deck-preview-flip"
            onClick={() => setFace((face + 1) % card.image_faces)}
            title={t.deckView.flip}
            aria-label={t.deckView.flip}
          >
            ⟲
          </button>
        )}
      </div>
      <div className="deck-preview-name">{card.printed_name ?? card.name}</div>
      <div className="muted small">{card.type_line}</div>
      <div className="muted small">
        {card.set_name} · #{card.collector_number}
      </div>
      <div className="small">
        {t.deckView.copiesIn(entry.quantity, part)}
        {entry.category && <span className="category-tag">{entry.category}</span>}
      </div>
      {hold && <div className={`deck-preview-hold small ${hold.kind}`}>{holdTitle(hold)}</div>}
      {(eur || usd) && (
        <div className="small">
          {[eur && `€${eur}`, usd && `$${usd}`].filter(Boolean).join(' · ')}
          {price?.prices_updated_at && (
            <span className="muted">{t.panels.pricesAsOf(new Date(price.prices_updated_at).toLocaleDateString(locale))}</span>
          )}
        </div>
      )}
      <button className="link-button small deck-preview-details" onClick={() => onDetails(entry)}>
        {t.builder.details}
      </button>
    </aside>
  )
}
