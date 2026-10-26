import { useSyncExternalStore } from 'react'
import type { components } from './api/schema'

type Prefs = components['schemas']['Prefs']

/** The UI's preferences (deckbuilder layout, card sizes, grouping, language…), kept by the backend:
the window app's web view forgets browser storage on restart. Loaded once before the app renders
(the language is picked when its modules load), so reads are synchronous; writes go to the backend
in the background, one at a time per key. Without the backend, browser storage stands in.
No `api/client` here: it reads the language, which isn't known yet. */

let values: Record<string, string> = {}
let backend = false
const writes = new Map<string, Promise<void>>()

/** Size of the whole interface; the window app zooms its web view (a browser has its own zoom). */
export const UI_SCALES = [0.8, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2]
let scale = { scale: 1, native: false }
// The window app opens several links at once in the system browser (the backend does it).
let openUrls = false
const scaleListeners = new Set<() => void>()

export async function loadPrefs(): Promise<void> {
  try {
    const resp = await fetch('/api/prefs', { headers: { Accept: 'application/json' } })
    if (!resp.ok) throw new Error(resp.statusText)
    const prefs = (await resp.json()) as Prefs
    values = prefs.values
    scale = { scale: prefs.scale, native: prefs.native_zoom }
    openUrls = prefs.open_urls ?? false
    backend = true
    if (!Object.keys(values).length) importBrowserStorage()
  } catch {
    // no backend: browser storage only
  }
}

/** Preferences this browser kept before they moved to the backend come along, once. */
function importBrowserStorage(): void {
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i)
      if (key?.startsWith('mtgdm.')) void setPref(key, localStorage.getItem(key))
    }
  } catch {
    // storage unavailable: nothing to bring along
  }
}

/** "Open selected" can open every link at once (the window app); a browser opens one per click. */
export function canOpenUrls(): boolean {
  return openUrls
}

export function getPref(key: string): string | null {
  if (backend) return values[key] ?? null
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

/** Store a preference (null removes it); resolves once the backend has it. */
export function setPref(key: string, value: string | null): Promise<void> {
  if (!backend) {
    try {
      if (value === null) localStorage.removeItem(key)
      else localStorage.setItem(key, value)
    } catch {
      // private mode: just not remembered
    }
    return Promise.resolve()
  }
  if (value === null) delete values[key]
  else values[key] = value
  // After the previous write of this key, with the value current by then: the last one wins.
  const write = (writes.get(key) ?? Promise.resolve()).then(() =>
    fetch('/api/prefs', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key, value: values[key] ?? null }),
    }).then(
      () => undefined,
      () => undefined, // not remembered; the app works on
    ),
  )
  writes.set(key, write)
  return write
}

export async function setUiScale(next: number): Promise<void> {
  const resp = await fetch('/api/prefs/scale', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ scale: next }),
  })
  if (!resp.ok) return
  const prefs = (await resp.json()) as Prefs
  scale = { scale: prefs.scale, native: prefs.native_zoom }
  for (const listener of scaleListeners) listener()
}

/** One step larger (+1) or smaller (−1) than the current scale. */
export function stepUiScale(step: 1 | -1): void {
  const current = scale.scale
  const next = step > 0 ? UI_SCALES.find((s) => s > current + 0.001) : [...UI_SCALES].reverse().find((s) => s < current - 0.001)
  if (next !== undefined) void setUiScale(next)
}

export function useUiScale(): { scale: number; native: boolean } {
  return useSyncExternalStore(
    (listener) => {
      scaleListeners.add(listener)
      return () => scaleListeners.delete(listener)
    },
    () => scale,
  )
}
