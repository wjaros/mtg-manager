import { useEffect, useMemo, useState } from 'react'
import {
  api,
  type Board,
  type DeckFormat,
  type ImportLine,
  type ImportReport,
  type Platform,
  type SeedInfo,
} from '../api/client'
import { useHoverPreview } from '../hooks/useHoverPreview'
import { FORMAT_LABEL } from '../decks'
import { t } from '../i18n'
import { CollectionImportPanel } from '../components/CollectionImportPanel'

const BOARD_LABEL: Record<Board, string> = {
  commander: t.panels.boardCommander,
  companion: 'Companion',
  main: t.panels.boardMain,
  sideboard: 'Sideboard',
  maybe: 'Maybeboard',
}
const BOARD_ORDER: Board[] = ['commander', 'companion', 'main', 'sideboard', 'maybe']

const PLACEHOLDER = `${t.importer.placeholderIntro}

Commander
1 Calix, Guided by Fate (MAT) 26

Deck
11 Forest (SOS) 281
1 Seal Away (DAR) 31`

interface Props {
  onImported: (deckId: number) => void
  onCollectionImported: (locationId: number | null) => void
}

export function ImportView({ onImported, onCollectionImported }: Props) {
  const [kind, setKind] = useState<'deck' | 'collection'>('deck')
  const [text, setText] = useState('')
  const [platform, setPlatform] = useState<'' | Platform>('')
  const [seeds, setSeeds] = useState<SeedInfo[]>([])
  const [report, setReport] = useState<ImportReport | null>(null)
  const [parsing, setParsing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.seeds().then(setSeeds, () => setSeeds([]))
  }, [])

  const analyze = async (source = text) => {
    if (!source.trim()) return
    setParsing(true)
    setError(null)
    try {
      setReport(await api.parseImport(source, platform || undefined))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setParsing(false)
    }
  }

  // Replace the card name on one line with a suggestion and analyze again.
  const applySuggestion = (line: ImportLine, suggestion: string) => {
    const lines = text.split('\n')
    lines[line.line_no - 1] = lines[line.line_no - 1].replace(line.name, suggestion)
    const next = lines.join('\n')
    setText(next)
    analyze(next)
  }

  return (
    <div className="view import-view">
      <div className="view-header">
        <h1>{t.importer.title}</h1>
        <div className="segmented" role="tablist">
          <button className={kind === 'deck' ? 'on' : ''} onClick={() => setKind('deck')} role="tab">
            {t.collectionImport.tabDeck}
          </button>
          <button className={kind === 'collection' ? 'on' : ''} onClick={() => setKind('collection')} role="tab">
            {t.collectionImport.tabCollection}
          </button>
        </div>
      </div>

      {kind === 'collection' ? (
        <CollectionImportPanel onImported={onCollectionImported} />
      ) : (
        <>

        <section className="panel import-input">
          {seeds.length > 0 && (
            <div className="seed-row">
              <span className="muted small">{t.importer.examples}</span>
              {seeds.map((seed) => (
                <button
                  key={seed.file}
                  className="chip"
                  onClick={() => {
                    setText(seed.text)
                    setReport(null)
                  }}
                >
                  {seed.name}
                </button>
              ))}
            </div>
          )}
          <textarea
            className="input decklist"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={PLACEHOLDER}
            spellCheck={false}
          />
          <div className="actions">
            <button className="button primary" onClick={() => analyze()} disabled={parsing || !text.trim()}>
              {parsing ? t.importer.analyzing : t.importer.analyze}
            </button>
            <select
              className="select"
              value={platform}
              onChange={(e) => setPlatform(e.target.value as '' | Platform)}
              aria-label={t.decks.platform}
            >
              <option value="">{t.importer.platformFromList}</option>
              <option value="arena">{t.importer.platformArena}</option>
              <option value="paper">{t.importer.platformPaper}</option>
            </select>
            <span className="muted small">{t.importer.nothingSaved}</span>
          </div>
          {error && <p className="status error">{error}</p>}
        </section>

        {report && (
          <ImportReportPanel
            // A new report resets the review form.
            key={JSON.stringify(report.meta) + report.lines.length + report.counts.not_found}
            report={report}
            platformOverride={platform || null}
            onSuggestion={applySuggestion}
            onImported={onImported}
          />
        )}
        </>
      )}
    </div>
  )
}

