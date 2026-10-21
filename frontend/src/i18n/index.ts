import { en } from './en'
import { pl, type Messages } from './pl'

export type Lang = 'pl' | 'en'

export const LANGUAGES: Record<Lang, string> = { pl: 'Polski', en: 'English' }

const STORAGE_KEY = 'mtgdm.lang'

function detect(): Lang {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved === 'pl' || saved === 'en') return saved
  } catch {
    // storage unavailable: fall back to the system language
  }
  return navigator.language.toLowerCase().startsWith('pl') ? 'pl' : 'en'
}

/** Chosen once at startup; changing it reloads the app (see setLang). */
export const lang: Lang = detect()
export const locale = lang === 'pl' ? 'pl-PL' : 'en-US'
export const t: Messages = lang === 'pl' ? pl : en

document.documentElement.lang = lang

export function setLang(next: Lang): void {
  try {
    localStorage.setItem(STORAGE_KEY, next)
  } catch {
    // not persisted: the reload falls back to the system language
  }
  window.location.reload()
}

export function formatNumber(n: number): string {
  return n.toLocaleString(locale)
}

/** SQLite datetime('now') values are UTC without a zone marker. */
export function formatDateTime(value: string): string {
  const date = new Date(value.includes('T') || value.endsWith('Z') ? value : value.replace(' ', 'T') + 'Z')
  return date.toLocaleString(locale, { dateStyle: 'short', timeStyle: 'short' })
}
