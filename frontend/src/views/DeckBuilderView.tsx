import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent, type MouseEvent } from 'react'
import {
  api,
  type CardQuery,
  type CardSummary,
  type DeckCard,
  type DeckFormat,
  type Holding,
  type Platform,
  type DeckStats,
  type ValidationResult,
} from '../api/client'
import { CardDetailPanel } from '../components/CardDetailPanel'
import { CardUsageInfo } from '../components/CardUsageInfo'
import { CardGrid } from '../components/CardGrid'
import { ContextMenu, type MenuItem, type MenuState } from '../components/ContextMenu'
import { ZoomControl } from '../components/ZoomControl'
import { useZoom } from '../hooks/useZoom'
import { DeckHistoryPanel } from '../components/DeckHistoryPanel'
import { DeckList } from '../components/DeckList'
import { DeckStatsPanel } from '../components/DeckStatsPanel'
import { DeckSwitcher } from '../components/DeckSwitcher'
import { DeckCombosPanel } from '../components/DeckCombosPanel'
import { ExportDialog } from '../components/ExportDialog'
import { ProxyDialog } from '../components/ProxyDialog'
import { SimilarCardsPanel } from '../components/SimilarCardsPanel'
import { editUserTagsFromMenu } from '../userTags'
import { Filters } from '../components/Filters'
import { useHoverPreview } from '../hooks/useHoverPreview'
import { ManaColumns } from '../components/ManaColumns'
import { MissingPanel } from '../components/MissingPanel'
import { ManaCost } from '../components/ManaCost'
import { ValidationPanel } from '../components/ValidationPanel'
import {
  canBeCommander,
  COMMANDER_FORMATS,
  matchesCardQuery,
  coverage,
  deckSizeTarget,
  FORMAT_LABEL,
  isBasicLand,
} from '../decks'
import { getCardDrag, isCardDrag, type CardDrag } from '../dnd'
import { EMPTY_FILTERS, toQuery, type FilterState } from '../filters'
import { useCardPages } from '../hooks/useCardPages'
import { useDebounced } from '../hooks/useDebounced'
import { useDeck } from '../hooks/useDeck'
import { formatNumber, locale, t } from '../i18n'

export type DeckTab = 'pool' | 'stats' | 'combos' | 'missing' | 'history'

// How the height is shared between the pool (top) and the mana columns (bottom): the pool alone,
// both, or the deck's columns over the whole height. Remembered per browser.
const LAYOUTS = ['pool', 'split', 'deck'] as const
type Layout = (typeof LAYOUTS)[number]
const LAYOUT_KEY = 'mtgdm.deckbuilderLayout'
// At the largest zoom cards are big enough to read: hovering shows no enlarged copy.
const LARGE_ZOOM = 2

function savedLayout(): Layout {
  try {
    const saved = localStorage.getItem(LAYOUT_KEY)
    return LAYOUTS.find((l) => l === saved) ?? 'split'
  } catch {
    return 'split'
  }
}

interface Props {
  deckId: number
  tab: DeckTab
  onTabChange: (tab: DeckTab) => void
  onBack: () => void
  onOpenDeck: (id: number) => void
}

