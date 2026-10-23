import type { DeckCard, DeckChange, DeckFormat, Holding, Platform } from './api/client'
import { t } from './i18n'

export const FORMAT_LABEL: Record<DeckFormat, string> = {
  brawl: 'Brawl (Historic)',
  standardbrawl: 'Standard Brawl',
  commander: 'Commander',
  historic: 'Historic',
  standard: 'Standard',
  pioneer: 'Pioneer',
  freeform: t.deck.freeform,
}

export const PLATFORM_LABEL: Record<Platform, string> = {
  paper: t.deck.paper,
  arena: t.deck.arena,
}

/** Formats with a commander and singleton rules; target deck size including the commander. */
export const COMMANDER_FORMATS: Partial<Record<DeckFormat, number>> = {
  brawl: 100,
  standardbrawl: 60,
  commander: 100,
}

export function deckSizeTarget(format: DeckFormat): number | null {
  return COMMANDER_FORMATS[format] ?? (format === 'freeform' ? null : 60)
}

// Order of type groups in the deck list; a card goes to the first group its type line matches.
const TYPE_GROUPS = [
  ['Creature', t.deck.typeCreature],
  ['Planeswalker', t.deck.typePlaneswalker],
  ['Battle', t.deck.typeBattle],
  ['Instant', t.deck.typeInstant],
  ['Sorcery', t.deck.typeSorcery],
  ['Artifact', t.deck.typeArtifact],
  ['Enchantment', t.deck.typeEnchantment],
  ['Land', t.deck.typeLand],
] as const

export function primaryType(typeLine: string | null | undefined): string {
  // For double-faced cards the front face decides.
  const front = (typeLine ?? '').split('//')[0]
  for (const [type] of TYPE_GROUPS) {
    if (front.includes(type)) return type
  }
  return 'Other'
}

export function isLand(card: DeckCard): boolean {
  return primaryType(card.card.type_line) === 'Land'
}

export function isBasicLand(typeLine: string | null | undefined): boolean {
  return (typeLine ?? '').includes('Basic') && (typeLine ?? '').includes('Land')
}

export interface CardGroup {
  type: string
  label: string
  cards: DeckCard[]
  count: number
}

/** Key of a card name on a board, as used by deck changes. */
export function changeKey(name: string, board: string): string {
  return `${board}|${name}`
}

export function changesByKey(changes: DeckChange[]): Map<string, DeckChange> {
  return new Map(changes.map((c) => [changeKey(c.name, c.board), c]))
}

export function changeLabel(change: DeckChange): string {
  if (change.before === 0) return t.deck.changeNew
  if (change.after === 0) return t.deck.changeRemoved
  const delta = change.after - change.before
  if (delta) return delta > 0 ? `+${delta}` : `−${-delta}`
  return t.deck.changePrinting
}

export function changeKind(change: DeckChange): 'added' | 'removed' | 'more' | 'less' | 'printing' {
  if (change.before === 0) return 'added'
  if (change.after === 0) return 'removed'
  if (change.after > change.before) return 'more'
  if (change.after < change.before) return 'less'
  return 'printing'
}

/** Physical state of a deck card: not owned (enough), only in other decks' boxes, loose / in a binder. */
export type HoldState =
  | { kind: 'missing'; missing: number; needed: number }
  | { kind: 'other_deck'; decks: string[] }
  | { kind: 'elsewhere' }
  | { kind: 'proxy'; proxy: number; needed: number }
  | null

export function holdState(holding: Holding | undefined): HoldState {
  if (!holding?.state) return null
  if (holding.state === 'missing') return { kind: 'missing', missing: holding.missing, needed: holding.needed }
  if (holding.state === 'other_deck') return { kind: 'other_deck', decks: holding.other_decks }
  if (holding.state === 'proxy') return { kind: 'proxy', proxy: holding.proxy ?? 0, needed: holding.needed }
  return { kind: 'elsewhere' }
}

export function holdTitle(state: NonNullable<HoldState>): string {
  if (state.kind === 'missing') return t.panels.holdMissingTitle(state.missing, state.needed)
  if (state.kind === 'other_deck') return t.panels.holdOtherDeckTitle(state.decks.join(', '))
  if (state.kind === 'proxy') return t.panels.holdProxyTitle(state.proxy, state.needed)
  return t.panels.holdElsewhereTitle
}

export interface Coverage {
  real: number
  proxy: number
  uncovered: number
}

/** Real + proxy + uncovered copies of a paper deck: the deck itself (sum = its size, like the
card count next to it) and its sideboard apart (copies go to the deck first). */
export function coverage(holdings: Iterable<Holding>): { deck: Coverage; sideboard: Coverage } {
  const deck = { real: 0, proxy: 0, uncovered: 0 }
  const sideboard = { real: 0, proxy: 0, uncovered: 0 }
  for (const h of holdings) {
    const side = h.sideboard ?? 0
    const sideReal = h.sideboard_real ?? 0
    const sideProxy = h.sideboard_proxy ?? 0
    sideboard.real += sideReal
    sideboard.proxy += sideProxy
    sideboard.uncovered += side - sideReal - sideProxy
    deck.real += (h.real ?? 0) - sideReal
    deck.proxy += (h.proxy ?? 0) - sideProxy
    deck.uncovered += (h.uncovered ?? 0) - (side - sideReal - sideProxy)
  }
  return { deck, sideboard }
}

export function groupByType(cards: DeckCard[]): CardGroup[] {
  const groups = new Map<string, DeckCard[]>()
  for (const c of cards) {
    const type = primaryType(c.card.type_line)
    groups.set(type, [...(groups.get(type) ?? []), c])
  }
  const order: (readonly [string, string])[] = [...TYPE_GROUPS, ['Other', t.deck.typeOther]]
  return order
    .filter(([type]) => groups.has(type))
    .map(([type, label]) => {
      const list = [...groups.get(type)!].sort(
        (a, b) => (a.card.cmc ?? 0) - (b.card.cmc ?? 0) || a.card.name.localeCompare(b.card.name),
      )
      return { type, label, cards: list, count: list.reduce((n, c) => n + c.quantity, 0) }
    })
}

export function canBeCommander(typeLine: string | null | undefined): boolean {
  const front = (typeLine ?? '').split('//')[0]
  return front.includes('Legendary') && (front.includes('Creature') || front.includes('Planeswalker'))
}

/** Lower case without diacritics, for searching card names ("Éowyn" matches "eowyn"). */
function fold(text: string): string {
  return text.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase()
}

/** Does the card's name (or its printed name) contain every word of the query? */
export function matchesCardQuery(card: { name: string; printed_name?: string | null }, query: string): boolean {
  const words = fold(query).split(/\s+/).filter(Boolean)
  if (!words.length) return true
  const text = fold(`${card.name} ${card.printed_name ?? ''}`)
  return words.every((w) => text.includes(w))
}
