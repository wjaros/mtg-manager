import { useEffect, useState } from 'react'
import { api, type ColorMode, type Order, type SetInfo, type UserTag } from '../api/client'
import { EMPTY_FILTERS, type FilterState } from '../filters'
import { t } from '../i18n'

const COLORS = [
  { id: 'W', label: t.filters.white },
  { id: 'U', label: t.filters.blue },
  { id: 'B', label: t.filters.black },
  { id: 'R', label: t.filters.red },
  { id: 'G', label: t.filters.green },
  { id: 'C', label: t.filters.colorless },
]
const COLOR_MODES: { id: ColorMode; label: string }[] = [
  { id: 'include', label: t.filters.modeInclude },
  { id: 'exact', label: t.filters.modeExact },
  { id: 'identity', label: t.filters.modeIdentity },
]
const MANA_VALUES = [0, 1, 2, 3, 4, 5, 6, 7]
const TYPES = ['Creature', 'Instant', 'Sorcery', 'Enchantment', 'Artifact', 'Planeswalker', 'Battle', 'Land', 'Legendary']
const RARITIES = [
  { id: 'common', label: 'C', title: 'Common' },
  { id: 'uncommon', label: 'U', title: 'Uncommon' },
  { id: 'rare', label: 'R', title: 'Rare' },
  { id: 'mythic', label: 'M', title: 'Mythic' },
]
const FORMATS = [
  { id: 'brawl', label: 'Brawl (Historic)' },
  { id: 'standardbrawl', label: 'Standard Brawl' },
  { id: 'commander', label: 'Commander' },
  { id: 'historic', label: 'Historic' },
  { id: 'standard', label: 'Standard' },
  { id: 'pioneer', label: 'Pioneer' },
  { id: 'modern', label: 'Modern' },
  { id: 'legacy', label: 'Legacy' },
  { id: 'pauper', label: 'Pauper' },
]

const SYNTAX_HELP = t.filters.syntax

function toggle<T>(list: T[], value: T): T[] {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value]
}

interface Props {
  value: FilterState
  onChange: (value: FilterState) => void
  /** Offer "Wolne": owned copies outside other decks' boxes (deckbuilder). */
  allowFree?: boolean
}