export function DeckBuilderView({ deckId, tab, onTabChange: setTab, onBack, onOpenDeck }: Props) {
  const actions = useDeck(deckId)
  const { deck } = actions
  const [filters, setFilters] = useState<FilterState>(EMPTY_FILTERS)
  const [constrain, setConstrain] = useState(true)
  const [hideAdded, setHideAdded] = useState(false)
  const [menu, setMenu] = useState<MenuState | null>(null)
  const [detail, setDetail] = useState<{ cardId: string; entry?: DeckCard } | null>(null)
  const [layout, setLayout] = useState<Layout>(savedLayout)
  const [poolZoom, setPoolZoom] = useZoom('pool')
  const [columnsZoom, setColumnsZoom] = useZoom('columns')
  const moveLayout = (step: 1 | -1) => {
    const next = LAYOUTS[Math.min(LAYOUTS.length - 1, Math.max(0, LAYOUTS.indexOf(layout) + step))]
    setLayout(next)
    try {
      localStorage.setItem(LAYOUT_KEY, next)
    } catch {
      // private mode: the layout just isn't remembered
    }
  }
  const [exporting, setExporting] = useState(false)
  const [printing, setPrinting] = useState(false)
  const [dropZone, setDropZone] = useState<'pool' | 'deck' | null>(null)
  const [collectionNote, setCollectionNote] = useState<string | null>(null)
  // Hover info (copies in this deck, where owned copies are) is for the pool; the deck list has the plain preview.
  const deckPreview = useHoverPreview()
  const usageRevision = useMemo(
    () => (deck ? JSON.stringify([deck.location_id, deck.cards.map((c) => [c.card.id, c.quantity, c.board])]) : ''),
    [deck],
  )
  const poolPreview = useHoverPreview(
    (cardId) =>
      deck && (
        <CardUsageInfo cardId={cardId} deckId={deck.id} revision={usageRevision} paper={deck.platform === 'paper'} />
      ),
    poolZoom < LARGE_ZOOM,
  )
  const closeMenu = useCallback(() => setMenu(null), [])
  const [similarTo, setSimilarTo] = useState<CardSummary | null>(null)
  const closeSimilar = useCallback(() => setSimilarTo(null), [])
  const closeDetail = useCallback(() => setDetail(null), [])

  const debounced = useDebounced(filters, 250)
  const query = useMemo<CardQuery>(() => {
    const base = toQuery(debounced)
    const q = deck ? { ...base, deck: deck.id, not_in_deck: hideAdded ? deck.id : undefined } : base
    if (!deck || !constrain) return q
    // Pool limited to what the deck may contain: commander identity, format legality, platform.
    const hasCommander = deck.commander_card_id !== null
    return {
      ...q,
      identity: hasCommander ? deck.color_identity.join('') || 'C' : undefined,
      format: deck.format !== 'freeform' ? deck.format : q.format,
      game: deck.platform === 'arena' ? 'arena' : q.game,
    }
  }, [debounced, deck, constrain, hideAdded])
  const pool = useCardPages(query)

  // Copies in the deck per card name (any printing), shown as badges on the pool.
  const inDeck = useMemo(() => {
    const counts = new Map<string, number>()
    for (const c of deck?.cards ?? []) {
      if (c.board === 'main' || c.board === 'commander') {
        counts.set(c.card.name, (counts.get(c.card.name) ?? 0) + c.quantity)
      }
    }
    return counts
  }, [deck])
  const badge = useCallback((card: CardSummary) => inDeck.get(card.name), [inDeck])
  const singleton = !!deck && deck.format in COMMANDER_FORMATS
  const dimmed = useCallback(
    (card: CardSummary) => singleton && !!inDeck.get(card.name) && !isBasicLand(card.type_line),
    [singleton, inDeck],
  )

  // Validation and stats refetch whenever the deck's contents, format or platform change.
  const revision = useMemo(
    () => (deck ? JSON.stringify([deck.format, deck.platform, deck.cards.map((c) => [c.card.id, c.quantity, c.board])]) : ''),
    [deck],
  )
  const [validation, setValidation] = useState<ValidationResult | null>(null)
  const [price, setPrice] = useState<DeckStats['price'] | null>(null)
  // Paper decks: which cards you don't own, or own but not in the deck's box.
  const [holdings, setHoldings] = useState<Map<string, Holding> | null>(null)
  // Search in the deck: Cmd+F / Ctrl+F jumps to the field, Esc clears it.
  const [deckQuery, setDeckQuery] = useState('')
  const deckSearch = useRef<HTMLInputElement>(null)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'f') {
        e.preventDefault()
        deckSearch.current?.focus()
        deckSearch.current?.select()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
  // Bumped when proxies change (they aren't part of the deck itself).
  const [holdingsVersion, setHoldingsVersion] = useState(0)
  const paper = deck?.platform === 'paper'
  useEffect(() => {
    if (!paper || !usageRevision) return
    let cancelled = false
    const timer = setTimeout(() => {
      api.deckHoldings(deckId).then(
        (list) => !cancelled && setHoldings(new Map(list.map((h) => [h.oracle_id, h]))),
        () => !cancelled && setHoldings(null),
      )
    }, 250)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [deckId, paper, usageRevision, holdingsVersion])
  useEffect(() => {
    if (!revision) return
    let cancelled = false
    // Debounced: rapid clicks in the pool trigger one validation.
    const timer = setTimeout(() => {
      api.validateDeck(deckId).then(
        (r) => !cancelled && setValidation(r),
        () => !cancelled && setValidation(null),
      )
      api.deckStats(deckId).then(
        (s) => !cancelled && setPrice(s.price),
        () => !cancelled && setPrice(null),
      )
    }, 250)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [deckId, revision])

  if (actions.error && !deck) {
    return (
      <div className="view">
        <p className="status error">{actions.error}</p>
        <button className="button" onClick={onBack}>
          {t.builder.back}
        </button>
      </div>
    )
  }
  if (!deck) {
    return (
      <div className="view">
        <p className="muted">{t.builder.loadingDeck}</p>
      </div>
    )
  }

  const isCommanderFormat = deck.format in COMMANDER_FORMATS
  const target = deckSizeTarget(deck.format)
  const violations = new Set(validation?.issues.filter((i) => i.severity === 'error').flatMap((i) => i.card_ids ?? []) ?? [])
  const errorCount = validation?.issues.filter((i) => i.severity === 'error').length ?? 0
  const hasCommander = deck.commander_card_id !== null

  const addFromPool = (card: { id: string; name: string; type_line?: string | null }) => {
    // Singleton formats: adding a second copy of a non-basic is almost always a misclick.
    if (isCommanderFormat && inDeck.get(card.name) && !isBasicLand(card.type_line)) return
    actions.add(card.id)
  }

  // Drag from the pool onto the deck adds a card; dragging a deck card onto the pool removes one.
  const dropTarget = (zone: 'pool' | 'deck', accept: CardDrag['from'], onDrop: (drag: CardDrag) => void) => ({
    onDragOver: (e: DragEvent) => {
      if (!isCardDrag(e)) return
      e.preventDefault()
      if (dropZone !== zone) setDropZone(zone)
    },
    onDragLeave: (e: DragEvent) => {
      if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDropZone(null)
    },
    onDrop: (e: DragEvent) => {
      e.preventDefault()
      setDropZone(null)
      const drag = getCardDrag(e)
      if (drag?.from === accept) onDrop(drag)
    },
  })
  const deckDrop = dropTarget('deck', 'pool', (d) => addFromPool({ id: d.cardId, name: d.name ?? '', type_line: d.typeLine }))
  const poolDrop = dropTarget('pool', 'deck', (d) => actions.remove(d.cardId, (d.board as DeckCard['board']) ?? 'main', 1))

  const poolMenu = (card: CardSummary, e: MouseEvent) => {
    const items: MenuItem[] = [
      { label: t.builder.addToDeck, onClick: () => actions.add(card.id) },
      { label: t.builder.addToMaybe, onClick: () => actions.add(card.id, 'maybe') },
    ]
    if (isCommanderFormat) {
      items.unshift({
        label: hasCommander ? t.builder.addPartner : t.builder.setCommander,
        onClick: () => actions.add(card.id, 'commander'),
        disabled: !canBeCommander(card.type_line) && !(card.type_line ?? '').includes('Background'),
      })
    } else {
      items.push({ label: t.builder.addToSideboard, onClick: () => actions.add(card.id, 'sideboard') })
    }
    items.push({ label: t.similar.menu, onClick: () => setSimilarTo(card) })
    items.push({ label: t.userTags.menu, onClick: () => editUserTagsFromMenu(card) })
    items.push({ label: t.builder.details, onClick: () => setDetail({ cardId: card.id }) })
    setMenu({ x: e.clientX, y: e.clientY, title: card.name, items })
  }

  const entryMenu = (entry: DeckCard, e: MouseEvent) => {
    const { card, board } = entry
    const moves: [typeof board, string][] = [
      ['main', t.builder.moveToMain],
      ['commander', t.builder.setCommander],
      ['maybe', t.builder.moveToMaybe],
      ['sideboard', t.builder.moveToSideboard],
      ['companion', t.builder.setCompanion],
    ]
    const items: MenuItem[] = moves
      .filter(([b]) => b !== board)
      .filter(([b]) => isCommanderFormat || (b !== 'commander' && b !== 'companion'))
      .map(([b, label]) => ({ label, onClick: () => actions.move(card.id, board, b) }))
    items.push({
      label: t.builder.category(entry.category),
      onClick: () => {
        const value = window.prompt(
          t.builder.categoryPrompt,
          entry.category ?? '',
        )
        if (value !== null) actions.setCategory(card.id, board, value.trim())
      },
    })
    items.push({ label: t.builder.details, onClick: () => setDetail({ cardId: card.id, entry }) })
    items.push({ label: t.similar.menu, onClick: () => setSimilarTo(card) })
    items.push({ label: t.userTags.menu, onClick: () => editUserTagsFromMenu(card) })
    if (deck?.platform === 'paper' && board !== 'maybe') {
      items.push({
        label: t.builder.addProxy,
        onClick: () =>
          api.addDeckProxy(deckId, card.id).then(
            () => setHoldingsVersion((n) => n + 1),
            (e: Error) => actions.setError(e.message),
          ),
      })
    }
    items.push({ label: t.builder.removeAll, danger: true, onClick: () => actions.remove(card.id, board) })
    setMenu({ x: e.clientX, y: e.clientY, title: card.name, items })
  }

  const toCollection = async () => {
    const replace = deck.location_id !== null
    if (
      replace &&
      !window.confirm(t.builder.confirmReplaceCollection)
    ) {
      return
    }
    try {
      const result = await api.deckToCollection(deck.id, replace)
      setCollectionNote(t.builder.addedToCollection(result.added, result.location.name))
      actions.reload()
    } catch (e) {
      setCollectionNote(t.common.error((e as Error).message))
    }
  }

  const saveVersion = () => {
    const note = window.prompt(t.builder.versionPrompt, '')
    if (note !== null) actions.saveVersion(note.trim() || undefined)
  }

  const discardChanges = () => {
    const base = deck.changes.base_id
    if (base === null) return
    if (window.confirm(t.builder.confirmDiscard(deck.changes.base_number))) {
      actions.restoreVersion(base)
    }
  }

  const rename = () => {
    const name = window.prompt(t.builder.namePrompt, deck.name)?.trim()
    if (name && name !== deck.name) actions.update({ name })
  }

  return (
    <div className={`view deckbuilder layout-${layout}`}>
      <header className="deckbuilder-header">
        <button className="link-button" onClick={onBack}>
          {t.builder.back}
        </button>
        <h1 className="deck-title" onDoubleClick={rename} title={t.builder.renameTitle}>
          {deck.name}
        </h1>
        <DeckSwitcher deckId={deck.id} onOpen={onOpenDeck} />
        <select
          className="select small"
          value={deck.format}
          onChange={(e) => actions.update({ format: e.target.value as DeckFormat })}
          aria-label={t.decks.format}
        >
          {(Object.keys(FORMAT_LABEL) as DeckFormat[]).map((f) => (
            <option key={f} value={f}>
              {FORMAT_LABEL[f]}
            </option>
          ))}
        </select>
        <select
          className="select small"
          value={deck.platform}
          onChange={(e) => actions.update({ platform: e.target.value as Platform })}
          aria-label={t.decks.platform}
        >
          <option value="arena">Arena</option>
          <option value="paper">{t.deck.paper}</option>
        </select>
        <ManaCost cost={deck.color_identity.map((c) => `{${c}}`).join('')} />
        {validation && (
          <span className={`validity ${validation.valid ? 'ok' : 'error'}`} title={t.builder.formatRules}>
            {validation.valid ? t.builder.valid : t.builder.errors(errorCount)}
          </span>
        )}
        <span className={`deck-count ${target && deck.counts.total !== target ? 'warn-text' : ''}`}>
          {deck.counts.total}
          {target ? ` / ${target}` : ''}
        </span>
        {paper && holdings && <CoverageTotals holdings={holdings} />}
        {price && (
          <span
            className="deck-price"
            title={t.builder.priceTitle(price.usd, price.as_of ? new Date(price.as_of).toLocaleDateString(locale) : null)}
          >
            €{price.eur.toFixed(2)}
            {paper && price.missing_eur > 0 && (
              <span className="warn-text"> · {t.builder.missingPrice(price.missing_eur.toFixed(2))}</span>
            )}
          </span>
        )}
        {deck.platform === 'paper' && (
          <button
            className="button header-action"
            onClick={toCollection}
            title={t.builder.toCollectionTitle}
          >
            {deck.location_id === null ? t.builder.ownDeck : t.builder.inCollection}
          </button>
        )}
        {deck.platform === 'paper' && (
          <button className="button" onClick={() => setPrinting(true)} title={t.print.buttonTitle}>
            {t.print.button}
          </button>
        )}
        <button className={`button ${deck.platform === 'paper' ? '' : 'header-action'}`} onClick={() => setExporting(true)}>
          {t.builder.export}
        </button>
        {deck.unsaved_changes > 0 ? (
          <span className="unsaved">
            <button className="link-button unsaved-label" onClick={() => setTab('history')} title={t.builder.showChanges}>
              {t.builder.unsaved(deck.unsaved_changes)}
            </button>
            <button className="button primary small" onClick={saveVersion} disabled={actions.busy}>
              {t.builder.saveVersion}
            </button>
            {deck.changes.base_id !== null && (
              <button className="link-button small" onClick={discardChanges} disabled={actions.busy}>
                {t.builder.discard}
              </button>
            )}
          </span>
        ) : (
          deck.changes.base_number !== null && (
            <button className="link-button muted small" onClick={() => setTab('history')} title={t.builder.versionHistory}>
              {t.builder.saved(deck.changes.base_number)}
            </button>
          )
        )}
        {collectionNote && (
          <span className="muted small" onClick={() => setCollectionNote(null)}>
            {collectionNote}
          </span>
        )}
        {actions.busy && <span className="muted small">{t.builder.saving}</span>}
        {actions.error && (
          <span className="status error small" onClick={actions.clearError}>
            {actions.error}
          </span>
        )}
      </header>

      <section className={`deckbuilder-pool ${dropZone === 'pool' ? 'drop-target' : ''}`} {...poolDrop}>
        <div className="segmented pool-tabs" role="tablist">
          <button className={tab === 'pool' ? 'on' : ''} onClick={() => setTab('pool')} role="tab">
            {t.builder.tabPool}
          </button>
          <button className={tab === 'stats' ? 'on' : ''} onClick={() => setTab('stats')} role="tab">
            {t.builder.tabStats}
          </button>
          <button className={tab === 'combos' ? 'on' : ''} onClick={() => setTab('combos')} role="tab">
            {t.builder.tabCombos}
          </button>
          {deck.platform === 'paper' && (
            <button className={tab === 'missing' ? 'on' : ''} onClick={() => setTab('missing')} role="tab">
              {t.builder.tabMissing}
            </button>
          )}
          <button className={tab === 'history' ? 'on' : ''} onClick={() => setTab('history')} role="tab">
            {t.builder.tabHistory}
            {deck.unsaved_changes > 0 && <span className="unsaved-dot"> ●</span>}
          </button>
        </div>
        {tab === 'history' ? (
          <div className="stats-scroll">
            <DeckHistoryPanel
              deck={deck}
              revision={revision}
              busy={actions.busy}
              onSave={saveVersion}
              onRestore={(v) => actions.restoreVersion(v.id)}
              onHover={deckPreview.show}
            />
          </div>
        ) : tab === 'stats' ? (
          <div className="stats-scroll">
            <DeckStatsPanel deckId={deck.id} platform={deck.platform} revision={revision} />
          </div>
        ) : tab === 'combos' ? (
          <div className="stats-scroll">
            <DeckCombosPanel
              deckId={deck.id}
              revision={revision}
              onAdd={(cardId) => actions.add(cardId)}
              onHover={deckPreview.show}
            />
          </div>
        ) : tab === 'missing' && deck.platform === 'paper' ? (
          <div className="stats-scroll">
            <MissingPanel deckId={deck.id} revision={revision + (deck.location_id ?? '')} onHover={deckPreview.show} />
          </div>
        ) : (
          <>
            <Filters value={filters} onChange={setFilters} allowFree={deck.platform === 'paper'} />
            <div className="pool-bar">
              <label className="checkbox">
                <input type="checkbox" checked={constrain} onChange={(e) => setConstrain(e.target.checked)} />
                {t.builder.constrain}
                <span className="muted small">
                  {' '}
                  ({[hasCommander && t.builder.commanderIdentity, deck.format !== 'freeform' && FORMAT_LABEL[deck.format], deck.platform === 'arena' && 'Arena']
                    .filter(Boolean)
                    .join(', ') || t.builder.noConstraints}
                  )
                </span>
              </label>
              <label className="checkbox">
                <input type="checkbox" checked={hideAdded} onChange={(e) => setHideAdded(e.target.checked)} />
                {t.builder.hideAdded}
              </label>
              <span className="muted small">
                {pool.total === null ? t.collection.searching : t.builder.poolCount(formatNumber(pool.total))}
              </span>
              <ZoomControl zoom={poolZoom} onChange={setPoolZoom} />
            </div>
            <CardGrid
              total={pool.total ?? 0}
              cardAt={pool.cardAt}
              ensureRange={pool.ensureRange}
              onSelect={addFromPool}
              onContextMenu={poolMenu}
              onHover={poolPreview.show}
              badge={badge}
              dimmed={dimmed}
              minCardWidth={140 * poolZoom}
              draggable
            />
          </>
        )}
      </section>

      <aside className={`deckbuilder-list ${dropZone === 'deck' ? 'drop-target' : ''}`} {...deckDrop}>
        <ValidationPanel result={validation} />
        {isCommanderFormat && !hasCommander && (
          <p className="hint">
            {t.builder.chooseCommander}
          </p>
        )}
        {deck.cards.length > 0 && (
          <div className="deck-search">
            <input
              ref={deckSearch}
              className="input small"
              type="search"
              value={deckQuery}
              onChange={(e) => setDeckQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Escape') {
                  setDeckQuery('')
                  e.currentTarget.blur()
                }
              }}
              placeholder={t.builder.searchDeck}
              aria-label={t.builder.searchDeck}
            />
            {deckQuery.trim() && (
              <span className="muted small">
                {t.builder.searchCount(
                  deck.cards.filter((c) => matchesCardQuery(c.card, deckQuery)).reduce((n, c) => n + c.quantity, 0),
                )}
              </span>
            )}
          </div>
        )}
        {deck.cards.length === 0 ? (
          <p className="muted">{t.builder.emptyDeck}</p>
        ) : (
          <DeckList
            query={deckQuery}
            cards={deck.cards}
            violations={violations}
            changes={deck.changes.cards}
            holdings={paper ? holdings : null}
            onRestore={(c) => c.card && actions.add(c.card.id, c.board, c.before)}
            onAdd={(entry) => actions.add(entry.card.id, entry.board)}
            onRemove={(entry) => actions.remove(entry.card.id, entry.board, 1)}
            onMenu={entryMenu}
            onHover={(entry, e) => deckPreview.show(entry?.card ?? null, e)}
          />
        )}
      </aside>

      <section className={`deckbuilder-columns ${dropZone === 'deck' ? 'drop-target' : ''}`} {...deckDrop}>
        <div className="columns-toggle">
          {layout !== 'pool' && <ZoomControl zoom={columnsZoom} onChange={setColumnsZoom} />}
          <button onClick={() => moveLayout(1)} disabled={layout === 'deck'} title={t.builder.expandDeckTitle}>
            {t.builder.expandDeck}
          </button>
          <button onClick={() => moveLayout(-1)} disabled={layout === 'pool'} title={t.builder.expandPoolTitle}>
            {t.builder.expandPool}
          </button>
        </div>
        {layout !== 'pool' && (
          <ManaColumns
            zoom={columnsZoom}
            query={deckQuery}
            cards={deck.cards}
            changes={deck.changes.cards}
            holdings={paper ? holdings : null}
            onRemove={(entry) => actions.remove(entry.card.id, entry.board, 1)}
            onMenu={entryMenu}
            onHover={(entry, e) => deckPreview.show(columnsZoom < LARGE_ZOOM ? (entry?.card ?? null) : null, e)}
          />
        )}
      </section>

      {deckPreview.element}
      {poolPreview.element}
      {menu && <ContextMenu menu={menu} onClose={closeMenu} />}
      {exporting && <ExportDialog deckId={deck.id} onClose={() => setExporting(false)} />}
      {printing && (
        <ProxyDialog
          deckId={deck.id}
          deckName={deck.name}
          onClose={() => {
            setPrinting(false)
            setHoldingsVersion((n) => n + 1) // proxies may have been marked
          }}
        />
      )}
      {similarTo && (
        <SimilarCardsPanel
          card={similarTo}
          deckId={deck.id}
          deckColors={deck.color_identity}
          onPick={addFromPool}
          onContextMenu={poolMenu}
          hoverInfo={(cardId) => (
            <CardUsageInfo cardId={cardId} deckId={deck.id} revision={usageRevision} paper={deck.platform === 'paper'} />
          )}
          badge={badge}
          dimmed={dimmed}
          onClose={closeSimilar}
        />
      )}
      {detail && (
        <div className="modal-backdrop" onClick={closeDetail}>
          <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
            <CardDetailPanel
              key={detail.cardId}
              cardId={detail.cardId}
              onClose={closeDetail}
              onChoosePrinting={
                detail.entry &&
                ((printingId) => {
                  actions.swapPrinting(detail.cardId, detail.entry!.board, printingId)
                  closeDetail()
                })
              }
            />
          </div>
        </div>
      )}
    </div>
  )
}

/** Paper decks: what the deck's copies are (real + proxy + missing = the deck's size), and the
sideboard's in short (covered / size, details on hover). */
function CoverageTotals({ holdings }: { holdings: Map<string, Holding> }) {
  const { deck, sideboard } = coverage(holdings.values())
  const sideSize = sideboard.real + sideboard.proxy + sideboard.uncovered
  return (
    <span className="coverage-totals small" title={t.builder.coverageTitle}>
      {t.builder.coverageReal(deck.real)} · <span className="proxy-text">{t.builder.coverageProxy(deck.proxy)}</span> ·{' '}
      <span className={deck.uncovered ? 'error-text' : ''}>{t.builder.coverageMissing(deck.uncovered)}</span>
      {sideSize > 0 && (
        <span
          className={sideboard.uncovered ? 'error-text' : 'muted'}
          title={t.builder.coverageSideboardTitle(sideboard.real, sideboard.proxy, sideboard.uncovered)}
        >
          {' '}
          · {t.builder.coverageSideboard(sideboard.real + sideboard.proxy, sideSize)}
        </span>
      )}
    </span>
  )
}
