import { useEffect, useState } from 'react'
import { api, type SyncCheck, type SyncStatus } from '../api/client'
import { t } from '../i18n'

const STALE_AFTER_DAYS = 7  // gameplay data changes rarely: refresh weekly
const DISMISS_KEY = 'mtgdm.updateDismissedFor'

interface Props {
  status: SyncStatus
  onRefresh: () => void
}

/** On start: if local card data is older than a week and Scryfall has newer, offer a refresh. */
export function UpdateBanner({ status, onRefresh }: Props) {
  const [check, setCheck] = useState<SyncCheck | null>(null)
  const [dismissed, setDismissed] = useState(false)
  // Captured once: the banner is about data age at startup.
  const [now] = useState(() => Date.now())

  const updatedAt = status.cards_updated_at
  const stale =
    status.card_count > 0 &&
    !!updatedAt &&
    now - new Date(updatedAt).getTime() > STALE_AFTER_DAYS * 24 * 3600 * 1000

  useEffect(() => {
    if (!stale) return
    let cancelled = false
    api.syncCheck().then(
      (c) => !cancelled && setCheck(c),
      () => {}, // offline: just don't show the banner
    )
    return () => {
      cancelled = true
    }
  }, [stale])

  if (!check?.update_available || dismissed || status.progress.running) return null
  try {
    if (localStorage.getItem(DISMISS_KEY) === check.remote_updated_at) return null
  } catch {
    // storage unavailable: show the banner
  }

  const dismiss = () => {
    try {
      localStorage.setItem(DISMISS_KEY, check.remote_updated_at)
    } catch {
      // ignore
    }
    setDismissed(true)
  }

  const days = Math.floor((now - new Date(updatedAt!).getTime()) / (24 * 3600 * 1000))
  return (
    <div className="update-banner" role="status">
      <span>{t.card.staleData(days)}</span>
      <button
        className="button primary"
        onClick={() => {
          api.syncStart().catch(() => {})
          setDismissed(true)
          onRefresh()
        }}
      >
        {t.card.refreshNow}
      </button>
      <button className="link-button" onClick={dismiss}>
        {t.card.later}
      </button>
    </div>
  )
}
