import { useEffect, useState } from 'react'
import { api, deckPdfUrl, type ExportResult } from '../api/client'
import { copyText } from '../clipboard'
import { t } from '../i18n'

type Target = 'arena' | 'text'

interface Props {
  deckId: number
  onClose: () => void
}

/** Decklist export; Arena imports a deck straight from the clipboard. */
export function ExportDialog({ deckId, onClose }: Props) {
  const [target, setTarget] = useState<Target>('arena')
  const [results, setResults] = useState<Partial<Record<Target, ExportResult>>>({})
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const result = results[target]

  useEffect(() => {
    let cancelled = false
    api.exportDeck(deckId, target).then(
      (r) => !cancelled && setResults((prev) => ({ ...prev, [target]: r })),
      (e: Error) => !cancelled && setError(e.message),
    )
    return () => {
      cancelled = true
    }
  }, [deckId, target])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const copy = async () => {
    if (!result) return
    try {
      await copyText(result.text)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div className="modal-backdrop centered" onClick={onClose}>
      <div className="dialog" onClick={(e) => e.stopPropagation()} role="dialog" aria-label={t.panels.exportTitle}>
        <div className="dialog-header">
          <h2>{t.panels.exportTitle}</h2>
          <button className="close-button static" onClick={onClose} aria-label={t.common.close}>
            ×
          </button>
        </div>
        <div className="segmented" role="tablist">
          <button className={target === 'arena' ? 'on' : ''} onClick={() => setTarget('arena')}>
            MTG Arena
          </button>
          <button className={target === 'text' ? 'on' : ''} onClick={() => setTarget('text')}>
            {t.panels.exportText}
          </button>
        </div>

        {result?.unavailable.length ? (
          <p className="status error small">
            {t.panels.unavailableOnArena(result.unavailable.join(', '))}
          </p>
        ) : null}
        {/* Swapped printings can be dozens of lines: one line, details on demand. */}
        {result?.warnings.length ? (
          <details className="export-warnings">
            <summary>{t.panels.exportWarnings(result.warnings.length)}</summary>
            <ul className="report-warnings">
              {result.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          </details>
        ) : null}

        <textarea className="input decklist" readOnly value={result?.text ?? t.common.loading} spellCheck={false} />
        {error && <p className="status error">{error}</p>}
        <div className="actions">
          <button className="button primary" onClick={copy} disabled={!result}>
            {copied ? t.common.copied : t.common.copy}
          </button>
          <a className="button" href={deckPdfUrl(deckId)} download title={t.collectionImport.pdfTitle}>
            {t.collectionImport.pdf}
          </a>
          {target === 'arena' && (
            <span className="muted small">{t.panels.arenaHint}</span>
          )}
        </div>
      </div>
    </div>
  )
}
