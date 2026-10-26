import { useLayoutEffect, useRef, useState, type CSSProperties, type MouseEvent } from 'react'
import { imageSizeFor, type Board, type DeckCard, type DeckChange, type Holding, type ImageSize } from '../api/client'
import {
  BOARD_SECTIONS,
  changeKey,
  changeKind,
  changeLabel,
  changesByKey,
  countCards,
  groupCards,
  holdState,
  holdTitle,
  matchesCardQuery,
  sortCards,
  type CardGroup,
  type DeckGrouping,
  type DeckSort,
  type DeckVisualMode,
} from '../decks'
import { setCardDrag } from '../dnd'
import { CardImage } from './CardImage'
import { t } from '../i18n'

interface Section extends CardGroup {
  board: Board
}

/** The whole deck in groups: commander and companion first, the main deck grouped, then sideboard
and maybeboard. `keepEmpty` keeps the main deck's empty groups (fixed mana value columns). */
function deckSections(cards: DeckCard[], grouping: DeckGrouping, sort: DeckSort, keepEmpty: boolean): Section[] {
  return BOARD_SECTIONS.flatMap<Section>(({ board, label }) => {
    const entries = cards.filter((c) => c.board === board)
    if (board === 'main') return groupCards(entries, grouping, sort, keepEmpty).map((g) => ({ ...g, board }))
    if (!entries.length) return []
    return [{ key: board, label, cards: sortCards(entries, sort), count: countCards(entries), board }]
  })
}

interface Props {
  cards: DeckCard[]
  mode: DeckVisualMode
  grouping: DeckGrouping
  sort: DeckSort
  zoom?: number // card width: 1 = the stack columns fill the width, at most 160px each
  query?: string // search in the deck: only matching cards (stacked cards overlap, so dimming wouldn't do)
  changes?: DeckChange[]
  holdings?: Map<string, Holding> | null
  onRemove: (entry: DeckCard) => void
  onMenu: (entry: DeckCard, event: MouseEvent) => void
  onHover: (entry: DeckCard | null, event?: MouseEvent) => void
}

/** The deck as card images: stacks (one column per group, overlapping cards, like Arena's
deckbuilder) or a visual spoiler (whole cards in a grid, one section per group). */
export function DeckVisual({
  cards,
  mode,
  grouping,
  sort,
  zoom = 1,
  query = '',
  changes = [],
  holdings,
  onRemove,
  onMenu,
  onHover,
}: Props) {
  const byKey = changesByKey(changes)
  const shown = cards.filter((c) => matchesCardQuery(c.card, query))
  // Mana value stacks keep their empty columns, so a card always lands in the same place.
  const sections = deckSections(shown, grouping, sort, mode === 'stacks' && grouping === 'mv')

  // Image size follows the card width (zoom, window size, number of columns), so large cards stay sharp.
  // All cards are as wide as the first column (stacks) or the first card (spoiler); watched again when that one changes.
  const ref = useRef<HTMLDivElement>(null)
  const [cardWidth, setCardWidth] = useState(0)
  const first = sections[0]
  const measured = `${mode}|${first?.board}|${first?.key}|${first?.cards[0]?.card.id}`
  useLayoutEffect(() => {
    const el = ref.current?.querySelector(mode === 'stacks' ? '.mana-column' : '.stack-card')
    if (!el) return
    const observer = new ResizeObserver(([entry]) => setCardWidth(entry.contentRect.width))
    observer.observe(el)
    return () => observer.disconnect()
  }, [mode, measured])
  const imageSize = imageSizeFor(cardWidth)

  const tile = (entry: DeckCard) => (
    <DeckTile
      key={entry.card.id}
      entry={entry}
      change={byKey.get(changeKey(entry.card.name, entry.board))}
      holding={entry.card.oracle_id ? holdings?.get(entry.card.oracle_id) : undefined}
      imageSize={imageSize}
      onRemove={onRemove}
      onMenu={onMenu}
      onHover={onHover}
    />
  )

  if (mode === 'spoiler') {
    return (
      <div className="deck-visual deck-spoiler" ref={ref} style={{ '--zoom': zoom } as CSSProperties}>
        {sections.map((section) => (
          <section key={`${section.board}|${section.key}`} className={`deck-spoiler-section board-${section.board}`}>
            <h3 className="deck-group-title">
              {section.label} <span className="muted">{section.count}</span>
            </h3>
            <div className="deck-spoiler-grid">{section.cards.map(tile)}</div>
          </section>
        ))}
      </div>
    )
  }
  return (
    <div
      className="deck-visual mana-columns"
      ref={ref}
      style={{ '--zoom': zoom, '--columns': Math.max(1, sections.length) } as CSSProperties}
    >
      {sections.map((section) => (
        <div key={`${section.board}|${section.key}`} className={`mana-column board-${section.board}`}>
          <div className="mana-column-header" title={section.label}>
            <span>{section.label}</span>
            <span className="muted">{section.count || ''}</span>
          </div>
          <div className="mana-column-stack">{section.cards.map(tile)}</div>
        </div>
      ))}
    </div>
  )
}

interface TileProps {
  entry: DeckCard
  change: DeckChange | undefined
  holding: Holding | undefined
  imageSize: ImageSize
  onRemove: (entry: DeckCard) => void
  onMenu: (entry: DeckCard, event: MouseEvent) => void
  onHover: (entry: DeckCard | null, event?: MouseEvent) => void
}

/** One card of the deck: click removes a copy, right click opens the menu; outlined when changed. */
function DeckTile({ entry, change, holding, imageSize, onRemove, onMenu, onHover }: TileProps) {
  const hold = holdState(holding)
  return (
    <button
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
}
