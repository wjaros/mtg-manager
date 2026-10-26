import { useEffect, useState } from 'react'
import { api, setIconUrl, type CardDetail, type CardSummary } from '../api/client'
import { CardImage } from './CardImage'
import { CopyButton } from './CopyButton'
import { RARITY_LABEL } from '../decks'
import { ManaCost } from './ManaCost'
import { OwnedCopies } from './OwnedCopies'
import { locale, t } from '../i18n'
import { editUserTags } from '../userTags'

const LEGALITY_FORMATS = [
  ['brawl', 'Brawl'],
  ['standardbrawl', 'Std Brawl'],
  ['commander', 'Commander'],
  ['historic', 'Historic'],
  ['standard', 'Standard'],
  ['modern', 'Modern'],
] as const

interface Props {
  cardId: string
  onClose: () => void
  /** Called with the printing chosen in the list, e.g. to use it in a deck. */
  onChoosePrinting?: (printingId: string) => void
  /** Called after the collection changed from this panel. */
  onCollectionChange?: () => void
}

/** Large image, rules text, artist, legality and every printing of the selected card. */
export function CardDetailPanel({ cardId, onClose, onChoosePrinting, onCollectionChange }: Props) {
  // The parent remounts this panel per card (key), so state starts fresh for each card.
  const [currentId, setCurrentId] = useState(cardId)
  const [card, setCard] = useState<CardDetail | null>(null)
  const [printings, setPrintings] = useState<CardSummary[] | null>(null)
  const [face, setFace] = useState(0)
  const [error, setError] = useState<{ id: string; message: string } | null>(null)

  useEffect(() => {
    let cancelled = false
    api.card(currentId).then(
      (c) => !cancelled && setCard(c),
      (e: Error) => !cancelled && setError({ id: currentId, message: e.message }),
    )
    return () => {
      cancelled = true
    }
  }, [currentId])

  useEffect(() => {
    let cancelled = false
    api.printings(cardId).then(
      (p) => !cancelled && setPrintings(p),
      () => !cancelled && setPrintings([]),
    )
    return () => {
      cancelled = true
    }
  }, [cardId])

  const selectPrinting = (id: string) => {
    setCurrentId(id)
    setFace(0)
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  if (error?.id === currentId) {
    return (
      <aside className="detail-panel">
        <button className="close-button" onClick={onClose} aria-label={t.common.close}>
          ×
        </button>
        <p className="status error">{error.message}</p>
      </aside>
    )
  }
  if (!card || card.id !== currentId) {
    return (
      <aside className="detail-panel">
        <p className="muted">{t.common.loading}</p>
      </aside>
    )
  }

  const faces = card.faces.length > 1 ? card.faces : null
  const shown = faces?.[face]

  return (
    <aside className="detail-panel">
      <button className="close-button" onClick={onClose} aria-label={t.common.close}>
        ×
      </button>

      <div className="detail-image">
        <CardImage
          key={`${card.id}-${face}`}
          cardId={card.id}
          name={card.name}
          size="large"
          face={card.image_faces > 1 ? face : 0}
          hasImage={card.image_faces > 0}
        />
        {faces && (
          <button className="button flip-button" onClick={() => setFace(face ? 0 : 1)}>
            ↻ {faces[face ? 0 : 1].name}
          </button>
        )}
      </div>

      <div className="detail-body">
        <h2 className="detail-title">
          <span>
            {shown?.name ?? card.name} <CopyButton text={card.name} title={t.common.copyName} />
          </span>
          <ManaCost cost={shown ? shown.mana_cost : card.mana_cost} />
        </h2>
        {card.printed_name && <p className="muted">{card.printed_name}</p>}
        <p className="type-line">{shown?.type_line ?? card.type_line}</p>
        <OracleText text={shown ? shown.oracle_text : card.oracle_text} />
        {(shown?.power ?? card.power) && (
          <p className="pt">
            {shown?.power ?? card.power}/{shown?.toughness ?? card.toughness}
          </p>
        )}
        {(shown?.loyalty ?? card.loyalty) && <p className="pt">{t.card.loyalty(String(shown?.loyalty ?? card.loyalty))}</p>}
        {(shown?.flavor_text ?? card.flavor_text) && <p className="flavor">{shown?.flavor_text ?? card.flavor_text}</p>}

        <dl className="facts">
          <dt>{t.card.printing}</dt>
          <dd className="set-line">
            <img className="set-icon" src={setIconUrl(card.set_code)} alt="" />
            {card.set_name} ({card.set_code.toUpperCase()}) #{card.collector_number}
          </dd>
          <dt>{t.card.rarity}</dt>
          <dd>{RARITY_LABEL[card.rarity ?? ''] ?? card.rarity}</dd>
          <dt>{t.card.artist}</dt>
          <dd>{shown?.artist ?? card.artist ?? '—'}</dd>
          <dt>{t.card.availableOn}</dt>
          <dd>{card.games.join(', ')}</dd>
          <dt>{t.userTags.label}</dt>
          <dd className="user-tags">
            {(card.user_tags ?? []).map((tag) => (
              <span key={tag} className="user-tag">
                {tag}
              </span>
            ))}
            <button
              className="link-button small"
              onClick={() =>
                editUserTags(card).then(
                  (tags) => tags && setCard({ ...card, user_tags: tags }),
                  (e: Error) => window.alert(e.message),
                )
              }
            >
              {t.userTags.edit}
            </button>
          </dd>
          {card.prices.eur && (
            <>
              <dt>{t.card.price}</dt>
              <dd>
                €{card.prices.eur}
                {card.prices.usd && ` · $${card.prices.usd}`}
                {card.prices_updated_at && (
                  <span className="muted"> ({new Date(card.prices_updated_at).toLocaleDateString(locale)})</span>
                )}
              </dd>
            </>
          )}
        </dl>

        <div className="legalities">
          {LEGALITY_FORMATS.map(([key, label]) => {
            const status = card.legalities[key] ?? 'not_legal'
            return (
              <span key={key} className={`legality ${status}`} title={status}>
                {label}
              </span>
            )
          })}
        </div>

        {onChoosePrinting && currentId !== cardId && (
          <button className="button primary choose-printing" onClick={() => onChoosePrinting(currentId)}>
            {t.card.usePrinting(`${card.set_code.toUpperCase()} #${card.collector_number}`)}
          </button>
        )}

        <OwnedCopies card={card} onChange={onCollectionChange} />

        <h3 className="printings-title">
          {t.card.printings} {printings && <span className="muted">({printings.length})</span>}
        </h3>
        {printings === null ? (
          <p className="muted">{t.common.loading}</p>
        ) : (
          <div className="printings">
            {printings.map((p) => (
              <button
                key={p.id}
                className={`printing ${p.id === currentId ? 'selected' : ''}`}
                onClick={() => selectPrinting(p.id)}
                title={`${p.set_name} #${p.collector_number} (${p.released_at ?? ''})`}
              >
                <CardImage cardId={p.id} name={p.name} size="small" hasImage={p.image_faces > 0} />
                <span className="printing-label">
                  {p.set_code.toUpperCase()} #{p.collector_number}
                  {p.lang !== 'en' && ` · ${p.lang}`}
                </span>
              </button>
            ))}
          </div>
        )}
      </div>
    </aside>
  )
}

function OracleText({ text }: { text: string | null | undefined }) {
  if (!text) return null
  return (
    <div className="oracle-text">
      {text.split('\n').map((line, i) => (
        <p key={i}>{line}</p>
      ))}
    </div>
  )
}
