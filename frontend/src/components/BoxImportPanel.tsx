import { useEffect, useMemo, useState } from 'react'
import {
  api,
  type DeckCard,
  type Location,
  type ProductDeck,
  type ProductDetail,
  type ProductSummary,
} from '../api/client'
import { useDebounced } from '../hooks/useDebounced'
import { useHoverPreview } from '../hooks/useHoverPreview'
import { t } from '../i18n'
import { DeckVisual } from './DeckVisual'
import { ManaCost } from './ManaCost'

const COLOR_ORDER = 'WUBRG'
// Above this many decks (Jumpstart pools), a filter over the deck names.
const FILTER_FROM = 12

/** A deck to create: one of the box's decks, or several combined (two 20-card halves = 40 cards). */
interface Plan {
  id: number
  name: string
  fileNames: string[]
}

function deckCards(parts: ProductDeck[]): DeckCard[] {
  // The same printing in two halves becomes one entry (DeckVisual keys tiles by card).
  const byKey = new Map<string, DeckCard>()
  for (const line of parts.flatMap((p) => p.lines)) {
    if (!line.card) continue
    const key = `${line.board}|${line.card.id}`
    const entry = byKey.get(key)
    if (entry) entry.quantity += line.quantity
    else byKey.set(key, { card: line.card, quantity: line.quantity, board: line.board, category: null })
  }
  return [...byKey.values()]
}

const countOf = (parts: ProductDeck[]) => parts.reduce((n, p) => n + p.cards, 0)
const colorsOf = (parts: ProductDeck[]) =>
  [...COLOR_ORDER].filter((c) => parts.some((p) => p.colors.includes(c))).map((c) => `{${c}}`).join('')
const notFoundOf = (deck: ProductDeck) =>
  deck.lines.filter((l) => !l.card).reduce((n, l) => n + l.quantity, 0)

interface Props {
  onImported: (deckIds: number[]) => void
}

/** Boxes holding several small decks (Beginner Box, Starter Kit, Jumpstart): preview each deck,
 * combine them into decks (two halves = 40 cards), create those decks at once, optionally owned. */
