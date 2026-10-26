import { getPref, setPref } from '../prefs'
import { en } from './en'
import { pl, type Messages } from './pl'

export type Lang = 'pl' | 'en'

export const LANGUAGES: Record<Lang, string> = { pl: 'Polski', en: 'English' }

const STORAGE_KEY = 'mtgdm.lang'

function detect(): Lang {
  const saved = getPref(STORAGE_KEY)
  if (saved === 'pl' || saved === 'en') return saved
  return navigator.language.toLowerCase().startsWith('pl') ? 'pl' : 'en'
}

/** Chosen once at startup; changing it reloads the app (see setLang). */
export const lang: Lang = detect()
export const locale = lang === 'pl' ? 'pl-PL' : 'en-US'
export const t: Messages = lang === 'pl' ? pl : en

document.documentElement.lang = lang

export function setLang(next: Lang): void {
  // Reloaded once stored (a reload would cut the write short).
  void setPref(STORAGE_KEY, next).then(() => window.location.reload())
}

export function formatNumber(n: number): string {
  return n.toLocaleString(locale)
}

/** SQLite datetime('now') values are UTC without a zone marker. */
export function formatDateTime(value: string): string {
  const date = new Date(value.includes('T') || value.endsWith('Z') ? value : value.replace(' ', 'T') + 'Z')
  return date.toLocaleString(locale, { dateStyle: 'short', timeStyle: 'short' })
}
