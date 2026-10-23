import { useEffect, useRef, useState } from 'react'
import { api, type DeckSummary } from '../api/client'
import { FORMAT_LABEL } from '../decks'
import { t } from '../i18n'

/** A ▾ button next to the deck's name: the other decks, filtered by typing, to switch to. */
export function DeckSwitcher({ deckId, onOpen }: { deckId: number; onOpen: (id: number) => void }) {
  const [open, setOpen] = useState(false)
  const [decks, setDecks] = useState<DeckSummary[] | null>(null)
  const [filter, setFilter] = useState('')
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    let cancelled = false
    // Asked for on every open: decks may have been added or renamed meanwhile.
    api.decks().then(
      (list) => !cancelled && setDecks(list),
      () => !cancelled && setDecks([]),
    )
    const onDown = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    window.addEventListener('mousedown', onDown)
    window.addEventListener('keydown', onKey)
    return () => {
      cancelled = true
      window.removeEventListener('mousedown', onDown)
      window.removeEventListener('keydown', onKey)
    }
  }, [open])

  const needle = filter.trim().toLowerCase()
  const shown = (decks ?? []).filter(
    (d) => !needle || d.name.toLowerCase().includes(needle) || d.commander_name?.toLowerCase().includes(needle),
  )
  const choose = (id: number) => {
    setOpen(false)
    setFilter('')
    if (id !== deckId) onOpen(id)
  }

  return (
    <div className="deck-switcher" ref={ref}>
      <button
        className="deck-switcher-toggle"
        onClick={() => setOpen((o) => !o)}
        title={t.builder.switchDeck}
        aria-label={t.builder.switchDeck}
        aria-expanded={open}
      >
        ▾
      </button>
      {open && (
        <div className="context-menu deck-switcher-menu" role="menu">
          <input
            className="input small"
            type="search"
            autoFocus
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && shown.length > 0 && choose(shown[0].id)}
            placeholder={t.builder.switchDeckFilter}
            aria-label={t.builder.switchDeckFilter}
          />
          <div className="deck-switcher-list">
            {decks === null && <p className="muted small">{t.common.loading}</p>}
            {decks !== null && shown.length === 0 && <p className="muted small">{t.builder.switchDeckNone}</p>}
            {shown.map((d) => (
              <button
                key={d.id}
                role="menuitem"
                className={d.id === deckId ? 'on' : ''}
                onClick={() => choose(d.id)}
              >
                {d.name}
                <span className="muted small">
                  {' '}
                  · {FORMAT_LABEL[d.format]}
                  {d.commander_name && ` · ${d.commander_name}`}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
