import { useVirtualizer } from '@tanstack/react-virtual'
import { useEffect, useLayoutEffect, useRef, useState, type MouseEvent } from 'react'
import type { CardSummary } from '../api/client'
import { setCardDrag } from '../dnd'
import { CardImage } from './CardImage'

const MIN_CARD_WIDTH = 170
const GAP = 12
const CARD_RATIO = 680 / 488 // Scryfall "normal" image height / width

interface Props {
  total: number
  cardAt: (index: number) => CardSummary | undefined
  ensureRange: (first: number, last: number) => void
  selectedId?: string | null
  onSelect: (card: CardSummary) => void
  onContextMenu?: (card: CardSummary, event: MouseEvent) => void
  onHover?: (card: CardSummary | null, event?: MouseEvent) => void
  /** Small number shown on the card, e.g. copies already in the deck. */
  badge?: (card: CardSummary) => number | undefined
  /** Greyed out, e.g. a singleton card already in the deck. */
  dimmed?: (card: CardSummary) => boolean
  minCardWidth?: number
  /** Cards can be dragged out (deckbuilder pool). */
  draggable?: boolean
}

/** Virtualized grid: only rows near the viewport are rendered and fetched. */
export function CardGrid({
  total,
  cardAt,
  ensureRange,
  selectedId = null,
  onSelect,
  onContextMenu,
  onHover,
  badge,
  dimmed,
  minCardWidth = MIN_CARD_WIDTH,
  draggable = false,
}: Props) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(0)

  useLayoutEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width))
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  const columns = Math.max(1, Math.floor((width + GAP) / (minCardWidth + GAP)))
  const cardWidth = width ? (width - GAP * (columns - 1)) / columns : minCardWidth
  const rowHeight = Math.round(cardWidth * CARD_RATIO) + GAP
  const rows = Math.ceil(total / columns)

  // The warning is about the React Compiler (not used here): TanStack Virtual's API can't be memoized by it.
  // oxlint-disable-next-line react/incompatible-library
  const virtualizer = useVirtualizer({
    count: rows,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => rowHeight,
    overscan: 3,
  })

  useEffect(() => {
    virtualizer.measure()
  }, [rowHeight, virtualizer])

  const items = virtualizer.getVirtualItems()
  const firstRow = items[0]?.index ?? 0
  const lastRow = items[items.length - 1]?.index ?? 0
  useEffect(() => {
    if (total > 0) ensureRange(firstRow * columns, Math.min(total - 1, (lastRow + 1) * columns - 1))
  }, [firstRow, lastRow, columns, total, ensureRange])

  return (
    <div className="card-grid-scroll" ref={scrollRef}>
      <div className="card-grid-inner" style={{ height: virtualizer.getTotalSize() }}>
        {items.map((row) => (
          <div
            key={row.key}
            className="card-grid-row"
            style={{ transform: `translateY(${row.start}px)`, gap: GAP, height: rowHeight - GAP }}
          >
            {Array.from({ length: columns }, (_, col) => {
              const index = row.index * columns + col
              if (index >= total) return null
              const card = cardAt(index)
              const count = card && badge?.(card)
              return (
                <div key={col} className="card-cell" style={{ width: cardWidth }}>
                  {card ? (
                    <button
                      className={`card-button ${card.id === selectedId ? 'selected' : ''} ${dimmed?.(card) ? 'dimmed' : ''}`}
                      onClick={() => onSelect(card)}
                      onContextMenu={
                        onContextMenu &&
                        ((e) => {
                          e.preventDefault()
                          onContextMenu(card, e)
                        })
                      }
                      draggable={draggable}
                      onDragStart={draggable ? (e) => setCardDrag(e, { cardId: card.id, from: 'pool', name: card.name, typeLine: card.type_line }) : undefined}
                      onMouseEnter={onHover && ((e) => onHover(card, e))}
                      onMouseLeave={onHover && (() => onHover(null))}
                      title={onHover ? undefined : `${card.name} · ${card.set_name} #${card.collector_number}`}
                    >
                      <CardImage cardId={card.id} name={card.name} hasImage={card.image_faces > 0} />
                      {count ? <span className="card-count-badge">{count}</span> : null}
                    </button>
                  ) : (
                    <div className="card-image skeleton" />
                  )}
                </div>
              )
            })}
          </div>
        ))}
      </div>
    </div>
  )
}
