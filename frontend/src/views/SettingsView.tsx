import { useEffect, useState } from 'react'
import { api, type Health, type SyncCheck, type SyncProgress, type SyncStatus } from '../api/client'
import { CloudBackupSettings } from '../components/CloudBackupSettings'
import { PrintingPanel } from '../components/PrintingPanel'
import { formatNumber, lang, LANGUAGES, locale, setLang, t, type Lang } from '../i18n'

const STAGE_LABEL: Record<string, string> = {
  sets: t.settings.stageSets,
  set_icons: t.settings.stageSetIcons,
  download: t.settings.stageDownload,
  import: t.settings.stageImport,
  precons: t.settings.stagePrecons,
  tags: t.settings.stageTags,
}

interface Props {
  status: SyncStatus | null
  onStatusChange: () => void
}

function formatDate(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleString(locale, { dateStyle: 'medium', timeStyle: 'short' }) : '—'
}

function formatBytes(bytes: number): string {
  return bytes > 1e9 ? `${(bytes / 1e9).toFixed(2)} GB` : `${Math.round(bytes / 1e6)} MB`
}

export function SettingsView({ status, onStatusChange }: Props) {
  const [health, setHealth] = useState<Health | null>(null)
  const [progress, setProgress] = useState<SyncProgress | null>(status?.progress ?? null)
  const [check, setCheck] = useState<SyncCheck | null>(null)
  const [checkError, setCheckError] = useState<string | null>(null)
  const [checking, setChecking] = useState(false)
  const [startError, setStartError] = useState<string | null>(null)

  useEffect(() => {
    api.health().then(setHealth, () => setHealth(null))
  }, [])

  const running = progress?.running ?? status?.progress.running ?? false

  // Follow a running sync over server-sent events, then refresh the data summary.
  useEffect(() => {
    if (!running) return
    const source = new EventSource('/api/sync/events')
    source.onmessage = (event) => {
      const next = JSON.parse(event.data) as SyncProgress
      setProgress(next)
      if (!next.running) {
        source.close()
        setCheck(null)
        onStatusChange()
      }
    }
    source.onerror = () => {
      source.close()
      onStatusChange()
    }
    return () => source.close()
  }, [running, onStatusChange])

  const start = async (force: boolean) => {
    setStartError(null)
    try {
      setProgress(await api.syncStart(force))
    } catch (e) {
      setStartError((e as Error).message)
    }
  }

  const runCheck = async () => {
    setChecking(true)
    setCheckError(null)
    try {
      setCheck(await api.syncCheck())
    } catch (e) {
      setCheckError((e as Error).message)
    } finally {
      setChecking(false)
    }
  }

  const hasData = (status?.card_count ?? 0) > 0
  const last = progress && !progress.running ? progress : null

  return (
    <div className="view settings">
      <h1>{t.settings.title}</h1>

      <section className="panel">
        <h2>{t.settings.languageTitle}</h2>
        <div className="actions">
          <select className="select" value={lang} onChange={(e) => setLang(e.target.value as Lang)} aria-label={t.settings.language}>
            {(Object.keys(LANGUAGES) as Lang[]).map((l) => (
              <option key={l} value={l}>
                {LANGUAGES[l]}
              </option>
            ))}
          </select>
          <span className="muted small">{t.settings.languageHint}</span>
        </div>
      </section>

      <section className="panel">
        <h2>{t.settings.cardData}</h2>
        {status ? (
          <dl className="facts">
            <dt>{t.settings.cards}</dt>
            <dd>
              {t.settings.dataSummary(
                formatNumber(status.oracle_count),
                formatNumber(status.card_count),
                formatNumber(status.set_count),
              )}
            </dd>
            <dt>{t.settings.scryfallDataFrom}</dt>
            <dd>{formatDate(status.cards_updated_at)}</dd>
            <dt>{t.settings.lastSetSync}</dt>
            <dd>{formatDate(status.sets_synced_at)}</dd>
          </dl>
        ) : (
          <p className="muted">{t.common.loading}</p>
        )}

        {running && progress && <SyncProgressBar progress={progress} />}

        {!running && (
          <div className="actions">
            <button className="button primary" onClick={() => start(false)}>
              {hasData ? t.settings.refreshData : t.settings.downloadData}
            </button>
            {hasData && (
              <>
                <button className="button" onClick={runCheck} disabled={checking}>
                  {checking ? t.settings.checking : t.settings.checkUpdates}
                </button>
                <button
                  className="button"
                  onClick={() => start(true)}
                  title={t.settings.forceTitle}
                >
                  {t.settings.force}
                </button>
              </>
            )}
          </div>
        )}

        {check && (
          <p className={check.update_available ? 'status warn' : 'status ok'}>
            {check.update_available
              ? t.settings.newerData(formatDate(check.remote_updated_at))
              : t.settings.upToDate}
          </p>
        )}
        {checkError && <p className="status error">{t.settings.checkFailed(checkError)}</p>}
        {startError && <p className="status error">{startError}</p>}
        {last?.error && <p className="status error">{t.settings.syncFailed(last.error)}</p>}
        {last?.result && !last.error && (
          <p className="status ok">
            {last.result.skipped
              ? t.settings.skipped
              : t.settings.imported(formatNumber(Number(last.result.cards)))}
          </p>
        )}
        <p className="muted small">{t.settings.dataNote}</p>
      </section>

      <BackupPanel />

      <PrintingPanel />

      <section className="panel">
        <h2>{t.settings.app}</h2>
        <dl className="facts">
          <dt>{t.settings.dataDir}</dt>
          <dd className="mono">{status?.data_dir ?? '—'}</dd>
          <dt>{t.settings.dbSize}</dt>
          <dd>{status ? formatBytes(status.db_size_bytes) : '—'}</dd>
          <dt>{t.settings.version}</dt>
          <dd>
            {health ? t.settings.versionValue(health.version, health.schema_version) : '—'}
          </dd>
        </dl>
      </section>

      <section className="panel about">
        <h2>{t.settings.about}</h2>
        <p className="small">{t.settings.aboutLicense}</p>
        <p className="small">{t.settings.aboutScryfall}</p>
        {/* Wizards' Fan Content Policy asks for this notice, in English, on the fan content itself. */}
        <p className="muted small">
          MTG Deck Manager is unofficial Fan Content permitted under the Fan Content Policy. Not approved/endorsed by
          Wizards. Portions of the materials used are property of Wizards of the Coast. ©Wizards of the Coast LLC.
        </p>
        <p className="muted small mono">https://github.com/wjaros/mtg-manager</p>
      </section>
    </div>
  )
}

