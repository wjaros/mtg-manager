import { useSyncExternalStore } from 'react'
import { getPref, setPref } from './prefs'

/** Light or dark: the system's preference (followed live), or one chosen in Settings → Appearance.
index.html sets the system's before the first paint; this applies the stored choice once prefs load. */
export type ThemeChoice = 'system' | 'light' | 'dark'
export const THEME_CHOICES: readonly ThemeChoice[] = ['system', 'light', 'dark']

const STORAGE_KEY = 'mtgdm.theme'
const systemLight = window.matchMedia('(prefers-color-scheme: light)')
const listeners = new Set<() => void>()

function choice(): ThemeChoice {
  return THEME_CHOICES.find((c) => c === getPref(STORAGE_KEY)) ?? 'system'
}

export function applyTheme(): void {
  const chosen = choice()
  document.documentElement.dataset.theme = chosen === 'system' ? (systemLight.matches ? 'light' : 'dark') : chosen
}

systemLight.addEventListener('change', applyTheme)

export function setTheme(next: ThemeChoice): void {
  void setPref(STORAGE_KEY, next)
  applyTheme()
  for (const listener of listeners) listener()
}

export function useTheme(): ThemeChoice {
  return useSyncExternalStore((listener) => {
    listeners.add(listener)
    return () => listeners.delete(listener)
  }, choice)
}
