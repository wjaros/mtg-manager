import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, type CardSummary, type CollectionStats } from '../api/client'
import { CardDetailPanel } from '../components/CardDetailPanel'
import { CardGrid, MIN_CARD_WIDTH } from '../components/CardGrid'
import { ZoomControl } from '../components/ZoomControl'
import { useZoom } from '../hooks/useZoom'
import { Filters } from '../components/Filters'
import { EMPTY_FILTERS, toQuery, type FilterState } from '../filters'
import { useCardPages } from '../hooks/useCardPages'
import { useDebounced } from '../hooks/useDebounced'
import { formatNumber, t } from '../i18n'

interface Props {
  hasData: boolean
  onOpenSettings: () => void
}

export function CollectionView({ hasData, onOpenSettings }: Props) {
  const [filters, setFilters] = useState<FilterState>(EMPTY_FILTERS)
  const [zoom, setZoom] = useZoom('collection')
  const debounced = useDebounced(filters, 250)
  const query = useMemo(() => toQuery(debounced), [debounced])
  const [version, setVersion] = useState(0)
  const { total, error, cardAt, ensureRange } = useCardPages(query, version)
  const [selected, setSelected] = useState<string | null>(null)
  const [stats, setStats] = useState<CollectionStats | null>(null)
  const closeDetail = useCallback(() => setSelected(null), [])

  useEffect(() => {
    if (hasData) api.collectionStats().then(setStats, () => setStats(null))
  }, [hasData, version])

  // Grid counts: copies of the card (any printing), or of the exact printing in printing mode.
  const prints = filters.unique === 'prints'
  const badge = useCallback((card: CardSummary) => (prints ? card.owned_printing : card.owned), [prints])
  // Refetch the grid so counts and the owned/missing filter reflect the change.
  const onCollectionChange = useCallback(() => setVersion((v) => v + 1), [])

  if (!hasData) {
    return (
      <div className="view">
        <h1>{t.collection.title}</h1>
        <section className="panel empty-state">
          <p>{t.collection.emptyDb}</p>
          <p className="muted">{t.collection.emptyDbHint}</p>
          <button className="button primary" onClick={onOpenSettings}>
            {t.collection.goToSettings}
          </button>
        </section>
      </div>
    )
  }

  return (
    <div className={`view collection ${selected ? 'with-detail' : ''}`}>
      <div className="collection-main">
        <div className="collection-header">
          <span className="muted result-count">
            {total === null ? t.collection.searching : t.collection.resultCount(formatNumber(total), filters.unique === 'prints')}
          </span>
          {stats && (
            <span className="muted result-count collection-stats">
              {t.collection.stats(formatNumber(stats.cards), formatNumber(stats.copies))}
            </span>
          )}
          <ZoomControl zoom={zoom} onChange={setZoom} />
        </div>
        <Filters value={filters} onChange={setFilters} />
        {error && <p className="status error">{t.collection.searchError(error)}</p>}
        {total === 0 && <p className="muted no-results">{t.collection.noResults}</p>}
        <CardGrid
          total={total ?? 0}
          cardAt={cardAt}
          ensureRange={ensureRange}
          selectedId={selected}
          onSelect={(card: CardSummary) => setSelected(card.id)}
          badge={badge}
          minCardWidth={MIN_CARD_WIDTH * zoom}
        />
      </div>
      {selected && (
        <CardDetailPanel
          key={selected}
          cardId={selected}
          onClose={closeDetail}
          onCollectionChange={onCollectionChange}
        />
      )}
    </div>
  )
}
