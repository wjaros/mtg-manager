import { t } from './i18n'

/** Copy text; falls back to execCommand where the async Clipboard API is unavailable (some webviews). */
export async function copyText(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text)
    return
  } catch {
    // fall through to the legacy path
  }
  const area = document.createElement('textarea')
  area.value = text
  area.setAttribute('readonly', '')
  area.style.position = 'fixed'
  area.style.opacity = '0'
  document.body.appendChild(area)
  area.select()
  const ok = document.execCommand('copy')
  area.remove()
  if (!ok) throw new Error(t.common.clipboardUnavailable)
}

/** Copy from a menu, which has nothing on screen to show the result: only a failure is reported. */
export function copyFromMenu(text: string): void {
  copyText(text).catch((e: Error) => window.alert(e.message))
}
