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
