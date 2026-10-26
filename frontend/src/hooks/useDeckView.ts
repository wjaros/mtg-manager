import { DECK_GROUPINGS, DECK_SORTS, type DeckGrouping, type DeckSort } from '../decks'
import { useStoredChoice } from './useStoredChoice'

export interface DeckView {
  grouping: DeckGrouping
  sort: DeckSort
  setGrouping: (grouping: DeckGrouping) => void
  setSort: (sort: DeckSort) => void
}

/** Grouping and sorting of one deck view, remembered per browser under `mtgdm.deckView.<key>.*`. */
export function useDeckView(key: string, grouping: DeckGrouping, sort: DeckSort): DeckView {
  const [g, setGrouping] = useStoredChoice(`mtgdm.deckView.${key}.grouping`, DECK_GROUPINGS, grouping)
  const [s, setSort] = useStoredChoice(`mtgdm.deckView.${key}.sort`, DECK_SORTS, sort)
  return { grouping: g, sort: s, setGrouping, setSort }
}
