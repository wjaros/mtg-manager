import { useEffect, useState } from 'react'
import {
  api,
  type CardSummary,
  type CollectionImportEntry,
  type CollectionImportReport,
  type ImportReport,
  type Location,
} from '../api/client'
import { useHoverPreview } from '../hooks/useHoverPreview'
import { t } from '../i18n'

type Source = 'list' | 'moxfield'

const FINISH_LABEL: Record<string, string> = { nonfoil: '', foil: 'foil', etched: 'etched' }

/** One reviewed line, whichever source it came from. */
interface Row {
  key: number
  quantity: number
  name: string
  set_code: string | null
  collector_number: string | null
  finish: NonNullable<CollectionImportEntry['finish']>
  condition: NonNullable<CollectionImportEntry['condition']>
  language: string
  note: string | null
  status: string
  card: CardSummary | null
  warnings: string[]
  suggestions: string[]
}

interface Review {
  rows: Row[]
  errors: { key: number; text: string }[]
}

function fromMoxfield(report: CollectionImportReport): Review {
  return {
    rows: report.lines.map((l) => ({ ...l, key: l.row })),
    errors: report.errors.map((e) => ({ key: e.row, text: t.collectionImport.rowError(e.row, e.message) })),
  }
}

function fromList(report: ImportReport): Review {
  return {
    rows: report.lines.map((l) => ({
      key: l.line_no,
      quantity: l.quantity,
      name: l.name,
      set_code: l.set_code,
      collector_number: l.collector_number,
      finish: l.foil ? 'foil' : 'nonfoil',
      condition: 'NM',
      language: l.card?.lang ?? 'en',
      // The line's own "# ..." note; otherwise any deviation (name-only match, other printing)
      // means the printing is a guess.
      note: l.note ?? (l.card && l.warnings.length ? t.collectionImport.unverifiedNote : null),
      status: l.status,
      card: l.card,
      warnings: l.warnings,
      suggestions: l.suggestions,
    })),
    errors: report.errors.map((e) => ({ key: e.line_no, text: t.importer.lineError(e.line_no, e.text.trim(), e.message) })),
  }
}

interface Props {
  onImported: (locationId: number | null) => void
}

/** Cards into the collection, not into a deck: a card list (e.g. a product's contents) or a
 * Moxfield collection CSV. Report first, then add the matched cards to one location. */
