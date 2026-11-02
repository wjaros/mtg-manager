import { useSyncExternalStore } from 'react'
import { t } from './i18n'
import { getPref, setPref } from './prefs'

/** Skins: the app's colors made from a few choices, a small JSON anyone can copy, paste or write by hand.
The generator keeps every surface at the lightness the classic colors have (in OKLCH, only hue and chroma
follow the skin), so status, mana and chart colors stay readable and validated on any skin; the accent and
the glow are moved in lightness until text in them keeps 4.5:1. The classic skin is index.css itself. */
export interface Skin {
  name: string
  hue: number // 0–360: the surfaces' hue
  tint: number // 0–1: how colored the surfaces are (0 = grey)
  accent: string // #rrggbb: main buttons, links, what is on
  glow: string // #rrggbb: focus, the current nav item
  /** Exact token values, e.g. {"dark": {"--bg": "#101010"}}: the generator's colors stay for the rest. */
  overrides?: Partial<Record<Mode, Record<string, string>>>
}

export interface StoredSkin extends Skin {
  id: string
  group?: SkinGroup // built-ins only
  mana?: string // a color pair or trio's skin: its mana symbols, e.g. 'GWU'
}

export type SkinGroup = 'basic' | 'mono' | 'guild' | 'shard' | 'wedge'
export const SKIN_GROUPS: SkinGroup[] = ['basic', 'mono', 'guild', 'shard', 'wedge']

type Mode = 'dark' | 'light'
type Lch = { l: number; c: number; h: number }

export const CLASSIC = 'classic'
const SKIN_KEY = 'mtgdm.skin'
const CUSTOM_KEY = 'mtgdm.skins'
const BY_DECK_KEY = 'mtgdm.skinByDeck' // '1': an open deck wears its colors' skin

/** Mana colors as a skin: each color's surface hue and tint, and its color for the accent or the glow. */
export const MANA_SKIN: Record<string, { hue: number; tint: number; color: string }> = {
  W: { hue: 90, tint: 0.25, color: '#e8d9a8' },
  U: { hue: 250, tint: 0.6, color: '#4a9ad8' },
  B: { hue: 310, tint: 0.2, color: '#a596c0' },
  R: { hue: 30, tint: 0.5, color: '#e8692f' }, // orange-leaning: apart from --error
  G: { hue: 150, tint: 0.5, color: '#4fbf7f' },
}

/** A skin from up to three mana colors: the surfaces', the accent's and the glow's (missing ones repeat the first). */
export function manaSkin(colors: string[]): Pick<Skin, 'hue' | 'tint' | 'accent' | 'glow'> {
  const [surface, accent = surface, glow = surface] = colors.map((c) => MANA_SKIN[c])
  return { hue: surface.hue, tint: surface.tint, accent: accent.color, glow: glow.color }
}

// Color pairs and trios as decks name them (game terms, the same in every language). The roles' order
// (surfaces, accent, glow) puts a shard's or wedge's central color in the surfaces or the accent.
const COMBOS: [SkinGroup, string, string, string][] = [
  ['mono', 'mono-w', t.skins.monoW, 'W'],
  ['mono', 'mono-u', t.skins.monoU, 'U'],
  ['mono', 'mono-b', t.skins.monoB, 'B'],
  ['mono', 'mono-r', t.skins.monoR, 'R'],
  ['mono', 'mono-g', t.skins.monoG, 'G'],
  ['guild', 'azorius', 'Azorius', 'UWU'],
  ['guild', 'dimir', 'Dimir', 'BUB'],
  ['guild', 'rakdos', 'Rakdos', 'BRB'],
  ['guild', 'gruul', 'Gruul', 'RGR'],
  ['guild', 'selesnya', 'Selesnya', 'GWG'],
  ['guild', 'orzhov', 'Orzhov', 'BWB'],
  ['guild', 'izzet', 'Izzet', 'URU'],
  ['guild', 'golgari', 'Golgari', 'BGB'],
  ['guild', 'boros', 'Boros', 'RWR'],
  ['guild', 'simic', 'Simic', 'GUG'],
  ['shard', 'bant', 'Bant', 'UWG'],
  ['shard', 'esper', 'Esper', 'UWB'],
  ['shard', 'grixis', 'Grixis', 'BRU'],
  ['shard', 'jund', 'Jund', 'RGB'],
  ['shard', 'naya', 'Naya', 'GWR'],
  ['wedge', 'abzan', 'Abzan', 'BWG'],
  ['wedge', 'jeskai', 'Jeskai', 'UWR'],
  ['wedge', 'sultai', 'Sultai', 'BGU'],
  ['wedge', 'mardu', 'Mardu', 'RWB'],
  ['wedge', 'temur', 'Temur', 'UGR'],
]

