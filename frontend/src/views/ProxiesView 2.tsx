import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  api,
  type CardSummary,
  type CollectionItem,
  type Location,
  type PrintHistory,
  type ReplaceWithReal,
} from '../api/client'
import { ProxyDialog } from '../components/ProxyDialog'
import { useHoverPreview } from '../hooks/useHoverPreview'
import { locale, t } from '../i18n'
import { printQueue, type QueuedCard } from '../printQueue'

const CONDITIONS = ['M', 'NM', 'EX', 'GD', 'LP', 'PL', 'PO'] as const
const FINISHES = [
  ['nonfoil', t.items.finishNonfoil],
  ['foil', t.items.finishFoil],
  ['etched', t.items.finishEtched],
] as const

function date(iso: string | null | undefined): string {
  // SQLite datetime('now') is UTC without a zone marker.
  return iso ? new Date(iso.includes('T') ? iso : `${iso.replace(' ', 'T')}Z`).toLocaleDateString(locale) : '—'
}

/** Collection › Proxies: every printed proxy, where it is, whether you own the real card by now,
and what to do with it (replace with the real card, move, remove, print again); plus past prints. */
export function ProxiesView() {
  const [proxies, setProxies] = useState<CollectionItem[] | null>(null)
  const [real, setReal] = useState<CollectionItem[]>([])
  const [locations, setLocations] = useState<Location[]>([])
  const [history, setHistory] = useState<PrintHistory[]>([])
  const [version, setVersion] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [locationFilter, setLocationFilter] = useState<number | 'all'>('all')
  const [ownedOnly, setOwnedOnly] = useState(false)
  const [jobFilter, setJobFilter] = useState<number | 'all'>('all')
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [moveTo, setMoveTo] = useState<number | ''>('')
  const [replacing, setReplacing] = useState<CollectionItem | null>(null)
  const [reprinting, setReprinting] = useState(false)
  const preview = useHoverPreview()

  useEffect(() => {
    let cancelled = false
    Promise.all([
      api.collection({ kind: 'proxy' }),
      api.collection({ kind: 'real' }),
      api.locations(),
      api.printHistory(),
    ]).then(
      ([p, r, l, h]) => {
        if (cancelled) return
        setProxies(p)
        setReal(r)
        setLocations(l)
        setHistory(h)
      },
      (e: Error) => !cancelled && setError(e.message),
    )
    return () => {
      cancelled = true
    }
  }, [version])

  const run = useCallback(async (action: () => Promise<unknown>) => {
    setError(null)
    try {
      await action()
    } catch (e) {
      setError((e as Error).message)
    }
    setSelected(new Set())
    setVersion((v) => v + 1)
  }, [])

  // Real copies per card (oracle id): "do I own it by now, and where?"
  const realByOracle = useMemo(() => {
    const map = new Map<string, CollectionItem[]>()
    for (const item of real) {
      const key = item.card.oracle_id ?? item.card.id
      map.set(key, [...(map.get(key) ?? []), item])
    }
    return map
  }, [real])
  const realOf = (item: CollectionItem) => realByOracle.get(item.card.oracle_id ?? item.card.id) ?? []
  const jobTitle = new Map(history.map((h) => [h.id, `${h.title} · ${date(h.created_at)}`]))
  const jobName = new Map(history.map((h) => [h.id, h.title]))

  const visible = (proxies ?? []).filter(
    (p) =>
      (locationFilter === 'all' || p.location?.id === locationFilter) &&
      (jobFilter === 'all' || p.print_job_id === jobFilter) &&
      (!ownedOnly || realOf(p).length > 0),
  )
  const chosen = visible.filter((p) => selected.has(p.id))
  const proxyLocations = locations.filter((l) => (proxies ?? []).some((p) => p.location?.id === l.id))
  const toggle = (id: number) =>
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  // Print again: the cards go to the collection's print list, and the print dialog opens with it.
  const reprint = (items: QueuedCard[]) => {
    printQueue.replace(items)
    setReprinting(true)
  }

  if (error && proxies === null) return <p className="status error">{error}</p>
  if (proxies === null) return <p className="muted">{t.common.loading}</p>

  return (
    <div className="view proxies-view">
      <p className="muted small">{t.proxies.intro}</p>

      <div className="proxies-filters">
        <select
          className="select small"
          value={locationFilter}
          onChange={(e) => setLocationFilter(e.target.value === 'all' ? 'all' : Number(e.target.value))}
          aria-label={t.proxies.location}
        >
          <option value="all">{t.proxies.allLocations}</option>
          {proxyLocations.map((l) => (
            <option key={l.id} value={l.id}>
              {l.name}
            </option>
          ))}
        </select>
        <select
          className="select small"
          value={jobFilter}
          onChange={(e) => setJobFilter(e.target.value === 'all' ? 'all' : Number(e.target.value))}
          aria-label={t.proxies.print}
        >
          <option value="all">{t.proxies.allPrints}</option>
          {history
            .filter((h) => (proxies ?? []).some((p) => p.print_job_id === h.id))
            .map((h) => (
              <option key={h.id} value={h.id}>
                {jobTitle.get(h.id)}
              </option>
            ))}
        </select>
        <label className="checkbox small">
          <input type="checkbox" checked={ownedOnly} onChange={(e) => setOwnedOnly(e.target.checked)} />
          {t.proxies.ownedOnly}
        </label>
        <span className="muted small">{t.proxies.count(visible.reduce((n, p) => n + p.quantity, 0))}</span>
      </div>

      {chosen.length > 0 && (
        <div className="proxies-bulk">
          <span className="small">{t.proxies.selected(chosen.length)}</span>
          <button
            className="button"
            onClick={() => run(async () => {
              for (const p of chosen) for (let i = 0; i < p.quantity; i++) await api.replaceWithReal(p.id, {})
            })}
            title={t.proxies.replaceAllTitle}
          >
            {t.proxies.replace}
          </button>
          <select className="select small" value={moveTo} onChange={(e) => setMoveTo(e.target.value ? Number(e.target.value) : '')}>
            <option value="">{t.proxies.moveTo}</option>
            {locations.map((l) => (
              <option key={l.id} value={l.id}>
                {l.name}
              </option>
            ))}
          </select>
          <button
            className="button"
            disabled={moveTo === ''}
            onClick={() => run(async () => {
              for (const p of chosen) await api.updateCollectionItem(p.id, { location_id: moveTo === '' ? null : moveTo })
            })}
          >
            {t.proxies.move}
          </button>
          <button
            className="button"
            onClick={() =>
              reprint(
                chosen.map((p) => ({
                  card_id: p.card.id,
                  name: p.card.name,
                  faces: Math.max(1, p.card.image_faces),
                  qty: p.quantity,
                  printing: `${p.card.set_code.toUpperCase()} #${p.card.collector_number}`,
                })),
              )
            }
          >
            {t.proxies.reprint}
          </button>
          <button
            className="button danger-text"
            onClick={() =>
              window.confirm(t.proxies.confirmRemove(chosen.reduce((n, p) => n + p.quantity, 0))) &&
              run(async () => {
                for (const p of chosen) await api.removeFromCollection(p.id)
              })
            }
          >
            {t.proxies.remove}
          </button>
        </div>
      )}

      {visible.length === 0 ? (
        <p className="muted">{proxies.length ? t.proxies.noneFiltered : t.proxies.none}</p>
      ) : (
        <table className="items-table proxies-table">
          <thead>
            <tr>
              <th>
                <input
                  type="checkbox"
                  checked={chosen.length === visible.length}
                  onChange={(e) => setSelected(new Set(e.target.checked ? visible.map((p) => p.id) : []))}
                  aria-label={t.proxies.selectAll}
                />
              </th>
              <th className="num">#</th>
              <th>{t.proxies.card}</th>
              <th>{t.proxies.location}</th>
              <th>{t.proxies.printed}</th>
              <th>{t.proxies.realOwned}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {visible.map((p) => {
              const copies = realOf(p)
              return (
                <tr key={p.id} className={selected.has(p.id) ? 'selected' : ''}>
                  <td>
                    <input type="checkbox" checked={selected.has(p.id)} onChange={() => toggle(p.id)} aria-label={p.card.name} />
                  </td>
                  <td className="num">{p.quantity}</td>
                  <td onMouseEnter={(e) => preview.show(p.card, e)} onMouseLeave={() => preview.show(null)}>
                    {p.card.name}{' '}
                    <span className="muted small">
                      {p.card.set_code.toUpperCase()} #{p.card.collector_number}
                    </span>
                  </td>
                  <td>{p.location?.name ?? <span className="muted">{t.common.noLocation}</span>}</td>
                  <td className="small">
                    {date(p.printed_at)}
                    {p.print_job_id && jobName.has(p.print_job_id) && (
                      <div className="muted">{jobName.get(p.print_job_id)}</div>
                    )}
                  </td>
                  <td className="small">
                    {copies.length === 0 ? (
                      <span className="muted">{t.proxies.no}</span>
                    ) : (
                      <span className="ok-text">
                        {t.proxies.yes}:{' '}
                        {copies.map((c) => `${c.quantity}× ${c.location?.name ?? t.proxies.loose}`).join(', ')}
                      </span>
                    )}
                  </td>
                  <td className="row-actions">
                    <button className="link-button small" onClick={() => setReplacing(p)}>
                      {t.proxies.replace}
                    </button>
                    <button
                      className="link-button danger small"
                      onClick={() => window.confirm(t.proxies.confirmRemove(p.quantity)) && run(() => api.removeFromCollection(p.id))}
                      aria-label={t.proxies.remove}
                      title={t.proxies.remove}
                    >
                      ×
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
      {error && <p className="status error">{error}</p>}

      <h2 className="proxies-history-title">{t.proxies.history}</h2>
      {history.length === 0 ? (
        <p className="muted small">{t.proxies.noHistory}</p>
      ) : (
        <table className="items-table">
          <thead>
            <tr>
              <th>{t.proxies.printed}</th>
              <th>{t.proxies.print}</th>
              <th className="num">{t.proxies.cards}</th>
              <th>{t.proxies.marked}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {history.map((h) => (
              <HistoryRow
                key={h.id}
                entry={h}
                locations={locations}
                onMark={(locationId) => run(() => api.markProxies(h.id, { location_id: locationId }))}
                onReprint={() =>
                  reprint(h.items.map((i) => ({ card_id: i.card_id, name: i.name, faces: 1, qty: i.qty, printing: i.printing })))
                }
              />
            ))}
          </tbody>
        </table>
      )}

      {replacing && (
        <ReplaceDialog
          proxy={replacing}
          loose={realOf(replacing).filter((c) => c.location === null)}
          onClose={() => setReplacing(null)}
          onReplace={(body) => {
            setReplacing(null)
            return run(() => api.replaceWithReal(replacing.id, body))
          }}
        />
      )}
      {reprinting && (
        <ProxyDialog
          deckId={null}
          onClose={() => {
            setReprinting(false)
            setVersion((v) => v + 1)
          }}
        />
      )}
      {preview.element}
    </div>
  )
}

function HistoryRow({
  entry,
  locations,
  onMark,
  onReprint,
}: {
  entry: PrintHistory
  locations: Location[]
  onMark: (locationId: number | null) => void
  onReprint: () => void
}) {
  const [locationId, setLocationId] = useState<number | ''>('')
  return (
    <tr>
      <td className="small">{date(entry.created_at)}</td>
      <td>
        {entry.title}
        {entry.deck_name && entry.deck_name !== entry.title && <span className="muted small"> · {entry.deck_name}</span>}
        <div className="muted small" title={entry.items.map((i) => `${i.qty} ${i.name}`).join('\n')}>
          {entry.items.slice(0, 4).map((i) => i.name).join(', ')}
          {entry.items.length > 4 && ` +${entry.items.length - 4}`}
        </div>
      </td>
      <td className="num">{entry.card_count}</td>
      <td className="small">{entry.proxies ? t.proxies.markedCount(entry.proxies) : <span className="muted">—</span>}</td>
      <td className="row-actions">
        {entry.deck_id !== null ? (
          <button className="link-button small" onClick={() => onMark(null)} title={t.proxies.markDeckTitle}>
            {t.proxies.mark}
          </button>
        ) : (
          <>
            <select
              className="select small"
              value={locationId}
              onChange={(e) => setLocationId(e.target.value ? Number(e.target.value) : '')}
              aria-label={t.proxies.location}
            >
              <option value="">{t.proxies.markWhere}</option>
              {locations.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name}
                </option>
              ))}
            </select>
            <button className="link-button small" disabled={locationId === ''} onClick={() => onMark(locationId === '' ? null : locationId)}>
              {t.proxies.mark}
            </button>
          </>
        )}
        <button className="link-button small" onClick={onReprint}>
          {t.proxies.reprint}
        </button>
      </td>
    </tr>
  )
}

/** One copy of a proxy becomes real: a loose copy you have moves in, or a new copy is recorded. */
function ReplaceDialog({
  proxy,
  loose,
  onClose,
  onReplace,
}: {
  proxy: CollectionItem
  loose: CollectionItem[]
  onClose: () => void
  onReplace: (body: ReplaceWithReal) => void
}) {
  const [useExisting, setUseExisting] = useState<number | null>(loose[0]?.id ?? null)
  const [printings, setPrintings] = useState<CardSummary[]>([])
  const [cardId, setCardId] = useState(proxy.card.id)
  const [finish, setFinish] = useState<ReplaceWithReal['finish']>('nonfoil')
  const [condition, setCondition] = useState<ReplaceWithReal['condition']>('NM')
  const [language, setLanguage] = useState(proxy.card.lang)

  useEffect(() => {
    api.printings(proxy.card.id).then(setPrintings, () => setPrintings([]))
  }, [proxy.card.id])

  return (
    <div className="modal-backdrop centered" onClick={onClose}>
      <div className="dialog" onClick={(e) => e.stopPropagation()} role="dialog" aria-label={t.proxies.replaceTitle}>
        <div className="dialog-header">
          <h2>{t.proxies.replaceTitle}</h2>
          <button className="close-button static" onClick={onClose} aria-label={t.common.close}>
            ×
          </button>
        </div>
        <p className="small">{t.proxies.replaceIntro(proxy.card.name, proxy.location?.name ?? t.common.noLocation)}</p>
        {loose.length > 0 && (
          <>
            {loose.map((c) => (
              <label key={c.id} className="checkbox small">
                <input type="radio" checked={useExisting === c.id} onChange={() => setUseExisting(c.id)} />
                {t.proxies.useLoose(`${c.card.set_code.toUpperCase()} #${c.card.collector_number}`, c.condition, c.quantity)}
              </label>
            ))}
            <label className="checkbox small">
              <input type="radio" checked={useExisting === null} onChange={() => setUseExisting(null)} />
              {t.proxies.newCopy}
            </label>
          </>
        )}
        {useExisting === null && (
          <div className="form-row">
            <label>
              {t.proxies.printing}
              <select className="select small" value={cardId} onChange={(e) => setCardId(e.target.value)}>
                {printings.length === 0 && <option value={proxy.card.id}>{proxy.card.set_code.toUpperCase()}</option>}
                {printings.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.set_code.toUpperCase()} #{p.collector_number} · {p.set_name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t.proxies.finish}
              <select className="select small" value={finish ?? 'nonfoil'} onChange={(e) => setFinish(e.target.value as ReplaceWithReal['finish'])}>
                {FINISHES.map(([id, label]) => (
                  <option key={id} value={id}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t.proxies.condition}
              <select className="select small" value={condition} onChange={(e) => setCondition(e.target.value as ReplaceWithReal['condition'])}>
                {CONDITIONS.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t.proxies.language}
              <input className="input small" value={language} onChange={(e) => setLanguage(e.target.value)} />
            </label>
          </div>
        )}
        <div className="actions">
          <button
            className="button primary"
            onClick={() =>
              onReplace(
                useExisting !== null
                  ? { use_existing_item_id: useExisting }
                  : { card_id: cardId, finish, condition, language: language || null },
              )
            }
          >
            {t.proxies.replaceConfirm}
          </button>
        </div>
      </div>
    </div>
  )
}
