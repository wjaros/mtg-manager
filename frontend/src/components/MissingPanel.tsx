import { useEffect, useState, type MouseEvent } from 'react'
import { api, missingExportUrl, type MissingEntry, type MissingFormat, type MissingReport } from '../api/client'
import { copyText } from '../clipboard'
import { locale, t } from '../i18n'

interface Props {
  deckId: number
  /** Changes whenever the deck's contents change, to refetch. */
  revision: string
  onHover: (card: { id: string; name: string; image_faces: number } | null, event?: MouseEvent) => void
}

/** Cards the deck needs beyond the collection, with shopping-list exports. */
export function MissingPanel({ deckId, revision, onHover }: Props) {
  const [excludeOtherDecks, setExcludeOtherDecks] = useState(false)
  // Exports: by default proxied cards are on the list too (a proxy is a card still to buy).
  const [includeProxied, setIncludeProxied] = useState(true)
  const [report, setReport] = useState<MissingReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api.deckMissing(deckId, excludeOtherDecks).then(
      (r) => !cancelled && setReport(r),
      (e: Error) => !cancelled && setError(e.message),
    )
    return () => {
      cancelled = true
    }
  }, [deckId, excludeOtherDecks, revision])

  const copy = async (format: MissingFormat, label: string) => {
    try {
      await copyText(await api.missingExport(deckId, format, excludeOtherDecks, includeProxied))
      setNote(t.panels.copiedList(label))
    } catch (e) {
      setNote(t.common.error((e as Error).message))
    }
  }

  if (error) return <p className="status error">{error}</p>
  if (!report) return <p className="muted">{t.panels.checkingCollection}</p>

  const asOf = report.prices_as_of ? new Date(report.prices_as_of).toLocaleDateString(locale) : null

  return (
    <div className="missing-panel">
      <label className="checkbox">
        <input
          type="checkbox"
          checked={excludeOtherDecks}
          onChange={(e) => setExcludeOtherDecks(e.target.checked)}
        />
        {t.panels.excludeOtherDecks}
        <span className="muted small">{t.panels.excludeOtherDecksHint}</span>
      </label>

      {report.entries.length === 0 ? (
        <p className="validation-ok missing-none">{t.panels.haveAll}</p>
      ) : (
        <>
          <div className="stat-tiles">
            <div className="stat-tile">
              <span className="stat-label">{t.panels.missing}</span>
              <span className="stat-value">{report.missing_copies}</span>
              <span className="stat-note">{t.panels.distinctCards(report.missing_cards)}</span>
            </div>
            <div className="stat-tile">
              <span className="stat-label">{t.panels.estimatedCost}</span>
              <span className="stat-value">€{report.total_eur.toFixed(2)}</span>
              <span className="stat-note">
                ${report.total_usd.toFixed(2)}
                {asOf && t.panels.pricesAsOf(asOf)}
              </span>
            </div>
          </div>

          <div className="actions">
            <button className="button primary" onClick={() => copy('cardmarket', 'CardMarket')}>
              {t.panels.copyCardmarket}
            </button>
            <button className="button" onClick={() => copy('text', t.panels.withPrintings)}>
              {t.panels.copyWithPrintings}
            </button>
            <a className="button" href={missingExportUrl(deckId, 'csv', excludeOtherDecks, includeProxied)} download>
              {t.panels.downloadCsv}
            </a>
            {note && <span className="muted small">{note}</span>}
          </div>
          {report.entries.some((e) => (e.proxied ?? 0) > 0) && (
            <label className="checkbox small">
              <input type="checkbox" checked={includeProxied} onChange={(e) => setIncludeProxied(e.target.checked)} />
              {t.panels.includeProxied}
            </label>
          )}
          <p className="muted small">{t.panels.cardmarketHint}</p>

          {/* Copies with no copy at all, then those a proxy stands in for (still to buy). */}
          <MissingTable
            title={t.panels.missingNoProxy}
            rows={report.entries.filter((e) => e.missing > (e.proxied ?? 0)).map((e) => [e, e.missing - (e.proxied ?? 0)])}
            onHover={onHover}
          />
          <MissingTable
            title={t.panels.missingProxied}
            rows={report.entries.filter((e) => (e.proxied ?? 0) > 0).map((e) => [e, (e.proxied ?? 0)])}
            onHover={onHover}
            proxy
          />
        </>
      )}
    </div>
  )
}

function MissingTable({
  title,
  rows,
  onHover,
  proxy = false,
}: {
  title: string
  rows: [MissingEntry, number][]
  onHover: Props['onHover']
  proxy?: boolean
}) {
  if (!rows.length) return null
  return (
    <>
      <h3 className={`missing-section ${proxy ? 'proxy-text' : ''}`}>
        {title} <span className="muted">({rows.reduce((n, [, q]) => n + q, 0)})</span>
      </h3>
      <table className="missing-table">
        <thead>
          <tr>
            <th className="num">{t.panels.missing}</th>
            <th>{t.panels.card}</th>
            <th>{t.panels.deckPrinting}</th>
            <th className="num">{t.panels.have}</th>
            <th className="num">{t.panels.price}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([e, qty]) => (
            <tr key={e.oracle_id} onMouseEnter={(ev) => onHover(e.card, ev)} onMouseLeave={() => onHover(null)}>
              <td className="num strong">{qty}</td>
              <td>
                {e.name}
                {proxy && <span className="proxy-chip">PROXY</span>}
              </td>
              <td className="muted">
                {e.card.set_code.toUpperCase()} #{e.card.collector_number}
              </td>
              <td className="num muted" title={t.panels.haveTitle(e.owned, e.available, e.needed)}>
                {e.available}/{e.needed}
                {e.owned !== e.available && <span className="muted"> ({e.owned})</span>}
              </td>
              <td className="num">{e.price_eur != null ? `€${(e.price_eur * qty).toFixed(2)}` : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}
