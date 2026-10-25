import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, type CardSummary, type CollectionStats } from '../api/client'
import { CardDetailPanel } from '../components/CardDetailPanel'
import { CardGrid, MIN_CARD_WIDTH } from '../components/CardGrid'
import { ContextMenu, type MenuState } from '../components/ContextMenu'
import { SimilarCardsPanel } from '../components/SimilarCardsPanel'
import { printQueue, usePrintQueue } from '../printQueue'
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
  const { total, error, typeHint, cardAt, ensureRange } = useCardPages(query, version)
  const [selected, setSelected] = useState<string | null>(null)
  const [stats, setStats] = useState<CollectionStats | null>(null)
  const closeDetail = useCallback(() => setSelected(null), [])
  // Picking cards for proxy printing: a click toggles the card instead of opening it.
  const [picking, setPicking] = useState(false)
  const [menu, setMenu] = useState<MenuState | null>(null)
  const [similarTo, setSimilarTo] = useState<CardSummary | null>(null)
  const closeSimilar = useCallback(() => setSimilarTo(null), [])
  const queue = usePrintQueue()
  const marked = useCallback((card: CardSummary) => queue.some((q) => q.card_id === card.id), [queue])

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
          {typeHint && (
            <button className="link-button small" title={t.filters.typeHintTitle} onClick={() => setFilters({ ...filters, q: typeHint })}>
              {t.filters.typeHint(typeHint)}
            </button>
          )}
          {stats && (
            <span className="muted result-count collection-stats">
              {t.collection.stats(formatNumber(stats.cards), formatNumber(stats.copies))}
            </span>
          )}
          <label className="checkbox small pick-toggle" title={t.print.pickTitle}>
            <input type="checkbox" checked={picking} onChange={(e) => setPicking(e.target.checked)} />
            {t.print.pick}
          </label>
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
          onSelect={(card: CardSummary) => (picking ? printQueue.toggle(card) : setSelected(card.id))}
          onContextMenu={(card, e) =>
            setMenu({
              x: e.clientX,
              y: e.clientY,
              title: card.name,
              items: [
                printQueue.has(card.id)
                  ? { label: t.print.unqueue, onClick: () => printQueue.remove(card.id) }
                  : { label: t.print.queue, onClick: () => printQueue.add(card) },
                { label: t.similar.menu, onClick: () => setSimilarTo(card) },
                { label: t.builder.details, onClick: () => setSelected(card.id) },
              ],
            })
          }
          badge={badge}
          marked={marked}
          minCardWidth={MIN_CARD_WIDTH * zoom}
        />
      </div>
      {menu && <ContextMenu menu={menu} onClose={() => setMenu(null)} />}
      {similarTo && (
        <SimilarCardsPanel
          card={similarTo}
          onPick={(card) => {
            setSimilarTo(null)
            setSelected(card.id)
          }}
          onClose={closeSimilar}
        />
      )}
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
