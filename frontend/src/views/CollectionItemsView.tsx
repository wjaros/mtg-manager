import { useCallback, useEffect, useState } from 'react'
import { api, collectionExportUrl, type CollectionItem, type CollectionItemUpdate, type Location } from '../api/client'
import { copyText } from '../clipboard'
import { useDebounced } from '../hooks/useDebounced'
import { useHoverPreview } from '../hooks/useHoverPreview'
import { t } from '../i18n'

const CONDITIONS = ['M', 'NM', 'EX', 'GD', 'LP', 'PL', 'PO'] as const
const FINISHES = [
  ['nonfoil', t.items.finishNonfoil],
  ['foil', t.items.finishFoil],
  ['etched', t.items.finishEtched],
] as const
const LANGUAGES = ['en', 'pl', 'de', 'fr', 'it', 'es', 'pt', 'ja', 'ko', 'ru', 'zhs', 'zht', 'ph']

/** 'all' | 'none' (no location) | location id */
export type LocationFilter = 'all' | 'none' | number

interface Props {
  location: LocationFilter
  onLocationChange: (location: LocationFilter) => void
}

/** Every physical copy in the collection, editable in place. */
export function CollectionItemsView({ location, onLocationChange }: Props) {
  const [items, setItems] = useState<CollectionItem[] | null>(null)
  const [locations, setLocations] = useState<Location[]>([])
  const [query, setQuery] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [version, setVersion] = useState(0)
  const debouncedQuery = useDebounced(query, 250)
  const preview = useHoverPreview()

  useEffect(() => {
    api.locations().then(setLocations, () => setLocations([]))
  }, [version])

  useEffect(() => {
    let cancelled = false
    api
      .collection({
        q: debouncedQuery || undefined,
        location_id: typeof location === 'number' ? location : undefined,
        unassigned: location === 'none' || undefined,
        kind: 'real', // proxies have their own tab
      })
      .then(
        (list) => !cancelled && setItems(list),
        (e: Error) => !cancelled && setError(e.message),
      )
    return () => {
      cancelled = true
    }
  }, [debouncedQuery, location, version])

  const run = useCallback(async (action: () => Promise<unknown>) => {
    setError(null)
    try {
      await action()
      setVersion((v) => v + 1)
    } catch (e) {
      setError((e as Error).message)
    }
  }, [])

  const [copied, setCopied] = useState(false)
  const exportFilter = {
    location_id: typeof location === 'number' ? location : undefined,
    unassigned: location === 'none' || undefined,
  }
  const copyArenaList = async () => {
    try {
      const response = await fetch(collectionExportUrl('arena', exportFilter))
      if (!response.ok) throw new Error(response.statusText)
      await copyText(await response.text())
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const update = (item: CollectionItem, body: CollectionItemUpdate) => run(() => api.updateCollectionItem(item.id, body))
  const total = items?.reduce((n, i) => n + i.quantity, 0) ?? 0

  return (
    <div className="view items-view">
      <div className="filter-row items-filters">
        <input
          className="input search"
          type="search"
          placeholder={t.items.searchPlaceholder}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <select
          className="select"
          value={String(location)}
          onChange={(e) => {
            const v = e.target.value
            onLocationChange(v === 'all' || v === 'none' ? v : Number(v))
          }}
          aria-label={t.items.location}
        >
          <option value="all">{t.items.allLocations}</option>
          <option value="none">{t.items.noLocation}</option>
          {locations.map((l) => (
            <option key={l.id} value={l.id}>
              {l.name} ({l.card_count}
              {l.proxy_count ? ` + ${l.proxy_count} proxy` : ''})
            </option>
          ))}
        </select>
        <span className="muted small">
          {items === null ? t.common.loading : t.items.summary(items.length, total)}
        </span>
        <span className="items-export" title={t.items.exportTitle}>
          <button className="button small" onClick={copyArenaList} disabled={!items?.length}>
            {copied ? t.common.copied : t.items.copyArena}
          </button>
          <a className="button small" href={collectionExportUrl('arena', exportFilter, true)} download>
            .txt
          </a>
          <a className="button small" href={collectionExportUrl('csv', exportFilter)} download>
            CSV
          </a>
          <a
            className="button small"
            href={collectionExportUrl('moxfield', exportFilter)}
            download
            title={t.collectionImport.exportMoxfieldTitle}
          >
            {t.collectionImport.exportMoxfield}
          </a>
        </span>
      </div>
      {error && <p className="status error">{error}</p>}

      {items && items.length === 0 ? (
        <p className="muted">{t.items.empty}</p>
      ) : (
        <table className="items-table">
          <thead>
            <tr>
              <th className="num">{t.items.quantity}</th>
              <th>{t.items.card}</th>
              <th>{t.items.printing}</th>
              <th>{t.items.finish}</th>
              <th>{t.items.language}</th>
              <th>{t.items.condition}</th>
              <th>{t.items.location}</th>
              <th>{t.items.note}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {items?.map((item) => (
              <tr key={item.id}>
                <td className="num nowrap">
                  <span className="deck-row-actions visible">
                    <button onClick={() => run(() => api.removeFromCollection(item.id, 1))} title={t.items.removeOne}>
                      −
                    </button>
                    <span className="qty">{item.quantity}</span>
                    <button onClick={() => update(item, { quantity: item.quantity + 1 })} title={t.items.addOne}>
                      +
                    </button>
                  </span>
                </td>
                <td onMouseEnter={(e) => preview.show(item.card, e)} onMouseLeave={() => preview.show(null)}>
                  {item.card.name}
                </td>
                <td className="muted nowrap">
                  {item.card.set_code.toUpperCase()} #{item.card.collector_number}
                </td>
                <td>
                  <select
                    className="select small"
                    value={item.finish}
                    onChange={(e) => update(item, { finish: e.target.value as CollectionItem['finish'] })}
                    aria-label={t.items.finish}
                  >
                    {FINISHES.map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <select
                    className="select small"
                    value={item.language}
                    onChange={(e) => update(item, { language: e.target.value })}
                    aria-label={t.items.language}
                  >
                    {[...new Set([item.language, ...LANGUAGES])].map((lang) => (
                      <option key={lang} value={lang}>
                        {lang}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <select
                    className="select small"
                    value={item.condition}
                    onChange={(e) => update(item, { condition: e.target.value as CollectionItem['condition'] })}
                    aria-label={t.items.condition}
                  >
                    {CONDITIONS.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <select
                    className="select small"
                    value={item.location?.id ?? ''}
                    onChange={(e) => update(item, { location_id: e.target.value ? Number(e.target.value) : null })}
                    aria-label={t.items.location}
                  >
                    <option value="">—</option>
                    {locations.map((l) => (
                      <option key={l.id} value={l.id}>
                        {l.name}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <input
                    className="input small note-input"
                    defaultValue={item.note ?? ''}
                    placeholder="—"
                    onBlur={(e) => {
                      const note = e.target.value.trim() || null
                      if (note !== (item.note ?? null)) update(item, { note })
                    }}
                    aria-label={t.items.note}
                  />
                </td>
                <td>
                  <button
                    className="link-button danger"
                    onClick={() => run(() => api.removeFromCollection(item.id))}
                    title={t.items.removeAllTitle}
                  >
                    {t.common.delete}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {preview.element}
    </div>
  )
}
