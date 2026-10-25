import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type CardQuery, type CardSummary } from '../api/client'

export const PAGE_SIZE = 120

interface State {
  key: string // query the pages belong to; results for an older query are ignored
  total: number | null
  pages: Map<number, CardSummary[]>
  error: string | null
  typeHint: string | null // the query with type words as type filters ("desert" -> "t:desert")
}

/**
 * Paged card search for a virtualized grid: pages are fetched on demand with ensureRange()
 * and the whole cache resets whenever the query changes.
 */
export function useCardPages(query: CardQuery, version = 0) {
  // version: bump to refetch the same query after data changed (e.g. the collection).
  const key = JSON.stringify([query, version])
  const [state, setState] = useState<State>({ key, total: null, pages: new Map(), error: null, typeHint: null })
  const inflight = useRef(new Map<number, AbortController>())
  const generation = useRef(0)

  const loadPage = useCallback(
    (page: number) => {
      if (inflight.current.has(page)) return
      const controller = new AbortController()
      inflight.current.set(page, controller)
      const gen = generation.current
      api
        .searchCards((JSON.parse(key) as [CardQuery])[0], page + 1, PAGE_SIZE, controller.signal)
        .then((result) => {
          if (gen !== generation.current) return
          setState((prev) => {
            const pages = new Map(prev.key === key ? prev.pages : [])
            pages.set(page, result.items)
            const typeHint = page === 0 ? (result.type_hint ?? null) : prev.key === key ? prev.typeHint : null
            return { key, total: result.total, pages, error: null, typeHint }
          })
        })
        .catch((err: Error) => {
          if (gen !== generation.current || err.name === 'AbortError') return
          inflight.current.delete(page)
          setState((prev) =>
            prev.key === key
              ? { ...prev, error: err.message }
              : { key, total: null, pages: new Map(), error: err.message, typeHint: null },
          )
        })
    },
    [key],
  )

  useEffect(() => {
    generation.current += 1
    inflight.current.forEach((c) => c.abort())
    inflight.current = new Map()
    loadPage(0)
  }, [key, loadPage])

  const ensureRange = useCallback(
    (firstIndex: number, lastIndex: number) => {
      for (let page = Math.floor(firstIndex / PAGE_SIZE); page <= Math.floor(lastIndex / PAGE_SIZE); page++) {
        loadPage(page)
      }
    },
    [loadPage],
  )

  const current = state.key === key ? state : null
  const pages = current?.pages
  const cardAt = useCallback(
    (index: number): CardSummary | undefined => pages?.get(Math.floor(index / PAGE_SIZE))?.[index % PAGE_SIZE],
    [pages],
  )

  return { total: current?.total ?? null, error: current?.error ?? null, typeHint: current?.typeHint ?? null, cardAt, ensureRange }
}
