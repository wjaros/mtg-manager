import { useEffect, useState } from 'react'
import { api, type CardPrices, type DeckCard } from '../api/client'
import { groupCards, mergeCards, sortCards, type DeckGrouping } from '../decks'
import { useHoverPreview } from '../hooks/useHoverPreview'
import { locale, t } from '../i18n'
import { DeckVisual } from './DeckVisual'
import { ManaCost } from './ManaCost'

/** One small deck of the box with its cards. */
export interface BoxPart {
  key: string
  name: string
  cards: DeckCard[]
}

type Grouping = 'deck' | Exclude<DeckGrouping, 'category' | 'none'>
const GROUPINGS: Grouping[] = ['deck', 'type', 'mv', 'color', 'rarity']
const GROUPING_LABEL: Record<Grouping, string> = {
  deck: t.boxes.groupDeck,
  type: t.deckView.groupType,
  mv: t.deckView.groupMv,
  color: t.deckView.groupColor,
  rarity: t.deckView.groupRarity,
}

interface Section {
  key: string
  label: string
  cards: DeckCard[]
}

const copies = (cards: DeckCard[]) => cards.reduce((n, c) => n + c.quantity, 0)

interface Props {
  parts: BoxPart[]
  shown: string[] | null // keys of the parts shown; null = all
  onShown: (keys: string[] | null) => void
}

/** A box's cards like a deck's list: grouped by its small decks or like a deck (type, mana value…),
 * with each card's price, the total value and what the collection lacks (any printing counts). */
