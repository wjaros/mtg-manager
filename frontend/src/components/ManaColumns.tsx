import { useLayoutEffect, useRef, useState, type CSSProperties, type MouseEvent } from 'react'
import { imageSizeFor, type DeckCard, type DeckChange, type Holding } from '../api/client'
import { changeKey, changeKind, changeLabel, changesByKey, holdState, holdTitle, isLand, matchesCardQuery } from '../decks'
import { setCardDrag } from '../dnd'
import { CardImage } from './CardImage'
import { t } from '../i18n'

const LANDS = t.panels.lands
const COLUMNS = ['0', '1', '2', '3', '4', '5', '6', '7+', LANDS]

function columnOf(entry: DeckCard): string {
  if (isLand(entry)) return LANDS
  const mv = Math.floor(entry.card.cmc ?? 0)
  return mv >= 7 ? '7+' : String(mv)
}

interface Props {
  cards: DeckCard[]
  zoom?: number // column width: 1 = the nine columns fill the width, at most 160px each
  query?: string // search in the deck: only matching cards (stacked cards overlap, so dimming wouldn't do)
  changes?: DeckChange[]
  holdings?: Map<string, Holding> | null
  onRemove: (entry: DeckCard) => void
  onMenu: (entry: DeckCard, event: MouseEvent) => void
  onHover: (entry: DeckCard | null, event?: MouseEvent) => void
}

/** Main deck laid out like Arena's deckbuilder: one column per mana value, overlapping cards. */
export function ManaColumns({ cards, zoom = 1, query = '', changes = [], holdings, onRemove, onMenu, onHover }: Props) {
  const byKey = changesByKey(changes)
  const main = cards.filter((c) => c.board === 'main' && matchesCardQuery(c.card, query))
  const columns = new Map<string, DeckCard[]>(COLUMNS.map((c) => [c, []]))
  for (const entry of main) columns.get(columnOf(entry))!.push(entry)

  // Image size follows the column width (zoom, window size), so large columns stay sharp.
  const ref = useRef<HTMLDivElement>(null)
  const [columnWidth, setColumnWidth] = useState(0)
  useLayoutEffect(() => {
    const el = ref.current?.firstElementChild
    if (!el) return
    const observer = new ResizeObserver(([entry]) => setColumnWidth(entry.contentRect.width))
    observer.observe(el)
    return () => observer.disconnect()
  }, [])
  const imageSize = imageSizeFor(columnWidth)

  return (
    <div className="mana-columns" ref={ref} style={{ '--zoom': zoom } as CSSProperties}>
      {COLUMNS.map((label) => {
        const entries = columns.get(label)!.sort((a, b) => a.card.name.localeCompare(b.card.name))
        const count = entries.reduce((n, c) => n + c.quantity, 0)
        return (
          <div key={label} className="mana-column">
            <div className="mana-column-header">
              <span>{label}</span>
              <span className="muted">{count || ''}</span>
            </div>
            <div className="mana-column-stack">
              {entries.map((entry) => {
                const change = byKey.get(changeKey(entry.card.name, entry.board))
                const hold = holdState(entry.card.oracle_id ? holdings?.get(entry.card.oracle_id) : undefined)
                return (
                <button
                  key={entry.card.id}
                  className={`stack-card ${change ? `change-${changeKind(change)}` : ''} ${hold ? `held-${hold.kind}` : ''}`}
                  title={hold ? holdTitle(hold) : undefined}
                  onClick={() => onRemove(entry)}
                  onContextMenu={(e) => {
                    e.preventDefault()
                    onMenu(entry, e)
                  }}
                  draggable
                  onDragStart={(e) => setCardDrag(e, { cardId: entry.card.id, from: 'deck', board: entry.board })}
                  onMouseEnter={(e) => onHover(entry, e)}
                  onMouseLeave={() => onHover(null)}
                  aria-label={t.panels.stackCard(entry.quantity, entry.card.name)}
                >
                  <CardImage cardId={entry.card.id} name={entry.card.name} size={imageSize} hasImage={entry.card.image_faces > 0} />
                  {entry.quantity > 1 && <span className="card-count-badge">×{entry.quantity}</span>}
                  {change && <span className="stack-change-badge">{changeLabel(change)}</span>}
                  {hold?.kind === 'proxy' && <span className="proxy-chip on-card">PROXY</span>}
                </button>
                )
              })}
            </div>
          </div>
        )
      })}
    </div>
  )
}
