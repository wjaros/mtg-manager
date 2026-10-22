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
import { printQueue } from '../printQueue'

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

/** The collection's print list as dialog rows. */
function queuedRows(): Row[] {
  return printQueue.items().map((q) => ({
    key: `extra-${q.card_id}`,
    card_id: q.card_id,
    name: q.name,
    reason: 'extra' as Reason,
    qty: q.qty,
    checked: true,
    faces: q.faces,
    other_decks: [],
    image_status: null,
  }))
}

interface Props {
  deckId: number | null // null: any cards, picked by hand (from the collection page)
  deckName?: string
  onClose: () => void
}

/** Print proxies for the cards this deck's box lacks (not owned, or sitting in another deck's box),
the tokens it makes, and any card added by hand; without a deck, just the cards you add. */
export function ProxyDialog({ deckId, deckName = '', onClose }: Props) {
  // Without a deck the cards come from (and go back to) the collection's print list.
  const [rows, setRows] = useState<Row[] | null>(() => (deckId === null ? queuedRows() : null))
  useEffect(() => {
    if (deckId !== null || rows === null) return
    printQueue.replace(rows.map((r) => ({ card_id: r.card_id, name: r.name, faces: r.faces, qty: r.qty })))
  }, [deckId, rows])
  const [includeBasics, setIncludeBasics] = useState(false)
  const [frontOnly, setFrontOnly] = useState(false)
  const [profiles, setProfiles] = useState<PrinterProfile[]>([])
  const [profileId, setProfileId] = useState<number | null>(null)
  const [paper, setPaper] = useState<Paper>('a4')
  const [gap, setGap] = useState(0)
  const [cutMarks, setCutMarks] = useState(true)
  const [duplex, setDuplex] = useState<Duplex>('off')
  const [style, setStyle] = useState<'image' | 'text'>('image')
  const [job, setJob] = useState<PrintJobStatus | null>(null)
  const [overflow, setOverflow] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (deckId === null) return
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
    if (deckId === null) return
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

  // A card added again (or twice in a pasted list) adds to its row.
  const addExtra = (card: CardSummary, qty = 1) =>
    setRows((prev) => {
      const list = prev ?? []
      const same = list.find((r) => r.reason === 'extra' && r.card_id === card.id)
      if (same) return list.map((r) => (r === same ? { ...r, qty: Math.min(99, r.qty + qty), checked: true } : r))
      return [
        ...list,
        {
          key: `extra-${card.id}`,
          card_id: card.id,
          name: card.name,
          reason: 'extra',
          qty: Math.min(99, qty),
          checked: true,
          faces: Math.max(1, card.image_faces),
          other_decks: [],
          image_status: null,
        },
      ]
    })

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
        style,
        title: deckName || t.print.title,
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
        <p className="muted small">{deckId === null ? t.print.introFree : t.print.intro}</p>

        {rows === null ? (
          <p className="muted">{t.common.loading}</p>
        ) : (
          REASONS.map((reason) => {
            const group = rows.filter((r) => r.reason === reason)
            if (group.length === 0) return null
            return (
              <section key={reason} className="proxy-group">
                <h3>
                  <input
                    type="checkbox"
                    className="group-check"
                    checked={group.every((r) => r.checked)}
                    onChange={(e) => {
                      const checked = e.target.checked
                      setRows((prev) => prev && prev.map((r) => (r.reason === reason ? { ...r, checked } : r)))
                    }}
                    aria-label={t.print.selectGroup}
                    title={t.print.selectGroup}
                  />
                  {t.print.reason[reason]}{' '}
                  <span className="muted">
                    ({reason === 'token' ? group.length : group.reduce((n, r) => n + r.qty, 0)})
                  </span>
                  {reason === 'token' && <span className="muted small"> · {t.print.tokensHint}</span>}
                </h3>
                {group.map((row) => (
                  <ProxyRow
                    key={row.key}
                    row={row}
                    onChange={(change) => update(row.key, change)}
                    onRemove={
                      row.reason === 'extra'
                        ? () => setRows((prev) => prev && prev.filter((r) => r.key !== row.key))
                        : undefined
                    }
                  />
                ))}
              </section>
            )
          })
        )}
        {deckId !== null && rows !== null && !rows.some((r) => r.reason === 'missing' || r.reason === 'in_other_deck') && (
          <p className="muted">{t.print.nothingMissing}</p>
        )}

        <AddCard onAdd={addExtra} />
        {deckId === null && (rows ?? []).length > 0 && (
          <button className="link-button small" onClick={() => setRows([])}>
            {t.print.clearList}
          </button>
        )}

        <div className="proxy-options">
          {deckId !== null && (
            <label className="checkbox">
              <input type="checkbox" checked={includeBasics} onChange={(e) => setIncludeBasics(e.target.checked)} />
              {t.print.includeBasics}
            </label>
          )}
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
            {t.print.style}{' '}
            <select className="select small" value={style} onChange={(e) => setStyle(e.target.value as 'image' | 'text')}>
              <option value="image">{t.print.styleImage}</option>
              <option value="text">{t.print.styleText}</option>
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

function ProxyRow({
  row,
  onChange,
  onRemove,
}: {
  row: Row
  onChange: (change: Partial<Row>) => void
  onRemove?: () => void
}) {
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
      {onRemove && (
        <button className="link-button danger" onClick={onRemove} aria-label={t.common.delete} title={t.common.delete}>
          ×
        </button>
      )}
    </div>
  )
}

function AddCard({ onAdd }: { onAdd: (card: CardSummary, qty?: number) => void }) {
  const [query, setQuery] = useState('')
  const [pasting, setPasting] = useState(false)
  const [list, setList] = useState('')
  const [notFound, setNotFound] = useState<string[]>([])
  const [results, setResults] = useState<CardSummary[]>([])
  const abort = useRef<AbortController | null>(null)

  useEffect(() => {
    abort.current?.abort()
    if (query.trim().length < 2) return
    const controller = new AbortController()
    abort.current = controller
    const timer = setTimeout(() => {
      // Tokens too: they're printed like any card.
      api.searchCards({ q: query.trim(), include_extras: true }, 0, 8, controller.signal).then(
        (page) => setResults(page.items),
        () => {},
      )
    }, 250)
    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, [query])

  // A pasted list ("4 Lightning Bolt (2X2) 117", Arena / Moxfield style): exact printings when given.
  const [listError, setListError] = useState<string | null>(null)
  const addList = async () => {
    setListError(null)
    try {
      const report = await api.parseImport(list)
      for (const line of report.lines) if (line.card) onAdd(line.card, line.quantity)
      setNotFound(report.lines.filter((l) => !l.card).map((l) => l.name))
      setList('')
      setPasting(false)
    } catch (e) {
      setListError((e as Error).message)
    }
  }

  const visible = query.trim().length < 2 ? [] : results
  return (
    <div className="proxy-add">
      <div className="proxy-add-bar">
        <input
          className="input"
          placeholder={t.print.addPlaceholder}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <button className="button" onClick={() => setPasting(!pasting)}>
          {t.print.pasteList}
        </button>
      </div>
      {pasting && (
        <div className="proxy-paste">
          <textarea
            className="input decklist"
            rows={6}
            placeholder={t.print.pastePlaceholder}
            value={list}
            onChange={(e) => setList(e.target.value)}
          />
          <button className="button primary" onClick={addList} disabled={!list.trim()}>
            {t.print.addList}
          </button>
        </div>
      )}
      {notFound.length > 0 && <p className="status warn">{t.print.notFound(notFound.join(', '))}</p>}
      {listError && <p className="status error">{listError}</p>}
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
