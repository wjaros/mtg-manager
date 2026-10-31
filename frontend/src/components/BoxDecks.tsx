import type { ReactNode } from 'react'
import { t } from '../i18n'
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