export const BUILT_IN: StoredSkin[] = [
  { id: 'arcane', group: 'basic', name: t.skins.arcane, hue: 300, tint: 1, accent: '#eab308', glow: '#a855f7' },
  { id: 'ink', group: 'basic', name: t.skins.ink, hue: 262, tint: 0.55, accent: '#eab308', glow: '#6ea8ff' },
  { id: 'ember', group: 'basic', name: t.skins.ember, hue: 70, tint: 0.3, accent: '#eab308', glow: '#e0b04f' },
  { id: 'dusk', group: 'basic', name: t.skins.dusk, hue: 295, tint: 0.4, accent: '#eab308', glow: '#a78bfa' },
  ...COMBOS.map(([group, id, name, roles]) => ({
    id,
    group,
    name,
    mana: [...'WUBRG'].filter((c) => roles.includes(c)).join(''),
    ...manaSkin([...roles]),
  })),
]

// What a skin sets; everything else (status, mana, rarity, chart series) comes from index.css.
export const SKIN_TOKENS = [
  '--bg',
  '--bg-sunken',
  '--bg-input',
  '--bg-elevated',
  '--bg-hover',
  '--border',
  '--text',
  '--text-muted',
  '--placeholder-from',
  '--placeholder-to',
  '--chart-grid',
  '--chart-axis',
  '--accent',
  '--on-accent',
  '--glow',
]

// ---------- Color math (OKLab / OKLCH, WCAG contrast) ----------

const toLinear = (v: number) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4)
const fromLinear = (v: number) => (v <= 0.0031308 ? 12.92 * v : 1.055 * v ** (1 / 2.4) - 0.055)

function rgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16)
  return [toLinear(((n >> 16) & 255) / 255), toLinear(((n >> 8) & 255) / 255), toLinear((n & 255) / 255)]
}

function toLch(hex: string): Lch {
  const [r, g, b] = rgb(hex)
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
  const L = 0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s
  const A = 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s
  const B = 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s
  return { l: L, c: Math.hypot(A, B), h: ((Math.atan2(B, A) * 180) / Math.PI + 360) % 360 }
}

function linearOf({ l, c, h }: Lch): [number, number, number] {
  const A = c * Math.cos((h * Math.PI) / 180)
  const B = c * Math.sin((h * Math.PI) / 180)
  const L = (l + 0.3963377774 * A + 0.2158037573 * B) ** 3
  const M = (l - 0.1055613458 * A - 0.0638541728 * B) ** 3
  const S = (l - 0.0894841775 * A - 1.291485548 * B) ** 3
  return [
    4.0767416621 * L - 3.3077115913 * M + 0.2309699292 * S,
    -1.2684380046 * L + 2.6097574011 * M - 0.3413193965 * S,
    -0.0041960863 * L - 0.7034186147 * M + 1.707614701 * S,
  ]
}

/** The color as #rrggbb; out of sRGB, chroma gives way (hue and lightness stay). */
function toHex(lch: Lch): string {
  let { c } = lch
  const fits = (chroma: number) => linearOf({ ...lch, c: chroma }).every((v) => v >= -1e-4 && v <= 1 + 1e-4)
  if (!fits(c)) {
    let low = 0
    for (let i = 0; i < 20; i++) {
      const mid = (low + c) / 2
      if (fits(mid)) low = mid
      else c = mid
    }
    c = low
  }
  const channels = linearOf({ ...lch, c }).map((v) => Math.round(fromLinear(Math.min(1, Math.max(0, v))) * 255))
  return `#${channels.map((v) => v.toString(16).padStart(2, '0')).join('')}`
}