export function Filters({ value, onChange, allowFree = false }: Props) {
  const [sets, setSets] = useState<SetInfo[]>([])
  useEffect(() => {
    api.sets().then(setSets, () => setSets([]))
  }, [])
  // The user's own tags; fetched again on focus, as cards get tagged from their menus meanwhile.
  const [userTags, setUserTags] = useState<UserTag[]>([])
  const loadUserTags = () => api.userTags().then(setUserTags, () => setUserTags([]))
  useEffect(() => {
    api.userTags().then(setUserTags, () => setUserTags([]))
  }, [])

  const set = <K extends keyof FilterState>(key: K, v: FilterState[K]) => onChange({ ...value, [key]: v })
  const isEmpty = JSON.stringify(value) === JSON.stringify(EMPTY_FILTERS)

  return (
    <div className="filters">
      <div className="filter-row">
        <input
          className="input search"
          type="search"
          placeholder={t.filters.namePlaceholder}
          value={value.q}
          onChange={(e) => set('q', e.target.value)}
          autoFocus
        />
        <details className="syntax-help">
          <summary title={t.filters.syntaxTitle}>?</summary>
          <div className="syntax-help-body">
            <p className="muted small">{t.filters.syntaxIntro}</p>
            <table>
              <tbody>
                {SYNTAX_HELP.map(([example, meaning]) => (
                  <tr key={example}>
                    <td className="mono">{example}</td>
                    <td>{meaning}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
        <input
          className="input"
          type="search"
          placeholder={t.filters.textPlaceholder}
          value={value.text}
          onChange={(e) => set('text', e.target.value)}
        />
        <div className="segmented" role="group" aria-label={t.filters.ownership}>
          {(
            [
              ['', t.filters.all],
              ['owned', t.filters.owned],
              ['missing', t.filters.missing],
              ['free', t.filters.free],
            ] as const
          )
            .filter(([id]) => allowFree || id !== 'free')
            .map(([id, label]) => (
            <button
              key={id}
              className={value.owned === id ? 'on' : ''}
              onClick={() => set('owned', id)}
              title={id === 'free' ? t.filters.freeTitle : undefined}
            >
              {label}
            </button>
          ))}
        </div>
        {value.owned && (
          <label className="checkbox small" title={t.filters.includeProxiesTitle}>
            <input
              type="checkbox"
              checked={value.includeProxies}
              onChange={(e) => set('includeProxies', e.target.checked)}
            />
            {t.filters.includeProxies}
          </label>
        )}
        <div className="segmented" role="group" aria-label={t.filters.view}>
          <button className={value.unique === 'cards' ? 'on' : ''} onClick={() => set('unique', 'cards')}>
            {t.filters.cards}
          </button>
          <button className={value.unique === 'prints' ? 'on' : ''} onClick={() => set('unique', 'prints')}>
            {t.filters.allPrintings}
          </button>
        </div>
        {!isEmpty && (
          <button className="link-button" onClick={() => onChange(EMPTY_FILTERS)}>
            {t.common.clear}
          </button>
        )}
      </div>

      <div className="filter-row">
        <div className="chip-group" role="group" aria-label={t.filters.colors}>
          {COLORS.map((c) => (
            <button
              key={c.id}
              className={`mana mana-${c.id.toLowerCase()} chip-mana ${value.colors.includes(c.id) ? 'on' : ''}`}
              title={c.label}
              aria-pressed={value.colors.includes(c.id)}
              onClick={() => set('colors', toggle(value.colors, c.id))}
            >
              {c.id}
            </button>
          ))}
          <select
            className="select small"
            value={value.colorMode}
            onChange={(e) => set('colorMode', e.target.value as ColorMode)}
            aria-label={t.filters.colorMode}
          >
            {COLOR_MODES.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label}
              </option>
            ))}
          </select>
        </div>

        <div className="chip-group" role="group" aria-label="Mana value">
          {MANA_VALUES.map((mv) => (
            <button
              key={mv}
              className={`chip ${value.mv.includes(mv) ? 'on' : ''}`}
              aria-pressed={value.mv.includes(mv)}
              onClick={() => set('mv', toggle(value.mv, mv))}
            >
              {mv === 7 ? '7+' : mv}
            </button>
          ))}
        </div>

        <div className="chip-group" role="group" aria-label={t.filters.rarity}>
          {RARITIES.map((r) => (
            <button
              key={r.id}
              className={`chip rarity-${r.id} ${value.rarity.includes(r.id) ? 'on' : ''}`}
              title={r.title}
              aria-pressed={value.rarity.includes(r.id)}
              onClick={() => set('rarity', toggle(value.rarity, r.id))}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      <div className="filter-row">
        <select className="select" value={value.type} onChange={(e) => set('type', e.target.value)} aria-label={t.filters.type}>
          <option value="">{t.filters.anyType}</option>
          {TYPES.map((type) => (
            <option key={type} value={type}>
              {type}
            </option>
          ))}
        </select>
        <select className="select" value={value.tag} onChange={(e) => set('tag', e.target.value)} aria-label={t.stats.function}>
          <option value="">{t.filters.anyFunction}</option>
          {Object.entries(t.functions).map(([tag, label]) => (
            <option key={tag} value={tag}>
              {label}
            </option>
          ))}
        </select>
        {(userTags.length > 0 || value.userTag) && (
          <select
            className="select"
            value={value.userTag}
            onChange={(e) => set('userTag', e.target.value)}
            onFocus={loadUserTags}
            aria-label={t.userTags.label}
          >
            <option value="">{t.filters.anyUserTag}</option>
            {userTags.map((u) => (
              <option key={u.tag} value={u.tag}>
                {u.tag} ({u.cards})
              </option>
            ))}
          </select>
        )}
        <select className="select" value={value.set} onChange={(e) => set('set', e.target.value)} aria-label="Set">
          <option value="">{t.filters.anySet}</option>
          {sets
            .filter((s) => s.card_count > 0)
            .map((s) => (
              <option key={s.code} value={s.code}>
                {s.name} ({s.code.toUpperCase()})
              </option>
            ))}
        </select>
        <select className="select" value={value.format} onChange={(e) => set('format', e.target.value)} aria-label="Format">
          <option value="">{t.filters.anyFormat}</option>
          {FORMATS.map((f) => (
            <option key={f.id} value={f.id}>
              {f.label}
            </option>
          ))}
        </select>
        <select
          className="select"
          value={value.game}
          onChange={(e) => set('game', e.target.value as FilterState['game'])}
          aria-label={t.filters.platform}
        >
          <option value="">{t.filters.paperAndArena}</option>
          <option value="paper">{t.filters.paperOnly}</option>
          <option value="arena">{t.filters.arenaOnly}</option>
        </select>
        <select
          className="select"
          value={value.order}
          onChange={(e) => set('order', e.target.value as Order)}
          aria-label={t.filters.sorting}
        >
          <option value="name">{t.filters.sortName}</option>
          <option value="mv">{t.filters.sortMv}</option>
          <option value="released">{t.filters.sortReleased}</option>
        </select>
      </div>
    </div>
  )
}
