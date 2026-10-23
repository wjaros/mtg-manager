import { useEffect, useState, type MouseEvent } from 'react'
import { api, type Combo, type ComboCard, type DeckCombos } from '../api/client'
import { t } from '../i18n'

const SPELLBOOK_URL = 'https://commanderspellbook.com'

interface Props {
  deckId: number
  /** Changes whenever the deck's contents change, to refetch. */
  revision: string
  onAdd: (cardId: string) => void
  onHover: (card: { id: string; name: string; image_faces: number } | null, event?: MouseEvent) => void
}

/** Combos the deck has and those one card away, from Commander Spellbook. */
export function DeckCombosPanel({ deckId, revision, onAdd, onHover }: Props) {
  // Results for one revision; a newer revision shows the old ones until its own arrive.
  const [combos, setCombos] = useState<DeckCombos | null>(null)
  const [error, setError] = useState<{ revision: string; message: string } | null>(null)

  useEffect(() => {
    let cancelled = false
    // Debounced: adding cards one after another asks once.
    const timer = setTimeout(() => {
      api.deckCombos(deckId).then(
        (c) => {
          if (cancelled) return
          setCombos(c)
          setError(null)
        },
        (e: Error) => !cancelled && setError({ revision, message: e.message }),
      )
    }, 400)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [deckId, revision])

  const credit = (
    <p className="muted small">
      {t.combos.credit}{' '}
      <a href={SPELLBOOK_URL} target="_blank" rel="noreferrer">
        Commander Spellbook
      </a>
    </p>
  )
  if (error && !combos) {
    return (
      <div className="combos-panel">
        <p className="status error">{error.message}</p>
        {credit}
      </div>
    )
  }
  if (!combos) return <p className="muted">{t.combos.loading}</p>

  return (
    <div className="combos-panel">
      {error && <p className="status error small">{error.message}</p>}
      <h3 className="combos-section">
        {t.combos.included} <span className="muted">({combos.included.length})</span>
      </h3>
      {combos.included.length === 0 && <p className="muted small">{t.combos.noneIncluded}</p>}
      {combos.included.map((c) => (
        <ComboItem key={c.id} combo={c} onAdd={onAdd} onHover={onHover} />
      ))}

      <h3 className="combos-section">
        {t.combos.almost} <span className="muted">({combos.almost.length})</span>
      </h3>
      <p className="muted small">{t.combos.almostHint}</p>
      {combos.almost.map((c) => (
        <ComboItem key={c.id} combo={c} onAdd={onAdd} onHover={onHover} />
      ))}
      {credit}
    </div>
  )
}

function ComboItem({ combo, onAdd, onHover }: { combo: Combo } & Pick<Props, 'onAdd' | 'onHover'>) {
  return (
    <section className="combo">
      <div className="combo-cards">
        {combo.cards.map((card, i) => (
          <ComboCardChip key={`${card.name}-${i}`} card={card} onAdd={onAdd} onHover={onHover} />
        ))}
        {combo.legal === false && <span className="combo-warn small">{t.combos.notLegal}</span>}
      </div>
      <ul className="combo-produces">
        {combo.produces.map((p) => (
          <li key={p}>{p}</li>
        ))}
      </ul>
      <details className="combo-details">
        <summary>{t.combos.howItWorks}</summary>
        {(combo.requires.length > 0 || combo.prerequisites || combo.mana_needed) && (
          <>
            <h4>{t.combos.prerequisites}</h4>
            <ul>
              {combo.requires.map((r) => (
                <li key={r}>{r}</li>
              ))}
              {combo.mana_needed && <li>{t.combos.manaNeeded(combo.mana_needed)}</li>}
              {combo.prerequisites.split('\n').filter(Boolean).map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          </>
        )}
        <h4>{t.combos.steps}</h4>
        <ol>
          {combo.description.split('\n').filter(Boolean).map((step, i) => (
            <li key={i}>{step}</li>
          ))}
        </ol>
        <a href={combo.url} target="_blank" rel="noreferrer" className="small">
          {t.combos.openOnSpellbook} ↗
        </a>
      </details>
    </section>
  )
}

function ComboCardChip({ card, onAdd, onHover }: { card: ComboCard } & Pick<Props, 'onAdd' | 'onHover'>) {
  const hover = card.card_id
    ? {
        onMouseEnter: (e: MouseEvent) => onHover({ id: card.card_id!, name: card.name, image_faces: card.image_faces ?? 0 }, e),
        onMouseLeave: () => onHover(null),
      }
    : {}
  if (card.in_deck) {
    return (
      <span className="combo-card" {...hover}>
        {card.name}
      </span>
    )
  }
  return (
    <span className="combo-card combo-card-missing" {...hover}>
      {card.name}
      {(card.owned ?? 0) > 0 && <span className="small"> · {t.combos.owned(card.owned ?? 0)}</span>}
      {card.card_id ? (
        <button className="button" onClick={() => onAdd(card.card_id!)}>
          {t.combos.add}
        </button>
      ) : (
        <span className="muted small"> · {t.combos.notInCardData}</span>
      )}
    </span>
  )
}
