import { Fragment, useEffect, useMemo, useState, type MouseEvent } from 'react'
import { api, type CardFit, type CompareRow, type DeckComparison, type DeckDetail, type DeckSummary } from '../api/client'
import { FORMAT_LABEL } from '../decks'
import { useHoverPreview } from '../hooks/useHoverPreview'
import { ManaCost } from './ManaCost'
import { locale, t } from '../i18n'

type Sort = 'mv-asc' | 'mv-desc' | 'price-desc' | 'price-asc' | 'name'
type View = 'side' | 'table' | 'diff'
const STORE_KEY = 'mtgdm.compareWith'

/** The deck (A) next to another one (B), card by card: copies in each, price, what one could take from
the other. Side by side, a table, or a diff with B's lines under A's; sorted by mana value or price, equal
ones by name. */
export function DeckComparePanel({
  deck,
  revision,
  onAddHere,
}: {
  deck: DeckDetail
  revision: string
  onAddHere: (cardId: string, quantity: number) => Promise<unknown>
}) {
  const [decks, setDecks] = useState<DeckSummary[]>([])
  const [otherId, setOtherId] = useState<number | null>(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(STORE_KEY) ?? '{}') as Record<string, number>
      return saved[deck.id] ?? null
    } catch {
      return null
    }
  })
  const [view, setView] = useState<View>('side')
  const [sort, setSort] = useState<Sort>('mv-asc')
  const [nameDesc, setNameDesc] = useState(false)
  const [showSame, setShowSame] = useState(false)
  const [otherRevision, setOtherRevision] = useState(0)
  const [result, setResult] = useState<{ key: string; data: DeckComparison } | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.decks().then(setDecks, (e: Error) => setError(e.message))
  }, [])

  // No deck chosen yet: one with the same commander (the other platform first), if any.
  const others = decks.filter((d) => d.id !== deck.id)
  const suggested =
    otherId ??
    (others
      .filter((d) => deck.commander_name && d.commander_name === deck.commander_name)
      .sort((a, b) => Number(a.platform === deck.platform) - Number(b.platform === deck.platform))[0]?.id ?? null)
  const key = `${deck.id}|${suggested}|${revision}|${otherRevision}`

  useEffect(() => {
    if (suggested === null) return
    let cancelled = false
    api.compareDecks(deck.id, suggested).then(
      (data) => !cancelled && setResult({ key, data }),
      (e: Error) => !cancelled && setError(e.message),
    )
    return () => {
      cancelled = true
    }
  }, [deck.id, suggested, key])

  const choose = (id: number | null) => {
    setOtherId(id)
    try {
      const saved = JSON.parse(localStorage.getItem(STORE_KEY) ?? '{}') as Record<string, number | null>
      localStorage.setItem(STORE_KEY, JSON.stringify({ ...saved, [deck.id]: id }))
    } catch {
      // the choice just isn't remembered
    }
  }

  const data = result?.key === key ? result.data : (result?.data ?? null) // the last one until the new arrives
  const rows = useMemo(() => {
    const all = data?.rows ?? []
    const shown = showSame ? all : all.filter((r) => r.a !== r.b)
    const byName = (a: CompareRow, b: CompareRow) => (nameDesc ? -1 : 1) * a.name.localeCompare(b.name, locale)
    if (sort === 'name') return [...shown].sort(byName)
    const value = (r: CompareRow) => (sort === 'mv-asc' || sort === 'mv-desc' ? r.card.cmc : r.price_eur)
    const sign = sort === 'mv-desc' || sort === 'price-desc' ? -1 : 1
    // Equal values by name; cards without one (no price) last either way.
    return [...shown].sort((a, b) => {
      const va = value(a)
      const vb = value(b)
      if (va == null || vb == null) return va == null ? (vb == null ? byName(a, b) : 1) : -1
      return sign * (va - vb) || byName(a, b)
    })
  }, [data, showSame, sort, nameDesc])

  // Sorted by mana value: a heading where it changes.
  const grouped = sort === 'mv-asc' || sort === 'mv-desc'
  const groupAt = (i: number) =>
    grouped && (i === 0 || rows[i].card.cmc !== rows[i - 1].card.cmc) ? t.compare.mvGroup(rows[i].card.cmc ?? '—') : null

  const byCardId = useMemo(() => new Map((data?.rows ?? []).map((r) => [r.card.id, r])), [data])
  const preview = useHoverPreview((cardId) => {
    const row = byCardId.get(cardId)
    return row && data ? <FitInfo row={row} data={data} /> : null
  })
  // On the name, not the whole row: the preview opens next to it, with the card's image.
  const name = (row: CompareRow, text: string) => (
    <span className="compare-name" onMouseEnter={(e: MouseEvent) => preview.show(row.card, e)} onMouseLeave={() => preview.show(null)}>
      {text}
    </span>
  )

  const addToOther = async (row: CompareRow) => {
    if (!data || !row.fit_b.card_id) return
    try {
      await api.addDeckCard(data.b.id, row.fit_b.card_id, 'main', row.fit_b.addable)
      setOtherRevision((n) => n + 1)
    } catch (e) {
      setError((e as Error).message)
    }
  }
  const addHere = async (row: CompareRow) => {
    if (!row.fit_a.card_id) return
    try {
      await onAddHere(row.fit_a.card_id, row.fit_a.addable)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const counts = useMemo(() => {
    const all = data?.rows ?? []
    return {
      onlyA: all.filter((r) => r.a > 0 && r.b === 0).length,
      onlyB: all.filter((r) => r.b > 0 && r.a === 0).length,
      differ: all.filter((r) => r.a > 0 && r.b > 0 && r.a !== r.b).length,
      same: all.filter((r) => r.a === r.b).length,
      priceA: all.reduce((sum, r) => sum + r.a * (r.price_eur ?? 0), 0),
      priceB: all.reduce((sum, r) => sum + r.b * (r.price_eur ?? 0), 0),
    }
  }, [data])

  // One deck's side of a row: its copies, or (none) why the other deck's can't come here.
  const sideCell = (row: CompareRow, copies: number, fit: CardFit, side: DeckComparison['a'], lacks: boolean) => (
    <div className={`side-cell ${copies ? '' : 'empty'}`}>
      {copies > 0 ? (
        <>
          {name(row, `${copies} ${row.name}`)}
          <span className="side-meta">
            <ManaCost cost={row.card.mana_cost} />
            <span className="muted small">{row.price_eur != null ? `€${row.price_eur.toFixed(2)}` : '—'}</span>
          </span>
        </>
      ) : (
        lacks && fit.addable === 0 && <span className="muted small">{blocker(fit, side)}</span>
      )}
    </div>
  )

  const actions = (row: CompareRow) => (
    <span className="compare-actions">
      {row.fit_b.addable > 0 && (
        <button className="link-button small" onClick={() => addToOther(row)} title={t.compare.addToTitle(data?.b.name ?? '')}>
          {t.compare.toB(row.fit_b.addable)}
        </button>
      )}
      {row.fit_a.addable > 0 && (
        <button className="link-button small" onClick={() => addHere(row)} title={t.compare.addToTitle(deck.name)}>
          {t.compare.toA(row.fit_a.addable)}
        </button>
      )}
      {row.a > row.b && row.fit_b.addable === 0 && <span className="muted small">{blocker(row.fit_b, data?.b)}</span>}
      {row.b > row.a && row.fit_a.addable === 0 && <span className="muted small">{blocker(row.fit_a, data?.a)}</span>}
    </span>
  )

  return (
    <div className="compare-panel">
      <div className="compare-toolbar">
        <label className="checkbox">
          {t.compare.with}
          <select className="select" value={suggested ?? ''} onChange={(e) => choose(e.target.value ? Number(e.target.value) : null)}>
            <option value="">{t.compare.pick}</option>
            {others.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name} · {FORMAT_LABEL[d.format]}
                {d.platform === 'arena' ? ' · Arena' : ''}
              </option>
            ))}
          </select>
        </label>
        <div className="segmented" role="tablist">
          <button className={view === 'side' ? 'on' : ''} onClick={() => setView('side')}>
            {t.compare.side}
          </button>
          <button className={view === 'table' ? 'on' : ''} onClick={() => setView('table')}>
            {t.compare.table}
          </button>
          <button className={view === 'diff' ? 'on' : ''} onClick={() => setView('diff')}>
            {t.compare.diff}
          </button>
        </div>
        <select className="select" value={sort} onChange={(e) => setSort(e.target.value as Sort)} aria-label={t.compare.sort}>
          <option value="mv-asc">{t.compare.mvAsc}</option>
          <option value="mv-desc">{t.compare.mvDesc}</option>
          <option value="price-desc">{t.compare.priceDesc}</option>
          <option value="price-asc">{t.compare.priceAsc}</option>
          <option value="name">{t.compare.byName}</option>
        </select>
        <div className="segmented" title={t.compare.nameOrder}>
          <button className={nameDesc ? '' : 'on'} onClick={() => setNameDesc(false)}>
            {t.compare.nameAsc}
          </button>
          <button className={nameDesc ? 'on' : ''} onClick={() => setNameDesc(true)}>
            {t.compare.nameDesc}
          </button>
        </div>
        <label className="checkbox">
          <input type="checkbox" checked={showSame} onChange={(e) => setShowSame(e.target.checked)} />
          {t.compare.showSame}
        </label>
      </div>

      {error && <p className="status error">{error}</p>}
      {suggested === null && <p className="muted">{t.compare.choose}</p>}
      {suggested !== null && !data && !error && <p className="muted">{t.common.loading}</p>}
      {data && (
        <>
          <p className="muted small">
            {t.compare.summary(counts.onlyA, counts.onlyB, counts.differ, counts.same)} ·{' '}
            {t.compare.prices(counts.priceA.toFixed(2), counts.priceB.toFixed(2))}
          </p>
          {rows.length === 0 ? (
            <p className="muted">{t.compare.identical}</p>
          ) : view === 'side' ? (
            <div className="compare-side">
              <div className="side-row side-head">
                <div>
                  <strong>A · {data.a.name}</strong>
                  <div className="muted small">€{counts.priceA.toFixed(2)}</div>
                </div>
                <div />
                <div>
                  <strong>B · {data.b.name}</strong>
                  <div className="muted small">€{counts.priceB.toFixed(2)}</div>
                </div>
              </div>
              {rows.map((row, i) => (
                <Fragment key={row.oracle_id}>
                  {groupAt(i) && <div className="compare-group">{groupAt(i)}</div>}
                  <div className={`side-row compare-${status(row)}`}>
                    {sideCell(row, row.a, row.fit_a, data.a, row.b > row.a)}
                    <div className="side-middle">
                      {row.fit_b.addable > 0 && (
                        <button className="link-button small" onClick={() => addToOther(row)} title={t.compare.addToTitle(data.b.name)}>
                          → +{row.fit_b.addable}
                        </button>
                      )}
                      {row.fit_a.addable > 0 && (
                        <button className="link-button small" onClick={() => addHere(row)} title={t.compare.addToTitle(deck.name)}>
                          +{row.fit_a.addable} ←
                        </button>
                      )}
                    </div>
                    {sideCell(row, row.b, row.fit_b, data.b, row.a > row.b)}
                  </div>
                </Fragment>
              ))}
            </div>
          ) : view === 'table' ? (
            <table className="missing-table compare-table">
              <thead>
                <tr>
                  <th>{t.panels.card}</th>
                  <th>{t.compare.manaCost}</th>
                  <th className="num" title={data.a.name}>
                    A
                  </th>
                  <th className="num" title={data.b.name}>
                    B
                  </th>
                  <th className="num">{t.panels.price}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((row, i) => (
                  <Fragment key={row.oracle_id}>
                    {groupAt(i) && (
                      <tr className="compare-group">
                        <td colSpan={6}>{groupAt(i)}</td>
                      </tr>
                    )}
                    <tr className={`compare-${status(row)}`}>
                      <td>{name(row, row.name)}</td>
                      <td>
                        <ManaCost cost={row.card.mana_cost} />
                      </td>
                      <td className="num strong">{row.a || '–'}</td>
                      <td className="num strong">{row.b || '–'}</td>
                      <td className="num muted">{row.price_eur != null ? `€${row.price_eur.toFixed(2)}` : '—'}</td>
                      <td>{actions(row)}</td>
                    </tr>
                  </Fragment>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="compare-diff">
              {rows.map((row, i) => (
                <Fragment key={row.oracle_id}>
                  {groupAt(i) && <div className="compare-group">{groupAt(i)}</div>}
                  <div className="diff-row">
                    <div className="diff-lines">
                      {row.a === row.b ? (
                        <div className="diff-line same">
                          <span className="diff-sign"> </span>
                          {name(row, `${row.a} ${row.name}`)}
                          <ManaCost cost={row.card.mana_cost} />
                        </div>
                      ) : (
                        <>
                          {row.a > 0 && (
                            <div className="diff-line removed">
                              <span className="diff-sign">−</span>
                              {name(row, `${row.a} ${row.name}`)}
                              <ManaCost cost={row.card.mana_cost} />
                            </div>
                          )}
                          {row.b > 0 && (
                            <div className="diff-line added">
                              <span className="diff-sign">+</span>
                              {name(row, `${row.b} ${row.name}`)}
                              <ManaCost cost={row.card.mana_cost} />
                            </div>
                          )}
                        </>
                      )}
                    </div>
                    {row.a !== row.b && actions(row)}
                  </div>
                </Fragment>
              ))}
            </div>
          )}
          <p className="muted small">{t.compare.legend(data.a.name, data.b.name)}</p>
        </>
      )}
      {preview.element}
    </div>
  )
}

