import { useEffect, useState } from 'react'
import { api, type UpdateInfo } from '../api/client'
import { locale, t } from '../i18n'
import { SimpleMarkdown } from './SimpleMarkdown'

/** On start: a newer version is out. What's new, download it, later, or skip that version. */
export function AppUpdateBanner() {
  const [info, setInfo] = useState<UpdateInfo | null>(null)
  const [hidden, setHidden] = useState(false)
  const [showNotes, setShowNotes] = useState(false)

  useEffect(() => {
    api.updates().then(setInfo, () => setInfo(null))
  }, [])

  if (!info?.newer || info.skipped || hidden) return showNotes && info ? <ChangesDialog info={info} onClose={() => setShowNotes(false)} /> : null

  return (
    <div className="update-banner app-update-banner" role="status">
      <span>{t.updates.available(info.latest ?? '', info.current)}</span>
      <button className="button" onClick={() => setShowNotes(true)}>
        {t.updates.whatsNew}
      </button>
      <a className="button primary" href={info.download?.url ?? info.url ?? '#'} target={info.download ? undefined : '_blank'} rel="noreferrer">
        {info.download ? t.updates.download : t.updates.openPage}
      </a>
      <button className="link-button" onClick={() => setHidden(true)}>
        {t.updates.later}
      </button>
      <button
        className="link-button"
        onClick={() => api.skipUpdate(info.latest ?? '').then(setInfo, () => setHidden(true))}
        title={t.updates.skipTitle}
      >
        {t.updates.skip}
      </button>
      {showNotes && <ChangesDialog info={info} onClose={() => setShowNotes(false)} />}
    </div>
  )
}

export function ChangesDialog({ info, onClose }: { info: UpdateInfo; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="modal-backdrop centered" onClick={onClose}>
      <div className="dialog changes-dialog" onClick={(e) => e.stopPropagation()} role="dialog" aria-label={t.updates.whatsNew}>
        <div className="dialog-header">
          <h2>{t.updates.whatsNewIn(info.latest ?? '')}</h2>
          <button className="close-button static" onClick={onClose} aria-label={t.common.close}>
            ×
          </button>
        </div>
        {info.releases.map((r) => (
          <section key={r.version} className="release-notes">
            <h3>
              <a href={r.url} target="_blank" rel="noreferrer">
                {r.version}
              </a>
              {r.published_at && <span className="muted small"> · {new Date(r.published_at).toLocaleDateString(locale)}</span>}
            </h3>
            {r.notes ? <SimpleMarkdown text={r.notes} /> : <p className="muted small">{t.updates.noNotes}</p>}
          </section>
        ))}
        {info.download && (
          <div className="actions">
            <a className="button primary" href={info.download.url}>
              {t.updates.downloadFile(info.download.name, Math.round(info.download.size / 1e6))}
            </a>
          </div>
        )}
      </div>
    </div>
  )
}

/** Settings › About: the version, the check on start, check now. */
export function UpdateSettings() {
  const [info, setInfo] = useState<UpdateInfo | null>(null)
  const [busy, setBusy] = useState(false)
  const [showNotes, setShowNotes] = useState(false)

  useEffect(() => {
    api.updates().then(setInfo, () => setInfo(null))
  }, [])

  const run = async (action: () => Promise<UpdateInfo>) => {
    setBusy(true)
    try {
      setInfo(await action())
    } finally {
      setBusy(false)
    }
  }

  if (!info) return null
  return (
    <div className="update-settings">
      <label className="checkbox small">
        <input type="checkbox" checked={info.enabled} onChange={(e) => run(() => api.setUpdateChecks(e.target.checked))} />
        {t.updates.checkOnStart}
      </label>
      <button className="button" disabled={busy} onClick={() => run(() => api.updates(true))}>
        {busy ? t.updates.checking : t.updates.checkNow}
      </button>
      <span className="small">
        {info.error
          ? <span className="error-text">{t.updates.failed}</span>
          : info.newer
            ? <>
                {t.updates.available(info.latest ?? '', info.current)}{' '}
                <button className="link-button small" onClick={() => setShowNotes(true)}>{t.updates.whatsNew}</button>
              </>
            : info.checked_at
              ? <span className="muted">{t.updates.upToDate(info.current)}</span>
              : null}
      </span>
      {showNotes && <ChangesDialog info={info} onClose={() => setShowNotes(false)} />}
    </div>
  )
}