export function BoxImportPanel({ onImported }: Props) {
  const [query, setQuery] = useState('')
  const [found, setFound] = useState<{ q: string; list: ProductSummary[] } | null>(null)
  const [detail, setDetail] = useState<ProductDetail | null>(null)
  const [opening, setOpening] = useState<string | null>(null)
  const [selected, setSelected] = useState<string[]>([])
  const [plans, setPlans] = useState<Plan[]>([])
  const [preview, setPreview] = useState<string[] | null>(null)
  const [own, setOwn] = useState(false)
  const [addUnused, setAddUnused] = useState(false)
  const [unusedLocation, setUnusedLocation] = useState<number | null>(null)
  const [locations, setLocations] = useState<Location[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState<string[]>([])
  const [deckFilter, setDeckFilter] = useState('')
  const hover = useHoverPreview()
  const q = useDebounced(query, 250).trim()

  useEffect(() => {
    let cancelled = false
    api.products(q).then(
      (list) => !cancelled && setFound({ q, list }),
      (e: Error) => !cancelled && setError(e.message),
    )
    return () => {
      cancelled = true
    }
  }, [q])

  useEffect(() => {
    api.locations().then(setLocations, () => setLocations([]))
  }, [])

  const open = async (product: ProductSummary) => {
    setOpening(product.key)
    setError(null)
    try {
      const next = await api.product(product.key)
      setDetail(next)
      setSelected([])
      setPlans([])
      setDeckFilter('')
      const first = next.decks.find((d) => d.loaded)
      setPreview(first ? [first.file_name] : null)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setOpening(null)
    }
  }

  const decks = useMemo(() => new Map((detail?.decks ?? []).map((d) => [d.file_name, d])), [detail])
  const partsOf = (fileNames: string[]) => fileNames.map((f) => decks.get(f)!).filter(Boolean)
  const planOf = new Map(plans.flatMap((p) => p.fileNames.map((f) => [f, p] as const)))
  const unused = (detail?.decks ?? []).filter((d) => !planOf.has(d.file_name))
  const previewParts = preview ? partsOf(preview) : []
  const previewCards = deckCards(previewParts)

  // A big product's decks are fetched when previewed or ticked.
  const ensureLoaded = async (fileNames: string[]) => {
    if (!detail) return
    const todo = fileNames.filter((f) => decks.get(f)?.loaded === false && !loading.includes(f))
    if (!todo.length) return
    setLoading((prev) => [...prev, ...todo])
    try {
      const fetched = await Promise.all(todo.map((f) => api.productDeck(detail.product.key, f)))
      const byName = new Map(fetched.map((d) => [d.file_name, d]))
      setDetail((prev) => prev && { ...prev, decks: prev.decks.map((d) => byName.get(d.file_name) ?? d) })
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading((prev) => prev.filter((f) => !todo.includes(f)))
    }
  }
  const showPreview = (fileNames: string[]) => {
    setPreview(fileNames)
    ensureLoaded(fileNames)
  }

  const addPlan = (fileNames: string[]) => {
    const parts = partsOf(fileNames)
    setPlans((prev) => [
      ...prev,
      { id: Date.now() + prev.length, name: parts.map((p) => p.name).join(' + '), fileNames },
    ])
  }
  const combine = () => {
    addPlan(selected)
    showPreview(selected)
    setSelected([])
  }
  const eachAlone = () => {
    for (const deck of unused) addPlan([deck.file_name])
    setSelected([])
  }

  const create = async () => {
    if (!detail) return
    setBusy(true)
    setError(null)
    try {
      const result = await api.importProduct(detail.product.key, {
        decks: plans.map((p) => ({ name: p.name.trim() || p.fileNames.join(' + '), file_names: p.fileNames })),
        own,
        add_unused: own && addUnused && unused.length > 0,
        unused_location_id: unusedLocation,
      })
      onImported(result.deck_ids)
    } catch (e) {
      setError((e as Error).message)
      setBusy(false)
    }
  }

  const results = found?.q === q ? found.list : null

  if (!detail) {
    return (
      <section className="panel box-import">
        <p className="muted small">{t.boxes.intro}</p>
        <div className="precon-search">
          <input
            className="input"
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t.boxes.placeholder}
            aria-label={t.boxes.placeholder}
          />
          {results !== null && results.length === 0 && <p className="muted small">{t.boxes.none}</p>}
          {results !== null && results.length > 0 && (
            <ul className="precon-results box-results">
              {results.map((p) => (
                <li key={p.key}>
                  <button onClick={() => open(p)} disabled={opening !== null}>
                    <strong>{p.name}</strong>
                    <span className="muted small">
                      {' '}
                      · {p.set_name ?? p.code.toUpperCase()}
                      {p.release_date && ` · ${p.release_date.slice(0, 4)}`} · {t.boxes.decks(p.decks)}
                    </span>
                    {opening === p.key && <span className="muted small"> {t.boxes.loadingDecks}</span>}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        {error && <p className="status error">{error}</p>}
      </section>
    )
  }

  const { product } = detail
  const selectedParts = partsOf(selected)
  const words = deckFilter.toLowerCase().split(/\s+/).filter(Boolean)
  const shownDecks = detail.decks.filter((d) => words.every((w) => d.name.toLowerCase().includes(w)))
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
      <p className="muted small">{t.boxes.hint}</p>
      {detail.decks.length > FILTER_FROM && (
        <input
          className="input box-filter"
          type="search"
          value={deckFilter}
          onChange={(e) => setDeckFilter(e.target.value)}
          placeholder={t.boxes.filter}
          aria-label={t.boxes.filter}
        />
      )}

      <div className="box-decks">
        {shownDecks.map((deck) => {
          const plan = planOf.get(deck.file_name)
          const checked = selected.includes(deck.file_name)
          const missing = notFoundOf(deck)
          return (
            <div
              key={deck.file_name}
              className={`box-deck ${checked ? 'on' : ''} ${plan ? 'used' : ''} ${
                preview?.length === 1 && preview[0] === deck.file_name ? 'previewed' : ''
              }`}
            >
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={checked}
                  disabled={!!plan}
                  onChange={() => {
                    if (!checked) ensureLoaded([deck.file_name])
                    setSelected((prev) =>
                      checked ? prev.filter((f) => f !== deck.file_name) : [...prev, deck.file_name],
                    )
                  }}
                />
                <strong>{deck.name}</strong>
              </label>
              <div className="box-deck-meta">
                {loading.includes(deck.file_name) ? (
                  <span className="muted small">{t.common.loading}</span>
                ) : deck.loaded ? (
                  <>
                    <ManaCost cost={colorsOf([deck])} />
                    <span className="muted small">{t.common.cards(deck.cards)}</span>
                  </>
                ) : (
                  <span className="muted small">{t.boxes.notLoaded}</span>
                )}
                {missing > 0 && <span className="pill error">{t.boxes.notFound(missing)}</span>}
              </div>
              <div className="box-deck-meta">
                <button className="link-button small" onClick={() => showPreview([deck.file_name])}>
                  {t.boxes.preview}
                </button>
                {plan && <span className="muted small">{t.boxes.usedIn(plan.name)}</span>}
              </div>
            </div>
          )
        })}
      </div>

      <div className="actions">
        <button className="button primary" onClick={combine} disabled={selected.length === 0}>
          {selected.length === 1 ? t.boxes.addSingle : t.boxes.combine(countOf(selectedParts))}
        </button>
        <button className="button" onClick={eachAlone} disabled={unused.length === 0}>
          {t.boxes.eachAlone}
        </button>
        {plans.length > 0 && (
          <button className="button" onClick={() => setPlans([])}>
            {t.boxes.clear}
          </button>
        )}
      </div>

      {previewParts.length > 0 && (
        <div className="box-preview">
          <h3 className="deck-group-title">
            {t.boxes.previewOf(previewParts.map((p) => p.name).join(' + '))}{' '}
            <span className="muted">{countOf(previewParts)}</span>
          </h3>
          <DeckVisual
            cards={previewCards}
            mode="stacks"
            grouping="type"
            sort="mv"
            onRemove={() => {}}
            onMenu={() => {}}
            onHover={(entry, e) => hover.show(entry?.card ?? null, e)}
          />
        </div>
      )}

      {plans.length > 0 && (
        <div className="import-save">
          <h2>{t.boxes.plansTitle}</h2>
          <ul className="box-plans">
            {plans.map((plan) => {
              const parts = partsOf(plan.fileNames)
              return (
                <li key={plan.id}>
                  <input
                    className="input"
                    value={plan.name}
                    aria-label={t.decks.name}
                    onChange={(e) =>
                      setPlans((prev) => prev.map((p) => (p.id === plan.id ? { ...p, name: e.target.value } : p)))
                    }
                  />
                  <ManaCost cost={colorsOf(parts)} />
                  <span className="muted small">{t.common.cards(countOf(parts))}</span>
                  <button className="link-button small" onClick={() => showPreview(plan.fileNames)}>
                    {t.boxes.preview}
                  </button>
                  <button
                    className="link-button small danger"
                    onClick={() => setPlans((prev) => prev.filter((p) => p.id !== plan.id))}
                  >
                    {t.boxes.remove}
                  </button>
                </li>
              )
            })}
          </ul>
          <label className="checkbox">
            <input type="checkbox" checked={own} onChange={(e) => setOwn(e.target.checked)} />
            {t.boxes.own}
          </label>
          {own && unused.length > 0 && (
            <div className="box-unused">
              <label className="checkbox">
                <input type="checkbox" checked={addUnused} onChange={(e) => setAddUnused(e.target.checked)} />
                {t.boxes.addUnused(unused.length, countOf(unused))}
              </label>
              <select
                className="select"
                value={unusedLocation ?? ''}
                disabled={!addUnused}
                onChange={(e) => setUnusedLocation(e.target.value ? Number(e.target.value) : null)}
                aria-label={t.items.location}
              >
                <option value="">{t.items.noLocation}</option>
                {locations.map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.name}
                  </option>
                ))}
              </select>
            </div>
          )}
          <div className="actions">
            <button className="button primary" onClick={create} disabled={busy}>
              {busy ? t.importer.saving : t.boxes.create(plans.length)}
            </button>
          </div>
        </div>
      )}
      {error && <p className="status error">{error}</p>}
      {hover.element}
    </section>
  )
}
