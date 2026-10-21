import { useCallback, useEffect, useRef, useState, type DragEvent, type MouseEvent } from 'react'
import {
  api,
  scanItemImageUrl,
  type CardSummary,
  type Location,
  type Scan,
  type ScanItem,
  type ScanItemUpdate,
} from '../api/client'
import { CardImage } from '../components/CardImage'
import { PageScanHeader } from '../components/PageScanHeader'
import { useDebounced } from '../hooks/useDebounced'
import { useHoverPreview } from '../hooks/useHoverPreview'
import { t } from '../i18n'

const ENGINE_KEY = 'mtgdm.ocrEngine'
const AUTO_ACCEPT = 0.9
const ENGINE_LABEL: Record<string, string> = { apple_vision: 'Apple Vision', rapidocr: 'RapidOCR' }
const CONDITIONS = ['M', 'NM', 'EX', 'GD', 'LP', 'PL', 'PO'] as const
const LANGUAGES = ['en', 'pl', 'de', 'fr', 'it', 'es', 'pt', 'ja', 'ko', 'ru', 'zhs', 'zht']

function readStoredEngine(): string | null {
  try {
    return localStorage.getItem(ENGINE_KEY)
  } catch {
    return null
  }
}

export function ScanView() {
  const [scans, setScans] = useState<Scan[] | null>(null)
  const [engines, setEngines] = useState<string[]>([])
  const [engine, setEngine] = useState<string | null>(readStoredEngine)
  const [locations, setLocations] = useState<Location[]>([])
  const [queue, setQueue] = useState<{ done: number; total: number; current: string } | null>(null)
  const [dragging, setDragging] = useState(false)
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null)
  const input = useRef<HTMLInputElement>(null)
  const preview = useHoverPreview()

  const reload = useCallback(() => {
    api.scans().then(setScans, (e: Error) => setMessage({ ok: false, text: e.message }))
  }, [])

  useEffect(() => {
    reload()
    api.scanEngines().then((e) => {
      setEngines(e.available)
      setEngine((current) => (current && e.available.includes(current) ? current : e.default))
    })
    api.locations().then(setLocations, () => setLocations([]))
  }, [reload])

  const chooseEngine = (value: string) => {
    setEngine(value)
    try {
      localStorage.setItem(ENGINE_KEY, value)
    } catch {
      // not persisted
    }
  }

  const uploadFiles = async (files: File[]) => {
    if (!files.length) return
    setMessage(null)
    const errors: string[] = []
    for (const [index, file] of files.entries()) {
      setQueue({ done: index, total: files.length, current: file.name })
      try {
        const created = await api.uploadScan(file, engine ?? undefined)
        setScans((prev) => [...created.reverse(), ...(prev ?? [])])
      } catch (e) {
        errors.push(`${file.name}: ${(e as Error).message}`)
      }
    }
    setQueue(null)
    if (errors.length) setMessage({ ok: false, text: errors.join(' · ') })
  }

  const replaceScan = (scan: Scan) => setScans((prev) => prev?.map((s) => (s.id === scan.id ? scan : s)) ?? null)

  const updateItem = async (scan: Scan, item: ScanItem, body: ScanItemUpdate) => {
    try {
      replaceScan(await api.updateScanItem(scan.id, item.id, body))
    } catch (e) {
      setMessage({ ok: false, text: (e as Error).message })
    }
  }

  const open = (scans ?? []).filter((s) => s.status !== 'committed')
  const pendingConfident = open.flatMap((s) =>
    s.items.filter((i) => i.status === 'pending' && i.chosen && i.confidence >= AUTO_ACCEPT).map((i) => [s, i] as const),
  )
  const acceptedScans = open.filter((s) => s.items.some((i) => i.status === 'accepted'))

  const acceptConfident = async () => {
    for (const [scan, item] of pendingConfident) await updateItem(scan, item, { status: 'accepted' })
  }

  const commitAll = async () => {
    let added = 0
    for (const scan of acceptedScans) {
      try {
        added += (await api.commitScan(scan.id)).added
      } catch (e) {
        setMessage({ ok: false, text: (e as Error).message })
      }
    }
    setMessage({ ok: true, text: t.scan.added(added) })
    reload()
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragging(false)
    uploadFiles([...e.dataTransfer.files])
  }

  return (
    <div className="view scan-view">
      <div className="view-header">
        <h1>{t.scan.title}</h1>
        {engines.length > 1 && (
          <label className="engine-select">
            <span className="muted small">{t.scan.engine}</span>
            <select className="select small" value={engine ?? ''} onChange={(e) => chooseEngine(e.target.value)}>
              {engines.map((name) => (
                <option key={name} value={name}>
                  {ENGINE_LABEL[name] ?? name}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      <div
        className={`drop-zone ${dragging ? 'active' : ''}`}
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => input.current?.click()}
        role="button"
        tabIndex={0}
      >
        <input
          ref={input}
          type="file"
          accept="image/*,.heic,.heif,.pdf,application/pdf"
          multiple
          hidden
          onChange={(e) => {
            const files = [...(e.target.files ?? [])]
            e.target.value = ''
            uploadFiles(files)
          }}
        />
        {queue ? (
          <span>
            {t.scan.recognizing(queue.done + 1, queue.total, queue.current)}
          </span>
        ) : (
          <>
            <strong>{t.scan.dropTitle}</strong>
            <span className="muted small">{t.scan.dropHint}</span>
          </>
        )}
      </div>

      {(pendingConfident.length > 0 || acceptedScans.length > 0) && (
        <div className="actions scan-bulk">
          {pendingConfident.length > 0 && (
            <button className="button" onClick={acceptConfident}>
              {t.scan.acceptConfident(Math.round(AUTO_ACCEPT * 100), pendingConfident.length)}
            </button>
          )}
          {acceptedScans.length > 0 && (
            <button className="button primary" onClick={commitAll}>
              {t.scan.commitAccepted}
            </button>
          )}
        </div>
      )}
      {message && <p className={`status ${message.ok ? 'ok' : 'error'}`}>{message.text}</p>}

      {scans === null ? (
        <p className="muted">{t.common.loading}</p>
      ) : scans.length === 0 ? (
        <p className="muted">{t.scan.empty}</p>
      ) : (
        <div className="scan-list">
          {scans.map((scan) => [
            scan.kind === 'page' && (
              <PageScanHeader
                key={`page-${scan.id}`}
                scan={scan}
                onChange={replaceScan}
                onError={(text) => setMessage({ ok: false, text })}
              />
            ),
            ...scan.items.map((item, index) => (
              <ScanItemCard
                key={item.id}
                scan={scan}
                item={item}
                number={scan.kind === 'page' ? index + 1 : null}
                locations={locations}
                onUpdate={(body) => updateItem(scan, item, body)}
                onDelete={async () => {
                  await api.deleteScan(scan.id)
                  setScans((prev) => prev?.filter((s) => s.id !== scan.id) ?? null)
                }}
                onHover={preview.show}
              />
            )),
          ])}
        </div>
      )}
      {preview.element}
    </div>
  )
}

function confidenceClass(value: number): string {
  return value >= AUTO_ACCEPT ? 'ok' : value >= 0.7 ? 'warn' : 'error'
}

function ScanItemCard({
  scan,
  item,
  number,
  locations,
  onUpdate,
  onDelete,
  onHover,
}: {
  scan: Scan
  item: ScanItem
  number: number | null
  locations: Location[]
  onUpdate: (body: ScanItemUpdate) => void
  onDelete: () => void
  onHover: (card: CardSummary | null, event?: MouseEvent) => void
}) {
  const [searching, setSearching] = useState(false)
  const committed = scan.status === 'committed'
  const chosen = item.chosen
  const alternatives = item.candidates.filter((c) => c.card.id !== chosen?.id)

  return (
    <div className={`scan-item ${item.status} ${committed ? 'committed' : ''}`}>
      <div className="scan-images">
        <img className="scan-crop" src={scanItemImageUrl(scan.id, item.id)} alt={t.scan.scannedCard} />
        <div className="scan-match">
          {chosen ? (
            <CardImage cardId={chosen.id} name={chosen.name} size="normal" hasImage={chosen.image_faces > 0} />
          ) : (
            <div className="card-image placeholder">
              <span className="card-image-name">{t.scan.notRecognized}</span>
            </div>
          )}
        </div>
      </div>

      <div className="scan-body">
        <div className="scan-title">
          {number !== null && <span className="page-number">{number}</span>}
          <strong>{chosen?.name ?? t.scan.notRecognizedCard}</strong>
          {chosen && (
            <span className="muted">
              {chosen.set_name} ({chosen.set_code.toUpperCase()}) #{chosen.collector_number}
            </span>
          )}
          <span className={`pill ${confidenceClass(item.confidence)}`}>{Math.round(item.confidence * 100)}%</span>
        </div>
        <p className="muted small">
          {t.scan.read(item.ocr_name ?? '—')}
          {item.ocr_number && ` · #${item.ocr_number}`}
          {item.ocr_set && ` · ${item.ocr_set.toUpperCase()}`}
          {item.candidates[0]?.reasons.length ? ` · ${item.candidates[0].reasons.join(', ')}` : ''}
        </p>

        {!committed && alternatives.length > 0 && (
          <div className="scan-alternatives">
            <span className="muted small">{t.importer.maybe}</span>
            {alternatives.map((alt) => (
              <button
                key={alt.card.id}
                className="chip"
                onClick={() => onUpdate({ chosen_card_id: alt.card.id })}
                onMouseEnter={(e) => onHover(alt.card, e)}
                onMouseLeave={() => onHover(null)}
              >
                {alt.card.name} · {alt.card.set_code.toUpperCase()} #{alt.card.collector_number} (
                {Math.round(alt.score * 100)}%)
              </button>
            ))}
          </div>
        )}
        {!committed &&
          (searching ? (
            <CardSearch
              onPick={(card) => {
                setSearching(false)
                onUpdate({ chosen_card_id: card.id })
              }}
              onCancel={() => setSearching(false)}
              initial={item.ocr_name ?? ''}
              onHover={onHover}
            />
          ) : (
            <div className="scan-links">
              <button className="link-button" onClick={() => setSearching(true)}>
                {t.scan.otherCard}
              </button>
            </div>
          ))}

        {!committed && (
          <div className="scan-attributes">
            <label>
              {t.items.quantity}
              <input
                className="input small qty-input"
                type="number"
                min={1}
                value={item.quantity}
                onChange={(e) => onUpdate({ quantity: Math.max(1, Number(e.target.value) || 1) })}
              />
            </label>
            <label>
              {t.items.finish}
              <select
                className="select small"
                value={item.finish}
                onChange={(e) => onUpdate({ finish: e.target.value as ScanItem['finish'] })}
              >
                <option value="nonfoil">{t.items.finishNonfoil}</option>
                <option value="foil">foil</option>
                <option value="etched">etched</option>
              </select>
            </label>
            <label>
              {t.items.language}
              <select
                className="select small"
                value={item.language ?? chosen?.lang ?? 'en'}
                onChange={(e) => onUpdate({ language: e.target.value })}
              >
                {[...new Set([item.language ?? chosen?.lang ?? 'en', ...LANGUAGES])].map((l) => (
                  <option key={l} value={l}>
                    {l}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t.items.condition}
              <select
                className="select small"
                value={item.condition}
                onChange={(e) => onUpdate({ condition: e.target.value as ScanItem['condition'] })}
              >
                {CONDITIONS.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t.items.location}
              <select
                className="select small"
                value={item.location_id ?? ''}
                onChange={(e) => onUpdate({ location_id: e.target.value ? Number(e.target.value) : null })}
              >
                <option value="">—</option>
                {locations.map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
        )}

        <div className="actions compact">
          {committed ? (
            <span className="status ok small">{t.scan.inCollection}</span>
          ) : (
            <>
              <button
                className={`button ${item.status === 'accepted' ? 'primary' : ''}`}
                onClick={() => onUpdate({ status: item.status === 'accepted' ? 'pending' : 'accepted' })}
                disabled={!chosen}
              >
                {item.status === 'accepted' ? t.scan.accepted : t.scan.accept}
              </button>
              <button
                className={`button ${item.status === 'rejected' ? 'danger-active' : ''}`}
                onClick={() => onUpdate({ status: item.status === 'rejected' ? 'pending' : 'rejected' })}
              >
                {item.status === 'rejected' ? t.scan.rejected : t.scan.reject}
              </button>
            </>
          )}
          <button className="link-button danger" onClick={onDelete} title={t.scan.deleteScanTitle}>
            {t.scan.deleteScan}
          </button>
        </div>
      </div>
    </div>
  )
}

function CardSearch({
  initial,
  onPick,
  onCancel,
  onHover,
}: {
  initial: string
  onPick: (card: CardSummary) => void
  onCancel: () => void
  onHover: (card: CardSummary | null, event?: MouseEvent) => void
}) {
  const [query, setQuery] = useState(initial)
  const [results, setResults] = useState<CardSummary[]>([])
  const debounced = useDebounced(query, 250)

  useEffect(() => {
    if (!debounced.trim()) return
    let cancelled = false
    api.searchCards({ q: debounced, unique: 'prints', game: 'paper', order: 'released' }, 1, 30).then(
      (page) => !cancelled && setResults(page.items),
      () => !cancelled && setResults([]),
    )
    return () => {
      cancelled = true
    }
  }, [debounced])

  return (
    <div className="scan-search">
      <div className="filter-row">
        <input
          className="input search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t.scan.searchPlaceholder}
          autoFocus
        />
        <button className="link-button" onClick={onCancel}>
          {t.common.cancel}
        </button>
      </div>
      <div className="scan-search-results">
        {results.map((card) => (
          <button
            key={card.id}
            className="printing"
            onClick={() => onPick(card)}
            onMouseEnter={(e) => onHover(card, e)}
            onMouseLeave={() => onHover(null)}
            title={`${card.name} · ${card.set_name} #${card.collector_number}`}
          >
            <CardImage cardId={card.id} name={card.name} size="small" hasImage={card.image_faces > 0} />
            <span className="printing-label">
              {card.set_code.toUpperCase()} #{card.collector_number}
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}
