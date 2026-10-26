import { useEffect, useState, type MouseEvent, type ReactNode } from 'react'
import { api, type CardSummary, type SimilarCards } from '../api/client'
import { useHoverPreview } from '../hooks/useHoverPreview'
import { t } from '../i18n'
import { getPref, setPref } from '../prefs'
import { CardImage } from './CardImage'

const COLORS = ['W', 'U', 'B', 'R', 'G'] as const
const LEGAL_ONLY_KEY = 'mtgdm.similarLegalOnly'

interface Props {
  card: Pick<CardSummary, 'id' | 'name' | 'color_identity'>
  deckId?: number // deckbuilder: the deck's format, without the cards already in it
  deckColors?: string[] // a shortcut to the deck's color identity
  initialColors?: string[] // instead of the card's own
  onPick: (card: CardSummary) => void
  onContextMenu?: (card: CardSummary, event: MouseEvent) => void
  hoverInfo?: (cardId: string) => ReactNode
  badge?: (card: CardSummary) => number | undefined // e.g. copies already in the deck
  dimmed?: (card: CardSummary) => boolean
  onClose: () => void
}

/** Cards doing a similar job to one card (rules text, Scryfall Tagger tags, mana value): the best ones
in the collection, then the best others. By default within the card's own colors; more can be switched on. */
export function SimilarCardsPanel({
  card,
  deckId,
  deckColors,
  initialColors,
  onPick,
  onContextMenu,
  hoverInfo,
  badge,
  dimmed,
  onClose,
}: Props) {
  const [colors, setColors] = useState<string[]>(initialColors ?? card.color_identity)
  // With a deck: only the cards it can play, or all of them with the others marked (remembered).
  const [legalOnly, setLegalOnly] = useState(() => getPref(LEGAL_ONLY_KEY) !== 'false')
  const legalParam = deckId === undefined ? undefined : legalOnly
  // Results and errors belong to one request: a newer one shows "searching" until its own arrive.
  const colorParam = COLORS.filter((c) => colors.includes(c)).join('') || 'C' // C: colorless only
  const key = [card.id, colorParam, deckId ?? '', legalParam ?? ''].join('|')
  const [result, setResult] = useState<{ key: string; data: SimilarCards } | null>(null)
  const [error, setError] = useState<{ key: string; message: string } | null>(null)
  const preview = useHoverPreview(hoverInfo)

  useEffect(() => {
    let cancelled = false
    api.similarCards(card.id, { colors: colorParam, deck: deckId, legal_only: legalParam }).then(
      (data) => !cancelled && setResult({ key, data }),
      (e: Error) => !cancelled && setError({ key, message: e.message }),
    )
    return () => {
      cancelled = true
    }
  }, [card.id, colorParam, deckId, legalParam, key])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const data = result?.key === key ? result.data : null
  const owned = data?.owned.map((i) => i.card) ?? []
  const others = data?.others.map((i) => i.card) ?? []
  const notLegal = new Set(
    [...(data?.owned ?? []), ...(data?.others ?? [])].filter((i) => i.legal === false).map((i) => i.card.id),
  )
  const chooseLegalOnly = (value: boolean) => {
    setLegalOnly(value)
    void setPref(LEGAL_ONLY_KEY, String(value))
  }
  const toggle = (c: string) => setColors((prev) => (prev.includes(c) ? prev.filter((x) => x !== c) : [...prev, c]))
  const sameColors = (a: string[], b: string[]) => a.length === b.length && a.every((c) => b.includes(c))

  const grid = (cards: CardSummary[]) => (
    <div className="similar-grid">
      {cards.map((c) => {
        const count = badge?.(c)
        return (
          <button
            key={c.id}
            className={`card-button ${dimmed?.(c) ? 'dimmed' : ''} ${notLegal.has(c.id) ? 'not-legal' : ''}`}
            title={notLegal.has(c.id) ? t.similar.notLegal : undefined}
            onClick={() => onPick(c)}
            onContextMenu={
              onContextMenu &&
              ((e) => {
                e.preventDefault()
                onContextMenu(c, e)
              })
            }
            onMouseEnter={(e) => preview.show(c, e)}
            onMouseLeave={() => preview.show(null)}
          >
            <CardImage cardId={c.id} name={c.name} size="normal" hasImage={c.image_faces > 0} />
            {count ? <span className="card-count-badge">{count}</span> : null}
            {notLegal.has(c.id) && <span className="card-legal-badge">{t.similar.notLegal}</span>}
          </button>
        )
      })}
    </div>
  )

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="similar-panel" onClick={(e) => e.stopPropagation()} role="dialog" aria-label={t.similar.title(card.name)}>
        <div className="dialog-header">
          <h2>{t.similar.title(card.name)}</h2>
          <button className="close-button static" onClick={onClose} aria-label={t.common.close}>
            ×
          </button>
        </div>
        <div className="similar-toolbar">
          <div className="chip-group" role="group" aria-label={t.similar.colors}>
            {COLORS.map((c) => (
              <button
                key={c}
                className={`mana mana-${c.toLowerCase()} chip-mana ${colors.includes(c) ? 'on' : ''}`}
                title={t.similar.colorsTitle}
                aria-pressed={colors.includes(c)}
                onClick={() => toggle(c)}
              >
                {c}
              </button>
            ))}
          </div>
          {deckColors && !sameColors(colors, deckColors) && (
            <button className="button small" onClick={() => setColors(deckColors)}>
              {t.similar.deckColors}
            </button>
          )}
          {!sameColors(colors, card.color_identity) && (
            <button className="button small" onClick={() => setColors(card.color_identity)}>
              {t.similar.cardColors}
            </button>
          )}
          {deckId !== undefined && (
            <label className="checkbox" title={t.similar.legalOnlyTitle}>
              <input type="checkbox" checked={legalOnly} onChange={(e) => chooseLegalOnly(e.target.checked)} />
              {t.similar.legalOnly}
            </label>
          )}
        </div>
        <p className="muted small">{deckId === undefined ? t.similar.hint : legalOnly ? t.similar.hintDeck : t.similar.hintDeckAll}</p>

        {error?.key === key && <p className="status error">{error.message}</p>}
        {data === null && error?.key !== key && <p className="muted">{t.similar.searching}</p>}
        {data && owned.length + others.length === 0 && <p className="muted">{t.similar.none}</p>}
        {owned.length > 0 && (
          <section>
            <h3 className="similar-heading">{t.similar.inCollection(owned.length)}</h3>
            {grid(owned)}
          </section>
        )}
        {others.length > 0 && (
          <section>
            <h3 className="similar-heading">{t.similar.others(others.length)}</h3>
            {grid(others)}
          </section>
        )}
        {preview.element}
      </div>
    </div>
  )
}
