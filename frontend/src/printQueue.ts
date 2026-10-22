import { useSyncExternalStore } from 'react'
import type { CardSummary } from './api/client'

type Card = Pick<CardSummary, 'id' | 'name' | 'image_faces' | 'set_code' | 'collector_number'>

/** Cards picked for proxy printing in the collection (one entry per printing), shared by the
collection grid, its context menu and the print dialog. Kept in this browser between visits. */
export interface QueuedCard {
  card_id: string
  name: string
  faces: number
  qty: number
  printing?: string // "DOM #31"
}

const STORAGE_KEY = 'mtgdm.printQueue'
const listeners = new Set<() => void>()
let queue: QueuedCard[] = load()

function load(): QueuedCard[] {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]')
    return Array.isArray(saved) ? saved : []
  } catch {
    return []
  }
}

function set(next: QueuedCard[]): void {
  queue = next
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
  } catch {
    // private mode: the list just isn't remembered
  }
  for (const listener of listeners) listener()
}

export const printQueue = {
  items: () => queue,
  has: (cardId: string) => queue.some((q) => q.card_id === cardId),
  add: (card: Card, qty = 1) => {
    const same = queue.find((q) => q.card_id === card.id)
    set(
      same
        ? queue.map((q) => (q === same ? { ...q, qty: Math.min(99, q.qty + qty) } : q))
        : [
            ...queue,
            {
              card_id: card.id,
              name: card.name,
              faces: Math.max(1, card.image_faces),
              qty,
              printing: card.set_code ? `${card.set_code.toUpperCase()} #${card.collector_number}` : undefined,
            },
          ],
    )
  },
  remove: (cardId: string) => set(queue.filter((q) => q.card_id !== cardId)),
  toggle: (card: Card) =>
    printQueue.has(card.id) ? printQueue.remove(card.id) : printQueue.add(card),
  replace: (next: QueuedCard[]) => set(next),
  clear: () => set([]),
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function usePrintQueue(): QueuedCard[] {
  return useSyncExternalStore(subscribe, () => queue)
}
