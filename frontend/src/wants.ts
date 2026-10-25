import { useSyncExternalStore } from 'react'
import { api, type WantList } from './api/client'
import { t } from './i18n'

/** The shopping list's size (copies to buy) for the Collection tab, and a short notice after a card
is put on the list from a context menu. The list itself lives in the backend. */
interface State {
  copies: number | null
  notice: string | null
}

const listeners = new Set<() => void>()
let state: State = { copies: null, notice: null }
let noticeTimer: ReturnType<typeof setTimeout> | undefined

function set(next: Partial<State>): void {
  state = { ...state, ...next }
  for (const listener of listeners) listener()
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  if (state.copies === null) wants.refresh()
  return () => listeners.delete(listener)
}

export const wants = {
  /** After the list changed elsewhere (its own view, a deck's missing cards). */
  update: (list: WantList) => set({ copies: list.copies }),
  refresh: () => api.wants().then(wants.update, () => {}),
  add: (card: { id: string; name: string }) =>
    api.addWant(card.id).then(
      (list) => {
        wants.update(list)
        const entry = list.entries.find((e) => e.name === card.name)
        wants.notify(t.wants.added(card.name, entry?.quantity ?? 1))
      },
      (e: Error) => wants.notify(t.common.error(e.message)),
    ),
  notify: (notice: string) => {
    clearTimeout(noticeTimer)
    set({ notice })
    noticeTimer = setTimeout(() => set({ notice: null }), 3500)
  },
}

export function useWants(): State {
  return useSyncExternalStore(subscribe, () => state)
}
