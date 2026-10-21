import type { MouseEvent } from 'react'
import type { Board, DeckCard, DeckChange, Holding } from '../api/client'
import { changeKey, changeKind, changeLabel, changesByKey, groupByType, holdState, holdTitle } from '../decks'
import { setCardDrag } from '../dnd'
import { ManaCost } from './ManaCost'
import { t } from '../i18n'

const BOARD_SECTIONS: { board: Board; label: string }[] = [
  { board: 'commander', label: t.panels.boardCommander },
  { board: 'companion', label: 'Companion' },
  { board: 'main', label: t.panels.boardMain },
  { board: 'sideboard', label: 'Sideboard' },
  { board: 'maybe', label: 'Maybeboard' },
]

interface Props {
  cards: DeckCard[]
  /** Card ids flagged by validation errors. */
  violations: Set<string>
  /** Unsaved changes: highlighted rows; removed cards are shown struck through. */
  changes?: DeckChange[]
  /** Paper decks: collection state per oracle id (missing / not in the deck's box). */
  holdings?: Map<string, Holding> | null
  onAdd: (entry: DeckCard) => void
  onRemove: (entry: DeckCard) => void
  /** Put a removed card back (its copies from the last saved version). */
  onRestore?: (change: DeckChange) => void
  onMenu: (entry: DeckCard, event: MouseEvent) => void
  onHover: (entry: DeckCard | null, event?: MouseEvent) => void
}

/** Text list of the deck grouped by board, then by card type (main board). */
export function DeckList({ cards, violations, changes = [], holdings, onAdd, onRemove, onRestore, onMenu, onHover }: Props) {
  const byKey = changesByKey(changes)
  // Removed cards as rows (with their saved quantity), so they show where they used to be.
  const ghosts = new Map<DeckCard, DeckChange>()
  for (const change of changes) {
    if (change.after === 0 && change.card) {
      ghosts.set({ card: change.card, quantity: change.before, board: change.board, category: null }, change)
    }
  }
  const counted = (list: DeckCard[]) => list.reduce((n, c) => n + (ghosts.has(c) ? 0 : c.quantity), 0)

  return (
    <div className="deck-list">
      {holdings && <HoldLegend holdings={holdings} />}
      {BOARD_SECTIONS.map(({ board, label }) => {
        const entries = [...cards, ...ghosts.keys()].filter((c) => c.board === board)
        if (!entries.length) return null
        const groups = (board === 'main' ? groupByType(entries) : [{ type: board, label, cards: entries, count: 0 }]).map(
          (g) => ({ ...g, count: counted(g.cards) }),
        )
        const total = counted(entries)
        return (
          <section key={board} className="deck-section">
            {board !== 'main' && (
              <h3 className="deck-group-title">
                {label} <span className="muted">{total}</span>
              </h3>
            )}
            {groups.map((group) => (
              <div key={group.type} className="deck-group">
                {board === 'main' && (
                  <h3 className="deck-group-title">
                    {group.label} <span className="muted">{group.count}</span>
                  </h3>
                )}
                {group.cards.map((entry) => {
                  const ghost = ghosts.get(entry)
                  if (ghost) {
                    return (
                      <div
                        key={`removed-${entry.card.id}-${entry.board}`}
                        className="deck-row change-removed"
                        onMouseEnter={(e) => onHover(entry, e)}
                        onMouseLeave={() => onHover(null)}
                        title={t.panels.removedTitle}
                      >
                        <span className="deck-qty">{entry.quantity}</span>
                        <span className="deck-name">{entry.card.name}</span>
                        <span className="change-badge">{t.deck.changeRemoved}</span>
                        <span className="deck-row-actions">
                          {onRestore && (
                            <button onClick={() => onRestore(ghost)} title={t.panels.restore} aria-label={t.panels.restoreCard(entry.card.name)}>
                              ↺
                            </button>
                          )}
                        </span>
                      </div>
                    )
                  }
                  const change = byKey.get(changeKey(entry.card.name, entry.board))
                  return (
                  <div
                    key={`${entry.card.id}-${entry.board}`}
                    className={`deck-row ${violations.has(entry.card.id) ? 'violation' : ''} ${change ? `change-${changeKind(change)}` : ''}`}
                    title={change ? changeTitle(change) : undefined}
                    draggable
                    onDragStart={(e) => setCardDrag(e, { cardId: entry.card.id, from: 'deck', board: entry.board })}
                    onMouseEnter={(e) => onHover(entry, e)}
                    onMouseLeave={() => onHover(null)}
                    onContextMenu={(e) => {
                      e.preventDefault()
                      onMenu(entry, e)
                    }}
                  >
                    <Quantity quantity={entry.quantity} holding={entry.card.oracle_id ? holdings?.get(entry.card.oracle_id) : undefined} />
                    <span className="deck-name" title={`${entry.card.set_name} #${entry.card.collector_number}`}>
                      {entry.card.name}
                      {entry.category && <span className="category-tag">{entry.category}</span>}
                    </span>
                    {change ? <span className="change-badge">{changeLabel(change)}</span> : <ManaCost cost={entry.card.mana_cost} />}
                    <span className="deck-row-actions">
                      <button onClick={() => onRemove(entry)} title={t.panels.removeOne} aria-label={t.panels.removeCard(entry.card.name)}>
                        −
                      </button>
                      <button onClick={() => onAdd(entry)} title={t.panels.addOne} aria-label={t.panels.addCard(entry.card.name)}>
                        +
                      </button>
                      <button onClick={(e) => onMenu(entry, e)} title={t.panels.more} aria-label={t.panels.more}>
                        ⋯
                      </button>
                    </span>
                  </div>
                  )
                })}
              </div>
            ))}
          </section>
        )
      })}
    </div>
  )
}

function changeTitle(change: DeckChange): string {
  if (change.before === 0) return t.panels.addedTitle
  if (change.after === change.before) return t.panels.printingTitle
  return t.panels.quantityTitle(change.before, change.after)
}

/** The quantity, framed in the colour of the card's physical state (paper decks). */
function Quantity({ quantity, holding }: { quantity: number; holding: Holding | undefined }) {
  const state = holdState(holding)
  return (
    <span className={`deck-qty ${state ? `held ${state.kind}` : ''}`} title={state ? holdTitle(state) : undefined}>
      {quantity}
    </span>
  )
}

/** What the coloured quantities mean, with how many cards are in each state. */
function HoldLegend({ holdings }: { holdings: Map<string, Holding> }) {
  const counts = { missing: 0, other_deck: 0, elsewhere: 0 }
  for (const h of holdings.values()) if (h.state) counts[h.state] += h.state === 'missing' ? h.missing : 1
  if (!counts.missing && !counts.other_deck && !counts.elsewhere) return null
  const items: [keyof typeof counts, string][] = [
    ['missing', t.panels.legendMissing(counts.missing)],
    ['other_deck', t.panels.legendOtherDeck(counts.other_deck)],
    ['elsewhere', t.panels.legendElsewhere(counts.elsewhere)],
  ]
  return (
    <p className="hold-legend small">
      {items
        .filter(([kind]) => counts[kind])
        .map(([kind, label]) => (
          <span key={kind} className={`held ${kind}`}>
            {label}
          </span>
        ))}
    </p>
  )
}
