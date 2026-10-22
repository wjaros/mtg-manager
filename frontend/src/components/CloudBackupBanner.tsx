import { useEffect, useState } from 'react'
import { api, type CloudBackupStatus } from '../api/client'
import { locale, t } from '../i18n'

/** On start: another computer wrote newer data to the backup folder. Load it (this computer's
data is kept in the folder's history) or keep this computer's. */
export function CloudBackupBanner() {
  const [status, setStatus] = useState<CloudBackupStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.cloudBackup().then(setStatus, () => setStatus(null))
  }, [])

  const newer = status?.newer
  if (!newer) return null

  const load = async () => {
    setBusy(true)
    setError(null)
    try {
      await api.cloudBackupLoad()
      window.location.reload() // every view shows the loaded data
    } catch (e) {
      setError((e as Error).message)
      setBusy(false)
    }
  }
  const keep = () => {
    api.cloudBackupDismiss().catch(() => {})
    setStatus(null)
  }

  return (
    <div className="update-banner cloud-banner" role="status">
      <span>
        {t.cloud.newer(newer.machine_name, new Date(newer.written_at).toLocaleString(locale), newer.decks, newer.collection_items)}
      </span>
      <button className="button primary" onClick={load} disabled={busy}>
        {t.cloud.load}
      </button>
      <button className="link-button" onClick={keep} disabled={busy} title={t.cloud.keepTitle}>
        {t.cloud.keep}
      </button>
      {error && <span className="error-text">{error}</span>}
    </div>
  )
}
