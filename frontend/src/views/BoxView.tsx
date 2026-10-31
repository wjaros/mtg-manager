import { useEffect, useState } from 'react'
import { api, type BoxDetail, type DeckCard, type DeckSummary } from '../api/client'
import { BoxCardList } from '../components/BoxCardList'
import { BoxDeckTile } from '../components/BoxDecks'
import { ManaCost } from '../components/ManaCost'
import { t } from '../i18n'

interface Props {
  boxId: number
  onBack: () => void
  onOpenDeck: (id: number) => void
  onOpenLocation: (id: number) => void
}

/** A box of small decks: its own decks stay as they came; tick some and combine them into a new deck
 * (a copy of their cards, e.g. two 20-card halves = 40 cards) as often as you like. */
export function BoxView({ boxId, onBack, onOpenDeck, onOpenLocation }: Props) {
  const [detail, setDetail] = useState<BoxDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<number[]>([])
  const [combineName, setCombineName] = useState<string | null>(null) // null: from the ticked decks' names
  const [shown, setShown] = useState<string[] | null>(null) // decks in the card list; null = all
  const [cards, setCards] = useState<Map<number, DeckCard[]>>(new Map())
  const [busy, setBusy] = useState(false)
  const [deleting, setDeleting] = useState(false)

  const reload = () => api.box(boxId).then(setDetail, (e: Error) => setError(e.message))
  useEffect(() => {
    api.box(boxId).then(
      (next) => {
        setDetail(next)
        // The box's own decks don't change here: their cards are loaded once, for the card list.
        for (const part of next.parts) {
          api.deck(part.id).then(
            (deck) => setCards((prev) => new Map(prev).set(part.id, deck.cards)),
            (e: Error) => setError(e.message),
          )
        }
      },
      (e: Error) => setError(e.message),
    )
  }, [boxId])

  const showPreview = (ids: number[]) => {
    setShown(ids.map(String))
    document.querySelector('.box-cards')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  if (error && !detail) {
    return (
      <div className="view">
        <p className="status error">{error}</p>
        <button className="button" onClick={onBack}>
          {t.builder.back}
        </button>
      </div>
    )
  }
  if (!detail) return <p className="muted view">{t.common.loading}</p>

  const { box, parts, combined } = detail
  const byId = new Map([...parts, ...combined.map((c) => c.deck)].map((d) => [d.id, d]))
  const chosen = selected.map((id) => byId.get(id)).filter((d): d is DeckSummary => !!d)
  const name = combineName ?? chosen.map((d) => d.name).join(' + ')
  const loaded = parts.every((p) => cards.has(p.id))

  const combine = async () => {
    setBusy(true)
    setError(null)
    try {
      await api.combineBox(box.id, selected, name.trim() || chosen.map((d) => d.name).join(' + '))
      setSelected([])
      setCombineName(null)
      await reload()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const rename = async () => {
    const next = window.prompt(t.boxes.renamePrompt, box.name)?.trim()
    if (!next || next === box.name) return
    try {
      await api.renameBox(box.id, next)
      reload()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const removeCombined = async (deck: DeckSummary) => {
    if (!window.confirm(t.decks.confirmDelete(deck.name))) return
    try {
      await api.deleteDeck(deck.id)
      reload()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div className="view box-view">
      <div className="view-header">
        <div>
          <button className="link-button" onClick={onBack}>
            {t.builder.back}
          </button>
          <h1 onDoubleClick={rename} title={t.boxes.renameTitle}>
            {box.name}
          </h1>
          <p className="muted small">
            {box.set_code && `${box.set_code.toUpperCase()} · `}
            {t.boxes.decks(box.parts)}
            {box.location_id !== null && (
              <>
                {' · '}
                <button className="link-button small" onClick={() => onOpenLocation(box.location_id!)}>
                  {t.boxes.inCollection}
                </button>
              </>
            )}
          </p>
        </div>
        <div className="actions">
          <button className="button" onClick={rename}>
            {t.boxes.rename}
          </button>
          <button className="button" onClick={() => setDeleting(true)}>
            {t.boxes.deleteBox}
          </button>
        </div>
      </div>

      <section className="panel">
        <h2>{t.boxes.partsTitle}</h2>
        <p className="muted small">{t.boxes.combineHint}</p>
        <div className="box-decks">
          {parts.map((deck) => {
            const checked = selected.includes(deck.id)
            return (
              <BoxDeckTile
                key={deck.id}
                name={deck.name}
                colors={deck.color_identity}
                cards={deck.counts.total}
                checked={checked}
                previewed={shown?.length === 1 && shown[0] === String(deck.id)}
                onToggle={() =>
                  setSelected((prev) => (checked ? prev.filter((id) => id !== deck.id) : [...prev, deck.id]))
                }
                onPreview={() => showPreview([deck.id])}
              >
                <button className="link-button small" onClick={() => onOpenDeck(deck.id)}>
                  {t.boxes.open}
                </button>
              </BoxDeckTile>
            )
          })}
        </div>
        <div className="box-combine">
          <input
            className="input"
            value={name}
            onChange={(e) => setCombineName(e.target.value)}
            placeholder={t.boxes.combinedName}
            aria-label={t.boxes.combinedName}
            disabled={selected.length < 2}
          />
          <button className="button primary" onClick={combine} disabled={busy || selected.length < 2}>
            {t.boxes.combine(chosen.reduce((n, d) => n + d.counts.total, 0))}
          </button>
          {selected.length > 0 && (
            <button className="link-button small" onClick={() => showPreview(selected)}>
              {t.boxes.previewSelected}
            </button>
          )}
        </div>
        {error && <p className="status error">{error}</p>}
      </section>

      <section className="panel">
        <h2>{t.boxes.combinedTitle}</h2>
        {combined.length === 0 ? (
          <p className="muted small">{t.boxes.noCombined}</p>
        ) : (
          <ul className="box-plans">
            {combined.map(({ deck, part_ids }) => (
              <li key={deck.id}>
                <button className="link-button" onClick={() => onOpenDeck(deck.id)}>
                  <strong>{deck.name}</strong>
                </button>
                <ManaCost cost={deck.color_identity.map((c) => `{${c}}`).join('')} />
                <span className="muted small">{t.common.cards(deck.counts.total)}</span>
                <span className="muted small">
                  {t.boxes.madeOf(part_ids.map((id) => byId.get(id)?.name ?? '?').join(' + '))}
                </span>
                <button className="link-button small danger" onClick={() => removeCombined(deck)}>
                  {t.boxes.remove}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="panel">
        <h2>{t.boxes.cardsTitle}</h2>
        {loaded ? (
          <BoxCardList
            parts={parts.map((p) => ({ key: String(p.id), name: p.name, cards: cards.get(p.id)! }))}
            shown={shown}
            onShown={setShown}
          />
        ) : (
          <p className="muted">{t.common.loading}</p>
        )}
      </section>

      {deleting && (
        <DeleteBoxDialog
          name={box.name}
          hasCards={box.location_id !== null}
          onClose={() => setDeleting(false)}
          onDelete={async (withCards) => {
            try {
              await api.deleteBox(box.id, withCards)
              onBack()
            } catch (e) {
              setError((e as Error).message)
              setDeleting(false)
            }
          }}
        />
      )}
    </div>
  )
}

function DeleteBoxDialog({
  name,
  hasCards,
  onDelete,
  onClose,
}: {
  name: string
  hasCards: boolean
  onDelete: (withCards: boolean) => void
  onClose: () => void
}) {
  const [withCards, setWithCards] = useState(false)
  return (
    <div className="modal-backdrop centered" onClick={onClose}>
      <div className="dialog" onClick={(e) => e.stopPropagation()} role="dialog" aria-label={t.boxes.deleteBox}>
        <div className="dialog-header">
          <h2>{t.boxes.deleteBox}</h2>
          <button className="close-button static" onClick={onClose} aria-label={t.common.close}>
            ×
          </button>
        </div>
        <p>{t.boxes.confirmDelete(name)}</p>
        {hasCards && (
          <label className="checkbox">
            <input type="checkbox" checked={withCards} onChange={(e) => setWithCards(e.target.checked)} />
            {t.boxes.deleteWithCards}
          </label>
        )}
        <div className="actions">
          <button className="button primary" onClick={() => onDelete(withCards)}>
            {t.common.delete}
          </button>
          <button className="button" onClick={onClose}>
            {t.common.cancel}
          </button>
        </div>
      </div>
    </div>
  )
}
