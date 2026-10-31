import type { ReactNode } from 'react'
import type { DeckCard } from '../api/client'
import { useHoverPreview } from '../hooks/useHoverPreview'
import { t } from '../i18n'
import { DeckVisual } from './DeckVisual'
import { ManaCost } from './ManaCost'

interface TileProps {
  name: string
  colors: string[]
  cards: number | null // null: not loaded yet
  checked: boolean
  disabled?: boolean
  previewed: boolean
  onToggle: () => void
  onPreview: () => void
  children?: ReactNode // extra line (a warning, an Open link)
}

/** One small deck of a box: tick it (to import or to combine), preview its cards. */
export function BoxDeckTile({ name, colors, cards, checked, disabled, previewed, onToggle, onPreview, children }: TileProps) {
  return (
    <div className={`box-deck ${checked ? 'on' : ''} ${previewed ? 'previewed' : ''}`}>
      <label className="checkbox">
        <input type="checkbox" checked={checked} disabled={disabled} onChange={onToggle} />
        <strong>{name}</strong>
      </label>
      <div className="box-deck-meta">
        {cards === null ? (
          <span className="muted small">{t.boxes.notLoaded}</span>
        ) : (
          <>
            <ManaCost cost={colors.map((c) => `{${c}}`).join('')} />
            <span className="muted small">{t.common.cards(cards)}</span>
          </>
        )}
      </div>
      <div className="box-deck-meta">
        <button className="link-button small" onClick={onPreview}>
          {t.boxes.preview}
        </button>
        {children}
      </div>
    </div>
  )
}

/** A deck's (or several decks') cards as image stacks, read only, with a large preview on hover. */
export function CardsPreview({ title, cards }: { title: string; cards: DeckCard[] }) {
  const hover = useHoverPreview()
  const count = cards.filter((c) => c.board === 'main' || c.board === 'commander').reduce((n, c) => n + c.quantity, 0)
  return (
    <div className="box-preview">
      <h3 className="deck-group-title">
        {t.boxes.previewOf(title)} <span className="muted">{count}</span>
      </h3>
      <DeckVisual
        cards={cards}
        mode="stacks"
        grouping="type"
        sort="mv"
        onRemove={() => {}}
        onMenu={() => {}}
        onHover={(entry, e) => hover.show(entry?.card ?? null, e)}
      />
      {hover.element}
    </div>
  )
}
