import { useEffect, useState, type MouseEvent } from 'react'
import { api, type CardSummary, type DeckChange, type DeckDetail, type DeckVersion, type DeckVersionDetail } from '../api/client'
import { changeKind, changeLabel, FORMAT_LABEL, PLATFORM_LABEL } from '../decks'
import { formatDateTime, t } from '../i18n'

const BOARD_LABEL: Record<string, string> = {
  main: '',
  commander: t.history.boardCommander,
  companion: 'companion',
  sideboard: 'sideboard',
  maybe: 'maybeboard',
}

interface Props {
  deck: DeckDetail
  /** Changes when the deck's contents change; versions are refetched. */
  revision: string
  busy: boolean
  onSave: () => void
  onRestore: (version: DeckVersion) => void
  onHover: (card: CardSummary | null, event?: MouseEvent) => void
}

/** Unsaved changes, saved versions, and what changed in each. */
export function DeckHistoryPanel({ deck, revision, busy, onSave, onRestore, onHover }: Props) {
  const [versions, setVersions] = useState<DeckVersion[] | null>(null)
  const [selected, setSelected] = useState<number | null>(null)
  const [compare, setCompare] = useState<'previous' | 'current'>('previous')
  const [detail, setDetail] = useState<DeckVersionDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api.deckVersions(deck.id).then(
      (v) => !cancelled && setVersions(v),
      (e: Error) => !cancelled && setError(e.message),
    )
    return () => {
      cancelled = true
    }
  }, [deck.id, revision, deck.changes.base_number])

  useEffect(() => {
    if (selected === null) return
    let cancelled = false
    api.deckVersion(deck.id, selected, compare).then(
      (d) => !cancelled && setDetail(d),
      (e: Error) => !cancelled && setError(e.message),
    )
    return () => {
      cancelled = true
    }
  }, [deck.id, selected, compare, revision])

  const { changes } = deck
  const settings = [
    changes.format_before && t.history.formatChange(FORMAT_LABEL[changes.format_before], FORMAT_LABEL[deck.format]),
    changes.platform_before &&
      t.history.platformChange(PLATFORM_LABEL[changes.platform_before], PLATFORM_LABEL[deck.platform]),
  ].filter(Boolean) as string[]

  return (
    <div className="history">
      {error && <p className="status error">{error}</p>}
      <section className="history-section">
        <h3>
          {t.history.unsaved}{' '}
          <span className="muted small">
            {changes.base_number === null ? t.history.noVersionYet : t.history.sinceVersion(changes.base_number)}
          </span>
        </h3>
        {deck.unsaved_changes === 0 ? (
          <p className="muted small">{t.history.noChanges}</p>
        ) : (
          <>
            {settings.map((s) => (
              <p key={s} className="small change-setting">
                {s}
              </p>
            ))}
            <ChangeList changes={changes.cards} onHover={onHover} />
            <button className="button primary" onClick={onSave} disabled={busy}>
              {t.history.saveVersion}
            </button>
          </>
        )}
      </section>

      <section className="history-section">
        <h3>{t.history.versions}</h3>
        {versions === null ? (
          <p className="muted small">{t.common.loading}</p>
        ) : versions.length === 0 ? (
          <p className="muted small">{t.history.noVersions}</p>
        ) : (
          <ul className="version-list">
            {versions.map((v) => (
              <li key={v.id}>
                <button
                  className={`version-row ${selected === v.id ? 'on' : ''}`}
                  onClick={() => {
                    setDetail(null)
                    setSelected(selected === v.id ? null : v.id)
                  }}
                >
                  <span className="version-number">v{v.number}</span>
                  <span className="version-note">{v.note ? (t.history.systemNotes[v.note] ?? v.note) : <span className="muted">{t.history.noNote}</span>}</span>
                  <span className="version-delta">
                    {v.added > 0 && <span className="delta-added">+{v.added}</span>}
                    {v.removed > 0 && <span className="delta-removed">−{v.removed}</span>}
                  </span>
                  <span className="muted small">{t.common.cards(v.total)}</span>
                  <span className="muted small">{formatDateTime(v.created_at)}</span>
                </button>
                {selected === v.id && (
                  <div className="version-detail">
                    <div className="segmented small">
                      <button className={compare === 'previous' ? 'on' : ''} onClick={() => setCompare('previous')}>
                        {t.history.whatChanged}
                      </button>
                      <button className={compare === 'current' ? 'on' : ''} onClick={() => setCompare('current')}>
                        {t.history.diffToCurrent}
                      </button>
                    </div>
                    {!detail ? (
                      <p className="muted small">{t.common.loading}</p>
                    ) : detail.changes.length === 0 ? (
                      <p className="muted small">{t.history.noDiff}</p>
                    ) : (
                      <ChangeList changes={detail.changes} onHover={onHover} />
                    )}
                    <button
                      className="button"
                      disabled={busy}
                      onClick={() => {
                        const unsaved = deck.unsaved_changes
                          ? t.history.restoreUnsaved
                          : ''
                        if (window.confirm(t.history.confirmRestore(v.number, unsaved))) onRestore(v)
                      }}
                    >
                      {t.history.restore}
                    </button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}

function ChangeList({ changes, onHover }: { changes: DeckChange[]; onHover: Props['onHover'] }) {
  return (
    <ul className="change-list">
      {changes.map((c) => (
        <li
          key={`${c.board}-${c.name}`}
          className={`change-row change-${changeKind(c)}`}
          onMouseEnter={(e) => onHover(c.card ?? null, e)}
          onMouseLeave={() => onHover(null)}
        >
          <span className="change-badge">{changeLabel(c)}</span>
          <span className="change-name">{c.name}</span>
          {BOARD_LABEL[c.board] && <span className="muted small">{BOARD_LABEL[c.board]}</span>}
          <span className="muted small change-qty">
            {c.before} → {c.after}
          </span>
        </li>
      ))}
    </ul>
  )
}