function status(row: CompareRow): 'same' | 'only-a' | 'only-b' | 'differ' {
  if (row.a === row.b) return 'same'
  if (row.b === 0) return 'only-a'
  if (row.a === 0) return 'only-b'
  return 'differ'
}

/** Why a card can't go into a deck. */
function blocker(fit: CardFit, side?: DeckComparison['a']): string {
  if (!fit.legal) return t.compare.notLegal(side ? FORMAT_LABEL[side.format as keyof typeof FORMAT_LABEL] : '')
  if (!fit.on_platform) return t.compare.notOnArena
  if (!fit.in_identity) return t.compare.notInIdentity
  return t.compare.atLimit
}

/** Hover info: the card in each deck, and whether it could go there. */
function FitInfo({ row, data }: { row: CompareRow; data: DeckComparison }) {
  const line = (side: DeckComparison['a'], copies: number, fit: CardFit) => (
    <div>
      <strong>{side.name}</strong>{' '}
      <span className="muted">
        ({FORMAT_LABEL[side.format as keyof typeof FORMAT_LABEL]}
        {side.platform === 'arena' ? ', Arena' : ''})
      </span>
      :{' '}
      {copies > 0
        ? t.compare.inDeck(copies)
        : fit.legal && fit.in_identity && fit.on_platform
          ? t.compare.fits
          : blocker(fit, side)}
    </div>
  )
  return (
    <div className="usage-info small">
      {line(data.a, row.a, row.fit_a)}
      {line(data.b, row.b, row.fit_b)}
    </div>
  )
}
