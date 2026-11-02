import { useEffect, useMemo, useState } from 'react'
import { api, type DeckCard, type ProductDeck, type ProductDetail } from '../api/client'
import { t } from '../i18n'
import { BoxCardList } from './BoxCardList'
import { BoxDeckTile } from './BoxDecks'
import { ProductBrowser } from './ProductBrowser'

// Up to this many decks (a Beginner Box) all are taken by default; above it (Jumpstart pools)
// none, and a filter over the deck names helps to find the packs you have.
const WHOLE_BOX = 12

function deckCards(deck: ProductDeck): DeckCard[] {
  return deck.lines
    .filter((l) => l.card)
    .map((l) => ({ card: l.card!, quantity: l.quantity, board: l.board, category: null }))
}

interface Props {
  initialKey?: string | null // a box to open right away (found in the Deck tab's search)
  onOpenBox: (boxId: number) => void // after the import too
}

/** Boxes of small decks (Beginner Box, Starter Kit, Jumpstart): preview each deck, pick the ones you
 * have and import them as a box in Decks (combining them comes later, in the box). */
export function BoxImportPanel({ initialKey, onOpenBox }: Props) {
  const [detail, setDetail] = useState<ProductDetail | null>(null)
  const [opening, setOpening] = useState<string | null>(initialKey ?? null)
  const [selected, setSelected] = useState<string[]>([])
  const [shown, setShown] = useState<string[] | null>(null) // decks in the card list; null = all
  const [name, setName] = useState('')
  const [own, setOwn] = useState(true)
  const [loading, setLoading] = useState<string[]>([])
  const [deckFilter, setDeckFilter] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const show = (next: ProductDetail) => {
    const { product, decks } = next
    setDetail(next)
    setSelected(decks.length <= WHOLE_BOX ? decks.map((d) => d.file_name) : [])
    setName(`${product.name} (${product.set_name ?? product.code.toUpperCase()})`)
    setDeckFilter('')
    setShown(null)
  }

  const open = async (key: string) => {
    setOpening(key)
    setError(null)
    try {
      show(await api.product(key))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setOpening(null)
    }
  }

  // Opened from the Deck tab's search: the panel mounts with the box to show (`opening` starts set).
  useEffect(() => {
    if (!initialKey) return
    let cancelled = false
    api
      .product(initialKey)
      .then(
        (next) => !cancelled && show(next),
        (e: Error) => !cancelled && setError(e.message),
      )
      .finally(() => !cancelled && setOpening(null))
    return () => {
      cancelled = true
    }
  }, [initialKey])

  const decks = useMemo(() => new Map((detail?.decks ?? []).map((d) => [d.file_name, d])), [detail])

  // A big product's decks are fetched when previewed or ticked.
  const ensureLoaded = async (fileName: string) => {
    if (!detail || decks.get(fileName)?.loaded !== false || loading.includes(fileName)) return
    setLoading((prev) => [...prev, fileName])
    try {
      const deck = await api.productDeck(detail.product.key, fileName)
      setDetail((prev) => prev && { ...prev, decks: prev.decks.map((d) => (d.file_name === fileName ? deck : d)) })
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading((prev) => prev.filter((f) => f !== fileName))
    }
  }

  const importBox = async () => {
    if (!detail) return
    setBusy(true)
    setError(null)
    try {
      const box = await api.importProduct(detail.product.key, { file_names: selected, name: name.trim() || null, own })
      onOpenBox(box.box.id)
    } catch (e) {
      setError((e as Error).message)
      setBusy(false)
    }
  }

  if (!detail) {
    return (
      <section className="panel box-import">
        <p className="muted small">{t.boxes.intro}</p>
        {opening && <p className="muted small">{t.boxes.loadingDecks}</p>}
        {error && <p className="status error">{error}</p>}
        <ProductBrowser opening={opening} onOpen={open} onOpenBox={onOpenBox} />
      </section>
    )
  }

  const { product } = detail
  const words = deckFilter.toLowerCase().split(/\s+/).filter(Boolean)
  const shownDecks = detail.decks.filter((d) => words.every((w) => d.name.toLowerCase().includes(w)))
  const cardCount = selected.reduce((n, f) => n + (decks.get(f)?.cards ?? 0), 0)
  return (
    <section className="panel box-import">
      <div className="box-header">
        <div>
          <strong className="box-title">{product.name}</strong>{' '}
          <span className="muted">
            {product.set_name ?? product.code.toUpperCase()}
            {product.release_date && ` · ${product.release_date.slice(0, 4)}`} · {t.boxes.decks(product.decks)}
          </span>
        </div>
        <button className="link-button" onClick={() => setDetail(null)} disabled={busy}>
          {t.boxes.other}
        </button>
      </div>
      <p className="muted small">{detail.decks.length > WHOLE_BOX ? t.boxes.pickPacks : t.boxes.importHint}</p>
      <div className="box-select-row">
        {detail.decks.length > WHOLE_BOX && (
          <input
            className="input box-filter"
            type="search"
            value={deckFilter}
            onChange={(e) => setDeckFilter(e.target.value)}
            placeholder={t.boxes.filter}
            aria-label={t.boxes.filter}
          />
        )}
        <button className="link-button small" onClick={() => setSelected(detail.decks.map((d) => d.file_name))}>
          {t.boxes.selectAll}
        </button>
        <button className="link-button small" onClick={() => setSelected([])}>
          {t.boxes.selectNone}
        </button>
      </div>

      <div className="box-decks">
        {shownDecks.map((deck) => {
          const checked = selected.includes(deck.file_name)
          const missing = deck.lines.filter((l) => !l.card).reduce((n, l) => n + l.quantity, 0)
          return (
            <BoxDeckTile
              key={deck.file_name}
              name={deck.name}
              colors={deck.colors}
              cards={deck.loaded ? deck.cards : null}
              checked={checked}
              previewed={shown?.length === 1 && shown[0] === deck.file_name}
              onToggle={() => {
                if (!checked) ensureLoaded(deck.file_name)
                setSelected((prev) =>
                  checked ? prev.filter((f) => f !== deck.file_name) : [...prev, deck.file_name],
                )
              }}
              onPreview={() => {
                setShown([deck.file_name])
                ensureLoaded(deck.file_name)
                document.querySelector('.box-cards')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
              }}
            >
              {loading.includes(deck.file_name) && <span className="muted small">{t.common.loading}</span>}
              {missing > 0 && <span className="pill error">{t.boxes.notFound(missing)}</span>}
            </BoxDeckTile>
          )
        })}
      </div>

      <div className="import-save">
        <div className="form-row">
          <label>
            {t.boxes.boxName}
            <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
          </label>
        </div>
        <label className="checkbox">
          <input type="checkbox" checked={own} onChange={(e) => setOwn(e.target.checked)} />
          {t.boxes.own}
        </label>
        <div className="actions">
          <button className="button primary" onClick={importBox} disabled={busy || selected.length === 0}>
            {busy ? t.importer.saving : t.boxes.importBox(selected.length, cardCount)}
          </button>
          <span className="muted small">{t.boxes.combineLater}</span>
        </div>
        {error && <p className="status error">{error}</p>}
      </div>

      <h2>{t.boxes.cardsTitle}</h2>
      <BoxCardList
        parts={detail.decks.filter((d) => d.loaded).map((d) => ({ key: d.file_name, name: d.name, cards: deckCards(d) }))}
        shown={shown}
        onShown={setShown}
      />
    </section>
  )
}