export function BoxCardList({ parts, shown, onShown }: Props) {
  const [grouping, setGrouping] = useState<Grouping>('deck')
  const [mode, setMode] = useState<'list' | 'images'>('list')
  const [prices, setPrices] = useState<CardPrices | null>(null)
  const hover = useHoverPreview()

  const ids = [...new Set(parts.flatMap((p) => p.cards.map((c) => c.card.id)))].sort().join(',')
  useEffect(() => {
    if (!ids) return
    let cancelled = false
    api.cardPrices(ids.split(',')).then(
      (result) => !cancelled && setPrices(result),
      () => !cancelled && setPrices(null),
    )
    return () => {
      cancelled = true
    }
  }, [ids])

  const visible = shown ? parts.filter((p) => shown.includes(p.key)) : parts
  const all = mergeCards(visible.flatMap((p) => p.cards))
  const priceOf = (c: DeckCard) => prices?.prices[c.card.id]?.eur ?? null
  const value = (cards: DeckCard[]) => cards.reduce((sum, c) => sum + (priceOf(c) ?? 0) * c.quantity, 0)
  // Copies the collection lacks for the shown decks together, per card (any printing counts).
  const oracle = (c: DeckCard) => c.card.oracle_id ?? c.card.id
  const lacking = new Map<string, { need: number; owned: number; price: number }>()
  for (const c of all) {
    const known = lacking.get(oracle(c))
    lacking.set(oracle(c), {
      need: (known?.need ?? 0) + c.quantity,
      owned: c.card.owned,
      price: known?.price ?? priceOf(c) ?? 0,
    })
  }
  const missingFor = (key: string) => {
    const l = lacking.get(key)
    return l ? Math.max(0, l.need - l.owned) : 0
  }
  const missingOf = (c: DeckCard) => Math.min(c.quantity, missingFor(oracle(c)))
  const missingCopies = [...lacking.keys()].reduce((n, k) => n + missingFor(k), 0)
  const missingValue = [...lacking.entries()].reduce((sum, [k, l]) => sum + missingFor(k) * l.price, 0)

  const sections: Section[] =
    grouping === 'deck'
      ? visible.map((p) => ({ key: p.key, label: p.name, cards: sortCards(p.cards, 'mv') }))
      : groupCards(all, grouping, 'mv').map((g) => ({ key: g.key, label: g.label, cards: g.cards }))
  // One row per card name: printings of a card (a box's eight different Plains) together, priced per copy
  // on average.
  const rows = (cards: DeckCard[]) => {
    const byName = new Map<string, { entry: DeckCard; value: number; priced: number }>()
    for (const c of cards) {
      const row = byName.get(c.card.name)
      const price = priceOf(c)
      if (row) {
        row.entry = { ...row.entry, quantity: row.entry.quantity + c.quantity }
        if (price !== null) {
          row.value += price * c.quantity
          row.priced += c.quantity
        }
      } else {
        byName.set(c.card.name, { entry: c, value: (price ?? 0) * c.quantity, priced: price !== null ? c.quantity : 0 })
      }
    }
    return [...byName.values()].map((r) => ({ entry: r.entry, price: r.priced ? r.value / r.priced : null }))
  }
  const euro = (n: number) => `€${n.toLocaleString(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

  return (
    <div className="box-cards">
      <div className="box-cards-toolbar">
        <div className="chip-group" role="group" aria-label={t.boxes.decksColumn}>
          <button className={`chip ${shown === null ? 'on' : ''}`} onClick={() => onShown(null)}>
            {t.boxes.allDecks}
          </button>
          {parts.map((p) => (
            <button
              key={p.key}
              className={`chip ${shown?.includes(p.key) ? 'on' : ''}`}
              onClick={(e) => {
                // Ctrl/Cmd-click adds a deck to the ones shown (e.g. two halves together).
                if ((e.metaKey || e.ctrlKey) && shown) {
                  onShown(shown.includes(p.key) ? shown.filter((k) => k !== p.key) : [...shown, p.key])
                } else onShown([p.key])
              }}
              title={t.boxes.chipTitle}
            >
              {p.name}
            </button>
          ))}
        </div>
        <div className="box-cards-options">
          <select className="select small" value={grouping} onChange={(e) => setGrouping(e.target.value as Grouping)}>
            {GROUPINGS.map((g) => (
              <option key={g} value={g}>
                {GROUPING_LABEL[g]}
              </option>
            ))}
          </select>
          <div className="segmented small" role="tablist">
            <button className={mode === 'list' ? 'on' : ''} onClick={() => setMode('list')} role="tab">
              {t.boxes.viewList}
            </button>
            <button className={mode === 'images' ? 'on' : ''} onClick={() => setMode('images')} role="tab">
              {t.boxes.viewImages}
            </button>
          </div>
          <span className="small">
            {t.common.cards(copies(all))}
            {prices && <strong> · {euro(value(all))}</strong>}
            {prices && missingCopies > 0 && (
              <span className="warn-text"> · {t.boxes.missing(missingCopies, euro(missingValue))}</span>
            )}
          </span>
        </div>
      </div>

      {mode === 'images' && grouping !== 'deck' ? (
        <div className="box-preview">
          <DeckVisual
            cards={all}
            mode="stacks"
            grouping={grouping}
            sort="mv"
            onRemove={() => {}}
            onMenu={() => {}}
            onHover={(entry, e) => hover.show(entry?.card ?? null, e)}
          />
        </div>
      ) : mode === 'images' ? (
        sections.map((s) => (
          <div key={s.key} className="box-preview">
            <h3 className="deck-group-title">
              {s.label} <span className="muted">{copies(s.cards)}</span>
              {prices && <span className="muted"> · {euro(value(s.cards))}</span>}
            </h3>
            <DeckVisual
              cards={s.cards}
              mode="stacks"
              grouping="type"
              sort="mv"
              onRemove={() => {}}
              onMenu={() => {}}
              onHover={(entry, e) => hover.show(entry?.card ?? null, e)}
            />
          </div>
        ))
      ) : (
        <div className="box-card-sections">
          {sections.map((s) => (
            <div key={s.key} className="deck-group">
              <h3 className="deck-group-title">
                {s.label} <span className="muted">{copies(s.cards)}</span>
                {prices && <span className="muted"> · {euro(value(s.cards))}</span>}
              </h3>
              {rows(s.cards).map(({ entry: c, price }) => {
                const missing = missingOf(c)
                return (
                  <div
                    key={`${c.board}-${c.card.name}`}
                    className="deck-row box-card-row"
                    onMouseEnter={(e) => hover.show(c.card, e)}
                    onMouseLeave={() => hover.show(null)}
                  >
                    <span className="deck-qty">{c.quantity}</span>
                    <span className="deck-name" title={`${c.card.set_name} #${c.card.collector_number}`}>
                      {c.card.name}
                    </span>
                    <span className="box-card-cost">
                      <ManaCost cost={c.card.mana_cost} />
                    </span>
                    <span className="num muted small">{price !== null ? euro(price) : '—'}</span>
                    <span
                      className={`small ${missing ? 'warn-text' : 'muted'}`}
                      title={t.boxes.ownedTitle(c.card.owned)}
                    >
                      {missing ? t.boxes.lacks(missing) : '✓'}
                    </span>
                  </div>
                )
              })}
            </div>
          ))}
        </div>
      )}
      {prices?.as_of && (
        <p className="muted small">{t.boxes.pricesAsOf(new Date(prices.as_of).toLocaleDateString(locale))}</p>
      )}
      {hover.element}
    </div>
  )
}
