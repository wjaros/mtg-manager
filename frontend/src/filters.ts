import type { CardQuery, ColorMode, Order } from './api/client'

export interface FilterState {
  q: string
  text: string
  colors: string[]
  colorMode: ColorMode
  mv: number[]
  type: string
  rarity: string[]
  set: string
  format: string
  game: '' | 'paper' | 'arena'
  owned: '' | 'owned' | 'missing' | 'free'
  tag: string // Scryfall function tag (ramp, removal, ...)
  userTag: string // one of the user's own tags
  includeProxies: boolean // the owned filter counts proxies as copies
  unique: 'cards' | 'prints'
  order: Order
}

export const EMPTY_FILTERS: FilterState = {
  q: '',
  text: '',
  colors: [],
  colorMode: 'include',
  mv: [],
  type: '',
  rarity: [],
  set: '',
  format: '',
  game: '',
  owned: '',
  tag: '',
  userTag: '',
  includeProxies: false,
  unique: 'cards',
  order: 'name',
}

export function toQuery(f: FilterState): CardQuery {
  return {
    q: f.q.trim() || undefined,
    text: f.text.trim() || undefined,
    colors: f.colors.join('') || undefined,
    color_mode: f.colors.length ? f.colorMode : undefined,
    mv: f.mv.length ? f.mv : undefined,
    type: f.type ? [f.type] : undefined,
    tag: f.tag ? [f.tag] : undefined,
    user_tag: f.userTag ? [f.userTag] : undefined,
    rarity: f.rarity.length ? f.rarity : undefined,
    set: f.set ? [f.set] : undefined,
    format: f.format || undefined,
    game: f.game || undefined,
    owned: f.owned || undefined,
    include_proxies: (f.owned && f.includeProxies) || undefined,
    unique: f.unique,
    order: f.order,
  }
}
