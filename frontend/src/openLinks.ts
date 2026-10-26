import { api } from './api/client'
import { t } from './i18n'
import { canOpenUrls } from './prefs'

const CONFIRM_ABOVE = 10

/** Open several links: the window app opens them all in the system browser (one tab each, the backend
paces them); a browser blocks more than one pop-up per click, so the first opens and the rest come back
to be shown as links. Returns the links still to open, or null when cancelled. */
export async function openLinks(urls: string[]): Promise<string[] | null> {
  if (!urls.length) return []
  if (urls.length > CONFIRM_ABOVE && !window.confirm(t.buy.confirmMany(urls.length))) return null
  if (canOpenUrls()) {
    await api.openUrls(urls)
    return []
  }
  window.open(urls[0], '_blank', 'noopener')
  return urls.slice(1)
}
