import { useEffect, useRef, useState } from 'react'
import {
  api,
  printJobPdfUrl,
  type CardSummary,
  type Paper,
  type PrinterProfile,
  type PrintJobStatus,
  type ProxyCandidate,
} from '../api/client'
import { t } from '../i18n'

type Reason = ProxyCandidate['reason'] | 'token' | 'extra'

interface Row {
  key: string
  card_id: string
  name: string
  reason: Reason
  qty: number
  checked: boolean
  faces: number
  other_decks: string[]
  sources?: string[] // tokens: the deck's cards that make them
  image_status: string | null
}

const GAPS = [0, 0.5, 1, 2]
type Duplex = 'off' | 'long' | 'short'
const REASONS: Reason[] = ['missing', 'in_other_deck', 'token', 'extra']
// Scryfall's image_status values worth a warning: the printed proxy would be blurry or a stand-in.
const POOR_IMAGES = ['lowres', 'placeholder', 'missing']

interface Props {
  deckId: number
  deckName: string
  onClose: () => void
}

/** Print proxies for the cards this deck's box lacks: not owned, or sitting in another deck's box. */
export function ProxyDialog({ deckId, deckName, onClose }: Props) {
  const [rows, setRows] = useState<Row[] | null>(null)
  const [includeBasics, setIncludeBasics] = useState(false)
  const [frontOnly, setFrontOnly] = useState(false)
  const [profiles, setProfiles] = useState<PrinterProfile[]>([])
  const [profileId, setProfileId] = useState<number | null>(null)
  const [paper, setPaper] = useState<Paper>('a4')
  const [gap, setGap] = useState(0)
  const [cutMarks, setCutMarks] = useState(true)
  const [duplex, setDuplex] = useState<Duplex>('off')
  const [job, setJob] = useState<PrintJobStatus | null>(null)
  const [overflow, setOverflow] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api.proxyCandidates(deckId, includeBasics).then(
      (list) =>
        !cancelled &&
        setRows((prev) => [
          ...list.map((c) => ({
            key: `${c.oracle_id}-${c.reason}`,
            card_id: c.card_id,
            name: c.name,
            reason: c.reason as Reason,
            qty: c.qty,
            checked: true,
            faces: c.faces,
            other_decks: c.other_decks,
            image_status: c.image_status ?? null,
          })),
          ...(prev ?? []).filter((r) => r.reason === 'token' || r.reason === 'extra'),
        ]),
      (e: Error) => !cancelled && setError(e.message),
    )
    return () => {
      cancelled = true
    }
  }, [deckId, includeBasics])

  // Tokens the deck makes: listed unchecked, you pick the ones you want.
  useEffect(() => {
    let cancelled = false
    api.deckTokens(deckId).then(
      (list) =>
        !cancelled &&
        setRows((prev) => [
          ...(prev ?? []).filter((r) => r.reason !== 'token'),
          ...list.map((tok) => ({
            key: `token-${tok.oracle_id}`,
            card_id: tok.card_id,
            name: tok.name,
            reason: 'token' as Reason,
            qty: 1,
            checked: false,
            faces: tok.faces,
            other_decks: [],
            sources: tok.sources,
            image_status: null,
          })),
        ]),
      () => {},
    )
    return () => {
      cancelled = true
    }
  }, [deckId])

  useEffect(() => {
    api.printerProfiles().then((list) => {
      setProfiles(list)
      const preferred = list.find((p) => p.is_default) ?? list[0]
      if (preferred) {
        setProfileId(preferred.id)
        setPaper(preferred.paper)
      }
    }, () => setProfiles([]))
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  // Follow the job until its PDF is ready.
  const running = job !== null && (job.stage === 'images' || job.stage === 'render')
  useEffect(() => {
    if (!running || !job) return
    const timer = setTimeout(() => api.printJob(job.id).then(setJob, (e: Error) => setError(e.message)), 400)
    return () => clearTimeout(timer)
  }, [running, job])

  const update = (key: string, change: Partial<Row>) =>
    setRows((prev) => prev && prev.map((r) => (r.key === key ? { ...r, ...change } : r)))

  const addExtra = (card: CardSummary) =>
    setRows((prev) => [
      ...(prev ?? []),
      {
        key: `extra-${card.id}-${Date.now()}`,
        card_id: card.id,
        name: card.name,
        reason: 'extra',
        qty: 1,
        checked: true,
        faces: Math.max(1, card.image_faces),
        other_decks: [],
        image_status: null,
      },
    ])

  const selected = (rows ?? []).filter((r) => r.checked && r.qty > 0)
  // Two-sided: one position per copy (a double-faced card's other face goes on the back).
  const slots = selected.reduce((n, r) => n + r.qty * (frontOnly || duplex !== 'off' ? 1 : r.faces), 0)
  const pages = Math.ceil(slots / 9) * (duplex !== 'off' ? 2 : 1)
  const profile = profiles.find((p) => p.id === profileId) ?? null
  const calibrated = profile?.calibrated_at != null

  const print = async () => {
    setError(null)
    setJob(null)
    try {
      const started = await api.startPrint({
        items: selected.map((r) => ({ card_id: r.card_id, qty: r.qty, faces: frontOnly ? 'front' : 'both' })),
        profile_id: profileId,
        paper,
        gap_mm: gap,
        cut_marks: cutMarks,
        duplex,
        title: deckName,
      })
      setOverflow(started.overflow ?? false)
      setJob(started)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div className="modal-backdrop centered" onClick={onClose}>
      <div className="dialog proxy-dialog" onClick={(e) => e.stopPropagation()} role="dialog" aria-label={t.print.title}>
        <div className="dialog-header">
          <h2>{t.print.title}</h2>
          <button className="close-button static" onClick={onClose} aria-label={t.common.close}>
            ×
          </button>
        </div>
        <p className="muted small">{t.print.intro}</p>

        {rows === null ? (
          <p className="muted">{t.common.loading}</p>
        ) : (
          REASONS.map((reason) => {
            const group = rows.filter((r) => r.reason === reason)
            if (group.length === 0) return null
            return (
              <section key={reason} className="proxy-group">
                <h3>
                  {t.print.reason[reason]}{' '}
                  <span className="muted">
                    ({reason === 'token' ? group.length : group.reduce((n, r) => n + r.qty, 0)})
                  </span>
                  {reason === 'token' && <span className="muted small"> · {t.print.tokensHint}</span>}
                </h3>
                {group.map((row) => (
                  <ProxyRow key={row.key} row={row} onChange={(change) => update(row.key, change)} />
                ))}
              </section>
            )
          })
        )}
        {rows !== null && !rows.some((r) => r.reason === 'missing' || r.reason === 'in_other_deck') && (
          <p className="muted">{t.print.nothingMissing}</p>
        )}

        <AddCard onAdd={addExtra} />

        <div className="proxy-options">
          <label className="checkbox">
            <input type="checkbox" checked={includeBasics} onChange={(e) => setIncludeBasics(e.target.checked)} />
            {t.print.includeBasics}
          </label>
          {duplex === 'off' && (
            <label className="checkbox">
              <input type="checkbox" checked={frontOnly} onChange={(e) => setFrontOnly(e.target.checked)} />
              {t.print.frontOnly}
            </label>
          )}
          <label className="checkbox">
            <input type="checkbox" checked={cutMarks} onChange={(e) => setCutMarks(e.target.checked)} />
            {t.print.cutMarks}
          </label>
        </div>
        <div className="proxy-options">
          <label>
            {t.print.printer}{' '}
            <select
              className="select small"
              value={profileId ?? ''}
              onChange={(e) => {
                const id = e.target.value ? Number(e.target.value) : null
                setProfileId(id)
                const chosen = profiles.find((p) => p.id === id)
                if (chosen) setPaper(chosen.paper)
              }}
            >
              <option value="">{t.print.noProfile}</option>
              {profiles.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                  {p.calibrated_at ? '' : ` (${t.print.uncalibratedShort})`}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t.print.paper}{' '}
            <select className="select small" value={paper} onChange={(e) => setPaper(e.target.value as Paper)}>
              <option value="a4">A4</option>
              <option value="letter">Letter</option>
            </select>
          </label>
          <label>
            {t.print.duplex}{' '}
            <select className="select small" value={duplex} onChange={(e) => setDuplex(e.target.value as Duplex)}>
              <option value="off">{t.print.duplexOff}</option>
              <option value="long">{t.print.duplexLong}</option>
              <option value="short">{t.print.duplexShort}</option>
            </select>
          </label>
          <label>
            {t.print.gap}{' '}
            <select className="select small" value={gap} onChange={(e) => setGap(Number(e.target.value))}>
              {GAPS.map((g) => (
                <option key={g} value={g}>
                  {g} mm
                </option>
              ))}
            </select>
          </label>
        </div>
        {duplex !== 'off' && (
          <p className="muted small">
            {t.print.duplexNote}
            {profile?.back_offset_duplex !== duplex && ` ${t.print.duplexUncalibrated}`}
          </p>
        )}
        {!calibrated && <p className="status warn">{t.print.uncalibrated}</p>}
        <p className="muted small">{t.print.personalUse}</p>

        <div className="actions">
          <button className="button primary" onClick={print} disabled={slots === 0 || running}>
            {t.print.make(slots, pages)}
          </button>
          {job?.stage === 'done' && (
            <a className="button" href={printJobPdfUrl(job.id)} download>
              {t.print.download(job.pages)}
            </a>
          )}
        </div>
        {running && job && (
          <div>
            <p className="small">{job.stage === 'images' ? t.print.stageImages(job.done, job.total) : t.print.stageRender(job.done, job.total)}</p>
            <div className="progress">
              <div className="progress-fill" style={{ width: `${job.total ? (job.done / job.total) * 100 : 0}%` }} />
            </div>
          </div>
        )}
        {job?.stage === 'done' && (
          <p className="small">{t.print.ready}</p>
        )}
        {job && job.missing_images.length > 0 && (
          <p className="status warn">{t.print.missingImages(job.missing_images.join(', '))}</p>
        )}
        {overflow && <p className="status warn">{t.print.overflow}</p>}
        {job?.stage === 'error' && <p className="status error">{job.error}</p>}
        {error && <p className="status error">{error}</p>}
      </div>
    </div>
  )
}

function ProxyRow({ row, onChange }: { row: Row; onChange: (change: Partial<Row>) => void }) {
  const [printings, setPrintings] = useState<CardSummary[] | null>(null)
  const load = () => {
    if (printings === null) api.printings(row.card_id).then(setPrintings, () => setPrintings([]))
  }
  return (
    <div className={`proxy-row ${row.checked ? '' : 'off'}`}>
      <input type="checkbox" checked={row.checked} onChange={(e) => onChange({ checked: e.target.checked })} aria-label={row.name} />
      <input
        className="input qty"
        type="number"
        min={1}
        max={99}
        value={row.qty}
        onChange={(e) => onChange({ qty: Math.max(1, Math.min(99, Number(e.target.value) || 1)) })}
      />
      <span className="proxy-name" title={row.other_decks.length ? t.print.inDecks(row.other_decks.join(', ')) : undefined}>
        {row.name}
        {row.faces > 1 && <span className="muted small"> · {t.print.doubleFaced}</span>}
        {row.other_decks.length > 0 && <span className="muted small"> · {row.other_decks.join(', ')}</span>}
        {row.sources && <span className="muted small"> · {t.print.tokenFrom(row.sources.join(', '))}</span>}
        {row.image_status && POOR_IMAGES.includes(row.image_status) && (
          <span className="warn-text small" title={t.print.poorImageTitle}>
            {' '}
            · {t.print.poorImage}
          </span>
        )}
      </span>
      <select
        className="select small proxy-printing"
        value={row.card_id}
        onFocus={load}
        onMouseDown={load}
        onChange={(e) => {
          const card = printings?.find((p) => p.id === e.target.value)
          if (card) onChange({ card_id: card.id, faces: Math.max(1, card.image_faces), image_status: null })
        }}
        aria-label={t.print.printing}
      >
        {(printings ?? []).length === 0 && <option value={row.card_id}>{t.print.deckPrinting}</option>}
        {(printings ?? []).map((p) => (
          <option key={p.id} value={p.id}>
            {p.set_code.toUpperCase()} #{p.collector_number} · {p.set_name}
          </option>
        ))}
      </select>
    </div>
  )
}

function AddCard({ onAdd }: { onAdd: (card: CardSummary) => void }) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<CardSummary[]>([])
  const abort = useRef<AbortController | null>(null)

  useEffect(() => {
    abort.current?.abort()
    if (query.trim().length < 2) return
    const controller = new AbortController()
    abort.current = controller
    const timer = setTimeout(() => {
      api.searchCards({ q: query.trim() }, 0, 8, controller.signal).then(
        (page) => setResults(page.items),
        () => {},
      )
    }, 250)
    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, [query])

  const visible = query.trim().length < 2 ? [] : results
  return (
    <div className="proxy-add">
      <input
        className="input"
        placeholder={t.print.addPlaceholder}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      {visible.length > 0 && (
        <div className="proxy-add-results">
          {visible.map((card) => (
            <button
              key={card.id}
              className="button small"
              onClick={() => {
                onAdd(card)
                setQuery('')
              }}
            >
              + {card.name}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
