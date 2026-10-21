import { useEffect, useState } from 'react'
import { api, type CardDetail, type CollectionItem } from '../api/client'
import { t } from '../i18n'

const FINISH_LABEL: Record<string, string> = { nonfoil: '', foil: 'foil', etched: 'etched' }

interface Props {
  card: CardDetail
  onChange?: () => void
}

/** Copies of this card (any printing) in the physical collection, with quick add/remove. */
export function OwnedCopies({ card, onChange }: Props) {
  const [items, setItems] = useState<CollectionItem[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [version, setVersion] = useState(0)

  useEffect(() => {
    let cancelled = false
    if (!card.oracle_id) return
    api.collection({ oracle_id: card.oracle_id }).then(
      (list) => !cancelled && setItems(list),
      (e: Error) => !cancelled && setError(e.message),
    )
    return () => {
      cancelled = true
    }
  }, [card.oracle_id, version])

  const run = async (action: () => Promise<unknown>) => {
    setError(null)
    try {
      await action()
      setVersion((v) => v + 1)
      onChange?.()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const total = items?.reduce((n, i) => n + i.quantity, 0) ?? 0
  const canFoil = card.finishes.includes('foil')

  return (
    <div className="owned-copies">
      <h3 className="printings-title">
        {t.card.inCollection} <span className="muted">{items === null ? '…' : total}</span>
      </h3>
      {items?.map((item) => (
        <div key={item.id} className="owned-row">
          <span className="deck-qty">{item.quantity}×</span>
          <span className="owned-label">
            {item.card.set_code.toUpperCase()} #{item.card.collector_number}
            {FINISH_LABEL[item.finish] && <span className="foil-tag"> {FINISH_LABEL[item.finish]}</span>}
            <span className="muted">
              {' '}
              · {item.condition}
              {item.language !== 'en' && ` · ${item.language}`}
              {item.location && ` · ${item.location.name}`}
            </span>
          </span>
          <span className="deck-row-actions visible">
            <button onClick={() => run(() => api.removeFromCollection(item.id, 1))} title={t.card.removeCopy}>
              −
            </button>
            <button
              onClick={() =>
                run(() =>
                  api.addToCollection({
                    card_id: item.card.id,
                    finish: item.finish,
                    language: item.language,
                    condition: item.condition,
                    location_id: item.location?.id ?? null,
                  }),
                )
              }
              title={t.card.addCopy}
            >
              +
            </button>
          </span>
        </div>
      ))}
      <div className="actions compact">
        <button className="button" onClick={() => run(() => api.addToCollection({ card_id: card.id }))}>
          {t.card.ownPrinting(card.set_code.toUpperCase())}
        </button>
        {canFoil && (
          <button
            className="button"
            onClick={() => run(() => api.addToCollection({ card_id: card.id, finish: 'foil' }))}
          >
            + foil
          </button>
        )}
      </div>
      {error && <p className="status error small">{error}</p>}
    </div>
  )
}
