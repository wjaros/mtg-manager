import { useEffect, useRef, useState } from 'react'
import { api, type BoxDetail, type DeckCard, type DeckSummary } from '../api/client'
import { BoxDeckTile, CardsPreview } from '../components/BoxDecks'
import { mergeCards } from '../decks'
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
  const [preview, setPreview] = useState<number[]>([])
  const [cards, setCards] = useState<Map<number, DeckCard[]>>(new Map())
  const [busy, setBusy] = useState(false)
  const [deleting, setDeleting] = useState(false)

  const reload = () => api.box(boxId).then(setDetail, (e: Error) => setError(e.message))
  useEffect(() => {
    api.box(boxId).then(
      (next) => {
        setDetail(next)
        setPreview(next.parts.length ? [next.parts[0].id] : [])
      },
      (e: Error) => setError(e.message),
    )
  }, [boxId])

  // A deck's cards are loaded when it is first previewed.
  const requested = useRef(new Set<number>())
  useEffect(() => {
    for (const id of preview) {
      if (requested.current.has(id)) continue
      requested.current.add(id)
      api.deck(id).then(
        (deck) => setCards((prev) => new Map(prev).set(id, deck.cards)),
        (e: Error) => setError(e.message),
      )
    }
  }, [preview])
  const showPreview = setPreview

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
  const previewDecks = preview.map((id) => byId.get(id)).filter((d): d is DeckSummary => !!d)
  const previewCards = preview.every((id) => cards.has(id)) ? mergeCards(preview.flatMap((id) => cards.get(id)!)) : null

  const combine = async () => {
    setBusy(true)
    setError(null)
    try {
      const deck = await api.combineBox(box.id, selected, name.trim() || chosen.map((d) => d.name).join(' + '))
      setSelected([])
      setCombineName(null)
      await reload()
      requested.current.add(deck.id)
      setCards((prev) => new Map(prev).set(deck.id, deck.cards))
      setPreview([deck.id])
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
      setPreview((prev) => prev.filter((id) => id !== deck.id))
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
                previewed={preview.length === 1 && preview[0] === deck.id}
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
                <button className="link-button small" onClick={() => showPreview([deck.id])}>
                  {t.boxes.preview}
                </button>
                <button className="link-button small danger" onClick={() => removeCombined(deck)}>
                  {t.boxes.remove}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {previewDecks.length > 0 && (
        <section className="panel">
          {previewCards ? (
            <CardsPreview title={previewDecks.map((d) => d.name).join(' + ')} cards={previewCards} />
          ) : (
            <p className="muted">{t.common.loading}</p>
          )}
        </section>
      )}

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