function luminance(hex: string): number {
  const [r, g, b] = rgb(hex)
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

/** The color, lighter (dark mode) or darker, until text in it reads on `against`. */
function readable(hex: string, against: string, mode: Mode): string {
  const lch = toLch(hex)
  let out = toHex(lch)
  for (let l = lch.l; contrast(out, against) < 4.5 && l > 0 && l < 1; ) {
    l += mode === 'dark' ? 0.01 : -0.01
    out = toHex({ ...lch, l })
  }
  return out
}

// ---------- Skin → tokens ----------

export function skinTokens(skin: Skin, mode: Mode): Record<string, string> {
  const { hue: h, tint } = skin
  const at = (l: number, c: number) => toHex({ l, c, h })
  const tokens: Record<string, string> =
    mode === 'dark'
      ? {
          '--bg': at(0.155, tint * 0.06),
          '--bg-sunken': at(0.13, tint * 0.05),
          '--bg-input': at(0.17, tint * 0.06),
          '--bg-elevated': at(0.195, tint * 0.065),
          '--bg-hover': at(0.245, tint * 0.075),
          '--border': at(0.3, 0.01 + tint * 0.08),
          '--text': at(0.95, tint * 0.012),
          '--text-muted': at(0.72, 0.02 + tint * 0.05),
        }
      : {
          '--bg': at(0.975, tint * 0.012),
          '--bg-sunken': at(0.925, tint * 0.02),
          '--bg-input': '#ffffff',
          '--bg-elevated': '#ffffff',
          '--bg-hover': at(0.94, tint * 0.025),
          '--border': at(0.87, 0.005 + tint * 0.035),
          '--text': at(0.22, tint * 0.02),
          '--text-muted': at(0.48, 0.02 + tint * 0.04),
        }
  tokens['--text-muted'] = readable(tokens['--text-muted'], tokens['--bg-hover'], mode)
  tokens['--placeholder-from'] = tokens['--bg-hover']
  tokens['--placeholder-to'] = mode === 'dark' ? tokens['--bg-elevated'] : tokens['--bg']
  tokens['--chart-grid'] = tokens['--bg-hover']
  tokens['--chart-axis'] = tokens['--border']
  // Accent text sits on panels and on the page: readable on the darker / lighter of the two.
  const behind = mode === 'dark' ? tokens['--bg-elevated'] : tokens['--bg']
  tokens['--accent'] = readable(skin.accent, behind, mode)
  tokens['--on-accent'] = contrast(tokens['--accent'], '#1a1408') >= contrast(tokens['--accent'], '#ffffff') ? '#1a1408' : '#ffffff'
  tokens['--glow'] = readable(skin.glow, behind, mode)
  return { ...tokens, ...skin.overrides?.[mode] }
}

// ---------- JSON ----------

export function skinJson(skin: Skin): string {
  const { name, hue, tint, accent, glow, overrides } = skin
  return JSON.stringify(overrides ? { name, hue, tint, accent, glow, overrides } : { name, hue, tint, accent, glow }, null, 2)
}

/** A skin from JSON (pasted or typed); throws an Error with the reason, in the UI's language. */
export function parseSkin(text: string): Skin {
  let data: unknown
  try {
    data = JSON.parse(text)
  } catch {
    throw new Error(t.skins.notJson)
  }
  const d = (data ?? {}) as Record<string, unknown>
  const hex = /^#[0-9a-f]{6}$/i
  if (typeof d.name !== 'string' || !d.name.trim()) throw new Error(t.skins.badField('name'))
  if (typeof d.hue !== 'number' || d.hue < 0 || d.hue > 360) throw new Error(t.skins.badField('hue'))
  if (typeof d.tint !== 'number' || d.tint < 0 || d.tint > 1) throw new Error(t.skins.badField('tint'))
  if (typeof d.accent !== 'string' || !hex.test(d.accent)) throw new Error(t.skins.badField('accent'))
  if (typeof d.glow !== 'string' || !hex.test(d.glow)) throw new Error(t.skins.badField('glow'))
  const skin: Skin = { name: d.name.trim().slice(0, 40), hue: d.hue, tint: d.tint, accent: d.accent, glow: d.glow }
  if (d.overrides !== undefined) {
    const overrides = d.overrides as Record<string, Record<string, unknown>>
    for (const [mode, values] of Object.entries(overrides ?? {})) {
      if (mode !== 'dark' && mode !== 'light') throw new Error(t.skins.badField(`overrides.${mode}`))
      for (const [token, value] of Object.entries(values ?? {})) {
        if (!SKIN_TOKENS.includes(token) || typeof value !== 'string' || !CSS.supports('color', value)) {
          throw new Error(t.skins.badField(`overrides.${mode}.${token}`))
        }
      }
    }
    skin.overrides = overrides as Skin['overrides']
  }
  return skin
}

// ---------- The chosen skin ----------

const listeners = new Set<() => void>()
let preview: Skin | null = null
let deckColors: string[] | null = null // the open deck's color identity
let customCache: { raw: string | null; skins: StoredSkin[] } = { raw: null, skins: [] }

export function customSkins(): StoredSkin[] {
  const raw = getPref(CUSTOM_KEY)
  if (raw !== customCache.raw) {
    let skins: StoredSkin[] = []
    try {
      skins = (JSON.parse(raw ?? '[]') as StoredSkin[]).filter((s) => typeof s?.id === 'string')
    } catch {
      // unreadable: no custom skins
    }
    customCache = { raw, skins }
  }
  return customCache.skins
}

export function skinId(): string {
  return getPref(SKIN_KEY) ?? CLASSIC
}

export function findSkin(id: string): StoredSkin | null {
  return [...BUILT_IN, ...customSkins()].find((s) => s.id === id) ?? null
}

/** The built-in skin of exactly these colors (mono, guild, shard, wedge); none for colorless or 4–5 colors. */
export function skinForColors(colors: string[]): StoredSkin | null {
  const mana = [...'WUBRG'].filter((c) => colors.includes(c)).join('')
  return BUILT_IN.find((s) => s.mana === mana) ?? null
}

export function skinByDeck(): boolean {
  return getPref(BY_DECK_KEY) === '1'
}

export function setSkinByDeck(on: boolean): void {
  void setPref(BY_DECK_KEY, on ? '1' : null)
  changed()
}

/** The deck on screen (null when it closes): with the option on, its colors' skin replaces the chosen one. */
export function showDeckColors(colors: string[] | null): void {
  deckColors = colors
  applySkin()
}

/** Sets the skin's tokens on <html> for the current light / dark (none: index.css's classic colors). */
export function applySkin(): void {
  const root = document.documentElement
  const deckSkin = deckColors && skinByDeck() ? skinForColors(deckColors) : null
  const skin = preview ?? deckSkin ?? findSkin(skinId())
  const tokens = skin ? skinTokens(skin, root.dataset.theme === 'light' ? 'light' : 'dark') : {}
  for (const token of SKIN_TOKENS) {
    if (tokens[token]) root.style.setProperty(token, tokens[token])
    else root.style.removeProperty(token)
  }
  setFavicon()
}

/** The tab's icon: the favicon's d20 in the skin's colors (classic: public/favicon.svg's colors, from index.css). */
function setFavicon(): void {
  const link = document.querySelector<HTMLLinkElement>('link[rel="icon"]')
  if (!link) return
  const style = getComputedStyle(document.documentElement)
  const v = (token: string) => style.getPropertyValue(token).trim()
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><defs>
<linearGradient id="b" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${v('--bg-hover')}"/><stop offset="1" stop-color="${v('--bg')}"/></linearGradient>
<linearGradient id="c" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${v('--glow')}"/><stop offset="1" stop-color="${v('--bg-hover')}"/></linearGradient></defs>
<rect width="64" height="64" rx="14" fill="url(#b)"/>
<polygon points="32,6 56,20 56,44 32,58 8,44 8,20" fill="${v('--bg-elevated')}" stroke="${v('--accent')}" stroke-width="3.5" stroke-linejoin="round"/>
<polygon points="32,15 48,43 16,43" fill="url(#c)" stroke="${v('--glow')}" stroke-width="2.5" stroke-linejoin="round"/>
<path d="M32 6V15M8 20L16 43M56 20L48 43M32 58L16 43M32 58L48 43" stroke="${v('--text')}" stroke-width="2" stroke-linecap="round"/></svg>`
  link.href = `data:image/svg+xml,${encodeURIComponent(svg)}`
}

// Light / dark switched (Settings or the system, see theme.ts): the skin's other set.
new MutationObserver(applySkin).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })

function changed(): void {
  applySkin()
  for (const listener of listeners) listener()
}

export function chooseSkin(id: string): void {
  void setPref(SKIN_KEY, id === CLASSIC ? null : id)
  changed()
}

/** Shown while the editor is open, without being stored. */
export function previewSkin(skin: Skin | null): void {
  preview = skin
  applySkin()
}

/** Stores a custom skin (new without an id) and chooses it. */
export function saveSkin(skin: Skin, id?: string): string {
  const key = id ?? `custom-${Date.now()}`
  const others = customSkins().filter((s) => s.id !== key)
  void setPref(CUSTOM_KEY, JSON.stringify([...others, { ...skin, id: key }]))
  chooseSkin(key)
  return key
}

export function deleteSkin(id: string): void {
  void setPref(CUSTOM_KEY, JSON.stringify(customSkins().filter((s) => s.id !== id)))
  if (skinId() === id) chooseSkin(CLASSIC)
  else changed()
}

export function useSkins(): { id: string; custom: StoredSkin[]; byDeck: boolean } {
  const id = useSyncExternalStore(subscribe, skinId)
  const custom = useSyncExternalStore(subscribe, customSkins)
  const byDeck = useSyncExternalStore(subscribe, skinByDeck)
  return { id, custom, byDeck }
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}