export function CollectionImportPanel({ onImported }: Props) {
  const [source, setSource] = useState<Source>('list')
  const [text, setText] = useState('')
  const [fileName, setFileName] = useState<string | null>(null)
  const [review, setReview] = useState<Review | null>(null)
  const [locations, setLocations] = useState<Location[]>([])
  const [locationId, setLocationId] = useState<number | null>(null)
  const [skipMissing, setSkipMissing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const preview = useHoverPreview()

  useEffect(() => {
    api.locations().then(setLocations, () => setLocations([]))
  }, [])

  const analyze = async (action: () => Promise<Review>) => {
    setError(null)
    setReview(null)
    setBusy(true)
    try {
      setReview(await action())
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const loadCsv = (file: File) => {
    setFileName(file.name)
    analyze(async () => fromMoxfield(await api.parseMoxfieldCollection(await file.text())))
  }

  const analyzeList = (value: string) => analyze(async () => fromList(await api.parseImport(value, 'paper')))

  const commit = async () => {
    if (!review) return
    setBusy(true)
    setError(null)
    try {
      await api.commitCollectionImport(
        review.rows
          .filter((r) => r.card)
          .map((r) => ({
            card_id: r.card!.id,
            quantity: r.quantity,
            finish: r.finish,
            condition: r.condition,
            language: r.language,
            note: r.note,
          })),
        locationId,
      )
      onImported(locationId)
    } catch (e) {
      setError((e as Error).message)
      setBusy(false)
    }
  }

  const rows = review?.rows ?? []
  const counts = {
    matched: rows.filter((r) => r.status === 'matched').length,
    warning: rows.filter((r) => r.status === 'warning').length,
    notFound: rows.filter((r) => r.status === 'not_found').length,
    copies: rows.filter((r) => r.card).reduce((n, r) => n + r.quantity, 0),
  }
  const blocked = counts.notFound > 0 && !skipMissing

  return (
    <>
      <section className="panel import-input">
        <div className="segmented" role="tablist">
          {(['list', 'moxfield'] as Source[]).map((s) => (
            <button
              key={s}
              className={source === s ? 'on' : ''}
              role="tab"
              onClick={() => {
                setSource(s)
                setReview(null)
                setError(null)
              }}
            >
              {s === 'list' ? t.collectionImport.sourceList : t.collectionImport.sourceMoxfield}
            </button>
          ))}
        </div>
        {source === 'list' ? (
          <>
            <p className="muted small">{t.collectionImport.listIntro}</p>
            <textarea
              className="input decklist"
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={t.collectionImport.listPlaceholder}
              spellCheck={false}
            />
            <div className="actions">
              <button className="button primary" onClick={() => analyzeList(text)} disabled={busy || !text.trim()}>
                {busy ? t.importer.analyzing : t.importer.analyze}
              </button>
              <label className={`button ${busy ? 'disabled' : ''}`}>
                {t.collectionImport.loadTextFile}
                <input
                  type="file"
                  accept=".txt,text/plain"
                  hidden
                  disabled={busy}
                  onChange={async (e) => {
                    const file = e.target.files?.[0]
                    e.target.value = ''
                    if (!file) return
                    const value = await file.text()
                    setText(value)
                    analyzeList(value)
                  }}
                />
              </label>
            </div>
          </>
        ) : (
          <>
            <p className="muted small">{t.collectionImport.intro}</p>
            <div className="actions">
              <label className={`button primary ${busy ? 'disabled' : ''}`}>
                {busy ? t.importer.analyzing : t.collectionImport.chooseFile}
                <input
                  type="file"
                  accept=".csv,text/csv"
                  hidden
                  disabled={busy}
                  onChange={(e) => {
                    const file = e.target.files?.[0]
                    e.target.value = ''
                    if (file) loadCsv(file)
                  }}
                />
              </label>
              {fileName && <span className="muted small">{fileName}</span>}
            </div>
          </>
        )}
        {error && <p className="status error">{error}</p>}
      </section>

      {review && (
        <section className="panel import-report">
          <div className="report-summary">
            <span className="pill ok">{t.importer.matched(counts.matched)}</span>
            <span className={`pill ${counts.warning ? 'warn' : ''}`}>{t.importer.warnings(counts.warning)}</span>
            <span className={`pill ${counts.notFound ? 'error' : ''}`}>{t.importer.notFound(counts.notFound)}</span>
            <span className="muted">{t.collectionImport.copies(counts.copies)}</span>
          </div>
          {review.errors.map((e) => (
            <p key={e.key} className="status error small">
              {e.text}
            </p>
          ))}

          <div className="report-lines">
            {rows.map((row) => (
              <div key={row.key} className={`report-line ${row.status}`}>
                <span className="report-status" title={row.status}>
                  {row.status === 'matched' ? '✓' : row.status === 'warning' ? '⚠' : '✗'}
                </span>
                <span className="deck-qty">{row.quantity}</span>
                <span className="report-input">
                  {row.name}
                  <span className="muted">
                    {row.set_code && ` (${row.set_code.toUpperCase()}${row.collector_number ? ` ${row.collector_number}` : ''})`}
                    {FINISH_LABEL[row.finish] && ` · ${FINISH_LABEL[row.finish]}`} · {row.condition}
                    {row.language !== 'en' && ` · ${row.language}`}
                    {row.note && ` · ${row.note}`}
                  </span>
                </span>
                <span
                  className="report-match"
                  onMouseEnter={(e) => preview.show(row.card ?? null, e)}
                  onMouseLeave={() => preview.show(null)}
                >
                  {row.card ? (
                    <>
                      → {row.card.name !== row.name && <strong>{row.card.name} </strong>}
                      <span className="muted">
                        {row.card.set_code.toUpperCase()} #{row.card.collector_number}
                      </span>
                    </>
                  ) : (
                    <span className="muted">
                      {t.importer.notFoundLine}
                      {row.suggestions.length > 0 && ` · ${t.importer.maybe} ${row.suggestions.join(', ')}`}
                    </span>
                  )}
                </span>
                {row.warnings.length > 0 && (
                  <ul className="report-warnings">
                    {row.warnings.map((w) => (
                      <li key={w}>{w}</li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>

          <div className="import-save">
            <h2>{t.collectionImport.addTitle}</h2>
            <div className="form-row">
              <label>
                {t.items.location}
                <select
                  className="select"
                  value={locationId ?? ''}
                  onChange={(e) => setLocationId(e.target.value ? Number(e.target.value) : null)}
                >
                  <option value="">{t.items.noLocation}</option>
                  {locations.map((l) => (
                    <option key={l.id} value={l.id}>
                      {l.name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {counts.notFound > 0 && (
              <label className="checkbox">
                <input type="checkbox" checked={skipMissing} onChange={(e) => setSkipMissing(e.target.checked)} />
                {t.collectionImport.skipMissing(counts.notFound)}
              </label>
            )}
            <p className="muted small">{t.collectionImport.addsNotReplaces}</p>
            <div className="actions">
              <button className="button primary" onClick={commit} disabled={busy || blocked || counts.copies === 0}>
                {busy ? t.importer.saving : t.collectionImport.add(counts.copies)}
              </button>
              {blocked && <span className="muted small">{t.importer.blocked}</span>}
            </div>
          </div>
          {preview.element}
        </section>
      )}
    </>
  )
}
