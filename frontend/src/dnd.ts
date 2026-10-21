/** Drag and drop of cards between the deckbuilder pool and the deck. */
import type { DragEvent } from 'react'

export const CARD_MIME = 'application/x-mtgdm-card'

export interface CardDrag {
  cardId: string
  from: 'pool' | 'deck'
  board?: string
  // Pool drags carry what the singleton check needs.
  name?: string
  typeLine?: string | null
}

export function setCardDrag(event: DragEvent, drag: CardDrag): void {
  event.dataTransfer.setData(CARD_MIME, JSON.stringify(drag))
  event.dataTransfer.effectAllowed = drag.from === 'pool' ? 'copy' : 'move'
}

export function getCardDrag(event: DragEvent): CardDrag | null {
  const raw = event.dataTransfer.getData(CARD_MIME)
  return raw ? (JSON.parse(raw) as CardDrag) : null
}

export function isCardDrag(event: DragEvent): boolean {
  return event.dataTransfer.types.includes(CARD_MIME)
}