function BackupPanel() {
  const [replace, setReplace] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null)

  const restore = async (file: File) => {
    setMessage(null)
    let data: unknown
    try {
      data = JSON.parse(await file.text())
    } catch {
      setMessage({ ok: false, text: t.settings.notJson })
      return
    }
    if (
      replace &&
      !window.confirm(t.settings.confirmReplace)
    ) {
      return
    }
    setBusy(true)
    try {
      const r = await api.backupImport(data, replace)
      const missing = r.missing_cards.length
        ? t.settings.missingCards(
            r.missing_cards.length,
            `${r.missing_cards.slice(0, 5).join(', ')}${r.missing_cards.length > 5 ? '…' : ''}`,
          )
        : ''
      setMessage({
        ok: missing === '',
        text: t.settings.restored(r.decks, r.collection_items, r.locations) + missing,
      })
    } catch (e) {
      setMessage({ ok: false, text: (e as Error).message })
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel">
      <h2>{t.settings.backup}</h2>
      <p className="muted small">{t.settings.backupNote}</p>
      <div className="actions">
        <a className="button primary" href="/api/backup/export" download>
          {t.settings.saveBackup}
        </a>
        <label className={`button ${busy ? 'disabled' : ''}`}>
          {busy ? t.settings.loading : t.settings.loadBackup}
          <input
            type="file"
            accept="application/json,.json"
            hidden
            disabled={busy}
            onChange={(e) => {
              const file = e.target.files?.[0]
              e.target.value = ''
              if (file) restore(file)
            }}
          />
        </label>
        <label className="checkbox">
          <input type="checkbox" checked={replace} onChange={(e) => setReplace(e.target.checked)} />
          {t.settings.replace}
        </label>
      </div>
      {message && <p className={`status ${message.ok ? 'ok' : 'error'}`}>{message.text}</p>}
      <CloudBackupSettings />
    </section>
  )
}

function SyncProgressBar({ progress }: { progress: SyncProgress }) {
  const { stage, done, total } = progress
  const pct = total > 0 ? Math.min(100, (done / total) * 100) : null
  let detail = ''
  if (stage === 'download') detail = total ? `${Math.round(done / 1e6)} / ${Math.round(total / 1e6)} MB` : ''
  else if (stage === 'import') detail = t.settings.printingsCount(formatNumber(done))
  else if (total) detail = `${done} / ${total}`

  return (
    <div className="sync-progress" role="status">
      <div className="sync-progress-label">
        <span>{STAGE_LABEL[stage ?? ''] ?? t.settings.preparing}</span>
        <span className="muted">{detail}</span>
      </div>
      <div className={`progress ${pct === null ? 'indeterminate' : ''}`}>
        <div className="progress-fill" style={pct === null ? undefined : { width: `${pct}%` }} />
      </div>
    </div>
  )
}
