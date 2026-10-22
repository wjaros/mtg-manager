import { useState } from 'react'

export const ZOOM_LEVELS = [0.6, 0.75, 0.9, 1, 1.15, 1.3, 1.5, 1.75, 2]

/** Card size of one view (1 = default), remembered per browser under `key`. */
export function useZoom(key: string): [number, (zoom: number) => void] {
  const storageKey = `mtgdm.zoom.${key}`
  const [zoom, setZoom] = useState(() => {
    try {
      const saved = Number(localStorage.getItem(storageKey))
      return ZOOM_LEVELS.includes(saved) ? saved : 1
    } catch {
      return 1
    }
  })
  const update = (next: number) => {
    setZoom(next)
    try {
      localStorage.setItem(storageKey, String(next))
    } catch {
      // private mode: the zoom just isn't remembered
    }
  }
  return [zoom, update]
}