function ImportReportPanel({
  report,
  platformOverride,
  onSuggestion,
  onImported,
}: {
  report: ImportReport
  platformOverride: Platform | null
  onSuggestion: (line: ImportLine, suggestion: string) => void
  onImported: (deckId: number) => void
}) {
  const { meta, counts } = report
  const [name, setName] = useState(meta.name ?? '')
  const [format, setFormat] = useState<DeckFormat>(meta.format ?? 'freeform')
  const [platform, setPlatform] = useState<Platform>(platformOverride ?? meta.platform ?? 'paper')
  const [skipMissing, setSkipMissing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const preview = useHoverPreview()

  const byBoard = useMemo(() => {
    const groups = new Map<Board, ImportLine[]>()
    for (const line of report.lines) groups.set(line.board, [...(groups.get(line.board) ?? []), line])
    return BOARD_ORDER.filter((b) => groups.has(b)).map((b) => [b, groups.get(b)!] as const)
  }, [report])

  const blocked = counts.not_found > 0 && !skipMissing
  const save = async () => {
    setSaving(true)
    setError(null)
    try {
      const deck = await api.commitImport({
        name: name.trim() || t.importer.defaultName,
        format,
        platform,
        description: meta.description,
        preferred_sets: meta.preferred_sets,
        entries: report.lines
          .filter((l) => l.card)
          .map((l) => ({ card_id: l.card!.id, quantity: l.quantity, board: l.board })),
      })
      onImported(deck.id)
    } catch (e) {
      setError((e as Error).message)
      setSaving(false)
    }
  }

  return (
    <section className="panel import-report">
      <div className="report-summary">
        <span className="pill ok">{t.importer.matched(counts.matched)}</span>
        <span className={`pill ${counts.warning ? 'warn' : ''}`}>{t.importer.warnings(counts.warning)}</span>
        <span className={`pill ${counts.not_found ? 'error' : ''}`}>{t.importer.notFound(counts.not_found)}</span>
        <span className="muted">{t.common.cards(counts.cards)}</span>
      </div>

      {report.errors.length > 0 && (
        <div className="report-errors">
          {report.errors.map((e) => (
            <p key={e.line_no} className="status error small">
              {t.importer.lineError(e.line_no, e.text.trim(), e.message)}
            </p>
          ))}
        </div>
      )}

      <div className="report-lines">
        {byBoard.map(([board, lines]) => (
          <div key={board} className="report-group">
            <h3 className="deck-group-title">
              {BOARD_LABEL[board]} <span className="muted">{lines.reduce((n, l) => n + l.quantity, 0)}</span>
            </h3>
            {lines.map((line) => (
              <div key={line.line_no} className={`report-line ${line.status}`}>
                <span className="report-status" title={line.status}>
                  {line.status === 'matched' ? '✓' : line.status === 'warning' ? '⚠' : '✗'}
                </span>
                <span className="deck-qty">{line.quantity}</span>
                <span className="report-input">
                  {line.name}
                  {line.set_code && (
                    <span className="muted">
                      {' '}
                      ({line.set_code.toUpperCase()}){line.collector_number ? ` ${line.collector_number}` : ''}
                    </span>
                  )}
                  {line.foil && <span className="muted"> *F*</span>}
                </span>
                <span
                  className="report-match"
                  onMouseEnter={(e) => preview.show(line.card ?? null, e)}
                  onMouseLeave={() => preview.show(null)}
                >
                  {line.card ? (
                    <>
                      → {line.card.name !== line.name && <strong>{line.card.name} </strong>}
                      <span className="muted">
                        {line.card.set_code.toUpperCase()} #{line.card.collector_number}
                      </span>
                    </>
                  ) : line.suggestions.length ? (
                    <span className="suggestions">
                      {t.importer.maybe}{' '}
                      {line.suggestions.map((s) => (
                        <button key={s} className="link-button" onClick={() => onSuggestion(line, s)}>
                          {s}
                        </button>
                      ))}
                    </span>
                  ) : (
                    <span className="muted">{t.importer.notFoundLine}</span>
                  )}
                </span>
                {line.warnings.length > 0 && (
                  <ul className="report-warnings">
                    {line.warnings.map((w) => (
                      <li key={w}>{w}</li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        ))}
      </div>

      <div className="import-save">
        <h2>{t.importer.saveAsNew}</h2>
        <div className="form-row">
          <label>
            {t.decks.name}
            <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label>
            {t.decks.format}
            <select className="select" value={format} onChange={(e) => setFormat(e.target.value as DeckFormat)}>
              {(Object.keys(FORMAT_LABEL) as DeckFormat[]).map((f) => (
                <option key={f} value={f}>
                  {FORMAT_LABEL[f]}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t.decks.platform}
            <select className="select" value={platform} onChange={(e) => setPlatform(e.target.value as Platform)}>
              <option value="arena">{t.deck.arena}</option>
              <option value="paper">{t.deck.paper}</option>
            </select>
          </label>
        </div>
        {counts.not_found > 0 && (
          <label className="checkbox">
            <input type="checkbox" checked={skipMissing} onChange={(e) => setSkipMissing(e.target.checked)} />
            {t.importer.skipMissing(counts.not_found)}
          </label>
        )}
        <div className="actions">
          <button className="button primary" onClick={save} disabled={saving || blocked || counts.cards === 0}>
            {saving ? t.importer.saving : t.importer.saveDeck}
          </button>
          {blocked && <span className="muted small">{t.importer.blocked}</span>}
        </div>
        {error && <p className="status error">{error}</p>}
      </div>
      {preview.element}
    </section>
  )
}
