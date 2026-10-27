import { useEffect, useState, type FormEvent } from 'react'
import { api, type DeckFormat, type DeckSummary, type Location, type Platform } from '../api/client'
import { CardImage } from '../components/CardImage'
import { ManaCost } from '../components/ManaCost'
import { deckSizeTarget, FORMAT_LABEL, PLATFORM_LABEL } from '../decks'
import { t } from '../i18n'

interface Props {
  onOpen: (deckId: number) => void
}

export function DecksView({ onOpen }: Props) {
  const [decks, setDecks] = useState<DeckSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [deleting, setDeleting] = useState<DeckSummary | null>(null)

  useEffect(() => {
    api.decks().then(setDecks, (e: Error) => setError(e.message))
  }, [])

  const remove = async (deck: DeckSummary, withCards: boolean) => {
    setDeleting(null)
    try {
      await api.deleteDeck(deck.id, withCards)
      setDecks((prev) => prev?.filter((d) => d.id !== deck.id) ?? null)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div className="view">
      <div className="view-header">
        <h1>{t.decks.title}</h1>
        {!creating && (
          <button className="button primary" onClick={() => setCreating(true)}>
            {t.decks.newDeck}
          </button>
        )}
      </div>

      {creating && (
        <NewDeckForm
          onCancel={() => setCreating(false)}
          onCreated={(id) => onOpen(id)}
          onError={setError}
        />
      )}
      {error && <p className="status error">{error}</p>}

      {decks === null ? (
        <p className="muted">{t.common.loading}</p>
      ) : decks.length === 0 && !creating ? (
        <section className="panel empty-state">
          <p>{t.decks.empty}</p>
          <p className="muted">{t.decks.emptyHint}</p>
        </section>
      ) : (
        <div className="deck-tiles">
          {decks.map((deck) => {
            const target = deckSizeTarget(deck.format)
            return (
              <div key={deck.id} className="deck-tile">
                <button className="deck-tile-open" onClick={() => onOpen(deck.id)}>
                  <div className="deck-tile-art">
                    {deck.cover_card_id ? (
                      <CardImage cardId={deck.cover_card_id} name={deck.commander_name ?? deck.name} size="normal" />
                    ) : (
                      <div className="card-image placeholder">
                        <span className="card-image-name">{deck.name}</span>
                      </div>
                    )}
                  </div>
                  <div className="deck-tile-body">
                    <strong className="deck-tile-name">{deck.name}</strong>
                    <span className="muted small">
                      {FORMAT_LABEL[deck.format]} · {PLATFORM_LABEL[deck.platform]}
                    </span>
                    {deck.commander_name && <span className="small">{deck.commander_name}</span>}
                    <span className="deck-tile-meta">
                      <ManaCost cost={deck.color_identity.map((c) => `{${c}}`).join('')} />
                      <span className={target && deck.counts.total !== target ? 'warn-text' : 'muted'}>
                        {deck.counts.total}
                        {target ? ` / ${target}` : ''}
                        {t.decks.cardsSuffix}
                      </span>
                      {deck.unsaved_changes > 0 && (
                        <span className="unsaved-dot" title={t.decks.unsavedTitle}>
                          {t.decks.unsaved}
                        </span>
                      )}
                    </span>
                  </div>
                </button>
                <button className="deck-tile-delete" onClick={() => setDeleting(deck)} title={t.decks.deleteDeck} aria-label={t.decks.deleteDeck}>
                  ×
                </button>
              </div>
            )
          })}
        </div>
      )}
      {deleting && (
        <DeleteDeckDialog deck={deleting} onDelete={(withCards) => remove(deleting, withCards)} onClose={() => setDeleting(null)} />
      )}
    </div>
  )
}

/** Confirms a deck's deletion; a deck with a box in the collection may take its cards along. */
function DeleteDeckDialog({
  deck,
  onDelete,
  onClose,
}: {
  deck: DeckSummary
  onDelete: (withCards: boolean) => void
  onClose: () => void
}) {
  const [box, setBox] = useState<Location | null>(null)
  const [withCards, setWithCards] = useState(false)

  useEffect(() => {
    if (deck.location_id === null) return
    api.locations().then(
      (locations) => setBox(locations.find((l) => l.id === deck.location_id) ?? null),
      () => setBox(null),
    )
  }, [deck.location_id])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const hasCards = box !== null && box.card_count + (box.proxy_count ?? 0) > 0

  return (
    <div className="modal-backdrop centered" onClick={onClose}>
      <div className="dialog" onClick={(e) => e.stopPropagation()} role="dialog" aria-label={t.decks.deleteDeck}>
        <div className="dialog-header">
          <h2>{t.decks.deleteDeck}</h2>
          <button className="close-button static" onClick={onClose} aria-label={t.common.close}>
            ×
          </button>
        </div>
        <p>{t.decks.confirmDelete(deck.name)}</p>
        {hasCards && (
          <div>
            <label className="checkbox">
              <input type="checkbox" checked={withCards} onChange={(e) => setWithCards(e.target.checked)} />
              {t.decks.deleteWithCards(box.card_count, box.proxy_count ?? 0)}
            </label>
            <p className="muted small">{t.decks.deleteWithCardsHint}</p>
          </div>
        )}
        <div className="actions">
          <button className="button primary" onClick={() => onDelete(hasCards && withCards)}>
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

function NewDeckForm({
  onCancel,
  onCreated,
  onError,
}: {
  onCancel: () => void
  onCreated: (id: number) => void
  onError: (message: string) => void
}) {
  const [name, setName] = useState('')
  const [format, setFormat] = useState<DeckFormat>('brawl')
  const [platform, setPlatform] = useState<Platform>('arena')
  const [saving, setSaving] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return
    setSaving(true)
    try {
      const deck = await api.createDeck({ name: name.trim(), format, platform })
      onCreated(deck.id)
    } catch (err) {
      onError((err as Error).message)
      setSaving(false)
    }
  }

  return (
    <form className="panel new-deck" onSubmit={submit}>
      <h2>{t.decks.newDeckTitle}</h2>
      <div className="form-row">
        <label>
          {t.decks.name}
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} autoFocus required />
        </label>
        <label>
          {t.decks.format}
          <select className="select" value={format} onChange={(e) => setFormat(e.target.value as DeckFormat)}>
            {(Object.keys(FORMAT_LABEL) as DeckFormat[]).map((f) => (
              <option key={f} value={f}>
                {FORMAT_LABEL[f]}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t.decks.platform}
          <select className="select" value={platform} onChange={(e) => setPlatform(e.target.value as Platform)}>
            <option value="arena">{t.deck.arena}</option>
            <option value="paper">{t.deck.paper}</option>
          </select>
        </label>
      </div>
      <div className="actions">
        <button className="button primary" type="submit" disabled={saving || !name.trim()}>
          {t.decks.create}
        </button>
        <button className="button" type="button" onClick={onCancel}>
          {t.common.cancel}
        </button>
      </div>
    </form>
  )
}
