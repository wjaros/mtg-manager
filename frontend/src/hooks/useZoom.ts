import { useState } from 'react'
import { getPref, setPref } from '../prefs'

export const ZOOM_LEVELS = [0.6, 0.75, 0.9, 1, 1.15, 1.3, 1.5, 1.75, 2]

/** Card size of one view (1 = default), remembered under `key`. */
export function useZoom(key: string): [number, (zoom: number) => void] {
  const storageKey = `mtgdm.zoom.${key}`
  const [zoom, setZoom] = useState(() => {
    const saved = Number(getPref(storageKey))
    return ZOOM_LEVELS.includes(saved) ? saved : 1
  })
  const update = (next: number) => {
    setZoom(next)
    void setPref(storageKey, String(next))
  }
  return [zoom, update]
}
