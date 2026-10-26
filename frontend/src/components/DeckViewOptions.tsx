import { DECK_GROUPINGS, DECK_SORTS, type DeckGrouping, type DeckSort } from '../decks'
import type { DeckView } from '../hooks/useDeckView'
import { t } from '../i18n'

const GROUPING_LABEL: Record<DeckGrouping, string> = {
  type: t.deckView.groupType,
  mv: t.deckView.groupMv,
  color: t.deckView.groupColor,
  rarity: t.deckView.groupRarity,
  category: t.deckView.groupCategory,
  none: t.deckView.groupNone,
}

const SORT_LABEL: Record<DeckSort, string> = {
  name: t.filters.sortName,
  mv: t.filters.sortMv,
}

/** Two selects: how the deck's cards are grouped and sorted within a group. */
export function DeckViewOptions({ view, className = 'select small' }: { view: DeckView; className?: string }) {
  return (
    <>
      <select
        className={className}
        value={view.grouping}
        onChange={(e) => view.setGrouping(e.target.value as DeckGrouping)}
        aria-label={t.deckView.grouping}
        title={view.grouping === 'category' ? t.deckView.groupCategoryTitle : t.deckView.grouping}
      >
        {DECK_GROUPINGS.map((g) => (
          <option key={g} value={g}>
            {GROUPING_LABEL[g]}
          </option>
        ))}
      </select>
      <select
        className={className}
        value={view.sort}
        onChange={(e) => view.setSort(e.target.value as DeckSort)}
        aria-label={t.filters.sorting}
        title={t.filters.sorting}
      >
        {DECK_SORTS.map((s) => (
          <option key={s} value={s}>
            {SORT_LABEL[s]}
          </option>
        ))}
      </select>
    </>
  )
}
