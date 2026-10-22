import { useEffect, useState } from 'react'
import { api, type CloudBackupStatus } from '../api/client'
import { locale, t } from '../i18n'

/** Settings › Backup: automatic backups into a folder that iCloud Drive / OneDrive / Dropbox syncs. */
export function CloudBackupSettings() {
  const [status, setStatus] = useState<CloudBackupStatus | null>(null)
  const [folder, setFolder] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.cloudBackup().then(
      (s) => {
        setStatus(s)
        setFolder(s.folder ?? s.suggestions?.[0] ?? '')
      },
      (e: Error) => setError(e.message),
    )
  }, [])

  const run = async (action: () => Promise<CloudBackupStatus>) => {
    setBusy(true)
    setError(null)
    try {
      setStatus(await action())
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  if (!status) return error ? <p className="status error">{error}</p> : null
  const written = status.last_written_at ? new Date(status.last_written_at).toLocaleString(locale) : null

  return (
    <div className="cloud-backup">
      <h3>{t.cloud.title}</h3>
      <p className="muted small">{t.cloud.intro}</p>
      <div className="cloud-folder">
        <input
          className="input"
          value={folder}
          onChange={(e) => setFolder(e.target.value)}
          placeholder={t.cloud.folderPlaceholder}
          aria-label={t.cloud.folder}
          list="cloud-folders"
        />
        <datalist id="cloud-folders">
          {(status.suggestions ?? []).map((s) => (
            <option key={s} value={s} />
          ))}
        </datalist>
        {status.enabled ? (
          <>
            {folder !== status.folder && (
              <button className="button" disabled={busy || !folder.trim()} onClick={() => run(() => api.saveCloudBackup(folder, true))}>
                {t.cloud.change}
              </button>
            )}
            <button className="button" disabled={busy} onClick={() => run(() => api.cloudBackupWrite())}>
              {t.cloud.writeNow}
            </button>
            <button className="link-button" disabled={busy} onClick={() => run(() => api.saveCloudBackup(status.folder, false))}>
              {t.cloud.turnOff}
            </button>
          </>
        ) : (
          <button className="button primary" disabled={busy || !folder.trim()} onClick={() => run(() => api.saveCloudBackup(folder, true))}>
            {t.cloud.turnOn}
          </button>
        )}
      </div>
      {(status.suggestions ?? []).length > 0 && !status.enabled && (
        <p className="muted small">
          {t.cloud.found}{' '}
          {(status.suggestions ?? []).map((s, i) => (
            <span key={s}>
              {i > 0 && ', '}
              <button className="link-button small" onClick={() => setFolder(s)}>
                {s}
              </button>
            </span>
          ))}
        </p>
      )}
      {status.enabled && (
        <p className={`small ${status.error ? 'status error' : 'muted'}`}>
          {status.error
            ? t.cloud.folderError(status.error)
            : written
              ? t.cloud.lastWritten(written, status.machine_name)
              : t.cloud.notYet}
        </p>
      )}
      {status.newer && <p className="status warn small">{t.cloud.newerHint(status.newer.machine_name)}</p>}
      {error && <p className="status error small">{error}</p>}
    </div>
  )
}
