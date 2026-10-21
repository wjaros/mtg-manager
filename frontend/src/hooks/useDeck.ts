import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type Board, type DeckDetail, type DeckUpdate } from '../api/client'

/** Loads one deck and exposes mutations; every mutation returns the updated deck from the API. */
export function useDeck(deckId: number) {
  const [deck, setDeck] = useState<DeckDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  // Mutations are serialized so rapid clicks apply in order.
  const queue = useRef<Promise<unknown>>(Promise.resolve())

  const [version, setVersion] = useState(0)

  useEffect(() => {
    let cancelled = false
    api.deck(deckId).then(
      (d) => !cancelled && setDeck(d),
      (e: Error) => !cancelled && setError(e.message),
    )
    return () => {
      cancelled = true
    }
  }, [deckId, version])

  const run = useCallback((action: () => Promise<DeckDetail>) => {
    setBusy(true)
    const next = queue.current.then(action).then(
      (d) => {
        setDeck(d)
        setError(null)
      },
      (e: Error) => setError(e.message),
    )
    queue.current = next.finally(() => setBusy(false))
    return next
  }, [])

  return {
    deck,
    error,
    busy,
    clearError: () => setError(null),
    reload: () => setVersion((v) => v + 1),
    update: (body: DeckUpdate) => run(() => api.updateDeck(deckId, body)),
    add: (cardId: string, board: Board = 'main', quantity = 1) =>
      run(() => api.addDeckCard(deckId, cardId, board, quantity)),
    remove: (cardId: string, board: Board = 'main', quantity?: number) =>
      run(() => api.removeDeckCard(deckId, cardId, board, quantity)),
    move: (cardId: string, board: Board, newBoard: Board) =>
      run(() => api.updateDeckCard(deckId, cardId, board, { new_board: newBoard })),
    setCategory: (cardId: string, board: Board, category: string) =>
      run(() => api.updateDeckCard(deckId, cardId, board, { category })),
    swapPrinting: (cardId: string, board: Board, newCardId: string) =>
      run(() => api.updateDeckCard(deckId, cardId, board, { new_card_id: newCardId })),
    saveVersion: (note?: string) =>
      run(async () => {
        await api.saveDeckVersion(deckId, note)
        return api.deck(deckId)
      }),
    restoreVersion: (versionId: number) => run(() => api.restoreDeckVersion(deckId, versionId)),
  }
}

export type DeckActions = ReturnType<typeof useDeck>
